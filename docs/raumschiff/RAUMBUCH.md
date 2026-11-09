# Raumbuch — Orakel Interstellar Headquarters

**Status:** Planung, keine Umsetzung  
**Maßstab:** 1 Three.js-Einheit = 1 Meter  
**Hülle:** ca. 280 m lang, 140 m breit, 68 m hoch  
**Decks:** 8 (E0–E7), je 8 m Strukturhöhe, 7 m lichte Höhe  
**Zentrum:** offenes Atrium mit sechs Aufzügen und zwei Treppenhäusern

Das Schiff ist kein Kriegsschiff. Es ist ein fliegendes Forschungs-, Handels- und
Verwaltungszentrum. Die Form ist aerodynamisch genug für eine Raumstation, aber
bewusst als Innenarchitektur gedacht: breite Korridore, Glasfronten, hohe Räume und
ein zentraler Lichthof.

## 1. Gesamtform und Erschließung

```
                               BUG / +Z
                         ┌──────────────────┐
                         │ Observation Deck │  E7
                         │ CEO / Executive  │
        ┌────────────────┤   LIFT CORE      ├────────────────┐
        │ Grand Conference│ Command Center   │ Observatory    │  E6
        ├────────────────┤                  ├────────────────┤
        │ Innovation Lab  │ Research / Labs  │ Test Rooms     │  E5
        ├────────────────┤                  ├────────────────┤
        │ Spider          │ News / Processing│ Archives       │  E4
        ├────────────────┤                  ├────────────────┤
        │ Trading Floor   │ Strategy Offices │ Market / Trade │  E3
        ├────────────────┤                  ├────────────────┤
        │ Engineering     │ Software / Server│ Monitoring     │  E2
        ├────────────────┤                  ├────────────────┤
        │ Risk Management │ Security Ops     │ Data Validation│  E1
        ├────────────────┤                  ├────────────────┤
        │ Knowledge Center│ Library          │ Archives / DB  │  E0
        └────────────────┴──────────────────┴────────────────┘
                               HECK / -Z
```

- **Längsachse:** Heck (E0–E7, Maschinen/Archive) → Bug (Executive/Observation).
- **Querachse:** Backbord (links, Quellen/Intelligence) → Steuerbord (rechts,
  Abteilungen/Verwaltung).
- **Zentraler Kern:** sechs Aufzüge in zwei Banks à drei Kabinen, zwei offene
  Treppenhäuser, ein durchgehendes Atrium. Jede Ebene hat eine eigene
  „Promenade“ als ringförmiger Korridor.
- **Sicherheitszonen:** Executive und Security sind zutrittsbeschränkt. Die
  Einschränkung ist im 3D-Raum sichtbar (rote Lichtschleusen), aber der CEO kann
  jederzeit alle Bereiche betreten.
- **Fluchtwege:** zwei unabhängige Treppenhäuser, vier Schleusen, kein Raum ohne
  zweiten Weg.
- **Barrierefreiheit:** Aufzüge zu jedem Deck, breite Türen, keine Stufen in
  Hauptkorridoren. First-Person ist eine Ansicht, keine Voraussetzung für alle
  Funktionen; die Karte bietet Direktreisen.

### Wege und Fahrzeiten

| Weg | Dauer (Gehen) | Dauer (Sprint) | Anmerkung |
|---|---:|---:|---|
| Atrium E3 → Trading Floor | 35 s | 18 s | über Promenade und zwei Schleusen |
| Trading E3 → Command E6 | 55 s | 30 s | Aufzug oder Treppe |
| Command E6 → Conference Hall | 25 s | 14 s | direkter Vorraum |
| Executive E7 → Conference E6 | 45 s | 24 s | exklusiver Aufzug |
| Knowledge E0 → Observatory E6 | 70 s | 38 s | Aufzug, dann Promenade |
| CEO Office → Secretariat | 8 s | 4 s | direkte Verbindung |

