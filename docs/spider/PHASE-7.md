# Phase 7 — 3D-Nexus mit Spinne

**Stand:** 10. November 2026
**Grundlage:** `orakel/nexus/raum.py`, `orakel/web.py`,
`orakel/web/static/nexus3d.js`, `orakel/web/static/app.js`,
`orakel/web/static/index.html`, `orakel/web/static/style.css`

---

## 1. Was jetzt passiert

Phase 7 ergänzt den persistenten Wissensgraph aus Phase 6 um eine eigene
3D-Ansicht. Die Szene ist **keine Datenquelle**:

```text
SQLite: nexus_claims / nexus_claim_quellen / nexus_widersprueche / Missionen
        └─ /api/nexus/raum ──→ Graph + Ereignisse + Kennzahlen
                                   └─ nexus3d.js: Raum, Graph, Spinne, Screens
```

Der Raum liest ausschließlich `GET /api/nexus/raum?zeitraum=24h|7d|30d|alle`.
Es gibt keine Demo-Knoten, keine erfundenen Missionen und keine künstliche
Bewegung. Die Kamera ist fest; Auswahl und Tooltip verändern nur die Ansicht.

---

## 2. Datenvertrag

`orakel/nexus/raum.py` baut den Graphen mit `graph_auffrischen` / `graph_daten`
und leitet Aktivität aus echten Zeitstempeln ab:

| Quelle | Ereignis | Zeitstempel |
|---|---|---|
| Mission | angelegt, gestartet, abgeschlossen | `erstellt`, `gestartet`, `beendet` |
| Kernaussage | bewertet | `aktualisiert` oder `erstmals` |
| Prognose | angelegt, geprüft | `erstellt`, `result_geprueft_am` |
| Quelle | Bewertung aktualisiert | `aktualisiert` |

Ereignisse haben stabile IDs und werden nach Zeitpunkt sortiert. Fehlt ein
Zeitstempel, entsteht kein Ereignis. Der Zeitfilter entfernt alte Ereignisse aus
der Ansicht, löscht sie aber nicht aus der Datenbank.

`aktivitaet.status` ist:

- `aktiv`, wenn eine Mission `laufend` ist oder mindestens eine Aufgabe
  `laufend` ist,
- `ruhig`, wenn es im Zeitraum echte Ereignisse gibt, aber nichts läuft,
- `leer`, wenn weder Ereignisse noch gespeicherte Aktivität vorliegen.

Die Antwort enthält zusätzlich `zahlen` für Knoten, Kanten, Claims, Quellen,
Missionen, Prognosen und Trefferquote. Alle Werte kommen aus SQLite.

---

## 3. 3D-Szene

`nexus3d.js` verwendet die bereits lokal eingebundene
`vendor/three.module.js` — keine zusätzliche Bibliothek, kein CDN.

- **Raum:** holografische Bodenfläche, Ringe, Speichen, zentrale Plattform.
- **Spinne:** Körper, Kopf, Augen und acht zweigliedrige Beine. Die Beine werden
  aus Hüft-, Knie- und Fußpunkten aufgebaut; im Leerlauf bleiben sie ruhig.
- **Graph:** Knoten werden deterministisch aus ihrer ID positioniert. Claims
  liegen innen, Themen in der Mitte, Quellen außen. Kanten werden als Bögen
  gezeichnet und nach Art eingefärbt.
- **Bewegung:** Beine bewegen sich nur bei `aktivitaet.laufend > 0` oder einer
  laufenden Aufgabe. Ist der Status `ruhig` oder `leer`, stehen die Beine still.
- **Aufleuchten:** Neue Knoten entstehen nur beim Vergleich zweier echter
  API-Antworten. Der erste Aufbau leuchtet nicht künstlich; nach einem Refresh
  blinken ausschließlich neue IDs kurz auf.
- **Screens:** Die beiden Holografien zeigen dieselben Knoten-, Kanten-,
  Ereignis- und Aktivitätszahlen wie die HTML-Leiste.
- **Auswahl:** Knoten lassen sich im 3D-Raum oder in der linken Leiste anklicken;
  Tooltip und Markierungsring zeigen Label, Typ und Status.
- **Leerzustand:** Ohne Graph bleibt die Spinne ruhig; die Ansicht nennt den
  fehlenden Graph und behauptet keine Knoten.

