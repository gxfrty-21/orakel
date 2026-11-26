# Manuelle Windows-/MT5-Abnahme für PR #302

**Gegenstand:** Windows-Transportclient und Task-Scheduler aus PR [#302](https://github.com/gxfrty-21/orakel/pull/302), Stand `ed8d31c`.

**Ziel:** Den realen Export aus MetaTrader 5, den HTTPS-Upload, die Retry-/Netzwerkpfade, die Fail-closed-Grenzen und die Scheduler-Planung nachvollziehbar abnehmen.

**Nicht Teil dieser Abnahme:** echte Broker-Orders, Bootstrap auf Produktionsdaten, ein real registrierter Scheduled Task, Merge oder Deployment.

## 0. Grenzen und Sicherheitsregeln

- Nur auf einem **dedizierten Windows-Abnahme-Rechner** oder einer isolierten VM ausführen.
- Nur gegen eine ausdrücklich freigegebene **Abnahme-Serverinstanz** testen. Keine Produktionsdatenbank und keinen Produktions-Ledger verändern.
- Der Transport-Token wird ausschließlich über die Umgebungsvariable gesetzt. Er darf nicht in der TOML, in `state.json`, `status.json`, Logs, Prozessargumenten oder Screenshots erscheinen.
- Der Task wird in dieser Checkliste **nur mit `-WhatIf`** geplant. Es gibt keinen Aufruf von `Register-ScheduledTask` ohne `-WhatIf`.
- Vor jedem Lauf prüfen: MT5 läuft, ist angemeldet, das konfigurierte Symbol steht im Market Watch und die benötigte Historie ist geladen.
- Bei einem unerwarteten Ergebnis **sofort abbrechen**, Evidenz sichern und keine Dateien „reparieren“, solange die Serverwahrheit nicht geprüft ist.
- Für die Netzwerkfälle wird ein lokaler Loopback-Stub verwendet. Der Testlauf darf dabei keine echte Serveranfrage erzeugen.

## 1. Arbeitskopie und Testzustand anlegen

Alle folgenden Blöcke in **derselben PowerShell-Sitzung** ausführen; Variablen und Funktionen werden wiederverwendet. PowerShell im Repository-Stamm:

```powershell
$ErrorActionPreference = "Stop"
$Repo   = (Resolve-Path ".").Path
$Python = Join-Path $Repo ".venv\Scripts\python.exe"
$Basis  = Join-Path $env:LOCALAPPDATA "Orakel\Abnahme"
$Config = Join-Path $Basis "transport.toml"
$State  = Join-Path $Basis "state"
$TaskName = "Orakel Transport Abnahme"
$ServerZone = "Europe/Athens"   # muss zu [export].server_zeitzone passen
$UploadStart = "00:15"            # Serverzeit

New-Item -ItemType Directory -Force $Basis | Out-Null
Copy-Item (Join-Path $Repo "scripts\transport_client.example.toml") $Config -Force
notepad $Config

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

# Nach dem Bearbeiten ohne BOM normalisieren; TOML akzeptiert keinen BOM.
Write-Utf8NoBom $Config (Get-Content $Config -Raw)
```

In der Kopie vor dem ersten Lauf anpassen:

- `[endpoint].url` auf die freigegebene Abnahme-Serverinstanz,
- `[endpoint].key_id`,
- `[export].symbole` auf den echten Broker-Symbolnamen inklusive Suffix,
- `[export].server_zeitzone` oder `server_versatz_stunden` passend zum Broker,
- `[export].terminal_pfad` auf die lokale `terminal64.exe`,
- `[state].pfad` auf den **absoluten** Pfad `$State` mit Forward Slashes (z. B. `C:/Users/.../AppData/Local/Orakel/Abnahme/state`), nicht auf den Produktionsordner. Backslashes müssten in TOML verdoppelt werden.

Danach die Platzhalter prüfen; die Ausgabe muss leer sein:

```powershell
Select-String -Path $Config -Pattern 'orakel\.example','<Token','YOUR_TOKEN'
if (-not ((Get-Content $Config -Raw) -match [regex]::Escape($State.Replace('\','/')))) {
    throw "Der Zustandspfad in der TOML zeigt nicht auf den isolierten Abnahmezustand."
}
```

Token nur für die aktuelle PowerShell-Sitzung setzen:

```powershell
$env:ORAKEL_TRANSPORT_TOKEN = Read-Host -Prompt "Transport-Token (wird nicht angezeigt)"
if (($env:ORAKEL_TRANSPORT_TOKEN).Length -lt 32) { throw "Token ist kürzer als 32 Zeichen." }
```

### 1.1 Konfiguration prüfen

```powershell
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $Config --check-config
$code = $LASTEXITCODE
```

**Erwartung:** `$code -eq 0`; Ausgabe `Konfiguration gültig: ...`; keine MT5- oder HTTP-Aktion.

### 1.2 Leeren Testzustand anlegen

```powershell
Remove-Item -Recurse -Force $State -ErrorAction SilentlyContinue
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $Config --init-state
$code = $LASTEXITCODE
```

**Erwartung:** `$code -eq 0`; Ausgabe `Leerer Zustand angelegt: ...`; `state.json` und `status.json` existieren; `staging/` und `sent/` sind leer.

```powershell
$Status = Get-Content (Join-Path $State "status.json") -Raw | ConvertFrom-Json
$Status.status            # erwartet: erfolg
$Status.grund             # erwartet: null
$Status.details.hinweis   # erwartet: "leerer Zustand angelegt"
```

## 2. Scheduler nur trocken planen

Dieser Schritt registriert **keinen** Task. Der eindeutige Testname verhindert, dass ein vorhandener produktiver Task berührt wird.

```powershell
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "Abnahmetask existiert bereits; zuerst manuell prüfen. Kein Überschreiben."
}
& (Join-Path $Repo "scripts\windows_transport_task.ps1") `
    -Config $Config `
    -Python $Python `
    -TaskName $TaskName `
    -ServerZeitzone $ServerZone `
    -UploadStart $UploadStart `
    -WhatIf
$code = $LASTEXITCODE
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "ABBRUCH: -WhatIf hat einen Task registriert."
}
```

**Erwartung:**

- `$code -eq 0`.
- Ausgabe enthält: `Geplant: $UploadStart Serverzeit = <lokale Zeit> lokale Zeit; ...`.
- Die lokale Zeit entspricht der Umrechnung von `$UploadStart` Serverzeit am nächsten Server-Kalendertag; Abweichung von mehr als einer Minute ist ein Befund.
- `-ServerZeitzone` muss exakt zu `[export].server_zeitzone` in der TOML passen. Das Scheduler-Skript hat **keinen** Parameter für `server_versatz_stunden`; bei einem festen Broker-Versatz ist der Scheduler-Trockenlauf nicht möglich, und die Abnahme stoppt an dieser Stelle als Befund.
- `Get-ScheduledTask -TaskName $TaskName` liefert **kein** Objekt, weder vor noch nach dem Aufruf.
- Keine Task-XML, keine Task-ID und kein Eintrag in der Windows-Aufgabenplanung wird erzeugt.

Die tatsächlichen Task-Einstellungen (`StartWhenAvailable`, `IgnoreNew`, 15 Minuten, zwei Neustarts) sind durch den automatisierten Scheduler-Test abgedeckt. Eine reale Registrierung ist für diese Abnahme ausdrücklich ausgeschlossen.

## 3. Reale Strecke mit MT5 und Abnahme-Server

### A1 — Erstlauf mit gültigem Tagesblock

Voraussetzungen:

- Bootstrap-Marker für Symbol und Zeitrahmen ist auf der Abnahme-Serverinstanz gesetzt.
- Transport ist dort aktiviert; Token und Key-ID passen.
- MT5-Historie enthält den letzten abgeschlossenen Server-Handelstag.

```powershell
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $Config --once
$code = $LASTEXITCODE
```

**Erwartung:** `$code -eq 0`; `status.json` hat `status=erfolg`, `grund=null`, `details.codes=[0]`.

Zustand prüfen:

```powershell
$Status  = Get-Content (Join-Path $State "status.json") -Raw | ConvertFrom-Json
$Zustand = Get-Content (Join-Path $State "state.json") -Raw | ConvertFrom-Json

$Status | Format-List
$Zustand.uploads.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{
        Key    = $_.Name
        Status = $_.Value.status
        Grund  = $_.Value.grund
        Versuche = $_.Value.versuche
        HTTP   = $_.Value.http_status
        Code   = $_.Value.server_code
        Pfad   = $_.Value.staged_path
    }
} | Format-Table -AutoSize

Get-ChildItem (Join-Path $State "staging"),(Join-Path $State "sent") -ErrorAction SilentlyContinue
```

**Erwartete Werte im Upload-Record:**

- `status`: `erfolgreich` oder `erfolgreich_degraded`
- `grund`: `null`
- `http_status`: `200`
- `server_code`: `importiert` oder `bereits_vorhanden`
- `staged_path`: `sent/<SYMBOL>_<TF>_<JJJJMMTT>.csv`
- `sha256` entspricht dem SHA-256 der Datei unter `sent/`
- `versuche`: `1` oder `2` (bei einem echten Retry)

Dateiintegrität:

```powershell
$rec = ($Zustand.uploads.PSObject.Properties | Select-Object -First 1).Value
$datei = Join-Path $State $rec.staged_path
(Test-Path $datei) -and
((Get-FileHash $datei -Algorithm SHA256).Hash.ToLower() -eq $rec.sha256)
```

**Erwartung:** `True`; `staging/` enthält die erfolgreiche Datei nicht mehr.

Serverseitig muss der Ledger genau eine Buchung für diese Datei zeigen. Auf der Abnahme-Serverinstanz, DB- und Python-Pfad je nach Server-Betriebssystem anpassen:

```bash
.venv/bin/python -c "import sqlite3; c=sqlite3.connect('orakel.db'); print(c.execute('select id,datei,symbol,zeitrahmen,kerzen,bis,importiert_am from datenimporte order by id desc limit 3').fetchall())"
```

**Erwartung:** Auf einer frischen Abnahme-DB genau eine neue Buchung mit passendem Symbol, Zeitrahmen und `bis`-Datum; keine zusätzliche Buchung für einen anderen Tag. Ist derselbe SHA auf der Abnahme-DB bereits gebucht, ist `server_code=bereits_vorhanden` mit **unverändertem** Ledger ebenfalls bestanden; es darf dann keine zweite Zeile entstehen.

### A2 — Wiederholter Lauf ohne Duplikat

Gleiche Konfiguration und gleicher Testzustand, direkt danach:

```powershell
$vorher = (Get-Content (Join-Path $State "state.json") -Raw | ConvertFrom-Json).uploads.PSObject.Properties.Count
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $Config --once
$code = $LASTEXITCODE
$nachher = (Get-Content (Join-Path $State "state.json") -Raw | ConvertFrom-Json).uploads.PSObject.Properties.Count
```

**Erwartung:** `$code -eq 0`; `$nachher -eq $vorher`; keine neue `staging`-Datei; im Log steht `tag_bereits_erfolgreich`; der Server-Ledger bleibt unverändert. Ein erneuter HTTP-Upload derselben erfolgreichen Datei darf in diesem Lauf nicht stattfinden.

### A3 — Kontrollierter Serverfehler ohne Datenverlust

Für die echten HTTP-Klassifikationen zuerst die lokalen Netzwerkfälle aus Abschnitt 4 verwenden. Erst danach, falls die Abnahme-Serverinstanz einen kontrollierten Fehlerzustand anbieten kann, `409 bootstrap_erforderlich` oder `401` testen. Keine Tokens oder Server-Secrets in der Konsole ausgeben. Bei einem unerwarteten Server-Ledger-Eintrag abbrechen.

## 4. Netzwerk- und Retry-Fälle mit lokalem Stub

Die folgenden Fälle ersetzen nur den HTTP-Endpunkt. Der Export kommt weiterhin aus dem echten MT5; es wird **kein** Produktionsserver kontaktiert. Der Stub bindet ausschließlich an `127.0.0.1`.

### 4.1 Netzwerk-Testkonfiguration

```powershell
$NetzConfig = Join-Path $Basis "transport-netz.toml"
$NetzState  = Join-Path $Basis "state-netz"
$NetzText   = Get-Content $Config -Raw
$NetzText   = $NetzText -replace '(?m)^url = ".*"$', 'url = "http://127.0.0.1:18080/api/daten/import"'
$NetzText   = $NetzText -replace '(?m)^pfad = ".*"$', ('pfad = "' + ($NetzState.Replace('\','/')) + '"')
$NetzText   = $NetzText -replace '(?m)^timeout_sekunden = .*$', 'timeout_sekunden = 1'
$NetzText   = $NetzText -replace '(?m)^basis_sekunden = .*$', 'basis_sekunden = 0'
$NetzText   = $NetzText -replace '(?m)^jitter_sekunden = .*$', 'jitter_sekunden = 0'
$NetzText   = $NetzText -replace '(?m)^retry_after_max_sekunden = .*$', 'retry_after_max_sekunden = 1'
Write-Utf8NoBom $NetzConfig $NetzText

function Reset-NetzState {
    Remove-Item -Recurse -Force $NetzState -ErrorAction SilentlyContinue
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $NetzConfig --init-state
    if ($LASTEXITCODE -ne 0) { throw "init-state für Netzwerktest fehlgeschlagen." }
}
```

Die Werte `timeout_sekunden=1`, `basis_sekunden=0` und `retry_after_max_sekunden=1` gelten nur für die Abnahme. Sie verkürzen die Wartezeiten, ändern aber nicht die Retry-Klassifikation. Die echte Konfiguration bleibt bei den dokumentierten Werten.

### 4.2 Lokaler HTTP-Stub

Datei `%LOCALAPPDATA%\Orakel\Abnahme\abnahme_stub.py` anlegen:

```python
"""Nur für die manuelle Transport-Abnahme: Loopback-HTTP-Stub."""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    modus = "500"
    anfragen = 0

    def log_message(self, *_args):
        return

    def do_POST(self):
        Handler.anfragen += 1
        laenge = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(laenge)
        print(
            f"{time.strftime('%H:%M:%S')} ANFRAGE {Handler.anfragen} "
            f"modus={self.modus} bytes={len(body)} "
            f"request_id={self.headers.get('X-Orakel-Request-Id')}",
            flush=True,
        )
        if self.modus == "timeout":
            time.sleep(10)
            self.close_connection = True
            return
        if self.modus == "reset":
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()
            return

        status, code = {
            "500": (500, "server_500"),
            "507": (507, "server_507"),
            "429": (429, "server_429"),
            "409": (409, "import_belegt"),
            "401": (401, "token_ungueltig"),
            "503": (503, "transport_deaktiviert"),
            "400": (400, "hash_mismatch"),
            "ok": (200, "importiert"),
            "degraded": (200, "importiert"),
            "bereits": (200, "bereits_vorhanden"),
        }[self.modus]
        antwort = {
            "ok": status == 200,
            "code": code,
            "sha256": hashlib.sha256(body).hexdigest(),
            "warnungen": ["Teilwiederherstellung: Stub-Test"] if self.modus == "degraded" else [],
        }
        roh = json.dumps(antwort).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        if self.modus in {"429", "409"}:
            self.send_header("Retry-After", "1")
        self.end_headers()
        self.wfile.write(roh)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modus", required=True,
        choices=["500", "507", "429", "409", "401", "503", "400",
                 "ok", "degraded", "bereits", "timeout", "reset"],
    )
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    Handler.modus = args.modus
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"STUB {args.modus} auf 127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
```

Stub starten und beenden:

```powershell
$Stub  = Join-Path $Basis "abnahme_stub.py"
$StubLog = Join-Path $Basis "stub.log"
$StubErr = Join-Path $Basis "stub.err"
Remove-Item $StubLog,$StubErr -Force -ErrorAction SilentlyContinue

if (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 18080 ist bereits belegt; zuerst den anderen Prozess prüfen."
}
$stubArgumente = "`"$Stub`" --modus 500 --port 18080"
$p = Start-Process -FilePath $Python `
    -ArgumentList $stubArgumente `
    -RedirectStandardOutput $StubLog `
    -RedirectStandardError $StubErr `
    -PassThru -WindowStyle Hidden
Start-Sleep -Milliseconds 700
if ($p.HasExited) { throw "Stub startet nicht: $(Get-Content $StubErr -Raw)" }

try {
    # Hier den jeweiligen Client-Lauf ausführen.
} finally {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
}
```

Den Modus im Startbefehl für jeden Fall ersetzen. Nach jedem Lauf:

```powershell
$Status  = Get-Content (Join-Path $NetzState "status.json") -Raw | ConvertFrom-Json
$Zustand = Get-Content (Join-Path $NetzState "state.json") -Raw | ConvertFrom-Json
$Status | Format-List
$Zustand.uploads.PSObject.Properties | ForEach-Object {
    [pscustomobject]@{Key=$_.Name; Status=$_.Value.status; Grund=$_.Value.grund;
        Versuche=$_.Value.versuche; HTTP=$_.Value.http_status;
        Code=$_.Value.server_code; RequestId=$_.Value.request_id;
        Pfad=$_.Value.staged_path}
} | Format-Table -AutoSize
Get-Content $StubLog -ErrorAction SilentlyContinue
(Get-Content $StubLog | Select-String 'ANFRAGE').Count
```

### 4.3 Fälle

Für jeden Fall den Stub im angegebenen Modus starten, den Client mit `--once` ausführen und die Werte mit den Erwartungen vergleichen. Bei Zeitüberschreitung/Reset den Stub im `finally` beenden.

**Reihenfolge ist wichtig:** `state.json` bindet den Konfigurationshash. Bei N1/N2 die URL **vor** `Reset-NetzState` ändern; sonst meldet der Client `konfiguration` und Exit 3, statt den Netzwerkpfad zu testen. Nach N1/N2 die URL wieder auf `http://127.0.0.1:18080/api/daten/import` setzen und erneut `Reset-NetzState` ausführen.

```powershell
function Set-NetzUrl([string]$Url) {
    $t = Get-Content $NetzConfig -Raw
    $t = $t -replace '(?m)^url = ".*"$', ('url = "' + $Url + '"')
    Write-Utf8NoBom $NetzConfig $t
}
```

N1 und N2 konkret:

```powershell
# N1: Connection refused
if (Get-NetTCPConnection -LocalPort 18081 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 18081 ist belegt; N1 würde keinen Connection-refused-Fall testen."
}
Set-NetzUrl "http://127.0.0.1:18081/api/daten/import"
Reset-NetzState
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $NetzConfig --once
$code = $LASTEXITCODE
# Erwartung: 2; status.json transient; Upload wartend/netzwerk; 0 Stub-Requests

# N2: DNS
Set-NetzUrl "https://nicht-vorhanden.invalid/api/daten/import"
Reset-NetzState
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $NetzConfig --once
$code = $LASTEXITCODE
# Erwartung: 2; status.json transient; Upload wartend/netzwerk; 0 Stub-Requests

# Zurück auf den Stub-Endpunkt für N3–N14
Set-NetzUrl "http://127.0.0.1:18080/api/daten/import"
Reset-NetzState
```

| ID | Vorbereitung | Client-/Stub-Aufruf | Requests | Exit | `status.json` | Upload-Record |
|---|---|---|---:|---:|---|---|
| N1 | Port 18081 unbelegt; URL auf `http://127.0.0.1:18081/api/daten/import` | `--once` ohne Stub | 0 | 2 | `status=transient`, `grund=null`, `details.codes=[2]` | `status=wartend`, `grund=netzwerk`, `versuche=2`, `http_status=null` |
| N2 | URL auf `https://nicht-vorhanden.invalid/api/daten/import` | `--once` ohne Stub | 0 | 2 | wie N1 | wie N1 |
| N3 | Stub `--modus timeout` | `--once` | 2 | 2 | wie N1 | `wartend`, `netzwerk`, `versuche=2`; Laufzeit ca. 2 × Timeout |
| N4 | Stub `--modus reset` | `--once` | 2 | 2 | wie N1 | `wartend`, `netzwerk`, `versuche=2` |
| N5 | Stub `--modus 500` | `--once` | 2 | 2 | `status=transient`, `grund=null` | `wartend`, `grund=server_500`, `http_status=500`, `server_code=server_500`, `versuche=2` |
| N6 | Stub `--modus 507` | `--once` | 2 | 2 | wie N5 | `wartend`, `grund=server_507`, `http_status=507`, `versuche=2` |
| N7 | Stub `--modus 429` | `--once` | 2 | 2 | wie N5 | `wartend`, `grund=server_429`, `http_status=429`, `versuche=2`; zweiter Request mindestens 1 s später |
| N8 | Stub `--modus 409` | `--once` | 2 | 2 | wie N5 | `wartend`, `grund=import_belegt`, `http_status=409`, `versuche=2`; zweiter Request mindestens 1 s später |
| N9 | Stub `--modus 401` | `--once` | 1 | 3 | `status=blockiert`, `grund=auth`, `details` ohne `codes` (globaler Stopp) | `status=blockiert`, `grund=auth`, `http_status=401`, `server_code=auth`, `versuche=1` |
| N10 | Stub `--modus 503` | `--once` | 1 | 3 | `status=blockiert`, `grund=transport_deaktiviert` | `blockiert`, `grund=transport_deaktiviert`, `http_status=503`, `versuche=1` |
| N11 | Stub `--modus 400` | `--once` | 1 | 3 | `status=blockiert`, `grund=null` | `status=quarantaene`, `grund=hash_mismatch`, `staged_path=quarantine/...`; `.error.json` vorhanden |
| N12 | Stub `--modus ok` | `--once` | 1 | 0 | `status=erfolg`, `grund=null` | `status=erfolgreich`, `http_status=200`, `server_code=importiert`; Datei unter `sent/` |
| N13 | Stub `--modus degraded` | `--once` | 1 | 0 | `status=erfolg` | `status=erfolgreich_degraded`, Warnung enthält `Teilwiederherstellung` |
| N14 | Stub `--modus bereits` | `--once` | 1 | 0 | `status=erfolg` | `status=erfolgreich`, `server_code=bereits_vorhanden` |

**Wichtig:** `status=transient` mit `grund=null` ist korrekt; der konkrete Grund steht im Upload-Record. Bei N1/N2 sind die „Requests“ die zwei Verbindungsversuche des Clients; ein Server sieht davon nichts. Bei N11 wird die Datei nach `quarantine/` verschoben; bei N12/N13/N14 nach `sent/`.

### 4.4 Retry-Budget, Request-ID und Retry-After

Für 4.4 mit `Reset-NetzState` starten; die N5-Zeile aus 4.3 zählt nicht mit. Dann drei Läufe hintereinander ausführen (jeweils `--once`, ohne `Reset-NetzState`):

- Nach Lauf 1: `versuche=2`
- Nach Lauf 2: `versuche=4`
- Nach Lauf 3: `versuche=6`
- Lauf 4: Exit `3`, **kein weiterer Request**, Upload-Record `status=blockiert`, `grund=budget`

**Erwartung:** Der Stub hat insgesamt genau 6 Requests gesehen. Die Request-ID in allen Requests und im Upload-Record ist identisch. Bei N7/N8 muss zwischen den beiden Requests mindestens die in `Retry-After: 1` angegebene Sekunde liegen.

## 5. Fail-closed-Fälle ohne Serverkontakt

Diese Fälle prüfen, dass der Client bei beschädigtem Zustand, fehlender Konfiguration oder fehlendem Token **vor** MT5-Export und HTTP stoppt. Dafür einen eigenen Zustand verwenden:

```powershell
$FixConfig = Join-Path $Basis "transport-fix.toml"
$FixState  = Join-Path $Basis "state-fix"
$FixText   = Get-Content $NetzConfig -Raw
$FixText   = $FixText -replace '(?m)^pfad = ".*"$', ('pfad = "' + ($FixState.Replace('\','/')) + '"')
Write-Utf8NoBom $FixConfig $FixText

function Reset-FixState {
    Remove-Item -Recurse -Force $FixState -ErrorAction SilentlyContinue
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --init-state
    if ($LASTEXITCODE -ne 0) { throw "init-state für Fail-closed-Test fehlgeschlagen." }
}

function Start-LocalStub([string]$Modus) {
    Remove-Item $StubLog,$StubErr -Force -ErrorAction SilentlyContinue
    $stubArgumente = "`"$Stub`" --modus $Modus --port 18080"
    $prozess = Start-Process -FilePath $Python `
        -ArgumentList $stubArgumente `
        -RedirectStandardOutput $StubLog `
        -RedirectStandardError $StubErr `
        -PassThru -WindowStyle Hidden
    Start-Sleep -Milliseconds 700
    if ($prozess.HasExited) { throw "Stub startet nicht: $(Get-Content $StubErr -Raw)" }
    return $prozess
}

