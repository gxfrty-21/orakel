from __future__ import annotations

import pandas as pd

from orakel.data import lade_csv, pruefe_daten, synthetische_kerzen


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
    # Format des MT5-Exports: <DATE> <TIME> <OPEN> ...
    inhalt = (
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
        "2025.01.02\t09:00\t1.03500\t1.03600\t1.03400\t1.03550\t120\t0\t2\n"
        "2025.01.02\t09:15\t1.03550\t1.03700\t1.03500\t1.03650\t140\t0\t2\n"
    )
    p = tmp_path / "EURUSD_M15.csv"
    p.write_text(inhalt, encoding="utf-8")

    df = lade_csv(p)
    assert len(df) == 2
    assert df["ts"].iloc[0] == pd.Timestamp("2025-01-02 09:00", tz="UTC")
    assert df["close"].iloc[1] == 1.0365
    assert df["volume"].iloc[0] == 120


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
