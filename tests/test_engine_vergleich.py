"""Paper- und Backtest-Ausführung verwenden dieselben Preisformeln.

Der Backtest rechnet Long-only auf einem Instrument. Der Paper-Takt nutzt
dieselbe Einstiegs- und Stop-Logik (Eröffnung der Folgekerze, min(Eröffnung,
Stop) bei Lücken, adverse Slippage, Kommission je Seite). Der Test vergleicht
die tatsächlich gebuchten Preise und Kosten beider Engines auf identischen
Kerzen. Unterschiede bleiben bei Signalquelle und Positionsverwaltung: Der
Paper-Takt schliesst eine Position immer vollständig, der Backtest arbeitet
ebenfalls ohne Teilverkäufe.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from orakel.backtest import backtest
from orakel.config import RisikoGrenzen
from orakel.paper import _fill, _kosten


def kerzen() -> pd.DataFrame:
    ts = pd.date_range("2026-01-05", periods=32, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "ts": ts,
        "open": [100.0] * 32,
        "high": [101.0] * 32,
        "low": [99.0] * 32,
        "close": [100.0] * 32,
        "volume": [1.0] * 32,
    })
    # Signal auf Kerze 20, Ausführung auf 21. ATR(14) = 2, Stop = 100.5 - 4.
    # Kerze 22 bricht unter den Stop; die Eröffnung 95 liegt darunter.
    df.loc[22, ["open", "high", "low", "close"]] = [95.0, 95.5, 94.0, 94.5]
    return df


def test_backtest_und_paper_nutzen_dieselben_fill_preise(cfg):
    cfg._d["kosten"].update({"slippage_bps": 50.0, "commission_per_share": 1.0,
                             "min_commission": 0.0})
    df = kerzen()
    signale = np.zeros(len(df))
    signale[20] = 1.0

    ergebnis = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg),
                        start=0, ende=len(df), startkapital=100000.0,
                        stop_art="atr")

    assert len(ergebnis.trades) == 1
    trade = ergebnis.trades[0]
    einstieg = _fill(float(df["open"].iloc[21]), 1.0, cfg)
    ausstieg = _fill(min(float(df["open"].iloc[22]), 96.5), -1.0, cfg)
    stueck = trade["stueck"]
    erwartet = stueck * (ausstieg - einstieg) - _kosten(stueck, cfg) - _kosten(stueck, cfg)

    assert einstieg == pytest.approx(100.0 * 1.005)
    assert ausstieg == pytest.approx(95.0 * 0.995)
    assert trade["netto"] == pytest.approx(round(erwartet, 2))
    assert trade["grund"] == "Signal"


def test_mehrere_positionen_loesen_gleichzeitig_aus(cfg):
    from orakel.db import Facts
    from orakel.paper import tick
    from test_paper_datenqualitaet import baue_df

    db = Facts(cfg.db_pfad)
    for symbol in ("AAA", "BBB"):
        db.kerzen_speichern(symbol, "M15",
                            baue_df([80.0], opens=[80.0], highs=[81.0], lows=[79.0])
                            .to_dict("records"))
        db.position_setzen(symbol, 10.0, 100.0, 95.0, "{}", "2026-01-01T00:00:00+00:00")

    ergebnis = tick(cfg, db)

    assert db.positionen() == []
    assert ergebnis["konto"]["cash"] == pytest.approx(100000.0 + 2 * 10 * 80.0)
    assert len(db.entscheide(10)) == 2
    assert all(dict(e)["aktion"] == "verkaufen" for e in db.entscheide(10))
