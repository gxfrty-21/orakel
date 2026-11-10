from __future__ import annotations

import http.server
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orakel.db import Facts
from orakel.nexus.abruf import Abrufer, CacheEintrag, HttpCache
from orakel.nexus.nacht import _backup, dns_und_tls, ist_faellig, nachtlauf

FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Nachtmeldung</title><link>https://example.com/n/1</link></item>
</channel></rss>"""

FEED_DUBLETTEN = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item>
  <title>EZB laesst Leitzins unveraendert</title>
  <link>https://example.com/n/a</link>
  <description>Die EZB laesst den Leitzins unveraendert.</description>
</item>
<item>
  <title>EZB laesst Leitzins unveraendert</title>
  <link>https://example.com/n/b</link>
  <description>Die EZB laesst den Leitzins unveraendert.</description>
</item>
</channel></rss>"""

JETZT = datetime(2026, 11, 9, 2, 30, tzinfo=timezone.utc)


class _Handler(http.server.BaseHTTPRequestHandler):
    ereignisse: list[tuple[str, str, str]] = []

    def log_message(self, *args):
        return

    def do_GET(self):  # noqa: N802
        type(self).ereignisse.append(("GET", self.path, ""))
        if self.path in ("/feed.xml", "/dubletten.xml"):
            body = FEED if self.path == "/feed.xml" else FEED_DUBLETTEN
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/ping":
            self.send_response(200)
            self.end_headers()
        elif self.path == "/fehler":
            self.send_response(500)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):  # noqa: N802
        laenge = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(laenge) if laenge else b""
        type(self).ereignisse.append(
            ("POST", self.path, body.decode("utf-8", "replace")))
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def server():
    _Handler.ereignisse = []
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_ohne_cache_eintrag_ist_immer_faellig():
    assert ist_faellig(None, 30, JETZT)


def test_alt_ist_faellig_frisch_nicht():
    alt = CacheEintrag(url="u", etag=None, last_modified=None,
                       abgerufen_am=(JETZT - timedelta(minutes=60)).isoformat(),
                       status=200, groesse=10)
    assert ist_faellig(alt, 30, JETZT)
    assert not ist_faellig(alt, 120, JETZT)


def test_kaputtes_datum_gilt_als_faellig():
    kaputt = CacheEintrag(url="u", etag=None, last_modified=None,
                          abgerufen_am="kein-datum", status=200, groesse=1)
    assert ist_faellig(kaputt, 30, JETZT)


def test_nachtlauf_ruft_nur_faellige_quellen_ab(server, tmp_path):
    register = tmp_path / "register.toml"
    register.write_text(
        f'''[[quelle]]
id = "faellig"
name = "Faellig"
typ = "rss"
url = "{server}/feed.xml"
land = "DE"
sprache = "de"
thema = "test"
intervall_minuten = 30

[[quelle]]
id = "frisch"
name = "Frisch"
typ = "rss"
url = "{server}/frisch.xml"
land = "DE"
sprache = "de"
thema = "test"
intervall_minuten = 30
''',
        encoding="utf-8",
    )
    db = tmp_path / "orakel.db"
    cache = HttpCache(db)
    cache.speichere(f"{server}/frisch.xml", 200, None, None, 10)

    abrufer = Abrufer(cache, "Test/1.0", min_abstand_sekunden=0)
    bericht = nachtlauf(db, register_pfad=register, backup_ordner=tmp_path / "backups",
                        jetzt=JETZT, abrufer=abrufer)

    assert bericht["faellig"] == 1
    assert bericht["abgerufen"] == 1
    assert bericht["meldungen"] == 1
    assert bericht["gespeichert"] == 1
    assert bericht["fehler"] == 0
    assert bericht["quellen"][0]["id"] == "faellig"
    assert Facts(db).artikel_statistik()["gesamt"] == 1

    backup = bericht["backup"]
    assert backup["integrity"] == "ok"
    assert Path(backup["pfad"]).exists()


