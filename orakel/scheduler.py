"""Dauerbetrieb: Paper-Takt und Mitternachtskonferenz, auch ohne offenes Dashboard."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import agents
from .config import Config, RisikoGrenzen
from .db import Facts
from .intel import IntelNetz
from .nexus.missionen import Missionen
from .paper import tick
from .spider import Spider
from .knowledge import Vault


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


def takt_schritt(cfg: Config, db: Facts, mit_spider: bool = False) -> dict[str, Any]:
    ergebnis: dict[str, Any] = {}
    try:
        ergebnis["paper"] = tick(cfg, db)
    except Exception as exc:
        db.ereignis("fehler", "Takt", f"Paper-Takt fehlgeschlagen: {exc}")
        ergebnis["paper"] = {"fehler": str(exc)}
    try:
        ergebnis["konferenz"] = konferenz_nachholen(cfg, db)
    except Exception as exc:
        db.ereignis("fehler", "Takt", f"Konferenz fehlgeschlagen: {exc}")
        ergebnis["konferenz"] = None
    if mit_spider:
        try:
            ergebnis["spider"] = Spider(cfg, db, Vault(cfg.vault_ordner)).lauf()
        except Exception as exc:
            db.ereignis("fehler", "Takt", f"Spider fehlgeschlagen: {exc}")
    try:
        netz = IntelNetz(cfg, db, Vault(cfg.vault_ordner))
        ids = (ergebnis.get("spider") or {}).get("neue_ids") or []
        ergebnis["intel"] = {**netz.verarbeite(ids), **netz.lernschleife()}
    except Exception as exc:
        db.ereignis("fehler", "Takt", f"Intelligence fehlgeschlagen: {exc}")
    try:
        ergebnis["missionen"] = Missionen(
            db, vault=Vault(cfg.vault_ordner)).weiterarbeiten(max_tasks=5)
    except Exception as exc:
        db.ereignis("fehler", "Takt", f"Missionen fehlgeschlagen: {exc}")
        ergebnis["missionen"] = {"fehler": str(exc)}
    if cfg.abschnitt("unternehmen").get("aktiv", False):
        try:
            ergebnis["unternehmen"] = unternehmen_takt(cfg, db)
        except Exception as exc:
            db.ereignis("fehler", "Takt", f"Company-Schicht fehlgeschlagen: {exc}")
            ergebnis["unternehmen"] = {"fehler": str(exc)}
    return ergebnis


class Takt(threading.Thread):
    """Hintergrund-Takt. Daemon-Thread: stirbt mit dem Prozess."""

    def __init__(self, cfg: Config, db: Facts, mit_spider: bool = False) -> None:
        super().__init__(daemon=True, name="orakel-takt")
        self.cfg = cfg
        self.db = db
        self.mit_spider = mit_spider
        self._stopp = threading.Event()
        self.letzter_lauf: dict[str, Any] = {}

    def run(self) -> None:  # pragma: no cover - Zeitverhalten
        intervall = max(5, int(self.cfg["paper"].get("takt_sekunden", 60)))
        while not self._stopp.is_set():
            self.letzter_lauf = takt_schritt(self.cfg, self.db, self.mit_spider)
            self._stopp.wait(intervall)
            # Nach dem ersten Durchlauf reicht der günstige Takt ohne Spider
            self.mit_spider = False

    def stoppe(self) -> None:
        self._stopp.set()
