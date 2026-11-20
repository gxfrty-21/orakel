-- Versuchszähler je Lauf-Auftrag, Migration 5.
-- Ein Lauf, der den Prozess abstürzen lässt, steht beim nächsten Start wieder
-- auf «aktiv» und wird erneut eingereiht. Ohne Grenze käme der Prozess aus der
-- Absturzschleife nicht heraus; nach MAX_VERSUCHE verbucht der Start den
-- Auftrag als Fehler.

ALTER TABLE laeufe ADD COLUMN versuche INTEGER NOT NULL DEFAULT 0;
