# Phase 4 — Missionen, Queue, Retry und Fortschritt

**Stand:** 10. November 2026
**Grundlage:** `orakel/nexus/missionen.py`, `orakel/db.py`
(`nexus_missionen`, `nexus_tasks`), `orakel/nexus/status.py`,
`orakel/web.py`, `orakel/scheduler.py`, `orakel/web/static/app.js`

---

## 1. Was jetzt passiert

Eine Mission ist eine persistente, nachvollziehbare Arbeitskette auf den
Kernaussagen aus Phase 3. Es gibt keinen LLM-Aufruf und keine erfundenen
Agenten. Phase 4 legte die ersten drei Aufgaben an; Phase 5 erweitert dieselbe
Kette auf fünf Aufgaben:

| Aufgabe | Arbeit | Ergebnis |
|---|---|---|
| `lage` | passende gespeicherte Kernaussagen über Suchbegriffe finden | Claim-IDs, Suchbegriffe, Hinweis auf Datenlücke |
| `pruefung` | Belege, unabhängige Hosts, Widersprüche und Prüfbedarf sammeln | Prüfbericht je Claim |
| `gegenargument` | 15 Prüfrollen und den Gegenargument-Agenten ausführen | Alternativerklärungen und Rollenbefunde |
| `bericht` | Belastbarkeit, Gegenargumente und offene Fragen formulieren | Text und strukturierter JSON-Bericht |
| `weitergabe` | Bericht an IntelNetz und Vault übergeben | Weiterleitungskennung und Vault-Pfad |

Die Suche ist bewusst **Stichwortsuche**, keine Semantik. Gibt es keine
Suchbegriffe, werden die zwölf belastbarsten gespeicherten Claims gezeigt. Gibt
es Suchbegriffe, aber keinen Treffer, endet die Mission mit einer ausdrücklichen
Datenlücke — nicht mit einer erfundenen Antwort.

Beispiel für einen Phase-4-Bericht (Phase 5 ergänzt Gegenargumente,
Prüfrollen und Weitergabe):

```text
Mission MS-20261110-0001 — EZB Leitzins
Auftrag: Prüfe die aktuelle Datenlage zum Leitzins der EZB.

Datenlage: 1 Kernaussage, 2 Belege, 2 unabhängige Hosts, 0 Widersprüche.

Befunde:
- [bestätigt, Grad 0,82] EZB hebt den Leitzins auf 4,5 Prozent — 2 unabhängige Quellen, 2 Belege

Offene Fragen:
- Keine offenen Fragen aus dem aktuellen Bestand. Das ist keine Aussage über die Zukunft.

Grenzen: Regelbasierte Auswertung gespeicherter Kernaussagen. Es wurden keine
neuen Quellen abgerufen und keine Semantik geprüft.
```

---

## 2. Queue, Lease und Retry

### Status

**Mission:** `offen` → `laufend` → `abgeschlossen` oder `fehlgeschlagen`.

**Aufgabe:** `offen` → `laufend` → `erledigt`; nach einem Fehler wieder
`offen`, nach dem letzten Versuch `fehlgeschlagen`. Folgeschritte eines
endgültig gescheiterten Schritts werden `blockiert`.

### Lease

`nexus_task_naechste` least eine fällige Aufgabe atomar mit
`BEGIN IMMEDIATE`. Die Lease gilt standardmäßig **300 Sekunden**. Stürzt der
Prozess ab, setzt der nächste Lauf abgelaufene Leases zurück. Ist der letzte
Versuch verbraucht, wird die Aufgabe zum Dead-Letter und die Mission
`fehlgeschlagen`. Ein erledigter Schritt wird nie erneut ausgeführt.

### Retry

Standard: höchstens **3 Versuche** pro Aufgabe.

```
Wartezeit = min(3600, 30 · 2^(Versuch−1)) Sekunden
```

Also 30 s nach dem ersten, 60 s nach dem zweiten Fehler. Ein Fehler wird immer
in `nexus_tasks.fehler` gespeichert; der Worker läuft weiter und blockiert die
übrigen Missionen nicht.

