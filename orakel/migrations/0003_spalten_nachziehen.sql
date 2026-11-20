-- Orakel Nachziehen, Migration 3.
-- Ergänzt Spalten, die ältere Datenbanken noch nicht haben. Auf einer frischen
-- Datenbank sind sie bereits in 0001/0002 enthalten; der Lauf überspringt
-- vorhandene Spalten dann ausdrücklich (SQLite kennt kein ADD COLUMN IF NOT EXISTS).
-- Bestehende Zeilen bleiben unberührt; neue Spalten sind leer und werden in der
-- Oberfläche als «unbekannt» dargestellt, nie erfunden.

ALTER TABLE artikel ADD COLUMN prioritaet TEXT NOT NULL DEFAULT '';
ALTER TABLE artikel ADD COLUMN prioritaet_grund TEXT NOT NULL DEFAULT '';
ALTER TABLE artikel ADD COLUMN erkannt TEXT;

ALTER TABLE nexus_tasks ADD COLUMN abgeschlossen_am TEXT;
ALTER TABLE nexus_tasks ADD COLUMN fehlgeschlagen_am TEXT;

ALTER TABLE nexus_claims ADD COLUMN zeitraum TEXT NOT NULL DEFAULT '';
ALTER TABLE nexus_claims ADD COLUMN bedingung TEXT NOT NULL DEFAULT '';
ALTER TABLE nexus_claims ADD COLUMN sicherheit REAL NOT NULL DEFAULT 0.5;

ALTER TABLE nexus_claim_quellen ADD COLUMN zeitraum TEXT NOT NULL DEFAULT '';
ALTER TABLE nexus_claim_quellen ADD COLUMN bedingung TEXT NOT NULL DEFAULT '';
ALTER TABLE nexus_claim_quellen ADD COLUMN sicherheit REAL NOT NULL DEFAULT 0.5;

ALTER TABLE nexus_widersprueche ADD COLUMN wert_a_bp REAL;
ALTER TABLE nexus_widersprueche ADD COLUMN wert_b_bp REAL;
