# Reproduzierbare Synthetik-Messung

`scripts/messe_synthetisch.py` erzeugt eine deterministische Fünfjahres-M15-Reihe
(Seed 42, Werktage 2021-11-22 bis 2026-11-20, 96 Kerzen je Tag) und legt sie als
`SYN1_M15.csv` bis `SYN<N>_M15.csv` ab. Damit lassen sich Import und Richterlauf
mit gleicher Datenmenge wiederholt messen. Für die Nachmessung aus PR #245 gibt
es zusätzlich den Modus `2-1-mio` mit 2.100.000 M15-Zeilen. Die Reihen sind
synthetisch und **keine Marktaussage**.

## Aufruf

```bash
# vier Symbole, wie in der Skalierungsmessung
.venv/bin/python scripts/messe_synthetisch.py

# ein Symbol als Referenz
.venv/bin/python scripts/messe_synthetisch.py --symbole 1

# Arbeitsordner behalten (muss leer sein)
.venv/bin/python scripts/messe_synthetisch.py --symbole 4 \
  --arbeitsordner artifacts/messung-2026-11-22
```

Ohne `--arbeitsordner` entsteht ein temporärer Ordner unter `artifacts/`, der
nach dem Lauf gelöscht wird. Mit `--arbeitsordner` bleiben Config, CSV, SQLite,
Vault und `bericht.json` zur Nachprüfung liegen.

## Drei getrennte Phasen

| Phase | Prozess | Inhalt |
|---|---|---|
| Import | `orakel daten --csv ...` | eine CSV je Symbol, blockweiser Import |
| Richter (nur Walk-Forward) | eigener Prozess | `beurteile_walk_forward` je Symbol und Strategie, ohne Agenten/Konferenz |
| Vollständiger Lauf | `orakel pruefen` | Daten → Research → Richter → Risiko → Plan → Bericht inkl. Agenten/Konferenz |

Jede Phase läuft in einem eigenen Prozess. Gemessen werden **Wanduhrzeit** und
**Spitzen-RSS getrennt**. Der RSS ist der höchste `VmHWM` des jeweiligen
Prozesses, kein Summenwert; unter Nicht-Linux gibt das Skript `n/a` aus.

## 2,1-Mio.-Nachmessung

```bash
.venv/bin/python scripts/messe_synthetisch.py --modus 2-1-mio \
  --arbeitsordner artifacts/messung-2-1-mio
```

Der Modus erzeugt genau 2.100.000 lückenlose M15-Zeilen bis
`2026-11-20 23:45 UTC` (Seed 42) in einer Datei `SYN1_M15.csv`. Danach laufen
drei Importpfade als getrennte Prozesse, jeweils mit eigener isolierter Config
und eigener SQLite-Datei:

| Phase | Pfad |
|---|---|
| Blockweise | `lade_csv_bloecke` und `kerzen_speichern_bloecke` |
| Zeilenweise | `lade_csv` und `kerzen_speichern` mit `to_dict("records")` |
| CLI (blockweise) | `orakel daten --csv SYN1_M15.csv` |

Wanduhrzeit und Spitzen-RSS werden für jede Phase separat gemessen. Die
Wanduhrzeit umfasst auch den Start des jeweiligen Python-Prozesses; der RSS ist
der höchste `VmHWM` dieses Prozesses. Die CSV-Erzeugung zählt nicht zur
Importzeit.

Anschliessend vergleicht das Skript die Tabelle `kerzen` der drei Datenbanken:
Zeilen- und Zeitstempelzahl, kleinsten und grössten Zeitstempel,
`PRAGMA integrity_check` und einen SHA-256 über alle Zeilen in stabiler
Sortierung. Lauf- und Ereignismetadaten werden nicht verglichen, weil nur der
CLI-Pfad sie zusätzlich schreibt. Das Ergebnis steht in `bericht.json` im
Arbeitsordner; bei Abweichung endet der Lauf mit Exit 1.

Der zeilenweise Pfad hält die gesamte Reihe und die Liste der Datensätze im
Speicher und braucht daher deutlich mehr RSS als der blockweise Pfad. Der
Modus ist für eine Maschine mit ausreichend RAM gedacht; konkrete Messwerte
hängen von Maschine, Commit und Dateisystem-Cache ab und sind keine Zusage.

## Isolation

Das Skript liest `config.toml` nur als Vorlage und schreibt eine eigene Config in
den Arbeitsordner. Darin zeigen `db_pfad`, `daten_ordner` und `vault_ordner`
ausschliesslich auf diesen Ordner; `datenquelle` steht auf `csv`. Die feste Reihe
soll nicht mit dem Kalender veralten, deshalb wird im Bench-Config
`max_alter_tage` auf 36500 gesetzt. Alle anderen Werte bleiben unverändert.

Vor dem Start prüft das Skript, dass die Bench-DB nicht die Projekt-`orakel.db`
ist. Die bestehende Datenbank wird weder geöffnet noch verändert.

## Einordnung

- Die reine Richterprüfung zeigt die Skalierung pro Symbol ohne den festen
  Pipeline-Anteil. Der vollständige Lauf enthält zusätzlich Agenten, Konferenz und
  Bericht; seine Zeit ist deshalb höher und weniger stark von der Symbolzahl
  abhängig.
- Bei der synthetischen Zufallsreihe besteht keine Strategie; der versiegelte
  Holdout wird nicht geöffnet. Bei echten Daten mit bestandenen Kandidaten kann
  der Richterlauf länger dauern.
- Eine Messung ist eine Hausnummer für diese Maschine und diesen Commit, keine
  garantierte Laufzeit. VM-Last, CPU-Pinning und Dateisystem-Cache bleiben
  Einflussgrössen.
