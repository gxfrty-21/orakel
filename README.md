# Orakel Trading-Engine

[![CI: Tests](https://github.com/gxfrty-21/orakel/actions/workflows/tests.yml/badge.svg)](https://github.com/gxfrty-21/orakel/actions/workflows/tests.yml)

Paper-Trading-System mit Richter, Research, Paper-Takt und Web-Dashboard.
Grundlage ist dein Meister-Prompt (Abschnitte 1–12) und dein Orakel-Design.

**Dieses Projekt handelt ausschliesslich Paper.** Der Paper-Takt rechnet direkt
in SQLite; es gibt keinen Broker-Aufruf und keinen Codepfad zu einer echten
Broker-Order. `[paper] order_freigabe` bleibt als harte Policy-Sperre auf
`false`.

**Raumschiff-Doku:** [docs/raumschiff/README.md](docs/raumschiff/README.md)
— Planung und aktueller 2D-Agenten-Querschnitt (103 Räume, elf Abteilungen, Zoom/Pan, Detailspalte).

**Architektur:** [docs/ARCHITEKTUR-KERN.md](docs/ARCHITEKTUR-KERN.md)
— Grenze zwischen Handelskern (`orakel/kern/`) und Oberfläche, Prüfung in der
CI und Feature-Stopp für Agenten und Raumschiff.

## Schnellstart

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 1) Daten: synthetisch (Test der Abläufe) ...
.venv/bin/python -m orakel daten --kerzen 6000
# ... oder echte MT5-Historie importieren (mehrere Dateien und Blöcke erlaubt):
.venv/bin/python -m orakel daten --csv daten/EURUSD_M15_2020.csv daten/EURUSD_M15_2021.csv

# 2) Vollständiger Lauf: Daten → Research → Richter → Risiko → Plan → Bericht
.venv/bin/python -m orakel pruefen

# 3) Dashboard (Bericht live aus der Fakten-Datenbank)
.venv/bin/python -m orakel serve --port 8000

# 4) Company-Schicht (Phase 1): 103 Profile, Queue, Policy, Audit-Kette
.venv/bin/python -m orakel unternehmen --status
.venv/bin/python -m orakel unternehmen
```

### Lange Läufe

«Lauf starten» blockiert nicht mehr. `POST /api/lauf` legt nur einen Auftrag an
und antwortet sofort mit `202` und `{"id": …}`; der Hintergrund-Loop (der
Takt-Scheduler aus `orakel/scheduler.py`) führt ihn aus. `GET /api/lauf/{id}` liefert `status` (`offen`, `aktiv`, `fertig`,
`fehler`) sowie bei Erfolg die Zusammenfassung aus Dauer, Validierungen, Plan
und Fehlern. Das Dashboard fragt alle zwei Sekunden nach und lädt den Bericht
erst danach neu.

Solange ein Auftrag offen oder aktiv ist, legt ein weiteres `POST /api/lauf`
keinen zweiten an: Die Antwort ist `409` mit `{"id": …}` des laufenden Laufs
und seinem `status`. Mehrfaches Klicken reiht deshalb keine Backtests
hintereinander ein; das Dashboard hängt sich an die bestehende ID und wartet
auf deren Ergebnis. Erst nach `fertig` oder `fehler` startet ein neuer Klick
einen neuen Auftrag.

Bleibt ein Auftrag nach einem Absturz auf `aktiv` stehen, setzt ihn der
Hintergrund-Loop beim nächsten Start wieder auf `offen` (`zuruecksetzen` in
`orakel/lauf_queue.py`): Beim Start hält kein Prozess mehr einen Auftrag, der
Rest kann also gefahrlos erneut laufen. `gestartet` wird geleert, ein Ereignis
protokolliert jeden Reset; erst danach beginnt die Schleife. Ein Auftrag, der
einen Absturz auslöst, läuft beim nächsten Start deshalb erneut. Hängt ein
Auftrag dagegen im laufenden Betrieb länger als 60 Minuten (`HAENGE_GRENZE`),
verbucht ihn die Schleife als `fehler`; der Fehlertext nennt die Grenze.
Danach ist die Warteschlange in beiden Fällen wieder frei für einen neuen
Start.

Ein Auftrag, der den Prozess beim Laufen mitnimmt, würde sonst bei jedem Start
wieder laufen. Jeder Startversuch zählt (`versuche`, Migration
`0005_laeufe_versuche.sql`); nach drei Versuchen (`MAX_VERSUCHE`) verbucht der
Start ihn als `fehler` mit Hinweis auf die Absturzschleife. Unterhalb der
Grenze wird er wie bisher wieder auf `offen` gesetzt.

Abgeschlossene Aufträge (`fertig`, `fehler`) bleiben 30 Tage (`AUFBEWAHRUNG`)
und werden dann gelöscht; die Aufbewahrung läuft beim Start und im
Dauerbetrieb höchstens stündlich (`AUFBEWAHRUNG_TAKT`). Offene und laufende
Aufträge bleiben unberührt, ebenso Einträge ohne Endzeit. Die Frist hängt an
`beendet`, nicht an `erstellt` — ein langer Lauf behält seine Frist nach dem
Ende.

Die Company-Schicht ist additiv und standardmäßig **nicht** in den laufenden
Paper-Takt eingebunden (`[unternehmen] aktiv = false`). Sie enthält noch keine
3D-Welt, keine LLM-Anbindung und keine echten Orders.

### Company-API

Die Phase-2-Endpunkte liegen geschützt unter `/api/company`. Lese-Endpunkte
liefern ausschließlich Daten aus SQLite; Schreib-Endpunkte validieren jeden
Entwurf, protokollieren ihn in der Audit-Kette und starten keine Handler:

- `GET /api/company/overview` — Kennzahlen, Agentenstatus, Abteilungen, letzte
  Konferenz, offene Entscheidungen und die zehn wichtigsten offenen Aufgaben.
- `GET /api/company/agents` — alle 103 Profile mit Status, offenen Aufgaben und
  letzter Aufgabe.
- `GET /api/company/agents/{id}` — Profil, Historie, aktuelle Aufgabe,
  Nachrichten und persönliche Erinnerungen eines Agenten.
- `GET /api/company/tasks` — Aufgabenqueue; standardmäßig nur offene Aufgaben,
  filterbar mit `dept`, `state` (`offen`, `alle` oder ein Zustand), `mindestprioritaet`
  und `limit`.
- `GET /api/company/paper-guard` — aktueller Paper-only-Status mit Broker,
  Order-Freigabe und Policy-Entscheidung; rein lesend.
- `GET /api/company/messages` — Nachrichten und Threads, filterbar mit `agent`,
  `dept`, `thread_id`, `seit`, `nur_offen` und `limit`.
- `GET /api/company/messages/{id}` — eine Nachricht mit Belegen und Quittung.
- `POST /api/company/messages` — direkte, Abteilungs- oder Broadcast-Nachricht;
  Empfänger werden serverseitig geprüft, jede Nachricht erhält einen Thread.
- `POST /api/company/messages/{id}/ack` — Nachricht als ihr Empfänger quittieren.
- `GET /api/company/agents/{id}/memories` — persönliche Erinnerungen, optional
  nach `scope` gefiltert.
- `POST /api/company/agents/{id}/memories` — persönlichen Eintrag anlegen oder
  aktualisieren; Scope und Schlüssel werden validiert.
- `GET /api/company/rooms` — 2D-Raumregister mit Abteilungen,
  Gemeinschafts- und Agentenräumen sowie dynamischem Raumstatus.
- `GET /api/company/conference/latest` — letzte Konferenz mit Teilnahme,
  Beiträgen, Abstimmungen, Entscheidungen und Massnahmen.
- `GET /api/company/stream` — SSE-Snapshots für Übersicht, Aufgaben,
  Nachrichten und Konferenz (8-Sekunden-Takt).

Jede Antwort nennt `data_state` (`live`/`empty`), `generated_at` in UTC und
`source_refs`. Fehlende Daten bleiben leer; es gibt keine Ersatzzahlen. Die
Raumschiff-Ansicht liest Übersicht, Agentenstatus und offene Aufgaben aus diesen
Endpunkten und aktualisiert sie alle 30 Sekunden, solange sie geöffnet ist. In der
Agenten-Detailspalte stehen zusätzlich Nachrichten und persönliche Erinnerungen;
Nachrichten lassen sich dort senden, eingehende Nachrichten quittieren.

Nachrichten sind auf direkte Kontakte, Abteilungsziele (`dept:A`) und Broadcasts
(`all`, nur A1/S1–S3) begrenzt. Abteilungsziele dürfen Leitung und Sekretariat
setzen; ein Agent kann sich nicht selbst adressieren. Jede Nachricht und jede
Gedächtnisänderung erzeugt ein Audit-Event. Persönliche Erinnerungen sind über
`agent_id`, `scope` und `key` getrennt und werden als JSON gespeichert.

Broadcasts haben einen persistenten Cooldown und ein 24-Stunden-Limit pro
Absender (`broadcast_cooldown_sekunden`, Standard 900 s;
`broadcast_max_pro_tag`, Standard 10 in 24 h; beide in `company_policies`).
Eine Überschreitung liefert HTTP 429 mit `Retry-After`; direkte und
Abteilungsnachrichten bleiben davon unberührt. Offene Quittungen werden nach
`ack_erinnerung_nach_minuten` (Standard 30) automatisch im ursprünglichen
Thread erinnert (`ack_erinnerung_wiederholen_minuten`, Standard 120;
`ack_erinnerungen_max`, Standard 1). Erinnerungen sind selbst nicht
quittungspflichtig und werden über eigene
`message_reminder`-Audit-Events genau einmal gezählt. Sie laufen im Company-Lauf
und im Hintergrund-Takt; ein Lauf ohne offene Quittungen schreibt nichts.

### Fehlerantworten

Jede Fehlerantwort trägt `ok: false`, einen Text in `fehler` und einen stabilen
`code`. Eingabefehler (`eingabe`) nennen den Grund im Klartext, weil der Text
bewusst formuliert ist. Interne Fehler (`interner_fehler`) zeigen nur eine
Fehler-ID im Text; der vollständige Ausnahmetext – samt Pfaden, SQL oder
Konfigurationswerten – bleibt im Log und lässt sich über die ID dort
wiederfinden. Clients prüfen deshalb `code`, nicht den Text.

## Dauerbetrieb mit Login und HTTPS

Fertige Docker-Konfiguration mit Caddy (automatisches TLS), HTTP-Basic-Login und
persistentem SQLite-Speicher im `/data`-Volume (Standardpfad
`/data/orakel.db`, per `ORAKEL_DB_PFAD` überschreibbar): siehe
[DEPLOY.md](DEPLOY.md).

Der Container bindet `0.0.0.0`; `ORAKEL_AUTH_USER` und `ORAKEL_AUTH_PASS`
sind deshalb **Pflicht**. Fehlen sie, bricht der Containerstart mit
`orakel-entrypoint: FEHLER: ORAKEL_AUTH_USER und ORAKEL_AUTH_PASS muessen gesetzt sein.`
ab. Ohne Login läuft der Server ausschliesslich auf Loopback; ein externer
Bind wird auch bei einem Neustart mit der Altlast `ORAKEL_ALLOW_NO_AUTH=1`
abgelehnt. Der sichere lokale Startbefehl ist:

```bash
.venv/bin/python -m orakel serve --host 127.0.0.1 --port 8000
```

Für einen externen Start müssen `ORAKEL_AUTH_USER` und `ORAKEL_AUTH_PASS`
gesetzt sein, etwa über die ignorierte `.env`:

```bash
set -a; . ./.env; set +a
.venv/bin/python -m orakel serve --host 0.0.0.0 --port 8000
```

Für Railway ohne eigenen Server, Caddy oder eigene Domain: siehe
[RAILWAY.md](RAILWAY.md).

### Phase 8: Dauerbetrieb und Monitoring

Der Hintergrund-Takt ist bewusst **opt-in** (`serve --takt` oder
`ORAKEL_TAKT=1`). Er plant Paper-Takt, Konferenz, Spider (standardmäßig alle
sechs Stunden), Intelligence, Missionen und optional die Company-Schicht. Im
laufenden Takt werden zusätzlich offene Quittungen nach Frist erinnert
(`[unternehmen] erinnerungen_intervall_minuten`).

Takt und Lauf-Warteschlange teilen sich denselben Thread (`Takt` in
`orakel/scheduler.py`): Je Runde läuft erst der Betriebstakt, dann genau ein
Auftrag aus der Warteschlange. Ohne `--takt` läuft derselbe Loop im
Sekundentakt nur für die Warteschlange, damit ein gestarteter Lauf auch ohne
Dauerbetrieb abgearbeitet wird.
Fehler erhalten einen persistenten exponentiellen Backoff; DB-, RSS- und
Speichergrenzen pausieren schreibintensive Jobs, statt den Prozess volllaufen
zu lassen. Jeder Lauf wird in `betrieb_laeufe` protokolliert.

```bash
python -m orakel betrieb           # Plan, Backoff, Ressourcen, letzte Läufe
python -m orakel betrieb --json    # vollständige Monitoringdaten
```

Im Dashboard gibt es dafür den Punkt **Betrieb**; die geschützte API liegt
unter `GET /api/betrieb`. `/api/health` bleibt offen und nennt eine kompakte
Betriebszeile sowie die Schiffs-Kennzahlen (11 Cluster, 103 Agenten). Details
und ehrliche Grenzen:
[docs/spider/PHASE-8.md](docs/spider/PHASE-8.md).

### Backoff-Fehlerfall

Der separate deterministische Fehlerfall prüft zwei aufeinanderfolgende
Spider-Fehler: 60 s Backoff, 120 s nach dem zweiten Fehler, kein Lauf bei
+180 s und ein erfolgreicher Retry bei +182 s. Ablauf und Kriterien stehen im
[Backoff-Bericht der Soak-Abnahme](docs/spider/SOAK-ABNAHME.md#23-separater-backoff-fehlerfall);
der erzeugte Rohbericht liegt nach dem Lauf unter
`artifacts/backoff-fehlerfall/report.md`.

## Was hier schon echt funktioniert

| Baustein | Zustand |
|---|---|
| Fakten-Datenbank (SQLite) | Kerzen, Validierungen, Trades, Entscheide, Ereignisse, Konto, Agentenläufe, Konferenzen |
| Datenprüfung | Lücken, Doppelungen, unmögliche Hoch/Tief, Preissprünge, Mindestmenge, Zeitrahmen-Abstand |
| Backtest | Kerze für Kerze, Ausführung zur Folge-Eröffnung, ATR-Stop, Gaps, Kommission, Slippage |
| Richter | Rollierende Walk-Forward-Fenster, versiegelter Holdout, Monte-Carlo, Nachbar-Parameter, Zufallsvergleich |
| Risiko | 1 % je Trade bis Stop, 10 % Not-Stop, max. 15 Positionen, Engagement, Bargeld, Korrelation |
| Paper-Takt | direkte SQLite-Simulation aus Kerzen; kein Broker-Aufruf, keine echten Orders |
| Agenten | 80 bestehende Agenten in 8 Abteilungen, jeder mit echter Aufgabe und Ergebnis in der DB |
| Company-Schicht | Phase 1: 103 Profile, SQLite-Queue mit Lease/Retry, Policy-Engine, Audit-Kette; Company-API für Übersicht, Agenten, Aufgaben, Details, Nachrichten, Räume und Konferenz; Agentenkommunikation mit Threads/Ack und persönliche Gedächtnisse; 2D-Agenten-Querschnitt mit 103 Räumen; 3D noch nicht |
| Konferenz | 00:00 Europe/Zurich, Nachholen verpasster Termine, Protokoll im Vault |
| Wissenszentrum | Obsidian-Vault mit Frontmatter, Tags, `[[Links]]` |
| Dashboard | Orakel-Design, 12 Ansichten, Live-Polling, 2D-Agenten-Querschnitt, «Lauf starten» |
| Cockpit | Bot-Zustand, Kontostand, Gewinn/Verlust (heute, 7 Tage, 1 Monat) und offene Positionen mit letztem Kurs, alles aus SQLite |
| Dauerbetrieb | persistenter Plan, Backoff, Ressourcenlimits, Jobprotokoll und Betriebsansicht |

### Navigation und Deep-Links

Die zehn Sidebar-Bereiche sind echte Links mit stabilen Hash-Routen, etwa
`#/lab` oder `#/spider`. Ein direkter Aufruf oder ein Reload öffnet den
gewählten Bereich; Zurück und Vorwärts folgen dem Browser-Verlauf. Der aktive
Eintrag trägt `aria-current="page"`, der Dokumenttitel nennt den Bereich, und
nach einem Wechsel liegt der Fokus auf dessen Überschrift. Der Skip-Link
«Zum Inhalt» ist die erste Tastaturstation und springt zu `main#inhalt`.
Unbekannte oder nicht sichtbare Bereiche fallen auf «Übersicht» zurück.
Auf schmalen Viewports hält die Navigation den aktiven Eintrag automatisch
im sichtbaren Ausschnitt. Die Rand-Fades erscheinen nur in die Richtung,
in der weitere Bereiche liegen; am jeweiligen Ende und beim aktiven
Eintrag entfällt die Ausblendung. Auf Desktop bleibt die Linkliste beim
Scrollen langer Ansichten sichtbar; bei kurzen Viewports scrollt sie
intern. Ihre Höhe ergibt sich aus der tatsächlichen Position der Linkliste
unter Kopfzeile und Banner, und der aktive Link wird auch dort sichtbar
gehalten. Im
Querformat wird die Navigation beim Verlassen des Raumschiffs wieder
geöffnet.

Der Browser-Test dafür ist
`node scripts/pruefe-sidebar-navigation.mjs --url http://127.0.0.1:3000`.
Er prüft die zehn unveränderten Einträge, Deep-Links, Reload, den
Browser-Verlauf, `aria-current`, Skip-Link, die Fokusführung, die
responsive Sichtbarkeit, die richtungsabhängigen Ränder, die mitscrollende
Desktop-Sidebar auf langen Ansichten, den aktiven Link bei
1280/1024 × 500 px (Deep-Link und Zurück), echte Resize-Übergänge
1024 × 500 → 1280 × 800 → 1024 × 500, den Querformat-Grenzfall 901 × 500,
eine explizite Header-Höhenänderung sowie das Querformat-Verhalten.

Der Holdout ist der letzte Datenblock und wird erst nach der Walk-Forward-Auswahl einmal geöffnet; scheitert er, gibt es keinen Ersatzkandidaten. Im Lab zeigt ein Chart die aggregierte Kapitalkurve der Testfenster; beim Überfahren nennt ein Tooltip Kapitalstand, Veränderung seit dem Start in Prozent, Datum sowie den bisherigen Höchststand mit Abstand in Prozent; per Tastatur (Tab, Pfeiltasten, Home/Ende) ist dieselbe Anzeige erreichbar. Solange der Tastaturfokus im sichtbaren Lab-Detail liegt, pausiert der Auto-Refresh nur den Ansichts-Render, damit die Anzeige beim Ablesen nicht neu aufgebaut wird; Daten und Kopfzeile werden weiter aktualisiert; ein Status in der Listenkopfzeile (`#labNeu`, höfliche Live-Region) zeigt «Neue Daten verfügbar», und beim Verlassen des Details wird sofort neu gezeichnet statt auf den nächsten Takt zu warten. Ein Fokus auf der Lab-Liste oder einem anderen Lab-Element blockiert den Render nicht; ein ausgeblendetes Lab ebenfalls nicht. Der Refresh baut die Liste nicht neu auf: Vorhandene Einträge werden über eine stabile Kandidatenkennung in die neue Reihenfolge gebracht, Auswahl, Fokus und Scrollposition bleiben erhalten. Der Acht-Sekunden-Takt startet keinen zweiten Aufruf, solange eine Antwort läuft, pausiert im Hintergrundtab und lädt beim Zurückkehren sofort nach. Dort und in der Strategien-Ansicht lässt sich zudem bei jedem Kandidaten die Liste der Walk-Forward-Fenster aufklappen: Trainings- und Testblock, gewählter Parameter, Trades, Profit Factor und Netto je Fenster.

Der isolierte [Monte-Carlo-Perturbationstest](docs/ROBUSTHEIT.md) prüft einen bereits festgelegten Kandidaten zusätzlich gegen kleine Preis- und Parameteränderungen. Er ist nicht Teil des Richters und ändert weder Risiko noch Paper-Sperre.

Der H1-Retest mit bestätigtem Retest und Re-Entry-Sperre ist als [Signalplan und H1-Strategie](docs/H1-RETEST.md) im Backtest umgesetzt. Die [bestätigte Kurzfassung mit den offenen Backtest- und Paper-Punkten](docs/H1-RETEST-SPEZIFIKATION.md) hält den Entscheidungsstand fest. Die H1-Parameter stehen im `[research]`-Raster; die Strategie wird nur bei `richter_zeitrahmen = "H1"` aktiv und bei M15 nicht mitbewertet. Richter, Risikogrenzen und Paper-Sperre bleiben unverändert.

Das Cockpit oben in der Übersicht zeigt vier Zahlen aus derselben Datenbank: Bot-Zustand (letzter Paper-Takt, Risikostopp), Kontostand, Gewinn/Verlust und offene Positionen. Der Zeitraum lässt sich zwischen heute, 7 Tagen und 1 Monat umschalten; «heute» beginnt um 00:00 Uhr Europe/Zurich, und der Verlauf ist auf 120 Punkte ausgedünnt. Fehlt eine Grundlage, steht «–», und ein leerer Verlauf wird als solcher benannt. Als «steht» gilt der Bot, wenn seit drei Takten (mindestens drei Minuten) kein Paper-Takt mehr lief; ein gesetzter Risikostopp hat Vorrang und zeigt seinen Grund. Die offenen Positionen erscheinen darunter mit Einstieg, letztem M15-Kurs, Stop und unrealisiertem Ergebnis.

## Kursdaten aus MT5

In MT5 das Symbol im gewünschten Chart öffnen, `Bars` (Strg+B) → `Save as`
und als CSV speichern. Der Import erkennt Tabulator, Semikolon und Komma;
mehrere Dateien dürfen Teilzeiträume sein:

```bash
# ein Block, Symbol und Zeitrahmen aus dem Dateinamen (EURUSD_M15.csv)
.venv/bin/python -m orakel daten --csv daten/EURUSD_M15.csv

# mehrere Jahre in Blöcken; überlappende Zeitstempel werden ersetzt, nicht doppelt gezählt
.venv/bin/python -m orakel daten --csv daten/EURUSD_M15_2020.csv daten/EURUSD_M15_2021.csv daten/EURUSD_M15_2022.csv

# Serverzeit des Brokers nach UTC umrechnen (Sommerzeit inklusive)
.venv/bin/python -m orakel daten --csv daten/EURUSD_M15.csv --server-zeitzone Europe/Athens

# oder mit festem Broker-Versatz, wenn der Server keine Sommerzeit kennt (z. B. UTC+3)
.venv/bin/python -m orakel daten --csv daten/EURUSD_M15.csv --server-versatz-stunden 3

# ohne Zeitrahmen im Dateinamen: Symbol und Rahmen vorgeben (nur bei einer Datei)
.venv/bin/python -m orakel daten --csv daten/export.csv --symbol EURUSD --zeitrahmen M15

# danach der vollständige Lauf: Research → Richter → Risiko → Plan
.venv/bin/python -m orakel pruefen
```

Unterstützte Spalten (Groß-/Kleinschreibung egal, mit oder ohne spitze Klammern):

| MT5-Kopfzeile | Bedeutung | Pflicht |
|---|---|---|
| `<DATE>` + `<TIME>` (auch `date` + `time`, `datum` + `zeit`) | Zeitstempel, getrennt oder in einer Spalte (`datetime`) | ja |
| `<OPEN>` `<HIGH>` `<LOW>` `<CLOSE>` (auch `open`, `high`, `low`, `close`, `eröffnung`, `hoch`, `tief`, `schluss`) | Kurse | ja |
| `<TICKVOL>` (auch `tickvol`, `volume`, `volumen`, `vol`) | Volumen; fehlt die Spalte, steht 0 | nein |
| `<VOL>`, `<SPREAD>` | echtes Volumen und Spread | werden ignoriert |

Zeitstempel: MT5 schreibt `YYYY.MM.DD HH:MM[:SS]`, zusätzlich wird ISO 8601 mit
Uhrzeit gelesen. Eine Tag/Monat-Vertauschung wird nicht geraten, und ein Datum
ohne Uhrzeit wird abgelehnt (daraus würde eine falsche Mitternachtskerze) —
unbekannte Formen brechen mit Meldung ab.

MT5 exportiert Serverzeit ohne Zeitzone; standardmässig gilt sie als UTC. Mit
`--server-zeitzone Europe/Athens` (oder `[daten] server_zeitzone` in
`config.toml`) wird sie als Ortszeit dieser IANA-Zone gelesen und nach UTC
umgerechnet — inklusive Sommerzeitwechsel über mehrere Jahre. Bei der
Rückstellung im Herbst wiederholen sich Uhrzeiten: Die frühere Fassung gilt als
Sommerzeit, die spätere als Standardzeit, sodass beide Stunden erhalten bleiben.
Eine absteigend sortierte Datei dreht diese Reihenfolge; der Import erkennt die
Richtung am ersten und letzten Zeitstempel und ordnet die Fassungen entsprechend
zu. Besteht eine Datei nur aus dem Herbstpaar, sind erster und letzter
Zeitstempel gleich; dann ist keine Richtung erkennbar und der Import nimmt
aufsteigend an (Sommerzeit zuerst). Das gilt innerhalb einer Datei; wird die
wiederholte Stunde über zwei Dateien verteilt, greift die Dublettenregel. Führt
der Broker dauerhaft einen festen Versatz ohne Sommerzeit, verschiebt
`--server-versatz-stunden 3` (oder
`[daten] server_versatz_stunden` in `config.toml`) die Serverzeit um drei
Stunden nach UTC; negative Werte sind erlaubt. Als Kurzform akzeptiert der
Import auch `--server-versatz +03:00` oder `--server-versatz -05:00`
(negativ auch mit Gleichheitszeichen: `--server-versatz=-05:00`); die Angabe
schliesst `--server-zeitzone` und `--server-versatz-stunden` aus. Zone und fester Versatz zusammen werden mit
einer Meldung abgelehnt, weil sonst unklar wäre, welche gilt. Preise brauchen einen Dezimalpunkt; `1,035` wird
abgelehnt statt still zu fehlen. Doppelte Zeitstempel gewinnen mit der letzten
Zeile, die Reihe wird aufsteigend sortiert. Kodierung: UTF-8 (auch mit BOM)
oder cp1252. Grosse Dateien (mehrere Jahre M1) werden tageweise blockweise
gelesen und in einer Transaktion geschrieben: Der Speicherbedarf beim Lesen und
Schreiben bleibt flach, bei einem Fehler bleibt die Datei unverändert, und
geprüft wird weiterhin die zusammengeführte Reihe. Die Datei muss nach Datum
und innerhalb eines Tages chronologisch sortiert sein (auf- oder absteigend).
Bei der Herbst-Rückstellung ist genau ein Rücksprung um die wiederholte Stunde
erlaubt. Alle Tagesläufe müssen dieselbe Richtung haben. Verschränkte Tage,
gemischte Tagesrichtungen oder anders gemischte Zeilen innerhalb eines Tages
brechen mit einer Meldung ab, statt die Herbststunden falsch zuzuordnen.

Zeitrahmen: importiert werden `M1`, `M5`, `M15`, `H1`. Der Zeitrahmen wird
an beliebiger Stelle im Dateinamen erkannt (`EURUSD_H1_2020.csv`,
`EURUSD_2020_H1.csv`) oder über `--zeitrahmen` gesetzt; ein Jahres-Suffix wie
`2020` wird ignoriert. Unbekannte Zeitrahmen-Tokens wie `H4` werden mit Meldung
abgelehnt, statt still als M15 gelesen zu werden. **Paper liest M15**; der
Richter bewertet `[basis] richter_zeitrahmen` (Standard `M15`, z. B. `H1`).
`bars_pro_jahr` gilt für M15 und wird für andere Zeitrahmen umgerechnet (H1:
6240 statt 24 960); `min_kerzen` folgt derselben Basis (H1: 300 statt 1200).
Der Ordner-Import über `[basis] datenquelle = "csv"` liest `daten/*.csv`,
importiert M15 und den Richter-Zeitrahmen; bekannte, nicht benötigte
Zeitrahmen werden mit Ereignis im Protokoll übersprungen. Ein unbekannter
Zeitrahmen bricht den Ordner-Import vor dem ersten Schreiben ab. Der Import
läuft in einer gemeinsamen Transaktion: `datenquelle = "csv"` wird erst nach
bestandener Reihenprüfung gesetzt, und ein Fehler in einer Datei rollt alle
Dateien dieses Imports zurück. Ist der Ordner leer, bricht der Lauf ohne
vorhandene Datenbankkerzen mit Meldung ab, statt synthetische Kerzen zu
erzeugen; vorhandene Datenbankkerzen werden mit einer Warnung weiterverwendet.
Beim Import wird die jüngste Kerze je Symbol und Zeitrahmen gegen ihre
Frischegrenze geprüft: `max_kurs_alter_stunden_<tf>` bzw. der Rückfall
`max_alter_tage`. Eine Überschreitung wird als Warnung protokolliert,
blockiert den Import aber nicht. Die Frischegrenzen bleiben
je Zeitrahmen getrennt (`max_kurs_alter_stunden_h1` usw.), auch wenn der
Paper-Takt M15 liest.

### Direkter Abruf aus dem Terminal (Windows)

Statt von Hand zu exportieren, holt `scripts/mt5_abruf.py` die Historie direkt
aus dem laufenden Terminal. Das Paket `MetaTrader5` gibt es nur für Windows
(64-Bit-Python), es spricht per IPC mit dem Terminal und steht deshalb bewusst
nicht in `requirements.txt`:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install MetaTrader5
.\.venv\Scripts\python.exe scripts\mt5_abruf.py --symbol EURUSD --zeitrahmen M15 --von 2020-01-01
```

Geschrieben wird `daten/EURUSD_M15.csv` im selben Format wie `Save as`
(`<DATE> <TIME> <OPEN> …`), monatsweise abgefragt, überlappend zusammengeführt
und aufsteigend sortiert.
Zusammengeführt wird nur, was in Zeit und Werten gleich ist — die doppelte
Stunde der Herbst-Rückstellung bleibt deshalb vollständig erhalten.
Tick-Daten holt derselbe Abruf mit `--format ticks`:

```powershell
.\\.venv\\Scripts\\python.exe scripts\\mt5_abruf.py --symbol EURUSD --format ticks --von 2025-01-01
```

Geschrieben wird `daten/EURUSD_ticks.csv` mit
`<DATE> <TIME> <MSEC> <BID> <ASK> <LAST> <VOLUME> <VOLUME_REAL> <FLAGS>`,
ebenfalls monatsweise abgefragt, aufsteigend nach Serverzeit und Millisekunde
sortiert und von exakten Dubletten befreit. `--zeitrahmen` gilt nur für Kerzen;
ohne `--format` entsteht unverändert das Kerzen-CSV. Die Tick-Datei ist ein
eigenes Archivformat und wird von `orakel daten --csv` nicht gelesen.

Danach wie oben importieren, inklusive `--server-zeitzone` oder
`--server-versatz`. Voraussetzung: Das
Terminal läuft, ist angemeldet und das Symbol steht im Market Watch;
Zugangsdaten braucht das Skript nicht, und es gibt keinen Weg zu einer Order.

Grenzen: Es kommen nur Kerzen, die das Terminal geladen hat — „Max. bars in
chart" und die Broker-Historie begrenzen die Tiefe, fehlende Bereiche werden
übersprungen statt erfunden. Broker-Symbole können abweichen (`EURUSD.a`), und
der Transport zum Server bleibt manuell: Datei kopieren und dort importieren.

Nach dem Import prüft der Befehl die **zusammengeführte** Reihe je Symbol und
Zeitrahmen (einzelne Blöcke dürfen kürzer als `min_kerzen` sein): Mindestzahl
Kerzen (`min_kerzen` gilt für M15 — 1200 Kerzen sind zwei Wochen — und wird für
andere Raster umgerechnet, z. B. 300 für H1), doppelte oder unsortierte Zeitstempel, unmögliches Hoch/Tief, Preise
≤ 0, Lücken über dem Dreifachen des Median-Abstands und Sprünge über
`max_sprung_pct`. Bei mehreren Jahren zeigt der Import die Kerzen je
Kalenderjahr nach UTC-Zeitstempel (`Abdeckung: 2023: 24960, 2024: 24960, …`)
und warnt, wenn
zwischen erstem und letztem Jahr ein ganzes Jahr ohne Kerzen bleibt — etwa wenn
die Broker-Historie abgeschnitten ist. Diese Warnung blockiert den Lauf nicht,
weil die vorhandene Reihe weiter verwendbar ist; die Jahresabdeckung und die
Warnung stehen auch im Datenqualitätsblock des Berichts. Trifft ein erneuter Import auf denselben
Zeitstempel mit anderen OHLC-Werten, nennt er die Zahl der abweichenden Kerzen
und ein Beispiel; ersetzt wird weiterhin, aber nicht mehr still. Der häufigste
Abstand muss ausserdem zum
angegebenen Zeitrahmen passen (M1/M5/M15/H1), damit auch Zwischenraster wie M20
oder M45 auffallen: Eine als M15 benannte H1-Datei wird mit Meldung abgelehnt,
statt still als M15 zu gelten. Geprüft wird vor dem Schreiben — die
falsch getakteten Zeilen landen gar nicht erst in der Tabelle. Die Vorprüfung
puffert zeilenbasiert höchstens 10 000 Zeilen; dünne Dateien werden vollständig
gepuffert und noch vor dem Schreiben geprüft. Wochenenden, Feiertage und
Handelspausen sind einzelne lange Abstände und verschieben den häufigsten
Abstand nicht; sie gelten nicht als Rasterfehler. Der Median bleibt nur für die
Lückenschwelle maßgeblich. Fehler und Warnungen stehen im Terminal und im Ereignisprotokoll;
bei einem Fehler endet der Befehl mit Exit-Code 1, importiert bleibt die Reihe
trotzdem.

Noch nicht unterstützt: die automatische Erkennung der Broker-Zeitzone (sie
muss als IANA-Zone oder fester Versatz angegeben werden), der automatische Transport der
Windows-Abfrage zum Server, Tick-Daten, Dezimalkommas und eine Bewertung anderer Zeitrahmen
als M15 im Paper-Takt; der Richter kann über `[basis] richter_zeitrahmen`
auch H1 lesen, wobei `bars_pro_jahr` umgerechnet wird.

## Risikogrenzen (deine Vorgaben)

```toml
risk_per_trade_pct = 1.0     # Obergrenze bis zum Stop
max_drawdown_pct   = 10.0    # Not-Stop
max_open_positions = 15      # harter Deckel
```

Zusätzlich konservativ: 10 % Tagesverlust, 100 % Gesamtengagement (kein Hebel),
20 % max. Positionsgrösse und 10 % Mindest-Bargeld. Die 1 % sind eine
**Obergrenze**, keine Zielgrösse: Bei einem engen Stop erlaubte das Risikobudget
deutlich mehr Stück, der 20-%-Deckel lässt aber höchstens ein Fünftel des
Kontos als Nominal zu. Ohne Hebel hängt die tatsächliche Risikohöhe deshalb am
Stop: 0.5 % Stop-Abstand ergeben 0.1 %, 1 % ergibt 0.2 %, 2 % ergeben 0.4 % des
Kontos. Die vollen 1 % erreicht eine Position erst ab etwa 5 % Stop-Abstand;
mehr als 1 % sind nie möglich.

## Kostenmodell

Das Instrument wählt Modell und Pip-Grösse: `orakel/kern/kosten.py` leitet die
Klasse aus dem Symbol ab. Nur Devisenpaare haben ein Profil (zwei bekannte
Währungscodes; Broker-Suffixe wie `EURUSDm`, `EURUSD_RAW` oder `EURUSD.pro`
werden ignoriert, JPY-Paare enden auf `JPY`): EURUSD rechnet mit 0.0001 je Pip,
USDJPY mit 0.01.
Indizes wie `US500` haben kein Profil und laufen wie andere unbekannte Symbole
über `[kosten]`. Backtest und Paper-Takt nutzen dieselbe Formel:

- `stueck` (Standard): Kommission je Stück, mindestens `min_commission` — für
  Aktien und andere Stück-Instrumente.
- `spread`: halber quotierter Spread je Seite, also `menge × spread_pips ×
  pip_groesse / 2` — für Devisen und andere Symbole mit `modell = "spread"`.
  Eine Kommission fällt dabei nicht an.

Beispiel EURUSD: 1 Pip = 0.0001, Spread 1.0 Pip. Bei 18'500 Einheiten kostet
eine Seite 0.93 USD. Das Stück-Modell mit 0.005 je Einheit verlangte 92.50 USD
je Seite, rund 46 Basispunkte — damit wäre jede Forex-Strategie nach Kosten
unrentabel. Der Spread fällt in der Kurswährung des Paares an: Bei USDJPY sind
die 92.5 JPY je Seite durch den Kurs zu teilen, bei 157 also rund 0.59 USD;
EURUSD notiert bereits in USD und bleibt bei 0.93. Für Paare ohne Kurs zur
Kontowährung (etwa EURGBP bei USD-Konto) bricht die Kostenrechnung mit einer
Meldung ab, statt eine falsche Währung zu buchen. `[kosten]` (inklusive
`modell`) gilt als Rückfall für unbekannte Symbole wie Aktien und Indizes; nur
Devisenpaare bringen ihr Profil mit, für sie muss in `config.toml` nichts je
Symbol eingestellt werden.

Optional bucht `finanzierung_bps_pro_tag` Finanzierungskosten pro UTC-Kalendertag
auf das Einstiegsnotional; der Default ist `0` (deaktiviert). Die Kennzahl
`finanzierung` steht im Backtest-Ergebnis getrennt von `gebuehren`. Der Bericht
führt den Tagessatz additiv unter `kosten.finanzierung_bps_pro_tag`; Lab und
Strategien zeigen die gebuchten Finanzierungskosten getrennt von den Gebühren.
Das Berichtsschema bleibt bei 2, neue Felder sind für bestehende Leser additiv.

## Aufbau

```
orakel/
  config.py      Konfiguration + Risikogrenzen
  db.py          Fakten-Datenbank (einzige Wahrheit)
  data.py        CSV-Import, Datenprüfung, synthetische Kerzen
  strategies.py  Bausteine + freigegebenes Parameter-Raster
  backtest.py    Kerze-für-Kerze-Engine
  metrics.py     Kennzahlen
  judge.py       Richter (keine KI)
  risk.py        Risikomanager + Positionsgrösse
  agents.py      Roster, Aufgaben, Mitternachtskonferenz
  knowledge.py   Obsidian-Vault
  report.py      Bericht im Schema 2 (dein Dashboard-Format)
  pipeline.py    kompletter Lauf
  web.py         FastAPI + Dashboard
tests/           Risiko, Backtest, Daten, Bericht
```

## Noch offen (nächste Phasen)

1. **Echte Daten**: CSV-Import und direkter Abruf aus dem Terminal auf deinem
Windows-Rechner stehen (siehe [Kursdaten aus MT5](#kursdaten-aus-mt5)); der
automatische Transport zum Server fehlt noch.
2. **Spider Intelligence**: Netz-Recherche mit Quellenprüfung, robots.txt und Limits.
3. **3D-Ausbau**: begehbare Decks und First-Person-Navigation sind zurückgestellt;
   die aktuelle 2D-Welt ist umgesetzt und an echte Daten gekoppelt.
4. **Dauerbetrieb aktivieren**: Der 24-Stunden-Soak ist noch nicht abgeschlossen.
   Ablauf und Abnahmekriterien stehen in
   [SOAK-ABNAHME.md](docs/spider/SOAK-ABNAHME.md). Der externe Watchdog ist in
   `.github/workflows/watchdog.yml` angelegt und prüft nach dem Push auf `main`
   den Takt alle fünf Minuten.
5. **Selbstlernen**: Auswertung abgeschlossener Trades inkl. Fehleranalyse.

## Grundsätze im Code

- Kein Look-Ahead: Signal an Kerze *i*, Ausführung zur Eröffnung von *i+1*.
- Kosten und Slippage in jedem Backtest.
- Der Richter ist fest verdrahtet; keine KI ändert seine Regeln.
- Jede Zahl im Dashboard stammt aus SQLite — nichts wird geschätzt oder erfunden.

## Qualitätstor

Drei eigene CI-Jobs prüfen den Code: `ruff` (blinde Fänge `BLE001`, stille
Fehlerschlucker `S110`, Sicherheitsregeln `S`), `mypy` für den Handelskern
(`paper`, `risk`, `backtest`, `judge`) und `Coverage Handelskern` mit einer
Untergrenze von 85 % für dieselben vier Module. Regeln, Ausnahmen für den
Altbestand und die lokalen Befehle stehen in
[docs/QUALITAET.md](docs/QUALITAET.md).

## Reproduzierbare Synthetik-Messung

`scripts/messe_synthetisch.py` erzeugt eine deterministische Fünfjahresreihe
und misst Import und Richterlauf getrennt (Wanduhrzeit und Spitzen-RSS) in einer
eigenen, isolierten SQLite-Datenbank. Aufruf, Isolationsgarantie und Grenzen:
[docs/BENCHMARK.md](docs/BENCHMARK.md).

## Review-Paket

`scripts/baue_review_paket.py` nimmt nur auf, was in
`scripts/review-paket-freigabe.json` freigegeben ist. Ins Paket gehören Code
(`orakel/`), Tests (`tests/`), Doku (`docs/`, `README.md`, `AGENTS.md`,
`DEPLOY.md`, `RAILWAY.md`), Prüf- und Evidenzskripte (`scripts/`), die
Konfiguration, die das Verhalten bestimmt (`config.toml`, `seed/`,
`requirements*`), die Prüfregeln (`ruff.toml`, `mypy.ini`, `.importlinter`,
`.githooks/pre-commit`), die CI-Workflows und die Deployment-Dateien
(`Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `deploy/`).

