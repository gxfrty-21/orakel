# Review-Dossier Orakel

**Stand:** 27. November 2026, Commit `43c110c8caed738f1bb454d014ead7d669347ba7`
(`main`; die Messung lief bei sauberem Arbeitsbaum).
**Zweck:** Eine externe KI soll das Repository realistisch einschätzen und die
schwächsten Bereiche identifizieren. Dieses Dossier liefert dafür Architektur,
Randbedingungen, gemessene Zahlen, Dateipfade und konkrete Prüfaufträge.
**Keine Note, keine Selbstbewertung:** Die Rangfolge in Abschnitt 6 ist eine
belegte Kandidatenliste, keine feststehende Wahrheit. Prüfe sie gegen den Code.

## 0. Auftrag an die reviewende KI

Lies zuerst dieses Dossier, dann die in Abschnitt 7 genannten Dateien. Bewerte
**nicht** nach Eindruck, sondern nach:

1. **Korrektheit und Risiko:** Kann ein Fehler Geld, Daten oder Vertrauen
   beschädigen?
2. **Evidenz:** Ist der Bereich durch automatisierte Tests, echte Hardware
   oder nur durch Behauptungen abgesichert?
3. **Änderungsrisiko:** Wie groß ist die Fläche, die ein Eingriff berührt?
4. **Betriebsrisiko:** Was passiert bei Absturz, Neustart, Netzfehler,
   Gleichzeitigkeit und falscher Konfiguration?

Liefere pro Befund: Datei und Zeile, Beobachtung, Severity (`S1` kritisch bis
`S4` kosmetisch), Konfidenz, kleinste sinnvolle Korrektur, notwendigen Test und
verbleibendes Risiko. Trenne ausdrücklich zwischen **belegt**, **plausibel** und
**ungeprüft**. Übernimm keine Zahl aus diesem Dossier ungeprüft; die
Reproduktionsbefehle stehen in Abschnitt 8.

## 1. Harte Randbedingungen

Diese Grenzen sind Projektregeln und dürfen durch Verbesserungen nicht
abgeschwächt werden (vollständig in [AGENTS.md](../AGENTS.md)):

- **Paper-only.** Es gibt keinen Codepfad zu einer echten Broker-Order;
  `order_freigabe` bleibt `false`. Fehlende Broker-Orders sind kein Mangel.
- **SQLite ist die einzige Wahrheit** für Zahlen. Fehlende Daten bleiben leer
  und werden nicht geschätzt oder erfunden.
- Kein Look-Ahead, Kosten und Slippage in Backtests, fest verdrahteter Richter.
- Oberflächentexte und Dokumentation sind deutsch.
- Keine Secrets, Tokens oder Zugangsdaten in Code, Doku, Commits oder Logs.
- Bestehende Tests nicht abschwächen, nicht überspringen und nicht mit
  Unterdrückungen grün machen. Ursache beheben.
- Keine Commits, Pushes, Merges oder Deployments ohne ausdrückliche Anweisung.
- `main` ist geschützt; Änderungen laufen über Branch und Pull Request.

## 2. System in Kurzform

Orakel ist eine Paper-Trading-Engine mit SQLite-Faktenbasis, Handelskern,
Web-Dashboard und mehreren additiven Schichten:

| Schicht | Pfad | Aufgabe |
|---|---|---|
| Handelskern | `orakel/kern/` | Daten, Backtest, Richter, Risiko, Paper-Takt, Metriken |
| Konfiguration | `orakel/config.py` | TOML, Grenzen, Laufzeitpfade |
| Oberfläche | `orakel/web.py`, `orakel/web/` | FastAPI-Endpunkte, Dashboard, Statik |
| Betrieb | `orakel/betrieb.py`, `orakel/scheduler.py`, `orakel/watchdog.py` | Takt, Wartung, Wächter |
| Company | `orakel/company/` | Agenten, Aufgaben, Nachrichten, Audit |
| Nexus/Spider | `orakel/nexus/`, `orakel/spider.py` | Research, Feeds, Claim-Bewertung |
| Zulieferung | `orakel/pipeline.py`, `orakel/intel.py`, `orakel/seed.py` | Daten und Research |
| Datentransport | `scripts/transport_client.py`, `orakel/transport.py` | CSV-Export aus MT5 und Server-Import |

Der Datenfluss ist im Kern:

```text
MT5/CSV -> datenimport -> SQLite (kerzen, datenimporte)
        -> Strategien -> Backtest -> Richter -> Risiko -> Paper-Takt
        -> Bericht/Dashboard
```

