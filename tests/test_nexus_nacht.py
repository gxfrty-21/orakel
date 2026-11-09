from __future__ import annotations

import http.server
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orakel.nexus.abruf import Abrufer, CacheEintrag, HttpCache
from orakel.nexus.nacht import _backup, dns_und_tls, ist_faellig, nachtlauf

FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Nachtmeldung</title><link>https://example.com/n/1</link></item>
</channel></rss>"""

JETZT = datetime(2026, 11, 9, 2, 30, tzinfo=timezone.utc)


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):  # noqa: N802
        if self.path == "/feed.xml":
            body = FEED
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def server():
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
    assert bericht["fehler"] == 0
    assert bericht["quellen"][0]["id"] == "faellig"

    backup = bericht["backup"]
    assert backup["integrity"] == "ok"
    assert Path(backup["pfad"]).exists()


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
    assert "orakel-2020-01-01.db" in ergebnis["entfernt"]
    assert not alt.exists()


def test_dns_pruefung_meldet_fehler_statt_ausnahme():
    ergebnis = dns_und_tls("example.invalid", timeout=2)
    assert ergebnis["ok"] is False
    assert "DNS" in (ergebnis.get("fehler") or "")