function Show-FixErgebnis {
    $s = Get-Content (Join-Path $FixState "status.json") -Raw | ConvertFrom-Json
    $z = Get-Content (Join-Path $FixState "state.json") -Raw | ConvertFrom-Json -ErrorAction SilentlyContinue
    [pscustomobject]@{Status=$s.status; Grund=$s.grund;
        Codes=($s.details.codes -join ','); Uploads=$z.uploads.PSObject.Properties.Count}
    Get-Content $StubLog -ErrorAction SilentlyContinue
    "Stub-Requests: " + ((Get-Content $StubLog -ErrorAction SilentlyContinue | Select-String 'ANFRAGE').Count)
}
```

### F1 — `state.json` fehlt, aber Staging-Datei vorhanden

```powershell
Remove-Item -Recurse -Force $FixState -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $FixState "staging") | Out-Null
Set-Content (Join-Path $FixState "staging\EURUSD_M15_20250102.csv") "kein gueltiger CSV-Inhalt"
$p = Start-LocalStub "ok"
try {
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
    $code = $LASTEXITCODE
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Show-FixErgebnis
```

**Erwartung:** Exit `5`; `status=state_reparatur_erforderlich`, `grund=state_fehlt`; **0** Stub-Requests; die Staging-Datei bleibt unverändert.

### F2 — Datei-Hash passt nicht zum Zustand

```powershell
Reset-FixState
$p = Start-LocalStub "500"
try { & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once } finally { Stop-Process -Id $p.Id -Force }
if ($LASTEXITCODE -ne 2) { throw "Vorbereitung für F2 fehlgeschlagen: erwartet Exit 2." }

$datei = Get-ChildItem (Join-Path $FixState "staging") -Filter "*.csv" | Select-Object -First 1
if (-not $datei) { throw "Keine Staging-Datei für F2 vorhanden." }
Add-Content $datei.FullName "X"

$p = Start-LocalStub "ok"
try {
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
    $code = $LASTEXITCODE
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Show-FixErgebnis
```

**Erwartung:** Exit `5`; `status=state_reparatur_erforderlich`, `grund=hash_mismatch`; **0** neue Stub-Requests; die Datei bleibt am Ort und wird nicht verändert.

### F3 — Sperrpfad nicht nutzbar

```powershell
Reset-FixState
Remove-Item -Force (Join-Path $FixState "lock") -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $FixState "lock") | Out-Null
$p = Start-LocalStub "ok"
try {
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
    $code = $LASTEXITCODE
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force (Join-Path $FixState "lock") -ErrorAction SilentlyContinue
Show-FixErgebnis
```

**Erwartung:** Exit `5`; `status=state_reparatur_erforderlich`, `grund=lock_fehler`; **0** Stub-Requests. Ein aktiver, aber gültiger Lock eines anderen Prozesses ist ein eigener Fall: Der Client beendet sich dann mit Exit `0` und `lauf_bereits_aktiv`; dieser Fall ist durch die automatisierten Sperrtests abgedeckt.

### F4 — `state.json` ist kein gültiges JSON

```powershell
Reset-FixState
Set-Content (Join-Path $FixState "state.json") "{kaputt"
$p = Start-LocalStub "ok"
try {
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
    $code = $LASTEXITCODE
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Show-FixErgebnis
```

**Erwartung:** Exit `5`; `status=state_reparatur_erforderlich`, `grund=state_unlesbar`; **0** Stub-Requests.

### F5 — Pflicht-Zeitzone fehlt

```powershell
$NoZone = Join-Path $Basis "transport-ohne-zone.toml"
$NoZoneText = (Get-Content $NetzConfig |
    Where-Object { $_ -notmatch '^\s*server_zeitzone\s*=' -and $_ -notmatch '^\s*server_versatz_stunden\s*=' }) -join "`r`n"
Write-Utf8NoBom $NoZone $NoZoneText
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $NoZone --check-config
$code = $LASTEXITCODE
```

**Erwartung:** Exit `3`; Fehlermeldung nennt `server_zeitzone`/`server_versatz_stunden`; keine MT5-/HTTP-Aktion. `--check-config` schreibt kein neues `status.json`.

### F6 — Token fehlt

```powershell
$savedToken = $env:ORAKEL_TRANSPORT_TOKEN
Remove-Item Env:\ORAKEL_TRANSPORT_TOKEN -ErrorAction SilentlyContinue
Reset-FixState
$p = Start-LocalStub "ok"
try {
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
    $code = $LASTEXITCODE
} finally {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    if ($savedToken) { $env:ORAKEL_TRANSPORT_TOKEN = $savedToken }
}
Show-FixErgebnis
```

**Erwartung:** Exit `3`; `status=blockiert`, `grund=auth`; **0** Stub-Requests. Der Token wird nicht ausgegeben.

### F7 — Zustand fehlt und keine Dateien vorhanden

```powershell
Remove-Item -Recurse -Force $FixState -ErrorAction SilentlyContinue
$p = Start-LocalStub "ok"
try {
    & $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
    $code = $LASTEXITCODE
} finally { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
Show-FixErgebnis
```

**Erwartung:** Exit `5`; `status=state_reparatur_erforderlich`, `grund=state_fehlt_init`; **0** Stub-Requests. Es wird kein Zustand automatisch angelegt.

### F8 — MT5 nicht verfügbar

MT5-Terminal schließen oder vorübergehend einen falschen `terminal_pfad` in einer Kopie der Konfiguration eintragen. Dann mit vorhandenem Testzustand:

```powershell
Reset-FixState
& $Python (Join-Path $Repo "scripts\transport_client.py") --config $FixConfig --once
$code = $LASTEXITCODE
$Status = Get-Content (Join-Path $FixState "status.json") -Raw | ConvertFrom-Json
```

**Erwartung:** Exit `4`; `status=mt5_nicht_verfuegbar`; `grund` ist `mt5_start` oder `mt5_fehlt`; keine HTTP-Anfrage. Danach MT5 wieder starten und anmelden.

## 6. Erwartete Status- und Exit-Werte

### 6.1 Exit-Codes

| Exit | Bedeutung | Typische Fälle |
|---:|---|---|
| `0` | Lauf erfolgreich, Tag bereits erfolgreich gebucht oder ein anderer Lauf hält den Lock | A1, A2, N12–N14, aktiver Lock |
| `2` | Transienter Fehler; Zustand bleibt für einen späteren Lauf offen | N1–N8 |
| `3` | Blockiert, Bedienerentscheidung, Auth-/Konfigurationsfehler | N9–N11, F5, F6 |
| `4` | MT5 nicht verfügbar oder Symbol nicht auswählbar | F8 |
| `5` | Zustand, Datei oder Lock fail-closed nicht nutzbar | F1–F4, F7 |
| `1` | Unerwarteter Laufzeitfehler; **Abnahme abbrechen** | jeder ungeplante Fall |

### 6.2 `status.json`

| `status` | `grund` | `details.codes` | Bedeutung |
|---|---|---|---|
| `erfolg` | `null` | `[0]` | Alle Serien erfolgreich oder bereits gebucht |
| `transient` | `null` | `[2]` | Mindestens eine Serie transient; konkreter Grund im Upload-Record |
| `blockiert` | `auth`, `transport_deaktiviert`, `bootstrap`, `daten_veraltet`, `server_409` oder `null` | `[3]` oder nicht vorhanden | Dauerhaft blockiert; bei globalem Stopp (`auth`, `transport_deaktiviert`) fehlt `details.codes`; bei `null` steht der Grund im Upload-Record |
| `mt5_nicht_verfuegbar` | `mt5_start`, `mt5_fehlt`, `mt5_symbol` | nicht vorhanden | MT5-Phase fehlgeschlagen |
| `state_reparatur_erforderlich` | `state_fehlt`, `state_fehlt_init`, `state_unlesbar`, `hash_mismatch`, `datei_fehlt`, `lock_fehler`, … | nicht vorhanden | Zustand ist nicht sicher nutzbar |

`details.codes` ist die Liste der Serien-Ergebnisse. Ein einzelner blockierter Fall kann daher `status=blockiert` mit `codes=[3]` erzeugen, während ein transienter Lauf `status=transient` mit `codes=[2]` und `grund=null` hat.

### 6.3 Upload-Record in `state.json`

| Feld | Erwartung |
|---|---|
| `status` | `vorbereitet`, `wartend`, `erfolgreich`, `erfolgreich_degraded`, `blockiert` oder `quarantaene` |
| `grund` | Bei transient/blockiert der konkrete Grund, z. B. `netzwerk`, `server_500`, `server_429`, `import_belegt`, `auth`, `transport_deaktiviert`, `hash_mismatch`, `budget` |
| `versuche` | Pro Lauf höchstens `http_versuche`, insgesamt höchstens `6` |
| `http_status` | Bei Netzwerkfehlern `null`; sonst der tatsächliche HTTP-Status |
| `server_code` | Der Server- oder Klassifikationscode, z. B. `importiert`, `bereits_vorhanden`, `server_500`, `auth` |
| `request_id` | Über alle Retries desselben Uploads identisch |
| `staged_path` | `staging/...`, nach Erfolg `sent/...`, nach Quarantäne `quarantine/...` |
| `letzte_kerze` | ISO-Zeitstempel der letzten Kerze; bei Fail-closed-Fällen unverändert |

## 7. Abbruchkriterien

Die Abnahme wird **sofort abgebrochen**, wenn einer der folgenden Punkte eintritt. Keine „schnelle Reparatur“ im Testzustand; zuerst Evidenz sichern und den Befund dokumentieren.

1. **Secret-Leak:** Token, Key-ID oder ein anderer geheimer Wert erscheint in der TOML, in `state.json`, `status.json`, `logs/`, einer Prozessliste, einem Screenshot oder der Chat-/Terminalausgabe.
2. **Task-Registrierung:** `Get-ScheduledTask -TaskName $TaskName` liefert vor oder nach `-WhatIf` ein Objekt; oder die Aufgabenplanung zeigt den Testtask. Der Test wird nicht durch Löschen „bereinigt“, sondern abgebrochen und der Befund gesichert.
3. **Fail-closed verletzt:** F1–F4 und F7 erzeugen einen Stub-Request größer als `0`, exportieren eine neue Datei, verschieben eine Datei oder verändern den Zustand trotz erwartetem Exit `5`. F5 und F6 erzeugen trotz erwartetem Exit `3` einen HTTP-Request oder eine MT5-Aktion.
4. **Falscher Server:** Es wurde versehentlich eine Produktionsinstanz kontaktiert oder der Server-Ledger enthält eine unerwartete Buchung. Abnahme-Server und Produktionsserver müssen eindeutig getrennt sein.
5. **Exit/Status-Mismatch:** Exit-Code, `status`, `grund`, `details.codes` oder Upload-Record weichen von der Tabelle ab.
6. **Retry-Verletzung:** Mehr als zwei Requests pro Lauf, mehr als sechs insgesamt, ein geänderter `request_id` innerhalb derselben Datei oder ein fehlender `Retry-After`-Abstand.
7. **Datenverlust:** Nach Erfolg fehlt die Datei unter `sent/`, der SHA-256 stimmt nicht, oder eine Staging-Datei wurde ohne Quarantäne-/Erfolgsstatus entfernt.
8. **Falscher Datenblock:** Symbol, Zeitrahmen, Handelstag oder `bis`-Datum passen nicht zur MT5-Historie bzw. zum Server-Ledger.
9. **MT5-Grenze:** MT5 ist nicht angemeldet, das Symbol fehlt im Market Watch, der letzte Tagesblock ist unvollständig oder die Zeitumrechnung weicht um mehr als eine Minute ab.
10. **Scheduler:** `-WhatIf` liefert eine unerwartete lokale Zeit, eine andere Task-Aktion als der Python-Aufruf oder eine Task-XML mit Token; oder der Scheduler-Aufruf endet ungleich `0`.
11. **Unbehandelte Ausnahme:** Traceback, unerwarteter Exit `1`, fehlende `status.json` nach einem Lauf oder ein nicht klassifizierter HTTP-Status.
12. **Fremde Dateien:** Der Test hat Dateien außerhalb von `%LOCALAPPDATA%\Orakel\Abnahme` verändert, insbesondere den produktiven State, `sent/` oder die Aufgabenplanung.

## 8. Evidenz und Abschluss

### 8.1 Während der Abnahme sichern

Den Transcript am besten **vor dem ersten Lauf** starten; der folgende Block ist die Vorlage. Er darf keine Token-Werte enthalten.

```powershell
Start-Transcript -Path (Join-Path $Basis "abnahme-transcript.txt")
# Abnahme ausführen; keine Token-Werte ausgeben.
Stop-Transcript
```

Pro Fall zusätzlich kopieren:

- `status.json` und `state.json` **vor und nach** dem Lauf,
- `logs/transport.jsonl`,
- Stub-Log mit Request-Zeitstempeln und `request_id`,
- die erzeugte CSV unter `sent/` bzw. `quarantine/` und deren SHA-256,
- die Ausgabe des `-WhatIf`-Laufs,
- das Ergebnis der Server-Ledger-Abfrage.

### 8.2 Evidenztabelle

| ID | Datum/Zeit | Exit | `status` | Upload-Record | Requests | Datei-SHA-256 | Ergebnis / Abweichung |
|---|---|---:|---|---|---:|---|---|
| Setup | | 0 | `erfolg` | — | 0 | — | |
| Scheduler | | 0 | — | — | 0 | — | |
| A1 | | 0 | `erfolg` | `erfolgreich`, HTTP 200 | 1 | | |
| A2 | | 0 | `erfolg` | unverändert | 0 | | |
| N1 | | 2 | `transient` | `wartend`, `netzwerk` | 0 | — | |
| N2 | | 2 | `transient` | `wartend`, `netzwerk` | 0 | — | |
| N3 | | 2 | `transient` | `wartend`, `netzwerk` | 2 | — | |
| N4 | | 2 | `transient` | `wartend`, `netzwerk` | 2 | — | |
| N5 | | 2 | `transient` | `wartend`, `server_500` | 2 | — | |
| N6 | | 2 | `transient` | `wartend`, `server_507` | 2 | — | |
| N7 | | 2 | `transient` | `wartend`, `server_429` | 2 | — | |
| N8 | | 2 | `transient` | `wartend`, `import_belegt` | 2 | — | |
| N9 | | 3 | `blockiert` | `blockiert`, `auth` | 1 | — | |
| N10 | | 3 | `blockiert` | `blockiert`, `transport_deaktiviert` | 1 | — | |
| N11 | | 3 | `blockiert` | `quarantaene`, `hash_mismatch` | 1 | — | |
| N12 | | 0 | `erfolg` | `erfolgreich` | 1 | | |
| N13 | | 0 | `erfolg` | `erfolgreich_degraded` | 1 | | |
| N14 | | 0 | `erfolg` | `erfolgreich`, `bereits_vorhanden` | 1 | | |
| F1–F4, F7 | | 5 | `state_reparatur_erforderlich` | — | 0 | — | |
| F5 | | 3 | — (nur `--check-config`) | — | 0 | — | |
| F6 | | 3 | `blockiert` | — | 0 | — | |
| F8 | | 4 | `mt5_nicht_verfuegbar` | — | 0 | — | |

### 8.3 Abschlussregel

```powershell
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw "ABBRUCH: Ein Task mit dem Abnahmenamen existiert."
}
"Kein Abnahmetask registriert."
```

Die Abnahme gilt nur als bestanden, wenn:

- alle Zeilen der Evidenztabelle mit den erwarteten Werten gefüllt sind,
- kein Abbruchkriterium aus Abschnitt 7 ausgelöst wurde,
- der Testtask nachweislich **nicht** existiert,
- der Server-Ledger den erwarteten A1-Eintrag enthält (neu oder `bereits_vorhanden`) und A2 keine zweite Buchung erzeugt hat,
- die reale Strecke A1/A2 auf der freigegebenen Abnahme-Serverinstanz erfolgreich war.

Nicht bestanden ist die Abnahme insbesondere dann, wenn nur die automatisierten Tests grün sind, aber kein realer MT5-Export und kein echter Upload auf der Abnahme-Serverinstanz stattfand. Die automatisierte CI kann die Windows-/MT5-Hardwareabnahme nicht ersetzen.

## 9. Automatisiert geprüft vs. manuell offen

**Bereits automatisiert geprüft (PR #302, Stand `ed8d31c`):** 797 Tests gesamt, 29 fokussierte Transport-/State-Tests, Ruff auf den geänderten Python-Dateien, Doku-Prüfung und `git diff --check`; CI mit 25/25 erfolgreichen Check-Runs.

**Diese Checkliste muss noch manuell auf echter Windows-/MT5-Hardware durchgeführt werden.** Der reale Broker-Export, die lokale MT5-Installation, der echte Abnahme-Server und die Windows-Aufgabenplanung sind nicht durch die CI abgedeckt. Ein Scheduled Task wurde für diese Checkliste **nicht registriert**; der Scheduler wird ausschließlich mit `-WhatIf` geprüft.
