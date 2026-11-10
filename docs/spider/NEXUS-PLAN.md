# SPIDER INTELLIGENCE NEXUS — Bestandsaufnahme und Umsetzungsplan

**Stand:** 10. November 2026
**Grundlage:** `orakel/spider.py`, `orakel/intel.py`, `orakel/knowledge.py`,
`orakel/globe.py`, `orakel/web.py`, `orakel/scheduler.py`, `orakel/company/`,
`migrations/001_company.sql`, `config.toml`, `orakel/web/static/`

Dieses Dokument beantwortet den Auftrag in der vom Auftrag selbst verlangten
Reihenfolge: **zuerst Bestandsaufnahme und realistischer Plan, keine
Großimplementierung.** Es trennt durchgehend zwischen *vorhanden*, *geplant* und
*technisch nicht leistbar*.

---

## 1. Kurzfassung

Der Nexus ist zu etwa einem Drittel gebaut — allerdings der unspektakuläre,
wertvolle Teil: Es gibt einen echten Spider mit robots.txt-Prüfung, Abruflimits,
Dublettenerkennung und Quellenbewertung, ein Intelligence-Netz mit
Weiterleitungen, Forschungsaufträgen und Lernschleife, einen
Obsidian-kompatiblen Vault, einen aus echten Daten abgeleiteten Globus und eine
Company-Schicht mit 103 Profilen, Queue, Policy und Audit-Kette.

Was fehlt, ist vor allem **Breite** (mehr Länder, Sprachen, Quellentypen),
**Textverständnis** (Ähnlichkeit, Sprache, Widersprüche), **Missionen**
(Zerlegung, Queue, Fortschritt), **Gedächtnis als Graph** und die **3D-Spinne im
Nexus-Raum**.

Der entscheidende ehrliche Punkt: Ohne Sprachmodell bleibt die „Intelligenz"
regelbasiert. Sie kann Quellen zählen, gruppieren, widersprüchliche Zahlen
finden und Hypothesen aus Daten ableiten — sie kann aber nicht frei
formulieren, übersetzen oder semantisch verstehen. Ein lokales Modell wäre
möglich, sprengt aber den derzeitigen Hosting-Rahmen (siehe 3.4).

Realistischer Aufwand für den vollen Umfang: **rund 20–25 Arbeitstage** für eine
Person, verteilt auf acht Phasen. Der erste senkrechte Schnitt (Phase 1–2)
liefert nach etwa **4–5 Tagen** sichtbaren Nutzen.

---

## 2. Bestandsaufnahme

### 2.1 Spider-Kern — vorhanden und getestet

`orakel/spider.py` (481 Zeilen) macht bereits mehr als ein üblicher Scraper:

| Fähigkeit | Umsetzung | Beleg |
|---|---|---|
| RSS und Atom | eigener Parser ohne Fremdbibliothek | `_parse`, `_feed_lesen` |
| robots.txt | pro Host geprüft, Verstoß wird protokolliert | `erlaubt`, `_robots_fuer` |
| Höflichkeit | Mindestabstand pro Host, harter Timeout, 2-MB-Limit | `_host_abstand`, `MAX_BYTES` |
| Dubletten | SHA-256 über normalisierten Titel, Unique-Index in SQLite | `Artikel.titel_hash`, `ix_artikel_hash` |
| Quellenbewertung | offene Heuristik: Quellengewicht, Domänenliste, Textlänge, Ziffern, Sensationswörter | `_qualitaet` |
| Marktbezug | 9 Symbole über Stichwortlisten | `SYMBOL_WOERTER` |
| Volltext | HTML-Extraktion ohne Skripte/Navigation, max. 6 Seiten je Lauf | `_text_aus_html`, `_seite_lesen` |
| Vault | jede Erkenntnis als Notiz mit Quelle, Tags, Link | `Vault.notiz` |
| Fehlertoleranz | eine defekte Quelle stoppt nie den Lauf | `lauf()` |

