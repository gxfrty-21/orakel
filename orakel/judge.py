"""Richter (C): feste Regeln, keine KI. Nur er entscheidet über Strategien.

Die Validierung ist rollierend:

1. Die letzten ``holdout_anteil`` der Kerzen werden versiegelt.
2. Im Entwicklungsteil werden mehrere aufeinanderfolgende Testfenster gebildet.
   Für jedes Fenster wird der Parameter **nur im davorliegenden Trainingsfenster**
   gewählt und danach im ungesehenen Testfenster geprüft.
3. Der versiegelte Holdout wird erst geöffnet, nachdem der beste Kandidat eines
   Symbols feststeht. Ein Fehlschlag dort führt nicht zu einem Fallback auf den
   zweitbesten Kandidaten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .backtest import BacktestErgebnis, backtest
from .config import Config, RisikoGrenzen
from .metrics import kennzahlen, max_drawdown_pct
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
    walk_forward_folds: list[dict[str, Any]] = field(default_factory=list)
    holdout: dict[str, Any] = field(default_factory=dict)
    holdout_ab: str = ""
    holdout_bestanden: bool | None = None

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
            "walk_forward_folds": self.walk_forward_folds,
            "holdout": self.holdout,
            "holdout_ab": self.holdout_ab,
            "holdout_bestanden": self.holdout_bestanden,
        }


def _zufallstest(
    df: pd.DataFrame, strategie: Strategie, parameter: dict[str, Any], cfg: Config,
    grenzen: RisikoGrenzen, von: int, bis: int, laeufe: int, seed: int = 11,
) -> float | None:
    """Zerstört die zeitliche Struktur (permutierte Renditen) und misst den Profit Factor.

    Der p-Wert ist der Anteil zufälliger Kurse, die mindestens so gut abschneiden.
    Es wird ausschliesslich der Datenausschnitt bis ``bis`` verwendet.
    """
    if bis - von < 200 or laeufe <= 0:
        return None
    df = df.iloc[:bis].reset_index(drop=True)
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


def _robustheit(
    df: pd.DataFrame, strategie: Strategie, parameter: dict[str, Any], cfg: Config,
    grenzen: RisikoGrenzen,
) -> float | None:
    """Anteil der Nachbar-Parameter, die im Entwicklungsteil profitabel sind."""
    if not parameter or not strategie.grid:
        return None
    liste = nachbarn(parameter, strategie.grid)
    if not liste:
        return None
    profitabel = 0
    for kandidat in liste:
        erg = backtest(df, strategie.signale(df, kandidat), cfg, grenzen)
        pf = erg.kennzahlen.get("profit_factor")
        if pf is not None and float(pf) > 1.0 and float(erg.kennzahlen.get("netto", 0.0)) > 0:
            profitabel += 1
    return round(profitabel / len(liste), 2)


def _aufteilung(n: int, v: dict[str, Any]) -> tuple[int, int, int, list[int]] | None:
    """Liefert (Entwicklungslänge, Holdout-Länge, Trainingsfenster, Fenstergrenzen)."""
    if n <= 0:
        return None
    holdout_anteil = float(v.get("holdout_anteil", 0.15))
    holdout_n = int(round(n * holdout_anteil))
    dev_n = n - holdout_n
    if holdout_n < 1 or dev_n < 1:
        return None

    fenster = int(v.get("walk_forward_fenster", 5))
    train_bars = int(dev_n * float(v.get("train_anteil", 0.7)))
    min_fold_bars = int(v.get("min_fold_bars", 50))
    if fenster < 2 or train_bars < 1 or dev_n - train_bars < fenster * min_fold_bars:
        return None

    grenzen = np.linspace(train_bars, dev_n, fenster + 1).astype(int).tolist()
    if any(b - a < min_fold_bars for a, b in zip(grenzen, grenzen[1:])):
        return None
    return dev_n, holdout_n, train_bars, grenzen


def _train_parameter(
    df: pd.DataFrame, strategie: Strategie, cfg: Config, grenzen: RisikoGrenzen,
    train_start: int, train_end: int,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Wählt den Parameter ausschliesslich anhand des Trainingsfensters."""
    v = cfg["validierung"]
    min_trades = int(v.get("min_train_trades", 5))
    prefix = df.iloc[:train_end].reset_index(drop=True)
    if prefix.empty or train_start >= train_end:
        return None

    best: tuple[tuple[float, float], dict[str, Any], dict[str, Any]] | None = None
    for parameter in strategie.grid:
        erg = backtest(
            prefix, strategie.signale(prefix, parameter), cfg, grenzen,
            start=train_start, ende=train_end,
        )
        k = erg.kennzahlen
        if int(k.get("trades", 0)) < min_trades:
            continue
        pf = k.get("profit_factor")
        netto = float(k.get("netto", 0.0))
        if pf is None or netto <= 0:
            continue
        score = (float(pf), netto)
        if best is None or score > best[0]:
            best = (score, dict(parameter), k)
    if best is None:
        return None
    return best[1], best[2]


