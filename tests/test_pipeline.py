from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from orakel.config import RisikoGrenzen
from orakel.kern.data import synthetische_kerzen
from orakel.kern.db import Facts
from orakel.kern.strategies import Signalplan
from orakel.pipeline import DatenFehler, _stop_fuer_plan, sicherstellen_daten


KOPF = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"


def _als_mt5(df) -> str:
    zeilen = [KOPF]
    for r in df.itertuples(index=False):
        zeilen.append(
            f"{r.ts:%Y.%m.%d}\t{r.ts:%H:%M:%S}\t{r.open}\t{r.high}\t{r.low}\t{r.close}"
            f"\t{int(r.volume)}\t0\t2\n"
        )
    return "".join(zeilen)


def _frische_m15(symbol: str = "EURUSD", kerzen: int = 1300,
                 alter_stunden: float = 1.0):
    """M15-Reihe, deren jüngste Kerze ``alter_stunden`` alt ist."""
    ende = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=alter_stunden)
    start = ende - pd.Timedelta(minutes=15 * (kerzen - 1))
    return synthetische_kerzen(symbol, kerzen=kerzen, seed=17,
                               start=start.isoformat())


def test_agenten_kontext_enthaelt_schema_2_bericht(cfg, monkeypatch, tmp_path):
    from orakel import pipeline

    gesehen = {}

    def merke(db, ctx, nur_abteilung=None):
        gesehen.update(ctx)
        return []

    monkeypatch.setattr(pipeline, "load_config", lambda pfad="config.toml": cfg)
    monkeypatch.setattr(pipeline, "sicherstellen_daten",
                        lambda cfg, db, quelle=None, **_kwargs:
                        (["EURUSD"], "synthetisch"))
    monkeypatch.setattr(pipeline.agenten, "lauf", merke)

    pipeline.lauf(bericht_pfad=str(tmp_path / "dashboard.json"),
                  mit_agenten=True, mit_konferenz=False, mit_spider=False)

    assert gesehen["bericht"]["schema"] == 2


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


