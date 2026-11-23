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
class Signalplan:
    """Kausaler Plan für eine Long-Position.

    ``ziel`` ist die 0/1-Zielhaltung. ``stop`` ist optional und enthält je
    Bar mit positivem Ziel den Stop-Preis; ``None`` bedeutet ATR-Fallback. Bei
    ``reentry_sperre`` bleibt das Instrument nach einem Stop gesperrt, bis das
    Ziel wieder neutral war. Die Array-Schnittstelle bleibt kompatibel, damit
    bestehende Konsumenten zunächst nur das Ziel lesen können.
    """

    ziel: np.ndarray
    stop: np.ndarray | None = None
    reentry_sperre: bool = False

    @classmethod
    def aus_ziel(cls, ziel: Any) -> "Signalplan":
        """Erzeugt den rückwärtskompatiblen Plan ohne Stop und Sperre."""
        return cls(ziel=np.asarray(ziel, dtype=float))

    def __len__(self) -> int:
        return len(self.ziel)

    def __getitem__(self, index: Any) -> Any:
        return self.ziel[index]

    def __array__(self, dtype: Any = None, copy: Any = None) -> np.ndarray:
        werte = np.asarray(self.ziel, dtype=dtype)
        return werte.copy() if copy else werte


def _h1_retest(df: pd.DataFrame, p: dict[str, Any]) -> Signalplan:
    """H1-Retest: Breakout, Berührung des Levels und spätere Bestätigung.

    Das Level wird am Breakout festgeschrieben. Der Retest muss das Level
    berühren, ohne darunter zu schliessen; erst ein späterer H1-Schluss über
    dem Level setzt das Einstiegssignal. Der Stop liegt unter dem tiefsten
    Retest-Tief. Alle Werte sind aus abgeschlossenen Kerzen berechnet.
    """
    n = len(df)
    ziel = np.zeros(n, dtype=float)
    stop = np.full(n, np.nan, dtype=float)
    lookback = max(1, int(p["lookback"]))
    retest_fenster = max(1, int(p["retest_fenster"]))
    puffer = max(0.0, float(p["stop_puffer_pct"]))

    level = (
        df["high"].rolling(lookback, min_periods=lookback).max().shift(1)
        .to_numpy(dtype=float)
    )
    close = df["close"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)

    in_position = False
    breakout_level = np.nan
    positions_stop = np.nan
    retest_tief = np.nan
    retest_bar = -1
    setup_bar = -1

    for i in range(n):
        if in_position:
            # Ein Schluss unter dem festgeschriebenen Level beendet die
            # Position; sonst bleibt die Zielhaltung long.
            if close[i] < breakout_level:
                in_position = False
                continue
            ziel[i] = 1.0
            # Halte-Bars tragen denselben Stop: Ein Walk-Forward-Testfenster
            # kann mitten in der Haltedauer beginnen.
            stop[i] = positions_stop
            continue

        # Das Fenster umfasst die Kerzen setup_bar+1 bis setup_bar+F. Es endet
        # auch, wenn der Ausbruch vor der Bestätigung scheitert.
        if setup_bar >= 0 and (i - setup_bar > retest_fenster or close[i] < breakout_level):
            setup_bar = -1

        if setup_bar < 0:
            if np.isfinite(level[i]) and close[i] > level[i]:
                setup_bar = i
                breakout_level = float(level[i])
                retest_tief = np.nan
                retest_bar = -1
            continue

        if low[i] <= breakout_level:
            if retest_bar < 0:
                retest_bar = i
                retest_tief = float(low[i])
            else:
                retest_tief = min(retest_tief, float(low[i]))
        if retest_bar >= 0 and i > retest_bar and close[i] > breakout_level:
            stop_wert = retest_tief * (1.0 - puffer)
            if np.isfinite(stop_wert) and stop_wert > 0:
                ziel[i] = 1.0
                stop[i] = stop_wert
                positions_stop = stop_wert
                in_position = True
            setup_bar = -1

    return Signalplan(ziel=ziel, stop=stop, reentry_sperre=True)


@dataclass(frozen=True, slots=True)
class Strategie:
    name: str
    beschreibung: str
    warmup: int
    rechner: Callable[[pd.DataFrame, dict[str, Any]], pd.Series | Signalplan]
    grid: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    # Paare, bei denen der erste Parameter kleiner als der zweite bleiben muss.
    parameter_ordnung: tuple[tuple[str, str], ...] = ()

    def signale(self, df: pd.DataFrame, parameter: dict[str, Any]) -> Signalplan | np.ndarray:
        werte = self.rechner(df, parameter)
        if isinstance(werte, Signalplan):
            return werte
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
    # H1-Retest nur mit H1-Daten: Der Richter-Zeitrahmen bestimmt das Raster,
    # auf dem die Kandidaten laufen. Bei M15 bleibt die Strategie aus.
    retest_grid = []
    if cfg.richter_zeitrahmen == "H1":
        retest_grid = [
            {"lookback": lookback, "retest_fenster": fenster, "stop_puffer_pct": puffer}
            for lookback in r.get("h1_retest_lookback", ())
            for fenster in r.get("h1_retest_fenster", ())
            for puffer in r.get("h1_retest_stop_puffer_pct", ())
        ]

    auswahl = {
        "ema_cross": Strategie(
            name="ema_cross",
            beschreibung="Trendfolge: Long, solange der schnelle EMA über dem langsamen liegt. "
                         "Ausstieg bei Gegenkreuzung.",
            warmup=110,
            rechner=_ema_cross,
            grid=tuple(ema_grid),
            parameter_ordnung=(("fast", "slow"),),
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
            parameter_ordnung=(("buy_below", "exit_above"),),
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
    if retest_grid:
        auswahl["h1_retest"] = Strategie(
            name="h1_retest",
            beschreibung="H1-Retest: Ausbruch über das Hoch der letzten N H1-Kerzen, "
                         "Bestätigung erst nach einem Retest; Stop unter dem Retest-Tief, "
                         "Re-Entry nach Stop erst nach neutralem Ziel.",
            warmup=60,
            rechner=_h1_retest,
            grid=tuple(retest_grid),
        )
    return auswahl


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
