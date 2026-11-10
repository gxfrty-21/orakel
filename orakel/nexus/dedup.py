"""SimHash für kopierte und leicht umformulierte Meldungen.

Kein Modell, keine Embeddings: Jeder Text wird in Zeichen-5-Gramme zerlegt,
jedes Gramm wird stabil gehasht und die 64 Bits werden mehrheitlich gesetzt.
Zwei Texte mit kleinen Unterschieden liegen dann meist nur wenige Bits
auseinander.

Zeichen-5-Gramme statt Wort-Shingles: Ein eingefügtes Wort verschiebt bei
Wort-Dreiergruppen alle folgenden Shingles und kippt dadurch viele Bits. Auf
Zeichenebene bleibt die Kopie dagegen stabil — auch bei Chinesisch, Japanisch
und Koreanisch, wo es keine Leerzeichen gibt.

SimHash allein ist nur ein Kandidatenfilter. Ein Treffer wird zusätzlich über
die Jaccard-Ähnlichkeit der Gramm-Mengen bestätigt. So werden Themen mit
ähnlichem Wortschatz nicht automatisch als Kopie verworfen.

Grenzen, die dazugehören:

- Der Index ist eine lineare Suche. Bei einigen tausend Meldungen ist das
  völlig ausreichend; für Millionen bräuchte es LSH-Bänder.
- Sehr kurze Texte (unter etwa 10 Grammen) sind für SimHash unzuverlässig.
  Für sie greift der exakte Titel-Hash in der Speicherung.
- Eine Schwelle von 10 Bits und Jaccard 0,55 ist eine Heuristik, kein Beweis
  für eine Kopie.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

STANDARD_SCHWELLE = 10
STANDARD_SHINGLE = 5
STANDARD_AEHNLICHKEIT = 0.55
MIN_GRAMME = 10


def normalisiere(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def titel_hash(titel: str) -> str:
    """Gleiche Normalisierung wie der bestehende Spider.

    Dadurch erkennt die alte und die neue Pipeline identische Titel. Die
    Normalisierung entfernt Akzente; das ist bewusst konservativ und wird in
    Phase 2 nicht rückwirkend geändert.
    """
    normal = re.sub(r"[^a-z0-9äöü]+", "", (titel or "").lower())
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()[:32]


def shingles(text: str, groesse: int = STANDARD_SHINGLE) -> frozenset[str]:
    """Menge der Zeichen-N-Gramme. Leerer Text hat keine Gramme."""
    text = normalisiere(text)
    if not text:
        return frozenset()
    if len(text) <= groesse:
        return frozenset((text,))
    return frozenset(text[i:i + groesse] for i in range(len(text) - groesse + 1))


def simhash(text: str, groesse: int = STANDARD_SHINGLE) -> int:
    """64-Bit-SimHash. Stabil über Prozesse hinweg (blake2b, kein ``hash``)."""
    teile = shingles(text, groesse)
    if not teile:
        return 0
    vektor = [0] * 64
    for teil in sorted(teile):
        wert = int.from_bytes(
            hashlib.blake2b(teil.encode("utf-8"), digest_size=8).digest(), "big")
        for bit in range(64):
            vektor[bit] += 1 if (wert >> bit) & 1 else -1
    ergebnis = 0
    for bit, stimmen in enumerate(vektor):
        if stimmen >= 0:
            ergebnis |= 1 << bit
    return ergebnis


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    vereinigung = len(a | b)
    return len(a & b) / vereinigung if vereinigung else 0.0


@dataclass(slots=True)
class Cluster:
    simhash: int
    cluster_id: str
    artikel_id: int
    meldung_key: str
    signatur: frozenset[str] = field(default_factory=frozenset)


class DedupIndex:
    """Lineare Suche über bereits gesehene Originale, mit Jaccard-Bestätigung."""

    def __init__(self, schwelle: int = STANDARD_SCHWELLE,
                 min_aehnlichkeit: float = STANDARD_AEHNLICHKEIT) -> None:
        self.schwelle = int(schwelle)
        self.min_aehnlichkeit = float(min_aehnlichkeit)
        self._cluster: list[Cluster] = []
        self._nach_id: dict[str, Cluster] = {}

    def __len__(self) -> int:
        return len(self._cluster)

    @property
    def cluster(self) -> tuple[Cluster, ...]:
        return tuple(self._cluster)

    def finde(self, wert: int, signatur: frozenset[str]) -> Cluster | None:
        kandidaten: list[tuple[float, int, str, Cluster]] = []
        for cluster in self._cluster:
            abstand = hamming(wert, cluster.simhash)
            if abstand > self.schwelle:
                continue
            aehnlich = jaccard(signatur, cluster.signatur)
            if aehnlich < self.min_aehnlichkeit:
                continue
            kandidaten.append((aehnlich, abstand, cluster.cluster_id, cluster))
        if not kandidaten:
            return None
        # Beste Ähnlichkeit, dann kleinste Distanz, dann stabile Cluster-ID.
        return min(kandidaten, key=lambda p: (-p[0], p[1], p[2]))[3]

    def hinzufuegen(self, wert: int, cluster_id: str, artikel_id: int,
                    meldung_key: str, signatur: frozenset[str]) -> Cluster:
        vorhanden = self._nach_id.get(cluster_id)
        if vorhanden is not None:
            return vorhanden
        cluster = Cluster(wert, cluster_id, int(artikel_id), meldung_key,
                          frozenset(signatur))
        self._cluster.append(cluster)
        self._nach_id[cluster_id] = cluster
        return cluster
