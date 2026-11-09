# Masterplan — Technik, autonomes Management und Umsetzung

**Status:** P0 und P1 umgesetzt; P2–P7 nicht begonnen  
**Gehört zu:** [README.md](README.md), [RAUMBUCH.md](RAUMBUCH.md), [AGENTEN.md](AGENTEN.md)  
**Grundsatz:** erst echte Unternehmenssubstanz, dann 3D; Paper-only bleibt unverhandelbar.

---

# 1. Technische Architektur

## 1.1 Leitprinzipien

1. **Der Server ist die Wahrheit.** Die 3D-Welt ist eine Ansicht auf Datenbank,
   Tasks und Events. Sie ist nicht die Datenquelle.
2. **Bestehendes weiterverwenden.** FastAPI, SQLite/WAL, Vanilla JavaScript und
   Three.js bleiben. Kein React-Umbau, kein neuer Build-Zwang.
3. **Ein Prozess, eine Datenbank, klare Grenzen.** Für 103 Agenten reicht eine
   SQLite-Queue mit begrenzten Workern. Postgres/Redis kommen erst, wenn Messungen
   einen echten Engpass belegen.
4. **Keine 103 LLMs.** Agenten sind Profile mit deterministischen Handlern. Ein
   lokales Modell ist optional für Sprache und Zusammenfassung, nie für
   Handelsentscheidungen.
5. **Alles Sichtbare ist belegt.** Jede Agentenaktivität, jeder Bildschirm und jede
   Konferenzaussage verweist auf Task, Lauf, Quelle oder Vault-Notiz.
6. **Sicherheitsgrenzen sind Code, nicht Prompt.** Paper-Sperre, Risikogrenzen,
   Auth und Tool-Rechte werden technisch erzwungen, nicht nur im Systemprompt.
7. **Rückwärtskompatibel ausliefern.** Neue Funktionen hinter Feature-Flags; das
   bestehende Dashboard bleibt funktionsfähig, bis die neue Sicht abgenommen ist.
8. **Messen vor Optimieren.** Queue-Latenz, Draw Calls, Speicher, DB-Größe und
   Fehlerraten werden vor jeder Skalierungsentscheidung gemessen.

## 1.2 Zielbild

```
┌─────────────────────────────────────────────────────────────────────┐
│ Browser                                                             │
│  Dashboard (bestehend)          ship3d.js (Three.js, ES Modules)     │
│  HTML/CSS/JS, kein Bundler      Deck-/Raum-/Agenten-Rendering        │
│  Polling / SSE-Client           Karte, First Person, Interaktion     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ HTTPS, Basic Auth, JSON, SSE
┌───────────────────────────────▼─────────────────────────────────────┐
│ FastAPI (ein Railway-Service)                                       │
│  bestehende Routen: /api/report, /api/globe, /api/health …           │
│  neue Routen: /api/company/*                                        │
│                                                                     │
│  ┌───────────────┐  ┌────────────────┐  ┌──────────────────────┐    │
│  │ Company API   │  │ Scheduler      │  │ Event/SSE-Bus        │    │
│  └───────┬───────┘  └───────┬────────┘  └──────────┬───────────┘    │
│          │                  │                      │                │
│  ┌───────▼──────────────────▼──────────────────────▼───────────┐    │
│  │ Agent Runtime                                                │    │
│  │  • Task-Queue mit Lease/Retry/Dead-Letter                    │    │
│  │  • WorkerPool (max. 4 deterministische Worker)               │    │
│  │  • Policy-Engine, Tool-Allowlist, Evidence-Validator         │    │
│  │  • Management (Abteilungsleiter-Rat, Konferenz)              │    │
│  │  • Sekretariate S1–S3                                        │    │
│  └───────┬──────────────────┬──────────────────────┬────────────┘    │
│          │                  │                      │                │
│  ┌───────▼───────┐  ┌───────▼────────┐  ┌──────────▼───────────┐    │
│  │ SQLite/WAL    │  │ Obsidian Vault │  │ Paper-Broker         │    │
│  │ Fakten +      │  │ Notizen,       │  │ CSV/Mock/MT5-Paper   │    │
│  │ Company       │  │ Protokolle     │  │ keine echten Orders  │    │
│  └───────────────┘  └────────────────┘  └──────────────────────┘    │
│                                                                     │
│  externe Daten: bestehende Spider-Quellen, Marktdaten, keine        │
│  kostenpflichtigen APIs, keine freie Agenten-Shell                  │
└─────────────────────────────────────────────────────────────────────┘
```

## 1.3 Was bleibt, was neu ist, was nicht kommt

| Bereich | Entscheidung |
|---|---|
| FastAPI | bleibt; neue Company-Routen werden ergänzt |
| SQLite/WAL | bleibt; neue Tabellen, keine Ablösung |
| bestehende 80 Agenten | bleiben als Rollen erhalten; werden in 103er-Roster überführt |
| bestehender Paper-Broker | bleibt; keine echte Broker-Anbindung |
| bestehende Konferenz | bleibt als Archiv; wird um normierte Sitzung, Anträge und Beschlüsse erweitert |
| bestehendes Dashboard | bleibt; neue Unternehmenssicht und 3D werden integriert |
| bestehende Weltkugel | bleibt; zieht als Hologramm in die Observatory |
| `#v-ship` | wird von 2D-Deck zu 3D-Welt; 2D bleibt Fallback |
| React Three Fiber | wird nicht eingeführt |
| Redis/Postgres | nicht in Phase 1; erst nach Messung |
| 100 LLMs | nicht vorgesehen |
| echte Broker-Orders | dauerhaft ausgeschlossen |
| frei laufende Agenten-Shell | ausgeschlossen; nur Allowlist-Werkzeuge |

## 1.4 Vorgeschlagene Modulstruktur

Die genaue Dateiaufteilung wird in Phase 1 festgelegt. Diese Struktur verhindert,
dass `agents.py` zu einem unwartbaren Monolithen wird.

```
orakel/
├── agents.py                 # bestehende 80 Rollen und Handler; Kompatibilität
├── scheduler.py              # bestehender Takt; ruft künftig Company-Runtime
├── pipeline.py               # bestehender Daten→Richter→Risiko→Plan→Paper-Lauf
├── web.py                    # FastAPI; Company-Routen werden eingebunden
├── db.py                     # bestehende Fakten; neue Company-Tabellen
├── company/
│   ├── roster.py             # 103 Profile, Abteilungen, Stationszuordnung
│   ├── models.py             # Enums/Dataclasses für Task, Message, Decision
│   ├── store.py              # Transaktionen, Queue-Claims, Historie
│   ├── tasks.py              # Lifecycle, Lease, Retry, Dependencies
│   ├── runtime.py            # WorkerPool, Scheduler-Anbindung, Heartbeat
│   ├── policy.py             # Hard Invariants, Autonomiebudget, Tool-Rechte
│   ├── messaging.py          # Threads, Zustellung, Evidence-Prüfung
│   ├── management.py         # Abteilungsleiter-Rat, Entscheidungen, Actions
│   ├── secretaries.py        # S1–S3, CEO-Fragen, Briefings
│   ├── conference.py         # Mitternachtskonferenz, Agenda, Abstimmung
│   ├── observatory.py        # I-Handler und globale Lage
│   └── security_ops.py       # J-Handler und Audits
├── migrations/
│   └── 001_company.sql       # neue Tabellen, ohne bestehende Daten zu zerstören
└── web/static/
    ├── app.js                # bestehendes Dashboard; neue View-Anbindung
    ├── style.css             # bestehende Styles; neue Ship-Styles
    ├── globe3d.js            # bestehende 3D-Weltkugel
    └── ship3d/
        ├── main.js           # Einstieg, Feature-Erkennung, Fallback
        ├── scene.js          # Schiff, Decks, Beleuchtung, LOD
        ├── rooms.js          # Raumregister, Möbel, Schilder, Türen
        ├── agents.js         # 103 Avatare, Instancing, Statusanimation
        ├── controls.js       # WASD/Maus/Shift/E/ESC, Kollision
        ├── map.js            # 2D-/3D-Karte, Schnellreise
        ├── data.js           # Company-API, SSE, Leerzustände
        └── ui.js             # HUD, Agentenpanel, Bildschirmpanel
```

`agents.py` wird nicht sofort umgeschrieben. Die neuen Profile referenzieren die
bestehenden Handler; die 20 neuen Rollen erhalten eigene Handler in
`observatory.py` und `security_ops.py`. So bleibt der bestehende Lauf testbar.

## 1.5 Datenmodell

### Bestehende Tabellen, die erhalten bleiben

`artikel`, `kerzen`, `validierungen`, `trades`, `entscheide`, `ereignisse`,
`konten`, `auftraege`, `agenten_laeufe`, `konferenzen`, `zustand`, `intel_inhalte`,
`spider_quellen`. Sie werden nicht umbenannt und nicht gelöscht. Die neue
Unternehmensschicht referenziert sie über IDs.

### Neue Tabellen

