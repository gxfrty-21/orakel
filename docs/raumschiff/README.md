# Orakel Raumschiff — Planung und 2D-Umsetzung

**Status:** Phase 1 umgesetzt (Company-Schicht); aktuelle Raumschiff-Ansicht ist der 2D-Querschnitt `#v-ship`<br>
**Stand:** 12. November 2026
**Grundlage:** bestehendes Orakel-Projekt in diesem Repository  
**Entscheidung des Owners:** Phase 1 freigegeben; 2D ist die aktuelle Darstellung

Dieses Dossier beantwortet den ersten Auftrag des Masterprompts: zuerst das bestehende
Projekt untersuchen, einen vollständigen Grundriss, eine technische Architektur, die
Agentenstruktur, das Management, die Sekretäre, die Kommunikation, die
Mitternachtskonferenz, den Ressourcenplan und einen realistischen Entwicklungsplan
vorlegen. Phase 1 ist inzwischen als additive Company-Schicht umgesetzt: 103 Profile,
SQLite-Queue, Policy-Engine, Audit-Kette und CLI. Ein begehbarer 3D-Prototyp des
Main Command Centers existierte kurzzeitig und wurde am 12. November 2026 wieder
entfernt. Die aktuelle Umsetzung ist der 2D-Querschnitt mit drei Decks, acht
Abteilungen, Meetingraum und Sekretariat; die Company-Lese-API für Übersicht,
Agentenstatus und offene Aufgaben ist umgesetzt, die übrige Company-API sowie
Management- und Konferenzlogik bleiben offen.

## Kurzfassung

Das Orakel ist bereits ein funktionierendes Paper-Trading-System mit echter
Fakten-Datenbank, Richter, Risikomanager, Spider Intelligence, Obsidian-Vault,
80 Agenten in acht Abteilungen, einer automatischen Mitternachtskonferenz und einem
Dashboard. Die „Weltkugel“ ist eine 2D-Datenvisualisierung des Intelligence-Graphen.
Die „Raumschiff“-Ansicht ist ein administratives 2D-Deck mit drei Decks und acht
Abteilungen; sie ist die aktuelle Umsetzung. Ein begehbarer 3D-Prototyp wurde am
12. November 2026 entfernt.

Der vorgeschlagene Ausbau ist deshalb **kein Neubau neben dem Projekt**, sondern eine
Erweiterung in drei Schichten:

1. **Unternehmensschicht:** 103 Agenten (100 Fachagenten + 3 Sekretäre), Aufgabenqueue,
   Rollen, Gedächtnis, Kommunikation, Policy-Engine und autonome Entscheidungswege.
2. **Raumschiffschicht (Planung, zurückgestellt):** acht Decks, 49 Räume (inkl. acht
   Serviceräumen), zentrale Liftschächte, begehbare 3D-Navigation und eine
   holografische Übersichtskarte.
3. **Präsentationsschicht:** die aktuelle `#v-ship`-Ansicht ist der 2D-Querschnitt;
   die Weltkugel bleibt die 2D-Datenansicht der Global Intelligence Observatory. Das
   restliche Dashboard bleibt erhalten.

Die wichtigste Empfehlung aus der Planungsphase — **nicht mit der 3D-Welt beginnen** —
ist mit der aktuellen 2D-Umsetzung umgesetzt. Eine 3D-Hülle ohne echte Agentenarbeit
wäre die im Masterprompt verbotene Dekoration. 3D ist derzeit nicht freigegeben.

## Ist-Analyse des bestehenden Projekts

### Was bereits echt funktioniert

| Baustein | Ist-Zustand | Relevanz für das Raumschiff |
|---|---|---|
| Fakten-DB | SQLite mit WAL, Kerzen, Validierungen, Trades, Entscheiden, Ereignissen, Konten, Agentenläufen, Konferenzen | Bleibt die einzige Wahrheit; wird um Aufgaben, Nachrichten und Raumstatus erweitert |
| Paper-Trading | CSV-/Mock-/MT5-Broker mit Paper-Sperre; kein Codepfad zu echten Orders | Bleibt unverändert und unverhandelbar |
| Richter | Training/OOS, Walk-Forward, Monte-Carlo, Nachbarparameter, Zufallstest | Kein Agent darf diese Regeln umgehen |
| Risiko | 1 % je Trade, 10 % Not-Stop, 15 Positionen, Engagement, Korrelation | Bleibt hart; Risk Management erhält Vetorecht |
| Spider | RSS-Quellen, robots.txt, Quellenprüfung, Artikel, Volltext, Weiterleitungen | Liefert die realen Daten für Intelligence und Observatory |
| Agenten | 80 deterministische Rollen in acht Abteilungen, je zehn Agenten, echte Ergebnisse je Lauf | Grundstock für die 100 Fachagenten; noch keine freie Agentenkommunikation |
| Konferenz | 00:00 Europe/Zurich, Nachholen, Protokoll, Massnahmen, Vault | Wird zum echten autonomen Führungsgremium ausgebaut |
| Vault | Obsidian-kompatibel, Frontmatter, Tags, `[[Links]]` | Gemeinsames Langzeitgedächtnis und Konferenzarchiv |
| Dashboard | FastAPI, 12 Ansichten, Live-Polling, 2D-Weltkugel, 2D-Raumschiff | Aktuelle Darstellung; 3D ist zurückgestellt |
| Tests | 197 Testfunktionen in 29 Dateien, unter anderem Risiko, Backtest, Daten, Spider, Globe, Web-Auth | Jede neue Phase muss diese Suite grün halten |
| Deployment | Railway, Docker, SQLite-Volume, Basic-Auth | 2D läuft im Browser; der Server bleibt schlank |

