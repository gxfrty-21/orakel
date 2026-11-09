#!/usr/bin/env bash
# Orakel — Systemcheck für ein späteres lokales Sprachmodell (Linux/macOS)
# Liest nur Werte aus, ändert nichts. Ausgabe kopieren und im Chat einfügen.
set -u

echo "Betriebssystem      $(uname -srm)"

if [ -r /proc/cpuinfo ]; then
  echo "Prozessor           $(awk -F: '/model name/ {gsub(/^ +/, "", $2); print $2; exit}' /proc/cpuinfo)"
fi
echo "Kerne               $(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo '?')"

if [ -r /proc/meminfo ]; then
  gesamt=$(awk '/MemTotal/ {printf "%.1f", $2/1048576}' /proc/meminfo)
  frei=$(awk '/MemAvailable/ {printf "%.1f", $2/1048576}' /proc/meminfo)
  echo "RAM gesamt          ${gesamt} GB"
  echo "RAM verfügbar       ${frei} GB"
else
  echo "RAM gesamt          $(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.1f GB", $1/1073741824}')"
fi

echo "Freier Speicher     $(df -h . | awk 'NR==2 {print $4}') (aktuelles Verzeichnis)"

echo ""
echo "Grafikkarte(n):"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | sed 's/^/  /'
elif command -v lspci >/dev/null 2>&1; then
  lspci | grep -Ei 'vga|3d|display' | sed 's/^/  /' || echo "  keine gefunden"
else
  echo "  keine Abfrage möglich"
fi

echo ""
echo "Python: $(python3 --version 2>/dev/null || echo 'nicht im PATH')"

echo ""
echo "Orientierung (Q4-Quantisierung, grob):"
echo "  unter 8 GB RAM   → 1-2B Modelle, 3B knapp"
echo "  8-12 GB RAM      → 3-4B flüssig, 7B sehr langsam"
echo "  16 GB RAM        → 7-8B auf CPU brauchbar (wenige Tokens/s)"
echo "  32 GB RAM        → 7-8B komfortabel, 13B knapp"
echo "  6-8 GB VRAM      → 7-8B schnell;  12 GB+ → 13B"
