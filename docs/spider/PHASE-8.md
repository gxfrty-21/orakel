# Phase 8 — Dauerbetrieb, Zeitplan, Backoff und Monitoring

**Stand:** 10. November 2026
**Grundlage:** `orakel/betrieb.py`, `orakel/scheduler.py`, `orakel/db.py`,
`orakel/web.py`, `orakel/web/static/app.js`, `config.toml`

---

## 1. Was jetzt passiert

Der bisherige Takt führte bei jedem Durchlauf alle Schritte aus; der Spider
lief nur einmal beim Start. Phase 8 macht daraus einen persistenten Plan:

```text
Takt (60 s)
  ├─ paper         jeder Takt
  ├─ konferenz     jeder Takt, führt nur einmal pro Tag wirklich aus
  ├─ spider        alle 6 h (konfigurierbar), mit Backoff
  ├─ intel         jeder Takt
  ├─ missionen     jeder Takt, max. 5 Aufgaben
  └─ unternehmen   nur wenn [unternehmen].aktiv = true, stündlich
```

Jeder Job hat einen nächsten Versuch in `zustand["betrieb_status"]`. Nach
einem Fehler wächst die Wartezeit exponentiell:

```text
60 s → 120 s → 240 s → … → max. 3600 s
Spider:                    max. 21600 s
```

Der Zustand steht in SQLite und überlebt einen Neustart. Ein bereits
erfolgreich ausgeführter Job wird nicht durch einen Neustart sofort erneut
ausgelöst. Ein Job mit Intervall `0` ist bewusst bei jedem Takt fällig.

Der Spider wird nicht mehr nur beim Prozessstart ausgelöst. Beim ersten Takt
ist er fällig, danach nach seinem Intervall. Der Start mit `--mit-spider`
erzwingt ihn weiterhin sofort.

## 2. Ressourcenlimits

`[betrieb]` enthält harte Grenzen:

| Grenze | Standard | Wirkung |
|---|---:|---|
| `max_db_mb` | 512 | schreibintensive Jobs pausieren |
| `max_rss_mb` | 768 | schreibintensive Jobs pausieren |
| `min_freier_speicher_mb` | 256 | schreibintensive Jobs pausieren |
| `max_takt_sekunden` | 240 | keine weiteren Jobs im selben Takt starten |
| `max_laeufe` | 1000 | altes Jobprotokoll wird gekürzt |

Als schreibintensiv gelten Spider und Company-Schicht. Paper, Konferenz,
Intelligence und Missionen laufen weiter, damit der Betrieb nicht wegen einer
einzelnen Grenze vollständig stehen bleibt. Die Entscheidung wird als
`uebersprungen` mit Grund protokolliert; es wird kein Erfolg vorgetäuscht.

Wichtig: `max_takt_sekunden` kann einen bereits laufenden Python-Aufruf nicht
gewaltsam abbrechen. Die Grenze verhindert nur, dass danach weitere Jobs
starten. Für einen harten Abbruch bräuchte es einen separaten Worker-Prozess;
das ist nicht Teil dieser Phase.

## 3. Monitoring

### `GET /api/betrieb` (hinter Login)

Liefert:

- Taktstatus `laeuft`, `ueberfaellig` oder `aus`, letzter Takt und Dauer,
- jeden Job mit Intervall, nächstem Versuch, Fehlversuchen und Backoff,
- DB-, RSS- und Speicherwerte samt Limits,
- die letzten 20 Job-Läufe,
- Zähler der letzten 24 Stunden,
- Warnungen mit Stufe und Grund.

`GET /api/health` bleibt ohne Login erreichbar und enthält zusätzlich eine
kompakte `betrieb`-Zeile. Der Health-Endpunkt bleibt bewusst `200`, solange
der Webserver antwortet; ein Job-Backoff darf keinen Container-Neustart-Loop
auslösen.

### CLI

```bash
python -m orakel betrieb
python -m orakel betrieb --json
```

### Dashboard

Der Navigationspunkt **Betrieb** zeigt Taktstatus, Zeitplan, Ressourcenbalken,
die letzten Job-Läufe und alle Warnungen. Er fragt alle 30 Sekunden neu ab.
Die Anzeige ist ein Spiegel von `/api/betrieb`; sie erfindet keine Entwarnung.

### Jobprotokoll

Jeder Lauf landet in `betrieb_laeufe`:

```text
zeit, job, status (ok | fehler | uebersprungen), dauer_ms, fehler, details
```