Grenzen im Code, offen dokumentiert: Bewertung ist eine Heuristik, keine
KI-Bewertung; Dubletten erkennen nur *identische* Titel, keine Umformulierungen;
es gibt keine Spracherkennung und keine Übersetzung.

**Quellen heute:** sieben Feeds in `config.toml` — Federal Reserve, EZB, BBC
Business, SEC, arXiv q-fin.TR, Yahoo Finance, Investing.com. Alle englisch oder
deutsch, alle Nachrichten/Wissenschaft, **keine Foren, keine Community-Quellen,
keine asiatischen oder südeuropäischen Quellen.**

### 2.2 Intelligence-Netz — vorhanden und getestet

`orakel/intel.py` (481 Zeilen):

- **Themen-Routing:** sechs Themen (Strategie, Risiko, Wissenschaft,
  Unternehmen, Makro, Markt) → Abteilungen C/D/E/F/G, Stichwortheuristik.
- **Weiterleitungen:** eigene Kennung `WL-JJJJMMTT-NNNN`, Status
  `neu → übernommen → erledigt`, Quellenbezug, Vault-Notiz.
- **Forschungsaufträge:** `RS-JJJJMMTT-NNNN` mit Pflichtfeldern Problem,
  Information, Quellen, Frage, Hypothese, Untersuchung, Nutzen, Risiko.
  Doppelte offene Aufträge werden sieben Tage lang verhindert.
- **Lernschleife:** Aufträge werden gegen echte Daten geschlossen — bei
  Strategieaufträgen gegen die nächste Validierung des Richters, bei
  Marktaufträgen gegen die tatsächliche Bewegung in ATR-Einheiten.
- **Hypothesen aus der Datenlage:** häufigster Ablehnungsgrund der letzten
  Validierungen, Korrelationspaare über der Risikoschwelle.

Das ist der vorhandene Kern von „Hypothesen-Jagd" und „Prognosekontrolle" — aber
ohne Sprachmodell und ohne Kalibrierungsstatistik über viele Aufträge.

### 2.3 Vault — vorhanden

`orakel/knowledge.py`: Obsidian-kompatibel, YAML-Frontmatter, Tags,
`[[Wikilinks]]`, acht Bereiche (`00-Index`, `10-Daten`, `20-Strategien`,
`30-Validierungen`, `40-Entscheide`, `50-Konferenz`, `60-Fehler`, `70-Wissen`).
Gleiche Titel überschreiben sich — bewusst, gegen Duplikate.

Der Vault ist **Textarchiv, kein Graph**: Links stehen als Text in der Notiz,
wer sie auswertet, ist der Globe.

### 2.4 Globe — vorhanden, aus echten Daten

`orakel/globe.py` (641 Zeilen) leitet Knoten und Kanten bei jedem Abruf aus
SQLite und Vault ab: Artikel, Forschungsaufträge, Vault-Notizen, Marktknoten,
Weiterleitungen. Zeiträume 24 h / 7 d / 30 d, sieben Quellenkanäle
(News, Markt, Wissenschaft, Bücher, Video, Makro, Extern), Abteilungen A–H.
Heuristisch abgeleitete Zuordnungen werden als `derived` markiert; es werden
keine Aktivitäten erfunden.

### 2.5 Company-Schicht — vorhanden

`migrations/001_company.sql` + `orakel/company/`: 103 Profile, Aufgabenqueue mit
Lease/Retry/Dead-Letter, Abhängigkeiten, Nachrichten mit Thread und
Zustellbestätigung, Agenten-Gedächtnis, Scores, Policy-Engine, Entscheidungen,
Maßnahmen, Konferenzsitzungen, Raumzustand.

### 2.6 Betrieb