Die Architekturgrenze ist erzwungen: Der Kern darf nur `orakel.kern.*` und
`orakel.config` importieren. Geprüft wird sie durch `.importlinter` im
CI-Job **Architektur** und zusätzlich durch `tests/test_architektur.py`.
Details: [ARCHITEKTUR-KERN.md](ARCHITEKTUR-KERN.md).

## 3. Messumgebung

| Feld | Wert |
|---|---|
| Betriebssystem | Windows 11 (Build 10.0.26300), AMD64 |
| Python | 3.12.10 im lokalen `.venv` |
| CPUs | 14 |
| Messzeitpunkt | 27.11.2026, Commit `43c110c` |
| Suite | 797 Tests, 151,84 s Wanduhrzeit |
| Datenbank | SQLite, WAL, ein schreibender Prozess |

Die Laufzeit ist maschinen- und cacheabhängig. Sie ist keine Zusage für CI
oder Produktion.

## 4. Gemessene Fakten

Alle Werte wurden auf dem genannten Commit mit den Befehlen aus Abschnitt 8
erhoben. Coverage zählt Statements, nicht Verhalten.

### 4.1 Tests und Coverage

| Kennzahl | Wert |
|---|---|
| Tests | **797 bestanden**, 0 fehlgeschlagen, 0 übersprungen |
| Testdateien | 72 |
| Statements gesamt (`orakel/` + `scripts/`) | 14.412 |
| Coverage gesamt | **76,93 %** |
| Coverage der vier Kernmodule zusammen | **93,03 %** |
| CI-Untergrenze Kern | 85 % |
| Skip-/Xfail-Marker in Tests | 0 |

Kernmodule im Einzelnen:

| Modul | Coverage | Statements |
|---|---:|---:|
| `orakel/kern/paper.py` | 94,9 % | 256 |
| `orakel/kern/risk.py` | 89,7 % | 87 |
| `orakel/kern/backtest.py` | 96,8 % | 156 |
| `orakel/kern/judge.py` | 90,3 % | 290 |

Niedrige Coverage außerhalb des Kerns (nur Dateien ab 40 Statements):

| Datei | Coverage | Statements | fehlende Zeilen |
|---|---:|---:|---:|
| `scripts/seed_widerspruch.py` | 0,0 % | 53 | 53 |
| `scripts/backoff_fehlerfall.py` | 0,0 % | 86 | 86 |
| `scripts/soak_monitor.py` | 41,8 % | 232 | 135 |
| `orakel/scheduler.py` | 42,9 % | 70 | 40 |
| `scripts/soak_abnahme.py` | 46,2 % | 238 | 128 |
| `orakel/web.py` | 47,0 % | 568 | 301 |
| `orakel/sekretariat.py` | 48,7 % | 450 | 231 |
| `scripts/messe_synthetisch.py` | 50,0 % | 274 | 137 |
| `scripts/pruefe_doku.py` | 54,3 % | 337 | 154 |
| `orakel/watchdog.py` | 54,8 % | 93 | 42 |
| `orakel/agents.py` | 61,6 % | 268 | 103 |
| `orakel/pipeline.py` | 65,2 % | 287 | 100 |
| `orakel/company/handlers.py` | 68,7 % | 246 | 77 |
| `scripts/transport_client.py` | 76,7 % | 970 | 226 |
| `orakel/transport.py` | 85,1 % | 276 | 41 |

Sieben Dateien mit mindestens 40 Statements liegen unter 50 % Coverage.

### 4.2 Statische Prüfungen

| Prüfung | Ergebnis |
|---|---|
| `ruff check .` | **All checks passed** (Exit 0) |
| `mypy` | **Success: no issues found in 4 source files** (Exit 0) |
| Doku-Prüfung | **OK**: 36 Dateien inkl. diesem Dossier, 108 relative Links, 8 Ankerlinks, 0 Befunde |
| `git diff --check` | Exit 0 |

Die grünen Prüfungen sind kein Beweis für Typ- oder Fehlerfreiheit:

- mypy prüft nur `paper.py`, `risk.py`, `backtest.py`, `judge.py` und deren
  Kernimporte. Web, Company, Nexus, Scheduler und Skripte bleiben außen vor.
- ruff nutzt eine **Schuldenliste**: 24 `per-file-ignores`-Einträge (19
  Module in `orakel/`, 4 Soak-Skripte, `tests/**`) sowie 102
  `noqa`-Kommentare. Neue blinde Fänge außerhalb der Liste lassen die CI
  scheitern; der Altbestand bleibt erlaubt.
