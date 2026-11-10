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

-- Phase 8: protokollierter Dauerbetrieb. Jeder Job-Lauf wird mit Dauer,
-- Status und kompakten Details gespeichert; das ist die auswertbare Logquelle.
CREATE TABLE IF NOT EXISTS betrieb_laeufe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeit TEXT NOT NULL,
    job TEXT NOT NULL,
    status TEXT NOT NULL,
    dauer_ms INTEGER NOT NULL DEFAULT 0,
    fehler TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_betrieb_laeufe_zeit ON betrieb_laeufe(zeit);
CREATE INDEX IF NOT EXISTS ix_betrieb_laeufe_job ON betrieb_laeufe(job, status);

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

-- Nexus Phase 3: Quellenreputation als nachvollziehbarer Snapshot.
-- Die Zähler stammen aus echten Auftrags-Ergebnissen (intel_quellen), die
-- Reputation ist daraus plus Registergewicht berechnet, nie erfunden.
CREATE TABLE IF NOT EXISTS nexus_quellen_reputation (
    quelle_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    gewicht REAL NOT NULL DEFAULT 0.5,
    artikel INTEGER NOT NULL DEFAULT 0,
    analysiert INTEGER NOT NULL DEFAULT 0,
    bestaetigt INTEGER NOT NULL DEFAULT 0,
    widerlegt INTEGER NOT NULL DEFAULT 0,
    widersprueche INTEGER NOT NULL DEFAULT 0,
    reputation REAL NOT NULL DEFAULT 0.5,
    vertrauen TEXT NOT NULL DEFAULT 'vorläufig',
    aktualisiert TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nexus_rep_host ON nexus_quellen_reputation(host);

-- Nexus Phase 3: eine Kernthese je normalisiertem Aussage-Muster.
CREATE TABLE IF NOT EXISTS nexus_claims (
    id INTEGER PRIMARY KEY,
    claim_key TEXT NOT NULL UNIQUE,
    kernaussage TEXT NOT NULL,
    thema TEXT NOT NULL,
    subjekt TEXT NOT NULL,
    metrik TEXT NOT NULL DEFAULT '',
    quellen INTEGER NOT NULL DEFAULT 0,
    belege INTEGER NOT NULL DEFAULT 0,
    widersprueche INTEGER NOT NULL DEFAULT 0,
    bestaetigungsgrad REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'unbestätigt',
    erstmals TEXT NOT NULL,
    aktualisiert TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nexus_claim_status ON nexus_claims(status);
CREATE INDEX IF NOT EXISTS ix_nexus_claim_grad ON nexus_claims(bestaetigungsgrad);

-- Jede Meldung, die zu einer Kernthese gehört. Kopien sind Belege, aber keine
-- unabhängigen Quellen; die Bewertung zählt sie deshalb nicht als Bestätigung.
CREATE TABLE IF NOT EXISTS nexus_claim_quellen (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL,
    meldung_key TEXT NOT NULL,
    artikel_id INTEGER NOT NULL,
    quelle_id TEXT NOT NULL,
    host TEXT NOT NULL,
    aussage TEXT NOT NULL,
    richtung TEXT NOT NULL,
    wert REAL,
    einheit TEXT NOT NULL DEFAULT '',
    negiert INTEGER NOT NULL DEFAULT 0,
    ist_kopie INTEGER NOT NULL DEFAULT 0,
    reputation REAL NOT NULL DEFAULT 0.5,
    erstellt TEXT NOT NULL,
    UNIQUE(claim_id, meldung_key)
);
CREATE INDEX IF NOT EXISTS ix_nexus_claimq_claim ON nexus_claim_quellen(claim_id);
CREATE INDEX IF NOT EXISTS ix_nexus_claimq_host ON nexus_claim_quellen(host);

-- Erkannte Widersprüche bleiben als Paar sichtbar, inklusive Grund und
-- Sicherheit. Kein Widerspruch wird stillschweigend zu einer Wahrheit.
CREATE TABLE IF NOT EXISTS nexus_widersprueche (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL,
    meldung_a TEXT NOT NULL,
    meldung_b TEXT NOT NULL,
    quelle_a TEXT NOT NULL,
    quelle_b TEXT NOT NULL,
    grund TEXT NOT NULL,
    sicherheit REAL NOT NULL,
    erstellt TEXT NOT NULL,
    UNIQUE(claim_id, meldung_a, meldung_b)
);
CREATE INDEX IF NOT EXISTS ix_nexus_wid_claim ON nexus_widersprueche(claim_id);

-- Nexus Phase 4: Missionen und persistente Aufgabequeue.
-- Eine Mission ist eine echte Arbeitskette, keine Demo: Der Worker leitet
-- Kernaussagen ab, prüft Belege und schreibt einen nachvollziehbaren Bericht.
CREATE TABLE IF NOT EXISTS nexus_missionen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kennung TEXT NOT NULL UNIQUE,
    titel TEXT NOT NULL,
    auftrag TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    prioritaet TEXT NOT NULL DEFAULT 'mittel',
    fortschritt INTEGER NOT NULL DEFAULT 0,
    erstellt TEXT NOT NULL,
    gestartet TEXT,
    beendet TEXT,
    bericht TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_nexus_mission_status ON nexus_missionen(status);
CREATE INDEX IF NOT EXISTS ix_nexus_mission_erstellt ON nexus_missionen(erstellt);

-- status: offen | laufend | erledigt | fehlgeschlagen | blockiert
CREATE TABLE IF NOT EXISTS nexus_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    position INTEGER NOT NULL,
    rolle TEXT NOT NULL,
    ziel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    versuche INTEGER NOT NULL DEFAULT 0,
    max_versuche INTEGER NOT NULL DEFAULT 3,
    lease_bis TEXT,
    faellig_am TEXT NOT NULL,
    ergebnis TEXT NOT NULL DEFAULT '',
    fehler TEXT NOT NULL DEFAULT '',
    abhaengig_von INTEGER,
    erstellt TEXT NOT NULL,
    aktualisiert TEXT NOT NULL,
    UNIQUE(mission_id, position),
    FOREIGN KEY(mission_id) REFERENCES nexus_missionen(id)
);
CREATE INDEX IF NOT EXISTS ix_nexus_task_mission ON nexus_tasks(mission_id, position);
CREATE INDEX IF NOT EXISTS ix_nexus_task_queue ON nexus_tasks(status, faellig_am, lease_bis);

-- Nexus Phase 6: persistierter Wissensgraph.
-- Knoten werden aus Claims, Quellen und Themen abgeleitet; die Kanten
-- stehen als nachvollziehbare Beziehungen dauerhaft in SQLite.
CREATE TABLE IF NOT EXISTS nexus_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    von TEXT NOT NULL,
    nach TEXT NOT NULL,
    art TEXT NOT NULL,
    begruendung TEXT NOT NULL DEFAULT '',
    sicherheit REAL NOT NULL DEFAULT 0.5,
    erstellt TEXT NOT NULL,
    UNIQUE(von, nach, art)
);
CREATE INDEX IF NOT EXISTS ix_nexus_edge_von ON nexus_edges(von);
CREATE INDEX IF NOT EXISTS ix_nexus_edge_nach ON nexus_edges(nach);
CREATE INDEX IF NOT EXISTS ix_nexus_edge_art ON nexus_edges(art);
CREATE INDEX IF NOT EXISTS ix_nexus_edge_erstellt ON nexus_edges(erstellt);

