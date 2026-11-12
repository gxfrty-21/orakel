# Orakel Trading-Engine

[![CI: Tests](https://github.com/gxfrty-21/orakel/actions/workflows/tests.yml/badge.svg)](https://github.com/gxfrty-21/orakel/actions/workflows/tests.yml)

Daytrading-System mit MetaTrader-5-Anbindung, Richter, Paper-Trading und Web-Dashboard.
Grundlage ist dein Meister-Prompt (Abschnitte 1–12) und dein Orakel-Design.

**Dieses Projekt handelt ausschliesslich Paper.** Es existiert kein Codepfad zu einer
echten Broker-Order: Der MT5-Broker verweigert Echtgeldkonten und sendet ohne
`order_freigabe = true` nur einen Probelauf.

**Raumschiff-Doku:** [docs/raumschiff/README.md](docs/raumschiff/README.md)
— Planung und aktueller 2D-Stand (drei Decks, acht Abteilungen, Meetingraum, Sekretariat).

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
3D-Welt, keine Company-API, keine LLM-Anbindung und keine echten Orders.

## Dauerbetrieb mit Login und HTTPS

Fertige Docker-Konfiguration mit Caddy (automatisches TLS), HTTP-Basic-Login und
persistentem SQLite-Speicher im `/data`-Volume: siehe [DEPLOY.md](DEPLOY.md).

Für Railway ohne eigenen Server, Caddy oder eigene Domain: siehe
[RAILWAY.md](RAILWAY.md).

### Phase 8: Dauerbetrieb und Monitoring

Der Hintergrund-Takt ist bewusst **opt-in** (`serve --takt` oder
`ORAKEL_TAKT=1`). Er plant Paper-Takt, Konferenz, Spider (standardmäßig alle
sechs Stunden), Intelligence, Missionen und optional die Company-Schicht.
Fehler erhalten einen persistenten exponentiellen Backoff; DB-, RSS- und
Speichergrenzen pausieren schreibintensive Jobs, statt den Prozess volllaufen
zu lassen. Jeder Lauf wird in `betrieb_laeufe` protokolliert.

```bash
python -m orakel betrieb           # Plan, Backoff, Ressourcen, letzte Läufe
python -m orakel betrieb --json    # vollständige Monitoringdaten
```

Im Dashboard gibt es dafür den Punkt **Betrieb**; die geschützte API liegt
unter `GET /api/betrieb`. `/api/health` bleibt offen und nennt nur eine
kompakte Betriebszeile. Details und ehrliche Grenzen:
[docs/spider/PHASE-8.md](docs/spider/PHASE-8.md).

Unter Windows zusätzlich `pip install MetaTrader5` (nur dort verfügbar) und in
`config.toml` `[paper] broker = "mt5"` setzen. MT5 muss laufen und mit dem
**Demo-Konto** eingeloggt sein.

## Was hier schon echt funktioniert

| Baustein | Zustand |
|---|---|
| Fakten-Datenbank (SQLite) | Kerzen, Validierungen, Trades, Entscheide, Ereignisse, Konto, Agentenläufe, Konferenzen |
| Datenprüfung | Lücken, Doppelungen, unmögliche Hoch/Tief, Preissprünge, Mindestmenge |
| Backtest | Kerze für Kerze, Ausführung zur Folge-Eröffnung, ATR-Stop, Gaps, Kommission, Slippage |
| Richter | Training/Out-of-Sample, Walk-Forward, Monte-Carlo, Nachbar-Parameter, Zufallsvergleich |
| Risiko | 1 % je Trade bis Stop, 10 % Not-Stop, max. 15 Positionen, Engagement, Bargeld, Korrelation |
| Broker-Schicht | `CsvBroker` (Paper-Replay), `MockBroker`, `MT5Broker` (Windows, Paper-Sperre) |
| Agenten | 80 bestehende Agenten in 8 Abteilungen, jeder mit echter Aufgabe und Ergebnis in der DB |
| Company-Schicht | Phase 1: 103 Profile, SQLite-Queue mit Lease/Retry, Policy-Engine, Audit-Kette; 3D/API noch nicht |
| Konferenz | 00:00 Europe/Zurich, Nachholen verpasster Termine, Protokoll im Vault |
| Wissenszentrum | Obsidian-Vault mit Frontmatter, Tags, `[[Links]]` |
| Dashboard | Orakel-Design, 12 Ansichten, Live-Polling, 2D-Raumschiff, «Lauf starten» |
| Dauerbetrieb | persistenter Plan, Backoff, Ressourcenlimits, Jobprotokoll und Betriebsansicht |

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
  brokers.py     Broker-Schnittstelle (CSV / Mock / MT5)
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
4. **Dauerbetrieb aktivieren**: `ORAKEL_TAKT=1` ist gesetzt; der 24-Stunden-Soak
   läuft. Der externe Watchdog ist in `.github/workflows/watchdog.yml` angelegt
   und prüft nach dem Push auf `main` den Takt alle fünf Minuten.
5. **Selbstlernen**: Auswertung abgeschlossener Trades inkl. Fehleranalyse.

## Grundsätze im Code

- Kein Look-Ahead: Signal an Kerze *i*, Ausführung zur Eröffnung von *i+1*.
- Kosten und Slippage in jedem Backtest.
- Der Richter ist fest verdrahtet; keine KI ändert seine Regeln.
- Jede Zahl im Dashboard stammt aus SQLite — nichts wird geschätzt oder erfunden.

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
- **Raumschiff**: 2D-Deck mit den acht Abteilungen, Belegung je Raum, Befunde farbig,
  Klick öffnet die Agentenliste und die Rohrpost des Laufs.

### Grenzen dieser Phasen (ehrlich)

- Der Spider bewertet Quellen nach Heuristik, **nicht** inhaltlich durch ein Sprachmodell.
  Er sammelt und ordnet; er zieht keine Handelsentscheidung daraus.
- Die 2D-Welt ist eine Datenansicht, **kein** 3D-Spiel. Der Meister-Prompt erlaubt das
  ausdrücklich, wenn 3D mit den Ressourcen nicht sinnvoll ist.
- Das Paper-Konto ist eine Simulation in SQLite. Echte Kurse und echte Ausführung kommen
  erst über MT5 auf deinem Windows-Rechner.
