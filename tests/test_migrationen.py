"""Tests für die nummerierten Migrationen (Bereich 4.3)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from orakel.kern import migrationen

ALLE = [m.nummer for m in migrationen.dateien()]


def _tabellen(pfad: Path) -> set[str]:
    c = sqlite3.connect(pfad)
    try:
        return {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        c.close()


def test_leere_datenbank_wendet_alle_migrationen_an(tmp_path):
    pfad = tmp_path / "leer.db"

    ergebnis = migrationen.anwenden(pfad)

    assert ergebnis["angewendet"] == ALLE
    assert migrationen.angewendet(pfad) == ALLE
    tabellen = _tabellen(pfad)
    assert {"kerzen", "artikel", "agent_profiles", "schema_migrationen"} <= tabellen


def test_teilstand_auf_0003_wendet_nur_die_neuere_migration_an(tmp_path):
    """Eine DB auf Stand 0003 bekommt nur die danach hinzugekommene Migration."""
    ordner = tmp_path / "migrationen"
    ordner.mkdir()
    for quelle in migrationen.dateien():
        for datei in (quelle.hoch, quelle.runter):
            if datei is not None:
                (ordner / datei.name).write_bytes(datei.read_bytes())
    (ordner / "0004_nachtrag.sql").write_text(
        "CREATE TABLE nachtrag (id INTEGER);\n", encoding="utf-8")
    pfad = tmp_path / "stand3.db"

    erster = migrationen.anwenden(pfad, ordner=ordner, bis=3)

    assert erster["angewendet"] == [1, 2, 3]
    assert migrationen.angewendet(pfad) == [1, 2, 3]
    assert "nachtrag" not in _tabellen(pfad)

    zweiter = migrationen.anwenden(pfad, ordner=ordner)

    assert zweiter["angewendet"] == [4]
    assert migrationen.angewendet(pfad) == [1, 2, 3, 4]
    assert "nachtrag" in _tabellen(pfad)
    assert "agent_profiles" in _tabellen(pfad)


def test_fehlerhafte_migration_rollt_zurueck_und_laesst_die_db_unveraendert(tmp_path):
    ordner = tmp_path / "migrationen"
    ordner.mkdir()
    (ordner / "0001_ok.sql").write_text("CREATE TABLE a (id INTEGER);\n", encoding="utf-8")
    (ordner / "0002_kaputt.sql").write_text(
        "CREATE TABLE b (id INTEGER);\nCREATE TABLE oops (;\n", encoding="utf-8")
    pfad = tmp_path / "kaputt.db"

    with pytest.raises(migrationen.MigrationsFehler, match="0002_kaputt.sql"):
        migrationen.anwenden(pfad, ordner=ordner)

    assert migrationen.angewendet(pfad) == [1]
    tabellen = _tabellen(pfad)
    assert "a" in tabellen
    assert "b" not in tabellen, "Teil der fehlerhaften Migration blieb zurück"


def test_bestehende_datenbank_wird_vor_der_migration_gesichert(tmp_path):
    pfad = tmp_path / "bestand.db"
    migrationen.anwenden(pfad, bis=ALLE[1])
    c = sqlite3.connect(pfad)
    c.execute("INSERT INTO kerzen (symbol, zeitrahmen, ts, open, high, low, close, volume) "
              "VALUES ('EURUSD', 'M15', '2026-01-01 00:00:00', 1, 1, 1, 1, 1)")
    c.commit()
    c.close()

    ergebnis = migrationen.anwenden(pfad)

    assert ergebnis["angewendet"] == ALLE[2:]
    sicherung = Path(str(ergebnis["backup"]))
    assert sicherung.exists()
    kopie = sqlite3.connect(sicherung)
    try:
        assert kopie.execute("SELECT COUNT(*) FROM kerzen").fetchone()[0] == 1
    finally:
        kopie.close()


def test_downgrade_entfernt_die_migration_und_ihre_tabellen(tmp_path):
    pfad = tmp_path / "zurueck.db"
    migrationen.anwenden(pfad)

    ergebnis = migrationen.zurueckrollen(pfad, bis=ALLE[1])

    assert ergebnis["zurueckgerollt"] == ALLE[2:]
    assert migrationen.angewendet(pfad) == ALLE[:2]
    tabellen = _tabellen(pfad)
    assert "agent_profiles" in tabellen
    assert "kerzen" in tabellen
    c = sqlite3.connect(pfad)
    try:
        spalten = {r[1] for r in c.execute("PRAGMA table_info(artikel)")}
    finally:
        c.close()
    assert "prioritaet" not in spalten


def test_downgrade_ohne_hinterlegte_datei_bricht_vorher_ab(tmp_path):
    ordner = tmp_path / "migrationen"
    ordner.mkdir()
    (ordner / "0001_ohne_down.sql").write_text("CREATE TABLE a (id INTEGER);\n",
                                               encoding="utf-8")
    pfad = tmp_path / "ohne.db"
    migrationen.anwenden(pfad, ordner=ordner)

    with pytest.raises(migrationen.MigrationsFehler, match="Downgrade"):
        migrationen.zurueckrollen(pfad, ordner=ordner)

    assert migrationen.angewendet(pfad) == [1]
    assert "a" in _tabellen(pfad)


def test_bestandsdatenbank_ohne_historie_wird_durchmigriert(tmp_path):
    """Ein alter Bestand verliert keine Daten und erhält die fehlenden Spalten."""
    from orakel.kern.db import Facts

    pfad = tmp_path / "alt.db"
    migrationen.anwenden(pfad)
    Facts(pfad).artikel_speichern(
        "Testquelle", "nachrichten", "Alter Artikel", "https://example.com/alt",
        None, "Bestand", 0.9, ["EURUSD"], "hash-alt",
    )

    c = sqlite3.connect(pfad)
    c.execute("DROP TABLE schema_migrationen")
    for spalte in ("prioritaet", "prioritaet_grund", "erkannt"):
        c.execute(f"ALTER TABLE artikel DROP COLUMN {spalte}")
    c.execute("PRAGMA user_version = 1")
    c.commit()
    c.close()

    ergebnis = migrationen.anwenden(pfad)

    assert ergebnis["angewendet"] == ALLE
    assert ergebnis["backup"] is not None
    c = sqlite3.connect(pfad)
    try:
        spalten = {r[1] for r in c.execute("PRAGMA table_info(artikel)")}
        assert {"prioritaet", "prioritaet_grund", "erkannt"} <= spalten
        assert c.execute("SELECT COUNT(*) FROM artikel").fetchone()[0] == 1
    finally:
        c.close()
