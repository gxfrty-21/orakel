"""Phase 7: Datenvertrag für den 3D-Nexus.

Der Raum ist keine eigene Datenquelle. Er liest den persistierten Graphen und
leitet Aktivitätsereignisse ausschließlich aus gespeicherten Zeitstempeln von
Missionen, Kernaussagen, Quellen und Prognosen ab. Fehlt ein Zeitstempel, wird
kein Ereignis erfunden; leere Daten ergeben einen leeren, ruhigen Raum.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Facts
from .graph import ZEITRAEUME, graph_auffrischen, graph_daten
from .kalibrierung import kalibrierung_statistik

MAX_EREIGNISSE = 48


def _jetzt(wert: datetime | None = None) -> datetime:
    if wert is None:
        return datetime.now(timezone.utc)
    if wert.tzinfo is None:
        return wert.replace(tzinfo=timezone.utc)
    return wert


def _zeit(text: object) -> datetime | None:
    try:
        wert = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert


def _im_zeitraum(text: object, grenze: datetime | None) -> bool:
    if grenze is None:
        return True
    zeit = _zeit(text)
    return zeit is not None and zeit >= grenze


def _ereignis(
    kennung: str, zeit: object, art: str, titel: str, text: str,
    status: str, referenz: str,
) -> dict[str, Any] | None:
    """Baut nur dann ein Ereignis, wenn ein echter Zeitpunkt vorliegt."""
    if _zeit(zeit) is None:
        return None
    return {
        "id": kennung,
        "zeit": str(zeit),
        "art": art,
        "titel": titel,
        "text": str(text or "")[:240],
        "status": str(status or ""),
        "referenz": referenz,
    }


def _aktivitaet_aus(
    missionen: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    forecasts: list[dict[str, Any]],
    quellen: list[dict[str, Any]],
    statistik: dict[str, Any],
    grenze: datetime | None,
) -> dict[str, Any]:
    ereignisse: list[dict[str, Any]] = []

    for mission in missionen:
        kennung = str(mission.get("kennung") or "")
        if not kennung:
            continue
        if mission.get("beendet"):
            zeit = mission["beendet"]
            titel = "Mission abgeschlossen"
            art = "mission"
        elif mission.get("gestartet"):
            zeit = mission["gestartet"]
            titel = "Mission gestartet"
            art = "mission"
        else:
            zeit = mission.get("erstellt")
            titel = "Mission angelegt"
            art = "mission"
        eintrag = _ereignis(
            f"mission:{kennung}:{titel}", zeit, art, titel,
            str(mission.get("titel") or kennung),
            str(mission.get("status") or ""), f"mission:{kennung}",
        )
        if eintrag and _im_zeitraum(zeit, grenze):
            ereignisse.append(eintrag)

    for claim in claims:
        claim_id = claim.get("id")
        if claim_id is None:
            continue
        zeit = claim.get("aktualisiert") or claim.get("erstmals")
        eintrag = _ereignis(
            f"claim:{claim_id}:bewertet", zeit, "claim", "Kernaussage bewertet",
            str(claim.get("kernaussage") or f"Kernaussage {claim_id}"),
            str(claim.get("status") or ""), f"claim:{claim_id}",
        )
        if eintrag and _im_zeitraum(zeit, grenze):
            ereignisse.append(eintrag)

    for forecast in forecasts:
        kennung = str(forecast.get("kennung") or "")
        if not kennung:
            continue
        geprueft = forecast.get("result_geprueft_am")
        if geprueft:
            zeit = geprueft
            titel = "Prognose geprüft"
            status = ("eingetreten" if forecast.get("result_eingetreten") == 1 else
                      "nicht eingetreten" if forecast.get("result_eingetreten") == 0 else
                      str(forecast.get("status") or ""))
        else:
            zeit = forecast.get("erstellt")
            titel = "Prognose angelegt"
            status = str(forecast.get("status") or "")
        eintrag = _ereignis(
            f"forecast:{kennung}:{'geprueft' if geprueft else 'angelegt'}",
            zeit, "prognose", titel,
            str(forecast.get("aussage") or kennung),
            status, f"forecast:{kennung}",
        )
        if eintrag and _im_zeitraum(zeit, grenze):
            ereignisse.append(eintrag)

    for quelle in quellen:
        host = str(quelle.get("host") or quelle.get("quelle_id") or "")
        if not host:
            continue
        zeit = quelle.get("aktualisiert")
        eintrag = _ereignis(
            f"quelle:{host}:bewertet", zeit, "quelle", "Quellenbewertung aktualisiert",
            str(quelle.get("name") or host),
            str(quelle.get("vertrauen") or ""), f"quelle:{host}",
        )
        if eintrag and _im_zeitraum(zeit, grenze):
            ereignisse.append(eintrag)

    ereignisse.sort(key=lambda e: (_zeit(e["zeit"]) or datetime.min.replace(
        tzinfo=timezone.utc)), reverse=True)
    ereignisse = ereignisse[:MAX_EREIGNISSE]

    nach_status = statistik.get("nach_status") or {}
    tasks = statistik.get("tasks") or {}
    laufend = int(nach_status.get("laufend") or 0)
    tasks_aktiv = int(tasks.get("laufend") or 0)
    aktiv = laufend > 0 or tasks_aktiv > 0
    if aktiv:
        status = "aktiv"
        label = "AKTIV"
        detail = (f"{laufend} Mission{'en' if laufend != 1 else ''} laufend · "
                  f"{tasks_aktiv} Aufgabe{'n' if tasks_aktiv != 1 else ''} aktiv")
    elif ereignisse:
        status = "ruhig"
        label = "RUHIG"
        letzte = ereignisse[0]
        detail = f"Letzte Aktivität: {letzte['titel']} · {letzte['zeit'][:16].replace('T', ' ')}"
    else:
        status = "leer"
        label = "LEER"
        gespeichert = len(missionen) + len(claims) + len(forecasts) + len(quellen)
        detail = ("Keine Aktivität im gewählten Zeitraum." if gespeichert else
                  "Keine Missionen, Kernaussagen, Prognosen oder Quellenbewertungen gespeichert.")

    return {
        "status": status,
        "label": label,
        "detail": detail,
        "laufend": laufend,
        "tasks_aktiv": tasks_aktiv,
        "offen": int(nach_status.get("offen") or 0),
        "gespeichert": len(missionen) + len(claims) + len(forecasts) + len(quellen),
        "events": ereignisse,
    }


def raum_daten(
    db: Facts, zeitraum: str = "7d", jetzt_wert: datetime | None = None,
    auffrischen: bool = True,
) -> dict[str, Any]:
    """Liefert Graph und echte Aktivität für die 3D-Ansicht."""
    zeitraum = str(zeitraum or "7d")
    if zeitraum not in ZEITRAEUME:
        raise ValueError(f"Unbekannter Zeitraum: {zeitraum}")
    jetzt = _jetzt(jetzt_wert)
    tage = ZEITRAEUME[zeitraum]
    grenze = jetzt - timedelta(days=tage) if tage else None

    if auffrischen:
        graph_auffrischen(db)
    graph = graph_daten(db, zeitraum, jetzt)

    missionen = db.nexus_missionen(20)
    claims = db.nexus_claims(40)
    forecasts = db.nexus_forecasts(40)
    quellen = db.nexus_quellen_reputation()
    mission_statistik = db.nexus_mission_statistik()
    claim_statistik = db.nexus_claim_statistik()
    kalibrierung = kalibrierung_statistik(db)
    aktivitaet = _aktivitaet_aus(
        missionen, claims, forecasts, quellen, mission_statistik, grenze,
    )

    nach_status = mission_statistik.get("nach_status") or {}
    hinweis = graph.get("hinweis") or ""
    if not aktivitaet["events"] and graph.get("knoten"):
        hinweis = ("Keine Aktivität im gewählten Zeitraum. "
                   "Der Raum zeigt nur gespeicherte Graphknoten.")
    return {
        "ok": True,
        "zeitraum": zeitraum,
        "generiert": jetzt.isoformat(timespec="seconds"),
        "graph": graph,
        "zahlen": {
            "knoten": int(graph["statistik"]["knoten"]),
            "kanten": int(graph["statistik"]["kanten"]),
            "claims": int(claim_statistik.get("gesamt") or 0),
            "quellen": len(quellen),
            "missionen": int(mission_statistik.get("gesamt") or 0),
            "laufend": int(aktivitaet["laufend"]),
            "offen": int(nach_status.get("offen") or 0),
            "prognosen": int(kalibrierung.get("gesamt") or 0),
            "trefferquote": kalibrierung.get("trefferquote"),
        },
        "aktivitaet": aktivitaet,
        "hinweis": hinweis,
    }
