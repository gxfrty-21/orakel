# 24-Stunden-Soak – Abnahmekriterien und Bericht

**Stand:** 15. November 2026
**Geltung:** Dauerbetrieb der Orakel-Engine
**Werkzeuge:** `scripts/soak_monitor.py`, `scripts/soak_abnahme.py`

---

## 1. Zweck und Grenze

Der Soak beantwortet eine andere Frage als die Testsuite: Bleibt der Betrieb
über einen vollständigen Tag stabil, ohne dass Takt, Jobs, Speicher oder
Datenbank unbemerkt aus dem Rahmen laufen?

Es gibt zwei getrennte Nachweise:

| Nachweis | Was er zeigt | Was er nicht zeigt |
|---|---|---|
| **Simulation** (`--simulieren`) | Scheduler, Persistenz, Backoff und Ressourcenlogik über 24 h virtuelle Zeit | Keine Wanduhr-, Netzwerk- oder Prozessstabilität |
| **Wanduhr-Soak** (`soak_monitor.py`) | Echtes Verhalten über 24 h mit Health- und Tiefen-Samples | Keine vollständige Code-/Sicherheitsprüfung |

**Nur der abgeschlossene Wanduhr-Soak ist eine Betriebsabnahme.** Die
Simulation ist ein reproduzierbarer Vorabtest und darf nicht als echter
24-Stunden-Lauf bezeichnet werden.

## 2. Reproduktion

### 2.1 Simulation ohne Wartezeit

```bash
python scripts/soak_abnahme.py --simulieren \
  --output-dir artifacts/soak-simulation
```

Erzeugt:

- `artifacts/soak-simulation/report.md`
- `artifacts/soak-simulation/messwerte.json`

Die Simulation verwendet eine virtuelle Uhr, 288 Fünf-Minuten-Takte und
deterministische Stub-Jobs. Sie öffnet keine Netzwerkverbindung und ruft keinen
Broker auf. Der Bericht wird nur bei vollständiger Erfüllung aller Kriterien
mit `BESTANDEN` abgeschlossen.

### 2.2 Echter 24-Stunden-Lauf

Voraussetzungen:

1. Der gewünschte Commit ist deployt.
2. `ORAKEL_TAKT=1` ist auf dem Zielhost gesetzt; `/api/health` meldet den Takt.
3. Railway-/SSH-Zugang für die Tiefen-Samples ist vorhanden, falls
   `soak_monitor.py` den vollständigen Betriebszustand abrufen soll.
4. Unter `/data/backups` liegt ein lesbares SQLite-Backup
   (`orakel-*.db`); der Monitor prüft eine Kopie und die Integrität.
5. Es werden keine Zugangsdaten, Tokens oder personenbezogenen Daten in den
   Bericht übernommen.

Start:

```bash
python scripts/soak_monitor.py \
  --duration-hours 24 \
  --interval-seconds 60 \
  --deep-interval-seconds 600 \
  --output-dir artifacts/soak-24h
```

Der Monitor ist wiederaufsetzbar und schreibt fortlaufend:

- `artifacts/soak-24h/health.jsonl`
- `artifacts/soak-24h/betrieb.jsonl`
- `artifacts/soak-24h/summary.md`
- `artifacts/soak-24h/monitor-status.json` beim Ende, mit `regulaer`,
  `abbruch`, `abbruch_grund` und der gemessenen Dauer

Für eine automatische Abnahme nach dem Monitor-Ende kann ein separater
Watcher gestartet werden. Er wartet auf die Monitor-PID und ruft danach
`soak_abnahme.py` auf:

```bash
MONITOR_PID=<pid-des-monitors>
nohup python scripts/soak_auto_abnahme.py \
  --monitor-pid "$MONITOR_PID" \
  --verzeichnis artifacts/soak-24h \
  > artifacts/soak-24h/abnahme-watcher.log 2>&1 &
```

Der Watcher schreibt `abnahme-status.json` mit `exit_code`, `bestanden` und
den Pfaden zu Bericht und Messwerten. Sein Exit-Code entspricht dem der
Abnahme; ohne bestandene Abnahme ist er `1`.

Der Watcher unterscheidet ein **reguläres Ende** von einem **vorzeitigen
Abbruch**:

- Bei einem regulären Ende startet er die Abnahme und setzt
  `monitor_ausgang: "regulaer"` sowie `abnahme_gestartet: true`.
