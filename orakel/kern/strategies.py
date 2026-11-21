from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

# Alle Signale sind kausal: Signal an Kerze i nutzt ausschliesslich Kerzen <= i.
# Der Backtest eröffnet erst zur Eröffnung von Kerze i+1 — nie zum selben Schlusskurs.


def _ema(reihe: pd.Series, spanne: int) -> pd.Series:
    return reihe.ewm(span=spanne, adjust=False, min_periods=spanne).mean()


def _rsi(close: pd.Series, periode: int) -> pd.Series:
    delta = close.diff()
    gewinn = delta.clip(lower=0.0)
    verlust = (-delta).clip(lower=0.0)
    avg_g = gewinn.ewm(alpha=1 / periode, adjust=False, min_periods=periode).mean()
    avg_v = verlust.ewm(alpha=1 / periode, adjust=False, min_periods=periode).mean()
    rs = avg_g / avg_v.replace(0.0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def atr(df: pd.DataFrame, periode: int = 14) -> pd.Series:
    hoch, tief, schluss = df["high"], df["low"], df["close"]
    vor = schluss.shift(1)
    tr = pd.concat([hoch - tief, (hoch - vor).abs(), (tief - vor).abs()], axis=1).max(axis=1)
    return tr.rolling(periode, min_periods=periode).mean()


def _zustand(einstieg: pd.Series, ausstieg: pd.Series) -> pd.Series:
    """Ereignisse in eine Positionshaltung (0/1) übersetzen. Ausstieg gewinnt am selben Balken."""
    s = pd.Series(np.nan, index=einstieg.index, dtype="float64")
    s[einstieg.fillna(False)] = 1.0
    s[ausstieg.fillna(False)] = 0.0
    return s.ffill().fillna(0.0)


def _ema_cross(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    fast, slow = _ema(df["close"], int(p["fast"])), _ema(df["close"], int(p["slow"]))
    return _zustand(fast > slow, fast < slow)


def _donchian(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    n = int(p["lookback"])
    ober = df["high"].rolling(n, min_periods=n).max().shift(1)
    unter = df["low"].rolling(n, min_periods=n).min().shift(1)
    return _zustand(df["close"] > ober, df["close"] < unter)


def _rsi_reversion(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    r = _rsi(df["close"], int(p.get("periode", 14)))
    return _zustand(r < float(p["buy_below"]), r > float(p["exit_above"]))


def _momentum(df: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    n = int(p["periode"])
    roc = df["close"].pct_change(n)
    return _zustand(roc > float(p.get("schwelle", 0.0)), roc < 0.0)


@dataclass(frozen=True, slots=True)
class Strategie:
    name: str
    beschreibung: str
    warmup: int
    rechner: Callable[[pd.DataFrame, dict[str, Any]], pd.Series]
    grid: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def signale(self, df: pd.DataFrame, parameter: dict[str, Any]) -> np.ndarray:
        werte = self.rechner(df, parameter)
        return werte.to_numpy(dtype=float)

    def schluessel(self, parameter: dict[str, Any]) -> str:
        teile = ",".join(f"{k}={parameter[k]}" for k in sorted(parameter))
        return f"{self.name}|{teile}"


def strategien(cfg: Any) -> dict[str, Strategie]:
    r = cfg["research"]
    ema_grid = [{"fast": f, "slow": s} for f in r["ema_fast"] for s in r["ema_slow"] if f < s]
    don_grid = [{"lookback": n} for n in r["donchian"]]
    rsi_grid = [
        {"periode": 14, "buy_below": b, "exit_above": e}
        for b in r["rsi_buy"] for e in r["rsi_exit"] if b < e
    ]
    roc_grid = [{"periode": n, "schwelle": 0.0} for n in r["roc_period"]]

    return {
        "ema_cross": Strategie(
            name="ema_cross",
            beschreibung="Trendfolge: Long, solange der schnelle EMA über dem langsamen liegt. "
                         "Ausstieg bei Gegenkreuzung.",
            warmup=110,
            rechner=_ema_cross,
            grid=tuple(ema_grid),
        ),
        "donchian": Strategie(
            name="donchian",
            beschreibung="Ausbruch: Long über dem Hoch der letzten N Kerzen, Ausstieg unter dem Tief. "
                         "Klassischer Trendfolger ohne Prognose.",
            warmup=60,
            rechner=_donchian,
            grid=tuple(don_grid),
        ),
        "rsi_reversion": Strategie(
            name="rsi_reversion",
            beschreibung="Rücksetzer-Kauf: Einstieg bei überverkauftem RSI, Ausstieg bei Erholung. "
                         "Gegenläufer im Seitwärtsmarkt.",
            warmup=30,
            rechner=_rsi_reversion,
            grid=tuple(rsi_grid),
        ),
        "momentum": Strategie(
            name="momentum",
            beschreibung="Momentum: Long, wenn die Rendite der letzten N Kerzen positiv ist, "
                         "Ausstieg bei negativer Rendite.",
            warmup=50,
            rechner=_momentum,
            grid=tuple(roc_grid),
        ),
    }


def kandidaten(cfg: Any) -> list[tuple[Strategie, dict[str, Any]]]:
    """Das freigegebene Parameter-Raster. Nichts ausserhalb dieser Liste wird getestet."""
    raus: list[tuple[Strategie, dict[str, Any]]] = []
    for strat in strategien(cfg).values():
        for parameter in strat.grid:
            raus.append((strat, dict(parameter)))
    return raus


def nachbarn(parameter: dict[str, Any], grid: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    """Parameter, die sich in genau einem Wert unterscheiden (Robustheits-Test)."""
    raus = []
    for kandidat in grid:
        unterschiede = [k for k in set(parameter) | set(kandidat) if parameter.get(k) != kandidat.get(k)]
        if len(unterschiede) == 1:
            raus.append(dict(kandidat))
    return raus
