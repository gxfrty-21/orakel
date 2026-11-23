from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from orakel.config import RisikoGrenzen
from orakel.kern.backtest import backtest
from orakel.kern.strategies import Signalplan, kandidaten, strategien


def h1_kerzen() -> pd.DataFrame:
    ts = pd.date_range("2025-01-01", periods=40, freq="1h", tz="UTC")
    close = np.full(40, 100.0)
    high = close + 1.0
    low = close - 1.0
    open_ = close.copy()

    # Breakout über das bisherige Hoch (101), anschliessend Retest und
    # Bestätigung auf einer späteren Kerze.
    close[10], high[10], low[10] = 105.0, 106.0, 100.0
    close[11], high[11], low[11] = 102.0, 103.0, 100.5
    close[12], high[12], low[12] = 104.0, 105.0, 101.0
    open_[13] = 104.0
    open_[21] = 100.0
    close[20], high[20], low[20] = 100.0, 101.0, 99.0

    return pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": [100.0] * 40,
    })


def flache_kerzen(n: int = 80) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "ts": ts, "open": [100.0] * n, "high": [101.0] * n,
        "low": [99.0] * n, "close": [100.0] * n, "volume": [100.0] * n,
    })


def mit_h1_raster(cfg):
    cfg._d.setdefault("basis", {})["richter_zeitrahmen"] = "H1"
    cfg._d["research"].update({
        "h1_retest_lookback": [5],
        "h1_retest_fenster": [5],
        "h1_retest_stop_puffer_pct": [0.01],
    })
    return cfg


def test_signalplan_ist_zielkompatibel():
    plan = Signalplan(np.array([0.0, 1.0]), np.array([np.nan, 99.0]), True)

    assert len(plan) == 2
    assert plan[-1] == 1.0
    assert np.array_equal(np.asarray(plan), np.array([0.0, 1.0]))


def test_h1_retest_wartet_auf_bestaetigung_und_setzt_stop(cfg):
    cfg = mit_h1_raster(cfg)
    strategie = strategien(cfg)["h1_retest"]
    df = h1_kerzen()

    plan = strategie.signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )

    assert isinstance(plan, Signalplan)
    assert plan.reentry_sperre is True
    assert plan.ziel[10] == 0.0  # Breakout allein reicht nicht
    assert plan.ziel[11] == 0.0  # Retest allein reicht nicht
    assert plan.ziel[12] == 1.0  # spätere Bestätigung
    assert plan.stop[12] == pytest.approx(100.5 * 0.99)
    assert plan.ziel[20] == 0.0  # Schluss auf der falschen Seite


def test_h1_plan_wird_zur_folgekerze_ausgefuehrt(cfg):
    cfg = mit_h1_raster(cfg)
    strategie = strategien(cfg)["h1_retest"]
    df = h1_kerzen()
    df.loc[13, "low"] = 100.5

    plan = strategie.signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )
    erg = backtest(df, plan, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.trades[0]["einstieg"] == str(df["ts"].iloc[13])[:19]
    assert erg.trades[0]["grund"] == "Signal"


def test_h1_retest_ohne_bestaetigung_erzeugt_kein_signal(cfg):
    cfg = mit_h1_raster(cfg)
    strategie = strategien(cfg)["h1_retest"]
    df = h1_kerzen()
    df.loc[12, "close"] = 100.0
    df.loc[12, "high"] = 101.0
    df.loc[12, "low"] = 99.0

    plan = strategie.signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )

    assert np.all(plan.ziel == 0.0)
    assert np.all(np.isnan(plan.stop))


def test_h1_retest_wird_erst_im_h1_raster_aktiv(cfg):
    assert "h1_retest" not in strategien(cfg)

    mit_raster = mit_h1_raster(cfg)
    assert "h1_retest" in strategien(mit_raster)
    assert "h1_retest" in strategien(mit_raster, zeitrahmen="H1")
    assert any(s.name == "h1_retest" for s, _ in kandidaten(mit_raster))