def test_nachtlauf_speichert_original_und_erkennt_kopie(server, tmp_path):
    bericht = _nacht(tmp_path, _register(tmp_path, f"{server}/dubletten.xml"))

    assert bericht["meldungen"] == 2
    assert bericht["gespeichert"] == 1
    assert bericht["dubletten"] == 1
    assert bericht["speicher_fehler"] == 0

    db = Facts(tmp_path / "orakel.db")
    assert db.artikel_statistik()["gesamt"] == 1
    statistik = db.nexus_statistik()
    assert statistik["gesamt"] == 2
    assert statistik["originale"] == 1
    assert statistik["dubletten"] == 1
    assert statistik["dublettenquote"] == 0.5


def test_nachtlauf_bewertet_kernaussage_und_kopie(server, tmp_path):
    bericht = _nacht(tmp_path, _register(tmp_path, f"{server}/dubletten.xml"))

    assert bericht["ok"] is True
    assert bericht["bewertung"]["kernaussagen"] == 1
    assert bericht["bewertung"]["belege"] == 2
    assert bericht["bewertung"]["widersprueche"] == 0

    claim = Facts(tmp_path / "orakel.db").nexus_claims(5)[0]
    assert claim["quellen"] == 1
    assert claim["belege"] == 2
    assert claim["status"] == "unbestätigt"


def test_zweiter_lauf_erzeugt_keine_neue_zeile(server, tmp_path):
    register = _register(tmp_path, f"{server}/feed.xml")
    erster = _nacht(tmp_path, register)
    assert erster["gespeichert"] == 1

    # Cache-Zeitpunkt liegt real in der Gegenwart; ein Lauf eine Stunde später
    # ist wieder fällig und sieht dieselbe Meldung erneut.
    spaeter = datetime.now(timezone.utc) + timedelta(hours=1)
    zweiter = _nacht(tmp_path, register, jetzt=spaeter)
    assert zweiter["meldungen"] == 1
    assert zweiter["wiederholungen"] == 1
    assert zweiter["gespeichert"] == 0
    assert Facts(tmp_path / "orakel.db").artikel_statistik()["gesamt"] == 1


def test_backup_entfernt_alte_dateien(tmp_path):
    db = tmp_path / "orakel.db"
    sqlite3.connect(db).execute("CREATE TABLE probe (x INTEGER)").connection.commit()

    ordner = tmp_path / "backups"
    ordner.mkdir()
    alt = ordner / "orakel-2020-01-01.db"
    alt.write_bytes(b"alt")
    altzeit = time.time() - 60 * 60 * 24 * 30
    import os
    os.utime(alt, (altzeit, altzeit))

    ergebnis = _backup(db, ordner, JETZT, behalten_tage=1)
    assert ergebnis["integrity"] == "ok"
    assert ergebnis["erstellt"].startswith("2026-11-09")
    assert "orakel-2020-01-01.db" in ergebnis["entfernt"]
    assert not alt.exists()


def test_dns_pruefung_meldet_fehler_statt_ausnahme():
    ergebnis = dns_und_tls("example.invalid", timeout=2)
    assert ergebnis["ok"] is False
    assert "DNS" in (ergebnis.get("fehler") or "")


def _register(tmp_path: Path, url: str) -> Path:
    pfad = tmp_path / "register.toml"
    pfad.write_text(
        f'''[[quelle]]
id = "q"
name = "Q"
typ = "rss"
url = "{url}"
land = "DE"
sprache = "de"
thema = "test"
intervall_minuten = 30
''',
        encoding="utf-8",
    )
    return pfad


def _nacht(tmp_path: Path, register: Path, **abweichung):
    db = tmp_path / "orakel.db"
    abrufer = Abrufer(HttpCache(db), "Test/1.0", min_abstand_sekunden=0)
    basis = dict(register_pfad=register, backup_ordner=tmp_path / "backups",
                 jetzt=JETZT, abrufer=abrufer)
    basis.update(abweichung)
    return nachtlauf(db, **basis)


def test_erfolg_sendet_ping_ohne_warnung(server, tmp_path):
    bericht = _nacht(tmp_path, _register(tmp_path, f"{server}/feed.xml"),
                     warnung_url=f"{server}/warnung", ping_url=f"{server}/ping")
    assert bericht["ok"] is True
    assert ("GET", "/ping", "") in _Handler.ereignisse
    assert not any(pfad == "/warnung" for _, pfad, _ in _Handler.ereignisse)


