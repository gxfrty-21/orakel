from __future__ import annotations

import argparse

import pandas as pd
import pytest

from orakel import __main__ as cli
from orakel.__main__ import _importiere_csv, _versatz
from orakel.kern.data import (
    df_aus_db,
    frische_grenze_stunden,
    lade_csv,
    lade_csv_bloecke,
    pruefe_daten,
    synthetische_kerzen,
    zerlege_dateiname,
)
from orakel.kern.db import Facts


def _args(**kwargs) -> argparse.Namespace:
    werte = {"symbol": None, "zeitrahmen": None, "server_zeitzone": None,
             "server_versatz": None, "server_versatz_stunden": None}
    werte.update(kwargs)
    return argparse.Namespace(**werte)


def _als_mt5(df: pd.DataFrame) -> str:
    """Schreibt eine Reihe im MT5-Tabformat mit getrenntem Datum und Zeit."""
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for r in df.itertuples(index=False):
        zeilen.append(
            f"{r.ts:%Y.%m.%d}\t{r.ts:%H:%M:%S}\t{r.open}\t{r.high}\t{r.low}\t{r.close}"
            f"\t{int(r.volume)}\t0\t2"
        )
    return "\n".join(zeilen) + "\n"


def test_erkennt_doppelte_und_unmoegliche_kerzen(cfg):
    df = synthetische_kerzen("X", kerzen=600, seed=1)
    df.loc[10, "high"] = df.loc[10, "low"] - 5  # Hoch unter Tief
    doppelt = pd.concat([df, df.iloc[[20]]], ignore_index=True)
    q = pruefe_daten(doppelt, "X", cfg)
    assert not q.ok
    assert any("Doppelte" in f for f in q.fehler)
    assert any("unmöglichem" in f for f in q.fehler)


def test_zu_wenig_kerzen_ist_ein_fehler(cfg):
    df = synthetische_kerzen("X", kerzen=50, seed=1)
    q = pruefe_daten(df, "X", cfg)
    assert not q.ok
    assert any("mindestens" in f for f in q.fehler)


def test_gesunde_daten_sind_ok(cfg):
    df = synthetische_kerzen("X", kerzen=2000, seed=2)
    q = pruefe_daten(df, "X", cfg)
    assert q.ok, q.fehler
    assert q.kerzen == 2000


def test_veraltete_reihe_warnt_ohne_fehler(cfg):
    df = synthetische_kerzen("X", kerzen=2000, seed=2)
    jetzt = pd.Timestamp(df["ts"].iloc[-1]) + pd.Timedelta(days=6)

    q = pruefe_daten(df, "X", cfg, jetzt=jetzt)

    assert q.ok, q.fehler
    assert any("Jüngste Kerze" in w for w in q.warnungen), q.warnungen


def test_haeufigster_abstand_muss_zum_zeitrahmen_passen(cfg):
    # H1-Takt, aber als M15 deklariert: der häufigste Abstand ist 60 statt 15 Min.
    h1 = synthetische_kerzen("X", kerzen=1300, seed=2, timeframe_minuten=60)
    q = pruefe_daten(h1, "X", cfg, timeframe="M15")
    assert not q.ok
    assert any("Häufigster Abstand" in f and "M15" in f for f in q.fehler), q.fehler

    # Umgekehrt ebenso: M15-Takt als H1 abgelegt (das war der stille Fehler).
    m15 = synthetische_kerzen("X", kerzen=1300, seed=2)
    q = pruefe_daten(m15, "X", cfg, timeframe="H1")
    assert not q.ok
    assert any("Häufigster Abstand" in f for f in q.fehler)

    # M1 bleibt als M1 in Ordnung (die Mindestzahl ist hier 1500 auf M1-Basis).
    m1 = synthetische_kerzen("X", kerzen=1800, seed=2, timeframe_minuten=1)
    assert pruefe_daten(m1, "X", cfg, timeframe="M1").ok


def test_zwischenraster_werden_erkannt(cfg):
    # 20- und 45-Minuten-Raster lagen innerhalb der alten Median-Toleranz.
    m20 = synthetische_kerzen("X", kerzen=400, seed=2, timeframe_minuten=20)
    q = pruefe_daten(m20, "X", cfg, timeframe="M15")
    assert not q.ok
    assert any("Häufigster Abstand 20 Min" in f for f in q.fehler), q.fehler

    m45 = synthetische_kerzen("X", kerzen=300, seed=2, timeframe_minuten=45)
    q = pruefe_daten(m45, "X", cfg, timeframe="H1")
    assert not q.ok
    assert any("Häufigster Abstand 45 Min" in f for f in q.fehler), q.fehler


def test_duenn_besetzter_m15_export_bleibt_gueltig(cfg):
    # Jede fünfte Kerze fehlt: der häufigste Abstand bleibt 15 Min, die Reihe
    # ist also M15 und nicht etwa M30.
    df = synthetische_kerzen("X", kerzen=500, seed=2)
    df = df.drop(df.index[4::5]).reset_index(drop=True)

    q = pruefe_daten(df, "X", cfg)

    assert q.ok, q.fehler


def test_kurze_reihe_meldet_keinen_falschen_zeitrahmen(cfg):
    # Zwei Kerzen über ein Wochenende: zu kurz für ein Takturteil, daher nur
    # der Mindestkerzen-Fehler und keine erfundene Zeitrahmen-Meldung.
    df = pd.DataFrame({
        "ts": pd.to_datetime(["2024-01-05 23:45", "2024-01-08 00:00"], utc=True),
        "open": [1.0, 1.0], "high": [1.1, 1.1], "low": [0.9, 0.9],
        "close": [1.05, 1.05], "volume": [10.0, 10.0],
    })

    q = pruefe_daten(df, "X", cfg)

    assert not q.ok
    assert any("mindestens" in f for f in q.fehler)
    assert not any("Häufigster Abstand" in f for f in q.fehler), q.fehler


