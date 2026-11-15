from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modul(name: str, datei: Path):
    spec = importlib.util.spec_from_file_location(name, datei)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _health(ts_epoch: float) -> dict:
    return {"ts_epoch": ts_epoch, "ok": True, "daten": {}}


def _health_schreiben(pfad: Path, zeiten: list[float]) -> None:
    pfad.write_text(
        "\n".join(json.dumps(_health(ts)) for ts in zeiten) + "\n",
        encoding="utf-8",
    )


def test_watcher_erkennt_regulaeres_ende_aus_statusdatei(tmp_path):
    modul = _modul("soak_auto_status_test", ROOT / "scripts" / "soak_auto_abnahme.py")
    (tmp_path / "monitor-status.json").write_text(json.dumps({
        "regulaer": True,
        "abbruch": False,
        "dauer_sekunden": 86400,
        "abbruch_grund": None,
    }), encoding="utf-8")

    ausgang = modul.monitor_ausgang(tmp_path, 24 * 3600)

    assert ausgang["monitor_ausgang"] == "regulaer"
    assert ausgang["monitor_abbruch"] is False
    assert ausgang["monitor_status_quelle"] == "monitor-status.json"


def test_watcher_erkennt_vorzeitigen_abbruch_aus_statusdatei(tmp_path):
    modul = _modul("soak_auto_abbruch_test", ROOT / "scripts" / "soak_auto_abnahme.py")
    (tmp_path / "monitor-status.json").write_text(json.dumps({
        "regulaer": False,
        "abbruch": True,
        "dauer_sekunden": 120,
        "abbruch_grund": "Signal 15",
    }), encoding="utf-8")

    ausgang = modul.monitor_ausgang(tmp_path, 24 * 3600)

    assert ausgang["monitor_ausgang"] == "abgebrochen"
    assert ausgang["monitor_abbruch"] is True
    assert "Signal 15" in ausgang["monitor_abbruch_grund"]


def test_watcher_fallback_erkennt_kurzen_lauf_als_abbruch(tmp_path):
    modul = _modul("soak_auto_fallback_test", ROOT / "scripts" / "soak_auto_abnahme.py")
    _health_schreiben(tmp_path / "health.jsonl", [0, 3600])

    ausgang = modul.monitor_ausgang(tmp_path, 24 * 3600)

    assert ausgang["monitor_ausgang"] == "abgebrochen"
    assert ausgang["monitor_abbruch"] is True
    assert ausgang["monitor_status_quelle"] == "health-fallback"
    assert ausgang["monitor_dauer_s"] == 3600


def test_watcher_fallback_erkennt_langen_lauf_als_regulaer(tmp_path):
    modul = _modul("soak_auto_fallback_lang_test", ROOT / "scripts" / "soak_auto_abnahme.py")
    _health_schreiben(tmp_path / "health.jsonl", [0, 86400])

    ausgang = modul.monitor_ausgang(tmp_path, 24 * 3600)

    assert ausgang["monitor_ausgang"] == "regulaer"
    assert ausgang["monitor_abbruch"] is False
    assert ausgang["monitor_status_quelle"] == "health-fallback"


def test_watcher_schreibt_abbruchstatus_ohne_abnahme(tmp_path, monkeypatch):
    modul = _modul("soak_auto_main_test", ROOT / "scripts" / "soak_auto_abnahme.py")
    _health_schreiben(tmp_path / "health.jsonl", [0, 120])
    monkeypatch.setattr(modul, "laeuft", lambda pid: False)
    monkeypatch.setattr(
        modul.subprocess, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Abnahme darf bei Abbruch nicht gestartet werden")
        ),
    )
    monkeypatch.setattr(sys, "argv", [
        "soak_auto_abnahme.py",
        "--monitor-pid", "12345",
        "--verzeichnis", str(tmp_path),
        "--duration-hours", "24",
    ])

    code = modul.main()

    assert code == 1
    status = json.loads((tmp_path / "abnahme-status.json").read_text(encoding="utf-8"))
    assert status["monitor_ausgang"] == "abgebrochen"
    assert status["monitor_abbruch"] is True
    assert status["abnahme_gestartet"] is False
    assert status["bestanden"] is False
    assert status["exit_code"] == 1
    assert "vorzeitig" in status["grund"]