`orakel/scheduler.py`: Daemon-Thread im Webprozess. Paper-Takt, Nachholen der
Mitternachtskonferenz, Spider **einmal** beim Start, Intel-Netz bei jedem Takt,
Company-Schicht optional. `POST /api/spider` startet einen Lauf manuell.

**Für den Nexus relevant:** Der Nachtlauf hat einen systemd-Zeitplan. Seit
Phase 4 gibt es zusätzlich eine persistente Missionen-Queue mit Lease, Retry
und Wiederaufnahme nach einem Neustart. Missionen werden über API/CLI oder den
Web-Takt ausgeführt; sie entstehen nicht automatisch aus erfundenen Fragen.

### 2.7 Tests

Aktuell **167 Tests grün**, darunter `tests/test_spider.py` (Parsing, Dubletten,
robots.txt-Verbot, Qualitätsstrafe, Volltext, Symbolzuordnung),
`tests/test_intel.py` (Themen, Weiterleitungen, Auftragsfelder, Lernschleife),
`tests/test_globe.py` und `tests/test_nexus_missionen.py` (Neustart, Retry,
Dead-Letter, Lease, Priorität).

### 2.8 Was der Auftrag zusätzlich verlangt

| Anforderung | Ist-Zustand | Aufwand |
|---|---|---|
| Foren/Communities (Reddit & Co.) | nur RSS | mittel, API-Zugang nötig |
| Mehrsprachigkeit (FR, IT, ES, ZH …) | keine Spracherkennung | klein für Erkennung, **groß für Übersetzung** |
| Textähnlichkeit, kopierte Meldungen | nur Titel-Hash | klein (SimHash/MinHash) |
| Desinformations-Heuristiken | nur Sensationswörter | klein–mittel |
| Prioritätsstufen KRITISCH/HOCH/MITTEL/NIEDRIG | nur Relevanz 0–1 | klein |
| Missionen mit Zerlegung und Fortschritt | persistent, drei Schritte (Phase 4) | erledigt |
| Gegenargument-Agent | Feld „Risiko" im Auftrag | mittel |
| Wissensgraph | abgeleitet, nicht persistiert | mittel |
| Prognosekontrolle mit Trefferquote | Lernschleife ohne Statistik | klein–mittel |
| 3D-Spinne + Nexus-Raum | 2D-Deck, Three.js-Globus | **groß** |
| 24/7-Recherche | ein Lauf beim Start | klein |

---

## 3. Ehrliche Grenzen

### 3.1 Ohne Sprachmodell bleibt es regelbasiert

Der Auftrag verbietet kostenpflichtige Dienste. Damit ist ein LLM im Betrieb
zunächst ausgeschlossen. Konsequenzen, die ich nicht beschönige:

- **Übersetzung** fremdsprachiger Quellen ist ohne Modell nicht möglich. Möglich
  ist Spracherkennung (Stoppwort-/Zeichenheuristik) und das Speichern des
  Originaltexts mit Sprach-Tag.
- **Freie Zusammenfassungen** entstehen nicht. Möglich ist die Extraktion von
  Sätzen mit Zahlen, Entitäten und Kernaussagen nach festen Regeln.
- **Hypothesen** bleiben aus Daten abgeleitet (wie heute), nicht sprachlich
  formuliert.
- **Agenten** sind deterministische Rollen mit klaren Protokollen — keine 103
  unabhängigen Modelle. Das ist auch mit Modell weder finanzierbar noch
  sinnvoll.

Ein lokales Modell (z. B. via Ollama) wäre technisch möglich, braucht aber
mehrere GB RAM und CPU-Zeit — auf dem aktuellen Hosting nicht vertretbar.

### 3.2 Quellen und Recht

- Reddit verlangt eine OAuth-Anwendung; ohne sie kein Zugriff. Rate-Limits sind
  verbindlich.
- Viele Foren erlauben kein automatisiertes Auslesen. Was robots.txt oder
  Nutzungsbedingungen verbieten, wird nicht abgerufen — auch nicht „nur einmal".
