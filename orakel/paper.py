"""Paper-Trading im Dauerbetrieb.

Der Takt arbeitet auf einem virtuellen Konto in SQLite. Es verlässt keine Order
diesen Rechner: `CsvBroker` und der Takt rechnen nur. Ein echtes MT5-Konto kann
nur der `MT5Broker` unter Windows ansprechen, und auch der nur mit
`order_freigabe = true` auf einem Demo-Konto.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import Any

import pandas as pd

from .config import Config, RisikoGrenzen
from .data import df_aus_db
from .db import Facts, jetzt
from .markt import korrelation_max
from .risk import KontoZustand, Order, Risikomanager, positionsgroesse
from .strategies import atr, strategien


def _kosten(menge: float, cfg: Config) -> float:
    k = cfg["kosten"]
    return max(float(k["min_commission"]), menge * float(k["commission_per_share"]))


def _konto_zustand(cfg: Config, db: Facts, equity: float, cash: float,
                   hoechst: float, tagesstart: float, positionen: list[dict]) -> KontoZustand:
    return KontoZustand(equity=equity, cash=cash, hoechststand=hoechst,
                        tagesstart_equity=tagesstart, positionen=positionen)


def tick(cfg: Config, db: Facts) -> dict[str, Any]:
    """Ein Takt: Stops prüfen, Ausstiege, Einstiege, Konto fortschreiben."""
    grenzen = RisikoGrenzen.aus_config(cfg)
    manager = Risikomanager(grenzen)
    heute = datetime.now().date().isoformat()

    zustand = db.zustand("paper_konto") or {}
    cash = float(zustand.get("cash", cfg.start_kapital))
    hoechst = float(zustand.get("hoechststand", cfg.start_kapital))
    tagesstart = float(zustand.get("tagesstart", cfg.start_kapital))
    if zustand.get("datum") != heute:
        tagesstart = cash + sum(
            float(p["menge"]) * float(p["einstieg"]) for p in db.positionen()
        )
        db.zustand_setzen("paper_konto", {**zustand, "datum": heute, "tagesstart": tagesstart})

    daten: dict[str, pd.DataFrame] = {}
    for symbol in db.symbole():
        daten[symbol] = df_aus_db(db.kerzen(symbol, "M15"))

    offene = db.positionen()
    positionen_fuer_risiko: list[dict] = []
    kurs_map: dict[str, float] = {}

    for p in offene:
        df = daten.get(p["symbol"])
        if df is None or df.empty:
            continue
        kurs = float(df["close"].iloc[-1])
        kurs_map[p["symbol"]] = kurs
        positionen_fuer_risiko.append({"menge": float(p["menge"]), "kurs": kurs})

    def equity_berechnen(cash_wert: float) -> float:
        return cash_wert + sum(
            float(p["menge"]) * kurs_map.get(p["symbol"], float(p["einstieg"]))
            for p in db.positionen()
        )

    equity = equity_berechnen(cash)

    # ---------- 1) Offene Positionen: Stop und Signal ----------
    # Symbole, die in diesem Takt geschlossen wurden, werden nicht sofort wieder gekauft.
    gesperrt: set[str] = set()
    for p in offene:
        symbol = p["symbol"]
        df = daten.get(symbol)
        if df is None or df.empty or len(df) < 30:
            continue
        letzte = df.iloc[-1]
        stop = float(p["stop"])
        menge = float(p["menge"])

        if letzte["low"] <= stop:
            preis = min(float(letzte["open"]), stop)
            prov = _kosten(menge, cfg)
            cash += menge * preis - prov
            netto = menge * (preis - float(p["einstieg"])) - prov
            db.position_loeschen(symbol)
            db.entscheid_speichern(symbol, "verkaufen", menge, preis, p["strategie"],
                                   "ausgeführt (Paper, Stop)", True,
                                   [f"Stop bei {stop:.5f} erreicht", f"Netto {netto:.2f}"])
            db.ereignis("info", "Trading Floor",
                        f"{symbol}: Stop ausgelöst bei {preis:.5f}, Netto {netto:.2f}")
            gesperrt.add(symbol)
            continue

        vid = int(json.loads(p["strategie"]).get("validierung_id", 0)) \
            if p["strategie"].startswith("{") else 0
        signal = 1.0
        if vid:
            zeile = db.validierung(vid)
            if zeile is not None:
                parameter = json.loads(zeile["parameter"])
                strat = strategien(cfg).get(zeile["strategie"])
                if strat is not None:
                    signal = float(strat.signale(df, parameter)[-1])
        if signal <= 0:
            gesperrt.add(symbol)
            preis = float(letzte["close"])
            prov = _kosten(menge, cfg)
            cash += menge * preis - prov
            netto = menge * (preis - float(p["einstieg"])) - prov
            db.position_loeschen(symbol)
            db.entscheid_speichern(symbol, "verkaufen", menge, preis, p["strategie"],
                                   "ausgeführt (Paper, Signal)", True,
                                   ["Strategiesignal ist neutral", f"Netto {netto:.2f}"])
            db.ereignis("info", "Trading Floor",
                        f"{symbol}: Ausstieg per Signal bei {preis:.5f}, Netto {netto:.2f}")

    # ---------- 2) Konto neu bewerten ----------
    equity = equity_berechnen(cash)
    hoechst = max(hoechst, equity)
    positionen_fuer_risiko = [
        {"menge": float(p["menge"]), "kurs": kurs_map.get(p["symbol"], float(p["einstieg"]))}
        for p in db.positionen()
    ]
    konto = _konto_zustand(cfg, db, equity, cash, hoechst, tagesstart, positionen_fuer_risiko)

    stopp = manager.stopp_grund(konto)
    if stopp:
        db.zustand_setzen("risiko_stopp", {"grund": stopp, "seit": jetzt(),
                                           "drawdown_pct": konto.drawdown_pct,
                                           "tagesverlust_pct": konto.tagesverlust_pct})
        db.ereignis("fehler", "Risiko", f"Handelsstopp: {stopp}")
    else:
        db.zustand_loeschen("risiko_stopp")

    # ---------- 3) Einstiege nur für ausgewählte Strategien ----------
    ereignisse: list[str] = []
    for wahl in db.auswahl():
        symbol = wahl["symbol"]
        if symbol in gesperrt:
            continue
        if any(p["symbol"] == symbol for p in db.positionen()):
            continue
        df = daten.get(symbol)
        zeile = db.validierung(int(wahl["validierung_id"]))
        if df is None or df.empty or zeile is None or len(df) < 60:
            continue
        parameter = json.loads(zeile["parameter"])
        strat = strategien(cfg).get(zeile["strategie"])
        if strat is None:
            continue
        signal = float(strat.signale(df, parameter)[-1])
        if signal <= 0:
            continue

        kurs = float(df["close"].iloc[-1])
        atr_wert = float(atr(df, 14).iloc[-1] or 0.0)
        if atr_wert <= 0:
            continue
        stop = kurs - grenzen.atr_stop_multiple * atr_wert
        menge = positionsgroesse(equity, cash, kurs, stop, grenzen)
        order = Order(symbol=symbol, aktion="kaufen", menge=menge, kurs=kurs,
                      strategie=wahl["schluessel"], stop=stop)
        # Klumpenrisiko: Korrelation zu den aktuell offenen Positionen
        offene_symbole = [p["symbol"] for p in db.positionen()]
        k = korrelation_max(symbol, daten, offene_symbole, grenzen.correlation_lookback)
        pruefung = manager.pruefe(order, replace(konto, letzte_korrelation=k)
                                  if k is not None else konto)

        if not pruefung.genehmigt:
            db.entscheid_speichern(symbol, "kaufen", menge, kurs, wahl["schluessel"],
                                   "vom Risiko abgelehnt", False, pruefung.gruende)
            db.ereignis("warnung", "Risiko", f"{symbol}: Kauf abgelehnt — {pruefung.gruende[0]}")
            ereignisse.append(f"{symbol}: abgelehnt")
            continue

        if menge <= 0:
            continue

        preis = kurs * (1 + float(cfg["kosten"]["slippage_bps"]) / 10_000.0)
        prov = _kosten(menge, cfg)
        if menge * preis + prov > cash:
            continue
        cash -= menge * preis + prov
        db.position_setzen(
            symbol, menge, preis, stop,
            json.dumps({"schluessel": wahl["schluessel"],
                        "validierung_id": int(wahl["validierung_id"])}, ensure_ascii=False),
            jetzt(),
        )
        db.entscheid_speichern(symbol, "kaufen", menge, preis, wahl["schluessel"],
                               "ausgeführt (Paper)", True,
                               pruefung.gruende + [f"Stop bei {stop:.5f}"])
        db.ereignis("info", "Trading Floor",
                    f"{symbol}: Paper-Kauf {menge:.0f} Stück zu {preis:.5f}, Stop {stop:.5f}")
        ereignisse.append(f"{symbol}: gekauft {menge:.0f}")
        equity = equity_berechnen(cash)
        konto = _konto_zustand(cfg, db, equity, cash, max(hoechst, equity), tagesstart,
                               [{"menge": float(p["menge"]),
                                 "kurs": kurs_map.get(p["symbol"], float(p["einstieg"]))}
                                for p in db.positionen()])

    # ---------- 4) Konto fortschreiben ----------
    equity = equity_berechnen(cash)
    hoechst = max(hoechst, equity)
    db.konto_speichern(equity, cash, len(db.positionen()), hoechst)
    db.zustand_setzen("paper_konto", {"cash": cash, "hoechststand": hoechst,
                                      "tagesstart": tagesstart, "datum": heute})
    db.zustand_setzen("paper_letzter_tick", jetzt())

    return {
        "zeit": jetzt(),
        "konto": {"equity": round(equity, 2), "cash": round(cash, 2),
                  "positionen": len(db.positionen())},
        "ereignisse": ereignisse,
        "gestoppt": bool(db.zustand("risiko_stopp")),
    }
