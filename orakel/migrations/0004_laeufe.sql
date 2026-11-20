-- Orakel Lauf-Warteschlange, Migration 4.
-- Lange Engine-Laeufe laufen nicht mehr im Request-Thread: Der Endpunkt legt
-- nur einen Auftrag an, ein Hintergrund-Arbeiter arbeitet ihn ab.

CREATE TABLE IF NOT EXISTS laeufe (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'offen',
    modus TEXT NOT NULL DEFAULT 'backtest',
    spider INTEGER NOT NULL DEFAULT 0,
    erstellt TEXT NOT NULL,
    gestartet TEXT,
    beendet TEXT,
    ergebnis_json TEXT,
    fehler TEXT
);

CREATE INDEX IF NOT EXISTS idx_laeufe_status ON laeufe(status);