Die Darstellung respektiert `prefers-reduced-motion`: Die Spinne startet dann
pausiert. Der Button `Bewegung pausieren` stoppt bzw. startet die Animation.

---

## 4. Oberfläche und Schnittstelle

Die **Nexus**-Ansicht mit:

- Zeitraumwahl `24 h`, `7 Tage`, `30 Tage`, `Alle`,
- echter Statusanzeige (`AKTIV`, `RUHIG`, `LEER`),
- Knotenliste und Aktivitätsprotokoll,
- 3D-Bühne mit fester Kamera und Tooltip,
- Knotenverteilung und Raumvertrag.

Neue Route:

```text
GET /api/nexus/raum?zeitraum=7d
```

Ungültige Zeiträume liefern `400` mit `{"ok": false, "fehler": "…"}`. Die
bestehenden Routen `/api/nexus/status`, `/api/nexus/graph` und
`/api/nexus/kalibrierung` bleiben unverändert.

---

## 5. Tests und Prüfungen

Neu: `tests/test_nexus_raum.py` mit vier Fällen:

- leerer Raum erfindet keine Knoten oder Ereignisse,
- Graph, Mission, Claims und Quellen erzeugen echte Ereignisse,
- laufende Mission setzt den Raum auf `aktiv`,
- Zeitfenster blendet alte Aktivität aus, ohne gespeicherte Daten zu löschen.

Ergebnis:

```text
pytest -q                         181 passed
python -m compileall -q orakel tests
node --check orakel/web/static/app.js
node --check orakel/web/static/nexus3d.js --input-type=module
git diff --check
```

API-Smoke-Test mit temporärer SQLite-Datenbank:

```text
9 Knoten · 11 Kanten · 3 Claims · 3 Quellen · 2 Missionen
8 Ereignisse · Status aktiv
ungültiger Zeitraum: HTTP 400
```

Visuelle Prüfung im Cloud-Browser bei **432 px**:

- **Aktiv:** 9 Knoten, 11 Kanten, 8 Ereignisse, 1 laufende Mission; Beine und
  Statusanzeige aktiv; Screens zeigen 9/11/8; kein horizontaler Überlauf.
- **Ruhe:** Status `RUHIG`, 0 laufend, Legende „Beine ruhig“; echte letzte
  Aktivität sichtbar.
- **Leer:** 0 Knoten, 0 Kanten, 0 Ereignisse; ehrliche Leermeldung, keine
  Demo-Geometrie.
- **Auswahl:** Klick auf einen echten Claim markiert den Knoten in der Leiste
  und zeigt den Tooltip.
- Keine Anwendungsfehler in der Konsole; nur WebGL-Treiberwarnungen
  (`ReadPixels`-Performance) und zwei 502-Einträge vom ersten Serverstart, der
  nach dem Shell-Ende neu gestartet werden musste.

---

## 6. Ehrliche Grenzen

- **Desktop-Breite nicht visuell geprüft.** Die Cloud-Browser-Sitzung rendert
  bei 432 px; die Playwright-Viewport-Steuerung scheitert weiterhin mit dem
  internen `options.mode`-Fehler. Das responsive CSS ist vorhanden, aber ein
  visueller Desktop-Beleg fehlt.
- **Feste Kamera statt begehbarem Raum.** Das ist die im Plan für Phase 7
  vorgesehene Variante; ein freier Raum folgt nicht in dieser Phase.
- **Keine semantische Graphanalyse.** Die Positionen und Kanten sind
  Darstellungen der gespeicherten Beziehungen, keine neue Interpretation.
- **Keine echten Orders.** Paper-Trading und Risikoregeln bleiben unverändert.
- **Ein SQLite-Worker.** Die Ansicht pollt nur; sie startet keine verteilten
  Worker.
- **Produktionsdaten.** Die visuelle Prüfung nutzte eine temporäre
  Testdatenbank, nicht die Railway-Daten.

---

## 7. Nächster Schritt

Phase 8 ist umgesetzt: Dauerbetrieb, Zeitplan, Backoff, Ressourcenlimits und
Monitoring, dokumentiert in [PHASE-8.md](PHASE-8.md). Ein visueller Desktop-Test
der Phase-7-Ansicht steht weiterhin aus.
