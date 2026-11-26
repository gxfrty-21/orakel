-- Rücknahme von 0006: Das Prüfsummen-Register verschwindet wieder.
DROP INDEX IF EXISTS ix_datenimporte_zeit;
DROP INDEX IF EXISTS ux_datenimporte_quelle;
DROP TABLE IF EXISTS datenimporte;