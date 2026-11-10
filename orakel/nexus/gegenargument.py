"""Regelbasierter Gegenargument-Agent.

Der Agent sucht keine neue Wahrheit und ruft keine Quellen ab. Er formuliert
prüfbare Alternativerklärungen aus den vorhandenen Belegen: Widersprüche,
fehlende Unabhängigkeit, Kopien, abweichende Zahlen und vorläufige Reputation.
"""

from __future__ import annotations

from typing import Any


def _befund(art: str, text: str, claim_id: int | None = None,
            schwere: str = "warnung") -> dict[str, Any]:
    return {"art": art, "text": text, "claim_id": claim_id, "schwere": schwere}


def lauf(lage: dict[str, Any], pruefung: dict[str, Any]) -> dict[str, Any]:
    claims = pruefung.get("claims") or []
    befunde: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = int(claim["id"])
        aussage = str(claim.get("kernaussage") or "unbenannte Kernaussage")
        wid = claim.get("widersprueche") or []
        belege = claim.get("belege_detail") or []
        if wid:
            for w in wid[:2]:
                befunde.append(_befund(
                    "widerspruch",
                    f"Zur Aussage «{aussage}» existiert eine Gegenposition: "
                    f"{w.get('grund')} ({w.get('quelle_a')} ↔ {w.get('quelle_b')}). "
                    "Die Gegenposition ist eine Alternative, kein automatischer Beweis.",
                    claim_id, "hoch",
                ))
        elif int(claim.get("quellen") or 0) < 2:
            befunde.append(_befund(
                "unabhaengigkeit",
                f"«{aussage}» kann eine einzelne redaktionelle Einschätzung sein: "
                "Es fehlt eine zweite unabhängige Originalquelle.",
                claim_id,
            ))
        kopien = sum(1 for b in belege if b.get("ist_kopie"))
        if kopien:
            befunde.append(_befund(
                "kopie",
                f"{kopien} Beleg(e) zu «{aussage}» sind Kopien. Eine gemeinsame "
                "Vorlage kann die Übereinstimmung erklären; sie bestätigt sie nicht.",
                claim_id,
            ))
        werte = sorted({round(float(b["wert"]), 6) for b in belege
                        if b.get("wert") is not None})
        if len(werte) > 1:
            befunde.append(_befund(
                "zahlenkonflikt",
                f"Zu «{aussage}» liegen mehrere Werte vor ({', '.join(str(w) for w in werte)}). "
                "Das kann ein echter Konflikt oder eine unterschiedliche Abgrenzung sein.",
                claim_id, "hoch",
            ))
        if not belege:
            befunde.append(_befund(
                "gegenbeleg",
                f"Für «{aussage}» sind keine Einzelbelege gespeichert. "
                "Die Aussage ist damit nicht nachprüfbar.",
                claim_id, "hoch",
            ))
        reps = [float(b.get("reputation") or 0) for b in belege]
        if reps and max(reps) < 0.6:
            befunde.append(_befund(
                "reputation",
                f"Die Belege zu «{aussage}» haben höchstens Reputation "
                f"{max(reps):.2f}; die Übereinstimmung kann institutionell geprägt sein.",
                claim_id,
            ))
    if not claims:
        befunde.append(_befund(
            "datenluecke",
            "Ohne passende Kernaussage gibt es keine Gegenargumente. "
            "Die Datenlücke ist selbst der Befund; sie ist keine Entwarnung.",
            None, "hoch",
        ))
    else:
        befunde.append(_befund(
            "grenze",
            "Fehlende Widersprüche sind kein Konsensbeweis: Geprüft wurden nur "
            "gespeicherte Claims, unterschiedliche Hosts und ein begrenztes Zeitfenster.",
            None, "hinweis",
        ))
    return {
        "gegenargumente": befunde[:20],
        "anzahl": len(befunde[:20]),
        "claims": len(claims),
        "grundlage": "Regelbasierte Gegenprüfung gespeicherter Belege; keine neuen Quellen.",
    }
