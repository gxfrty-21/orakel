# Orakel Raumschiff — Planungsdossier

**Status:** Phase 1 umgesetzt (Company-Schicht); Phase 2 ff. nicht begonnen  
**Stand:** 8. November 2026  
**Grundlage:** bestehendes Orakel-Projekt in diesem Repository  
**Entscheidung des Owners:** Phase 1 freigegeben

Dieses Dossier beantwortet den ersten Auftrag des Masterprompts: zuerst das bestehende
Projekt untersuchen, einen vollständigen Grundriss, eine technische Architektur, die
Agentenstruktur, das Management, die Sekretäre, die Kommunikation, die
Mitternachtskonferenz, den Ressourcenplan und einen realistischen Entwicklungsplan
vorlegen. Phase 1 ist inzwischen als additive Company-Schicht umgesetzt: 103 Profile,
SQLite-Queue, Policy-Engine, Audit-Kette und CLI. 3D-Welt, Company-API, Management-
und Konferenzlogik bleiben offen.

## Kurzfassung

Das Orakel ist bereits ein funktionierendes Paper-Trading-System mit echter
Fakten-Datenbank, Richter, Risikomanager, Spider Intelligence, Obsidian-Vault,
80 Agenten in acht Abteilungen, einer automatischen Mitternachtskonferenz und einem
Dashboard. Die vorhandene „Weltkugel“ ist eine echte Three.js-Datenvisualisierung.
Die vorhandene „Raumschiff“-Ansicht ist dagegen ein administratives 2D-Deck, keine
begehbare 3D-Welt.

Der vorgeschlagene Ausbau ist deshalb **kein Neubau neben dem Projekt**, sondern eine
Erweiterung in drei Schichten:

1. **Unternehmensschicht:** 103 Agenten (100 Fachagenten + 3 Sekretäre), Aufgabenqueue,
   Rollen, Gedächtnis, Kommunikation, Policy-Engine und autonome Entscheidungswege.
2. **Raumschiffschicht:** acht Decks, 49 Räume (inkl. acht Serviceräumen),
   zentrale Liftschächte, begehbare 3D-Navigation und eine holografische
   Übersichtskarte.
3. **Präsentationsschicht:** die bestehende `#v-ship`-Ansicht wird zur 3D-Welt; die
   bestehende Weltkugel wird zum zentralen Hologramm der Global Intelligence
   Observatory. Das restliche Dashboard bleibt erhalten.

Die wichtigste Empfehlung: **nicht mit der 3D-Welt beginnen.** Zuerst muss die
Agenten- und Unternehmensschicht real werden. Eine schöne 3D-Hülle ohne echte,
nachvollziehbare Agentenarbeit würde genau die im Masterprompt verbotene Dekoration
erschaffen.

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
| Dashboard | FastAPI, 11 Ansichten, Live-Polling, 3D-Weltkugel | Wird um Unternehmenssicht und 3D-Raumschiff erweitert |
| Tests | 56 Tests, unter anderem Risiko, Backtest, Daten, Spider, Globe, Web-Auth | Jede neue Phase muss diese Suite grün halten |
| Deployment | Railway, Docker, SQLite-Volume, Basic-Auth | 3D läuft im Browser; der Server bleibt schlank |

### Was heute noch fehlt

- Keine begehbare 3D-Welt und keine First-Person-Navigation.
- Keine CEO-Etage, kein Sekretariat und keine drei Sekretäre.
- Keine zwei zusätzlichen Fachabteilungen für Observatory und Security.
- Keine 100 spezialisierten Fachagenten; derzeit 80.
- Keine echte Agenten-zu-Agenten-Kommunikation, keine Threads, keine Zustellbestätigung.
- Keine allgemeine Aufgabenwarteschlange mit Lease, Retry, Dead-Letter und Abhängigkeiten.
- Keine unabhängigen Agentenläufe außerhalb des Pipeline-/Takt-Kontexts.
- Keine Policy-Engine für autonome Entscheidungen und harte Verbote.
- Keine Abteilungsleiter-Ratssitzung als Ebene 2; die Konferenz ist heute eher ein
  generiertes Protokoll aus Validierungszahlen.
- Keine Agenten-Gedächtnisse pro Person; der Vault ist gemeinsames Gedächtnis.
- Keine 3D-Räume, Robotermodelle, Wege, Türen, Aufzüge oder Interaktionspunkte.
- Keine unternehmensweite Echtzeitübertragung; das Dashboard pollt.
- Keine explizite Trennung zwischen Trading-Risiko und IT-/Sicherheitsrisiko.

### Wichtige technische Ist-Entscheidungen

- Python 3.12, FastAPI und SQLite; eine Instanz, ein Volume.
- Frontend ohne React-Build: klassisches JavaScript und lokal eingebundenes Three.js.
- Der bestehende 3D-Globus ist eine Datenansicht, kein Spiel.
- Die Agenten sind heute deterministische Handler, keine 80 unabhängigen LLMs.
- Der Scheduler ist ein Daemon-Thread im Webprozess; die Konferenz läuft auch ohne
  geöffnetes Dashboard, solange der Server läuft.

### Betriebsbefund außerhalb dieses Auftrags

