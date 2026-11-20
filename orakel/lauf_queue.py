"""Warteschlange für lange Engine-Läufe.

Der Endpunkt ``POST /api/lauf`` legt nur noch einen Auftrag in der Tabelle
``laeufe`` an und antwortet sofort mit 202 und der ID. Ein Hintergrund-Thread
nimmt die Aufträge einzeln auf und ruft die bestehende Pipeline auf; damit
blockiert kein Backtest mehr den Request-Thread und kein Proxy-Timeout bricht
einen Lauf ab, der ohnehin weiterliefe.

Der Status ist über ``GET /api/lauf/{id}`` abfragbar: ``offen``, ``aktiv``,
``fertig`` oder ``fehler``. Ein einzelner Arbeiter verarbeitet die Aufträge
nacheinander; die Reihenfolge ist die Reihenfolge des Eingangs.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Callable

from .kern.db import Facts, jetzt

OFFEN = "offen"
AKTIV = "aktiv"
FERTIG = "fertig"
FEHLER = "fehler"

Engine = Callable[..., dict[str, Any]]


def _einfuegen(c: sqlite3.Connection, modus: str, spider: bool) -> int:
    cur = c.execute(
        "INSERT INTO laeufe (status, modus, spider, erstellt) VALUES (?, ?, ?, ?)",
        (OFFEN, modus, int(bool(spider)), jetzt()),
    )
    return int(cur.lastrowid)


def anlegen(db: Facts, modus: str = "backtest", spider: bool = False) -> int:
    """Legt einen Auftrag an und liefert seine ID. Führt nichts aus."""
    with db.conn() as c:
        return _einfuegen(c, modus, spider)


def anlegen_wenn_frei(db: Facts, modus: str = "backtest",
                      spider: bool = False) -> tuple[int, bool]:
    """Legt nur an, wenn kein Auftrag offen oder aktiv ist: ``(id, neu)``.

    Prüfung und Einfügen laufen in einer Schreibtransaktion (``BEGIN
    IMMEDIATE``). Zwei gleichzeitige Klicks sehen deshalb nacheinander denselben
    Stand: Der zweite bekommt die ID des ersten Auftrags und legt keinen
    weiteren an. ``neu`` ist ``False``, wenn ein bestehender Auftrag den Start
    verhindert.
    """
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        zeile = c.execute(
            "SELECT id FROM laeufe WHERE status IN (?, ?) ORDER BY id LIMIT 1",
            (OFFEN, AKTIV),
        ).fetchone()
        if zeile is not None:
            return int(zeile["id"]), False
        return _einfuegen(c, modus, spider), True


def stand(db: Facts, lauf_id: int) -> dict[str, Any] | None:
    """Status eines Auftrags; ``None``, wenn es die ID nicht gibt."""
    with db.conn() as c:
        zeile = c.execute("SELECT * FROM laeufe WHERE id = ?", (lauf_id,)).fetchone()
    if zeile is None:
        return None
    daten = dict(zeile)
    ergebnis = None
    if daten.get("ergebnis_json"):
        try:
            ergebnis = json.loads(daten["ergebnis_json"])
        except ValueError:
            ergebnis = None
    return {
        "id": daten["id"],
        "status": daten["status"],
        "modus": daten["modus"],
        "spider": bool(daten["spider"]),
        "erstellt": daten["erstellt"],
        "gestartet": daten["gestartet"],
        "beendet": daten["beendet"],
        "ergebnis": ergebnis,
        "fehler": daten["fehler"],
    }


def offene_id(db: Facts) -> int | None:
    """Ältester noch nicht begonnener Auftrag."""
    with db.conn() as c:
        zeile = c.execute(
            "SELECT id FROM laeufe WHERE status = ? ORDER BY id LIMIT 1", (OFFEN,)
        ).fetchone()
    return int(zeile["id"]) if zeile else None


def _beanspruchen(db: Facts, lauf_id: int) -> bool:
    """Setzt den Auftrag atomar auf aktiv; nur ein Arbeiter gewinnt."""
    with db.conn() as c:
        cur = c.execute(
            "UPDATE laeufe SET status = ?, gestartet = ? WHERE id = ? AND status = ?",
            (AKTIV, jetzt(), lauf_id, OFFEN),
        )
        return cur.rowcount == 1


def abschliessen(db: Facts, lauf_id: int, ergebnis: dict[str, Any]) -> None:
    with db.conn() as c:
        c.execute(
            "UPDATE laeufe SET status = ?, beendet = ?, ergebnis_json = ?, fehler = NULL "
            "WHERE id = ?",
            (FERTIG, jetzt(), json.dumps(ergebnis, ensure_ascii=False), lauf_id),
        )


def scheitern(db: Facts, lauf_id: int, fehler: str) -> None:
    with db.conn() as c:
        c.execute(
            "UPDATE laeufe SET status = ?, beendet = ?, fehler = ? WHERE id = ?",
            (FEHLER, jetzt(), fehler[:500], lauf_id),
        )


def _zusammenfassung(ergebnis: dict[str, Any]) -> dict[str, Any]:
    """Nur die Kennzahlen speichern; der volle Bericht liegt in dashboard.json."""
    return {
        "dauer": ergebnis.get("dauer_sekunden"),
        "validierungen": len(ergebnis.get("validierungen", []) or []),
        "plan": len(ergebnis.get("plan", []) or []),
        "fehler": len(ergebnis.get("fehler", []) or []),
    }


def verarbeite_einen(cfg_pfad: str, db: Facts | None = None,
                     engine: Engine | None = None) -> dict[str, Any] | None:
    """Arbeitet den ältesten offenen Auftrag ab. Ohne Auftrag passiert nichts.

    ``engine`` ist im Normalfall ``orakel.pipeline.lauf``; Tests ersetzen sie,
    ohne die echte Pipeline zu starten.
    """
    if db is None:
        from .config import load_config

        db = Facts(load_config(cfg_pfad).db_pfad)
    lauf_id = offene_id(db)
    if lauf_id is None:
        return None
    if not _beanspruchen(db, lauf_id):
        return None
    auftrag = stand(db, lauf_id)
    try:
        if engine is None:
            from .pipeline import lauf as engine
        ergebnis = engine(cfg_pfad=cfg_pfad, modus=auftrag["modus"],
                          mit_spider=bool(auftrag["spider"]))
    except Exception as exc:  # noqa: BLE001 - Auftrag scheitert, Arbeiter lebt weiter
        db.ereignis("fehler", "Lauf", f"Auftrag {lauf_id} abgebrochen: {exc}")
        scheitern(db, lauf_id, f"{type(exc).__name__}: {exc}")
        return {"id": lauf_id, "status": FEHLER}
    zusammenfassung = _zusammenfassung(ergebnis)
    abschliessen(db, lauf_id, zusammenfassung)
    return {"id": lauf_id, "status": FERTIG, **zusammenfassung}


class LaufWorker(threading.Thread):
    """Daemon-Thread: nimmt Aufträge aus der Warteschlange, bis er gestoppt wird."""

    def __init__(self, cfg_pfad: str, db: Facts, intervall: float = 1.0) -> None:
        super().__init__(daemon=True, name="orakel-lauf-arbeiter")
        self.cfg_pfad = cfg_pfad
        self.db = db
        self.intervall = max(0.05, float(intervall))
        self._stopp = threading.Event()

    def run(self) -> None:  # pragma: no cover - Zeitverhalten
        while not self._stopp.is_set():
            try:
                self.verarbeite()
            except Exception as exc:  # noqa: BLE001 - Arbeiter darf nicht sterben
                self.db.ereignis("fehler", "Lauf", f"Arbeiter gestört: {exc}")
            self._stopp.wait(self.intervall)

    def verarbeite(self) -> dict[str, Any] | None:
        return verarbeite_einen(self.cfg_pfad, db=self.db)

    def stoppe(self) -> None:
        self._stopp.set()
