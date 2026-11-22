-- Margin-Buchung je Position.
-- Neue Positionen speichern die reservierte Margin (Nominal / max_leverage).
-- Bestandszeilen bleiben NULL: Sie wurden voll aus dem Bargeld bezahlt und
-- werden beim Lesen weiterhin mit ihrem vollen Einstiegswert gerechnet.

ALTER TABLE positionen ADD COLUMN margin REAL;