-- Nexus Phase 6: Prognoseregister und echte Prüfergebnisse.
-- Die Konfidenz ist die Wahrscheinlichkeit, mit der die Erwartung eintritt.
-- Automatisch aus Intel-Aufträgen importierte Prognosen tragen bewusst 0,5,
-- weil dort keine Modellwahrscheinlichkeit gespeichert ist.
CREATE TABLE IF NOT EXISTS nexus_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kennung TEXT NOT NULL UNIQUE,
    auftrag_id INTEGER UNIQUE,
    mission_kennung TEXT,
    claim_id INTEGER,
    aussage TEXT NOT NULL,
    erwartung TEXT NOT NULL,
    zeithorizont TEXT NOT NULL,
    faellig_am TEXT NOT NULL,
    konfidenz REAL NOT NULL DEFAULT 0.5,
    symbol TEXT NOT NULL DEFAULT '',
    basiswert REAL,
    toleranz_pct REAL NOT NULL DEFAULT 0.1,
    status TEXT NOT NULL DEFAULT 'offen',
    erstellt TEXT NOT NULL,
    aktualisiert TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nexus_forecast_status ON nexus_forecasts(status);
CREATE INDEX IF NOT EXISTS ix_nexus_forecast_faellig ON nexus_forecasts(faellig_am);

CREATE TABLE IF NOT EXISTS nexus_forecast_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    forecast_id INTEGER NOT NULL UNIQUE,
    eingetreten INTEGER,
    messwert REAL,
    geprueft_am TEXT NOT NULL,
    notiz TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(forecast_id) REFERENCES nexus_forecasts(id)
);

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


