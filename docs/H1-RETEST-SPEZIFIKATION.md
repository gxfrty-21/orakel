# H1-Retest: bestätigte Strategie-Spezifikation

**Status:** Bestätigt · Backtest-Grundlage inkl. optionaler Finanzierung
umgesetzt · Paper-Integration offen.

Diese Kurzfassung ist die verbindliche Entscheidungsgrundlage. Die
Implementierungsdetails und die ausführliche API-Beschreibung stehen in
[H1-RETEST.md](H1-RETEST.md). Dieses Dokument ändert keinen Handelscode.

## Geltungsbereich

- Ausschliesslich **Long**-Positionen auf abgeschlossenen **H1**-Kerzen.
- Paper-only; es gibt keinen Broker- oder Live-Order-Pfad.
- Die Richterlogik, die Risikogrenzen und die bestehende Paper-Sperre bleiben
  unverändert.
- Signale entstehen am Schluss der Kerze `i`; die Ausführung erfolgt zur
  Eröffnung von `i + 1`. Kein Look-Ahead.

## Bestätigte Regeln

### Level und Breakout

- Das Level ist das Hoch der letzten `N` H1-Kerzen **vor** der
  Breakout-Kerze.
- Ein Breakout liegt vor, wenn die Kerze über diesem Level schliesst.
- Das Level wird beim Breakout festgeschrieben und ändert sich während des
  Setups nicht mehr.

### Bestätigter Retest

1. Nach dem Breakout muss der Preis das Level innerhalb des Retest-Fensters
   berühren.
2. Eine Retest-Kerze darf nicht unter dem Level schliessen.
3. Erst eine **spätere** abgeschlossene H1-Kerze, die wieder über dem Level
   schliesst, bestätigt den Einstieg. Der bloße Kontakt mit dem Level reicht
   nicht.
4. Das Einstiegssignal entsteht am Schluss der Bestätigungskerze; der
   Backtest kauft zur Eröffnung der folgenden H1-Kerze.

### Stop und Ausstieg

- Der Stop liegt unter dem tiefsten Retest-Tief, abzüglich des konfigurierten
  Puffers.
- Der Stop wird beim Einstieg festgelegt und innerhalb der Kerze geprüft;
  eine Lücke unter den Stop wird zur Eröffnung gefüllt.
- Ein H1-Schluss unter dem festgeschriebenen Level beendet die Position. Der
  Ausstieg erfolgt zur folgenden Eröffnung.

### Re-Entry-Sperre

- Nach einem Stop bleibt das Instrument gesperrt, solange das Ziel positiv
  ist.
- Die Sperre wird erst aufgehoben, nachdem das Ziel wieder neutral
  (`<= 0`) war.
- Ein weiterhin positives Ziel ist **kein** Wiedereinstieg. Ein neuer
  Breakout mit Retest und Bestätigung muss den Ablauf erneut durchlaufen.

### Kosten

- Transaktionskosten und Slippage werden wie bisher je Seite gebucht:
  Kommission oder halber Spread plus Slippage.
- Finanzierungskosten sind optional über `[kosten]
  finanzierung_bps_pro_tag` (Standard `0.0`, also aus) aktiv. Der Backtest
  bucht sie als eigene Kennzahl `finanzierung` getrennt von `gebuehren`; die
  Kosten mindern das Trade-Netto und die Kapitalkurve.

#### Finanzierungsmodell und seine Grenzen

Das Modell ist eine **vereinfachte Kostenannahme für den Backtest**, keine
Nachbildung eines Broker-Swaps:

- **Buchung am UTC-Tag:** Belastet wird bei jedem UTC-Datumswechsel der
  Kerzen. Ein Broker-Rollover (typisch 21:00/22:00 UTC oder 17:00 New York)
  wird nicht modelliert. Eine Position, die zwischen UTC-Mitternacht und dem
  tatsächlichen Rollover eröffnet oder geschlossen wird, kann dadurch einen
  Tag zu früh oder zu spät belastet werden.
- **Kalendertage statt Triple-Swap:** Jeder Kalendertag zählt, auch Samstag
  und Sonntag. Der übliche dreifache Swap am Mittwoch fehlt. Gegenüber einem
  Broker kann das je nach Haltefenster über- oder untertreiben: Freitag bis
  Montag sind es 3 Tage statt typischerweise 1 Tag am Freitag-Rollover; eine
  Position über den Mittwoch wird mit 1 Tag statt mit 3 belastet. Über eine
  vollständig gehaltene Woche stimmt die Summe dagegen (7 Tage).
- **Einstiegsnotional:** Belastet wird `Stück × Einstiegspreis`, nicht der
  tägliche Marktwert. Kursänderungen während der Haltedauer und ein
  abweichender Rollover-Kurs werden nicht neu bewertet.
