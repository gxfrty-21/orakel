#!/usr/bin/env bash
# Führt den Widerspruch-E2E lokal reproduzierbar aus: Seed-Kopie, Dashboard
# auf Port 3300, Positivfall, 3/3-Negativtest und Manifest-Prüfung.
#
# Voraussetzungen:
#   - Python-Umgebung mit requirements.txt (.venv oder PYTHON=…)
#   - Playwright-Abhängigkeit: (cd scripts && npm ci && npx playwright install chromium)
#   - Chromium-Laufzeitbibliotheken, z. B. über scripts/setup-playwright-local.sh
#
# Aufruf:
#   bash scripts/e2e-widerspruch-lokal.sh
#   ORAKEL_E2E_PORT=3310 bash scripts/e2e-widerspruch-lokal.sh
#   PYTHON=.venv/bin/python bash scripts/e2e-widerspruch-lokal.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ORAKEL_E2E_PORT:-3300}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3 || command -v python || true)"
fi
if [ -z "$PYTHON" ]; then
  echo "FEHLER: Kein Python gefunden. PYTHON=/pfad/zu/python setzen." >&2
  exit 1
fi

# Ohne diese Variablen fehlt Chromium libnspr4.so & Co. Das Setup-Skript legt
# sie in .playwright-local/ ab und schreibt env.sh.
if [ -r "$ROOT/.playwright-local/env.sh" ]; then
  # shellcheck disable=SC1091
  . "$ROOT/.playwright-local/env.sh"
fi

if [ ! -d "$ROOT/scripts/node_modules/playwright" ]; then
  echo "FEHLER: Playwright fehlt in scripts/node_modules." >&2
  echo "  (cd scripts && npm ci && npx playwright install chromium)" >&2
  exit 1
fi

# Früh prüfen, damit ein fehlendes Systempaket nicht wie ein Serverfehler wirkt.
if ! (cd "$ROOT/scripts" && node --input-type=module -e '
import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
await browser.close();
') >/dev/null 2>&1; then
  echo "FEHLER: Chromium startet nicht (typisch: libnspr4.so fehlt)." >&2
  echo "Einmalig ohne sudo:" >&2
  echo "  bash scripts/setup-playwright-local.sh" >&2
  echo "  source .playwright-local/env.sh" >&2
  echo "Oder systemweit (sudo):" >&2
  echo "  npx --prefix scripts playwright install --with-deps chromium" >&2
  exit 1
fi

TMP="$(mktemp -d -t orakel-widerspruch-XXXXXX)"
DB="$TMP/widerspruch.db"
SERVER_LOG="$TMP/server.log"
server=""
aufraeumen() {
  if [ -n "$server" ]; then
    kill "$server" 2>/dev/null || true
  fi
  rm -rf "$TMP"
}
trap aufraeumen EXIT

echo "1/4: Seed-Kopie anlegen ($DB)"
cp "$ROOT/seed/orakel-seed.db" "$DB"
"$PYTHON" "$ROOT/scripts/seed_widerspruch.py" "$DB"

echo "2/4: Dashboard auf http://127.0.0.1:$PORT starten"
(
  cd "$ROOT"
  ORAKEL_DB_PFAD="$DB" "$PYTHON" -m orakel serve --host 127.0.0.1 --port "$PORT"
) >"$SERVER_LOG" 2>&1 &
server=$!

bereit=0
for _ in $(seq 1 30); do
  if curl --silent --fail "http://127.0.0.1:$PORT/api/nexus/status" >/dev/null; then
    bereit=1
    break
  fi
  sleep 1
done
if [ "$bereit" -ne 1 ]; then
  echo "FEHLER: Dashboard wurde auf Port $PORT nicht bereit." >&2
  echo "Ist der Port belegt? ORAKEL_E2E_PORT=3310 setzen." >&2
  tail -20 "$SERVER_LOG" >&2
  exit 1
fi
echo "     bereit"

echo "3/4: Positivfall (API bis Karte)"
node "$ROOT/scripts/pruefe-widerspruch-e2e.mjs" --url "http://127.0.0.1:$PORT"

echo "4/4: Negativtest 3/3 mit JSON-Ergebnis und Manifest-Prüfung"
node "$ROOT/scripts/pruefe-widerspruch-e2e.mjs" --url "http://127.0.0.1:$PORT" \
  --negativtest --ergebnis "$TMP/negativtest-ergebnis.json"
node "$ROOT/scripts/pruefe-widerspruch-e2e-ergebnis.mjs" \
  --ergebnis "$TMP/negativtest-ergebnis.json" \
  --pflicht "$ROOT/scripts/widerspruch-e2e-required-checks.json" \
  --profil voll

echo
echo "Lokaler Widerspruch-E2E grün: Positivfall, 3/3-Negativtest und"
echo "drei bestandene Pflichtfälle laut Manifest."
