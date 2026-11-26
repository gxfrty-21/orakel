"""Isolierter Monte-Carlo-Perturbationstest für eine feste Strategie.

Der Test ist bewusst **kein Teil des Richters**. Er verändert weder die
Parameterwahl noch das Urteil, die Risikogrenzen oder den Paper-Takt. Statt
eines einzelnen Backtests werden viele leicht veränderte Preisreihen und
Parameterkombinationen geprüft und die Verteilung von Drawdown und
Profit Factor ausgewertet.

Die Preis-Perturbation legt kleine, kumulative Log-Return-Schocks auf die
Schlusskursreihe. Dadurch bleibt der Preisverlauf zusammenhängend und die
OHLC-Relationen einer Kerze bleiben erhalten. Die Signale werden anschließend
vollständig aus der perturbierten Reihe berechnet; es wird kein zukünftiger
Wert verwendet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..config import Config, RisikoGrenzen
from .backtest import backtest
from .strategies import Strategie

STANDARD_LAEUFE = 500
STANDARD_PREIS_SIGMA = 0.0005
STANDARD_PARAMETER_JITTER = 0.10
STANDARD_SEED = 20261122
PREISSPALTEN = ("open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class RobustheitsErgebnis:
    """Zusammenfassung eines Monte-Carlo-Perturbationslaufs."""

    laeufe: int
    laeufe_mit_trades: int
    basis_trades: int
    basis_drawdown_pct: float | None
    basis_profit_factor: float | None
    drawdown_p50_pct: float | None
    drawdown_p95_pct: float | None
    drawdown_max_pct: float | None
    profit_factor_p50: float | None
    profit_factor_p05: float | None
    profit_factor_ueber_1_anteil: float | None

    def als_dict(self) -> dict[str, Any]:
        return {
            "laeufe": self.laeufe,
            "laeufe_mit_trades": self.laeufe_mit_trades,
            "basis_trades": self.basis_trades,
            "basis_drawdown_pct": self.basis_drawdown_pct,
            "basis_profit_factor": self.basis_profit_factor,
            "drawdown_p50_pct": self.drawdown_p50_pct,
            "drawdown_p95_pct": self.drawdown_p95_pct,
            "drawdown_max_pct": self.drawdown_max_pct,
            "profit_factor_p50": self.profit_factor_p50,
            "profit_factor_p05": self.profit_factor_p05,
            "profit_factor_ueber_1_anteil": self.profit_factor_ueber_1_anteil,
        }


def _pruefe_preis_sigma(sigma: float) -> None:
    if not np.isfinite(sigma) or sigma < 0:
        raise ValueError("preis_sigma muss eine endliche Zahl >= 0 sein")


def _pruefe_parameter_jitter(anteil: float) -> None:
    if not np.isfinite(anteil) or not 0 <= anteil <= 1:
        raise ValueError("parameter_jitter muss zwischen 0 und 1 liegen")


def preise_perturbieren(
    df: pd.DataFrame, rng: np.random.Generator, sigma: float,
) -> pd.DataFrame:
    """Legt kumulative Log-Return-Schocks auf die Preisreihe.

    Die erste Kerze bleibt der Anker; jede folgende Kerze erhält einen Schock
    auf ihre Log-Rendite. Der daraus kumulierte Faktor wird auf Open, High, Low
    und Close derselben Kerze angewendet. Damit bleibt der Preisverlauf
    zusammenhängend, und Hoch >= Open/Close sowie Tief <= Open/Close bleiben
    erhalten. Zeitstempel und Volumen bleiben unverändert.
    """
    _pruefe_preis_sigma(sigma)
    neu = df.copy(deep=True)
    if sigma == 0 or neu.empty:
        return neu

    schocks = rng.normal(0.0, sigma, size=len(neu))
    schocks[0] = 0.0  # erste Kerze als Anker
    faktoren = np.exp(np.cumsum(schocks))
    neu[list(PREISSPALTEN)] = (
        neu[list(PREISSPALTEN)].to_numpy(dtype=float) * faktoren[:, None]
    )
    return neu


def parameter_perturbieren(
    parameter: dict[str, Any],
    rng: np.random.Generator,
    anteil: float,
    *,
    ordnung: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Jittert numerische Parameter um höchstens ``anteil`` relativ.

    Ganzzahlen bleiben Ganzzahlen und mindestens 1. Boolesche und textliche
    Werte werden unverändert übernommen. ``ordnung`` nennt Paare, bei denen der
    erste Wert kleiner als der zweite bleiben muss; die Strategie liefert diese
    Metadaten. Dadurch enthält die Funktion keine strategie-spezifischen
    Schlüsselnamen.
    """
    _pruefe_parameter_jitter(anteil)
    neu = dict(parameter)
    if anteil == 0:
        return neu

    for schluessel, wert in parameter.items():
        if isinstance(wert, bool) or not isinstance(wert, (int, float)):
            continue
        if not np.isfinite(wert) or wert == 0:
            continue

        geaendert = float(wert) * (1.0 + float(rng.uniform(-anteil, anteil)))
        if isinstance(wert, int):
            neu[schluessel] = max(1, int(round(geaendert)))
        else:
            neu[schluessel] = float(geaendert)

    for klein, gross in ordnung:
        if klein not in neu or gross not in neu:
            continue
        if neu[klein] < neu[gross]:
            continue
        if isinstance(neu[gross], int) and not isinstance(neu[gross], bool):
            if neu[gross] < 2:
                neu[gross] = 2
            neu[klein] = int(neu[gross]) - 1
        else:
            neu[klein] = float(np.nextafter(float(neu[gross]), -np.inf))
    return neu


