from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modul(name: str, datei: Path):
    spec = importlib.util.spec_from_file_location(name, datei)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _health(ts_epoch: float, paper_tick: str) -> dict:
    return {
        "ts_epoch": ts_epoch,
        "ok": True,
        "daten": {
            "commit": "test-commit",
            "paper_tick": paper_tick,
            "betrieb": {"status": "laeuft", "db_mb": 10.0, "rss_mb": 100.0},
        },
    }


def _tief(company: dict, backup: dict) -> dict:
    return {
        "takt": {"status": "laeuft", "letzter": "2026-11-15T00:00:00+00:00"},
        "ressourcen": {
            "db_mb": 10.0,
            "rss_mb": 100.0,
            "freier_speicher_mb": 1000.0,
            "limits": {"max_db_mb": 512.0, "max_rss_mb": 768.0},
        },
        "jobs": [{"name": "paper", "fehlschluesse": 0, "backoff_sekunden": 0}],
        "letzte_laeufe": [{"status": "ok"}],
        "company": company,
        "backup": backup,
    }


def _schreibe_messreihe(tmp_path: Path, company: dict, backup: dict) -> Path:
    health = [
        _health(0, "2026-11-15T00:00:00+00:00"),
        _health(86400, "2026-11-16T00:00:00+00:00"),
    ]
    deep = [
        {"ok": True, "daten": _tief(company, backup)},
    ]
    (tmp_path / "health.jsonl").write_text(
        "\n".join(json.dumps(z) for z in health) + "\n", encoding="utf-8"
    )
    (tmp_path / "betrieb.jsonl").write_text(
        "\n".join(json.dumps(z) for z in deep) + "\n", encoding="utf-8"
    )
    return tmp_path


def _kriterien(daten: dict) -> dict[str, dict]:
    return {k["name"]: k for k in daten["kriterien"]}


def test_echter_soak_prueft_audit_queue_und_backup(tmp_path):
    modul = _modul("soak_abnahme_test", ROOT / "scripts" / "soak_abnahme.py")
    ordner = _schreibe_messreihe(
        tmp_path,
        company={
            "audit_ok": True,
            "queue_offen": 0,
            "queue_alter_max_s": None,
            "dead_letter": 0,
            "blocked": 0,
            "fehler": None,
        },
        backup={
            "ok": True,
            "integrity": "ok",
            "restore_ok": True,
            "alter_s": 60.0,
        },
    )
    daten = modul._echter_soak(ordner)
    kriterien = _kriterien(daten)

    assert kriterien["Audit-Kette"]["bestanden"] is True
    assert kriterien["Company-Queue"]["bestanden"] is True
    assert kriterien["Backup-Restore"]["bestanden"] is True
    assert daten["metriken"]["audit_ok"] is True
    assert daten["metriken"]["queue_dead_letter"] == 0
    assert daten["metriken"]["backup_restore_ok"] is True


def test_echter_soak_meldet_fehlendes_backup_und_queue_problem(tmp_path):
    modul = _modul("soak_abnahme_fehler_test", ROOT / "scripts" / "soak_abnahme.py")
    ordner = _schreibe_messreihe(
        tmp_path,
        company={
            "audit_ok": True,
            "queue_offen": 2,
            "queue_alter_max_s": 7200.0,
            "dead_letter": 1,
            "blocked": 1,
            "fehler": None,
        },
        backup={"ok": False, "integrity": None, "restore_ok": False,
                "alter_s": None, "fehler": "kein SQLite-Backup gefunden"},
    )
    daten = modul._echter_soak(ordner)
    kriterien = _kriterien(daten)

    assert kriterien["Audit-Kette"]["bestanden"] is True
    assert kriterien["Company-Queue"]["bestanden"] is False
    assert kriterien["Backup-Restore"]["bestanden"] is False


def test_monitor_zusammenfassung_zeigt_company_queue(tmp_path):
    monitor = _modul("soak_monitor_test", ROOT / "scripts" / "soak_monitor.py")
    jetzt = datetime(2026, 11, 15, tzinfo=timezone.utc)
    deep = [{
        "ok": True,
        "daten": {
            "company": {
                "queue_offen": 2,
                "queue_alter_max_s": 7200.0,
                "dead_letter": 1,
                "blocked": 1,
                "fehler": None,
            },
            "jobs": [],
        },
    }]

    text = monitor._markdown_zusammenfassung(jetzt, jetzt, [], deep, tmp_path)

    assert "## Company-Queue" in text
    assert "Offene Tasks (max.): `2`" in text
    assert "Dead-Letter (max.): `1`" in text
    assert "Max. Alter offener Tasks: `7200.0 s`" in text
    assert "1 Dead-Letter-Task(s)" in text


def test_backup_probe_erkennt_beschaedigtes_backup(tmp_path):
    probe = _modul("soak_probe_kaputt_test", ROOT / "scripts" / "soak_probe.py")
    datei = tmp_path / "orakel-2026-11-15.db"
    datei.write_bytes(b"kein gueltiges SQLite-Backup")

    ergebnis = probe._backup(tmp_path)

    assert ergebnis["ok"] is False
    assert ergebnis["restore_ok"] is False
    assert ergebnis["integrity"] is None
    assert ergebnis["tabellen"] == {}
    assert "Restore-Probe fehlgeschlagen" in ergebnis["fehler"]
    assert ergebnis["pfad"] == str(datei)


def test_backup_probe_restauriert_kopie_und_prueft_integritaet(tmp_path):
    probe = _modul("soak_probe_test", ROOT / "scripts" / "soak_probe.py")
    quelle = tmp_path / "orakel-2026-11-15.db"
    con = sqlite3.connect(quelle)
    try:
        con.execute("CREATE TABLE artikel (id INTEGER PRIMARY KEY, titel TEXT)")
        con.execute("INSERT INTO artikel (titel) VALUES ('Test')")
        con.commit()
    finally:
        con.close()

    ergebnis = probe._backup(tmp_path)

    assert ergebnis["ok"] is True
    assert ergebnis["integrity"] == "ok"
    assert ergebnis["restore_ok"] is True
    assert ergebnis["tabellen"] == {"artikel": 1}
