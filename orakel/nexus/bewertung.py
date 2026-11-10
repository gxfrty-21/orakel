"""Phase 3: Quellenreputation, Bestätigungsgrad und Widersprüche.

Die Bewertung ist bewusst regelbasiert und offen begrenzt:

- Eine **Kernaussage** ist ein Satz aus Titel oder Zusammenfassung, der eine
  prüfbare Richtung, einen Wert oder eine Verneinung enthält. Ohne solches
  Muster wird keine Aussage erfunden.
- Der ``claim_key`` gruppiert Aussagen über Subjekt und Metrik (z. B.
  ``ezb`` + ``leitzins``). Das ist Oberflächenähnlichkeit, keine Semantik.
- **Kopien zählen nicht als unabhängige Bestätigung.** Sie bleiben als Belege
  sichtbar, aber nur Originale verschiedener Hosts erhöhen ``quellen``.
- **Widersprüche** entstehen nur bei unterschiedlichen Hosts und entweder
  entgegengesetzter Richtung oder unterschiedlicher Verneinung innerhalb des
  Zeitfensters. Das ist eine Heuristik; sie markiert Prüfbedarf, keine Wahrheit.
- Die **Quellenreputation** beginnt beim Registergewicht und wird durch echte
  Ergebnisse aus ``intel_quellen`` sowie erkannte Widersprüche angepasst.
  Ohne Ergebnis bleibt sie ausdrücklich ``vorläufig``.

Alle Zahlen kommen aus SQLite. Es gibt keine Demo-Claims und keine erfundenen
Bestätigungen.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Iterable
from urllib.parse import urlparse

from ..db import Facts, jetzt
from .quellen import Quelle, lade_register

FENSTER_TAGE = 7
PRIOR_GEWICHT = 4.0
SCHWELLE_BESTAETIGT = 0.7
SCHWELLE_TEILWEISE = 0.55
MAX_BELEGE_PRO_CLAIM = 200
MAX_GRUPPEN = 5000

# Themen nur für die Gruppierung. Die Wörter sind absichtlich wenige und
# nachvollziehbar; sie ersetzen keine semantische Analyse.
THEMEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("makro", ("ezb", "ecb", "fed", "notenbank", "leitzins", "zins", "inflation",
               "teuerung", "geldpolitik", "konjunktur", "bip", "arbeitsmarkt",
               "arbeitslosigkeit", "staatsanleihe", "interest rate", "economy",
               "economic", "gdp", "unemployment", "wages", "deficit")),
    ("unternehmen", ("gewinn", "umsatz", "quartal", "earnings", "bilanz", "aktie",
                     "unternehmen", "boersengang", "uebernahme", "revenue",
                     "profit", "sales", "company", "business", "shares")),
    ("markt", ("kurs", "index", "dax", "nasdaq", "rohstoff", "gold", "oel",
               "bitcoin", "rendite", "markt", "preis", "market", "stocks",
               "oil", "yield", "yields")),
    ("risiko", ("risiko", "drawdown", "volatilitaet", "absicherung", "hedge",
                "exposure", "klumpen", "risk", "volatility")),
    ("wissenschaft", ("studie", "paper", "forschung", "research", "journal",
                     "universitaet", "arxiv", "empirisch", "study", "scientists")),
    ("strategie", ("strategie", "signal", "backtest", "parameter", "modell",
                   "indikator", "ema", "rsi", "momentum", "strategy")),
)

METRIKEN: tuple[str, ...] = (
    "leitzins", "zinssatz", "zins", "inflation", "teuerung", "arbeitslosigkeit",
    "arbeitsmarkt", "bip", "wachstum", "gewinn", "umsatz", "rendite", "kurs",
    "preis", "oelpreis", "oel", "gold", "bitcoin", "anleihe", "staatsanleihe",
    "interest rate", "rate", "rates", "inflation", "growth", "revenue", "profit",
    "sales", "earnings", "gdp", "unemployment", "prices", "price", "oil", "yield",
    "yields", "debt", "deficit", "spending",
)

RICHTUNG_WOERTER: dict[str, tuple[str, ...]] = {
    "unveraendert": ("unveraendert", "unverandert", "haelt", "halten", "belaesst",
                     "laesst", "lassen", "konstant", "stabil", "bleibt", "bleiben",
                     "unchanged", "holds", "held", "steady", "flat", "stable",
                     "maintains", "maintained", "keeps", "kept"),
    "sinkt": ("sinkt", "sinken", "senkt", "senken", "gesenkt", "kuerzt", "kuerzen",
              "faellt", "fallen", "schrumpft", "schrumpfen", "verliert", "verlieren",
              "niedriger", "reduziert", "reduzieren", "falls", "fall", "fell",
              "falling", "drops", "dropped", "down", "lower", "decreases",
              "decreased", "declines", "declined", "slides", "slid", "slumps",
              "slumped", "cuts", "cut", "lowers", "lowered", "shrinks", "shrank"),
    "steigt": ("steigt", "steigen", "erhoeht", "erhoehen", "hebt", "anhebt",
               "anheben", "waechst", "wachsen", "gewinnt", "gewinnen", "hoeher",
               "zulegt", "zulegen", "erhoeht", "rises", "rise", "rose", "rising",
               "gains", "gained", "up", "higher", "increases", "increased",
               "climbs", "climbed", "surges", "surged", "jumps", "jumped",
               "grows", "grew", "raises", "raised", "hikes", "hiked"),
}

RICHTUNG_TOKENS = {w for werte in RICHTUNG_WOERTER.values() for w in werte}
NEGATION_TOKENS = {"nicht", "kein", "keine", "keinen", "keinem", "keiner",
                   "ohne", "nie", "niemals", "dementiert", "bestreitet",
                   "verneint", "not", "never", "without", "denies", "denied",
                   "rejects", "rejected"}
UNIT_TOKENS = {"prozent", "%", "basispunkte", "bp", "mrd", "mio", "milliarden",
               "millionen", "eur", "usd", "chf", "gbp", "jpy", "euro", "dollar"}

STOPPWOERTER = {
    "die", "der", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "eines", "und", "oder", "aber", "auf", "bei", "mit", "von", "vom", "zu",
    "zum", "zur", "im", "in", "am", "an", "als", "auch", "sich", "wird",
    "werden", "ist", "sind", "war", "waren", "hat", "haben", "hatte", "haette",
    "haetten", "laut", "nach", "vor", "fuer", "um", "bis", "aus", "durch",
    "the", "and", "of", "to", "in", "on", "for", "with", "from", "by", "at",
    "is", "are", "was", "were", "has", "have", "had", "will", "would", "can",
    "could", "not", "no", "its", "their", "this", "that", "these", "those",
    "as", "it", "be", "been", "being", "after", "before", "over", "under",
    "more", "less", "than", "says", "said", "amid", "into", "about", "new",
    "top", "may", "might", "should", "could", "still", "just", "now", "today",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}

ALIASE: tuple[tuple[str, str], ...] = (
    (r"\beuropaeische zentralbank\b", "ezb"),
    (r"\beuropean central bank\b", "ezb"),
    (r"\becb\b", "ezb"),
    (r"\bfederal reserve\b", "fed"),
    (r"\bbank of england\b", "boe"),
    (r"\bbank of japan\b", "boj"),
    (r"\bbank of canada\b", "boc"),
    (r"\breserve bank of australia\b", "rba"),
    (r"\bschweizerische nationalbank\b", "snb"),
    (r"\bswiss national bank\b", "snb"),
)


@dataclass(frozen=True, slots=True)
class Kernaussage:
    meldung_key: str
    artikel_id: int
    quelle_id: str
    host: str
    aussage: str
    thema: str
    subjekt: str
    metrik: str
    richtung: str
    wert: float | None
    einheit: str
    negiert: bool
    ist_kopie: bool
    erstellt: str

    @property
    def claim_key(self) -> str:
        return f"{self.thema}|{self.subjekt or 'allgemein'}|{self.metrik or 'allgemein'}"


def _normalisiere(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or "")).lower()
    text = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))
    text = re.sub(r"[^a-z0-9%.,]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _aliase(text: str) -> str:
    for muster, ersatz in ALIASE:
        text = re.sub(muster, ersatz, text)
    return text


def _host(url: str) -> str:
    host = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    return host or "unbekannt"


def _sauber(text: str, max_zeichen: int = 320) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_zeichen]


def _erster_satz(text: str) -> str:
    sauber = _sauber(text)
    if not sauber:
        return ""
    return re.split(r"(?<=[.!?])\s+", sauber)[0].strip()


def thema(text: str) -> str:
    normal = _normalisiere(text)
    for name, woerter in THEMEN:
        if any(w in normal for w in woerter):
            return name
    return "allgemein"


def richtung(text: str) -> str:
    normal = _normalisiere(text)
    for name in ("unveraendert", "sinkt", "steigt"):
        if any(re.search(rf"\b{re.escape(w)}\b", normal) for w in RICHTUNG_WOERTER[name]):
            return name
    return "unklar"


def negiert(text: str) -> bool:
    normal = _normalisiere(text)
    return any(re.search(rf"\b{re.escape(w)}\b", normal) for w in NEGATION_TOKENS)


def wert_und_einheit(text: str) -> tuple[float | None, str]:
    normal = _normalisiere(text)
    treffer = re.search(
        r"(?<![\w.])(\d{1,3}(?:[.,]\d+)?)\s*"
        r"(%|prozent|basispunkte|bp|mrd|mio|milliarden|millionen|eur|usd|chf|"
        r"gbp|jpy|euro|dollar)\b",
        normal,
    )
    if not treffer:
        return None, ""
    try:
        zahl = float(treffer.group(1).replace(",", "."))
    except ValueError:
        return None, ""
    einheit = treffer.group(2)
    einheit = {
        "prozent": "%", "basispunkte": "bp", "milliarden": "mrd",
        "millionen": "mio", "euro": "eur", "dollar": "usd",
    }.get(einheit, einheit)
    return zahl, einheit


def metrik(text: str) -> str:
    normal = _normalisiere(text)
    for name in METRIKEN:
        if re.search(rf"\b{re.escape(name)}\b", normal):
            return name
    return ""


def subjekt(text: str) -> str:
    normal = _aliase(_normalisiere(text))
    metric = metrik(normal)
    raus: list[str] = []
    for token in normal.split():
        token = token.strip(".,;:!?")
        if not token or token in STOPPWOERTER:
            continue
        if token in RICHTUNG_TOKENS or token in NEGATION_TOKENS or token in UNIT_TOKENS:
            continue
        if token == metric or token in METRIKEN:
            continue
        # Zahlen, Prozente und Datumsreste gehören nicht ins Subjekt.
        if len(token) < 3 or any(zeichen.isdigit() for zeichen in token):
            continue
        if token not in raus:
            raus.append(token)
        if len(raus) >= 4:
            break
    return " ".join(raus)


def _aussage_aus_text(text: str) -> dict[str, Any] | None:
    sauber = _sauber(text)
    if not sauber:
        return None
    # Eine Frage ist keine Behauptung.
    if sauber.rstrip().endswith("?"):
        return None
    richtung_wert = richtung(sauber)
    zahl, einheit = wert_und_einheit(sauber)
    negiert_wert = negiert(sauber)
    subj = subjekt(sauber)
    metric = metrik(sauber)
    # Eine Verneinung allein ist noch keine Aussage: „not for distribution“
    # ist eine Rechtsfloskel, keine Kernaussage. Es braucht eine Metrik oder
    # einen konkreten Wert; ohne Richtung muss mindestens der Wert bleiben.
    if not metric and zahl is None:
        return None
    if richtung_wert == "unklar" and zahl is None:
        return None
    if not subj and not metric:
        return None
    return {
        "aussage": sauber,
        "thema": thema(sauber),
        "subjekt": subj,
        "metrik": metric,
        "richtung": richtung_wert,
        "wert": zahl,
        "einheit": einheit,
        "negiert": negiert_wert,
    }


def extrahiere_aussage(meldung: Any, quellen: dict[str, Quelle] | None = None) -> Kernaussage | None:
    """Eine Meldung ergibt höchstens eine Kernaussage.

    Zuerst der Titel, nur bei fehlendem Muster der erste Satz der
    Zusammenfassung. Damit entstehen keine künstlichen Mehrfach-Claims aus
    derselben Meldung.
    """
    quellen = quellen or {}
    basis = _aussage_aus_text(str(meldung["titel"] or ""))
    if basis is None:
        basis = _aussage_aus_text(_erster_satz(str(meldung["zusammenfassung"] or "")))
    if basis is None:
        return None

    quelle = quellen.get(str(meldung["quelle_id"]))
    host = _host(quelle.url) if quelle is not None else _host(str(meldung["url"] or ""))
    return Kernaussage(
        meldung_key=str(meldung["meldung_key"]),
        artikel_id=int(meldung["artikel_id"]),
        quelle_id=str(meldung["quelle_id"]),
        host=host,
        aussage=basis["aussage"],
        thema=basis["thema"],
        subjekt=basis["subjekt"],
        metrik=basis["metrik"],
        richtung=basis["richtung"],
        wert=basis["wert"],
        einheit=basis["einheit"],
        negiert=bool(basis["negiert"]),
        ist_kopie=not bool(int(meldung["ist_original"])),
        erstellt=str(meldung["abgerufen_am"] or jetzt()),
    )


def _zeit(text: str) -> datetime | None:
    try:
        zeit = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit


def _im_fenster(a: Kernaussage, b: Kernaussage) -> bool:
    za, zb = _zeit(a.erstellt), _zeit(b.erstellt)
    if za is None or zb is None:
        return True
    return abs(za - zb) <= timedelta(days=FENSTER_TAGE)


def widerspruchsgrund(a: Kernaussage, b: Kernaussage) -> tuple[str, float] | None:
    """Nur unterschiedliche Hosts und klar entgegengesetzte Muster zählen."""
    if a.host == b.host or not _im_fenster(a, b):
        return None
    paare = {a.richtung, b.richtung}
    if paare == {"steigt", "sinkt"}:
        return "Richtung steigt gegen sinkt", 0.8
    if "unveraendert" in paare and paare & {"steigt", "sinkt"}:
        return "unverändert gegen Veränderung", 0.7
    if a.richtung == b.richtung and a.negiert != b.negiert:
        return "Verneinung gegen Behauptung", 0.6
    return None


def quellen_reputation(
    db: Facts,
    quellen: Iterable[Quelle],
    widersprueche_je_host: dict[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Reputation je Registerquelle aus echten Ergebnissen und Registerprior.

    ``intel_quellen`` wird vom bestehenden Auftrags-Abschluss gepflegt. Die
    Reputation ist ein geglätteter Anteil, kein Wahrheitsanspruch.
    """
    # Die absolute Artikelbasis kommt direkt aus artikel/intel_inhalte. Die
    # alte intel_quellen-Tabelle wird nur für echte Auftrags-Ergebnisse
    # (bestätigt/widerlegt) verwendet; ihr Artikelzähler kann veralten.
    artikel_stats = {str(z["quelle"]): z for z in db.intel_quelle_aus_artikeln()}
    ergebnis_stats = {str(z["quelle"]): z for z in db.intel_quellen()}
    wid = widersprueche_je_host or {}
    ergebnis: dict[str, dict[str, Any]] = {}
    for q in quellen:
        a = artikel_stats.get(q.name)
        e = ergebnis_stats.get(q.name)
        artikel = int(a["artikel"] or 0) if a else 0
        analysiert = int(a["analysiert"] or 0) if a else 0
        bestaetigt = int(e["bestaetigt"] or 0) if e else 0
        widerlegt = int(e["widerlegt"] or 0) if e else 0
        qualitaet_summe = float(a["qualitaet_summe"] or 0.0) if a else 0.0
        qualitaet = (qualitaet_summe / artikel) if artikel else 0.0
        prior = (0.5 * float(q.gewicht) + 0.5 * qualitaet) if qualitaet else float(q.gewicht)
        prior = round(max(0.0, min(1.0, prior)), 3)
        host = _host(q.url)
        eigene_widersprueche = int(wid.get(host, 0))
        nenner = PRIOR_GEWICHT + bestaetigt + widerlegt + 0.5 * eigene_widersprueche
        reputation = (prior * PRIOR_GEWICHT + bestaetigt) / nenner if nenner else prior
        ergebnis[q.id] = {
            "quelle_id": q.id,
            "name": q.name,
            "host": host,
            "gewicht": round(float(q.gewicht), 3),
            "artikel": artikel,
            "analysiert": analysiert,
            "bestaetigt": bestaetigt,
            "widerlegt": widerlegt,
            "widersprueche": eigene_widersprueche,
            "reputation": round(max(0.0, min(1.0, reputation)), 3),
            "vertrauen": "belegt" if bestaetigt + widerlegt > 0 else "vorläufig",
            "aktualisiert": jetzt(),
        }
    return ergebnis


