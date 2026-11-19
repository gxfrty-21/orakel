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

## Schnellstart

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# 1) Daten: synthetisch (Test der Abläufe) ...
.venv/bin/python -m orakel daten --kerzen 6000
# ... oder echte MT5-Historie importieren:
.venv/bin/python -m orakel daten --csv daten/EURUSD_M15.csv --symbol EURUSD

# 2) Vollständiger Lauf: Daten → Research → Richter → Risiko → Plan → Bericht
.venv/bin/python -m orakel pruefen

# 3) Dashboard (Bericht live aus der Fakten-Datenbank)
.venv/bin/python -m orakel serve --port 8000

# 4) Company-Schicht (Phase 1): 103 Profile, Queue, Policy, Audit-Kette
.venv/bin/python -m orakel unternehmen --status
.venv/bin/python -m orakel unternehmen
```

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

## Dauerbetrieb mit Login und HTTPS

Fertige Docker-Konfiguration mit Caddy (automatisches TLS), HTTP-Basic-Login und
persistentem SQLite-Speicher im `/data`-Volume: siehe [DEPLOY.md](DEPLOY.md).

Für Railway ohne eigenen Server, Caddy oder eigene Domain: siehe
[RAILWAY.md](RAILWAY.md).

### Phase 8: Dauerbetrieb und Monitoring

Der Hintergrund-Takt ist bewusst **opt-in** (`serve --takt` oder
`ORAKEL_TAKT=1`). Er plant Paper-Takt, Konferenz, Spider (standardmäßig alle
sechs Stunden), Intelligence, Missionen und optional die Company-Schicht. Im
laufenden Takt werden zusätzlich offene Quittungen nach Frist erinnert
(`[unternehmen] erinnerungen_intervall_minuten`).
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
| Datenprüfung | Lücken, Doppelungen, unmögliche Hoch/Tief, Preissprünge, Mindestmenge |
| Backtest | Kerze für Kerze, Ausführung zur Folge-Eröffnung, ATR-Stop, Gaps, Kommission, Slippage |
| Richter | Rollierende Walk-Forward-Fenster, versiegelter Holdout, Monte-Carlo, Nachbar-Parameter, Zufallsvergleich |
| Risiko | 1 % je Trade bis Stop, 10 % Not-Stop, max. 15 Positionen, Engagement, Bargeld, Korrelation |
| Paper-Takt | direkte SQLite-Simulation aus Kerzen; kein Broker-Aufruf, keine echten Orders |
| Agenten | 80 bestehende Agenten in 8 Abteilungen, jeder mit echter Aufgabe und Ergebnis in der DB |
| Company-Schicht | Phase 1: 103 Profile, SQLite-Queue mit Lease/Retry, Policy-Engine, Audit-Kette; Company-API für Übersicht, Agenten, Aufgaben, Details, Nachrichten, Räume und Konferenz; Agentenkommunikation mit Threads/Ack und persönliche Gedächtnisse; 2D-Agenten-Querschnitt mit 103 Räumen; 3D noch nicht |
| Konferenz | 00:00 Europe/Zurich, Nachholen verpasster Termine, Protokoll im Vault |
| Wissenszentrum | Obsidian-Vault mit Frontmatter, Tags, `[[Links]]` |
| Dashboard | Orakel-Design, 12 Ansichten, Live-Polling, 2D-Agenten-Querschnitt, «Lauf starten» |
| Dauerbetrieb | persistenter Plan, Backoff, Ressourcenlimits, Jobprotokoll und Betriebsansicht |

Der Holdout ist der letzte Datenblock und wird erst nach der Walk-Forward-Auswahl einmal geöffnet; scheitert er, gibt es keinen Ersatzkandidaten. Im Lab zeigt ein Chart die aggregierte Kapitalkurve der Testfenster; beim Überfahren nennt ein Tooltip Kapitalstand, Veränderung seit dem Start in Prozent, Datum sowie den bisherigen Höchststand mit Abstand in Prozent; per Tastatur (Tab, Pfeiltasten, Home/Ende) ist dieselbe Anzeige erreichbar. dort und in der Strategien-Ansicht lässt sich zudem bei jedem Kandidaten die Liste der Walk-Forward-Fenster aufklappen: Trainings- und Testblock, gewählter Parameter, Trades, Profit Factor und Netto je Fenster.

## Risikogrenzen (deine Vorgaben)

```toml
risk_per_trade_pct = 1.0     # 1 % des Kontos bis zum Stop
max_drawdown_pct   = 10.0    # Not-Stop
max_open_positions = 15      # harter Deckel
```

Zusätzlich konservativ: 3 % Tagesverlust, 100 % Gesamtengagement (kein Hebel),
20 % max. Positionsgrösse, 10 % Mindest-Bargeld.

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

1. **Echte Daten**: MT5-Export oder direkter Abruf auf deinem Windows-Rechner.
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
geändert wurden; andernfalls wird er übersprungen.

### Lokaler Pre-Commit-Hook

Der versionierte Hook `.githooks/pre-commit` startet die Doku-Prüfung, sobald
Markdown-Dateien oder `scripts/pruefe_doku.py` gestaged sind. Ist das Prüfskript
selbst gestaged, führt er zusätzlich den Negativtest `--negativtest` aus. Einmalig
im Repository aktivieren:

```sh
git config core.hooksPath .githooks
```

Ohne relevante Änderungen beendet sich der Hook sofort.

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
bp-Werte mit der gerenderten Widerspruchskarte.

### Lokal reproduzierbar

Voraussetzungen: Python-Umgebung aus `requirements.txt`, Node.js >= 20 und
`curl`. Einmalig Playwright und die Chromium-Systembibliotheken bereitstellen –
ohne diese Bibliotheken scheitert der Browserstart mit
`libnspr4.so: cannot open shared object file`:

```bash
# Einmalig, ohne sudo (Ubuntu 24.04 amd64): Bibliotheken nach .playwright-local/
bash scripts/setup-playwright-local.sh
source .playwright-local/env.sh

