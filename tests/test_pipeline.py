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

    # Der Fehler in der zweiten Datei rollt auch die bereits gelesene H1-Datei zurück.
    assert db.kerzen("EURUSD", "H1") == []
    assert db.kerzen("EURUSD", "M15") == []
    assert db.zustand("datenquelle") is None
    assert any("Häufigster Abstand" in zeile["text"] for zeile in db.ereignisse())


def test_fehlende_reihe_rollt_import_zurueck_und_setzt_quelle_nicht(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    # Kopf ohne Kerzen: Die Datei ist lesbar, liefert aber keine Reihe.
    (ordner / "US500_M15.csv").write_text(KOPF, encoding="utf-8")
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler) as fehler:
        sicherstellen_daten(cfg, db)

    assert "US500_M15.csv" in str(fehler.value)
    assert db.symbole() == []
    assert db.kerzen("EURUSD", "M15") == []
    assert db.zustand("datenquelle") is None


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


def test_leerer_csv_ordner_verwendet_vorhandene_db_kerzen_ohne_synthetik(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    db = Facts(cfg.db_pfad)
    bestand = synthetische_kerzen("EURUSD", kerzen=120, seed=9)
    db.kerzen_speichern_df("EURUSD", "M15", bestand)
    db.zustand_setzen("datenquelle", "csv")
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)

    symbole, quelle = sicherstellen_daten(cfg, db)

    assert symbole == ["EURUSD"]
    assert quelle == "csv"
    assert len(db.kerzen("EURUSD", "M15")) == len(bestand)
    assert db.kerzen("US500", "M15") == []
    ereignisse = db.ereignisse()
    assert any(
        zeile["stufe"] == "warnung"
        and "Keine CSV-Datei" in zeile["text"]
        and "vorhandene Datenbankkerzen" in zeile["text"]
        for zeile in ereignisse
    )
    assert not any("Synthetische Kerzen erzeugt" in zeile["text"]
                   for zeile in ereignisse)


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
    # kein stiller Rückfall auf synthetische Kerzen und kein Teilimport der M15-Datei
    assert db.kerzen("EURUSD", "H1") == []
    assert db.kerzen("EURUSD", "M15") == []
    assert db.kerzen("US500", "M15") == []
    assert any("EURUSD H1" in zeile["text"] for zeile in db.ereignisse())


def test_h1_datei_mit_jahres_suffix_wird_als_h1_importiert(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_H1_2020.csv").write_text(
        KOPF
        + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
        + "2025.01.02\t10:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.kerzen("EURUSD", "H1")) == 2
    assert db.zustand("datenquelle") == "csv"


def test_veraltete_csv_warnt_ohne_import_zu_blockieren(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.kerzen("EURUSD", "M15")) == 1
    assert any(
        zeile["stufe"] == "warnung"
        and "EURUSD M15" in zeile["text"]
        and "jüngste Kerze" in zeile["text"]
        for zeile in db.ereignisse()
    )


def test_unbekannter_zeitrahmen_bricht_vor_dem_ersten_schreiben_ab(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    (ordner / "ZZZ_H4.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler) as fehler:
        sicherstellen_daten(cfg, db)

    meldung = str(fehler.value)
    assert "H4" in meldung
    assert "ZZZ_H4.csv" in meldung
    # Die gültige M15-Datei darf nicht vor dem Abbruch importiert werden.
    assert db.symbole() == []
    assert db.kerzen("EURUSD", "M15") == []
    assert any("H4" in zeile["text"] and zeile["stufe"] == "fehler"
               for zeile in db.ereignisse())


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


@pytest.mark.parametrize("befehl", ["cmd_pruefen", "cmd_konferenz"])
def test_cli_meldet_datenfehler_mit_exit_1(befehl, monkeypatch, capsys):
    import argparse

    from orakel import __main__ as cli
    from orakel import pipeline

    def datenfehler(**_kwargs):
        raise DatenFehler("CSV-Quelle liefert keine verwendbaren Kerzen")

    monkeypatch.setattr(pipeline, "lauf", datenfehler)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: object())
    monkeypatch.setattr(cli, "_schema_pruefen", lambda _cfg: None)
    args = argparse.Namespace(
        config="config.toml", modus="backtest", quelle=None, bericht="dashboard.json",
        ohne_konferenz=False, mit_spider=False,
    )

    code = getattr(cli, befehl)(args)

    assert code == 1
    assert "FEHLER CSV-Quelle liefert keine verwendbaren Kerzen" in capsys.readouterr().err
