from __future__ import annotations

import pytest

from orakel.kern.db import Facts
from orakel.pipeline import DatenFehler, sicherstellen_daten


KOPF = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"


def test_h1_datei_wird_importiert_wenn_der_richter_h1_liest(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    zeilen = [KOPF]
    for stunde in (9, 10, 11):
        zeilen.append(f"2025.01.02\t{stunde:02d}:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n")
    (ordner / "EURUSD_H1.csv").write_text("".join(zeilen), encoding="utf-8")
    (ordner / "EURUSD_M5.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n", encoding="utf-8")
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