Die Karte erlaubt zusätzlich „Direkt besuchen“ für alle Räume, damit die Erkundung
nicht zur Pflicht wird. Das ist kein Widerspruch zur begehbaren Welt, sondern eine
Barrierefreiheits- und Bedienhilfe.

## 2. Material- und Lichtkonzept

### Grundmaterialien

- **Hülle:** gebürstetes Titan, dunkles Anthrazit, Sichtcarbon an Kanten.
- **Böden:** dunkler Basalt, eingelassene cyanfarbene Lichtbänder, taktile
  Bodenplatten in Korridoren.
- **Wände:** schallabsorbierende dunkle Paneele, Messing-/Titan-Zierlinien,
  Glasfronten mit entspiegeltem Blau.
- **Decken:** offene technische Spine mit Leitungen, indirekte Lichtkanäle,
  schwebende Hologrammprojektoren.
- **Türen:** automatische Doppelschiebetüren, Statuslicht (grün = offen,
  amber = Schleuse, rot = gesperrt).
- **Fenster:** raumhohe, mehrschichtige Panoramafenster mit leichter Blautönung;
  außen Sternenfeld, vorbeiziehende Nebel und gelegentliche Schiffsverkehr-Lichter.

### Farbwelten pro Deck

| Deck | Grundton | Akzent | Wirkung |
|---|---|---|---|
| E7 Executive | Schwarz, warmes Anthrazit | Champagner, warmes Weiss | ruhig, exklusiv, repräsentativ |
| E6 Command | Dunkelstahl, Nachtblau | Cyan, Eisblau | wach, präzise, global |
| E5 Research | Graphit, Weiss | Violett, Eisblau | neugierig, laborhaft |
| E4 Intelligence | Tiefschwarz, Dunkelgrün | Cyan, Signalgrün | verborgen, analytisch |
| E3 Trading | Anthrazit, Schwarz | Grün, Amber, Rot | schnell, kontrastreich |
| E2 Engineering | Stahlgrau, Schwarz | Orange, Weiss | funktional, robust |
| E1 Security | Schwarz, Dunkelblau | Rot, Eisblau | kontrolliert, warnend |
| E0 Knowledge | Dunkelblau, Schwarz | Gold, warmes Weiss | bewahrend, ruhig |

Jede Abteilung hat ein eigenes Signet an der Eingangsschleuse, auf dem Boden und
auf den Robotern. Die Wegweisung ist dreisprachig: Deutsch, Englisch und eine
grafische Symbolsprache.

## 3. Decks und Räume

Die folgenden Tabellen beschreiben **alle** Räume. Die Flächen sind Planungswerte,
keine fertigen CAD-Maße. Jeder Raum besitzt mindestens eine echte Datenquelle
(Bildschirm, Terminal oder Hologramm) und eine sichtbare Funktion.

### E7 — Executive Deck

**Gesamtfläche:** ca. 1.450 m², kleinere, exklusive Ebene im Bug.  
**Zugang:** exklusiver Aufzug vom Atrium, Sicherheitsschleuse, Treppe nur für
Executive/Notfall.  
**Besonderheit:** durchgehende Glasfront zum Bug; das Deck schwebt optisch über
der Command-Ebene.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E7-01 | CEO Private Office | 220 m² | 1–6 | Arbeitsplatz, Lagebild, Entscheidungen | 6 m hohe Decke, raumhohes Panoramafenster, schwarzer Metallschreibtisch, Wandschrift „GIANLUCA — CHIEF EXECUTIVE OFFICER“ |
| E7-02 | Executive Reception | 110 m² | 1–12 | Empfang, Gäste, Zugangskontrolle | Tresen aus Titan und Glas, drei Infodisplays, Sitzinseln, Sicherheitslicht |
| E7-03 | Secretary Office | 150 m² | 3–9 | Arbeitsplatz der drei Sekretäre | drei halbrunde Arbeitsplätze, je drei Monitore, zentrales Hologramm, ruhige Glaswände |
| E7-04 | Private Meeting Room | 120 m² | 2–12 | vertrauliche Gespräche | ovaler Tisch, holografischer Projektor, schallisolierte Wände, dimmbares Licht |
| E7-05 | Executive Lounge | 100 m² | 1–8 | Rückzug, kleine Gespräche | tiefe Sofas, kleine Bar ohne Alkoholausgabe, warme Lichtnischen, Sternenfenster |
| E7-06 | Panoramic Observation Deck | 180 m² | 1–20 | Aussicht, CEO-Ansprachen, Ruhe | 270°-Glasfront, schwebende Sitzbänke, leiser Luftzug, Sternenprojektion |
| E7-07 | Executive Service | 35 m² | 1–2 | Technik, Getränke, Reinigung, Notstrom | versteckte Servicezelle, keine sichtbare Hauptfunktion |