Reine Meta-Dateien bleiben draußen: `.gitignore` und `.dockerignore` regeln
Repository- und Build-Hygiene, `.env.example` ist eine Platzhalter-Vorlage (die
wirksame Konfiguration steht in `config.toml`), `railway.json` beschreibt die
Plattform und ist über `DEPLOY.md` und das Dockerfile abgedeckt. Sie stehen mit
Begründung unter `ausnahmen`, und der Bericht des Pakets weist sie aus.
`tests/test_review_paket.py` verlangt für jede Wurzeldatei entweder einen Platz
im Paket oder eine begründete Ausnahme; Code, Tests, Doku, Skripte und CI
lassen sich nicht ausnehmen.

## Doku-Prüfung

`python scripts/pruefe_doku.py` prüft die versionierten Markdown-Dateien auf
relative Links, vorhandene Überschriften-Anker, veraltete Deck- und
Navigationsbegriffe sowie englische Altnamen der Agentenabteilungen. Jeder
relative Pfad wird vom jeweiligen Dokument aus aufgelöst; externe URLs werden
übersprungen. Relative Links mit `#Sprungmarke` werden zusätzlich gegen die aus
Markdown-Überschriften erzeugten GitHub-Anker und explizite `id`-Attribute in
HTML-Überschriften (`<h1>`–`<h6>`) geprüft, auch reine Sprungmarken innerhalb
derselben Datei. Der Lauf schlägt fehl, wenn ein Ziel oder ein Anker fehlt, ein
alter Deck- oder Navigationsbegriff auftaucht oder ein englischer Altname einer
Agentenabteilung erscheint. Der Normallauf verlangt ausserdem mindestens einen
gültigen Ankerlink; sonst würde eine stillschweigend entfernte
Sprungmarkenprüfung auffallen. Die historischen Planungsdokumente `MASTERPLAN.md`
und `RAUMBUCH.md` sind ausgenommen, weil sie den früheren 3D-Prototyp und die
damaligen Raumnamen dokumentieren. `--negativtest` erzeugt absichtlich einen
kaputten Link, vier falsche Anker, mehrere alte Deck- und Navigationsangaben
sowie neun englische Altnamen; alles muss erkannt werden. Der eigene CI-Job
`doku` führt beide Läufe aus, sobald Markdown-Dateien oder das Prüfskript
geändert wurden; andernfalls wird er übersprungen. Zusätzlich verlangt der
Lauf, dass `README.md` die Schutz-Dokumentation
[docs/pr-schutz.md](docs/pr-schutz.md) verlinkt; sonst schlägt er fehl, damit
die Datei nicht unbemerkt verwaist.

