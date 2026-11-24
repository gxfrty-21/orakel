#!/bin/sh
set -eu

PORT="${PORT:-3000}"
DATA="${ORAKEL_DATA:-/data}"
CONFIG="${ORAKEL_CONFIG:-/app/config.toml}"

# Fail-closed: Der Container bindet 0.0.0.0. Ohne Login startet der Server nicht.
# Eine frühere ORAKEL_ALLOW_NO_AUTH-Ausnahme gibt es hier bewusst nicht mehr:
# Ein Neustart mit einer Altlast darf keinen offenen externen Port erzeugen.
if [ -z "${ORAKEL_AUTH_USER:-}" ] || [ -z "${ORAKEL_AUTH_PASS:-}" ]; then
  echo "orakel-entrypoint: FEHLER: ORAKEL_AUTH_USER und ORAKEL_AUTH_PASS muessen gesetzt sein." >&2
  echo "orakel-entrypoint: Der Container bindet 0.0.0.0; ohne Login bricht der Server ab (fail-closed)." >&2
  echo "orakel-entrypoint: Docker: beide Werte in .env, Railway: Service-Variablen setzen." >&2
  exit 1
fi

mkdir -p "$DATA/daten" "$DATA/vault"

export ORAKEL_DB_PFAD="${ORAKEL_DB_PFAD:-$DATA/orakel.db}"
export ORAKEL_DATEN_ORDNER="${ORAKEL_DATEN_ORDNER:-$DATA/daten}"
export ORAKEL_VAULT_ORDNER="${ORAKEL_VAULT_ORDNER:-$DATA/vault}"

# Erststart: mitgelieferte DB nur in ein leeres Volume importieren.
# Bestehende Daten werden nie überschrieben, siehe orakel/seed.py.
if ! python -m orakel.seed --db "$ORAKEL_DB_PFAD" \
     --seed "${ORAKEL_SEED_DB:-/app/seed/orakel-seed.db}"; then
  echo "orakel-entrypoint: Seed-Schritt ohne Import beendet (siehe Meldung oben)"
fi

if [ "${ORAKEL_TAKT:-0}" = "1" ]; then
  exec python -m orakel --config "$CONFIG" serve --host 0.0.0.0 --port "$PORT" --takt
fi

exec python -m orakel --config "$CONFIG" serve --host 0.0.0.0 --port "$PORT"
