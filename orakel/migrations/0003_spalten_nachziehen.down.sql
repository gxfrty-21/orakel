-- Downgrade zu 0003_spalten_nachziehen.sql.
-- ACHTUNG: entfernt die nachgezogenen Spalten samt ihrer Werte.
ALTER TABLE artikel DROP COLUMN prioritaet;
ALTER TABLE artikel DROP COLUMN prioritaet_grund;
ALTER TABLE artikel DROP COLUMN erkannt;
ALTER TABLE nexus_tasks DROP COLUMN abgeschlossen_am;
ALTER TABLE nexus_tasks DROP COLUMN fehlgeschlagen_am;
ALTER TABLE nexus_claims DROP COLUMN zeitraum;
ALTER TABLE nexus_claims DROP COLUMN bedingung;
ALTER TABLE nexus_claims DROP COLUMN sicherheit;
ALTER TABLE nexus_claim_quellen DROP COLUMN zeitraum;
ALTER TABLE nexus_claim_quellen DROP COLUMN bedingung;
ALTER TABLE nexus_claim_quellen DROP COLUMN sicherheit;
ALTER TABLE nexus_widersprueche DROP COLUMN wert_a_bp;
ALTER TABLE nexus_widersprueche DROP COLUMN wert_b_bp;
