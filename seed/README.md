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
src = sqlite3.connect("file:orakel.db?mode=ro", uri=True)
dst = sqlite3.connect("seed/orakel-seed.db")
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
```

`Connection.backup` übernimmt auch noch nicht checkpointete WAL-Inhalte, die
Datei ist danach in sich konsistent.

## Warum das nötig ist

`orakel.db` ist per `.gitignore` und `.dockerignore` vom Build ausgeschlossen.
Ohne Seed legt die App beim ersten Start nur eine leere Datenbank an – genau
das war die Ursache des leeren Railway-Volumes (siehe `RAILWAY.md`).
