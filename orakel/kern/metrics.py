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


def sortino(kapital: Sequence[float], bars_pro_jahr: int) -> float | None:
    """Annualisierte Sortino-Ratio gegen eine Zielrendite von null.

    Nur negative Renditen zählen als Abwärtsrisiko. Ohne mindestens 30
    Renditen oder ohne negative Rendite ist die Kennzahl nicht belastbar und
    bleibt ``None``.
    """
    if len(kapital) < 30:
        return None
    renditen = [jetzt / vor - 1 for vor, jetzt in zip(kapital, kapital[1:]) if vor > 0]
    if len(renditen) < 30:
        return None
    abwaerts = [min(0.0, r) for r in renditen]
    varianz = sum(r * r for r in abwaerts) / (len(abwaerts) - 1)
    if varianz <= 0:
        return None
    mittel = sum(renditen) / len(renditen)
    return round(mittel / math.sqrt(varianz) * math.sqrt(bars_pro_jahr), 2)


def kennzahlen(
    trades: Sequence[dict[str, Any]],
    kapital: Sequence[float],
    gebuehren: float,
    startkapital: float,
    bars_pro_jahr: int,
    zeit_im_markt_pct: float,
    finanzierung: float = 0.0,
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
    anzahl_gewinne = sum(1 for t in trades if float(t["netto"]) > 0)
    anzahl_verluste = sum(1 for t in trades if float(t["netto"]) < 0)
    haltezeiten = [float(t["bars"]) for t in trades
                   if t.get("bars") is not None and float(t["bars"]) >= 0]
    kosten = float(gebuehren) + float(finanzierung)
    brutto = netto + kosten
    return {
        "netto": round(netto, 2),
        "rendite_pct": round((endkapital / startkapital - 1) * 100, 2) if startkapital else 0.0,
        "profit_factor": pf,
        "trefferquote_pct": round(treffer / len(trades) * 100, 1) if trades else 0.0,
        "max_drawdown_pct": max_drawdown_pct(kapital),
        "trades": len(trades),
        "gebuehren": round(gebuehren, 2),
        "finanzierung": round(finanzierung, 2),
        "kosten_anteil_pct": round(kosten / brutto * 100, 1) if brutto > 0 else None,
        "zeit_im_markt_pct": round(zeit_im_markt_pct, 1),
        "sharpe": sharpe(kapital, bars_pro_jahr),
        "sortino": sortino(kapital, bars_pro_jahr),
        "erwartungswert": round(netto / len(trades), 2) if trades else 0.0,
        "avg_gewinn": round(gewinne / anzahl_gewinne, 2) if anzahl_gewinne else 0.0,
        "avg_verlust": round(-verluste / anzahl_verluste, 2) if anzahl_verluste else 0.0,
        "avg_halte_bars": round(sum(haltezeiten) / len(haltezeiten), 1) if haltezeiten else None,
        "endkapital": round(endkapital, 2),
    }


def leer() -> dict[str, Any]:
    return {
        "netto": 0.0, "rendite_pct": 0.0, "profit_factor": None, "trefferquote_pct": 0.0,
        "max_drawdown_pct": 0.0, "trades": 0, "gebuehren": 0.0,
        "finanzierung": 0.0, "kosten_anteil_pct": None, "zeit_im_markt_pct": 0.0,
        "sharpe": None, "sortino": None, "erwartungswert": 0.0,
        "avg_gewinn": 0.0, "avg_verlust": 0.0, "avg_halte_bars": None,
        "endkapital": 0.0,
    }