- Bei einem vorzeitigen Monitor-Ende setzt er
  `monitor_ausgang: "abgebrochen"`, `abnahme_gestartet: false` und
  `exit_code: 1`. Die Abnahme wird dann nicht gestartet; der Grund steht in
  `monitor_abbruch_grund`.
- Für ältere Monitore ohne `monitor-status.json` schätzt der Watcher die
  Laufzeit aus `health.jsonl` und wertet einen zu kurzen Lauf als Abbruch.

Die Tiefen-Samples werden mit `scripts/soak_probe.py` auf dem Zielhost
erzeugt. Die Probe liest nur; sie prüft Audit-Kette, Company-Queue und eine
Kopie des neuesten Backups in einem temporären Verzeichnis.

Nach dem Lauf:

```bash
python scripts/soak_abnahme.py --verzeichnis artifacts/soak-24h
```

Er erzeugt `artifacts/soak-24h/report.md` und `messwerte.json`. Der Exit-Code ist
`0`, wenn alle Kriterien bestanden sind, sonst `1`.

### 2.3 Separater Backoff-Fehlerfall

Der Backoff-Mechanismus wird absichtlich mit zwei aufeinanderfolgenden
kontrollierten Fehlern geprüft. Dieser Lauf ist **kein Teil der sauberen
Soak-Abnahme** und verändert weder `artifacts/soak-24h/` noch deren Kriterien:

```bash
python scripts/backoff_fehlerfall.py \
  --output-dir artifacts/backoff-fehlerfall
```

Er erzeugt `report.md` und `messwerte.json`. Der Bericht zeigt:

- erster Spider-Lauf scheitert,
- Backoff wird auf 60 s gesetzt,
- bei +30 s läuft der Job nicht,
- bei +61 s scheitert auch der zweite Lauf,
- der Backoff verdoppelt sich auf 120 s,
- bei +180 s läuft der Job noch nicht,
- bei +182 s läuft er erfolgreich,
- der Fehlerzähler wird zurückgesetzt.

Der Exit-Code ist `0`, wenn diese Erwartung vollständig erfüllt ist.

## 3. Abnahmekriterien

Alle Kriterien sind **harte Kriterien**. Ein einzelner Fehler führt zu
`NICHT BESTANDEN`; Durchschnittswerte dürfen einen Ausfall nicht verdecken.

### 3.1 Wanduhr-Soak

| Kriterium | Schwelle | Begründung |
|---|---:|---|
| Laufzeit | ≥ 23,5 h | Ein 24-h-Lauf darf nicht als Kurztest durchgehen |
| Health-Samples | ≥ 1380 | Bei 60-s-Intervall fehlen höchstens ca. 60 Samples |
| Health-Fehler | ≤ 5 | Einzelne Netz-Hänger sind tolerierbar, kein Dauerausfall |
| Maximale Health-Lücke | ≤ 180 s | Der Takt darf nicht länger unbemerkt stehen |
| Taktstatus | durchgehend `laeuft` | Kein `aus` oder `ueberfaellig` nach dem Start |
| Commit | genau 1 Commit | Kein unbemerkter Wechsel während der Messung |
| Paper-Ticks | ≥ 288 verschiedene Zeitpunkte | Mindestens ein Takt alle fünf Minuten |
| Letzter Paper-Tick | ≤ 300 s vor dem letzten Health-Sample | Der Takt darf am Ende nicht stehen |
| Tiefen-Samples | alle erfolgreich | Audit-, Queue- und Backup-Prüfung brauchen vollständige Daten |
| Job-Fehler | 0 | Kein Job darf in den Backoff laufen |
| Job-Backoff | 0 s | Kein verdeckter Fehler-/Wartezyklus |
| Ressourcen-Skips | 0 | Kein Job darf wegen DB/RSS/Speicher pausiert werden |
| Fehlerhafte Jobläufe | 0 | Keine `fehler`-Einträge im Jobprotokoll |
| Audit-Kette | alle Tiefen-Samples `ok` | Keine unbemerkte Manipulation oder Lücke |
| Company-Queue | 0 Dead-Letter, 0 Blocked, max. Alter ≤ 3600 s | Queue darf nicht dauerhaft verstopfen |
| Backup-Restore | Backup vorhanden, `integrity_check` ok, Probe-Restore ok, Alter ≤ 48 h | Sicherung ist lesbar und aktuell |
| DB-Wachstum | < 512 MB | Produktives `max_db_mb`-Limit |
| Prozess-RSS | < 768 MB | Produktives `max_rss_mb`-Limit |
| Freier Speicher | > 256 MB | Produktives `min_freier_speicher_mb`-Limit |

