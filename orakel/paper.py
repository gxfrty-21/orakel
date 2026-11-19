"""Paper-Trading im Dauerbetrieb.

Der Takt arbeitet auf einem virtuellen Konto in SQLite. Es gibt keinen
Broker-Aufruf und keinen Codepfad zu einer echten Order: Käufe, Verkäufe und
Stops werden direkt aus den vorhandenen Kerzen berechnet und in SQLite
fortgeschrieben. `order_freigabe` bleibt als harte Policy-Sperre für zukünftige
Integrationen auf `false`.

Ausführungsmodell (identisch zum Backtest):

- Signale entstehen ausschliesslich auf der letzten **abgeschlossenen** Kerze
  (in der Datenbank die vorletzte Zeile, weil die letzte Zeile die laufende
  Kerze ist, zu deren Eröffnung ausgeführt wird).
- Ausgeführt wird frühestens auf der folgenden Kerze, hier zur Eröffnung der
  letzten vorhandenen Kerze. Der Schlusskurs der Signalkerze wird nie als
  Ausführungspreis verwendet.
- Stops werden innerhalb der laufenden Kerze geprüft; eine Lücke unter den Stop
  füllt zur Eröffnung (realistisch schlechter).
- Kauf füllt mit Aufschlag (`+slippage_bps`), Verkauf mit Abschlag
  (`-slippage_bps`); beide Seiten tragen die Kommission.

Datenqualität: Fehlende, veraltete oder unmögliche Kerzen ersetzen keinen Kurs.
Sie werden protokolliert, die betroffene Position gilt als nicht belastbar
bewertet, und neue Einstiege sind gesperrt, solange die Bewertung unsicher ist.
"""
from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .config import Config, RisikoGrenzen
from .data import df_aus_db
from .db import Facts, jetzt
from .markt import korrelation_max
from .risk import KontoZustand, Order, Risikomanager, positionsgroesse
from .strategies import atr, strategien

# Handelstag und Tagesverlust rechnen in der Handelszeitzone. Der Server läuft
# in UTC; ein Takt um 00:30 UTC gehört in Zürich bereits zum neuen Tag.
HANDELSZEITZONE = ZoneInfo("Europe/Zurich")

# Ohne Zeitstempel grenznahe Kurse ist keine Risikobewertung möglich. Der Wert
# ist bewusst konservativ (24 h) und kann in [daten] überschrieben werden.
STANDARD_KURS_MAX_ALTER_STUNDEN = 24.0


def handelstag(zeitpunkt: datetime | None = None) -> str:
    """Kalendertag des Zeitpunkts in der Handelszeitzone (Europe/Zurich)."""
    zeit = zeitpunkt or datetime.now(timezone.utc)
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.astimezone(HANDELSZEITZONE).date().isoformat()


def _pruefe_paper_konfiguration(cfg: Config) -> None:
    """Der Takt braucht beide Abschnitte; fehlende Werte dürfen nicht als
    stiller Standardwert durchlaufen."""
    fehlend = [
        name for name in ("risiko", "kosten")
        if not cfg.abschnitt(name)
    ]
    if fehlend:
        raise ValueError(
            "Paper-Takt: erforderliche Konfigurationsabschnitte fehlen: "
            + ", ".join(f"[{name}]" for name in fehlend)
        )
    slippage = float(cfg["kosten"]["slippage_bps"])
    if not 0.0 <= slippage < 10_000.0:
        raise ValueError(
            "Paper-Takt: [kosten] slippage_bps muss zwischen 0 und 9999 liegen, "
            f"ist aber {slippage}."
        )


def _kosten(menge: float, cfg: Config) -> float:
    k = cfg["kosten"]
    return max(float(k["min_commission"]), menge * float(k["commission_per_share"]))


def _fill(preis: float, richtung: float, cfg: Config) -> float:
    """Ausführungspreis inklusive adverser Slippage.

    ``richtung`` ist +1 für Kauf und -1 für Verkauf. Damit wird der Käufer
    teurer und der Verkäufer billiger ausgeführt — nie umgekehrt.
    """
    return preis * (1 + richtung * float(cfg["kosten"]["slippage_bps"]) / 10_000.0)


def _positionswert(p: Any, kurs_map: dict[str, float],
                   ersatz_map: dict[str, float]) -> float:
    """Kurswert einer Position; ohne aktuellen Kurs konservativ der kleinere Wert."""
    kurs = kurs_map.get(p["symbol"])
    if kurs is not None:
        return kurs
    einstieg = float(p["einstieg"])
    ersatz = ersatz_map.get(p["symbol"])
    return min(ersatz, einstieg) if ersatz is not None else einstieg