def test_h1_jahres_suffix_landet_in_h1_und_ueberschreibt_m15_nicht(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    h1 = synthetische_kerzen("EURUSD", kerzen=3, seed=4, timeframe_minuten=60)
    m15 = synthetische_kerzen("EURUSD", kerzen=3, seed=5)
    (ordner / "EURUSD_H1_2020.csv").write_text(_als_mt5(h1), encoding="utf-8")
    (ordner / "EURUSD_M15.csv").write_text(_als_mt5(m15), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")

    assert len(db.kerzen("EURUSD", "H1")) == 3
    assert len(db.kerzen("EURUSD", "M15")) == 3


def test_unbekannter_zeitrahmen_im_ordner_bricht_vor_dem_schreiben_ab(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    cfg._d["basis"]["richter_zeitrahmen"] = "H1"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    m15 = synthetische_kerzen("EURUSD", kerzen=3, seed=5)
    (ordner / "EURUSD_M15.csv").write_text(_als_mt5(m15), encoding="utf-8")
    (ordner / "EURUSD_M15_H4.csv").write_text(_als_mt5(m15), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler, match="Unbekannter Zeitrahmen.*H4"):
        sicherstellen_daten(cfg, db)

    assert db.kerzen("EURUSD", "M15") == []
    assert db.kerzen("EURUSD", "H1") == []
    assert any("Unbekannter Zeitrahmen" in zeile["text"]
               for zeile in db.ereignisse())


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


def test_kaputte_zweite_datei_laesst_keine_daten_oder_zustand(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    # Zweite Datei ist kaputt, nachdem die erste bereits in der Transaktion liegt.
    (ordner / "US500_M15.csv").write_text(
        KOPF + "2025.01.02\t09:00:00\tkaputt\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )
    db = Facts(cfg.db_pfad)
    db.zustand_setzen("datenquelle", "datenbank")

    with pytest.raises(DatenFehler, match="US500_M15.csv"):
        sicherstellen_daten(cfg, db)

    assert db.symbole() == []
    assert db.kerzen("EURUSD", "M15") == []
    assert db.kerzen("US500", "M15") == []
    assert db.zustand("datenquelle") == "datenbank"
    assert not any("Kerzen importiert" in zeile["text"] for zeile in db.ereignisse())


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


def test_ordner_import_ist_idempotent_mit_pruefsumme(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        _als_mt5(_frische_m15()), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.datenimporte()) == 1
    assert len(db.kerzen("EURUSD", "M15")) == 1300

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.datenimporte()) == 1
    assert len(db.kerzen("EURUSD", "M15")) == 1300
    assert sum("EURUSD_M15.csv: 1300 Kerzen importiert" in zeile["text"]
               for zeile in db.ereignisse()) == 1


def test_ordner_import_erkennt_geaenderte_pruefsumme(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    df = _frische_m15()
    datei = ordner / "EURUSD_M15.csv"
    datei.write_text(_als_mt5(df), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    df.loc[10, "volume"] += 1
    datei.write_text(_als_mt5(df), encoding="utf-8")

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.datenimporte()) == 2
    assert len(db.kerzen("EURUSD", "M15")) == 1300


def test_direkter_und_ordner_import_teilen_die_pruefsumme(cfg, capsys):
    import argparse

    from orakel.__main__ import _importiere_csv

    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / "EURUSD_M15.csv"
    datei.write_text(_als_mt5(_frische_m15()), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.datenimporte()) == 1

    args = argparse.Namespace(
        csv=[str(datei)], symbol=None, zeitrahmen=None,
        server_zeitzone=None, server_versatz=None,
        server_versatz_stunden=None, frisch=False, max_alter_stunden=None)
    assert _importiere_csv(cfg, db, args) == 0

    assert len(db.datenimporte()) == 1
    assert "bereits importiert" in capsys.readouterr().out


def test_ordner_import_frische_gate_lehnt_alte_datei_ab(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    alt = synthetische_kerzen("EURUSD", kerzen=1300, seed=17, start="2024-01-01")
    (ordner / "EURUSD_M15.csv").write_text(_als_mt5(alt), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler, match="Daten veraltet"):
        sicherstellen_daten(cfg, db, frisch=True)

    assert db.kerzen("EURUSD", "M15") == []
    assert db.datenimporte() == []
    assert db.zustand("datenquelle") is None


def test_ordner_gate_nutzt_zusammengefuehrte_reihe_trotz_altem_duplikat(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    alt = synthetische_kerzen("EURUSD", kerzen=1300, seed=19, start="2024-01-01")
    alt_datei = ordner / "EURUSD_M15_2024.csv"
    alt_datei.write_text(_als_mt5(alt), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    # Der alte Block ist bereits importiert und steht als Duplikat im Ordner.
    assert sicherstellen_daten(cfg, db) == (["EURUSD"], "csv")
    assert len(db.datenimporte()) == 1
    assert len(db.kerzen("EURUSD", "M15")) == 1300

    frisch = _frische_m15("EURUSD")
    (ordner / "EURUSD_M15_2025.csv").write_text(_als_mt5(frisch), encoding="utf-8")

    # Die frische Datei muss trotz des alten Duplikats importiert werden; das
    # Gate entscheidet über die zusammengeführte Reihe, nicht über den Altblock.
    assert sicherstellen_daten(cfg, db, frisch=True) == (["EURUSD"], "csv")
    assert len(db.datenimporte()) == 2
    assert len(db.kerzen("EURUSD", "M15")) == 2600
    assert (db.juengste_kerze("EURUSD", "M15")[:19]
            == str(frisch["ts"].iloc[-1])[:19])


def test_ordner_import_gate_rollt_alle_dateien_gemeinsam_zurueck(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        _als_mt5(_frische_m15("EURUSD")), encoding="utf-8")
    alt = synthetische_kerzen("US500", kerzen=1300, seed=18, start="2024-01-01")
    (ordner / "US500_M15.csv").write_text(_als_mt5(alt), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler, match="Daten veraltet"):
        sicherstellen_daten(cfg, db, frisch=True)

    assert db.symbole() == []
    assert db.kerzen("EURUSD", "M15") == []
    assert db.kerzen("US500", "M15") == []
    assert db.datenimporte() == []
    assert db.zustand("datenquelle") is None


def test_ordner_import_max_alter_stunden_ueberschreibt_grenze(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "EURUSD_M15.csv").write_text(
        _als_mt5(_frische_m15(alter_stunden=1.0)), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    with pytest.raises(DatenFehler, match="Daten veraltet"):
        sicherstellen_daten(cfg, db, max_alter_stunden=0.5)

    assert db.kerzen("EURUSD", "M15") == []
    assert db.datenimporte() == []


def test_ordner_warnung_nutzt_die_frischegrenze_aus_der_option(cfg):
    cfg._d["basis"]["datenquelle"] = "csv"
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    ende = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=100)
    start = ende - pd.Timedelta(minutes=15 * 1299)
    alt = synthetische_kerzen("EURUSD", kerzen=1300, seed=21,
                              start=start.isoformat())
    (ordner / "EURUSD_M15.csv").write_text(_als_mt5(alt), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    # Die Konfiguration erlaubt nur vier Stunden; die Option hebt die Grenze
    # bewusst an. Dann darf auch die Warnung nach dem Import nicht anschlagen.
    assert sicherstellen_daten(cfg, db, max_alter_stunden=1000) == (
        ["EURUSD"], "csv")
    assert not any("jüngste Kerze" in zeile["text"] for zeile in db.ereignisse())


def test_pruefen_gibt_frischeoptionen_an_die_pipeline(monkeypatch):
    from orakel import __main__ as cli

    gesehen: dict[str, object] = {}

    def fake_pipeline(**kwargs):
        gesehen.update(kwargs)
        return {"modus": "backtest", "datenquelle": "csv",
                "validierungen": [], "auswahl": [], "plan": [],
                "dauer_sekunden": 0}

    monkeypatch.setattr(cli, "_cfg", lambda _pfad: object())
    monkeypatch.setattr(cli, "_schema_pruefen", lambda _cfg: None)
    monkeypatch.setattr(cli, "_pipeline_lauf", fake_pipeline)

    assert cli.main(["pruefen", "--frisch", "--max-alter-stunden", "6"]) == 0
    assert gesehen["frisch"] is True
    assert gesehen["max_alter_stunden"] == 6.0


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


def test_plan_stop_kommt_aus_dem_signalplan(cfg):
    grenzen = RisikoGrenzen.aus_config(cfg)
    plan = Signalplan(np.array([0.0, 1.0]), np.array([np.nan, 95.0]), True)

    stop, quelle = _stop_fuer_plan(plan, kurs=100.0, atr_wert=2.0, grenzen=grenzen)

    assert stop == pytest.approx(95.0)
    assert quelle == "Signalplan"


def test_plan_stop_faellt_ohne_gueltigen_planstop_auf_atr_zurueck(cfg):
    grenzen = RisikoGrenzen.aus_config(cfg)
    kandidaten = [
        np.array([0.0, 1.0]),                                   # Array ohne Stop
        Signalplan(np.array([1.0]), np.array([np.nan]), True),  # kein Stop gesetzt
        Signalplan(np.array([1.0]), np.array([101.0]), True),   # Stop nicht unter dem Kurs
    ]

    for signale in kandidaten:
        stop, quelle = _stop_fuer_plan(signale, kurs=100.0, atr_wert=2.0, grenzen=grenzen)
        assert stop == pytest.approx(96.0)
        assert quelle == "2.0 × ATR"

    stop, quelle = _stop_fuer_plan(np.array([1.0]), kurs=100.0, atr_wert=0.0,
                                   grenzen=grenzen)
    assert stop == 0.0
