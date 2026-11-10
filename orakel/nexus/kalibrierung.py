"""Phase 6: Prognosekontrolle mit Trefferquote und Brier-Score.

Grundsätze:

- Eine Prognose wird nur mit einer echten, prüfbaren Erwartung angelegt.
- Marktprognosen werden ausschließlich gegen tatsächlich gespeicherte Kerzen
  geprüft; fehlt der Kurs nach dem Horizont, bleibt die Prognose offen.
- Abgeschlossene Intel-Aufträge werden als Prognosen importiert. Dort ist keine
  Modellwahrscheinlichkeit gespeichert, deshalb wird bewusst 0,5 als neutrale
  Konfidenz verwendet. Der Brier-Score ist für diese Fälle nur eine Referenz.
- ``verworfen`` bedeutet „nicht prüfbar“ und zählt nicht als Fehlprognose.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Facts

ERWARTUNGEN = ("steigt", "sinkt", "unveraendert")
MAX_PROGNOSEN = 2000
STANDARD_KONFIDENZ = 0.5
STANDARD_TOLERANZ_PCT = 0.1

KONFIDENZ_KLASSEN: tuple[tuple[float, float, str], ...] = (
    (0.0, 0.2, "0–20 %"),
    (0.2, 0.4, "20–40 %"),
    (0.4, 0.6, "40–60 %"),
    (0.6, 0.8, "60–80 %"),
    (0.8, 1.0000001, "80–100 %"),
)


def _jetzt(wert: datetime | None = None) -> datetime:
    if wert is None:
        return datetime.now(timezone.utc)
    if wert.tzinfo is None:
        return wert.replace(tzinfo=timezone.utc)
    return wert


def _iso(wert: datetime) -> str:
    return wert.astimezone(timezone.utc).isoformat(timespec="seconds")


def _zeit(text: object) -> datetime | None:
    try:
        wert = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert


def _horizont_sekunden(text: str) -> int:
    treffer = re.fullmatch(r"\s*(\d+)\s*([mhd])\s*", str(text or ""))
    if not treffer:
        raise ValueError("Zeithorizont muss z. B. 30m, 24h oder 7d sein.")
    anzahl = int(treffer.group(1))
    if anzahl <= 0:
        raise ValueError("Der Zeithorizont muss größer als null sein.")
    faktor = {"m": 60, "h": 3600, "d": 86400}[treffer.group(2)]
    return anzahl * faktor


def _kennung(db: Facts, jetzt: datetime) -> str:
    tag = jetzt.strftime("%Y%m%d")
    basis = db.nexus_forecast_zaehler(tag) + 1
    for nummer in range(basis, basis + 1000):
        kennung = f"FC-{tag}-{nummer:04d}"
        if db.nexus_forecast(kennung) is None:
            return kennung
    raise RuntimeError("Keine freie Prognosekennung gefunden")


def prognose_anlegen(
    db: Facts,
    aussage: str,
    erwartung: str,
    *,
    zeithorizont: str = "24h",
    konfidenz: float = STANDARD_KONFIDENZ,
    symbol: str | None = None,
    toleranz_pct: float = STANDARD_TOLERANZ_PCT,
    mission_kennung: str | None = None,
    claim_id: int | None = None,
    jetzt_wert: datetime | None = None,
) -> dict[str, Any]:
    """Legt eine marktgebundene, gegen echte Kerzen prüfbare Prognose an."""
    aussage = re.sub(r"\s+", " ", str(aussage or "")).strip()
    erwartung = str(erwartung or "").strip().lower()
    symbol = str(symbol or "").strip().upper()
    if len(aussage) < 5:
        raise ValueError("Die Aussage braucht mindestens 5 Zeichen.")
    if erwartung not in ERWARTUNGEN:
        raise ValueError(f"Unbekannte Erwartung: {erwartung}")
    if not symbol:
        raise ValueError("Eine marktgebundene Prognose braucht ein Symbol.")
    try:
        konfidenz = float(konfidenz)
    except (TypeError, ValueError) as exc:
        raise ValueError("Konfidenz muss eine Zahl zwischen 0 und 1 sein.") from exc
    if not 0.0 <= konfidenz <= 1.0:
        raise ValueError("Konfidenz muss zwischen 0 und 1 liegen.")
    try:
        toleranz_pct = max(0.0, float(toleranz_pct))
    except (TypeError, ValueError) as exc:
        raise ValueError("Toleranz muss eine nichtnegative Zahl sein.") from exc

    kerzen = db.kerzen(symbol, "M15")
    if not kerzen:
        raise ValueError(f"Keine M15-Kerzen für {symbol} vorhanden.")
    basiswert = float(kerzen[-1]["close"])
    if basiswert <= 0:
        raise ValueError(f"Ungültiger letzter Kurs für {symbol}.")

    jetzt = _jetzt(jetzt_wert)
    faellig = jetzt + timedelta(seconds=_horizont_sekunden(zeithorizont))
    kennung = _kennung(db, jetzt)
    daten = {
        "kennung": kennung,
        "auftrag_id": None,
        "mission_kennung": mission_kennung,
        "claim_id": claim_id,
        "aussage": aussage[:500],
        "erwartung": erwartung,
        "zeithorizont": str(zeithorizont).strip(),
        "faellig_am": _iso(faellig),
        "konfidenz": round(konfidenz, 4),
        "symbol": symbol,
        "basiswert": basiswert,
        "toleranz_pct": round(toleranz_pct, 4),
        "status": "offen",
        "erstellt": _iso(jetzt),
        "aktualisiert": _iso(jetzt),
    }
    return db.nexus_forecast_anlegen(daten)


def prognosen_aus_intel(db: Facts, jetzt_wert: datetime | None = None) -> dict[str, int]:
    """Importiert echte Intel-Aufträge als Prognosen; keine künstlichen Fälle."""
    jetzt = _jetzt(jetzt_wert)
    zeit = _iso(jetzt)
    zaehler = {"gesamt": 0, "offen": 0, "abgeschlossen": 0, "unpruefbar": 0}
    for auftrag in db.intel_auftraege(2000):
        art = str(auftrag["art"] or "")
        if art not in ("markt", "strategie"):
            continue
        aussage = str(auftrag["hypothese"] or auftrag["titel"] or "").strip()
        if not aussage:
            continue
        auftrag_status = str(auftrag["status"] or "offen")
        if auftrag_status == "bestätigt":
            status, eingetreten = "eingetreten", 1
        elif auftrag_status == "widerlegt":
            status, eingetreten = "nicht_eingetreten", 0
        elif auftrag_status == "verworfen":
            status, eingetreten = "unpruefbar", None
        else:
            status, eingetreten = "offen", None

        erwartung = "bewegung" if art == "markt" else "bestaetigt"
        zeithorizont = "96xM15" if art == "markt" else "naechste Validierung"
        kennung = f"FC-{auftrag['kennung']}"
        basiswert = auftrag["kurs_bei_erstellung"]
        daten = {
            "kennung": kennung,
            "auftrag_id": int(auftrag["id"]),
            "mission_kennung": None,
            "claim_id": None,
            "aussage": aussage[:500],
            "erwartung": erwartung,
            "zeithorizont": zeithorizont,
            "faellig_am": str(auftrag["zeit"] or zeit),
            "konfidenz": STANDARD_KONFIDENZ,
            "symbol": str(auftrag["bezug_symbol"] or "").upper(),
            "basiswert": (float(basiswert) if basiswert is not None else None),
            "toleranz_pct": STANDARD_TOLERANZ_PCT,
            "status": status,
            "erstellt": str(auftrag["zeit"] or zeit),
            "aktualisiert": zeit,
        }
        forecast = db.nexus_forecast_anlegen(daten)
        forecast_id = int(forecast["id"])
        if eingetreten is None:
            db.nexus_forecast_result_loeschen(forecast_id)
        else:
            notiz = (f"Intel-Auftrag {auftrag['kennung']} ({auftrag_status}): "
                     f"{str(auftrag['ergebnis'] or '')[:500]}")
            db.nexus_forecast_result_speichern(
                forecast_id, eingetreten, None, zeit, notiz,
            )
        zaehler["gesamt"] += 1
        if status == "offen":
            zaehler["offen"] += 1
        elif status == "unpruefbar":
            zaehler["unpruefbar"] += 1
        else:
            zaehler["abgeschlossen"] += 1
    return zaehler


def pruefe_prognosen(db: Facts, jetzt_wert: datetime | None = None) -> int:
    """Prüft fällige manuelle Marktprognosen gegen die erste Kerze nach Fälligkeit."""
    jetzt = _jetzt(jetzt_wert)
    zeit = _iso(jetzt)
    geprueft = 0
    for forecast in db.nexus_forecasts(MAX_PROGNOSEN):
        if forecast.get("auftrag_id") is not None:
            continue
        if str(forecast.get("status") or "") != "offen":
            continue
        ergebnis = forecast.get("ergebnis")
        if isinstance(ergebnis, dict) and ergebnis.get("eingetreten") is not None:
            continue
        symbol = str(forecast.get("symbol") or "").upper()
        basiswert = forecast.get("basiswert")
        if not symbol or basiswert is None:
            continue
        basiswert = float(basiswert)
        faellig = _zeit(forecast.get("faellig_am"))
        if faellig is None or faellig > jetzt:
            continue
        ziel = None
        for kerze in db.kerzen(symbol, "M15"):
            kerzenzeit = _zeit(kerze["ts"])
            if kerzenzeit is None or kerzenzeit < faellig:
                continue
            ziel = (kerzenzeit, float(kerze["close"]))
            break
        if ziel is None:
            continue
        _, messwert = ziel
        veraenderung = (messwert - basiswert) / basiswert * 100 if basiswert else 0.0
        erwartung = str(forecast.get("erwartung") or "")
        if erwartung == "steigt":
            eingetreten = veraenderung > 0
        elif erwartung == "sinkt":
            eingetreten = veraenderung < 0
        elif erwartung == "unveraendert":
            eingetreten = abs(veraenderung) <= float(forecast.get("toleranz_pct") or 0.0)
        else:
            continue
        status = "eingetreten" if eingetreten else "nicht_eingetreten"
        notiz = (f"{symbol}: Basis {basiswert:.5f}, Kurs {messwert:.5f} "
                 f"({veraenderung:+.3f} %) nach {forecast.get('zeithorizont')}; "
                 f"Erwartung «{erwartung}».")
        db.nexus_forecast_result_speichern(
            int(forecast["id"]), int(eingetreten), messwert, zeit, notiz,
        )
        db.nexus_forecast_status_setzen(str(forecast["kennung"]), status, zeit)
        geprueft += 1
    return geprueft


def _leere_gruppe() -> dict[str, Any]:
    return {"n": 0, "treffer": 0, "quote": None, "brier": None}


def kalibrierung_statistik(db: Facts) -> dict[str, Any]:
    """Berechnet Trefferquote/Brier ausschließlich aus geprüften Prognosen."""
    forecasts = db.nexus_forecasts(MAX_PROGNOSEN)
    geprueft = [
        f for f in forecasts
        if isinstance(f.get("ergebnis"), dict)
        and f["ergebnis"].get("eingetreten") is not None
    ]
    treffer = sum(int(f["ergebnis"]["eingetreten"]) for f in geprueft)
    brier = None
    if geprueft:
        brier = round(sum(
            (max(0.0, min(1.0, float(f.get("konfidenz") or STANDARD_KONFIDENZ)))
             - int(f["ergebnis"]["eingetreten"])) ** 2
            for f in geprueft
        ) / len(geprueft), 4)

    nach_erwartung: dict[str, dict[str, Any]] = {}
    klassen = [
        {"klasse": label, "von": von, "bis": min(bis, 1.0),
         "n": 0, "treffer": 0, "quote": None, "brier": None}
        for von, bis, label in KONFIDENZ_KLASSEN
    ]
    for forecast in geprueft:
        erwartung = str(forecast.get("erwartung") or "unbekannt")
        gruppe = nach_erwartung.setdefault(erwartung, _leere_gruppe())
        gruppe["n"] += 1
        gruppe["treffer"] += int(forecast["ergebnis"]["eingetreten"])
        gruppe["_brier_summe"] = (gruppe.get("_brier_summe", 0.0) + (
            max(0.0, min(1.0, float(forecast.get("konfidenz") or STANDARD_KONFIDENZ)))
            - int(forecast["ergebnis"]["eingetreten"])
        ) ** 2)

        konfidenz = max(0.0, min(1.0, float(forecast.get("konfidenz") or STANDARD_KONFIDENZ)))
        for klasse in klassen:
            if klasse["von"] <= konfidenz < klasse["bis"] or (
                klasse["bis"] == 1.0 and konfidenz == 1.0
            ):
                klasse["n"] += 1
                klasse["treffer"] += int(forecast["ergebnis"]["eingetreten"])
                klasse["_brier_summe"] = (klasse.get("_brier_summe", 0.0) + (
                    konfidenz - int(forecast["ergebnis"]["eingetreten"])
                ) ** 2)
                break

    for gruppe in nach_erwartung.values():
        gruppe["quote"] = (round(gruppe["treffer"] / gruppe["n"], 3)
                           if gruppe["n"] else None)
        gruppe["brier"] = (round(gruppe.pop("_brier_summe") / gruppe["n"], 4)
                           if gruppe["n"] else None)
    for klasse in klassen:
        klasse["quote"] = (round(klasse["treffer"] / klasse["n"], 3)
                           if klasse["n"] else None)
        klasse["brier"] = (round(klasse.pop("_brier_summe") / klasse["n"], 4)
                           if klasse["n"] else None)

    auto = sum(1 for f in forecasts if f.get("auftrag_id") is not None)
    manuell = len(forecasts) - auto
    offen = sum(1 for f in forecasts if str(f.get("status") or "") == "offen")
    unpruefbar = sum(1 for f in forecasts if str(f.get("status") or "") == "unpruefbar")
    if not geprueft:
        hinweis = ("Noch keine geprüfte Prognose. Trefferquote und Brier-Score "
                   "sind ohne Stichprobe keine Aussage.")
    elif auto and not manuell:
        hinweis = ("Auto-importierte Intel-Aufträge tragen 0,5 als neutrale "
                   "Konfidenz; der Brier-Score ist deshalb nur eine Referenz.")
    elif auto:
        hinweis = ("Die Statistik mischt manuelle Prognosen mit neutral "
                   "importierten Intel-Aufträgen (Konfidenz 0,5).")
    else:
        hinweis = ""
    return {
        "ok": True,
        "gesamt": len(forecasts),
        "geprueft": len(geprueft),
        "offen": offen,
        "unpruefbar": unpruefbar,
        "treffer": treffer,
        "trefferquote": round(treffer / len(geprueft), 3) if geprueft else None,
        "brier": brier,
        "auto": auto,
        "manuell": manuell,
        "nach_erwartung": nach_erwartung,
        "kalibrierungsklassen": klassen,
        "letzte": forecasts[:20],
        "hinweis": hinweis,
    }


def kalibrierung_auffrischen(db: Facts, jetzt_wert: datetime | None = None) -> dict[str, Any]:
    """Synchronisiert Intel-Prognosen und prüft fällige manuelle Marktprognosen."""
    jetzt = _jetzt(jetzt_wert)
    intel = prognosen_aus_intel(db, jetzt)
    geprueft = pruefe_prognosen(db, jetzt)
    return {
        "intel": intel,
        "neu_geprueft": geprueft,
        "statistik": kalibrierung_statistik(db),
    }