def _wfo_fenster(
    df: pd.DataFrame, strategie: Strategie, cfg: Config, grenzen: RisikoGrenzen,
    grenzen_idx: list[int], train_bars: int,
) -> tuple[list[dict[str, Any]], list[BacktestErgebnis | None]]:
    details: list[dict[str, Any]] = []
    ergebnisse: list[BacktestErgebnis | None] = []

    for nr, (test_start, test_end) in enumerate(zip(grenzen_idx, grenzen_idx[1:]), start=1):
        train_end = int(test_start)
        train_start = max(0, train_end - train_bars)
        gewaehlt = _train_parameter(df, strategie, cfg, grenzen, train_start, train_end)
        if gewaehlt is None:
            details.append({
                "nr": nr,
                "parameter": {},
                "train_von": str(df["ts"].iloc[train_start])[:19],
                "train_bis": str(df["ts"].iloc[train_end - 1])[:19],
                "test_von": str(df["ts"].iloc[test_start])[:19],
                "test_bis": str(df["ts"].iloc[test_end - 1])[:19],
                "train": {},
                "test": {},
                "profitable": False,
                "grund": "Kein Parameter erfüllte die Mindestzahl an Trainings-Trades.",
            })
            ergebnisse.append(None)
            continue

        parameter, train_k = gewaehlt
        prefix = df.iloc[:test_end].reset_index(drop=True)
        erg = backtest(
            prefix, strategie.signale(prefix, parameter), cfg, grenzen,
            start=int(test_start), ende=int(test_end),
        )
        pf = erg.kennzahlen.get("profit_factor") or 0.0
        netto = float(erg.kennzahlen.get("netto", 0.0))
        details.append({
            "nr": nr,
            "parameter": parameter,
            "train_von": str(df["ts"].iloc[train_start])[:19],
            "train_bis": str(df["ts"].iloc[train_end - 1])[:19],
            "test_von": str(df["ts"].iloc[test_start])[:19],
            "test_bis": str(df["ts"].iloc[test_end - 1])[:19],
            "train": train_k,
            "test": erg.kennzahlen,
            "profitable": bool(netto > 0 and float(pf) > 1.0),
        })
        ergebnisse.append(erg)
    return details, ergebnisse


