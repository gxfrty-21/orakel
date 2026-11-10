"""Speichert Nexus-Meldungen in der Fakten-DB.

Die Tabelle ``artikel`` bleibt die sichtbare Artikelliste. Dort landet pro
Cluster nur das **Original**; Kopien würden sonst die Artikelliste aufblähen.
Jede Meldung — auch jede Kopie — wird in ``nexus_meldungen`` festgehalten und
auf das Original verlinkt. Damit ist die Dublettenquote messbar und keine
Meldung geht verloren.

Reihenfolge der Prüfungen:

1. Wurde genau diese Meldung (Quelle, Titel, URL) schon gesehen? → Wiederholung.
2. Liegt der SimHash nahe an einem bekannten Original? → Dublette.
3. Sonst: Artikel speichern und als Original in den Index aufnehmen.

Der SimHash-Index wird beim Start aus den vorhandenen Originalen aufgebaut.
So werden auch Kopien erkannt, die erst in einem späteren Nachtlauf auftauchen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..db import Facts
from .dedup import (DedupIndex, MIN_GRAMME, STANDARD_SCHWELLE, STANDARD_SHINGLE,
                     shingles, simhash, titel_hash)
from .feeds import Meldung
from .quellen import Quelle
from .sprache import erkenne


def _jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True, slots=True)
class SpeicherErgebnis:
    status: str
    artikel_id: int | None = None
    cluster_id: str | None = None
    sprache: str = ""
    konfidenz: float = 0.0
    methode: str = ""
    fehler: str | None = None


class MeldungSpeicher:
    """Verbindet Parser, Spracherkennung, SimHash und SQLite."""

    def __init__(self, db: Facts, schwelle: int = STANDARD_SCHWELLE,
                 shingle: int = STANDARD_SHINGLE) -> None:
        self.db = db
        self.shingle = int(shingle)
        self.index = DedupIndex(schwelle)
        self._index_laden()

    def _index_laden(self) -> None:
        for zeile in self.db.nexus_originale():
            text = f"{zeile['titel']} {zeile['zusammenfassung']}".strip()
            self.index.hinzufuegen(
                int(zeile["simhash"], 16),
                str(zeile["cluster_id"]),
                int(zeile["artikel_id"]),
                str(zeile["meldung_key"]),
                shingles(text, self.shingle),
            )

    def speichere(self, meldung: Meldung, quelle: Quelle,
                  abgerufen_am: str | None = None) -> SpeicherErgebnis:
        key = meldung.kennung
        bekannt = self.db.nexus_meldung(key)
        if bekannt is not None:
            return SpeicherErgebnis(
                "wiederholung", int(bekannt["artikel_id"]), str(bekannt["cluster_id"]),
                str(bekannt["sprache"]), float(bekannt["sprache_konfidenz"]),
                str(bekannt["sprache_methode"]),
            )

        text = f"{meldung.titel} {meldung.zusammenfassung}".strip()
        sprache = erkenne(text, quelle.sprache)
        wert = simhash(text, self.shingle)
        signatur = shingles(text, self.shingle)
        # Bei sehr kurzen Titeln ist SimHash unzuverlässig. Dort entscheidet
        # der exakte Titel-Hash; der Cluster-Index bleibt außen vor.
        treffer = (self.index.finde(wert, signatur)
                   if len(signatur) >= MIN_GRAMME else None)

        if treffer is not None:
            gespeichert = self._dublette(meldung, quelle, treffer, wert, sprache,
                                         abgerufen_am)
            return gespeichert

        artikel_id = self.db.artikel_speichern(
            quelle.name, quelle.typ, meldung.titel, meldung.url,
            meldung.veroeffentlicht, meldung.zusammenfassung,
            round(max(0.0, min(1.0, float(quelle.gewicht))), 2),
            [], titel_hash(meldung.titel),
        )
        if artikel_id is None:
            # Bereits im alten Spider oder in einem früheren Lauf gespeichert,
            # aber noch nicht im Nexus-Index. Als Dublette verlinken.
            vorhanden = self.db.artikel_id_by_url_oder_hash(
                meldung.url, titel_hash(meldung.titel))
            if vorhanden is None:
                return SpeicherErgebnis("fehler", fehler="Artikel vorhanden, id fehlt")
            cluster_id = key
            self.index.hinzufuegen(wert, cluster_id, vorhanden, key, signatur)
            neu = self.db.nexus_meldung_speichern(
                key, vorhanden, cluster_id, f"{wert:016x}", sprache.code,
                sprache.konfidenz, sprache.methode, False, quelle.id,
                meldung.titel, meldung.zusammenfassung, meldung.url,
                abgerufen_am or _jetzt(),
            )
            if not neu:
                return SpeicherErgebnis("wiederholung", vorhanden, cluster_id,
                                        sprache.code, sprache.konfidenz,
                                        sprache.methode)
            return SpeicherErgebnis("dublette", vorhanden, cluster_id, sprache.code,
                                    sprache.konfidenz, sprache.methode)

        cluster_id = key
        self.db.nexus_meldung_speichern(
            key, artikel_id, cluster_id, f"{wert:016x}", sprache.code,
            sprache.konfidenz, sprache.methode, True, quelle.id,
            meldung.titel, meldung.zusammenfassung, meldung.url,
            abgerufen_am or _jetzt(),
        )
        self.index.hinzufuegen(wert, cluster_id, artikel_id, key, signatur)
        return SpeicherErgebnis("neu", artikel_id, cluster_id, sprache.code,
                                sprache.konfidenz, sprache.methode)

    def _dublette(self, meldung: Meldung, quelle: Quelle, cluster,
                  wert: int, sprache, abgerufen_am: str | None) -> SpeicherErgebnis:
        neu = self.db.nexus_meldung_speichern(
            meldung.kennung, cluster.artikel_id, cluster.cluster_id, f"{wert:016x}",
            sprache.code, sprache.konfidenz, sprache.methode, False, quelle.id,
            meldung.titel, meldung.zusammenfassung, meldung.url,
            abgerufen_am or _jetzt(),
        )
        if not neu:
            return SpeicherErgebnis("wiederholung", cluster.artikel_id,
                                    cluster.cluster_id, sprache.code,
                                    sprache.konfidenz, sprache.methode)
        return SpeicherErgebnis("dublette", cluster.artikel_id, cluster.cluster_id,
                                sprache.code, sprache.konfidenz, sprache.methode)
