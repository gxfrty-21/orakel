# Phase 6 — Wissensgraph und Prognosekontrolle

**Stand:** 10. November 2026
**Grundlage:** `orakel/nexus/graph.py`, `orakel/nexus/kalibrierung.py`,
`orakel/db.py`, `orakel/nexus/bewertung.py`, `orakel/nexus/nacht.py`,
`orakel/nexus/status.py`, `orakel/nexus/__main__.py`, `orakel/web.py`,
`orakel/web/static/index.html`, `orakel/web/static/app.js`

---

## 1. Was jetzt passiert

Phase 6 ergänzt zwei persistente, nachprüfbare Schichten:

```text
Kernaussagen/Belege/Widersprüche → nexus_edges → Wissensgraph
Intel-Aufträge/Manuelle Prognosen → nexus_forecasts → Prüfung gegen M15-Kerzen
                                      → Trefferquote/Brier-Score
```

Es gibt weiterhin **keine echten Orders, keine Änderung der Handels- oder
Risikoregeln und keine erfundenen Prognosen**. Der Graph und die Kalibrierung
sind additiv; bestehende Pfade bleiben unverändert.

---

## 2. Wissensgraph

### Aufbau

`orakel/nexus/graph.py` leitet den Graphen ausschließlich aus gespeicherten
Daten ab:

| Kante | Von | Nach | Begründung |
|---|---|---|---|
| `gehoert_zu` | `claim:<id>` | `thema:<name>` | regelbasierte Themeneinordnung |
| `belegt_durch` | `claim:<id>` | `quelle:<host>` | Anzahl Belege, Originale und Kopien |
| `widerspruch` | `quelle:<host>` | `quelle:<host>` | gespeicherter Widerspruch |

Die Kanten liegen in `nexus_edges`. Der Aufbau ist deterministisch und
idempotent: wiederholtes `graph_auffrischen` erzeugt dieselben Beziehungen. Als
Kantenzeitpunkt wird die früheste echte Beobachtung der beteiligten Daten
verwendet; der Zeitfilter `24h`, `7d`, `30d` oder `alle` arbeitet damit auch
nach einem Rebuild korrekt.

`claims_auffrischen` baut den Graphen nach jeder neuen Claim-Bewertung neu auf.
Der Nachtlauf ruft ihn zusätzlich auf. Fehler werden im Nachtbericht als
`graph_fehler` sichtbar, nicht verschluckt.

### Lesen

`GET /api/nexus/graph?zeitraum=7d` liefert:

```json
{
  "ok": true,
  "zeitraum": "7d",
  "knoten": [{"id": "claim:1", "typ": "claim", "label": "…", "status": "bestätigt"}],
  "kanten": [{"von": "claim:1", "nach": "quelle:example.org", "art": "belegt_durch", "sicherheit": 0.8}],
  "statistik": {"knoten": 3, "kanten": 2, "typen": {}, "arten": {}},
  "hinweis": ""
}
```

Die API baut den Graphen vor dem Lesen neu auf. Knoten werden aus Claims,
Quellenreputation und Themen beschrieben; fehlende Bezüge werden nicht
erfunden. Die Zahl der zurückgegebenen Kanten ist begrenzt, damit die Antwort
auch bei vielen Quellen beherrschbar bleibt.

---

## 3. Prognosekontrolle

### Manuelle Marktprognosen

`POST /api/nexus/prognose` oder:

```bash
python -m orakel.nexus prognose --symbol EURUSD --erwartung steigt \
  --aussage "EURUSD steigt in den nächsten 24 Stunden" \
  --zeithorizont 24h --konfidenz 0.65
```

Eine manuelle Prognose braucht:

- eine Aussage,
- eine Erwartung (`steigt`, `sinkt`, `unveraendert`),
- ein Symbol mit vorhandenen M15-Kerzen,
- eine Konfidenz zwischen 0 und 1,
- einen Horizont wie `30m`, `24h` oder `7d`.

Der Basiswert ist der letzte gespeicherte M15-Schlusskurs. Die Prognose wird
erst fällig, wenn der Horizont abgelaufen ist. Geprüft wird gegen die erste
echte Kerze **nach** Fälligkeit. Fehlt diese Kerze, bleibt die Prognose offen;
es wird kein Kurs geschätzt. Bei `unveraendert` entscheidet die konfigurierte
Toleranz in Prozent.

### Intel-Aufträge

Abgeschlossene Aufträge der Arten `markt` und `strategie` werden als Prognosen
importiert:

| Auftrag | Erwartung | Ergebnis |
|---|---|---|
| `bestätigt` | `bewegung` / `bestaetigt` | eingetreten |
| `widerlegt` | `bewegung` / `bestaetigt` | nicht eingetreten |
| `verworfen` | – | unprüfbar, zählt nicht als Fehlprognose |
| offen | – | offen |