# Seed-Kopie, Dashboard auf Port 3300, Positivfall, 3/3-Negativtest und
# Manifest-Prüfung in einem Lauf:
bash scripts/e2e-widerspruch-lokal.sh
```

Das Skript legt eine Seed-Kopie in einem temporären Verzeichnis an, startet
`python -m orakel serve` auf `127.0.0.1:3300`, wartet auf
`/api/nexus/status`, führt beide Prüfläufe samt Manifest-Prüfung aus und beendet
den Server wieder. Die eigene Datenbank bleibt unberührt; ein belegter Port
lässt sich mit `ORAKEL_E2E_PORT=3310` umgehen, eine andere Python-Umgebung mit
`PYTHON=.venv/bin/python`.

Erwartete Ausgabe (Exit-Code 0):

```text
Widerspruch-E2E OK: Claim 1, «Richtung steigt gegen sinkt», e2e-a.example ↔ e2e-b.example, 450 bp ↔ 400 bp
Widerspruch-E2E-Negativtest OK: 3/3 (falsche DOM-Zeile, fehlende DOM-Zeile und fehlende API-Zeile erkannt)
Widerspruch-E2E-Ergebnis OK: 3/3 Pflichtfälle bestanden · negativ 3/3
```

Auf Systemen ohne das Ubuntu-24.04-Setup installiert
`npx --prefix scripts playwright install --with-deps chromium` (mit sudo) die
Bibliotheken systemweit; danach genügt ebenfalls
`bash scripts/e2e-widerspruch-lokal.sh`.

Manuell, wenn Server und Prüfung getrennt laufen sollen:

```bash
cp seed/orakel-seed.db /tmp/orakel-widerspruch.db
python scripts/seed_widerspruch.py /tmp/orakel-widerspruch.db

# Dashboard in einem zweiten Terminal starten:
ORAKEL_DB_PFAD=/tmp/orakel-widerspruch.db python -m orakel serve --host 127.0.0.1 --port 3300

