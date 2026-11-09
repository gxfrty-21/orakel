"""Spider Intelligence: Analyse, Weiterleitung, Forschungsaufträge, Lernschleife.

Grundsätze, an die sich dieses Modul hält:

- Alles arbeitet auf echten Daten: Artikel aus der Fakten-Datenbank,
  Validierungen des Richters und Kerzen. Es gibt keine simulierten Erkenntnisse.
- Jede Aussage behält Quelle und Zeitpunkt. Ohne Quelle keine Weiterleitung.
- Ohne prüfbare Untersuchung bleibt ein Auftrag offen und behauptet keinen Erfolg.
- Die Spinne ändert keine Handelsregel. Sie liefert Fragen, Belege und Kontext.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from .config import Config
from .db import Facts, jetzt
from .knowledge import Vault

SCHWELLE_RELEVANZ = 0.45
KONFIRM_FENSTER_TAGE = 3
MAX_WEITERLEITUNGEN = 6
MAX_AUFTRAEGE = 3
MARKT_KERZEN = 96          # 96 × M15 = 24 Stunden
MARKT_ATR_FAKTOR = 1.0
VERFALL_TAGE = 30

# Themen und ihre Zuordnung. Reine Stichwort-Heuristik, offen dokumentiert.
THEMEN: dict[str, tuple[str, ...]] = {
    "strategie": ("strategie", "signal", "indikator", "backtest", "parameter",
                   "algorithmus", "modell", "ema", "rsi", "momentum", "handelssystem"),
    "risiko": ("risiko", "drawdown", "volatilität", "volatility", "absicherung",
               "hedge", "klumpen", "exposure", "risikomanagement"),
    "wissenschaft": ("studie", "paper", "forschung", "research", "journal",
                     "universität", "arxiv", "empirisch", "working paper"),
    "unternehmen": ("gewinn", "umsatz", "quartal", "earnings", "unternehmen",
                    "aktie", "börsengang", "übernahme", "bilanz"),
    "makro": ("notenbank", "zins", "inflation", "ezb", "ecb", "fed", "bip",
              "arbeitsmarkt", "konjunktur", "staatsanleihe", "geldpolitik"),
    "markt": ("markt", "kurs", "index", "s&p", "dax", "nasdaq", "rohstoff",
              "gold", "öl", "bitcoin", "wall street"),
}

ABTEILUNG_NAME = {code: name for code, name in {
    "strategie": ("C", "Labor"),
    "risiko": ("F", "Risikomanagement"),
    "wissenschaft": ("E", "Forschungsabteilung"),
    "unternehmen": ("D", "Trading Floor"),
    "makro": ("D", "Trading Floor"),
    "markt": ("D", "Trading Floor"),
    "allgemein": ("G", "Wissenszentrum"),
}.values()}

ABTEILUNG: dict[str, tuple[str, str]] = {
    "strategie": ("C", "Labor"),
    "risiko": ("F", "Risikomanagement"),
    "wissenschaft": ("E", "Forschungsabteilung"),
    "unternehmen": ("D", "Trading Floor"),
    "makro": ("D", "Trading Floor"),
    "markt": ("D", "Trading Floor"),
    "allgemein": ("G", "Wissenszentrum"),
}

WEITERLEITUNG_STATUS = ("neu", "übernommen", "erledigt")
ABTEILUNGEN = tuple(dict.fromkeys(name for _, name in ABTEILUNG.values()))
AUFTRAG_STATUS = ("offen", "bestätigt", "widerlegt", "verworfen")


def weiterleitung_aendern(db: Facts, kennung: str, abteilung: str, status: str) -> bool:
    """Setzt Abteilung und Status einer echten Weiterleitung. False = Kennung unbekannt."""
    if abteilung not in ABTEILUNGEN:
        raise ValueError(f"Unbekannte Abteilung: {abteilung}")
    if status not in WEITERLEITUNG_STATUS:
        raise ValueError(f"Unbekannter Status: {status}")
    return db.intel_weiterleitung_aendern(kennung, abteilung, status) > 0


def auftrag_aendern(db: Facts, kennung: str, status: str, ergebnis: str = "") -> bool:
    """Setzt Status und Ergebnis eines Forschungsauftrags. False = Kennung unbekannt."""
    if status not in AUFTRAG_STATUS:
        raise ValueError(f"Unbekannter Status: {status}")
    ergebnis = ergebnis.strip()
    if status != "offen" and not ergebnis:
        raise ValueError("Ein abgeschlossener Auftrag braucht ein Ergebnis.")
    if len(ergebnis) > 2000:
        raise ValueError("Ergebnis ist zu lang (max. 2000 Zeichen).")
    return db.intel_status_setzen(kennung, status, ergebnis) > 0


def _jetzt() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _nach(zeit_a: str, zeit_b: str) -> bool:
    """Zeitvergleich über echte Zeitstempel, nicht über Zeichenketten."""
    try:
        a = datetime.fromisoformat(str(zeit_a))
        b = datetime.fromisoformat(str(zeit_b))
        if a.tzinfo is None:
            a = a.replace(tzinfo=timezone.utc)
        if b.tzinfo is None:
            b = b.replace(tzinfo=timezone.utc)
        return a > b
    except Exception:
        return str(zeit_a) > str(zeit_b)


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return host or "unbekannt"


def _thema(text: str) -> str:
    klein = text.lower()
    for thema, woerter in THEMEN.items():
        if any(w in klein for w in woerter):
            return thema
    return "allgemein"


def _aktualitaet(veroeffentlicht: str | None) -> float:
    """1.0 = frisch, 0.0 = älter als 14 Tage. Unbekanntes Datum = 0.5."""
    if not veroeffentlicht:
        return 0.5
    try:
        zeit = parsedate_to_datetime(veroeffentlicht)
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        tage = (_jetzt() - zeit).total_seconds() / 86400
    except Exception:
        return 0.5
    if tage < 0:
        return 1.0
    return max(0.0, 1.0 - tage / 14.0)


def relevanz(artikel: Any, inhalt: str = "") -> float:
    """Nachvollziehbare Relevanz: Qualität, Symbolbezug, Tiefe, Aktualität."""
    q = float(artikel["qualitaet"] or 0.0)
    try:
        symbole = json.loads(artikel["symbole"] or "[]")
    except Exception:
        symbole = []
    tiefe = min(1.0, len(inhalt) / 1500.0) if inhalt else 0.0
    return round(min(1.0, 0.45 * q + 0.25 * min(1.0, len(symbole) / 2.0)
                     + 0.15 * tiefe + 0.15 * _aktualitaet(artikel["veroeffentlicht"])), 2)


def _artikel_text(artikel: Any, inhalt: str = "") -> str:
    return " ".join(str(artikel[k] or "") for k in ("titel", "zusammenfassung")) + " " + inhalt


def _atr(kerzen: list[Any], fenster: int = 14) -> float:
    if len(kerzen) < fenster:
        return 0.0
    spanne = [float(k["high"]) - float(k["low"]) for k in kerzen[-fenster:]]
    return sum(spanne) / len(spanne)


class IntelNetz:
    """Zentrale Koordination: verteilt Informationen und führt Aufträge nach."""

    def __init__(self, cfg: Config, db: Facts, vault: Vault) -> None:
        self.cfg = cfg
        self.db = db
        self.vault = vault
        self.s = cfg.abschnitt("spider") or {}
        self.max_auftraege = int(self.s.get("max_auftraege_pro_lauf", MAX_AUFTRAEGE))
        self.max_weiter = int(self.s.get("max_weiterleitungen_pro_lauf", MAX_WEITERLEITUNGEN))

    # ---------- Kennungen ----------
    def _kennung(self, prefix: str) -> str:
        tag = _jetzt().strftime("%Y%m%d")
        if prefix == "WL":
            return f"WL-{tag}-{self.db.intel_weiterleitung_zaehler(tag) + 1:04d}"
        return f"{prefix}-{tag}-{self.db.intel_zaehler(prefix, tag) + 1:04d}"

    # ---------- Weiterleitung ----------
    def weiterleiten(self, an: str, betreff: str, bezug: dict[str, Any],
                     von: str = "B:Spider Intelligence") -> str:
        kennung = self._kennung("WL")
        self.db.intel_weiterleitung_speichern(kennung, von, an, betreff, bezug)
        return kennung

    # ---------- Forschungsauftrag ----------
    def auftrag(self, **felder: Any) -> str | None:
        """Legt einen Auftrag an. None = gleicher offener Auftrag existiert schon."""
        art = felder.get("art", "allgemein")
        symbol = felder.get("bezug_symbol")
        schluessel = felder.get("bezug_schluessel")
        if self.db.intel_auftrag_existiert(art, symbol, schluessel, tage=7):
            return None
        kennung = self._kennung("RS")
        daten = {"kennung": kennung, "zeit": jetzt(), **felder}
        self.db.intel_auftrag_speichern(daten)
        self._vault_notiz(daten)
        # Die Weiterleitungen dieser Abteilung sind damit nachweislich übernommen.
        name = ABTEILUNG_NAME.get(str(felder.get("abteilung")), str(felder.get("abteilung")))
        self.db.intel_weiterleitung_status_setzen(name, "neu", "übernommen")
        return kennung

    def _vault_notiz(self, auftrag: dict[str, Any]) -> None:
        quellen = auftrag.get("quellen") or []
        inhalt = "\n".join([
            f"**Kennung:** {auftrag['kennung']}",
            f"**Abteilung:** {auftrag['abteilung']}",
            "",
            "## Ausgangsproblem",
            auftrag.get("problem") or "—",
            "",
            "## Gefundene Informationen",
            auftrag.get("information") or "—",
            "",
            "## Quellen",
            *([f"- {q}" for q in quellen] if quellen else ["- keine"]),
            "",
            "## Forschungsfrage",
            auftrag.get("frage") or "—",
            "",
            "## Hypothese",
            auftrag.get("hypothese") or "—",
            "",
            "## Vorgeschlagene Untersuchung",
            auftrag.get("untersuchung") or "—",
            "",
            "## Erwarteter Nutzen",
            auftrag.get("nutzen") or "—",
            "",
            "## Mögliche Risiken",
            auftrag.get("risiko") or "—",
        ])
        self.vault.notiz(
            "wissen" if auftrag.get("art") == "markt" else "strategien",
            f"{auftrag['kennung']} {auftrag['titel']}",
            inhalt,
            tags=["spider", "forschungsauftrag", auftrag.get("art", "allgemein"),
                  (auftrag.get("bezug_symbol") or "").lower()],
            verlinkt=[auftrag.get("bezug_symbol") or ""],
        )

    # ---------- Verarbeitung neuer Artikel ----------
    def verarbeite(self, neue_ids: list[int], markt: dict[str, Any] | None = None) -> dict[str, Any]:
        ids = list(dict.fromkeys(int(i) for i in neue_ids))
        artikel = self.db.artikel_by_ids(ids)
        gruppen: dict[tuple[str, str, str, str], list[Any]] = defaultdict(list)
        nach_symbol: dict[str, list[Any]] = defaultdict(list)

        for a in artikel:
            inhalt = self.db.artikel_inhalt(a["id"])
            text = _artikel_text(a, inhalt)
            thema = _thema(text)
            abt, name = ABTEILUNG[thema]
            try:
                symbole = json.loads(a["symbole"] or "[]")
            except Exception:
                symbole = []
            for sym in (symbole or [""]):
                gruppen[(abt, name, sym, thema)].append(a)
                if sym:
                    nach_symbol[sym].append(a)

        self.quellen_auffrischen()

        weiter = 0
        for (abt, name, sym, thema), eintraege in sorted(
                gruppen.items(), key=lambda kv: -len(kv[1]))[: self.max_weiter]:
            betreff = (f"{len(eintraege)} Meldung(en) zu {sym}" if sym
                       else f"{len(eintraege)} Meldung(en), Thema {thema}")
            self.weiterleiten(name, betreff, {
                "abteilung": abt, "thema": thema, "symbol": sym,
                "artikel": [int(a["id"]) for a in eintraege],
                "quellen": sorted({_domain(a["url"]) for a in eintraege}),
            })
            weiter += 1

        auftraege: list[str] = []
        for sym, eintraege in sorted(nach_symbol.items(), key=lambda kv: -len(kv[1])):
            if len(auftraege) >= self.max_auftraege:
                break
            doms = {_domain(a["url"]) for a in eintraege}
            if len(eintraege) < 3 or len(doms) < 2:
                continue
            serioes = [a for a in eintraege if float(a["qualitaet"]) >= 0.5]
            if not serioes:
                continue
            kerzen = self.db.kerzen(sym, "M15")
            kurs = float(kerzen[-1]["close"]) if kerzen else None
            atr = _atr(kerzen)
            kennung = self.auftrag(
                abteilung="D", titel=f"Meldungslage zu {sym} prüfen",
                problem=f"{len(eintraege)} Meldungen aus {len(doms)} Quellen zu {sym} "
                        f"innerhalb von {KONFIRM_FENSTER_TAGE} Tagen.",
                information="; ".join(a["titel"] for a in serioes[:4]),
                quellen=[a["url"] for a in serioes[:6]],
                frage=f"Ist die Häufung von Meldungen zu {sym} nachrichtengetrieben, "
                      f"und geht sie mit einer Bewegung von mindestens einem ATR einher?",
                hypothese=f"Die Meldungslage geht mit einer Bewegung von mindestens "
                          f"{MARKT_ATR_FAKTOR:g} ATR in {sym} einher.",
                untersuchung=f"Kursbewegung ab Auftragszeitpunkt über {MARKT_KERZEN} "
                             f"M15-Kerzen gegen den ATR bei Erstellung prüfen.",
                nutzen="Frühwarnung für Regimewechsel und Kontext für den Trading Floor.",
                risiko="Schlagzeilen können kurzfristig irreführen; keine Regeländerung "
                       "ohne Test.",
                art="markt", bezug_symbol=sym,
                kurs_bei_erstellung=kurs, atr_bei_erstellung=atr or None,
            )
            if kennung:
                auftraege.append(kennung)

        return {"weiterleitungen": weiter, "auftraege": auftraege,
                "artikel": len(artikel)}

    # ---------- Eigene Hypothesen aus der Datenlage ----------
    def hypothesen_aus_lage(self, markt: dict[str, Any] | None = None) -> list[str]:
        neu: list[str] = []
        if len(neu) >= self.max_auftraege:
            return neu

        # 1) Häufigster Ablehnungsgrund der letzten Prüfungen → Labor
        abgelehnt: list[tuple[Any, str]] = []
        for r in self.db.letzte_validierungen():
            if r["urteil"] != "abgelehnt":
                continue
            try:
                bericht = json.loads(r["bericht"])
            except Exception:
                bericht = {}
            gruende = [str(g) for g in (bericht.get("gruende") or [])]
            if gruende:
                abgelehnt.append((r, gruende[0].split("—")[0].strip()[:70]))
        if abgelehnt:
            r, grund = max(abgelehnt, key=lambda x: x[0]["id"])
            kennung = self.auftrag(
                abteilung="C", titel=f"Ablehnungsgrund «{grund}» prüfen",
                problem=f"{r['symbol']} {r['schluessel']} wurde abgelehnt: {grund}",
                information=f"Letzte Prüfung {r['erstellt']} mit Urteil «{r['urteil']}».",
                quellen=[f"validierung:{r['id']}"],
                frage=f"Ist «{grund}» systematisch oder ein Ausreisser dieses Kandidaten?",
                hypothese=f"Der Grund «{grund}» tritt auch bei der nächsten Prüfung dieses "
                          f"Kandidaten auf.",
                untersuchung="Nächste Validierung desselben Kandidaten abwarten und "
                             "Urteil sowie Ablehnungsgrund vergleichen.",
                nutzen="Verhindert, dass derselbe Fehler mehrfach Parameter kostet.",
                risiko="Ein einzelner Grund kann zufällig sein; Aussage gilt nur für "
                       "diesen Kandidaten.",
                art="strategie", bezug_symbol=r["symbol"], bezug_schluessel=r["schluessel"],
            )
            if kennung:
                neu.append(kennung)

        # 2) Korrelationspaare über der Risikoschwelle → Risikomanagement
        schwelle = float(self.cfg["risiko"].get("max_korrelation", 0.85))
        for paar in (markt or {}).get("korrelation") or []:
            if len(neu) >= self.max_auftraege:
                break
            if abs(float(paar.get("wert", 0))) <= schwelle:
                continue
            kennung = self.auftrag(
                abteilung="F", titel=f"Klumpenrisiko {paar['a']}/{paar['b']}",
                problem=f"Korrelation {paar['wert']} über der Schwelle {schwelle}.",
                information="Berechnet aus den importierten Kerzen (letzte 500 Renditen).",
                quellen=["markt:korrelation"],
                frage="Bleibt das Paar über der Schwelle, und verhindert die Sperre "
                      "tatsächlich einen zweiten Kauf?",
                hypothese=f"Die Korrelationssperre blockiert einen Kauf in {paar['b']}, "
                          f"solange {paar['a']} offen ist.",
                untersuchung="Entscheide der nächsten Paper-Takte auf Korrelationsgrund "
                             "prüfen.",
                nutzen="Belegt, ob die Risikosperre im Betrieb greift.",
                risiko="Korrelationen sind zeitlich instabil.",
                art="risiko", bezug_symbol=paar["b"],
            )
            if kennung:
                neu.append(kennung)
            break

        return neu

    # ---------- Geschlossener Lernkreislauf ----------
    def lernschleife(self, markt: dict[str, Any] | None = None) -> dict[str, Any]:
        ergebnis = {"bestaetigt": 0, "widerlegt": 0, "verworfen": 0, "offen": 0}
        for o in self.db.intel_auftraege(300):
            if o["status"] != "offen":
                continue
            alter = self._alter_tage(o["zeit"])
            if o["art"] == "strategie" and o["bezug_symbol"] and o["bezug_schluessel"]:
                v = self.db.validierung_nach(o["bezug_symbol"], o["bezug_schluessel"], o["zeit"])
                if v is not None:
                    if v["urteil"] == "abgelehnt":
                        self._abschluss(o, "bestätigt",
                                        f"Erneut abgelehnt am {v['erstellt']}: Die Hypothese "
                                        f"zum systematischen Grund hält.")
                        ergebnis["bestaetigt"] += 1
                    else:
                        self._abschluss(o, "widerlegt",
                                        f"Kandidat bestand am {v['erstellt']} — der "
                                        f"Ablehnungsgrund war nicht systematisch.")
                        ergebnis["widerlegt"] += 1
                    continue
            elif o["art"] == "markt" and o["bezug_symbol"] and o["kurs_bei_erstellung"]:
                kerzen = [k for k in self.db.kerzen(o["bezug_symbol"], "M15")
                          if _nach(k["ts"], o["zeit"])]
                if len(kerzen) >= MARKT_KERZEN:
                    atr = float(o["atr_bei_erstellung"] or 0.0)
                    if atr > 0:
                        bewegt = abs(float(kerzen[-1]["close"]) - float(o["kurs_bei_erstellung"]))
                        if bewegt >= atr * MARKT_ATR_FAKTOR:
                            self._abschluss(o, "bestätigt",
                                            f"Bewegung {bewegt:.5f} ≥ {MARKT_ATR_FAKTOR:g} ATR "
                                            f"({atr:.5f}) innerhalb von {MARKT_KERZEN} Kerzen.")
                            ergebnis["bestaetigt"] += 1
                        else:
                            self._abschluss(o, "widerlegt",
                                            f"Bewegung {bewegt:.5f} blieb unter "
                                            f"{MARKT_ATR_FAKTOR:g} ATR ({atr:.5f}).")
                            ergebnis["widerlegt"] += 1
                        continue
            if alter > VERFALL_TAGE:
                self._abschluss(o, "verworfen",
                                f"Nach {VERFALL_TAGE} Tagen keine prüfbare Untersuchung.")
                ergebnis["verworfen"] += 1
            else:
                ergebnis["offen"] += 1
        return ergebnis

    def quellen_auffrischen(self) -> None:
        """Quellenkennzahlen aus allen Artikeln neu berechnen (idempotent)."""
        for z in self.db.intel_quelle_aus_artikeln():
            self.db.intel_quelle_abgleichen(z["quelle"], z["artikel"],
                                            z["analysiert"], z["qualitaet_summe"])

    def _alter_tage(self, zeit: str) -> float:
        try:
            then = datetime.fromisoformat(zeit)
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
            return (_jetzt() - then).total_seconds() / 86400
        except Exception:
            return 0.0

    def _abschluss(self, auftrag: Any, status: str, ergebnis: str) -> None:
        self.db.intel_status_setzen(auftrag["kennung"], status, ergebnis)
        try:
            quellen = json.loads(auftrag["quellen"] or "[]")
        except Exception:
            quellen = []
        for eintrag in quellen:
            if str(eintrag).startswith("http"):
                quelle = self.db.artikel_quelle(str(eintrag)) or _domain(str(eintrag))
                self.db.intel_quelle_pflegen(
                    quelle,
                    bestaetigt=1 if status == "bestätigt" else 0,
                    widerlegt=1 if status == "widerlegt" else 0,
                )
        name = ABTEILUNG_NAME.get(str(auftrag["abteilung"]), str(auftrag["abteilung"]))
        self.db.intel_weiterleitung_status_setzen(name, "übernommen", "erledigt")
        self.vault.notiz(
            "wissen", f"{auftrag['kennung']} Ergebnis",
            f"**Status:** {status}\n\n**Ergebnis:** {ergebnis}\n\n"
            f"**Auftrag:** {auftrag['titel']}",
            tags=["spider", "ergebnis", status],
        )


def lage(db: Facts) -> dict[str, Any]:
    """Kurzbericht für das Dashboard, ausschliesslich aus der Datenbank."""
    return {
        "statistik": db.intel_statistik(),
        "auftraege": [dict(r) for r in db.intel_auftraege(40)],
        "weiterleitungen": [dict(r) for r in db.intel_weiterleitungen(40)],
        "quellen": db.intel_quellen(),
        "abteilungen": list(ABTEILUNGEN),
        "weiterleitung_status": list(WEITERLEITUNG_STATUS),
        "auftrag_status": list(AUFTRAG_STATUS),
    }
