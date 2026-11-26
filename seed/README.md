# Seed-Datenbank

`orakel-seed.db` ist die Datenbank, die der Container beim **ersten Start** in
ein leeres Volume importiert. Sie wird im Image unter `/app/seed/` mitgeliefert
und über `ORAKEL_SEED_DB` angesprochen.

## Verhalten

Der Import läuft in `orakel/seed.py`, aufgerufen vom `docker-entrypoint.sh`
**vor** dem Serverstart:

| Zustand der Zieldatenbank | Aktion |
|---|---|
| Datei fehlt | Seed wird atomar kopiert |
| Datei vorhanden, aber 0 Zeilen in allen Kerntabellen | leere DB wird als `orakel.db.leer-<zeitstempel>` gesichert, dann Seed importiert |
| Datei enthält Kerndaten | nichts wird angefasst, nur eine Logzeile |
| Datei unlesbar/beschädigt | nichts wird angefasst, Warnung im Log, Start läuft weiter |
| kein Seed vorhanden | nichts wird angefasst, Hinweis im Log |

Kerndaten sind Zeilen in `artikel`, `validierungen`, `trades`, `kerzen`,
`agenten_laeufe`, `intel_inhalte`, `konferenzen`, `ereignisse`, `entscheide`,
`positionen` und `auswahl`. Buchhaltungstabellen (`konto`, `zustand`) sowie das
Company-Grundgerüst (`agent_profiles`, `company_*`) entstehen schon beim ersten
Start und zählen bewusst **nicht** – sonst würde eine frische, leere DB nie als
leer erkannt.

Der Austausch ist atomar: Kopie nach `orakel.db.seed-tmp-<pid>`,
`integrity_check` auf der Kopie, dann `os.replace`. WAL-/SHM-Reste der alten DB
werden zur Sicherung mit verschoben, damit sie nicht zur neuen Datei passen.

## Neu erzeugen

Die Datei ist ein Snapshot der lokalen Datenbank und wird nicht automatisch
aktualisiert. Nach größeren Datenständen neu bauen:

```bash
python3 - <<'PY'
import sqlite3
from orakel.config import load_config

# [basis] db_pfad aus config.toml; ORAKEL_DB_PFAD sticht ihn.
db = load_config("config.toml").db_pfad
src = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
dst = sqlite3.connect("seed/orakel-seed.db")
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
```

`Connection.backup` übernimmt auch noch nicht checkpointete WAL-Inhalte, die
Datei ist danach in sich konsistent.

## Doppelte Validierungen entfernen

Ältere Stände enthalten dieselbe Bewertung mehrfach — ein Eintrag je
Engine-Lauf, obwohl sich an den Kerzen nichts geändert hat. Der Befehl
`--deduplizieren` räumt das auf: je Kombination aus Symbol, Strategie,
Schlüssel, Urteil und Trade-Liste bleibt die jüngste Zeile, die Kopien
verschwinden mit ihren Trades, `auswahl` wird auf die verbliebene Zeile
umgehängt. Das Urteil gehört zur Gleichheit; eine abweichende Bewertung wird
nie gelöscht. Der Befehl ist idempotent — ein zweiter Aufruf entfernt nichts
mehr und meldet `0`.

```bash
# Probelauf auf der DB aus config.toml/ORAKEL_DB_PFAD: nur zeigen, was wegfiele
python -m orakel.seed --deduplizieren --probelauf

# Aufräumen und die Datei verdichten
python -m orakel.seed --deduplizieren --vakuum

# Anderer Bestand, etwa der Seed selbst
python -m orakel.seed --db /app/seed/orakel-seed.db --deduplizieren
```

Der Befehl meldet vorher und nachher die Zahl der Validierungen, die
entfernten Trades, umgehängte `auswahl`-Zeilen sowie `integrity_check` und
`foreign_key_check`.

## Ein-Lauf-Stand

Der mitgelieferte Seed zeigt nur den letzten Lauf. `--ein-lauf` entfernt alle
Zeilen älterer Läufe: Ereignisse, Konferenzprotokolle, Agentenläufe, Konto und
Paper-Zustand sowie Spider- und Intel-Daten. Maßgeblich ist
`zustand.letzter_lauf_id`; Zeilen des letzten Laufs bleiben stehen, ebenso
Kerzen, Validierungen und Trades. Der Befehl ist idempotent.

```bash
# Probelauf: nur zählen, was wegfiele
python -m orakel.seed --ein-lauf --probelauf

# Aufräumen und die Datei verdichten
python -m orakel.seed --ein-lauf --vakuum

# Anderer Bestand, etwa der Seed selbst
python -m orakel.seed --db /app/seed/orakel-seed.db --ein-lauf --vakuum
```

`--probelauf` und `--vakuum` gelten für `--deduplizieren` und `--ein-lauf`;
beide Schritte lassen sich in einem Aufruf kombinieren.

## Warum das nötig ist

`orakel.db` ist per `.gitignore` und `.dockerignore` vom Build ausgeschlossen.
Ohne Seed legt die App beim ersten Start nur eine leere Datenbank an – genau
das war die Ursache des leeren Railway-Volumes (siehe `RAILWAY.md`).
