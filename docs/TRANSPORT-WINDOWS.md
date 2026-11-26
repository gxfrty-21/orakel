# Windows-Client und Scheduler für den Datentransport

Der Windows-Rechner lädt nach dem Handelsschluss genau einen abgeschlossenen
MT5-Server-Kalendertag über `POST /api/daten/import` hoch. Der Server bleibt die
Wahrheit: Er prüft Bootstrap-Marker, Hash, Datenqualität und Frische und führt
Kerzen und Ledger in einer Transaktion. Der Client ist kein Broker-Zugang und
erzeugt keine Order; das Projekt bleibt Paper-only.

Die verbindlichen Grenzen stehen in [AGENTS.md](../AGENTS.md) und in der
[Transportdokumentation des Servers](../README.md#automatischer-https-transport-zum-server).
Dieses Dokument beschreibt nur die Windows-Inbetriebnahme.

## Voraussetzungen

- Windows 10 oder Windows Server 2016 oder neuer (wegen `RestartCount`).
- 64-Bit-Python 3.12 im venv, mit `MetaTrader5` aus dem Windows-Paket.
- Ein laufendes, angemeldetes MT5-Terminal mit dem konfigurierten Symbol im
  Market Watch. Der Client startet MT5 nicht selbst.
- Ein dediziertes lokales Standardbenutzerkonto, unter dem MT5 angemeldet ist.
  Kein SYSTEM, kein Dienstkonto und kein gespeichertes Kontopasswort.
- Der Server-Transport ist aktiviert und der Bootstrap-Marker wurde serverseitig
  gesetzt (siehe README).

## Dateien

| Datei | Zweck |
|---|---|
| `scripts/transport_client.py` | eigenständiger Client, ein Lauf mit `--once` |
| `scripts/transport_client.example.toml` | Beispielkonfiguration ohne Secrets |
| `scripts/windows_transport_task.ps1` | Installer/Deinstaller des Tasks |
| `tests/test_transport_client.py` | Export-, HTTP- und Retry-Tests |
| `tests/test_transport_client_state.py` | Fail-closed- und Neustarttests |

## Konfiguration

Die Beispielkonfiguration nach `%LOCALAPPDATA%\Orakel\Transport\transport.toml`
kopieren und anpassen. Wichtig sind die tatsächlichen Broker-Symbolnamen
(inklusive Suffix), die Serverzeitzone und die Mindestzahl Kerzen pro Tag.

```toml
[endpoint]
url = "https://orakel.example/api/daten/import"
key_id = "windows-1"
token_env = "ORAKEL_TRANSPORT_TOKEN"

[export]
symbole = ["EURUSD"]
zeitrahmen = ["M15"]
server_zeitzone = "Europe/Athens"
terminal_pfad = "C:/Program Files/MetaTrader 5/terminal64.exe"
min_kerzen_pro_tag = { M15 = 90, H1 = 20 }
max_alter_stunden = { M15 = 4, H1 = 24 }

[state]
pfad = "%LOCALAPPDATA%/Orakel/Transport"

[retry]
http_versuche = 2
basis_sekunden = 60
retry_after_max_sekunden = 120
jitter_sekunden = 2
```

Regeln:

- Nur HTTPS; `http://127.0.0.1` ist ausschliesslich für lokale Tests erlaubt.
- Der Token steht **nicht** in der TOML. Er kommt aus der Umgebungsvariable, die
  im Konto des Tasks gesetzt ist; die Beispielkonfiguration nennt nur den Namen.
- `M15` muss immer enthalten sein. `H1` nur ergänzen, wenn der serverseitige
  Richter-Zeitrahmen `H1` ist.
- `server_zeitzone` und `server_versatz_stunden` schliessen sich aus. Die Werte
  müssen zur Serverkonfiguration passen; eine Änderung erzeugt einen neuen
  Konfigurationsfingerabdruck und blockiert den alten lokalen Zustand. Genau
  einer der beiden Werte ist Pflicht; der Client rät keine Zeitzone.
- Die Mindestzahlen sind eine lokale Vorprüfung. Die endgültige Entscheidung
  bleibt beim Server.

## Einrichtung

1. Im venv `MetaTrader5` installieren (nur Windows, 64-Bit):

   ```powershell
   .\venv\Scripts\python.exe -m pip install MetaTrader5
   ```

2. Token im Task-Konto als Benutzerumgebungsvariable setzen. Nicht in eine
   Datei im Repository schreiben und nicht als Task-Argument übergeben:

   ```powershell
   [Environment]::SetEnvironmentVariable(
       "ORAKEL_TRANSPORT_TOKEN", "<Token aus dem Server-Secret>", "User")
   ```

3. Konfiguration prüfen, ohne MT5 oder HTTP zu starten:

   ```powershell
   .\venv\Scripts\python.exe scripts\transport_client.py `
       --config "$env:LOCALAPPDATA\Orakel\Transport\transport.toml" --check-config
   ```

4. Einmalig den leeren lokalen Zustand anlegen. Das ist nur erlaubt, wenn
   `staging/` und `sent/` leer sind. Der Befehl lädt nichts hoch:

   ```powershell
   .\venv\Scripts\python.exe scripts\transport_client.py `
       --config "$env:LOCALAPPDATA\Orakel\Transport\transport.toml" --init-state
   ```

5. Vor dem Scheduler einen manuellen Lauf mit `--once` ausführen und Log sowie
   `status.json` prüfen. Der Server-Bootstrap muss bereits gesetzt sein.

6. Task zunächst mit `-WhatIf` planen, dann registrieren:

   ```powershell
   .\scripts\windows_transport_task.ps1 -Config "$env:LOCALAPPDATA\Orakel\Transport\transport.toml" `
       -Python ".\venv\Scripts\python.exe" -ServerZeitzone "Europe/Athens" -UploadStart "00:15" -WhatIf

   .\scripts\windows_transport_task.ps1 -Config "$env:LOCALAPPDATA\Orakel\Transport\transport.toml" `
       -Python ".\venv\Scripts\python.exe" -ServerZeitzone "Europe/Athens" -UploadStart "00:15"
   ```

   Windows PowerShell 5.1 kennt nicht alle IANA-Zonen. Der Installer übersetzt
   die dokumentierten Zonen `Europe/Athens`, `Europe/Berlin`, `Europe/Zurich`,
   `Europe/Vienna` und `UTC`; alternativ eine Windows-Zeitzonen-ID übergeben.
   `-ServerZeitzone` muss zu `server_zeitzone` in der TOML passen; der Installer
   liest die TOML nicht.

7. Task entfernen:

   ```powershell
   .\scripts\windows_transport_task.ps1 -Remove
   ```

## Task-Scheduler

Der Installer registriert:

- einen täglichen Trigger zu `-UploadStart`, umgerechnet in lokale
  Windows-Zeit,
- `StartWhenAvailable` für einen verpassten Lauf nach Login oder Boot,
- `MultipleInstances = IgnoreNew`,
- ein Ausführungslimit von 15 Minuten,
- höchstens zwei native Neustarts im Abstand von 30 Minuten.

Der Task läuft nur bei angemeldetem Benutzer. Ist das Konto abgemeldet, läuft
nichts; `StartWhenAvailable` holt den Lauf nach dem nächsten Login nach, sofern
der Block noch frisch ist. Ein gesperrter Desktop ist zulässig. Auto-Login ist
optional und nur mit BitLocker/TPM und kontrolliertem physischem Zugang sinnvoll.

Der Client schläft nie über Minuten und plant keine eigenen Retry-Timer. Die
HTTP-Ebene hat höchstens zwei Versuche pro Lauf; die Scheduler-Ebene höchstens
zwei folgenlose Restarts. Jeder Versuch sendet denselben Hash.

## Zustand und Fail-closed

Der Zustandsordner enthält:

```text
%LOCALAPPDATA%\Orakel\Transport\
  state.json
  state.json.bak
  status.json
  lock
  staging\
  sent\
  quarantine\
  logs\
```

`state.json` wird über `state.json.tmp` und `os.replace` atomar ersetzt;
`state.json.bak` ist die letzte gültige Sicherung. Der Server-Ledger bleibt die
Wahrheit, der lokale Zustand ist nur ein Intent-Journal.

Bei folgenden Befunden wird **kein HTTP-Request und kein neuer MT5-Export**
ausgeführt:

- `state.json` fehlt oder ist unlesbar, während `staging/` oder `sent/` eine
  Datei enthält,
- die Sperrdatei nicht geöffnet oder gesperrt werden kann (`lock_fehler`),
- der SHA-256 einer Staging- oder Sent-Datei weicht vom Zustand ab,
- eine im Zustand referenzierte offene Datei fehlt.

Der Lauf endet mit Exit 5, schreibt `status=state_reparatur_erforderlich` und
den Grund (`state_fehlt`, `state_unlesbar`, `hash_mismatch`, `datei_fehlt`,
`lock_fehler`) in `status.json`. `.bak` wird **nicht automatisch** übernommen
und Dateien werden nicht automatisch verschoben oder gelöscht.

### Bedieneraktion bei Fail-closed

1. Task deaktivieren, damit keine weiteren No-Op-Läufe starten.
2. `state.json`, `.bak`, `status.json`, Logs und die betroffenen Dateien sichern.
3. Im serverseitigen Ledger (DB/CLI) prüfen, ob die Datei bereits gebucht ist.
4. `.bak` nur übernehmen, wenn sie gültig ist, zum aktuellen Schema und
   Konfigurationsfingerabdruck passt, alle Datei-Hashes bestätigt und der
   Server-Ledger die Einträge deckt.
5. Bei einem Hash-Mismatch die Datei als beschädigt behandeln und nicht senden.
   Ist der alte Hash serverseitig gebucht, den lokalen Status auf die
   Serverwahrheit zurücksetzen; sonst die Datei nach
   `quarantine/manual_<zeitstempel>/` verschieben und keinen neuen Export
   automatisch starten.
6. Ohne sichere Rekonstruktion alle verwaisten Dateien nach
   `quarantine/manual_<zeitstempel>/` verschieben und einen leeren Zustand nur
   mit ausdrücklicher Freigabe über `--init-state` anlegen.
7. Erst nach einem manuellen `--once`-Testlauf den Task wieder aktivieren und den
   Vorfall im Log dokumentieren.

Sind `staging/` und `sent/` leer, verlangt der Client trotzdem eine bewusste
Initialisierung mit `--init-state`; ein fehlender Zustand wird nie stillschweigend
als leerer Zustand behandelt.

## Exit-Codes

| Code | Bedeutung |
|---|---|
| `0` | Erfolg, bereits erledigt oder Lauf bereits aktiv |
| `2` | transient; Scheduler darf erneut starten |
| `3` | Bedienerentscheidung nötig (Bootstrap, veraltet, Auth, Konfiguration) |
| `4` | MT5 nicht verfügbar oder keine Daten |
| `5` | lokaler Zustand oder Lock beschädigt; Fail-closed |

## HTTP-Klassifikation

- `200 importiert`: Erfolg.
- `200 bereits_vorhanden`: idempotenter Erfolg.
- `200` mit Warnung `Teilwiederherstellung`: Erfolg für den Block, Status
  `erfolgreich_degraded`; der Bootstrap-Marker bleibt ungültig.
- `409 bootstrap_erforderlich`: blockiert, kein automatischer Bootstrap.
- `409 daten_veraltet`: blockiert, kein Retry.
- `409 import_belegt`: genau ein Retry mit `Retry-After` (maximal 120 s).
- `400`/`413`/`415`/`401`/`403`/`503 transport_deaktiviert`: blockiert oder
  Quarantäne; kein blinder Retry.
- `500`/`507`/Netzwerkfehler: höchstens zwei Versuche, danach `wartend`.

Der Authorization-Header und der Token werden nicht in `state.json`,
`status.json` oder Logs geschrieben.

## Diagnose

```powershell
Get-ScheduledTask -TaskName "Orakel Transport"
Get-ScheduledTaskInfo -TaskName "Orakel Transport"
Get-Content "$env:LOCALAPPDATA\Orakel\Transport\status.json"
Get-Content "$env:LOCALAPPDATA\Orakel\Transport\logs\transport.jsonl" -Tail 50
```

## Grenzen

- Die automatisierte Prüfung deckt den Client mit Fake-MT5 und injiziertem
  HTTP-Transport ab. Ein echter Lauf mit dem Broker-Terminal, Task Scheduler
  nach Reboot, Netzwerkausfall und ein vollständiger Bootstrap-Zyklus bleiben
  eine manuelle Windows-Abnahme.
- Ein verpasster Tag kann nach Ablauf der Frischegrenze nicht als neuer
  Delta-Upload nachgeholt werden. Exakt gebuchte Altblöcke nur im Rahmen der
  serverseitigen Ledger-Reparatur wieder einspielen.
- Der Client startet MT5 nicht und speichert kein Kontopasswort.
- Die Aufbewahrung löscht nur abgelaufene `sent/`-, `quarantine/`- und Logdateien.
  Den Zustand selbst löscht der Client nicht automatisch.