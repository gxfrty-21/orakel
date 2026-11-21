# Orakel dauerhaft hosten

Diese Konfiguration betreibt das Dashboard als Docker-Stack:

- **orakel** — FastAPI-App mit HTTP-Basic-Login, ausschließlich Paper-Trading
- **caddy** — TLS (Let's Encrypt) und Reverse Proxy
- **orakel_data** — persistentes Volume für SQLite, Vault und Daten

Der Stack ist für **eine** Instanz gedacht. SQLite verträgt keine mehreren
gleichzeitig schreibenden Maschinen; nicht horizontal skalieren.

> Für Railway ohne eigenen Server, Caddy oder eigene Domain siehe
> [RAILWAY.md](RAILWAY.md). Die VPS-Variante hier bleibt unverändert.

## Voraussetzungen

- Docker Engine und Compose v2
- Eine Domain, deren A/AAAA-Eintrag auf den Server zeigt; Ports 80 und 443 offen
- Keine externe Datenbank: alle Daten bleiben im Volume

## Einrichten

1. DNS: `orakel.example.com` auf die IP des Servers zeigen lassen (A, optional AAAA).
2. `.env` anlegen und ausfüllen:

   ```bash
   cp .env.example .env
   chmod 600 .env
   ```

   Domain, Benutzer und ein starkes Passwort eintragen. Passwort erzeugen und
   im Passwortmanager ablegen, zum Beispiel:

   ```bash
   openssl rand -base64 24
   ```

   Sonderzeichen im Passwort in der `.env` in Anführungszeichen setzen.
   `.env` ist per `.gitignore` ausgeschlossen und gehört nicht ins Repository.

3. Bauen und starten:

   ```bash
   docker compose up -d --build
   ```

4. Prüfen:

   ```bash
   docker compose ps
   docker compose logs -f orakel
   curl -s https://DEINE-DOMAIN/api/health
   ```

   Das erste TLS-Zertifikat holt Caddy automatisch, sobald die Domain korrekt
   zeigt.

### Dauerbetrieb aktivieren

Der Hintergrund-Takt ist standardmäßig aus. In `.env`:

```bash
ORAKEL_TAKT=1
```

Danach den App-Container neu erzeugen, damit die Variable greift:

```bash
docker compose up -d --force-recreate orakel
```

Der Takt plant Paper, Konferenz, Spider, Intelligence und Missionen; Fehler
bekommen persistenten Backoff. Grenzen und Intervalle stehen in `[betrieb]` in
`config.toml`. Status im Container:

```bash
docker compose exec -T orakel python -m orakel betrieb
curl -u BENUTZER:PASSWORT https://DEINE-DOMAIN/api/betrieb
```

## Wo die Daten liegen

Im Volume `orakel_data`, im Container unter `/data`:

| Pfad | Inhalt |
|---|---|
| `/data/orakel.db` | SQLite-Fakten-DB (WAL) |
| `/data/vault/` | Obsidian-Vault |
| `/data/daten/` | Kerzen und CSV-Importe |

Der Entrypoint setzt `ORAKEL_DB_PFAD=/data/orakel.db`,
`ORAKEL_DATEN_ORDNER=/data/daten` und `ORAKEL_VAULT_ORDNER=/data/vault`, sofern
die Variablen nicht schon gesetzt sind. Diese Variablen haben Vorrang vor
`[basis] db_pfad`, `daten_ordner` und `vault_ordner` in `config.toml`; die
eingecheckte `config.toml` bleibt unverändert. Massgeblich ist damit
`ORAKEL_DB_PFAD`: Im Container zeigt er ohne eigene Angabe auf
`/data/orakel.db`; ausserhalb des Containers ohne gesetzte Variable gilt der
Pfad aus `config.toml`.

## Bestehende Daten übernehmen

Die Quelle vorher stoppen, damit SQLite keine offene WAL-Datei hat; den
Ziel-Container hält der Import unten an. Der Datenbankpfad ist
`[basis] db_pfad` aus `config.toml`, `ORAKEL_DB_PFAD` hat Vorrang. Im Archiv
muss die Datei `orakel.db` heissen (Standardpfad des Containers); bei einem
abweichenden `ORAKEL_DB_PFAD` entsprechend anpassen.

```bash
# im bisherigen Projektordner
DB=$(python3 -c "from orakel.config import load_config; print(load_config('config.toml').db_pfad)")
DB="${ORAKEL_DB_PFAD:-$DB}"
if [ "$DB" != "orakel.db" ]; then cp "$DB" orakel.db; fi
tar czf orakel-umzug.tar.gz orakel.db vault daten
```

```bash
# auf dem Host, im Ordner dieses Projekts
docker compose stop orakel
docker compose run --rm --no-deps -T --entrypoint sh orakel \
  -c "tar xzf - -C /data" < orakel-umzug.tar.gz
docker compose start orakel
```

Danach im Dashboard prüfen, ob die bisherigen Aufträge und Artikel sichtbar
sind.

## Backup und Wiederherstellung

Die Datenbank läuft im WAL-Modus. Eine einfache Dateikopie kann deshalb
unvollständig sein; das Skript nutzt den Online-Backup von SQLite, der auch
bei laufender App konsistent ist. Die Sicherungen liegen unter
`/data/backups` im Volume; für einen Serververlust zusätzlich regelmässig auf
den Host kopieren.

```bash
docker compose run --rm -T --entrypoint python orakel \
  /app/scripts/pruefe_backup.py --db /data/orakel.db --ordner /data/backups
```

Aufbewahrung: 7 Tagesstände, sonntags zusätzlich ein Wochenstand, davon die
letzten 4. Ältere Dateien entfernt das Skript. Als täglicher Cronjob:

```cron
15 3 * * * cd /srv/orakel && docker compose run --rm -T --entrypoint python \
  orakel /app/scripts/pruefe_backup.py --db /data/orakel.db --ordner /data/backups
```

Nach jeder Sicherung prüft `PRAGMA integrity_check` die Datei. Die
Wiederherstellung wird gegen die laufende Datenbank verglichen (Zeilenzahlen
aller Tabellen):

```bash
docker compose run --rm -T --entrypoint python orakel \
  /app/scripts/pruefe_backup.py --db /data/orakel.db --ordner /data/backups --pruefen
```

Exit 0 heisst: Integrität `ok` und alle Zeilenzahlen stimmen überein.

Für den Umzug auf einen anderen Server das komplette Volume archivieren — bei
gestoppter App, damit die WAL-Datei nicht offen ist. Das Archiv enthält auch
die Sicherungen aus `/data/backups`:

```bash
mkdir -p backups
docker compose stop orakel
docker compose run --rm --no-deps -T --entrypoint sh orakel \
  -c "tar czf - -C /data ." > "backups/orakel-$(date +%F-%H%M).tar.gz"
docker compose start orakel
```

Ein solches Volume-Archiv wird wie ein Umzugsarchiv eingespielt; die Befehle
stehen unter «Bestehende Daten übernehmen».

Das Volume `caddy_data` enthält nur die TLS-Zertifikate; Caddy erneuert sie
selbst.

## Aktualisieren

```bash
git pull
docker compose up -d --build
```

Das Basis-Image im `Dockerfile` ist auf einen Digest gepinnt. Ein
Python-Update ist damit eine bewusste Änderung im `Dockerfile`, kein
Zufallsergebnis des nächsten Builds.

Das Daten-Volume bleibt erhalten. Nach Änderungen an der `.env` genügt
derselbe Neustart wie beim Dauerbetrieb:
`docker compose up -d --force-recreate orakel`.

## Sicherheit

- Der Container bindet `0.0.0.0`. `ORAKEL_AUTH_USER` und `ORAKEL_AUTH_PASS`
  sind deshalb Pflicht: `docker compose` bricht ohne sie schon beim Auflösen
  der `.env` ab (`:?` in `docker-compose.yml`), der Entrypoint meldet es
  zusätzlich und beendet sich mit Exit 1. Nur für die lokale Entwicklung
  erlaubt `ORAKEL_ALLOW_NO_AUTH=1` einen Start ohne Login.
- Schreibende Anfragen mit fremder Herkunft lehnt die App mit 403
  `herkunft_abgelehnt` ab. Erlaubt sind die eigene Adresse sowie die
  kommagetrennten Einträge in `ORAKEL_ERLAUBTE_ORIGINS`; `GET`, `HEAD` und
  `OPTIONS` prüfen die Herkunft nicht.
- Basic-Auth nur über HTTPS. Port 3000 wird nicht nach außen veröffentlicht;
  erreichbar sind ausschließlich Caddy auf 80/443.
- Es gibt genau ein Login, keine Rollen und keine Zwei-Faktor-Anmeldung. Für
  mehrere Benutzer gehört eine Identity-Aware-Proxy-Schicht davor.
- `/api/health` ist absichtlich ohne Login erreichbar und nennt Laufzeitstatus,
  Artikelzahl und eine kompakte Betriebszeile. Der vollständige Plan liegt
  hinter dem Login unter `/api/betrieb`.
- `.env` niemals committen oder weitergeben. Passwortwechsel: `.env` ändern,
  App-Container neu erzeugen (wie oben).
- Das Projekt bleibt **Paper-Trading**. Es existiert kein Codepfad zu einer
  echten Broker-Order.

## Grenzen

- Eine Instanz, ein Volume, eine Region. Kein Autoscaling.
- Ohne Domain gibt es kein öffentliches TLS. Für einen LAN-Test kann
  `ORAKEL_DOMAIN=localhost` gesetzt werden (interne Caddy-CA, Browserwarnung).
  Basic-Auth über offenes HTTP niemals ins Internet stellen.
- Der Healthcheck im Image nutzt `PORT` (Standard `3000`). Wer `PORT` ändert,
  muss den Healthcheck nicht separat anpassen.
- Dieser Stack braucht einen Docker-Server. Die Freebuff-Vorschau bleibt davon
  unabhängig und ist kein Dauerhosting.
