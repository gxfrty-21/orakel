from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from orakel.config import Config
from orakel.data import synthetische_kerzen


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    daten = {
        "basis": {
            "start_kapital": 100000.0, "waehrung": "USD", "zeitzone": "Europe/Zurich",
            "daten_ordner": str(tmp_path / "daten"), "vault_ordner": str(tmp_path / "vault"),
            "db_pfad": str(tmp_path / "orakel.db"), "datenquelle": "synthetisch",
            "bars_pro_jahr": 24960,
        },
        "risiko": {
            "risk_per_trade_pct": 1.0, "max_drawdown_pct": 10.0, "max_open_positions": 15,
            "max_daily_loss_pct": 10.0, "max_gross_exposure_pct": 100.0, "max_position_pct": 20.0,
            "min_cash_pct": 10.0, "max_correlation": 0.85, "correlation_lookback": 60,
            "atr_stop_multiple": 2.0,
        },
        "kosten": {"commission_per_share": 0.0, "min_commission": 0.0, "slippage_bps": 0.0},
        "daten": {"min_kerzen": 100, "max_luecke_pct": 5.0, "max_sprung_pct": 25.0, "max_alter_tage": 5},
        "validierung": {
            "train_anteil": 0.7, "walk_forward_fenster": 3, "holdout_anteil": 0.15,
            "min_fold_bars": 50, "min_fold_profitabel": 0.6, "min_train_trades": 5,
            "min_walk_forward_trades": 5, "min_holdout_trades": 10,
            "monte_carlo_laeufe": 50, "zufallslaeufe": 5, "min_profit_factor": 1.15,
            "min_sharpe": 0.3, "max_drawdown_oos_pct": 10.0, "min_robustheit": 0.5,
            "max_zufall_p": 0.10,
        },
        "research": {
            "ema_fast": [10], "ema_slow": [50], "donchian": [20],
            "rsi_buy": [30], "rsi_exit": [65], "roc_period": [20],
        },
        "paper": {"order_freigabe": False, "broker": "csv",
                  "takt_sekunden": 60, "takt_aktiv": False},
        "betrieb": {
            "spider_intervall_minuten": 360, "unternehmen_intervall_minuten": 60,
            "max_missionen_pro_takt": 3, "backoff_basis_sekunden": 60,
            "backoff_max_sekunden": 3600, "spider_backoff_max_sekunden": 3600,
            "grenze_pause_sekunden": 300, "max_takt_sekunden": 240,
            "max_db_mb": 512, "max_rss_mb": 768,
            "min_freier_speicher_mb": 128, "max_laeufe": 1000,
        },
        "spider": {
            "aktiv": True, "max_artikel_pro_lauf": 5, "max_notizen_pro_lauf": 3,
            "min_qualitaet": 0.2, "timeout_sekunden": 5, "min_abstand_sekunden": 0,
            "user_agent": "TestBot/0.1",
            "quelle": [{"name": "Testquelle", "url": "https://example.com/feed.xml",
                        "typ": "nachrichten", "gewicht": 0.9}],
        },
    }
    return Config(daten, tmp_path / "config.toml")


@pytest.fixture
def kerzen() -> pd.DataFrame:
    return synthetische_kerzen("TEST", kerzen=1500, seed=3)
