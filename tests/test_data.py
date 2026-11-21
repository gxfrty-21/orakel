from __future__ import annotations

import argparse

import pandas as pd
import pytest

from orakel.__main__ import _importiere_csv
from orakel.kern.data import (
    df_aus_db,
    lade_csv,
    pruefe_daten,
    synthetische_kerzen,
    zerlege_dateiname,
)
from orakel.kern.db import Facts


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


def test_zwei_bloecke_ergeben_eine_gepruefte_reihe(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1500, seed=3)
    a = tmp_path / "EURUSD_M15_a.csv"
    b = tmp_path / "EURUSD_M15_b.csv"
    a.write_text(_als_mt5(basis.iloc[:800]), encoding="utf-8")
    b.write_text(_als_mt5(basis.iloc[700:]), encoding="utf-8")
    db = Facts(cfg.db_pfad)
    args = argparse.Namespace(csv=[str(a), str(b)], symbol=None, zeitrahmen=None)

    assert _importiere_csv(cfg, db, args) == 0
    # 100 überlappende Kerzen werden zusammengeführt statt doppelt gespeichert.
    assert len(db.kerzen("EURUSD", "M15")) == 1500

    # Erneuter Import desselben Blocks ändert die Reihe nicht.
    assert _importiere_csv(cfg, db, argparse.Namespace(csv=[str(a)], symbol=None, zeitrahmen=None)) == 0
    assert len(db.kerzen("EURUSD", "M15")) == 1500

    df = df_aus_db(db.kerzen("EURUSD", "M15"))
    q = pruefe_daten(df, "EURUSD", cfg)
    assert q.ok, q.fehler
    assert q.von == "2024-01-01 00:00:00"


def test_zeitrahmen_aus_dateiname_wird_gespeichert_und_nicht_bewertet(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1300, seed=5)
    p = tmp_path / "EURUSD_H1.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert _importiere_csv(cfg, db, argparse.Namespace(csv=[str(p)], symbol=None, zeitrahmen=None)) == 0
    assert len(db.kerzen("EURUSD", "H1")) == 1300
    assert db.kerzen("EURUSD", "M15") == []


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
