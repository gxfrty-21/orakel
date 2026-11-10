# Phase 5 — Agentenrollen, Gegenargumente und Übergabe

**Stand:** 10. November 2026
**Grundlage:** `orakel/nexus/rollen.py`, `orakel/nexus/gegenargument.py`,
`orakel/nexus/missionen.py`, `orakel/knowledge.py`, `orakel/db.py`

---

## 1. Was jetzt passiert

Die Missionkette aus Phase 4 ist um zwei Aufgaben erweitert:

```text
lage → pruefung → gegenargument → bericht → weitergabe
```

Es gibt weiterhin **keinen LLM-Aufruf und keine erfundene Agentenaktivität**.
Die 15 Rollen sind deterministische Prüfungen. Jede schreibt ein echtes
Ergebnis in `agenten_laeufe`; eine Rolle ohne Befund meldet ausdrücklich
„geprüft, kein Befund“.

---

## 2. Die 15 Nexus-Prüfrollen

| Rolle | Prüfung |
|---|---|
| `N1 Quellenlage` | Gibt es überhaupt passende Kernaussagen? |
| `N2 Unabhängigkeit` | Hat jeder Claim mindestens zwei unabhängige Hosts? |
| `N3 Kopien` | Werden Kopien fälschlich als unabhängige Belege gezählt? |
| `N4 Widerspruch` | Welche gespeicherten Widersprüche betreffen die Claims? |
| `N5 Zahlenkonflikt` | Liegen zum selben Claim verschiedene Werte vor? |
| `N6 Aktualität` | Sind Zeitstempel vorhanden und jünger als 30 Tage? |
| `N7 Reputation` | Wie hoch ist die durchschnittliche Belegreputation? |
| `N8 Abdeckung` | War die Stichwortsuche erfolgreich oder breit/leer? |
| `N9 Gegenargument` | Welche Alternativerklärungen folgen aus den Belegen? |
| `N10 Gegenbeleg` | Gibt es Prüfbedarf oder fehlende Gegenbelege? |
| `N11 Herkunft` | Hat jeder Beleg Host und Quelle? |
| `N12 Zeitfenster` | Ist die Aktualisierung vor der ersten Sichtung? |
| `N13 Reputationsabgleich` | Ist ein Claim bestätigt, obwohl alle Quellen schwach sind? |
| `N14 Datenintegrität` | Sind Status und Bestätigungsgrad gültig? |
| `N15 Zahlenintegrität` | Hat jeder Zahlenwert eine Einheit? |

Die Rollen laufen in fester Reihenfolge. Ein Fehler in einer Rolle stoppt die
übrigen nicht. Das Ergebnis wird als Liste `agenten` im Missionsbericht
gespeichert; jedes Element enthält Kennung, Name, Aufgabe, Status und Befunde.
Zusätzlich stehen die Kurzprotokolle in `agenten_laeufe` und erscheinen damit
in der bestehenden Aktivitätsanzeige.

**Wichtig:** Das sind Prüfrollen, keine 15 unabhängigen Sprachmodelle. Sie
können zählen, vergleichen und Regelverstöße markieren; sie verstehen keine
freie Sprache und ersetzen keine semantische Recherche.

---

## 3. Gegenargument-Agent

`orakel/nexus/gegenargument.py` erzeugt aus den vorhandenen Prüfdaten
Alternativerklärungen. Er ruft keine Quelle ab und behauptet keine neue
Wahrheit. Die Regeln:

- **Widerspruch:** Eine gespeicherte Gegenposition wird mit Quelle A und
  Quelle B genannt. Sie ist eine Alternative, kein automatischer Beweis.
- **Einzelquelle:** Fehlt eine zweite unabhängige Originalquelle, kann die
  Aussage eine einzelne redaktionelle Einschätzung sein.
- **Kopien:** Kopien können auf einer gemeinsamen Vorlage beruhen; sie
  bestätigen die Aussage nicht unabhängig.
- **Zahlenkonflikt:** Mehrere Werte zum selben Claim können unterschiedliche
  Stichtage oder Abgrenzungen bedeuten — oder ein echter Konflikt sein.
- **Fehlende Belege:** Ohne Einzelbelege ist die Aussage nicht nachprüfbar.
- **Schwache Reputation:** Eine Übereinstimmung kann institutionell geprägt
  sein, wenn alle Belege eine niedrige Reputation haben.
- **Keine Widersprüche:** Das ist kein Konsensbeweis. Geprüft wurden nur
  gespeicherte Claims, bestimmte Hosts und ein begrenztes Zeitfenster.
- **Datenlücke:** Ohne Kernaussage ist die Lücke selbst der Befund.

Der Agent liefert höchstens 20 Gegenargumente. Der Bericht übernimmt die
wichtigsten acht in den Abschnitt `Gegenargumente`; alle bleiben strukturiert
im JSON erhalten.

---

## 4. Vault- und Intel-Übergabe

Die Aufgabe `weitergabe` läuft erst, wenn der Bericht vorliegt.

### IntelNetz

- Abteilung nach Thema: Strategie → Labor, Risiko → Risikomanagement,
  Wissenschaft → Forschungsabteilung, Markt/Makro/Unternehmen → Trading Floor,
  sonst Wissenszentrum.
- Es wird eine echte Zeile in `intel_weiterleitungen` mit Kennung
  `WL-JJJJMMTT-NNNN` angelegt. Der Bezug enthält Mission, Titel, Thema,
  Claim-IDs, Kennzahlen und Anzahl der Gegenargumente.
