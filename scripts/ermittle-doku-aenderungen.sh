#!/usr/bin/env bash
# Ermittelt für den changes-Job, ob Doku-relevante Dateien geändert wurden.
# Gibt genau eine Zeile "doku=true" oder "doku=false" aus.
set -euo pipefail

: "${EVENT_NAME:?EVENT_NAME fehlt}"
: "${PUSH_SHA:?PUSH_SHA fehlt}"
BASE_SHA="${BASE_SHA:-}"
HEAD_SHA="${HEAD_SHA:-}"
BEFORE_SHA="${BEFORE_SHA:-}"

geaendert=""
range=""
if [ "$EVENT_NAME" = "pull_request" ]; then
  range="$BASE_SHA...$HEAD_SHA"
elif [ -z "$BEFORE_SHA" ] || [ "${BEFORE_SHA//0/}" = "" ]; then
  geaendert=$(git ls-tree -r --name-only "$PUSH_SHA")
elif git cat-file -e "${BEFORE_SHA}^{commit}" 2>/dev/null; then
  range="$BEFORE_SHA..$PUSH_SHA"
else
  # Nach einem Force-Push kann der alte Commit nicht mehr im Checkout liegen;
  # dann konservativ den ganzen Baum prüfen.
  geaendert=$(git ls-tree -r --name-only "$PUSH_SHA")
fi

if [ -z "$geaendert" ] && [ -n "$range" ]; then
  if ! geaendert=$(git diff --name-only "$range"); then
    geaendert=$(git ls-tree -r --name-only "$PUSH_SHA")
  fi
fi

if printf '%s\n' "$geaendert" | grep -Eq '\.md$|^scripts/pruefe_doku\.py$'; then
  echo "doku=true"
else
  echo "doku=false"
fi
