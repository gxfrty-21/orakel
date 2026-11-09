from __future__ import annotations

from orakel.config import _umgebung


def test_umgebung_ueberschreibt_nur_gesetzte_pfade(monkeypatch):
    daten = {"basis": {"db_pfad": "orakel.db", "daten_ordner": "daten",
                       "vault_ordner": "vault", "start_kapital": 100000.0}}
    monkeypatch.setenv("ORAKEL_DB_PFAD", "/data/orakel.db")
    monkeypatch.setenv("ORAKEL_VAULT_ORDNER", "/data/vault")
    monkeypatch.delenv("ORAKEL_DATEN_ORDNER", raising=False)

    basis = _umgebung(daten)["basis"]

    assert basis["db_pfad"] == "/data/orakel.db"
    assert basis["vault_ordner"] == "/data/vault"
    assert basis["daten_ordner"] == "daten"
    assert basis["start_kapital"] == 100000.0