def _aggregiere(ergebnisse: list[BacktestErgebnis | None], cfg: Config) -> tuple[
    list[dict[str, Any]], list[float], list[list[Any]], dict[str, Any]
]:
    """Verkettet die Testfenster zu einer durchgehenden OOS-Kurve."""
    start = cfg.start_kapital
    trades: list[dict[str, Any]] = []
    kapital: list[float] = []
    kurve: list[list[Any]] = []
    gebuehren = 0.0
    zeit_gewichtet = 0.0
    bars = 0
    global_equity = start

    for erg in ergebnisse:
        if erg is None:
            continue
        shift = global_equity - start
        for ts, wert in erg.kapitalkurve:
            neuer_wert = round(float(wert) + shift, 2)
            kapital.append(neuer_wert)
            kurve.append([ts, neuer_wert])
        if erg.kapitalkurve:
            global_equity = float(erg.kapitalkurve[-1][1]) + shift
        trades.extend(erg.trades)
        gebuehren += float(erg.kennzahlen.get("gebuehren", 0.0))
        zeit_gewichtet += float(erg.zeit_im_markt_pct) * len(erg.kapital)
        bars += len(erg.kapital)

    zeit_im_markt = zeit_gewichtet / bars if bars else 0.0
    k = kennzahlen(trades, kapital, gebuehren, start, cfg.bars_pro_jahr, zeit_im_markt)
    return trades, kapital, kurve, k


def _pruefe_entwicklung(
    u: Urteil, df: pd.DataFrame, strategie: Strategie, cfg: Config,
    grenzen: RisikoGrenzen, dev_n: int, first_test_start: int,
) -> None:
    v = cfg["validierung"]
    oos = u.out_of_sample
    min_fold = float(v.get("min_fold_profitabel", 0.6))
    min_trades = int(v.get("min_walk_forward_trades", v.get("min_trades", 25)))

    checks: list[tuple[str, bool, str]] = [
        (f"Walk-Forward-Fenster profitabel ≥ {min_fold * 100:.0f} %",
         u.walk_forward_bestanden is not None and u.walk_forward_bestanden >= min_fold,
         f"{0 if u.walk_forward_bestanden is None else u.walk_forward_bestanden * 100:.0f} %"),
        ("Walk-Forward-Netto positiv", float(oos.get("netto", 0.0)) > 0,
         f"Netto {float(oos.get('netto', 0.0)):.2f}"),
        (f"Profit Factor Walk-Forward ≥ {v['min_profit_factor']}",
         oos.get("profit_factor") is not None
         and float(oos["profit_factor"]) >= float(v["min_profit_factor"]),
         f"Profit Factor {oos.get('profit_factor') if oos.get('profit_factor') is not None else '–'}"),
        (f"Drawdown Walk-Forward ≤ {v['max_drawdown_oos_pct']} %",
         float(oos.get("max_drawdown_pct", 100)) <= float(v["max_drawdown_oos_pct"]),
         f"Drawdown {float(oos.get('max_drawdown_pct', 0)):.2f} %"),
        (f"Mindestens {min_trades} Walk-Forward-Trades",
         int(oos.get("trades", 0)) >= min_trades,
         f"{int(oos.get('trades', 0))} Trades"),
        ("Gebühren durch Walk-Forward-Netto gedeckt",
         float(oos.get("gebuehren", 0.0)) < abs(float(oos.get("netto", 0.0))) + 1e-9,
         f"Gebühren {float(oos.get('gebuehren', 0.0)):.2f}"),
    ]
    sharpe_wert = oos.get("sharpe")
    if sharpe_wert is not None:
        checks.append((f"Sharpe Walk-Forward ≥ {v['min_sharpe']}",
                       float(sharpe_wert) >= float(v["min_sharpe"]),
                       f"Sharpe {sharpe_wert}"))

    for name, ok, detail in checks:
        if ok:
            u.erfuellt.append(f"{name} ({detail})")
        else:
            u.gruende.append(f"{name} — {detail}")
    if u.gruende:
        u.urteil = "abgelehnt"
        return

    # Diese Prüfungen sehen ausschliesslich den Entwicklungsteil, nie den Holdout.
    u.robustheit_anteil = _robustheit(
        df.iloc[:dev_n].reset_index(drop=True), strategie, u.parameter, cfg, grenzen
    )
    if u.robustheit_anteil is not None and u.robustheit_anteil < float(v["min_robustheit"]):
        u.gruende.append(
            f"Nicht robust: nur {u.robustheit_anteil * 100:.0f} % der Nachbar-Parameter "
            f"sind profitabel (min. {float(v['min_robustheit']) * 100:.0f} %)"
        )

    u.monte_carlo_dd_p95 = _monte_carlo(u.trades, int(v["monte_carlo_laeufe"]))
    if u.monte_carlo_dd_p95 is not None and u.monte_carlo_dd_p95 > float(v["max_drawdown_oos_pct"]) * 1.5:
        u.gruende.append(
            f"Monte-Carlo: 95 % der Pfade erreichen {u.monte_carlo_dd_p95} % Drawdown "
            f"(Grenze {float(v['max_drawdown_oos_pct']) * 1.5:.1f} %)"
        )

    u.zufall_p_wert = _zufallstest(
        df.iloc[:dev_n].reset_index(drop=True), strategie, u.parameter, cfg, grenzen,
        first_test_start, dev_n, int(v["zufallslaeufe"]),
    )
    if u.zufall_p_wert is not None and u.zufall_p_wert > float(v["max_zufall_p"]):
        u.gruende.append(
            f"Zufallsvergleich: p = {u.zufall_p_wert:.3f} — auch zufällige Kurse sind so gut "
            f"(max. {v['max_zufall_p']})"
        )

    u.urteil = "abgelehnt" if u.gruende else "bestanden"


