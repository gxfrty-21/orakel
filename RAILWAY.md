# Orakel auf Railway

Railway-Variante ohne eigenen Server, ohne Caddy und ohne eigene Domain.
Railway baut den vorhandenen `Dockerfile`, stellt TLS und eine
`*.up.railway.app`-Adresse bereit. SQLite, Vault und Daten liegen im
persistenten Volume unter `/data`.

Das Projekt bleibt **Paper-Trading**. Es gibt keinen Codepfad zu einer echten
Broker-Order.

## Aktueller Stand

Zuletzt deployed am 12. November 2026:

- Dashboard: <https://orakel-production-fb18.up.railway.app>
- Projekt: `orakel` (`565cd49f-e067-415b-aa3a-5680557fedd9`)
- Environment: `production` (`97106b8a-7ff8-4285-a30e-e8309da409fd`)
- Service: `orakel` (`1f8e2304-31d5-4c7e-80b3-8010ee2d969e`)
- Volume: `orakel-volume` (`241709d8-4eb6-40c9-8163-a28edb58b3ed`),
  Mount `/data`, 500 MB
- Deploy: automatischer GitHub-Build aus `main`; den ausgelieferten Commit
  nennt `/api/health` im Feld `commit`. Der erste Build nach dem Merge war
  `ea11f42e` (Commit `ad454e0`).
- Domain: Target Port `3000`, TLS von Railway
- Deploy-Weg: GitHub-Quelle `gxfrty-21/orakel`, Branch `main`, ist wieder
  verbunden; Pushes bauen automatisch. Der CLI-Upload bleibt Fallback, wenn
  kein Push möglich ist. Project Tokens setzen eine bezahlte Subscription
  voraus und sind hier nicht im Einsatz.
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

## Deploy ohne GitHub-Push (CLI-Upload)

Wenn der Push nach GitHub nicht möglich ist (fehlende Zugangsdaten in der
Umgebung), lädt die Railway-CLI den lokalen Stand direkt hoch. Railway baut
dabei denselben `Dockerfile`; ein Commit auf GitHub ist nicht nötig. Seit dem
12. November 2026 ist die GitHub-Quelle wieder verbunden — dieser Weg bleibt
der manuelle Fallback.

Voraussetzungen:

- Railway-CLI (`npm i -g @railway/cli` oder `npx @railway/cli`)
- angemeldete CLI (`railway login`); der Login liegt in `~/.railway`
- alternativ `RAILWAY_TOKEN`/`RAILWAY_API_TOKEN` in der Umgebung. In dieser
  Chat-Umgebung kommen Projekt-Secrets nicht als Umgebungsvariablen an; dort
  funktioniert nur der gespeicherte CLI-Login.
- verknüpftes Projekt; sonst `--project` und `--environment` angeben

```bash
railway up \
  --project 565cd49f-e067-415b-aa3a-5680557fedd9 \
  --environment production \
  --service orakel \
  --ci
```

Was hochgeladen wird, begrenzt `.dockerignore`: `vault/`, `daten/`, `orakel.db`,
`tests/`, `artifacts/` und `.git` bleiben außen vor (im Test 3,7 MB). Das
Volume `/data` wird nicht angefasst; der Entrypoint importiert den Seed nur in
eine leere DB.

Nachprüfung:

```bash
railway deployment list          # neueste Zeile: SUCCESS
curl -s https://orakel-production-fb18.up.railway.app/api/health
```

`/api/health` liefert bei CLI-Uploads `commit: null`, weil
`RAILWAY_GIT_COMMIT_SHA` fehlt. `deploy-check.yml` läuft dafür nicht; die
Prüfung erfolgt über Deployment-Status, `ok: true` und `/` → 401.

### Überschreib-Gefahr

Der Service ist seit dem 12. November 2026 wieder mit `gxfrty-21/orakel`,
Branch `main`, verbunden (`railway service source connect`), nachdem PR #4 den
Produktionsstand auf `main` gebracht hatte. Zuvor war die Quelle kurzzeitig
getrennt, weil `main` hinter der Produktion lag; ein Rebuild hätte den
CLI-Stand ersetzt. `railway up` funktioniert weiterhin als manueller Weg.

