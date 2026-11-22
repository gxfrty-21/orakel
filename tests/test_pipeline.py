from __future__ import annotations

import pytest

from orakel.kern.data import synthetische_kerzen
from orakel.kern.db import Facts
from orakel.pipeline import DatenFehler, sicherstellen_daten


KOPF = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"


def _als_mt5(df) -> str:
    zeilen = [KOPF]
    for r in df.itertuples(index=False):
        zeilen.append(
            f"{r.ts:%Y.%m.%d}\t{r.ts:%H:%M:%S}\t{r.open}\t{r.high}\t{r.low}\t{r.close}"
            f"\t{int(r.volume)}\t0\t2\n"
        )
    return "".join(zeilen)


def test_h1_datei_wird_importiert_wenn_der_richter_h1_liest(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    zeilen = [KOPF]
    for stunde in (9, 10, 11):
        zeilen.append(f"2025.01.02\t{stunde:02d}:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n")
        (ordner / "EURUSD_H1.csv").write_text("".join(zeilen), encoding="utf-8")
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n", encoding="utf-8"
    )
    (ordner / "EURUSD_M5.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n", encoding="utf-8"
    )
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.kerzen("EURUSD", "H1")) == 3
    assert db.kerzen("EURUSD", "M5") == []


def test_bars_pro_jahr_folgt_dem_zeitrahmen(cfg):
    assert cfg.bars_pro_jahr_fuer("M15") == 24960
    assert cfg.bars_pro_jahr_fuer("H1") == 6240
    assert cfg.mit_bars_pro_jahr(6240).bars_pro_jahr == 6240
    assert cfg.bars_pro_jahr == 24960  # Original bleibt unverändert
    cfg._d["basis"]["richter_zeitrahmen"] = "h1"
    assert cfg.richter_zeitrahmen == "H1"


def test_min_kerzen_folgt_dem_zeitrahmen(cfg):
    cfg._d["daten"]["min_kerzen"] = 1200

    assert cfg.min_kerzen_fuer("M15") == 1200
    assert cfg.min_kerzen_fuer("H1") == 300
    urteil = cfg.fuer_zeitrahmen("H1")
    assert urteil["daten"]["min_kerzen"] == 300
    assert urteil.bars_pro_jahr == 6240
    # Original bleibt unverändert
    assert cfg["daten"]["min_kerzen"] == 1200
    assert cfg.bars_pro_jahr == 24960


def test_falsch_getaktete_datei_landet_nicht_im_ordner_import(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    h1 = synthetische_kerzen("EURUSD", kerzen=200, seed=4, timeframe_minuten=60)
    (ordner / "EURUSD_H1.csv").write_text(_als_mt5(h1), encoding="utf-8")
    # Gleiche Kerzen unter M15-Namen: vor dem Schreiben abgelehnt.
    (ordner / "EURUSD_M15.csv").write_text(_als_mt5(h1), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler):
        sicherstellen_daten(cfg, db)

    assert len(db.kerzen("EURUSD", "H1")) == 200
    assert db.kerzen("EURUSD", "M15") == []
    assert any("Median-Abstand" in zeile["text"] for zeile in db.ereignisse())


def test_leerer_csv_ordner_bricht_ab_statt_synthetisch(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler) as fehler:
        sicherstellen_daten(cfg, db)

    meldung = str(fehler.value)
    assert "Keine CSV-Datei" in meldung
    assert "synthetischen Kerzen" in meldung
    # kein stiller Rückfall auf synthetische Kerzen
    assert db.symbole() == []
    assert db.kerzen("EURUSD", "M15") == []
    assert any("Keine CSV-Datei" in zeile["text"] for zeile in db.ereignisse())


def test_h1_richter_ohne_h1_datei_bricht_ab_statt_leer_zu_laufen(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler) as fehler:
        sicherstellen_daten(cfg, db)

    meldung = str(fehler.value)
    assert "EURUSD H1" in meldung
    assert "H1" in meldung and "M15" in meldung
    # kein stiller Rückfall auf synthetische Kerzen und keine leere H1-Reihe
    assert db.kerzen("EURUSD", "H1") == []
    assert db.kerzen("US500", "M15") == []
    assert any("EURUSD H1" in zeile["text"] for zeile in db.ereignisse())


def test_nur_nicht_m15_dateien_brechen_ab_statt_synthetisch(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M1.csv").write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler) as fehler:
        sicherstellen_daten(cfg, db)

    meldung = str(fehler.value)
    assert "M15" in meldung
    assert "EURUSD_M1.csv" in meldung
    # kein stiller Rückfall auf synthetische Kerzen
    assert db.symbole() == []
    assert db.kerzen("EURUSD", "M15") == []
    assert any("EURUSD_M1.csv" in zeile["text"] for zeile in db.ereignisse())
