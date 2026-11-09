"""Richter (C): feste Regeln, keine KI. Nur er entscheidet über Strategien."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .backtest import BacktestErgebnis, backtest
from .config import Config, RisikoGrenzen
from .metrics import max_drawdown_pct
from .strategies import Strategie, nachbarn


@dataclass(slots=True)
class Urteil:
    symbol: str
    strategie: str
    parameter: dict[str, Any]
    beschreibung: str
    urteil: str
    gruende: list[str] = field(default_factory=list)
    erfuellt: list[str] = field(default_factory=list)
    in_sample: dict[str, Any] = field(default_factory=dict)
    out_of_sample: dict[str, Any] = field(default_factory=dict)
    gesamt: dict[str, Any] = field(default_factory=dict)
    kaufen_halten_oos_pct: float = 0.0
    robustheit_anteil: float | None = None
    zufall_p_wert: float | None = None
    oos_ab: str = ""
    kapitalkurve: list[list[Any]] | None = None
    trades: list[dict[str, Any]] = field(default_factory=list)
    schluessel: str = ""
    monte_carlo_dd_p95: float | None = None
    walk_forward_bestanden: float | None = None

    def als_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategie": self.strategie,
            "parameter": self.parameter,
            "beschreibung": self.beschreibung,
            "urteil": self.urteil,
            "gruende": self.gruende,
            "erfuellt": self.erfuellt,
            "in_sample": self.in_sample,
            "out_of_sample": self.out_of_sample,
            "gesamt": self.gesamt,
            "kaufen_halten_oos_pct": round(self.kaufen_halten_oos_pct, 2),
            "robustheit_anteil": self.robustheit_anteil,
            "zufall_p_wert": self.zufall_p_wert,
            "oos_ab": self.oos_ab,
            "kapitalkurve": self.kapitalkurve,
            "trades": self.trades,
            "schluessel": self.schluessel,
            "monte_carlo_dd_p95": self.monte_carlo_dd_p95,
            "walk_forward_bestanden": self.walk_forward_bestanden,
        }


def _zufallstest(
    df: pd.DataFrame, strategie: Strategie, parameter: dict[str, Any], cfg: Config,
    grenzen: RisikoGrenzen, von: int, bis: int, laeufe: int, seed: int = 11,
) -> float | None:
    """Zerstört die zeitliche Struktur (permutierte Renditen) und misst den Profit Factor.

    Der p-Wert ist der Anteil zufälliger Kurse, die mindestens so gut abschneiden.
    """
    if bis - von < 200 or laeufe <= 0:
        return None
    rng = np.random.default_rng(seed)
    close = df["close"].to_numpy(dtype=float)
    if np.any(close <= 0):
        return None
    logret = np.diff(np.log(close), prepend=np.log(close[0]))
    echt = backtest(df, strategie.signale(df, parameter), cfg, grenzen, start=von, ende=bis)
    pf_echt = echt.kennzahlen.get("profit_factor") or 0.0
    besser = 0
    for _ in range(laeufe):
        perm = rng.permutation(logret[1:])
        neu = close[0] * np.exp(np.cumsum(np.concatenate([[0.0], perm])))
        faktor = neu / close
        df2 = df.copy()
        for spalte in ("open", "high", "low", "close"):
            df2[spalte] = df[spalte].to_numpy() * faktor
        erg = backtest(df2, strategie.signale(df2, parameter), cfg, grenzen, start=von, ende=bis)
        if (erg.kennzahlen.get("profit_factor") or 0.0) >= pf_echt:
            besser += 1
    return round(besser / laeufe, 4)


def _monte_carlo(trades: list[dict[str, Any]], laeufe: int, seed: int = 5) -> float | None:
    """Bootstrap der Trade-Reihenfolge: Wie schlimm kann der Drawdown werden?"""
    if len(trades) < 10 or laeufe <= 0:
        return None
    rng = np.random.default_rng(seed)
    pnl = np.array([float(t["netto"]) for t in trades])
    dds: list[float] = []
    for _ in range(laeufe):
        reihe = rng.choice(pnl, size=len(pnl), replace=True)
        kapital = 100_000.0 + np.cumsum(reihe)
        dds.append(max_drawdown_pct(kapital.tolist()))
    return round(float(np.percentile(dds, 95)), 2)


def _walk_forward(
    df: pd.DataFrame, strategie: Strategie, parameter: dict[str, Any], cfg: Config,
    grenzen: RisikoGrenzen, von: int, bis: int, fenster: int,
) -> float | None:
    if fenster < 2 or bis - von < fenster * 100:
        return None
    grenzen_idx = np.linspace(von, bis, fenster + 1).astype(int)
    gut = 0
    for a, b in zip(grenzen_idx, grenzen_idx[1:]):
        erg = backtest(df, strategie.signale(df, parameter), cfg, grenzen, start=int(a), ende=int(b))
        pf = erg.kennzahlen.get("profit_factor")
        if pf is not None and pf > 1.0:
            gut += 1
    return round(gut / fenster, 2)


def _robustheit(
    df: pd.DataFrame, strategie: Strategie, parameter: dict[str, Any], cfg: Config,
    grenzen: RisikoGrenzen,
) -> float | None:
    kandidaten = nachbarn(parameter, strategie.grid)
    if not kandidaten:
        return None
    profitabel = 0
    for kandidat in kandidaten:
        erg = backtest(df, strategie.signale(df, kandidat), cfg, grenzen)
        if float(erg.kennzahlen.get("netto", 0.0)) > 0:
            profitabel += 1
    return round(profitabel / len(kandidaten), 2)


def beurteile(
    df: pd.DataFrame,
    symbol: str,
    strategie: Strategie,
    parameter: dict[str, Any],
    cfg: Config,
    grenzen: RisikoGrenzen,
) -> Urteil:
    v = cfg["validierung"]
    u = Urteil(
        symbol=symbol,
        strategie=strategie.name,
        parameter=dict(parameter),
        beschreibung=strategie.beschreibung,
        urteil="abgelehnt",
        schluessel=strategie.schluessel(parameter),
    )

    signale = strategie.signale(df, parameter)
    n = len(df)
    if n < int(cfg["daten"]["min_kerzen"]) or not np.isfinite(signale).any():
        u.urteil = "zu wenig Daten"
        u.gruende.append(f"Nur {n} Kerzen — mindestens {cfg['daten']['min_kerzen']} nötig")
        return u

    split = int(n * float(v["train_anteil"]))
    u.oos_ab = str(df["ts"].iloc[split])[:19]

    gesamt: BacktestErgebnis = backtest(df, signale, cfg, grenzen)
    training: BacktestErgebnis = backtest(df, signale, cfg, grenzen, start=0, ende=split)
    ungesehen: BacktestErgebnis = backtest(df, signale, cfg, grenzen, start=split, ende=n)

    u.gesamt = gesamt.kennzahlen
    u.in_sample = training.kennzahlen
    u.out_of_sample = ungesehen.kennzahlen
    u.trades = gesamt.trades

    basis = float(df["close"].iloc[split])
    if basis > 0:
        u.kaufen_halten_oos_pct = (float(df["close"].iloc[-1]) / basis - 1) * 100

    if gesamt.kennzahlen.get("trades", 0) < int(v["min_trades"]):
        u.urteil = "zu wenig Daten"
        u.gruende.append(
            f"Nur {gesamt.kennzahlen.get('trades', 0)} Trades — mindestens {v['min_trades']} nötig"
        )
        return u

    oos = ungesehen.kennzahlen
    pf = oos.get("profit_factor")
    checks: list[tuple[str, bool, str]] = [
        ("Ungesehener Teil ist profitabel", float(oos.get("netto", 0)) > 0,
         f"Netto ungesehen {oos.get('netto', 0):.2f}"),
        (f"Profit Factor ungesehen ≥ {v['min_profit_factor']}", pf is not None and pf >= float(v["min_profit_factor"]),
         f"Profit Factor {pf if pf is not None else '–'}"),
        (f"Drawdown ungesehen ≤ {v['max_drawdown_oos_pct']} %",
         float(oos.get("max_drawdown_pct", 100)) <= float(v["max_drawdown_oos_pct"]),
         f"Drawdown {oos.get('max_drawdown_pct', 0):.2f} %"),
        ("Mehr Trades als Gebühren wert sind",
         float(gesamt.kennzahlen.get("gebuehren", 0)) < abs(float(gesamt.kennzahlen.get("netto", 0))) + 1e-9,
         f"Gebühren {gesamt.kennzahlen.get('gebuehren', 0):.2f}"),
    ]
    sharpe_wert = oos.get("sharpe")
    if sharpe_wert is not None:
        checks.append((f"Sharpe ungesehen ≥ {v['min_sharpe']}", float(sharpe_wert) >= float(v["min_sharpe"]),
                       f"Sharpe {sharpe_wert}"))

    for name, ok, detail in checks:
        if ok:
            u.erfuellt.append(f"{name} ({detail})")
        else:
            u.gruende.append(f"{name} — {detail}")

    # Teure Prüfungen nur, wenn die billigen Regeln bestanden sind
    if not u.gruende:
        u.robustheit_anteil = _robustheit(df, strategie, parameter, cfg, grenzen)
        if u.robustheit_anteil is not None and u.robustheit_anteil < float(v["min_robustheit"]):
            u.gruende.append(
                f"Nicht robust: nur {u.robustheit_anteil * 100:.0f} % der Nachbar-Parameter sind profitabel "
                f"(min. {float(v['min_robustheit']) * 100:.0f} %)"
            )

        u.walk_forward_bestanden = _walk_forward(
            df, strategie, parameter, cfg, grenzen, 0, split, int(v["walk_forward_fenster"])
        )
        if u.walk_forward_bestanden is not None and u.walk_forward_bestanden < 0.67:
            u.gruende.append(
                f"Walk-Forward: nur {u.walk_forward_bestanden * 100:.0f} % der Fenster profitabel (min. 67 %)"
            )

        u.monte_carlo_dd_p95 = _monte_carlo(u.trades, int(v["monte_carlo_laeufe"]))
        if u.monte_carlo_dd_p95 is not None and u.monte_carlo_dd_p95 > float(v["max_drawdown_oos_pct"]) * 1.5:
            u.gruende.append(
                f"Monte-Carlo: 95 % der Pfade erreichen {u.monte_carlo_dd_p95} % Drawdown "
                f"(Grenze {float(v['max_drawdown_oos_pct']) * 1.5:.1f} %)"
            )

        u.zufall_p_wert = _zufallstest(
            df, strategie, parameter, cfg, grenzen, split, n, int(v["zufallslaeufe"])
        )
        if u.zufall_p_wert is not None and u.zufall_p_wert > float(v["max_zufall_p"]):
            u.gruende.append(
                f"Zufallsvergleich: p = {u.zufall_p_wert:.3f} — auch zufällige Kurse sind so gut "
                f"(max. {v['max_zufall_p']})"
            )

    u.urteil = "abgelehnt" if u.gruende else "bestanden"
    if u.urteil == "bestanden":
        u.kapitalkurve = gesamt.kapitalkurve
    return u
