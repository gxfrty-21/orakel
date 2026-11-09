# Migration auf Oracle Always Free

**Stand:** 9. November 2026
**Ziel:** Orakel von Railway auf eine kostenlose Oracle-VM umziehen, ohne Datenverlust
und ohne die laufende Instanz vorher abzuschalten.
**Grundlage:** [PHASE-0-PLAN.md](PHASE-0-PLAN.md) · `Dockerfile` ·
`docker-compose.yml` · `deploy/Caddyfile` · `RAILWAY.md`

> **Was ich nicht selbst ausführen konnte:** Oracle verlangt ein Konto mit
> Kreditkarte und Zugriff auf dein Railway-Projekt. Ich habe keinen davon.
> Geprüft sind: Shell-Syntax aller Skripte, `docker compose config`, der
> konsistente SQLite-Export an einer Kopie der echten DB, die Archivstruktur
> und — real — die Hacker-News-API. **Nicht** geprüft: Caddy-Validierung
> (Docker-Daemon im Sandbox gesperrt), ein echter Railway-Export, ein echter
> Oracle-Start. Diese drei Punkte bleiben bis zum ersten Lauf offen.

---

## 0. Reihenfolge (wichtig)

Railway läuft **weiter**, bis Oracle nachweislich funktioniert. Erst Daten
exportieren, dann importieren, dann prüfen, **danach** Railway stoppen. Ein
Rollback ist damit nur ein Stoppen der VM.

```
Railway (läuft) ──Export──▶ Archiv ──scp──▶ Oracle ──Import──▶ Prüfung
                                                              │
                                              Railway erst jetzt stoppen
```

---

## 1. Instanz anlegen

1. Konto auf <https://cloud.oracle.com> anlegen (Kreditkarte nur zur
   Verifikation, keine Abbuchung ohne Upgrade).
2. Region = **Heimatregion** (Always Free gilt nur dort).
3. Compute → Instanz:
   - Shape **VM.Standard.A1.Flex**, **2 OCPU / 12 GB** (Always-Free-Grenze;
     die früheren 4/24 wurden am 15.6.2026 halbiert).
   - Image **Ubuntu 24.04** (Arm).
   - Boot-Volume **50 GB** (Minimum; 200 GB stehen insgesamt zur Verfügung).
   - SSH-Key hinterlegen (öffentlicher Schlüssel deines Rechners).
4. Öffentliche IPv4 notieren.
5. Bei „out of host capacity": andere Availability Domain versuchen oder
   später erneut; das ist ein bekanntes Oracle-Problem, kein Fehler bei dir.

### Security List

Networking → VCN → Security List → Ingress:

| Port | Quelle | Zweck |
|---|---|---|
| 22/tcp | deine IP | SSH |
| 80/tcp | 0.0.0.0/0 | Let's Encrypt HTTP-01 |
| 443/tcp | 0.0.0.0/0 | Dashboard |

### iptables auf Oracle-Ubuntu

Die Ubuntu-Images von Oracle bringen eigene iptables-Regeln mit, die ufw
aushebeln. `scripts/oracle-bootstrap.sh` ergänzt die Regeln, wenn
`/etc/iptables/rules.v4` existiert. Wenn der Port später trotzdem zu ist:

