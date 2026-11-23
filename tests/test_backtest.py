from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from orakel.kern.backtest import backtest
from orakel.config import RisikoGrenzen, validiere_config


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


def tagesreihe(n: int = 60, kurs: float = 100.0) -> pd.DataFrame:
    """Stündliche Kerzen ab 20:00 UTC; der Handel läuft über Mitternacht."""
    ts = pd.date_range("2025-01-01 20:00", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "ts": ts, "open": [kurs] * n, "high": [kurs + 1] * n,
        "low": [kurs - 1] * n, "close": [kurs] * n, "volume": [100.0] * n,
    })


def test_finanzierung_modell_bucht_pro_utc_kalendertag(cfg):
    cfg._d["kosten"]["finanzierung_bps_pro_tag"] = 10.0
    df = tagesreihe()
    signale = np.zeros(len(df))
    signale[20:40] = 1.0

    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    trade = erg.trades[0]
    assert trade["einstieg"] == str(df["ts"].iloc[21])[:19]
    notional = trade["stueck"] * df["open"].iloc[21]
    assert erg.kennzahlen["finanzierung"] == pytest.approx(0.001 * notional, abs=0.01)
    assert erg.kennzahlen["gebuehren"] == 0.0
    assert erg.kennzahlen["netto"] == pytest.approx(
        -erg.kennzahlen["finanzierung"], abs=0.01,
    )


def test_finanzierung_ohne_tageswechsel_ist_null(cfg):
    cfg._d["kosten"]["finanzierung_bps_pro_tag"] = 10.0
    df = reihe(60)
    signale = np.zeros(60)
    signale[30:40] = 1.0

    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.trades
    assert erg.kennzahlen["finanzierung"] == 0.0


def test_finanzierung_modell_nutzt_das_einstiegsnotional(cfg):
    cfg._d["kosten"]["finanzierung_bps_pro_tag"] = 10.0
    df = tagesreihe()
    # Kurs verdoppelt sich nach dem Einstieg; das Modell bewertet nicht neu.
    df.loc[25:, ["open", "high", "low", "close"]] = [200.0, 201.0, 199.0, 200.0]
    signale = np.zeros(len(df))
    signale[20:40] = 1.0

    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    trade = erg.trades[0]
    assert trade["einstieg"] == str(df["ts"].iloc[21])[:19]
    assert erg.kennzahlen["finanzierung"] == pytest.approx(
        0.001 * trade["stueck"] * 100.0, abs=0.01,
    )


def test_finanzierung_ist_standardmaessig_aus(cfg):
    df = tagesreihe()
    signale = np.zeros(len(df))
    signale[20:40] = 1.0

    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.kennzahlen["finanzierung"] == 0.0
    assert erg.kennzahlen["netto"] == 0.0


def test_finanzierung_ist_von_gebuehren_getrennt(cfg):
    cfg._d["kosten"].update({
        "commission_per_share": 0.005, "min_commission": 1.0,
        "slippage_bps": 0.0, "finanzierung_bps_pro_tag": 10.0,
    })
    df = tagesreihe()
    signale = np.zeros(len(df))
    signale[20:40] = 1.0

    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.kennzahlen["gebuehren"] == pytest.approx(2.0, abs=0.01)
    assert erg.kennzahlen["finanzierung"] > 0
    assert erg.kennzahlen["netto"] == pytest.approx(
        -2.0 - erg.kennzahlen["finanzierung"], abs=0.02,
    )


def test_finanzierung_modell_bucht_wochenende_als_kalendertage(cfg):
    # Bewusste Vereinfachung gegenüber dem ueblichen Triple-Swap am Mittwoch:
    # Freitag bis Montag sind hier drei Kalendertage, kein Broker-Swap.

    cfg._d["kosten"]["finanzierung_bps_pro_tag"] = 10.0
    ts = pd.DatetimeIndex(
        list(pd.date_range("2025-01-03", periods=20, freq="1h", tz="UTC"))
        + list(pd.date_range("2025-01-06", periods=10, freq="1h", tz="UTC"))
    )
    n = len(ts)
    df = pd.DataFrame({
        "ts": ts, "open": [100.0] * n, "high": [101.0] * n,
        "low": [99.0] * n, "close": [100.0] * n, "volume": [100.0] * n,
    })
    signale = np.zeros(n)
    signale[14:20] = 1.0

    erg = backtest(df, signale, cfg, RisikoGrenzen.aus_config(cfg))

    trade = erg.trades[0]
    assert trade["einstieg"] == str(ts[15])[:19]
    assert trade["ausstieg"] == str(ts[21])[:19]
    notional = trade["stueck"] * 100.0
    assert erg.kennzahlen["finanzierung"] == pytest.approx(
        3 * 0.001 * notional, abs=0.01,
    )


def test_finanzierung_rechnet_das_notional_in_die_kontowaehrung(cfg):
    cfg._d["kosten"]["finanzierung_bps_pro_tag"] = 10.0
    df = tagesreihe(kurs=150.0)  # USDJPY: Kurswährung JPY, Konto USD
    signale = np.zeros(len(df))
    signale[20:40] = 1.0

    erg = backtest(
        df, signale, cfg, RisikoGrenzen.aus_config(cfg), symbol="USDJPY",
    )

    trade = erg.trades[0]
    # 1 Stück USDJPY ist 1 USD; das Notional in USD ist die Stückzahl.
    assert erg.kennzahlen["finanzierung"] == pytest.approx(
        0.001 * trade["stueck"], abs=0.01,
    )


def test_finanzierung_ohne_kreuzkurs_bricht_ab(cfg):
    cfg._d["kosten"]["finanzierung_bps_pro_tag"] = 10.0
    df = reihe(60, kurs=0.85)  # EURGBP: weder Basis noch Quote ist USD
    df["high"] = df["open"] + 0.001
    df["low"] = df["open"] - 0.001
    signale = np.zeros(60)
    signale[30:40] = 1.0

    with pytest.raises(ValueError, match="EURGBP"):
        backtest(
            df, signale, cfg, RisikoGrenzen.aus_config(cfg), symbol="EURGBP",
        )


def test_negative_finanzierungskosten_werden_abgelehnt(tmp_path):
    daten = cfg_daten(tmp_path)
    daten["kosten"]["finanzierung_bps_pro_tag"] = -0.1

    with pytest.raises(ValueError, match="finanzierung_bps_pro_tag"):
        validiere_config(daten)


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
