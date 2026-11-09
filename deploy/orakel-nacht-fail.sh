#!/bin/sh
# Sendet bei einem Unit-Fehler einen Fail-Ping an Healthchecks.io.
# Die Ping-URL kommt aus der Umgebung (/srv/orakel/.env), nicht aus argv.
set -eu

[ -n "${ORAKEL_PING_URL:-}" ] || exit 0

if ! command -v curl >/dev/null 2>&1; then
  echo "curl fehlt; Healthchecks-Fail-Ping nicht gesendet" >&2
  exit 0
fi

# -K - liest die URL aus stdin, damit sie nicht in der Prozessliste steht.
{
  printf 'url = "%s"\n' "${ORAKEL_PING_URL%/}/fail"
  printf 'request = "POST"\n'
  printf 'max-time = 10\n'
  printf 'retry = 2\n'
  printf 'retry-delay = 2\n'
  printf 'globoff\n'
} | curl -fsS -K - >/dev/null 2>&1 || true
