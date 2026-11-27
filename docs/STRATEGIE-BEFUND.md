# Strategie-Befund

**Stand:** 27. November 2026, Basis `aa945d5` plus der Änderungen dieses
Review-Blocks.
**Datenbasis:** `seed/orakel-seed.db`, Zeitrahmen M15, 1. Januar bis 4. Mai
2024, zwei Symbole (EURUSD, US500). Der Seed ist synthetisch erzeugt; dieser
Bericht ist **keine Marktaussage**, sondern die Messung des Prüfablaufs auf
diesen Kerzen.

## Ergebnis

Geprüft wurden **10 Kandidaten** aus **5 Strategien** auf 2 Symbolen mit
**28 Parameterkombinationen**. Bestanden: **0**. Abgelehnt: **10**. Ohne
ausreichende Daten: **0**. Den Holdout-Benchmark „Kaufen und Halten"
geschlagen: **1** (US500 · `ema_cross`), der aber die Mindesttradezahl
verfehlt.

Damit ist **keine Strategie validiert**. Die Paper-Sperre bleibt zu; es wird
weiterhin nicht gehandelt.

## Prüfweg

1. Walk-Forward: Parameter werden in den Trainingsfenstern gewählt, nicht auf
   dem Holdout. Der beste Kandidat je Symbol und Strategie wird genau einmal
   gegen den versiegelten Holdout geprüft.
2. Gates: mindestens 25 Walk-Forward-Trades, mindestens 60 % profitable
   Walk-Forward-Fenster, Profit Factor und Sharpe über der Schwelle, positive
   Nachbar-Parameter, positiver Holdout und ein Holdout-Ergebnis über dem
   Benchmark, sofern der Benchmark positiv ist.
3. Kosten: Kommission und Slippage sind in Backtest und Kennzahlen enthalten;
   Kaufen-und-Halten-Werte enthalten dieselben Kosten nicht und markieren nur
   die Marktrendite.

## Einzelbefunde

| Symbol | Strategie | WF-Trades | WF Netto % | WF PF | Holdout Netto % | Holdout PF | K&H Holdout % | Urteil |
|---|---|---:|---:|---:|---:|---:|---:|---|
| EURUSD | donchian | 5 | 0.35 | 2.31 | −0.87 | 0.33 | −0.47 | abgelehnt |
| EURUSD | ema_cross | 8 | 0.25 | 1.59 | −0.84 | 0.29 | −0.47 | abgelehnt |
| EURUSD | momentum | 0 | – | – | – | – | −0.47 | abgelehnt |
| EURUSD | rsi_reversion | 0 | – | – | – | – | −0.47 | abgelehnt |
| EURUSD | trend_regime | 27 | −0.08 | 0.88 | −0.99 | 0.34 | −0.47 | abgelehnt |
| US500 | donchian | 8 | 1.99 | 6.91 | −0.96 | 0.50 | −0.41 | abgelehnt |
| US500 | ema_cross | 13 | 1.83 | 5.54 | **+0.32** | 1.26 | −0.41 | abgelehnt |
| US500 | momentum | 0 | – | – | – | – | −0.41 | abgelehnt |
| US500 | rsi_reversion | 0 | – | – | – | – | −0.41 | abgelehnt |
| US500 | trend_regime | 16 | −0.07 | 0.80 | −0.58 | 0.80 | −0.41 | abgelehnt |

Die vollständigen Zahlen samt p-Werten, Bonferroni-Korrektur,
Monte-Carlo-Abschlag, Ausstiegsgründen und Marktregimen stehen im erzeugten
Strategie-Bericht (`artifacts/strategie-bericht/strategie-bericht.md`); er wird
aus dem Seed erzeugt und ist nicht versioniert.

### Was die einzelnen Befunde bedeuten

- **EURUSD:** Beide trendfolgenden Kandidaten sind im Walk-Forward knapp
  positiv, brechen im Holdout aber deutlich ein (−0,87 % und −0,84 %). Die
  Stichprobe ist mit 5 und 8 Trades ohnehin zu klein. `momentum` und
  `rsi_reversion` finden im Training keinen Parameter mit mindestens 5
  Trades, der netto positiv bleibt.
- **US500:** `donchian` ist im Training stark (PF 6,91), verliert im Holdout
  aber 0,96 %. `ema_cross` ist der einzige Kandidat, der den Benchmark im
  Holdout schlägt (+0,32 % gegen −0,41 %), scheitert aber an der
  Mindesttradezahl (13 Walk-Forward-Trades, im Holdout 11, gefordert sind 25).
  Ein einzelnes positives Holdout-Fenster mit 11 Trades ist kein
  Vorteilsnachweis.
- **`trend_regime`:** Der vorab festgelegte EMA-50/EMA-200-Filter wurde ohne
  Parametersuche geprüft und in beiden Symbolen abgelehnt. EURUSD verliert im
  Holdout 0,99 % bei 27 Trades, US500 0,58 % bei 16 Trades. Damit ist der
  naheliegende Einwand „zu wenig Trades" für diesen Kandidaten ausgeräumt: Auch
  mit ausreichender Stichprobe entsteht kein Vorteil.

## Was daraus folgt

- Es wird **nicht** nachträglich am Holdout optimiert. Ein Kandidat, der erst
  nach Sicht auf die Holdout-Zahlen angepasst wird, liefert keine Evidenz mehr.
- Der nächste belastbare Schritt ist echte, längere Historie aus MT5 über
  mehrere Marktphasen, nicht ein breiteres Parameterraster auf denselben
  Kerzen. Die Datenanbindung und der gesperrte Orderpfad sind in
  [MT5-ORDERPFAD.md](MT5-ORDERPFAD.md) beschrieben.
- Ein Strategiewechsel (neue Idee, neue Datenbasis) ist ein neuer Kandidat mit
  eigenem Holdout. Die bestehenden zehn Zeilen bleiben als Negativbefund
  erhalten.

## Reproduktion

```bash
python -m orakel strategie-bericht --db seed/orakel-seed.db \
  --quelle "seed/orakel-seed.db (Simulation, keine Marktaussage)" \
  --ausgabe artifacts/strategie-bericht
```

Der Befehl schreibt `strategie-bericht.json` und `strategie-bericht.md`. Die
Zahlen oben stammen aus diesem Lauf; der Bericht nennt zusätzlich den Commit,
die Testzahl je Kandidat und die einzelnen Ablehnungsgründe.