def _leere_bewertung(db: Facts, quellen: Iterable[Quelle], meldungen: int) -> dict[str, Any]:
    """Keine Aussagen: Tabellen leeren, aber Quellenprior sichtbar halten."""
    rep = quellen_reputation(db, quellen)
    for zeile in rep.values():
        zeile["aktualisiert"] = jetzt()
    db.nexus_bewertung_ersetzen(list(rep.values()), [], [], [])
    return {
        "meldungen": meldungen, "meldungen_mit_claim": 0, "kernaussagen": 0,
        "belege": 0, "widersprueche": 0, "quellen": len(rep),
        "ohne_kernaussage": meldungen, "uebersprungen": 0, "nach_status": {},
    }


def claims_auffrischen(db: Facts, quellen: Iterable[Quelle] | None = None) -> dict[str, Any]:
    """Baut Claims, Widersprüche und Reputation deterministisch neu auf.

    Der Rebuild ist absichtlich idempotent: gleiche Meldungen ergeben gleiche
    Gruppen und Zähler. Er ist kein Lernmodell und ändert keine Handelsregel.
    """
    quellen = list(quellen) if quellen is not None else lade_register()
    quelle_map = {q.id: q for q in quellen}
    meldungen = db.nexus_meldungen_alle()
    aussagen = [a for m in meldungen if (a := extrahiere_aussage(m, quelle_map)) is not None]
    if not aussagen:
        return _leere_bewertung(db, quellen, len(meldungen))

    gruppen: dict[str, list[Kernaussage]] = defaultdict(list)
    for a in aussagen:
        gruppen[a.claim_key].append(a)

    gruppen_daten: list[tuple[str, list[Kernaussage], list[tuple[Kernaussage, Kernaussage, str, float]]]] = []
    widersprueche_je_host: dict[str, int] = defaultdict(int)
    uebersprungen = 0
    for key, eintraege in list(gruppen.items())[:MAX_GRUPPEN]:
        eintraege = sorted(eintraege, key=lambda a: (a.erstellt, a.meldung_key))
        if len(eintraege) > MAX_BELEGE_PRO_CLAIM:
            uebersprungen += len(eintraege) - MAX_BELEGE_PRO_CLAIM
            eintraege = eintraege[:MAX_BELEGE_PRO_CLAIM]
        paare: list[tuple[Kernaussage, Kernaussage, str, float]] = []
        for a, b in combinations(eintraege, 2):
            grund = widerspruchsgrund(a, b)
            if grund is None:
                continue
            paare.append((a, b, grund[0], grund[1]))
            widersprueche_je_host[a.host] += 1
            widersprueche_je_host[b.host] += 1
        gruppen_daten.append((key, eintraege, paare))

    reps = quellen_reputation(db, quellen, widersprueche_je_host)
    # Quellen, die nicht im Register stehen (z. B. alte Test-/Sonderfeeds),
    # bleiben sichtbar, aber ohne erfundene Historie.
    for a in aussagen:
        if a.quelle_id in reps:
            continue
        reps[a.quelle_id] = {
            "quelle_id": a.quelle_id, "name": a.quelle_id, "host": a.host,
            "gewicht": 0.5, "artikel": 0, "analysiert": 0, "bestaetigt": 0,
            "widerlegt": 0, "widersprueche": int(widersprueche_je_host.get(a.host, 0)),
            "reputation": 0.5, "vertrauen": "vorläufig", "aktualisiert": jetzt(),
        }

    claims: list[dict[str, Any]] = []
    claim_quellen: list[dict[str, Any]] = []
    widersprueche: list[dict[str, Any]] = []
    claim_id = 0
    claim_quelle_id = 0
    widerspruch_id = 0
    for key, eintraege, paare in gruppen_daten:
        claim_id += 1
        original_je_host: dict[str, Kernaussage] = {}
        for a in eintraege:
            if not a.ist_kopie:
                original_je_host.setdefault(a.host, a)
        if not original_je_host:
            for a in eintraege:
                original_je_host.setdefault(a.host, a)
        quellen_anzahl = len(original_je_host)
        rep_werte = [
            float(reps.get(a.quelle_id, {}).get("reputation", 0.5))
            for a in original_je_host.values()
        ]
        avg_rep = sum(rep_werte) / len(rep_werte) if rep_werte else 0.5
        quellen_faktor = min(1.0, quellen_anzahl / 3.0)
        belege_faktor = min(1.0, len(eintraege) / 3.0)
        grad = 0.5 * quellen_faktor + 0.3 * avg_rep + 0.2 * belege_faktor
        if paare:
            grad *= 0.5
        grad = round(max(0.0, min(1.0, grad)), 3)
        if paare:
            status = "widersprüchlich"
        elif quellen_anzahl >= 2 and grad >= SCHWELLE_BESTAETIGT:
            status = "bestätigt"
        elif grad >= SCHWELLE_TEILWEISE:
            status = "teilweise"
        else:
            status = "unbestätigt"

        repräsentant = next((a for a in eintraege if not a.ist_kopie), eintraege[0])
        erstmals = min(a.erstellt for a in eintraege)
        claims.append({
            "id": claim_id, "claim_key": key,
            "kernaussage": repräsentant.aussage,
            "thema": repräsentant.thema, "subjekt": repräsentant.subjekt,
            "metrik": repräsentant.metrik, "quellen": quellen_anzahl,
            "belege": len(eintraege), "widersprueche": len(paare),
            "bestaetigungsgrad": grad, "status": status,
            "erstmals": erstmals, "aktualisiert": jetzt(),
        })
        for a in eintraege:
            claim_quelle_id += 1
            claim_quellen.append({
                "id": claim_quelle_id, "claim_id": claim_id,
                "meldung_key": a.meldung_key, "artikel_id": a.artikel_id,
                "quelle_id": a.quelle_id, "host": a.host, "aussage": a.aussage,
                "richtung": a.richtung, "wert": a.wert, "einheit": a.einheit,
                "negiert": int(a.negiert), "ist_kopie": int(a.ist_kopie),
                "reputation": float(reps.get(a.quelle_id, {}).get("reputation", 0.5)),
                "erstellt": a.erstellt,
            })
        for a, b, grund, sicherheit in paare:
            widerspruch_id += 1
            widersprueche.append({
                "id": widerspruch_id, "claim_id": claim_id,
                "meldung_a": a.meldung_key, "meldung_b": b.meldung_key,
                "quelle_a": a.host, "quelle_b": b.host, "grund": grund,
                "sicherheit": sicherheit, "erstellt": jetzt(),
            })

    db.nexus_bewertung_ersetzen(list(reps.values()), claims, claim_quellen, widersprueche)
    nach_status: dict[str, int] = defaultdict(int)
    for c in claims:
        nach_status[c["status"]] += 1
    return {
        "meldungen": len(meldungen),
        "meldungen_mit_claim": len(aussagen),
        "kernaussagen": len(claims),
        "belege": len(claim_quellen),
        "widersprueche": len(widersprueche),
        "quellen": len(reps),
        "ohne_kernaussage": len(meldungen) - len(aussagen),
        "uebersprungen": uebersprungen,
        "nach_status": dict(nach_status),
    }