### 3.2 Simulation

Die Simulation prüft zusätzlich deterministisch:

| Kriterium | Schwelle |
|---|---:|
| Virtuelle Dauer | 24,00 h |
| Takte | exakt 288 |
| Taktstatus | 288/288 `ok` |
| Takt-Monitor | `laeuft` |
| Job-Fehler / Backoff / Skips | je 0 |
| DB / RSS / freier Speicher | innerhalb der produktiven Grenzen |
| Spider-Zeitplan | genau 0, 6, 12 und 18 Uhr |
| Fünf-Minuten-Jobs | je 288 Läufe |
| Health-Simulation | 1440 Samples, maximale Lücke 60 s |

Die Queue-Altersmessung der Simulation verwendet einen **absichtlich offenen
synthetischen Task**. Der Wert zeigt, dass die Alterskennzahl funktioniert; er
ist kein Nachweis über eine reale Produktionsqueue. Der Wanduhr-Monitor erfasst
die echte Company-Queue in jedem Tiefen-Sample. Die Simulation prüft die
Audit-Kette, aber keinen Backup-Restore.

## 4. Bericht und Nachweise

Ein abgeschlossener Wanduhr-Soak wird mit folgenden Dateien abgelegt:

```text
artifacts/soak-24h/
  health.jsonl
  betrieb.jsonl
  summary.md
  report.md
  messwerte.json
```

Der Bericht enthält:

- Ergebnis `BESTANDEN` oder `NICHT BESTANDEN`
- Commit und Messzeitraum
- eine Tabelle aller Kriterien mit Messwert und Status
- die Rohwerte als JSON
- die Grenzen der Aussage

`summary.md` bleibt die ausführliche Verlaufsdarstellung; `report.md` ist die
formale Abnahme. Beide werden nicht versioniert, weil sie Messdaten und
Laufzeitinformationen enthalten können. `report.md` weist zusätzlich
Health-Lücken, Backoff, Audit-Status, Queue-Alter, Backup-Integrität und
DB-Wachstum aus.

## 5. Was der Soak nicht abdeckt

- **Audit-Kette:** Sie wird in jedem Tiefen-Sample geprüft, aber nicht bei
  jedem Health-Abruf.
- **Company-Queue:** Dead-Letter, Blocked und das maximale Alter offener
  Aufgaben werden geprüft; Lease-Recovery und einzelne Retry-Pfade nicht.
- **Backoff-Fehlerfall:** Der gezielte Fehlerfall in
  `artifacts/backoff-fehlerfall/` belegt zwei aufeinanderfolgende Fehler und
  die Verdopplung des Backoffs, ist aber kein Teil der sauberen
  24-Stunden-Abnahme.
- **Backup und Restore:** Geprüft wird eine Kopie des neuesten Backups
  (`integrity_check` und Lesbarkeit). Ein vollständiges Live-Rollback oder ein
  Restore-Test mit Dienstneustart ist damit nicht bewiesen.
- **Broker/Order:** Es gibt keinen Broker-Aufruf; Paper-only wird durch die
  bestehenden Invariantentests geschützt.
- **Externe Dienste:** Ein Ausfall von Railway, GitHub oder Healthchecks ist
  kein Beweis für einen Fehler der Engine, verhindert aber die Abnahme.
- **Safari/Hardware:** Der Soak ist kein Browser- oder Gerätetest.

## 6. Umgang mit einem Fehlschlag

1. `report.md` und die fehlgeschlagenen Kriterien sichern.
2. Ursache aus `summary.md`, `health.jsonl` und `betrieb.jsonl` bestimmen.
3. Keine Kriterien nachträglich lockern, um den Lauf zu retten.
4. Fix umsetzen und den **vollständigen** 24-Stunden-Lauf wiederholen.
5. Erst danach `BESTANDEN` dokumentieren.

Ein Lauf mit fehlenden Tiefen-Samples ist nicht bestanden, auch wenn die
Health-Werte gut aussehen. Ohne Tiefen-Samples sind Job-Fehler, Backoff,
Ressourcen-Skips, Audit-Kette, Company-Queue und Backup-Restore nicht belegbar.