### Fortschritt

Der Fortschritt ist `erledigte Aufgaben / Gesamtaufgaben`, gerundet auf ganze
Prozent. Gespeichert wird er in `nexus_missionen.fortschritt`; die Anzeige
kommt aus SQLite und wird nicht im Browser geschätzt.

---

## 3. Datenmodell

| Tabelle | Inhalt |
|---|---|
| `nexus_missionen` | Kennung `MS-JJJJMMTT-NNNN`, Titel, Auftrag, Priorität, Status, Fortschritt, Zeitstempel, Abschlussbericht als JSON |
| `nexus_tasks` | Mission, Position, Rolle, Ziel, Status, Versuche, `max_versuche`, Lease, Fälligkeit, Ergebnis-JSON, Fehler, Vorgänger |

Mission und Aufgaben werden in **einer Transaktion** angelegt. Der Bericht wird
in derselben Transaktion übernommen, in der die letzte Aufgabe erledigt wird.
Ein abgebrochener Lauf hinterlässt keinen halb fertigen Abschluss.

Prioritäten: `niedrig`, `mittel`, `hoch`, `kritisch`; die Queue zieht
`kritisch` zuerst.

---

## 4. Schnittstellen

### HTTP

```text
POST /api/nexus/mission                    Mission anlegen
GET  /api/nexus/missionen?limit=20         Liste und Queue-Statistik
GET  /api/nexus/mission/{kennung}          Detail, Aufgaben und Bericht
POST /api/nexus/mission/{kennung}/lauf     fällige Aufgaben ausführen
GET  /api/nexus/status                     enthält missionen.statistik und -liste
```

`POST /api/nexus/mission` erwartet JSON:

```json
{
  "titel": "EZB Leitzins",
  "auftrag": "Prüfe die Datenlage zum Leitzins der EZB.",
  "prioritaet": "hoch"
}
```

Der Lauf-Endpunkt nimmt `max_tasks` (1–50) entgegen. Er führt nur fällige,
nicht blockierte Aufgaben aus; `max_tasks=10` bedeutet nicht, dass zehn
Aufgaben existieren müssen.

### CLI

```bash
python -m orakel.nexus mission --titel "EZB Leitzins" \
  --auftrag "Prüfe die Datenlage zum Leitzins der EZB." --start
python -m orakel.nexus missionen --limit 20
python -m orakel.nexus mission-lauf --kennung MS-20261110-0001 --max 10
```

### Dauerbetrieb

Ist der Web-Takt aktiv (`paper.takt_aktiv = true`), ruft `scheduler.takt_schritt`
alle Takte `Missionen.weiterarbeiten(max_tasks=5)` auf. Der Nachtlauf selbst
legt **keine** Missionen an. Es gibt keinen automatischen Generator, der sich
Fragen ausdenkt; Missionen kommen aus API, CLI oder einem späteren Zeitplan.

---

## 5. Dashboard

Im Spider-Tab gibt es die Karte **Missionen**:

- Kennzahlen: Missionen, laufend/offen, abgeschlossen, durchschnittlicher
  Fortschritt.
- Formular für Titel, Auftrag und Priorität; „Mission anlegen & starten“ legt
  die Mission an und führt die Aufgaben aus.
- Liste mit Status, Fortschrittsbalken, Aufgabenstand und Fehlerzahl.
- **Weiterarbeiten** für offene oder fehlgeschlagene Missionen.
- **Bericht** lädt den gespeicherten Text aus
  `GET /api/nexus/mission/{kennung}`.

Die Oberfläche erfindet keine Inhalte: Ohne Missionen steht dort ein leerer
Hinweis; ohne Claim endet der Bericht als Datenlücke.

---

## 6. Tests und Prüfungen

**168 Tests grün** (10. November 2026). Die Missionstests umfassen sechs
Fälle:

