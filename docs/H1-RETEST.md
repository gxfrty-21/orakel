# H1-Retest: Signalplan und Spezifikation

**Status:** Umgesetzt · H1, bestätigter Retest und Re-Entry-Sperre sind im
Backtest und in der H1-Strategie aktiv. Richter, Risikogrenzen und die
bestehende Paper-Sperre bleiben unverändert.

Dieses Dokument beschreibt die kleinste saubere Erweiterung der
Backtest-Signal-API. Im Mittelpunkt steht die Trennung zwischen
Strategieentscheidung und Ausführung: Die Strategie liefert Einstiegs- und
Stop-Informationen, der Backtest führt Position, Stop und Re-Entry-Sperre.

## Ausgangslage

`Strategie.signale` liefert heute eine 0/1-Zielhaltung als `np.ndarray`.
`backtest` eröffnet bei einem positiven Ziel die Folgekerze, setzt den Stop
selbst als ATR-Abstand und schließt bei einem Stop oder einem neutralen Ziel.

Damit kann eine H1-Retest-Strategie weder einen Stop unter dem Retest-Tief
setzen noch nach einem Stop verhindern, dass ein weiterhin positives Ziel
sofort wieder als Einstieg gilt. Würde sie Stop- und Sperrzustand selbst
nachbauen, entstünde eine zweite, leicht abweichende Ausführungslogik.

## Entscheidungen

- **H1:** Der Retest wird ausschließlich auf abgeschlossenen H1-Kerzen
  ausgewertet. Signale entstehen am Schluss der Kerze `i`; die Ausführung
  erfolgt zur Eröffnung von `i + 1`. Es gibt keinen Look-Ahead.
- **Bestätigter Retest:** Ein Retest ist erst bestätigt, wenn nach dem
  Breakout eine H1-Kerze das Level berührt und eine spätere abgeschlossene
  H1-Kerze wieder auf der Breakout-Seite schließt. Der bloße Kontakt mit dem
  Level reicht nicht.
- **Re-Entry-Sperre:** Ein Stop erzeugt keinen neuen Einstieg. Nach einem Stop
  bleibt das Instrument gesperrt, bis das Zielsignal wieder neutral (`<= 0`)
  war; erst ein danach neu gesetztes positives Ziel darf wieder einsteigen.
  Die Sperre ist damit zustands- und setup-basiert, nicht an eine feste Zahl
  von Kerzen gebunden.

## Signalplan

Die neue optionale Hülle wird in `orakel/kern/strategies.py` definiert, weil
`strategies.py` bereits von `backtest.py` importiert wird und kein neuer
Importzyklus entstehen soll:

```python
@dataclass(frozen=True, slots=True)
class Signalplan:
    ziel: np.ndarray
    stop: np.ndarray | None = None
    reentry_sperre: bool = False
```

`Signalplan` ist kein neuer Zustandsspeicher. Die Arrays beschreiben nur, was
die Strategie aus den bis dahin abgeschlossenen Kerzen weiß.

| Feld | Bedeutung |
|---|---|
| `ziel` | Zielhaltung je Kerze: `> 0` long, `<= 0` flat; Länge wie `df` |
| `stop` | Optionaler Stop-Preis je H1-Kerze mit positivem Ziel; Halte-Bars tragen den Stop des laufenden Trades, damit ein Testfenster auch mitten in der Haltedauer beginnen kann. `None` bedeutet ATR-Fallback, ein nicht finiter/nicht positiver Wert wird als ungültig übersprungen |
| `reentry_sperre` | `True`: nach einem Stop erst nach einem neutralen Ziel wieder einsteigen |

### Semantik

- `ziel[i]` wird am Schluss von Kerze `i` ausgewertet; die Ausführung erfolgt
  frühestens zur Eröffnung von `i + 1`.
- `stop[i]` gehört zum Einstieg, der durch `ziel[i] > 0` ausgelöst wird. Der
  Wert muss aus Kerzen `<= i` berechnet sein. Der Backtest verwendet ihn erst
  beim Fill in `i + 1`; dadurch entsteht kein Look-Ahead durch das Tief der
  Fill-Kerze. Nach dem Einstieg tragen die Halte-Bars denselben Stop, sodass
  ein Walk-Forward-Fenster, das mitten in der Haltedauer beginnt, mit dem
  festgeschriebenen Stop startet statt ohne Stop zu warnen.