- Vor dem Schreiben wird nach derselben Mission gesucht. Ein Absturz zwischen
  Intel-Schreiben und Aufgabenabschluss erzeugt deshalb keine zweite
  Weiterleitung.
- **Ohne Kernaussage** wird keine Weiterleitung erzeugt. Die Mission meldet
  `keine_weitergabe`; eine leere Mission soll keine Aktivität vortäuschen.

### Vault

- Der vollständige Bericht wird als Notiz unter `70-Wissen` abgelegt.
- Titel: `MS-… <Missionstitel>`; Tags: `nexus`, `mission`, Thema,
  `gegenargument`; Quelle: `mission:MS-…`.
- Die Notiz verlinkt die Claim-Schlüssel als Wikilinks.
- Der Web-Takt und die API übergeben `Vault(cfg.vault_ordner)`. Die CLI nutzt
  `--vault` (Standard: `vault` oder `ORAKEL_VAULT`).
- Ohne konfigurierten Vault wird die Mission nicht abgebrochen; der Bericht
  nennt ehrlich `nicht_konfiguriert`. In Web und Scheduler ist der Vault
  konfiguriert.

Die Übergabe ist **keine neue Recherche**. Sie verteilt den vorhandenen
Bericht; sie erzeugt keine Quellen, keine Orders und keine Regeländerung.

---

## 5. Schnittstellen

Die HTTP-Endpunkte aus Phase 4 bleiben unverändert. `GET /api/nexus/mission/{kennung}`
liefert jetzt zusätzlich:

```json
{
  "bericht": {
    "gegenargumente": [],
    "agenten": [],
    "kennzahlen": {"gegenargumente": 1, "pruefrollen": 15},
    "weitergabe": {
      "intel": {"status": "uebergeben", "kennung": "WL-…"},
      "vault": {"status": "geschrieben", "pfad": "…"}
    }
  }
}
```

CLI:

```bash
python -m orakel.nexus mission --titel "EZB Leitzins" \
  --auftrag "Prüfe die Datenlage zum Leitzins der EZB." --start \
  --vault /data/vault
python -m orakel.nexus mission-lauf --kennung MS-20261110-0001 \
  --vault /data/vault
```

Im Web-Takt ruft `scheduler.takt_schritt` weiterhin höchstens fünf fällige
Aufgaben pro Takt aus; die beiden neuen Aufgaben laufen über dieselbe Queue,
Lease und Retry-Logik. Der Nachtlauf legt keine Missionen an.

---

## 6. Tests und Prüfungen

**168 Tests grün** (10. November 2026). Die Missionstests umfassen jetzt sechs
Fälle:

1. vollständiger Lauf über einen simulierten Prozessneustart, inklusive 15
   Rollen, Gegenargumenten, Vault-Notiz und Intel-Weiterleitung,
2. Datenlücke ohne Claim; keine vorgetäuschte Intel-/Vault-Aktivität,
3. Fehler → Backoff → Dead-Letter, alle Folgeschritte blockiert,
4. Rückgewinnung einer abgelaufenen Lease,
5. Priorität vor Erstellungsreihenfolge,
6. Gegenargumente für Widerspruch und Kopie.

Zusätzlich:

- `node --check orakel/web/static/app.js` grün,
- `compileall` grün,
- `git diff --check` grün,
- CLI und HTTP werden mit einer temporären Datenbank geprüft; die Mission
  durchläuft fünf Aufgaben und schreibt eine Vault-Notiz sowie eine
  Intel-Weiterleitung.
- Missionen-Karte und Bericht werden im Cloud-Browser bei 432 px Breite geprüft.
  Der Bericht bleibt nach dem 8-Sekunden-Refresh offen, ist schließbar und
  erzeugt keinen horizontalen Seitenüberlauf.

---

## 7. Ehrliche Grenzen

- **Keine neuen Quellen.** Die Mission liest den vorhandenen Claim-Bestand.
- **Keine Semantik und kein LLM.** Die Rollen sind Regeln, keine Persönlichkeiten.
- **15 Rollen sind Prüfungen.** Sie führen keine autonomen Debatten und
  verändern keine Strategie.
- **Vault/Intel nur bei Daten.** Ohne Kernaussage gibt es keine Übergabe.
- **Ein SQLite-Worker.** Mehrere verteilte Worker sind nicht getestet.
- **Keine 3D-Ansicht.** Die feste 3D-Kamera/der Nexus-Raum bleibt außerhalb
  dieser Phase; zuerst müssen echte Missionsdaten und echte Aktivität da sein.
- **UI im Browser geprüft.** Missionen-Karte und Bericht wurden bei 432 px
  Breite im Cloud-Browser geprüft. Der Bericht bleibt nach dem
  8-Sekunden-Refresh offen, ist über „Schließen“ wieder schließbar und erzeugt
  keinen horizontalen Seitenüberlauf; langer Text scrollt im Bericht selbst.
- **Oracle-VM.** Dort läuft weiterhin der alte Stand, bis du pullst und den
  Takt neu startest.

---

## 8. Nächster Schritt

Phase 6 ist umgesetzt: [PHASE-6.md](PHASE-6.md) beschreibt den persistierten
Wissensgraph und die Prognosekontrolle. Erst danach ist die 3D-Darstellung
sinnvoll; die Missionen- und Übergabeschicht bleibt eine Datenquelle dafür.
