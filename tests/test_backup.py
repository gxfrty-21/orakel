from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modul():
    name = "pruefe_backup_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "pruefe_backup.py")
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _db(tmp_path: Path) -> Path:
    from orakel.db import Facts

    pfad = tmp_path / "orakel.db"
    db = Facts(pfad)
    db.ereignis("info", "Test", "erste Zeile")
    db.ereignis("warnung", "Test", "zweite Zeile")
    db.kerzen_speichern("EURUSD", "M15", [
        {"ts": f"2026-01-01 00:0{i}:00", "open": 1.0, "high": 1.1, "low": 0.9,
         "close": 1.05, "volume": 1.0}
        for i in range(5)
    ])
    return pfad


def test_sicherung_ist_integer_und_hat_dieselben_zeilen(tmp_path):
    modul = _modul()
    db = _db(tmp_path)

    ergebnis = modul.sichere(db, tmp_path / "backups",
                             jetzt=datetime(2026, 5, 20, 12, tzinfo=timezone.utc))

    assert ergebnis["integrity"] == "ok"
    sicherung = Path(ergebnis["pfad"])
    assert sicherung.exists()
    assert modul.zeilenzahlen(sicherung) == modul.zeilenzahlen(db)
    probe = modul.pruefe_restore(db, sicherung)
    assert probe["ok"] is True
    assert probe["abweichungen"] == []


def test_alte_tagesstaende_werden_entfernt(tmp_path):
    modul = _modul()
    db = _db(tmp_path)
    ordner = tmp_path / "backups"
    ordner.mkdir()
    alt = ordner / "orakel-2026-04-01.db"
    alt.write_bytes(b"alt")
    os.utime(alt, (0, 0))

    ergebnis = modul.sichere(db, ordner,
                             jetzt=datetime(2026, 5, 20, 12, tzinfo=timezone.utc), tage=7)

    assert not alt.exists()
    assert "orakel-2026-04-01.db" in ergebnis["entfernt"]


def test_sonntag_legt_wochenstand_an_und_haelt_vier(tmp_path):
    modul = _modul()
    db = _db(tmp_path)
    ordner = tmp_path / "backups"
    ordner.mkdir()
    for nummer in range(1, 7):
        (ordner / f"orakel-kw-2026-{nummer:02d}.db").write_bytes(b"alt")

    modul.sichere(db, ordner, jetzt=datetime(2026, 5, 24, 12, tzinfo=timezone.utc))

    wochen = sorted(ordner.glob("orakel-kw-*.db"))
    assert len(wochen) == 4
    assert any("2026-21" in pfad.name for pfad in wochen)


def test_restore_probe_erkennt_abweichende_zeilen(tmp_path):
    modul = _modul()
    db = _db(tmp_path)
    sicherung = Path(modul.sichere(db, tmp_path / "backups")["pfad"])

    c = sqlite3.connect(sicherung)
    c.execute("DELETE FROM kerzen")
    c.commit()
    c.close()

    probe = modul.pruefe_restore(db, sicherung)

    assert probe["ok"] is False
    assert [a["tabelle"] for a in probe["abweichungen"]] == ["kerzen"]


def test_alte_zeitstempel_der_sicherung_bleiben_lesbar(tmp_path):
    modul = _modul()
    db = _db(tmp_path)
    gestern = datetime.now(timezone.utc) - timedelta(days=1)

    ergebnis = modul.sichere(db, tmp_path / "backups", jetzt=gestern)

    assert modul.integritaet(Path(ergebnis["pfad"])) == "ok"