def test_h1_retest_wird_bei_m15_nicht_mitbewertet(cfg):
    cfg = mit_h1_raster(cfg)
    assert "h1_retest" not in strategien(cfg, zeitrahmen="M15")

    cfg._d["basis"]["richter_zeitrahmen"] = "M15"
    assert "h1_retest" not in strategien(cfg)
    assert "h1_retest" not in strategien(cfg, zeitrahmen="H1")
    assert all(s.name != "h1_retest" for s, _ in kandidaten(cfg))
    assert "donchian" in strategien(cfg)


def test_expliziter_stop_hat_vorrang_vor_atr(cfg):
    df = flache_kerzen()
    df.loc[31, "low"] = 85.0  # ATR-Stop wäre bei 96; der Plan-Stop liegt bei 80
    ziel = np.zeros(len(df))
    ziel[30:50] = 1.0
    stop = np.full(len(df), 80.0)
    plan = Signalplan(ziel=ziel, stop=stop, reentry_sperre=True)

    erg = backtest(df, plan, cfg, RisikoGrenzen.aus_config(cfg))

    assert len(erg.trades) == 1
    assert erg.trades[0]["grund"] == "Signal"
    assert not erg.warnungen


def test_expliziter_stop_respektiert_eine_luecke(cfg):
    df = flache_kerzen()
    df.loc[35, "open"] = 70.0
    df.loc[35, "low"] = 69.0
    df.loc[35, "close"] = 70.0
    ziel = np.zeros(len(df))
    ziel[30:40] = 1.0
    stop = np.full(len(df), 80.0)

    erg = backtest(
        df, Signalplan(ziel, stop, True), cfg, RisikoGrenzen.aus_config(cfg),
    )

    assert erg.trades[0]["grund"] == "Stop"
    assert erg.trades[0]["netto"] < 0
    assert erg.trades[0]["ausstieg"] == str(df["ts"].iloc[35])[:19]


def test_reentry_sperre_verhindert_wiedereinstieg_nach_stop(cfg):
    df = flache_kerzen()
    df.loc[31, "low"] = 80.0  # Stop bereits in der Einstiegskerze
    ziel = np.zeros(len(df))
    ziel[30:70] = 1.0
    stop = np.full(len(df), 80.0)

    ohne_sperre = backtest(
        df, Signalplan(ziel, stop, False), cfg, RisikoGrenzen.aus_config(cfg),
    )
    mit_sperre = backtest(
        df, Signalplan(ziel, stop, True), cfg, RisikoGrenzen.aus_config(cfg),
    )

    assert ohne_sperre.trades[0]["grund"] == "Stop (Einstiegskerze)"
    assert len(ohne_sperre.trades) == 2
    assert len(mit_sperre.trades) == 1


def test_reentry_sperre_endet_nach_neutralem_ziel(cfg):
    df = flache_kerzen()
    df.loc[31, "low"] = 80.0
    ziel = np.zeros(len(df))
    ziel[30:40] = 1.0
    ziel[60:70] = 1.0
    stop = np.full(len(df), 80.0)

    erg = backtest(
        df, Signalplan(ziel, stop, True), cfg, RisikoGrenzen.aus_config(cfg),
    )

    assert len(erg.trades) == 2
    assert erg.trades[0]["grund"] == "Stop (Einstiegskerze)"
    assert erg.trades[1]["grund"] == "Signal"


def test_ungueltiger_stop_verhindert_einstieg_und_warnt(cfg):
    df = flache_kerzen()
    ziel = np.zeros(len(df))
    ziel[30:50] = 1.0
    stop = np.full(len(df), np.nan)

    erg = backtest(
        df, Signalplan(ziel, stop, True), cfg, RisikoGrenzen.aus_config(cfg),
    )

    assert erg.trades == []
    assert erg.warnungen
    assert "Ungültiger Stop" in erg.warnungen[0]


