"""Sicherer Erststart-Import einer mitgelieferten Orakel-Datenbank.

Der Schritt läuft im Container vor dem Serverstart (siehe
``docker-entrypoint.sh``). Er importiert die Seed-DB ausschließlich dann, wenn
die Zieldatenbank fehlt oder zwar das Schema, aber noch keine Kerndaten
enthält. Vorhandene Daten werden nie überschrieben: ist auch nur eine
Kernzeile vorhanden, bleibt die Datei unangetastet.

Der Import ist atomar (Kopie nach ``*.seed-tmp-*``, Integritätsprüfung,
``os.replace``), sodass ein Abbruch nie eine halb geschriebene DB hinterlässt.
Eine ersetzte leere DB wird vorher als ``<db>.leer-<zeitstempel>`` gesichert.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Tabellen, die nur durch echte Läufe gefüllt werden. Buchhaltungstabellen
# (konto, zustand) und das Company-Grundgerüst (agent_profiles, company_*)
# entstehen schon beim ersten Start und zählen deshalb nicht als Daten –
# sonst würde eine frisch angelegte DB nie als leer erkannt.
KERN_TABELLEN: tuple[str, ...] = (
    "artikel",
    "validierungen",
    "trades",
    "kerzen",
    "agenten_laeufe",
    "intel_inhalte",
    "konferenzen",
    "ereignisse",
    "entscheide",
    "positionen",
    "auswahl",
)

# Mindestens eine dieser Tabellen muss der Seed mitbringen, sonst ist er
# keine Orakel-Datenbank.
SEED_PFLICHT_TABELLEN = ("artikel", "trades", "validierungen")

STATUS_KEIN_SEED = "kein_seed"
STATUS_IMPORTIERT = "importiert"
STATUS_ERSETZT = "leer_ersetzt"
STATUS_VORHANDEN = "daten_vorhanden"
STATUS_ZIEL_KAPUTT = "ziel_kaputt"
STATUS_SEED_KAPUTT = "seed_kaputt"

STANDARD_SEED = "/app/seed/orakel-seed.db"


def _verbinden(pfad: Path, *, unveraenderlich: bool = False) -> sqlite3.Connection:
    """Öffnet read-only.

    ``unveraenderlich`` nutzt ``immutable=1``: SQLite legt dann keine
    ``-shm``/``-wal``-Dateien an. Das ist für den Seed und die Prüfkopie
    richtig (eine einzelne, statische Datei), nicht für die Zieldatenbank,
    die eine echte WAL haben kann.
    """
    option = "&immutable=1" if unveraenderlich else ""
    return sqlite3.connect(f"file:{pfad}?mode=ro{option}", uri=True, timeout=15)


def _integritaet(pfad: Path, *, unveraenderlich: bool = False) -> str | None:
    """Gibt ``None`` zurück, wenn die Datei eine intakte SQLite-DB ist."""
    try:
        with closing(_verbinden(pfad, unveraenderlich=unveraenderlich)) as c:
            zeile = c.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as fehler:
        return str(fehler)
    if not zeile:
        return "keine Antwort auf integrity_check"
    return None if str(zeile[0]).lower() == "ok" else str(zeile[0])


def _tabellen(pfad: Path, *, unveraenderlich: bool = False) -> set[str]:
    with closing(_verbinden(pfad, unveraenderlich=unveraenderlich)) as c:
        return {str(r[0]) for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}


def kern_zahlen(pfad: Path, *, unveraenderlich: bool = False) -> dict[str, int]:
    """Zeilenzahl der Kerntabellen; fehlende Tabellen zählen als 0."""
    with closing(_verbinden(pfad, unveraenderlich=unveraenderlich)) as c:
        vorhanden = {str(r[0]) for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        return {
            tabelle: int(c.execute(f'SELECT COUNT(*) FROM "{tabelle}"').fetchone()[0])
            for tabelle in KERN_TABELLEN
            if tabelle in vorhanden
        }


def ist_leer(zahlen: dict[str, int]) -> bool:
    return sum(zahlen.values()) == 0


def _beschreibung(zahlen: dict[str, int]) -> str:
    gefuellt = [f"{name}={wert}" for name, wert in zahlen.items() if wert]
    return ", ".join(gefuellt) if gefuellt else "keine Kerndaten"


def _freier_name(pfad: Path) -> Path:
    if not pfad.exists():
        return pfad
    for nummer in range(2, 1000):
        kandidat = pfad.with_name(f"{pfad.name}-{nummer}")
        if not kandidat.exists():
            return kandidat
    raise RuntimeError(f"kein freier Sicherungsname für {pfad}")


def _zeitstempel() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _beiseite(db: Path, ziel: Path) -> None:
    """Verschiebt WAL/SHM/Journal-Reste, damit sie nicht zur neuen DB passen."""
    for endung in ("-wal", "-shm", "-journal"):
        rest = db.with_name(db.name + endung)
        if rest.exists():
            os.replace(rest, ziel.with_name(ziel.name + endung))


def _fsync_ordner(ordner: Path) -> None:
    try:
        fd = os.open(ordner, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _installieren(seed: Path, ziel: Path) -> None:
    """Atomarer Austausch: kopieren, prüfen, umbenennen."""
    ziel.parent.mkdir(parents=True, exist_ok=True)
    temp = ziel.with_name(f"{ziel.name}.seed-tmp-{os.getpid()}")
    try:
        shutil.copyfile(seed, temp)
        with open(temp, "rb+") as datei:
            os.fsync(datei.fileno())
        fehler = _integritaet(temp, unveraenderlich=True)
        if fehler:
            raise RuntimeError(f"Kopie des Seeds ist beschädigt: {fehler}")
        if not set(SEED_PFLICHT_TABELLEN) & _tabellen(temp, unveraenderlich=True):
            raise RuntimeError("Kopie des Seeds enthält keine Orakel-Tabellen")
        os.replace(temp, ziel)
        _fsync_ordner(ziel.parent)
    finally:
        # Die Prüfverbindung kann -shm/-wal zur Kopie anlegen; die gehören
        # nicht ins Volume.
        for rest in (temp, *(temp.with_name(temp.name + e) for e in ("-wal", "-shm", "-journal"))):
            if rest.exists():
                rest.unlink()


def seed_importieren(
    db_pfad: str | Path,
    seed_pfad: str | Path | None,
    *,
    log: Callable[[str], None] = print,
) -> str:
    """Importiert ``seed_pfad`` nur in eine fehlende oder leere DB.

    Rückgabe ist einer der ``STATUS_*``-Werte. Die Funktion wirft nicht, wenn
    der Seed fehlt oder eine Datei unlesbar ist – sie meldet es und lässt die
    Zieldatenbank unverändert.
    """
    ziel = Path(db_pfad)
    seed = Path(seed_pfad) if seed_pfad else None

    if seed is None or not seed.exists():
        if ziel.exists():
            log(f"orakel-seed: kein Seed unter {seed} – vorhandene DB bleibt unverändert")
        else:
            log(f"orakel-seed: kein Seed unter {seed} – leere DB wird angelegt")
        return STATUS_KEIN_SEED

    # Eine offene WAL-Datei gehört zum Seed; ohne sie würde der Import Daten
    # verlieren. Der Seed wird deshalb als eine konsistente Datei erwartet
    # (erzeugen mit Connection.backup, siehe seed/README.md).
    seed_wal = seed.with_name(seed.name + "-wal")
    if seed_wal.exists() and seed_wal.stat().st_size > 0:
        log(f"orakel-seed: Seed {seed} hat eine offene WAL-Datei – bitte mit "
            "Connection.backup neu erzeugen, nichts importiert")
        return STATUS_SEED_KAPUTT

    fehler = _integritaet(seed, unveraenderlich=True)
    if fehler or not set(SEED_PFLICHT_TABELLEN) & _tabellen(seed, unveraenderlich=True):
        grund = fehler or "keine Orakel-Tabellen"
        log(f"orakel-seed: Seed {seed} ist unbrauchbar ({grund}) – nichts importiert")
        return STATUS_SEED_KAPUTT

    seed_zahlen = kern_zahlen(seed, unveraenderlich=True)
    kopf = (f"orakel-seed: Seed {seed.name} ({seed.stat().st_size} Bytes, "
            f"{_beschreibung(seed_zahlen)})")

    if not ziel.exists():
        _installieren(seed, ziel)
        log(f"{kopf} in neue DB {ziel} importiert")
        return STATUS_IMPORTIERT

    fehler = _integritaet(ziel)
    if fehler:
        log(f"orakel-seed: vorhandene DB {ziel} ist unlesbar ({fehler}) – "
            "bleibt unangetastet, bitte manuell prüfen")
        return STATUS_ZIEL_KAPUTT

    zahlen = kern_zahlen(ziel)
    if not ist_leer(zahlen):
        log(f"orakel-seed: {ziel} enthält Daten ({_beschreibung(zahlen)}) – "
            "nichts importiert")
        return STATUS_VORHANDEN

    sicherung = _freier_name(ziel.with_name(f"{ziel.name}.leer-{_zeitstempel()}"))
    shutil.copy2(ziel, sicherung)
    _beiseite(ziel, sicherung)
    _installieren(seed, ziel)
    log(f"{kopf} importiert; leere DB vorher gesichert als {sicherung.name}")
    return STATUS_ERSETZT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orakel-seed",
        description="Importiert eine mitgelieferte Orakel-DB nur in eine leere Zieldatenbank.",
    )
    parser.add_argument(
        "--db",
        default=os.environ.get("ORAKEL_DB_PFAD", "/data/orakel.db"),
        help="Pfad der Zieldatenbank (Standard: $ORAKEL_DB_PFAD)",
    )
    parser.add_argument(
        "--seed",
        default=os.environ.get("ORAKEL_SEED_DB", STANDARD_SEED),
        help=f"Pfad der Seed-Datenbank (Standard: $ORAKEL_SEED_DB, sonst {STANDARD_SEED})",
    )
    args = parser.parse_args(argv)

    try:
        status = seed_importieren(args.db, args.seed)
    except OSError as fehler:
        print(f"orakel-seed: Import fehlgeschlagen: {fehler}", file=sys.stderr)
        return 1
    # 0 = entschieden (importiert oder bewusst nichts getan),
    # 2 = Datei unlesbar/unbrauchbar, 1 = technischer Fehler.
    return 2 if status in (STATUS_ZIEL_KAPUTT, STATUS_SEED_KAPUTT) else 0


if __name__ == "__main__":
    raise SystemExit(main())