def test_mindestkerzen_folgen_dem_zeitrahmen(cfg):
    # 1200 M15-Kerzen sind zwei Wochen; im H1-Raster wären das 50 Tage.
    cfg._d["daten"]["min_kerzen"] = 1200

    h1 = synthetische_kerzen("X", kerzen=400, seed=2, timeframe_minuten=60)
    q = pruefe_daten(h1, "X", cfg, timeframe="H1")
    assert q.ok, q.fehler  # 400 H1-Kerzen ≈ 16 Tage reichen

    kurz = synthetische_kerzen("X", kerzen=250, seed=2, timeframe_minuten=60)
    q = pruefe_daten(kurz, "X", cfg, timeframe="H1")
    assert not q.ok
    assert any("mindestens 300" in f for f in q.fehler), q.fehler

    # M15 behält die Basis: 400 M15-Kerzen sind weiterhin zu wenig.
    m15 = synthetische_kerzen("X", kerzen=400, seed=2)
    assert not pruefe_daten(m15, "X", cfg).ok


def test_falsch_getaktete_datei_wird_vor_dem_schreiben_abgelehnt(cfg, tmp_path):
    # H1-Takt unter M15-Dateinamen: die Zeilen dürfen gar nicht erst in die
    # Tabelle gehen, statt erst nach dem Import als Median-Fehler aufzufallen.
    h1 = synthetische_kerzen("X", kerzen=200, seed=2, timeframe_minuten=60)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(h1), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert _importiere_csv(cfg, db, _args(csv=[str(p)])) == 1

    assert db.kerzen("EURUSD", "M15") == []
    assert any("Häufigster Abstand" in zeile["text"] and "EURUSD_M15.csv" in zeile["text"]
               for zeile in db.ereignisse())


def test_jahresabdeckung_zaehlt_kerzen_je_jahr(cfg):
    df = synthetische_kerzen("X", kerzen=2000, seed=2)
    q = pruefe_daten(df, "X", cfg)

    assert q.jahre == {2024: 2000}
    assert not any("Keine Kerzen in" in w for w in q.warnungen), q.warnungen


def test_jahresabdeckung_steht_im_datenqualitaetsblock(cfg):
    anfang = synthetische_kerzen("X", kerzen=1200, seed=2, start="2023-01-01")
    spaeter = synthetische_kerzen("X", kerzen=1200, seed=3, start="2025-01-01")
    df = pd.concat([anfang, spaeter], ignore_index=True)

    block = pruefe_daten(df, "X", cfg).als_dict()

    assert block["jahre"] == {2023: 1200, 2025: 1200}
    assert any("Keine Kerzen in 2024" in w for w in block["warnungen"]), block["warnungen"]


def test_fehlendes_jahr_wird_als_warnung_gemeldet(cfg):
    # 2023 und 2025 belegt, 2024 fehlt vollständig — der Fall einer
    # abgeschnittenen Broker-Historie nach einem mehrjährigen Import.
    anfang = synthetische_kerzen("X", kerzen=1200, seed=2, start="2023-01-01")
    spaeter = synthetische_kerzen("X", kerzen=1200, seed=3, start="2025-01-01")
    df = pd.concat([anfang, spaeter], ignore_index=True)

    q = pruefe_daten(df, "X", cfg)

    assert q.jahre == {2023: 1200, 2025: 1200}
    assert any("Keine Kerzen in 2024" in w for w in q.warnungen), q.warnungen
    # Eine Lücke macht die Reihe nicht unbrauchbar; der Import bleibt erfolgreich.
    assert q.ok, q.fehler


def test_median_abstand_ignoriert_wochenende_und_handelspausen(cfg):
    df = synthetische_kerzen("X", kerzen=2000, seed=2)
    # Zwei Handelstage am Stück fehlen (Wochenende): nur ein langer Abstand,
    # der Median bleibt beim M15-Raster.
    luecke = df["ts"].iloc[500]
    df = df[~((df["ts"] >= luecke) & (df["ts"] < luecke + pd.Timedelta(days=2)))].reset_index(
        drop=True)
    q = pruefe_daten(df, "X", cfg)
    assert q.ok, q.fehler
    assert not any("Häufigster Abstand" in f for f in q.fehler)


def test_mt5_csv_mit_getrenntem_datum_und_zeit(tmp_path):
    # Format des MT5-Exports: <DATE> <TIME> <OPEN> ..., Datum als YYYY.MM.DD.
    inhalt = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2024.12.31\t23:45:00\t1.03500\t1.03600\t1.03400\t1.03550\t120\t0\t2\n"
        # gemischte Genauigkeit: mit und ohne Sekunden in derselben Datei
        "2025.01.02\t09:00\t1.03500\t1.03600\t1.03400\t1.03550\t120\t0\t2\n"
        "2025.01.02\t09:15:00\t1.03550\t1.03700\t1.03500\t1.03650\t140\t0\t2\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    df = lade_csv(p)
    assert len(df) == 3
    # YYYY.MM.DD wird nicht als Tag/Monat vertauscht (31. Dezember bleibt Dezember).
    assert df["ts"].iloc[0] == pd.Timestamp("2024-12-31 23:45", tz="UTC")
    assert df["ts"].iloc[1] == pd.Timestamp("2025-01-02 09:00", tz="UTC")
    assert df["close"].iloc[2] == 1.0365
    assert df["volume"].iloc[1] == 120