**CEO Office im Detail:** Der Raum ist bewusst kein operativer Kontrollraum.
Der Schreibtisch steht seitlich zum Fenster, nicht als Kommandopult. Ein großes
Hologramm zeigt ausschließlich aggregierte Unternehmensdaten: Agentenstatus,
aktuelle Projekte, Paper-Ergebnis, letzte Konferenz und offene Entscheidungen.
Ein zweites, kleineres Display zeigt die drei Sekretäre und den aktuellen Tagesbrief.
Die Sitzinsel ist für Gespräche mit Abteilungsleitern gedacht. An der Wand hängt
neben dem Namen eine gerahmte Karte des Schiffs, keine Waffen, keine Trophäen.

### E6 — Command Deck

**Gesamtfläche:** ca. 2.700 m².  
**Zugang:** zentrale Aufzüge, Haupttreppe, Conference-Vorraum.  
**Funktion:** Gesamtüberwachung, Führung, globale Lage, Konferenz.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E6-01 | Main Command Center | 420 m² | 10–18 | Gesamtüberwachung, Koordination, Priorisierung | kreisförmig, zentrales 8-m-Hologramm, zehn Stationen im Halbkreis, gebogene Wandbildschirme |
| E6-02 | Central Operations | 260 m² | 8–16 | Tagesbetrieb, Aufgabenfluss, Eskalationen | erhöhte Galerie, Taktikpulte, Statusband über alle Abteilungen |
| E6-03 | Global Intelligence Observatory | 360 m² | 10–20 | globale Markt- und Informationslage | 8-m-Weltkugel, zehn Analystenstationen im Kreis, dunkler Sternenhimmel, Glasboden über Datenring |
| E6-04 | Grand Conference Hall | 700 m² | 100–140 | Mitternachtskonferenz, Führungsrat, Ansprachen | 26-m-Kuppel, halbkreisförmige Ränge, ovaler 24-Platz-Tisch, 7-m-Hologramm, Panoramafenster |
| E6-05 | Conference Foyer | 180 m² | 20–100 | Einlass, Pausen, informelle Gespräche | Empfangsband, Abteilungsbanner, Getränkeinseln, Live-Protokollwände |
| E6-06 | Command Briefing Room | 110 m² | 6–16 | kurzfristige Lagebesprechungen | Wandkarte, sechs Sitze, gesicherte Leitung, keine Dauerausstellung |
| E6-07 | Command Service Core | 60 m² | 2–4 | Technik, Kühlung, Projektoren | wartbarer Technikring, Notfallpanel, keine Agentenstation |

**Main Command Center:** Zehn ringförmige Stationen für die zehn
Abteilungsleiter; in der Mitte ein begehbares Hologramm des Schiffes mit
Echtzeitstatus pro Raum. Die Wände zeigen keine dekorativen Charts, sondern
ausschließlich Daten aus `/api/company/state`: aktive Aufgaben, blockierte
Aufgaben, offene Entscheidungen, Risikostatus, Konferenzcountdown. Bei
Datenausfall wird der betroffene Bildschirm grau und mit „KEINE DATEN“
beschriftet, nicht mit erfundenen Werten.

