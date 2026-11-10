# Nachtbetrieb — was automatisch läuft und was nicht

**Stand:** 10. November 2026
**Grundlage:** `orakel/nexus/nacht.py` · `deploy/orakel-nacht.service` ·
`deploy/orakel-nacht.timer` · `deploy/orakel-nacht-fail.service` ·
`scripts/oracle-nacht-install.sh`

---

## 1. Die ehrliche Grenze

**Ich, der Assistent, laufe nicht über Nacht.** Ich bin an diesen Chat
gebunden: Wenn er geschlossen ist, arbeite ich nicht weiter, und ich kann mich
nicht selbst wecken.

**Das Orakel kann es.** Der Nachtlauf ist ein Programm im Container, das ein
systemd-Timer auf dem Host startet — unabhängig davon, ob ein Chat offen ist.
Das ist der einzige Weg, „automatisch über Nacht" ehrlich umzusetzen.

**Was ich nicht kann:** die Einrichtung auf deiner Oracle-VM ausführen. Aus
diesem Chat gibt es keinen SSH-Zugang zu deiner VM. Vorbereitet und lokal
geprüft sind Shell-Syntax, systemd-Unit-Syntax, der Fail-Pfad und die
Python-Tests. Auf deiner VM läuft der Installer erst, wenn du ihn dort
startest. Auch das Healthchecks-Konto und die Bestätigung der E-Mail kann nur
du anlegen.

Was der Nachtlauf **nicht** kann: Entscheidungen treffen, ein Oracle-Konto
anlegen, DNS-Einträge setzen, einen Railway-Export auslösen oder neue,
unbekannte Aufgaben erfinden. Jede neue Aufgabe muss einmal eingeplant werden.

---

## 2. Was um 02:30 Uhr wirklich passiert

Der Timer läuft um **02:30 Uhr Europe/Zurich** (auch wenn die VM auf UTC
steht). `Persistent=true` holt einen verpassten Lauf beim nächsten Start nach.

| Schritt | Inhalt | Wirkung |
|---|---|---|
| 1 | Fällige Quellen bestimmen | Cache-Metadaten: `abgerufen_am` + `intervall_minuten` |
| 2 | Abruf mit `If-None-Match` / `If-Modified-Since` | unveränderte Quellen: `304`, kein Body, kein Parsen |
| 3 | Neue Antworten parsen | Meldungen zählen (RSS 2.0, RDF, Atom), Sprache schätzen, SimHash berechnen |
| 4 | Speichern und gruppieren | Original in `artikel`, jede Meldung in `nexus_meldungen` |
| 5 | Kernaussagen bewerten | regelbasierte Claims, Quellenreputation, Widersprüche |
| 6 | Ereignis und Zustand schreiben | `ereignisse`, `zustand["nexus_nacht"]` |
| 7 | SQLite-Backup | `backups/orakel-JJJJ-MM-TT.db`, `integrity_check` |
| 8 | Backups aufräumen | älter als 14 Tage werden gelöscht |
| 9 | Optional DNS/TLS | A/AAAA, Zertifikatsablauf, `/api/health` |

**Was noch nicht:** Volltextanalyse, Entitäten und semantisches Verstehen.
Phase 3 bewertet nur Sätze mit prüfbaren Mustern (Metrik, Zahl, Richtung,
Verneinung). 431 von 446 Meldungen im letzten breiten Lauf hatten kein solches
Muster und bleiben bewusst ohne Claim. Der Lauf behauptet nicht, den Inhalt
verstanden zu haben.

Der Lauf ist damit ehrlich beschrieben: Er hält Artikel, Cache, Claims und
Backup aktuell und protokolliert, was er gesehen hat — er erfindet keine
Erkenntnisse.

### Missionen im Takt

Die Phasen 4 und 5 ergänzen eine persistente Missionen-Queue mit fünf Aufgaben
(`lage`, `pruefung`, `gegenargument`, `bericht`, `weitergabe`). Ist der
Web-Takt aktiv (`paper.takt_aktiv = true`), führt `scheduler.takt_schritt` bei
jedem Takt höchstens fünf fällige Missionen-Aufgaben aus. Ohne aktiven Takt
laufen Missionen nur über `POST /api/nexus/mission/{kennung}/lauf` oder die CLI
`python -m orakel.nexus mission-lauf`. Der Nachtlauf selbst legt keine
Missionen an; es gibt keinen Generator, der sich Fragen ausdenkt. Details:
[PHASE-4.md](PHASE-4.md) und [PHASE-5.md](PHASE-5.md).

---

## 3. Einrichten auf der Oracle-VM

Voraussetzungen: Projekt liegt unter `/srv/orakel`, Container laufen
(`docker compose up -d`), `.env` enthält `ORAKEL_DOMAIN`, `curl` ist
vorhanden (installiert der Bootstrap).

