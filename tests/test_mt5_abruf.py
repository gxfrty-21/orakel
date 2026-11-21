"""Tests für den Windows-Abruf über das Fake-Modul MetaTrader5."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DTYPE = [
    ("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
    ("close", "<f8"), ("tick_volume", "<u8"), ("spread", "<i4"),
    ("real_volume", "<u8"),
]


def _modul():
    name = "mt5_abruf_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "mt5_abruf.py")
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _stamp(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp())


def _bars(*werte: tuple[str, float]) -> np.ndarray:
    reihen = [( _stamp(zeit), preis, preis + 0.001, preis - 0.001, preis, 42, 2, 0)
              for zeit, preis in werte]
    return np.array(reihen, dtype=DTYPE)


class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 16385

    def __init__(self, antworten=None, symbol_ok: bool = True):
        self.antworten = antworten or {}
        self.symbol_ok = symbol_ok
        self.aufrufe: list[tuple[str, int, int, int]] = []
        self.beendet = False
        self.symbol = None

    def initialize(self, **kwargs) -> bool:
        self.terminal_pfad = kwargs.get("path")
        return True

    def shutdown(self) -> None:
        self.beendet = True

    def symbol_select(self, symbol: str, an: bool) -> bool:
        self.symbol = (symbol, an)
        return self.symbol_ok

    def copy_rates_range(self, symbol, rahmen, anfang, ende):
        self.aufrufe.append((symbol, rahmen, anfang, ende))
        return self.antworten.get((anfang, ende), np.array([], dtype=DTYPE))

    def last_error(self):
        return (1, "testfehler")


def test_schreibt_mt5_csv_und_fuehrt_bloecke_zusammen(tmp_path, monkeypatch):
    modul = _modul()
    januar = (_stamp("2025-01-01T00:00:00"), _stamp("2025-01-31T23:59:59"))
    februar = (_stamp("2025-02-01T00:00:00"), _stamp("2025-02-28T23:59:59"))
    fake = FakeMT5({
        januar: _bars(("2025-01-02T09:15:00", 1.0405), ("2025-01-02T09:00:00", 1.035)),
        # Überlappende Kerze aus dem nächsten Block ersetzt die ältere Zeile.
        februar: _bars(("2025-02-03T08:00:00", 1.2), ("2025-01-02T09:00:00", 1.9)),
    })
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    code = modul.main([
        "--symbol", "EURUSD", "--zeitrahmen", "M15",
        "--von", "2025-01-01", "--bis", "2025-02-28", "--ausgabe", str(tmp_path),
    ])

    assert code == 0
    datei = tmp_path / "EURUSD_M15.csv"
    zeilen = datei.read_text(encoding="utf-8").splitlines()
    assert zeilen[0] == "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"
    # aufsteigend; gleiche Zeit mit anderen Werten bleibt als zweite Zeile stehen,
    # der Import führt sie mit «letzte gewinnt» zusammen.
    assert [z.split("\t")[0] + " " + z.split("\t")[1] for z in zeilen[1:]] == [
        "2025.01.02 09:00:00", "2025.01.02 09:00:00",
        "2025.01.02 09:15:00", "2025.02.03 08:00:00",
    ]
    assert [z.split("\t")[2] for z in zeilen[1:3]] == ["1.035", "1.9"]
    assert zeilen[1].split("\t")[6:] == ["42", "0", "2"]
    assert all(len(z.split("\t")) == 9 for z in zeilen[1:])
    assert "," not in datei.read_text(encoding="utf-8")
    assert len(fake.aufrufe) == 2
    assert fake.aufrufe[0][1] == fake.TIMEFRAME_M15
    assert fake.aufrufe[0][2] == _stamp("2025-01-01T00:00:00")
    assert fake.beendet is True


def test_geschriebene_datei_liest_der_import(tmp_path, monkeypatch):
    modul = _modul()
    fake = FakeMT5({(_stamp("2025-01-01T00:00:00"), _stamp("2025-01-31T23:59:59")):
                    _bars(("2025-01-02T09:00:00", 1.035))})
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    assert modul.main(["--symbol", "EURUSD", "--von", "2025-01-01", "--bis", "2025-01-31",
                       "--ausgabe", str(tmp_path)]) == 0

    from orakel.kern.data import lade_csv

    df = lade_csv(tmp_path / "EURUSD_M15.csv", server_zeitzone="Europe/Athens")
    assert str(df["ts"].iloc[0]) == "2025-01-02 07:00:00+00:00"
    assert df["open"].iloc[0] == 1.035
    assert abs(df["high"].iloc[0] - 1.036) < 1e-12
    assert abs(df["low"].iloc[0] - 1.034) < 1e-12
    assert df["close"].iloc[0] == 1.035
    assert df["volume"].iloc[0] == 42


def test_herbst_stunde_und_ueberlappung_gehen_nicht_verloren(tmp_path, monkeypatch):
    modul = _modul()
    # Beide Fassungen der Stunde 03:00 tragen in MT5 dieselbe Serverzeit.
    herbst = np.concatenate([
        _bars(("2025-10-26T03:00:00", 1.0), ("2025-10-26T03:15:00", 1.1)),
        _bars(("2025-10-26T03:00:00", 2.0), ("2025-10-26T03:15:00", 2.1)),
        _bars(("2025-10-26T04:00:00", 3.0)),
    ])
    fake = FakeMT5({
        (_stamp("2025-09-01T00:00:00"), _stamp("2025-09-30T23:59:59")): herbst,
        (_stamp("2025-10-01T00:00:00"), _stamp("2025-10-31T23:59:59")): herbst,
    })
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    assert modul.main(["--symbol", "EURUSD", "--von", "2025-09-01", "--bis", "2025-10-31",
                       "--ausgabe", str(tmp_path)]) == 0

    zeilen = (tmp_path / "EURUSD_M15.csv").read_text(encoding="utf-8").splitlines()
    # fünf Kerzen, obwohl derselbe Block zweimal geliefert wurde; je Zeitstempel
    # steht die erste Fassung vor der zweiten, der Import trennt sie nach Zone.
    assert [z.split("\t")[1] + " " + z.split("\t")[2] for z in zeilen[1:]] == [
        "03:00:00 1.0", "03:00:00 2.0", "03:15:00 1.1", "03:15:00 2.1", "04:00:00 3.0",
    ]

    from orakel.kern.data import lade_csv

    df = lade_csv(tmp_path / "EURUSD_M15.csv", server_zeitzone="Europe/Athens")
    assert [str(t) for t in df["ts"]] == [
        "2025-10-26 00:00:00+00:00", "2025-10-26 00:15:00+00:00",
        "2025-10-26 01:00:00+00:00", "2025-10-26 01:15:00+00:00",
        "2025-10-26 02:00:00+00:00",
    ]


def test_monatsfenster_und_zeitrahmen_werden_uebergeben(tmp_path, monkeypatch):
    modul = _modul()
    fake = FakeMT5()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    code = modul.main([
        "--symbol", "XAUUSD", "--zeitrahmen", "H1",
        "--von", "2024-12-15", "--bis", "2025-02-10", "--ausgabe", str(tmp_path),
    ])

    assert code == 1  # keine Kerzen, aber die Fenster sind geprüft
    assert [(a[2], a[3]) for a in fake.aufrufe] == [
        (_stamp("2024-12-15T00:00:00"), _stamp("2024-12-31T23:59:59")),
        (_stamp("2025-01-01T00:00:00"), _stamp("2025-01-31T23:59:59")),
        (_stamp("2025-02-01T00:00:00"), _stamp("2025-02-10T23:59:59")),
    ]
    assert {a[1] for a in fake.aufrufe} == {fake.TIMEFRAME_H1}


def test_fehlendes_paket_erklaert_die_windows_abhaengigkeit(tmp_path, monkeypatch, capsys):
    modul = _modul()
    monkeypatch.setitem(sys.modules, "MetaTrader5", None)

    code = modul.main([
        "--symbol", "EURUSD", "--von", "2025-01-01", "--ausgabe", str(tmp_path),
    ])

    assert code == 1
    assert "Windows" in capsys.readouterr().err


def test_abbruch_bei_terminalfehler(tmp_path, monkeypatch, capsys):
    modul = _modul()

    class Kaputt(FakeMT5):
        def copy_rates_range(self, symbol, rahmen, anfang, ende):
            return None

    fake = Kaputt()
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)

    code = modul.main([
        "--symbol", "EURUSD", "--von", "2025-01-01", "--ausgabe", str(tmp_path),
    ])

    assert code == 1
    assert "testfehler" in capsys.readouterr().err
    assert fake.beendet is True


def test_nicht_schreibbares_ziel_meldet_deutsch(tmp_path, monkeypatch, capsys):
    modul = _modul()
    fake = FakeMT5({(_stamp("2025-01-01T00:00:00"), _stamp("2025-01-31T23:59:59")):
                    _bars(("2025-01-02T09:00:00", 1.0))})
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake)
    (tmp_path / "EURUSD_M15.csv").mkdir()

    code = modul.main([
        "--symbol", "EURUSD", "--von", "2025-01-01", "--bis", "2025-01-31",
        "--ausgabe", str(tmp_path),
    ])

    assert code == 1
    fehler = capsys.readouterr().err
    assert "nicht schreibbar" in fehler
    assert "EURUSD_M15.csv" in fehler


def test_unbekanntes_symbol_bricht_ab(tmp_path, monkeypatch, capsys):
    modul = _modul()
    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeMT5(symbol_ok=False))

    code = modul.main([
        "--symbol", "GIBTSNICHT", "--von", "2025-01-01", "--ausgabe", str(tmp_path),
    ])

    assert code == 1
    assert "Market Watch" in capsys.readouterr().err