**Grand Conference Hall:** Der Raum ist für 100 Agenten plus Sekretariat und
Gastbereich ausgelegt. Die Ränge sind nach Abteilungen gruppiert, jede Abteilung
hat ein eigenes Farbband. Der zentrale ovale Tisch hat 24 Plätze für die zehn
Abteilungsleiter, die drei Sekretäre, den CEO und Gäste. Über dem Tisch schwebt
ein 7-m-Hologramm, das während der Konferenz zwischen Tagesbilanz,
Strategielandkarte und offenen Konflikten wechselt. Die Rückwand zeigt das
Live-Protokoll mit Sprecher, Aussage, Beleg und Status. Der Raum kann ohne
Konferenz als offener Versammlungsort genutzt werden.

### E5 — Research Deck

**Gesamtfläche:** ca. 2.400 m².  
**Zugang:** Haupttreppe, Aufzug, Schleuse zum Testbereich.  
**Funktion:** Hypothesen, Strategien, Experimente, wissenschaftliche Prüfung.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E5-01 | Innovation Laboratory | 380 m² | 10–16 | Ideen, Strategieentwicklung, Prototypen | zehn Experimentiertische, holografische Testflächen, flexible Roboterarme, Ideenwand |
| E5-02 | Research Department | 320 m² | 10–16 | Statistik, Modelle, Regime, Korrelation | geschwungene Datenwände, zehn Analyseplätze, zentrale Modellkarte |
| E5-03 | Scientific Research Labs | 360 m² | 8–14 | Studien, Methoden, externe Forschung | drei abgetrennte Labore, Reinraum, Quellenarchiv, ruhige Lichtzonen |
| E5-04 | Experimental Testing Rooms | 300 m² | 4–10 | Backtests, Simulationen, kontrollierte Fehler | zwei schallisolierte Kammern, je ein Simulationshologramm, Not-Aus |
| E5-05 | Research Library Nook | 80 m² | 1–6 | kurze Literaturprüfung | Regale, zwei Lesesessel, Quellenterminal |
| E5-06 | Research Service | 50 m² | 1–2 | Kühlung, Proben, Technik | Servicezugang, keine Dekoration |

Die Testräume sind bewusst von der offenen Laborfläche getrennt. Ein fehlgeschlagener
Backtest ist ein Ergebnis, kein Feuerwerk; die Kammern zeigen den Fehler mit
klaren Messwerten und einem „nicht bestanden“-Status. Keine Kammer simuliert
Erfolg, wenn keine Daten vorliegen.

### E4 — Intelligence Deck

**Gesamtfläche:** ca. 2.100 m².  
**Zugang:** Aufzug, Treppe, gesicherte Datenwege.  
**Funktion:** Internetrecherche, Nachrichten, Volltext, Archivierung.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E4-01 | Spider Intelligence | 380 m² | 10–14 | Recherche, Quellen, Weiterleitung | zentrale 6-m-Roboterspinne auf erhöhter Plattform, zehn Stationen, leuchtende Datenfäden |
| E4-02 | News Intelligence | 240 m² | 8–12 | Nachrichtenlage, Themen, Symbole | zehn Nachrichtenwände, Tickerband, Quellenampeln |
| E4-03 | Information Processing | 220 m² | 4–8 | Volltext, Extraktion, Dubletten | Serverracks, Textpipeline, Warteschlangenanzeige |
| E4-04 | Digital Archives | 220 m² | 2–6 | Rohdaten, Snapshots, Quellen | kalte Lichtschränke, robotische Archivarme, verschlüsselte Schränke |
| E4-05 | Intelligence Briefing | 100 m² | 4–10 | Lagebesprechung, Übergabe | kleiner runder Tisch, drei Wände mit Quellenlage |
| E4-06 | Intelligence Service | 45 m² | 1–2 | Kühlung, Netzwerk, Technik | Servicezugang, Netzwerkmonitor |

