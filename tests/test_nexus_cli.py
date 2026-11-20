"""Der ``--db``-Standard der nexus-CLI kommt aus der Konfiguration."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from orakel.config import load_config
from orakel.nexus import __main__ as cli


def test_explizites_db_gewinnt():
    assert cli._db_pfad("anderer-bestand.db") == "anderer-bestand.db"


def test_ohne_db_kommt_der_pfad_aus_config_und_umgebung(monkeypatch):
    """Ohne ``--db`` gilt ``[basis] db_pfad``; ``ORAKEL_DB_PFAD`` sticht ihn."""
    monkeypatch.delenv("ORAKEL_CONFIG", raising=False)
    monkeypatch.delenv("ORAKEL_DB_PFAD", raising=False)

    assert cli._db_pfad(None) == str(load_config("config.toml").db_pfad)

    monkeypatch.setenv("ORAKEL_DB_PFAD", "/tmp/probe.db")
    assert cli._db_pfad(None) == "/tmp/probe.db"


def test_orakel_config_nennt_die_konfiguration_im_container(monkeypatch):
    gelesen: list[str] = []

    def laden(pfad):
        gelesen.append(str(pfad))
        return SimpleNamespace(db_pfad=Path("/data/orakel.db"))

    monkeypatch.setenv("ORAKEL_CONFIG", "/app/config.toml")
    monkeypatch.setattr(cli, "load_config", laden)

    assert cli._db_pfad(None) == "/data/orakel.db"
    assert gelesen == ["/app/config.toml"]


def test_main_setzt_den_aufgeloesten_pfad(monkeypatch):
    gesehen: list[str] = []

    monkeypatch.setattr(cli, "_db_pfad", lambda _db: "/aus/config.db")
    monkeypatch.setattr(cli, "_status", lambda args: gesehen.append(args.db) or 0)

    assert cli.main(["status"]) == 0
    assert gesehen == ["/aus/config.db"]