def _verkauf(db: Facts, cfg: Config, p: Any, preis: float, status: str,
             grund: str, ereignis: str) -> float:
    """Bucht einen vollständigen Verkauf und liefert den Cash-Zufluss.

    Ein Teilverkauf existiert im Paper-Takt nicht: Eine Position wird immer
    ganz geschlossen.
    """
    menge = float(p["menge"])
    prov = _kosten(menge, cfg)
    netto = menge * (preis - float(p["einstieg"])) - prov - _kosten(menge, cfg)
    db.position_loeschen(p["symbol"])
    db.entscheid_speichern(p["symbol"], "verkaufen", menge, preis, p["strategie"],
                           status, True, [grund, f"Netto {netto:.2f}"])
    db.ereignis("info", "Trading Floor",
                f"{p['symbol']}: {ereignis} bei {preis:.5f}, Netto {netto:.2f}")
    return menge * preis - prov


def _kerze_gueltig(zeile: Any) -> bool:
    """Prüft eine Kerze auf endliche, positive und plausible OHLC-Werte."""
    werte = []
    for spalte in ("open", "high", "low", "close"):
        try:
            wert = float(zeile[spalte])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(wert) or wert <= 0:
            return False
        werte.append(wert)
    o, h, l, c = werte
    return h >= max(o, c) - 1e-9 and l <= min(o, c) + 1e-9 and h >= l


def _kursstand(
    df: pd.DataFrame | None,
    jetzt_ts: pd.Timestamp,
    max_alter_stunden: float,
) -> tuple[float | None, float | None, str | None]:
    """Liefert (aktueller Kurs, letzter bekannter Kurs, Problemgrund).

    Der aktuelle Kurs ist nur gesetzt, wenn die letzte Kerze gültig und nicht
    älter als ``max_alter_stunden`` ist. ``ersatz`` ist der letzte gültige
    Schlusskurs — auch wenn er veraltet ist —, damit offene Positionen nicht
    zum Einstiegspreis bewertet werden müssen.
    """
    if df is None or df.empty:
        return None, None, "keine Kerzen"
    letzte = df.iloc[-1]
    if not _kerze_gueltig(letzte):
        ersatz = None
        for i in range(len(df) - 1, -1, -1):
            if _kerze_gueltig(df.iloc[i]):
                ersatz = float(df.iloc[i]["close"])
                break
        return None, ersatz, "letzte Kerze ungültig (OHLC)"
    kurs = float(letzte["close"])
    ts = pd.Timestamp(letzte["ts"])
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    alter_h = (jetzt_ts - ts.tz_convert("UTC")).total_seconds() / 3600.0
    if alter_h > max_alter_stunden:
        return None, kurs, f"Kurs {alter_h:.1f} h alt (Grenze {max_alter_stunden:.0f} h)"
    return kurs, kurs, None


def _equity(
    cash: float,
    positionen: list[Any],
    kurs_map: dict[str, float],
    ersatz_map: dict[str, float],
) -> tuple[float, bool]:
    """Kontowert aus Cash und offenen Positionen.

    Fehlt ein aktueller Kurs, wird bewusst der *kleinere* Wert aus letztem
    bekannten Kurs und Einstiegspreis eingesetzt. Damit kann eine fehlende
    Kursangabe die Equity nicht künstlich erhöhen. Der Rückgabewert sagt, ob
    die Bewertung unsicher ist; in diesem Fall sind neue Einstiege gesperrt.
    """
    summe = cash
    unsicher = False
    for p in positionen:
        if p["symbol"] not in kurs_map:
            unsicher = True
        summe += float(p["menge"]) * _positionswert(p, kurs_map, ersatz_map)
    return summe, unsicher


def _konto_zustand(equity: float, cash: float, hoechst: float,
                   tagesstart: float, positionen: list[dict]) -> KontoZustand:
    return KontoZustand(equity=equity, cash=cash, hoechststand=hoechst,
                        tagesstart_equity=tagesstart, positionen=positionen)


