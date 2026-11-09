#!/bin/sh
set -eu

PORT="${PORT:-3000}"
DATA="${ORAKEL_DATA:-/data}"
CONFIG="${ORAKEL_CONFIG:-/app/config.toml}"

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
