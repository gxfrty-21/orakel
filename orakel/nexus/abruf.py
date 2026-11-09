"""Höflicher HTTP-Abruf mit bedingten Anfragen.

Der Cache speichert nur Metadaten (ETag, Last-Modified), nicht die Inhalte.
Ein 304 bedeutet: unverändert, kein Body, kein erneutes Parsen nötig.

Regeln:
- ein Abruf pro Host höchstens alle ``min_abstand_sekunden``
- nach ``fehlerbudget`` Fehlern in Folge wird der Host für ``pause_sekunden``
  pausiert, statt ihn weiter zu belasten
- harte Obergrenze für die Antwortgröße
- HTML statt Feed wird als Fehler gewertet, nicht als Inhalt
"""

from __future__ import annotations

import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .quellen import Quelle

MAX_BYTES = 2_000_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS nexus_http_cache (
    url TEXT PRIMARY KEY,
    etag TEXT,
    last_modified TEXT,
    abgerufen_am TEXT NOT NULL,
    status INTEGER NOT NULL,
    groesse INTEGER NOT NULL DEFAULT 0
);
"""


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class CacheEintrag:
    url: str
    etag: str | None
    last_modified: str | None
    abgerufen_am: str
    status: int
    groesse: int


@dataclass(slots=True)
class AbrufErgebnis:
    quelle_id: str
    url: str
    status: int
    inhalt: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    aus_cache: bool = False
    fehler: str | None = None
    dauer_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.fehler is None


class HttpCache:
    """ETag-Metadaten in derselben SQLite-Datei wie die übrigen Fakten."""

    def __init__(self, pfad: str | Path) -> None:
        self.pfad = Path(pfad)
        self._anlegen()

    def _verbindung(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.pfad, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _anlegen(self) -> None:
        conn = self._verbindung()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()

    def hole(self, url: str) -> CacheEintrag | None:
        conn = self._verbindung()
        try:
            zeile = conn.execute(
                "SELECT url, etag, last_modified, abgerufen_am, status, groesse "
                "FROM nexus_http_cache WHERE url = ?",
                (url,),
            ).fetchone()
        finally:
            conn.close()
        if not zeile:
            return None
        return CacheEintrag(**dict(zeile))

    def speichere(self, url: str, status: int, etag: str | None,
                  last_modified: str | None, groesse: int) -> None:
        conn = self._verbindung()
        try:
            conn.execute(
                "INSERT INTO nexus_http_cache (url, etag, last_modified, abgerufen_am, status, groesse) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, "
                "last_modified = excluded.last_modified, abgerufen_am = excluded.abgerufen_am, "
                "status = excluded.status, groesse = excluded.groesse",
                (url, etag, last_modified, _jetzt(), status, groesse),
            )
            conn.commit()
        finally:
            conn.close()

    def beruehre(self, url: str, etag: str | None = None,
                 last_modified: str | None = None) -> None:
        """Nach einem 304: Abrufzeitpunkt (und ggf. neue Validatoren) festhalten."""
        conn = self._verbindung()
        try:
            conn.execute(
                "UPDATE nexus_http_cache SET abgerufen_am = ?, "
                "etag = COALESCE(?, etag), last_modified = COALESCE(?, last_modified) "
                "WHERE url = ?",
                (_jetzt(), etag, last_modified, url),
            )
            conn.commit()
        finally:
            conn.close()

    def statistik(self) -> dict[str, object]:
        conn = self._verbindung()
        try:
            zeile = conn.execute(
                "SELECT COUNT(*) AS anzahl, COALESCE(SUM(groesse), 0) AS bytes, "
                "MIN(abgerufen_am) AS aelteste, MAX(abgerufen_am) AS neueste "
                "FROM nexus_http_cache"
            ).fetchone()
        finally:
            conn.close()
        return dict(zeile) if zeile else {"anzahl": 0, "bytes": 0, "aelteste": None, "neueste": None}


class Abrufer:
    """Führt bedingte Anfragen aus und respektiert Host-Grenzen."""

    def __init__(
        self,
        cache: HttpCache,
        user_agent: str,
        timeout: float = 15.0,
        max_bytes: int = MAX_BYTES,
        min_abstand_sekunden: float = 1.0,
        fehlerbudget: int = 3,
        pause_sekunden: float = 300.0,
        oeffnen: Callable[..., object] | None = None,
        uhr: Callable[[], float] = time.monotonic,
        schlaf: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache = cache
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.min_abstand_sekunden = min_abstand_sekunden
        self.fehlerbudget = fehlerbudget
        self.pause_sekunden = pause_sekunden
        self.oeffnen = oeffnen or urllib.request.urlopen
        self.uhr = uhr
        self.schlaf = schlaf
        self._letzter_abruf: dict[str, float] = {}
        self._fehler: dict[str, tuple[int, float]] = {}

    @staticmethod
    def _host(url: str) -> str:
        return urlparse(url).netloc.lower()

    def _warten(self, host: str) -> None:
        letzter = self._letzter_abruf.get(host)
        if letzter is not None:
            rest = self.min_abstand_sekunden - (self.uhr() - letzter)
            if rest > 0:
                self.schlaf(rest)
        self._letzter_abruf[host] = self.uhr()

    def _fehler_zaehlen(self, host: str) -> None:
        anzahl = self._fehler.get(host, (0, 0.0))[0] + 1
        bis = self.uhr() + self.pause_sekunden if anzahl >= self.fehlerbudget else 0.0
        self._fehler[host] = (anzahl, bis)

    def _erfolg(self, host: str) -> None:
        self._fehler.pop(host, None)

    def pausiert(self, url: str) -> bool:
        anzahl, bis = self._fehler.get(self._host(url), (0, 0.0))
        return anzahl >= self.fehlerbudget and self.uhr() < bis

    def hole(self, quelle: Quelle, bedingt: bool = True) -> AbrufErgebnis:
        return self.hole_url(quelle.url, quelle.id, bedingt=bedingt)

    def hole_url(self, url: str, quelle_id: str = "", bedingt: bool = True) -> AbrufErgebnis:
        host = self._host(url)
        if self.pausiert(url):
            anzahl, _ = self._fehler.get(host, (0, 0.0))
            return AbrufErgebnis(quelle_id, url, 0,
                                 fehler=f"Host pausiert nach {anzahl} Fehlern")

        self._warten(host)
        eintrag = self.cache.hole(url) if bedingt else None
        kopf = {
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, "
                      "text/xml, application/json;q=0.9, */*;q=0.5",
        }
        if eintrag and eintrag.etag:
            kopf["If-None-Match"] = eintrag.etag
        if eintrag and eintrag.last_modified:
            kopf["If-Modified-Since"] = eintrag.last_modified

        start = self.uhr()
        try:
            with self.oeffnen(urllib.request.Request(url, headers=kopf),
                              timeout=self.timeout) as antwort:
                status = int(getattr(antwort, "status", 200) or 200)
                kopfzeilen = antwort.headers
                ctype = (kopfzeilen.get("Content-Type") or "").lower()
                etag = kopfzeilen.get("ETag")
                last_modified = kopfzeilen.get("Last-Modified")
                if status == 304:
                    self.cache.beruehre(url, etag, last_modified)
                    self._erfolg(host)
                    return AbrufErgebnis(
                        quelle_id, url, 304, etag=etag, last_modified=last_modified,
                        aus_cache=True, dauer_ms=self._dauer(start),
                    )
                roh = antwort.read(self.max_bytes + 1)
        except urllib.error.HTTPError as exc:
            # urllib wirft auch bei 304 eine HTTPError — das ist kein Fehler.
            if exc.code == 304:
                self.cache.beruehre(url, exc.headers.get("ETag"),
                                    exc.headers.get("Last-Modified"))
                self._erfolg(host)
                return AbrufErgebnis(quelle_id, url, 304, aus_cache=True,
                                     etag=exc.headers.get("ETag"),
                                     last_modified=exc.headers.get("Last-Modified"),
                                     dauer_ms=self._dauer(start))
            self._fehler_zaehlen(host)
            return AbrufErgebnis(quelle_id, url, exc.code,
                                 fehler=f"HTTP {exc.code}", dauer_ms=self._dauer(start))
        except Exception as exc:  # Netzfehler jeder Art stoppen nie den gesamten Lauf
            self._fehler_zaehlen(host)
            return AbrufErgebnis(quelle_id, url, 0, fehler=type(exc).__name__,
                                 dauer_ms=self._dauer(start))

        if len(roh) > self.max_bytes:
            self._fehler_zaehlen(host)
            return AbrufErgebnis(quelle_id, url, status,
                                 fehler=f"Antwort über {self.max_bytes} Bytes",
                                 dauer_ms=self._dauer(start))
        if "text/html" in ctype:
            self._fehler_zaehlen(host)
            return AbrufErgebnis(quelle_id, url, status,
                                 fehler=f"HTML statt Feed ({ctype})",
                                 dauer_ms=self._dauer(start))

        self.cache.speichere(url, status, etag, last_modified, len(roh))
        self._erfolg(host)
        return AbrufErgebnis(quelle_id, url, status, inhalt=roh, etag=etag,
                             last_modified=last_modified, dauer_ms=self._dauer(start))

    def _dauer(self, start: float) -> int:
        return int((self.uhr() - start) * 1000)
