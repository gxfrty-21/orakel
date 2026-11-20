"""Dauerbetrieb: geplanter Betriebstakt, auch ohne offenes Dashboard."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import agents
from .betrieb import Betrieb
from .config import Config, RisikoGrenzen
from .kern.db import Facts
from .lauf_queue import (AUFBEWAHRUNG_TAKT, raeume_auf, verarbeite_einen,
                         verwerfe_haengende, zuruecksetzen)


def _validierungen_als_dicts(db: Facts) -> list[dict[str, Any]]:
    import json

    lauf = db.zustand("letzter_lauf_id")
    raus = []
    for r in db.letzte_validierungen(lauf):
        try:
            bericht = json.loads(r["bericht"])
        except Exception:
            bericht = {}
        bericht.update({"symbol": r["symbol"], "strategie": r["strategie"],
                        "urteil": r["urteil"], "parameter": json.loads(r["parameter"]),
                        "beschreibung": r["beschreibung"], "schluessel": r["schluessel"]})
        raus.append(bericht)
    return raus


def _kontext(cfg: Config, db: Facts, modus: str = "paper") -> dict[str, Any]:
    letztes = db.letztes_konto()
    equity = float(letztes["equity"]) if letztes else cfg.start_kapital
    hoechst = float(letztes["hoechststand"]) if letztes else cfg.start_kapital
    dd = (hoechst - equity) / hoechst * 100 if hoechst else 0.0
    return {
        "cfg": cfg,
        "grenzen": RisikoGrenzen.aus_config(cfg),
        "validierungen": _validierungen_als_dicts(db),
        "qualitaet": [],
        "konto": {"equity": equity, "positionen": len(db.positionen()),
                  "drawdown_pct": round(dd, 2)},
        "plan": [],
        "modus": modus,
        "db": db,
    }


def agenda_nachholen(cfg: Config, db: Facts,
                     jetzt_wert: datetime | None = None) -> dict[str, Any] | None:
    """Sammelt die Agenda am Abend vor der Mitternachtssitzung — einmal pro Tag.

    Vor 22:00 Uhr passiert nichts. Ist für heute schon eine Agenda gespeichert,
    wird sie nicht überschrieben.
    """
    tz = ZoneInfo(cfg["basis"].get("zeitzone", "Europe/Zurich"))
    jetzt = jetzt_wert or datetime.now(tz)
    if jetzt.tzinfo is None:
        jetzt = jetzt.replace(tzinfo=tz)
    else:
        jetzt = jetzt.astimezone(tz)
    if jetzt.hour < 22:
        return None
    gespeichert = db.zustand("sekretariat_agenda") or {}
    if str(gespeichert.get("zeit") or "")[:10] == jetzt.date().isoformat():
        return None
    from .sekretariat import agenda

    eintrag = agenda(db)
    db.ereignis("info", "Sekretariat",
                f"Abendagenda für die Mitternachtssitzung gesammelt "
                f"({len(eintrag.get('themen') or [])} Themen)")
    return eintrag


def konferenz_nachholen(cfg: Config, db: Facts) -> dict[str, Any] | None:
    """Ist die Konferenz des heutigen Tages ausgeblieben, wird sie nachgeholt."""
    tz = ZoneInfo(cfg["basis"].get("zeitzone", "Europe/Zurich"))
    heute = datetime.now(tz).date().isoformat()
    letzte = db.zustand("letzte_konferenz")
    if letzte and str(letzte)[:10] >= heute:
        return None
    return agents.konferenz(db, _kontext(cfg, db), erzwungen=True)


def unternehmen_takt(cfg: Config, db: Facts, max_tasks: int | None = None) -> dict[str, Any]:
    """Ein Company-Lauf; nur bei aktivierter Unternehmensschicht aufgerufen."""
    from .company.runtime import CompanyRuntime

    return CompanyRuntime(cfg, db).run(max_tasks=max_tasks)


def takt_schritt(cfg: Config, db: Facts, mit_spider: bool = False,
                 jetzt_wert: Any = None) -> dict[str, Any]:
    """Ein geplanter Betriebstakt.

    Die Jobs laufen nicht mehr ungeprüft nacheinander: ``Betrieb`` prüft
    Intervall, Backoff und Ressourcenbudget. ``mit_spider`` erzwingt den
    ersten Recherche-Lauf, der bisher beim Start üblich war.
    """
    jetzt = (lambda: jetzt_wert) if jetzt_wert is not None else None
    return Betrieb(cfg, db, jetzt_funktion=jetzt).takt(
        erzwungen={"spider"} if mit_spider else None)


class Takt(threading.Thread):
    """Der eine Hintergrund-Loop: Betriebstakt und Lauf-Warteschlange.

    Beide Arbeiten teilen sich denselben Thread, damit der Prozess nur einen
    Hintergrund-Loop hat. Ohne ``takt_aktiv`` läuft nur die Warteschlange: Der
    Paper-Takt bleibt opt-in (``serve --takt``), ein eingereihter Lauf wird
    aber in jedem Fall abgearbeitet. ``cfg_pfad`` ist der Pfad, den die
    Pipeline eines Auftrags benutzt.
    """

    def __init__(self, cfg: Config, db: Facts, mit_spider: bool = False, *,
                 cfg_pfad: str = "config.toml", takt_aktiv: bool = True) -> None:
        super().__init__(daemon=True, name="orakel-takt")
        self.cfg = cfg
        self.db = db
        self.mit_spider = mit_spider
        self.cfg_pfad = cfg_pfad
        self.takt_aktiv = takt_aktiv
        self._stopp = threading.Event()
        self.letzter_lauf: dict[str, Any] = {}
        self.betrieb = Betrieb(cfg, db)

    def run(self) -> None:  # pragma: no cover - Zeitverhalten
        intervall = (max(5, int(self.cfg["paper"].get("takt_sekunden", 60)))
                     if self.takt_aktiv else 1.0)
        try:
            erinnerungs_minuten = max(1, int(self.cfg.abschnitt(
                "unternehmen").get("erinnerungen_intervall_minuten", 5)))
        except (TypeError, ValueError):
            erinnerungs_minuten = 5
        erinnerungs_intervall = erinnerungs_minuten * 60
        # -inf macht beide Arbeiten in der ersten Runde fällig. 0.0 wäre erst
        # nach dem vollen Intervall Laufzeit der Monotonic-Uhr fällig – und die
        # zählt ab dem Boot: Auf einem frisch gestarteten Rechner (Container,
        # CI) würden Erinnerungen und Aufbewahrung sonst eine ganze Runde
        # warten.
        letzte_erinnerung = float("-inf")
        letzte_aufbewahrung = float("-inf")
        erzwungen = {"spider"} if self.mit_spider else None
        # Einmal beim Start: Was ein Absturz auf «aktiv» liess, wird wieder
        # eingereiht. Nicht in der Schleife, sonst reiht sich ein laufender
        # Auftrag selbst wieder ein.
        zuruecksetzen(self.db)
        while not self._stopp.is_set():
            beginn = time.monotonic()
            if self.takt_aktiv:
                try:
                    self.letzter_lauf = self.betrieb.takt(erzwungen=erzwungen)
                except Exception as exc:
                    self.db.ereignis("fehler", "Takt", f"Betriebstakt abgebrochen: {exc}")
                erzwungen = None
                if time.monotonic() - letzte_erinnerung >= erinnerungs_intervall:
                    letzte_erinnerung = time.monotonic()
                    try:
                        from .company.messaging import MessagingService
                        from .company.store import CompanyStore

                        MessagingService(CompanyStore(self.db)).erinnere_offene_acks()
                    except Exception as exc:
                        self.db.ereignis(
                            "fehler", "Takt", f"Erinnerungen abgebrochen: {exc}")
            # Genau ein Auftrag je Runde; ein langer Lauf verlängert den Abstand
            # genauso wenig wie ein langer Takt.
            try:
                # Aufbewahrung vor dem Lauf, damit ein langer Auftrag sie nicht
                # um Stunden verschiebt; im Dauerbetrieb höchstens stündlich.
                if time.monotonic() - letzte_aufbewahrung >= AUFBEWAHRUNG_TAKT:
                    letzte_aufbewahrung = time.monotonic()
                    raeume_auf(self.db)
                verwerfe_haengende(self.db)
                verarbeite_einen(self.db, self.cfg_pfad)
            except Exception as exc:
                self.db.ereignis("fehler", "Lauf", f"Warteschlange abgebrochen: {exc}")
            wartezeit = max(1.0, intervall - (time.monotonic() - beginn))
            self._stopp.wait(wartezeit)

    def stoppe(self) -> None:
        self._stopp.set()
