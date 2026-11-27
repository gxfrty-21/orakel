# MT5-Orderpfad: Planung, Prüfung und bewusste Sperre

**Stand:** 27. November 2026
**Status:** Orderplanung implementiert und getestet; **keine echte Orderausführung**.
Das ist keine offene Baustelle, sondern die Paper-Grenze aus
[AGENTS.md](../AGENTS.md).

## Warum es diesen Baustein gibt

Bis zu diesem Stand importierte ORAKEL MT5-Daten, konnte aber keinen
Broker-Auftrag auch nur vorbereiten. Damit fehlte die prüfbare Verbindung
zwischen Risikokern und Plattform: Volumenschritt, Mindestvolumen,
Stop-Level, Füllungsart und Stop-/Take-Profit-Abstand wurden nirgends gegen
echte Symbol-Metadaten validiert.

`orakel/kern/mt5_orders.py` schliesst genau diese Lücke. Der Baustein baut
einen vollständigen `order_send`-Request, sendet ihn aber nie. Der einzige
Gateway (`PaperOrderGateway`) lehnt jeden Sendeversuch mit `PaperOnlyError`
ab. Ein späterer Demobetrieb braucht daher eine ausdrückliche Policy-Änderung
und einen separaten, dann einzeln geprüften Adapter.

## Was implementiert ist

| Baustein | Aufgabe |
|---|---|
| `SymbolSpec` | Broker-Metadaten: Digits, Point, Min-/Max-Volumen, Volumenschritt, Stop-Level, Füllungsart |
| `normalisiere_volumen` | Rundet **nach unten** auf den Volumenschritt; unter Minimum → `0` |
| `plane_kauf` | Prüft Kurs, Stop, Stop-Level, Take-Profit und Risikobudget; baut den MT5-Request |
| `gleiche_positionen` | Abgleich lokaler und Broker-Mengen: fehlend, zusätzlich, abweichend |
| `PaperOrderGateway` | Nimmt einen Plan entgegen und verweigert das Senden |

Der Request enthält die MT5-Felder `action`, `symbol`, `volume`, `type`,
`price`, `sl`, `tp`, `deviation`, `magic`, `comment`, `type_time` und
`type_filling`. Die Zahlenwerte der MT5-Konstanten sind dokumentiert, damit
das Modul ohne installiertes `MetaTrader5` importierbar und in CI testbar
bleibt.

## Risikokette

```text
Signal -> Risikomanager.pruefe (Stop, Risikobudget, Exposure, Korrelation)
       -> positionsgroesse (eine Formel für Backtest und Paper)
       -> normalisiere_volumen (Broker-Schritt, nach unten)
       -> plane_kauf (Stop-Level, Request)
       -> PaperOrderGateway.senden -> PaperOnlyError
```

Kein Schritt kann übersprungen werden: `plane_kauf` verlangt einen Stop unter
dem Ask, einen positiven Kurs und ein Volumen, dessen Risiko das Budget nicht
überschreitet. Der Risikomanager lehnt einen Kauf ohne Stop-Loss ab.

## Broker-Symbole und Datenzuordnung

Broker-Suffixe (`EURUSDm`, `EURUSD.a`, `US500.cash`) werden **nicht geraten**.
Die Zuordnung erfolgt ausschliesslich über `[daten.symbol_map]`:

```toml
[daten.symbol_map]
EURUSDm = "EURUSD"
"US500.cash" = "US500"
```

Der Import (CLI und HTTPS-Transport) wendet die Tabelle vor der Symbolprüfung
an. Ohne Eintrag bleibt der Name unverändert. Eine automatische Suffix-
Erkennung wäre gefährlich, weil sie verschiedene Instrumente vermischen kann.

## Abnahme auf dieser Maschine

Am 27.11.2026 wurde Folgendes tatsächlich ausgeführt:

| Schritt | Ergebnis |
|---|---|
| `MetaTrader5` im venv installieren | erfolgreich, Version 5.0.6231 |
| Terminal starten | `terminal64.exe` lief |
| `mt5.initialize(path=...)` | **fehlgeschlagen**: `(-6, 'Terminal: Authorization failed')` |
| Kerzenabruf EURUSD M15 | nicht möglich, weil die Initialisierung scheitert |
| Orderplanung | mit Tests und konstruierten Symbol-Metadaten geprüft |
| echte Order | **nicht gesendet** (Paper-Sperre und fehlende Anmeldung) |

Die Ursache ist eine fehlende bzw. abgelehnte Terminal-Anmeldung. Zugangsdaten
gehören nicht ins Repository und wurden nicht erfragt oder protokolliert.
Damit ist die reale Daten- und Orderabnahme **nicht** erbracht.

## Nächste Schritte für eine echte Demo-Abnahme

1. MT5-Terminal mit einem Demo-Konto anmelden und das gewünschte Symbol im
   Market Watch sichtbar machen.
2. `scripts/mt5_abruf.py` für einen Monat ausführen und die CSV importieren.
3. Symbol-Metadaten (`symbol_info`) einmalig auslesen und mit `SymbolSpec`
   vergleichen: Digits, Point, Volumen-Schritt, Stop-Level, Füllungsarten.
4. Einen Kaufplan mit `plane_kauf` erzeugen und **ohne** Senden gegen die
   Terminal-Metadaten prüfen.
5. Erst nach ausdrücklicher Policy-Änderung einen separaten Adapter für
   `order_send` ergänzen; dabei Rejects, Teilfüllungen, Wiederholungen und den
   Positionsabgleich mit `gleiche_positionen` testen.
6. Keine echten Orders ohne Demo-Konto, ausdrückliche Freigabe und
   dokumentierte Ergebnisse.

## Was dieser Baustein nicht leistet

- Keine echte Orderausführung, keine Retries gegen den Broker, keine
  Teilfüllungsbehandlung.
- Keine automatische Symbol-Suffix-Erkennung.
- Keine Aussage über Strategiequalität oder Profitabilität.
- Keine Abnahme der realen MT5-Verbindung; die ist auf dieser Maschine an der
  Terminal-Autorisierung gescheitert.
