from __future__ import annotations

import pandas as pd
import pytest

from orakel.config import RisikoGrenzen
from orakel.kern.data import synthetische_kerzen
from orakel.strategiebericht import (
    erstelle_bericht,
    kaufen_halten_pct,
    rendere_markdown,
    schreibe_bericht,
)


@pytest.fixture(scope="module")
def bericht():
    from orakel.config import Config

    daten = {
        "basis": {
            "start_kapital": 100000.0, "waehrung": "USD", "zeitzone": "Europe/Zurich",
            "daten_ordner": "daten", "vault_ordner": "vault", "db_pfad": "orakel.db",
            "datenquelle": "synthetisch", "bars_pro_jahr": 24960,
        },
        "risiko": {
            "risk_per_trade_pct": 1.0, "max_drawdown_pct": 10.0, "max_open_positions": 15,
            "max_daily_loss_pct": 10.0, "max_gross_exposure_pct": 100.0,
            "max_position_pct": 20.0, "min_cash_pct": 10.0, "max_correlation": 0.85,
            "correlation_lookback": 60, "atr_stop_multiple": 2.0,
        },
        "kosten": {"commission_per_share": 0.0, "min_commission": 0.0, "slippage_bps": 0.0},
        "daten": {"min_kerzen": 100, "max_luecke_pct": 5.0, "max_sprung_pct": 25.0,
                  "max_alter_tage": 5},
        "validierung": {
            "train_anteil": 0.7, "walk_forward_fenster": 3, "holdout_anteil": 0.15,
            "min_fold_bars": 50, "min_fold_profitabel": 0.6, "min_train_trades": 5,
            "min_walk_forward_trades": 5, "min_holdout_trades": 5,
            "monte_carlo_laeufe": 30, "zufallslaeufe": 3, "min_profit_factor": 1.15,
            "min_sharpe": 0.3, "max_drawdown_oos_pct": 10.0, "min_robustheit": 0.5,
            "max_zufall_p": 0.10,
        },
        "research": {
            "ema_fast": [10, 20], "ema_slow": [50], "donchian": [20],
            "rsi_buy": [30], "rsi_exit": [65], "roc_period": [20],
        },
    }
    config = Config(daten, None)
    df = synthetische_kerzen("TEST", kerzen=700, seed=5)
    return erstelle_bericht(
        {"TEST": df}, config, RisikoGrenzen.aus_config(config),
        quelle="synthetisch (Test)", commit="0" * 40,
    )


def test_kaufen_halten_rechnet_ueber_den_zeitraum():
    df = pd.DataFrame({"ts": ["a", "b", "c"], "close": [100.0, 110.0, 120.0]})

    assert kaufen_halten_pct(df, 0, 3) == 20.0
    assert kaufen_halten_pct(df, 1, 3) == pytest.approx(9.09, abs=0.01)
    assert kaufen_halten_pct(df, 3, 3) == 0.0


def test_bericht_enthaelt_jede_strategie_mit_holdout(bericht):
    strategien = [e["strategie"] for e in bericht["kandidaten"]]

    assert sorted(strategien) == ["donchian", "ema_cross", "momentum", "rsi_reversion"]
    for eintrag in bericht["kandidaten"]:
        assert eintrag["urteil"] in {"bestanden", "abgelehnt", "zu wenig Daten"}
        assert "kennzahlen" in eintrag["holdout"]
        assert "kaufen_halten_pct" in eintrag["walk_forward"]
        assert "kaufen_halten_pct" in eintrag["entwicklung"]
        assert eintrag["parameterkombinationen"] >= 1


def test_zusammenfassung_zaehlt_dieselben_kandidaten(bericht):
    z = bericht["zusammenfassung"]

    assert z["kandidaten"] == len(bericht["kandidaten"])
    assert z["bestanden"] + z["abgelehnt"] + z["ohne_ausreichende_daten"] == z["kandidaten"]
    assert z["parameterkombinationen"] == sum(
        e["parameterkombinationen"] for e in bericht["kandidaten"])


def test_p_wert_bonferroni_ist_nie_groesser_als_eins(bericht):
    for eintrag in bericht["kandidaten"]:
        p = eintrag["zufall_p_wert_bonferroni"]
        if p is not None:
            assert 0.0 <= p <= 1.0


def test_markdown_nennt_vergleich_und_einordnung(bericht):
    text = rendere_markdown(bericht)

    assert "Kaufen" not in text or "K&H" in text
    assert "Bonferroni" in text
    assert "keine Marktaussage" in text
    for eintrag in bericht["kandidaten"]:
        assert eintrag["strategie"] in text


def test_schreibe_bericht_legt_json_und_markdown_ab(bericht, tmp_path):
    json_pfad, md_pfad = schreibe_bericht(bericht, tmp_path / "out")

    assert json_pfad.exists() and md_pfad.exists()
    assert '"schema": "strategie-bericht.v1"' in json_pfad.read_text(encoding="utf-8")
    assert md_pfad.read_text(encoding="utf-8").startswith("# Strategie-Bericht")
