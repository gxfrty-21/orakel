# Monte-Carlo-Perturbation

Der Monte-Carlo-Perturbationstest ist ein **isolierter Robustheitstest** für
eine bereits festgelegte Strategie und ihre Parameter. Er ist nicht Teil des
Richters: Er ändert weder die Parameterwahl noch das Urteil, die Risikogrenzen
oder die Paper-Sperre.

## Ablauf

Für jeden Lauf werden zwei Dinge leicht verändert:

1. **Preise:** Die Schlusskursreihe erhält pro Kerze einen kleinen Shock auf
   ihre Log-Rendite; daraus wird ein kumulativer Faktor gebildet. Die erste
   Kerze bleibt der Anker. Open, High, Low und Close derselben Kerze verwenden
   denselben Faktor; dadurch bleiben der Preisverlauf zusammenhängend und die
   OHLC-Relationen gültig. Signale werden erst danach aus der vollständigen
   perturbierten Reihe berechnet. Es gibt keinen Look-Ahead.
2. **Parameter:** Numerische Parameter werden unabhängig um höchstens den
   angegebenen relativen Anteil verändert. Ganzzahlen bleiben Ganzzahlen. Die
   Strategie liefert die Paare, deren Reihenfolge erhalten bleiben muss (etwa
   `fast < slow` oder `buy_below < exit_above`); `robustheit.py` enthält dafür
   keine fest verdrahteten Schlüsselnamen.

Standardmäßig laufen **500 Kombinationen** mit einem Log-Return-Schock von
0,05 % pro Kerze und einem Parameter-Jitter von 10 %. Ein fester Seed macht
den Lauf reproduzierbar. Diese Standardwerte bleiben unverändert.

### Laufzeit und Drift

Gemessen mit den Standardwerten (500 Läufe, `preis_sigma=0.0005`,
`parameter_jitter=0.10`, Seed 20261122), synthetischen Kerzen
(`synthetische_kerzen("TEST", kerzen=N, seed=3)`) und der Strategie
`donchian` (`lookback=20`):

| Kerzen | Laufzeit für 500 Läufe | je Lauf | max. terminale Drift | max. Drift im Pfad |
|---:|---:|---:|---:|---:|
| 12.000 | 59,0 s (frühere Messung: ~56 s) | 0,118 s | ±22,5 % | ±22,6 % |
| 24.000 | 117,6 s | 0,235 s | ±35,0 % | ±35,3 % |
| 100.000 | 516,3 s (8:36 min) | 1,033 s | ±79,3 % | ±88,7 % |

Die frühere Angabe von rund 56 Sekunden gilt nur für 12.000 Kerzen. Die
Laufzeit skaliert praktisch linear mit der Kerzenzahl: 24.000 Kerzen brauchen
ziemlich genau doppelt so lange wie 12.000; 100.000 Kerzen sind rund 8,3-mal
so viele Kerzen und brauchen gemessen rund 8,75-mal so lange. Das entspricht
etwa 10 µs pro Kerze und Lauf; die Laufzeit hängt zusätzlich von Strategie und
Rechner ab und ist keine Garantie.

Die kumulative Preis-Perturbation ist ein Random Walk: Die **Log-Rendite**
wächst mit der Wurzel der Kerzenzahl, die Standardabweichung beträgt
`0,0005 × √N` (12.000: 5,5 %, 24.000: 7,7 %, 100.000: 15,8 %). Das Maximum
über 500 Läufe liegt bei etwa dem 3,7- bis 4,0-Fachen dieser Streuung. Weil
die Preisniveau-Drift `exp(Log-Drift) − 1` ist, wächst sie prozentual
schneller als die Wurzel: gemessen ±22,5 % bei 12.000, ±35,0 % bei 24.000 und
±79,3 % bei 100.000 Kerzen (terminal); im Pfad beträgt das Maximum bei
100.000 Kerzen ±88,7 %. Die früheren „±20 %“ sind damit ein empirischer
Maximalwert für 12.000 Kerzen, keine harte Obergrenze. Der Faktor wird nicht
gekappt; einzelne Seeds können darüber liegen.

Bei 100.000 Kerzen ist die Standard-Drift kein kleiner Shock mehr, sondern
eine bewusste Stressannahme. Der Standardwert `preis_sigma=0.0005` bleibt
unverändert; wer eine engere Preisniveau-Prüfung braucht, kann `preis_sigma`
pro Lauf gezielt kleiner setzen. Die Standardwerte werden dadurch nicht
verändert.

## Auswertung

Das Ergebnis enthält den Basis-Backtest und die Verteilung der Läufe:

| Feld | Bedeutung |
|---|---|
| `basis_drawdown_pct` | Drawdown des unveränderten Backtests |
| `basis_profit_factor` | Profit Factor des unveränderten Backtests |
| `drawdown_p50_pct` | Median des maximalen Drawdowns |
| `drawdown_p95_pct` | 95-%-Perzentil des maximalen Drawdowns |
| `drawdown_max_pct` | schlechtester Drawdown aller Läufe |
| `profit_factor_p50` | Median des Profit Factors |
| `profit_factor_p05` | pessimistisches 5-%-Perzentil |
| `profit_factor_ueber_1_anteil` | Anteil der Läufe mit Profit Factor > 1 |

Läufe ohne Trades zählen beim Drawdown mit, gehen aber nicht in die
Profit-Factor-Verteilung ein. `profit_factor_ueber_1_anteil` bezieht sich
deshalb nur auf Läufe mit einem berechenbaren Profit Factor.

Die Werte sind eine **Verteilung, kein neues Urteil**. Ein robuster Kandidat
sollte auch unter Preis- und Parameteränderungen einen vertretbaren
Drawdown behalten und mehrheitlich einen Profit Factor über 1 zeigen. Der Test
wird nur aufgerufen, wenn ein Kandidat bereits feststeht; er ersetzt keine
Walk-Forward- oder Holdout-Prüfung.

## Nutzung

```python
from orakel.config import RisikoGrenzen
from orakel.kern.robustheit import perturbationstest

ergebnis = perturbationstest(
    df,
    strategie,
    parameter,
    cfg,
    RisikoGrenzen.aus_config(cfg),
    laeufe=500,
    seed=20261122,
)
print(ergebnis.als_dict())
```

`df` enthält die Kerzen, `strategie` und `parameter` den festgelegten
Kandidaten. Die Kerzen müssen denselben Zeitrahmen wie die Strategie haben;
`h1_retest` ist ausschliesslich für H1-Kerzen vorgesehen. Die Funktion
verändert keine der übergebenen Strukturen. Für einen schnellen Test lassen
sich `laeufe`, `preis_sigma` und `parameter_jitter` gezielt verkleinern; für
eine belastbare Aussage sollten es mindestens mehrere hundert Läufe sein.

## CLI

Ein gespeicherter Kandidat lässt sich direkt über seine ID aus der Tabelle
`validierungen` prüfen:

```bash
python -m orakel robustheit --kandidat 134
```

Der Aufruf liest Symbol, Strategie und Parameter aus der Validierung und die
Kerzen aus der Datenbank. Er schreibt kein neues Urteil und keine Auswahl
zurück. Standardmäßig laufen 500 Kombinationen; `--laeufe N` ändert die
Laufzahl, `--seed N` den reproduzierbaren Zufallsstart und `--db PFAD` die
Datenbank. Die Ausgabe nennt den Basislauf sowie Drawdown- und
Profit-Factor-Perzentile.