Die Roboterspinne ist kein Deko-Objekt: Sie ist das sichtbare Modell des
Spider-Routers. Ihre Beine zeigen die Anzahl aktiver Quellenkanäle, ihr Körper
zeigt den Status des letzten Laufs. Bei einem Fehler färbt sich der betroffene
Kanal amber, nicht das ganze Tier. Die zehn Stationen entsprechen den zehn
B-Rollen; jede Station hat einen echten letzten Artikel oder den Status
„keine Daten“.

### E3 — Trading Deck

**Gesamtfläche:** ca. 2.300 m².  
**Zugang:** Hauptaufzug, Treppe, Glasfront zur Promenade.  
**Funktion:** Marktbeobachtung, Signale, Paper-Trading, Auswertung.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E3-01 | Main Trading Floor | 480 m² | 10–20 | Markt, Signale, Paper-Ausführung | Reihen von Handelspulten, je drei Monitore, zentrale Kurs- und Risikowand, Glasfront |
| E3-02 | Strategy Trading Offices | 220 m² | 6–10 | Strategieauswahl, Parameter, Freigaben | sechs abgetrennte Büros, Strategie-Hologramme, keine echten Orderknöpfe |
| E3-03 | Market Monitoring | 200 m² | 4–8 | Kurse, Regime, Volatilität, Korrelation | gebogene Kurslandschaft, Farbbänder, Stress-Radar |
| E3-04 | Trade Analysis Rooms | 200 m² | 4–8 | Auswertung, Journal, Fehleranalyse | zwei Analysezimmer, Trade-Replay, klare Verlust-/Gewinnfarben |
| E3-05 | Trader Lounge | 90 m² | 2–8 | kurze Pausen, Übergaben | ruhige Sitznischen, Fenster, Getränke, keine Ablenkungsbildschirme |
| E3-06 | Trading Service | 55 m² | 1–2 | Technik, Kühlung, Not-Aus | Servicezugang, Paper-Only-Siegel am Eingang |

Auf dem Trading Floor gibt es **keinen** Knopf für echte Orders. Der sichtbare
Status jedes Platzes ist „Paper“, „Probelauf“, „wartend“ oder „keine Daten“.
Die zentrale Wand zeigt das Risikobudget und den Paper-Kontostand, nicht
animierte Gewinne. Die Strategie-Büros sind Glaskabinen, damit Gespräche
sichtbar, aber nicht laut sind.

### E2 — Engineering Deck

**Gesamtfläche:** ca. 2.000 m².  
**Zugang:** Aufzug, Lastenaufzug, Treppe.  
**Funktion:** Code, Tests, Server, Monitoring, Reparatur.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E2-01 | Engineering Department | 360 m² | 10–16 | Code, Systeme, Reparatur | zehn Werkbänke, Robotikteile, große Codewand, Testrig |
| E2-02 | Software Development | 260 m² | 8–14 | Entwicklung, Reviews, Tests | acht Doppelstationen, CI-Wand, ruhige Fokuszonen |
| E2-03 | Server Infrastructure | 240 m² | 2–6 | Datenbank, Queue, Backups | Serverracks in Reihen, Flüssigkeitskühlung, Zugangsschleuse |
| E2-04 | System Monitoring | 180 m² | 4–8 | Health, Latenz, Fehler, Kapazität | Wand aus Health-Kacheln, Alarmband, Incident-Pult |
| E2-05 | Engineering Workshop | 160 m² | 4–8 | Robotik, Hardware, Ersatzteile | 3D-Drucker, Werkzeugwände, halbfertige Roboterschalen |
| E2-06 | Engineering Service | 65 m² | 1–3 | Energie, Kühlung, Technik | Servicezugang, Notstrom, keine Agentenstation |

Die Serverräume sind für Agenten nur über eine Schleuse zugänglich. Jeder
Serverblock zeigt seinen echten Health-Status. Die Codewand zeigt kein
dekoratives „Hacker“-Grün, sondern offene Tasks, Teststatus und die letzte
Änderung. Ein roter Test blockiert die Freigabe; er wird nicht wegretuschiert.

### E1 — Security Deck

