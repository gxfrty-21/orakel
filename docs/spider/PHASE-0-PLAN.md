# Phase 0 — Infrastruktur, Entscheidungen und Grenzen

**Stand:** 9. November 2026
**Entscheidungen des Owners:** ohne LLM starten · kostenloses Hosting bevorzugen ·
RSS + Hacker News zuerst · feste 3D-Kamera
**Gilt zusätzlich zu:** [NEXUS-PLAN.md](NEXUS-PLAN.md)

Dieses Dokument beantwortet den Auftrag „zeige mir zuerst den konkreten
Umsetzungsplan und die benötigte Infrastruktur" — mit echten Preisen, echten
Grenzen und ohne die Vision zu verkleinern.

---

## 1. Entscheidungen

| Punkt | Entscheidung | Konsequenz |
|---|---|---|
| Sprachmodell | Start **ohne** LLM, regelbasiert, 0 € | kein Übersetzen, kein freies Zusammenfassen; Provider-Schnittstelle wird vorbereitet |
| Hosting | zuerst **kostenlos**, Railway Hobby nur nach gemeinsamer Entscheidung | Migration von Railway ist Teil von Phase 0 |
| Quellen | **RSS + Hacker News** (+ frei zugängliche APIs) | Quellen-Adapter von Anfang an mehrquellig; Reddit später |
| 3D | **feste Kamera** auf Spinne, Recherchefläche, Globus | begehbarer Nexus erst nach echten Missionsdaten |

Unverändert: Paper-Trading, keine echten Orders, keine kostenpflichtigen Dienste
ohne Zustimmung, keine Fake-Aktivitäten.

---

## 2. Kostenloses Hosting — ehrlicher Vergleich

### 2.1 Oracle Cloud Always Free (Empfehlung)

| Ressource | Stand 9.11.2026 |
|---|---|
| Arm-Compute (VM.Standard.A1.Flex) | **2 OCPU + 12 GB RAM** dauerhaft (1.500 OCPU-h / 9.000 GB-h pro Monat) |
| AMD-Micro | 2 × VM.Standard.E2.1.Micro mit je 1 GB RAM |
| Block-Storage | 200 GB gesamt (Boot-Volume min. 50 GB) |
| Egress | 10 TB/Monat |
| Kosten | 0 €; Kreditkarte nur zur Verifikation, keine Abbuchung ohne Upgrade |

**Haken, die ich nicht verschweige:**

- **Halbierung:** Bis 15. Juni 2026 waren es 4 OCPU/24 GB. Oracle hat ohne
  Ankündigung halbiert. Die Zusage ist nicht dauerhaft garantiert.
- **Idle-Reclamation:** Oracle darf eine Instanz zurückholen, wenn über 7 Tage
  CPU-P95 < 20 %, Netzwerk < 20 % **und** (bei A1) RAM < 20 % liegen. Ein
  Orakel-Dienst mit ~300 MB RAM und wenig Last fällt in dieses Raster — obwohl
  er durchgehend läuft. Das ist ein echtes Betriebsrisiko, kein Gerücht.
- **Kapazität:** „out of host capacity" ist in beliebten Regionen häufig; man
  braucht Geduld oder eine andere Availability Domain.
- **Home-Region:** Always Free gilt nur in der Heimatregion.

**Für uns relevant:** 12 GB RAM sind genug für Dienst + SQLite + später ein
kleines lokales Modell (7B Q4 auf CPU, langsam aber nutzbar). Das ist der
Grund für die Empfehlung trotz der Haken.

### 2.2 Google Cloud Free Tier (Fallback)

1 × e2-micro (2 geteilte vCPU, **1 GB RAM**) in `us-west1`, `us-central1` oder
`us-east1`, 30 GB Standard-Disk, **1 GB Egress pro Monat** (ohne China und
Australien). Dauerhaft kostenlos, Karte erforderlich.

**Haken:** 1 GB RAM ist für Build + pandas/numpy + uvicorn knapp (Swap nötig,
Build besser außerhalb). 1 GB Egress pro Monat ist für ein aktiv genutztes
Dashboard zu wenig — ein Polling-Dashboard kann das in wenigen Tagen
überschreiten. Als Hintergrundbetrieb ohne viel Web-Traffic brauchbar, als
täglich benutztes Dashboard nicht.

### 2.3 Heimrechner (dritte Option, gut für LLM-Tests)