- Ist `stop[i]` nicht endlich oder nicht positiv, wird der Einstieg
  übersprungen und als Warnung gemeldet; es wird kein Stop erfunden.
- `ziel <= 0` beendet eine offene Position weiterhin zur Folge-Eröffnung.
- Bei `reentry_sperre=True` merkt sich der Backtest nach einem Stop, dass das
  Instrument gesperrt ist. Die Sperre wird aufgehoben, sobald `ziel <= 0`
  beobachtet wurde. Ein weiterhin positives Ziel ist kein Wiedereinstieg.
- Der Stop wird im Backtest ausgeführt, einschließlich Gap-Fill, Slippage und
  Kosten. Die Strategie enthält keine Positions-, Stop- oder Sperrlogik.

### Rückwärtskompatibilität

`backtest` akzeptiert weiterhin ein `np.ndarray`:

```python
Signal = np.ndarray | Signalplan
```

Ein Array wird intern mit `Signalplan.aus_ziel(array)` zu einem Plan mit
`stop=None` und `reentry_sperre=False` normalisiert. Die bestehenden
Strategien und ihre Tests bleiben damit unverändert. Die neue H1-Strategie
liefert dagegen einen `Signalplan` mit eigenem Stop und
`reentry_sperre=True`.

`Strategie.signale` erhält den Rückgabetyp `np.ndarray | Signalplan`.
`backtest` bleibt der einzige Ort, an dem Position, Stop und Re-Entry-Sperre
ausgeführt werden. `Signalplan` bietet zusätzlich `__len__`, `__getitem__` und
`__array__`, damit bestehende Leser wie `paper.py`, `pipeline.py` und
`judge.py` ohne Umbau weiterhin den Zielwert lesen können.

## H1-Retest-Regeln und Strategieparameter

Die Regeln werden über das `[research]`-Raster als Strategieparameter
übergeben. Die Signal-API bleibt unverändert: `Signalplan` enthält weiterhin
nur `ziel`, `stop` und `reentry_sperre`. Die Bestätigung ist eine feste
Strategieregel und kein zusätzliches API-Feld.

| Regel | Rasterschlüssel → Strategieparameter | Konkrete Regel |
|---|---|---|
| **Level** | `h1_retest_lookback` → `lookback` | Positive Ganzzahl `N`. Das Level ist das Hoch der letzten `N` **abgeschlossenen** H1-Kerzen vor der Breakout-Kerze, also `max(high[i-N:i])`. Die Breakout-Kerze zählt nicht mit. Ein Schluss `close[i] > level` startet das Setup; das Level wird dabei festgeschrieben und ändert sich während des Setups nicht mehr. |
| **Retest-Fenster** | `h1_retest_fenster` → `retest_fenster` | Positive Ganzzahl `F`. Das Fenster beginnt mit der ersten Kerze nach dem Breakout (`setup_bar + 1`) und umfasst `F` abgeschlossene H1-Kerzen bis einschliesslich `setup_bar + F`. Die Breakout-Kerze zählt nicht mit. Endet das Fenster ohne Bestätigung, verfällt das Setup. |
| **Bestätigung** | `bestaetigung = close_ueber_level` (feste Regel, kein eigener Rasterschlüssel) | Eine **spätere** abgeschlossene H1-Kerze als die Retest-Kerze muss `close > level` erfüllen. Ein Schluss `close < level` bricht das Setup ab; die Bestätigung muss innerhalb desselben Retest-Fensters liegen. Erst an dieser Kerze setzt die Strategie `ziel[i] = 1`. |
| **Stop-Puffer** | `h1_retest_stop_puffer_pct` → `stop_puffer_pct` | Nicht-negative Dezimalzahl als Anteil, z. B. `0.001` = 0,1 %. Der Stop liegt bei `Retest-Tief × (1 - stop_puffer_pct)`. Das Retest-Tief ist das tiefste `low` aller gültigen Retest-Kerzen. Der Stop wird beim Signal festgeschrieben; der Backtest prüft ihn innerhalb der Kerze und füllt eine Lücke zur Eröffnung. |