Der Railway-Health-Endpunkt meldet aktuell `artikel: 0`; das Railway-Volume ist
nahezu leer. Für eine Live-Demonstration mit echten Daten muss zuerst der bestehende
Datenbestand wiederhergestellt werden. Dieser Plan erfindet dafür keine Daten. Die
Planung geht davon aus, dass echte Artikel, Kurse und Vault-Notizen vor der
Abnahme einer Live-Phase vorhanden sind.

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

Diese Entscheidungen sind bewusst als Vorschlag formuliert; sie sind noch nicht
umgesetzt.

1. **Acht Decks, 49 Räume (inkl. acht Serviceräume).** Executive, Command, Research,
   Intelligence, Trading, Engineering, Security und Knowledge. Zentraler
   Liftschacht und Atrium verbinden alle Ebenen. Der Grundriss steht in
   `RAUMBUCH.md`.
2. **Zehn Fachabteilungen mit je zehn Agenten, plus drei Sekretäre.** Insgesamt 103
   Agenten. Die neuen Abteilungen sind Global Intelligence Observatory (I) und
   Security Operations (J). Die bestehenden A–H werden in die neue Struktur überführt.
3. **Vanilla Three.js bleibt.** Kein React-Three-Fiber-Umbau. Das bestehende
   Dashboard ist ohne Bundler gebaut; ein Frameworkwechsel würde das ganze Frontend
   neu schreiben, ohne das eigentliche Problem zu lösen. Blender wird nur für
   optionale GLB-Hero-Assets verwendet, nicht als Voraussetzung.
4. **Der Server bleibt autoritativ.** Die 3D-Welt liest Zustand und schreibt nur über
   klar definierte Interaktionen. Kein Agent und kein Browser darf die Datenbank
   direkt verändern.
5. **SQLite bleibt zunächst die einzige Datenhaltung.** Eine Aufgabenqueue in SQLite
   reicht für 103 Agenten bei diesem Takt. Redis/Postgres werden erst eingeführt,
   wenn Messungen einen echten Engpass zeigen.
6. **Keine LLM-Pflicht.** Die 100 Fachagenten arbeiten standardmäßig deterministisch
   und datengebunden. Ein lokales Open-Source-Modell ist optional für Formulierung,
   Zusammenfassung und CEO-Dialog; es trifft keine Handelsentscheidung und läuft
   nicht auf Railway. Keine kostenpflichtigen APIs.
7. **Die bestehende `#v-ship`-Ansicht wird ersetzt, nicht dupliziert.** Die 2D-Deck-
   Ansicht bleibt als Fallback und für kleine Bildschirme erhalten.
8. **Die Weltkugel bleibt.** Sie wird zum zentralen Exponat der Global Intelligence
   Observatory und behält ihren Zeitfilter.
9. **Paper-only und Sicherheitsgrenzen sind unantastbar.** Kein Agent darf Broker,
   Risikogrenzen, Auth, Secrets oder Produktionsdeployments eigenmächtig ändern.
10. **Phase 1 ist umgesetzt; Phase 2 beginnt mit API und 3D.** Die Unternehmens-
    schicht ist zuerst entstanden, damit die sichtbare Welt später echte Aufgaben
    und Ergebnisse zeigt.

## Umsetzungsstand

**Phase 1 — umgesetzt:** additive Migration ohne Änderung bestehender Tabellen,
103 Profile, Task-Queue mit Lease/Retry/Dead-Letter, Policy-Engine, Audit-Hash-Kette,
CLI `python -m orakel unternehmen` und sieben neue Tests. Die Scheduler-Anbindung
ist vorhanden, aber mit `[unternehmen] aktiv = false` standardmäßig aus.

**Noch nicht umgesetzt:** Company-API (P2), 3D-Welt und Navigation (P2+), CEO-Etage
(P4), vollständige Kommunikation (P5), autonomes Management und Mitternachts-
konferenz (P6), Produktionsdeployment, LLM und echte Broker-Orders.

Der nächste Schritt nach separater Freigabe ist Phase 2: Company-API und eine
3D-Hülle mit einem Deck, Karte und Steuerung — weiterhin ohne echte Orders.

## Offene Entscheidungen für die nächsten Phasen

Die Freigabe für Phase 1 wurde erteilt. Die folgenden Fragen betreffen Phase 2–7:

1. Ist die Aufteilung **8 Decks / 10 Abteilungen / 100 + 3 Agenten** bestätigt?
2. Soll die 3D-Welt auf **Desktop First-Person + Mobile 2D-Fallback** ausgelegt werden?
3. Bleibt **Vanilla Three.js** der verbindliche Weg, oder soll ein React-Umbau
   ausdrücklich geprüft werden?
4. Ist **keine LLM-Pflicht** akzeptabel, mit optionalem lokalem Modell später?
5. Soll die erste Ausbaustufe nur **Command Center und Trading Floor** umfassen,
   bevor alle Abteilungen folgen?
6. Darf nach Phase 1 ein **Railway-Preview-Deployment** der Unternehmensschicht
   erfolgen, ohne dass die 3D-Welt fertig ist?

Die Antworten auf diese Fragen sind die Freigabe für die nächsten Phasen. Der
aktuelle Arbeitsstand liegt in `orakel/company/` und
`orakel/migrations/001_company.sql`; die Planung bleibt die Referenz für die
weitere Umsetzung. Ein Git-Commit wurde für Phase 1 noch nicht erstellt.
