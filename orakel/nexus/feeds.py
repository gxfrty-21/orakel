"""Feed-Parser für RSS 2.0, RSS 1.0 (RDF) und Atom.

Der bestehende Spider findet nur RSS-2.0-``item`` ohne Namespace. Sechs der
geprüften Quellen liefern RDF (RSS 1.0) und wurden dadurch leer gelesen.
Dieser Parser behandelt alle drei Formen und relative Links.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .quellen import Quelle

RDF = "{http://purl.org/rss/1.0/}"
ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"


@dataclass(slots=True)
class Meldung:
    quelle_id: str
    titel: str
    url: str
    veroeffentlicht: str | None
    zusammenfassung: str
    sprache: str
    land: str

    @property
    def kennung(self) -> str:
        """Stabile Kennung für spätere Dubletten-Erkennung (Phase 2)."""
        roh = f"{self.quelle_id}|{self.titel}|{self.url}"
        return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:32]


def _saeubern(roh: str, grenze: int = 600) -> str:
    # Erst Entities auflösen, dann Tags entfernen: sonst bleibt aus
    # ``&lt;p&gt;`` ein sichtbares ``<p>`` im Text stehen.
    text = html_mod.unescape(roh or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:grenze]


def _text(eintrag: ET.Element, *tags: str) -> str:
    for tag in tags:
        wert = eintrag.findtext(tag)
        if wert and wert.strip():
            return wert.strip()
    return ""


def _link(eintrag: ET.Element) -> str:
    for tag in ("link", f"{ATOM}link", f"{RDF}link"):
        element = eintrag.find(tag)
        if element is None:
            continue
        if element.text and element.text.strip():
            return element.text.strip()
        href = element.attrib.get("href", "").strip()
        if href:
            return href
    return ""


def parse_feed(roh: bytes, quelle: Quelle) -> list[Meldung]:
    """Liest alle Einträge. Wirft ``ET.ParseError`` bei kaputtem XML."""
    wurzel = ET.fromstring(roh)
    eintraege = (
        wurzel.findall(".//item")
        + wurzel.findall(f".//{RDF}item")
        + wurzel.findall(f".//{ATOM}entry")
    )

    meldungen: list[Meldung] = []
    for eintrag in eintraege:
        titel = _saeubern(_text(eintrag, "title", f"{RDF}title", f"{ATOM}title"), 200)
        link = _link(eintrag)
        if not titel or not link:
            continue
        link = urljoin(quelle.url, link)
        if urlparse(link).scheme not in ("http", "https"):
            continue
        beschreibung = _text(
            eintrag, "description", f"{RDF}description", f"{ATOM}summary", f"{ATOM}content"
        )
        datum = _text(eintrag, "pubDate", f"{DC}date", f"{ATOM}published", f"{ATOM}updated")
        meldungen.append(
            Meldung(
                quelle_id=quelle.id,
                titel=titel,
                url=link,
                veroeffentlicht=datum or None,
                zusammenfassung=_saeubern(beschreibung),
                sprache=quelle.sprache,
                land=quelle.land,
            )
        )
    return meldungen