### Schutz von `main`

`main` ist durch ein Repository-Ruleset geschützt: Änderungen laufen
ausschliesslich über Pull Requests, und sechs Required Checks müssen grün sein.
Die aktuelle Liste der Checks, das Skip-Verhalten der Doku-Prüfung und die
Bypass-Regeln stehen in [docs/pr-schutz.md](docs/pr-schutz.md); diese Datei ist
der verbindliche Stand und wird bei Änderungen am Ruleset mitgepflegt.

### Lokaler Pre-Commit-Hook

Der versionierte Hook `.githooks/pre-commit` startet die Doku-Prüfung, sobald
Markdown-Dateien oder `scripts/pruefe_doku.py` gestaged sind. Ist das Prüfskript
selbst gestaged, führt er zusätzlich den Negativtest `--negativtest` aus. Einmalig
im Repository aktivieren:

```sh
git config core.hooksPath .githooks
```

Ohne relevante Änderungen beendet sich der Hook sofort.

## CI-Trigger für Feature-Branches

Ein Pull Request führt den vollen Workflow `Tests` aus (`pull_request`); ein
Push auf `main` ebenfalls, damit Railway sein "Wait for CI" erkennt.
Feature-Branch-Pushes ohne offenen Pull Request starten den schlanken Workflow
`Branch-Smoke`: Er prüft Python-Syntax, Doku-Links und die Syntax der
Prüfskripte. Sobald ein Pull Request offen ist, überspringt `Branch-Smoke` seine
Prüfschritte, weil der volle PR-Lauf übernimmt – pro Commit läuft damit genau
ein vollständiger Satz Jobs.