Ein CLI-Upload erzeugt **keinen** Commit: `main` bleibt alt, die Produktion
läuft trotzdem neu. Ist die Quelle verbunden, baut jeder Deploy aus GitHub
(Push auf `main`, manueller Redeploy, Neustart mit Source-Build, „Wait for CI“)
wieder `main` und ersetzt den CLI-Stand.

Konkret am 12. November 2026:

- `main` = `ad454e0` (Merge von PR #4, 2D-Stand mit Sekretariat und
  Filter-Fixes)
- Produktion = derselbe Commit, automatisch als `ea11f42e` gebaut
- Die frühere CLI-Version `40ab8686` (Stand `e8b7e08`) ist damit ersetzt; das
  Volume blieb erhalten (`artikel=46`, 28.086 Trades).
- Spätere Pushes bauen automatisch weiter; maßgeblich ist der `commit` in
  `/api/health`.

Erkennungsmerkmal: Bei CLI-Deploys fehlt `RAILWAY_GIT_COMMIT_SHA`, deshalb
steht in `/api/health` `commit: null`, und `deploy-check.yml` läuft nicht. Ein
GitHub-Deploy liefert dort den Commit-Hash.

Schutz vor einem unbeabsichtigten Rückschritt:

1. Vor einem GitHub-Deploy muss der gewünschte Stand auf `main` liegen; ein
   Push baut genau diesen Commit.
2. Nach einem CLI-Deploy liegt `main` zurück: Quelle trennen oder zeitnah
   denselben Stand auf `main` bringen. Wiederverbinden:

   ```bash
   railway service source connect \
     --repo gxfrty-21/orakel --branch main --service orakel
   ```

3. Wenn CLI-Deploys dauerhaft der Weg sein sollen, bleibt die Quelle getrennt.

Merksatz: Ein CLI-Deploy deployt den Workspace, aber aktualisiert nicht das
Repository. `main` bleibt die Quelle für jeden automatischen Build.

## Deploy nur bei grüner CI

Railway kann ein Deployment zurückhalten, bis die GitHub-Actions-Läufe des
Commits fertig sind. Dann geht kein Commit mit roten Tests live, und die
laufende Version bleibt erreichbar.

### Einmalig einschalten

Voraussetzungen:

- Der Service ist mit dem GitHub-Repository verbunden (Autodeploy), nicht nur
  per CLI befüllt. Die Quelle ist seit dem 12. November 2026 wieder verbunden.
- Ein Projektmitglied hat Schreibzugriff auf das Repository.
- Ein Workflow läuft auf `push` in den Deploy-Branch. `.github/workflows/tests.yml`
  macht das mit `on: push: branches: [main]`.

1. Railway-Projekt öffnen → Service `orakel` → **Settings → Source →
   Connect Repo** → Repository `gxfrty-21/orakel`, Branch `main`.
2. Danach im selben Service **Settings → Wait for CI** einschalten. Fehlt der
   Schalter, zuerst die aktualisierten GitHub-Berechtigungen der Railway-App
   bestätigen (GitHub → Settings → Applications → Railway → Configure).
3. Kein `RAILWAY_TOKEN` und kein Project Token nötig. Project Tokens setzen
   eine aktive bezahlte Subscription voraus und werden hier nicht verwendet.

### Verhalten

| Fall | Ergebnis |
|---|---|
| alle Workflows grün | Deployment startet, Healthcheck `/api/health` entscheidet über den Wechsel |
| ein Workflow rot | Deployment `SKIPPED`, die laufende Version bleibt aktiv |
| Workflow abgebrochen | blockiert nur, wenn kein anderer Workflow des Commits grün war |
| nach 2 Stunden nicht fertig | Deployment wird übersprungen |

Railway bewertet den Abschluss ganzer Workflow-Läufe, nicht einzelne Jobs, und
ignoriert Checks anderer GitHub-Apps. Für Schritte, die **vor** jedem Deploy
laufen müssen (Migrationen), reicht Wait for CI allein nicht.