@pytest.mark.parametrize("stop_preis", [100.0, 101.0])
def test_plan_stop_auf_oder_ueber_fill_verhindert_einstieg_und_warnt(cfg, stop_preis):
    df = flache_kerzen()
    ziel = np.zeros(len(df))
    ziel[30] = 1.0
    stop = np.full(len(df), stop_preis)

    erg = backtest(
        df, Signalplan(ziel, stop, True), cfg, RisikoGrenzen.aus_config(cfg),
    )

    # Der Fill wäre die Eröffnung von Bar 31 bei 100,0. Ein ATR-Fallback
    # hätte einen Trade erzeugt; der Plan-Stop darf nicht ersetzt werden.
    assert erg.trades == []
    assert erg.warnungen == [
        "Stop im Signalplan nicht unter dem Einstieg an Bar 30"
    ]


def retest_kerzen(bestaetigung_bar: int) -> pd.DataFrame:
    """Breakout bei 10, Retest bei 11, Bestätigung bei ``bestaetigung_bar``."""
    n = 40
    ts = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    close = np.full(n, 100.0)
    high = close + 1.0
    low = close - 1.0
    open_ = close.copy()

    # Level = Hoch der fünf Kerzen vor dem Breakout = 101.
    close[10], high[10], low[10] = 105.0, 106.0, 100.0
    # Erster gültiger Retest: Berührung, aber Schluss auf dem Level.
    close[11], high[11], low[11] = 101.0, 102.0, 100.5
    # Ruhige Kerzen im Fenster: kein Schluss über dem Level.
    for i in range(12, 30):
        close[i], high[i], low[i] = 101.0, 101.5, 100.8
    close[bestaetigung_bar], high[bestaetigung_bar], low[bestaetigung_bar] = (
        103.0, 103.5, 100.9,
    )

    return pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": [100.0] * n,
    })


@pytest.mark.parametrize("bestaetigung_bar", [15, 16])
def test_h1_bestaetigung_nur_bis_zur_letzten_fensterkerze(cfg, bestaetigung_bar):
    df = retest_kerzen(bestaetigung_bar)

    plan = strategien(mit_h1_raster(cfg))["h1_retest"].signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )

    if bestaetigung_bar == 15:  # setup_bar + F ist noch im Fenster
        assert plan.ziel[15] == 1.0
        assert plan.stop[15] == pytest.approx(100.5 * 0.99)
    else:  # setup_bar + F + 1: Setup ist verfallen
        assert np.all(plan.ziel == 0.0)
        assert np.all(np.isnan(plan.stop))


def test_h1_retest_stop_nutzt_das_tiefste_retest_tief(cfg):
    df = retest_kerzen(15)
    df.loc[13, "low"] = 99.0  # zweiter gültiger Retest, Schluss weiterhin am Level

    plan = strategien(mit_h1_raster(cfg))["h1_retest"].signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )

    assert plan.ziel[15] == 1.0
    assert plan.stop[15] == pytest.approx(99.0 * 0.99)


def test_h1_fensterende_erlaubt_gleichzeitiges_neues_breakout(cfg):
    n = 40
    ts = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    df = pd.DataFrame({
        "ts": ts, "open": [100.0] * n, "high": [101.0] * n,
        "low": [99.0] * n, "close": [100.0] * n, "volume": [100.0] * n,
    })
    # Erster Ausbruch bei 10; im Fenster (2 Kerzen) gibt es keinen Retest.
    df.loc[10, ["high", "low", "close"]] = [106.0, 100.0, 105.0]
    df.loc[11, ["high", "low", "close"]] = [107.0, 105.5, 106.0]
    df.loc[12, ["high", "low", "close"]] = [107.0, 105.5, 106.0]
    # Bar 13 schliesst das Fenster und ist selbst ein Ausbruch über das
    # aktuelle Hoch (107): Das darf kein Setup verschlucken.
    df.loc[13, ["high", "low", "close"]] = [109.0, 107.0, 108.0]
    df.loc[14, ["high", "low", "close"]] = [109.0, 107.0, 108.0]
    df.loc[15, ["high", "low", "close"]] = [109.5, 107.5, 108.5]

    plan = strategien(mit_h1_raster(cfg))["h1_retest"].signale(
        df, {"lookback": 2, "retest_fenster": 2, "stop_puffer_pct": 0.01},
    )

    assert plan.ziel[12] == 0.0  # altes Setup: noch keine Bestätigung
    assert plan.ziel[15] == 1.0  # neues Setup aus Bar 13 bestätigt
    assert plan.stop[15] == pytest.approx(107.0 * 0.99)


