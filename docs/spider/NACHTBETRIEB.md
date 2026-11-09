# Nachtbetrieb — was automatisch läuft und was nicht

**Stand:** 9. November 2026
**Grundlage:** `orakel/nexus/nacht.py` · `deploy/orakel-nacht.service` ·
`deploy/orakel-nacht.timer`

---

## 1. Die ehrliche Grenze

**Ich, der Assistent, laufe nicht über Nacht.** Ich bin an diesen Chat
gebunden: Wenn er geschlossen ist, arbeite ich nicht weiter, und ich kann mich
nicht selbst wecken.

**Das Orakel kann es.** Der Nachtlauf ist ein Programm im Container, das ein
systemd-Timer auf dem Host startet — unabhängig davon, ob ein Chat offen ist.
Das ist der einzige Weg, „automatisch über Nacht" ehrlich umzusetzen.

Was der Nachtlauf **nicht** kann: Entscheidungen treffen, ein Oracle-Konto
anlegen, DNS-Einträge setzen, einen Railway-Export auslösen oder neue,
unbekannte Aufgaben erfinden. Jede neue Aufgabe muss einmal eingeplant werden.

---

## 2. Was um 02:30 Uhr wirklich passiert

| Schritt | Inhalt | Wirkung |
|---|---|---|
| 1 | Fällige Quellen bestimmen | Cache-Metadaten: `abgerufen_am` + `intervall_minuten` |
| 2 | Abruf mit `If-None-Match` / `If-Modified-Since` | unveränderte Quellen: `304`, kein Body, kein Parsen |
| 3 | Neue Antworten parsen | Meldungen zählen (RSS 2.0, RDF, Atom) |
| 4 | Ereignis und Zustand schreiben | `ereignisse`, `zustand["nexus_nacht"]` |
| 5 | SQLite-Backup | `backups/orakel-JJJJ-MM-TT.db`, `integrity_check` |
| 6 | Backups aufräumen | älter als 14 Tage werden gelöscht |
| 7 | Optional DNS/TLS | A/AAAA, Zertifikatsablauf, `/api/health` |

**Noch nicht:** Die Meldungen werden nicht in `artikel` gespeichert. Ohne
Dubletten-Erkennung entstünden Doppelzeilen. Das ist Phase 2 und wird dann in
den Nachtlauf eingehängt.

Der Lauf ist damit ehrlich beschrieben: Er hält Cache und Backup aktuell und
protokolliert, was er gesehen hat — er erfindet keine Erkenntnisse.

---

## 3. Einrichten (auf der Oracle-VM)

Voraussetzungen: Projekt liegt unter `/srv/orakel`, Container laufen
(`docker compose up -d`), `.env` enthält `ORAKEL_DOMAIN`.

```bash
cd /srv/orakel
sudo cp deploy/orakel-nacht.service deploy/orakel-nacht.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now orakel-nacht.timer
```

Prüfen:

```bash
systemctl list-timers orakel-nacht.timer
sudo systemctl start orakel-nacht.service   # einmal sofort
journalctl -u orakel-nacht.service -n 50 --no-pager
```

Der Timer hat `Persistent=true`: War die VM um 02:30 aus, läuft der Nachtlauf
beim nächsten Start nach.

### Alternative ohne systemd

```cron
30 2 * * * cd /srv/orakel && /usr/bin/docker compose exec -T orakel python -m orakel.nexus nacht --db /data/orakel.db --backup-ordner /data/backups >> /var/log/orakel-nacht.log 2>&1
```

---

## 4. Manuell prüfen

```bash
# im Container
docker compose exec -T orakel python -m orakel.nexus status --db /data/orakel.db
docker compose exec -T orakel python -m orakel.nexus nacht --db /data/orakel.db \
  --backup-ordner /data/backups --domain "$ORAKEL_DOMAIN" --limit 5

# auf dem Host
ls -lh /var/lib/docker/volumes/orakel_orakel_data/_data/backups/
```

Die Ausgabe ist JSON und nennt `faellig`, `abgerufen`, `unveraendert`,
`fehler`, `meldungen`, den Backup-Pfad mit `integrity` und — falls gesetzt —
`domain` mit `tage_rest`.

---

## 5. Warnung bei Ausfall

Der Lauf allein reicht nicht: Wer nicht hinsieht, merkt einen Ausfall nicht.
Deshalb gibt es drei Stufen.

### Stufe 1 — Exit-Code und Status

Der Befehl endet mit `1`, sobald etwas fehlschlägt. `systemd` markiert die
Unit als `failed`. Der letzte Bericht steht unter
`zustand["nexus_nacht"]` und erscheint in `GET /api/nexus/status` als Feld
`nacht` — inklusive `ok`, `fehler`, Backup-Status und Warnung.