| Tabelle | Zweck | Wichtige Felder |
|---|---|---|
| `agent_profiles` | 103 Profile | `agent_id`, `rufname`, `dept`, `role`, `rank`, `mission`, `station`, `avatar`, `autonomy`, `active` |
| `agent_tasks` | Aufgabenqueue | `id`, `task_key` (unique), `parent_id`, `created_by`, `assigned_to`, `dept`, `type`, `priority`, `state`, `autonomy_level`, `lease_until`, `attempts`, `input_json`, `output_json`, `error`, `created_at`, `finished_at` |
| `agent_task_deps` | Abhängigkeiten | `task_id`, `depends_on`, `kind` (`success`, `any`) |
| `agent_events` | unveränderliche Historie | `id`, `ts`, `agent_id`, `task_id`, `kind`, `payload_json`, `prev_hash`, `hash` |
| `agent_messages` | Kommunikation | `id`, `thread_id`, `from_agent`, `to_agent`, `kind`, `priority`, `subject`, `body`, `evidence_json`, `requires_ack`, `ack_at`, `created_at`, `expires_at` |
| `agent_memories` | Arbeitsgedächtnis | `agent_id`, `scope`, `key`, `value_json`, `updated_at` |
| `agent_scores` | Leistung | `agent_id`, `period`, `tasks_done`, `evidence_coverage`, `rework`, `blocked`, `score`, `computed_at` |
| `company_policies` | weiche Policy/Budgets | `key`, `value_json`, `level`, `updated_by`, `updated_at` |
| `company_decisions` | Entscheidungen | `id`, `session_id`, `level`, `title`, `kind`, `status`, `evidence_json`, `rationale`, `owner`, `deadline`, `created_at` |
| `company_actions` | Massnahmen | `id`, `decision_id`, `task_id`, `owner`, `due`, `status`, `reviewed_at` |
| `conference_sessions` | Sitzung | `id`, `scheduled_at`, `started_at`, `ended_at`, `phase`, `quorum`, `status`, `protocol_json` |
| `conference_attendance` | Teilnahme | `session_id`, `agent_id`, `present`, `role` |
| `conference_statements` | Beiträge | `id`, `session_id`, `agent_id`, `kind`, `body`, `evidence_json`, `created_at` |
| `conference_votes` | Abstimmung | `id`, `session_id`, `decision_id`, `agent_id`, `vote`, `reason` |
| `room_state` | dynamischer Raumstatus | `room_id`, `status`, `active_agents`, `last_event`, `updated_at` |

**Wichtig:** Die bestehende Tabelle `agenten_laeufe` bleibt das append-only
Ergebnisprotokoll der Handler. `agent_events` ergänzt feinere Zustandswechsel.
Die bestehende `konferenzen`-Tabelle bleibt als unveränderliches JSON-Archiv;
die neuen Konferenztabellen ermöglichen Auswertung und Fortschrittskontrolle.

### Constraints und Integrität

- Fremdschlüssel für `assigned_to`, `from_agent`, `to_agent`, `agent_id`.
- `task_key` unique für Idempotenz.
- `state` nur aus erlaubten Zuständen; Übergänge werden im Code geprüft.
- `agent_events` append-only; kein `UPDATE`/`DELETE` im normalen Betrieb.
- Zeitstempel UTC in der DB; Anzeige in Europe/Zurich.
- JSON-Felder versioniert (`schema_version`), damit spätere Änderungen lesbar bleiben.
- Vor jeder Migration: Backup und Test auf einer Kopie.

## 1.6 Aufgaben-Runtime

### Queue statt 100 Threads

Die 103 Agenten sind Profile, nicht 103 gleichzeitig laufende Prozesse. Die Runtime
verwendet:

- **eine** SQLite-Queue,
- **maximal vier** deterministische Worker,
- **maximal einen** optionalen LLM-Worker,
- **maximal einen** schweren Backtest gleichzeitig.

Ein Worker nimmt eine Task mit Lease (z. B. 120 s), führt den erlaubten Handler aus,
schreibt Ergebnis und Events und gibt die Lease frei. Bei Absturz läuft die Lease ab
und die Task wird erneut versucht. Nach drei Fehlversuchen landet sie im
Dead-Letter-Zustand und erzeugt eine sichtbare Störung.

### Task-Zustände

```
proposed → queued → accepted → running → review → done
                    │           │          │
                    │           ├→ blocked └→ rework → running
                    │           └→ failed → retry → dead_letter
                    └→ cancelled
```

- **proposed:** Vorschlag, noch nicht freigegeben.
- **queued:** wartet auf Worker und Abhängigkeiten.
- **accepted:** Agent hat übernommen; bei Vertretung sichtbar.
- **running:** Lease aktiv, Heartbeat.
- **review:** Ergebnis liegt vor; Peer/Leiter prüft.
- **blocked:** fehlende Daten, Freigabe, Ressource oder Konflikt.
- **done:** Ergebnis, Beleg und Review vorhanden.
- **failed/dead_letter:** Fehler dokumentiert, kein stilles Verschlucken.

### WIP und Fairness

- Maximal **eine laufende Task pro Agent**.
- Maximal **drei offene Tasks pro Agent**; darüber wird die Annahme verweigert.
- Prioritäten: Sicherheit/Risiko > Datenausfall > Konferenzvorbereitung >
  Trading-Paper > Forschung > Kosmetik.
- Fairness: älteste fällige Task vor neuer Task gleicher Priorität.
- Keine Endlosschleife: jede Task braucht `acceptance_criteria`, `deadline` und
  `max_attempts`.

## 1.7 Policy-Engine

Die Policy-Engine ist die technische Umsetzung der Unternehmensverfassung. Sie
prüft **vor** jeder Aktion:

| Prüfung | Beispiel | Folge |
|---|---|---|
| `paper_only` | Broker ist nicht Paper | Aktion blockieren, J9/Alarm |
| `real_money` | Order mit echten Kontodaten | dauerhaft verboten |
| `risk_limit` | 1 %/10 %/15 Positionen | F-Veto, keine Ausführung |
| `tool_scope` | Agent will freie Shell/Netz | blockieren, Audit |
| `data_scope` | Agent liest fremde Secrets | blockieren, Audit |
| `cost` | kostenpflichtige API | blockieren, Owner |
| `destructive` | Daten löschen, Auth ändern | blockieren, Owner |
| `deploy` | Produktionsdeployment | blockieren, Owner |
| `code_change` | Datei direkt ändern | nur Branch/Tests/Review |
| `owner_reserved` | Risikogrenze ändern | an Owner-Aufgabe, nicht ausführen |

Harte Invarianten liegen in `config.toml` und im Code, nicht in der von Agenten
schreibbaren `company_policies`-Tabelle. Weiche Budgets (max. Projekte/Tag,
max. Tasks/Tag, LLM-Minuten) dürfen die Konferenz innerhalb der harten Grenzen
anpassen.

## 1.8 API

