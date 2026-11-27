"""Tests für den Windows-Transportclient ohne echtes MT5 und ohne Netz."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import threading
from datetime import datetime, time, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JETZT = datetime(2025, 1, 3, 0, 15, tzinfo=timezone.utc)
TOKEN = "transport-client-test-token"  # noqa: S105


def _modul():
    name = "transport_client_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "transport_client.py")
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _konfiguration(tmp_path: Path, *, url: str = "https://orakel.example/api/daten/import",
                    zeitrahmen: str = '"M15"', symbole: str = '"EURUSD"',
                    zeitzone: str | None = '"UTC"') -> Path:
    pfad = tmp_path / "transport.toml"
    zone_zeile = "" if zeitzone is None else f"server_zeitzone = {zeitzone}\n"
    pfad.write_text(
        f'''
[endpoint]
url = "{url}"
key_id = "windows-1"
token_env = "ORAKEL_TRANSPORT_TOKEN"
timeout_sekunden = 5
max_bytes = 5242880

[export]
symbole = [{symbole}]
zeitrahmen = [{zeitrahmen}]
{zone_zeile}
min_kerzen_pro_tag = {{ M15 = 90, H1 = 20 }}
max_alter_stunden = {{ M15 = 4, H1 = 24 }}
lookback_tage = 10

[state]
pfad = "{(tmp_path / 'state').as_posix()}"
sent_aufbewahrung_tage = 30
quarantaene_aufbewahrung_tage = 90
logs_aufbewahrung_tage = 30

[retry]
http_versuche = 2
basis_sekunden = 0
retry_after_max_sekunden = 120
jitter_sekunden = 0
''',
        encoding="utf-8",
    )
    return pfad


def _bars(tag: str, anzahl: int = 96, *, minuten: int = 15) -> list[dict]:
    start = datetime.fromisoformat(tag + "T00:00:00").replace(tzinfo=timezone.utc)
    return [
        {
            "time": int((start + timedelta(minutes=minuten * i)).timestamp()),
            "open": 1.10 + i / 10000,
            "high": 1.11 + i / 10000,
            "low": 1.09 + i / 10000,
            "close": 1.105 + i / 10000,
            "tick_volume": 10,
            "real_volume": 0,
            "spread": 2,
        }
        for i in range(anzahl)
    ]


class FakeMT5:
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    def __init__(self, tage: dict[str, list[dict]] | None = None, *,
                 tick: str | None = "2025-01-02T23:45:00", symbol_ok: bool = True):
        self.tage = tage or {}
        self.tick = tick
        self.symbol_ok = symbol_ok
        self.abrufe: list[tuple[int, int]] = []
        self.positionen: list[tuple[str, int]] = []
        self.beendet = False

    def initialize(self, **kwargs) -> bool:
        return True

    def shutdown(self) -> None:
        self.beendet = True

    def symbol_select(self, symbol: str, an: bool) -> bool:
        return self.symbol_ok

    def symbol_info_tick(self, symbol: str):
        if self.tick is None:
            return None
        return {"time": int(datetime.fromisoformat(self.tick).replace(tzinfo=timezone.utc).timestamp())}

    def copy_rates_from_pos(self, symbol: str, rahmen: int, start: int, anzahl: int):
        self.positionen.append((symbol, rahmen))
        for tag in sorted(self.tage):
            return self.tage[tag][-1:]
        return []

    def copy_rates_range(self, symbol: str, rahmen: int, anfang: int, ende: int):
        self.abrufe.append((anfang, ende))
        tag = datetime.fromtimestamp(anfang, tz=timezone.utc).date().isoformat()
        return self.tage.get(tag, [])


class FakeSender:
    def __init__(self, antworten: list[object] | None = None):
        self.antworten = list(antworten or [])
        self.aufrufe: list[tuple[str, bytes, dict[str, str], float]] = []

    def send(self, url: str, body: bytes, headers: dict[str, str], timeout: float):
        self.aufrufe.append((url, body, headers, timeout))
        if self.antworten:
            antwort = self.antworten.pop(0)
        else:
            antwort = _erfolg()
        if callable(antwort):
            return antwort(body, headers)
        return antwort


def _antwort(status: int, code: str, *, extra: dict | None = None,
             headers: dict[str, str] | None = None):
    daten = {"ok": status == 200, "code": code, **(extra or {})}
    from transport_client_test import HttpAntwort  # type: ignore[import-not-found]

    return HttpAntwort(status, headers or {}, json.dumps(daten).encode("utf-8"))


def _erfolg(code: str = "importiert", *, warnungen: list[str] | None = None):
    def antwort(body: bytes, headers: dict[str, str]):
        from transport_client_test import HttpAntwort  # type: ignore[import-not-found]

        return HttpAntwort(200, {}, json.dumps({
            "ok": True,
            "code": code,
            "sha256": hashlib.sha256(body).hexdigest(),
            "warnungen": warnungen or [],
        }).encode("utf-8"))
    return antwort


def _lauf(modul, cfg, fake_mt5, sender, *, token: str | None = TOKEN):
    schlaf: list[float] = []
    code = modul.run(cfg, mt5=fake_mt5, sender=sender, jetzt=JETZT,
                     schlaf=schlaf.append, token=token)
    return code, schlaf


def _state(cfg) -> dict:
    return json.loads((cfg.state.pfad / "state.json").read_text(encoding="utf-8"))


def _cfg(tmp_path: Path, **kwargs):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path, **kwargs))
    assert modul._initialisiere_state(cfg) == 0
    return cfg


def test_tagesblock_wird_mit_hash_und_pflichtheadern_gesendet(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender()

    code, _ = _lauf(modul, cfg, fake, sender)

    assert code == 0
    assert len(sender.aufrufe) == 1
    url, body, headers, timeout = sender.aufrufe[0]
    assert url == cfg.endpoint.url
    assert timeout == 5
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["X-Orakel-Key-Id"] == "windows-1"
    assert headers["X-Orakel-Content-SHA256"] == hashlib.sha256(body).hexdigest()
    assert headers["X-Orakel-Dateiname"] == "EURUSD_M15_20250102.csv"
    assert headers["Content-Type"] == "text/csv"
    assert headers["Content-Length"] == str(len(body))
    zeilen = body.decode("utf-8").splitlines()
    assert zeilen[0] == (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>"
        "\t<TICKVOL>\t<VOL>\t<SPREAD>"
    )
    assert len(zeilen) == 97
    assert zeilen[1].startswith("2025.01.02\t00:00:00")
    assert zeilen[-1].startswith("2025.01.02\t23:45:00")
    hoch = _state(cfg)
    eintrag = next(iter(hoch["uploads"].values()))
    assert eintrag["status"] == "erfolgreich"
    assert eintrag["sha256"] == hashlib.sha256(body).hexdigest()
    assert (cfg.state.pfad / "sent" / "EURUSD_M15_20250102.csv").is_file()
    assert TOKEN not in (cfg.state.pfad / "state.json").read_text(encoding="utf-8")


def test_zweiter_lauf_laedt_erfolgreichen_tag_nicht_erneut_hoch(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender()

    assert _lauf(modul, cfg, fake, sender)[0] == 0
    assert _lauf(modul, cfg, fake, sender)[0] == 0

    assert len(sender.aufrufe) == 1


def test_unvollstaendiger_tag_wird_nicht_gesendet(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02", 50)})
    sender = FakeSender()

    code, _ = _lauf(modul, cfg, fake, sender)

    assert code == 2
    assert sender.aufrufe == []
    assert not (cfg.state.pfad / "staging" / "EURUSD_M15_20250102.csv").exists()


def test_bootstrap_wird_nicht_wiederholt(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender([_antwort(409, "bootstrap_erforderlich")])

    code, schlaf = _lauf(modul, cfg, fake, sender)

    assert code == 3
    assert len(sender.aufrufe) == 1
    assert schlaf == []
    eintrag = next(iter(_state(cfg)["uploads"].values()))
    assert eintrag["status"] == "blockiert"
    assert eintrag["grund"] == "bootstrap"


def test_import_belegt_wird_genau_einmal_mit_retry_after_wiederholt(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender([
        _antwort(409, "import_belegt", headers={"Retry-After": "5"}),
        _erfolg(),
    ])

    code, schlaf = _lauf(modul, cfg, fake, sender)

    assert code == 0
    assert len(sender.aufrufe) == 2
    assert schlaf == [5.0]
    assert next(iter(_state(cfg)["uploads"].values()))["versuche"] == 2


def test_serverfehler_nutzt_maximal_zwei_versuche_und_bleibt_wartend(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender([
        _antwort(500, "interner_fehler"),
        _antwort(500, "interner_fehler"),
    ])

    code, _ = _lauf(modul, cfg, fake, sender)

    assert code == 2
    assert len(sender.aufrufe) == 2
    assert [a[2]["X-Orakel-Content-SHA256"] for a in sender.aufrufe] == [
        sender.aufrufe[0][2]["X-Orakel-Content-SHA256"]] * 2
    assert len({a[2]["X-Orakel-Request-Id"] for a in sender.aufrufe}) == 1
    assert next(iter(_state(cfg)["uploads"].values()))["status"] == "wartend"


def test_authfehler_stoppt_sofort(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender([_antwort(401, "token_ungueltig")])

    code, _ = _lauf(modul, cfg, fake, sender)

    assert code == 3
    assert len(sender.aufrufe) == 1
    assert next(iter(_state(cfg)["uploads"].values()))["grund"] == "auth"


def test_bereits_vorhanden_ist_erfolg(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender([_erfolg("bereits_vorhanden")])

    code, _ = _lauf(modul, cfg, fake, sender)

    assert code == 0
    assert next(iter(_state(cfg)["uploads"].values()))["status"] == "erfolgreich"


def test_teilwiederherstellung_ist_erfolg_mit_alarm(tmp_path):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender([_erfolg(warnungen=["Teilwiederherstellung: 96 von 1200 Kerzen"])])

    code, _ = _lauf(modul, cfg, fake, sender)

    assert code == 0
    eintrag = next(iter(_state(cfg)["uploads"].values()))
    assert eintrag["status"] == "erfolgreich_degraded"
    assert eintrag["warnungen"]


def test_konfiguration_erzwingt_https_und_m15(tmp_path):
    modul = _modul()
    with pytest.raises(modul.KonfigurationsFehler):
        modul.load_config(_konfiguration(tmp_path, url="http://orakel.example/api/daten/import"))
    with pytest.raises(modul.KonfigurationsFehler):
        modul.load_config(_konfiguration(tmp_path, zeitrahmen='"H1"'))
    with pytest.raises(modul.KonfigurationsFehler):
        modul.load_config(_konfiguration(tmp_path, zeitzone=None))
    assert modul.load_config(_konfiguration(
        tmp_path, url="http://127.0.0.1:8000/api/daten/import"))


def test_fehlender_token_verhindert_jeden_http_aufruf(tmp_path, monkeypatch):
    modul = _modul()
    cfg = _cfg(tmp_path)
    fake = FakeMT5({"2025-01-02": _bars("2025-01-02")})
    sender = FakeSender()
    monkeypatch.delenv("ORAKEL_TRANSPORT_TOKEN", raising=False)

    code = modul.run(cfg, mt5=fake, sender=sender, jetzt=JETZT)

    assert code == 3
    assert sender.aufrufe == []


def test_check_config_ohne_token(tmp_path):
    modul = _modul()
    pfad = _konfiguration(tmp_path)
    assert modul.main(["--config", str(pfad), "--check-config"]) == 0


def test_httptransport_sendet_header_und_folgt_keiner_umleitung():
    modul = _modul()
    gesehen: list[tuple[str, bytes, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            laenge = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(laenge)
            if self.path == "/umleitung":
                self.send_response(302)
                self.send_header("Location", "/ziel")
                self.end_headers()
                return
            gesehen.append((self.path, body, dict(self.headers)))
            antwort = json.dumps({"ok": True, "code": "importiert"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(antwort)))
            self.end_headers()
            self.wfile.write(antwort)

        def log_message(self, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sender = modul.HttpSender()
        headers = {
            "Authorization": "Bearer test-token",
            "X-Orakel-Key-Id": "windows-1",
            "X-Orakel-Content-SHA256": hashlib.sha256(b"abc").hexdigest(),
            "X-Orakel-Dateiname": "EURUSD_M15_20250102.csv",
            "Content-Type": "text/csv",
        }
        antwort = sender.send(
            f"http://127.0.0.1:{server.server_port}/api/daten/import",
            b"abc", headers, 2.0,
        )
        assert antwort.status == 200
        assert gesehen[0][1] == b"abc"
        assert gesehen[0][2]["Authorization"] == "Bearer test-token"
        assert gesehen[0][2]["X-Orakel-Dateiname"] == "EURUSD_M15_20250102.csv"

        umleitung = sender.send(
            f"http://127.0.0.1:{server.server_port}/umleitung", b"abc", headers, 2.0,
        )
        assert umleitung.status == 302
        assert len(gesehen) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)