- Es gibt keine Abhängigkeitsprüfung (`pip-audit` oder vergleichbar). Das
  steht selbst in [QUALITAET.md](QUALITAET.md).

### 4.3 Struktur und Größe

| Kennzahl | Wert |
|---|---|
| Versionierte Dateien (Mess-Commit) | 282 |
| Python-Dateien | 148 |
| Python-Zeilen | 43.129 |
| Testdateien | 72 |
| JavaScript / ES-Module | 21 / 9 |
| CSS / HTML | 10 / 1 |
| SQL-Migrationen | 12 (6 hoch, 6 zurück) |
| Markdown-Dateien (Mess-Commit) | 35 |

Größte Python-Dateien:

| Datei | Zeilen |
|---|---:|
| `orakel/kern/db.py` | 1.544 |
| `scripts/transport_client.py` | 1.349 |
| `tests/test_data.py` | 1.218 |
| `scripts/baue_review_paket.py` | 1.056 |
| `orakel/web.py` | 930 |
| `orakel/__main__.py` | 826 |
| `orakel/sekretariat.py` | 783 |
| `orakel/company/api.py` | 764 |
| `orakel/kern/data.py` | 752 |

Längste Funktionen (nur `orakel/`):

| Funktion | Zeilen | Ort |
|---|---:|---|
| `create_app()` | 751 | `orakel/web.py:180` |
| `baue_globe()` | 383 | `orakel/globe.py:259` |
| `lauf()` | 273 | `orakel/pipeline.py:237` |
| `tick()` | 251 | `orakel/kern/paper.py:243` |
| `backtest()` | 212 | `orakel/kern/backtest.py:28` |
| `sicherstellen_daten()` | 179 | `orakel/pipeline.py:37` |
| `nachtlauf()` | 167 | `orakel/nexus/nacht.py:196` |

29 Funktionen in `orakel/` sind mindestens 80 Zeilen lang.

### 4.4 CI und Repository-Zustand

- CI-Jobs in `.github/workflows/tests.yml`: `pytest`, `architektur`, `doku`,
  `review_paket`, `docker`, `text250`, `widerspruch_e2e`, `touch`, `ruff`,
  `mypy`, `coverage` (plus `changes`).
- Der PR #304 hatte auf `285b232` **25/25 erfolgreiche Check-Runs**
  (0 übersprungen, 0 Fehler). Auf `main` @ `43c110c` ist der Tests-Workflow
  erfolgreich.
- Offene GitHub-Issues: **keine** (Stand 27.11.2026).
- Bei der Messung keine uncommitteten Änderungen; `main` = `origin/main`.

## 5. Was belastbar abgesichert ist

Diese Bereiche sind nicht perfekt, aber deutlich besser belegt als der Rest:

- **Handelskern:** 93,03 % Coverage, mypy, Architekturvertrag und gezielte
  Tests für Backtest, Richter, Risiko und Paper-Takt.
- **Datenbankmigrationen:** Anwenden, Teilstände, Rollback, Sicherung und
  Altbestände sind in [MIGRATIONEN.md](MIGRATIONEN.md) und
  `tests/test_migrationen.py` beschrieben.
- **Container und Login:** Der Docker-Job baut das Image, startet es, prüft
  `/api/health` und dass `/` ohne Zugangsdaten `401` und mit Zugangsdaten
  `200` liefert.
- **Oberfläche:** `text250` prüft 250-%-Schrift und lange Komposita,
  `widerspruch_e2e` prüft einen Drei-Fall-Negativtest, `touch` prüft
  Ein-Finger-Pan, Pinch und Tippen per CDP.
- **Doku und Review-Paket:** Relative Links, Anker und Begriffe werden
  geprüft; das Review-Paket wird byteweise gegen den Commit verifiziert.

Wichtig: Das sind automatisierte Nachweise. Sie ersetzen **keine** echte
Windows-/MT5-Hardware und keinen echten Broker-Export.

## 6. Kandidaten für die schwächsten Bereiche

Reihenfolge nach Schaden bei Fehlverhalten, Größe der unbelegten Fläche und
Änderungsrisiko. Die Einschätzung ist bewusst konservativ; prüfe jede Zeile.

### 6.1 Reale Datenstrecke Windows/MT5 — höchstes Risiko