```bash
sudo iptables -L INPUT -n --line-numbers | head
sudo iptables -I INPUT 5 -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

---

## 2. DNS und TLS (0 €)

Caddy braucht einen Hostnamen für ein Let's-Encrypt-Zertifikat. Zwei Wege:

### A. DuckDNS (einfach, kostenlos)

1. <https://www.duckdns.org> → mit GitHub/Google anmelden.
2. Subdomain anlegen, z. B. `orakel-xyz`, und die öffentliche IP der VM
   eintragen.
3. Ergebnis: `orakel-xyz.duckdns.org`.

**Ehrlich:** DuckDNS ist kostenlos und läuft, aber von Spendengeldern
finanziert. Die Let's-Encrypt-Community meldet wiederholt DNS-Aussetzer, die
eine Zertifikatserneuerung verzögern können. Für den Start vertretbar; bei
wiederholten Problemen auf Cloudflare Tunnel oder eine eigene Domain
(5–12 €/Jahr) wechseln.

### B. Cloudflare Tunnel (robuster, ebenfalls 0 €)

Keine offenen Ports, TLS von Cloudflare, aber ein Cloudflare-Konto und eine
`cloudflared`-Konfiguration nötig. Für diesen Stack nicht vorbereitet; als
Alternative dokumentiert.

### Caddy

`deploy/Caddyfile` ist bereits fertig: automatisches TLS, HTTP→HTTPS,
Reverse Proxy auf `orakel:3000`, HSTS. Es wird nichts weiter gebraucht als
`ORAKEL_DOMAIN` in der `.env`.

---

## 3. Repository auf die VM bringen

Das Repository ist privat. Lege auf der VM einen **read-only Deploy-Key** an
und trage ihn in GitHub ein (Settings → Deploy keys → Add deploy key,
„Allow write access" **aus**):

```bash
ssh-keygen -t ed25519 -C "oracle-vm" -f ~/.ssh/orakel_deploy -N ""
cat ~/.ssh/orakel_deploy.pub
```

Dann in GitHub eintragen. Der private Schlüssel bleibt auf der VM.

---

## 4. Bootstrap

```bash
scp scripts/oracle-bootstrap.sh ubuntu@IP:/tmp/
ssh ubuntu@IP
sudo REPO_URL=git@github.com:gxfrty-21/orakel.git \
     ORAKEL_DOMAIN=orakel-xyz.duckdns.org \
     bash /tmp/oracle-bootstrap.sh
```

Das Skript ist idempotent und macht:

1. Docker + Compose aus dem offiziellen Repository installieren.
2. ufw: 22, 80, 443; iptables-Regeln für Oracle-Images ergänzen.
3. Repository nach `/srv/orakel` klonen (oder `git pull`).
4. `.env` aus `.env.example` erzeugen, **Passwort zufällig generieren**,
   `chmod 600`. Vorhandene `.env` wird nie überschrieben.
5. DNS gegen die eigene öffentliche IP prüfen und warnen.
6. `docker compose up -d --build`.
7. Bis zu 5 Minuten auf `https://DOMAIN/api/health` warten.

Passwort anzeigen:

```bash
sudo grep ORAKEL_AUTH_PASS /srv/orakel/.env
```

**Bewusst unverändert:** `ORAKEL_TAKT=0`. Der Takt ist Paper-Trading und war
auf Railway aus; die Recherche bekommt ihren Zeitplan erst in Phase 8. Wer ihn
jetzt will, setzt `ORAKEL_TAKT=1` und startet den Container neu.

---

## 5. Datenübernahme

### 5.1 Export auf dem eigenen Rechner

Voraussetzungen: Railway CLI, eingeloggt, Projekt verlinkt, **Dienst läuft**
(der Volume-Zugriff geht über die laufende Instanz).

```bash
railway link          # falls noch nicht geschehen
./scripts/railway-export.sh ./orakel-umzug.tar.gz
```

Was das Skript tut und warum:

| Schritt | Warum |
|---|---|
| `sqlite3.backup()` im Container nach `/tmp/orakel.db` | konsistente Kopie trotz WAL und laufendem Schreiben; ein `tar` der offenen DB kann korrupt sein |
| `PRAGMA integrity_check` + Artikelzahl | beweist, dass die Kopie lesbar ist |
| `tar czf … vault daten -C /tmp orakel.db` | Archiv mit genau den Pfaden, die der Restore erwartet |
| `railway volume files download` | offizieller Weg; Pfade sind relativ zum Volume-Root |
| lokale Prüfung mit `tarfile` + `sqlite3` | ein Download allein ist kein Beweis |

**Wichtig:** Railway-Volume-Backups sind **kein Export**. Laut Railway-Doku
lassen sie sich nur im selben Projekt/Environment wiederherstellen, und
Restore erfordert den Pro-Plan. Deshalb der eigene Export.

### 5.2 Übertragen

```bash
scp ./orakel-umzug.tar.gz ubuntu@IP:/tmp/
```

### 5.3 Import auf der VM

```bash
ssh ubuntu@IP
cd /srv/orakel
sudo ./scripts/oracle-restore.sh /tmp/orakel-umzug.tar.gz
```