- **Kontowährung:** Das Notional wird mit dem Einstiegspreis in die
  Kontowährung umgerechnet, wenn die Kurswährung abweicht — dieselbe Logik
  wie bei den Spread-Kosten. Symbole ohne Währungsprofil gelten als in
  Kontowährung notiert. Für Paare ohne Kurs zur Kontowährung (etwa EURGBP
  bei USD-Konto) bricht der Backtest bei aktiver Finanzierung mit einer
  Meldung ab, statt eine falsche Währung zu buchen.
- **Long-only:** Ein Kredit-/Habenzins für Short-Positionen ist nicht
  modelliert; der Backtest handelt keine Shorts.

## Implementierungsstand

- `Signalplan` in `orakel/kern/strategies.py` transportiert Ziel, optionalen
  Stop und Re-Entry-Sperre; bestehende Array-Strategien bleiben kompatibel.
- `backtest` in `orakel/kern/backtest.py` führt explizite Stops und die
  Re-Entry-Sperre aus.
- Die Strategie `h1_retest` ist über die H1-Parameter im
  `[research]`-Raster registriert, aber nur bei
  `[basis] richter_zeitrahmen = "H1"`. Bei M15 bleibt sie aus dem Raster und
  wird nicht mitbewertet.
- Die Tests liegen in `tests/test_h1_retest.py` und `tests/test_paper.py`;
  die bestehenden Backtest-Tests bleiben unverändert gültig.
- Der Finanzierungskosten-Backtest ist implementiert:
  `finanzierung_bps_pro_tag` wird validiert, am UTC-Kalendertag auf das
  Einstiegsnotional in Kontowährung gebucht und als `finanzierung` in den
  Kennzahlen ausgewiesen. Bei `0.0` bleibt das Ergebnis unverändert.
- Die Finanzierung ist bewusst eine Backtest-Annahme, kein Broker-Swap:
  Rollover-Zeitpunkt, Triple-Swap und tägliche Neubewertung des Notionals
  sind nicht modelliert (siehe [Finanzierungsmodell und seine
  Grenzen](#finanzierungsmodell-und-seine-grenzen)).
- Die ausgelieferten Rasterwerte sind Startwerte, keine validierte
  Optimierung.

## Backtest-Integrationspunkte

1. **Broker-nahe Finanzierung:** Falls die Finanzierung später einem
   konkreten Broker entsprechen soll, braucht es dessen Rollover-Zeitpunkt,
   Triple-Swap-Regel und eine Bewertung des Notionals zum Buchungszeitpunkt.
   Das ist bewusst nicht Teil dieser vereinfachten Annahme.
2. **Kennzahlen:** `finanzierung` steht im Backtest-Ergebnis. Der Bericht
   führt den Tagessatz additiv unter `kosten.finanzierung_bps_pro_tag`; Lab
   und Strategien zeigen die gebuchten Finanzierungskosten getrennt von den
   Gebühren. Das Schema 2 bleibt für bestehende Leser unverändert.
3. **Parameterprüfung:** Das H1-Raster und der Stop-Puffer müssen an echten
   H1-Daten validiert werden; die aktuellen Werte sind nur ein testbarer
   Startpunkt.

## Offene Paper-Integrationspunkte

1. Der Paper-Takt liest weiterhin ausschliesslich **M15**-Kerzen. Die
   H1-Strategie wird dort nicht als H1-Handel ausgeführt. Das Strategienraster
   wird im Paper-Takt ausdrücklich mit `zeitrahmen="M15"` aufgebaut;
   `h1_retest` ist dort auch bei `richter_zeitrahmen="H1"` nicht registriert
   und wird nicht auf M15-Kerzen ausgewertet. Die H1-Strategie bleibt
   zusätzlich an `richter_zeitrahmen="H1"` gebunden; ein explizites H1-Raster
   kann diese Bindung nicht umgehen.
2. `paper.py` liest aus einem `Signalplan` nur das Ziel. Der strategieeigene
   Stop und die Re-Entry-Sperre werden im Paper-Takt nicht verwendet; dort
   gelten weiterhin der ATR-Stop und die bestehende Ein-Takt-Sperre.
3. `pipeline.py` übernimmt für den Auftragsentwurf den Stop des Signalplans,
   wenn die ausgewählte Strategie einen gültigen liefert; Grösse und
   Begründung des Entwurfs folgen damit der validierten Strategie. Der
   Entwurf bleibt ein Probelauf auf dem Richter-Zeitrahmen: Der M15-Paper-Takt
   liest ihn nicht und setzt weiterhin seinen eigenen ATR-Stop. Eine
   H1-Ausführung im Paper-Pfad bleibt offen und braucht eine eigene,
   ausdrücklich freigegebene Integration.
4. Die Paper-Sperre und `order_freigabe = false` bleiben unverändert. Eine
   H1-Paper-Integration darf diese Grenzen nicht abschwächen.

## Nächster Schritt

Die **Finanzierungskosten** sind als vereinfachtes Tageskostenmodell
entschieden, dokumentiert und getestet; Broker-Rollover, Triple-Swap und
tägliche Neubewertung bleiben bewusst offen. Danach kann getrennt über eine
H1-Ausführung im Paper-Takt entschieden werden; bis dahin bleibt der
Paper-Pfad unverändert.
