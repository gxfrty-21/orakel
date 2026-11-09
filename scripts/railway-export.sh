#!/usr/bin/env bash
# Exportiert das Railway-Volume als umzugsfähiges Archiv.
# SQLite wird über die Backup-API konsistent kopiert, nicht mitten im Schreiben getarnt.
#
# Voraussetzungen: Railway CLI installiert und eingeloggt, Projekt verlinkt,
# Dienst läuft (Volume-Zugriff geht über die laufende Instanz).
#
# Aufruf:  ./scripts/railway-export.sh [ziel.tar.gz]
set -euo pipefail

ZIEL="${1:-./orakel-umzug-$(date +%F-%H%M).tar.gz}"
VOL_ARCHIV="${VOL_ARCHIV:-/umzug.tar.gz}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }

command -v railway >/dev/null 2>&1 || fehler "Railway CLI fehlt (npm i -g @railway/cli)"
railway status >/dev/null 2>&1 || fehler "kein verlinktes Projekt — erst 'railway link' ausführen"

echo "==> Dienststatus"
railway status | sed -n '1,12p'

echo "==> SQLite konsistent sichern (Backup-API)"
railway ssh -- python -c \
  "import sqlite3; s=sqlite3.connect('/data/orakel.db'); d=sqlite3.connect('/tmp/orakel.db'); s.backup(d); d.close(); s.close(); print('db-backup ok')"

railway ssh -- python -c \
  "import sqlite3; c=sqlite3.connect('/tmp/orakel.db'); print('integrity:', c.execute('PRAGMA integrity_check').fetchone()[0]); print('artikel:', c.execute('SELECT COUNT(*) FROM artikel').fetchone()[0]); c.close()"

echo "==> Vault und Daten prüfen"
railway ssh -- sh -c 'ls -d /data/vault /data/daten 2>/dev/null || echo "WARNUNG: Ordner fehlen"'

echo "==> Archiv im Volume erzeugen"
railway ssh -- tar czf "$VOL_ARCHIV" -C /data vault daten -C /tmp orakel.db
railway ssh -- stat -c 'Archivgroesse: %s Bytes' "$VOL_ARCHIV"

echo "==> Herunterladen"
railway volume files download "$VOL_ARCHIV" "$ZIEL"

echo "==> Aufräumen im Volume"
railway ssh -- rm -f "$VOL_ARCHIV" /tmp/orakel.db

echo "==> Lokal prüfen"
[ -s "$ZIEL" ] || fehler "Download ist leer"
tar tzf "$ZIEL" >/dev/null || fehler "Archiv ist kein gültiges tar.gz"

python3 - "$ZIEL" <<'PY'
import sqlite3, sys, tarfile, tempfile, os
archiv = sys.argv[1]
with tarfile.open(archiv, "r:gz") as t:
    namen = t.getnames()
    for pflicht in ("orakel.db", "vault"):
        if not any(n == pflicht or n.startswith(pflicht + "/") for n in namen):
            raise SystemExit(f"FEHLER: {pflicht} fehlt im Archiv")
    with tempfile.TemporaryDirectory() as tmp:
        t.extract("orakel.db", tmp)
        c = sqlite3.connect(os.path.join(tmp, "orakel.db"))
        print("integrity:", c.execute("PRAGMA integrity_check").fetchone()[0])
        print("artikel:", c.execute("SELECT COUNT(*) FROM artikel").fetchone()[0])
        c.close()
print("Dateien im Archiv:", len(namen))
print("OK:", archiv)
PY

echo
echo "Nächster Schritt: Archiv auf die Oracle-VM übertragen und dort"
echo "  ./scripts/oracle-restore.sh $ZIEL"
