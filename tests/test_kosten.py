"""Kostenmodell: Stück-Kommission für Aktien, halber Spread für Devisen."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from orakel.config import Config, RisikoGrenzen, validiere_config
from orakel.kern.backtest import backtest
from orakel.kern.kosten import instrument, kosten_je_seite, kostenmodell

WURZEL = Path(__file__).resolve().parents[1]


def _daten(**kosten: Any) -> dict[str, Any]:
    """Die echte config.toml, optional mit geänderten Kostenwerten."""
    daten = tomllib.loads((WURZEL / "config.toml").read_text(encoding="utf-8"))
    daten["kosten"].update(kosten)
    return daten


def _cfg(tmp_path: Path, **kosten: Any) -> Config:
    return Config(_daten(**kosten), tmp_path / "config.toml")


def _reihe(n: int = 60, kurs: float = 1.1) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "ts": ts, "open": [kurs] * n, "high": [kurs + 0.001] * n,
        "low": [kurs - 0.001] * n, "close": [kurs] * n, "volume": [100.0] * n,
    })


def test_standardmodell_ist_stueck(tmp_path):
    assert kostenmodell(_cfg(tmp_path)) == "stueck"


def test_instrumentenklasse_wird_aus_dem_symbol_abgeleitet():
    assert instrument("EURUSD").pip_groesse == pytest.approx(0.0001)
    assert instrument("usdjpy").pip_groesse == pytest.approx(0.01)
    assert instrument("EURUSD").klasse == "fx"
    assert instrument("USDJPY").klasse == "fx_jpy"
    # Broker-Zusätze hinter einem Punkt ändern die Klasse nicht.
    assert instrument("EURUSD.a").klasse == "fx"
    assert instrument("US500").klasse == "index"
    # Unbekannte Symbole (Aktien) haben kein Profil und nutzen [kosten].
    assert instrument("AAPL") is None
    assert instrument(None) is None


def test_kosten_je_symbol_nutzen_das_instrumentprofil(tmp_path):
    # config.toml bleibt bewusst auf dem Stück-Modell; das Symbol entscheidet.
    cfg = _cfg(tmp_path, modell="stueck")

    # EURUSD: 18'500 × 1 Pip × 0.0001 / 2
    assert kosten_je_seite(18_500, cfg, "EURUSD") == pytest.approx(0.925)
    # USDJPY: gleiche Menge, aber 1 Pip = 0.01
    assert kosten_je_seite(18_500, cfg, "USDJPY") == pytest.approx(92.5)
    # US500: 0.5 Punkte Spread, 1 Punkt je Pip → 10 × 0.5 × 1.0 / 2
    assert kosten_je_seite(10, cfg, "US500") == pytest.approx(2.5)
    # Unbekanntes Symbol: Stück-Modell mit Mindestkommission wie bisher.
    assert kosten_je_seite(10, cfg, "AAPL") == pytest.approx(1.0)


def test_backtest_rechnet_mit_dem_pip_des_symbols(tmp_path):
    cfg = _cfg(tmp_path, modell="stueck", slippage_bps=0.0)
    signale = np.zeros(60)
    signale[30:45] = 1.0

    for symbol, kurs in (("EURUSD", 1.1), ("USDJPY", 150.0)):
        erg = backtest(_reihe(kurs=kurs), signale, cfg, RisikoGrenzen.aus_config(cfg),
                       symbol=symbol)
        assert erg.trades, f"{symbol}: Es muss ein Trade entstanden sein"
        erwartet = 2 * kosten_je_seite(erg.trades[0]["stueck"], cfg, symbol)
        assert erg.kennzahlen["gebuehren"] == pytest.approx(erwartet, abs=0.01)


def test_stueck_modell_nutzt_kommission_und_minimum(tmp_path):
    cfg = _cfg(tmp_path, commission_per_share=0.005, min_commission=1.0)

    assert kosten_je_seite(1000, cfg) == pytest.approx(5.0)
    # Kleine Menge: das Minimum greift.
    assert kosten_je_seite(10, cfg) == pytest.approx(1.0)


def test_spread_modell_zahlt_halben_spread_je_seite(tmp_path):
    cfg = _cfg(tmp_path, modell="spread", spread_pips=1.0, pip_groesse=0.0001)

    # 18'500 Einheiten × 1 Pip × 0.0001 / 2
    assert kosten_je_seite(18_500, cfg) == pytest.approx(0.925)
    assert 2 * kosten_je_seite(18_500, cfg) == pytest.approx(1.85)


def test_spread_ist_bei_forex_rund_hundertmal_billiger_als_stueck(tmp_path):
    stueck = _cfg(tmp_path, commission_per_share=0.005, min_commission=1.0)
    spread = _cfg(tmp_path, modell="spread", spread_pips=1.0, pip_groesse=0.0001)

    assert kosten_je_seite(18_500, stueck) == pytest.approx(92.5)
    assert kosten_je_seite(18_500, stueck) / kosten_je_seite(18_500, spread) \
        == pytest.approx(100.0)


def test_backtest_bucht_spread_auf_beiden_seiten(tmp_path):
    cfg = _cfg(tmp_path, modell="spread", spread_pips=1.0, pip_groesse=0.0001,
               slippage_bps=0.0)
    signale = np.zeros(60)
    signale[30:45] = 1.0

    erg = backtest(_reihe(), signale, cfg, RisikoGrenzen.aus_config(cfg))

    assert erg.trades, "Es muss ein Trade entstanden sein"
    erwartet = 2 * kosten_je_seite(erg.trades[0]["stueck"], cfg)
    assert erg.kennzahlen["gebuehren"] == pytest.approx(erwartet, abs=0.01)


def test_gepruefte_config_toml_ist_gueltig():
    validiere_config(_daten())


def test_unbekanntes_kostenmodell_wird_abgelehnt():
    with pytest.raises(ValueError, match="modell muss"):
        validiere_config(_daten(modell="pro_lot"))


def test_negativer_spread_wird_abgelehnt():
    with pytest.raises(ValueError, match="spread_pips"):
        validiere_config(_daten(modell="spread", spread_pips=-1.0))


def test_pip_groesse_muss_positiv_sein():
    with pytest.raises(ValueError, match="pip_groesse"):
        validiere_config(_daten(pip_groesse=0.0))