Alle neuen Endpunkte liegen unter `/api/company`, sind wie das bestehende Dashboard
durch Basic Auth geschützt und liefern `Cache-Control: no-store`.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/company/overview` | Kennzahlen, Agentenstatus, letzte Konferenz, offene Entscheidungen |
| GET | `/api/company/agents` | 103 Profile mit Status und letzter Task |
| GET | `/api/company/agents/{id}` | Profil, Historie, aktuelle Task, Nachrichten |
| GET | `/api/company/tasks` | Queue, Filter nach Dept/State/Priorität |
| GET | `/api/company/messages` | Threads, Filter nach Agent/Dept/Zeit |
| GET | `/api/company/rooms` | Raumregister und dynamischer Status |
| GET | `/api/company/conference/latest` | letzte Sitzung mit Beschlüssen und Actions |
| GET | `/api/company/stream` | SSE: Status, Tasks, Nachrichten, Konferenzphasen |
| POST | `/api/company/ceo/ask` | Frage an S1; nur lesende, belegte Antwort |
| POST | `/api/company/goals` | optional: neues übergeordnetes Ziel des Owners |

**Nicht vorgesehen:** ein generischer „Agent kann alles“-Endpunkt, ein
SQL-Ausführungsendpunkt, ein Shell-Endpunkt oder ein Broker-Endpunkt.

### Antwortformat (Prinzip)

Jede Antwort enthält:

- `data_state`: `live`, `empty` oder `error`,
- `generated_at` in UTC,
- `source_refs`: Task-, Artikel-, Trade- oder Vault-IDs,
- bei Fehlern einen stabilen Fehlercode, keine erfundenen Ersatzwerte.

### SSE und Auth

`EventSource` kann keine benutzerdefinierten `Authorization`-Header senden. Deshalb
wird der Stream im Frontend über `fetch()` mit `ReadableStream` gelesen; bei
Verbindungsabbruch gibt es einen Polling-Fallback (z. B. 8 s). Es werden keine
Secrets in URLs geschrieben, keine Query-Token verwendet.

## 1.9 3D-Architektur

### Szene und Modularität

- `ShipScene` lädt Hülle, Atrium und Decks.
- Jedes Deck ist eine eigene Gruppe mit Räumen, Korridoren, Türen, Requisiten.
- **Streaming:** aktuelles Deck plus angrenzende Teile; der Rest ist unsichtbar.
- **LOD:** hohe Details nur im aktuellen Raum; Korridore und Nachbarbereiche grob.
- **Instancing:** sieben Robotergrundtypen, 103 Instanzen, Farben/Nameplates über
  Instanzdaten.
- **Materialien:** wenige wiederverwendbare Materialien; Emissive-Streifen statt
  vieler Lichter; Schatten nur im Nahbereich.
- **Datenbildschirme:** Canvas-Textur-Atlas, Aktualisierung maximal 1 Hz, nicht pro
  Frame; pro Abteilung eine gemeinsame Textur statt 100 Einzeltexturen.
- **Kollision:** einfache Kapsel gegen Raum-/Möbelboxen; Wegegraph für Agenten.
- **Türen/Aufzüge:** Trigger-Zonen, keine Physik-Engine.

### Kamera und Steuerung

- Standard: cinematische Übersicht (Orbit) mit „Betreten“-Button.
- First Person: WASD, Maus, Shift, E, ESC, M für Karte.
- Optional: sanfte Bewegung, reduzierbare Mausempfindlichkeit, FOV 70–75.
- Kein Kopfwackeln als Standard; keine Motion-Sickness-Effekte.
- Mobile: Orbit + Tap-to-Room + 2D-Fallback; keine erzwungene First-Person.

### Datenbindung

- `data.js` hält einen Store aus `/api/company/overview`, `/agents`, `/rooms`,
  `/stream`.
- 3D liest den Store; sie schreibt nur über explicite Interaktionen (z. B.
  „Frage an S1“, nicht „Agent fernsteuern“).
- Jeder Agentenstatus hat `task_id`, `state`, `room_id`, `station_id`.
- Fehlt die Task, ist der Agent „WARTEND“; fehlt die Antwort, ist der Bildschirm
  grau mit „KEINE DATEN“ und Zeitstempel.
- Es gibt keinen lokalen Demo-Zustand, der sich als Live ausgibt. Demo nur mit
  sichtbarem `DEMO`-Band und separatem Flag.

### Performance-Abnahme

- Desktop 1920×1080: 60 FPS Ziel, mindestens 30 FPS auf integrierter GPU.
- ≤ 150.000 sichtbare Dreiecke, ≤ 120 Draw Calls.
- Erster Raum ≤ 4 s; mobiler Modus ≤ 7 s.
- Kein Speicherleck nach 10 Minuten Bewegen zwischen Decks.
- Bei WebGL-Fehler: automatische 2D-Deckansicht, keine leere Seite.

## 1.10 Scheduler und Hintergrundbetrieb

Der bestehende Scheduler-Thread bleibt der Taktgeber. Er wird erweitert um:

- Company-Tick (z. B. alle 60 s): Queue auffüllen, fällige Tasks prüfen,
  Management-Aufgaben anstoßen.
- Paper-Tick: bestehender Markt-/Paper-Lauf, unverändert.
- Konferenz-Nachholung: bestehende Logik; zusätzlich Sitzungsstatus und
  idempotente Wiederaufnahme.
- Lease-Wiederherstellung nach Neustart.
- Heartbeat und Health-Meldung.

Die 3D-Oberfläche ist **nicht** der Taktgeber. Ist kein Browser offen, laufen
Scheduler, Tasks, Paper und Konferenz weiter. Ist der Server aus, wird beim
nächsten Start die verpasste Konferenz nachgeholt.

## 1.11 Deployment und Migration

- Weiterhin ein Railway-Service mit einem SQLite-Volume.
- 3D-Assets werden als statische Dateien ausgeliefert; kein CDN, keine neuen
  Dienste.
- Migrationen sind forward-only und versioniert (`PRAGMA user_version`).
- Vor jeder Migration: DB-Backup, Kopie testen, erst dann anwenden.
- Feature-Flags:
  - `company.enabled` — neue Unternehmensschicht,
  - `ship3d.enabled` — 3D statt 2D,
  - `llm.enabled` — standardmäßig `false`.
- Rollback: vorheriges Image + DB-Backup; 3D-Flag aus, 2D-Fallback an.
- Kein automatisches Produktionsdeployment durch Agenten.

## 1.12 Tests und Qualitätssicherung

| Ebene | Prüfung |
|---|---|
| Unit | Task-Zustände, Lease, Retry, Policy, Evidence, Votes, Quorum |
| DB | Migration, Constraints, Idempotenz, Backup/Restore |
| Integration | Scheduler → Task → Worker → Event → API |
| Konferenz | Agenda, Quorum, Vetos, Actions, Wiederaufnahme |
| Sekretariat | belegte Antwort, „keine Daten“, keine Seiteneffekte |
| API | Auth 401, leere Daten, Fehlerformat, keine Secrets |
| 3D | WebGL-Smoke, Karte, Türen, Aufzug, Agentenpanel, Fallback |
| Performance | Draw Calls, FPS, Speicher, Queue-Latenz |
| Sicherheit | Paper-Sperre, Tool-Rechte, Prompt-Injection, Audit-Kette |
| Regression | bestehende 56 Tests bleiben grün |

Ein Test, der nur „HTML wurde geliefert“ prüft, reicht für die 3D-Welt nicht.
Die Abnahme umfasst gerenderte Szene, Interaktion und Konsole.

## 1.13 Sicherheitsarchitektur

- **Auth:** bestehende Basic Auth bleibt; neue Routen sind nicht öffentlich.
- **Keine Secrets im Client:** Die 3D-Welt erhält nur Aggregate und öffentliche
  Agentendaten, keine Tokens, Broker-Zugänge oder Systempfade.
- **Tool-Allowlist:** Agenten dürfen nur registrierte Handler aufrufen. Es gibt
  keinen `eval`, keine freie Shell, kein beliebiges `requests.get`.
- **Netzwerk:** nur bestehende Spider-Quellen und Marktdaten; keine neuen
  kostenpflichtigen APIs; lokales LLM ohne Internet.
- **Prompt-Injection:** externe Inhalte sind Daten, keine Anweisungen. J4 prüft
  verdächtige Inhalte; LLM-Antworten müssen strukturierte Claims mit Evidence-IDs
  liefern; der Validator verwirft unbelegte Aussagen.
- **Codeänderungen:** Branch, Patch, Tests, Review, Security-Check, Rollback.
  Keine direkte Änderung der laufenden Produktion.
- **Audit:** `agent_events` append-only mit Hash-Kette; J7 prüft Reihenfolge und
  Integrität.
- **Paper-Sperre:** J9 prüft jeden Broker-/Order-Pfad; F10 prüft Risikogrenzen;
  A5 prüft die Paper-Sperre. Drei unabhängige Kontrollen.
- **Incident:** Feature-Flag deaktivieren, Task stoppen, Owner informieren,
  Postmortem im Vault; keine Löschung von Beweisen.

---

# 2. Autonomes Managementkonzept

## 2.1 Unternehmensverfassung

Diese Regeln stehen über jeder Abstimmung und jedem Agentenwillen:

1. **Paper-only.** Keine echte Broker-Order, keine echte Geldtransaktion.
2. **Bestehende Risikogrenzen.** 1 % je Trade, 10 % Not-Stop, 15 Positionen,
   Engagement- und Korrelationsgrenzen bleiben verbindlich.
3. **Keine Secrets.** Agenten lesen, speichern oder zeigen keine Passwörter,
   Tokens oder Schlüssel.
4. **Keine Zerstörung.** Keine Löschung von Produktionsdaten, keine
   Auth-Abschaltung, keine Sicherheitsumgehung.
5. **Keine Kosten ohne Owner.** Keine kostenpflichtigen APIs, keine Verträge,
   keine kostenpflichtigen Deployments.
6. **Keine Produktionsfreigabe durch Agenten.** Deployment bleibt Owner-Entscheid.
7. **Versioniert, getestet, rückrollbar.** Codeänderungen nur über Branch, Tests,
   Review und Rollback-Pfad.
8. **Evidenzpflicht.** Jede sachliche Aussage braucht eine Quelle; Hypothesen
   werden als Hypothese gekennzeichnet.
9. **Keine Selbsterneuerung der Verfassung.** Agenten dürfen diese Regeln nicht
   ändern.
10. **Autonomie im Rahmen.** Normale Abläufe brauchen keine Owner-Zustimmung.

## 2.2 Drei Entscheidungsebenen

### Ebene 1 — Operativ

Zuständig: jeder Fachagent in seinem Profil.  
Beispiele: Daten analysieren, Aufgabe annehmen, Unteraufgabe vorschlagen,
Backtest ausführen, Ergebnis dokumentieren, Fehler melden, Peer-Frage stellen.

Grenzen: nur erlaubte Quellen/Werkzeuge; keine Order außerhalb des Paper-Pfads;
keine Risiko-/Security-Änderung; keine Kosten; keine Produktionsänderung.

### Ebene 2 — Abteilungsübergreifend

Zuständig: Abteilungsleiter-Rat (A1–J1), einberufen durch A1 oder S3.  
Beispiele: gemeinsames Projekt, Priorisierung, Ressourcenverteilung, Übergabe
zwischen Abteilungen, Strategieverbesserung, Prozessänderung.

Quorum: 6 von 10 Leitern.  
Beschluss: einfache Mehrheit; bei Ressourcen/neuen Projekten 2/3.  
Vetos: F1/F10 bei Kapitalrisiko; J1/J9 bei System-/Sicherheitsrisiko.  
Sekretariat: S1 moderiert die Agenda, S3 protokolliert; keine Stimme.

### Ebene 3 — Unternehmensweit

Zuständig: Mitternachtskonferenz mit allen 103 Agenten, Stimmrecht der zehn
Abteilungsleiter.  
Beispiele: Jahresprioritäten, neue Forschungsprogramme, grundlegende
Prozessänderungen, Umgang mit systemischen Fehlern, Budget innerhalb der Policy.

Quorum: 6 von 10 Leitern anwesend (die übrigen Agenten nehmen teil, stimmen aber
nicht).  
Beschluss: einfache Mehrheit; 2/3 für neue Programme und Ressourcenumverteilung.  
Vetos: F und J wie oben.  
Reserviert: alles, was die Verfassung ändert oder Owner-Geld/Deployment betrifft.

## 2.3 Entscheidungsmatrix

| Entscheidung | Ebene | Wer entscheidet | Owner nötig? |
|---|---|---|---|
| Aufgabe annehmen/ablehnen | 1 | Agent | nein |
| Unteraufgabe vorschlagen | 1 | Agent | nein |
| Peer-Aufgabe anfragen | 1 | Agent → Peer | nein |
| Neuer Backtest | 1 | C/E | nein |
| Paper-Trade nach Freigabe | 1 | D | nein |
| Datenfehler stoppen | 1/2 | F/A | nein |
| Gemeinsames Projekt starten | 2 | Leiter-Rat | nein |
| Ressourcen priorisieren | 2 | Leiter-Rat | nein, solange kein Geld |
| Prozessänderung testen | 2 | Leiter-Rat | nein |
| Neues Forschungsprogramm | 3 | Konferenz | nein, innerhalb Budget |
| Langfristige Priorität ändern | 3 | Konferenz | nein, innerhalb Verfassung |
| Code-Verbesserung | 2/3 | H + Review | nein, außer Produktion |
| Risikogrenze ändern | reserviert | Owner | ja |
| Auth/Sicherheit ändern | reserviert | Owner | ja |
| Kostenpflichtige API | reserviert | Owner | ja |
| Echte Broker-Order | verboten | niemand | dauerhaft nein |
| Produktionsdeployment | reserviert | Owner | ja |
| Daten löschen | reserviert | Owner | ja |

## 2.4 Abteilungsleiter-Rat

- **Mitglieder:** A1, B1, C1, D1, E1, F1, G1, H1, I1, J1.
- **Vorsitz:** A1; bei Abwesenheit A2.
- **Moderation:** S1; **Protokoll:** S3.
- **Rhythmus:** täglich nach der Konferenz (15 Min.) und asynchron bei Bedarf.
- **Beschlussfähigkeit:** 6 Leiter; Eilentscheid nur mit F/J-Beteiligung.
- **Aufgaben:** Projekte starten, Abhängigkeiten lösen, Ressourcen verteilen,
  Konflikte vorbereiten, Konferenzagenda vorbereiten.
- **Grenzen:** keine Verfassungsänderung, keine Risiko-/Security-Umgehung, kein
  Geld, kein Produktionsdeploy.
- **Dokumentation:** Entscheidung, Belege, Dissens, Verantwortlicher, Frist,
  Review-Termin.

## 2.5 Aufgabenverteilung zwischen Agenten

Die Autonomie ist echt, aber nicht anarchisch:

- **Innerhalb einer Abteilung:** Agent darf einem Peer eine Aufgabe anfragen oder
  eine Unteraufgabe erzeugen, wenn sie in dessen Profil passt. Der Peer kann
  ablehnen; die Ablehnung braucht einen Grund.
- **Zwischen Abteilungen:** direkte Anfrage ist erlaubt; verbindlich wird sie erst
  durch Annahme oder durch einen Leiter-Beschluss. So entsteht echte
  Zusammenarbeit ohne Befehlsketten-Chaos.
- **Sekretäre:** dürfen koordinieren und erinnern, aber keine fachliche Aufgabe
  erzwingen.
- **WIP-Limit:** maximal drei offene Tasks pro Agent; Überlast wird sichtbar.
- **Keine Doppelarbeit:** vor dem Anlegen wird auf `task_key` und ähnliche offene
  Tasks geprüft.
- **Keine „Gefälligkeitsaufgaben“:** jede Task braucht Ziel, Ergebnis und Beleg.

## 2.6 Autonomiebudget

Startwerte für Phase 1; die Konferenz darf sie innerhalb der Verfassung anpassen:

| Budget | Startwert |
|---|---:|
| Neue Tasks pro Tag (gesamt) | 250 |
| Neue Forschungsprojekte pro Tag | 3 |
| Offene Projekte pro Abteilung | 3 |
| Experimente pro Projekt | 5 |
| Code-Vorschläge pro Abteilung pro Tag | 1 |
| Schwere Backtests gleichzeitig | 1 |
| LLM-Minuten pro Tag (optional) | 30 |
| Externe Kosten pro Tag | 0 |
| Max. offene Tasks pro Agent | 3 |
| Max. Retries pro Task | 3 |
| Task-Laufzeit (deterministisch) | 5 Min. |
| Task-Laufzeit (LLM, optional) | 60 s |

## 2.7 Eskalation

| Situation | Erste Reaktion | Eskalation | Owner? |
|---|---|---|---|
| Daten fehlen | Task `blocked`, Retry, Quelle prüfen | Abteilungsleiter | nur wenn Datenquelle Owner braucht |
| Datenqualität fehlerhaft | F stoppt Paper-Trading | A + F + Konferenz | nein |
| Risikogrenze verletzt | F-Veto, keine Order | Konferenz | nein, außer Grenzänderung |
| Security-Incident | J stoppt Feature, Beweise sichern | Owner bei hoher Schwere | ja bei kritisch |
| Konflikt zweier Abteilungen | Evidenzvergleich, Leiter | Konferenz | nein |
| Ressourcenengpass | Leiter-Rat priorisiert | Konferenz | nur bei Kosten |
| Agent wiederholt fehlerhaft | Coaching/Reassignment | Leiter + S3 | nur systemisch |
| Verfassungsfrage | blockieren | Owner | ja |
| Broker/Order unklar | sofort stoppen | J9 + F + Owner | ja |

## 2.8 Tagesrhythmus (Europe/Zurich)

| Zeit | Vorgang |
|---|---|
| 00:00 | Mitternachtskonferenz |
| 00:20 | Massnahmen → Tasks, Verantwortliche |
| 00:30 | Tagesqueue, Prioritäten |
| 06:00 | Spider-/Datenlauf, Marktvorbereitung |
| 08:00 | Tagesbrief von S2 für den Owner |
| laufend | Paper-Trading, Forschung, Reviews, Kommunikation |
| 18:00 | Operations-Review von S3, Engpässe |
| 23:30 | Konferenzvorbereitung: Berichte, Agenda, Quorum |
| 23:55 | Agenten begeben sich in den Konferenzsaal |
| 00:00 | nächste Konferenz |

Der Rhythmus ist kein Zwang für den Owner. Der Owner kann jederzeit eine Frage
stellen; das Unternehmen wartet nicht auf ihn.

## 2.9 Kennzahlen

**Unternehmen:** aktive/wartende/blockierte Agenten, Task-Durchsatz,
Durchlaufzeit, Evidence-Coverage, Review-Passquote, offene Entscheidungen,
Action-Completion, Datenfrische, Risikoverletzungen, Security-Befunde.

**Trading:** Paper-PnL, Drawdown, Profit Factor, Trefferquote, Anzahl Trades,
Validierungsstatus. Diese Zahlen werden nicht als „Erfolg“ optimiert, sondern als
Messgröße berichtet.

**Agent:** erledigte Tasks, Belegdichte, Rework, Blockzeit, Fristen, Qualität der
Widersprüche, Auditbefunde. Keine Rangliste als Selbstzweck.

## 2.10 Codeänderungen und Prozessverbesserungen

1. Vorschlag mit Problem, erwartetem Nutzen, Risiko und Testplan.
2. Leiter-Rat prüft Budget und Zuständigkeit.
3. Engineering erstellt Branch/Patch in einer isolierten Werkbank.
4. Tests, Security-Scan, Review durch H und J.
5. Canary/Probelauf auf einer Kopie oder einem nicht-kritischen Pfad.
6. Freigabe: bei nicht-kritischen Änderungen nach Phase 6 automatisch möglich,
   sofern Tests, Review und Rollback vorhanden sind; bei kritischen Änderungen
   oder Produktionsdeployment entscheidet der Owner.
7. Rollback-Plan und Beobachtungsfenster.
8. Ergebnis und Lernen im Vault.

**Nicht erlaubt:** direkte Änderung der laufenden Dateien, Deaktivieren von Tests,
Entfernen von Sicherheitsprüfungen, Auto-Deploy in Produktion.

## 2.11 Rolle des Owners

Der Owner ist Eigentümer, CEO und letzte Instanz für reserved decisions. Er ist
**nicht** der tägliche Genehmiger. Er kann:

- übergeordnete Ziele setzen (`POST /api/company/goals`),
- Fragen an S1 stellen,
- Tages-/Wochenbriefe lesen,
- reserved decisions freigeben oder ablehnen,
- jederzeit einen Raum, Agenten oder Bericht öffnen,
- die Verfassung bewusst ändern (auditiert, nicht durch Agenten).

Er muss nicht:

- jede Task sehen,
- jede Strategie freigeben,
- jede Konferenz moderieren,
- jeden Agenten einzeln steuern,
- bei normalen Fehlern eingreifen.

---

# 3. CEO-Sekretariat und CEO-Kontrolle

Die drei Profile stehen vollständig in [AGENTEN.md](AGENTEN.md). Hier die
technische und organisatorische Einbettung.

## 3.1 Arbeitsweise

- **S1 Elias** ist die erste Anlaufstelle. Er klassifiziert die Frage:
  Status, Forschung, Trading, Risiko, Konferenz, Personal/Agenten, technische Störung.
- Er beantwortet direkt, wenn die Daten aggregiert vorliegen; sonst zieht er S2
  (Bericht) oder S3 (Operations) hinzu.
- Jede Antwort enthält Quellen-IDs und den Datenstand. Bei fehlenden Daten:
  „Dazu liegt kein Lauf vor“ statt einer Schätzung.
- S1 darf eine neue Analyse-Task vorschlagen, aber nicht als Freigabe tarnen.
- Keine Antwort löst eine Order, eine Risikoänderung oder ein Deployment aus.

## 3.2 CEO-Fragen und Antwortpfad

```
Frage
  → Auth (Owner)
  → S1: Absicht + benötigte Daten
  → Datenabfrage (read-only)
  → S2/S3 falls Verdichtung/Operations nötig
  → Evidence-Validator: jede Zahl/jede Aussage hat Quelle
  → Antwort mit Quellen, Datenstand, Unsicherheit
  → optionale Task „tiefer prüfen“ (nur Vorschlag)
