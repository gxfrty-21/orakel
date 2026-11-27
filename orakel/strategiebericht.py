"""Reproduzierbarer Strategie-Bericht: jede Strategie, jedes Symbol, mit Holdout.

Der Bericht beantwortet die Frage, ob eine Strategie nach Kosten besser abschneidet
als Kaufen und Halten. Er zeigt bewusst **alle** Kandidaten, auch abgelehnte: ein
Bericht, der nur Gewinner listet, ist kein Nachweis.

Abgrenzung zum Handelspfad: ``pipeline.lauf`` öffnet den versiegelten Holdout nur für
den besten Walk-Forward-Kandidaten je Symbol und wählt danach aus. Dieser Bericht
öffnet den Holdout für **jede** Strategie, weil sonst keine Aussage über die
abgelehnten möglich wäre. Er ändert keine Auswahl und keine Handelsentscheidung; die
Zahl der geprüften Parameterkombinationen steht deshalb im Bericht, und der
p-Wert wird zusätzlich nach Bonferroni über diese Kombinationen korrigiert.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Config, RisikoGrenzen
from .kern.judge import aufteilung, beurteile_walk_forward, pruefe_holdout
from .kern.strategies import Strategie, atr, strategien

SCHEMA = "strategie-bericht.v1"


def kaufen_halten_pct(df: pd.DataFrame, von: int, bis: int) -> float:
    """Rendite eines Kaufs bei ``von`` und Verkaufs bei ``bis - 1`` (in Prozent)."""
    if bis <= von or von < 0 or bis > len(df):
        return 0.0
    basis = float(df["close"].iloc[von])
    if basis <= 0:
        return 0.0
    return round((float(df["close"].iloc[bis - 1]) / basis - 1) * 100, 2)


def _zeitraum(df: pd.DataFrame, von: int, bis: int) -> dict[str, str]:
    if bis <= von:
        return {"von": "", "bis": ""}
    return {"von": str(df["ts"].iloc[von])[:19], "bis": str(df["ts"].iloc[bis - 1])[:19]}


def _regime_serien(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Trend- und Volatilitätsregime je Kerze, ausschliesslich kausal.

    Trend = Schlusskurs über/unter EMA200. Volatilität = ATR(14) relativ zum
    Schlusskurs, verglichen mit dem rollierenden Median der letzten 250 Kerzen.
    Die ersten 200 bzw. 50 Kerzen bleiben «unklar», statt eine Richtung zu
    erfinden.
    """
    close = df["close"].astype(float)
    ema = close.ewm(span=200, min_periods=200).mean()
    atr_pct = atr(df, 14) / close.replace(0.0, float("nan"))
    median = atr_pct.rolling(250, min_periods=50).median()
    trend: list[str] = []
    volatilitaet: list[str] = []
    for kurs, mittel, wert, grenze in zip(close, ema, atr_pct, median):
        if pd.isna(mittel):
            trend.append("unklar")
        elif kurs > mittel:
            trend.append("aufwärts")
        elif kurs < mittel:
            trend.append("abwärts")
        else:
            trend.append("neutral")
        if pd.isna(wert) or pd.isna(grenze):
            volatilitaet.append("unklar")
        elif wert > grenze:
            volatilitaet.append("hoch")
        else:
            volatilitaet.append("niedrig")
    return trend, volatilitaet


def _regime_aggregat(df: pd.DataFrame, trades: list[dict[str, Any]],
                    art: str) -> dict[str, dict[str, Any]]:
    """Nettorendite und Trefferquote je Trend- oder Volatilitätsregime."""
    if not trades:
        return {}
    trend, volatilitaet = _regime_serien(df)
    serie = trend if art == "trend" else volatilitaet
    index = {str(ts)[:19]: i for i, ts in enumerate(df["ts"])}
    gruppen: dict[str, dict[str, Any]] = {}
    for trade in trades:
        i = index.get(str(trade.get("einstieg", ""))[:19])
        if i is None or i >= len(serie):
            continue
        name = serie[i]
        gruppe = gruppen.setdefault(name, {"trades": 0, "netto": 0.0, "gewinner": 0})
        gruppe["trades"] += 1
        gruppe["netto"] += float(trade.get("netto", 0.0))
        if float(trade.get("netto", 0.0)) > 0:
            gruppe["gewinner"] += 1
    for gruppe in gruppen.values():
        gruppe["netto"] = round(gruppe["netto"], 2)
        gruppe["trefferquote_pct"] = (
            round(gruppe["gewinner"] / gruppe["trades"] * 100, 1)
            if gruppe["trades"] else 0.0
        )
    return dict(sorted(gruppen.items()))


