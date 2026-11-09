#!/bin/sh
set -eu

PORT="${PORT:-3000}"
DATA="${ORAKEL_DATA:-/data}"
CONFIG="${ORAKEL_CONFIG:-/app/config.toml}"

mkdir -p "$DATA/daten" "$DATA/vault"

export ORAKEL_DB_PFAD="${ORAKEL_DB_PFAD:-$DATA/orakel.db}"
export ORAKEL_DATEN_ORDNER="${ORAKEL_DATEN_ORDNER:-$DATA/daten}"
export ORAKEL_VAULT_ORDNER="${ORAKEL_VAULT_ORDNER:-$DATA/vault}"

if [ "${ORAKEL_TAKT:-0}" = "1" ]; then
  exec python -m orakel --config "$CONFIG" serve --host 0.0.0.0 --port "$PORT" --takt
fi

exec python -m orakel --config "$CONFIG" serve --host 0.0.0.0 --port "$PORT"
