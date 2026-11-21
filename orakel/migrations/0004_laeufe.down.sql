-- Downgrade zu 0004_laeufe.sql.
-- ACHTUNG: entfernt die Warteschlange samt ihrer Auftraege.
DROP INDEX IF EXISTS idx_laeufe_status;
DROP TABLE IF EXISTS laeufe;