def test_fehler_sendet_warnung_und_fail_ping(server, tmp_path):
    bericht = _nacht(tmp_path, _register(tmp_path, f"{server}/fehler"),
                     warnung_url=f"{server}/warnung", ping_url=f"{server}/ping")
    assert bericht["ok"] is False
    assert any(pfad == "/warnung" for _, pfad, _ in _Handler.ereignisse)
    assert ("POST", "/ping/fail", "") in _Handler.ereignisse
    # Das Dashboard liest genau diesen Zustand — er muss ok und Warnung enthalten.
    zustand = Facts(tmp_path / "orakel.db").zustand("nexus_nacht")
    assert zustand["ok"] is False
    assert zustand["warnung"]["gesendet"] is True
    assert zustand["backup"]["erstellt"]


def test_warnung_als_text_fuer_ntfy(server, tmp_path):
    _nacht(tmp_path, _register(tmp_path, f"{server}/fehler"),
           warnung_url=f"{server}/warnung", warnung_art="text")
    body = next(b for _, pfad, b in _Handler.ereignisse if pfad == "/warnung")
    assert "Nachtlauf fehlgeschlagen" in body
    assert not body.startswith("{")


def test_unerreichbare_warnung_bricht_den_lauf_nicht_ab(server, tmp_path):
    bericht = _nacht(tmp_path, _register(tmp_path, f"{server}/fehler"),
                     warnung_url="http://127.0.0.1:1/warnung")
    assert bericht["warnung"]["gesendet"] is False
    assert bericht["backup"]["integrity"] == "ok"


# ---------- systemd/Healthchecks-Einrichtung ----------

WURZEL = Path(__file__).resolve().parents[1]
FAIL_SKRIPT = WURZEL / "deploy" / "orakel-nacht-fail.sh"


def test_nacht_unit_hat_timeout_und_onfailure():
    text = (WURZEL / "deploy" / "orakel-nacht.service").read_text(encoding="utf-8")
    assert "Type=oneshot" in text
    assert "TimeoutStartSec=2700" in text
    assert "OnFailure=orakel-nacht-fail.service" in text
    # Domain und Ping-URL kommen aus der Container-Umgebung, nicht aus ExecStart.
    assert "EnvironmentFile" not in text
    assert "--domain" not in text


def test_compose_gibt_domain_an_den_nachtlauf():
    text = (WURZEL / "docker-compose.yml").read_text(encoding="utf-8")
    assert "ORAKEL_DOMAIN: ${ORAKEL_DOMAIN:-}" in text


def test_nacht_timer_laeuft_taeglich_und_persistent():
    text = (WURZEL / "deploy" / "orakel-nacht.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 02:30:00 Europe/Zurich" in text
    assert "Persistent=true" in text
    assert "Unit=orakel-nacht.service" in text


def test_fail_unit_nutzt_skript_und_env_datei():
    text = (WURZEL / "deploy" / "orakel-nacht-fail.service").read_text(encoding="utf-8")
    assert "EnvironmentFile=-/srv/orakel/.env" in text
    assert "ExecStart=/srv/orakel/deploy/orakel-nacht-fail.sh" in text


def test_fail_skript_sendet_fail_ping(server):
    if not shutil.which("curl"):
        pytest.skip("curl fehlt")
    env = {**os.environ, "ORAKEL_PING_URL": f"{server}/ping"}
    subprocess.run(["sh", str(FAIL_SKRIPT)], env=env, check=True, timeout=30)
    assert ("POST", "/ping/fail", "") in _Handler.ereignisse


def test_fail_skript_ohne_url_ist_still(server):
    env = {k: v for k, v in os.environ.items() if k != "ORAKEL_PING_URL"}
    ergebnis = subprocess.run(["sh", str(FAIL_SKRIPT)], env=env,
                              capture_output=True, text=True, timeout=10)
    assert ergebnis.returncode == 0
    assert not _Handler.ereignisse


def test_installer_ist_ausfuehrbar():
    skript = WURZEL / "scripts" / "oracle-nacht-install.sh"
    assert skript.is_file()
    assert os.access(skript, os.X_OK)


def test_ohne_warnungs_url_wird_das_ehrlich_gemeldet(server, tmp_path):
    bericht = _nacht(tmp_path, _register(tmp_path, f"{server}/fehler"))
    assert bericht["warnung"]["gesendet"] is False
    assert "keine Warnungs-URL" in bericht["warnung"]["grund"]
