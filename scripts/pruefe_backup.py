#!/usr/bin/env python3
"""Sichert die SQLite-Datenbank online und prüft die Wiederherstellung.

Der Online-Backup der SQLite-Bibliothek ist auch bei laufender App konsistent
(anders als das Kopieren der Datei, das mit WAL unvollständig sein kann). Nach
jeder Sicherung wird geprüft: ``PRAGMA integrity_check`` ist ``ok`` und die
Zeilenzahlen aller Tabellen stimmen mit der Quelle überein. Die
Wiederherstellungsprüfung öffnet die Sicherung ausschliesslich lesend mit
``mode=ro&immutable=1``; dadurch entstehen neben dem Backup keine
``-wal``/``-shm``-Dateien.

Aufrufe:
    python scripts/pruefe_backup.py --db orakel.db --ordner backups
    python scripts/pruefe_backup.py --db orakel.db --ordner backups --pruefen

Standard-Aufbewahrung: 7 Tagesstände und 4 Wochenstände.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TAGES_PRAEFIX = "orakel-"
WOCHEN_PRAEFIX = "orakel-kw-"


def _verbinde(pfad: Path, *, unveraenderlich: bool = False) -> sqlite3.Connection:
    """Öffnet eine Datenbank; Sicherungen nur lesend und unveränderlich.

    Eine normale Verbindung kann bei einer WAL-Datenbank ``-wal``/``-shm``
    anlegen. ``immutable=1`` sagt SQLite, dass die Datei unverändert bleibt;
    das ist für die statische Sicherung richtig und lässt den Backup-Ordner
    unberührt.
    """
    if unveraenderlich:
        uri = f"{Path(pfad).resolve().as_uri()}?mode=ro&immutable=1"
        c = sqlite3.connect(uri, uri=True)
    else:
        c = sqlite3.connect(pfad)
    c.execute("PRAGMA busy_timeout = 5000")
    return c


def _tabellen(c: sqlite3.Connection) -> list[str]:
    return [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


# Tabellennamen lassen sich in SQLite nicht als Parameter binden. Deshalb wird
# jede Kennung vor dem Einsetzen gegen ein reines Bezeichner-Muster geprüft:
# Buchstaben, Ziffern und Unterstriche, kein Anführungszeichen, kein Semikolon.
KENNUNG = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _zaehle(c: sqlite3.Connection, name: str) -> int:
    if not KENNUNG.match(name):
        raise ValueError(f"unerwarteter Tabellenname: {name!r}")
    return int(c.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])  # noqa: S608 - Kennung oben geprüft, kein Nutzertext


def zeilenzahlen(pfad: Path, *, unveraenderlich: bool = False) -> dict[str, int]:
    """Zeilenzahl je Tabelle; fehlende Tabellen fehlen auch im Ergebnis."""
    c = _verbinde(pfad, unveraenderlich=unveraenderlich)
    try:
        return {name: _zaehle(c, name) for name in _tabellen(c)}
    finally:
        c.close()


def integritaet(pfad: Path, *, unveraenderlich: bool = False) -> str:
    c = _verbinde(pfad, unveraenderlich=unveraenderlich)
    try:
        return str(c.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        c.close()


def sichere(db_pfad: Path, ordner: Path, *, jetzt: datetime | None = None,
            tage: int = 7, wochen: int = 4) -> dict[str, Any]:
    """Legt einen Tagesstand an, sonntags zusätzlich einen Wochenstand."""
    jetzt = jetzt or datetime.now(timezone.utc)
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / f"{TAGES_PRAEFIX}{jetzt:%Y-%m-%d}.db"

    quelle = _verbinde(db_pfad)
    kopie = sqlite3.connect(ziel)
    try:
        quelle.backup(kopie)
    finally:
        kopie.close()
        quelle.close()

    pruefung = integritaet(ziel, unveraenderlich=True)
    if pruefung != "ok":
        raise RuntimeError(f"Backup {ziel.name} ist nicht integer: {pruefung}")

    entfernt: list[str] = []
    if jetzt.weekday() == 6:  # Sonntag
        woche = ordner / f"{WOCHEN_PRAEFIX}{jetzt:%G-%V}.db"
        woche.write_bytes(ziel.read_bytes())
        for alt in sorted(ordner.glob(f"{WOCHEN_PRAEFIX}*.db"),
                          key=lambda p: p.stat().st_mtime, reverse=True)[wochen:]:
            alt.unlink()
            entfernt.append(alt.name)

    grenze = jetzt - timedelta(days=tage)
    for datei in sorted(ordner.glob(f"{TAGES_PRAEFIX}[0-9]*.db")):
        if datei == ziel:
            continue
        alter = datetime.fromtimestamp(datei.stat().st_mtime, timezone.utc)
        if alter < grenze:
            datei.unlink()
            entfernt.append(datei.name)

    return {"pfad": str(ziel), "bytes": ziel.stat().st_size, "integrity": pruefung,
            "erstellt": jetzt.isoformat(timespec="seconds"), "entfernt": entfernt}


def pruefe_restore(db_pfad: Path, backup_pfad: Path) -> dict[str, Any]:
    """Vergleicht Integrität und Zeilenzahlen von Quelle und Sicherung.

    Die Sicherung wird nur mit ``mode=ro&immutable=1`` geöffnet. Die Quelle
    bleibt der normale, live gelesene Pfad; sie ist nicht Teil des Backups.
    """
    if not backup_pfad.exists():
        raise FileNotFoundError(f"Backup fehlt: {backup_pfad}")
    integritaet_wert = integritaet(backup_pfad, unveraenderlich=True)
    quelle = zeilenzahlen(db_pfad)
    sicherung = zeilenzahlen(backup_pfad, unveraenderlich=True)
    abweichungen = [
        {"tabelle": name, "quelle": quelle.get(name), "sicherung": sicherung.get(name)}
        for name in sorted(set(quelle) | set(sicherung))
        if quelle.get(name) != sicherung.get(name)
    ]
    return {
        "backup": str(backup_pfad),
        "integrity": integritaet_wert,
        "tabellen": len(sicherung),
        "abweichungen": abweichungen,
        "ok": integritaet_wert == "ok" and not abweichungen,
    }


def neuestes_backup(ordner: Path) -> Path | None:
    dateien = sorted(ordner.glob(f"{TAGES_PRAEFIX}[0-9]*.db"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    return dateien[0] if dateien else None


def main() -> int:
    ap = argparse.ArgumentParser(description="SQLite-Backup sichern und prüfen.")
    ap.add_argument("--db", required=True, help="Pfad zur laufenden Datenbank")
    ap.add_argument("--ordner", default="backups", help="Zielordner der Sicherungen")
    ap.add_argument("--pruefen", action="store_true",
                    help="nur die neueste Sicherung gegen die Quelle prüfen")
    ap.add_argument("--tage", type=int, default=7)
    ap.add_argument("--wochen", type=int, default=4)
    args = ap.parse_args()

    db_pfad = Path(args.db)
    ordner = Path(args.ordner)
    if not db_pfad.exists():
        print(f"FEHLER: Datenbank fehlt: {db_pfad}", file=sys.stderr)
        return 2

    try:
        if args.pruefen:
            backup = neuestes_backup(ordner)
            if backup is None:
                print(f"FEHLER: keine Sicherung in {ordner}", file=sys.stderr)
                return 1
            ergebnis = pruefe_restore(db_pfad, backup)
            print(f"Restore-Probe: {backup.name} · integrity {ergebnis['integrity']} · "
                  f"{ergebnis['tabellen']} Tabellen · "
                  f"{'OK' if ergebnis['ok'] else 'ABWEICHUNGEN'}")
            for abweichung in ergebnis["abweichungen"]:
                print(f"  {abweichung['tabelle']}: Quelle {abweichung['quelle']}, "
                      f"Sicherung {abweichung['sicherung']}")
            return 0 if ergebnis["ok"] else 1
        ergebnis = sichere(db_pfad, ordner, tage=args.tage, wochen=args.wochen)
    except (OSError, sqlite3.Error, RuntimeError) as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        return 1
    print(f"Sicherung: {ergebnis['pfad']} ({ergebnis['bytes']} Bytes, "
          f"integrity {ergebnis['integrity']})")
    if ergebnis["entfernt"]:
        print("Entfernt: " + ", ".join(ergebnis["entfernt"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
