#!/usr/bin/env bash
# Prüft die Screenshotpfade aus einem Selbsttest-Log gegen die erzeugten
# Dateien. Jeder Clusterbefund braucht einen eigenen, nicht-leeren Screenshot;
# zusätzlich muss die Anzahl der Logeinträge zur Anzahl der Dateien passen.
set -euo pipefail

LOG=${1:?Aufruf: pruefe-cluster-screenshotnamen.sh <selbsttest.log> <bilderverzeichnis>}
BILDER=${2:?Aufruf: pruefe-cluster-screenshotnamen.sh <selbsttest.log> <bilderverzeichnis>}

mapfile -t bilder < <(grep '^Screenshot: ' "$LOG" | sed 's/^Screenshot: //')

if [ "${#bilder[@]}" -lt 2 ]; then
  echo "Zu wenige Cluster-Screenshots: ${#bilder[@]} (erwartet mindestens 2)"
  exit 1
fi

doppelt=$(printf '%s\n' "${bilder[@]}" | sort | uniq -d)
if [ -n "$doppelt" ]; then
  echo "Doppelte Screenshot-Namen:"
  printf '%s\n' "$doppelt"
  exit 1
fi

for bild in "${bilder[@]}"; do
  if [ ! -s "$bild" ]; then
    echo "Screenshot fehlt oder ist leer: $bild"
    exit 1
  fi
done

anzahl=$(find "$BILDER" -maxdepth 1 \
  -name 'selbsttest-360px-ship-cluster-*.png' -size +0c | wc -l)
if [ "$anzahl" -ne "${#bilder[@]}" ]; then
  echo "Screenshot-Anzahl passt nicht zum Selbsttestlog: $anzahl Dateien, ${#bilder[@]} Logeinträge"
  exit 1
fi

echo "Cluster-Screenshots eindeutig: ${#bilder[@]}"
