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
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Config, RisikoGrenzen
from .kern.judge import aufteilung, beurteile_walk_forward, pruefe_holdout
from .kern.strategies import Strategie, strategien

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
            "kennzahlen": dict(u.out_of_sample or {}),
            "kaufen_halten_pct": kaufen_halten_pct(df, wf_start, dev_n),
            "fenster_bestanden_pct": (
                None if u.walk_forward_bestanden is None
                else round(float(u.walk_forward_bestanden) * 100, 0)
            ),
            "fenster": list(u.walk_forward_folds or []),
        },
        "holdout": {
            "zeitraum": {"von": holdout.get("von", u.holdout_ab), "bis": holdout.get("bis", "")},
            "kennzahlen": holdout_k,
            "kaufen_halten_pct": holdout.get("kaufen_halten_pct"),
            "bestanden": holdout.get("bestanden"),
            "gruende": list(holdout.get("gruende") or []),
        },
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
    return {
        "schema": SCHEMA,
        "commit": commit,
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
        f"Quelle: {bericht['datenquelle']} · Commit `{bericht['commit'] or 'unbekannt'}` · "
        f"Zeitraum {bericht['zeitraum']['von']} bis {bericht['zeitraum']['bis']}",
        "",
        f"Geprüft: **{z['kandidaten']}** Kandidaten aus {len(z['strategien'])} Strategien auf "
        f"{len(bericht['symbole'])} Symbolen, **{z['parameterkombinationen']}** "
        f"Parameterkombinationen. Bestanden: **{z['bestanden']}**, abgelehnt: "
        f"**{z['abgelehnt']}**, ohne ausreichende Daten: **{z['ohne_ausreichende_daten']}**.",
        "",
        "## Walk-Forward und versiegelter Holdout",
        "",
        "| Symbol | Strategie | Parameter | Trades | Netto % | PF | Sharpe | max. DD % | "
        "Gebühren | K&H % | Holdout Netto % | Holdout K&H % | p | p (Bonferroni) | "
        "MC-DD p95 % | Urteil |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for e in sorted(bericht["kandidaten"], key=lambda x: (x["symbol"], x["strategie"])):
        parameter = ", ".join(f"{k}={v}" for k, v in sorted((e["parameter"] or {}).items())) or "–"
        zeilen.append(
            f"| {e['symbol']} | {e['strategie']} | {parameter} | "
            f"{int(_kennzahl(e, 'walk_forward', 'trades') or 0)} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'rendite_pct'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'profit_factor'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'sharpe'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'max_drawdown_pct'))} | "
            f"{_prozent(_kennzahl(e, 'walk_forward', 'gebuehren'))} | "
            f"{_prozent(e['walk_forward']['kaufen_halten_pct'])} | "
            f"{_prozent((e['holdout']['kennzahlen'] or {}).get('rendite_pct'))} | "
            f"{_prozent(e['holdout']['kaufen_halten_pct'])} | "
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
