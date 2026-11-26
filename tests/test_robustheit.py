from __future__ import annotations

import numpy as np
import pytest

from orakel.config import RisikoGrenzen
from orakel.kern.backtest import backtest
from orakel.kern.robustheit import (
    STANDARD_LAEUFE,
    parameter_perturbieren,
    perturbationstest,
    preise_perturbieren,
)
from orakel.kern.strategies import strategien


def _strategie_und_parameter(cfg):
    strategie = strategien(cfg)["donchian"]
    return strategie, {"lookback": 20}


def test_standardlauf_hat_mehrere_hundert_laeufe():
    assert STANDARD_LAEUFE >= 300


def test_perturbationstest_ist_deterministisch(cfg, kerzen):
    strategie, parameter = _strategie_und_parameter(cfg)
    grenzen = RisikoGrenzen.aus_config(cfg)

    a = perturbationstest(
        kerzen, strategie, parameter, cfg, grenzen, laeufe=8, seed=42,
    )
    b = perturbationstest(
        kerzen, strategie, parameter, cfg, grenzen, laeufe=8, seed=42,
    )

    assert a == b
    assert a.als_dict() == b.als_dict()
    assert a.laeufe == 8
    assert 0 <= a.laeufe_mit_trades <= 8
    assert a.basis_trades > 0
    assert a.drawdown_p95_pct is not None
    assert 0 <= a.drawdown_p95_pct <= 100
    assert a.profit_factor_p50 is not None
    assert a.profit_factor_ueber_1_anteil is not None
    assert 0 <= a.profit_factor_ueber_1_anteil <= 1


def test_ohne_perturbation_entspricht_dem_basislauf(cfg, kerzen):
    strategie, parameter = _strategie_und_parameter(cfg)
    grenzen = RisikoGrenzen.aus_config(cfg)
    basis = backtest(kerzen, strategie.signale(kerzen, parameter), cfg, grenzen)

    ergebnis = perturbationstest(
        kerzen, strategie, parameter, cfg, grenzen, laeufe=3,
        preis_sigma=0.0, parameter_jitter=0.0, seed=7,
    )

    assert ergebnis.basis_drawdown_pct == basis.kennzahlen["max_drawdown_pct"]
    assert ergebnis.drawdown_p50_pct == basis.kennzahlen["max_drawdown_pct"]
    assert ergebnis.drawdown_p95_pct == basis.kennzahlen["max_drawdown_pct"]
    assert ergebnis.drawdown_max_pct == basis.kennzahlen["max_drawdown_pct"]
    assert ergebnis.profit_factor_p50 == basis.kennzahlen["profit_factor"]
    assert ergebnis.profit_factor_p05 == basis.kennzahlen["profit_factor"]


def test_preis_perturbation_erhaelt_ohlc_und_original(cfg, kerzen):
    original = kerzen.copy(deep=True)
    rng = np.random.default_rng(1)

    neu = preise_perturbieren(kerzen, rng, 0.001)

    assert not neu.equals(kerzen)
    assert neu["ts"].equals(kerzen["ts"])
    assert neu["volume"].equals(kerzen["volume"])
    assert neu["close"].iloc[0] == kerzen["close"].iloc[0]
    assert (neu["high"] >= neu[["open", "close"]].max(axis=1)).all()
    assert (neu["low"] <= neu[["open", "close"]].min(axis=1)).all()
    assert kerzen.equals(original)


def test_preis_perturbation_kumuliert_die_schocks(cfg, kerzen):
    rng = np.random.default_rng(11)
    schocks = rng.normal(0.0, 0.001, size=len(kerzen))
    schocks[0] = 0.0
    erwartete_faktoren = np.exp(np.cumsum(schocks))

    neu = preise_perturbieren(kerzen, np.random.default_rng(11), 0.001)

    np.testing.assert_allclose(
        (neu["close"] / kerzen["close"]).to_numpy(), erwartete_faktoren,
    )


def test_parameter_perturbation_bleibt_im_bereich_und_gueltig(cfg):
    parameter = {"lookback": 50, "fast": 10, "slow": 11, "aktiv": True}
    original = dict(parameter)
    rng = np.random.default_rng(2)

    neu = parameter_perturbieren(parameter, rng, 0.1, ordnung=(("fast", "slow"),))

    assert 45 <= neu["lookback"] <= 55
    assert neu["fast"] < neu["slow"]
    assert neu["aktiv"] is True
    assert parameter == original


def test_parameter_perturbation_verhindert_ungueltige_rsi_reihenfolge(cfg):
    rng = np.random.default_rng(3)

    neu = parameter_perturbieren(
        {"periode": 14, "buy_below": 30, "exit_above": 31}, rng, 0.5,
        ordnung=(("buy_below", "exit_above"),),
    )

    assert neu["buy_below"] < neu["exit_above"]
    assert neu["periode"] >= 1


@pytest.mark.parametrize(
    ("name", "parameter"),
    [
        ("ema_cross", {"fast": 10, "slow": 50}),
        ("rsi_reversion", {"periode": 14, "buy_below": 30, "exit_above": 65}),
    ],
)
def test_perturbationstest_nutzt_die_strategieordnung(cfg, kerzen, name, parameter):
    strategie = strategien(cfg)[name]

    ergebnis = perturbationstest(
        kerzen, strategie, parameter, cfg, RisikoGrenzen.aus_config(cfg),
        laeufe=2, parameter_jitter=0.2, seed=5,
    )

    assert ergebnis.laeufe == 2
    assert 0 <= ergebnis.laeufe_mit_trades <= 2


@pytest.mark.parametrize("laeufe", [0, -1])
def test_ungueltige_laufzahl_wird_abgelehnt(cfg, kerzen, laeufe):
    strategie, parameter = _strategie_und_parameter(cfg)
    with pytest.raises(ValueError, match="laeufe"):
        perturbationstest(
            kerzen, strategie, parameter, cfg, RisikoGrenzen.aus_config(cfg),
            laeufe=laeufe,
        )


def test_ungueltige_perturbationsbreiten_werden_abgelehnt(cfg, kerzen):
    strategie, parameter = _strategie_und_parameter(cfg)
    grenzen = RisikoGrenzen.aus_config(cfg)

    with pytest.raises(ValueError, match="preis_sigma"):
        perturbationstest(
            kerzen, strategie, parameter, cfg, grenzen, laeufe=1,
            preis_sigma=-0.1,
        )
    with pytest.raises(ValueError, match="parameter_jitter"):
        perturbationstest(
            kerzen, strategie, parameter, cfg, grenzen, laeufe=1,
            parameter_jitter=1.1,
        )


def test_fehlende_preisspalten_werden_abgelehnt(cfg, kerzen):
    strategie, parameter = _strategie_und_parameter(cfg)
    with pytest.raises(ValueError, match="fehlt Spalten"):
        perturbationstest(
            kerzen.drop(columns=["high"]), strategie, parameter, cfg,
            RisikoGrenzen.aus_config(cfg), laeufe=1,
        )