Bewusst keine Concurrency-Cancellation zwischen Push- und PR-Lauf: Ein
abgebrochener Lauf hinterlässt `cancelled`-Check-Kontexte auf demselben
Head-Commit, die als nicht erfolgreich gelten und den Pull Request blockieren.
`Branch-Smoke` hat einen eigenen Check-Namen und ist kein Required Check; die
Job-Namen und `needs`-Ketten aus `tests.yml` bleiben unverändert.

## Manuelle iPhone-Safari-Prüfung

Für die Abnahme der Schiffsansicht auf echter Safari-Hardware:
[Checkliste für Pan, Pinch und Tippen](docs/raumschiff/IPHONE-SAFARI-CHECKLISTE.md).
Sie ergänzt den automatisierten Touch-Test und deckt Porträt, Querformat,
Safari-Seitenzoom und die Legendenbedienung ab. Der Touch-Test prüft zusätzlich den
2400-px-Grossmodus bei 1100 px Breite. Die Ergebnisse des letzten
Chromium-Emulationslaufs stehen in
[TOUCH-EMULATION.md](docs/raumschiff/TOUCH-EMULATION.md).

## Widerspruch von der API bis in die Karte

`scripts/pruefe-widerspruch-e2e.mjs` prüft einen Widerspruch nicht an
injizierten DOM-Daten, sondern am echten Weg: Der Seed legt zwei gegenläufige
Meldungen über den Nexus-Pfad in einer Kopie der Seed-Datenbank an. Die
Spider-Ansicht lädt anschließend den echten `/api/nexus/status`-Response; der
Browser vergleicht Grund, Widerspruchssicherheit, Quellen und normalisierte
bp-Werte mit der gerenderten Widerspruchskarte. Erwartungen und
API-Vertragsprüfung liegen gemeinsam in `scripts/widerspruch-api-pruefung.mjs`;
`tests/test_widerspruch_api_pruefung.py` prüft denselben Vertrag ohne Browser und
schlägt bei fehlender, falscher oder doppelter Widerspruchszeile an. Mit
`--url http://127.0.0.1:3300` holt das Skript die Antwort selbst von der
laufenden API; `tests/test_api_vertrag_live.py` startet dafür eine
geseedete Kopie und prüft einmal den angelegten Widerspruch und einmal dessen
Fehlen in einer frischen Seed-Datenbank — Node genügt, Playwright ist nicht
nötig.

