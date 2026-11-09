"""Erzeugt den Bericht im Schema 2 — genau das Format der Orakel-Oberfläche."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Config, RisikoGrenzen
from .db import Facts, jetzt
from .intel import lage as intel_lage

STATUS = {"simulation": "SIMULATION", "backtest": "BACKTEST", "paper": "PAPER TRADING", "live": "LIVE"}


def _json(row: Any, feld: str, standard: Any) -> Any:
    try:
        return json.loads(row[feld])
    except Exception:
        return standard


def risiko_block(db: Facts, grenzen: RisikoGrenzen, cfg: Config) -> tuple[dict[str, Any], dict[str, Any]]:
    konto = db.letztes_konto()
    stopp = db.zustand("risiko_stopp")
    if stopp:
        risiko = {
            "status": "gestoppt",
            "grund": stopp.get("grund", "Grenze überschritten"),
            "seit": stopp.get("seit"),
            "auslastung": {
                "drawdown_pct": round(float(stopp.get("drawdown_pct", 0.0)), 2),
                "tagesverlust_pct": round(float(stopp.get("tagesverlust_pct", 0.0)), 2),
                "engagement_pct": 0.0,
                "positionen": 0,
            },
        }
    else:
        auslastung = {"drawdown_pct": 0.0, "tagesverlust_pct": 0.0, "engagement_pct": 0.0, "positionen": 0}
        if konto:
            hoechst = float(konto["hoechststand"]) or float(konto["equity"])
            dd = max(0.0, (hoechst - float(konto["equity"])) / hoechst * 100) if hoechst else 0.0
            auslastung["drawdown_pct"] = round(dd, 2)
            auslastung["positionen"] = int(konto["positionen"])
        risiko = {"status": "aktiv", "grund": "Keine Grenze überschritten", "seit": None,
                  "auslastung": auslastung}
    return risiko, grenzen.als_dict()


def wissen_block(db: Facts) -> dict[str, Any]:
    alle = db.alle_validierungen()
    gruppen: dict[str, dict[str, Any]] = {}
    for r in alle:
        typ = r["strategie"]
        g = gruppen.setdefault(typ, {"typ": typ, "tests": 0, "bestanden": 0,
                                     "pfs": [], "ablehnungen": {}})
        g["tests"] += 1
        bericht = _json(r, "bericht", {})
        if r["urteil"] == "bestanden":
            g["bestanden"] += 1
            pf = (bericht.get("out_of_sample") or {}).get("profit_factor")
            if pf is not None:
                g["pfs"].append(float(pf))
        else:
            for grund in bericht.get("gruende") or []:
                kurz = str(grund).split("—")[0].strip()[:60]
                g["ablehnungen"][kurz] = g["ablehnungen"].get(kurz, 0) + 1

    typen = []
    for g in gruppen.values():
        pfs = sorted(g["pfs"])
        median = pfs[len(pfs) // 2] if pfs else None
        haeufigste = sorted(g["ablehnungen"].items(), key=lambda kv: -kv[1])[:2]
        typen.append({
            "typ": g["typ"],
            "tests": g["tests"],
            "bestanden": g["bestanden"],
            "quote_pct": round(g["bestanden"] / g["tests"] * 100, 1) if g["tests"] else 0.0,
            "median_pf_oos": round(median, 2) if median is not None else None,
            "haeufigste_ablehnung": [k for k, _ in haeufigste],
        })
    typen.sort(key=lambda t: -t["quote_pct"])
    return {"typen": typen}


def baue_bericht(
    cfg: Config,
    db: Facts,
    modus: str = "backtest",
    datenquelle: str = "synthetisch",
    qualitaet: list[dict[str, Any]] | None = None,
    plan: list[dict[str, Any]] | None = None,
    fehler: list[str] | None = None,
) -> dict[str, Any]:
    grenzen = RisikoGrenzen.aus_config(cfg)
    risiko, grenzen_dict = risiko_block(db, grenzen, cfg)

    validierungen = []
    lauf = db.zustand("letzter_lauf_id")
    for r in db.letzte_validierungen(lauf):
        bericht = _json(r, "bericht", {})
        eintrag = {**bericht}
        eintrag["symbol"] = r["symbol"]
        eintrag["strategie"] = r["strategie"]
        eintrag["parameter"] = _json(r, "parameter", {})
        eintrag["urteil"] = r["urteil"]
        eintrag["beschreibung"] = r["beschreibung"]
        validierungen.append(eintrag)

    konto_row = db.letztes_konto()
    konto = None
    # Das Paper-Konto ist echte Buchhaltung: zeigen, sobald ein Takt gelaufen ist.
    if konto_row:
        konto = {"equity": float(konto_row["equity"]), "cash": float(konto_row["cash"]),
                 "last_equity": float(konto_row["hoechststand"])}

    entscheide = [
        {"symbol": r["symbol"], "aktion": r["aktion"], "zeit": r["zeit"], "status": r["status"],
         "gruende": _json(r, "gruende", []), "genehmigt": bool(r["genehmigt"])}
        for r in db.entscheide(60)
    ]
    ereignisse = [
        {"zeit": r["zeit"], "stufe": r["stufe"], "quelle": r["quelle"], "text": r["text"]}
        for r in db.ereignisse(40)
    ]

    return {
        "schema": 2,
        "modus": modus,
        "erstellt": jetzt(),
        "datenquelle": datenquelle,
        "usd_chf": None,
        "konto": konto,
        "risiko": risiko,
        "risiko_grenzen": grenzen_dict,
        "validierungen": validierungen,
        "auswahl": [{"symbol": r["symbol"], "schluessel": r["schluessel"]} for r in db.auswahl()],
        "plan": plan or [],
        "entscheide": entscheide,
        "ereignisse": ereignisse,
        "fehler": fehler or [],
        "datenqualitaet": qualitaet or [],
        "wissen": wissen_block(db),
        "intel": intel_lage(db),
        "kosten": {
            "commission_per_share": float(cfg["kosten"]["commission_per_share"]),
            "min_commission": float(cfg["kosten"]["min_commission"]),
            "slippage_bps": float(cfg["kosten"]["slippage_bps"]),
        },
        "live": {"gruende": [
            "Projekt ist ausschliesslich Paper-Trading (Meister-Prompt, Abschnitt 9)",
            "Kein Pfad zu echten Orders im Code vorhanden",
            "Freigabe nur nach positiven, robusten Paper-Ergebnissen durch dich",
        ]},
    }


def schreibe_bericht(bericht: dict[str, Any], pfad: str | Path = "dashboard.json") -> Path:
    ziel = Path(pfad)
    ziel.write_text(json.dumps(bericht, ensure_ascii=False, indent=1), encoding="utf-8")
    return ziel