- Paywalls, Logins und technische Sperren werden nicht umgangen.
- Öffentliche, nicht personenbezogene Daten only; keine Profile über private
  Personen.

### 3.3 Echtzeit

RSS und die meisten APIs aktualisieren verzögert. „Frühwarnung" heißt hier
**Minuten bis Stunden**, nicht Sekunden. Echte Echtzeit gibt es nur bei
Quellen, die sie selbst anbieten (z. B. Websocket-Feeds von Börsen) — die sind
kostenpflichtig und damit außerhalb des Rahmens.

### 3.4 Hosting

Der Railway-Trial läuft in wenigen Wochen ab (siehe `RAILWAY.md`). Dauerbetrieb
mit Recherche-Takt braucht eine Entscheidung: Hobby-Tarif (5 $/Monat) oder
Umzug auf eine kostenlose VM. Ohne diese Entscheidung ist „24/7" nur ein Wort.

### 3.5 3D

Die Spinne ist machbar: Three.js ist bereits lokal eingebunden, Beine über
Inverse Kinematics, Animation an echte Ereignisse gekoppelt. Aufwand liegt
eher im Detail (Gangart, Übergänge, Lesbarkeit) als in der Technik. Wichtig:
Die Spinne darf **nichts vortäuschen** — im Leerlauf ruhig, bei echter
Recherche aktiv.

---

## 4. Zielarchitektur

### 4.1 Module

Neues Paket `orakel/nexus/`, additiv, ohne bestehende Pfade zu brechen:

| Modul | Aufgabe |
|---|---|
| `quellen.py` | Quellenregister mit Typ, Land, Sprache, Gewicht, Zugangsart |
| `abruf.py` | HTTP-Client: robots.txt, Rate-Limit, ETag/Last-Modified, Cache, Fehlerbudget |
| `extraktion.py` | Text, Sprache (Heuristik), Entitäten, Zahlen, Zitate |
| `dedup.py` | SimHash über Shingles, Cluster kopierter Meldungen |
| `bewertung.py` | Quellenreputation aus tatsächlichen Ergebnissen, Bestätigungsgrad |
| `missionen.py` | Mission → Teilaufgaben → Queue, Priorität, Retry, Fortschritt |
| `agenten.py` | 15 deterministische Rollen, jede mit eigenem Protokoll |
| `gegenargument.py` | Gegenquellen, Alternativerklärungen, Schwachstellen |
| `graph.py` | persistierte Knoten/Kanten, Zeitverlauf, Vault-Sync |
| `kalibrierung.py` | Trefferquote, Brier-Score, Fehleranalyse |
| `api.py` | FastAPI-Router für Missionen, Status, Graph, Warnungen |

Der bestehende `Spider` bleibt der Abruf-Kern; `nexus/` erweitert ihn, statt ihn
zu ersetzen. `IntelNetz` bleibt das Routing; Missionen nutzen es.

### 4.2 Neue Tabellen

```
nexus_missionen      id, kennung, titel, auftrag, status, priorität, fortschritt,
                     erstellt, gestartet, beendet, bericht
nexus_tasks          id, mission_id, rolle, ziel, status, versuche, lease_bis,
                     ergebnis, fehler, abhängig_von
nexus_quellen        host, name, typ, land, sprache, gewicht, zugang,
                     letzter_abruf, etag, fehlerquote, reputation
nexus_claims         id, text_hash, kernaussage, erstmals_gesehen, quellen_anzahl
nexus_claim_quellen  claim_id, artikel_id, rolle (original | kopie | widerspruch)
nexus_edges          von, nach, art, begruendung, sicherheit, erstellt
nexus_forecasts      id, auftrag_id, aussage, erwartung, zeithorizont, status
nexus_forecast_results  forecast_id, eingetreten, messwert, geprueft_am, notiz
```