Derselbe Modus deckt den Bericht ab: `scripts/report-api-pruefung.mjs --url
http://127.0.0.1:3300` prüft, dass `/api/report` Cockpit (Konto,
Gewinnfenster heute/7 T/1 M), Papier- und Spider-Abschnitt in der Form liefert,
auf die die Ansichten zugreifen. Beträge und Equity dürfen `null` sein, die
Struktur nicht; ohne erreichbare API schlägt der Prüfer anstatt still zu
bestehen. `tests/test_api_vertrag_live.py` führt ihn gegen eine frische
Seed-Kopie aus.

Dasselbe gilt für die Company-Übersicht: `scripts/company-api-pruefung.mjs
--url http://127.0.0.1:3300` prüft an `/api/company/overview` die Zahlen, die im
Raumschiff stehen — Agentenzahl, Statuszähler, Abteilungen und offene Aufgaben —
und dass `aufgaben.offen` zu den offenen Einzelstaaten passt. Geprüft wird die
Struktur, nicht ein bestimmter Wert; eine frische Datenbank hat null offene
Aufgaben. Auch dieser Prüfer schlägt ohne erreichbare API an, statt still zu
bestehen.

```bash
cp seed/orakel-seed.db /tmp/orakel-widerspruch.db
python scripts/seed_widerspruch.py /tmp/orakel-widerspruch.db

# Dashboard in einem zweiten Terminal starten:
ORAKEL_DB_PFAD=/tmp/orakel-widerspruch.db python -m orakel serve --host 127.0.0.1 --port 3300

# Im ersten Terminal:
node scripts/pruefe-widerspruch-e2e.mjs --url http://127.0.0.1:3300

# Negativtest: verfälscht im DOM den Widerspruchsgrund, entfernt danach
# die Widerspruchszeile und entfernt sie zusätzlich aus einer Kopie der
# API-Antwort; alle drei Fälle müssen als Fehler erkannt werden.
node scripts/pruefe-widerspruch-e2e.mjs --url http://127.0.0.1:3300 --negativtest
```