Der Docker-Job der CI baut dasselbe Image wie Railway. Ein kaputtes `Dockerfile`
oder ein fehlendes Paket fällt damit vor dem Deploy auf; der Smoke-Test im
Container prüft zusätzlich Start, Health und Login-Schutz.

### Ein Weg: GitHub-Quelle + Wait for CI

| Voraussetzung | Ablauf |
|---|---|
| Service ist mit `gxfrty-21/orakel` verbunden, Branch `main` | Railway baut den Commit selbst, sobald `Tests` grün ist |

Der tokenbasierte `Deploy`-Workflow wurde entfernt. `.github/workflows/deploy.yml`
gibt es nicht mehr; GitHub Actions lädt den Commit nicht mehr selbst hoch.
Damit gibt es auch keinen Job, der ohne `RAILWAY_TOKEN` rot wird. Project Tokens
setzen eine aktive bezahlte Subscription voraus; dieser Weg wird nicht mehr
verwendet.

### Nachprüfung nach dem Deploy

Ein grüner CI-Lauf heißt noch nicht, dass der Commit auch ausgeliefert wird.
`.github/workflows/deploy-check.yml` läuft nach einem erfolgreichen
Railway-Deployment (`deployment_status: success`) und prüft die Produktion:

- `/api/health` muss als `commit` genau den ausgelieferten Commit nennen. Der
  Wert kommt aus `RAILWAY_GIT_COMMIT_SHA`, das Railway bei Deploys aus GitHub
  selbst setzt — dafür war das Feld `commit` in `/api/health` nötig.
- Gewartet wird bis zu 13 Minuten, danach ist der Lauf rot. Der Job braucht
  keinen Token; `/api/health` ist ohne Login erreichbar.
- Zusätzlich: `ok: true`, eine Artikelzahl über 0 (fängt ein leeres Volume ab)
  und `/` ohne Zugangsdaten muss `401` liefern.

Der Lauf beantwortet damit die Frage „ist der Deploy wirklich durch?“. Er startet
erst nach dem Deploy und blockiert deshalb nicht Railways „Wait for CI“. Bei
einem manuellen CLI-Deploy ohne GitHub-Status läuft er nicht; dann fehlt auch
`RAILWAY_GIT_COMMIT_SHA`. Für diesen Service ist GitHub der einzige automatische
Deploy-Weg; der CLI-Upload ist manuell und wird von `deploy-check.yml` nicht
geprüft.

## Dauerbetrieb (Phase 8)

Der Takt bleibt standardmäßig aus. Zum Aktivieren im Railway-Service
`ORAKEL_TAKT=1` setzen und neu deployen. Danach zeigt
`/api/health` eine kompakte Betriebszeile; der vollständige Plan mit Backoff
und Ressourcenwerten liegt hinter dem Login unter `/api/betrieb`.

Der Railway-Healthcheck bleibt bewusst nur auf HTTP 200. Ein Job im Backoff
darf keinen Container-Neustart-Loop auslösen. Ein echter 24-Stunden-Soak steht
noch aus.

Der externe Watchdog ist als GitHub-Actions-Workflow in
`.github/workflows/watchdog.yml` angelegt. Nach dem Push auf den Default-Branch
prüft er alle fünf Minuten `/api/health`, öffnet bei einem Taktalter über 300
Sekunden oder einem Status ungleich `laeuft` ein GitHub-Issue und schließt es
nach der Erholung wieder. GitHub kann geplante Läufe verzögern; der Watchdog
ergänzt den Railway-Healthcheck, ersetzt ihn aber nicht.

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
   | `ORAKEL_TAKT` | `0` (kein Hintergrund-Takt; für Phase 8 auf `1` setzen) |
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
- `/api/health` ist absichtlich ohne Login erreichbar und nennt Laufzeitstatus,
  Artikelzahl und eine kompakte Betriebszeile. Der vollständige Plan liegt
  hinter dem Login unter `/api/betrieb`.
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