Alles in derselben SQLite-Datei, additiv per Migration. Kein zweiter
Datenspeicher.

### 4.3 Ablauf einer Mission

1. **Annahme:** Auftrag per API oder Zeitplan, Mission erhält `MS-…`.
2. **Zerlegung:** Mission → Teilaufgaben (Quellen suchen, lesen, prüfen,
   bestätigen, widersprechen, verknüpfen, berichten).
3. **Ausführung:** Worker nehmen Aufgaben mit Lease; Retry mit Backoff;
   Dead-Letter nach n Versuchen.
4. **Prüfung:** `bewertung` und `gegenargument` prüfen jede Kernaussage.
5. **Bericht:** Mission erhält einen Abschlussbericht mit Quellen, Unsicherheit
   und offenen Fragen — als Vault-Notiz und API-Antwort.
6. **Weitergabe:** `IntelNetz.weiterleiten` an die zuständige Abteilung.
7. **Nachkontrolle:** `kalibrierung` prüft später, ob die Einschätzung stimmte.

### 4.4 API (Ergänzung, keine Änderung bestehender Routen)

```
POST /api/nexus/mission        Mission anlegen
GET  /api/nexus/missionen      Liste mit Fortschritt
GET  /api/nexus/mission/{id}   Detail + Bericht
GET  /api/nexus/status         Kennzahlen (Quellen, Länder, Sprachen, Warnungen)
GET  /api/nexus/graph?zeitraum Knoten/Kanten für die 3D-Ansicht
GET  /api/nexus/warnungen      Priorisierte Hinweise
```

Alle Kennzahlen kommen aus SQLite. Kein Feld ist berechnet, ohne dass die
Quelle mitgeliefert wird.

### 4.5 3D-Kopplung

Neue Datei `orakel/web/static/nexus3d.js`, Ansicht `#v-nexus`:

- Raum mit holografischer Fläche und Globus (bestehende `globe3d.js`-Daten).
- Spinne: Körper + acht Beine, IK, ruhiger Idle-Zustand.
- Animation ausschließlich aus `/api/nexus/status` und `/api/nexus/graph`:
  Beinbewegung nur bei laufenden Aufgaben, Aufleuchten nur bei neuen
  Erkenntnissen, sonst Ruhe.
- Bildschirme im Raum zeigen dieselben Zahlen wie die API — keine Dekoration.

---

## 5. Phasenplan

| Phase | Inhalt | Aufwand | Abnahme |
|---|---|---|---|
| **1** | Quellenregister (40+ Feeds, 6 Sprachen, 12 Länder), ETag-Cache, Fehlerbudget | 2–3 T | 40 Quellen konfiguriert, Cache greift, Tests grün |
| **2** | Spracherkennung (Heuristik), SimHash-Dedup, Cluster kopierter Meldungen | 2 T | Kopien werden gruppiert, Original markiert |
| **3** | Quellenreputation aus Ergebnissen, Bestätigungsgrad, Widerspruchserkennung | 2–3 T | jede Kernaussage hat Bestätigungsstatus |
| **4** | Missionen, Queue, Retry, Fortschritt, API + UI-Liste | 3 T | Mission läuft Ende-zu-Ende, auch nach Neustart |
| **5** | 15 Agentenrollen, Gegenargument-Agent, Berichte | 3–4 T | Bericht je Mission mit Gegenargumenten |
| **6** | Wissensgraph persistiert, Prognosekontrolle mit Trefferquote | 3 T | Graph aus DB, Kalibrierung sichtbar |
| **7** | 3D-Nexus mit Spinne, an echte Events gekoppelt | 4–6 T | Blick in den Raum zeigt echten Zustand |
| **8** | Dauerbetrieb: Zeitplan, Backoff, Ressourcenlimits, Monitoring | 2 T | 24 h Lauf ohne Eingriff, Logs auswertbar |