1. Mission läuft über einen simulierten Prozessneustart weiter und schreibt
   einen Bericht mit zwei unabhängigen Hosts.
2. Ohne passende Kernaussage endet die Mission ehrlich als Datenlücke.
3. Fehler → Backoff → zweiter Fehler → Dead-Letter; Folgeschritte blockiert.
4. Abgelaufene Lease wird nach einem simulierten Absturz zurückgeholt.
5. Höhere Priorität wird vor der Erstellungsreihenfolge ausgeführt.
6. Gegenargumente benennen Widerspruch und Kopie.

Seit Phase 5 kommen 15 Prüfrollen, Gegenargumente, Vault- und Intel-Übergabe
hinzu; Details: [PHASE-5.md](PHASE-5.md).

Zusätzlich geprüft:

- `node --check orakel/web/static/app.js` grün,
- `compileall` grün, `git diff --check` grün,
- CLI-Anlage und -Lauf mit einer temporären Datenbank: Mission
  `abgeschlossen`, Fortschritt `100`,
- HTTP-Smoke-Test mit `uvicorn` und temporärer Datenbank: Anlegen, Lauf über
  fünf Aufgaben, Detailbericht, Liste und `/api/nexus/status` erfolgreich.

Der lokale Root-Bestand `orakel.db` hatte zum Prüfzeitpunkt 34 Artikel, aber
keine `nexus_meldungen`/`nexus_claims`. Die CLI-Mission lief deshalb korrekt
mit **0 Kernaussagen** und einem Datenlücken-Bericht ab. Es wurden keine
Testdaten als echte Erkenntnisse ausgegeben.

---

## 7. Ehrliche Grenzen

- **Keine neuen Quellen.** Eine Mission liest nur den vorhandenen Claim-Bestand.
  Sie löst keinen Feed-Abruf und keine Volltextrecherche aus.
- **Keine Semantik.** Suchbegriffe werden als Wörter verglichen. Synonyme,
  Übersetzungen und Bedeutungen werden nicht verstanden.
- **Kein eigener Wahrheitsbegriff.** Der Bericht wiederholt Status und
  Unsicherheit aus Phase 3. `bestätigt` heißt weiterhin nur: mindestens zwei
  unabhängige Original-Hosts und genug Belege nach der dortigen Heuristik.
- **15 Prüfrollen, keine Modellagenten.** Die Rollen in Phase 5 sind
  deterministische Prüfungen, keine simulierten Persönlichkeiten.
- **Ein Prozess.** Die Queue ist für einen lokalen SQLite-Worker gebaut. Mehrere
  gleichzeitige Worker sind nicht getestet; `BEGIN IMMEDIATE` schützt die
  Lease-Vergabe, ersetzt aber keinen verteilten Scheduler.
- **Übergabe nur mit Kernaussage.** Ohne Claim erzeugt die Mission weder eine
  Intel-Weiterleitung noch eine Vault-Notiz; das ist Absicht, keine Panne.
- **Vault/Intel sind real, aber keine neue Recherche.** Sie verteilen den
  vorhandenen Bericht; sie rufen keine Quellen ab und ändern keine Regeln.
- **UI nicht visuell geprüft.** Die Karte und die Handler sind eingebaut, aber
  in diesem Lauf nur per `node --check` und HTTP-Smoke-Test geprüft, nicht im
  Browser angesehen.
- **Keine echten Orders, keine Regeländerungen.** Missionen ändern weder
  Handelsregeln noch Sicherheitsgrenzen.

---

## 8. Nächster Schritt

Phase 5 ist umgesetzt: 15 Prüfrollen, Gegenargument-Agent, Vault- und
Intel-Übergabe. Siehe [PHASE-5.md](PHASE-5.md). Als Nächstes folgen
Wissensgraph und Prognosekontrolle (Phase 6); die 3D-Darstellung bleibt bewusst
später. Auf der Oracle-VM läuft weiterhin der alte Stand, bis dort gepullt und
der Takt neu gestartet wird.