**Befund:** Der Transportclient ist mit 1.349 Zeilen und 970 Statements der
zweitgrößte Python-Baustein, hat 76,7 % Coverage und ist nur mit Fake-MT5,
injiziertem HTTP und einem Loopback-Stub getestet. Die reale Abnahme auf
Windows mit MT5, Broker-Symbolen, Zeitzonen und Abnahme-Server ist **nicht
ausgeführt**. Das steht offen in [ABNAHME-PR-302.md](ABNAHME-PR-302.md).

**Warum kritisch:** Ohne verlässlichen Tagesimport hat der Rest des Systems
keine echten Daten. Fehler in Retry, Zustand, Quarantäne, Zeitzone oder
Scheduler führen nicht zu einem Absturz, sondern zu fehlenden oder falschen
Blöcken — und damit zu falschen Kennzahlen.

**Belege:** `scripts/transport_client.py`, `scripts/windows_transport_task.ps1`,
`tests/test_transport_client.py`, `tests/test_transport_client_state.py`,
`tests/test_windows_transport_task.py`, [TRANSPORT-WINDOWS.md](TRANSPORT-WINDOWS.md).

**Konkrete Prüffragen:**

- Sind alle Zustandsübergänge (`vorbereitet`, `wartend`, `erfolgreich`,
  `erfolgreich_degraded`, `blockiert`, `quarantaene`) idempotent und
  crash-sicher?
- Kann ein halber Tag, ein falscher Tag oder ein doppelter Block hochgeladen
  werden? Was verhindert das genau?
- Stimmen Zeitumrechnung, Sommerzeit und `server_versatz_stunden` in allen
  Pfaden überein?
- Ist das Retry-Budget (2 pro Lauf, 6 insgesamt) unterbrochen werden sicher?
- Was passiert bei `401`, `409`, `429`, `503`, `500` und Verbindungsabbruch —
  jeweils mit Zustand, Exit-Code und Datei?
- Ist der Scheduler-Trockenlauf (`-WhatIf`) wirklich frei von Nebenwirkungen?

### 6.2 Web-/UI-Schicht — große Fläche, wenig direkte Tests

**Befund:** `orakel/web.py` hat 930 Zeilen, 568 Statements und nur 47,0 %
Coverage. `create_app()` ist mit 751 Zeilen die längste Funktion im Projekt.
Die UI-Tests laufen mit Chromium/CDP; echte Safari-/iPad-Hardware ist laut
[IPHONE-SAFARI-CHECKLISTE.md](raumschiff/IPHONE-SAFARI-CHECKLISTE.md) weiterhin
manuell offen.

**Warum wichtig:** Die Web-Schicht enthält Authentifizierung, schreibende
API-Endpunkte, SSE und die Darstellung aller Kennzahlen. Ein Fehler hier kann
Daten offenlegen, Aktionen auslösen oder Zahlen falsch anzeigen.

**Belege:** `orakel/web.py`, `orakel/web/static/`, `tests/test_web.py`,
`tests/test_company_api.py`, `tests/test_api_vertrag_live.py`.

**Konkrete Prüffragen:**

- Welche Routen sind ohne Login erreichbar, welche nicht? Ist jeder
  schreibende Endpunkt serverseitig validiert und protokolliert?
- Gibt es CSRF-, XSS-, Session- oder Pfad-Traversal-Lücken?
- Werden Fehler intern vollständig, nach außen aber ohne Pfade/SQL/Secrets
  ausgegeben?
- Ist `create_app()` sinnvoll zerlegbar, ohne Verhalten zu ändern, und welche
  Tests sichern die Zerlegung?
- Sind die UI-Aussagen durch die Seed-Daten gedeckt, oder können leere Daten
  als echte Kennzahlen erscheinen?

### 6.3 Hintergrundbetrieb und Company-Lauf — schwache Coverage

**Befund:** `orakel/scheduler.py` hat 42,9 %, `orakel/sekretariat.py` 48,7 %,
`orakel/company/handlers.py` 68,7 % Coverage. Der Betrieb läuft im
Hintergrund, schreibt in SQLite und muss Absturz, Neustart, Doppelstart und
Backoff aushalten.

**Warum wichtig:** Fehler treten hier zeitversetzt und ohne Nutzerinteraktion
auf. Ein doppelter Lauf, ein verlorener Auftrag oder eine nicht atomare
Buchung ist schwer zu bemerken und schwer zu reparieren.

**Belege:** `orakel/scheduler.py`, `orakel/lauf_queue.py`,
`orakel/sekretariat.py`, `tests/test_lauf_queue.py`, `tests/test_betrieb.py`.

