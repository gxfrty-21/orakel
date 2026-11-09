# Orakel — Systemcheck für ein späteres lokales Sprachmodell
# Liest nur Werte aus, ändert nichts. Ausgabe kopieren und im Chat einfügen.
$ErrorActionPreference = "SilentlyContinue"

function Zeile($name, $wert) {
    "{0,-22} {1}" -f $name, $wert
}

$os  = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1

$ramGB  = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$freiGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)

$laufwerk = Get-PSDrive -PSProvider FileSystem | Sort-Object Free -Descending | Select-Object -First 1
$diskFrei = if ($laufwerk) { [math]::Round($laufwerk.Free / 1GB, 1) } else { "unbekannt" }

Zeile "Betriebssystem" $os.Caption
Zeile "Prozessor"     $cpu.Name
Zeile "Kerne / Threads" ("{0} / {1}" -f $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
Zeile "RAM gesamt"    "$ramGB GB"
Zeile "RAM frei"      "$freiGB GB"
Zeile "Freier Speicher" "$diskFrei GB ($($laufwerk.Name))"

Write-Output ""
Write-Output "Grafikkarte(n):"
$gpus = Get-CimInstance Win32_VideoController
if (-not $gpus) { Write-Output "  keine gefunden" }
foreach ($g in $gpus) {
    $vram = if ($g.AdapterRAM) { [math]::Round($g.AdapterRAM / 1GB, 1) } else { "?" }
    Write-Output ("  {0} — gemeldeter VRAM: {1} GB" -f $g.Name, $vram)
}
Write-Output "  Hinweis: Windows meldet bei Karten über 4 GB oft zu wenig. Exakt mit 'dxdiag' oder 'nvidia-smi' prüfen."

Write-Output ""
$nvidia = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($nvidia) {
    Write-Output "nvidia-smi:"
    & nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
} else {
    Write-Output "nvidia-smi: nicht vorhanden (keine NVIDIA-Treiber oder keine NVIDIA-Karte)"
}

Write-Output ""
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { Write-Output ("Python: " + (& python --version 2>&1)) } else { Write-Output "Python: nicht im PATH" }

Write-Output ""
Write-Output "Orientierung (Q4-Quantisierung, grob):"
Write-Output "  unter 8 GB RAM   → 1-2B Modelle, 3B knapp"
Write-Output "  8-12 GB RAM      → 3-4B flüssig, 7B sehr langsam"
Write-Output "  16 GB RAM        → 7-8B auf CPU brauchbar (wenige Tokens/s)"
Write-Output "  32 GB RAM        → 7-8B komfortabel, 13B knapp"
Write-Output "  6-8 GB VRAM      → 7-8B schnell;  12 GB+ → 13B"
