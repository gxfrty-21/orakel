"""Warteschlange für lange Engine-Läufe.

Der Endpunkt ``POST /api/lauf`` legt nur noch einen Auftrag in der Tabelle
``laeufe`` an und antwortet sofort mit 202 und der ID. Ein Hintergrund-Thread
nimmt die Aufträge einzeln auf und ruft die bestehende Pipeline auf; damit
blockiert kein Backtest mehr den Request-Thread und kein Proxy-Timeout bricht
einen Lauf ab, der ohnehin weiterliefe.

Der Status ist über ``GET /api/lauf/{id}`` abfragbar: ``offen``, ``aktiv``,
``fertig`` oder ``fehler``. Ein einzelner Arbeiter verarbeitet die Aufträge
nacheinander; die Reihenfolge ist die Reihenfolge des Eingangs.

Beim Start hält kein Prozess mehr einen Auftrag: Was dann noch auf ``aktiv``
steht, stammt von einem abgestürzten Vorgänger und wird wieder auf ``offen``
gesetzt, damit es nicht liegen bleibt.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .kern.db import Facts, jetzt

OFFEN = "offen"
AKTIV = "aktiv"
FERTIG = "fertig"
FEHLER = "fehler"

# Ein Auftrag, der länger als das hier auf «aktiv» steht, kann nicht mehr von
# einem laufenden Arbeiter stammen: Der Prozess hängt oder ist abgestürzt.
HAENGE_GRENZE = timedelta(minutes=60)

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
                      spider: bool = False) -> tuple[int, str | None]:
    """Legt nur an, wenn kein Auftrag offen oder aktiv ist: ``(id, blockiert)``.

    Prüfung und Einfügen laufen in einer Schreibtransaktion (``BEGIN
    IMMEDIATE``). Zwei gleichzeitige Klicks sehen deshalb nacheinander denselben
    Stand: Der zweite bekommt die ID des ersten Auftrags und legt keinen
    weiteren an. ``blockiert`` ist ``None`` für einen neuen Auftrag, sonst der
    Status des Auftrags, der den Start verhindert.
    """
    with db.conn() as c:
        c.execute("BEGIN IMMEDIATE")
        zeile = c.execute(
            "SELECT id, status FROM laeufe WHERE status IN (?, ?) ORDER BY id LIMIT 1",
            (OFFEN, AKTIV),
        ).fetchone()
        if zeile is not None:
            return int(zeile["id"]), str(zeile["status"])
        return _einfuegen(c, modus, spider), None


def stand(db: Facts, lauf_id: int) -> dict[str, Any] | None:
    """Auftrag als Zeile; ``ergebnis`` ist ausgepackt, ``None`` ohne ID."""
    with db.conn() as c:
        zeile = c.execute("SELECT * FROM laeufe WHERE id = ?", (lauf_id,)).fetchone()
    if zeile is None:
        return None
    daten = dict(zeile)
    roh = daten.pop("ergebnis_json", None)
    daten["spider"] = bool(daten["spider"])
    daten["ergebnis"] = json.loads(roh) if roh else None
    return daten


def zuruecksetzen(db: Facts) -> list[int]:
    """Setzt Aufträge, die ein Absturz auf «aktiv» liess, wieder auf «offen».

    Das läuft genau einmal beim Start des Arbeiters, nicht in der Schleife:
    Beim Start hält kein Prozess mehr einen Auftrag, ein Absturzrest kann also
    gefahrlos erneut eingereiht werden. ``gestartet`` wird geleert, damit die
    Hänge-Grenze ab dem neuen Versuch misst. Ein Ereignis hält jeden Reset
    fest. In der Schleife würde derselbe Aufruf einen laufenden Auftrag wieder
    einreihen.
    """
    with db.conn() as c:
        ids = [int(zeile["id"]) for zeile in c.execute(
            "SELECT id FROM laeufe WHERE status = ? ORDER BY id", (AKTIV,))]
        if ids:
            c.execute(
                "UPDATE laeufe SET status = ?, gestartet = NULL WHERE status = ?",
                (OFFEN, AKTIV),
            )
    for lauf_id in ids:
        db.ereignis("warnung", "Lauf",
                    f"Auftrag {lauf_id} stand beim Start auf «aktiv» und ist wieder offen")
    return ids


def verwerfe_haengende(db: Facts, *, grenze: timedelta = HAENGE_GRENZE,
                       jetzt_wert: datetime | None = None) -> list[int]:
    """Verbucht Aufträge, die im Betrieb länger als ``grenze`` «aktiv» sind.

    Ein Auftrag, der den Prozess nicht abstürzen lässt, aber nie zurückkommt,
    würde die Warteschlange sonst dauerhaft blockieren. Der Fehlertext nennt
    die Grenze. Beim Start ist das nicht nötig: Dort greift ``zuruecksetzen``.
    """
    bezug = (jetzt_wert or datetime.now(timezone.utc)).astimezone()
    grenz_zeit = (bezug - grenze).replace(microsecond=0).isoformat()
    with db.conn() as c:
        ids = [int(zeile["id"]) for zeile in c.execute(
            "SELECT id FROM laeufe WHERE status = ? AND gestartet IS NOT NULL "
            "AND gestartet <= ? ORDER BY id",
            (AKTIV, grenz_zeit),
        )]
    minuten = int(grenze.total_seconds() // 60)
    for lauf_id in ids:
        scheitern(
            db, lauf_id,
            f"Lauf blieb länger als {minuten} Minuten auf «aktiv» und wurde "
            "verworfen (Arbeiter hängen geblieben)",
        )
        db.ereignis("fehler", "Lauf",
                    f"Auftrag {lauf_id} hing auf «aktiv» und wurde als Fehler verbucht")
    return ids


def scheitern(db: Facts, lauf_id: int, fehler: str) -> None:
    with db.conn() as c:
        c.execute(
            "UPDATE laeufe SET status = ?, beendet = ?, fehler = ? WHERE id = ?",
            (FEHLER, jetzt(), fehler[:500], lauf_id),
        )


def abschliessen(db: Facts, lauf_id: int, ergebnis: dict[str, Any]) -> None:
    with db.conn() as c:
        c.execute(
            "UPDATE laeufe SET status = ?, beendet = ?, ergebnis_json = ?, fehler = NULL "
            "WHERE id = ?",
            (FERTIG, jetzt(), json.dumps(ergebnis, ensure_ascii=False), lauf_id),
        )


def _zusammenfassung(ergebnis: dict[str, Any]) -> dict[str, Any]:
    """Nur die Kennzahlen speichern; der volle Bericht liegt in dashboard.json."""
    return {
        "dauer": ergebnis.get("dauer_sekunden"),
        "validierungen": len(ergebnis.get("validierungen", []) or []),
        "plan": len(ergebnis.get("plan", []) or []),
        "fehler": len(ergebnis.get("fehler", []) or []),
    }


def _naechsten_beanspruchen(db: Facts) -> int | None:
    """Setzt den ältesten offenen Auftrag auf aktiv; nur ein Arbeiter gewinnt."""
    with db.conn() as c:
        zeile = c.execute(
            "SELECT id FROM laeufe WHERE status = ? ORDER BY id LIMIT 1", (OFFEN,)
        ).fetchone()
        if zeile is None:
            return None
        lauf_id = int(zeile["id"])
        cur = c.execute(
            "UPDATE laeufe SET status = ?, gestartet = ? WHERE id = ? AND status = ?",
            (AKTIV, jetzt(), lauf_id, OFFEN),
        )
        return lauf_id if cur.rowcount == 1 else None


def verarbeite_einen(db: Facts, cfg_pfad: str = "config.toml",
                     engine: Engine | None = None) -> int | None:
    """Arbeitet den ältesten offenen Auftrag ab und liefert seine ID.

    ``engine`` ist im Normalfall ``orakel.pipeline.lauf``; Tests ersetzen sie,
    ohne die echte Pipeline zu starten. Ohne offenen Auftrag passiert nichts.
    """
    lauf_id = _naechsten_beanspruchen(db)
    if lauf_id is None:
        return None
    auftrag = stand(db, lauf_id)
    try:
        if engine is None:
            from .pipeline import lauf as engine
        ergebnis = engine(cfg_pfad=cfg_pfad, modus=auftrag["modus"],
                          mit_spider=auftrag["spider"])
    except Exception as exc:  # noqa: BLE001 - Auftrag scheitert, Arbeiter lebt weiter
        db.ereignis("fehler", "Lauf", f"Auftrag {lauf_id} abgebrochen: {exc}")
        scheitern(db, lauf_id, f"{type(exc).__name__}: {exc}")
        return lauf_id
    abschliessen(db, lauf_id, _zusammenfassung(ergebnis))
    return lauf_id