**Konkrete Prüffragen:**

- Wie wird verhindert, dass zwei Prozesse denselben Auftrag ausführen?
- Was passiert bei Absturz mitten in einer Buchung oder zwischen zwei
  Tabellenupdates? Wo liegt die Transaktionsgrenze?
- Sind Zeitpläne, Backoff und Aufbewahrung unter Sommerzeit und Neustart
  korrekt?
- Ist die Audit-Kette lückenlos, auch bei Fehlern?

### 6.4 Typ- und Lint-Schulden außerhalb des Kerns

**Befund:** mypy prüft vier Kernmodule. 24 `per-file-ignores` und 102
`noqa`-Kommentare erlauben breite Fänge und stilles Schlucken im Altbestand.
Das ist bewusst als Schuldenliste dokumentiert, aber es verdeckt Fehler.

**Warum wichtig:** Genau die Module mit schwacher Coverage (Web, Scheduler,
Sekretariat) sind auch typ- und lint-mäßig kaum abgesichert. Fehler werden
dort später und teurer gefunden.

**Belege:** `mypy.ini`, `ruff.toml`, [QUALITAET.md](QUALITAET.md).

**Konkrete Prüffragen:**

- Welche der 24 Ausnahmen verdecken echte Fehlerpfade, welche sind berechtigt?
- Welche Module würden von einer schrittweisen Typisierung am meisten
  profitieren?
- Gibt es `except Exception`-Pfade, die einen Fehler loggen, aber den Lauf
  fälschlich als Erfolg beenden?

### 6.5 Hotspots und Kopplung

**Befund:** `orakel/kern/db.py` hat 1.544 Zeilen, `transport_client.py` 1.349,
`web.py` 930. Die längsten Funktionen liegen bei 751, 383 und 273 Zeilen.
Große Dateien sind nicht automatisch schlecht, erschweren aber Review,
Testisolation und sichere Änderungen.

**Belege:** Tabelle in Abschnitt 4.3; `git log` ist squash-geprägt, daher sind
Hotspots nicht über Commit-Häufigkeit gemessen.

**Konkrete Prüffragen:**

- Welche Verantwortlichkeiten in `db.py` und `web.py` sind vermischt?
- Welche Zerlegung bringt Testbarkeit, ohne öffentliche APIs zu brechen?
- Wo sind Globals, Caches oder implizite Reihenfolgen die eigentliche Gefahr?

### 6.6 Skalierung und Performance — nur synthetisch belegt

**Befund:** [BENCHMARK.md](BENCHMARK.md) beschreibt reproduzierbare
Synthetik-Messungen, aber keine echte Marktlast. [ROBUSTHEIT.md](ROBUSTHEIT.md)
nennt 516 s für 500 Läufe mit 100.000 Kerzen (rund 8,6 min) und eine nahezu
lineare Skalierung. Der vollständige Lauf mit echten Daten, vielen Symbolen
und Richter-Kandidaten ist nicht gemessen.

**Warum wichtig:** Langsame oder speicherhungrige Pfade können den Tageslauf
in den nächsten Tag schieben; ein voller Takt mit echten Daten ist der
Realbetrieb.

**Belege:** `scripts/messe_synthetisch.py`, `docs/BENCHMARK.md`,
`docs/ROBUSTHEIT.md`, `orakel/kern/robustheit.py`.

**Konkrete Prüffragen:**

- Welche Abfragen scannen große Tabellen ohne Index?
- Wo wird die gesamte Kerzenreihe oder ein DataFrame unnötig kopiert?
- Ist der Speicherbedarf bei 2,1 Mio. Zeilen und mehreren Symbolen tragbar?
- Welche Messung fehlt, um die Behauptung „linear“ zu widerlegen?

### 6.7 Lieferkette und Abhängigkeiten

**Befund:** Die Abhängigkeiten sind exakt gepinnt, aber es gibt keine
automatisierte Schwachstellenprüfung. Das steht offen in
[QUALITAET.md](QUALITAET.md).

**Konkrete Prüffragen:**

- Welche gepinnten Versionen haben bekannte CVEs?
- Welche Abhängigkeit ist für die Kernfunktion wirklich nötig?
- Wie würde ein Update ohne vollständige Suite abgesichert?

### 6.8 Doku-Drift — kleines, aber reales Prozessrisiko

