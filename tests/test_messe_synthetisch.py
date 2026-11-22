from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _modul():
    datei = ROOT / "scripts" / "messe_synthetisch.py"
    spec = importlib.util.spec_from_file_location("messe_synthetisch_test", datei)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)
    return modul


def test_reihe_ist_deterministisch_und_fuenfjaehrig():
    modul = _modul()
    erste = modul.erzeuge_reihe()
    zweite = modul.erzeuge_reihe()

    assert len(erste) == 125_280
    assert erste == zweite
    assert erste[0][0].date() == modul.START
    assert erste[-1][0].date() == modul.ENDE
    assert all(zeit.weekday() < 5 for zeit, *_ in erste)


def test_grosse_reihe_schreibt_exakt_die_angeforderte_zeilenzahl(tmp_path):
    modul = _modul()
    pfad = tmp_path / "gross.csv"

    assert modul.erzeuge_grosse_reihe(pfad, anzahl=1_000) == 1_000
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    assert len(zeilen) == 1_001
    assert zeilen[0] == modul.KOPF
    assert zeilen[-1].split("\t")[:2] == ["2026.11.20", "23:45:00"]


def test_db_vergleich_erkennt_abweichende_kerzen(tmp_path):
    modul = _modul()
    from orakel.kern.db import Facts

    reihe = [{"ts": "2026.01.02 00:00:00+00:00", "open": 1.0, "high": 1.1,
              "low": 0.9, "close": 1.05, "volume": 100}]
    block = tmp_path / "block.db"
    zeilenweise = tmp_path / "zeilenweise.db"
    cli = tmp_path / "cli.db"
    for pfad in (block, zeilenweise, cli):
        Facts(pfad).kerzen_speichern("SYN1", "M15", reihe)

    assert modul.vergleiche_dbs(block, zeilenweise, cli)["identisch"]
    Facts(zeilenweise).kerzen_speichern(
        "SYN1", "M15", [{**reihe[0], "close": 1.06}]
    )
    assert not modul.vergleiche_dbs(block, zeilenweise, cli)["identisch"]


def test_config_legt_db_und_vault_nur_im_arbeitsordner_an(tmp_path):
    modul = _modul()
    ziel = modul.isoliere_config(ROOT / "config.toml", tmp_path / "config.toml", tmp_path)

    from orakel.config import load_config

    cfg = load_config(ziel)
    assert cfg.db_pfad.resolve() == (tmp_path / "orakel.db").resolve()
    assert cfg.db_pfad.resolve() != (ROOT / "orakel.db").resolve()
    assert cfg.daten_ordner.resolve() == (tmp_path / "leer").resolve()
    assert cfg.vault_ordner.resolve() == (tmp_path / "vault").resolve()
    assert cfg["basis"]["datenquelle"] == "csv"
    assert cfg["daten"]["max_alter_tage"] == 36500


def test_arbeitsordner_lehnt_vorhandene_dateien_ab(tmp_path):
    modul = _modul()
    (tmp_path / "belegt.txt").write_text("x", encoding="utf-8")

    with pytest.raises(SystemExit):
        modul._arbeitsordner(tmp_path)
