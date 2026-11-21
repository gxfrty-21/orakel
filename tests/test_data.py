from __future__ import annotations

import argparse

import pandas as pd
import pytest

from orakel.__main__ import _importiere_csv
from orakel.kern.data import (
    df_aus_db,
    lade_csv,
    lade_csv_bloecke,
    pruefe_daten,
    synthetische_kerzen,
    zerlege_dateiname,
)
from orakel.kern.db import Facts


def _args(**kwargs) -> argparse.Namespace:
    werte = {"symbol": None, "zeitrahmen": None, "server_zeitzone": None,
             "server_versatz_stunden": None}
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


def test_zeitrahmen_aus_dateiname_wird_gespeichert_und_nicht_bewertet(cfg, tmp_path):
    basis = synthetische_kerzen("X", kerzen=1300, seed=5)
    p = tmp_path / "EURUSD_H1.csv"
    p.write_text(_als_mt5(basis), encoding="utf-8")
    db = Facts(cfg.db_pfad)

    assert _importiere_csv(cfg, db, _args(csv=[str(p)])) == 0
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
