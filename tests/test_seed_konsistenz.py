"""Dauerhafte Prüfung der Seed-Datenbank auf interne Widersprüche.

Geprüft wird, dass die gespeicherten Verweise in sich stimmen: Zeiger auf
Konferenzen, Auswahl und Trades auf Validierungen und der jüngste
Laufabschluss auf die Zeilen des letzten Laufs.

Ohne ``ORAKEL_SEED`` prüft der Test ``seed/orakel-seed.db``; ein Pfad in der
Umgebungsvariablen richtet ihn auf eine Kopie oder einen neu gebauten Seed.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

STANDARD_SEED = Path(__file__).resolve().parents[1] / "seed" / "orakel-seed.db"
SEED = Path(os.environ.get("ORAKEL_SEED", STANDARD_SEED))


@pytest.fixture(scope="module")
def db() -> Iterator[sqlite3.Connection]:
    assert SEED.is_file(), f"Seed fehlt: {SEED}"
    # Der Seed ist eine statische Datei; immutable verhindert -shm/-wal-Reste.
    verbindung = sqlite3.connect(f"file:{SEED}?mode=ro&immutable=1", uri=True)
    try:
        yield verbindung
    finally:
        verbindung.close()


def _zustand(c: sqlite3.Connection, schluessel: str) -> Any:
    zeile = c.execute("SELECT wert FROM zustand WHERE schluessel=?", (schluessel,)).fetchone()
    return json.loads(zeile[0]) if zeile else None


def _moment(wert: str) -> datetime:
    return datetime.fromisoformat(wert).astimezone(timezone.utc)


def test_letzte_konferenz_zeigt_auf_gespeicherte_sitzung(db: sqlite3.Connection) -> None:
    zeiger = _zustand(db, "letzte_konferenz")
    zeiten = [zeile[0] for zeile in db.execute("SELECT zeit FROM konferenzen")]
    if zeiger is None:
        assert not zeiten, "letzte_konferenz fehlt, obwohl Sitzungen gespeichert sind"
        return
    assert zeiten, "letzte_konferenz gesetzt, aber keine Sitzung gespeichert"
    assert _moment(zeiger) == max(_moment(zeit) for zeit in zeiten)


def test_auswahl_zeigt_auf_passende_validierung(db: sqlite3.Connection) -> None:
    offen = [zeile[0] for zeile in db.execute(
        "SELECT a.validierung_id FROM auswahl a"
        " LEFT JOIN validierungen v ON v.id = a.validierung_id"
        " WHERE v.id IS NULL")]
    assert not offen, f"Auswahl verweist auf fehlende Validierungen: {offen}"
    falsch = [tuple(zeile) for zeile in db.execute(
        "SELECT a.symbol, a.schluessel, a.validierung_id, v.symbol, v.schluessel, v.urteil"
        " FROM auswahl a JOIN validierungen v ON v.id = a.validierung_id"
        " WHERE v.urteil != 'bestanden' OR a.symbol != v.symbol"
        " OR a.schluessel != v.schluessel")]
    assert not falsch, f"Auswahl passt nicht zur Validierung: {falsch}"


def test_trades_zeigen_auf_passende_validierung(db: sqlite3.Connection) -> None:
    offen = [zeile[0] for zeile in db.execute(
        "SELECT t.id FROM trades t"
        " LEFT JOIN validierungen v ON v.id = t.validierung_id"
        " WHERE v.id IS NULL")]
    assert not offen, f"Trades verweisen auf fehlende Validierungen: {offen}"
    fremd = [tuple(zeile) for zeile in db.execute(
        "SELECT t.id, t.symbol, v.symbol FROM trades t"
        " JOIN validierungen v ON v.id = t.validierung_id"
        " WHERE t.symbol != v.symbol")]
    assert not fremd, f"Trades tragen ein fremdes Symbol: {fremd}"


def test_konferenzprotokolle_sind_lesbar_und_konsistent_datiet(db: sqlite3.Connection) -> None:
    for kid, zeit, roh in db.execute("SELECT id, zeit, protokoll FROM konferenzen"):
        protokoll = json.loads(roh)
        assert isinstance(protokoll, dict), f"Konferenz {kid}: Protokoll ist kein Objekt"
        assert protokoll.get("beschluss"), f"Konferenz {kid}: Beschluss fehlt"
        assert isinstance(protokoll.get("berichte"), list), f"Konferenz {kid}: Berichte fehlen"
        assert isinstance(protokoll.get("massnahmen"), list), f"Konferenz {kid}: Massnahmen fehlen"
        assert _moment(protokoll["zeit"]) == _moment(zeit), \
            f"Konferenz {kid}: Protokollzeit weicht von der Zeile ab"


def test_neuester_laufabschluss_passt_zu_den_zeilen(db: sqlite3.Connection) -> None:
    """Ereignisse tragen keine Lauf-ID; der jüngste Abschluss muss zu den Zeilen passen."""
    abschluss = None
    for (text,) in db.execute("SELECT text FROM ereignisse ORDER BY id DESC"):
        abschluss = re.search(r"\((\d+) Prüfungen, (\d+) ausgewählt\)", text)
        if abschluss:
            break
    assert abschluss, "Kein Laufabschluss-Ereignis gefunden"

    lauf = _zustand(db, "letzter_lauf_id")
    assert lauf, "letzter_lauf_id fehlt"
    pruefungen = db.execute(
        "SELECT COUNT(*) FROM validierungen WHERE lauf = ?", (lauf,)).fetchone()[0]
    auswahl = db.execute("SELECT COUNT(*) FROM auswahl").fetchone()[0]
    assert int(abschluss.group(1)) == pruefungen, \
        "Laufabschluss nennt andere Prüfungen als der letzte Lauf gespeichert hat"
    assert int(abschluss.group(2)) == auswahl, \
        "Laufabschluss nennt eine andere Auswahl als gespeichert ist"
