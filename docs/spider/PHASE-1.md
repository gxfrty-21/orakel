# Phase 1 — Quellenregister, Hacker News, ETag-Cache

**Stand:** 9. November 2026
**Commit:** folgt mit diesem Dokument
**Grundlage:** [NEXUS-PLAN.md](NEXUS-PLAN.md) · [PHASE-0-PLAN.md](PHASE-0-PLAN.md)

---

## 1. Was gebaut wurde

| Modul | Aufgabe |
|---|---|
| `orakel/nexus/quellen.py` | Register laden und fachlich prüfen (IDs, Typen, URLs, Land, Sprache, Gewicht, Intervall) |
| `orakel/nexus/register.toml` | 47 Quellen: 46 RSS/Atom plus Hacker News als `json_api` |
| `orakel/nexus/abruf.py` | bedingte HTTP-Anfragen mit ETag/Last-Modified, Rate-Limit pro Host, Fehlerbudget, Größenlimit, HTML-Abwehr |
| `orakel/nexus/feeds.py` | Parser für RSS 2.0, RSS 1.0 (RDF) und Atom, inklusive relativer Links |
| `orakel/nexus/hackernews.py` | offizielle Firebase-API: `topstories` und `item`, filtert tote Beiträge und Kommentare |
| `orakel/nexus/status.py` | Verteilungen für Register und Cache |
| `orakel/nexus/__main__.py` | `python -m orakel.nexus status` und `… hole` |
| `GET /api/nexus/status` | Status im Dashboard, hinter dem bestehenden Login |

## 2. Register (gemessen, nicht behauptet)

Jede der 47 Quellen wurde vor der Aufnahme **real abgerufen**. Aus 51
Kandidaten wurden 46 Feeds mit gültigem XML und mindestens einem Eintrag:

| Sprache | Quellen |
|---|---|
| en | 32 |
| de | 11 |
| it | 2 |
| es | 1 |
| fr | 1 |

Länder: US 16, DE 9, GB 8, AT 2, CH 2, EU 2, IT 2, CN 1, ES 1, FR 1, HK 1,
JP 1, QA 1. Themen: Nachrichten, Markt, Notenbank, Geldpolitik, Wissenschaft,
Technologie, Energie, Gesundheit, Statistik, Krypto.

**Ausgeschlossen, mit Grund:**

| Quelle | Grund |
|---|---|
| IMF News | HTTP 404 |
| World Bank News | HTTP 404 |
| Les Échos | HTTP 403 |
| arXiv cs.AI | Feed antwortet, enthält aktuell 0 Einträge |
| BIS Press | Feed antwortet, enthält aktuell 0 Einträge |

Spannweite der Einträge: 4 (arXiv Economics) bis 160 (Der Standard). Vier
Quellen liefern RSS 1.0/RDF — sie wurden vorher **leer gelesen**:

| Quelle | Einträge mit RDF-Parser |
|---|---|
| Deutsche Welle | 119 |
| Nature | 75 |
| ORF | 25 |
| Science News | 10 |

## 3. Cache und Höflichkeit

- Erster Abruf: `200`, ETag und Last-Modified werden gespeichert.
- Zweiter Abruf: `If-None-Match` / `If-Modified-Since`, Antwort `304`, **kein
  Body**, kein erneutes Parsen.
- Der Cache speichert nur Metadaten, keine Feed-Inhalte — die DB bleibt klein.
- Ein Abruf pro Host frühestens nach `min_abstand_sekunden`.
- Nach drei Fehlern in Folge wird der Host für fünf Minuten pausiert.
- Antworten über 2 MB und `text/html` werden als Fehler gewertet, nicht als
  Inhalt.
- `robots.txt` wird hier nicht erneut geprüft: Feeds sind zum Abrufen
  veröffentlicht, und der Abruf bleibt durch Rate-Limit und User-Agent
  begrenzt. Der bestehende Spider prüft `robots.txt` weiterhin für
  Volltextseiten.

## 4. Tests

| Prüfung | Ergebnis |
|---|---|
| Neue Nexus-Tests | **23 passed** |
| Gesamte Suite | **97 passed** in 11,28 s |
| Registergröße und -verteilung | ≥ 40 Quellen, 5 Sprachen, 13 Länder |
| Validierung | doppelte ID, unbekannter Typ, ungültige URL, Land/Sprache/Gewicht/Intervall, fehlendes Pflichtfeld |
| ETag | erster Abruf 200, zweiter 304, Cache-Eintrag korrekt |
| Abwehr | HTML, Größenlimit, Fehlerbudget mit Host-Pause |
| Parser | RSS 2.0, RDF, Atom, relativer Link, kaputtes XML, leerer Feed |
| Hacker News | Top-Liste, tote Beiträge, Kommentare, URL-Rückfall |

Zusätzlich real gegen das Netz geprüft:

- `hole --limit 3`: EZB Press 15, EZB Blog 15, Fed Press 20 Meldungen,
  0 Fehler.
- `hole --hn --limit 5`: fünf echte Geschichten mit Punkten und URLs.

## 5. Grenzen (bewusst offen)

- **Keine Speicherung in `artikel`.** Phase 1 ruft ab und cached; das
  Schreiben in die Fakten-DB kommt mit der Dubletten-Erkennung, sonst
  entstehen Doppelzeilen.
- **Kein SimHash, keine Spracherkennung, kein Volltext.** Das ist Phase 2.
- **Der alte Spider bleibt unverändert.** Er hat denselben RDF-Blindfleck,
  liest aber nur die sieben RSS-2.0-Quellen aus `config.toml`. Den Umbau
  trenne ich von Phase 1, damit sich Fehler eindeutig zuordnen lassen.
- **Keine OAuth-Quellen.** Reddit bleibt registrierungspflichtig und ist
  ausdrücklich später geplant.
- **Kein Scheduling.** `hole` läuft auf Aufruf; der 24/7-Takt ist Phase 8.

## 6. Nächster Schritt

Phase 2: SimHash über Shingles, Cluster kopierter Meldungen, Sprach-Heuristik
und Entitäten — danach werden die Meldungen in `artikel` geschrieben und die
Dublettenquote ist messbar.
