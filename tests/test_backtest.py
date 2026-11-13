from __future__ import annotations

import numpy as np
import pandas as pd

from orakel.backtest import backtest
from orakel.config import RisikoGrenzen


def reihe(n: int = 60, kurs: float = 100.0) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "ts": ts, "open": [kurs] * n, "high": [kurs + 1] * n,
        "low": [kurs - 1] * n, "close": [kurs] * n, "volume": [100.0] * n,
    })


def test_einstieg_erfolgt_zur_naechsten_eroeffnung(cfg):
    df = reihe(60)
    signale = np.zeros(60)
    signale[30] = 1.0  # Signal am Schlusskurs von Kerze 30
    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.trades, "Es muss ein Trade entstanden sein"
    assert erg.trades[0]["einstieg"] == str(df["ts"].iloc[31])[:19]
    # Einstiegskurs ist die Eröffnung der Folgekerze, nicht der Signal-Schlusskurs
    assert erg.kapitalkurve[31][0] == str(df["ts"].iloc[31])[:19]


def test_stop_wird_innerhalb_der_kerze_ausgefuehrt(cfg):
    df = reihe(60)
    df.loc[35, "low"] = 90.0  # Stop bei 2 x ATR = 4 -> 96 wird gerissen
    signale = np.zeros(60)
    signale[30:40] = 1.0  # Haltephase, nicht nur ein Balken
    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    trade = erg.trades[0]
    assert trade["grund"] == "Stop"
    assert trade["netto"] < 0
    # Stop-Preis, nicht der Tiefstkurs der Kerze: Ausstieg in der Kerze mit dem gerissenen Stop
    assert trade["ausstieg"] == str(df["ts"].iloc[35])[:19]


def test_luecke_unter_stop_fuellt_zur_eroeffnung(cfg):
    df = reihe(60)
    df.loc[35, "open"] = 80.0
    df.loc[35, "low"] = 79.0
    df.loc[35, "close"] = 80.0
    signale = np.zeros(60)
    signale[30:40] = 1.0
    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.trades[0]["grund"] == "Stop"
    # Bei einer Lücke unter den Stop wird zur Eröffnung gefüllt (schlechter als der Stop)
    assert erg.trades[0]["netto"] < -3 * 100


def test_kosten_werden_abgezogen(tmp_path):
    from orakel.config import Config

    basis = cfg_daten(tmp_path)
    basis["kosten"] = {"commission_per_share": 0.01, "min_commission": 5.0, "slippage_bps": 5.0}
    cfg = Config(basis, tmp_path / "config.toml")
    df = reihe(60)
    signale = np.zeros(60)
    signale[30] = 1.0
    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))
    assert erg.kennzahlen["gebuehren"] > 0


def cfg_daten(tmp_path) -> dict:
    return {
        "basis": {"start_kapital": 100000.0, "waehrung": "USD", "zeitzone": "Europe/Zurich",
                  "daten_ordner": str(tmp_path / "d"), "vault_ordner": str(tmp_path / "v"),
                  "db_pfad": str(tmp_path / "o.db"), "datenquelle": "synthetisch",
                  "bars_pro_jahr": 24960},
        "risiko": {"risk_per_trade_pct": 1.0, "max_drawdown_pct": 10.0, "max_open_positions": 15,
                   "max_daily_loss_pct": 3.0, "max_gross_exposure_pct": 100.0,
                   "max_position_pct": 20.0, "min_cash_pct": 10.0, "max_correlation": 0.85,
                   "correlation_lookback": 60, "atr_stop_multiple": 2.0},
        "kosten": {"commission_per_share": 0.0, "min_commission": 0.0, "slippage_bps": 0.0},
        "daten": {"min_kerzen": 100, "max_luecke_pct": 5.0, "max_sprung_pct": 25.0, "max_alter_tage": 5},
        "validierung": {"train_anteil": 0.7, "walk_forward_fenster": 3, "holdout_anteil": 0.15,
                        "min_fold_bars": 50, "min_fold_profitabel": 0.6, "min_train_trades": 5,
                        "min_walk_forward_trades": 5, "min_holdout_trades": 10,
                        "monte_carlo_laeufe": 50, "zufallslaeufe": 5, "min_profit_factor": 1.15,
                        "min_sharpe": 0.3, "max_drawdown_oos_pct": 10.0, "min_robustheit": 0.5,
                        "max_zufall_p": 0.10},
        "research": {"ema_fast": [10], "ema_slow": [50], "donchian": [20],
                     "rsi_buy": [30], "rsi_exit": [65], "roc_period": [20]},
        "paper": {"order_freigabe": False, "broker": "csv"},
    }
