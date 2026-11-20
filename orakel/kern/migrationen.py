"""Nummerierte Migrationen für die Fakten-Datenbank.

Jede Datei ``orakel/migrations/NNNN_name.sql`` wird genau einmal angewendet;
die Tabelle ``schema_migrationen`` hält fest, welche Nummer wann lief. Ein
Downgrade nutzt die gleichnamige Datei ``NNNN_name.down.sql``.

Bestandsdatenbanken aus der Zeit vor dieser Tabelle erhalten keine
Sonderbehandlung: ``0001`` und ``0002`` sind idempotent, ``0003`` ergänzt
fehlende Spalten. Ein alter Bestand wird deshalb beim ersten Start normal
durchmigriert, ohne Daten zu verlieren.

Vor jedem Lauf, der auf einer bestehenden Datenbank tatsächlich etwas ändert,
entsteht eine Sicherung per SQLite-Online-Backup. Schlägt eine Migration fehl,
wird ihre Transaktion zurückgerollt; die Datenbank bleibt auf dem Stand davor.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

MIGRATIONS_ORDNER = Path(__file__).resolve().parents[1] / "migrations"
TABELLE = "schema_migrationen"
SCHEMA_TABELLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABELLE} (
    nummer INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    angewendet_am TEXT NOT NULL
)
"""


class MigrationsFehler(RuntimeError):
    """Migrationen sind nicht eindeutig, fehlerhaft oder nicht umkehrbar."""


class AltesSchemaFehler(MigrationsFehler):
    """Der Bestand hat ein älteres Schema, das sich nicht nachziehen lässt.

    Typisch: Die Tabelle existiert schon, aber ohne die Spalte, auf die eine
    Migration einen Index legt. SQLite kann eine vorhandene Tabelle nicht
    umbauen; hier hilft nur Export und Import in ein frisches Schema.
    """


_INDEX_SQL = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?P<index>\w+)\s+"
    r"ON\s+(?P<tabelle>\w+)\s*\((?P<spalten>[^)]*)\)",
    re.IGNORECASE,
)
_SPALTE_IM_FEHLER = re.compile(r"no such column: (?P<spalte>[\w.]+)")


@dataclass(frozen=True, slots=True)
class Migration:
    nummer: int
    name: str
    hoch: Path
    runter: Path | None

    @property
    def stand(self) -> str:
        return f"{self.nummer:04d}_{self.name}"


