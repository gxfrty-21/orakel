# Orakel auf Railway

Railway-Variante ohne eigenen Server, ohne Caddy und ohne eigene Domain.
Railway baut den vorhandenen `Dockerfile`, stellt TLS und eine
`*.up.railway.app`-Adresse bereit. SQLite, Vault und Daten liegen im
persistenten Volume unter `/data`.

Das Projekt bleibt **Paper-Trading**. Es gibt keinen Codepfad zu einer echten
Broker-Order.

## Aktueller Stand

Deployed am 8. November 2026:

- Dashboard: <https://orakel-production-fb18.up.railway.app>
- Projekt: `orakel` (`565cd49f-e067-415b-aa3a-5680557fedd9`)
- Environment: `production` (`97106b8a-7ff8-4285-a30e-e8309da409fd`)
- Service: `orakel` (`1f8e2304-31d5-4c7e-80b3-8010ee2d969e`)
- Volume: `orakel-volume` (`241709d8-4eb6-40c9-8163-a28edb58b3ed`),
  Mount `/data`, 500 MB
- Letztes Deployment: `0c6a45b6-9c0f-4ea7-94d8-db6b89d5eeda` — `SUCCESS`
  (Build aus dem Workspace mit Seed-Schritt; Zeitfilter 24 h / 7 Tage / 30 Tage
  für Graph und Aktivität)
- Domain: Target Port `3000`, TLS von Railway
- Graph-API: `/api/globe?zeitraum=24h|7d|30d`; ungültige Werte fallen auf `24h`
  zurück. Der Markt-Snapshot bleibt die aktuelle Live-Ansicht.

Der Login-Benutzer ist `orakel`. Das generierte Passwort steht in Railway
unter `ORAKEL_AUTH_PASS`; es ist absichtlich nicht im Repository und nicht in
dieser Anleitung. Nach dem ersten Login ein eigenes Passwort setzen.

Geprüft: `/api/health` → 200, `/` ohne Login → 401.

### Warum das Volume leer war

Der `Dockerfile` kopiert nur `orakel/` und `config.toml` ins Image. Die lokale
`orakel.db` ist per `.gitignore` vom Build ausgeschlossen, und
`docker-entrypoint.sh` legt nur `/data/daten` und `/data/vault` an. Beim ersten
Start hat die App deshalb eine neue, leere SQLite-Datei erzeugt (135.168
Bytes). Es gab keinen Seed- oder Import-Schritt — das Volume war nie befüllt.

### Wiederherstellung (8. November 2026)

Die lokalen Daten wurden bei gestopptem Dienst eingespielt:

1. Deployment über `deploymentStop` gestoppt; `/api/health` antwortete mit 502.
2. Lokale `orakel.db` (15.626.240 Bytes) nach `/orakel.db.neu` hochgeladen und
   `vault/` (44 Markdown-Notizen) nach `/vault`.
3. Im Container getauscht: die leere DB als `/orakel.db.leer-2026-11-08`
   gesichert, `/orakel.db.neu` nach `/orakel.db` umbenannt.
4. Deployment neu gestartet.

Ergebnis: `artikel: 34`, `integrity_check: ok`, 28.086 Trades, 480
Agentenläufe, 144 Validierungen, 44 Vault-Notizen. Die leere Originaldatei
bleibt als `/orakel.db.leer-2026-11-08` auf dem Volume; die Sicherungen liegen
unter `artifacts/railway-volume-backup/`.

Hinweis: Der Volume-Dateizugriff (`railway volume files`) läuft über die
laufende Instanz. Bei gestopptem Dienst bricht er mit `Failed to initialize
SFTP session` ab — deshalb wird zuerst neu deployt und dann auf einen
separaten Pfad hochgeladen und im Container getauscht.

### Seed beim Erststart