def test_h1_plan_traegt_den_stop_ueber_halte_bars(cfg):
    cfg = mit_h1_raster(cfg)
    df = retest_kerzen(15)
    plan = strategien(cfg)["h1_retest"].signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )

    assert plan.ziel[18] == 1.0
    assert np.allclose(plan.stop[15:30], 100.5 * 0.99)

    # Ein Walk-Forward-Fenster kann mitten in der Haltedauer beginnen: Der
    # Backtest steigt dann mit dem festgeschriebenen Stop ein, nicht ohne Stop.
    erg = backtest(df, plan, cfg, RisikoGrenzen.aus_config(cfg), start=18, ende=25)

    assert len(erg.trades) == 1
    assert erg.trades[0]["einstieg"] == str(df["ts"].iloc[19])[:19]
    assert not erg.warnungen


def test_h1_retest_nach_stop_neu_erst_nach_neutralem_ziel(cfg):
    df = h1_kerzen()
    # Position nach der Bestätigung halten, damit erst der Stop sie beendet.
    df.loc[13:19, "close"] = 104.0
    df.loc[13:19, "high"] = 105.0
    df.loc[13:19, "low"] = 100.5  # kein Stop in der Einstiegskerze
    df.loc[14, "low"] = 98.0      # Stop unter dem Retest-Tief

    # Zweites Setup erst, nachdem das alte Ziel neutral war (Bar 20).
    df.loc[25, ["close", "high", "low"]] = [105.0, 106.0, 100.0]
    df.loc[26, ["close", "high", "low"]] = [101.0, 102.0, 100.5]
    df.loc[27, ["close", "high", "low"]] = [103.0, 103.5, 100.9]
    df.loc[28:, "close"] = 104.0
    df.loc[28:, "high"] = 105.0
    df.loc[28:, "low"] = 102.0
    df.loc[28, "open"] = 104.0

    plan = strategien(mit_h1_raster(cfg))["h1_retest"].signale(
        df, {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
    )
    erg = backtest(df, plan, cfg, RisikoGrenzen.aus_config(cfg))

    assert plan.ziel[19] == 1.0  # altes Signal bleibt nach dem Stop positiv
    assert plan.ziel[20] == 0.0  # neutrales Ziel hebt die Sperre auf
    assert plan.ziel[27] == 1.0  # neues Setup wird bestätigt
    assert [t["grund"] for t in erg.trades] == ["Stop", "Ende der Daten"]
    assert erg.trades[1]["einstieg"] == str(df["ts"].iloc[28])[:19]


def test_array_und_plan_liefern_denselben_backtest(cfg):
    df = flache_kerzen()
    ziel = np.zeros(len(df))
    ziel[30:50] = 1.0

    als_array = backtest(df, ziel, cfg, RisikoGrenzen.aus_config(cfg))
    als_plan = backtest(
        df, Signalplan.aus_ziel(ziel), cfg, RisikoGrenzen.aus_config(cfg),
    )

    assert als_array.trades == als_plan.trades
    assert als_array.kennzahlen == als_plan.kennzahlen
    assert not als_array.warnungen
    assert not als_plan.warnungen