def dateien(ordner: Path | None = None) -> list[Migration]:
    """Liest die Migrationen in Nummernreihenfolge und prüft ihre Eindeutigkeit."""
    basis = Path(ordner or MIGRATIONS_ORDNER)
    hoch: dict[int, Migration] = {}
    for pfad in sorted(basis.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        if pfad.name.endswith(".down.sql"):
            continue
        try:
            nummer = int(pfad.name[:4])
        except ValueError as fehler:  # pragma: no cover - glob erzwingt Ziffern
            raise MigrationsFehler(f"Ungültiger Dateiname: {pfad.name}") from fehler
        if nummer in hoch:
            raise MigrationsFehler(f"Nummer {nummer} doppelt vergeben: {pfad.name}")
        runter = pfad.with_name(pfad.name[:-4] + ".down.sql")
        hoch[nummer] = Migration(nummer, pfad.name[5:-4], pfad,
                                 runter if runter.exists() else None)
    if not hoch:
        raise MigrationsFehler(f"Keine Migrationen in {basis}")
    return [hoch[nummer] for nummer in sorted(hoch)]


def _statements(sql: str) -> Iterable[str]:
    """Teilt ein SQL-Skript in vollständige Anweisungen (ohne Kommentarzeilen)."""
    puffer = ""
    for zeile in sql.splitlines(keepends=True):
        if not puffer and (not zeile.strip() or zeile.lstrip().startswith("--")):
            continue
        puffer += zeile
        if sqlite3.complete_statement(puffer):
            if puffer.strip():
                yield puffer.strip()
            puffer = ""
    if puffer.strip():
        yield puffer.strip()


def _altes_schema(datei: Path, anweisung: str, fehler: sqlite3.OperationalError,
                  datenbank: Path | None) -> AltesSchemaFehler:
    """Baut aus einem ``no such column`` eine Meldung mit Export/Import-Weg."""
    index = _INDEX_SQL.search(anweisung)
    spalte = _SPALTE_IM_FEHLER.search(str(fehler))
    name = spalte.group("spalte") if spalte else "eine erwartete Spalte"
    if index:
        was = (f"Index {index.group('index')} braucht die Spalte "
               f"{index.group('tabelle')}.{name}, die im Bestand fehlt")
    else:
        was = f"die Spalte {name} fehlt im Bestand"
    ziel = str(datenbank) if datenbank is not None else "<datenbank>"
    return AltesSchemaFehler(
        f"{datei.name}: {was}.\n"
        "Die Tabelle steht bereits in einer älteren Form in der Datenbank; "
        "CREATE TABLE IF NOT EXISTS ändert eine vorhandene Tabelle nicht.\n"
        "Die Migration wurde zurückgerollt; an der Datenbank hat sich nichts geändert.\n"
        "Daten exportieren und in ein frisches Schema importieren "
        "(Details: docs/MIGRATIONEN.md, Abschnitt «Sehr alte Bestände»):\n"
        f'  1. Datei sichern: cp "{ziel}" "{ziel}.vor-umbau"\n'
        f"  2. Export:        sqlite3 \"{ziel}\" '.dump' > orakel-export.sql\n"
        "  3. Alte Datei weglegen, die Anwendung einmal starten (legt das neue "
        "Schema an) und danach die Daten der Tabellen übernehmen, deren Spalten "
        "beide Stände teilen."
    )


def _wende_datei_an(c: sqlite3.Connection, datei: Path,
                    datenbank: Path | None = None) -> None:
    """Führt eine Datei in einer Transaktion aus; bei Fehler bleibt nichts zurück."""
    c.execute("BEGIN")
    try:
        for anweisung in _statements(datei.read_text(encoding="utf-8")):
            if anweisung.upper().startswith("PRAGMA"):
                # WAL und foreign_keys setzt der Aufrufer vor der Transaktion.
                continue
            try:
                c.execute(anweisung)
            except sqlite3.OperationalError as fehler:
                # SQLite kennt kein ADD COLUMN IF NOT EXISTS. Eine bereits
                # vorhandene Spalte ist kein Fehler, sondern der Normalfall bei
                # einer frisch angelegten Datenbank.
                if "duplicate column name" in str(fehler):
                    continue
                if "no such column" in str(fehler):
                    # Ein Bestand ohne die Spalte (etwa ein Index auf
                    # titel_hash) ist kein Programmierfehler: Die Meldung nennt
                    # Index, Tabelle und Spalte und den Weg über Export/Import.
                    raise _altes_schema(datei, anweisung, fehler, datenbank) from fehler
                raise
        c.commit()
    except AltesSchemaFehler:
        c.rollback()
        raise
    except Exception as fehler:
        c.rollback()
        raise MigrationsFehler(f"{datei.name}: {fehler}") from fehler


def _verbinde(pfad: Path) -> sqlite3.Connection:
    c = sqlite3.connect(pfad, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout = 5000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _tabellen(c: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' AND name != ?", (TABELLE,))]


def angewendet(pfad: str | Path) -> list[int]:
    """Nummern der bereits angewendeten Migrationen (leer, wenn Tabelle fehlt)."""
    c = sqlite3.connect(pfad)
    try:
        vorhanden = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (TABELLE,)).fetchone()
        if not vorhanden:
            return []
        return [int(r[0]) for r in c.execute(
            f"SELECT nummer FROM {TABELLE} ORDER BY nummer")]
    finally:
        c.close()


def _sichere(pfad: Path, jetzt: datetime) -> Path:
    ziel = pfad.with_name(f"{pfad.name}.vor-migration-{jetzt:%Y%m%d-%H%M%S}.bak")
    quelle = sqlite3.connect(pfad)
    kopie = sqlite3.connect(ziel)
    try:
        quelle.backup(kopie)
    finally:
        kopie.close()
        quelle.close()
    return ziel


def anwenden(pfad: str | Path, *, ordner: Path | None = None, bis: int | None = None,
             jetzt: datetime | None = None) -> dict[str, object]:
    """Wendet alle offenen Migrationen bis einschliesslich ``bis`` an."""
    datei = Path(pfad)
    datei.parent.mkdir(parents=True, exist_ok=True)
    jetzt = jetzt or datetime.now(timezone.utc)
    alle = dateien(ordner)
    c = _verbinde(datei)
    try:
        c.executescript(SCHEMA_TABELLE_SQL)
        c.commit()
        stand = {int(r["nummer"]) for r in c.execute(f"SELECT nummer FROM {TABELLE}")}
        bestand = _tabellen(c)

        offen = [m for m in alle
                 if m.nummer not in stand and (bis is None or m.nummer <= bis)]
        sicherung = None
        if offen and bestand:
            sicherung = _sichere(datei, jetzt)

        angewendet_nummern: list[int] = []
        for migration in offen:
            _wende_datei_an(c, migration.hoch, datei)
            c.execute(
                f"INSERT INTO {TABELLE} (nummer, name, angewendet_am) VALUES (?, ?, ?)",
                (migration.nummer, migration.name, jetzt.isoformat(timespec="seconds")),
            )
            c.commit()
            angewendet_nummern.append(migration.nummer)

        neuer_stand = max(stand | set(angewendet_nummern), default=0)
        if neuer_stand:
            # Auch die alte Initialisierung kannte nur user_version; der Wert
            # bleibt als grobe Standanzeige erhalten (höchste Migration).
            c.execute(f"PRAGMA user_version = {neuer_stand}")
            c.commit()

        return {
            "angewendet": angewendet_nummern,
            "backup": str(sicherung) if sicherung else None,
            "stand": neuer_stand,
        }
    finally:
        c.close()


def zurueckrollen(pfad: str | Path, *, bis: int = 0, ordner: Path | None = None,
                  jetzt: datetime | None = None) -> dict[str, object]:
    """Rollt Migrationen oberhalb von ``bis`` mit ihren Down-Dateien zurück.

    Das löscht Daten der betroffenen Tabellen. Die Sicherung entsteht vor dem
    ersten Rückrollschritt; ohne Down-Datei bricht der Lauf ab, bevor etwas
    geändert wurde.
    """
    datei = Path(pfad)
    jetzt = jetzt or datetime.now(timezone.utc)
    alle = {m.nummer: m for m in dateien(ordner)}
    stand = angewendet(datei)
    zurueck = sorted((nummer for nummer in stand if nummer > bis), reverse=True)
    fehlend = [nummer for nummer in zurueck
               if alle.get(nummer) is None or alle[nummer].runter is None]
    if fehlend:
        raise MigrationsFehler(
            "Kein Downgrade hinterlegt für: " + ", ".join(f"{n:04d}" for n in fehlend))
    if not zurueck:
        return {"zurueckgerollt": [], "backup": None}

    sicherung = _sichere(datei, jetzt)
    c = _verbinde(datei)
    try:
        for nummer in zurueck:
            _wende_datei_an(c, alle[nummer].runter, datei)  # type: ignore[arg-type]
            c.execute(f"DELETE FROM {TABELLE} WHERE nummer = ?", (nummer,))
            c.commit()
    finally:
        c.close()
    return {"zurueckgerollt": zurueck, "backup": str(sicherung)}