def tick(cfg: Config, db: Facts, zeitpunkt: datetime | None = None) -> dict[str, Any]:
    """Ein Takt: Stops prüfen, Ausstiege, Einstiege, Konto fortschreiben."""
    _pruefe_paper_konfiguration(cfg)
    grenzen = RisikoGrenzen.aus_config(cfg)
    manager = Risikomanager(grenzen)
    jetzt_dt = zeitpunkt or datetime.now(timezone.utc)
    if jetzt_dt.tzinfo is None:
        jetzt_dt = jetzt_dt.replace(tzinfo=timezone.utc)
    jetzt_ts = pd.Timestamp(jetzt_dt.astimezone(timezone.utc))
    heute = handelstag(jetzt_dt)
    daten_cfg = cfg.abschnitt("daten") or {}
    max_alter = float(daten_cfg.get("max_kurs_alter_stunden",
                                    STANDARD_KURS_MAX_ALTER_STUNDEN))

    zustand = db.zustand("paper_konto") or {}
    cash = float(zustand.get("cash", cfg.start_kapital))
    hoechst = float(zustand.get("hoechststand", cfg.start_kapital))
    tagesstart = float(zustand.get("tagesstart", cfg.start_kapital))
    tagesstart_unsicher = bool(zustand.get("tagesstart_unsicher", False))

    daten: dict[str, pd.DataFrame] = {}
    for symbol in db.symbole():
        daten[symbol] = df_aus_db(db.kerzen(symbol, "M15"))

    offene = db.positionen()
    kurs_map: dict[str, float] = {}
    ersatz_map: dict[str, float] = {}
    datenprobleme: dict[str, str] = {}
    for p in offene:
        symbol = p["symbol"]
        df = daten.get(symbol)
        kurs, ersatz, problem = _kursstand(df, jetzt_ts, max_alter)
        if problem is not None:
            datenprobleme[symbol] = problem
        if kurs is not None:
            kurs_map[symbol] = kurs
        if ersatz is not None:
            ersatz_map[symbol] = ersatz

    if zustand.get("datum") != heute:
        tagesstart, tagesstart_unsicher = _equity(cash, offene, kurs_map, ersatz_map)
        if tagesstart_unsicher:
            db.ereignis(
                "warnung", "Risiko",
                "Tagesstart ohne aktuelle Kurse für alle Positionen; "
                "Bewertung als unsicher markiert",
            )
        db.zustand_setzen("paper_konto", {
            **zustand, "datum": heute, "tagesstart": tagesstart,
            "tagesstart_unsicher": tagesstart_unsicher,
        })

    def konto_aktualisieren(cash_wert: float) -> tuple[float, bool, KontoZustand]:
        positionen = db.positionen()
        equity, unsicher = _equity(cash_wert, positionen, kurs_map, ersatz_map)
        konto = _konto_zustand(
            equity, cash_wert, max(hoechst, equity), tagesstart,
            [{"menge": float(p["menge"]),
              "kurs": _positionswert(p, kurs_map, ersatz_map)} for p in positionen],
        )
        return equity, unsicher, konto

    equity, equity_unsicher, konto = konto_aktualisieren(cash)

    # ---------- 1) Offene Positionen: Stop und Signal ----------
    # Symbole, die in diesem Takt geschlossen wurden, werden nicht sofort wieder gekauft.
    gesperrt: set[str] = set()
    for p in offene:
        symbol = p["symbol"]
        df = daten.get(symbol)
        problem = datenprobleme.get(symbol)
        if problem is not None:
            # Der Stop braucht keine 30 Kerzen — aber eine Kerze. Ohne gültige
            # Kerze wird nichts geschlossen und nichts erfunden.
            db.ereignis(
                "warnung", "Trading Floor",
                f"{symbol}: keine belastbaren Kurse ({problem}); "
                "Position bleibt offen, Einstiege gesperrt",
            )
            gesperrt.add(symbol)
            continue

        letzte = df.iloc[-1]
        stop = float(p["stop"])

        # Stop-Loss zuerst und unabhängig von der Historie: eine gültige
        # Kerze genügt.
        if float(letzte["low"]) <= stop:
            preis = _fill(min(float(letzte["open"]), stop), -1.0, cfg)
            cash += _verkauf(db, cfg, p, preis, "ausgeführt (Paper, Stop)",
                             f"Stop bei {stop:.5f} erreicht", "Stop ausgelöst")
            gesperrt.add(symbol)
            continue

        # Strategieausstieg: Signal auf der letzten abgeschlossenen Kerze,
        # Ausführung zur Eröffnung der laufenden Kerze.
        vid = int(json.loads(p["strategie"]).get("validierung_id", 0)) \
            if p["strategie"].startswith("{") else 0
        signal = 1.0
        if vid and len(df) >= 30:
            zeile = db.validierung(vid)
            if zeile is not None:
                parameter = json.loads(zeile["parameter"])
                strat = strategien(cfg).get(zeile["strategie"])
                if strat is not None:
                    signal = float(strat.signale(df.iloc[:-1], parameter)[-1])
        if signal <= 0:
            gesperrt.add(symbol)
            preis = _fill(float(letzte["open"]), -1.0, cfg)
            cash += _verkauf(db, cfg, p, preis, "ausgeführt (Paper, Signal)",
                             "Strategiesignal ist neutral", "Ausstieg per Signal")

    # ---------- 2) Konto neu bewerten ----------
    equity, equity_unsicher, konto = konto_aktualisieren(cash)
    hoechst = konto.hoechststand

    stopp = manager.stopp_grund(konto)
    if stopp:
        db.zustand_setzen("risiko_stopp", {"grund": stopp, "seit": jetzt(),
                                           "drawdown_pct": konto.drawdown_pct,
                                           "tagesverlust_pct": konto.tagesverlust_pct})
        db.ereignis("fehler", "Risiko", f"Handelsstopp: {stopp}")
    elif equity_unsicher and db.zustand("risiko_stopp") is not None:
        # Ohne belastbare Kurse wird ein bestehender Stopp nicht freigegeben.
        db.ereignis("warnung", "Risiko",
                    "Handelsstopp bleibt aktiv: Bewertung unsicher")
    else:
        db.zustand_loeschen("risiko_stopp")

    # ---------- 3) Einstiege nur für ausgewählte Strategien ----------
    # Zentrale Sperre: Ein aktiver Risikostopp oder eine unsichere Bewertung
    # verhindert jeden Einstieg — unabhängig von Strategie oder Auswahlpfad.
    risiko_gesperrt = stopp is not None or db.zustand("risiko_stopp") is not None
    einstiege_gesperrt: list[str] = []
    if risiko_gesperrt:
        einstiege_gesperrt.append("Risikostopp aktiv")
    if equity_unsicher:
        einstiege_gesperrt.append("Kursdaten unvollständig oder veraltet")

    ereignisse: list[str] = []
    if einstiege_gesperrt:
        db.ereignis("warnung", "Risiko",
                    "Keine neuen Einstiege: " + "; ".join(einstiege_gesperrt))

    for wahl in ([] if einstiege_gesperrt else db.auswahl()):
        symbol = wahl["symbol"]
        if symbol in gesperrt:
            continue
        if any(p["symbol"] == symbol for p in db.positionen()):
            continue
        df = daten.get(symbol)
        zeile = db.validierung(int(wahl["validierung_id"]))
        if df is None or df.empty or zeile is None or len(df) < 60:
            continue
        kurs, _, problem = _kursstand(df, jetzt_ts, max_alter)
        if problem is not None:
            db.ereignis("warnung", "Risiko",
                        f"{symbol}: kein Einstieg — {problem}")
            continue
        parameter = json.loads(zeile["parameter"])
        strat = strategien(cfg).get(zeile["strategie"])
        if strat is None:
            continue
        # Signal nur auf abgeschlossenen Kerzen; die letzte Zeile ist die
        # Ausführungskerze.
        signal = float(strat.signale(df.iloc[:-1], parameter)[-1])
        if signal <= 0:
            continue

        kurs = _fill(float(df["open"].iloc[-1]), 1.0, cfg)
        atr_wert = float(atr(df.iloc[:-1], 14).iloc[-1] or 0.0)
        if not math.isfinite(atr_wert) or atr_wert <= 0:
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

        prov = _kosten(menge, cfg)
        if menge * kurs + prov > cash:
            continue
        cash -= menge * kurs + prov
        kurs_map[symbol] = kurs
        db.position_setzen(
            symbol, menge, kurs, stop,
            json.dumps({"schluessel": wahl["schluessel"],
                        "validierung_id": int(wahl["validierung_id"])}, ensure_ascii=False),
            jetzt(),
        )
        db.entscheid_speichern(symbol, "kaufen", menge, kurs, wahl["schluessel"],
                               "ausgeführt (Paper)", True,
                               pruefung.gruende + [f"Stop bei {stop:.5f}"])
        db.ereignis("info", "Trading Floor",
                    f"{symbol}: Paper-Kauf {menge:.0f} Stück zu {kurs:.5f}, Stop {stop:.5f}")
        ereignisse.append(f"{symbol}: gekauft {menge:.0f}")
        equity, equity_unsicher, konto = konto_aktualisieren(cash)
        hoechst = konto.hoechststand

    # ---------- 4) Konto fortschreiben ----------
    equity, equity_unsicher, konto = konto_aktualisieren(cash)
    hoechst = konto.hoechststand
    db.konto_speichern(equity, cash, len(db.positionen()), hoechst)
    db.zustand_setzen("paper_konto", {"cash": cash, "hoechststand": hoechst,
                                      "tagesstart": tagesstart,
                                      "tagesstart_unsicher": tagesstart_unsicher,
                                      "datum": heute,
                                      "equity_unsicher": equity_unsicher,
                                      "datenprobleme": datenprobleme})
    db.zustand_setzen("paper_letzter_tick", jetzt())

    return {
        "zeit": jetzt(),
        "konto": {"equity": round(equity, 2), "cash": round(cash, 2),
                  "positionen": len(db.positionen()),
                  "bewertung_unsicher": equity_unsicher},
        "ereignisse": ereignisse,
        "datenprobleme": datenprobleme,
        "einstiege_gesperrt": einstiege_gesperrt,
        "gestoppt": risiko_gesperrt,
    }
