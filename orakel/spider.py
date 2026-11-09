"""Spider Intelligence — das Informationsnetzwerk.

Regeln, an die sich dieser Code hält:
- Nur frei zugängliche Quellen (RSS).
- robots.txt wird vor jedem Abruf geprüft.
- Ein Abruf pro Host höchstens alle `min_abstand_sekunden`.
- Grössenlimit pro Antwort, harter Timeout.
- Dubletten werden über URL und Titel-Hash erkannt.
- Jede Erkenntnis behält ihre Quelle.

Ohne Netzwerkzugang bricht nichts: Der Lauf meldet die Fehler und macht weiter.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .db import Facts
from .knowledge import Vault

MAX_BYTES = 2_000_000

# Domains mit hoher Quellenqualität (Notenbanken, Statistik, etablierte Presse)
SERIOESE_DOMAINS = {
    "federalreserve.gov", "ecb.europa.eu", "bis.org", "imf.org", "oecd.org",
    "destatis.de", "bls.gov", "bea.gov", "sec.gov", "europa.eu",
    "reuters.com", "ft.com", "bloomberg.com", "wsj.com", "bbc.co.uk",
    "finance.yahoo.com", "apnews.com", "handelsblatt.com", "faz.net", "nzz.ch",
}

SENSATIONSWORTE = (
    "garantiert", "sicher reich", "verdopple", "100 % rendite", "geheimtipp",
    "wirst du nicht glauben", "krypto-millionär", "sofort kaufen",
)

# Marktbezug: Welche Symbole betrifft ein Text?
SYMBOL_WOERTER: dict[str, tuple[str, ...]] = {
    "EURUSD": ("ezb", "ecb", "euro", "eurozone", "eur/usd", "euro area"),
    "USDJPY": ("boj", "bank of japan", "yen", "japan"),
    "GBPUSD": ("boe", "bank of england", "pfund", "pound", "uk inflation"),
    "US500": ("s&p", "s&p 500", "wall street", "nasdaq", "aktien", "equities", "us-aktien"),
    "US30": ("dow", "dow jones", "industrials"),
    "GER40": ("dax", "german stocks", "deutsche börse"),
    "XAUUSD": ("gold", "goldpreis", "bullion"),
    "XTIUSD": ("öl", "oil", "crude", "opec", "brent", "wti"),
    "BTCUSD": ("bitcoin", "btc", "krypto", "crypto"),
}


@dataclass(slots=True)
class Artikel:
    quelle: str
    typ: str
    titel: str
    url: str
    veroeffentlicht: str | None = None
    zusammenfassung: str = ""
    qualitaet: float = 0.0
    symbole: list[str] = field(default_factory=list)

    @property
    def titel_hash(self) -> str:
        normal = re.sub(r"[^a-z0-9äöü]+", "", self.titel.lower())
        return hashlib.sha256(normal.encode("utf-8")).hexdigest()[:32]


def _text_saeubern(roh: str, grenze: int = 600) -> str:
    ohne_tags = re.sub(r"<[^>]+>", " ", roh or "")
    text = html_mod.unescape(ohne_tags)
    return re.sub(r"\s+", " ", text).strip()[:grenze]


def _text_aus_html(roh: str) -> str:
    """Liest den sichtbaren Text einer Seite. Skripte, Navigation und Fusszeilen fliegen raus."""
    ohne = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", roh or "")
    ohne = re.sub(r"(?is)<(header|footer|nav|aside)[^>]*>.*?</\1>", " ", ohne)
    text = re.sub(r"(?s)<[^>]+>", " ", ohne)
    return re.sub(r"\s+", " ", html_mod.unescape(text)).strip()


def _symbole_erkennen(text: str) -> list[str]:
    klein = text.lower()
    return [symbol for symbol, woerter in SYMBOL_WOERTER.items()
            if any(w in klein for w in woerter)]


def _qualitaet(quelle_gewicht: float, url: str, titel: str, text: str) -> float:
    """Heuristik, offen dokumentiert. Keine KI-Bewertung, keine erfundene Zahl."""
    wert = 0.15 + 0.35 * quelle_gewicht
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if any(host.endswith(d) for d in SERIOESE_DOMAINS):
        wert += 0.2
    if len(text) >= 400:
        wert += 0.15
    elif len(text) < 80:
        wert -= 0.1
    if re.search(r"\d", text):
        wert += 0.05
    if re.search(r"\d{1,2}\.\s?\d{1,2}\.|\b20\d\d\b", text):
        wert += 0.05
    if any(w in (titel + " " + text).lower() for w in SENSATIONSWORTE):
        wert -= 0.35
    if titel.isupper() or titel.count("!") >= 2:
        wert -= 0.1
    return round(max(0.0, min(1.0, wert)), 2)


class Spider:
    """Sammelt, prüft und speichert Informationen. Jede Aussage behält ihre Quelle."""

    def __init__(
        self,
        cfg: Any,
        db: Facts,
        vault: Vault,
        abrufer: Callable[[str, int, str], bytes | None] | None = None,
        schlaf: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.vault = vault
        self.s = cfg.abschnitt("spider") or {}
        for schluessel, standard in (
            ("max_artikel_pro_lauf", 24), ("max_notizen_pro_lauf", 8),
            ("min_qualitaet", 0.35), ("timeout_sekunden", 10),
            ("min_abstand_sekunden", 1.5),
            ("max_seiten_pro_lauf", 6), ("max_text_zeichen", 6000),
            ("user_agent", "OrakelResearchBot/0.1"),
        ):
            self.s.setdefault(schluessel, standard)
        self.abrufer = abrufer or self._abrufen_std
        self.schlaf = schlaf
        self._robots: dict[str, RobotFileParser] = {}
        self._letzter_abruf: dict[str, float] = {}

    # ---------- Netzwerk ----------
    def _abrufen_std(self, url: str, timeout: int, user_agent: str) -> bytes | None:
        anfrage = urllib.request.Request(url, headers={"User-Agent": user_agent,
                                                      "Accept": "application/rss+xml, application/xml, text/xml"})
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:  # noqa: S310
            return antwort.read(MAX_BYTES)

    def _robots_fuer(self, basis: str) -> RobotFileParser:
        if basis in self._robots:
            return self._robots[basis]
        parser = RobotFileParser()
        parser.set_url(f"{basis}/robots.txt")
        try:
            roh = self.abrufer(f"{basis}/robots.txt", int(self.s["timeout_sekunden"]),
                               str(self.s["user_agent"]))
            parser.parse((roh or b"").decode("utf-8", "replace").splitlines())
        except Exception:
            # Nicht erreichbar: wir behandeln es wie "keine Regel gefunden",
            # protokollieren das aber als Warnung.
            parser.parse([])
            self.db.ereignis("warnung", "Spider", f"robots.txt nicht lesbar: {basis}")
        self._robots[basis] = parser
        return parser

    def erlaubt(self, url: str) -> bool:
        teil = urlparse(url)
        if teil.scheme not in ("http", "https"):
            return False
        basis = f"{teil.scheme}://{teil.netloc}"
        return self._robots_fuer(basis).can_fetch(str(self.s["user_agent"]), url)

    def _host_abstand(self, url: str) -> None:
        host = urlparse(url).netloc
        letzter = self._letzter_abruf.get(host)
        if letzter is not None:
            wartezeit = float(self.s["min_abstand_sekunden"]) - (time.monotonic() - letzter)
            if wartezeit > 0:
                self.schlaf(wartezeit)
        self._letzter_abruf[host] = time.monotonic()

    # ---------- RSS ----------
    def _feed_lesen(self, quelle: dict[str, Any]) -> list[Artikel]:
        url = quelle["url"]
        if not self.erlaubt(url):
            self.db.ereignis("warnung", "Spider", f"robots.txt verbietet {url}")
            return []
        self._host_abstand(url)
        try:
            roh = self.abrufer(url, int(self.s["timeout_sekunden"]), str(self.s["user_agent"]))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.db.ereignis("warnung", "Spider", f"{quelle['name']}: {exc}")
            return []
        if not roh:
            return []
        return self._parse(roh, quelle)

    def _parse(self, roh: bytes, quelle: dict[str, Any]) -> list[Artikel]:
        try:
            wurzel = ET.fromstring(roh)
        except ET.ParseError as exc:
            self.db.ereignis("warnung", "Spider", f"{quelle['name']}: XML unlesbar ({exc})")
            return []

        raus: list[Artikel] = []
        atom = "{http://www.w3.org/2005/Atom}"
        eintraege = wurzel.findall(".//item") or wurzel.findall(f".//{atom}entry")
        for eintrag in eintraege[:40]:
            titel = (eintrag.findtext("title") or eintrag.findtext(f"{atom}title") or "").strip()
            link = (eintrag.findtext("link") or "").strip()
            if not link:
                link_el = eintrag.find(f"{atom}link")
                if link_el is not None:
                    link = link_el.attrib.get("href", "")
            beschreibung = (eintrag.findtext("description")
                            or eintrag.findtext(f"{atom}summary")
                            or eintrag.findtext(f"{atom}content") or "")
            datum = (eintrag.findtext("pubDate") or eintrag.findtext(f"{atom}updated") or None)
            if not titel or not link:
                continue

            zusammenfassung = _text_saeubern(beschreibung)
            artikel = Artikel(
                quelle=str(quelle["name"]),
                typ=str(quelle["typ"]),
                titel=_text_saeubern(titel, 200),
                url=link,
                veroeffentlicht=datum,
                zusammenfassung=zusammenfassung,
                symbole=_symbole_erkennen(titel + " " + zusammenfassung),
            )
            artikel.qualitaet = _qualitaet(float(quelle.get("gewicht", 0.5)), link,
                                           artikel.titel, zusammenfassung)
            raus.append(artikel)
        return raus

    def _seite_lesen(self, url: str) -> str | None:
        """Holt den Volltext einer Meldung — nur wenn robots.txt es erlaubt."""
        if not url.startswith(("http://", "https://")) or not self.erlaubt(url):
            return None
        self._host_abstand(url)
        try:
            roh = self.abrufer(url, int(self.s["timeout_sekunden"]), str(self.s["user_agent"]))
        except Exception as exc:
            self.db.ereignis("warnung", "Spider", f"Seite nicht lesbar: {url} ({exc})")
            return None
        if not roh:
            return None
        text = _text_aus_html(roh.decode("utf-8", "replace"))
        probe = text[:600]
        if len(text) < 80 or (probe and sum(ch.isalpha() for ch in probe) / len(probe) < 0.4):
            return None
        return text[: int(self.s["max_text_zeichen"])]

    # ---------- Lauf ----------
    def lauf(self) -> dict[str, Any]:
        quellen = list(self.s.get("quelle") or [])
        limit = int(self.s["max_artikel_pro_lauf"])
        min_q = float(self.s["min_qualitaet"])
        max_notizen = int(self.s["max_notizen_pro_lauf"])

        gesammelt: list[Artikel] = []
        fehler: list[str] = []
        for quelle in quellen:
            try:
                gesammelt.extend(self._feed_lesen(quelle))
            except Exception as exc:  # eine defekte Quelle stoppt nie den Lauf
                fehler.append(f"{quelle.get('name')}: {exc}")

        gesammelt.sort(key=lambda a: a.qualitaet, reverse=True)
        neu = 0
        notizen = 0
        neu_ids: list[int] = []
        for artikel in gesammelt[:limit]:
            if artikel.qualitaet < min_q:
                continue
            aid = self.db.artikel_speichern(
                artikel.quelle, artikel.typ, artikel.titel, artikel.url,
                artikel.veroeffentlicht, artikel.zusammenfassung, artikel.qualitaet,
                artikel.symbole, artikel.titel_hash,
            )
            if not aid:
                continue
            neu += 1
            neu_ids.append(aid)
            if notizen < max_notizen:
                self.vault.notiz(
                    "wissen", artikel.titel,
                    f"**Quelle:** {artikel.quelle} ({artikel.typ})\n\n"
                    f"**Link:** {artikel.url}\n\n"
                    f"**Veröffentlicht:** {artikel.veroeffentlicht or 'unbekannt'}\n\n"
                    f"**Qualität (Heuristik):** {artikel.qualitaet}\n\n"
                    f"**Marktbezug:** {', '.join(artikel.symbole) or 'kein klarer Bezug'}\n\n"
                    f"{artikel.zusammenfassung or '_Keine Zusammenfassung in der Quelle._'}",
                    tags=["spider", artikel.typ, *(s.lower() for s in artikel.symbole)],
                    quelle=artikel.url,
                )
                notizen += 1

        # Volltext-Analyse: nur die neuesten Meldungen, begrenzt und höflich.
        analysiert = 0
        for aid in neu_ids:
            if analysiert >= int(self.s["max_seiten_pro_lauf"]):
                break
            zeile = self.db.artikel_by_ids([aid])
            if not zeile:
                continue
            a = zeile[0]
            volltext = self._seite_lesen(a["url"])
            if not volltext:
                continue
            try:
                symbole = set(json.loads(a["symbole"] or "[]"))
            except Exception:
                symbole = set()
            symbole |= set(_symbole_erkennen(a["titel"] + " " + volltext))
            qualitaet = float(a["qualitaet"])
            qualitaet += 0.05 if len(volltext) >= 800 else (-0.05 if len(volltext) < 200 else 0.0)
            qualitaet = round(max(0.0, min(1.0, qualitaet)), 2)
            self.db.artikel_inhalt_speichern(aid, volltext)
            self.db.artikel_aktualisieren(aid, qualitaet, sorted(symbole))
            analysiert += 1

        self.db.ereignis(
            "info" if neu else "warnung", "Spider",
            f"{len(quellen)} Quellen, {len(gesammelt)} Artikel gelesen, {neu} neu gespeichert"
            + (f", {len(fehler)} Fehler" if fehler else ""),
        )
        return {
            "quellen": len(quellen),
            "gelesen": len(gesammelt),
            "neu": neu,
            "notizen": notizen,
            "analysiert": analysiert,
            "neue_ids": neu_ids,
            "fehler": fehler,
            "top": [{"titel": a.titel, "quelle": a.quelle, "qualitaet": a.qualitaet,
                     "symbole": a.symbole, "url": a.url} for a in gesammelt[:8]],
            "statistik": self.db.artikel_statistik(),
        }