0 € Hardware, wenn ein Rechner ohnehin läuft. Strom ist der echte Preis:
10 W Dauerlast ≈ 88 kWh/Jahr ≈ 25–30 € bei 0,30 €/kWh; 30 W ≈ 80 €/Jahr.
Öffentliche Erreichbarkeit ohne Portfreigabe über einen kostenlosen Tunnel
(z. B. Cloudflare Tunnel). Verfügbarkeit hängt an Internet und Strom.

### 2.4 Railway Hobby (nicht jetzt)

5 $/Monat, inklusive 5 $ Nutzung — deckt diesen Dienst voraussichtlich. Wird
erst nach gemeinsamer Entscheidung aktiviert. Der Trial läuft in wenigen Wochen
ab; die Migration muss vorher stehen.

---

## 3. Empfehlung und Migrationspfad

**Ziel:** Oracle Always Free (2 OCPU/12 GB) als Primärsystem, Google e2-micro
als Fallback, Heimrechner für LLM-Experimente. Railway bleibt bis zur Migration
unverändert.

Schritte (Phase 0, 1–2 Tage):

1. Oracle-Konto anlegen, Instanz in der Heimatregion versuchen; bei
   „out of capacity" andere Availability Domain oder später erneut.
2. Docker + Compose installieren, Image aus dem Repository bauen.
3. Volume unter `/srv/orakel/data` einhängen, `ORAKEL_DATA=/data` setzen.
4. Reverse Proxy mit TLS: Caddy (Ports 80/443) oder Cloudflare Tunnel ohne
   offene Ports.
5. Daten aus Railway übernehmen: `orakel.db`, `vault/`, `daten/` (Anleitung in
   `RAILWAY.md`, Abschnitt Backup), danach Healthcheck und Login prüfen.
6. Erst wenn alles läuft: Railway-Deployment stoppen.

**Hostneutralität ist bereits gegeben:** `Dockerfile`, `docker-compose.yml`,
`docker-entrypoint.sh` mit `PORT` und `/data`, Healthcheck auf `/api/health`,
SQLite als einzige Datenhaltung. Ein Umzug ist damit ein Umzug von Dateien und
Umgebungsvariablen, kein Umbau.

---

## 4. Lokales Sprachmodell — vorbereitet, nicht eingebaut

Geplant ist eine schmale Schnittstelle `orakel/nexus/llm.py`:

```
Provider (Protocol)
  verfuegbar() -> bool
  zusammenfassen(text, max_saetze) -> str
  uebersetzen(text, zielsprache) -> str
  hypothese_formulieren(beobachtung) -> str
```

Standard ist `KeinModell`: Es liefert **nichts** und die aufrufenden Stellen
arbeiten regelbasiert weiter. Später kommt `OllamaProvider` (HTTP auf
`127.0.0.1:11434`) dazu — lokal, kostenlos, ohne Cloud. Es gibt keinen stillen
Fallback, der Ergebnisse erfindet: Fehlt das Modell, bleibt die Ausgabe
regelbasiert und wird als solche gekennzeichnet.

### Schwellenwerte (für llama.cpp/Ollama, Q4-Quantisierung)

| Modellgröße | RAM/VRAM | Alltagstauglich |
|---|---|---|
| 1–2B | 2–3 GB | ja, auch CPU |
| 3–4B | 4–6 GB | ja, CPU langsam |
| 7–8B | 8–12 GB | CPU: wenige Tokens/s; GPU 8 GB: gut |
| 13B | 16–24 GB | nur mit GPU sinnvoll |
| Embeddings (384-dim) | < 1 GB | immer, CPU genügt |

**Wichtig:** Ich habe keinen Zugriff auf deinen Rechner. Ob er reicht, klärt
`scripts/systemcheck.ps1` (Windows) bzw. `scripts/systemcheck.sh` — es liest
nur Werte aus, ändert nichts. Ausgabe hier einfügen, dann bekommst du eine
konkrete Einschätzung statt einer Vermutung.

---

## 5. Quellen — Architektur von Anfang an mehrquellig

Adapter-Typen in `orakel/nexus/quellen.py`:

| Typ | Beispiel | Zugang |
|---|---|---|
| `rss` | Notenbanken, Presse, Statistik, arXiv | frei, robots.txt wird geprüft |
| `json_api` | Hacker News (Firebase) | frei, keine Authentifizierung |
| `oauth` | Reddit | **später**, App-Registrierung nötig |
| `csv` | Statistikämter, Rohdaten | frei, Datei-Download |

