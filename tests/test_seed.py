from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from orakel.seed import (
    STATUS_ERSETZT,
    STATUS_IMPORTIERT,
    STATUS_KEIN_SEED,
    STATUS_SEED_KAPUTT,
    STATUS_VORHANDEN,
    STATUS_ZIEL_KAPUTT,
    kern_zahlen,
    main,
    seed_importieren,
)


def _db(pfad: Path, *, artikel: int = 0, konto: int = 0) -> Path:
    """Kleine Test-DB mit Kern- und Buchhaltungstabellen."""
    c = sqlite3.connect(pfad)
    try:
        c.executescript(
            """
            CREATE TABLE artikel (id INTEGER PRIMARY KEY, titel TEXT NOT NULL);
            CREATE TABLE trades (id INTEGER PRIMARY KEY, symbol TEXT NOT NULL);
            CREATE TABLE konto (id INTEGER PRIMARY KEY, equity REAL NOT NULL);
            """
        )
        c.executemany("INSERT INTO artikel(titel) VALUES (?)",
                      [(f"Seed-Artikel {i}",) for i in range(artikel)])
        c.executemany("INSERT INTO konto(equity) VALUES (?)",
                      [(100000.0,) for _ in range(konto)])
        c.commit()
    finally:
        c.close()
    return pfad


def _artikel(pfad: Path) -> int:
    with sqlite3.connect(f"file:{pfad}?mode=ro", uri=True) as c:
        return int(c.execute("SELECT COUNT(*) FROM artikel").fetchone()[0])


def _hash(pfad: Path) -> str:
    return hashlib.sha256(pfad.read_bytes()).hexdigest()


def _ruhig(_: str) -> None:
    pass


@pytest.fixture
def seed(tmp_path: Path) -> Path:
    return _db(tmp_path / "seed.db", artikel=5)


def test_fehlende_db_wird_aus_seed_angelegt(tmp_path: Path, seed: Path) -> None:
    ziel = tmp_path / "orakel.db"
    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_IMPORTIERT
    assert _artikel(ziel) == 5
    assert kern_zahlen(ziel)["artikel"] == 5


def test_bestehende_daten_bleiben_unangetastet(tmp_path: Path, seed: Path) -> None:
    ziel = _db(tmp_path / "orakel.db", artikel=2)
    vorher = _hash(ziel)
    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_VORHANDEN
    assert _hash(ziel) == vorher
    assert _artikel(ziel) == 2
    assert not list(tmp_path.glob("orakel.db.leer-*"))


def test_leere_db_wird_ersetzt_und_gesichert(tmp_path: Path, seed: Path) -> None:
    # Buchhaltungszeilen entstehen beim ersten Start und dürfen den Import
    # nicht blockieren.
    ziel = _db(tmp_path / "orakel.db", artikel=0, konto=1)
    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_ERSETZT
    assert _artikel(ziel) == 5
    sicherungen = list(tmp_path.glob("orakel.db.leer-*"))
    assert len(sicherungen) == 1
    assert _artikel(sicherungen[0]) == 0


def test_wal_reste_werden_mitgesichert(tmp_path: Path, seed: Path) -> None:
    ziel = _db(tmp_path / "orakel.db", artikel=0)
    (tmp_path / "orakel.db-wal").write_bytes(b"wal-rest")
    (tmp_path / "orakel.db-shm").write_bytes(b"shm-rest")

    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_ERSETZT

    assert not (tmp_path / "orakel.db-wal").exists()
    assert not (tmp_path / "orakel.db-shm").exists()
    # Nach dem Import dürfen keine Reste zur neuen DB passen.
    assert not list(tmp_path.glob("orakel.db.seed-tmp-*"))

    sicherungen = [p for p in tmp_path.glob("orakel.db.leer-*")
                   if not p.name.endswith(("-wal", "-shm"))]
    assert len(sicherungen) == 1
    sicherung = sicherungen[0]
    assert Path(str(sicherung) + "-wal").read_bytes() == b"wal-rest"
    # SQLite legt die -shm beim Lesen neu an; entscheidend ist, dass sie zur
    # Sicherung gehört und nicht zur neuen DB.
    assert Path(str(sicherung) + "-shm").exists()


def test_seed_mit_offener_wal_wird_abgelehnt(tmp_path: Path, seed: Path) -> None:
    (tmp_path / "seed.db-wal").write_bytes(b"ungesicherte seiten")
    ziel = tmp_path / "orakel.db"
    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_SEED_KAPUTT
    assert not ziel.exists()


def test_kaputte_db_bleibt_unangetastet(tmp_path: Path, seed: Path) -> None:
    ziel = tmp_path / "orakel.db"
    ziel.write_bytes(b"das ist keine datenbank")
    vorher = _hash(ziel)

    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_ZIEL_KAPUTT
    assert _hash(ziel) == vorher
    assert not list(tmp_path.glob("orakel.db.leer-*"))


def test_fehlender_seed_legt_nichts_an(tmp_path: Path) -> None:
    ziel = tmp_path / "orakel.db"
    assert seed_importieren(ziel, tmp_path / "gibtsnicht.db", log=_ruhig) == STATUS_KEIN_SEED
    assert not ziel.exists()


def test_unbrauchbarer_seed_wird_nicht_importiert(tmp_path: Path) -> None:
    ziel = tmp_path / "orakel.db"
    kaputt = tmp_path / "seed.db"
    kaputt.write_bytes(b"kein sqlite")
    assert seed_importieren(ziel, kaputt, log=_ruhig) == STATUS_SEED_KAPUTT
    assert not ziel.exists()


def test_leere_fremd_db_ohne_orakel_tabellen_ist_kein_seed(tmp_path: Path) -> None:
    ziel = tmp_path / "orakel.db"
    fremd = tmp_path / "fremd.db"
    with sqlite3.connect(fremd) as c:
        c.execute("CREATE TABLE irgendwas (id INTEGER)")
    assert seed_importieren(ziel, fremd, log=_ruhig) == STATUS_SEED_KAPUTT
    assert not ziel.exists()


def test_zweiter_lauf_aendert_nichts(tmp_path: Path, seed: Path) -> None:
    ziel = tmp_path / "orakel.db"
    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_IMPORTIERT
    nachher = _hash(ziel)
    assert seed_importieren(ziel, seed, log=_ruhig) == STATUS_VORHANDEN
    assert _hash(ziel) == nachher


def test_cli_exitcodes(tmp_path: Path, seed: Path) -> None:
    ziel = tmp_path / "orakel.db"
    assert main(["--db", str(ziel), "--seed", str(seed)]) == 0
    assert _artikel(ziel) == 5
    assert main(["--db", str(ziel), "--seed", str(seed)]) == 0

    kaputt = tmp_path / "kaputt.db"
    kaputt.write_bytes(b"kein sqlite")
    assert main(["--db", str(tmp_path / "neu.db"), "--seed", str(kaputt)]) == 2
    assert not (tmp_path / "neu.db").exists()
