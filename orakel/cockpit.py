"""Cockpit: die vier wichtigsten Zahlen für die Übersicht.

1. Läuft der Bot?            (letzter Paper-Takt, Risikostopp)
2. Kontostand                (letzte Zeile der Tabelle ``konto``)
3. Gewinn/Verlust            (heute, 7 Tage, 1 Monat, mit Verlauf)
4. Offene Positionen         (mit letztem Kurs und unrealisiertem Ergebnis)

Alles wird nur aus SQLite gelesen. Fehlt eine Grundlage, bleibt der Wert
``None``; es gibt keine Ersatzzahlen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Config
from .kern.db import Facts

HANDELSZEITZONE = ZoneInfo("Europe/Zurich")
PAPER_ZEITRAHMEN = "M15"
MAX_PUNKTE = 120  # Punkte je Verlaufskurve; reicht für eine kleine Linie.


def _zeit(text: Any) -> datetime | None:
    """ISO-Zeit lesen; Zeiten ohne Zeitzone gelten als UTC."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat() if dt else None


def _bot_status(cfg: Config, db: Facts, jetzt: datetime) -> dict[str, Any]:
    paper = cfg.abschnitt("paper") or {}
    takt = max(1, int(paper.get("takt_sekunden", 60)))
    # Drei verpasste Takte (mindestens 3 Minuten) gelten als Stillstand.
    grenze = max(3 * takt, 180)
    letzter = _zeit(db.zustand("paper_letzter_tick"))
    stopp = db.zustand("risiko_stopp")
    alter = int((jetzt - letzter).total_seconds()) if letzter else None

    if stopp:
        zustand, text = "gestoppt", "Risikostopp: " + str(stopp.get("grund", "Grenze überschritten"))
    elif letzter is None:
        zustand, text = "nie", "Der Paper-Takt ist noch nie gelaufen"
    elif alter is not None and alter <= grenze:
        zustand, text = "laeuft", "Paper-Takt aktiv"
    else:
        zustand, text = "steht", "Kein Takt seit mehr als " + str(grenze // 60) + " Minuten"
    return {
        "zustand": zustand,
        "text": text,
        "letzter_takt": _iso(letzter),
        "alter_sekunden": alter,
        "takt_sekunden": takt,
    }


def _kontoverlauf(db: Facts, ab: datetime) -> tuple[list[tuple[datetime, float]], tuple[datetime, float] | None]:
    """Kontozeilen seit ``ab`` (chronologisch) und die letzte Zeile davor.

    Liest rückwärts und hört bei der ersten Zeile vor ``ab`` auf, damit eine
    grosse Tabelle nicht ganz geladen wird.
    """
    zeilen: list[tuple[datetime, float]] = []
    davor: tuple[datetime, float] | None = None
    with db.conn() as c:
        for r in c.execute("SELECT zeit, equity FROM konto ORDER BY zeit DESC, id DESC"):
            dt = _zeit(r["zeit"])
            if dt is None:
                continue
            if dt < ab:
                davor = (dt, float(r["equity"]))
                break
            zeilen.append((dt, float(r["equity"])))
    zeilen.sort(key=lambda p: p[0])
    return zeilen, davor


def _ausduennen(punkte: list[tuple[datetime, float]]) -> list[list[Any]]:
    if len(punkte) > MAX_PUNKTE:
        schritt = (len(punkte) - 1) / (MAX_PUNKTE - 1)
        punkte = [punkte[round(i * schritt)] for i in range(MAX_PUNKTE)]
    return [[_iso(dt), round(wert, 2)] for dt, wert in punkte]


def _zeitraum(name: str, ab: datetime, alle: list[tuple[datetime, float]],
              davor: tuple[datetime, float] | None, equity: float | None,
              start_kapital: float) -> dict[str, Any]:
    seit = [p for p in alle if p[0] >= ab]
    vorher = [p for p in alle if p[0] < ab]
    referenz = vorher[-1] if vorher else davor
    if equity is None or not seit:
        return {"name": name, "betrag": None, "pct": None, "basis": None,
                "seit": _iso(ab), "seit_start": False, "verlauf": []}
    # Kein Kontowert vor dem Zeitraum: Der Bot ist erst darin gestartet.
    seit_start = referenz is None
    basis = start_kapital if referenz is None else referenz[1]
    betrag = equity - basis
    verlauf = ([(seit[0][0], basis)] if seit_start else [(ab, basis)]) + seit
    return {
        "name": name,
        "betrag": round(betrag, 2),
        "pct": round(betrag / basis * 100, 2) if basis else None,
        "basis": round(basis, 2),
        "seit": _iso(seit[0][0] if seit_start else ab),
        "seit_start": seit_start,
        "verlauf": _ausduennen(verlauf),
    }


def _letzter_kurs(db: Facts, symbol: str) -> tuple[float | None, str | None]:
    with db.conn() as c:
        r = c.execute(
            "SELECT ts, close FROM kerzen WHERE symbol=? AND zeitrahmen=? ORDER BY ts DESC LIMIT 1",
            (symbol, PAPER_ZEITRAHMEN),
        ).fetchone()
    return (float(r["close"]), str(r["ts"])) if r else (None, None)


def _positionen(db: Facts) -> list[dict[str, Any]]:
    raus = []
    for p in db.positionen():
        menge, einstieg = float(p["menge"]), float(p["einstieg"])
        kurs, kurs_ts = _letzter_kurs(db, p["symbol"])
        ergebnis = round((kurs - einstieg) * menge, 2) if kurs is not None else None
        raus.append({
            "symbol": p["symbol"],
            "menge": menge,
            "einstieg": einstieg,
            "stop": float(p["stop"]),
            "strategie": p["strategie"],
            "eroeffnet": p["eroeffnet"],
            "kurs": kurs,
            "kurs_ts": kurs_ts,
            "wert": round(kurs * menge, 2) if kurs is not None else None,
            "ergebnis": ergebnis,
            "ergebnis_pct": round((kurs / einstieg - 1) * 100, 2) if kurs is not None and einstieg else None,
        })
    return raus


def cockpit_block(cfg: Config, db: Facts, jetzt: datetime | None = None) -> dict[str, Any]:
    jetzt = (jetzt or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lokal = jetzt.astimezone(HANDELSZEITZONE)
    tagesbeginn = lokal.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    grenzen = {
        "heute": tagesbeginn,
        "7t": jetzt - timedelta(days=7),
        "1m": jetzt - timedelta(days=30),
    }

    konto = db.letztes_konto()
    equity = float(konto["equity"]) if konto else None
    alle, davor = _kontoverlauf(db, min(grenzen.values()))
    positionen = _positionen(db)
    offen = [p["ergebnis"] for p in positionen if p["ergebnis"] is not None]

    return {
        "stand": _iso(jetzt),
        "bot": _bot_status(cfg, db, jetzt),
        "konto": {
            "equity": round(equity, 2) if equity is not None else None,
            "cash": round(float(konto["cash"]), 2) if konto else None,
            "start_kapital": float(cfg.start_kapital),
            "zeit": konto["zeit"] if konto else None,
        },
        "gewinn": {name: _zeitraum(name, ab, alle, davor, equity, float(cfg.start_kapital))
                  for name, ab in grenzen.items()},
        "positionen": positionen,
        "positionen_ergebnis": round(sum(offen), 2) if offen else None,
    }