Die Tabelle ist die auswertbare Logquelle. Sie wächst nur bis `max_laeufe`.
Fachdaten wie Artikel, Claims, Missionen oder Paper-Trades werden davon nicht
berührt.

## 4. Starten

Dauerbetrieb bleibt **opt-in**:

```bash
python -m orakel serve --takt
# oder im Container:
ORAKEL_TAKT=1
```

Ohne diese Option läuft nur der Webserver; der Betrieb zeigt dann ehrlich
`aus`. Das ist Absicht, damit ein reiner Dashboard-Start keine ungefragten
Netzabrufe und Paper-Takte auslöst.

Der separate Befehl `python -m orakel daemon` nutzt denselben Plan und ist für
einen Vordergrund-/systemd-Betrieb gedacht.

## 5. Tests und Prüfungen

```text
pytest -q                         185 passed
python -m compileall -q orakel tests
node --check orakel/web/static/app.js
node --check orakel/web/static/nexus3d.js --input-type=module
git diff --check
```

Neu in `tests/test_betrieb.py`:

1. **24-Stunden-Simulation:** 288 Fünf-Minuten-Takte; der Spider läuft genau
   um 0, 6, 12 und 18 Uhr, nicht bei jedem Takt.
2. **Backoff über Neustart:** Fehler wird gespeichert, ein neuer `Betrieb`
   wartet den Backoff ab und startet erst danach wieder.
3. **Ressourcengrenze:** Ein zu großes DB-Limit überspringt den Spider, der
   Job wird als `uebersprungen` protokolliert.
4. **Monitoring:** Limits, DB-Wert, Taktstatus und Jobhistorie sind vorhanden.

API-Smoke-Test mit temporärer SQLite-Datenbank:

```text
/api/health  → 200, ok=true, betrieb.jobs=5
/api/betrieb → Jobs paper/konferenz/spider/intel/missionen,
               Limits, Ressourcen, letzte_laeufe
CLI betrieb  → Takt aus, 5 Jobs, Ressourcen, letzte 24 h
```

## 6. Ehrliche Grenzen

- **Kein echter 24-Stunden-Dauerlauf wurde abgewartet.** Geprüft ist eine
  simulierte 24-Stunden-Schleife mit echtem SQLite-Zustand, nicht ein Tag
  Wanduhrzeit. Der reale Nachweis bleibt ein Betriebs-Soak.
- **`ORAKEL_TAKT` ist im Railway-Deploy weiterhin `0`.** Die Funktion ist
  eingebaut, aber nicht stillschweigend für die Produktion aktiviert.
- **Ein Prozess, ein SQLite-Writer.** Der Takt ist ein Daemon-Thread; es gibt
  keine verteilten Worker und keine horizontale Skalierung.
- **Kein externes Alerting.** Warnungen stehen in SQLite, API und UI. Ein
  Dead-man's-Switch für den Takt selbst ist nicht angeschlossen; der
  bestehende Nachtlauf hat dafür seinen eigenen Healthchecks-Pfad.
- **RSS ist Spitzenwert.** `ru_maxrss` ist der Spitzenverbrauch des Prozesses,
  kein momentaner Livewert. Das Limit schützt trotzdem vor weiterem Wachstum.
- **Keine CPU- oder Netzwerkquote pro Job.** Die vorhandenen Limits aus
  `[spider]` (Artikel, Seiten, Timeout, Host-Abstand) gelten weiter.
- **Der Takt kann nicht unterbrochen werden.** Siehe `max_takt_sekunden`.
- **Keine erfundenen Jobs.** Der Plan ruft ausschließlich bestehende
  Funktionen auf. Ohne Missionen entstehen keine Missionen; ohne Quellen
  entstehen keine Artikel.
- **Desktop-Breite der neuen Betriebsansicht** wurde nicht visuell geprüft,
  solange die Cloud-Browser-Steuerung keinen Desktop-Viewport liefert.

## 7. Nächster Schritt

Phase 8 ist lokal umgesetzt und getestet. Für einen echten Dauerbetrieb sind
zwei getrennte Entscheidungen nötig:

1. `ORAKEL_TAKT=1` auf dem Zielhost setzen und einen kurzen Soak beobachten.
2. Einen externen Watchdog für den Takt ergänzen, damit ein stehender Prozess
   nicht nur im Dashboard sichtbar ist.

Paper-Trading, Risikogrenzen und der Nachtlauf bleiben unverändert.