Damit sind alle vier Regeln benannt: `lookback`, `retest_fenster`,
`bestaetigung = close_ueber_level` und `stop_puffer_pct`. Nur die drei
Rasterschlüssel mit dem Präfix `h1_retest_` werden aus `[research]` gelesen;
die Bestätigung bleibt fest und benötigt keine API-Erweiterung.

### Entscheidung: Bestätigung bleibt ein fester Strategiewert

`bestaetigung = close_ueber_level` ist bewusst **kein** eigener
`[research]`-Parameter und kein Rasterschlüssel. Ein solcher Parameter ist
nicht erforderlich und wird nicht eingeführt. Die Bestätigung definiert die
Strategie, statt sie zu justieren:

- **Fachlich:** Die Regel, dass eine spätere abgeschlossene H1-Kerze über dem
  festgeschriebenen Level schliesst, ist die Mindestbedingung des bestätigten
  Retests. Ein Raster über diese Regel würde keine Variante derselben
  Strategie erzeugen, sondern andere Strategien – etwa eine Bestätigung per
  blossem Kontakt oder per Schluss unter dem Level. Solche Varianten
  bräuchten eine eigene Regel, eigene Dokumentation und eigene Tests.
- **Methodisch:** Jeder zusätzliche Rasterschlüssel vergrössert den Suchraum
  und das Risiko, den Backtest an die Historie anzupassen. Für eine Variante
  der Bestätigung gibt es weder eine Hypothese noch eine validierte
  Datengrundlage; die ausgelieferten H1-Werte sind ausdrücklich Startwerte.
- **Technisch:** Die Bestätigung wird in `_h1_retest` direkt aus `close` und
  dem festgeschriebenen `level` berechnet. Ein Parameter würde einen neuen
  `h1_retest_*`-Schlüssel, Validierung, Rasteraufnahme und zusätzliche Tests
  verlangen, ohne den Signalplan zu verbessern.

Damit bleiben genau drei `[research]`-Schlüssel massgeblich:
`h1_retest_lookback`, `h1_retest_fenster` und
`h1_retest_stop_puffer_pct`. `bestaetigung = close_ueber_level` ist nur der
Name der festen Regel in der Tabelle. Die `Signalplan`-API bleibt unverändert:
`ziel`, `stop` und `reentry_sperre` sind weiterhin die einzigen Felder; die
Bestätigung erzeugt kein neues Feld und keinen zusätzlichen Zustand.

Sollte später eine andere Bestätigungsart gewünscht sein, wird sie als eigene
Strategie – oder als ausdrücklich spezifizierte Regel mit eigener
Dokumentation und eigenen Tests – eingeführt, nicht als versteckter
`[research]`-Schalter dieser Strategie.

### Ablauf

1. **Breakout:** Ein abgeschlossener H1-Schluss über dem Level startet das
   Setup. Das Level wird aus den `lookback` Kerzen **vor** dieser Kerze
   gebildet und danach nicht mehr verändert.
2. **Retest:** Im Retest-Fenster muss mindestens eine Kerze das Level
   berühren (`low <= level`) und darf nicht darunter schliessen
   (`close >= level`). Die erste Berührung setzt `retest_bar`; weitere
   gültige Berührungen aktualisieren das Retest-Tief.
3. **Bestätigung:** Eine spätere Kerze als `retest_bar` muss innerhalb des
   Fensters mit `close > level` schliessen. Der blosse Kontakt reicht nicht.
4. **Einstieg:** Die Strategie setzt auf der Bestätigungskerze `ziel=1` und
   den Stop-Preis. Der Backtest kauft zur Eröffnung der folgenden H1-Kerze.
5. **Stop:** Der Stop wird aus dem Retest-Tief und dem Stop-Puffer berechnet
   und beim Einstieg festgeschrieben. Der Backtest führt ihn innerhalb der
   Kerze und bei einer Lücke zur Eröffnung aus.
6. **Ausstieg:** Ein H1-Schluss unter dem Level setzt `ziel=0`; der Backtest
   schliesst zur Folge-Eröffnung.
7. **Re-Entry:** Nach einem Stop bleibt `reentry_sperre=True` aktiv, bis das
   Ziel neutral war. Ein neuer Breakout mit Retest und Bestätigung muss den
   Ablauf erneut durchlaufen.

## Umsetzung