Das Image enthält eine Seed-DB unter `/app/seed/orakel-seed.db` (`COPY seed`
im `Dockerfile`). `docker-entrypoint.sh` ruft vor dem Serverstart
`python -m orakel.seed` auf. Der Schritt importiert nur, wenn die Zieldatei
fehlt oder keine Kerndaten enthält; vorhandene Daten bleiben unangetastet, eine
alte leere DB wird als `orakel.db.leer-<zeitstempel>` gesichert. Bei
beschädigtem Ziel oder fehlendem Seed läuft der Start unverändert weiter,
allerdings mit deutlicher Logzeile.

Der Seed wird nicht automatisch aktuell gehalten — nach größeren Datenständen
neu bauen (siehe `seed/README.md`) und deployen. Ob er gegriffen hat, zeigt
`railway logs`: `orakel-seed: Seed orakel-seed.db (...) importiert ...` oder
`orakel-seed: ... enthält Daten ... – nichts importiert`.

Im Deployment `0c6a45b6` geprüft: Der Startlog meldet für die bestehende DB
`enthält Daten (artikel=34, …) – nichts importiert`; ein Import auf einem
Scratch-Pfad im Container (`/data/seed-probe`, danach gelöscht) ergab
`integrity ok`, 34 Artikel, 28.086 Trades, `user_version 1`, keine
`seed-tmp`-Reste, und ein zweiter Lauf importierte nichts. Die Produktions-DB
blieb bei 34 Artikeln/28.086 Trades.

## Unterschiede zur VPS-Variante

- Kein Caddy, kein Reverse Proxy, keine Ports 80/443.
- Keine DNS-Einträge und keine Domain; die Railway-Adresse reicht.
- Ein Service, ein Volume, **eine Instanz**. SQLite darf nicht horizontal
  skaliert werden.
- TLS und öffentliche URL kommen von Railway.
- Der Container hört auf `PORT`; der Healthcheck nutzt denselben Port.

## Wichtig: `railway.json` ist Legacy

`railway.json` liegt im Projekt, weil es für diese Variante angefordert wurde.
Railway hat **Config as Code** (`railway.json` / `railway.toml`) aber
abgekündigt:

- Neue Services können es nicht mehr aktivieren.
- Bestehende Dateien werden ab **1. Dezember 2026** nicht mehr gelesen.
- Für einen neuen Service gelten die Einstellungen im Dashboard bzw. die
  CLI-Befehle unten.

Die Datei bleibt als Dokumentation und für bestehende Legacy-Services. Für
einen neuen Railway-Service ist sie nicht die Quelle der Wahrheit.

## Voraussetzungen

- Railway-Konto
- Repository bei GitHub (oder Railway CLI, um diesen Ordner hochzuladen)
- Keine Domain, kein Docker-Server und kein Caddy

## Einrichten über das Dashboard

1. **Projekt anlegen:** Railway → New Project → Deploy from GitHub repo →
   Repository auswählen. Railway erkennt den `Dockerfile` automatisch.
2. **Volume:** Im Projekt-Canvas ein Volume hinzufügen, mit dem Service
   verbinden und als **Mount Path** `/data` setzen. Name z. B. `orakel-data`.
3. **Variablen** (Service → Variables):

   | Variable | Wert |
   |---|---|
   | `ORAKEL_AUTH_USER` | Benutzername für das Dashboard |
   | `ORAKEL_AUTH_PASS` | starkes Passwort, als Secret/Sealed markieren |
   | `ORAKEL_DATA` | `/data` |
   | `ORAKEL_TAKT` | `0` (kein Hintergrund-Takt) |
   | `PORT` | `3000` |
   | `RAILWAY_RUN_UID` | `0` (siehe Sicherheit) |

   `ORAKEL_AUTH_USER` und `ORAKEL_AUTH_PASS` müssen **beide** gesetzt sein.
   Fehlen sie, startet die App ohne Login-Schutz. Vor dem ersten Deploy
   setzen.

4. **Settings:**
   - Healthcheck Path: `/api/health`
   - Restart Policy: `Always`
   - Replicas: `1`
   - Sleeping: aus (falls der Plan die Option anzeigt)