**Befund:** Die Doku-Prüfung kontrolliert Links, Anker und Begriffe, aber
nicht, ob genannte Commit-Hashes, CI-Zahlen oder erwartete Werte noch zum
Code passen. Genau dort war die N9-Abweichung (`server_code`) zuletzt
auffällig.

**Konkrete Prüffragen:**

- Welche Doku nennt konkrete Hashes, Testzahlen oder CI-Ergebnisse?
- Welche davon sind reproduzierbar und welche nur historisch?
- Lohnt ein Prüfskript für erwartete Werte aus Code und Doku?

## 7. Empfohlene Lesereihenfolge

1. [AGENTS.md](../AGENTS.md) und [README.md](../README.md) — Grenzen und
   Systemüberblick.
2. [ARCHITEKTUR-KERN.md](ARCHITEKTUR-KERN.md) — erzwungene Trennung.
3. `orakel/kern/backtest.py`, `orakel/kern/judge.py`,
   `orakel/kern/risk.py`, `orakel/kern/paper.py` — Handelslogik.
4. `scripts/transport_client.py` und [TRANSPORT-WINDOWS.md](TRANSPORT-WINDOWS.md)
   — reale Datenstrecke.
5. `orakel/web.py` und `orakel/web/static/js/` — Oberfläche und Auth.
6. `orakel/scheduler.py`, `orakel/lauf_queue.py`, `orakel/sekretariat.py` —
   Hintergrundbetrieb.
7. `orakel/kern/db.py`, `orakel/kern/migrationen.py`,
   [MIGRATIONEN.md](MIGRATIONEN.md) — Datenwahrheit und Schema.
8. [QUALITAET.md](QUALITAET.md), [ROBUSTHEIT.md](ROBUSTHEIT.md),
   [BENCHMARK.md](BENCHMARK.md) — was das Qualitätstor nicht prüft.

## 8. Reproduktion der Messwerte

Windows (Git Bash, Projektwurzel):

```bash
.venv/Scripts/python.exe -m pytest -q --cov=orakel --cov=scripts --cov-report=term-missing
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy
.venv/Scripts/python.exe scripts/pruefe_doku.py
git diff --check
```

Linux/macOS im Projekt:

```bash
.venv/bin/python -m pytest -q --cov=orakel --cov=scripts --cov-report=term-missing
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
.venv/bin/python scripts/pruefe_doku.py
git diff --check
```

Erwartete Größenordnung auf dieser Maschine: 797 Tests in rund 150 s,
Gesamt-Coverage 76,93 %, Kern 93,03 %. Abweichungen sind möglich und selbst
ein Prüfpunkt.

## 9. Offene Datenlücken

Diese Punkte konnte oder sollte dieses Dossier nicht belegen:

- **Keine reale Windows-/MT5-Abnahme:** Hardware, Brokerdaten,
  Abnahme-Server und Token fehlen; der Scheduled Task wurde nur mit `-WhatIf`
  geprüft. Siehe [ABNAHME-PR-302.md](ABNAHME-PR-302.md).
- **Keine Safari-/iPad-Hardware:** Chromium- und WebKit-Emulation sind kein
  Ersatz; die Checkliste bleibt offen.
- **Keine Produktionslast:** Alle Performancewerte sind synthetisch.
- **Keine Schwachstellenprüfung der Abhängigkeiten.**
- **Keine Aussage über Strategiequalität:** Das Dossier bewertet Technik und
  Evidenz, nicht Rentabilität. Der Strategie-Nachweis ist ein eigenes,
  offenes Ziel ([ARCHITEKTUR-KERN.md](ARCHITEKTUR-KERN.md), Abschnitt
  „Feature-Stopp“).
- **Keine echte Issue-Historie:** Es gibt derzeit keine offenen Issues; das
  ist kein Beweis für Fehlerfreiheit.

## 10. Was nicht als Schwäche zählt

Damit die Bewertung nicht an bewussten Entscheidungen vorbeigeht:

- Paper-only und fehlende Broker-Orders sind Absicht, kein Rückstand.
- SQLite und eine einzelne Instanz sind bewusst gewählt; horizontale
  Skalierung ist ausdrücklich ausgeschlossen ([DEPLOY.md](../DEPLOY.md)).
- Fehlende 3D-Welt, LLM-Anbindung und echte Orders sind bekannte Grenzen.
- Deutsche Oberfläche und deutsche Doku sind Projektvorgabe.
- Fehlende Daten werden leer angezeigt; das ist korrekt und keine
  „fehlende Kreativität“.