### Was heute noch fehlt

- 3D-Welt und begehbare Decks sind nicht umgesetzt; der Prototyp wurde am
  12. November 2026 entfernt. Die 2D-Ansicht ist bewusst die aktuelle Stufe.
- Die Company-Schicht ist additiv und mit `[unternehmen] aktiv = false` nicht in den
  laufenden Takt eingebunden; die Company-Lese-API ist da, freie
  Agentenkommunikation und die übrigen API-Endpunkte fehlen.
- Keine Agenten-Gedächtnisse pro Person; der Vault ist gemeinsames Gedächtnis.
- Keine Abteilungsleiter-Ratssitzung als Ebene 2; die Konferenz protokolliert
  Validierungszahlen, statt autonom zu führen.
- Keine 100 spezialisierten Fachagenten im Dashboard; dort laufen die 80 bestehenden
  Rollen, die 103 Company-Profile sind additiv.
- Keine unternehmensweite Echtzeitübertragung; das Dashboard pollt.
- Kein LLM und keine echten Broker-Orders. Paper-only ist eine harte Grenze, keine
  offene Aufgabe.
- Echte MT5-Historie und Selbstlernen aus abgeschlossenen Trades stehen aus.

### Wichtige technische Ist-Entscheidungen

- Python 3.12, FastAPI und SQLite; eine Instanz, ein Volume.
- Frontend ohne React-Build: klassisches JavaScript; die aktuelle Darstellung ist 2D.
- Die Weltkugel ist eine 2D-Datenansicht, kein Spiel.
- Die Agenten sind heute deterministische Handler, keine 80 unabhängigen LLMs.
- Der Scheduler ist ein Daemon-Thread im Webprozess; die Konferenz läuft auch ohne
  geöffnetes Dashboard, solange der Server läuft.

### Betriebsbefund außerhalb dieses Auftrags

Der Railway-Health-Endpunkt meldet am 12. November 2026 `artikel: 46`; der frühere
Befund `artikel: 0` ist behoben. Die Produktion läuft auf Commit `fdc819e`. Für eine
Live-Demonstration mit mehr echten Daten müssen Artikel, Kurse und Vault-Notizen
weiter gepflegt werden; dieser Plan erfindet keine Daten.

## Die zehn angeforderten Ergebnisse

| # | Ergebnis | Dokument |
|---|---|---|
| 1 | Vollständiger Grundriss des Raumschiffs | [RAUMBUCH.md](RAUMBUCH.md) |
| 2 | Detaillierte Beschreibung sämtlicher Räume | [RAUMBUCH.md](RAUMBUCH.md) |
| 3 | Technischer Architekturplan | [MASTERPLAN.md](MASTERPLAN.md) |
| 4 | Vollständige Agentenstruktur | [AGENTEN.md](AGENTEN.md) |
| 5 | Autonomes Managementkonzept | [MASTERPLAN.md](MASTERPLAN.md) |
| 6 | Beschreibung der drei Sekretäre | [AGENTEN.md](AGENTEN.md) und [MASTERPLAN.md](MASTERPLAN.md) |
| 7 | Konzept der Agentenkommunikation | [MASTERPLAN.md](MASTERPLAN.md) |
| 8 | Konzept der Mitternachtskonferenz | [MASTERPLAN.md](MASTERPLAN.md) |
| 9 | Hardware- und Ressourcenplan | [MASTERPLAN.md](MASTERPLAN.md) |
| 10 | Realistischer Entwicklungsplan | [MASTERPLAN.md](MASTERPLAN.md) |

## Empfohlene Grundsatzentscheidungen

Diese Entscheidungen stammen aus der Planungsphase. Umgesetzt sind die 2D-Ansicht,
Paper-only, SQLite und die Company-Phase 1; die 3D-Punkte sind zurückgestellt.

1. **Acht Decks, 49 Räume (inkl. acht Serviceräume).** Executive, Command, Research,
   Intelligence, Trading, Engineering, Security und Knowledge. Zentraler
   Liftschacht und Atrium verbinden alle Ebenen. Der Grundriss steht in
   `RAUMBUCH.md`.
2. **Zehn Fachabteilungen mit je zehn Agenten, plus drei Sekretäre.** Insgesamt 103
   Agenten. Die neuen Abteilungen sind Global Intelligence Observatory (I) und
   Security Operations (J). Die bestehenden A–H werden in die neue Struktur überführt.
3. **Kein React-Umbau.** Das Dashboard bleibt ohne Bundler gebaut. Die aktuelle
   2D-Darstellung kommt ohne 3D-Framework aus; Three.js ist für eine spätere
   3D-Stufe optional, aber nicht im Einsatz.