Das Skript sichert zuerst den aktuellen Volume-Inhalt nach
`backups/vor-import-<zeit>.tar.gz`, stoppt `orakel`, spielt das Archiv ein,
startet neu und prüft den Healthcheck inklusive Artikelzahl.

---

## 6. Nachprüfung

```bash
curl -i https://DOMAIN/api/health          # 200, ohne Login
curl -i https://DOMAIN/                    # 401, ohne Login
curl -iu orakel:PASSWORT https://DOMAIN/   # 200
```

Im Dashboard prüfen: Artikelzahl, Vault-Notizen, Paper-Trading-Historie.
Erwartet: dieselben Zahlen wie auf Railway (zuletzt 34 Artikel, 44 Notizen).

**Das `commit`-Feld bleibt auf Oracle leer.** Es kommt aus
`RAILWAY_GIT_COMMIT_SHA`, das nur Railway setzt. Die
`deploy-check.yml`-Nachprüfung betrifft ausschließlich Railway und wird nach
dem Umzug abgeschaltet oder auf Oracle umgestellt.

---

## 7. Railway stoppen

Erst wenn Abschnitt 6 vollständig grün ist:

1. Railway → Service → Settings → Deployment stoppen (oder Dienst löschen,
   **Volume vorher exportiert**).
2. Volume nicht sofort löschen — es ist die letzte Rückfallebene, bis ein
   Oracle-Backup existiert.
3. Trial-Ende beachten: nach Ablauf werden Trial-Volumes nach 30 Tagen
   gelöscht.

### Rollback

Solange Railway läuft: VM stoppen, Railway starten, fertig. Nach dem Stoppen:
Archiv aus `backups/` bzw. den letzten Export einspielen.

---

## 8. Dauerbetrieb und Idle-Risiko

Oracle darf Always-Free-Instanzen zurückholen, wenn über 7 Tage **alle drei**
gelten: CPU-P95 < 20 %, Netzwerk < 20 %, RAM < 20 %. Ein Dienst mit ~300 MB
RAM fällt darunter, auch wenn er läuft.

Ehrliche Einordnung: Es gibt keine saubere Gegenmaßnahme, die nicht Ressourcen
verbrennt. Sinnvoll sind:

- **echte** periodische Arbeit (Spider-Lauf, Phase 8) statt künstlicher Last,
- tägliches Backup außerhalb der VM (`scp` oder Object Storage),
- Monitoring, das einen Ausfall meldet (Phase 8),
- Neuerstellung in Minuten, weil der Stack hostneutral ist.

Ein 24/7-SLA gibt es bei 0 € nicht. Wer es braucht, zahlt 5 $/Monat.

---

## 9. Kosten

| Posten | Betrag |
|---|---|
| Oracle Always Free (2 OCPU/12 GB, 200 GB, 10 TB Egress) | 0 € |
| DuckDNS-Subdomain | 0 € |
| TLS (Let's Encrypt über Caddy) | 0 € |
| Domain (optional statt DuckDNS) | 5–12 €/Jahr |
| Strom (nur bei Heimvariante) | 25–80 €/Jahr |

---

## 10. Bekannte Fallstricke

| Symptom | Ursache | Lösung |
|---|---|---|
| `Failed to initialize SFTP session` beim Export | Dienst gestoppt | Dienst starten; Export braucht die laufende Instanz |
| Caddy holt kein Zertifikat | DNS falsch oder Port 80 zu | `getent hosts DOMAIN`, Security List, iptables prüfen |
| `502` von Caddy | App startet nicht | `docker compose logs orakel` |
| `out of host capacity` | Oracle-Kapazität | andere Availability Domain, später erneut |
| Healthcheck rot nach Import | Dateirechte im Volume | Restore läuft als `orakel`-User; Volume neu erzeugen und erneut importieren |
| Instanz plötzlich weg | Idle-Reclamation | Backup einspielen, Instanz neu bauen |

---

## 11. Was danach kommt

Phase 1 (Quellenregister, Hacker-News-Adapter, Cache) läuft unabhängig vom
Hosting. Die Migration ändert keine Trading-Regel und keinen Codepfad: Es
bleibt Paper-Trading.