def _perzentil(werte: list[float], q: float) -> float | None:
    if not werte:
        return None
    return round(float(np.percentile(werte, q)), 2)


def _basis_wert(kennzahlen: dict[str, Any], schluessel: str) -> float | None:
    wert = kennzahlen.get(schluessel)
    return None if wert is None else float(wert)


def perturbationstest(
    df: pd.DataFrame,
    strategie: Strategie,
    parameter: dict[str, Any],
    cfg: Config,
    grenzen: RisikoGrenzen,
    *,
    laeufe: int = STANDARD_LAEUFE,
    preis_sigma: float = STANDARD_PREIS_SIGMA,
    parameter_jitter: float = STANDARD_PARAMETER_JITTER,
    seed: int = STANDARD_SEED,
    symbol: str = "",
) -> RobustheitsErgebnis:
    """Führt den isolierten Monte-Carlo-Perturbationstest aus.

    Jeder Lauf kombiniert eine leicht gestörte Preisreihe mit leicht gestörten
    Parametern. Ausgewertet werden der maximale Drawdown und der Profit Factor
    jedes Laufs. Die Rückgabe enthält Perzentile und den Anteil der Läufe mit
    Profit Factor > 1. Läufe ohne Trades zählen für den Drawdown, aber nicht
    für die Profit-Factor-Verteilung.

    Die Funktion verändert weder ``df`` noch ``parameter``, ``cfg`` oder
    ``grenzen``. ``seed`` macht den Lauf reproduzierbar.
    """
    if laeufe < 1:
        raise ValueError("laeufe muss mindestens 1 sein")
    _pruefe_preis_sigma(preis_sigma)
    _pruefe_parameter_jitter(parameter_jitter)

    fehlend = {"open", "high", "low", "close"} - set(df.columns)
    if fehlend:
        raise ValueError(f"df fehlt Spalten: {', '.join(sorted(fehlend))}")
    if df.empty:
        raise ValueError("df darf nicht leer sein")

    basis = backtest(
        df, strategie.signale(df, parameter), cfg, grenzen, symbol=symbol,
    )
    basis_k = basis.kennzahlen
    basis_trades = int(basis_k.get("trades", 0))

    rng = np.random.default_rng(seed)
    drawdowns: list[float] = []
    profit_factors: list[float] = []
    laeufe_mit_trades = 0

    for _ in range(laeufe):
        df_neu = preise_perturbieren(df, rng, preis_sigma)
        parameter_neu = parameter_perturbieren(
            parameter, rng, parameter_jitter, ordnung=strategie.parameter_ordnung,
        )
        erg = backtest(
            df_neu, strategie.signale(df_neu, parameter_neu), cfg, grenzen,
            symbol=symbol,
        )
        k = erg.kennzahlen
        if not k:
            continue

        drawdown = k.get("max_drawdown_pct")
        if drawdown is not None:
            drawdowns.append(float(drawdown))

        if int(k.get("trades", 0)) > 0:
            laeufe_mit_trades += 1
        profit_factor = k.get("profit_factor")
        if profit_factor is not None:
            profit_factors.append(float(profit_factor))

    ueber_eins = (
        round(sum(1 for pf in profit_factors if pf > 1.0) / len(profit_factors), 3)
        if profit_factors else None
    )
    return RobustheitsErgebnis(
        laeufe=laeufe,
        laeufe_mit_trades=laeufe_mit_trades,
        basis_trades=basis_trades,
        basis_drawdown_pct=_basis_wert(basis_k, "max_drawdown_pct"),
        basis_profit_factor=_basis_wert(basis_k, "profit_factor"),
        drawdown_p50_pct=_perzentil(drawdowns, 50),
        drawdown_p95_pct=_perzentil(drawdowns, 95),
        drawdown_max_pct=round(max(drawdowns), 2) if drawdowns else None,
        profit_factor_p50=_perzentil(profit_factors, 50),
        profit_factor_p05=_perzentil(profit_factors, 5),
        profit_factor_ueber_1_anteil=ueber_eins,
    )