**Gesamtfläche:** ca. 1.500 m².  
**Zugang:** Security-Schleuse, Aufzug nur mit Freigabe, Notfalltreppe.  
**Funktion:** Risiko, IT-Sicherheit, Datenvalidierung, Incident Response.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E1-01 | Risk Management | 300 m² | 10–14 | Drawdown, Positionen, Korrelation, Stopps | Wand aus Risikokacheln, zentrale Ampel, zehn Stationen, Paper-only-Siegel |
| E1-02 | Security Operations | 280 m² | 10–14 | Zugriff, Audit, Prompt-Injection, Incident Response | dunkler Kontrollraum, Zugriffsmatrix, Alarmkonsole, keine Secrets auf Bildschirmen |
| E1-03 | Data Validation | 220 m² | 6–10 | Kerzen, Lücken, Doppelungen, Integrität | Prüfstraßen, Datenflussdiagramm, Fehlerkörbe |
| E1-04 | Security Briefing | 90 m² | 4–8 | Übergabe, Incident-Review | kleiner Tisch, drei gesicherte Displays |
| E1-05 | Security Service | 45 m² | 1–2 | Technik, Kühlung | Servicezugang, Not-Aus |

Security Operations ist bewusst **nicht** dasselbe wie Risk Management:
Risk Management schützt das Kapital und die Trading-Regeln; Security Operations
schützt System, Daten, Zugriffe und Agentenverhalten. Beide haben ein Vetorecht
in ihrem Bereich. Kein Security-Agent zeigt Secrets, Tokens oder Passwörter;
Audits zeigen nur „vorhanden/nicht vorhanden“ und einen Fingerprint.

### E0 — Knowledge Deck

**Gesamtfläche:** ca. 2.500 m².  
**Zugang:** Hauptaufzug, Lastenaufzug, Treppe.  
**Funktion:** Obsidian-Vault, Bibliothek, Archive, Handelshistorie.

| ID | Raum | Fläche | Personen | Funktion | Signatur |
|---|---|---:|---:|---|---|
| E0-01 | Knowledge Center | 420 m² | 10–18 | Vault, Verknüpfung, Wissenspflege | hohe Regale, zentrale Obsidian-Konsole, schwebende Wissensknoten, warmes Licht |
| E0-02 | Digital Library | 300 m² | 4–10 | Bücher, Studien, Quellen | mehrstöckige Regale, Lesenischen, Quellenterminals |
| E0-03 | Research Archives | 240 m² | 2–6 | alte Studien, Notizen, Verlauf | kompakte Archivschränke, Roboterarme, kühles Licht |
| E0-04 | Historical Trade Database | 220 m² | 4–8 | Trades, Validierungen, Entscheide | Zeitachse an der Wand, Replay-Pult, keine Live-Kurse |
| E0-05 | Knowledge Atrium | 140 m² | 2–12 | Austausch, Lesungen, Übergaben | kleine Bühne, Sitzstufen, Wissenswand |
| E0-06 | Knowledge Service | 60 m² | 1–2 | Technik, Papier, Konservierung | Servicezugang, keine Dekoration |

Das Knowledge Center ist das sichtbare Gegenstück zum Vault. Die zentrale Konsole
zeigt die echte Ordnerstruktur (`00-Index` bis `70-Wissen`), die Anzahl Notizen
und die zuletzt geänderten Dokumente. Ein fehlender Link wird als offener Punkt
angezeigt, nicht als geschlossener Wissensknoten.

## 4. Zentrales Atrium und Verkehr

### Atrium

Ein 24 m breiter, über alle acht Decks offener Lichthof. In der Mitte schwebt
eine 12 m große holografische Übersichtskarte des Schiffs. Die Karte zeigt:

- alle Decks und Räume,
- aktuelle Agentenpositionen (aggregiert, nicht als Überwachung einzelner Personen),
- offene Aufgaben und Konferenzstatus,
- Wege und Aufzüge,
- Warnzustände (Security, Datenausfall, Konferenz).

