from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS kerzen (
    symbol TEXT NOT NULL,
    zeitrahmen TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, zeitrahmen, ts)
);

CREATE TABLE IF NOT EXISTS validierungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    erstellt TEXT NOT NULL,
    lauf TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL,
    strategie TEXT NOT NULL,
    schluessel TEXT NOT NULL,
    parameter TEXT NOT NULL,
    urteil TEXT NOT NULL,
    beschreibung TEXT NOT NULL,
    bericht TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_val_erstellt ON validierungen(erstellt);
CREATE INDEX IF NOT EXISTS ix_val_lauf ON validierungen(lauf);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    validierung_id INTEGER,
    symbol TEXT NOT NULL,
    einstieg TEXT,
    ausstieg TEXT,
    stueck REAL,
    netto REAL,
    rendite_pct REAL,
    grund TEXT
);

CREATE TABLE IF NOT EXISTS entscheide (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    symbol TEXT NOT NULL,
    aktion TEXT NOT NULL,
    menge REAL,
    kurs REAL,
    strategie TEXT,
    status TEXT NOT NULL,
    genehmigt INTEGER NOT NULL,
    gruende TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ereignisse (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    stufe TEXT NOT NULL,
    quelle TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS konto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    positionen INTEGER NOT NULL,
    hoechststand REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS positionen (
    symbol TEXT PRIMARY KEY,
    menge REAL NOT NULL,
    einstieg REAL NOT NULL,
    stop REAL NOT NULL,
    strategie TEXT NOT NULL,
    eroeffnet TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS konferenzen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    protokoll TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agenten_laeufe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    agent TEXT NOT NULL,
    abteilung TEXT NOT NULL,
    aufgabe TEXT NOT NULL,
    ergebnis TEXT NOT NULL,
    ok INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS auswahl (
    symbol TEXT PRIMARY KEY,
    schluessel TEXT NOT NULL,
    validierung_id INTEGER NOT NULL,
    zeit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zustand (
    schluessel TEXT PRIMARY KEY,
    wert TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artikel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    geholt TEXT NOT NULL,
    quelle TEXT NOT NULL,
    typ TEXT NOT NULL,
    titel TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    veroeffentlicht TEXT,
    zusammenfassung TEXT,
    qualitaet REAL NOT NULL,
    symbole TEXT NOT NULL DEFAULT '[]',
    titel_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_artikel_hash ON artikel(titel_hash);
CREATE INDEX IF NOT EXISTS ix_artikel_geholt ON artikel(geholt);

-- Nexus: jede Meldung, auch Kopien. artikel_id zeigt auf das Original.
CREATE TABLE IF NOT EXISTS nexus_meldungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meldung_key TEXT NOT NULL UNIQUE,
    artikel_id INTEGER NOT NULL,
    cluster_id TEXT NOT NULL,
    simhash TEXT NOT NULL,
    sprache TEXT NOT NULL,
    sprache_konfidenz REAL NOT NULL DEFAULT 0,
    sprache_methode TEXT NOT NULL DEFAULT '',
    ist_original INTEGER NOT NULL DEFAULT 1,
    quelle_id TEXT NOT NULL,
    titel TEXT NOT NULL,
    zusammenfassung TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    abgerufen_am TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nexus_cluster ON nexus_meldungen(cluster_id);
CREATE INDEX IF NOT EXISTS ix_nexus_artikel ON nexus_meldungen(artikel_id);
CREATE INDEX IF NOT EXISTS ix_nexus_sprache ON nexus_meldungen(sprache);

-- Spider Intelligence: analysierter Volltext je Artikel
CREATE TABLE IF NOT EXISTS intel_inhalte (
    artikel_id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    zeichen INTEGER NOT NULL,
    analysiert TEXT NOT NULL
);

-- Forschungsaufträge mit vollständigem Steckbrief
CREATE TABLE IF NOT EXISTS intel_auftraege (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kennung TEXT NOT NULL UNIQUE,
    zeit TEXT NOT NULL,
    abteilung TEXT NOT NULL,
    titel TEXT NOT NULL,
    problem TEXT NOT NULL DEFAULT '',
    information TEXT NOT NULL DEFAULT '',
    quellen TEXT NOT NULL DEFAULT '[]',
    frage TEXT NOT NULL DEFAULT '',
    hypothese TEXT NOT NULL DEFAULT '',
    untersuchung TEXT NOT NULL DEFAULT '',
    nutzen TEXT NOT NULL DEFAULT '',
    risiko TEXT NOT NULL DEFAULT '',
    art TEXT NOT NULL DEFAULT 'allgemein',
    bezug_symbol TEXT,
    bezug_schluessel TEXT,
    kurs_bei_erstellung REAL,
    atr_bei_erstellung REAL,
    status TEXT NOT NULL DEFAULT 'offen',
    ergebnis TEXT NOT NULL DEFAULT '',
    aktualisiert TEXT
);
CREATE INDEX IF NOT EXISTS ix_intel_status ON intel_auftraege(status);

-- Weiterleitungen an Abteilungen
CREATE TABLE IF NOT EXISTS intel_weiterleitungen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kennung TEXT NOT NULL,
    zeit TEXT NOT NULL,
    von TEXT NOT NULL,
    an TEXT NOT NULL,
    betreff TEXT NOT NULL,
    bezug TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'neu'
);
CREATE INDEX IF NOT EXISTS ix_intel_wl_zeit ON intel_weiterleitungen(zeit);

-- Quellenqualität aus echten Läufen
CREATE TABLE IF NOT EXISTS intel_quellen (
    quelle TEXT PRIMARY KEY,
    artikel INTEGER NOT NULL DEFAULT 0,
    analysiert INTEGER NOT NULL DEFAULT 0,
    qualitaet_summe REAL NOT NULL DEFAULT 0,
    bestaetigt INTEGER NOT NULL DEFAULT 0,
    widerlegt INTEGER NOT NULL DEFAULT 0,
    zuletzt TEXT
);
"""


def jetzt() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


COMPANY_SCHEMA_VERSION = 1
MIGRATIONS_ORDNER = Path(__file__).with_name("migrations")


def _company_schema_laden() -> str:
    pfad = MIGRATIONS_ORDNER / "001_company.sql"
    if not pfad.exists():
        raise FileNotFoundError(f"Company-Migration fehlt: {pfad}")
    return pfad.read_text(encoding="utf-8")


class Facts:
    """Fakten-Datenbank. Jede Zahl im Dashboard stammt von hier."""

    def __init__(self, pfad: str | Path) -> None:
        self.pfad = Path(pfad)
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript(SCHEMA_SQL)
            version = int(c.execute("PRAGMA user_version").fetchone()[0])
            if version < COMPANY_SCHEMA_VERSION:
                # Additive Migration: bestehende Tabellen und Zeilen bleiben unberührt.
                c.executescript(_company_schema_laden())
                c.execute(f"PRAGMA user_version = {COMPANY_SCHEMA_VERSION}")

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.pfad, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- Kerzen ----------
    def kerzen_speichern(self, symbol: str, zeitrahmen: str, reihen: Iterable[dict[str, Any]]) -> int:
        daten = [
            (symbol, zeitrahmen, str(r["ts"]), float(r["open"]), float(r["high"]),
             float(r["low"]), float(r["close"]), float(r.get("volume", 0) or 0))
            for r in reihen
        ]
        if not daten:
            return 0
        with self.conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO kerzen(symbol,zeitrahmen,ts,open,high,low,close,volume)"
                " VALUES (?,?,?,?,?,?,?,?)",
                daten,
            )
        return len(daten)

    def kerzen(self, symbol: str, zeitrahmen: str) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT ts,open,high,low,close,volume FROM kerzen"
                " WHERE symbol=? AND zeitrahmen=? ORDER BY ts",
                (symbol, zeitrahmen),
            ))

    def symbole(self) -> list[str]:
        with self.conn() as c:
            return [r["symbol"] for r in c.execute("SELECT DISTINCT symbol FROM kerzen ORDER BY symbol")]

    # ---------- Validierungen ----------
    def validierung_speichern(
        self, symbol: str, strategie: str, schluessel: str, parameter: dict[str, Any],
        urteil: str, beschreibung: str, bericht: dict[str, Any],
        trades: Sequence[dict[str, Any]] = (), lauf: str = "",
    ) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO validierungen(erstellt,lauf,symbol,strategie,schluessel,parameter,urteil,beschreibung,bericht)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (jetzt(), lauf, symbol, strategie, schluessel,
                 json.dumps(parameter, ensure_ascii=False),
                 urteil, beschreibung, json.dumps(bericht, ensure_ascii=False)),
            )
            vid = int(cur.lastrowid or 0)
            if trades:
                c.executemany(
                    "INSERT INTO trades(validierung_id,symbol,einstieg,ausstieg,stueck,netto,rendite_pct,grund)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    [(vid, symbol, t["einstieg"], t["ausstieg"], t["stueck"], t["netto"],
                      t["rendite_pct"], t["grund"]) for t in trades],
                )
        return vid

    def letzte_validierungen(self, lauf: str | None = None) -> list[sqlite3.Row]:
        with self.conn() as c:
            if lauf:
                return list(c.execute(
                    "SELECT * FROM validierungen WHERE lauf=? ORDER BY symbol, strategie", (lauf,)
                ))
            return list(c.execute(
                "SELECT * FROM validierungen WHERE id IN ("
                "SELECT MAX(id) FROM validierungen GROUP BY symbol, schluessel)"
                " ORDER BY symbol, strategie"
            ))

    def alle_validierungen(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM validierungen ORDER BY id DESC"))

    # ---------- Auswahl ----------
    def auswahl_setzen(self, symbol: str, schluessel: str, validierung_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO auswahl(symbol,schluessel,validierung_id,zeit) VALUES (?,?,?,?)",
                (symbol, schluessel, validierung_id, jetzt()),
            )

    def auswahl(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM auswahl ORDER BY symbol"))

    # ---------- Entscheide ----------
    def entscheid_speichern(self, symbol: str, aktion: str, menge: float | None, kurs: float | None,
                            strategie: str | None, status: str, genehmigt: bool,
                            gruende: Sequence[str]) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO entscheide(zeit,symbol,aktion,menge,kurs,strategie,status,genehmigt,gruende)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (jetzt(), symbol, aktion, menge, kurs, strategie, status, int(genehmigt),
                 json.dumps(list(gruende), ensure_ascii=False)),
            )
            return int(cur.lastrowid or 0)

    def entscheide(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM entscheide ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- Ereignisse ----------
    def ereignis(self, stufe: str, quelle: str, text: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO ereignisse(zeit,stufe,quelle,text) VALUES (?,?,?,?)",
                      (jetzt(), stufe, quelle, text))

    def ereignisse(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM ereignisse ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- Konto ----------
    def konto_speichern(self, equity: float, cash: float, positionen: int, hoechststand: float) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO konto(zeit,equity,cash,positionen,hoechststand) VALUES (?,?,?,?,?)",
                      (jetzt(), equity, cash, positionen, hoechststand))

    def letztes_konto(self) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM konto ORDER BY id DESC LIMIT 1").fetchone()

    # ---------- Agenten ----------
    def agenten_lauf(self, agent: str, abteilung: str, aufgabe: str, ergebnis: str, ok: bool) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO agenten_laeufe(zeit,agent,abteilung,aufgabe,ergebnis,ok) VALUES (?,?,?,?,?,?)",
                (jetzt(), agent, abteilung, aufgabe, ergebnis, int(ok)),
            )

    def agenten_laeufe(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM agenten_laeufe ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- Positionen ----------
    def positionen(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM positionen ORDER BY symbol"))

    def position_setzen(self, symbol: str, menge: float, einstieg: float, stop: float,
                        strategie: str, eroeffnet: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO positionen(symbol,menge,einstieg,stop,strategie,eroeffnet)"
                " VALUES (?,?,?,?,?,?)",
                (symbol, menge, einstieg, stop, strategie, eroeffnet),
            )

    def position_loeschen(self, symbol: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM positionen WHERE symbol=?", (symbol,))

    def validierung(self, vid: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM validierungen WHERE id=?", (vid,)).fetchone()

    # ---------- Artikel (Spider Intelligence) ----------
    def artikel_speichern(
        self, quelle: str, typ: str, titel: str, url: str, veroeffentlicht: str | None,
        zusammenfassung: str, qualitaet: float, symbole: list[str], titel_hash: str,
    ) -> int | None:
        """Speichert einen Artikel und gibt seine id zurück. None = Dublette."""
        with self.conn() as c:
            bekannt = c.execute(
                "SELECT 1 FROM artikel WHERE url=? OR titel_hash=? LIMIT 1", (url, titel_hash)
            ).fetchone()
            if bekannt:
                return None
            cur = c.execute(
                "INSERT INTO artikel(geholt,quelle,typ,titel,url,veroeffentlicht,zusammenfassung,"
                "qualitaet,symbole,titel_hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (jetzt(), quelle, typ, titel, url, veroeffentlicht, zusammenfassung,
                 qualitaet, json.dumps(symbole, ensure_ascii=False), titel_hash),
            )
            return int(cur.lastrowid or 0) or None

    def artikel(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM artikel ORDER BY id DESC LIMIT ?", (limit,)
            ))

    def artikel_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = c.execute("SELECT COUNT(*) n FROM artikel").fetchone()["n"]
            nach_typ = [dict(r) for r in c.execute(
                "SELECT typ, COUNT(*) n, AVG(qualitaet) q FROM artikel GROUP BY typ ORDER BY n DESC"
            )]
            nach_quelle = [dict(r) for r in c.execute(
                "SELECT quelle, COUNT(*) n FROM artikel GROUP BY quelle ORDER BY n DESC LIMIT 10"
            )]
        return {"gesamt": gesamt, "typen": nach_typ, "quellen": nach_quelle}

    def artikel_id_by_url_oder_hash(self, url: str, titel_hash: str) -> int | None:
        """Findet ein bereits vorhandenes Original, ohne es erneut zu speichern."""
        with self.conn() as c:
            zeile = c.execute(
                "SELECT id FROM artikel WHERE url=? OR titel_hash=? LIMIT 1",
                (url, titel_hash),
            ).fetchone()
        return int(zeile["id"]) if zeile else None

    # ---------- Nexus: Meldungen und Dubletten ----------
    def nexus_meldung(self, meldung_key: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM nexus_meldungen WHERE meldung_key=?", (meldung_key,)
            ).fetchone()

    def nexus_meldung_speichern(
        self, meldung_key: str, artikel_id: int, cluster_id: str, simhash: str,
        sprache: str, konfidenz: float, methode: str, ist_original: bool,
        quelle_id: str, titel: str, zusammenfassung: str, url: str,
        abgerufen_am: str,
    ) -> bool:
        """Speichert eine Meldung. False = key war schon vorhanden."""
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO nexus_meldungen(meldung_key,artikel_id,cluster_id,simhash,"
                "sprache,sprache_konfidenz,sprache_methode,ist_original,quelle_id,"
                "titel,zusammenfassung,url,abgerufen_am)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(meldung_key) DO NOTHING",
                (meldung_key, int(artikel_id), cluster_id, simhash, sprache,
                 float(konfidenz), methode, int(ist_original), quelle_id, titel,
                 zusammenfassung, url, abgerufen_am),
            )
            return bool(cur.rowcount)

    def nexus_originale(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT meldung_key, artikel_id, cluster_id, simhash, titel, "
                "zusammenfassung FROM nexus_meldungen WHERE ist_original=1 ORDER BY id"
            ))

    def nexus_meldungen(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM nexus_meldungen ORDER BY id DESC LIMIT ?", (limit,)
            ))

    def nexus_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_meldungen").fetchone()["n"])
            originale = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_meldungen WHERE ist_original=1"
            ).fetchone()["n"])
            cluster = int(c.execute(
                "SELECT COUNT(DISTINCT cluster_id) n FROM nexus_meldungen"
            ).fetchone()["n"])
            nach_sprache = [dict(r) for r in c.execute(
                "SELECT sprache, COUNT(*) n FROM nexus_meldungen "
                "GROUP BY sprache ORDER BY n DESC, sprache"
            )]
        dubletten = gesamt - originale
        return {
            "gesamt": gesamt,
            "originale": originale,
            "dubletten": dubletten,
            "dublettenquote": round(dubletten / gesamt, 3) if gesamt else 0.0,
            "cluster": cluster,
            "nach_sprache": nach_sprache,
        }

    def artikel_by_ids(self, ids: Sequence[int]) -> list[sqlite3.Row]:
        if not ids:
            return []
        platzhalter = ",".join("?" for _ in ids)
        with self.conn() as c:
            return list(c.execute(f"SELECT * FROM artikel WHERE id IN ({platzhalter})", tuple(ids)))

    def artikel_aktualisieren(self, artikel_id: int, qualitaet: float, symbole: list[str]) -> None:
        with self.conn() as c:
            c.execute("UPDATE artikel SET qualitaet=?, symbole=? WHERE id=?",
                      (qualitaet, json.dumps(symbole, ensure_ascii=False), artikel_id))

    def artikel_inhalt_speichern(self, artikel_id: int, text: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO intel_inhalte(artikel_id,text,zeichen,analysiert)"
                " VALUES (?,?,?,?)",
                (artikel_id, text, len(text), jetzt()),
            )

    def artikel_inhalt(self, artikel_id: int) -> str:
        with self.conn() as c:
            r = c.execute("SELECT text FROM intel_inhalte WHERE artikel_id=?", (artikel_id,)).fetchone()
        return r["text"] if r else ""

    # ---------- Spider Intelligence: Aufträge ----------
    def intel_zaehler(self, prefix: str, tag: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM intel_auftraege WHERE kennung LIKE ?",
                          (f"{prefix}-{tag}-%",)).fetchone()
        return int(r["n"])

    def intel_auftrag_speichern(self, daten: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_auftraege(kennung,zeit,abteilung,titel,problem,information,"
                "quellen,frage,hypothese,untersuchung,nutzen,risiko,art,bezug_symbol,"
                "bezug_schluessel,kurs_bei_erstellung,atr_bei_erstellung,status,ergebnis,aktualisiert)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (daten["kennung"], daten.get("zeit") or jetzt(), daten["abteilung"],
                 daten["titel"], daten.get("problem", ""), daten.get("information", ""),
                 json.dumps(daten.get("quellen") or [], ensure_ascii=False),
                 daten.get("frage", ""), daten.get("hypothese", ""),
                 daten.get("untersuchung", ""), daten.get("nutzen", ""),
                 daten.get("risiko", ""), daten.get("art", "allgemein"),
                 daten.get("bezug_symbol"), daten.get("bezug_schluessel"),
                 daten.get("kurs_bei_erstellung"), daten.get("atr_bei_erstellung"),
                 daten.get("status", "offen"), daten.get("ergebnis", ""), jetzt()),
            )

    def intel_auftraege(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM intel_auftraege ORDER BY id DESC LIMIT ?", (limit,)))

    def intel_auftrag(self, kennung: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM intel_auftraege WHERE kennung=?", (kennung,)).fetchone()

    def intel_offener_auftrag(self, art: str, bezug_symbol: str | None = None,
                              bezug_schluessel: str | None = None) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM intel_auftraege WHERE status='offen' AND art=?"
                " AND COALESCE(bezug_symbol,'')=COALESCE(?,'')"
                " AND COALESCE(bezug_schluessel,'')=COALESCE(?,'') LIMIT 1",
                (art, bezug_symbol, bezug_schluessel),
            ).fetchone()

    def intel_auftrag_existiert(self, art: str, bezug_symbol: str | None = None,
                                bezug_schluessel: str | None = None, tage: int = 7) -> bool:
        """Verhindert Wiederholungen — auch nach Abschluss eines Auftrags."""
        grenze = (datetime.now(timezone.utc) - timedelta(days=tage)).replace(
            microsecond=0).astimezone().isoformat()
        with self.conn() as c:
            r = c.execute(
                "SELECT 1 FROM intel_auftraege WHERE art=?"
                " AND COALESCE(bezug_symbol,'')=COALESCE(?,'')"
                " AND COALESCE(bezug_schluessel,'')=COALESCE(?,'')"
                " AND zeit>? LIMIT 1",
                (art, bezug_symbol, bezug_schluessel, grenze),
            ).fetchone()
        return r is not None

    def intel_status_setzen(self, kennung: str, status: str, ergebnis: str) -> int:
        with self.conn() as c:
            cur = c.execute("UPDATE intel_auftraege SET status=?, ergebnis=?, aktualisiert=? WHERE kennung=?",
                            (status, ergebnis, jetzt(), kennung))
            return int(cur.rowcount or 0)

    def intel_weiterleitung_zaehler(self, tag: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM intel_weiterleitungen WHERE kennung LIKE ?",
                          (f"WL-{tag}-%",)).fetchone()
        return int(r["n"])

    def intel_weiterleitung_status_setzen(self, an: str, von: str, zu: str) -> int:
        with self.conn() as c:
            cur = c.execute("UPDATE intel_weiterleitungen SET status=? WHERE an=? AND status=?",
                            (zu, an, von))
            return int(cur.rowcount or 0)

    def intel_weiterleitung_aendern(self, kennung: str, abteilung: str, status: str) -> int:
        with self.conn() as c:
            cur = c.execute("UPDATE intel_weiterleitungen SET an=?, status=? WHERE kennung=?",
                            (abteilung, status, kennung))
            return int(cur.rowcount or 0)

    def intel_weiterleitung_speichern(self, kennung: str, von: str, an: str,
                                      betreff: str, bezug: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_weiterleitungen(kennung,zeit,von,an,betreff,bezug,status)"
                " VALUES (?,?,?,?,?,?,'neu')",
                (kennung, jetzt(), von, an, betreff,
                 json.dumps(bezug, ensure_ascii=False)),
            )

    def intel_weiterleitungen(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM intel_weiterleitungen ORDER BY id DESC LIMIT ?", (limit,)))

    def intel_quelle_pflegen(self, quelle: str, artikel: int = 0, analysiert: int = 0,
                             qualitaet: float = 0.0, bestaetigt: int = 0,
                             widerlegt: int = 0) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_quellen(quelle,artikel,analysiert,qualitaet_summe,"
                "bestaetigt,widerlegt,zuletzt) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(quelle) DO UPDATE SET"
                " artikel=artikel+excluded.artikel,"
                " analysiert=analysiert+excluded.analysiert,"
                " qualitaet_summe=qualitaet_summe+excluded.qualitaet_summe,"
                " bestaetigt=bestaetigt+excluded.bestaetigt,"
                " widerlegt=widerlegt+excluded.widerlegt,"
                " zuletzt=excluded.zuletzt",
                (quelle, artikel, analysiert, float(qualitaet), bestaetigt, widerlegt, jetzt()),
            )

    def intel_quelle_aus_artikeln(self) -> list[dict[str, Any]]:
        """Absolute Kennzahlen je Quelle aus allen Artikeln — idempotent, ohne Doppelzählung."""
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT a.quelle AS quelle, COUNT(*) AS artikel,"
                " SUM(CASE WHEN i.artikel_id IS NOT NULL THEN 1 ELSE 0 END) AS analysiert,"
                " SUM(a.qualitaet) AS qualitaet_summe"
                " FROM artikel a LEFT JOIN intel_inhalte i ON i.artikel_id = a.id"
                " GROUP BY a.quelle"
            ).fetchall()
        return [dict(r) for r in zeilen]

    def intel_quelle_abgleichen(self, quelle: str, artikel: int, analysiert: int,
                                qualitaet_summe: float) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_quellen(quelle,artikel,analysiert,qualitaet_summe,"
                "bestaetigt,widerlegt,zuletzt) VALUES (?,?,?,?,0,0,?)"
                " ON CONFLICT(quelle) DO UPDATE SET artikel=excluded.artikel,"
                " analysiert=excluded.analysiert,"
                " qualitaet_summe=excluded.qualitaet_summe,"
                " zuletzt=excluded.zuletzt",
                (quelle, artikel, analysiert, float(qualitaet_summe), jetzt()),
            )

    def artikel_quelle(self, url: str) -> str | None:
        with self.conn() as c:
            r = c.execute("SELECT quelle FROM artikel WHERE url=? LIMIT 1", (url,)).fetchone()
        return r["quelle"] if r else None

    def intel_quellen(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT quelle, artikel, analysiert, bestaetigt, widerlegt,"
                " CASE WHEN artikel>0 THEN ROUND(qualitaet_summe/artikel,2) ELSE 0 END AS qualitaet,"
                " zuletzt FROM intel_quellen ORDER BY artikel DESC, quelle"
            ).fetchall()
        return [dict(r) for r in zeilen]

    def intel_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            auftraege = c.execute("SELECT COUNT(*) n FROM intel_auftraege").fetchone()["n"]
            nach_status = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) n FROM intel_auftraege GROUP BY status")}
            weiter = c.execute("SELECT COUNT(*) n FROM intel_weiterleitungen").fetchone()["n"]
            offen = c.execute(
                "SELECT COUNT(*) n FROM intel_weiterleitungen WHERE status='neu'").fetchone()["n"]
            analysiert = c.execute("SELECT COUNT(*) n FROM intel_inhalte").fetchone()["n"]
            quellen = c.execute("SELECT COUNT(*) n FROM intel_quellen").fetchone()["n"]
        return {"auftraege": auftraege, "nach_status": nach_status,
                "weiterleitungen": weiter, "weiterleitungen_offen": offen,
                "analysiert": analysiert, "quellen": quellen}

    def validierung_nach(self, symbol: str, schluessel: str, seit: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM validierungen WHERE symbol=? AND schluessel=? AND erstellt>?"
                " ORDER BY id ASC LIMIT 1",
                (symbol, schluessel or "", seit),
            ).fetchone()

    # ---------- Konferenz ----------
    def konferenz_speichern(self, protokoll: dict[str, Any]) -> int:
        with self.conn() as c:
            cur = c.execute("INSERT INTO konferenzen(zeit,protokoll) VALUES (?,?)",
                            (jetzt(), json.dumps(protokoll, ensure_ascii=False)))
            return int(cur.lastrowid or 0)

    def letzte_konferenz(self) -> dict[str, Any] | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM konferenzen ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return None
        return {"zeit": r["zeit"], "protokoll": json.loads(r["protokoll"])}

    # ---------- Zustand ----------
    def zustand_setzen(self, schluessel: str, wert: Any) -> None:
        with self.conn() as c:
            c.execute("INSERT OR REPLACE INTO zustand(schluessel,wert) VALUES (?,?)",
                      (schluessel, json.dumps(wert, ensure_ascii=False)))

    def zustand(self, schluessel: str, standard: Any = None) -> Any:
        with self.conn() as c:
            r = c.execute("SELECT wert FROM zustand WHERE schluessel=?", (schluessel,)).fetchone()
        return json.loads(r["wert"]) if r else standard

    def zustand_loeschen(self, schluessel: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM zustand WHERE schluessel=?", (schluessel,))
