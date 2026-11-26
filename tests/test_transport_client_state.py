"""Fail-closed- und Neustarttests für den Windows-Transportclient."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JETZT = datetime(2025, 1, 3, 0, 15, tzinfo=timezone.utc)
TOKEN = "transport-client-state-token"  # noqa: S105


def _modul():
    name = "transport_client_state_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "transport_client.py")
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _konfiguration(tmp_path: Path) -> Path:
    pfad = tmp_path / "transport.toml"
    pfad.write_text(
        f'''
[endpoint]
url = "https://orakel.example/api/daten/import"
key_id = "windows-1"
token_env = "ORAKEL_TRANSPORT_TOKEN"
timeout_sekunden = 5

[export]
symbole = ["EURUSD"]
zeitrahmen = ["M15"]
server_zeitzone = "UTC"
min_kerzen_pro_tag = {{ M15 = 90 }}
max_alter_stunden = {{ M15 = 4 }}
lookback_tage = 10

[state]
pfad = "{(tmp_path / 'state').as_posix()}"

[retry]
http_versuche = 2
basis_sekunden = 0
jitter_sekunden = 0
''',
        encoding="utf-8",
    )
    return pfad


class FakeMT5:
    TIMEFRAME_M15 = 15

    def __init__(self):
        self.abrufe: list[tuple[int, int]] = []
        self.positionen: list[tuple[str, int]] = []

    def symbol_select(self, symbol: str, an: bool) -> bool:
        return True

    def symbol_info_tick(self, symbol: str):
        return {"time": int(datetime(2025, 1, 2, 23, 45, tzinfo=timezone.utc).timestamp())}

    def copy_rates_from_pos(self, symbol: str, rahmen: int, start: int, anzahl: int):
        self.positionen.append((symbol, rahmen))
        return []

    def copy_rates_range(self, symbol: str, rahmen: int, anfang: int, ende: int):
        self.abrufe.append((anfang, ende))
        return []

    def shutdown(self) -> None:
        pass


class FakeSender:
    def __init__(self):
        self.aufrufe: list[tuple[str, bytes, dict[str, str], float]] = []

    def send(self, url: str, body: bytes, headers: dict[str, str], timeout: float):
        self.aufrufe.append((url, body, headers, timeout))
        modul = _modul()
        return modul.HttpAntwort(200, {}, json.dumps({
            "ok": True, "code": "importiert", "sha256": hashlib.sha256(body).hexdigest(),
            "warnungen": [],
        }).encode("utf-8"))


def _lauf(cfg, fake=None, sender=None):
    modul = _modul()
    return modul.run(cfg, mt5=fake or FakeMT5(), sender=sender or FakeSender(),
                     jetzt=JETZT, schlaf=lambda _s: None, token=TOKEN)


def _status(cfg) -> dict:
    return json.loads((cfg.state.pfad / "status.json").read_text(encoding="utf-8"))


def _state_schreiben(cfg, uploads: dict) -> None:
    root = cfg.state.pfad
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps({
        "schema": 1,
        "config_hash": cfg.config_hash,
        "serien": {},
        "uploads": uploads,
    }), encoding="utf-8")


def _upload(dateiname: str, sha: str, *, status: str = "wartend",
            pfad: str | None = None) -> dict:
    return {
        "symbol": "EURUSD", "zeitrahmen": "M15", "handelstag": "2025-01-02",
        "dateiname": dateiname, "sha256": sha,
        "staged_path": pfad or f"staging/{dateiname}", "status": status,
        "versuche": 0, "letzte_kerze": "2025-01-02T23:45:00",
    }


def test_fehlender_state_mit_staging_datei_blockiert_vor_mt5_und_http(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    (cfg.state.pfad / "staging").mkdir(parents=True)
    datei = cfg.state.pfad / "staging" / "EURUSD_M15_20250102.csv"
    datei.write_bytes(b"unangetastet")
    fake = FakeMT5()
    sender = FakeSender()

    code = _lauf(cfg, fake, sender)

    assert code == 5
    assert fake.abrufe == []
    assert sender.aufrufe == []
    assert datei.read_bytes() == b"unangetastet"
    assert not (cfg.state.pfad / "state.json").exists()
    assert _status(cfg)["status"] == "state_reparatur_erforderlich"
    assert _status(cfg)["grund"] == "state_fehlt"


def test_fehlender_state_mit_sent_datei_blockiert(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    (cfg.state.pfad / "sent").mkdir(parents=True)
    (cfg.state.pfad / "sent" / "EURUSD_M15_20250102.csv").write_bytes(b"alt")
    sender = FakeSender()

    assert _lauf(cfg, sender=sender) == 5
    assert sender.aufrufe == []


def test_kaputter_state_blockiert_ohne_bak_automatik(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    cfg.state.pfad.mkdir(parents=True)
    (cfg.state.pfad / "state.json").write_text("{kaputt", encoding="utf-8")
    (cfg.state.pfad / "state.json.bak").write_text(
        json.dumps({"schema": 1, "config_hash": cfg.config_hash,
                    "serien": {}, "uploads": {}}), encoding="utf-8")
    (cfg.state.pfad / "staging").mkdir()
    (cfg.state.pfad / "staging" / "EURUSD_M15_20250102.csv").write_bytes(b"x")
    sender = FakeSender()

    assert _lauf(cfg, sender=sender) == 5
    assert sender.aufrufe == []
    assert (cfg.state.pfad / "state.json").read_text(encoding="utf-8") == "{kaputt"


def test_hash_mismatch_im_staging_blockiert_ohne_neu_export(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    dateiname = "EURUSD_M15_20250102.csv"
    (cfg.state.pfad / "staging").mkdir(parents=True)
    datei = cfg.state.pfad / "staging" / dateiname
    datei.write_bytes(b"veraendert")
    _state_schreiben(cfg, {f"EURUSD|M15|2025-01-02": _upload(
        dateiname, hashlib.sha256(b"erwartet").hexdigest())})
    fake = FakeMT5()
    sender = FakeSender()

    assert _lauf(cfg, fake, sender) == 5
    assert fake.abrufe == []
    assert sender.aufrufe == []
    assert datei.read_bytes() == b"veraendert"
    assert _status(cfg)["grund"] == "hash_mismatch"


def test_hash_mismatch_im_sent_blockiert(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    dateiname = "EURUSD_M15_20250102.csv"
    (cfg.state.pfad / "sent").mkdir(parents=True)
    (cfg.state.pfad / "sent" / dateiname).write_bytes(b"veraendert")
    _state_schreiben(cfg, {f"EURUSD|M15|2025-01-02": _upload(
        dateiname, hashlib.sha256(b"erwartet").hexdigest(), status="erfolgreich",
        pfad=f"sent/{dateiname}")})
    sender = FakeSender()

    assert _lauf(cfg, sender=sender) == 5
    assert sender.aufrufe == []


def test_fehlende_staging_datei_bei_offenem_zustand_blockiert(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    dateiname = "EURUSD_M15_20250102.csv"
    _state_schreiben(cfg, {f"EURUSD|M15|2025-01-02": _upload(
        dateiname, hashlib.sha256(b"erwartet").hexdigest())})
    fake = FakeMT5()
    sender = FakeSender()

    assert _lauf(cfg, fake, sender) == 5
    assert fake.abrufe == []
    assert sender.aufrufe == []
    assert _status(cfg)["grund"] == "datei_fehlt"


def test_state_fehlt_und_ordner_leer_verlangt_init(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    sender = FakeSender()
    assert _lauf(cfg, sender=sender) == 5
    assert sender.aufrufe == []
    assert not (cfg.state.pfad / "state.json").exists()

    assert modul.main(["--config", str(cfg.pfad), "--init-state"]) == 0
    assert (cfg.state.pfad / "state.json").is_file()


def test_wartender_upload_wird_ohne_neu_export_fortgesetzt(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    body = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t23:45:00\t1.1\t1.2\t1.0\t1.15\t10\t0\t2\n"
    ).encode("utf-8")
    dateiname = "EURUSD_M15_20250102.csv"
    (cfg.state.pfad / "staging").mkdir(parents=True)
    (cfg.state.pfad / "staging" / dateiname).write_bytes(body)
    _state_schreiben(cfg, {f"EURUSD|M15|2025-01-02": _upload(
        dateiname, hashlib.sha256(body).hexdigest())})
    fake = FakeMT5()
    sender = FakeSender()

    assert _lauf(cfg, fake, sender) == 0
    assert fake.abrufe == []
    assert fake.positionen == []
    assert len(sender.aufrufe) == 1
    assert sender.aufrufe[0][1] == body
    eintrag = json.loads((cfg.state.pfad / "state.json").read_text(encoding="utf-8"))["uploads"][
        "EURUSD|M15|2025-01-02"]
    assert eintrag["status"] == "erfolgreich"


def test_konfigurationswechsel_blockiert_vor_mt5_und_http(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    cfg.state.pfad.mkdir(parents=True)
    (cfg.state.pfad / "state.json").write_text(json.dumps({
        "schema": 1, "config_hash": "andere-konfiguration",
        "serien": {}, "uploads": {},
    }), encoding="utf-8")
    fake = FakeMT5()
    sender = FakeSender()

    assert _lauf(cfg, fake, sender) == 3
    assert fake.abrufe == []
    assert sender.aufrufe == []


def test_belegtes_lock_beendet_ohne_upload(tmp_path):
    modul = _modul()
    cfg = modul.load_config(_konfiguration(tmp_path))
    _state_schreiben(cfg, {})
    sperre = modul.Dateisperre(cfg.state.pfad / "lock")
    assert sperre.erwerben()
    fake = FakeMT5()
    sender = FakeSender()
    try:
        assert _lauf(cfg, fake, sender) == 0
    finally:
        sperre.freigeben()
    assert fake.abrufe == []
    assert sender.aufrufe == []