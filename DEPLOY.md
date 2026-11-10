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
- Kein weiterer Dienst nötig: alle Daten bleiben im Volume

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

   `/api/health` ist absichtlich ohne Login erreichbar. Alles andere fragt nach
   Benutzer und Passwort. Das erste TLS-Zertifikat holt Caddy automatisch,
   sobald die Domain korrekt zeigt.

### Dauerbetrieb aktivieren

Der Hintergrund-Takt ist standardmäßig aus. In `.env`:

```bash
ORAKEL_TAKT=1
```

Danach `docker compose up -d --force-recreate orakel`. Der Takt plant Paper,
Konferenz, Spider, Intelligence und Missionen; Fehler bekommen persistenten
Backoff. Grenzen und Intervalle stehen in `[betrieb]` in `config.toml`.
Status im Container:

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

Der Entrypoint setzt dafür `ORAKEL_DB_PFAD`, `ORAKEL_DATEN_ORDNER` und
`ORAKEL_VAULT_ORDNER`. Die eingecheckte `config.toml` bleibt unverändert.

## Bestehende Daten übernehmen

Die Quelle vorher stoppen, damit SQLite keine offene WAL-Datei hat.

```bash
# im bisherigen Projektordner
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

Backup bei gestoppter App, damit die Datenbank konsistent ist:

```bash
mkdir -p backups
docker compose stop orakel
docker compose run --rm --no-deps -T --entrypoint sh orakel \
  -c "tar czf - -C /data ." > "backups/orakel-$(date +%F-%H%M).tar.gz"
docker compose start orakel
```

Wiederherstellen:

```bash
docker compose stop orakel
docker compose run --rm --no-deps -T --entrypoint sh orakel \
  -c "tar xzf - -C /data" < backups/orakel-2026-11-08-1200.tar.gz
docker compose start orakel
```

Das Volume `caddy_data` enthält nur die TLS-Zertifikate; Caddy erneuert sie
selbst.

## Aktualisieren

```bash
git pull
docker compose up -d --build
```

Das Daten-Volume bleibt erhalten. Nach Änderungen an der `.env` den App-Container
neu erzeugen:

```bash
docker compose up -d --force-recreate orakel
```

## Sicherheit

- Basic-Auth nur über HTTPS. Port 3000 wird nicht nach außen veröffentlicht;
  erreichbar sind ausschließlich Caddy auf 80/443.
- Es gibt genau ein Login, keine Rollen und keine Zwei-Faktor-Anmeldung. Für
  mehrere Benutzer gehört eine Identity-Aware-Proxy-Schicht davor.
- `/api/health` ist ohne Login erreichbar und nennt Laufzeitstatus, Artikelzahl
  und eine kompakte Betriebszeile. Der vollständige Plan liegt hinter dem Login
  unter `/api/betrieb`.
- `.env` niemals committen oder weitergeben. Passwortwechsel: `.env` ändern,
  `docker compose up -d --force-recreate orakel`.
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