def beurteile_walk_forward(
    df: pd.DataFrame, symbol: str, strategie: Strategie, cfg: Config, grenzen: RisikoGrenzen,
) -> Urteil:
    """Rollierende Walk-Forward-Prüfung ohne Öffnen des versiegelten Holdouts."""
    v = cfg["validierung"]
    u = Urteil(
        symbol=symbol,
        strategie=strategie.name,
        parameter={},
        beschreibung=strategie.beschreibung,
        urteil="abgelehnt",
    )

    n = len(df)
    if n < int(cfg["daten"]["min_kerzen"]):
        u.urteil = "zu wenig Daten"
        u.gruende.append(f"Nur {n} Kerzen — mindestens {cfg['daten']['min_kerzen']} nötig")
        return u

    auf = _aufteilung(n, v)
    if auf is None:
        u.urteil = "zu wenig Daten"
        u.gruende.append("Zu wenig Kerzen für Trainingsfenster, Walk-Forward und Holdout")
        return u
    dev_n, _, train_bars, grenzen_idx = auf
    u.holdout_ab = str(df["ts"].iloc[dev_n])[:19]

    final_start = max(0, dev_n - train_bars)
    final = _train_parameter(df, strategie, cfg, grenzen, final_start, dev_n)
    if final is None:
        u.gruende.append("Im finalen Trainingsfenster erfüllte kein Parameter die Mindestzahl an Trades")
        return u
    u.parameter, u.in_sample = final
    u.schluessel = strategie.schluessel(u.parameter)

    details, ergebnisse = _wfo_fenster(df, strategie, cfg, grenzen, grenzen_idx, train_bars)
    u.walk_forward_folds = details
    erfolgreich = sum(1 for d in details if d.get("profitable"))
    u.walk_forward_bestanden = round(erfolgreich / len(details), 2) if details else 0.0

    trades, _, kurve, oos = _aggregiere(ergebnisse, cfg)
    u.trades = trades
    u.kapitalkurve = kurve
    u.out_of_sample = oos
    first_test_start = int(grenzen_idx[0])
    u.oos_ab = str(df["ts"].iloc[first_test_start])[:19]

    basis = float(df["close"].iloc[first_test_start])
    if basis > 0:
        u.kaufen_halten_oos_pct = (float(df["close"].iloc[dev_n - 1]) / basis - 1) * 100

    prefix = df.iloc[:dev_n].reset_index(drop=True)
    gesamt = backtest(
        prefix, strategie.signale(prefix, u.parameter), cfg, grenzen, start=0, ende=dev_n
    )
    u.gesamt = gesamt.kennzahlen

    _pruefe_entwicklung(u, df, strategie, cfg, grenzen, dev_n, first_test_start)
    return u