Die Karte ist bedienbar: Raum antippen, Route anzeigen, „Direkt besuchen“.
Die Karte ist auch als 2D-Overlay verfügbar, damit die Navigation nicht von
WebGL abhängt.

### Aufzüge

- Zwei Banks à drei Kabinen, zentrale Lage.
- Kabine 1–3: reguläre Personen- und Lastaufzüge.
- Kabine 4: Executive/CEO, nur mit CEO- oder S1-Freigabe.
- Kabine 5: Security/Notfall, nur mit J1- oder F1-Freigabe.
- Kabine 6: Service/Lastenaufzug, keine Agenten im Normalbetrieb.
- Jede Kabine zeigt Deck, Ziel, Fahrzeit und Sicherheitsstatus.
- Bei Stromausfall bleiben Treppenhäuser und Notlicht aktiv.

### Korridore

- Ringförmige Promenade pro Deck, mindestens 4 m breit.
- Zwei Hauptschleusen pro Deck, keine Sackgassen.
- Sichtachsen zu Glasfronten und zentralem Atrium.
- Bodenlicht führt zu Abteilungen; Farbe entspricht dem Deck.
- Automatische Türen öffnen bei 2 m Abstand; Sicherheitstüren zeigen rot.
- Keine Werbeplakate, keine beliebigen Requisiten: Jede Wandfläche hat eine
  Funktion (Wegweiser, Status, Kunst oder Struktur).

## 5. Roboterdarstellung

### Grundtypen

| Typ | Einsatz | Höhe | Erkennungsmerkmal |
|---|---|---:|---|
| Analyst | Research, Observatory, Intelligence | 1,75 m | schmaler Körper, großes Visier, Datenring |
| Trader | Trading Floor | 1,80 m | breitere Schultern, drei Bildschirm-Arme, grüner Statusring |
| Engineer | Engineering, Server | 1,85 m | Werkzeugmodul, robuste Gliedmaßen, orange Markierung |
| Security | Security, Risk | 1,90 m | kompakte Panzerung, rotes Visier, Scanner |
| Secretary | Executive | 1,70 m | elegante Silhouette, warmes Licht, keine Waffe |
| Archivist | Knowledge, Archives | 1,72 m | schlank, goldene Datenfäden, holografische Buchsymbole |
| Director | Abteilungsleitung | 1,95 m | zusätzlicher Schulterring, Namensschild, ruhiger Puls |

Die 103 Agenten teilen sich sieben modulare Grundkörper. Individualisierung
erfolgt über Farbe, Schulterband, Namensschild, Visierform und kleine
Accessoires. Das ist keine „100× derselbe Roboter“-Lösung: Jede Abteilung hat
eine eigene Silhouette und jedes Exemplar eine sichtbare ID.

### Animationen

- **Idle:** ruhiges Atmen, gelegentlicher Blick zur Station.
- **Arbeiten:** Tippen, Greifen, Hologramm drehen, Messwert ablesen.
- **Gehen:** modulare Laufanimation auf Wegegraph, kein Schweben.
- **Blockiert:** Stillstand, amberfarbener Ring, Blick zur Tür.
- **Konferenz:** Sitzen/Stehen im zugewiesenen Rang, Sprecherlicht.
- **Warten:** klare „WARTEND“-Anzeige, kein hektisches Scheinbeschäftigen.

Die Animation ist an den echten Aufgabenstatus gekoppelt. Ein Agent, der keine
Aufgabe hat, sitzt nicht hektisch vor einem erfundenen Bildschirm. Ein Agent,
der auf Daten wartet, zeigt „WARTEND“ und den Grund.

## 6. Interaktion und Navigation

### Desktop

| Eingabe | Funktion |
|---|---|
| WASD / Pfeiltasten | Gehen |
| Maus | Umsehen |
| Shift | Sprint |
| E | Interagieren: Tür, Aufzug, Terminal, Agent |
| ESC | Maus freigeben / Menü schließen |
| M | Übersichtskarte |
| F | Fokus auf aktuelles Ziel |
| 1–8 | Deck direkt anwählen, wenn freigeschaltet |
| Klick auf Agent | Agentenprofil und letzte echte Aufgabe |
| Klick auf Bildschirm | Datenpanel öffnen |
| Klick auf Raum | Rauminfo, Belegung, Funktion |

