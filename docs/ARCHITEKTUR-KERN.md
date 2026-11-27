# Architektur: Handelskern und Oberfläche

Der Code ist in zwei Bereiche getrennt: den **Handelskern** unter
`orakel/kern/` und alles, was Oberfläche, Agenten und Betrieb betrifft, unter
`orakel/` (Web, Company, Nexus, Raumschiff, Sekretariat, Spider, Pipeline).

Die Trennung ist nicht nur eine Ordnerkonvention. Sie wird an zwei Stellen
erzwungen:

- `.importlinter` enthält den Vertrag „Handelskern importiert keine UI-,
  Agenten- oder Betriebsmodule“; der CI-Job **Architektur** führt
  `lint-imports` aus.
- `tests/test_architektur.py` prüft dieselbe Grenze ohne Zusatzpaket im
  normalen `pytest`-Lauf. Damit fällt ein Verstoss auch lokal auf, bevor der
  CI-Job überhaupt startet.

## Was gehört wozu

| Bereich | Pfad | Inhalt |
|---|---|---|
| Kern | `orakel/kern/data.py` | Kurse laden, DataFrame aus SQLite |
| Kern | `orakel/kern/datenimport.py` | Gemeinsamer idempotenter CSV-Import für CLI und Ordnerquelle |
| Kern | `orakel/kern/strategies.py` | Signale, ATR, Strategien |
| Kern | `orakel/kern/backtest.py` | Backtest ohne Look-Ahead, Slippage |
| Kern | `orakel/kern/kosten.py` | Kosten je Seite: Kommission pro Stück oder halber Spread |
| Kern | `orakel/kern/judge.py` | Walk-Forward, Holdout, Robustheit |
| Kern | `orakel/kern/risk.py` | Positionsgrösse, Risikostopp |
| Kern | `orakel/kern/mt5_orders.py` | MT5-Orderplanung, Volumenschritt, Stop-Level, bewusst gesperrtes Senden |
| Kern | `orakel/kern/paper.py` | Paper-Takt, Paper-Sperre |
| Kern | `orakel/kern/metrics.py` | Kennzahlen, Drawdown |
| Kern | `orakel/kern/db.py` | Fakten, Abfragen, Startinitialisierung |
| Kern | `orakel/kern/migrationen.py` | Nummerierte Migrationen, Backup, Downgrade |
| Kern | `orakel/kern/markt.py` | Korrelation und Marktbreite für Risiko/Paper |
| Basis | `orakel/config.py` | Konfiguration, Risikogrenzen |
| Oberfläche | `orakel/web.py`, `orakel/web/` | HTTP-Endpunkte, Templates, Statik |
| Oberfläche | `orakel/company/`, `orakel/nexus/` | Agenten, Räume, Sitzungen |
| Betrieb | `orakel/betrieb.py`, `orakel/scheduler.py`, `orakel/watchdog.py` | Takt, Wartung, Wächter |
| Zulieferung | `orakel/spider.py`, `orakel/pipeline.py`, `orakel/intel.py`, `orakel/seed.py` | Research und Datenbeschaffung |

Die Migrationen selbst stehen in `orakel/migrations/` und sind in
[MIGRATIONEN.md](MIGRATIONEN.md) beschrieben.

`markt.py` liegt bewusst im Kern, weil `paper.py` die Korrelation für die
Risikoprüfung braucht. Alles andere aus der Zulieferung bleibt draussen.

## Erlaubte Abhängigkeiten

```
orakel.web, orakel.company, orakel.nexus, orakel.betrieb, ...   (Oberfläche)
                    │  darf importieren
                    ▼
             orakel.kern.*        (Handel)
                    │  darf importieren
                    ▼
             orakel.config        (gemeinsame Basis)
```

Der Kern darf ausschliesslich `orakel.kern.*` und `orakel.config` importieren.
Die Oberfläche darf den Kern nutzen; der Kern niemals die Oberfläche. Ein
Import wie `from ..web import create_app` in `orakel/kern/` bricht den Vertrag
und lässt den CI-Job scheitern.

## Selbst prüfen

```bash
.venv/bin/pip install import-linter==2.17
.venv/bin/lint-imports
.venv/bin/python -m pytest -q tests/test_architektur.py
```

`lint-imports` gibt `Contracts: 1 kept, 0 broken` aus. Der Negativtest ist im
Test enthalten: Eine künstlich eingefügte UI-Importzeile im Kern muss den
Vertrag brechen.

## Feature-Stopp für Oberfläche und Agenten

Bis ein belastbarer Nachweis für die Handelslogik vorliegt, werden **keine
neuen Funktionen** an Agenten, Raumschiff, Nexus, Konferenz oder Sekretariat
gebaut. Grund: Der Kern hat rund 630 Zeilen, der Rest des Projekts ein
Vielfaches davon. Jede Stunde in Simulation fehlt der Handelsqualität.

Erlaubt bleiben:

- Fehlerbehebungen und Sicherheitskorrekturen in allen Bereichen,
- Tests, Doku und Aufräumarbeiten,
- Arbeiten, die den Nachweis der Strategie ermöglichen (Daten, Richter,
  Backtest, Bericht).

Der Nachweis gilt als erbracht, wenn `python -m orakel strategie-bericht`
einen Bericht erzeugt, der für mindestens eine Strategie und ein Instrument
im Holdout-Zeitraum eine positive Netto-Rendite **nach Kosten** gegenüber
„Kaufen und Halten“ zeigt und der Richter sie annimmt. Der Bericht muss als
Beleg im Review-Paket liegen, nicht nur als Behauptung.

Wird der Nachweis nicht erbracht, bleibt der Feature-Stopp bestehen und wird
im Bericht ausdrücklich als Ergebnis festgehalten. Ein negativer Befund ist ein
gültiges Ergebnis; ein weitergebautes UI ohne Nachweis ist es nicht.

Die MT5-Orderplanung in `orakel/kern/mt5_orders.py` ist ausdrücklich kein
Durchbruch dieses Stopps: Sie baut und prüft nur einen Request, sendet ihn
nicht und ersetzt keinen Strategienachweis. Details und die Grenzen der
Abnahme stehen in [MT5-ORDERPFAD.md](MT5-ORDERPFAD.md).
