#!/usr/bin/env bash
# Richtet den täglichen Orakel-Nachtlauf auf der Oracle-VM ein.
#
# Aufruf auf der VM im Projektordner:
#   sudo bash scripts/oracle-nacht-install.sh
#
# Die Healthchecks-Ping-URL wird verdeckt abgefragt und nur in
# /srv/orakel/.env (chmod 600) gespeichert. Für Automatisierung kann
# ORAKEL_PING_URL vorab gesetzt werden; der verdeckte Prompt ist der sichere
# Weg. OHNE_LAUF=1 installiert nur den Timer ohne Testlauf.
set -euo pipefail

ZIEL="${ZIEL:-/srv/orakel}"
DIENST="orakel-nacht.service"
FAIL_DIENST="orakel-nacht-fail.service"
TIMER="orakel-nacht.timer"
TMP=""
URLDATEI=""
aufraeumen() { rm -f "${TMP:-}" "${URLDATEI:-}"; }
trap aufraeumen EXIT

fehler() { echo "FEHLER: $*" >&2; exit 1; }
info()   { echo "==> $*"; }

[ "$(id -u)" -eq 0 ] || fehler "bitte als root bzw. mit sudo ausführen"
[ -d "$ZIEL" ] || fehler "Projektordner fehlt: $ZIEL"
[ -f "$ZIEL/.env" ] || fehler ".env fehlt: $ZIEL/.env — zuerst scripts/oracle-bootstrap.sh ausführen"
[ -f "$ZIEL/docker-compose.yml" ] || fehler "docker-compose.yml fehlt in $ZIEL"
[ -x "$ZIEL/deploy/orakel-nacht-fail.sh" ] || fehler "deploy/orakel-nacht-fail.sh fehlt oder ist nicht ausführbar"
command -v docker >/dev/null 2>&1 || fehler "docker fehlt"
docker compose version >/dev/null 2>&1 || fehler "docker compose plugin fehlt"
grep -Eq '^ORAKEL_DOMAIN=.+' "$ZIEL/.env" || fehler "ORAKEL_DOMAIN fehlt in $ZIEL/.env"

info "Container-Status prüfen"
if ! docker compose --project-directory "$ZIEL" ps --status running --services 2>/dev/null \
    | grep -qx "orakel"; then
  fehler "Container 'orakel' läuft nicht. Zuerst: cd $ZIEL && docker compose up -d"
fi

info "Healthchecks-Ping-URL"
PING="${ORAKEL_PING_URL:-}"
if [ -z "$PING" ]; then
  PING="$(grep -m1 '^ORAKEL_PING_URL=' "$ZIEL/.env" 2>/dev/null | cut -d= -f2- || true)"
fi
if [ -z "$PING" ] && [ -t 0 ]; then
  printf "%s" "Ping-URL aus Healthchecks (leer = ohne Dead-man's-Switch): "
  IFS= read -rsp '' PING || true
  echo
fi
if [ -n "$PING" ]; then
  PING="${PING%/}"
  case "$PING" in
    http://*|https://*) ;;
    *) fehler "Ping-URL muss mit http:// oder https:// beginnen" ;;
  esac
  case "$PING" in
    *[[:space:]]*|*\"*) fehler "Ping-URL enthält Leerzeichen oder Anführungszeichen" ;;
  esac
  case "$PING" in
    */fail) fehler "Bitte die normale Ping-URL ohne /fail einfügen" ;;
  esac
fi

if [ -n "$PING" ]; then
  info "Ping-URL in .env schreiben (chmod 600, kein Klartext im Log)"
  URLDATEI="$(mktemp)"
  chmod 600 "$URLDATEI"
  printf '%s' "$PING" > "$URLDATEI"
  TMP="$(mktemp)"
  awk 'NR==FNR { url=$0; next }
       /^ORAKEL_PING_URL=/ {
         if (!gesetzt) { print "ORAKEL_PING_URL=" url; gesetzt=1 }
         next
       }
       { print }
       END { if (!gesetzt) print "ORAKEL_PING_URL=" url }' \
      "$URLDATEI" "$ZIEL/.env" > "$TMP"
  install -m 600 "$TMP" "$ZIEL/.env"
  rm -f "$TMP" "$URLDATEI"
  TMP=""; URLDATEI=""
else
  info "Keine Ping-URL — der Dead-man's-Switch bleibt aus"
  chmod 600 "$ZIEL/.env"
fi

info "Container mit der neuen Umgebung neu starten"
docker compose --project-directory "$ZIEL" up -d

info "Auf Healthcheck warten"
gesund=0
for _ in $(seq 1 30); do
  if docker compose --project-directory "$ZIEL" exec -T orakel python -c \
      "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','3000')+'/api/health',timeout=4)" \
      >/dev/null 2>&1; then
    gesund=1
    break
  fi
  sleep 2
done
if [ "$gesund" -ne 1 ]; then
  docker compose --project-directory "$ZIEL" logs --tail 30 orakel || true
  fehler "Container wurde nicht gesund"
fi

info "systemd-Einheiten installieren"
install -m 0644 "$ZIEL/deploy/$DIENST" "/etc/systemd/system/$DIENST"
install -m 0644 "$ZIEL/deploy/$FAIL_DIENST" "/etc/systemd/system/$FAIL_DIENST"
install -m 0644 "$ZIEL/deploy/$TIMER" "/etc/systemd/system/$TIMER"
systemctl daemon-reload
systemctl enable "$TIMER" >/dev/null
systemctl restart "$TIMER"

lauf_ok=1
if [ "${OHNE_LAUF:-0}" != "1" ]; then
  info "Erster Nachtlauf — das kann einige Minuten dauern"
  if ! systemctl start "$DIENST"; then
    lauf_ok=0
  fi
  echo "--- Dienststatus ---"
  systemctl --no-pager --full status "$DIENST" 2>&1 | sed -n '1,12p' || true
  echo "--- letzte Zeilen ---"
  journalctl -u "$DIENST" -n 20 --no-pager || true
fi

info "Gespeicherten Zustand lesen"
docker compose --project-directory "$ZIEL" exec -T orakel python -c \
  "import json; from orakel.db import Facts; n=Facts('/data/orakel.db').zustand('nexus_nacht') or {}; b=n.get('backup') or {}; print(json.dumps({'ok': n.get('ok'), 'zeit': n.get('zeit'), 'fehler': n.get('fehler'), 'meldungen': n.get('meldungen'), 'backup_erstellt': b.get('erstellt'), 'backup_integrity': b.get('integrity'), 'ping': n.get('ping')}, ensure_ascii=False))" || true

echo
systemctl list-timers --all "$TIMER" --no-pager || true
echo
if [ -n "$PING" ]; then
  echo "Healthchecks: Ping-URL aktiv. Im Healthchecks-Dashboard muss der erste Ping sichtbar sein."
else
  echo "Healthchecks: keine Ping-URL gesetzt — der Dead-man's-Switch ist noch aus."
  echo "Später erneut ausführen, um ihn zu aktivieren."
fi
if [ "$lauf_ok" -ne 1 ]; then
  echo "Der erste Lauf ist fehlgeschlagen. Details: journalctl -u $DIENST -n 50 --no-pager"
  exit 1
fi
echo "Fertig. Nächster Lauf: systemctl list-timers $TIMER"
