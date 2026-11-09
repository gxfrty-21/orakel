"""Quellenregister des Nexus.

Jede Quelle ist eine Zeile in ``register.toml``. Das Register ist Daten, kein
Code: Neue Feeds kommen ohne Python-Änderung dazu. Was ungültig ist, wird beim
Laden gemeldet — nicht stillschweigend ignoriert.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

TYPEN = ("rss", "json_api", "oauth", "csv")
STANDARD_REGISTER = Path(__file__).with_name("register.toml")


@dataclass(frozen=True, slots=True)
class Quelle:
    id: str
    name: str
    typ: str
    url: str
    land: str
    sprache: str
    thema: str
    gewicht: float = 0.5
    aktiv: bool = True
    intervall_minuten: int = 30


def lade_register(pfad: str | Path | None = None) -> list[Quelle]:
    """Lädt und validiert das Register. Ungültige Register werden abgelehnt."""
    p = Path(pfad) if pfad else STANDARD_REGISTER
    with p.open("rb") as fh:
        rohdaten = tomllib.load(fh)

    quellen: list[Quelle] = []
    fehler: list[str] = []
    for nummer, eintrag in enumerate(rohdaten.get("quelle") or [], start=1):
        try:
            quellen.append(
                Quelle(
                    id=str(eintrag["id"]).strip(),
                    name=str(eintrag["name"]).strip(),
                    typ=str(eintrag["typ"]).strip(),
                    url=str(eintrag["url"]).strip(),
                    land=str(eintrag["land"]).strip().upper(),
                    sprache=str(eintrag["sprache"]).strip().lower(),
                    thema=str(eintrag["thema"]).strip(),
                    gewicht=float(eintrag.get("gewicht", 0.5)),
                    aktiv=bool(eintrag.get("aktiv", True)),
                    intervall_minuten=int(eintrag.get("intervall_minuten", 30)),
                )
            )
        except KeyError as exc:
            fehler.append(f"Quelle {nummer}: Pflichtfeld {exc.args[0]} fehlt")

    fehler.extend(pruefe_register(quellen))
    if fehler:
        raise ValueError("Quellenregister ungültig: " + "; ".join(fehler))
    return quellen


def pruefe_register(quellen: list[Quelle]) -> list[str]:
    """Prüft fachliche Regeln. Gibt alle Fehler zurück, nicht nur den ersten."""
    fehler: list[str] = []
    if not quellen:
        return ["Register ist leer"]

    gesehen: set[str] = set()
    for q in quellen:
        if not q.id:
            fehler.append("Quelle ohne id")
        if q.id in gesehen:
            fehler.append(f"doppelte id: {q.id}")
        gesehen.add(q.id)

        if q.typ not in TYPEN:
            fehler.append(f"{q.id}: unbekannter Typ {q.typ!r} (erlaubt: {', '.join(TYPEN)})")

        teil = urlparse(q.url)
        if teil.scheme not in ("http", "https") or not teil.netloc:
            fehler.append(f"{q.id}: ungültige URL {q.url!r}")

        if len(q.land) not in (2, 3):
            fehler.append(f"{q.id}: Land muss ISO-3166 (2) oder 'INT' sein, ist {q.land!r}")
        if len(q.sprache) != 2:
            fehler.append(f"{q.id}: Sprache muss zweistellig sein, ist {q.sprache!r}")
        if not 0.0 <= q.gewicht <= 1.0:
            fehler.append(f"{q.id}: Gewicht muss zwischen 0 und 1 liegen")
        if q.intervall_minuten < 5:
            fehler.append(f"{q.id}: Intervall unter 5 Minuten belastet Quellen unnötig")
    return fehler


def _zaehle(quellen: list[Quelle], feld: str) -> dict[str, int]:
    zaehler: dict[str, int] = {}
    for q in quellen:
        wert = str(getattr(q, feld))
        zaehler[wert] = zaehler.get(wert, 0) + 1
    return dict(sorted(zaehler.items(), key=lambda paar: (-paar[1], paar[0])))


def statistik(quellen: list[Quelle]) -> dict[str, object]:
    """Verteilung des Registers — die Grundlage für ``/api/nexus/status``."""
    return {
        "gesamt": len(quellen),
        "aktiv": sum(1 for q in quellen if q.aktiv),
        "nach_typ": _zaehle(quellen, "typ"),
        "nach_sprache": _zaehle(quellen, "sprache"),
        "nach_land": _zaehle(quellen, "land"),
        "nach_thema": _zaehle(quellen, "thema"),
    }
