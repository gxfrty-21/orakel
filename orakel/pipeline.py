"""Der vollständige Lauf: Daten → Research → Richter → Risiko → Auswahl → Bericht."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import pandas as pd

from . import agents as agenten
from .config import Config, RisikoGrenzen, load_config
from .data import df_aus_db, lade_csv, pruefe_daten, synthetische_kerzen
from .db import Facts, jetzt
from .intel import IntelNetz
from .judge import beurteile_walk_forward, pruefe_holdout
from .knowledge import Vault
from .markt import korrelation_max, markt_uebersicht
from .report import baue_bericht, schreibe_bericht
from .risk import KontoZustand, Order, Risikomanager, positionsgroesse
from .strategies import atr, strategien

SYMBOLE_STANDARD = ["EURUSD", "US500"]


def sicherstellen_daten(cfg: Config, db: Facts, quelle: str | None = None) -> tuple[list[str], str]:
    """Lädt CSV-Dateien aus daten/ oder erzeugt synthetische Kerzen."""
    quelle = quelle or str(cfg["basis"].get("datenquelle", "synthetisch"))
    ordner = cfg.daten_ordner
    ordner.mkdir(parents=True, exist_ok=True)
    symbole: list[str] = []

    if quelle == "csv":
        for datei in sorted(ordner.glob("*.csv")):
            symbol = datei.stem.split("_")[0].upper()
            try:
                df = lade_csv(datei)
            except Exception as exc:
                db.ereignis("fehler", "Daten", f"{datei.name}: {exc}")
                continue
            db.kerzen_speichern(symbol, "M15", df.to_dict("records"))
            symbole.append(symbol)
            db.ereignis("info", "Daten", f"{datei.name}: {len(df)} Kerzen importiert")
        if symbole:
            db.zustand_setzen("datenquelle", "csv")
            return sorted(set(symbole)), "csv"

    if db.symbole():
        # Herkunft der vorhandenen Kerzen — entscheidet über den Dashboard-Modus
        return db.symbole(), str(db.zustand("datenquelle", "datenbank"))

    for i, symbol in enumerate(SYMBOLE_STANDARD):
        df = synthetische_kerzen(symbol, kerzen=12000, seed=7 + i * 13)
        db.kerzen_speichern(symbol, "M15", df.to_dict("records"))
        symbole.append(symbol)
    db.zustand_setzen("datenquelle", "synthetisch")
    db.ereignis("warnung", "Daten", "Synthetische Kerzen erzeugt — keine Aussage über echte Märkte")
    return symbole, "synthetisch"


def lauf(
    cfg_pfad: str = "config.toml",
    modus: str = "backtest",
    quelle: str | None = None,
    bericht_pfad: str = "dashboard.json",
    mit_agenten: bool = True,
    mit_konferenz: bool = True,
    mit_spider: bool = False,
) -> dict[str, Any]:
    start = time.perf_counter()
    lauf_id = jetzt()
    cfg = load_config(cfg_pfad)
    db = Facts(cfg.db_pfad)
    grenzen = RisikoGrenzen.aus_config(cfg)
    vault = Vault(cfg.vault_ordner)
    fehler: list[str] = []

    symbole, datenquelle = sicherstellen_daten(cfg, db, quelle)
    qualitaet: list[dict[str, Any]] = []
    daten: dict[str, pd.DataFrame] = {}

    for symbol in symbole:
        df = df_aus_db(db.kerzen(symbol, "M15"))
        daten[symbol] = df
        q = pruefe_daten(df, symbol, cfg)
        qualitaet.append(q.als_dict())
        if not q.ok:
            db.ereignis("fehler", "Daten", f"{symbol}: {'; '.join(q.fehler)}")
            fehler.append(f"{symbol}: {'; '.join(q.fehler)}")
            vault.notiz("fehler", f"Datenfehler {symbol}",
                        "\n".join(f"- {f}" for f in q.fehler), tags=["daten", "fehler"])

    # Datenfehler stoppen im Paper-Modus den Handel (Sicherheitsgrenzen)
    if modus == "paper" and fehler:
        db.zustand_setzen("risiko_stopp", {"grund": "Datenfehler: " + fehler[0],
                                           "seit": jetzt(), "drawdown_pct": 0.0,
                                           "tagesverlust_pct": 0.0})
        db.ereignis("fehler", "Risiko", "Handelsstopp wegen Datenfehlern")

    # ---------- Research + Richter: rollierender Walk-Forward ----------
    roh: dict[str, list[tuple[Any, Any]]] = {}
    for symbol in symbole:
        df = daten[symbol]
        if len(df) < int(cfg["daten"]["min_kerzen"]):
            continue
        for strategie in strategien(cfg).values():
            try:
                u = beurteile_walk_forward(df, symbol, strategie, cfg, grenzen)
            except Exception as exc:
                db.ereignis("fehler", "Richter", f"{symbol} {strategie.name}: {exc}")
                fehler.append(f"{symbol} {strategie.name}: {exc}")
                continue
            roh.setdefault(symbol, []).append((u, strategie))

    # Der Holdout wird nur für den besten Walk-Forward-Kandidaten je Symbol geöffnet.
    beste_urteile: dict[str, Any] = {}
    for symbol, kandidaten in roh.items():
        bestanden = [(u, s) for u, s in kandidaten if u.urteil == "bestanden"]
        if not bestanden:
            continue
        bester, strategie = max(
            bestanden,
            key=lambda paar: (
                ((paar[0].out_of_sample or {}).get("profit_factor") or 0.0),
                ((paar[0].out_of_sample or {}).get("netto") or 0.0),
            ),
        )
        try:
            pruefe_holdout(bester, daten[symbol], strategie, cfg, grenzen)
        except Exception as exc:
            bester.urteil = "abgelehnt"
            bester.gruende.append(f"Versiegelter Holdout konnte nicht geprüft werden: {exc}")
            db.ereignis("fehler", "Richter", f"{symbol} Holdout: {exc}")
            fehler.append(f"{symbol} Holdout: {exc}")
        if bester.urteil == "bestanden":
            beste_urteile[symbol] = bester
        for u, _ in bestanden:
            if u is bester:
                continue
            u.urteil = "abgelehnt"
            u.gruende.append(
                "Nicht die beste Walk-Forward-Leistung — der versiegelte Holdout "
                "wird nur für den besten Kandidaten je Symbol geöffnet."
            )

    # Ohne neue Freigabe darf keine alte Auswahl weiterlaufen — auch nicht für
    # Symbole, die mangels Daten gar nicht erst geprüft werden konnten.
    for symbol in symbole:
        if symbol not in beste_urteile:
            db.auswahl_loeschen(symbol)

    urteil_liste: list[dict[str, Any]] = []
    beste: dict[str, dict[str, Any]] = {}
    for symbol, liste in roh.items():
        for u, strategie in liste:
            d = u.als_dict()
            vid = db.validierung_speichern(
                symbol, strategie.name, u.schluessel, u.parameter, u.urteil,
                strategie.beschreibung, d, u.trades, lauf=lauf_id,
            )
            d["validierung_id"] = vid
            urteil_liste.append(d)
            if beste_urteile.get(symbol) is u:
                beste[symbol] = d
            if u.urteil == "bestanden":
                db.ereignis("info", "Richter",
                            f"{symbol} {strategie.name} bestanden (PF Walk-Forward "
                            f"{(u.out_of_sample.get('profit_factor') or 0):.2f}, Holdout "
                            f"{(u.holdout.get('kennzahlen') or {}).get('profit_factor') or 0:.2f})")
                vault.notiz(
                    "validierungen", f"{symbol} {strategie.name} {u.schluessel}",
                    f"**Urteil:** bestanden\n\n**Parameter:** `{u.parameter}`\n\n"
                    f"**Walk-Forward-Fenster:** {u.walk_forward_bestanden * 100:.0f} % profitabel\n\n"
                    f"**Profit Factor Walk-Forward:** {u.out_of_sample.get('profit_factor')}\n\n"
                    f"**Profit Factor Holdout:** {(u.holdout.get('kennzahlen') or {}).get('profit_factor')}\n\n"
                    f"**Trades Walk-Forward:** {len(u.trades)}\n\n**Zeit im Markt:** "
                    f"{u.gesamt.get('zeit_im_markt_pct')} %",
                    tags=["validierung", "bestanden", symbol.lower(), strategie.name, "holdout"],
                )
            elif u.urteil == "abgelehnt":
                vault.notiz(
                    "validierungen", f"Abgelehnt {symbol} {strategie.name} {u.schluessel}",
                    "**Gründe:**\n" + "\n".join(f"- {g}" for g in u.gruende),
                    tags=["validierung", "abgelehnt", symbol.lower(), strategie.name],
                )

    for symbol, d in beste.items():
        db.auswahl_setzen(symbol, d["schluessel"], int(d["validierung_id"]))

    # ---------- Risiko + Plan ----------
    manager = Risikomanager(grenzen)
    konto_row = db.letztes_konto()
    equity = float(konto_row["equity"]) if konto_row else cfg.start_kapital
    hoechst = float(konto_row["hoechststand"]) if konto_row else cfg.start_kapital
    offene = [{"menge": float(p["menge"]), "kurs": float(p["einstieg"])}
              for p in db.positionen()]
    konto = KontoZustand(equity=equity, cash=equity, hoechststand=max(hoechst, equity),
                         tagesstart_equity=equity, positionen=offene)

    plan: list[dict[str, Any]] = []
    for symbol, d in beste.items():
        df = daten.get(symbol)
        if df is None or len(df) < 60:
            continue
        strat = strategien(cfg).get(d["strategie"])
        if strat is None:
            continue
        signal = strat.signale(df, d["parameter"])[-1]
        kurs = float(df["close"].iloc[-1])
        atr_wert = float(atr(df, 14).iloc[-1] or 0.0)
        stop = kurs - grenzen.atr_stop_multiple * atr_wert if atr_wert > 0 else 0.0

        if signal > 0:
            menge = positionsgroesse(equity, equity, kurs, stop, grenzen)
            order = Order(symbol=symbol, aktion="kaufen", menge=menge, kurs=kurs,
                          strategie=d["schluessel"], stop=stop)
            # Klumpenrisiko: Korrelation des geplanten Symbols zu offenen Positionen
            offene_symbole = [p["symbol"] for p in db.positionen()]
            k = korrelation_max(symbol, daten, offene_symbole, grenzen.correlation_lookback)
            pruefung = manager.pruefe(order, replace(konto, letzte_korrelation=k)
                                      if k is not None else konto)
            status = "Probelauf (keine Order gesendet)" if pruefung.genehmigt else \
                "vom Risiko abgelehnt"
            gruende = list(pruefung.gruende)
            if stop:
                gruende.append(f"Stop bei {stop:.5f} ({grenzen.atr_stop_multiple} × ATR)")
            plan.append({
                "symbol": symbol, "aktion": "kaufen", "menge": menge, "kurs": round(kurs, 5),
                "strategie": d["schluessel"], "status": status,
                "genehmigt": pruefung.genehmigt, "gruende": gruende,
            })
            db.entscheid_speichern(symbol, "kaufen", menge, kurs, d["schluessel"], status,
                                   pruefung.genehmigt, pruefung.gruende)
        else:
            plan.append({
                "symbol": symbol, "aktion": "halten", "menge": 0, "kurs": round(kurs, 5),
                "strategie": d["schluessel"], "status": "keine Aktion (kein Signal)",
                "genehmigt": True, "gruende": ["Signal der ausgewählten Strategie ist neutral"],
            })

    # ---------- Marktbild für die Weltkugel ----------
    markt = markt_uebersicht(daten)

    # ---------- Spider (optional, Netzwerk) ----------
    spider_ergebnis: dict[str, Any] | None = None
    if mit_spider:
        from .spider import Spider

        try:
            spider_ergebnis = Spider(cfg, db, vault).lauf()
        except Exception as exc:
            db.ereignis("fehler", "Spider", f"Recherche fehlgeschlagen: {exc}")
            fehler.append(f"Spider: {exc}")

    # ---------- Intelligence: Weiterleitung, Aufträge, Lernschleife ----------
    intel_ergebnis: dict[str, Any] = {}
    try:
        netz = IntelNetz(cfg, db, vault)
        intel_ergebnis = netz.verarbeite((spider_ergebnis or {}).get("neue_ids") or [], markt=markt)
        intel_ergebnis.update(netz.lernschleife(markt=markt))
        intel_ergebnis["hypothesen"] = netz.hypothesen_aus_lage(markt=markt)
    except Exception as exc:
        db.ereignis("fehler", "Intel", f"Intelligence fehlgeschlagen: {exc}")
        fehler.append(f"Intel: {exc}")

    # ---------- Agenten + Konferenz ----------
    ctx = {
        "cfg": cfg, "grenzen": grenzen, "validierungen": urteil_liste,
        "qualitaet": qualitaet,
        "konto": {"equity": equity, "positionen": len(offene),
                  "drawdown_pct": konto.drawdown_pct},
        "plan": plan, "modus": modus, "db": db, "markt": markt,
        "intel": intel_ergebnis,
    }
    agenten_ergebnisse: list[dict[str, Any]] = []
    protokoll: dict[str, Any] | None = None
    if mit_agenten:
        try:
            agenten_ergebnisse = agenten.lauf(db, ctx)
        except Exception as exc:  # Agenten dürfen den Lauf nie abbrechen
            db.ereignis("fehler", "Agenten", f"Agentenlauf fehlgeschlagen: {exc}")
            fehler.append(f"Agentenlauf: {exc}")
    if mit_konferenz:
        try:
            protokoll = agenten.konferenz(db, ctx)
        except Exception as exc:
            db.ereignis("fehler", "Konferenz", f"Konferenz fehlgeschlagen: {exc}")
            fehler.append(f"Konferenz: {exc}")

    # Synthetische Kurse sind keine Marktaussage: Dashboard zeigt dann SIMULATION.
    bericht_modus = "simulation" if (datenquelle == "synthetisch" and modus != "paper") else modus
    db.zustand_setzen("letzter_lauf_id", lauf_id)
    bericht = baue_bericht(cfg, db, modus=bericht_modus, datenquelle=datenquelle,
                           qualitaet=qualitaet, plan=plan, fehler=fehler)
    bericht["agenten"] = agenten_ergebnisse
    bericht["konferenz"] = protokoll
    bericht["markt"] = markt
    bericht["spider"] = spider_ergebnis or db.zustand("spider_letzter_lauf", {})
    bericht["dauer_sekunden"] = round(time.perf_counter() - start, 2)

    # Basis für die Live-Ansicht: /api/report baut daraus jeden Aufruf neu.
    db.zustand_setzen("bericht_basis", {
        "modus": bericht_modus, "datenquelle": datenquelle, "qualitaet": qualitaet,
        "plan": plan, "fehler": fehler, "agenten": agenten_ergebnisse,
        "konferenz": protokoll, "markt": markt,
    })
    if spider_ergebnis is not None:
        db.zustand_setzen("spider_letzter_lauf", spider_ergebnis)

    schreibe_bericht(bericht, bericht_pfad)
    db.zustand_setzen("letzter_lauf", {"zeit": jetzt(), "modus": bericht_modus,
                                       "dauer": bericht["dauer_sekunden"]})
    db.ereignis("info", "Engine", f"Lauf beendet in {bericht['dauer_sekunden']} s "
                                  f"({len(urteil_liste)} Prüfungen, {len(beste)} ausgewählt)")
    return bericht
