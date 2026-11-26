<#
.SYNOPSIS
Registriert den täglichen Orakel-Transporttask für ein angemeldetes Windows-Konto.

.DESCRIPTION
Der Task startet den Client genau einmal pro Tag. Er läuft nur bei angemeldetem
Benutzer, hat ein Ausführungslimit von 15 Minuten und höchstens zwei native
Neustarts im Abstand von 30 Minuten. Der Token wird nicht als Argument oder in
der Task-XML gespeichert; er kommt aus der Benutzerumgebungsvariable des Kontos.

.PARAMETER Config
TOML-Konfiguration des Clients.

.PARAMETER ServerZeitzone
IANA-Zone der im Client konfigurierten Serverzeit, z. B. Europe/Athens.

.PARAMETER UploadStart
Server-Wandzeit des täglichen Laufs, Standard 00:15.

.PARAMETER Remove
Entfernt den Task, statt ihn anzulegen.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Config = (Join-Path $env:LOCALAPPDATA "Orakel\Transport\transport.toml"),
    [string]$Python = "python.exe",
    [string]$TaskName = "Orakel Transport",
    [string]$ServerZeitzone = "Europe/Athens",
    [string]$UploadStart = "00:15",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$Client = Join-Path $PSScriptRoot "transport_client.py"
$Root = Split-Path -Parent $PSScriptRoot

function Resolve-ServerZeitzone {
    param([string]$Zone)

    try {
        return [TimeZoneInfo]::FindSystemTimeZoneById($Zone)
    } catch [System.TimeZoneNotFoundException] {
        # Windows PowerShell 5.1 kennt oft nur Windows-IDs. Die häufigsten
        # IANA-Zonen der Betriebsdoku werden hier eindeutig übersetzt.
        $iana = @{
            "Europe/Athens" = "GTB Standard Time"
            "Europe/Berlin" = "W. Europe Standard Time"
            "Europe/Zurich" = "W. Europe Standard Time"
            "Europe/Vienna" = "W. Europe Standard Time"
            "UTC" = "UTC"
        }
        if (-not $iana.ContainsKey($Zone)) {
            throw "Zeitzone '$Zone' ist unter Windows PowerShell nicht bekannt. Bitte eine Windows-Zeitzonen-ID oder eine der dokumentierten IANA-Zonen verwenden."
        }
        return [TimeZoneInfo]::FindSystemTimeZoneById($iana[$Zone])
    }
}

function Get-LokaleStartzeit {
    param([string]$Zone, [string]$Start)

    if ($Start -notmatch '^([01]\d|2[0-3]):([0-5]\d)$') {
        throw "UploadStart muss HH:MM sein, z. B. 00:15."
    }
    $teile = $Start.Split(':')
    $versatz = New-TimeSpan -Hours ([int]$teile[0]) -Minutes ([int]$teile[1])
    $roh = Resolve-ServerZeitzone -Zone $Zone
    $tz = [TimeZoneInfo]::FindSystemTimeZoneById($roh.Id)
    $serverJetzt = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz)
    $serverTag = $serverJetzt.Date
    if ($serverJetzt.TimeOfDay -ge $versatz) {
        $serverTag = $serverTag.AddDays(1)
    }
    $serverWand = [DateTime]::SpecifyKind($serverTag.Add($versatz), [DateTimeKind]::Unspecified)
    $utc = [TimeZoneInfo]::ConvertTimeToUtc($serverWand, $tz)
    return [TimeZoneInfo]::ConvertTimeFromUtc($utc, [TimeZoneInfo]::Local)
}

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        if ($PSCmdlet.ShouldProcess($TaskName, "Task entfernen")) {
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Output "Task '$TaskName' entfernt."
        }
    } else {
        Write-Output "Task '$TaskName' existiert nicht."
    }
    return
}

if ($env:USERNAME -ieq "SYSTEM" -or $env:USERNAME -ieq "LocalSystem") {
    throw "Der Transporttask darf nicht als SYSTEM laufen; MT5 braucht den angemeldeten Desktop."
}
if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) {
    throw "Konfiguration fehlt: $Config"
}
if (-not (Test-Path -LiteralPath $Client -PathType Leaf)) {
    throw "Client fehlt: $Client"
}
if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python nicht gefunden: $Python"
}

$check = & $Python $Client --config $Config --check-config
if ($LASTEXITCODE -ne 0) {
    throw "Konfiguration ungültig: $check"
}

$lokal = Get-LokaleStartzeit -Zone $ServerZeitzone -Start $UploadStart
$argumente = "`"$Client`" --config `"$Config`" --once"
$action = New-ScheduledTaskAction -Execute $Python -Argument $argumente -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -Daily -At $lokal
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Write-Output ("Geplant: {0} Serverzeit = {1} lokale Zeit; nur bei angemeldetem Benutzer {2}\{3}." `
    -f $UploadStart, $lokal.ToString("yyyy-MM-dd HH:mm"), $env:USERDOMAIN, $env:USERNAME)

if ($PSCmdlet.ShouldProcess($TaskName, "täglichen Transporttask registrieren")) {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Orakel: abgeschlossenen MT5-Tagesblock einmalig hochladen; kein Bootstrap, keine Broker-Order." `
        -Force | Out-Null
    $task = Get-ScheduledTask -TaskName $TaskName
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Output "Task '$TaskName' registriert; Status: $($task.State); letzter Lauf: $($info.LastRunTime)."
}