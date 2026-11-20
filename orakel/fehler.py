"""Fehler, die an Ablaufgrenzen abgefangen und gemeldet werden dürfen.

Ein blindes ``except Exception`` verschluckt auch Programmierfehler. An den
Grenzen, an denen eine defekte Quelle, ein Job, ein Handler oder eine Ansicht
den übrigen Lauf nicht abbrechen darf, werden deshalb nur die Fehler
abgefangen, die aus Daten, Datenbank, Dateisystem, Netz und fremden Abläufen
entstehen. Alles andere schlägt durch und bleibt sichtbar.
"""

from __future__ import annotations

import sqlite3

ABLAUF_FEHLER = (
    OSError,        # Dateisystem, Netz, Unterprozess
    sqlite3.Error,  # Datenbank, Migrationen, Sperren
    ValueError,     # Zahlen, JSON, Zeitstempel
    TypeError,      # unerwartete Datentypen aus Quellen und Zeilen
    KeyError,       # fehlende Felder in Berichten und Zeilen
    RuntimeError,   # abgebrochene Abläufe und Zustandsfehler
)