def _json_wert(text: str, standard: Any = None) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return standard


def _forecast_aus_zeile(zeile: sqlite3.Row) -> dict[str, Any]:
    """Trennt Prognose und Prüfergebnis für die API, ohne Werte zu erfinden."""
    daten = dict(zeile)
    result_id = daten.pop("result_id", None)
    ergebnis = None
    if result_id is not None:
        ergebnis = {
            "id": int(result_id),
            "eingetreten": (None if daten.get("result_eingetreten") is None
                            else int(daten["result_eingetreten"])),
            "messwert": daten.get("result_messwert"),
            "geprueft_am": daten.get("result_geprueft_am"),
            "notiz": daten.get("result_notiz") or "",
        }
    for schluessel in list(daten):
        if schluessel.startswith("result_"):
            daten.pop(schluessel)
    daten["ergebnis"] = ergebnis
    return daten


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

    def nexus_meldungen_alle(self) -> list[sqlite3.Row]:
        """Alle Meldungen für den deterministischen Bewertungs-Rebuild."""
        with self.conn() as c:
            return list(c.execute("SELECT * FROM nexus_meldungen ORDER BY id"))

    # ---------- Nexus Phase 3: Quellenreputation, Claims, Widersprüche ----------
    def nexus_bewertung_ersetzen(
        self,
        quellen: Sequence[dict[str, Any]],
        claims: Sequence[dict[str, Any]],
        claim_quellen: Sequence[dict[str, Any]],
        widersprueche: Sequence[dict[str, Any]],
    ) -> None:
        """Ersetzt den Bewertungsstand atomar. Kein halber Rebuild bleibt sichtbar."""
        with self.conn() as c:
            for tabelle in ("nexus_claim_quellen", "nexus_widersprueche",
                            "nexus_claims", "nexus_quellen_reputation"):
                c.execute(f"DELETE FROM {tabelle}")
            if quellen:
                c.executemany(
                    "INSERT INTO nexus_quellen_reputation(quelle_id,name,host,gewicht,"
                    "artikel,analysiert,bestaetigt,widerlegt,widersprueche,reputation,"
                    "vertrauen,aktualisiert) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[k] for k in (
                        "quelle_id", "name", "host", "gewicht", "artikel",
                        "analysiert", "bestaetigt", "widerlegt", "widersprueche",
                        "reputation", "vertrauen", "aktualisiert")) for r in quellen],
                )
            if claims:
                c.executemany(
                    "INSERT INTO nexus_claims(id,claim_key,kernaussage,thema,subjekt,"
                    "metrik,quellen,belege,widersprueche,bestaetigungsgrad,status,"
                    "erstmals,aktualisiert) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[k] for k in (
                        "id", "claim_key", "kernaussage", "thema", "subjekt",
                        "metrik", "quellen", "belege", "widersprueche",
                        "bestaetigungsgrad", "status", "erstmals",
                        "aktualisiert")) for r in claims],
                )
            if claim_quellen:
                c.executemany(
                    "INSERT INTO nexus_claim_quellen(id,claim_id,meldung_key,artikel_id,"
                    "quelle_id,host,aussage,richtung,wert,einheit,negiert,ist_kopie,"
                    "reputation,erstellt) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[k] for k in (
                        "id", "claim_id", "meldung_key", "artikel_id", "quelle_id",
                        "host", "aussage", "richtung", "wert", "einheit",
                        "negiert", "ist_kopie", "reputation", "erstellt"))
                     for r in claim_quellen],
                )
            if widersprueche:
                c.executemany(
                    "INSERT INTO nexus_widersprueche(id,claim_id,meldung_a,meldung_b,"
                    "quelle_a,quelle_b,grund,sicherheit,erstellt) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    [tuple(r[k] for k in (
                        "id", "claim_id", "meldung_a", "meldung_b", "quelle_a",
                        "quelle_b", "grund", "sicherheit", "erstellt"))
                     for r in widersprueche],
                )

    def nexus_quellen_reputation(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM nexus_quellen_reputation "
                "ORDER BY reputation DESC, artikel DESC, name"
            )]

    def nexus_claims(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        with self.conn() as c:
            if status:
                zeilen = c.execute(
                    "SELECT * FROM nexus_claims WHERE status=? "
                    "ORDER BY bestaetigungsgrad DESC, quellen DESC, id DESC LIMIT ?",
                    (status, int(limit)),
                )
            else:
                zeilen = c.execute(
                    "SELECT * FROM nexus_claims "
                    "ORDER BY bestaetigungsgrad DESC, quellen DESC, id DESC LIMIT ?",
                    (int(limit),),
                )
            return [dict(r) for r in zeilen]

    def nexus_widersprueche(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT w.*, c.claim_key, c.kernaussage, c.status AS claim_status "
                "FROM nexus_widersprueche w JOIN nexus_claims c ON c.id=w.claim_id "
                "ORDER BY w.sicherheit DESC, w.id DESC LIMIT ?",
                (int(limit),),
            )
            return [dict(r) for r in zeilen]

    def nexus_claim_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = int(c.execute("SELECT COUNT(*) n FROM nexus_claims").fetchone()["n"])
            nach_status = {r["status"]: int(r["n"]) for r in c.execute(
                "SELECT status, COUNT(*) n FROM nexus_claims GROUP BY status")}
            belege = int(c.execute(
                "SELECT COALESCE(SUM(belege),0) n FROM nexus_claims").fetchone()["n"])
            widersprueche = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_widersprueche").fetchone()["n"])
            quellen = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_quellen_reputation").fetchone()["n"])
            grad = c.execute(
                "SELECT COALESCE(AVG(bestaetigungsgrad),0) w FROM nexus_claims").fetchone()["w"]
        return {
            "gesamt": gesamt,
            "nach_status": nach_status,
            "belege": belege,
            "widersprueche": widersprueche,
            "quellen": quellen,
            "bestaetigungsgrad": round(float(grad or 0.0), 3),
        }

    # ---------- Nexus Phase 4: Missionen, Queue und Retry ----------
    def nexus_mission_zaehler(self, tag: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM nexus_missionen WHERE kennung LIKE ?",
                          (f"MS-{tag}-%",)).fetchone()
        return int(r["n"])

    def nexus_mission_kennung_existiert(self, kennung: str) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM nexus_missionen WHERE kennung=? LIMIT 1",
                             (kennung,)).fetchone() is not None

    def nexus_mission_anlegen(
        self, kennung: str, titel: str, auftrag: str, prioritaet: str,
        tasks: Sequence[dict[str, Any]], erstellt: str,
    ) -> dict[str, Any]:
        """Legt Mission und Aufgabenkette in einer Transaktion an."""
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO nexus_missionen(kennung,titel,auftrag,status,prioritaet,"
                "fortschritt,erstellt,bericht) VALUES (?,?,?,'offen',?,0,?,'')",
                (kennung, titel, auftrag, prioritaet, erstellt),
            )
            mission_id = int(cur.lastrowid or 0)
            vorgaenger: int | None = None
            for position, aufgabe in enumerate(tasks):
                cur = c.execute(
                    "INSERT INTO nexus_tasks(mission_id,position,rolle,ziel,status,"
                    "versuche,max_versuche,lease_bis,faellig_am,ergebnis,fehler,"
                    "abhaengig_von,erstellt,aktualisiert) "
                    "VALUES (?,?,?,?,'offen',0,?,NULL,?,'','',?,?,?)",
                    (mission_id, position, str(aufgabe["rolle"]), str(aufgabe["ziel"]),
                     int(aufgabe.get("max_versuche", 3)), erstellt,
                     vorgaenger, erstellt, erstellt),
                )
                vorgaenger = int(cur.lastrowid or 0)
        return self.nexus_mission(kennung) or {}

    def nexus_mission(self, kennung: str) -> dict[str, Any] | None:
        with self.conn() as c:
            zeile = c.execute("SELECT * FROM nexus_missionen WHERE kennung=?",
                              (kennung,)).fetchone()
            if not zeile:
                return None
            tasks = [dict(r) for r in c.execute(
                "SELECT * FROM nexus_tasks WHERE mission_id=? ORDER BY position, id",
                (int(zeile["id"]),),
            )]
        mission = dict(zeile)
        mission["bericht"] = _json_wert(mission.get("bericht") or "", {}) or {}
        for task in tasks:
            task["ergebnis"] = _json_wert(task.get("ergebnis") or "", {}) or {}
        mission["tasks"] = tasks
        return mission

    def nexus_missionen(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT m.*, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id) AS tasks, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id AND t.status='erledigt') AS erledigt, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id AND t.status='offen') AS offen, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id AND t.status='fehlgeschlagen') AS fehlgeschlagen "
                "FROM nexus_missionen m "
                "ORDER BY CASE m.status WHEN 'laufend' THEN 0 WHEN 'offen' THEN 1 "
                "WHEN 'fehlgeschlagen' THEN 2 ELSE 3 END, m.erstellt DESC, m.id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        ergebnis = []
        for zeile in zeilen:
            eintrag = dict(zeile)
            eintrag["bericht_vorhanden"] = bool(eintrag.pop("bericht", ""))
            ergebnis.append(eintrag)
        return ergebnis

    def nexus_mission_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = int(c.execute("SELECT COUNT(*) n FROM nexus_missionen").fetchone()["n"])
            nach_status = {r["status"]: int(r["n"]) for r in c.execute(
                "SELECT status, COUNT(*) n FROM nexus_missionen GROUP BY status")}
            tasks = {r["status"]: int(r["n"]) for r in c.execute(
                "SELECT status, COUNT(*) n FROM nexus_tasks GROUP BY status")}
            fortschritt = c.execute(
                "SELECT COALESCE(AVG(fortschritt),0) w FROM nexus_missionen").fetchone()["w"]
        return {"gesamt": gesamt, "nach_status": nach_status,
                "tasks": tasks, "fortschritt": round(float(fortschritt or 0.0), 1)}

    def nexus_task(self, task_id: int) -> dict[str, Any] | None:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung, m.titel, m.auftrag, m.prioritaet "
                "FROM nexus_tasks t JOIN nexus_missionen m ON m.id=t.mission_id WHERE t.id=?",
                (int(task_id),),
            ).fetchone()
        if not zeile:
            return None
        task = dict(zeile)
        task["ergebnis"] = _json_wert(task.get("ergebnis") or "", {}) or {}
        return task

    def nexus_task_naechste(self, jetzt: str, lease_bis: str,
                            mission_kennung: str | None = None) -> dict[str, Any] | None:
        """Least eine fällige Aufgabe atomar. Abhängigkeiten werden geprüft."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            bedingung = " AND m.kennung=?" if mission_kennung else ""
            args: list[Any] = [jetzt]
            if mission_kennung:
                args.append(mission_kennung)
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung, m.titel, m.auftrag, "
                "m.prioritaet, m.status AS mission_status "
                "FROM nexus_tasks t JOIN nexus_missionen m ON m.id=t.mission_id "
                "WHERE t.status='offen' AND t.faellig_am<=? "
                "AND m.status IN ('offen','laufend') "
                "AND (t.abhaengig_von IS NULL OR EXISTS ("
                "  SELECT 1 FROM nexus_tasks v WHERE v.id=t.abhaengig_von AND v.status='erledigt'"
                ")) " + bedingung + " "
                "ORDER BY CASE m.prioritaet WHEN 'kritisch' THEN 0 WHEN 'hoch' THEN 1 "
                "WHEN 'mittel' THEN 2 ELSE 3 END, m.erstellt, t.position, t.id LIMIT 1",
                tuple(args),
            ).fetchone()
            if not zeile:
                return None
            c.execute(
                "UPDATE nexus_tasks SET status='laufend', versuche=versuche+1, "
                "lease_bis=?, aktualisiert=? WHERE id=?",
                (lease_bis, jetzt, int(zeile["id"])),
            )
            c.execute(
                "UPDATE nexus_missionen SET status='laufend', "
                "gestartet=COALESCE(gestartet, ?) WHERE id=?",
                (jetzt, int(zeile["mission_id"])),
            )
            task = dict(zeile)
            task["status"] = "laufend"
            task["versuche"] = int(zeile["versuche"]) + 1
            task["lease_bis"] = lease_bis
            return task

    def _mission_fehlerhaft(self, c: sqlite3.Connection, mission_id: int,
                             position: int, fehler: str, jetzt: str) -> None:
        """Blockiert Folgeschritte und markiert die Mission als abgebrochen."""
        c.execute(
            "UPDATE nexus_tasks SET status='blockiert', fehler=?, aktualisiert=? "
            "WHERE mission_id=? AND position>? AND status IN ('offen','laufend')",
            ("Vorgänger fehlgeschlagen", jetzt, int(mission_id), int(position)),
        )
        zahlen = c.execute(
            "SELECT COUNT(*) gesamt, "
            "SUM(CASE WHEN status='erledigt' THEN 1 ELSE 0 END) erledigt "
            "FROM nexus_tasks WHERE mission_id=?", (int(mission_id),),
        ).fetchone()
        gesamt = int(zahlen["gesamt"] or 0)
        erledigt = int(zahlen["erledigt"] or 0)
        fortschritt = round(erledigt / gesamt * 100) if gesamt else 0
        bericht = json.dumps({
            "fehler": fehler,
            "text": f"Mission abgebrochen: {fehler}",
            "generiert": jetzt,
        }, ensure_ascii=False)
        c.execute(
            "UPDATE nexus_missionen SET status='fehlgeschlagen', fortschritt=?, "
            "beendet=?, bericht=? WHERE id=?",
            (fortschritt, jetzt, bericht, int(mission_id)),
        )

    def nexus_task_leases_loesen(self, jetzt: str) -> int:
        """Gibt abgelaufene Leases frei; nach dem letzten Versuch: Dead-Letter."""
        freigegeben = 0
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung FROM nexus_tasks t "
                "JOIN nexus_missionen m ON m.id=t.mission_id "
                "WHERE t.status='laufend' AND t.lease_bis IS NOT NULL AND t.lease_bis<?",
                (jetzt,),
            ).fetchall()
            for zeile in zeilen:
                task = dict(zeile)
                endgueltig = int(task["versuche"]) >= int(task["max_versuche"])
                if endgueltig:
                    c.execute(
                        "UPDATE nexus_tasks SET status='fehlgeschlagen', lease_bis=NULL, "
                        "fehler=?, aktualisiert=? WHERE id=?",
                        ("Lease abgelaufen; letzter Versuch verbraucht", jetzt,
                         int(task["id"])),
                    )
                    self._mission_fehlerhaft(
                        c, int(task["mission_id"]), int(task["position"]),
                        "Lease abgelaufen; letzter Versuch verbraucht", jetzt,
                    )
                else:
                    c.execute(
                        "UPDATE nexus_tasks SET status='offen', lease_bis=NULL, "
                        "faellig_am=?, fehler=?, aktualisiert=? WHERE id=?",
                        (jetzt, "Lease abgelaufen; neuer Versuch", jetzt, int(task["id"])),
                    )
                    c.execute(
                        "UPDATE nexus_missionen SET status='offen' WHERE id=?",
                        (int(task["mission_id"]),),
                    )
                freigegeben += 1
        return freigegeben

    def nexus_task_erledigt(self, task_id: int, ergebnis: dict[str, Any],
                            bericht: dict[str, Any] | None, jetzt: str) -> dict[str, Any]:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung FROM nexus_tasks t "
                "JOIN nexus_missionen m ON m.id=t.mission_id WHERE t.id=?",
                (int(task_id),),
            ).fetchone()
            if not zeile:
                raise ValueError(f"Unbekannte Aufgabe: {task_id}")
            if zeile["status"] == "erledigt":
                kennung = str(zeile["mission_kennung"])
            else:
                c.execute(
                    "UPDATE nexus_tasks SET status='erledigt', lease_bis=NULL, "
                    "ergebnis=?, fehler='', aktualisiert=? WHERE id=?",
                    (json.dumps(ergebnis, ensure_ascii=False), jetzt, int(task_id)),
                )
                zahlen = c.execute(
                    "SELECT COUNT(*) gesamt, "
                    "SUM(CASE WHEN status='erledigt' THEN 1 ELSE 0 END) erledigt "
                    "FROM nexus_tasks WHERE mission_id=?", (int(zeile["mission_id"]),),
                ).fetchone()
                gesamt = int(zahlen["gesamt"] or 0)
                erledigt = int(zahlen["erledigt"] or 0)
                fortschritt = round(erledigt / gesamt * 100) if gesamt else 0
                kennung = str(zeile["mission_kennung"])
                if erledigt >= gesamt:
                    c.execute(
                        "UPDATE nexus_missionen SET status='abgeschlossen', fortschritt=100, "
                        "beendet=?, bericht=? WHERE id=?",
                        (jetzt, json.dumps(bericht or {}, ensure_ascii=False),
                         int(zeile["mission_id"])),
                    )
                else:
                    c.execute(
                        "UPDATE nexus_missionen SET status='offen', fortschritt=? WHERE id=?",
                        (fortschritt, int(zeile["mission_id"])),
                    )
        return self.nexus_mission(kennung) or {}

    def nexus_task_fehler(self, task_id: int, fehler: str, faellig_am: str,
                          endgueltig: bool, jetzt: str) -> dict[str, Any]:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung FROM nexus_tasks t "
                "JOIN nexus_missionen m ON m.id=t.mission_id WHERE t.id=?",
                (int(task_id),),
            ).fetchone()
            if not zeile:
                raise ValueError(f"Unbekannte Aufgabe: {task_id}")
            status = "fehlgeschlagen" if endgueltig else "offen"
            c.execute(
                "UPDATE nexus_tasks SET status=?, lease_bis=NULL, faellig_am=?, "
                "fehler=?, aktualisiert=? WHERE id=?",
                (status, faellig_am, fehler, jetzt, int(task_id)),
            )
            if endgueltig:
                self._mission_fehlerhaft(
                    c, int(zeile["mission_id"]), int(zeile["position"]),
                    fehler, jetzt,
                )
            else:
                c.execute("UPDATE nexus_missionen SET status='offen' WHERE id=?",
                          (int(zeile["mission_id"]),))
            kennung = str(zeile["mission_kennung"])
        return self.nexus_mission(kennung) or {}

    def nexus_claims_by_ids(self, ids: Sequence[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        platzhalter = ",".join("?" for _ in ids)
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT * FROM nexus_claims WHERE id IN ({platzhalter}) ORDER BY id",
                tuple(int(i) for i in ids),
            )]

    def nexus_claim_quellen_fuer(self, claim_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not claim_ids:
            return []
        platzhalter = ",".join("?" for _ in claim_ids)
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT * FROM nexus_claim_quellen WHERE claim_id IN ({platzhalter}) "
                "ORDER BY claim_id, id",
                tuple(int(i) for i in claim_ids),
            )]

    def nexus_widersprueche_fuer(self, claim_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not claim_ids:
            return []
        platzhalter = ",".join("?" for _ in claim_ids)
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT w.*, c.claim_key, c.kernaussage FROM nexus_widersprueche w "
                f"JOIN nexus_claims c ON c.id=w.claim_id WHERE w.claim_id IN ({platzhalter}) "
                "ORDER BY w.sicherheit DESC, w.id",
                tuple(int(i) for i in claim_ids),
            )]

    # ---------- Nexus Phase 6: Wissensgraph und Prognosen ----------
    def nexus_graph_ersetzen(self, kanten: Sequence[dict[str, Any]]) -> None:
        """Ersetzt den persistierten Graph atomar. Idempotenter Rebuild."""
        with self.conn() as c:
            c.execute("DELETE FROM nexus_edges")
            if kanten:
                c.executemany(
                    "INSERT INTO nexus_edges(von,nach,art,begruendung,sicherheit,erstellt)"
                    " VALUES (?,?,?,?,?,?)",
                    [(str(k["von"]), str(k["nach"]), str(k["art"]),
                      str(k.get("begruendung") or ""),
                      round(max(0.0, min(1.0, float(k.get("sicherheit", 0.5)))), 3),
                      str(k["erstellt"])) for k in kanten],
                )

    def nexus_graph_edges(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM nexus_edges ORDER BY erstellt, id"
            )]

    def nexus_forecast_zaehler(self, tag: str) -> int:
        with self.conn() as c:
            r = c.execute(
                "SELECT COUNT(*) n FROM nexus_forecasts WHERE kennung LIKE ?",
                (f"FC-{tag}-%",),
            ).fetchone()
        return int(r["n"])

    def nexus_forecast(self, kennung: str) -> dict[str, Any] | None:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT f.*, r.id AS result_id, r.eingetreten AS result_eingetreten,"
                " r.messwert AS result_messwert, r.geprueft_am AS result_geprueft_am,"
                " r.notiz AS result_notiz FROM nexus_forecasts f"
                " LEFT JOIN nexus_forecast_results r ON r.forecast_id=f.id"
                " WHERE f.kennung=?",
                (kennung,),
            ).fetchone()
        return _forecast_aus_zeile(zeile) if zeile else None

    def nexus_forecast_anlegen(self, daten: dict[str, Any]) -> dict[str, Any]:
        """Legt eine Prognose an oder aktualisiert dieselbe Kennung."""
        felder = (
            "kennung", "auftrag_id", "mission_kennung", "claim_id", "aussage",
            "erwartung", "zeithorizont", "faellig_am", "konfidenz", "symbol",
            "basiswert", "toleranz_pct", "status", "erstellt", "aktualisiert",
        )
        werte = tuple(daten.get(feld) for feld in felder)
        with self.conn() as c:
            c.execute(
                "INSERT INTO nexus_forecasts(kennung,auftrag_id,mission_kennung,claim_id,"
                "aussage,erwartung,zeithorizont,faellig_am,konfidenz,symbol,basiswert,"
                "toleranz_pct,status,erstellt,aktualisiert) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(kennung) DO UPDATE SET "
                "auftrag_id=excluded.auftrag_id, mission_kennung=excluded.mission_kennung,"
                "claim_id=excluded.claim_id, aussage=excluded.aussage,"
                "erwartung=excluded.erwartung, zeithorizont=excluded.zeithorizont,"
                "faellig_am=excluded.faellig_am, konfidenz=excluded.konfidenz,"
                "symbol=excluded.symbol, basiswert=excluded.basiswert,"
                "toleranz_pct=excluded.toleranz_pct, status=excluded.status,"
                "aktualisiert=excluded.aktualisiert",
                werte,
            )
        return self.nexus_forecast(str(daten["kennung"])) or {}

    def nexus_forecast_status_setzen(self, kennung: str, status: str,
                                     aktualisiert: str) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE nexus_forecasts SET status=?, aktualisiert=? WHERE kennung=?",
                (status, aktualisiert, kennung),
            )

    def nexus_forecast_result_speichern(
        self, forecast_id: int, eingetreten: int | None, messwert: float | None,
        geprueft_am: str, notiz: str = "",
    ) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO nexus_forecast_results(forecast_id,eingetreten,messwert,"
                "geprueft_am,notiz) VALUES (?,?,?,?,?) "
                "ON CONFLICT(forecast_id) DO UPDATE SET eingetreten=excluded.eingetreten,"
                "messwert=excluded.messwert, geprueft_am=excluded.geprueft_am,"
                "notiz=excluded.notiz",
                (int(forecast_id), None if eingetreten is None else int(eingetreten),
                 messwert, geprueft_am, notiz[:2000]),
            )

    def nexus_forecast_result_loeschen(self, forecast_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM nexus_forecast_results WHERE forecast_id=?",
                      (int(forecast_id),))

    def nexus_forecasts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT f.*, r.id AS result_id, r.eingetreten AS result_eingetreten,"
                " r.messwert AS result_messwert, r.geprueft_am AS result_geprueft_am,"
                " r.notiz AS result_notiz FROM nexus_forecasts f"
                " LEFT JOIN nexus_forecast_results r ON r.forecast_id=f.id"
                " ORDER BY COALESCE(f.faellig_am, f.erstellt) DESC, f.id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_forecast_aus_zeile(z) for z in zeilen]

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

    # ---------- Betrieb (Phase 8) ----------
    def betrieb_lauf_speichern(
        self, job: str, status: str, dauer_ms: int = 0,
        fehler: str = "", details: dict[str, Any] | None = None,
    ) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO betrieb_laeufe(zeit,job,status,dauer_ms,fehler,details)"
                " VALUES (?,?,?,?,?,?)",
                (jetzt(), str(job)[:80], str(status)[:30], max(0, int(dauer_ms)),
                 str(fehler or "")[:1000],
                 json.dumps(details or {}, ensure_ascii=False, sort_keys=True)[:8000]),
            )
            return int(cur.lastrowid or 0)

    def betrieb_laeufe(self, limit: int = 50) -> list[dict[str, Any]]:
        grenze = max(1, min(int(limit), 500))
        with self.conn() as c:
            zeilen = list(c.execute(
                "SELECT * FROM betrieb_laeufe ORDER BY id DESC LIMIT ?", (grenze,)
            ))
        raus: list[dict[str, Any]] = []
        for zeile in zeilen:
            eintrag = dict(zeile)
            eintrag["details"] = _json_wert(eintrag.get("details") or "{}", {})
            raus.append(eintrag)
        return raus

    def betrieb_laeufe_trim(self, max_laeufe: int = 1000) -> int:
        """Hält das Jobprotokoll beschränkt; Fachdaten werden nicht berührt."""
        grenze = max(100, int(max_laeufe))
        with self.conn() as c:
            cur = c.execute(
                "DELETE FROM betrieb_laeufe WHERE id NOT IN ("
                "SELECT id FROM betrieb_laeufe ORDER BY id DESC LIMIT ?)",
                (grenze,),
            )
            return int(cur.rowcount or 0)

    def betrieb_statistik(self, stunden: int = 24) -> dict[str, Any]:
        seit = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(stunden)))
                ).isoformat(timespec="seconds")
        with self.conn() as c:
            gesamt = int(c.execute(
                "SELECT COUNT(*) n FROM betrieb_laeufe WHERE zeit>=?", (seit,)
            ).fetchone()["n"])
            fehler = int(c.execute(
                "SELECT COUNT(*) n FROM betrieb_laeufe WHERE zeit>=? AND status='fehler'",
                (seit,),
            ).fetchone()["n"])
            uebersprungen = int(c.execute(
                "SELECT COUNT(*) n FROM betrieb_laeufe WHERE zeit>=? AND status='uebersprungen'",
                (seit,),
            ).fetchone()["n"])
        return {"stunden": int(stunden), "gesamt": gesamt, "fehler": fehler,
                "uebersprungen": uebersprungen}
