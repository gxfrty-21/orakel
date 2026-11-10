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
from .db import Facts


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
    """Hintergrund-Takt. Daemon-Thread: stirbt mit dem Prozess."""

    def __init__(self, cfg: Config, db: Facts, mit_spider: bool = False) -> None:
        super().__init__(daemon=True, name="orakel-takt")
        self.cfg = cfg
        self.db = db
        self.mit_spider = mit_spider
        self._stopp = threading.Event()
        self.letzter_lauf: dict[str, Any] = {}
        self.betrieb = Betrieb(cfg, db)

    def run(self) -> None:  # pragma: no cover - Zeitverhalten
        intervall = max(5, int(self.cfg["paper"].get("takt_sekunden", 60)))
        erzwungen = {"spider"} if self.mit_spider else None
        while not self._stopp.is_set():
            beginn = time.monotonic()
            try:
                self.letzter_lauf = self.betrieb.takt(erzwungen=erzwungen)
            except Exception as exc:
                self.db.ereignis("fehler", "Takt", f"Betriebstakt abgebrochen: {exc}")
            erzwungen = None
            # Ein langer Takt verlängert den Abstand nicht zusätzlich.
            wartezeit = max(1.0, intervall - (time.monotonic() - beginn))
            self._stopp.wait(wartezeit)

    def stoppe(self) -> None:
        self._stopp.set()
