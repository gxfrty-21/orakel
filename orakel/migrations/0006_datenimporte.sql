-- Prüfsummen-Register für den lokalen CSV-Import, Migration 6.
-- Eine Datei wird nur einmal je Ziel (Symbol, Zeitrahmen, Zeitzone, Versatz)
-- importiert. Der SHA-256 bezieht sich auf die Rohdatei; so bleiben
-- Wiederholungen idempotent, ohne dass der Inhalt erneut gelesen werden muss.

CREATE TABLE IF NOT EXISTS datenimporte (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sha256 TEXT NOT NULL,
    datei TEXT NOT NULL,
    symbol TEXT NOT NULL,
    zeitrahmen TEXT NOT NULL,
    zeitzone TEXT NOT NULL DEFAULT '',
    versatz TEXT NOT NULL DEFAULT '',
    kerzen INTEGER NOT NULL,
    von TEXT NOT NULL,
    bis TEXT NOT NULL,
    importiert_am TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_datenimporte_quelle
    ON datenimporte(sha256, symbol, zeitrahmen, zeitzone, versatz);
CREATE INDEX IF NOT EXISTS ix_datenimporte_zeit
    ON datenimporte(importiert_am);