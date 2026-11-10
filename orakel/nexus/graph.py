"""Phase 6: persistierter Wissensgraph des Nexus.

Der Graph wird ausschließlich aus gespeicherten Daten abgeleitet:

- Kernaussage → Thema (regelbasierte Einordnung)
- Kernaussage → Quellenhost (jeder Beleg, Kopien getrennt ausgewiesen)
- Quellenhost → Quellenhost (erkannter Widerspruch)

Die Kanten liegen in ``nexus_edges``. Knoten werden beim Lesen aus den
zugehörigen Tabellen beschrieben; es werden keine Knoten oder Beziehungen
erfunden. Die Zeitangabe einer Kante ist die früheste echte Beobachtung, damit
der Zeitfilter auch nach einem Rebuild aussagekräftig bleibt.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Facts

ZEITRAEUME: dict[str, int | None] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "alle": None,
}
STANDARD_ZEITRAUM = "7d"
MAX_KANTEN = 2000
MAX_NODES = 3000


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


def _frueheste(a: object, b: object) -> str:
    """Behält den frühesten echten Zeitpunkt einer Beziehung."""
    if not a:
        return str(b or "")
    if not b:
        return str(a)
    za, zb = _zeit(a), _zeit(b)
    if za is None:
        return str(b)
    if zb is None:
        return str(a)
    return str(a) if za <= zb else str(b)


def _sicherheit(wert: object) -> float:
    try:
        return round(max(0.0, min(1.0, float(wert))), 3)
    except (TypeError, ValueError):
        return 0.5


def graph_auffrischen(db: Facts) -> dict[str, Any]:
    """Baut ``nexus_edges`` deterministisch aus Claims, Belegen und Widersprüchen."""
    claims = db.nexus_claims(1000)
    kanten: dict[tuple[str, str, str], dict[str, Any]] = {}

    def hinzu(von: str, nach: str, art: str, begruendung: str,
             sicherheit: object, erstellt: object) -> None:
        if not von or not nach or von == nach:
            return
        key = (von, nach, art)
        eintrag = kanten.get(key)
        if eintrag is None:
            kanten[key] = {
                "von": von,
                "nach": nach,
                "art": art,
                "begruendung": begruendung[:500],
                "sicherheit": _sicherheit(sicherheit),
                "erstellt": str(erstellt or ""),
            }
            return
        eintrag["sicherheit"] = max(eintrag["sicherheit"], _sicherheit(sicherheit))
        eintrag["erstellt"] = _frueheste(eintrag["erstellt"], erstellt)

    for claim in claims:
        thema = str(claim.get("thema") or "allgemein")
        hinzu(
            f"claim:{int(claim['id'])}",
            f"thema:{thema}",
            "gehoert_zu",
            f"Regelbasierte Themeneinordnung: {thema}",
            0.9,
            claim.get("erstmals") or claim.get("aktualisiert"),
        )

    claim_ids = [int(c["id"]) for c in claims]
    if claim_ids:
        belege = db.nexus_claim_quellen_fuer(claim_ids)
        gruppen: dict[tuple[int, str], dict[str, Any]] = {}
        for beleg in belege:
            key = (int(beleg["claim_id"]), str(beleg["host"] or "unbekannt"))
            eintrag = gruppen.setdefault(key, {
                "anzahl": 0,
                "originale": 0,
                "kopien": 0,
                "sicherheit": 0.0,
                "erstellt": "",
            })
            eintrag["anzahl"] += 1
            if bool(beleg.get("ist_kopie")):
                eintrag["kopien"] += 1
            else:
                eintrag["originale"] += 1
            eintrag["sicherheit"] = max(
                float(eintrag["sicherheit"]),
                _sicherheit(beleg.get("reputation")),
            )
            eintrag["erstellt"] = _frueheste(eintrag["erstellt"], beleg.get("erstellt"))
        for (claim_id, host), eintrag in gruppen.items():
            hinzu(
                f"claim:{claim_id}",
                f"quelle:{host}",
                "belegt_durch",
                f"{eintrag['anzahl']} Belege, "
                f"{eintrag['originale']} Originale, "
                f"{eintrag['kopien']} Kopien",
                eintrag["sicherheit"],
                eintrag["erstellt"],
            )

    for widerspruch in db.nexus_widersprueche(1000):
        hinzu(
            f"quelle:{widerspruch.get('quelle_a') or 'unbekannt'}",
            f"quelle:{widerspruch.get('quelle_b') or 'unbekannt'}",
            "widerspruch",
            f"Claim {widerspruch.get('claim_id')}: {widerspruch.get('grund') or ''}",
            widerspruch.get("sicherheit"),
            widerspruch.get("erstellt"),
        )

    kanten_liste = sorted(
        kanten.values(), key=lambda k: (str(k["erstellt"]), k["von"], k["nach"], k["art"])
    )
    db.nexus_graph_ersetzen(kanten_liste)
    knoten = {wert for kante in kanten_liste for wert in (kante["von"], kante["nach"])}
    return {
        "knoten": len(knoten),
        "kanten": len(kanten_liste),
        "arten": dict(Counter(k["art"] for k in kanten_liste)),
    }


def _knoten(kennung: str, claims: dict[int, dict[str, Any]],
            quellen: dict[str, dict[str, Any]]) -> dict[str, Any]:
    typ, _, wert = kennung.partition(":")
    if typ == "claim":
        try:
            claim = claims.get(int(wert))
        except ValueError:
            claim = None
        if claim:
            return {
                "id": kennung,
                "typ": "claim",
                "label": str(claim.get("kernaussage") or kennung)[:220],
                "status": str(claim.get("status") or ""),
                "meta": {
                    "thema": str(claim.get("thema") or ""),
                    "quellen": int(claim.get("quellen") or 0),
                    "belege": int(claim.get("belege") or 0),
                    "bestaetigungsgrad": float(claim.get("bestaetigungsgrad") or 0),
                },
            }
        return {"id": kennung, "typ": "claim", "label": "unbekannte Kernaussage",
                "status": "", "meta": {}}
    if typ == "quelle":
        quelle = quellen.get(wert)
        return {
            "id": kennung,
            "typ": "quelle",
            "label": str((quelle or {}).get("name") or wert or "unbekannte Quelle")[:160],
            "status": str((quelle or {}).get("vertrauen") or "vorläufig"),
            "meta": {
                "host": wert,
                "reputation": float((quelle or {}).get("reputation") or 0.5),
            },
        }
    if typ == "thema":
        return {"id": kennung, "typ": "thema", "label": wert or "allgemein",
                "status": "", "meta": {}}
    return {"id": kennung, "typ": typ or "unbekannt", "label": wert or kennung,
            "status": "", "meta": {}}


def graph_daten(db: Facts, zeitraum: str = STANDARD_ZEITRAUM,
                jetzt_wert: datetime | None = None) -> dict[str, Any]:
    """Liest den persistierten Graph, gefiltert nach dem echten Kantenzeitpunkt."""
    zeitraum = str(zeitraum or STANDARD_ZEITRAUM)
    if zeitraum not in ZEITRAEUME:
        raise ValueError(f"Unbekannter Zeitraum: {zeitraum}")
    jetzt = _jetzt(jetzt_wert)
    tage = ZEITRAEUME[zeitraum]
    grenze = jetzt - timedelta(days=tage) if tage else None

    alle = db.nexus_graph_edges()
    gefiltert: list[dict[str, Any]] = []
    for kante in alle:
        zeit = _zeit(kante.get("erstellt"))
        if grenze is not None and zeit is not None and zeit < grenze:
            continue
        gefiltert.append(kante)
    if len(gefiltert) > MAX_KANTEN:
        gefiltert = gefiltert[-MAX_KANTEN:]

    claim_ids = sorted({
        int(k["von"].split(":", 1)[1])
        for k in gefiltert
        if str(k["von"]).startswith("claim:")
    } | {
        int(k["nach"].split(":", 1)[1])
        for k in gefiltert
        if str(k["nach"]).startswith("claim:")
    })
    claims = {int(c["id"]): c for c in db.nexus_claims_by_ids(claim_ids)}
    quellen = {
        str(q["host"]): q for q in db.nexus_quellen_reputation()
    }

    knoten: dict[str, dict[str, Any]] = {}
    for kante in gefiltert:
        for kennung in (str(kante["von"]), str(kante["nach"])):
            if kennung not in knoten:
                knoten[kennung] = _knoten(kennung, claims, quellen)
    knoten_liste = sorted(knoten.values(), key=lambda n: (n["typ"], n["id"]))
    if len(knoten_liste) > MAX_NODES:
        knoten_liste = knoten_liste[:MAX_NODES]
        erlaubt = {n["id"] for n in knoten_liste}
        gefiltert = [k for k in gefiltert
                     if k["von"] in erlaubt and k["nach"] in erlaubt]

    kanten_liste = [
        {
            "von": str(k["von"]),
            "nach": str(k["nach"]),
            "art": str(k["art"]),
            "begruendung": str(k.get("begruendung") or ""),
            "sicherheit": float(k.get("sicherheit") or 0.5),
            "erstellt": str(k.get("erstellt") or ""),
        }
        for k in gefiltert
    ]
    typen = Counter(n["typ"] for n in knoten_liste)
    arten = Counter(k["art"] for k in kanten_liste)
    return {
        "ok": True,
        "zeitraum": zeitraum,
        "generiert": jetzt.isoformat(timespec="seconds"),
        "knoten": knoten_liste,
        "kanten": kanten_liste,
        "statistik": {
            "knoten": len(knoten_liste),
            "kanten": len(kanten_liste),
            "typen": dict(typen),
            "arten": dict(arten),
        },
        "hinweis": ("" if kanten_liste else
                    "Noch keine Graphkanten. Der Graph entsteht aus gespeicherten "
                    "Kernaussagen, Belegen und Widersprüchen."),
    }
