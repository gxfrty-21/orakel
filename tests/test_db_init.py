"""Tests für die einmalige Schema-Initialisierung der Fakten-Datenbank."""

from __future__ import annotations

from orakel.kern import db as db_mod


def test_schema_wird_pro_pfad_nur_einmal_angelegt(tmp_path, monkeypatch):
    pfad = tmp_path / "einmal.db"
    aufrufe: list[int] = []
    echtes_anwenden = db_mod.migrationen.anwenden

    def zaehle(ziel, **kwargs):
        aufrufe.append(1)
        return echtes_anwenden(ziel, **kwargs)

    monkeypatch.setattr(db_mod.migrationen, "anwenden", zaehle)

    db_mod.Facts(pfad)
    db_mod.Facts(pfad)
    db_mod.Facts(pfad)

    assert pfad.exists()
    assert len(aufrufe) == 1


def test_initialisiere_ist_idempotent(tmp_path):
    pfad = tmp_path / "idempotent.db"

    db_mod.initialisiere(pfad)
    db_mod.initialisiere(pfad)

    with db_mod.Facts(pfad).conn() as c:
        tabellen = {
            zeile["name"]
            for zeile in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "kerzen" in tabellen


def test_verbindung_setzt_busy_timeout(tmp_path):
    fakt = db_mod.Facts(tmp_path / "timeout.db")

    with fakt.conn() as c:
        assert int(c.execute("PRAGMA busy_timeout").fetchone()[0]) == 5000
