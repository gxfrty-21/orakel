"""Persistente Missionen für den Nexus.

Eine Mission ist eine kleine, nachvollziehbare Arbeitskette:

``lage`` → ``pruefung`` → ``bericht``

Die Schritte laufen auf gespeicherten Kernaussagen aus Phase 3. Es gibt keinen
LLM-Aufruf, keinen erfundenen Agenten und keinen künstlichen Fortschritt. Jede
Aufgabe wird mit einer Lease aus der SQLite-Queue geholt; Fehler werden mit
Backoff erneut versucht und nach dem letzten Versuch als Dead-Letter markiert.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..db import Facts

PRIORITAETEN = ("niedrig", "mittel", "hoch", "kritisch")
ROLLEN = ("lage", "pruefung", "bericht")
STATUS_RANG = {"bestätigt": 0, "teilweise": 1, "widersprüchlich": 2,
               "unbestätigt": 3}
STOPPWOERTER = {
    "aber", "alle", "auch", "auf", "aus", "bei", "bitte", "das", "dem", "den",
    "der", "des", "die", "dies", "eine", "einer", "eines", "für", "hat", "haben",
    "hier", "ist", "mit", "nach", "oder", "sich", "sind", "über", "und", "von",
    "was", "welche", "welcher", "wie", "wird", "werden", "zur", "zum",
    "the", "and", "are", "for", "from", "has", "have", "how", "into", "its",
    "market", "mission", "of", "on", "that", "the", "this", "to", "what",
    "which", "will", "with",
}


def _sauber(text: object, grenze: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:grenze]


def _begriffe(titel: str, auftrag: str) -> list[str]:
    """Einfache Suchbegriffe. Keine Semantik, nur Wörter."""
    text = f"{titel} {auftrag}".casefold()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    roh = re.findall(r"[a-z0-9]{3,}", text)
    begriffe: list[str] = []
    for wort in roh:
        if wort in STOPPWOERTER or any(zeichen.isdigit() for zeichen in wort):
            continue
        if wort not in begriffe:
            begriffe.append(wort)
        if len(begriffe) >= 12:
            break
    return begriffe


def _grad(wert: object) -> str:
    try:
        return f"{float(wert):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "–"


def _menge(anzahl: int, einzahl: str, mehrzahl: str) -> str:
    return f"{anzahl} {einzahl if anzahl == 1 else mehrzahl}"


class Missionen:
    """Queue und Ausführung. Der Zustand liegt vollständig in SQLite."""

    def __init__(
        self,
        db: Facts,
        *,
        max_versuche: int = 3,
        lease_sekunden: int = 300,
        backoff_sekunden: int = 30,
        jetzt_funktion: Callable[[], datetime] | None = None,
    ) -> None:
        self.db = db
        self.max_versuche = max(1, int(max_versuche))
        self.lease_sekunden = max(1, int(lease_sekunden))
        self.backoff_sekunden = max(1, int(backoff_sekunden))
        self._jetzt_funktion = jetzt_funktion or (lambda: datetime.now(timezone.utc))

    def _jetzt(self) -> datetime:
        zeit = self._jetzt_funktion()
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return zeit.astimezone(timezone.utc).replace(microsecond=0)

    @staticmethod
    def _iso(zeit: datetime) -> str:
        return zeit.isoformat(timespec="seconds")

    def _kennung(self, jetzt: datetime) -> str:
        tag = jetzt.strftime("%Y%m%d")
        basis = self.db.nexus_mission_zaehler(tag) + 1
        for nummer in range(basis, basis + 1000):
            kennung = f"MS-{tag}-{nummer:04d}"
            if not self.db.nexus_mission_kennung_existiert(kennung):
                return kennung
        raise RuntimeError("Keine freie Missionskennung gefunden")

    def anlegen(self, titel: str, auftrag: str, prioritaet: str = "mittel") -> dict[str, Any]:
        titel = _sauber(titel, 200)
        auftrag = _sauber(auftrag, 4000)
        prioritaet = str(prioritaet or "mittel").strip().lower()
        if len(titel) < 3:
            raise ValueError("Der Missionstitel braucht mindestens 3 Zeichen.")
        if len(auftrag) < 10:
            raise ValueError("Der Auftrag braucht mindestens 10 Zeichen.")
        if prioritaet not in PRIORITAETEN:
            raise ValueError(f"Unbekannte Priorität: {prioritaet}")
        jetzt = self._jetzt()
        aufgaben = [
            {"rolle": "lage", "ziel": f"Kernaussagen zu «{titel}» suchen",
             "max_versuche": self.max_versuche},
            {"rolle": "pruefung", "ziel": "Belege, unabhängige Quellen und Widersprüche prüfen",
             "max_versuche": self.max_versuche},
            {"rolle": "bericht", "ziel": "Belastbarkeit und offene Fragen berichten",
             "max_versuche": self.max_versuche},
        ]
        return self.db.nexus_mission_anlegen(
            self._kennung(jetzt), titel, auftrag, prioritaet, aufgaben,
            self._iso(jetzt),
        )

    def weiterarbeiten(self, max_tasks: int = 10,
                       kennung: str | None = None) -> dict[str, Any]:
        """Führt fällige Aufgaben aus. Mehrfach aufrufbar, auch nach Neustart."""
        max_tasks = max(1, min(int(max_tasks), 50))
        jetzt = self._jetzt()
        freigegeben = self.db.nexus_task_leases_loesen(self._iso(jetzt))
        zaehler = {"ausgefuehrt": 0, "erledigt": 0, "fehler": 0,
                   "retries": 0, "dead_letter": 0, "leases": freigegeben}
        while zaehler["ausgefuehrt"] < max_tasks:
            task = self.db.nexus_task_naechste(
                self._iso(jetzt), self._iso(jetzt + timedelta(seconds=self.lease_sekunden)),
                kennung,
            )
            if not task:
                break
            mission = self.db.nexus_mission(str(task["mission_kennung"]))
            if mission is None:
                self.db.nexus_task_fehler(
                    int(task["id"]), "Mission nicht gefunden",
                    self._iso(jetzt), True, self._iso(jetzt),
                )
                zaehler["fehler"] += 1
                zaehler["dead_letter"] += 1
                zaehler["ausgefuehrt"] += 1
                continue
            zaehler["ausgefuehrt"] += 1
            try:
                ergebnis = self._aufgabe(task, mission, jetzt)
                bericht = ergebnis if task["rolle"] == "bericht" else None
                self.db.nexus_task_erledigt(
                    int(task["id"]), ergebnis, bericht, self._iso(jetzt))
                zaehler["erledigt"] += 1
            except Exception as exc:  # eine defekte Aufgabe stoppt die Queue nicht
                versuch = int(task["versuche"])
                endgueltig = versuch >= int(task["max_versuche"])
                if endgueltig:
                    naechste = jetzt
                    zaehler["dead_letter"] += 1
                else:
                    sekunden = min(3600, self.backoff_sekunden * (2 ** max(0, versuch - 1)))
                    naechste = jetzt + timedelta(seconds=sekunden)
                    zaehler["retries"] += 1
                fehler = f"{type(exc).__name__}: {str(exc)[:240]}"
                self.db.nexus_task_fehler(
                    int(task["id"]), fehler, self._iso(naechste), endgueltig,
                    self._iso(jetzt),
                )
                zaehler["fehler"] += 1
        return {
            **zaehler,
            "kennung": kennung,
            "statistik": self.db.nexus_mission_statistik(),
            "liste": self.db.nexus_missionen(20),
        }

    def _aufgabe(self, task: dict[str, Any], mission: dict[str, Any],
                 jetzt: datetime) -> dict[str, Any]:
        rolle = str(task["rolle"])
        if rolle == "lage":
            return self._lage(mission)
        if rolle == "pruefung":
            return self._pruefung(task)
        if rolle == "bericht":
            return self._bericht(task, jetzt)
        raise ValueError(f"Unbekannte Missionrolle: {rolle}")

    def _lage(self, mission: dict[str, Any]) -> dict[str, Any]:
        titel = str(mission.get("titel") or "")
        auftrag = str(mission.get("auftrag") or "")
        begriffe = _begriffe(titel, auftrag)
        alle = self.db.nexus_claims(1000)
        auswahl = "stichwort"
        if not begriffe:
            auswahl = "breit"
            passend = alle[:12]
            hinweis = ("Keine unterscheidbaren Suchbegriffe; gezeigt werden die "
                       "belastbarsten gespeicherten Kernaussagen.")
        else:
            bewertet = []
            for claim in alle:
                haystack = " ".join(str(claim.get(feld) or "") for feld in (
                    "claim_key", "kernaussage", "thema", "subjekt", "metrik",
                )).casefold()
                treffer = sum(1 for begriff in begriffe if begriff in haystack)
                if treffer:
                    bewertet.append((treffer, claim))
            bewertet.sort(key=lambda paar: (
                -paar[0], STATUS_RANG.get(str(paar[1].get("status")), 9),
                -float(paar[1].get("bestaetigungsgrad") or 0),
                -int(paar[1].get("quellen") or 0), -int(paar[1].get("id") or 0),
            ))
            passend = [claim for _, claim in bewertet[:12]]
            auswahl = "stichwort" if passend else "keine"
            hinweis = ("" if passend else
                       "Keine gespeicherte Kernaussage enthält die Suchbegriffe. "
                       "Das ist eine Datenlücke, keine Entwarnung.")
        return {
            "rolle": "lage",
            "titel": titel,
            "begriffe": begriffe,
            "auswahl": auswahl,
            "gefunden": len(passend),
            "claims": [self._claim_kurz(claim) for claim in passend],
            "hinweis": hinweis,
        }

    @staticmethod
    def _claim_kurz(claim: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(claim["id"]),
            "claim_key": str(claim["claim_key"]),
            "kernaussage": str(claim["kernaussage"]),
            "thema": str(claim["thema"]),
            "subjekt": str(claim["subjekt"]),
            "metrik": str(claim["metrik"]),
            "status": str(claim["status"]),
            "quellen": int(claim["quellen"]),
            "belege": int(claim["belege"]),
            "widersprueche": int(claim["widersprueche"]),
            "bestaetigungsgrad": float(claim["bestaetigungsgrad"]),
            "erstmals": str(claim["erstmals"]),
            "aktualisiert": str(claim["aktualisiert"]),
        }

    def _vorher(self, task: dict[str, Any]) -> dict[str, Any]:
        vorgaenger = task.get("abhaengig_von")
        if not vorgaenger:
            return {}
        vorher = self.db.nexus_task(int(vorgaenger))
        return (vorher or {}).get("ergebnis") or {}

    def _pruefung(self, task: dict[str, Any]) -> dict[str, Any]:
        lage = self._vorher(task)
        kurz = lage.get("claims") or []
        ids = [int(claim["id"]) for claim in kurz if claim.get("id") is not None]
        claims = {int(c["id"]): c for c in self.db.nexus_claims_by_ids(ids)}
        belege = self.db.nexus_claim_quellen_fuer(ids)
        widersprueche = self.db.nexus_widersprueche_fuer(ids)
        nach_claim: dict[int, list[dict[str, Any]]] = {i: [] for i in ids}
        for beleg in belege:
            nach_claim.setdefault(int(beleg["claim_id"]), []).append({
                "host": str(beleg["host"]),
                "quelle_id": str(beleg["quelle_id"]),
                "aussage": str(beleg["aussage"]),
                "richtung": str(beleg["richtung"]),
                "ist_kopie": bool(beleg["ist_kopie"]),
                "reputation": float(beleg["reputation"]),
            })
        geprueft = []
        for claim_id in ids:
            claim = claims.get(claim_id)
            if not claim:
                continue
            eigene = nach_claim.get(claim_id, [])
            hosts = sorted({b["host"] for b in eigene if not b["ist_kopie"]})
            wid = [w for w in widersprueche if int(w["claim_id"]) == claim_id]
            status = str(claim["status"])
            bedarf = (status == "widersprüchlich" or bool(wid)
                      or int(claim["quellen"]) < 2 or status == "unbestätigt")
            geprueft.append({
                **self._claim_kurz(claim),
                "hosts": hosts,
                "hosts_unabhaengig": len(hosts),
                "belege_detail": eigene[:20],
                "widersprueche": [
                    {"grund": str(w["grund"]), "sicherheit": float(w["sicherheit"]),
                     "quelle_a": str(w["quelle_a"]), "quelle_b": str(w["quelle_b"])}
                    for w in wid
                ],
                "pruefbedarf": bedarf,
            })
        kennzahlen = {
            "claims": len(geprueft),
            "bestaetigt": sum(1 for c in geprueft if c["status"] == "bestätigt"),
            "teilweise": sum(1 for c in geprueft if c["status"] == "teilweise"),
            "unbestaetigt": sum(1 for c in geprueft if c["status"] == "unbestätigt"),
            "widerspruechlich": sum(1 for c in geprueft if c["status"] == "widersprüchlich"),
            "belege": sum(len(c["belege_detail"]) for c in geprueft),
            "hosts": len({h for c in geprueft for h in c["hosts"]}),
            "widersprueche": len(widersprueche),
            "pruefbedarf": sum(1 for c in geprueft if c["pruefbedarf"]),
        }
        return {
            "rolle": "pruefung",
            "kennzahlen": kennzahlen,
            "claims": geprueft,
            "widersprueche": [
                {"claim_id": int(w["claim_id"]), "claim_key": str(w["claim_key"]),
                 "kernaussage": str(w["kernaussage"]), "grund": str(w["grund"]),
                 "sicherheit": float(w["sicherheit"]), "quelle_a": str(w["quelle_a"]),
                 "quelle_b": str(w["quelle_b"])}
                for w in widersprueche[:20]
            ],
            "hinweis": lage.get("hinweis") or "",
        }

    def _bericht(self, task: dict[str, Any], jetzt: datetime) -> dict[str, Any]:
        pruefung = self._vorher(task)
        claims = pruefung.get("claims") or []
        widersprueche = pruefung.get("widersprueche") or []
        kz = dict(pruefung.get("kennzahlen") or {})
        befunde: list[str] = []
        offene: list[str] = []
        for claim in claims:
            status = str(claim.get("status") or "unbestätigt")
            zeile = (f"[{status}, Grad {_grad(claim.get('bestaetigungsgrad'))}] "
                     f"{claim.get('kernaussage')} — "
                     f"{_menge(int(claim.get('quellen') or 0), 'unabhängige Quelle', 'unabhängige Quellen')}, "
                     f"{_menge(int(claim.get('belege') or 0), 'Beleg', 'Belege')}")
            wid = claim.get("widersprueche") or []
            if wid:
                zeile += f", {len(wid)} Widerspruch"
            befunde.append(zeile)
            if wid:
                for w in wid[:2]:
                    offene.append(
                        f"Widerspruch zu «{claim.get('kernaussage')}» prüfen: "
                        f"{w.get('grund')} ({w.get('quelle_a')} ↔ {w.get('quelle_b')})."
                    )
            elif int(claim.get("quellen") or 0) < 2:
                offene.append(
                    f"Für «{claim.get('kernaussage')}» fehlt eine zweite "
                    "unabhängige Originalquelle."
                )
            elif status == "unbestätigt":
                offene.append(
                    f"Die Kernaussage «{claim.get('kernaussage')}» ist noch nicht "
                    "bestätigt; weitere Originalquellen prüfen."
                )
        if not claims:
            befunde.append("Keine passende Kernaussage im aktuellen Bestand.")
            offene.append(
                "Die Mission braucht neue Quellen oder präzisere Suchbegriffe; "
                "die fehlende Datenlage ist keine Entwarnung."
            )
        if not offene:
            offene.append(
                "Keine offenen Fragen aus dem aktuellen Bestand. Das ist keine "
                "Aussage über die Zukunft."
            )
        offene = offene[:8]
        kennzahlen = {
            "claims": int(kz.get("claims") or len(claims)),
            "bestaetigt": int(kz.get("bestaetigt") or 0),
            "teilweise": int(kz.get("teilweise") or 0),
            "unbestaetigt": int(kz.get("unbestaetigt") or 0),
            "widerspruechlich": int(kz.get("widerspruechlich") or 0),
            "belege": int(kz.get("belege") or 0),
            "hosts": int(kz.get("hosts") or 0),
            "widersprueche": int(kz.get("widersprueche") or 0),
            "offene_fragen": len(offene),
        }
        titel = str(task.get("titel") or "")
        auftrag = str(task.get("auftrag") or "")
        grundlage = pruefung.get("hinweis") or ""
        text = "\n".join([
            f"Mission {task.get('mission_kennung', '')} — {titel}",
            f"Auftrag: {auftrag}",
            "",
            f"Datenlage: {_menge(kennzahlen['claims'], 'Kernaussage', 'Kernaussagen')}, "
            f"{_menge(kennzahlen['belege'], 'Beleg', 'Belege')}, "
            f"{_menge(kennzahlen['hosts'], 'unabhängiger Host', 'unabhängige Hosts')}, "
            f"{_menge(kennzahlen['widersprueche'], 'Widerspruch', 'Widersprüche')}.",
            "",
            "Befunde:",
            *[f"- {zeile}" for zeile in befunde],
            "",
            "Offene Fragen:",
            *[f"- {zeile}" for zeile in offene],
            "",
            "Grenzen: Regelbasierte Auswertung gespeicherter Kernaussagen. "
            "Es wurden keine neuen Quellen abgerufen und keine Semantik geprüft.",
        ] + ([f"Hinweis: {grundlage}"] if grundlage else []))
        return {
            "rolle": "bericht",
            "kennzahlen": kennzahlen,
            "befunde": befunde,
            "offene_fragen": offene,
            "claims": claims,
            "widersprueche": widersprueche,
            "generiert": self._iso(jetzt),
            "text": text[:12000],
        }
