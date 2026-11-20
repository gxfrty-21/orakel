# Datenbankmigrationen

Das Schema der Fakten-Datenbank liegt nicht mehr als Python-String im Code,
sondern in nummerierten Dateien unter `orakel/migrations/`. Angewendet wird
ausschliesslich beim Start; die Historie steht in der Tabelle
`schema_migrationen`.

## Dateien

| Datei | Inhalt |
|---|---|
| `0001_basis.sql` | Grundschema: Kerzen, Artikel, Trades, Ereignisse, Nexus, Intel |
| `0002_company.sql` | Agenten, Aufgaben, Ereignisse, Sitzungen der Company-Schicht |
| `0003_spalten_nachziehen.sql` | Spalten, die ältere Datenbanken noch nicht haben |
| `NNNN_name.down.sql` | Rückweg einer Migration (Pflicht für jeden Downgrade) |

Eine Migration läuft genau einmal. Die Nummer muss vierstellig und eindeutig
sein; `migrationen.dateien()` bricht bei doppelten Nummern ab. Jede Datei wird
in einer eigenen Transaktion ausgeführt: Schlägt eine Anweisung fehl, wird die
komplette Datei zurückgerollt, und die Datenbank bleibt auf dem Stand davor.
`PRAGMA`-Zeilen in einer Datei werden übersprungen; WAL und `foreign_keys`
setzt der Aufrufer vor der Transaktion.

## Ablauf beim Start

`orakel/kern/db.initialisiere()` ruft einmal pro Prozess und Datenbankpfad
`migrationen.anwenden()` auf. Der Ablauf:

1. `schema_migrationen` anlegen (falls nötig) und den Stand lesen.
2. Eine Datenbank aus der Zeit vor dieser Tabelle wird normal durchmigriert:
   `0001` und `0002` legen nur an, was fehlt, und `0003` ergänzt fehlende
   Spalten. Bestehende Zeilen bleiben dabei erhalten.
3. Vor jedem Lauf, der auf einer bestehenden Datenbank tatsächlich etwas
   ändert, entsteht per SQLite-Online-Backup eine Sicherung
   `<db>.vor-migration-JJJJMMTT-HHMMSS.bak` neben der Datenbank.
4. Jede offene Migration wird ausgeführt und mit Nummer, Name und Zeitpunkt in
   `schema_migrationen` eingetragen. `PRAGMA user_version` spiegelt danach die
   höchste angewendete Nummer.

`ADD COLUMN` auf einer Spalte, die es schon gibt, wird bewusst übersprungen:
SQLite kennt kein `ADD COLUMN IF NOT EXISTS`, und auf einer frischen Datenbank
sind die Spalten aus `0003` bereits in `0001`/`0002` enthalten. Alle anderen
Fehler brechen ab und rollen zurück.

## Sehr alte Bestände

Reicht das Nachziehen nicht, weil eine Tabelle schon existiert, aber anders
aufgebaut ist, hilft kein weiteres `ALTER TABLE`: `CREATE TABLE IF NOT EXISTS`
lässt die vorhandene Tabelle unverändert, und ein `CREATE INDEX` auf eine
fehlende Spalte scheitert. `anwenden()` bricht dann mit `AltesSchemaFehler`
(einer Unterklasse von `MigrationsFehler`) ab und nennt Datei, Index, Tabelle
und Spalte — statt eines nackten `no such column`. Die Transaktion ist
zurückgerollt, die Datenbank bleibt unverändert, die Sicherung von Schritt 3
liegt daneben.

Beim Start prüft jeder Befehl, der die Datenbank anfasst (`serve`, `pruefen`,
`konferenz`, `unternehmen`, `daten`), das Schema vorab. Ein solcher Bestand
beendet den Prozess deshalb mit einer eigenen Meldung statt mit einem
Traceback aus dem Lifespan von uvicorn: je Punkt eine Zeile mit dem Präfix
`orakel:` — Fehler, zurückgerollter Stand, die vorhandene Sicherungsdatei und
der Verweis auf diesen Abschnitt. Der Prozess endet mit Exit-Code 2. Im
Container gilt das ohne Zusatz, weil `docker-entrypoint.sh` `python -m orakel …
serve` startet; der Seed-Schritt davor rührt ein vorhandenes Schema nicht an.
Eine eigene App-Instanz (`create_app(...)` direkt) prüft erst im Lifespan — also
beim ersten Request — und meldet den Fehler dort als Serverfehler.

Der Weg führt über Export und Import in ein frisches Schema:

```bash
# 1. Datei sichern (die Migration legt zusätzlich eine .bak an)
cp orakel.db orakel.db.vor-umbau

# 2. Daten exportieren (vollständiger, lesbarer SQL-Export)
sqlite3 orakel.db '.dump' > orakel-export.sql

# 3. Alte Datei weglegen und die Anwendung einmal starten;
#    sie legt das neue Schema vollständig an
mv orakel.db orakel.db.alt

# 4. Daten der Tabellen übernehmen, deren Spalten beide Stände teilen
```

Für Schritt 4 zählt man die gemeinsamen Spalten beider Stände aus
(`PRAGMA table_info`) und kopiert sie mit `ATTACH` und
`INSERT INTO neu.tabelle (spalten) SELECT spalten FROM alt.tabelle`. Spalten,
die es nur im neuen Schema gibt, bleiben auf ihrem Default; Zeilen ohne
Pflichtspalte werden nicht erfunden, sondern bleiben weg. Fehlt eine Tabelle
im Bestand, entsteht sie beim Start leer.

## Stand und Rückweg

```bash
# Stand anzeigen
.venv/bin/python -c "from orakel.kern import migrationen; print(migrationen.angewendet('orakel.db'))"

# Auf Stand 0002 zurückrollen (führt 0003_*.down.sql aus)
.venv/bin/python -c "from orakel.kern import migrationen; print(migrationen.zurueckrollen('orakel.db', bis=2))"
```

Der Rückweg löscht Daten der betroffenen Migrationen. Fehlt eine
`.down.sql`-Datei, bricht `zurueckrollen()` ab, **bevor** etwas geändert wird,
und nennt die Nummern. Vor dem ersten Rückrollschritt entsteht eine Sicherung.

## Tests

`tests/test_migrationen.py` deckt die drei geforderten Fälle und die
Betriebswege ab:

- leere Datenbank: alle Migrationen laufen, Historie ist vollständig,
- Teilststand auf 0003: nur die danach hinzugekommene Migration läuft, die
  Stände 0001 bis 0003 bleiben unangetastet,
- fehlerhafte Migration: Rollback, Tabelle aus der kaputten Datei fehlt,
  vorherige Migration und ihre Historie bleiben,
- uralter Bestand, dessen `artikel`-Tabelle die Spalte `titel_hash` nicht hat:
  `AltesSchemaFehler` mit Datei, Index, Tabelle, Spalte und Export/Import-Weg,
  Datenbank unverändert, Sicherung vorhanden,
- Sicherung vor der Migration enthält die vorhandenen Zeilen,
- Downgrade entfernt Eintrag und Spalten, ohne die früheren Migrationen
  anzufassen,
- Bestandsdatenbank ohne Historie wird durchmigriert: Zeilen bleiben,
  fehlende Spalten kommen hinzu, und vorher entsteht eine Sicherung.