### 3.1 Healthchecks-Check anlegen

1. Auf <https://healthchecks.io> ein kostenloses Konto anlegen und die
   E-Mail-Adresse bestätigen.
2. **Add Check**:
   - Name: `Orakel Nachtlauf`
   - Schedule type: **Simple**
   - Period: **1 day**
   - Grace Time: **2 hours**
   - Timezone: `Europe/Zurich`
   - Notification: E-Mail (Standard); weitere Kanäle optional.
3. Die **Ping-URL** kopieren: `https://hc-ping.com/<uuid>`.

Die Ping-URL ist ein Secret. Sie gehört nur in `/srv/orakel/.env` (chmod 600)
— nicht in den Chat, in Logs oder ins Repository.

Die Grace Time von 2 Stunden deckt den Lauf ab (maximal 45 Minuten) und
verzögert einen echten Ausfall nicht unnötig. Wer schneller alarmiert werden
will, senkt sie.

### 3.2 Installer ausführen

Im SSH-Fenster der VM:

```bash
cd /srv/orakel
sudo git pull --ff-only
sudo bash scripts/oracle-nacht-install.sh
```

Der Installer:

1. prüft Projektordner, `.env`, Docker und den laufenden Container,
2. fragt die Healthchecks-Ping-URL **verdeckt** ab (leer = ohne
   Dead-man's-Switch),
3. schreibt sie nach `.env` (chmod 600) und startet den Container mit der
   neuen Umgebung neu,
4. installiert `orakel-nacht.service`, `orakel-nacht-fail.service` und
   `orakel-nacht.timer`, aktiviert den Timer,
5. startet einen echten ersten Lauf und zeigt den gespeicherten Zustand.

Der erste Lauf kann einige Minuten dauern. `OHNE_LAUF=1` überspringt ihn.

### 3.3 Prüfen

```bash
systemctl list-timers orakel-nacht.timer --no-pager
systemctl status orakel-nacht.service --no-pager
journalctl -u orakel-nacht.service -n 50 --no-pager
```

Zustand aus der Datenbank:

```bash
cd /srv/orakel
sudo docker compose exec -T orakel python -c "import json; from orakel.db import Facts; n=Facts('/data/orakel.db').zustand('nexus_nacht') or {}; b=n.get('backup') or {}; print(json.dumps({'ok': n.get('ok'), 'zeit': n.get('zeit'), 'backup': b.get('erstellt'), 'integrity': b.get('integrity'), 'ping': n.get('ping')}, ensure_ascii=False))"
```

Im Healthchecks-Dashboard muss der erste Ping sichtbar sein. `ping.gesendet:
true` im Zustand bestätigt, dass der Lauf ihn gesendet hat; die URL selbst
steht nicht im Bericht.

### 3.4 Alternative ohne systemd

Im root-Crontab (`sudo crontab -e`):

```cron
30 2 * * * cd /srv/orakel && /usr/bin/docker compose exec -T orakel python -m orakel.nexus nacht --db /data/orakel.db --backup-ordner /data/backups >> /var/log/orakel-nacht.log 2>&1
```

Der Container bringt `ORAKEL_DOMAIN` und `ORAKEL_PING_URL` aus der `.env` mit.
Cron hat aber kein `Persistent=true`: War die VM um 02:30 aus, fällt der Lauf
aus und Healthchecks alarmiert nach Period + Grace. Der systemd-Timer ist
deshalb der bessere Weg.

---

## 4. Manuell prüfen

```bash
# im Container
sudo docker compose exec -T orakel python -m orakel.nexus status --db /data/orakel.db
sudo docker compose exec -T orakel python -m orakel.nexus nacht --db /data/orakel.db \
  --backup-ordner /data/backups --limit 5 --ping-url ""
sudo docker compose exec -T orakel python -m orakel.nexus bewertung --db /data/orakel.db
```

Die Ausgabe ist JSON und nennt `faellig`, `abgerufen`, `unveraendert`,
`fehler`, `meldungen`, den Backup-Pfad mit `integrity` und — falls gesetzt —
`domain` mit `tage_rest`.

**Wichtig:** Ein manueller Lauf ohne `--ping-url ""` sendet einen echten
Erfolgs-Ping und verschiebt damit den Healthchecks-Erwartungspunkt. Für reine
Tests den Ping mit `--ping-url ""` abschalten.

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

`ORAKEL_PING_URL` zeigt auf den Healthchecks-Check. Der Lauf sendet:

| Situation | Anfrage | Alarm |
|---|---|---|
| Erfolg | `GET <ping-url>` | nein |
| Lauf mit Fehlern | `POST <ping-url>/fail` (Python) | sofort |
| Container/systemd scheitert vor Python | `OnFailure` → `orakel-nacht-fail.sh` → `POST <ping-url>/fail` | sofort |
| VM aus oder Timer startet nicht | kein Ping | nach Period + Grace |
| Ping-URL falsch oder Dienst down | kein gültiger Ping | nach Period + Grace |

Der Python-Lauf und die Fail-Unit senden die URL nie als Kommandozeilen-
Argument; sie kommt aus der Umgebung und wird von `curl` über stdin gelesen.
Im Bericht steht nur `ping.gesendet` und ein Fehlertyp, nie die URL.

Ohne konfigurierte URL bleibt der Bericht ehrlich: `warnung.gesendet: false`
mit dem Grund `keine Warnungs-URL konfiguriert`; ein `ping`-Feld fehlt dann
ganz. Der Timer läuft trotzdem, aber niemand wird bei einem Ausfall geweckt.

---

## 6. Dashboard

`GET /api/nexus/status` liefert den letzten Lauf unter `nacht`: `ok`,
`warnung_noetig`, `warnung`, `ping`, `backup.erstellt` und die Zähler. Im
Spider-Tab steht dafür die Karte **Nachtbetrieb**:

| Anzeige | Quelle |
|---|---|
| Status OK/Warnung | `nacht.ok` |
| Laufzeit | `nacht.zeit` |
| Quellen | `faellig`, `abgerufen`, `unveraendert` |
| Meldungen, gespeichert, Kopien | `meldungen`, `gespeichert`, `dubletten` |
| Kernaussagen, Belege | `bewertung.kernaussagen`, `bewertung.belege` |
| Widersprüche | `bewertung.widersprueche` |
| Fehler | `fehler`, `speicher_fehler`, `bewertung.fehler` |
| Backup-Zeitpunkt | `backup.erstellt` |
| Integrität und Größe | `backup.integrity`, `backup.bytes` |
| Warnung und Ping | `warnung.gesendet`, `ping.gesendet` |

Ohne gespeicherten Lauf steht dort „Noch kein Nachtlauf“ — keine erfundene
Zahl. Die Karte lädt beim Öffnen des Spider-Tabs neu.

Die Karte **Kernaussagen** zeigt zusätzlich `claims.statistik` und
`claims.top` aus derselben API. `GET /api/nexus/claims` liefert alle Claims,
Widersprüche und die Quellenreputation; `status=widersprüchlich` filtert.

```bash
curl -s 'http://127.0.0.1:8000/api/nexus/claims?limit=20' | python -m json.tool
```

---

## 7. Grenzen und Risiken

| Punkt | Ehrliche Einordnung |
|---|---|
| Backup-Ort | liegt im Docker-Volume, also auf derselben VM. Gegen Verlust der VM hilft nur eine Kopie außerhalb (`scp`, Object Storage) — Phase 8. |
| Container aus | `OnFailure` sendet sofort `/fail`; fehlt der Ping ganz, alarmiert Healthchecks nach Period + Grace. |
| VM aus | kein Ping; Healthchecks alarmiert nach Period + Grace. Das ist der eigentliche Dead-man's-Switch. |
| Healthchecks selbst | externer Dienst. Konto und bestätigte E-Mail sind nötig; die Ping-URL ist ein Secret. Fällt Healthchecks aus, kommt keine Alarmierung. |
| Oracle-Idle | Der Nachtlauf erzeugt echte Last, aber keine Dauerlast. Die Idle-Reclamation bleibt ein Risiko. |
| Domain-Prüfung | läuft nur, wenn `ORAKEL_DOMAIN` gesetzt ist. Auf Railway gibt es kein Zertifikat im Container; dort ist der Check sinnlos. |
| Kosten | 0 €. Healthchecks ist kostenlos; SMS/Telefon-Alarme können kostenpflichtig sein. |
| Fehlermeldungen | landen im Bericht, in `ereignisse` und im Journal. Die Fail-Unit meldet Unit-Fehler, der Python-Lauf seine eigenen Fehler. |
| Erster Lauf | Der Installer startet einen vollen Lauf; bei 47 Quellen kann das einige Minuten dauern. |
| Kein SSH | Die Einrichtung auf der VM muss von dir ausgeführt werden; dieser Chat hat keinen Zugang. |

---

## 8. Was ich nicht automatisch machen kann

Diese Dinge brauchen dich oder einen Zugang, den ich nicht habe:

- Oracle-Konto und Instanz anlegen (Kreditkarte, Verifikation).
- DNS-Eintrag bei DuckDNS oder Cloudflare setzen.
- Railway-Export starten (Railway-Login).
- Healthchecks-Konto anlegen und die E-Mail bestätigen.
- Den Installer auf der VM ausführen (kein SSH-Zugang aus diesem Chat).
- Entscheiden, ob Railway nach der Migration gestoppt wird.
- Neue Aufgaben in den Nachtlauf aufnehmen — das muss einmal programmiert
  werden, danach läuft es.