- `Signalplan.aus_ziel(array)` normalisiert die bisherigen 0/1-Arrays zu einem
  Plan ohne Stop und ohne Re-Entry-Sperre. `backtest` akzeptiert beide Formen.
- Der Backtest prüft einen expliziten Stop vor dem Einstieg. Ist er nicht
  endlich, nicht positiv oder nicht unter dem Fill-Preis, wird der Einstieg
  übersprungen und eine Warnung erzeugt; ein ATR-Stop wird in diesem Fall
  nicht erfunden.
- Nach einem Stop setzt der Backtest bei `reentry_sperre=True` den Sperrzustand.
  Erst wenn `ziel <= 0` beobachtet wurde, darf ein neues positives Ziel wieder
  einsteigen. Das gilt auch für einen Stop in der Einstiegskerze.
- Die H1-Strategie `h1_retest` ist in `strategien.py` registriert. Sie wird
  nur aktiviert, wenn in `[research]` die H1-Parameter konfiguriert sind
  (`h1_retest_lookback`, `h1_retest_fenster`,
  `h1_retest_stop_puffer_pct`) **und**
  `[basis] richter_zeitrahmen = "H1"` gesetzt ist. Bei M15 bleibt sie aus dem
  Raster und wird nicht mitbewertet. Die ausgelieferte `config.toml` enthält
  ein kleines Raster; bestehende Testkonfigurationen ohne diese Schlüssel
  bleiben unverändert. Der Paper-Takt bleibt unabhängig davon bei M15.
- Die exakten Regeln und die Zuordnung der Rasterschlüssel zu den
  Strategieparametern stehen in der Tabelle unter
  [H1-Retest-Regeln und Strategieparameter](#h1-retest-regeln-und-strategieparameter).
  Die Bestätigung benötigt kein neues `Signalplan`-Feld: Sie wird in der
  Strategie aus `close` und dem festgeschriebenen Level berechnet; `ziel` und
  `stop` bleiben die einzigen Ausgaben.
- `judge.py`, `robustheit.py` und `paper.py` wurden nicht umgebaut. Sie reichen
  den Plan weiter oder lesen über die Array-Schnittstelle nur das Ziel. Der
  Auftragsentwurf der Pipeline nutzt dagegen den Stop des Signalplans, wenn die
  ausgewählte Strategie einen gültigen liefert; sonst bleibt es beim ATR-Stop.
  Der M15-Paper-Takt liest diesen Entwurf nicht, setzt seinen Stop weiterhin
  selbst und bleibt unverändert; die Paper-Sperre bleibt unangetastet.

## Tests

Die Tests liegen in `tests/test_h1_retest.py` und ergänzen die bestehenden
Backtest-Tests:

- Ein Array mit dauerhaft positivem Ziel nach einem Stop erzeugt keinen
  zweiten Einstieg, bis das Ziel neutral war.
- Ein expliziter `stop` wird gegenüber dem ATR-Stop verwendet und respektiert
  Gap und Slippage.
- Ein fehlender oder ungültiger Stop führt zu keinem Einstieg und einer
  Warnung.
- Die 0/1-Ziel-Arrays bestehender Strategien erzeugen dieselben Trades wie
  bisher, solange kein Stop und keine Sperre aktiv sind.
- H1-Retest: Einstieg erst nach bestätigter Kerze, Ausführung erst zur
  Folge-Eröffnung, Stop unter dem Retest-Tief, kein Wiedereinstieg aus dem
  alten Signal.
- Ein Retest ohne Bestätigung erzeugt kein Signal.
- Bei `richter_zeitrahmen = "M15"` wird `h1_retest` nicht registriert und
  erscheint nicht im Kandidatenraster.
- Der Auftragsentwurf der Pipeline übernimmt bei einem Signalplan dessen Stop
  und fällt ohne gültigen Stop auf den ATR-Stop zurück.

## Nicht Teil dieser Änderung

- Keine Änderung am Richter, an den Risikogrenzen oder an der Paper-Sperre.
- Keine Änderung an der Monte-Carlo-Perturbation.
- Keine neue Broker- oder Order-Schnittstelle; das Projekt bleibt Paper-only.
- Kein Umbau des M15-Paper-Takts auf H1 oder auf den H1-Plan-Stop.
