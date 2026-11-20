-- Orakel Basis-Schema, Migration 1.
-- Alle Anweisungen sind idempotent (IF NOT EXISTS), damit ein Bestand
-- ohne Migrationshistorie sie gefahrlos erneut ausfuehren kann.

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
    titel_hash TEXT NOT NULL,
    prioritaet TEXT NOT NULL DEFAULT '',
    prioritaet_grund TEXT NOT NULL DEFAULT '',
    erkannt TEXT
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
    zeitraum TEXT NOT NULL DEFAULT '',
    bedingung TEXT NOT NULL DEFAULT '',
    sicherheit REAL NOT NULL DEFAULT 0.5,
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
    zeitraum TEXT NOT NULL DEFAULT '',
    bedingung TEXT NOT NULL DEFAULT '',
    sicherheit REAL NOT NULL DEFAULT 0.5,
    ist_kopie INTEGER NOT NULL DEFAULT 0,
    reputation REAL NOT NULL DEFAULT 0.5,
    erstellt TEXT NOT NULL,
    UNIQUE(claim_id, meldung_key)
);
CREATE INDEX IF NOT EXISTS ix_nexus_claimq_claim ON nexus_claim_quellen(claim_id);
CREATE INDEX IF NOT EXISTS ix_nexus_claimq_host ON nexus_claim_quellen(host);

-- Erkannte Widersprüche bleiben als Paar sichtbar, inklusive Grund,
-- Sicherheit und optionaler normierter Vergleichswerte in Basispunkten.
-- Kein Widerspruch wird stillschweigend zu einer Wahrheit.
CREATE TABLE IF NOT EXISTS nexus_widersprueche (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL,
    meldung_a TEXT NOT NULL,
    meldung_b TEXT NOT NULL,
    quelle_a TEXT NOT NULL,
    quelle_b TEXT NOT NULL,
    grund TEXT NOT NULL,
    sicherheit REAL NOT NULL,
    wert_a_bp REAL,
    wert_b_bp REAL,
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
    abgeschlossen_am TEXT,
    fehlgeschlagen_am TEXT,
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
