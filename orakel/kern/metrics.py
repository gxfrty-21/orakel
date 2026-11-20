from __future__ import annotations

import math
from typing import Any, Sequence


def max_drawdown_pct(kapital: Sequence[float]) -> float:
    if not kapital:
        return 0.0
    hoechst = kapital[0]
    groesster = 0.0
    for wert in kapital:
        if wert > hoechst:
            hoechst = wert
        if hoechst > 0:
            dd = (hoechst - wert) / hoechst * 100
            groesster = max(groesster, dd)
    return round(groesster, 2)


def sharpe(kapital: Sequence[float], bars_pro_jahr: int) -> float | None:
    if len(kapital) < 30:
        return None
    renditen = []
    for vor, jetzt in zip(kapital, kapital[1:]):
        if vor > 0:
            renditen.append(jetzt / vor - 1)
    if len(renditen) < 30:
        return None
    mittel = sum(renditen) / len(renditen)
    varianz = sum((r - mittel) ** 2 for r in renditen) / (len(renditen) - 1)
    if varianz <= 0:
        return None
    return round(mittel / math.sqrt(varianz) * math.sqrt(bars_pro_jahr), 2)


def kennzahlen(
    trades: Sequence[dict[str, Any]],
    kapital: Sequence[float],
    gebuehren: float,
    startkapital: float,
    bars_pro_jahr: int,
    zeit_im_markt_pct: float,
) -> dict[str, Any]:
    netto = sum(float(t["netto"]) for t in trades)
    gewinne = sum(float(t["netto"]) for t in trades if float(t["netto"]) > 0)
    verluste = sum(-float(t["netto"]) for t in trades if float(t["netto"]) < 0)
    if verluste > 0:
        pf: float | None = round(gewinne / verluste, 2)
    else:
        pf = None if not gewinne else 99.0
    endkapital = kapital[-1] if kapital else startkapital
    treffer = sum(1 for t in trades if float(t["netto"]) > 0)
    return {
        "netto": round(netto, 2),
        "rendite_pct": round((endkapital / startkapital - 1) * 100, 2) if startkapital else 0.0,
        "profit_factor": pf,
        "trefferquote_pct": round(treffer / len(trades) * 100, 1) if trades else 0.0,
        "max_drawdown_pct": max_drawdown_pct(kapital),
        "trades": len(trades),
        "gebuehren": round(gebuehren, 2),
        "zeit_im_markt_pct": round(zeit_im_markt_pct, 1),
        "sharpe": sharpe(kapital, bars_pro_jahr),
        "endkapital": round(endkapital, 2),
    }


def leer() -> dict[str, Any]:
    return {
        "netto": 0.0, "rendite_pct": 0.0, "profit_factor": None, "trefferquote_pct": 0.0,
        "max_drawdown_pct": 0.0, "trades": 0, "gebuehren": 0.0, "zeit_im_markt_pct": 0.0,
        "sharpe": None, "endkapital": 0.0,
    }