Hacker News wird über die offizielle Firebase-API gelesen
(`/v0/topstories.json`, `/v0/item/<id>.json`), mit eigenem User-Agent,
Rate-Limit und Cache. Keine Umgehung von Zugangsbeschränkungen; was robots.txt
oder Nutzungsbedingungen verbieten, wird nicht abgerufen.

Erweiterung auf Reddit bleibt ausdrücklich vorgesehen: Der Adapter bekommt eine
eigene Authentifizierung, die Tokens liegen außerhalb des Repositories.

---

## 6. 3D — feste Kamera zuerst

`orakel/web/static/nexus3d.js`, Ansicht `#v-nexus`:

- feste Kamera auf eine holografische Recherchefläche, dahinter der bestehende
  Globus;
- Spinne mit Körper und acht Beinen, Inverse Kinematics, ruhiger Idle-Zustand;
- Beinbewegung und Aufleuchten **nur** aus echten Ereignissen
  (`/api/nexus/status`: laufende Aufgaben, neue Artikel, Warnungen);
- keine Schleifen, die Aktivität vortäuschen, wenn keine Daten vorliegen.

Der begehbare Raum bleibt als spätere Erweiterung geplant; die Kamera-Logik
wird so gebaut, dass sie später durch eine freie Navigation ersetzt werden kann.

---

## 7. Phasen (angepasst)

| Phase | Inhalt | Aufwand |
|---|---|---|
| **0** | Hosting-Migration, Volume, TLS, Datenübernahme | 1–2 Tage |
| **1** | Quellenregister 40+, Hacker-News-Adapter, ETag-Cache | 3 Tage |
| **2** | Spracherkennung, SimHash-Dedup, Cluster | 2 Tage |
| **3** | Quellenreputation, Bestätigung, Widersprüche | 2–3 Tage |
| **4** | Missionen, Queue, Fortschritt, API | 3 Tage |
| **5** | Agentenrollen, Gegenargument-Agent, **3D feste Kamera** | 4 Tage |

**Stand 10. November 2026:** Agentenrollen, Gegenargument-Agent und
Vault-/Intel-Übergabe sind umgesetzt; die 3D-Kamera bleibt offen, bis echte
Missionsdaten vorliegen. Siehe [PHASE-5.md](PHASE-5.md).
| **6** | Wissensgraph, Prognosekontrolle | 3 Tage |
| **7** | begehbarer Nexus | 4–6 Tage |
| **8** | Dauerbetrieb, Backoff, Limits, Monitoring | 2 Tage |

Die 3D-Ansicht kommt bewusst nach den Missionen: Vorher gäbe es nichts Echtes
zu zeigen — und genau das ist verboten.

---

## 8. Kosten (transparent)

| Posten | Kosten |
|---|---|
| Hosting Oracle Always Free | 0 € |
| Domain | nicht nötig (Tunnel/`*.oraclecloud.com` oder Caddy mit Subdomain) |
| Sprachmodell lokal | 0 € |
| Quellen (RSS, HN) | 0 € |
| **Summe laufend** | **0 €** |
| Einmalig: Kreditkarte zur Verifikation | keine Abbuchung ohne Upgrade |
| Optional Heimrechner-Strom | 25–80 €/Jahr |

Sobald ein kostenpflichtiger Dienst dazukommen soll, frage ich vorher.

---

## 9. Risiken

| Risiko | Wirkung | Gegenmaßnahme |
|---|---|---|
| Oracle halbiert erneut oder streicht Always Free | Umzug nötig | hostneutraler Docker-Stack, Backups außerhalb |
| Idle-Reclamation | Instanz weg | täglicher Heartbeat, Backup, Neuaufbau in Minuten |
| „out of host capacity" | keine Instanz | andere Availability Domain, GCP-Fallback |
| GCP-Egress 1 GB | Dashboard bricht | GCP nur als Hintergrundbetrieb |
| Heimrechner-Ausfall | Dienst weg | nur für LLM-Tests, nicht für Produktion |
| Trial-Ende Railway | Datenverlust | Volume-Backup vor Ablauf |

---

## 10. Nächster Schritt

1. `scripts/systemcheck.ps1` ausführen und Ausgabe hier einfügen → Einschätzung
   zum lokalen Modell.
2. Entscheidung: Oracle-Konto jetzt anlegen (ich begleite die Schritte) oder
   zuerst Phase 1 auf Railway weiterbauen und die Migration später.
3. Danach Phase 1: Quellenregister, Hacker-News-Adapter, Cache — mit Tests.