Der Negativtest verändert keine Datenbank und keine echte API-Antwort. Er prüft,
dass derselbe Kartenprüfer eine falsche Widerspruchszeile und eine fehlende
Widerspruchszeile zuverlässig ablehnt und dass der API-Prüfer eine aus der
API-Antwort entfernte Widerspruchszeile erkennt. Der eigene CI-Job
`Widerspruch-E2E 3/3` führt den positiven Test und den Negativtest auf einer
frischen Seed-Kopie aus. Sein stabiler Check-Name ist `Widerspruch-E2E 3/3`;
bei Erfolg lädt er `lauf.log` und `negativtest.log` als Artefakt
`widerspruch-e2e-3-3-erfolg` hoch; zusätzlich erscheint
`Widerspruch-E2E-Negativtest: 3/3 bestanden` im Job-Log und in der
Job-Zusammenfassung. Das Seed-Skript verweigert eine fehlende
Zieldatenbank, damit es nicht versehentlich eine neue Produktionsdatenbank
anlegt.

## Browser-Prüfung bei grosser Schrift

`scripts/pruefe-text250.mjs` skaliert die Schrift im Dashboard auf 250 %
(Faktor 2,5 auf berechnete Schriftgrössen und Zeilenhöhen). Der 250-%-Lauf
prüft ausschliesslich 360, 320 und 280 px und misst dort, ob Inhalte seitlich
aus ihrem Kasten oder aus dem Viewport laufen. Davon getrennt prüft der Lauf
alle zwölf Ansichten bei 240 px ausschliesslich in normaler Schrift sowie die
Kernaussagen-Karte und die Kopf- und Navigationsleiste. Die vier KPI-Kacheln
und das Claim-Grid wechseln auf eine Spalte, die Quellenzeile bleibt im
Panel. Kopf und Navigation brechen kompakt um; die Seite scrollt dort nicht
horizontal. **240 px wird ausschliesslich in normaler Schrift geprüft; der
12/12-Nachweis gilt nur dafür. Der 250-%-Lauf läuft ausschliesslich bei 360,
320 und 280 px. Ein voller 250-%-Lauf bei 240 px ist nicht Teil der Zusage.
240 px ist die untere geprüfte Breite, darunter gibt es keine Layoutzusage.**

Die 240-px-Prüfung misst alle zwölf Ansichten in normaler Schrift bei
240 × 900 px. Jede Zeile prüft Seiten-, Kopf- und Navigationsbreite:

| Ansicht | Scrollbreite | Ergebnis |
| --- | ---: | --- |
| Übersicht | 240 px | OK |
| Risiko & Daten | 240 px | OK |
| Lab | 240 px | OK |
| Strategien | 240 px | OK |
| Research | 240 px | OK |
| Weltkugel | 240 px | OK |
| Betrieb | 240 px | OK |
| Raumschiff | 240 px | OK |
| Spider | 240 px | OK |
| Wissensbank | 240 px | OK |
| Agentenraum | 240 px | OK |
| Konferenz | 240 px | OK |

