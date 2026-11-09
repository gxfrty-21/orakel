"""Hacker News über die offizielle Firebase-API.

Keine Authentifizierung, keine Umgehung: ``topstories`` und ``item`` sind die
dokumentierten Endpunkte. Die Top-Liste wird ohne bedingte Anfrage geholt,
weil bei einem 304 kein Body mit den IDs vorliegt und der Cache nur
Validatoren speichert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .abruf import Abrufer

HN_BASIS = "https://hacker-news.firebaseio.com/v0"


@dataclass(slots=True)
class HNMeldung:
    id: int
    titel: str
    url: str
    zeit: int
    punkte: int
    kommentare: int
    autor: str


def top_ids(abrufer: Abrufer, limit: int = 30, basis: str = HN_BASIS) -> list[int]:
    ergebnis = abrufer.hole_url(f"{basis}/topstories.json", "hn-top", bedingt=False)
    if not ergebnis.ok or not ergebnis.inhalt:
        return []
    try:
        daten = json.loads(ergebnis.inhalt)
    except json.JSONDecodeError:
        return []
    if not isinstance(daten, list):
        return []
    ids: list[int] = []
    for wert in daten[:limit]:
        try:
            ids.append(int(wert))
        except (TypeError, ValueError):
            continue
    return ids


def item(abrufer: Abrufer, kennung: int, basis: str = HN_BASIS) -> dict[str, object] | None:
    ergebnis = abrufer.hole_url(f"{basis}/item/{kennung}.json", f"hn-{kennung}",
                               bedingt=False)
    if not ergebnis.ok or not ergebnis.inhalt:
        return None
    try:
        daten = json.loads(ergebnis.inhalt)
    except json.JSONDecodeError:
        return None
    if not isinstance(daten, dict) or daten.get("deleted") or daten.get("dead"):
        return None
    return daten


def meldungen(abrufer: Abrufer, limit: int = 20, basis: str = HN_BASIS) -> list[HNMeldung]:
    raus: list[HNMeldung] = []
    for kennung in top_ids(abrufer, limit=limit, basis=basis):
        daten = item(abrufer, kennung, basis=basis)
        if not daten or daten.get("type") != "story":
            continue
        titel = str(daten.get("title") or "").strip()
        if not titel:
            continue
        link = str(daten.get("url") or f"https://news.ycombinator.com/item?id={kennung}")
        raus.append(
            HNMeldung(
                id=kennung,
                titel=titel,
                url=link,
                zeit=int(daten.get("time") or 0),
                punkte=int(daten.get("score") or 0),
                kommentare=int(daten.get("descendants") or 0),
                autor=str(daten.get("by") or ""),
            )
        )
        if len(raus) >= limit:
            break
    return raus