5. **Networking:** Generate Domain. Target Port `3000` prüfen. Railway kann
   den Port automatisch erkennen; mit `PORT=3000` ist er eindeutig.

6. **Deploy** und Logs prüfen. Danach testen:

   ```bash
   curl -i https://DEINE-ADRESSE.up.railway.app/api/health   # 200, ohne Login
   curl -i https://DEINE-ADRESSE.up.railway.app/              # 401, ohne Login
   curl -iu BENUTZER:PASSWORT https://DEINE-ADRESSE.up.railway.app/  # 200
   ```

## Einrichten über die CLI

```bash
npm i -g @railway/cli
railway login
railway init
railway up
railway volume add --mount-path /data
```

Variablen setzen (Passwort separat und nicht in der Shell-History):

```bash
railway variable set \
  ORAKEL_AUTH_USER=orakel \
  ORAKEL_DATA=/data \
  ORAKEL_TAKT=0 \
  PORT=3000 \
  RAILWAY_RUN_UID=0
```

Das Passwort im Dashboard als Sealed Variable setzen oder lokal über
`railway variable set ORAKEL_AUTH_PASS --stdin` einlesen. Danach im Dashboard
unter Networking eine Domain erzeugen und den Target Port auf `3000` prüfen.

## Bestehende Daten übernehmen

Die App vorher stoppen, damit SQLite keine offene WAL-Datei hat. Dann die
Dateien in das Volume hochladen:

```bash
railway volume files upload ./orakel.db /orakel.db
railway volume files upload ./vault /vault
railway volume files upload ./daten /daten
```

Alternativ `railway volume browse /` für den interaktiven Upload verwenden.
Nach dem Start im Dashboard prüfen, ob die bisherigen Aufträge und Artikel
sichtbar sind. Die lokale `orakel.db` ist per `.gitignore` vom Repository
ausgeschlossen und wird nicht mitgebaut.

## Backup und Wiederherstellung

Bei gestopptem Service:

```bash
mkdir -p backups
railway volume files download /orakel.db ./backups/orakel.db
railway volume files download /vault ./backups/vault
railway volume files download /daten ./backups/daten
```

Zurückspielen entsprechend mit `railway volume files upload`. Railway bietet
für Volumes zusätzlich eigene Backups an; die Verfügbarkeit hängt vom Plan ab.

## Sicherheit

- Basic-Auth nur über HTTPS. Railway liefert TLS für die
  `*.up.railway.app`-Adresse.
- `/api/health` ist absichtlich ohne Login erreichbar und nennt nur
  Laufzeitstatus und Artikelzahl.
- Railway mountet Volumes als `root`. Deshalb ist für dieses non-root-Image
  `RAILWAY_RUN_UID=0` nötig; der Container läuft auf Railway damit als root.
  Das ist der offizielle Railway-Workaround für Volume-Images. Für diesen
  Single-User-Dienst ist das vertretbar; wer das nicht will, braucht ein
  eigenes Image mit Privilege-Drop (z. B. `gosu`) oder die VPS-Variante.
- Keine weiteren Ports veröffentlichen. Nur der Web-Port wird exponiert.
- Keine mehreren Replicas: SQLite verträgt keine parallelen Schreiber.

## Grenzen

- Eine Instanz, ein Volume, eine Region. Kein Autoscaling.
- Bei einem Redeploy mit Volume kann es kurz downtime geben, weil Railway
  nicht zwei Deployments gleichzeitig auf dasselbe Volume lässt.
- Der Railway-Healthcheck läuft nur beim Deployment, nicht dauerhaft.
- Die Free-/Trial-Grenzen (Volume, Guthaben, Schlafmodus) können sich
  ändern; für 24/7 ist ein bezahlter Plan realistisch. Aktuelle Preise:
  <https://railway.com/pricing>
- Ohne gesetzte Auth-Variablen ist das Dashboard offen. Das ist kein
  Railway-Problem, sondern die bewusste Lokal-Konfiguration der App.