def test_server_zeitzone_wird_mit_sommerzeit_nach_utc_umgerechnet(tmp_path):
    # Europe/Athens: UTC+2 im Winter, UTC+3 im Sommer.
    inhalt = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
        "2025.07.01\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    df = lade_csv(p, server_zeitzone="Europe/Athens")
    assert df["ts"].iloc[0] == pd.Timestamp("2025-01-02 07:00", tz="UTC")
    assert df["ts"].iloc[1] == pd.Timestamp("2025-07-01 06:00", tz="UTC")


def test_fester_broker_versatz_verschiebt_serverzeit_nach_utc(tmp_path):
    # Fester Versatz: derselbe Offset im Winter und im Sommer, keine Sommerzeit.
    inhalt = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
        "2025.07.01\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    df = lade_csv(p, server_versatz_stunden=3)
    assert [str(t) for t in df["ts"]] == [
        "2025-01-02 06:00:00+00:00", "2025-07-01 06:00:00+00:00",
    ]
    assert lade_csv(p, server_versatz_stunden=-5)["ts"].iloc[0] == pd.Timestamp(
        "2025-01-02 14:00", tz="UTC")
    # Auch der blockweise Import verschiebt identisch.
    bloecke = list(lade_csv_bloecke(p, server_versatz_stunden=3))
    assert bloecke[0]["ts"].iloc[0] == pd.Timestamp("2025-01-02 06:00", tz="UTC")


def test_zeitzone_und_fester_versatz_schliessen_sich_aus(tmp_path):
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schliessen sich aus"):
        lade_csv(p, server_zeitzone="Europe/Athens", server_versatz_stunden=2)


