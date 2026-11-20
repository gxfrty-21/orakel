"""Tests für den Unterbefehl ``orakel migration`` (Stand und Rückweg)."""
from __future__ import annotations

import dataclasses
from pathlib import Path

from orakel import __main__ as cli
from orakel.kern import migrationen


def _db_mit_migrationen(cfg) -> Path:
    pfad = Path(cfg.db_pfad)
    migrationen.anwenden(pfad)
    return pfad


def test_status_zeigt_stand_und_offene(cfg, monkeypatch, capsys):
    pfad = _db_mit_migrationen(cfg)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--status"]) == 0

    ausgabe = capsys.readouterr().out
    assert f"orakel: Datenbank {pfad}" in ausgabe
    for datei in migrationen.dateien():
        assert f"{datei.nummer:04d}_{datei.name}" in ausgabe
    assert "orakel: Offen keine" in ausgabe


def test_status_nennt_offene_migrationen_nach_teilrueckzug(cfg, monkeypatch, capsys):
    pfad = _db_mit_migrationen(cfg)
    alle = migrationen.dateien()
    migrationen.zurueckrollen(pfad, bis=1)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--status"]) == 0

    ausgabe = capsys.readouterr().out
    assert "orakel: Stand 0001_" in ausgabe
    for datei in alle[1:]:
        assert f"{datei.nummer:04d}_{datei.name}" in ausgabe


def test_status_legt_keine_datenbank_an(cfg, monkeypatch, capsys):
    pfad = Path(cfg.db_pfad)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--status"]) == 1

    assert not pfad.exists()                  # rein lesend, nichts angelegt
    assert "Keine Datenbank" in capsys.readouterr().err


def test_ohne_schalter_kommt_ein_hinweis(cfg, monkeypatch, capsys):
    _db_mit_migrationen(cfg)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration"]) == 1

    assert "--status oder --zurueck" in capsys.readouterr().err


def test_status_und_zurueck_gleichzeitig_abgelehnt(cfg, monkeypatch, capsys):
    _db_mit_migrationen(cfg)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--status", "--zurueck", "2"]) == 1

    assert "schliessen sich aus" in capsys.readouterr().err


def test_zurueck_ohne_bestaetigen_aendert_nichts(cfg, monkeypatch, capsys):
    pfad = _db_mit_migrationen(cfg)
    vorher = migrationen.angewendet(pfad)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--zurueck", "1"]) == 1

    ausgabe = capsys.readouterr()
    assert "Geplant" in ausgabe.out
    assert "--bestaetigen" in ausgabe.err
    assert "Nichts geändert" in ausgabe.err
    assert migrationen.angewendet(pfad) == vorher
    assert not list(pfad.parent.glob("*.vor-migration-*.bak"))


def test_zurueck_mit_bestaetigen_rollt_und_nennt_sicherung(cfg, monkeypatch, capsys):
    pfad = _db_mit_migrationen(cfg)
    alle = migrationen.dateien()
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--zurueck", "1", "--bestaetigen"]) == 0

    ausgabe = capsys.readouterr().out
    assert migrationen.angewendet(pfad) == [alle[0].nummer]
    assert "orakel: Zurückgerollt" in ausgabe
    assert "orakel: Sicherung" in ausgabe and ".vor-migration-" in ausgabe
    assert f"orakel: Neuer Stand 0001_{alle[0].name}" in ausgabe
    assert list(pfad.parent.glob(f"{pfad.name}.vor-migration-*.bak"))


def test_zurueck_auf_aktuellen_stand_meldet_nichts_zu_tun(cfg, monkeypatch, capsys):
    pfad = _db_mit_migrationen(cfg)
    letzte = migrationen.angewendet(pfad)[-1]
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--zurueck", str(letzte), "--bestaetigen"]) == 0

    assert "Nichts zu tun" in capsys.readouterr().out
    assert not list(pfad.parent.glob("*.vor-migration-*.bak"))


def test_fehlende_down_datei_bricht_vor_jeder_aenderung_ab(cfg, monkeypatch, capsys):
    pfad = _db_mit_migrationen(cfg)
    vorher = migrationen.angewendet(pfad)
    ohne = [dataclasses.replace(datei, runter=None)
            if datei.nummer == vorher[-1] else datei
            for datei in migrationen.dateien()]
    monkeypatch.setattr(migrationen, "dateien", lambda ordner=None: ohne)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    assert cli.main(["migration", "--zurueck", "1", "--bestaetigen"]) == 1

    ausgabe = capsys.readouterr()
    assert "Kein Downgrade hinterlegt" in ausgabe.err
    assert "Nichts geändert" in ausgabe.err
    assert migrationen.angewendet(pfad) == vorher
    assert not list(pfad.parent.glob("*.vor-migration-*.bak"))


def test_nutzt_den_pfad_aus_der_konfiguration(cfg, monkeypatch, capsys, tmp_path):
    pfad = _db_mit_migrationen(cfg)
    eigene = tmp_path / "eigene.toml"
    gesehen: list[str] = []

    def merken(pfad_arg: str):
        gesehen.append(pfad_arg)
        return cfg

    monkeypatch.setattr(cli, "load_config", merken)

    assert cli.main(["--config", str(eigene), "migration", "--status"]) == 0

    assert gesehen == [str(eigene)]
    assert str(pfad) in capsys.readouterr().out
