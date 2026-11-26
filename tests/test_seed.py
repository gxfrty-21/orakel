from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from orakel.kern.db import Facts
from orakel.seed import (
    STATUS_ERSETZT,
    STATUS_IMPORTIERT,
    STATUS_KEIN_SEED,
    STATUS_SEED_KAPUTT,
    STATUS_VORHANDEN,
    STATUS_ZIEL_KAPUTT,
    ein_lauf_stand,
    kern_zahlen,
    main,
    seed_importieren,
    validierungen_deduplizieren,
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


def _altbestand(pfad: Path) -> list[int]:
    """Altzustand nachstellen: drei inhaltsgleiche Kopien einer Validierung."""
    db = Facts(pfad)
    ids: list[int] = []
    with db.conn() as c:
        for lauf in ("L1", "L2", "L3"):
            cur = c.execute(
                "INSERT INTO validierungen(erstellt,lauf,symbol,strategie,schluessel,"
                "parameter,urteil,beschreibung,bericht) VALUES (?,?,?,?,?,?,?,?,?)",
                (lauf, lauf, "US500", "ema_cross", "ema_cross|fast=10,slow=100",
                 "{}", "bestanden", "Test", "{}"))
            vid = int(cur.lastrowid or 0)
            c.execute(
                "INSERT INTO trades(validierung_id,symbol,einstieg,ausstieg,stueck,netto,"
                "rendite_pct,grund) VALUES (?,?,?,?,?,?,?,?)",
                (vid, "US500", "2024-01-02 10:00:00", "2024-01-02 12:00:00",
                 10.0, 12.5, 0.4, "Signal"))
            ids.append(vid)
        c.execute(
            "INSERT INTO auswahl(symbol,schluessel,validierung_id,zeit) VALUES (?,?,?,?)",
            ("US500", "ema_cross|fast=10,slow=100", ids[0], "2026-01-01T00:00:00+00:00"))
    return ids


def test_deduplizieren_entfernt_kopien_und_haengt_auswahl_um(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    ids = _altbestand(pfad)

    ergebnis = validierungen_deduplizieren(pfad, log=_ruhig)

    assert ergebnis == {"gruppen": 1, "validierungen": 2, "trades": 2, "auswahl": 1}
    with sqlite3.connect(pfad) as c:
        assert c.execute("SELECT COUNT(*) FROM validierungen").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
        assert c.execute("SELECT id FROM validierungen").fetchone()[0] == ids[-1]
        assert c.execute("SELECT validierung_id FROM auswahl").fetchone()[0] == ids[-1]


def test_deduplizieren_ist_wiederholbar(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _altbestand(pfad)
    validierungen_deduplizieren(pfad, log=_ruhig)

    ergebnis = validierungen_deduplizieren(pfad, log=_ruhig)

    assert ergebnis["validierungen"] == 0
    assert ergebnis["trades"] == 0
    assert ergebnis["auswahl"] == 0


def test_deduplizieren_probelauf_aendert_nichts(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _altbestand(pfad)
    vorher = _hash(pfad)

    ergebnis = validierungen_deduplizieren(pfad, probelauf=True, log=_ruhig)

    assert ergebnis["validierungen"] == 2
    assert _hash(pfad) == vorher


def test_deduplizieren_laesst_abweichendes_urteil_stehen(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _altbestand(pfad)
    db = Facts(pfad)
    with db.conn() as c:
        c.execute("UPDATE validierungen SET urteil='abgelehnt'"
                  " WHERE id=(SELECT MAX(id) FROM validierungen)")

    ergebnis = validierungen_deduplizieren(pfad, log=_ruhig)

    assert ergebnis["gruppen"] == 2
    assert ergebnis["validierungen"] == 1
    with sqlite3.connect(pfad) as c:
        urteile = [r[0] for r in c.execute("SELECT urteil FROM validierungen ORDER BY id")]
    assert urteile == ["bestanden", "abgelehnt"]


def test_deduplizieren_laesst_ereignisse_und_konferenzen_stehen(tmp_path: Path) -> None:
    """Die Bereinigung räumt keine datierte Historie weg."""
    pfad = tmp_path / "orakel.db"
    _altbestand(pfad)
    db = Facts(pfad)
    with db.conn() as c:
        c.execute(
            "INSERT INTO ereignisse(zeit,stufe,quelle,text) VALUES (?,?,?,?)",
            ("2026-11-08T16:30:00+01:00", "info", "Engine",
             "Lauf beendet (24 Prüfungen, 1 ausgewählt)"))
        c.execute(
            "INSERT INTO ereignisse(zeit,stufe,quelle,text) VALUES (?,?,?,?)",
            ("2026-11-26T07:40:00+01:00", "info", "Engine",
             "Lauf beendet (8 Prüfungen, 0 ausgewählt)"))
        c.execute(
            "INSERT INTO konferenzen(zeit,protokoll) VALUES (?,?)",
            ("2026-11-08T17:30:33+01:00",
             '{"beschluss": "2 Strategien bleiben freigegeben"}'))
    with sqlite3.connect(pfad) as c:
        vorher_ereignisse = c.execute(
            "SELECT id,zeit,stufe,quelle,text FROM ereignisse ORDER BY id").fetchall()
        vorher_konferenzen = c.execute(
            "SELECT id,zeit,protokoll FROM konferenzen ORDER BY id").fetchall()

    validierungen_deduplizieren(pfad, log=_ruhig)

    with sqlite3.connect(pfad) as c:
        assert c.execute(
            "SELECT id,zeit,stufe,quelle,text FROM ereignisse ORDER BY id").fetchall() \
            == vorher_ereignisse
        assert c.execute(
            "SELECT id,zeit,protokoll FROM konferenzen ORDER BY id").fetchall() \
            == vorher_konferenzen
        assert c.execute("SELECT COUNT(*) FROM validierungen").fetchone()[0] == 1


def _historie(pfad: Path) -> None:
    """Zwei Läufe: alter Bestand und die Zeilen des letzten Laufs."""
    alt = "2026-11-08T15:18:00+00:00"
    neu = "2026-11-26T07:40:00+01:00"
    with sqlite3.connect(pfad) as c:
        c.executescript(
            """
            CREATE TABLE zustand (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
            CREATE TABLE ereignisse (id INTEGER PRIMARY KEY, zeit TEXT NOT NULL);
            CREATE TABLE konferenzen (id INTEGER PRIMARY KEY, zeit TEXT NOT NULL);
            CREATE TABLE agenten_laeufe (id INTEGER PRIMARY KEY, zeit TEXT NOT NULL);
            CREATE TABLE konto (id INTEGER PRIMARY KEY, zeit TEXT NOT NULL);
            CREATE TABLE artikel (id INTEGER PRIMARY KEY, geholt TEXT NOT NULL);
            CREATE TABLE intel_inhalte (artikel_id INTEGER, analysiert TEXT NOT NULL);
            CREATE TABLE intel_quellen (quelle TEXT, artikel INTEGER NOT NULL);
            CREATE TABLE intel_auftraege (id INTEGER PRIMARY KEY, zeit TEXT NOT NULL);
            """
        )
        c.executemany("INSERT INTO ereignisse(zeit) VALUES (?)", [(alt,), (alt,), (neu,)])
        c.execute("INSERT INTO konferenzen(zeit) VALUES (?)", (alt,))
        c.executemany("INSERT INTO agenten_laeufe(zeit) VALUES (?)",
                      [(alt,), (alt,), (alt,), (neu,), (neu,)])
        c.execute("INSERT INTO konto(zeit) VALUES (?)", (alt,))
        c.executemany("INSERT INTO artikel(geholt) VALUES (?)", [(alt,), (alt,)])
        c.executemany("INSERT INTO intel_inhalte(artikel_id, analysiert) VALUES (?,?)",
                      [(1, alt), (2, alt)])
        c.execute("INSERT INTO intel_quellen(quelle, artikel) VALUES (?,?)", ("SEC", 1))
        c.executemany("INSERT INTO intel_auftraege(zeit) VALUES (?)", [(alt,), (neu,)])
        c.executemany("INSERT INTO zustand(schluessel, wert) VALUES (?,?)", [
            ("letzter_lauf_id", '"2026-11-26T07:28:54+01:00"'),
            ("datenquelle", '"synthetisch"'),
            ("paper_letzter_tick", f'"{alt}"'),
            ("paper_konto", '{"datum": "2026-11-08"}'),
            ("letzte_konferenz", f'"{alt}"'),
            ("spider_letzter_lauf", "{}"),
        ])


def test_ein_lauf_stand_entfernt_zeilen_aelterer_laeufe(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _historie(pfad)

    ergebnis = ein_lauf_stand(pfad, log=_ruhig)

    assert ergebnis == {"ereignisse": 2, "konferenzen": 1, "agenten_laeufe": 3,
                        "konto": 1, "artikel": 2, "intel_inhalte": 2,
                        "intel_quellen": 1, "intel_auftraege": 1, "zustand": 4}
    with sqlite3.connect(pfad) as c:
        assert c.execute("SELECT COUNT(*) FROM ereignisse").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM konferenzen").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM agenten_laeufe").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM konto").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM artikel").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM intel_inhalte").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM intel_quellen").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM intel_auftraege").fetchone()[0] == 1
        assert {r[0] for r in c.execute("SELECT schluessel FROM zustand")} == {
            "letzter_lauf_id", "datenquelle"}


def test_ein_lauf_stand_behaelt_zeilen_des_letzten_laufs(tmp_path: Path) -> None:
    """Die Gegenprobe: Was zum letzten Lauf gehört, bleibt samt Zeigern stehen."""
    pfad = tmp_path / "orakel.db"
    _historie(pfad)
    neu = "2026-11-26T07:40:00+01:00"
    with sqlite3.connect(pfad) as c:
        c.execute("INSERT INTO ereignisse(zeit) VALUES (?)", ("2026-11-26T07:28:54+01:00",))
        c.execute("INSERT INTO konferenzen(zeit) VALUES (?)", (neu,))
        c.execute("INSERT INTO konto(zeit) VALUES (?)", (neu,))
        c.execute("INSERT INTO artikel(geholt) VALUES (?)", (neu,))
        c.execute("INSERT INTO intel_inhalte(artikel_id, analysiert) VALUES (?,?)", (3, neu))
        c.execute("INSERT INTO intel_quellen(quelle, artikel) VALUES (?,?)", ("NEU", 3))
        c.execute("UPDATE zustand SET wert=? WHERE schluessel='letzte_konferenz'",
                  (f'"{neu}"',))
        c.execute("UPDATE zustand SET wert=? WHERE schluessel='paper_letzter_tick'",
                  (f'"{neu}"',))
        c.execute("UPDATE zustand SET wert=? WHERE schluessel='paper_konto'",
                  ('{"datum": "2026-11-26"}',))

    ergebnis = ein_lauf_stand(pfad, log=_ruhig)

    assert ergebnis == {"ereignisse": 2, "konferenzen": 1, "agenten_laeufe": 3,
                        "konto": 1, "artikel": 2, "intel_inhalte": 2,
                        "intel_quellen": 0, "intel_auftraege": 1, "zustand": 0}
    with sqlite3.connect(pfad) as c:
        # Die Grenze selbst gehört noch zum letzten Lauf, nur Älteres fällt weg.
        assert {r[0] for r in c.execute("SELECT zeit FROM ereignisse")} == {
            "2026-11-26T07:28:54+01:00", neu}
        assert c.execute("SELECT zeit FROM konferenzen").fetchall() == [(neu,)]
        assert c.execute("SELECT zeit FROM konto").fetchall() == [(neu,)]
        assert c.execute("SELECT geholt FROM artikel").fetchall() == [(neu,)]
        assert c.execute("SELECT artikel_id FROM intel_inhalte").fetchall() == [(3,)]
        assert "NEU" in {r[0] for r in c.execute("SELECT quelle FROM intel_quellen")}
        zustand = dict(c.execute("SELECT schluessel, wert FROM zustand"))
        assert zustand["letzte_konferenz"] == f'"{neu}"'
        assert zustand["paper_letzter_tick"] == f'"{neu}"'
        assert zustand["paper_konto"] == '{"datum": "2026-11-26"}'
        assert "spider_letzter_lauf" in zustand


def test_ein_lauf_stand_ist_wiederholbar(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _historie(pfad)
    ein_lauf_stand(pfad, log=_ruhig)

    ergebnis = ein_lauf_stand(pfad, log=_ruhig)

    assert not any(ergebnis.values())


def test_ein_lauf_stand_probelauf_aendert_nichts(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _historie(pfad)
    vorher = _hash(pfad)

    ergebnis = ein_lauf_stand(pfad, probelauf=True, log=_ruhig)

    assert ergebnis["ereignisse"] == 2
    assert ergebnis["zustand"] == 4
    assert _hash(pfad) == vorher


def test_ein_lauf_stand_als_befehl(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _historie(pfad)

    assert main(["--db", str(pfad), "--ein-lauf", "--probelauf"]) == 0
    assert main(["--db", str(pfad), "--ein-lauf"]) == 0
    with sqlite3.connect(pfad) as c:
        assert c.execute("SELECT COUNT(*) FROM ereignisse").fetchone()[0] == 1


def test_deduplizieren_als_befehl(tmp_path: Path) -> None:
    pfad = tmp_path / "orakel.db"
    _altbestand(pfad)

    assert main(["--db", str(pfad), "--deduplizieren", "--probelauf"]) == 0
    assert main(["--db", str(pfad), "--deduplizieren"]) == 0
    with sqlite3.connect(pfad) as c:
        assert c.execute("SELECT COUNT(*) FROM validierungen").fetchone()[0] == 1
    with pytest.raises(SystemExit):
        main(["--db", str(pfad), "--probelauf"])