### Mobile und kleine Bildschirme

- Keine First-Person-Pflicht.
- 3D-Übersicht mit Orbit, Zoom und Raumantippen.
- 2D-Deckplan als Fallback.
- Agentenlisten und Raumdetails als Bottom-Sheet.
- Performance-Modus: reduzierte Partikel, weniger Schatten, kein Volumenlicht.

### Onboarding

Beim ersten Betreten erscheint eine kurze, überspringbare Einführung:

1. „Das ist dein Unternehmen. Du kannst zusehen, ohne jeden Schritt zu steuern.“
2. „Die Karte führt dich direkt zu jedem Raum.“
3. „Jeder Agent zeigt seine letzte echte Aufgabe. Graue Karten bedeuten: keine Daten.“
4. „Paper-Trading ist keine echte Broker-Order.“

## 7. Datenbindung und Leerzustände

- Jeder Bildschirm und jedes Hologramm liest aus einer definierten API.
- Keine Hardcodes für Kurse, Agentennamen, Erfolge oder Konferenzaussagen.
- Bei fehlenden Daten: grauer Zustand, Text „KEINE DATEN“, Zeitstempel der
  letzten erfolgreichen Aktualisierung.
- Bei Demo-Daten: deutliches `DEMO`-Wasserzeichen; niemals als Live-Aktivität.
- Bei Verbindungsverlust: letzter bekannter Stand mit „OFFLINE“-Band; keine
  automatische Erfindung.
- Jede Agentenaktivität verweist auf eine Task-ID und einen DB-Eintrag.
- Die 3D-Welt ist Darstellung; die Fakten-DB bleibt die Wahrheit.

## 8. Performance- und Qualitätsbudget

| Ziel | Budget |
|---|---|
| Desktop-Framerate | 60 FPS bei 1920×1080, mindestens 30 FPS auf integrierter GPU |
| Sichtbare Dreiecke | ≤ 150.000 pro Frame |
| Draw Calls | ≤ 120 pro Frame |
| Agenten | 103 über Instancing/LOD, nicht 103 einzelne High-Poly-Szenen |
| Gleichzeitige Räume | aktuelles Deck + angrenzende Deckteile |
| Texturen | max. 2K pro Hauptmaterial, Canvas-Datenpanels 1 Hz |
| Ladezeit erster Raum | ≤ 4 s auf Desktop, ≤ 7 s mobil |
| Speicher | ≤ 350 MB Browser-RAM im Normalbetrieb |
| Mobiler Modus | 2D/3D-Übersicht, ≤ 30 FPS, reduzierte Effekte |

## 9. Visuelle Abnahme

Ein Raum gilt erst als fertig, wenn:

- alle sichtbaren Funktionen mit echten Daten oder klaren Leerzuständen belegt sind,
- die Beschilderung korrekt und lesbar ist,
- Türen, Kollisionen und Wege funktionieren,
- die Beleuchtung die Funktion unterstützt und nicht blendet,
- mindestens ein Agent oder ein klarer „unbesetzt“-Status vorhanden ist,
- die Perspektive aus Augenhöhe und aus der Übersicht funktioniert,
- keine erfundenen Aktivitäten, Kurse oder Erfolge sichtbar sind.

## 10. Was bewusst nicht Teil des Raumbuchs ist

- Keine Waffen, keine Kampfmechanik, keine Zerstörung.
- Keine echten Broker-Terminals, keine echten Orderknöpfe.
- Keine frei erfundenen Agentenbiografien ohne Datenbezug.
- Keine 100 einzigartigen High-Poly-Modelle in Phase 1.
- Keine VR-Pflicht; VR kann später geprüft werden.
- Keine Server-gerenderte 3D-Welt; die GPU des Browsers rendert.