Der erfolgreiche [text250-CI-Lauf](https://github.com/gxfrty-21/orakel/actions/runs/43811966526/job/133115401944)
bestätigt diesen 12/12-Nachweis für normale Schrift bei 240 px. Der CI-Schritt
prüft dafür die expliziten Fall-IDs `text250.240.<ansicht>` aus dem
maschinenlesbaren Ergebnis.

Der spätere erfolgreiche [CI-Lauf 43939906217](https://github.com/gxfrty-21/orakel/actions/runs/43939906217)
auf PR-Head `5f21361` bestätigt diese Prüfung ebenfalls; alle sechs Jobs waren
erfolgreich.

### Belastbarkeitsgrenze bei 240 px

Die Kernaussagen-Karte ist bei 240 px in normaler Darstellung tragfähig:

- `#bewertungPanel` ist 208 px breit (206 px Innenbreite) und bleibt zwischen
  16 und 224 px im Viewport.
- Die Quellenzeile ist 178 px breit, bricht zweizeilig um und bleibt mit
  `scrollWidth === clientWidth === 178` im Panel.
- KPI-Kacheln und Claim-Grid wechseln auf eine Spalte; die Claim-Liste bleibt
  intern scrollbar.
- Die Seite bleibt mit `scrollWidth === clientWidth === 240` ohne horizontalen
  Überlauf. Kopf und Navigation umbrechen kompakt und bleiben jeweils innerhalb
  ihrer 240-px-Container.

Die 240-px-Prüfung umfasst alle zwölf Ansichten in normaler Schrift
(`240px: 12/12`). Der 250-%-Lauf läuft ausschliesslich bei 360, 320 und
280 px; 240 px ist nicht Teil davon.
Der gezielte Spider-Lauf prüft die Karte zusätzlich bei 240 px, auch wenn
240 px nicht in `--breiten` steht:

```bash
node scripts/pruefe-text250.mjs --ansichten spider --breiten 240 \
  --url http://127.0.0.1:3400
```

Erwartet werden Exit-Code 0, `240px/spider: OK · Seite 240px · Kopf 240/240 ·
Navigation 240/240`, `240px: 1/1 Ansichten ohne horizontalen Überlauf` und
`Claims 1× geprüft`. Der Standardlauf mit `--breiten 360,320,280` prüft die
Karte zusätzlich bei 240 px in normaler Schrift und meldet `Claims 4× geprüft`.

**240 px ist die untere geprüfte Breite.** Darunter gibt es keine Layoutzusage,
weder für die Karte noch für die übrigen Ansichten.

Die feste Pixel-Art des Raumschiffs ist von der Textskalierung
ausgenommen; die Agentendetails in der rechten Spalte skalieren mit. Tabellen werden zusätzlich mit langen deutschen Komposita belastet und
als Karten geprüft. Im Lab überfährt er ausserdem die Kapitalkurve und prüft
den Tooltip (Kapitalstand, Datum, Lage im Kasten, Verschwinden von Tooltip und
Live-Region beim Verlassen, Wiederkommen nach erneutem Überfahren mit demselben
Kapitalstand, Datum, Prozentwert und Abstand zum Hoch, dazu ein Punkt unter dem
Hoch mit positivem Abstand, der aus Kapitalstand und Hochstand nachgerechnet
wird, am Hochpunkt selbst 0 %); der Hinweis unter der
Kurve führt ← und → als
kbd-Tasten. Geprüft wird die Tastaturbedienung
(Durchtabben von oben bis zur Kurve, Fokusring auf der Kurve, Shift+Tab zurück,
Tab zum nächsten Element mit sichtbarem Fokusring, Fokusring verschwindet nach
dem Verlassen,
Pfeiltasten, Home/Ende,
aria-label nennt Pfeiltasten, Home und Ende, der Accessibility-Snapshot führt die
Live-Region als Status mit ihrem Text und aktualisiert ihn bei Pfeil rechts,
Start/Tief/Hoch/Ende stimmen mit der
Fusszeile überein, Tief/Hoch auch mit den Extremwerten aus den API-Daten, die
gezeichnete Punktzahl mit deren Ausdünnung sowie Start, Viertel, Mitte,
Dreiviertel und Ende mit den API-Zeitstempeln und -Werten, jeweils in Tooltip
und Live-Region — per Maus und nochmals über Home, Pfeil rechts und Ende per
Tastatur, samt nachgerechnetem Prozentwert ab Start, Abstand zum Hoch
und angezeigtem Hochstand (Tooltip und Live-Region gegen das fortgeschriebene
API-Hoch),
Start/Ende auch mit den Tooltips bei Home/Ende, genau
eine Live-Region je Kurve,
die visuell verborgen bleibt, role=status sowie aria-live=polite trägt, nicht
aria-hidden ist und in keinem display:none- oder visibility:hidden-Vorfahren
liegt).
Exit-Code 1 bei einem Befund.

Die früheren 24 Lab-Befunde im 250-%-Lauf, ihre Zuordnung zu 360 px und die Ursache im Auto-Refresh sind in [PHASE-3](docs/spider/PHASE-3.md) dokumentiert.

Der Standardlauf prüft bei 1440 px zusätzlich die kompakte
Abteilungslegende: offen, elf Einträge, kompakter Kopf und kein horizontaler
Überlauf. Die Zusammenfassung meldet `Desktop-Legende 1× geprüft`.

Der Standardlauf prüft zusätzlich die drei Company-Schreibwege über die
Web-API: eine direkte Nachricht senden, sie als Empfänger quittieren und einen
persönlichen Gedächtniseintrag anlegen sowie aktualisieren. Die Prüfung nutzt
eindeutige Testwerte; in der CI schreibt sie ausschliesslich in die Seed-Kopie.

Im Spider-Tab rendert der Standardlauf ausserdem deterministische
Claim-Metadaten im Browser: Zeitraum, Bedingung und Extraktionssicherheit sowie
Widerspruchsdetails mit Grund, Widerspruchssicherheit, normalisierten
Vergleichswerten in bp und den beteiligten Quellen.
Dabei prüft er, ob die Karte,
ihre Metadaten und Widerspruchszeilen seitlich aus dem Viewport oder ihrem
Kasten laufen. Zusätzlich werden vier bewusst lange Quellenfälle geprüft – zwei
überlange Hostpaare, ein einzelner sehr langer Host mit Punkten und Bindestrichen
sowie ein langer Host ganz ohne Punkt oder Bindestrich. Beim Extremfall ohne
Punkt oder Bindestrich bleiben die Quellenzeilen in normaler Darstellung ohne
Überlauf; die konkreten Breiten sind:

| Viewport | Quellenzeile | Host-Spanne | Zeilen des 114-Zeichen-Hosts |
| ---: | ---: | ---: | ---: |
| 360 px | 298 px | 294 px | 3 |
| 320 px | 258 px | 252 px | 4 |
| 280 px | 218 px | 217 px | 4 |
| 240 px | 178 px | 175 px | 5 |

`scrollWidth` und `clientWidth` der Quellenzeile stimmen in allen vier Breiten
überein; der Trenner `↔` bleibt jeweils in der Quellenzeile.
Die Testdaten werden nur ins DOM injiziert und nicht in SQLite geschrieben. Die
Zusammenfassung meldet `Claims 4× geprüft` (250 % bei 360, 320 und 280 px
sowie zusätzlich 240 px in normaler Schrift) sowie
`Langhost 114 (114 Zeichen) 4× geprüft`. Beide Klartextzähler stehen in
derselben Zusammenfassungszeile, sind nur für Menschen lesbar und kein
CI-Gate.
Verbindlich sind die Zähler `claims: 4` und `langhost114: 4` im Check-Manifest
sowie die expliziten IDs `text250.claims.<breite>` und
`text250.langhost114.<breite>` im maschinenlesbaren Ergebnis. Damit ist der
Extremfall ohne Punkt oder Bindestrich unabhängig von der Claim-Zusammenfassung
im Ergebnis nachweisbar.

Gezielt nur die Spider-Quellenzeile prüfen:

```bash
node scripts/pruefe-text250.mjs --ansichten spider --breiten 360,320,280
```

Der Aufruf prüft die vier Langhost-Fälle bei 360, 320 und 280 px sowie die
zusätzliche 240-px-Claim-Prüfung in normaler Schrift. Erwartet werden Exit-Code 0,
`Claims 4× geprüft`, `Langhost 114 (114 Zeichen) 4× geprüft` und die Zeile
`240px/spider: OK · Seite 240px · Kopf 240/240 · Navigation 240/240`.
Die Belastbarkeitsgrenze und der separate 240-px-Aufruf sind oben dokumentiert.

Zusätzlich prüft der Lauf bei 240, 280 und 360 px in jeder Ansicht die
Geometrie: Steuerelemente mit verstecktem Überlauf dürfen ihren Inhalt nicht
abschneiden, statisch positionierte Steuerelemente innerhalb desselben
Bausteins dürfen sich nicht überlappen, und der Tastaturfokus muss einen
sichtbaren Ring zeigen. Gemessen werden DOM-Rechtecke
und berechnete Stile; Screenshot-Goldens werden dafür nicht verwendet. Die
Fälle `text250.geometrie.<breite>` und der Manifest-Zähler `geometrie`
(36 im Profil `voll`, 6 im Seed-Profil) belegen, dass die Prüfung tatsächlich
lief.

Für Strategien, Research, das Raumschiff, Agentenraum und Konferenz gleicht der
Lauf zusätzlich die Kerndaten mit `/api/report` ab: Zahl und Namen der
bestandenen Strategien, markierte Auswahl, fünf KPIs und die fünf Kernzeilen;
die sechs Research-Stationen mit ihren Nummern und den aus dem Bericht
berechneten Zahlen; die elf sichtbaren Schiffsabteilungscluster A–J und S samt
Vollständigkeit und erwarteter Agentenzahl (A–J je zehn, S drei); die acht
Tabs der bisherigen Agentenraum-Inhaltsprüfung (nicht die elf Schiffsabteilungen) mit Agentenzahl, Kopfzeile
und den letzten 40 Aktivitäten; schliesslich die vier Konferenz-Panels mit Beschluss, Modus,
Berichten, Diskussion und Massnahmentabelle. Bei den Massnahmen vergleicht er
jede Zelle mit dem API-Feld, damit auch ein bewusst leerer Verantwortlicher
korrekt als leer erkannt wird. Die Zusammenfassung meldet
`Inhalte 15× geprüft` (fünf Ansichten × drei Breiten).

Der separate Aufruf `--negativtest` lädt die betroffenen sechs Ansichten, prüft
zuerst den sauberen Zustand und schreibt dann absichtlich falsche Kerndaten
ins DOM: einen falschen Strategie-KPI, eine falsche Research-Kandidatenzahl,
eine falsche Agenten-Kopfzahl, einen entfernten Abteilungstab im Agentenraum,
einen entfernten sichtbaren Schiffsabteilungscluster, einen geleerten
Schiffscluster, einen fehlenden Agenten in einem Schiffscluster, einen
zusätzlichen Agenten in einem zweiten Schiffscluster, eine doppelte Agenten-ID
über Cluster hinweg, eine doppelte Agenten-ID im selben Cluster bei
unveränderter Agentenzahl, einen falschen Konferenz-Testplan sowie in der
Claim-Karte einen entfernten Widerspruchsgrund und eine entfernte
Widerspruchssicherheit. Drei weitere Fälle prüfen die Geometrie am
Agentenraum: abgeschnittener Inhalt, überlappende statische Steuerelemente und
ein fehlender Fokusring müssen jeweils den passenden Befund auslösen. Jeder
Fall läuft unter einer stabilen Fall-ID und muss einen Befund auslösen; der
unveränderte Zustand davor muss dagegen ohne Befund bleiben. Die CI verlangt
deshalb `Negativtest OK: 16/16` sowie die Zähler `negativtest: 16` und
`negativFehler: 0` aus dem Manifest, damit weder ein
übersprungener noch ein durch einen anderen ersetzter Fall und auch kein
Prüfer, der unveränderte Zustände als Befund meldet, grün durchgeht.

### Reproduktion des 16/16-Negativtests

Der Lauf braucht eine frische Seed-Kopie, ein laufendes Dashboard und
Playwright-Chromium. Er verändert nur das DOM; die Seed-Kopie und die
API-Antworten werden nicht verändert. Im ersten Terminal:

```bash
cp seed/orakel-seed.db /tmp/orakel-negativtest.db
ORAKEL_DB_PFAD=/tmp/orakel-negativtest.db \
  python -m orakel serve --host 127.0.0.1 --port 3400
```

Im zweiten Terminal aus dem Repository-Wurzelverzeichnis:

```bash
npm ci --prefix scripts
npm --prefix scripts exec playwright install chromium

node scripts/pruefe-text250.mjs --negativtest \
  --url http://127.0.0.1:3400
```

Der Lauf muss mit Exit-Code 0 enden und folgende Zeile ausgeben:

```text
Negativtest OK: 16/16 falsche Inhalte erkannt
```

Fehlen lokal die Chromium-Systembibliotheken, kann zuerst das
[lokale Playwright-Setup](#lokales-playwright-setup-ohne-systemrechte)
ausgeführt und die Umgebung mit `source .playwright-local/env.sh` aktiviert
werden. Der Negativtest benötigt keine zusätzliche Testdatenbank und schreibt
keine Daten in die Seed-Kopie.

Der Standardlauf umfasst alle zwölf Ansichten inklusive der weiterhin geprüften
Inhaltsansichten Agentenraum, Konferenz und Raumschiff. Der CI-Job
`text250` setzt auf dem `ubuntu-24.04`-Image auf: Chromium wird ohne
`--with-deps` installiert, die nötigen Systembibliotheken kommen aus dem Image.
Auch ein leerer Playwright-Cache funktioniert; der Browser wird dann frisch
geladen. Installation und Prüflauf haben je ein Step-Timeout von 5 Minuten; das
Job-Limit liegt bei 15 Minuten. Serverlog und Screenshots lädt der Job auch bei
Fehlschlag, Abbruch oder Timeout hoch und bewahrt sie 7 Tage auf. Screenshots
entstehen nur bei Befunden. Ein eigener Step `Seed-Tastaturlauf` startet eine
frische Seed-Kopie auf Port 3100 und prüft die fünf Stichproben bei 360, 320
und 280 px ausschliesslich über Home, Pfeil rechts und Ende. Zusätzlich prüft er
die elf Schiffscluster samt erwarteter Agentenzahl, die Gesamtsumme von 103
Agenten, eindeutige Agenten-IDs und die Ops-Abteilungslegende (elf Einträge,
kompakter Kopf, eingeklappt und per Tastatur aufklappbar). Er verlangt in der
Ausgabe `Tastatur 3× geprüft`, `Inhalte 3× geprüft`, `Agenten 3× geprüft`,
`Legende 3× geprüft` und `Desktop-Legende 1× geprüft`, damit ein stilles
Überspringen als Fehler auffällt.

```bash
# Dashboard mit Beispieldaten starten, ohne die eigene DB anzufassen
cp seed/orakel-seed.db /tmp/orakel-text250.db
ORAKEL_DB_PFAD=/tmp/orakel-text250.db python -m orakel serve --port 3000

# Einmalig: Abhängigkeit und Browser installieren
npm ci --prefix scripts
npm --prefix scripts exec playwright install chromium

# Prüfen (alle zwölf Ansichten, drei Breiten)
node scripts/pruefe-text250.mjs
```

### Lokales Playwright-Setup ohne Systemrechte

In einer frischen Ubuntu-24.04-Umgebung (amd64) fehlen Chromium oft die
nötigen Laufzeitbibliotheken und Fonts. Das Setup-Skript lädt die Pakete als
`.deb` herunter, entpackt sie in das ignorierte Verzeichnis `.playwright-local/`
und richtet `LD_LIBRARY_PATH` sowie Fontconfig ein. Es installiert nichts
systemweit, benötigt kein `sudo` und prüft am Ende den Chromium-Start und die
geladenen Font-Metriken:

```bash
bash scripts/setup-playwright-local.sh
source .playwright-local/env.sh
```

Die Aktivierung mit `source` erfolgt aus dem Projektverzeichnis. Das Skript
erwartet `apt-get`, `dpkg-deb`, `npm` und Node.js >= 20. Die heruntergeladenen
Pakete liegen nur in `.playwright-local/`; dieses Verzeichnis wird nicht
versioniert.

Die Seed-Kurve der neuesten US500-Validierungen beginnt bewusst mit zwei
unterschiedlichen Punkten (USD 100'000 und 100'100). Damit prüft der Status-Test
bei Pfeil rechts im CI eine echte Textänderung.

Einschränken lässt sich der Lauf mit `--ansichten lab,kb --breiten 360,280`,
die Adresse mit `--url http://127.0.0.1:8000`, Tabellen mit `--ohne-tabellen`.
Mit `--bilder <verzeichnis>` schreibt der Lauf bei Befunden je Ansicht und
Breite einen Screenshot, den HTML-Zustand der betroffenen Ansicht und die
konkreten Befunde in `text250-befunde.txt`. Mit
`--bild-praefix <name>` erhalten diese Dateien einen Namenspräfix; der
Seed-Tastaturlauf nutzt `seed-tastatur-`, damit seine Diagnosen im gemeinsamen
Artefakt nicht die Namen des Hauptlaufs überschreiben. Schiffscluster-Befunde
erhalten eigene Bildnamen wie
`320px-ship-cluster-01-abteilung-b-hat-11-statt-10-agenten.png`; mit Präfix
entsprechend `seed-tastatur-320px-ship-cluster-01-...png`. Ein CI-Selbsttest
entfernt absichtlich Cluster S und einen Agenten aus Cluster A, erzeugt damit
mehrere gleichzeitige Cluster-Befunde, schreibt seine Diagnose mit dem Präfix
`selbsttest-` und verlangt für jeden Befund einen eigenen, nicht leeren
Screenshot mit eindeutigem Namen sowie die Befunde in
`selbsttest-text250-befunde.txt`. Ein eigener CI-Schritt prüft zusätzlich, dass
mindestens zwei Clusterbefunde im selben Lauf eigene, nicht-leere
Screenshotdateien mit eindeutigen Namen erhalten haben. Ein zweiter Selbsttest (`--selbsttest-agent`)
entfernt gezielt einen Agenten aus Cluster A und verlangt den Befund samt Screenshot
`selbsttest-agent-...-abteilung-a-hat-9-statt-10-agenten.png`. In GitHub Actions
läuft derselbe Prüflauf als eigener
Job `text250` der Workflow-Datei `.github/workflows/tests.yml`; bei Erfolg lädt
er `lauf.log`, `negativtest.log` und das maschinenlesbare `ergebnis.json`
kompakt als Artefakt `text250-laufprotokoll` hoch. Schlägt er fehl, lädt er
Bilder, Befundtexte und HTML als Artefakt `text250-diagnose` und das
Serverprotokoll als `text250-serverlog` hoch (je 7 Tage).

Der Lauf schreibt mit `--ergebnis artifacts/text250/ergebnis.json` ein
JSON-Ergebnis mit stabilen Fall-IDs und den tatsächlichen Zählern im Feld
`counters`. Enthält der Seed-Bericht keine Validierungen, bricht der Lauf vor
der Inhaltsprüfung mit Exit-Code 1 ab, statt leer zu bestehen; die Meldung nennt
`ORAKEL_DB_PFAD` und die Seed-Datenbank als Prüfpunkte. CI prüft es mit `scripts/pruefe-text250-ergebnis.mjs` gegen das
Check-Manifest `scripts/text250-required-checks.json` (Schema
`text250-check-manifest.v2`). Das Manifest nennt je Profil – `voll`,
`seed-tastatur`, `negativtest`, `selbsttest-cluster` und `selbsttest-agent` –
die erwarteten Zähler, die Pflichtfall-IDs und optional erlaubte Skips. CI
vergleicht jeden erwarteten Zähler mit dem tatsächlichen Wert (zum Beispiel
`refresh: 2` oder `langhost114: 4`) und scheitert ausserdem an fehlenden
Pflichtfällen und an jedem unerwarteten Skip, also einem Fall mit
`status: skipped`, den das Profil nicht ausdrücklich in `allow_skips` nennt.
Der Checker sichert diese Logik mit `--selbsttest` selbst ab: Ein Skip aus
`allow_skips` muss akzeptiert, ein Skip ausserhalb der Liste muss als
unerwartet erkannt werden; der text250-CI-Job führt den Selbsttest vor der
Manifestprüfung aus.
Zu den Pflichtfällen des Profils `voll` gehören die zwölf 240-px-Ansichten,
die vier Claim-Breiten, der 114-Zeichen-Langhost ohne Punkt oder Bindestrich,
der Lab-Auto-Refresh bei 360 und 280 px mit HTTP 200, sichtbarem Kopfmarker,
unverändert gezeichneter Lab-Liste und erneutem Rendern nach Fokusverlust, die
beiden Lab-Fokus-Varianten sowie die direkte Guard-Prüfung, der Pausenhinweis,
die Listen-Umsortierung und der Refresh-Takt. Die Klartextzeilen im Laufprotokoll wie
`Claims 4×` oder `Refresh 2×` sind nur für Menschen lesbar und kein Gate.

### CI auf Feature-Branches ohne Pull Request

Ein Push auf einen Branch startet den Workflow `Tests` direkt; ein offener Pull
Request ist dafür nicht nötig. `main` bleibt eingeschlossen, damit Railway sein
"Wait for CI" weiterhin erkennt. Bei Branches mit offenem Pull Request entsteht
dadurch zusätzlich zum PR-Lauf ein Push-Lauf. Zusätzlich ist der Workflow
manuell startbar, sobald diese Fassung auf `main` und im gewählten Branch
liegt:

```bash
gh workflow run tests.yml --ref ci/negativtest-13
```

GitHub bietet `workflow_dispatch` erst an, wenn die Workflow-Datei auf dem
Default-Branch existiert; auch der gewählte Branch muss den Trigger enthalten.
Für bereits gepushte Commits löst der neue Push-Trigger nicht rückwirkend aus.
Der manuelle Lauf testet die Spitze des angegebenen Branches.

Nach einem fehlgeschlagenen, abgebrochenen oder abgelaufenen Lauf. Die Befehle
setzen eine angemeldete GitHub CLI voraus (`gh auth login`):

```bash
# Letzte Läufe des Workflows anzeigen
gh run list --workflow tests.yml --limit 5

# Serverlog und Diagnose (Screenshots + Befunde + HTML) des gewünschten Laufs herunterladen
gh run download <run-id> -n text250-serverlog -D "artifacts/text250-ci-<run-id>"
gh run download <run-id> -n text250-diagnose -D "artifacts/text250-ci-<run-id>"

# Vollständiges Job-Log anzeigen (alle Jobs, inklusive text250)
gh run view <run-id> --log

# Job-ID des text250-Jobs ermitteln und nur dessen Log ansehen
gh run view <run-id> --json jobs --jq '.jobs[] | select(.name=="text250") | .databaseId'
gh run view <run-id> --job <job-id> --log

# Nur fehlgeschlagene Schritte dieses Jobs ansehen
gh run view <run-id> --job <job-id> --log-failed
```

Die Dateien landen im laufspezifischen Verzeichnis
`artifacts/text250-ci-<run-id>`; Screenshots gibt es nur bei Befunden.
Vorhandene ältere Downloads unter `artifacts/text250-ci/` sind mit
`VERALTET.md` markiert und kein aktueller Beleg.

## Phase 5–11: was jetzt zusätzlich läuft

### Spider Intelligence (Phase 5)

```bash
python -m orakel spider          # RSS-Quellen abrufen und prüfen
```

- Prüft **robots.txt** vor jedem Abruf, hält `min_abstand_sekunden` pro Host ein.
- Nur frei zugängliche RSS-Feeds (Notenbanken, Presse, Marktnachrichten) — keine Paywalls,
  keine Umgehung von Nutzungsbedingungen.
- Quellenqualität als **offengelegte Heuristik** (Domain, Textlänge, Zahlen, Sensationswörter),
  keine KI-Bewertung.
- Dubletten über URL **und** Titel-Hash; jeder Artikel behält Quelle und Link.
- Ohne Netzwerkzugang bricht nichts: Der Lauf meldet Fehler und arbeitet weiter.

### Paper-Trading im Dauerbetrieb (Phase 7)

```bash
python -m orakel paper           # ein Takt
python -m orakel daemon          # Dauerbetrieb (Takt + Mitternachtskonferenz)
python -m orakel serve --takt    # Dashboard + Takt im Hintergrund
```

Der Takt führt ein **virtuelles Konto in SQLite**: Einstiege über die ausgewählten Strategien,
Stops innerhalb der Kerze, Ausstieg per Signal, Kommission und Slippage, Kontostand je Takt.
Ein Symbol, das in einem Takt per Stop geschlossen wurde, wird in diesem Takt nicht sofort
wieder gekauft. Es verlässt keine Order den Rechner.

### Weltkugel und Raumschiff (Phase 10–11)

Zwei neue Ansichten im Dashboard, vollständig aus echten Daten:

- **Weltkugel**: Handelsplätze je Symbol, Kurs, 24-h-Änderung, ATR, Regime und Korrelationen
  (letzte 500 Kerzen). Die Kugel ist Darstellung — die Zahlen kommen aus SQLite.
- **Raumschiff**: Pixel-Art-Agenten-Querschnitt mit 103 Company-Agentenräumen in elf
  Abteilungen (A–J und S), Zoom/Pan und rechter Detailspalte. Ein Klick öffnet Rolle,
  Status und Aufgabe; Agentenraum und Konferenz liegen als Gemeinschaftsräume im
  Schiff, die bisherigen Panels bleiben eingeklappt erhalten. Unter 1100 px
  Viewportbreite gilt die kompakte 1500-px-Bühne, ab 1100 px der 2400-px-Grossmodus
  mit 150/180/270 px hohen Räumen, 48-px-Türen und der reicheren Anhang-Pixelkunst.
  Beim Wechsel wird das Schiff neu gezeichnet und neu eingepasst.

### Grenzen dieser Phasen (ehrlich)

- Der Spider bewertet Quellen nach Heuristik, **nicht** inhaltlich durch ein Sprachmodell.
  Er sammelt und ordnet; er zieht keine Handelsentscheidung daraus.
- Die 2D-Welt ist eine Datenansicht, **kein** 3D-Spiel. Der Meister-Prompt erlaubt das
  ausdrücklich, wenn 3D mit den Ressourcen nicht sinnvoll ist.
- Das Paper-Konto ist eine Simulation in SQLite. Echte Kurse und echte Ausführung kommen
  erst über MT5 auf deinem Windows-Rechner.