# Im ersten Terminal, nach `source .playwright-local/env.sh`:
node scripts/pruefe-widerspruch-e2e.mjs --url http://127.0.0.1:3300

# Negativtest: verfälscht im DOM den Widerspruchsgrund, entfernt danach
# die Widerspruchszeile und entfernt sie zusätzlich aus einer Kopie der
# API-Antwort; alle drei Fälle müssen als Fehler erkannt werden.
node scripts/pruefe-widerspruch-e2e.mjs --url http://127.0.0.1:3300 --negativtest
```

Der Negativtest verändert keine Datenbank und keine echte API-Antwort. Er prüft,
dass derselbe Kartenprüfer eine falsche Widerspruchszeile und eine fehlende
Widerspruchszeile zuverlässig ablehnt und dass der API-Prüfer eine aus der
API-Antwort entfernte Widerspruchszeile erkennt. Der CI-Job
`Widerspruch-E2E 3/3` führt den positiven Test und den Negativtest auf einer
frischen Seed-Kopie aus. Das
Seed-Skript verweigert eine fehlende Zieldatenbank, damit es nicht versehentlich
eine neue Produktionsdatenbank anlegt.

## Browser-Prüfung bei grosser Schrift

`scripts/pruefe-text250.mjs` skaliert die Schrift im Dashboard auf 250 %
(Faktor 2,5 auf berechnete Schriftgrössen und Zeilenhöhen). Bei 360, 320 und
280 px prüft es, ob Inhalte seitlich aus ihrem Kasten oder aus dem Viewport
laufen. Die Kernaussagen-Karte und die Kopf- und Navigationsleiste werden
zusätzlich bei 240 px in normaler Darstellung geprüft. Die vier KPI-Kacheln
und das Claim-Grid wechseln auf eine Spalte, die Quellenzeile bleibt im
Panel. Kopf und Navigation brechen kompakt um; die Seite scrollt dort nicht
horizontal. **240 px ist für die geprüfte Spider-Seite in normaler
Darstellung unterstützt, aber keine allgemeine Mindestbreite aller Ansichten
und nicht für den vollen 250-%-Lauf zugesagt.** Der separate 250-%-Lauf bei
240 px scheitert an Panel-Kopf und KPI-Beschriftung; 260/270 px haben
ebenfalls Befunde. Die kleinste geprüfte Breite mit vollständigem 250-%-Lauf ist 280 px.

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

Der CI-Schritt verlangt dafür die Zusammenfassung
`240px: 12/12 Ansichten ohne horizontalen Überlauf`.

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
Zusammenfassung meldet `Claims 4× geprüft` (360, 320, 280 und zusätzlich
240 px).

Gezielt nur die Spider-Quellenzeile prüfen:

```bash
node scripts/pruefe-text250.mjs --ansichten spider --breiten 360,320,280
```

Der Aufruf prüft die vier Langhost-Fälle bei 360, 320 und 280 px sowie die
zusätzliche 240-px-Claim-Prüfung. Erwartet werden Exit-Code 0, `Claims 4× geprüft`
und die Zeile `240px/spider: OK · Seite 240px · Kopf 240/240 · Navigation 240/240`.

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
Widerspruchssicherheit. Jeder Fall muss einen Befund auslösen; die CI verlangt
`Negativtest OK: 13/13`, damit die Inhaltsprüfung auch Strukturänderungen im
Agentenraum, am Raumschiff und an den Widerspruchsdetails nicht
stillschweigend übersieht.

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
systemweit, benötigt kein `sudo` und prüft am Ende den Chromium-Start:

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
er `lauf.log` und `negativtest.log` kompakt als Artefakt
`text250-laufprotokoll` hoch. Schlägt er fehl, lädt er Bilder, Befundtexte und
HTML als Artefakt `text250-diagnose` und das Serverprotokoll als
`text250-serverlog` hoch (je 7 Tage).

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
