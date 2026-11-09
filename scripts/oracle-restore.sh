#!/usr/bin/env bash
# Spielt ein Export-Archiv in das Docker-Volume auf der Oracle-VM ein.
# Aufruf auf der VM im Projektordner:
#   sudo ./scripts/oracle-restore.sh /pfad/orakel-umzug.tar.gz
set -euo pipefail

ARCHIV="${1:-}"
ZIEL="${ZIEL:-/srv/orakel}"

fehler() { echo "FEHLER: $*" >&2; exit 1; }
info()   { echo "==> $*"; }

[ -n "$ARCHIV" ] || fehler "Aufruf: $0 /pfad/orakel-umzug.tar.gz"
[ -f "$ARCHIV" ] || fehler "Archiv nicht gefunden: $ARCHIV"
cd "$ZIEL" || fehler "Projektordner fehlt: $ZIEL"

tar tzf "$ARCHIV" >/dev/null || fehler "kein gültiges tar.gz"
tar tzf "$ARCHIV" | grep -qx "orakel.db" || fehler "orakel.db fehlt im Archiv"

info "Sicherung des aktuellen Volume-Inhalts"
mkdir -p "$ZIEL/backups"
docker compose run --rm --no-deps -T --entrypoint sh orakel \
  -c "tar czf - -C /data ." > "$ZIEL/backups/vor-import-$(date +%F-%H%M).tar.gz"

info "App stoppen"
docker compose stop orakel

info "Archiv einspielen"
docker compose run --rm --no-deps -T --entrypoint sh orakel \
  -c "tar xzf - -C /data" < "$ARCHIV"

info "App starten"
docker compose start orakel

info "Warten auf Healthcheck"
ok=0
for _ in $(seq 1 30); do
  if docker compose exec -T orakel python -c \
      "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','3000')+'/api/health',timeout=4)" \
      >/dev/null 2>&1; then
    ok=1; break
  fi
  sleep 4
done

if [ "$ok" -eq 1 ]; then
  echo
  docker compose exec -T orakel python -c \
    "import os,urllib.request,json; d=json.load(urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','3000')+'/api/health')); print(d)"
  echo "OK. Login und Artikelzahl im Dashboard prüfen."
else
  echo "Healthcheck rot. Logs:"
  docker compose logs --tail 50 orakel
  echo "Rollback: die Sicherung unter $ZIEL/backups/ mit demselben Befehl einspielen."
  exit 1
fi