def _diagnose(df: pd.DataFrame, trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Warum die Trades endeten und wie sie über Marktregime verteilt waren.

    Die Zahlen sind eine Diagnose, keine zusätzliche Bestehensbedingung. Sie
    machen sichtbar, ob eine Strategie vor allem an Stops, an Signalen, an
    einem Regime oder an zu wenigen Trades scheitert.
    """
    gruende = Counter(str(t.get("grund", "unbekannt")) for t in trades)
    bars = [float(t["bars"]) for t in trades if t.get("bars") is not None]
    return {
        "ausstiege": dict(sorted(gruende.items(), key=lambda paar: (-paar[1], paar[0]))),
        "gewinner": sum(1 for t in trades if float(t.get("netto", 0.0)) > 0),
        "verlierer": sum(1 for t in trades if float(t.get("netto", 0.0)) < 0),
        "avg_bars": round(sum(bars) / len(bars), 1) if bars else None,
        "min_bars": int(min(bars)) if bars else None,
        "max_bars": int(max(bars)) if bars else None,
        "regime_trend": _regime_aggregat(df, trades, "trend"),
        "regime_volatilitaet": _regime_aggregat(df, trades, "volatilitaet"),
    }


def _eintrag(u: Any, df: pd.DataFrame, strategie: Strategie, cfg: Config) -> dict[str, Any]:
    """Ein Kandidat mit Entwicklungs-, Walk-Forward- und Holdout-Zahlen."""
    auf = aufteilung(len(df), cfg)
    dev_n = auf[0] if auf else len(df)
    wf_start = auf[3][0] if auf else 0
    kombinationen = len(strategie.grid)
    p_wert = u.zufall_p_wert
    p_bonferroni = None if p_wert is None else round(min(1.0, p_wert * kombinationen), 4)

    holdout = dict(u.holdout or {})
    holdout_k = dict(holdout.get("kennzahlen") or {})
    wf_k = dict(u.out_of_sample or {})
    wf_benchmark = kaufen_halten_pct(df, wf_start, dev_n) if auf else 0.0
    holdout_benchmark = holdout.get("kaufen_halten_pct")
    return {
        "symbol": u.symbol,
        "strategie": u.strategie,
        "beschreibung": u.beschreibung,
        "parameter": u.parameter,
        "parameterkombinationen": kombinationen,
        "urteil": u.urteil,
        "gruende": list(u.gruende),
        "erfuellt": list(u.erfuellt),
        "entwicklung": {
            "zeitraum": _zeitraum(df, 0, dev_n),
            "kennzahlen": dict(u.gesamt or {}),
            "kaufen_halten_pct": kaufen_halten_pct(df, 0, dev_n),
        },
        "walk_forward": {
            "zeitraum": _zeitraum(df, wf_start, dev_n),
            "kennzahlen": wf_k,
            "kaufen_halten_pct": wf_benchmark,
            "mehrwert_gegen_kaufen_halten_pct": (
                round(float(wf_k["rendite_pct"]) - float(wf_benchmark), 2)
                if wf_k.get("rendite_pct") is not None else None
            ),
            "fenster_bestanden_pct": (
                None if u.walk_forward_bestanden is None
                else round(float(u.walk_forward_bestanden) * 100, 0)
            ),
            "fenster": list(u.walk_forward_folds or []),
        },
        "holdout": {
            "zeitraum": {"von": holdout.get("von", u.holdout_ab), "bis": holdout.get("bis", "")},
            "kennzahlen": holdout_k,
            "kaufen_halten_pct": holdout_benchmark,
            "mehrwert_gegen_kaufen_halten_pct": (
                round(float(holdout_k["rendite_pct"]) - float(holdout_benchmark), 2)
                if holdout_k.get("rendite_pct") is not None
                and holdout_benchmark is not None else None
            ),
            "bestanden": holdout.get("bestanden"),
            "gruende": list(holdout.get("gruende") or []),
        },
        "diagnose": _diagnose(df, list(u.trades or [])),
        "robustheit_anteil": u.robustheit_anteil,
        "zufall_p_wert": p_wert,
        "zufall_p_wert_bonferroni": p_bonferroni,
        "monte_carlo_dd_p95": u.monte_carlo_dd_p95,
    }


def erstelle_bericht(
    daten: dict[str, pd.DataFrame], cfg: Config, grenzen: RisikoGrenzen, *,
    quelle: str, commit: str = "",
) -> dict[str, Any]:
    """Prüft jede Strategie auf jedem Symbol und liefert den Bericht als Dict."""
    eintraege: list[dict[str, Any]] = []
    for symbol in sorted(daten):
        df = daten[symbol]
        for strategie in strategien(cfg).values():
            u = beurteile_walk_forward(df, symbol, strategie, cfg, grenzen)
            pruefe_holdout(u, df, strategie, cfg, grenzen)
            eintraege.append(_eintrag(u, df, strategie, cfg))

    bestanden = [e for e in eintraege if e["urteil"] == "bestanden"]
    benchmark_geschlagen = sum(
        1 for e in eintraege
        if e["holdout"].get("mehrwert_gegen_kaufen_halten_pct") is not None
        and float(e["holdout"]["mehrwert_gegen_kaufen_halten_pct"]) > 0
    )
    return {
        "schema": SCHEMA,
        "commit": commit,
        "zeitrahmen": cfg.richter_zeitrahmen,
        "datenquelle": quelle,
        "symbole": sorted(daten),
        "zeitraum": {
            "von": min((str(df["ts"].iloc[0])[:19] for df in daten.values()), default=""),
            "bis": max((str(df["ts"].iloc[-1])[:19] for df in daten.values()), default=""),
        },
        "zusammenfassung": {
            "kandidaten": len(eintraege),
            "bestanden": len(bestanden),
            "abgelehnt": sum(1 for e in eintraege if e["urteil"] == "abgelehnt"),
            "ohne_ausreichende_daten": sum(
                1 for e in eintraege if e["urteil"] not in ("bestanden", "abgelehnt")
            ),
            "strategien": sorted({e["strategie"] for e in eintraege}),
            "parameterkombinationen": sum(e["parameterkombinationen"] for e in eintraege),
            "holdout_benchmark_geschlagen": benchmark_geschlagen,
        },
        "kandidaten": eintraege,
    }


def _prozent(wert: Any) -> str:
    return "–" if wert is None else f"{float(wert):.2f}"


def _kennzahl(eintrag: dict[str, Any], abschnitt: str, name: str) -> Any:
    return (eintrag[abschnitt].get("kennzahlen") or {}).get(name)


def rendere_markdown(bericht: dict[str, Any]) -> str:
    """Lesbare Fassung des Berichts; alle Zahlen stammen aus dem Dict."""
    z = bericht["zusammenfassung"]
    zeilen = [
        "# Strategie-Bericht",
        "",
        f"Zeitrahmen: **{bericht.get('zeitrahmen', 'unbekannt')}** · "
        f"Quelle: {bericht['datenquelle']} · Commit `{bericht['commit'] or 'unbekannt'}` · "
        f"Zeitraum {bericht['zeitraum']['von']} bis {bericht['zeitraum']['bis']}",
        "",
        f"Geprüft: **{z['kandidaten']}** Kandidaten aus {len(z['strategien'])} Strategien auf "
        f"{len(bericht['symbole'])} Symbolen, **{z['parameterkombinationen']}** "
        f"Parameterkombinationen. Bestanden: **{z['bestanden']}**, abgelehnt: "
        f"**{z['abgelehnt']}**, ohne ausreichende Daten: **{z['ohne_ausreichende_daten']}**. "
        f"Holdout-Benchmark geschlagen: **{z.get('holdout_benchmark_geschlagen', 0)}**.",
        "",
        "## Walk-Forward und versiegelter Holdout",
        "",
        "| Symbol | Strategie | Parameter | Trades | Netto % | PF | Sharpe | Sortino | "
        "max. DD % | Gebühren | Kosten % | EW $ | Ø Bars | K&H % | Holdout Netto % | "
        "Holdout K&H % | Mehrwert % | p | p (Bonferroni) | MC-DD p95 % | Urteil |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for e in sorted(bericht["kandidaten"], key=lambda x: (x["symbol"], x["strategie"])):
        parameter = ", ".join(f"{k}={v}" for k, v in sorted((e["parameter"] or {}).items())) or "–"
        zeilen.append(
            f"| {e['symbol']} | {e['strategie']} | {parameter} | "
            f"{int(_kennzahl(e, 'walk_forward', 'trades') or 0)} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'rendite_pct'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'profit_factor'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'sharpe'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'sortino'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'max_drawdown_pct'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'gebuehren'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'kosten_anteil_pct'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'erwartungswert'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'avg_halte_bars'))} | "
            f"{_prozent(e['walk_forward']['kaufen_halten_pct'])} | "
            f"{_prozent((e['holdout']['kennzahlen'] or {}).get('rendite_pct'))} | "
            f"{_prozent(e['holdout']['kaufen_halten_pct'])} | "
            f"{_prozent(e['holdout'].get('mehrwert_gegen_kaufen_halten_pct'))} | "
            f"{_prozent(e['zufall_p_wert'])} | {_prozent(e['zufall_p_wert_bonferroni'])} | "
            f"{_prozent(e['monte_carlo_dd_p95'])} | {e['urteil']} |"
        )
    zeilen += ["", "## Entwicklungsteil (vor dem Holdout)", "",
               "| Symbol | Strategie | Netto % | K&H % | PF | Trades | Gebühren |",
               "|---|---|---:|---:|---:|---:|---:|"]
    for e in sorted(bericht["kandidaten"], key=lambda x: (x["symbol"], x["strategie"])):
        zeilen.append(
            f"| {e['symbol']} | {e['strategie']} | "
            f"{_prozent(_kennzahl(e, 'entwicklung', 'rendite_pct'))} | "
            f"{_prozent(e['entwicklung']['kaufen_halten_pct'])} | "
            f"{_prozent(_kennzahl(e, 'entwicklung', 'profit_factor'))} | "
            f"{int(_kennzahl(e, 'entwicklung', 'trades') or 0)} | "
            f"{_prozent(_kennzahl(e, 'entwicklung', 'gebuehren'))} |"
        )
    zeilen += ["", "## Ausstiege der Walk-Forward-Trades", "",
               "| Symbol | Strategie | Trades | Gewinner | Verlierer | Ø Bars | Ausstiegsgründe |",
               "|---|---|---:|---:|---:|---:|---|"]
    for e in sorted(bericht["kandidaten"], key=lambda x: (x["symbol"], x["strategie"])):
        d = e.get("diagnose") or {}
        gruende = ", ".join(f"{name}: {zahl}" for name, zahl in (d.get("ausstiege") or {}).items()) or "–"
        zeilen.append(
            f"| {e['symbol']} | {e['strategie']} | "
            f"{int(_kennzahl(e, 'walk_forward', 'trades') or 0)} | "
            f"{int(d.get('gewinner') or 0)} | {int(d.get('verlierer') or 0)} | "
            f"{_prozent(d.get('avg_bars'))} | {gruende} |"
        )
    zeilen += ["", "## Marktregime der Walk-Forward-Trades", "",
               "| Symbol | Strategie | Trend-Regime | Volatilitäts-Regime |",
               "|---|---|---|---|"]
    for e in sorted(bericht["kandidaten"], key=lambda x: (x["symbol"], x["strategie"])):
        d = e.get("diagnose") or {}
        def _regime_text(gruppen: dict[str, Any]) -> str:
            return "; ".join(
                f"{name}: {wert['trades']} Trades, {wert['netto']:.2f} USD, "
                f"{wert['trefferquote_pct']:.0f} % Treffer"
                for name, wert in (gruppen or {}).items()
            ) or "–"
        zeilen.append(
            f"| {e['symbol']} | {e['strategie']} | "
            f"{_regime_text(d.get('regime_trend') or {})} | "
            f"{_regime_text(d.get('regime_volatilitaet') or {})} |"
        )
    zeilen += ["", "## Urteile und Gründe", ""]
    for e in sorted(bericht["kandidaten"], key=lambda x: (x["urteil"] != "bestanden",
                                                          x["symbol"], x["strategie"])):
        zeilen.append(f"### {e['symbol']} · {e['strategie']} · {e['urteil']}")
        zeilen.append("")
        if e["gruende"]:
            zeilen.extend(f"- {grund}" for grund in e["gruende"])
        else:
            zeilen.append("- Keine Ablehnungsgründe.")
        zeilen.append("")
    zeilen += [
        "## Einordnung",
        "",
        "- Der versiegelte Holdout wird hier für jede Strategie geöffnet, damit auch "
        "abgelehnte Kandidaten Holdout-Zahlen haben. Für Auswahl und Handel gilt weiterhin: "
        "nur der beste Walk-Forward-Kandidat je Symbol wird geprüft (siehe `pipeline.py`).",
        "- Der p-Wert vergleicht gegen zufällig permutierte Renditen; die Bonferroni-Spalte "
        "multipliziert ihn mit der Zahl der getesteten Parameterkombinationen dieser Strategie.",
        "- Kauft-und-Halten-Werte (K&H) sind dieselben Kosten nicht enthalten; sie markieren "
        "nur die Marktrendite im jeweiligen Zeitraum.",
        "- Bei synthetischen oder Seed-Kerzen ist der Bericht **keine Marktaussage**, sondern "
        "eine Messung des Ablaufs.",
        "",
    ]
    return "\n".join(zeilen)


def schreibe_bericht(bericht: dict[str, Any], ordner: str | Path) -> tuple[Path, Path]:
    """Schreibt JSON und Markdown; gibt beide Pfade zurück."""
    ziel = Path(ordner)
    ziel.mkdir(parents=True, exist_ok=True)
    json_pfad = ziel / "strategie-bericht.json"
    md_pfad = ziel / "strategie-bericht.md"
    json_pfad.write_text(json.dumps(bericht, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    md_pfad.write_text(rendere_markdown(bericht) + "\n", encoding="utf-8")
    return json_pfad, md_pfad