Im Intel-Auftrag ist keine Modellwahrscheinlichkeit gespeichert. Deshalb wird
bewusst **0,5 als neutrale Konfidenz** verwendet. Das ist keine erfundene
Wahrscheinlichkeit, sondern eine dokumentierte Referenz; der Brier-Score ist
für diese Fälle nur eingeschränkt aussagekräftig.

### Kennzahlen

- **Trefferquote** = eingetretene / geprüfte Prognosen.
- **Brier-Score** = Mittelwert aus `(Konfidenz − eingetreten)^2`.
  Niedriger ist besser; 0 = immer sicher richtig, 1 = immer sicher falsch.
- Zusätzlich werden die Treffer nach Erwartung und nach Konfidenzklassen
  aufgeschlüsselt.
- Ohne geprüfte Prognose bleiben Trefferquote und Brier `null`; es wird keine
  Zahl aus einer leeren Stichprobe gebildet.

---

## 4. Schnittstellen

### HTTP

| Route | Zweck |
|---|---|
| `GET /api/nexus/graph?zeitraum=…` | Graph neu aufbauen und Knoten/Kanten liefern |
| `GET /api/nexus/kalibrierung` | Intel-Prognosen synchronisieren, fällige prüfen, Statistik liefern |
| `POST /api/nexus/prognose` | manuelle, marktgebundene Prognose anlegen |

`GET /api/nexus/status` enthält zusätzlich `graph` (Statistik) und
`kalibrierung` (Kennzahlen und die letzten fünf Prognosen).

### CLI

```bash
python -m orakel.nexus graph --zeitraum 7d
python -m orakel.nexus kalibrierung
python -m orakel.nexus prognose --symbol EURUSD --erwartung steigt \
  --aussage "EURUSD steigt in den nächsten 24 Stunden" --konfidenz 0.65
```

### Oberfläche

Im Spider-Tab gibt es zwei neue Panels:

- **Wissensgraph** mit Zeitraumwahl, Knotenliste, Kantentabelle und ehrlichem
  Leerzustand.
- **Prognosekontrolle** mit Kennzahlen, Konfidenzklassen, Prognoseliste und
  einem Formular für eine prüfbare manuelle Marktprognose.

Die Panels lesen dieselben APIs wie CLI und Status. Sie zeigen keine
Demo-Daten.

---

## 5. Tests und Prüfungen

Die Phase-6-Tests decken ab:

- Graph aus Claims, Quellen und Widersprüchen,
- idempotenten Rebuild,
- Zeitfilter auf echten Kantenzeitstempeln,
- leeren Graphen ohne erfundene Knoten,
- Treffer und Fehltreffer gegen echte M15-Kerzen,
- offene Prognose vor Fälligkeit,
- Intel-Import mit neutraler Konfidenz,
- verworfene Aufträge als unprüfbar,
- Brier/Trefferquote und den ehrlichen Leerzustand.

Zusätzlich geprüft:

```text
pytest -q                         177 passed
python -m compileall -q orakel tests
node --check orakel/web/static/app.js
git diff --check
python -m orakel.nexus --help
```

Die HTTP-Routen werden separat mit einer temporären SQLite-Datenbank geprüft;
die UI wurde in diesem Lauf nicht visuell im Browser geöffnet.

---

## 6. Ehrliche Grenzen

- **Kein Sprachmodell.** Der Graph ist eine strukturierte Ableitung, keine
  semantische Verständnisleistung.
- **Keine automatische Prognoseerfindung.** Manuelle Prognosen müssen
  ausdrücklich angelegt werden; Intel-Prognosen stammen aus echten Aufträgen.
- **Neutrale Intel-Konfidenz.** 0,5 ist eine Referenz, keine echte
  Modellwahrscheinlichkeit.
- **Keine Kurslücken-Füllung.** Ohne Kerze nach Fälligkeit bleibt eine Prognose
  offen.
- **Ein SQLite-Worker.** Mehrere verteilte Worker sind nicht getestet.
- **Keine 3D-Spinne.** Der persistierte Graph ist die Datengrundlage für
  Phase 7; die räumliche Darstellung bleibt dort.
- **Paper-Trading unverändert.** Es werden keine Orders gesendet oder Regeln
  geändert.

---

## 7. Nächster Schritt

Phase 7: 3D-Nexus mit Spinne, ausschließlich an echte Graph- und
Aktivitätsdaten gekoppelt. Vorher muss die UI von Phase 6 visuell geprüft
werden; die Datenschicht steht.