def pruefe_holdout(
    u: Urteil, df: pd.DataFrame, strategie: Strategie, cfg: Config, grenzen: RisikoGrenzen,
) -> None:
    """Öffnet den versiegelten Holdout genau einmal für einen ausgewählten Kandidaten."""
    v = cfg["validierung"]
    if not u.parameter:
        u.holdout = {"bestanden": False, "gruende": ["Kein finaler Parameter vorhanden"]}
        u.holdout_bestanden = False
        u.urteil = "abgelehnt"
        u.gruende.append("Versiegelter Holdout: kein finaler Parameter vorhanden")
        return

    auf = _aufteilung(len(df), v)
    if auf is None:
        u.holdout = {"bestanden": False, "gruende": ["Holdout nicht abgrenzbar"]}
        u.holdout_bestanden = False
        u.urteil = "abgelehnt"
        u.gruende.append("Versiegelter Holdout: nicht abgrenzbar")
        return

    dev_n, _, _, _ = auf
    u.holdout_ab = str(df["ts"].iloc[dev_n])[:19]
    erg = backtest(
        df, strategie.signale(df, u.parameter), cfg, grenzen,
        start=dev_n, ende=len(df),
    )
    oos = erg.kennzahlen
    min_trades = int(v.get("min_holdout_trades", 10))
    gruende: list[str] = []
    checks = [
        (f"Mindestens {min_trades} Holdout-Trades", int(oos.get("trades", 0)) >= min_trades,
         f"{int(oos.get('trades', 0))} Trades"),
        ("Holdout-Netto positiv", float(oos.get("netto", 0.0)) > 0,
         f"Netto {float(oos.get('netto', 0.0)):.2f}"),
        (f"Profit Factor Holdout ≥ {v['min_profit_factor']}",
         oos.get("profit_factor") is not None
         and float(oos["profit_factor"]) >= float(v["min_profit_factor"]),
         f"Profit Factor {oos.get('profit_factor') if oos.get('profit_factor') is not None else '–'}"),
        (f"Drawdown Holdout ≤ {v['max_drawdown_oos_pct']} %",
         float(oos.get("max_drawdown_pct", 100)) <= float(v["max_drawdown_oos_pct"]),
         f"Drawdown {float(oos.get('max_drawdown_pct', 0)):.2f} %"),
        ("Gebühren durch Holdout-Netto gedeckt",
         float(oos.get("gebuehren", 0.0)) < abs(float(oos.get("netto", 0.0))) + 1e-9,
         f"Gebühren {float(oos.get('gebuehren', 0.0)):.2f}"),
    ]
    sharpe_wert = oos.get("sharpe")
    if sharpe_wert is not None:
        checks.append((f"Sharpe Holdout ≥ {v['min_sharpe']}",
                       float(sharpe_wert) >= float(v["min_sharpe"]),
                       f"Sharpe {sharpe_wert}"))
    for name, ok, detail in checks:
        if not ok:
            gruende.append(f"{name} — {detail}")

    basis = float(df["close"].iloc[dev_n])
    benchmark = (float(df["close"].iloc[-1]) / basis - 1) * 100 if basis > 0 else 0.0
    u.holdout = {
        "von": str(df["ts"].iloc[dev_n])[:19],
        "bis": str(df["ts"].iloc[-1])[:19],
        "kennzahlen": oos,
        "kaufen_halten_pct": round(benchmark, 2),
        "bestanden": not gruende,
        "gruende": gruende,
    }
    u.holdout_bestanden = not gruende
    if gruende:
        u.urteil = "abgelehnt"
        u.gruende.extend(f"Versiegelter Holdout: {grund}" for grund in gruende)
    else:
        u.erfuellt.append(
            f"Versiegelter Holdout bestanden (PF {oos.get('profit_factor')}, "
            f"{oos.get('trades', 0)} Trades)"
        )
    u.urteil = "abgelehnt" if u.gruende else "bestanden"