4. **Der Server bleibt autoritativ.** Die Darstellung liest Zustand und schreibt nur
   über klar definierte Interaktionen. Kein Agent und kein Browser darf die Datenbank
   direkt verändern.
5. **SQLite bleibt zunächst die einzige Datenhaltung.** Eine Aufgabenqueue in SQLite
   reicht für 103 Agenten bei diesem Takt. Redis/Postgres werden erst eingeführt,
   wenn Messungen einen echten Engpass zeigen.
6. **Keine LLM-Pflicht.** Die 100 Fachagenten arbeiten standardmäßig deterministisch
   und datengebunden. Ein lokales Open-Source-Modell ist optional für Formulierung,
   Zusammenfassung und CEO-Dialog; es trifft keine Handelsentscheidung und läuft
   nicht auf Railway. Keine kostenpflichtigen APIs.
7. **Die `#v-ship`-Ansicht ist die aktuelle 2D-Umsetzung.** Ein begehbarer
   Command-Center-Prototyp wurde am 12. November 2026 entfernt; 3D ist zurückgestellt
   und braucht eine neue Freigabe.
8. **Die Weltkugel bleibt.** Sie wird zum zentralen Exponat der Global Intelligence
   Observatory und behält ihren Zeitfilter.
9. **Paper-only und Sicherheitsgrenzen sind unantastbar.** Kein Agent darf Broker,
   Risikogrenzen, Auth, Secrets oder Produktionsdeployments eigenmächtig ändern.
10. **Phase 1 ist umgesetzt; Phase 2 läuft als 2D-Ausbau.** Die Unternehmensschicht
    ist zuerst entstanden, damit die sichtbare Welt echte Aufgaben und Ergebnisse
    zeigt. 3D ist nicht Teil dieser Stufe.

## Umsetzungsstand

**Phase 1 — umgesetzt:** additive Migration ohne Änderung bestehender Tabellen,
103 Profile, Task-Queue mit Lease/Retry/Dead-Letter, Policy-Engine, Audit-Hash-Kette,
CLI `python -m orakel unternehmen` und sieben neue Tests. Die Scheduler-Anbindung
ist vorhanden, aber mit `[unternehmen] aktiv = false` standardmäßig aus.

**Phase 2 — 2D-Umsetzung (Stand 12.11.2026):** Im Dashboard gibt es `#v-ship` als
2D-Querschnitt mit drei Decks: Deck A (Brücke) mit A, B, E, C; Deck B (Hauptdeck)
mit D, F, G, H; Deck C (Executive) mit CEO-Büro, Empfang/Sekretariat, privatem
Besprechungsraum, Meetingraum und Beobachtungsdeck. Dazu gehören der Meetingraum mit
Agenda, Protokoll und Live-Aktualisierung sowie das Sekretariat mit Mira, Jonas und
Lea (Agenda sammeln, Chat, Vault-Suche).
Die Anzeigen lesen `/api/report`, `/api/betrieb`, `/api/sekretariat` sowie
`/api/company/overview`, `/api/company/agents` und `/api/company/tasks`; fehlende
Werte werden als `KEINE DATEN` angezeigt. Agentenstatus und offene Aufgaben
aktualisieren sich alle 30 Sekunden, solange die Ansicht geöffnet ist. Die Ansicht
ist eine Darstellung, keine neue Datenquelle und keine Automation.

**Noch nicht umgesetzt:** die übrige Company-API (Detailprofil, Nachrichten,
Räume, Konferenz, SSE), 3D-Welt und begehbare Decks (zurückgestellt),
vollständige Agentenkommunikation und -gedächtnisse, autonomes Management,
Mitternachtskonferenz als Führungsgremium, LLM und echte Broker-Orders (bewusst kein
Codepfad).

Die 2D-Ansicht ist der aktuelle sichtbare Teil von Phase 2. Die Company-Lese-API
für Übersicht, Agentenstatus und offene Aufgaben ist umgesetzt. Als Nächstes folgen
die übrige Company-API und die inhaltliche Vertiefung der Agentenarbeit — weiterhin
ohne echte Orders. Ein 3D-Ausbau ist nicht freigegeben.

## Offene Entscheidungen für die nächsten Phasen

Die Freigabe für Phase 1 wurde erteilt; die 2D-Ansicht ist umgesetzt. Die früheren
3D-Fragen sind damit **zurückgestellt, nicht beantwortet**:

1. Die Aufteilung 8 Decks / 10 Abteilungen / 100 + 3 Agenten bleibt Planung.
2. 3D (First-Person, Three.js, restliche Decks) ist nicht freigegeben.
3. Keine LLM-Pflicht: Die Agenten arbeiten deterministisch und datengebunden.
4. Offen bleiben die übrige Company-API, Agentenkommunikation, Management und
   Konferenz.

Der aktuelle Arbeitsstand liegt in `orakel/company/` und
`orakel/migrations/001_company.sql`; die 2D-Ansicht liegt in
`orakel/web/static/`. Phase 1 ist implementiert, getestet und committet.