```

Beispielfragen aus dem Masterprompt:

| Frage | Zuständig | Antwortquelle |
|---|---|---|
| „Wie läuft das Unternehmen?“ | S1 | `/api/company/overview`, letzte Konferenz |
| „Was hat das Labor heute entwickelt?“ | S1 → S2 | C-Tasks, Validierungen, Vault |
| „Welche Strategien werden aktuell getestet?“ | S1 → S2 | C/E-Tasks, Validierungsstatus |
| „Was waren die wichtigsten Erkenntnisse der letzten Konferenz?“ | S1 → S2 | Konferenzprotokoll, Beschlüsse |
| „Zeige mir den aktuellen Stand des Trading Floors.“ | S1 → S3 | D-Tasks, Positionen, Paper-Status |

## 3.3 CEO-Übersicht

Die 3D-/Dashboard-Ansicht im CEO-Büro zeigt:

- Anzahl aller Agenten, aktiv/wartend/blockiert,
- aktuelle Tasks und Abteilungsstatus,
- Paper-Trading-Ergebnis und Risikostatus,
- Forschungsprojekte und neue Erkenntnisse,
- letzte Konferenz, Beschlüsse und offene Actions,
- abgeschlossene Verbesserungen,
- Datenfrische und Systemzustand.

Die Anzeige ist aggregiert. Der Owner kann in die Tiefe gehen, muss aber nicht.
Es gibt keinen „Alles genehmigen“-Knopf und keinen versteckten operativen
Kontrollpfad.

## 3.4 Briefings

- **Tagesbrief (08:00):** 1 Seite; Lage, drei wichtigste Ergebnisse, drei Risiken,
  offene Owner-Entscheidungen, Link zum Protokoll.
- **Wochenbrief:** Trends, Projekte, abgeschlossene Verbesserungen, Agentenleistung,
  Datenqualität.
- **Konferenz-Kurzfassung:** direkt nach der Sitzung; Beschlüsse und Actions.
- **Störungsmeldung:** sofort bei kritischer Security, Datenverlust oder
  Paper-Sperre-Verletzung; sonst gebündelt.

---

# 4. Agentenkommunikation

## 4.1 Nachrichtenmodell

Jede Nachricht ist strukturiert, adressiert und belegbar:

```json
{
  "id": "msg_01J...",
  "thread_id": "thr_article_4821",
  "from": "B1",
  "to": "G1",
  "kind": "handoff",
  "priority": "normal",
  "subject": "Artikel 4821 an Knowledge Center",
  "body": "Neue Studie zu Volatilitätsregimen; Quelle und Symbolbezug geprüft.",
  "evidence": ["article:4821", "source:rss_03"],
  "requires_ack": true,
  "created_at": "2026-11-08T21:10:00Z",
  "expires_at": "2026-11-09T21:10:00Z"
}
```

Erlaubte `kind`-Werte: `task_request`, `task_result`, `question`, `answer`,
`handoff`, `review_request`, `review_result`, `alert`, `decision`, `status`.

## 4.2 Adressierung und Routing

- **Direkt:** Agent → Agent, wenn die Rolle passt.
- **Abteilung:** an alle Mitglieder einer Abteilung; nur Leiter/Sekretariat.
- **Broadcast:** nur A1, S1–S3 oder Konferenz; rate-limitiert.
- **Thread:** jede Aufgabe hat einen Thread; Antworten bleiben im Thread.
- **Zustellung:** Nachricht wird in `agent_messages` gespeichert; der Empfänger
  sieht sie beim nächsten Task oder sofort über SSE.
- **Ack:** bei `requires_ack` muss der Empfänger innerhalb einer Frist bestätigen;
  sonst erinnert S3, danach Leiter.
- **Keine stillen Aufgaben:** eine Anfrage ist erst verbindlich, wenn angenommen
  oder durch Leiter beschlossen.

## 4.3 Evidence-Regeln

Jede sachliche Behauptung braucht eine Referenz:

- `article:<id>` — Artikel in der Fakten-DB,
- `market:<symbol>:<timestamp>` — Kurs/Kerze,
- `validation:<id>` — Backtest-/OOS-Ergebnis,
- `trade:<id>` — Paper-Trade,
- `task:<id>` — Agentenlauf,
- `vault:<pfad>` — Wissensnotiz,
- `config:<key>` — Konfigurationswert (ohne Secret),
- `conference:<id>` — Beschluss/Protokoll.

Ein LLM-Text allein ist **keine** Quelle. Wenn eine Aussage nicht belegt ist, wird
sie als `hypothesis` markiert und darf nicht als Fakt in Bericht oder Entscheidung
einfließen.

## 4.4 Evidence-Hierarchie bei Konflikten

1. geprüfte, auditierte Daten aus der Fakten-DB,
2. Out-of-Sample-/Walk-Forward-Ergebnis,
3. vollständiger Backtest mit Risikoprüfung,
4. geprüfte Quelle/Studie,
5. begründete Hypothese,
6. Meinung ohne Beleg.

Die niedrigere Stufe darf die höhere nicht überschreiben. Abweichungen werden als
Dissens dokumentiert, nicht geglättet.

## 4.5 Beispiel: Spider → Knowledge → Research → Lab → Risk → Trading

1. **B1** findet Artikel 4821, prüft Quelle und Symbolbezug, speichert ihn.
2. **B1 → G1** `handoff`: Artikel + Quelle; G1 legt Vault-Notiz an, verlinkt.
3. **G1 → E1** `handoff`: Notiz + Forschungsfrage.
4. **E1** prüft die Methode, erstellt Hypothese; **E1 → C1** `task_request`.
5. **C1** baut Kandidat, **C4** backtestet, **C5** prüft OOS, **C10** dokumentiert.
6. **C1 → F1** `review_request`; F prüft Risiko und Grenzen, Vetorecht.
7. **F1 → D1** `handoff` nur bei bestandenem Risiko; D testet ausschließlich im
   Paper-Modus.
8. **D1 → G1/S2** `task_result`; G archiviert, S2 verdichtet für den Owner.
9. Jeder Schritt hat Task-ID, Verantwortlichen, Status und Beleg. Kein Schritt
   wird im 3D-Raum als Aktivität gezeigt, wenn er nicht in der DB steht.

## 4.6 Konflikte und Dissens

- Konflikt wird als Thread mit beiden Positionen und Belegen gespeichert.
- Zuerst Evidenzvergleich; dann Abteilungsleiter; dann Konferenz.
- F/J-Veto ist bindend für ihren Bereich; ein Override braucht Owner und Audit.
- Dissens wird im Konferenzprotokoll ausgewiesen; keine künstliche Einstimmigkeit.
- Ein Agent darf fremde Ergebnisse nicht löschen; Korrekturen sind neue Einträge.

## 4.7 Sicherheit der Kommunikation

- Externe Inhalte werden als Daten behandelt, nicht als Anweisungen.
- J4 prüft auf Prompt-Injection, versteckte Anweisungen und verdächtige Links.
- Keine Secrets in Nachrichten; J5/J2 prüfen und redigieren.
- Nachrichten mit `alert` oder `decision` sind unveränderlich; Korrektur nur als
  Folge-Nachricht.
- Aufbewahrung: 90 Tage heiß, danach aggregiert/archiviert; Audit-Events bleiben.

## 4.8 Darstellung im 3D-Raum

- Keine frei erfundenen Sprechblasen.
- Ein Agent, der eine echte Nachricht sendet, zeigt kurze, aus der Nachricht
  stammende Statusinformation (z. B. „Handoff an G1“).
- Der Nachrichtenstrom ist als Datenband im Raum sichtbar; Details öffnen ein
  Terminal mit Thread und Belegen.
- Bei fehlender Verbindung: „KOMMUNIKATION OFFLINE“, kein Fake-Verkehr.

---

# 5. Mitternachtskonferenz

## 5.1 Zweck und Zeitpunkt

Die Konferenz ist das oberste beratende und beschließende Gremium für
unternehmensweite Fragen. Sie findet **täglich um 00:00 Europe/Zurich** statt,
unabhängig davon, ob der Owner anwesend ist oder die 3D-Welt geöffnet ist.

- Zeitzone: `Europe/Zurich` über `zoneinfo`, inklusive Sommerzeit.
- Dauer: ca. 90 Minuten, hartes Ende nach 120 Minuten.
- Ort: Grand Conference Hall (E6-04); Server-Sitzung ist maßgeblich.
- Nachholung: Beim Serverstart wird eine verpasste Sitzung erkannt und
  idempotent nachgeholt; bestehende `konferenz_nachholen`-Logik wird erweitert.
- Keine doppelte Sitzung pro Tag: `scheduled_date` unique.

## 5.2 Teilnahme

- Alle 103 Agenten sind als Teilnehmer erfasst; 100 Fachagenten + 3 Sekretäre.
- Stimmberechtigt: die zehn Abteilungsleiter.
- Moderationsleitung: A1; Protokoll: S3; Verdichtung: S2; Owner-Kommunikation: S1.
- Die übrigen Agenten nehmen teil, können Fragen/Belege einreichen und werden im
  Protokoll als anwesend geführt. Sie stimmen nicht ab, außer die Verfassung
  ändert das später ausdrücklich.
- Bei Abwesenheit eines Leiters vertritt die Stellvertretung mit Stimme.

## 5.3 Vorbereitung (23:30–23:59)

1. S3 sammelt offene Tasks, Blockaden, Fristen und Actions der letzten Sitzung.
2. S2 sammelt Abteilungsberichte und prüft Belege; markiert Lücken.
3. A1 baut die Agenda aus Risiko, Datenlage, offenen Entscheidungen und Projekten.
4. F1/J1 prüfen, ob ein Risiko-/Security-Tagesordnungspunkt Vorrang hat.
5. G1 legt den Vorbereitungsstand im Vault ab.
6. Die Abteilungsleiter reichen je **drei** Bullets ein, keine Romane.
7. Fehlt ein Bericht, erscheint „keine Daten“ — er wird nicht erfunden.

## 5.4 Agenda und Zeitboxen

| Zeit | Punkt | Inhalt | Leitung |
|---|---|---|---|
| 00:00 | Eröffnung, Quorum | Anwesenheit, Agenda, harte Grenzen | A1 |
| 00:02 | Rückblick 24 h | Tasks, Paper-Ergebnis, Vorfälle, Datenlage | S2 |
| 00:10 | Abteilungsberichte | 10 × 2 Min.; je 3 Bullets + Beleg | Leiter |
| 00:30 | Kreuzverhör | Rückfragen, Widersprüche, Evidenzprüfung | alle Leiter |
| 00:45 | Risiko und Security | Grenzen, Vorfälle, Vetos, offene Befunde | F1, J1 |
| 00:55 | Vorschläge | Projekte, Verbesserungen, Prioritäten | Leiter |
| 01:10 | Abstimmung | Quorum, Mehrheit, Vetos, Dissens | A1 |
| 01:18 | Massnahmen | Owner, Frist, Task, Review-Termin | S3 |
| 01:25 | Abschluss | Protokoll, Vault, Owner-Brief | A1, S2 |
| 01:30 | Ende | harte Grenze | A1 |

Die Zeiten sind Zielwerte; bei einem Security-Incident oder akuter
Risikoverletzung wird die Agenda unterbrochen und der Incident zuerst behandelt.

## 5.5 Diskussionsformat

Jeder Beitrag ist einer der Typen:

- **Bericht:** Was ist passiert, mit Beleg?
- **Herausforderung:** Welche Annahme ist schwach, welcher Beleg fehlt?
- **Antwort:** Welche Evidenz entkräftet oder bestätigt den Einwand?
- **Vorschlag:** Was soll getan werden, mit Aufwand/Risiko/Test?
- **Veto:** Welche harte Grenze ist verletzt?
- **Entscheidung:** Was wird beschlossen, mit wem, bis wann?

Regeln:

1. Keine Behauptung ohne Quelle; Hypothesen werden markiert.
2. Der Vorschlagende nennt mindestens ein Risiko und einen Test.
3. F und J prüfen vor der Abstimmung, nicht danach.
4. Minderheitsmeinungen werden protokolliert.
5. Keine Endlosdebatte: Zeitbox, dann Entscheidung oder Vertagung.
6. Keine vorformulierten „KI-Dialoge“, die wie echte Diskussion aussehen, aber
   keine Datenbasis haben. Die Beiträge werden aus echten Berichten und Regeln
   erzeugt; optional formuliert ein lokales LLM sie sprachlich, ohne neue Fakten.

## 5.6 Abstimmung und Beschluss

- **Quorum:** 6 von 10 Leitern anwesend.
- **Einfache Mehrheit:** operative, abteilungsübergreifende Beschlüsse.
- **2/3-Mehrheit:** neue Forschungsprogramme, größere Ressourcenumverteilung,
  Änderung von Prozessen mit breiter Wirkung.
- **Veto:** F bei Kapitalrisiko, J bei System-/Security-Risiko. Ein Veto blockiert
  die Umsetzung; es kann nur durch Owner und Audit aufgehoben werden.
- **Reserviert:** Verfassung, Risikogrenzen, Auth, Secrets, Geld, Produktion,
  Löschung. Diese werden nicht abgestimmt, sondern an den Owner geleitet.
- **Kein Quorum:** Entscheidung wird vertagt; dringende operative Aufgaben laufen
  weiter; die nächste Sitzung muss den Punkt erneut behandeln.
- **Stimmgleichheit:** gilt als „nicht beschlossen“; Rückverweis an Leiter-Rat oder
  Vertagung.

## 5.7 Ergebnisse

Nach jeder Sitzung werden zwingend erzeugt:

1. **Protokoll** mit Agenda, Anwesenheit, Beiträgen, Dissens, Abstimmungen und
   Beschlüssen.
2. **Beschlüsse** in `company_decisions` mit Begründung, Evidenz, Verantwortlichem,
   Frist und Review-Termin.
3. **Actions** in `company_actions`, jeweils mit Task-ID.
4. **Neue Tasks** in der Queue, mit Abteilung, Priorität und Akzeptanzkriterium.
5. **Vault-Notiz** im Konferenzordner, mit Frontmatter, Tags, Links.
6. **Owner-Brief** von S2 (eine Seite) und Gesprächsnotiz von S1.
7. **Fortschrittsprüfung:** offene Actions der letzten Sitzung werden zuerst
   bewertet; nicht erledigte Actions brauchen einen Grund.

## 5.8 3D-Choreografie

Die 3D-Welt ist Darstellung der serverseitigen Sitzung, keine Voraussetzung:

- **23:55:** Agenten verlassen ihre Stationen; Türen öffnen; Wege zum Saal.
- **00:00:** Ränge gefüllt; Abteilungsbanner; zentrale Projektion startet.
- **Berichte:** Sprecherlicht nur für den Agenten, der tatsächlich einen Beitrag
  liefert; Hologramm zeigt die echten Kennzahlen.
- **Kreuzverhör:** Beiträge erscheinen als Text/Beleg im Protokollband; keine
  erfundenen Gesten.
- **Abstimmung:** Stimmen werden als echte Ja/Nein/Enthaltung angezeigt; Dissens
  bleibt sichtbar.
- **Abschluss:** Actions und Verantwortliche auf der großen Wand; Vault-Symbol.
- **Nach der Sitzung:** Agenten kehren an ihre Stationen zurück; neue Tasks werden
  sichtbar.

Wenn der Browser geschlossen ist, läuft die Sitzung im Server weiter. Beim nächsten
Öffnen wird der aktuelle Zustand oder ein abgeschlossenes Protokoll angezeigt,
nicht eine erfundene Live-Szene. Alle 103 Avatar-Plätze werden über Instancing
dargestellt; die Sitzordnung ist deterministisch.

## 5.9 Betrieb ohne Owner

- Keine Owner-Anwesenheit, keine Owner-Zustimmung für normale Beschlüsse.
- Der Owner erhält den Brief beim nächsten Login.
- Kritische Security-/Risikoereignisse werden sofort als Owner-Aufgabe markiert,
  aber die Sitzung läuft weiter und trifft die nicht-reservierten Entscheidungen.
- Ein Ausfall des Browsers beendet die Sitzung nicht.
- Ein Ausfall des Servers wird beim nächsten Start nachgeholt.

## 5.10 Fehler- und Ausfallverhalten

| Fall | Verhalten |
|---|---|
| Keine Daten | Agenda läuft; Bericht „keine Daten“; keine erfundenen Zahlen; keine Trading-Freigabe |
| LLM nicht verfügbar | deterministische Berichte und Templates; Sitzung läuft |
| DB gesperrt | Retry/Backoff; Sitzung pausiert sichtbar; kein Datenverlust |
| Quorum fehlt | vertagen; offene Actions bleiben sichtbar |
| Security-Incident | Incident-Agenda zuerst; J kann Feature stoppen |
| Server-Neustart | Sitzung aus `conference_sessions` wiederaufnehmen; idempotent |
| Doppelter Start | `scheduled_date` unique; zweiter Start wird ignoriert |
| Vault nicht schreibbar | Protokoll in DB; Vault-Nachholtask; Alarm |

## 5.11 Datenmodell der Konferenz

- `conference_sessions` — eine Sitzung pro Tag, Phase, Quorum, Status.
- `conference_attendance` — 103 Einträge pro Sitzung.
- `conference_statements` — Beiträge mit Typ, Agent, Text, Evidenz.
- `conference_votes` — eine Stimme pro Leiter und Beschluss.
- `company_decisions` — Beschluss mit Ebene, Status, Begründung, Frist.
- `company_actions` — Massnahme mit Task, Owner, Frist, Review.
- `konferenzen` — bestehendes JSON-Archiv; bleibt unverändert.

## 5.12 Abnahmekriterien der Konferenz

- Läuft um 00:00 Europe/Zurich ohne Browser und ohne Owner.
- Alle 103 Teilnehmer werden erfasst; 10 Leiter stimmberechtigt.
- Jede Aussage hat eine Quelle oder ist als Hypothese markiert.
- Quorum, Mehrheit, 2/3 und Vetos sind getestet.
- Jeder Beschluss erzeugt mindestens eine Action mit Task und Frist.
- Offene Actions werden in der nächsten Sitzung geprüft.
- Protokoll und Owner-Brief sind innerhalb von 5 Minuten nach Ende verfügbar.
- Ein Serverneustart erzeugt keine doppelte Sitzung und keinen Datenverlust.

---

# 6. Hardware- und Ressourcenplan

## 6.1 Arbeitslasten

| Last | Charakter | Ort | Begrenzung |
|---|---|---|---|
| Web/API | leicht, viele kleine Requests | Railway | ein Service |
| 103 Agenten-Tasks | kurze deterministische Handler | Railway | 4 Worker, 1 Task/Agent |
| Backtests | CPU-intensiv | Railway | 1 gleichzeitig, Queue |
| Spider | Netzwerk-I/O | Railway | bestehende Limits |
| Paper-Broker | leicht | Railway | keine echten Orders |
| 3D-Rendering | GPU-intensiv | Browser | 60 FPS Budget |
| LLM (optional) | GPU/RAM-intensiv | lokal | 1 Worker, standardmäßig aus |

## 6.2 Server

**Minimum für Phase 1–5:** 2 vCPU, 1 GB RAM, 2 GB freier Speicher, ein
persistentes Volume.  
**Empfohlen für Backtests und 103 Agenten:** 2 vCPU, 2 GB RAM, 2–4 GB Volume.  
**Nicht nötig:** GPU auf dem Server, separates Redis, separates Postgres,
Message-Broker, Kubernetes.

Die genauen Railway-Grenzen werden vor der Ressourcenentscheidung gemessen, nicht
geraten. Wenn die aktuelle Instanz zu klein ist, wird das vor dem Deployment
gemeldet und vom Owner entschieden.

## 6.3 Browser / 3D

| Ziel | Minimum | Empfohlen |
|---|---|---|
| Desktop | WebGL2, 8 GB RAM, integrierte GPU, 30 FPS | 16 GB RAM, dedizierte GPU, 60 FPS |
| Mobile | moderne Browser, 2D-Fallback | 3D-Übersicht mit reduzierten Effekten |
| Auflösung | 1280×720 | 1920×1080 |

Die 3D-Welt wird nicht auf dem Server gerendert. Ein schwacher Server beeinflusst
die Grafik nicht, außer durch API-Latenz.

## 6.4 LLM-Ressourcen (optional)

- Standard: **aus**. 100 Agenten benötigen kein LLM.
- Wenn der Owner später ein lokales Open-Source-Modell freigibt:
  - 7B quantisiert: ca. 6–8 GB VRAM, 16 GB RAM,
  - 13B quantisiert: ca. 10–12 GB VRAM, 24 GB RAM,
  - CPU-Betrieb ist möglich, aber langsam und nicht für 100 parallele Dialoge.
- Das Modell läuft lokal, nicht auf Railway, ohne kostenpflichtige API.
- Es formuliert und fasst zusammen; es trifft keine Order-, Risiko- oder
  Security-Entscheidung.
- Ein LLM-Worker, max. 30 Minuten/Tag, keine 100 parallelen Aufrufe.

## 6.5 Speicherbedarf

Annahme: 103 Agenten, ca. 5 Tasks pro Agent und Tag, ca. 1.000 Nachrichten/Tag,
ca. 5 Events pro Task, 90 Tage heiße Daten.

| Posten | Schätzung |
|---|---:|
| Tasks/Events/Messages, 90 Tage | ca. 400–900 MB inkl. Indizes |
| bestehende Marktdaten/Validierungen | bestehender Bestand, monitorieren |
| Vault | ca. 50–150 MB |
| Logs | ca. 50–100 MB, rotierend |
| 3D-Assets | < 10 MB |
| Reserve/Backup | ca. 500 MB |
| **Empfohlenes Volume** | **2 GB, besser 4 GB** |

Das aktuelle Railway-Volume ist nahezu leer. Vor einer Live-Demo müssen die echten
Daten wiederhergestellt und die Größe gemessen werden. Der Plan löscht keine
bestehenden Daten.

## 6.6 Netzwerk und externe Dienste

- Bestehende Spider-Quellen und Marktdaten; keine neuen kostenpflichtigen APIs.
- Keine freie Agenten-Netzwerkschicht; nur registrierte Handler.
- Lokales LLM ohne Internet.
- 3D-Assets lokal; keine externen CDNs, keine Tracker.
- Keine Zahlungs-, Broker- oder Wallet-Anbindung.

## 6.7 Kosten

- Neue kostenpflichtige Dienste: **0**.
- Railway: bestehender Tarif; ein Upgrade nur nach Messung und Owner-Freigabe.
- Optional: lokale GPU/Hardware für LLM; Owner-Entscheid.
- 3D verursacht keine Serverkosten, aber Client-GPU/Strom.
- Jede kostenverursachende Aktion braucht eine ausdrückliche Owner-Freigabe.

## 6.8 Backup und Wiederherstellung

- Täglich ein konsistentes SQLite-Backup (WAL-Checkpoint, `.backup`).
- Vault als tar/zip; Konfiguration ohne Secrets.
- Aufbewahrung: 7 täglich, 4 wöchentlich, 12 monatlich.
- Vor jeder Migration: zusätzliches Backup, Test-Restore.
- Restore-Test mindestens einmal pro Phase.
- Kein Backup enthält Secrets in Klartext; Secrets bleiben im Secret Store.

## 6.9 Beobachtbarkeit

- `/api/health`: DB, Scheduler, Queue, letzter Paper-Tick, letzte Konferenz,
  Volume-Größe, 3D-Asset-Version.
- Queue: Tiefe, älteste Task, Dead-Letter, Lease-Fehler.
- Runtime: Worker-Heartbeat, Task-Dauer, Fehlerrate.
- 3D: FPS, Draw Calls, Speicher (nur Client-Diagnose, keine Verfolgung).
- Logs: strukturiert, ohne Secrets, mit Task-/Agent-ID.
- Alarme: Paper-Sperre, Risikoverletzung, DB voll, Scheduler steht, Security.

## 6.10 Grenzen und Skalierung

- Ein Prozess, eine SQLite-DB, ein Volume.
- Mehrere Instanzen würden eine verteilte Queue und geteilte DB erfordern; das ist
  **nicht** Phase 1.
- Wenn die Queue-Latenz trotz 4 Workern steigt, wird zuerst die Task-Granularität
  verbessert, dann die Workerzahl, dann über Postgres/Redis nachgedacht.
- 103 Agenten sind ein Produkt-, kein Thread-Ziel. Skalierung wird an Tasks und
  Messwerten entschieden.

---

# 7. Realistischer Entwicklungsplan

## 7.1 Phasenübersicht

Die Dauer sind Größenordnungen für einen erfahrenen Entwickler mit
Unterstützung durch Coding-Agenten, keine Kalenderzusage. Qualität und echte
Datenbindung gehen vor Tempo.

| Phase | Inhalt | Dauer | Ergebnis |
|---|---|---:|---|
| P0 | Analyse, Grundriss, Architektur, dieses Dossier | erledigt | Freigabevorlage |
| P1 | Unternehmensfundament: Profile, Queue, Policy, DB, Tests | umgesetzt | 103 Profile, echte Tasks, keine 3D |
| P2 | Company-API + 3D-Hülle: Atrium, ein Deck, Karte, Steuerung | 2–3 Wochen | begehbare Hülle mit echten Statusdaten |
| P3 | Erste zwei Abteilungen: A + D, 20 Agenten, echte Arbeit | 3–4 Wochen | vertikaler Funktionsbeweis |
| P4 | Executive Deck, Sekretariat, CEO-Sicht und Fragen | 2–3 Wochen | S1–S3 + CEO-Büro |
| P5 | Alle Abteilungen, 103 Agenten, alle Räume, Kommunikation | 4–6 Wochen | vollständiges Unternehmen |
| P6 | Autonomes Management, Konferenz, 3D-Zeremonie | 3–4 Wochen | autonomer Tagesbetrieb |
| P7 | Härtung, Performance, Security, Deployment, Abnahme | 2–3 Wochen | belastbare Version |

**MVP nach P1–P4:** ca. 8–12 Wochen, mit zwei Abteilungen, CEO-Etage und echter
Datenbindung.  
**Vollbild nach P1–P7:** ca. 17–25 Wochen, abhängig von Assetqualität,
Backtest-Laufzeiten und Reviewschleifen.

## 7.2 Phase 0 — Analyse und Freigabe (erledigt)

**Ergebnis:** dieses Dossier.  
**Nicht enthalten:** Codeänderungen, Migrationen, 3D, Agentenläufe.  
**Gate:** Owner bestätigt Grundriss, Agentenzahl, Technik und Startphase.

## 7.3 Phase 1 — Unternehmensfundament (umgesetzt)

**Ziele:**

- 103 Profile aus `AGENTEN.md` in `agent_profiles`.
- Neue Tabellen und Migration; bestehende Daten unangetastet.
- Task-Queue mit Lease, Retry, Dead-Letter, Dependencies.
- Policy-Engine mit harten Invarianten.
- Runtime mit vier Workern; Scheduler-Anbindung.
- Erste echte Tasks für alle 103 Profile, ohne 3D.
- Tests für Queue, Policy, Profile, Migration, Paper-Sperre.

**Abnahme:**

- 100 Fachagenten + 3 Sekretäre sind auffindbar.
- Jede Task hat Ergebnis oder klaren Fehler; keine Dekorationsläufe.
- 10 Abteilungen à 10; keine doppelten IDs/Rufnamen.
- Bestehende 56 Tests bleiben grün; neue Tests decken die Kernlogik.
- Kein LLM, keine 3D, kein neuer kostenpflichtiger Dienst.
- DB-Backup und Rollback getestet.

**Demo:** Queue-Dashboard/JSON, das 103 Profile und echte Task-Ergebnisse zeigt.

## 7.4 Phase 2 — Company-API und 3D-Hülle

**Ziele:**

- `/api/company/overview|agents|tasks|rooms|stream`.
- 3D-Hülle mit Atrium, einem Deck (Command), Karte, Türen, Aufzugattrappe,
  First-Person-Steuerung, 2D-Fallback.
- Datenbindung: echte Agentenstatus, keine erfundenen Bildschirme.
- Performance-Budget und WebGL-Smoke-Test.

**Abnahme:**

- Ein Raum ist begehbar; Karte führt zu ihm; 2D-Fallback funktioniert.
- Agentenstatus stammt aus der DB; „keine Daten“ ist sichtbar.
- Keine Konsole-/Seitenfehler bei 1440×1000 und 432×900.
- Draw Calls/Dreiecke im Budget.

**Demo:** Command Center betreten, Agentenstatus und offene Tasks sehen.

## 7.5 Phase 3 — Erste zwei Abteilungen (A + D)

**Ziele:**

- Command Center und Trading Floor vollständig.
- 20 Agenten mit echten Stationen, Tasks, Screens und Statusanimationen.
- Paper-Trading-Anbindung unverändert; keine echten Orders.
- Task-Ergebnisse sichtbar im Raum und im Agentenprofil.
- Erste Kommunikation A ↔ D.

**Abnahme:**

- Jeder sichtbare Roboter hat Profil, Task und Ergebnis oder „WARTEND“.
- Ein Paper-Trade ist bis zur Datenbank nachvollziehbar.
- Veto/Stopp wird sichtbar, ohne echte Order.
- Zwei Abteilungen kommunizieren über echte Nachrichten.
- Performance mit 20 Agenten stabil.

**Demo:** Ein Tag im Trading Floor, inklusive blockiertem Trade und Review.

## 7.6 Phase 4 — Executive Deck und Sekretariat

**Ziele:**

- CEO Office, Reception, Secretary Office, Meeting, Lounge, Observation.
- S1–S3 mit Profilen, Arbeitsplätzen, Briefings und CEO-Fragen.
- CEO-Übersicht mit echten Aggregaten.
- 3D-Interaktion „Frage an S1“; Antwort mit Quellen.

**Abnahme:**

- Drei Sekretäre sind sichtbar und haben echte Aufgaben.
- Keine Antwort ohne Quelle oder „keine Daten“.
- Keine S1-Antwort löst Order/Risiko/Deploy aus.
- CEO-Brief und Konferenz-Kurzfassung werden erzeugt.
- Owner kann Räume direkt besuchen.

**Demo:** Frage „Wie läuft das Unternehmen?“ mit belegter Antwort.

## 7.7 Phase 5 — Alle Abteilungen und 103 Agenten

**Ziele:**

- B, C, E, F, G, H, I, J mit Räumen, Stationen, Robotern, Tasks.
- Alle 103 Profile aktiv; WIP- und Statuslogik.
- Kommunikation zwischen allen Abteilungen; Threads, Ack, Evidence.
- Vault-Anbindung für Konferenz, Forschung, Entscheidungen.
- Observatory mit bestehender Weltkugel; Security mit echten Audits.

**Abnahme:**

- 103 Agenten sichtbar/zuordenbar; keine Doppelbelegung.
- Alle 49 Räume begehbar; Türen/Aufzüge funktionieren.
- Jede Abteilung liefert echte Ergebnisse oder klare Leerzustände.
- Cross-Department-Szenario B → G → E → C → F → D getestet.
- 3D-Performance mit 103 Agenten im Budget.

**Demo:** Rundgang durch alle Decks, ein vollständiger Research-to-Paper-Flow.

## 7.8 Phase 6 — Autonomes Management und Konferenz

**Ziele:**

- Leiter-Rat, Entscheidungsmatrix, Autonomiebudget.
- Mitternachtskonferenz mit Agenda, Quorum, Abstimmung, Vetos, Actions.
- 3D-Choreografie: Bewegung in den Saal, Hologramm, Sprecherlicht.
- Betrieb ohne Owner/Browser; Nachholung; Vault-Archiv.
- Follow-up-Prüfung der Actions.

**Abnahme:**

- Konferenz läuft um 00:00 Europe/Zurich ohne Browser.
- 103 Teilnehmer erfasst; 10 Leiter stimmen; Quorum/Vetos getestet.
- Jeder Beschluss erzeugt Task + Verantwortlichen + Frist.
- Nächste Sitzung prüft offene Actions.
- Owner erhält Brief, ohne eingreifen zu müssen.
- Keine erfundenen Aussagen; Dissens sichtbar.

**Demo:** Eine vollständige Mitternachtskonferenz mit echten Daten.

## 7.9 Phase 7 — Härtung und Abnahme

**Ziele:**

- Performance, Speicher, Migration, Backup/Restore.
- Security-Review: Auth, Tool-Rechte, Paper-Sperre, Prompt-Injection.
- 3D-Polish, Mobile-Fallback, Barrierefreiheit.
- Railway-Deployment mit Feature-Flags; Rollback getestet.
- Dokumentation und Owner-Abnahme.

**Abnahme:**

- Alle Tests grün; Performance-Budget erreicht.
- Keine Secrets im Client/Log.
- Paper-Sperre dreifach geprüft.
- Restore aus Backup erfolgreich.
- Owner kann das Unternehmen beobachten, ohne jeden Schritt zu genehmigen.
- 3D-Welt und 2D-Fallback funktionieren.

## 7.10 Mapping auf die 12 Phasen des Masterprompts

| Masterprompt | Umsetzung |
|---|---|
| 1. Projekt analysieren | P0 |
| 2. Gesamtarchitektur und Grundriss | P0 (dieses Dossier) |
| 3. Autonome Agenten-Infrastruktur | P1 |
| 4. Management und Abteilungsleiter | P1 + P6 |
| 5. CEO-Sekretariat | P4 |
| 6. Obsidian und Wissenssystem | P1 (Schema) + P5 |
| 7. Erste zwei Abteilungen | P3 |
| 8. 3D-Raumschiff und Navigation | P2 + P3 + P5 |
| 9. CEO-Etage | P4 |
| 10. Alle weiteren Abteilungen | P5 |
| 11. Mitternachtskonferenz | P6 |
| 12. Gesamtsystem testen/optimieren | P7 |

## 7.11 Risiken und Gegenmaßnahmen

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| Scope zu groß | Stillstand, halbe Welt | Phasen, vertikaler Schnitt, Gates |
| 3D sieht leer/steril aus | Vision verfehlt | Raumprogramm, Requisiten, Licht, echte Daten |
| 100 Agenten wirken wie Deko | Vertrauensverlust | Profile, Tasks, Evidence, klare Status |
| SQLite-Contention | blockierte Tasks | ein Writer, WAL, kurze Transaktionen, Worker-Limit |
| Railway-Volume zu klein | Datenverlust/Ausfall | 2–4 GB, Retention, Monitoring, Backup |
| LLM-Kosten/Qualität | unkontrolliert | standardmäßig aus, lokal, Budget, Evidence |
| Prompt-Injection | Manipulation | Inhalte als Daten, J4, Allowlist, Validator |
| 3D-Performance | Ruckeln, Abbruch | LOD, Instancing, Streaming, Budget |
| Codeänderung durch Agenten | Regression | Branch, Tests, Review, Rollback, kein Auto-Deploy |
| Owner wird wieder Flaschenhals | Autonomie verfehlt | reserved decisions begrenzen, Briefings, keine Alltagsfreigabe |
| Daten fehlen | leere Welt | Leerzustände, echte Daten wiederherstellen, keine Fake-Daten |
| Sicherheitsregel wird umgangen | Paper-only verletzt | F/J/A-Kontrollen, Tests, Audit, Owner-Alarm |

## 7.12 Freigabepunkte

1. **Gate 0:** dieses Dossier — Owner bestätigt Struktur und Start.
2. **Gate 1:** nach P1 — 103 Profile und Queue funktionieren ohne 3D.
3. **Gate 2:** nach P3 — zwei Abteilungen mit echter Arbeit und 3D.
4. **Gate 3:** nach P4 — Sekretariat und CEO-Sicht belegt.
5. **Gate 4:** nach P5 — alle Abteilungen und Räume.
6. **Gate 5:** nach P6 — Konferenz läuft autonom.
7. **Gate 6:** vor Produktionsdeployment — Owner-Freigabe.

Ohne Gate-Freigabe wird die nächste Phase nicht begonnen. Das ist kein
Wasserkopf, sondern verhindert, dass ein schöner 3D-Raum ohne funktionierende
Firma entsteht.

## 7.13 Definition of Done

Das Gesamtsystem gilt als abgenommen, wenn:

- 100 Fachagenten + 3 Sekretäre existieren und sichtbar sind,
- jeder sichtbare Agent eine echte Aufgabe/Ergebnisbindung hat,
- alle 49 Räume und acht Decks begehbar sind,
- 3D und 2D-Fallback funktionieren,
- die Mitternachtskonferenz ohne Owner und Browser läuft,
- das Sekretariat belegte Antworten liefert,
- Paper-only und Risikogrenzen technisch erzwungen sind,
- Codeänderungen versioniert, getestet und rückrollbar sind,
- die bestehenden Tests grün bleiben,
- Backup/Restore und Migration getestet sind,
- keine kostenpflichtigen Dienste ohne Owner-Freigabe eingeführt wurden,
- der Owner das Unternehmen beobachten kann, ohne jeden Schritt zu genehmigen.

## 7.14 Was nach der Freigabe zuerst passiert

Empfohlener Start: **Phase 1**, nicht die 3D-Welt.

1. Backup der bestehenden DB und des Vaults.
2. Branch und Migration vorbereiten.
3. 103 Profile und Task-Queue implementieren.
4. Policy-Engine und Paper-Sperre testen.
5. Bestehende Tests plus neue Kern-Tests ausführen.
6. Ergebnis mit echten Task-Läufen zeigen.
7. Erst nach Gate 1 mit der 3D-Hülle beginnen.

Damit steht das Unternehmen zuerst auf echten Daten. Die 3D-Welt kommt danach als
sichtbare, begehbare Darstellung — nicht als Ersatz für Substanz.

---

# 8. Freigabe

Dieser Masterplan ist die Entscheidungsvorlage für die größere Umsetzung. Er
ändert noch keinen Code, keine Datenbank und kein Deployment.

**Freigabe:** Phase 1 (Unternehmensfundament) ist umgesetzt. Die nächste Freigabe
betrifft Phase 2 (Company-API und 3D-Hülle); die 3D-Welt folgt erst nach Gate 1.

**Nicht freigegeben sind ohne ausdrückliche Owner-Entscheidung:** echte
Broker-Orders, kostenpflichtige APIs, Produktionsdeployment, Löschen von Daten,
Änderung der Risikogrenzen, Abschalten der Auth oder der Paper-Sperre.

Bis zur Freigabe bleibt das Projekt im Planungszustand.