**Summe: 21–25 Arbeitstage.** Phase 7 ist der größte Einzelposten und bewusst
zuletzt — eine schöne Hülle ohne echte Daten wäre genau die verbotene
Dekoration.

**Stand 10. November 2026:** Phasen 1–4 sind lokal umgesetzt und getestet
(siehe [PHASE-1.md](PHASE-1.md), [PHASE-2.md](PHASE-2.md),
[PHASE-3.md](PHASE-3.md), [PHASE-4.md](PHASE-4.md)). Phase 4 liefert die
persistente Missionen-Queue, aber noch nicht die 15 Agentenrollen oder den
Gegenargument-Agenten. Auf der Oracle-VM läuft noch der alte Stand; die
Migration ist vorbereitet, aber nicht ausgeführt.

---

## 6. Erste Scheibe (empfohlener Start)

Ein senkrechter Schnitt statt vieler Baustellen:

1. `orakel/nexus/quellen.py` + `abruf.py`: Register mit Land/Sprache/Typ,
   ETag/Last-Modified, gemeinsamer Cache, Fehlerbudget pro Host.
2. `orakel/nexus/dedup.py`: SimHash über Shingles, Gruppen in
   `nexus_claims`/`nexus_claim_quellen`.
3. `orakel/nexus/extraktion.py`: Sprach-Heuristik, Entitäten, Zahlen.
4. `config.toml`: Quellen von 7 auf 40 erweitern (Nachrichten, Notenbanken,
   Statistik, Wissenschaft, Technik; DE/EN/FR/IT/ES/ZH).
5. `GET /api/nexus/status`: Quellen, Sprachen, Länder, Dublettenquote.
6. Tests: Cache-Treffer, Rate-Limit, SimHash-Gruppierung, Sprachschätzung.

Ergebnis nach 4–5 Tagen: deutlich breitere Abdeckung, weniger Doppelmeldungen,
belastbare Kennzahlen — und eine Datenbasis, auf der Missionen und 3D
aufsetzen können.

---

## 7. Nicht-Ziele (bewusst)

- Keine echten Broker-Orders. Paper-Trading bleibt unverändert.
- Keine Umgehung von Paywalls, Logins oder robots.txt.
- Keine Bild- oder Dokumentforensik („manipulierte Bilder erkennen") — dafür
  fehlen Modell und Rechtssicherheit.
- Keine Zusage von Echtzeit.
- Keine 103 gleichzeitig laufenden Modelle.
- Keine erfundenen Kennzahlen, keine Demo-Aktivität in der 3D-Ansicht.

---

## 8. Entscheidungen (9. November 2026)

1. **Sprachmodell:** Start **ohne** LLM, regelbasiert, 0 €. Ein lokales Modell
   wird über eine Provider-Schnittstelle vorbereitet, aber nicht eingebaut.
2. **Hosting:** zuerst kostenlos (Oracle Always Free bevorzugt). Railway Hobby
   (5 $/Monat) nur nach gemeinsamer Entscheidung.
3. **Community-Zugang:** RSS + Hacker News. Reddit-OAuth bleibt als spätere
   Erweiterung eingeplant.
4. **3D:** feste Kamera auf Spinne, Recherchefläche und Globus; der begehbare
   Nexus-Raum folgt später.

Details, Kosten und Grenzen: [PHASE-0-PLAN.md](PHASE-0-PLAN.md).

---

## 9. Grundsätze, die für jede Phase gelten

- Jede Aussage behält Quelle, Zeitpunkt und Unsicherheit.
- Heuristiken werden als Heuristiken benannt, nicht als Erkenntnis verkauft.
- Was nicht abrufbar ist, wird als Lücke dokumentiert, nicht erfunden.
- Webseiteninhalte sind Daten, niemals Anweisungen.
- Die Spinne ändert keine Handelsregel und keine Sicherheitsgrenze.
- Jede Phase endet mit Tests und einem dokumentierten Ist-Stand.
