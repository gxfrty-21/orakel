"""Spracherkennung als Heuristik — kein Modell, keine Übersetzung.

Die Quelle nennt oft schon eine Sprache. Sie ist aber nur ein Prior: Ein
englischer Feed kann eine deutsche Meldung zitieren, und ein deutscher Feed
kann eine englische Pressemitteilung übernehmen. Deshalb wird der tatsächliche
Text geprüft.

Zwei einfache Verfahren, offen benannt:

1. **Schriftzeichen.** Chinesisch, Japanisch, Koreanisch, Kyrillisch, Arabisch,
   Griechisch, Hebräisch und Devanagari sind an ihren Zeichen erkennbar.
2. **Stoppwörter.** Für lateinische Sprachen werden Funktionswörter gezählt.
   Das ist bei kurzen Titeln unsicher; dann fällt das Ergebnis auf die
   Quellensprache zurück und sagt das auch.

Das Ergebnis ist eine Schätzung. Es wird nie als sichere Erkenntnis verkauft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Nur eindeutige Funktionswörter. Mehrdeutige Kurzformen wie "in", "a", "e"
# oder "la" werden bewusst nicht allein als Beweis gewertet.
STOPPWOERTER: dict[str, frozenset[str]] = {
    "de": frozenset((
        "der", "die", "das", "den", "dem", "des", "und", "ist", "sind", "nicht",
        "mit", "für", "auf", "von", "ein", "eine", "einer", "einem", "eines",
        "im", "zu", "sich", "auch", "es", "wird", "werden", "bei", "aus", "nach",
        "wie", "über", "lässt", "bleibt", "steigt", "sinkt", "hat", "haben",
        "dass", "ob", "als", "vor", "durch", "gegen", "ohne", "um", "zum", "zur",
    )),
    "en": frozenset((
        "the", "and", "of", "to", "is", "that", "for", "on", "with", "as",
        "at", "by", "from", "it", "this", "be", "are", "or", "not", "has",
        "have", "will", "would", "can", "but", "its", "their", "they", "we",
        "was", "were", "been", "into", "than", "which", "while", "after",
    )),
    "fr": frozenset((
        "le", "la", "les", "et", "de", "des", "du", "un", "une", "est", "que",
        "qui", "dans", "pour", "pas", "sur", "au", "avec", "ce", "il", "elle",
        "en", "se", "ne", "plus", "par", "comme", "sont", "été", "être",
        "cette", "ces", "aux", "leur", "leurs", "mais", "ou", "où",
    )),
    "it": frozenset((
        "il", "lo", "la", "gli", "le", "di", "del", "della", "che", "e", "è",
        "un", "una", "per", "con", "non", "su", "da", "in", "al", "allo",
        "come", "più", "sono", "stato", "questa", "questo", "anche", "ma",
        "nel", "nella", "dei", "delle",
    )),
    "es": frozenset((
        "el", "la", "los", "las", "de", "del", "y", "que", "en", "un", "una",
        "es", "por", "con", "para", "no", "se", "al", "lo", "como", "más",
        "son", "fue", "esta", "este", "también", "pero", "sus", "entre",
        "desde", "hasta", "sobre",
    )),
    "pt": frozenset((
        "os", "as", "de", "do", "da", "que", "em", "um", "uma", "para", "com",
        "não", "por", "se", "ao", "como", "mais", "são", "foi", "esta", "este",
        "também", "mas", "seus", "entre", "desde", "até", "sobre",
    )),
    "nl": frozenset((
        "de", "het", "een", "en", "van", "is", "dat", "op", "te", "voor",
        "met", "niet", "zijn", "er", "maar", "om", "aan", "ook", "als", "bij",
        "uit", "naar", "dan", "nog", "wel", "wordt", "worden", "heeft",
    )),
}

# Reihenfolge ist wichtig: Kana/Hangul vor CJK, weil japanische Texte auch
# chinesische Zeichen enthalten.
SKRIPTE: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("ja", re.compile(r"[\u3040-\u30ff]"), 2),
    ("ko", re.compile(r"[\uac00-\ud7af]"), 2),
    ("zh", re.compile(r"[\u4e00-\u9fff]"), 3),
    ("ru", re.compile(r"[\u0400-\u04ff]"), 3),
    ("ar", re.compile(r"[\u0600-\u06ff]"), 3),
    ("el", re.compile(r"[\u0370-\u03ff]"), 3),
    ("he", re.compile(r"[\u0590-\u05ff]"), 3),
    ("hi", re.compile(r"[\u0900-\u097f]"), 3),
)

BUCHSTABE = re.compile(r"[^\W\d_]", re.UNICODE)
WORT = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SprachErgebnis:
    code: str
    konfidenz: float
    methode: str


def _zeichen_sprache(text: str) -> SprachErgebnis | None:
    buchstaben = len(BUCHSTABE.findall(text))
    if buchstaben < 3:
        return None
    for code, muster, minimum in SKRIPTE:
        treffer = len(muster.findall(text))
        anteil = treffer / buchstaben
        if treffer >= minimum and anteil >= 0.2:
            return SprachErgebnis(code, round(min(0.95, 0.55 + 0.4 * anteil), 2),
                                 "zeichen")
    return None


def _stoppwort_sprache(text: str) -> SprachErgebnis | None:
    tokens = [t.lower() for t in WORT.findall(text)]
    if len(tokens) < 2:
        return None
    treffer = {
        code: sum(1 for token in tokens if token in woerter)
        for code, woerter in STOPPWOERTER.items()
    }
    sortiert = sorted(treffer.items(), key=lambda paar: (-paar[1], paar[0]))
    best, anzahl = sortiert[0]
    zweit = sortiert[1][1] if len(sortiert) > 1 else 0
    gesamt = sum(treffer.values())
    if anzahl < 2 or anzahl <= zweit or gesamt == 0:
        return None
    konfidenz = round(min(0.95, 0.5 + 0.5 * anzahl / gesamt), 2)
    return SprachErgebnis(best, konfidenz, "stoppwoerter")


def erkenne(text: str, quelle_sprache: str | None = None) -> SprachErgebnis:
    """Schätzt die Sprache. Fällt bei Unsicherheit auf die Quelle zurück."""
    text = (text or "").strip()
    if not text:
        return _fallback(quelle_sprache)

    zeichen = _zeichen_sprache(text)
    if zeichen is not None:
        return zeichen

    stoppen = _stoppwort_sprache(text)
    if stoppen is not None:
        return stoppen

    return _fallback(quelle_sprache)


def _fallback(quelle_sprache: str | None) -> SprachErgebnis:
    code = (quelle_sprache or "").strip().lower()
    if len(code) == 2 and code.isalpha():
        return SprachErgebnis(code, 0.3, "quelle")
    return SprachErgebnis("und", 0.0, "unbekannt")