### Stufe 2 — Webhook (Fehlerfall)

`ORAKEL_WARNUNG_URL` in der `.env` setzen. Der Lauf sendet nur bei Fehlern,
nie im Normalbetrieb.

| Ziel | `ORAKEL_WARNUNG_ART` | Beispiel-URL |
|---|---|---|
| Slack, Mattermost | `json` | `https://hooks.slack.com/services/…` |
| Discord | `json` | `https://discord.com/api/webhooks/…` |
| ntfy | `text` | `https://ntfy.sh/mein-thema` |
| eigener Endpunkt | `json` oder `text` | beliebige https-URL |

Die Nachricht enthält nur Zähler, Backup- und Domain-Status — keine
Feed-Inhalte. Die URL selbst wird **nicht** im Bericht oder Log gespeichert.

### Stufe 3 — Dead man's switch (auch Host-Ausfall)

Ein Webhook kann nicht melden, wenn die VM aus ist. Dafür `ORAKEL_PING_URL`
auf einen Healthchecks-Check zeigen lassen (kostenlos, z. B.
<https://healthchecks.io>):

| Lauf | Anfrage |
|---|---|
| Erfolg | `GET <ping-url>` |
| Fehler | `POST <ping-url>/fail` |

Bleibt der Ping aus, alarmiert der Dienst nach der eingestellten Frist per
E-Mail — auch dann, wenn der Nachtlauf gar nicht starten konnte.

### Einrichten

```bash
# /srv/orakel/.env ergänzen (nicht committen)
ORAKEL_WARNUNG_URL=https://ntfy.sh/orakel-xyz
ORAKEL_WARNUNG_ART=text
ORAKEL_PING_URL=https://hc-ping.com/DEINE-UUID

cd /srv/orakel && docker compose up -d   # Container übernimmt die Variablen
docker compose exec -T orakel python -m orakel.nexus nacht --limit 1 --backup-ordner /data/backups
```

Ohne konfigurierte URL bleibt der Bericht ehrlich: `warnung.gesendet: false`
mit dem Grund `keine Warnungs-URL konfiguriert`.

## 6. Dashboard

`GET /api/nexus/status` liefert den letzten Lauf unter `nacht`: `ok`,
`warnung_noetig`, `warnung`, `ping`, `backup.erstellt` und die Zähler. Im
Spider-Tab steht dafür die Karte **Nachtbetrieb**:

| Anzeige | Quelle |
|---|---|
| Status OK/Warnung | `nacht.ok` |
| Laufzeit | `nacht.zeit` |
| Quellen | `faellig`, `abgerufen`, `unveraendert` |
| Meldungen und Fehler | `meldungen`, `fehler` |
| Backup-Zeitpunkt | `backup.erstellt` |
| Integrität und Größe | `backup.integrity`, `backup.bytes` |
| Warnung und Ping | `warnung.gesendet`, `ping.gesendet` |

Ohne gespeicherten Lauf steht dort „Noch kein Nachtlauf“ — keine erfundene
Zahl. Die Karte lädt beim Öffnen des Spider-Tabs neu.

## 7. Grenzen und Risiken

| Punkt | Ehrliche Einordnung |
|---|---|
| Backup-Ort | liegt im Docker-Volume, also auf derselben VM. Gegen Verlust der VM hilft nur eine Kopie außerhalb (`scp`, Object Storage) — Phase 8. |
| Container aus | `docker compose exec` schlägt fehl; `restart: unless-stopped` deckt Abstürze ab, nicht ein manuell gestopptes Projekt. |
| Oracle-Idle | Der Nachtlauf erzeugt echte Last, aber keine Dauerlast. Die Idle-Reclamation bleibt ein Risiko. |
| Domain-Prüfung | läuft nur, wenn `ORAKEL_DOMAIN` gesetzt ist. Auf Railway gibt es kein Zertifikat im Container; dort ist der Check sinnlos. |
| Kosten | 0 €. Keine kostenpflichtigen Dienste. |
| Fehlermeldungen | landen im Bericht und in `ereignisse`; der Timer selbst schweigt. Wer alarmiert werden will, braucht Phase 8 (Monitoring). |

---

## 6. Was ich nicht automatisch machen kann

Diese Dinge brauchen dich oder einen Zugang, den ich nicht habe:

- Oracle-Konto und Instanz anlegen (Kreditkarte, Verifikation).
- DNS-Eintrag bei DuckDNS oder Cloudflare setzen.
- Railway-Export starten (Railway-Login).
- Entscheiden, ob Railway nach der Migration gestoppt wird.
- Neue Aufgaben in den Nachtlauf aufnehmen — das muss einmal programmiert
  werden, danach läuft es.