def test_herbst_umstellung_behaelt_beide_stunden(tmp_path):
    # Europe/Athens am 26.10.2025: 04:00 Sommerzeit wird zu 03:00 Standardzeit,
    # die Stunde 03:00–03:59 kommt also zweimal vor.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit in ("02:45:00", "03:00:00", "03:15:00", "03:00:00", "03:15:00", "04:00:00"):
        zeilen.append(f"2025.10.26\t{zeit}\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    df = lade_csv(p, server_zeitzone="Europe/Athens")
    # Erste Fassung = Sommerzeit (+3), zweite Fassung = Standardzeit (+2).
    assert [str(t) for t in df["ts"]] == [
        "2025-10-25 23:45:00+00:00",
        "2025-10-26 00:00:00+00:00",
        "2025-10-26 00:15:00+00:00",
        "2025-10-26 01:00:00+00:00",
        "2025-10-26 01:15:00+00:00",
        "2025-10-26 02:00:00+00:00",
    ]
    assert len(df) == 6  # keine der beiden Stunden fällt als Dublette weg


def test_herbst_umstellung_bei_gemischter_reihenfolge(tmp_path):
    # Die beiden Fassungen wechseln sich je Viertelstunde ab, statt blockweise
    # zu stehen; die Richtung bleibt trotzdem aufsteigend.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit in ("03:00:00", "03:00:00", "03:15:00", "03:15:00"):
        zeilen.append(f"2025.10.26\t{zeit}\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    df = lade_csv(p, server_zeitzone="Europe/Athens")

    # Erste Fassung je Uhrzeit = Sommerzeit (+3), zweite = Standardzeit (+2).
    assert [str(t) for t in df["ts"]] == [
        "2025-10-26 00:00:00+00:00",
        "2025-10-26 00:15:00+00:00",
        "2025-10-26 01:00:00+00:00",
        "2025-10-26 01:15:00+00:00",
    ]


def test_herbst_umstellung_in_absteigender_datei(tmp_path):
    # Dieselbe Rückstellung, aber absteigend exportiert: Die Standardzeitfassung
    # steht zuerst in der Datei, die Sommerzeitfassung folgt später. Jede Zeile
    # hat einen eigenen Preis, damit eine vertauschte Fassungs-Zuordnung auffällt.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit, preis in (
        ("04:00:00", "1.40"),
        ("03:15:00", "1.35"),  # Standardzeit
        ("03:00:00", "1.30"),  # Standardzeit
        ("03:15:00", "1.25"),  # Sommerzeit
        ("03:00:00", "1.20"),  # Sommerzeit
        ("02:45:00", "1.15"),
    ):
        zeilen.append(f"2025.10.26\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    df = lade_csv(p, server_zeitzone="Europe/Athens")

    # Der Preis bleibt an seiner Fassung: 03:00 Sommerzeit → 00:00 UTC (1.20),
    # 03:00 Standardzeit → 01:00 UTC (1.30) usw. Eine Drehung der Zuordnung
    # würde hier 1.30 und 1.20 vertauschen.
    assert [(str(t), float(c)) for t, c in zip(df["ts"], df["close"])] == [
        ("2025-10-25 23:45:00+00:00", 1.15),
        ("2025-10-26 00:00:00+00:00", 1.20),
        ("2025-10-26 00:15:00+00:00", 1.25),
        ("2025-10-26 01:00:00+00:00", 1.30),
        ("2025-10-26 01:15:00+00:00", 1.35),
        ("2025-10-26 02:00:00+00:00", 1.40),
    ]


def test_herbstpaar_ohne_exportrichtung_gilt_als_aufsteigend(tmp_path):
    # Nur die beiden Fassungen derselben Uhrzeit: Erster und letzter Zeitstempel
    # sind gleich, eine Exportrichtung ist nicht erkennbar. Der Import nimmt
    # deshalb aufsteigend an: Sommerzeit zuerst, Standardzeit danach.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for preis in ("1.20", "1.30"):
        zeilen.append(f"2025.10.26\t03:00:00\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    df = lade_csv(p, server_zeitzone="Europe/Athens")

    assert [(str(t), float(c)) for t, c in zip(df["ts"], df["close"])] == [
        ("2025-10-26 00:00:00+00:00", 1.20),
        ("2025-10-26 01:00:00+00:00", 1.30),
    ]


def test_sommerzeitluecke_meldet_deutschen_fehler(tmp_path):
    # Europe/Athens springt am 30.03.2025 von 03:00 auf 04:00; 03:15 existiert
    # dort nicht und darf nicht mit einer englischen pandas-Meldung abbrechen.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit in ("02:45:00", "03:15:00", "04:00:00"):
        zeilen.append(f"2025.03.30\t{zeit}\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError) as fehler:
        lade_csv(p, server_zeitzone="Europe/Athens")

    text = str(fehler.value)
    assert "Sommerzeitlücke" in text
    assert "Europe/Athens" in text
    assert "2025-03-30 03:15:00" in text
    assert "server_zeitzone" in text
    assert "--server-versatz-stunden" in text
    assert "nonexistent time" not in text


def _herbst_datei(pfad):
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit in ("02:45:00", "03:00:00", "03:15:00", "03:00:00", "03:15:00", "04:00:00"):
        zeilen.append(f"2025.10.26\t{zeit}\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    pfad.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def test_bloecke_zerteilen_die_herbststunde_nicht(tmp_path):
    p = tmp_path / "EURUSD_M15.csv"
    _herbst_datei(p)

    bloecke = list(lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=4))

    # Der Tageswechsel bestimmt die Blockgrenze: trotz block=4 ein Block, sechs
    # getrennte UTC-Zeitstempel.
    assert len(bloecke) == 1
    assert [str(t) for t in bloecke[0]["ts"]] == [
        "2025-10-25 23:45:00+00:00", "2025-10-26 00:00:00+00:00",
        "2025-10-26 00:15:00+00:00", "2025-10-26 01:00:00+00:00",
        "2025-10-26 01:15:00+00:00", "2025-10-26 02:00:00+00:00",
    ]


def test_aufsteigende_tage_bleiben_blockweise_zusammen(tmp_path):
    # Drei aufsteigend exportierte Tage; block=3 zwingt Chunks mitten in die
    # Tage. Die Tagesgrenze muss den Herbsttag trotzdem zusammenhalten.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for tag, zeit, preis in (
        ("2025.10.25", "09:00:00", "1.10"),
        ("2025.10.25", "09:15:00", "1.11"),
        ("2025.10.26", "03:00:00", "1.20"),
        ("2025.10.26", "03:15:00", "1.25"),
        ("2025.10.26", "03:00:00", "1.30"),
        ("2025.10.26", "03:15:00", "1.35"),
        ("2025.10.27", "09:00:00", "1.40"),
        ("2025.10.27", "09:15:00", "1.41"),
    ):
        zeilen.append(f"{tag}\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    bloecke = list(lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=3))

    assert [len(b) for b in bloecke] == [2, 4, 2]
    assert [(str(t), float(c)) for t, c in zip(bloecke[1]["ts"], bloecke[1]["close"])] == [
        ("2025-10-26 00:00:00+00:00", 1.20),
        ("2025-10-26 00:15:00+00:00", 1.25),
        ("2025-10-26 01:00:00+00:00", 1.30),
        ("2025-10-26 01:15:00+00:00", 1.35),
    ]
    assert [str(t) for t in bloecke[0]["ts"]] == [
        "2025-10-25 06:00:00+00:00", "2025-10-25 06:15:00+00:00",
    ]
    assert [str(t) for t in bloecke[2]["ts"]] == [
        "2025-10-27 07:00:00+00:00", "2025-10-27 07:15:00+00:00",
    ]


def test_iso_tage_ohne_nullauffuellung_werden_als_ein_tag_erkannt(tmp_path):
    # Gültige ISO-Zeitstempel ohne führende Nullen: Die Tagesprüfung darf nicht
    # die ersten zehn Zeichen vergleichen, sonst wird derselbe Tag je nach
    # Stunde zerteilt.
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(
        "datetime,open,high,low,close,volume\n"
        "2025-1-2 09:00:00,1,1,1,1,1\n"
        "2025-1-2 10:00:00,1,1,1,1,1\n"
        "2025-1-3 09:00:00,1,1,1,1,1\n"
        "2025-1-3 10:00:00,1,1,1,1,1\n",
        encoding="utf-8",
    )

    bloecke = list(lade_csv_bloecke(p, block=2))

    assert [len(b) for b in bloecke] == [2, 2]
    assert [str(t) for t in bloecke[0]["ts"]] == [
        "2025-01-02 09:00:00+00:00", "2025-01-02 10:00:00+00:00",
    ]
    assert [str(t) for t in bloecke[1]["ts"]] == [
        "2025-01-03 09:00:00+00:00", "2025-01-03 10:00:00+00:00",
    ]


def test_absteigende_tage_bleiben_blockweise_zusammen(tmp_path):
    # Zwei absteigend exportierte Tage; die Blockgrenze darf den Herbsttag nicht
    # zerteilen, sonst würde eine der beiden 03:00-Fassungen falsch umgerechnet.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit, preis in (
        ("04:00:00", "1.40"), ("03:15:00", "1.35"), ("03:00:00", "1.30"),
        ("03:15:00", "1.25"), ("03:00:00", "1.20"), ("02:45:00", "1.15"),
    ):
        zeilen.append(f"2025.10.26\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    for zeit in ("09:15:00", "09:00:00"):
        zeilen.append(f"2025.10.25\t{zeit}\t1.0\t1.0\t1.0\t1.0\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    bloecke = list(lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=4))

    assert [len(b) for b in bloecke] == [6, 2]
    assert [str(t) for t in bloecke[0]["ts"]] == [
        "2025-10-25 23:45:00+00:00", "2025-10-26 00:00:00+00:00",
        "2025-10-26 00:15:00+00:00", "2025-10-26 01:00:00+00:00",
        "2025-10-26 01:15:00+00:00", "2025-10-26 02:00:00+00:00",
    ]
    assert [str(t) for t in bloecke[1]["ts"]] == [
        "2025-10-25 06:00:00+00:00", "2025-10-25 06:15:00+00:00",
    ]


def test_absteigende_herbststunde_bleibt_je_tagesblock_zugeordnet(tmp_path):
    # Drei absteigend exportierte Tage; block=4 erzwingt Chunks, die mitten im
    # Herbsttag beginnen. lade_csv_bloecke muss trotzdem je Tag einen Block
    # liefern und beide 03:00-Fassungen samt Preis zusammenhalten.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit, preis in (("09:15:00", "1.07"), ("09:00:00", "1.06")):
        zeilen.append(f"2025.10.27\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    for zeit, preis in (
        ("04:00:00", "1.40"), ("03:15:00", "1.35"), ("03:00:00", "1.30"),
        ("03:15:00", "1.25"), ("03:00:00", "1.20"), ("02:45:00", "1.15"),
    ):
        zeilen.append(f"2025.10.26\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    for zeit, preis in (("09:15:00", "1.05"), ("09:00:00", "1.04")):
        zeilen.append(f"2025.10.25\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    bloecke = list(lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=4))

    # Ein Block je Tag, obwohl die Roh-Chunks mitten im Herbsttag wechseln.
    assert [len(b) for b in bloecke] == [2, 6, 2]
    # Der Herbstblock enthält beide 03:00-Fassungen: Sommerzeit → 00:00 UTC
    # (1.20), Standardzeit → 01:00 UTC (1.30). Eine Drehung würde die Preise
    # vertauschen, ohne die Zahl der Zeitstempel zu verändern.
    assert [(str(t), float(c)) for t, c in zip(bloecke[1]["ts"], bloecke[1]["close"])] == [
        ("2025-10-25 23:45:00+00:00", 1.15),
        ("2025-10-26 00:00:00+00:00", 1.20),
        ("2025-10-26 00:15:00+00:00", 1.25),
        ("2025-10-26 01:00:00+00:00", 1.30),
        ("2025-10-26 01:15:00+00:00", 1.35),
        ("2025-10-26 02:00:00+00:00", 1.40),
    ]
    assert [str(t) for t in bloecke[0]["ts"]] == [
        "2025-10-27 07:00:00+00:00", "2025-10-27 07:15:00+00:00",
    ]
    assert [str(t) for t in bloecke[2]["ts"]] == [
        "2025-10-25 06:00:00+00:00", "2025-10-25 06:15:00+00:00",
    ]


def test_gemischte_zeilen_innerhalb_eines_tages_brechen_ab(tmp_path):
    # Derselbe Tag, aber die Uhrzeiten stehen nicht chronologisch. Der Import
    # darf das nicht still sortieren, weil die Reihenfolge bei der Herbst-
    # Rückstellung über die Sommer-/Standardzeitfassung entscheidet.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit in ("09:15:00", "09:00:00", "09:30:00"):
        zeilen.append(f"2025.01.02\t{zeit}\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="innerhalb des Tages nicht aufsteigend sortiert"):
        list(lade_csv_bloecke(p, block=2))


def test_gemischte_herbstzeilen_brechen_ab(tmp_path):
    # Zwei Umkehrungen an einem Herbsttag: Das ist keine gültige
    # Exportreihenfolge mehr und würde die Fassungen vertauschen.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit, preis in (
        ("03:00:00", "1.20"),
        ("03:15:00", "1.25"),
        ("02:45:00", "1.15"),
        ("03:00:00", "1.30"),
        ("03:15:00", "1.35"),
        ("04:00:00", "1.40"),
    ):
        zeilen.append(f"2025.10.26\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="innerhalb des Tages nicht aufsteigend sortiert"):
        list(lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=2))


def test_gemischte_tagesrichtungen_brechen_ab(tmp_path):
    # Drei Tage im selben Block: Tag 1 steigt auf, Tag 2 fällt ab. Die globale
    # Blockrichtung wäre aufsteigend; ohne Prüfung je Tageslauf würde Tag 2
    # mit der falschen Herbstrichtung gelesen.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for tag, zeit, preis in (
        ("2025.01.02", "09:00:00", "1.10"),
        ("2025.01.02", "09:15:00", "1.11"),
        ("2025.01.03", "09:15:00", "1.20"),
        ("2025.01.03", "09:00:00", "1.21"),
        ("2025.01.04", "09:00:00", "1.30"),
        ("2025.01.04", "09:15:00", "1.31"),
    ):
        zeilen.append(f"{tag}\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="gemischte Richtungen"):
        list(lade_csv_bloecke(p, block=100))


def test_gemischte_tagesrichtungen_am_herbsttag_brechen_ab(tmp_path):
    # Der Vortag fällt ab, der Herbsttag läuft aufsteigend. Unter der globalen
    # Abwärtsrichtung würde der Rücksprung am Herbsttag sonst als Sommerzeit
    # gelesen und die beiden 03:15-Preise würden vertauscht.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for tag, zeit, preis in (
        ("2025.10.27", "09:15:00", "1.07"),
        ("2025.10.27", "09:00:00", "1.06"),
        ("2025.10.26", "03:00:00", "1.20"),
        ("2025.10.26", "03:15:00", "1.25"),
        ("2025.10.26", "03:15:00", "1.30"),
        ("2025.10.25", "09:15:00", "1.05"),
        ("2025.10.25", "09:00:00", "1.04"),
    ):
        zeilen.append(f"{tag}\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="gemischte Richtungen"):
        list(lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=100))


def test_verschraenkte_tage_brechen_ab_statt_herbststunden_zu_trennen(cfg, tmp_path):
    # Der Herbsttag ist mit einem anderen Tag verschränkt. Blockweises Lesen
    # würde die beiden 03:00-Fassungen trennen; der Import muss stattdessen
    # abbrechen und die Transaktion zurückrollen.
    db = Facts(cfg.db_pfad)
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for tag, zeit, preis in (
        ("2025.10.26", "03:00:00", "1.20"),  # Sommerzeitfassung
        ("2025.10.26", "03:15:00", "1.25"),
        ("2025.10.25", "09:00:00", "1.10"),
        ("2025.10.25", "09:15:00", "1.11"),
        ("2025.10.26", "03:00:00", "1.30"),  # Standardzeitfassung
        ("2025.10.26", "03:15:00", "1.35"),
        ("2025.10.25", "09:30:00", "1.12"),
        ("2025.10.25", "09:45:00", "1.13"),
    ):
        zeilen.append(f"{tag}\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="2025.10.26.*mehreren"):
        db.kerzen_speichern_bloecke(
            "EURUSD", "M15",
            lade_csv_bloecke(p, server_zeitzone="Europe/Athens", block=4))

    assert db.kerzen("EURUSD", "M15") == []


def test_fehlzeile_im_zweiten_block_rollt_die_datei_zurueck(cfg, tmp_path):
    db = Facts(cfg.db_pfad)
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for zeit in ("09:00:00", "09:15:00", "09:30:00"):
        zeilen.append(f"2025.01.02\t{zeit}\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    zeilen.append("2025.01.03\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2")
    zeilen.append("2025.01.03\t09:15:00\tkaputt\t1.1\t0.9\t1.05\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unlesbaren Preisen"):
        db.kerzen_speichern_bloecke("EURUSD", "M15", lade_csv_bloecke(p, block=3))

    # Der erste Block war schon geschrieben; die Transaktion nimmt ihn zurück.
    assert db.kerzen("EURUSD", "M15") == []


def test_unbekannte_zeitzone_wird_abgelehnt(tmp_path):
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(
        "date,open,high,low,close,volume\n2025-01-02 09:00:00,1,1,1,1,1\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="unbekannte Zeitzone"):
        lade_csv(p, server_zeitzone="Bogus/Zone")


def test_unlesbarer_zeitstempel_nennt_anzahl_und_zeile(tmp_path):
    inhalt = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t09:00:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
        "2025.01.02\t09:15:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
        "2025.01.02\t25:99:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    with pytest.raises(ValueError) as fehler:
        lade_csv(p)

    meldung = str(fehler.value)
    assert "1 Zeitstempel nicht lesbar" in meldung
    assert "2025.01.02 25:99:00" in meldung


def test_cli_speichert_serverzeit_als_utc(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1300, seed=5)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert _importiere_csv(cfg, db, _args(csv=[str(p)], server_zeitzone="Europe/Athens")) == 0
    # 2024-01-01 00:00 Ortszeit (Winter, +2) wird zu 2023-12-31 22:00 UTC.
    assert db.kerzen("EURUSD", "M15")[0]["ts"] == "2023-12-31 22:00:00+00:00"


def test_kurzform_server_versatz_wird_geparst():
    assert _versatz("+03:00") == 3.0
    assert _versatz("-05:30") == -5.5
    assert _versatz("-14:00") == -14.0
    assert _versatz("-00:00") == 0.0
    with pytest.raises(argparse.ArgumentTypeError):
        _versatz("3")
    with pytest.raises(argparse.ArgumentTypeError):
        _versatz("+14:30")
    with pytest.raises(argparse.ArgumentTypeError):
        _versatz("-14:30")
    with pytest.raises(argparse.ArgumentTypeError):
        _versatz("-05:60")


def test_cli_negative_kurzform_ohne_gleichheitszeichen(monkeypatch):
    # argparse würde -05:00 als Option lesen; die CLI muss den negativen Wert
    # direkt hinter --server-versatz akzeptieren. Die positive Form und die
    # Gleichheitsform dürfen weiter funktionieren.
    gesehen: list[float | None] = []

    def fake_daten(args: argparse.Namespace) -> int:
        gesehen.append(args.server_versatz)
        return 0

    monkeypatch.setattr(cli, "cmd_daten", fake_daten)

    assert cli.main(["daten", "--csv", "x.csv", "--server-versatz", "-05:00"]) == 0
    assert cli.main(["daten", "--csv", "x.csv", "--server-versatz", "+05:00"]) == 0
    assert cli.main(["daten", "--csv", "x.csv", "--server-versatz=-05:00"]) == 0
    assert gesehen == [-5.0, 5.0, -5.0]


def test_cli_versatzoptionen_schliessen_sich_im_parser_aus():
    # Die drei expliziten Angaben sind schon auf Parser-Ebene Alternativen;
    # das verhindert Seiteneffekte, bevor cmd_daten Config und DB anfasst.
    for argumente in (
        ["daten", "--csv", "x.csv", "--server-zeitzone", "Europe/Athens",
         "--server-versatz", "-05:00"],
        ["daten", "--csv", "x.csv", "--server-versatz", "-05:00",
         "--server-versatz-stunden", "3"],
    ):
        with pytest.raises(SystemExit) as fehler:
            cli.main(argumente)
        assert fehler.value.code == 2


def test_cli_kurzform_server_versatz_als_utc(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1300, seed=5)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    # Kurzform, Zonenangabe und Stundenform schliessen sich gegenseitig aus.
    assert _importiere_csv(cfg, db, _args(csv=[str(p)], server_zeitzone="Europe/Athens",
                                           server_versatz=3.0)) == 2
    assert _importiere_csv(cfg, db, _args(csv=[str(p)], server_versatz=3.0,
                                           server_versatz_stunden=3)) == 2
    assert db.kerzen("EURUSD", "M15") == []

    assert _importiere_csv(cfg, db, _args(csv=[str(p)], server_versatz=-5.5)) == 0
    # 2024-01-01 00:00 Serverzeit (UTC-5:30) wird zu 05:30 UTC.
    assert db.kerzen("EURUSD", "M15")[0]["ts"] == "2024-01-01 05:30:00+00:00"


def test_cli_speichert_festen_versatz_als_utc(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1300, seed=5)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    # Beide Angaben zusammen lehnt die CLI ab, bevor etwas importiert wird.
    assert _importiere_csv(cfg, db, _args(csv=[str(p)], server_zeitzone="Europe/Athens",
                                           server_versatz_stunden=2)) == 2
    assert db.kerzen("EURUSD", "M15") == []

    assert _importiere_csv(cfg, db, _args(csv=[str(p)], server_versatz_stunden=5)) == 0
    # 2024-01-01 00:00 Serverzeit (UTC+5) wird zu 2023-12-31 19:00 UTC.
    assert db.kerzen("EURUSD", "M15")[0]["ts"] == "2023-12-31 19:00:00+00:00"
    assert db.zustand("datenquelle") == "csv"


def test_cp1252_mit_deutschem_kopf(tmp_path):
    inhalt = (
        "Datum;Zeit;Eröffnung;Hoch;Tief;Schluss;Volumen\r\n"
        "2025.01.02;09:00;1.035;1.036;1.034;1.0355;10\r\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_bytes(inhalt.encode("cp1252"))

    df = lade_csv(p)
    assert len(df) == 1
    assert df["open"].iloc[0] == 1.035
    assert df["ts"].iloc[0] == pd.Timestamp("2025-01-02 09:00", tz="UTC")


def test_crlf_und_leere_spalte_werden_ignoriert(tmp_path):
    inhalt = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\t\r\n"
        "2025.01.02\t09:00\t1.0\t1.1\t0.9\t1.05\t10\t0\t2\t\r\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_bytes(inhalt.encode("utf-8"))

    df = lade_csv(p)
    assert len(df) == 1
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]


def test_gleicher_zeitpunkt_in_zwei_schreibweisen_ist_derselbe_stempel(tmp_path):
    punkt = tmp_path / "EURUSD_M15_a.csv"
    iso = tmp_path / "EURUSD_M15_b.csv"
    punkt.write_text(
        "date,time,open,high,low,close,volume\n2025.01.02,09:00:00,1,1,1,1,1\n", encoding="utf-8"
    )
    iso.write_text(
        "datetime,open,high,low,close,volume\n2025-01-02T09:00:00,1,1,1,1,1\n", encoding="utf-8"
    )

    # Dieselbe Kerze muss unter demselben Zeitstempel landen, sonst entstehen Dubletten.
    assert lade_csv(punkt)["ts"].iloc[0] == lade_csv(iso)["ts"].iloc[0]


def test_datum_ohne_uhrzeit_wird_abgelehnt(tmp_path):
    inhalt = "date,open,high,low,close,volume\n2025-01-02,100,101,99,100.5,10\n"
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    with pytest.raises(ValueError, match="Zeitstempel nicht lesbar"):
        lade_csv(p)


def test_dezimalkomma_wird_abgelehnt(tmp_path):
    inhalt = (
        "date;open;high;low;close;volume\n"
        "2025-01-02 09:00:00;1,035;1,036;1,034;1,0355;10\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    with pytest.raises(ValueError, match="unlesbaren Preisen"):
        lade_csv(p)


def test_dateiname_liefert_symbol_und_zeitrahmen():
    assert zerlege_dateiname("EURUSD_M15.csv") == ("EURUSD", "M15")
    assert zerlege_dateiname("US500_CASH_H1.csv") == ("US500_CASH", "H1")
    assert zerlege_dateiname("EURUSD.csv") == ("EURUSD", "M15")
    assert zerlege_dateiname("EURUSD_2024.csv") == ("EURUSD", "M15")
    assert zerlege_dateiname("EURUSD_H1_2020.csv") == ("EURUSD", "H1")
    assert zerlege_dateiname("US500_H1_2023.csv") == ("US500", "H1")


def test_dateiname_lehnt_unbekannten_zeitrahmen_ab():
    for name in ("EURUSD_H4.csv", "EURUSD_H4_2020.csv"):
        with pytest.raises(ValueError, match="H4"):
            zerlege_dateiname(name)


def test_frischegrenze_nutzt_zeitrahmenlimit_und_max_alter_tage(cfg):
    daten = cfg["daten"]
    assert frische_grenze_stunden(daten, "M15") == 120.0
    daten["max_kurs_alter_stunden_m15"] = 4.0
    assert frische_grenze_stunden(daten, "M15") == 4.0
    assert frische_grenze_stunden(daten, "H1") == 120.0


def test_zwei_bloecke_ergeben_eine_gepruefte_reihe(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1500, seed=3)
    a = tmp_path / "EURUSD_M15_a.csv"
    b = tmp_path / "EURUSD_M15_b.csv"
    a.write_text(_als_mt5(basis.iloc[:800]), encoding="utf-8")
    b.write_text(_als_mt5(basis.iloc[700:]), encoding="utf-8")
    db = Facts(cfg.db_pfad)
    args = _args(csv=[str(a), str(b)])

    assert _importiere_csv(cfg, db, args) == 0
    # 100 überlappende Kerzen werden zusammengeführt statt doppelt gespeichert.
    assert len(db.kerzen("EURUSD", "M15")) == 1500

    # Erneuter Import desselben Blocks ändert die Reihe nicht.
    assert _importiere_csv(cfg, db, _args(csv=[str(a)])) == 0
    assert len(db.kerzen("EURUSD", "M15")) == 1500

    df = df_aus_db(db.kerzen("EURUSD", "M15"))
    q = pruefe_daten(df, "EURUSD", cfg)
    assert q.ok, q.fehler
    assert q.von == "2024-01-01 00:00:00"


def test_abweichende_ueberschneidung_wird_gemeldet(cfg, tmp_path, capsys):
    basis = synthetische_kerzen("X", kerzen=1300, seed=4)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert _importiere_csv(cfg, db, _args(csv=[str(p)])) == 0
    assert "abweichende Kerzen" not in capsys.readouterr().out

    # Gleicher Zeitstempel, anderes OHLC: gültige Kerze, aber ein neuer Export.
    geaendert = basis.copy()
    for spalte in ("open", "high", "low", "close"):
        geaendert.loc[700, spalte] += 0.01
    p.write_text(_als_mt5(geaendert), encoding="utf-8")

    assert _importiere_csv(cfg, db, _args(csv=[str(p)])) == 0
    ausgabe = capsys.readouterr().out
    assert "Warnung: abweichende Kerzen: 1" in ausgabe
    assert str(basis["ts"].iloc[700]) in ausgabe
    # Ersetzt wird weiterhin, aber nicht mehr still.
    gespeichert = {str(r["ts"]): r for r in db.kerzen("EURUSD", "M15")}
    assert float(gespeichert[str(basis["ts"].iloc[700])]["close"]) == pytest.approx(
        float(geaendert["close"].iloc[700]))
    assert any("abweichende Kerzen ersetzt" in e["text"] for e in db.ereignisse())


def test_cli_zeigt_die_jahresabdeckung(cfg, tmp_path, capsys):
    anfang = synthetische_kerzen("X", kerzen=1200, seed=2, start="2023-01-01")
    spaeter = synthetische_kerzen("X", kerzen=1200, seed=3, start="2025-01-01")
    df = pd.concat([anfang, spaeter], ignore_index=True)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(df), encoding="utf-8")

    assert _importiere_csv(cfg, Facts(cfg.db_pfad), _args(csv=[str(p)])) == 0

    ausgabe = capsys.readouterr().out
    assert "Abdeckung: 2023: 1200, 2025: 1200" in ausgabe
    assert "Keine Kerzen in 2024" in ausgabe


def test_cli_lehnt_verschraenkte_tagesdatei_ab_und_schreibt_keine_kerzen(
        cfg, tmp_path, monkeypatch, capsys):
    # Der Herbsttag ist mit einem anderen Tag verschränkt. Der blockweise
    # Import erkennt die wiederkehrende Tagesgrenze und bricht ab, bevor Kerzen
    # gespeichert werden.
    zeilen = ["<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"]
    for tag, zeit, preis in (
        ("2025.10.26", "03:00:00", "1.20"),  # Sommerzeitfassung
        ("2025.10.26", "03:15:00", "1.25"),
        ("2025.10.25", "09:00:00", "1.10"),
        ("2025.10.25", "09:15:00", "1.11"),
        ("2025.10.26", "03:00:00", "1.30"),  # Standardzeitfassung
        ("2025.10.26", "03:15:00", "1.35"),
        ("2025.10.25", "09:30:00", "1.12"),
        ("2025.10.25", "09:45:00", "1.13"),
    ):
        zeilen.append(f"{tag}\t{zeit}\t{preis}\t{preis}\t{preis}\t{preis}\t10\t0\t2")
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    code = cli.main(["daten", "--csv", str(p), "--server-zeitzone", "Europe/Athens"])

    ausgabe = capsys.readouterr()
    assert code == 1
    assert "FEHLER EURUSD_M15.csv:" in ausgabe.err
    assert "ist nicht nach Datum sortiert" in ausgabe.err
    assert "2025.10.26" in ausgabe.err
    assert "mehreren" in ausgabe.err
    assert "Nichts importiert." in ausgabe.err
    assert Facts(cfg.db_pfad).kerzen("EURUSD", "M15") == []


def test_zeitrahmen_aus_dateiname_wird_gespeichert_und_nicht_bewertet(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1300, seed=5, timeframe_minuten=60)
    p = tmp_path / "EURUSD_H1.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert _importiere_csv(cfg, db, _args(csv=[str(p)])) == 0
    assert len(db.kerzen("EURUSD", "H1")) == 1300
    assert db.kerzen("EURUSD", "M15") == []


def test_als_m15_benannte_h1_datei_wird_beim_import_abgelehnt(cfg, tmp_path):
    h1 = synthetische_kerzen("X", kerzen=1300, seed=5, timeframe_minuten=60)
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(_als_mt5(h1), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    # Der Import endet mit Fehler, statt die H1-Kerzen still als M15 abzulegen.
    assert _importiere_csv(cfg, db, _args(csv=[str(p)])) == 1


def test_csv_mit_komma_trenner(tmp_path):
    inhalt = (
        "date,open,high,low,close,volume\n"
        "2025-01-02 09:00:00,100,101,99,100.5,10\n"
        "2025-01-02 09:15:00,100.5,102,100,101.5,12\n"
    )
    p = tmp_path / "US500_M15.csv"
    p.write_text(inhalt, encoding="utf-8")
    df = lade_csv(p)
    assert len(df) == 2
    assert list(df.columns) == ["ts", "open", "high", "low", "close", "volume"]
