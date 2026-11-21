# Phase 3 — Quellenreputation, Kernaussagen und Widersprüche

**Stand:** 16. November 2026
**Grundlage:** `orakel/nexus/bewertung.py`, `orakel/db.py`
(`nexus_claims`, `nexus_claim_quellen`, `nexus_widersprueche`,
`nexus_quellen_reputation`), `orakel/nexus/nacht.py`, `orakel/nexus/status.py`,
`orakel/web.py`, `orakel/web/static/app.js`

---

## 1. Was jetzt passiert

Nachdem der Nachtlauf Meldungen gespeichert hat, bewertet er sie
regelbasiert. Es gibt kein Sprachmodell und keine semantische Wahrheit.

1. **Kernaussage extrahieren.** Zuerst der Titel, nur bei fehlendem Muster der
   erste Satz der Zusammenfassung. Eine Meldung ergibt höchstens eine
   Kernaussage. Neben Thema, Subjekt, Metrik, Richtung, Wert, Einheit und
   Verneinung werden `zeitraum`, `bedingung` und `sicherheit` erfasst.
2. **Muster prüfen.** Eine Aussage braucht eine **Metrik** oder einen
   **konkreten Wert**; ohne Richtung muss mindestens der Wert bleiben. Fragen,
   Rechtsfloskeln („not for distribution“) und passive Verwaltungsmeldungen
   („Minutes … held“) werden verworfen. `zeitraum` wird nur aus expliziten
   Datumsangaben gesetzt; relative Angaben wie „heute“ werden nicht geraten.
   `bedingung` übernimmt eine erkennbare Wenn-/Falls-Klausel als Text. Die
   `sicherheit` ist eine Extraktionsheuristik, keine Quellenreputation.
3. **Gruppieren.** Der `claim_key` lautet `thema|subjekt|metrik` und bekommt bei
   explizitem Zeitraum die Endung `|zeitraum=YYYY-MM` bzw. `YYYY-Qn`.
   Subjekt und Metrik werden aus normalisierten Wörtern gebildet; Monate,
   Zahlen und Prozentzeichen fliegen aus dem Subjekt. Bekannte Namen werden
   vereinheitlicht (`ECB`/`EZB` → `ezb`, `Bank of England` → `boe`).
4. **Bestätigungsgrad berechnen.** Nur **Originale verschiedener Hosts** zählen
   als unabhängige Quellen. Kopien bleiben als Belege sichtbar, bestätigen aber
   nichts.
5. **Widersprüche markieren.** Verglichen werden nur unterschiedliche Hosts
   innerhalb von sieben Tagen. Explizit verschiedene Zeiträume sind kein
   Widerspruch. Erkannt werden entgegengesetzte Richtungen (`steigt`/`sinkt`),
   `unverändert` gegen Veränderung, Verneinung gegen Behauptung, unvereinbare
   Zahlenwerte bei gleicher Einheit sowie bedingte gegen unbedingte Aussage.
   `%`, `pp` und `bp` werden für den Zahlenvergleich kontrolliert umgerechnet
   (1 pp = 1 % = 100 bp); gespeichert bleiben die Originalwerte. Die
   Gleichsetzung von Prozent und Prozentpunkten ist nur eine
   Vergleichsannahme, keine Aussage über ihre Bedeutung im Kontext.
   Jeder Widerspruch behält Grund und Sicherheit; die Widerspruchssicherheit
   wird durch die Extraktionssicherheit der schwächeren Aussage begrenzt.
6. **Quellenreputation fortschreiben.** Sie startet beim Registergewicht und
   der echten Artikelqualität. Abgeschlossene Forschungsaufträge liefern
   `bestätigt`/`widerlegt`; erkannte Widersprüche werden gedämpft eingerechnet.
   Ohne Ergebnis bleibt die Quelle ausdrücklich `vorläufig`.

---

## 2. Datenmodell

| Tabelle | Inhalt |
|---|---|
| `nexus_claims` | eine Zeile je normalisierter Kernthese: `claim_key`, `kernaussage`, `zeitraum`, `bedingung`, `sicherheit`, `quellen`, `belege`, `widersprueche`, `bestaetigungsgrad`, `status` |
| `nexus_claim_quellen` | jede Meldung zur These: `meldung_key`, `artikel_id`, `quelle_id`, `host`, `aussage`, `richtung`, `wert`, `einheit`, `negiert`, `zeitraum`, `bedingung`, `sicherheit`, `ist_kopie`, Reputations-Snapshot |
| `nexus_widersprueche` | Paar aus zwei Meldungen, Grund, Sicherheit und normierte Vergleichswerte (`wert_a_bp`, `wert_b_bp`; `NULL`, wenn nicht umrechenbar); keine automatische „Wahrheit“ |
| `nexus_quellen_reputation` | Snapshot je Registerquelle: Artikel, Analysiert, Bestätigt, Widerlegt, Widersprüche, Reputation, Vertrauensstufe |

Der Rebuild ist atomar: `nexus_bewertung_ersetzen` löscht und schreibt in einer
Transaktion. Ein abgebrochener Lauf hinterlässt keinen halben Bewertungsstand.
Die Bewertung ist idempotent; gleiche Meldungen ergeben gleiche Gruppen.

---

## 3. Formeln und Schwellen

**Bestätigungsgrad:**

```
quellen_faktor   = min(1, quellen / 3)
belege_faktor    = min(1, belege / 3)
grad             = 0,5·quellen_faktor + 0,3·Ø_quellenreputation
                   + 0,2·belege_faktor
bei Widerspruch: grad = grad · 0,5
```

**Status:**

| Status | Bedingung |
|---|---|
| `bestätigt` | mindestens 2 unabhängige Original-Hosts und `grad ≥ 0,70`, kein Widerspruch |
| `teilweise` | `grad ≥ 0,55`, aber keine vollständige Bestätigung |
| `unbestätigt` | darunter |
| `widersprüchlich` | mindestens ein erkannter Widerspruch; hat Vorrang |

**Quellenreputation:**

```
prior = 0,5·Registergewicht + 0,5·Ø-Artikelqualität
reputation = (prior·4 + bestätigt)
             / (4 + bestätigt + widerlegt + 0,5·Widersprüche)
```

Die 4 ist ein bewusster Prior-Gewichtungsfaktor: Ohne Ergebnisse bleibt die
Quelle nahe ihrem Registergewicht. `vertrauen` ist `belegt`, sobald echte
Auftrags-Ergebnisse vorliegen, sonst `vorläufig`.

---

## 4. Schnittstellen

`GET /api/nexus/status` liefert zusätzlich:

```json
"claims": {
  "statistik": {"gesamt": 12, "nach_status": {"unbestätigt": 11, "teilweise": 1},
                "belege": 15, "widersprueche": 0, "quellen": 47,
                "bestaetigungsgrad": 0.501},
  "top": [],
  "widersprueche": []
},
"reputation": []
```

`GET /api/nexus/claims?status=widersprüchlich&limit=50` liefert Claims,
Widersprüche, Statistik und die vollständige Reputationsliste. Der Nachtlauf
schreibt seine Bewertung unter `bericht["bewertung"]`; die Dashboard-Karte
**Kernaussagen** zeigt dieselben Zahlen und je Eintrag zusätzlich Zeitraum,
Bedingung und Extraktionssicherheit. Bei erkannten Konflikten stehen direkt am
Claim außerdem Widerspruchsgrund, Widerspruchssicherheit, normalisierte
Vergleichswerte in bp (falls beide Werte umrechenbar sind) und die beiden
beteiligten Quellen (`quelle_a` ↔ `quelle_b`). Fehlende Angaben
erscheinen als `–`, nicht als geratene Werte. Ein Fehler in der Bewertung macht den Lauf `ok=false`, ohne
gespeicherte Meldungen zu verlieren.

Manuell neu berechnen:

```bash
python -m orakel.nexus bewertung
```

Den Datenbankpfad nimmt der Befehl aus `config.toml` (`[basis] db_pfad`);
`ORAKEL_DB_PFAD` sticht ihn. `--db` ist nur für einen anderen Bestand nötig.

---

## 5. Ehrliche Grenzen

- **Keine Semantik.** Gruppiert wird über Wörter, nicht über Bedeutung. Zwei
  Aussagen zur selben Sache können getrennt bleiben; ähnliche Sätze können
  falsch zusammenlaufen.
- **Nur Titel und erste Zusammenfassung.** Kein Volltext, keine Entitäten,
  keine Zitate, keine Übersetzung.
- **Deutsch und Englisch.** Andere Sprachen werden nur erfasst, wenn ihre
  Wörter zufällig in den Listen stehen. Das ist keine mehrsprachige Analyse.
- **Eine Kernaussage je Meldung.** Ein Artikel mit mehreren Aussagen verliert
  die übrigen; das ist bewusst konservativ.
- **Kopien bestätigen nicht.** Auch eine Kopie von einem anderen Host bleibt
  Kopie. Das kann echte unabhängige Berichterstattung unterschätzen.
- **Widerspruch ist Prüfbedarf, keine Wahrheit.** Die Erkennung vergleicht
  strukturierte Felder, aber keine Bedeutung. Sie deckt keine feinen
  Abschwächungen oder impliziten Bedingungen ab. Nur `%`, `pp` und `bp` werden
  umgerechnet; andere Einheiten und Währungen bleiben ohne Zahlenvergleich.
  `pp` wird dabei wie `%` mit 100 bp angesetzt. Diese Annahme ersetzt keine
  semantische Prüfung, ob eine Prozentänderung oder eine Prozentpunktdifferenz
  gemeint ist.
  „Bedingung gegen unbedingte Aussage“ ist ein Prüfhinweis, kein bewiesener
  Widerspruch.
- **Zeiträume sind nur explizit.** Relative Angaben, fehlende Datumsbezüge und
  unterschiedliche Perioden werden nicht interpretiert. Der Sieben-Tage-Filter
  bezieht sich auf den Abrufzeitpunkt, nicht auf den Aussagezeitraum.
- **Untere Darstellungsgrenze.** Die Kernaussagen-Karte wird bei 240 px
  unterstützt. Dort ist das Panel 208 px breit (206 px Innenbreite), die
  Quellenzeile misst 178 px und bricht zweizeilig um; KPI-Kacheln und
  Claim-Grid wechseln auf eine Spalte. Die Seite bleibt mit
  `scrollWidth === clientWidth === 240` ohne horizontalen Überlauf. Kopf- und
  Navigationsleiste brechen kompakt um. Die zwölf Ansichten werden bei 240 px
  in normaler Schrift geprüft (`240px: 12/12`); der volle 250-%-Lauf bei
  240 px bleibt ausserhalb der Zusage, die CI prüft 250 % bei 360/320/280 px.
  240 px ist die untere geprüfte Breite und keine allgemeine Mindestbreite für alle anderen
  Ansichten; darunter gibt es keine Layoutzusage.
- **Quellenreputation ist keine Trefferquote.** Sie startet mit einem Prior
  und wird nur durch echte Auftrags-Ergebnisse belastbar. Im breiten Lauf gab
  es noch keine abgeschlossenen Aufträge; alle Quellen waren `vorläufig`.
- **Kein Claim ist auch ein Ergebnis.** 431 von 446 Meldungen im letzten Lauf
  hatten kein prüfbares Muster. Sie werden nicht künstlich zu Aussagen gemacht.

---

## 6. Tests und echter Lauf

Die Nexus-Bewertungstests in `tests/test_nexus_bewertung.py` prüfen unter
anderem:

- Richtung, Wert, Metrik und Subjekt aus echten Schlagzeilen,
- `lässt`/`hält` als „unverändert“, Verneinung getrennt von Richtung,
- Fragen, Rechtsfloskeln und passive Minutenmeldungen ohne Claim,
- Monats- und Prozentreste nicht im Subjekt,
- expliziten Zeitraum, Bedingung und Extraktionssicherheit,
- getrennte Claims für verschiedene Zeiträume, aber keinen Widerspruch daraus,
- keine Erfindung eines Zeitraums aus „heute“; unbekannt und explizit bleiben
  getrennt,
- unterschiedliche Bedingungen ohne harten Widerspruch,
- Zahlenkonflikt bei gleicher Richtung und gleichem Zeitraum,
- gleichwertige Angaben in Prozent, Prozentpunkten und Basispunkten ohne
  Widerspruch,
- Zahlenkonflikt bei abweichenden Prozent-, Prozentpunkte- oder
  Basispunkte-Werten,
- gespeicherte normalisierte Vergleichswerte in Basispunkten für Widersprüche
  mit abweichenden, umrechenbaren Zahlen,
- keine Zahlenkonflikte bei nicht umrechenbaren Einheiten,
- `pp`, `Prozentpunkte`, englische `percentage points` und `bps` werden als Einheiten erkannt,
- `pp` in Fremdwörtern wie „Apps“, „Kipppunkt“ oder „Grappas“ wird nicht als
  Einheit gewertet; nur die eigenständige Zeichenfolge nach einer Zahl zählt,
- zusätzlich sieben echte RSS-Schlagzeilen mit pp-Fremdwörtern aus
  `tests/fixtures/nexus_pp_fremdwoerter_rss.json` geprüft; keine davon ergibt
  eine pp-Einheit,
- bedingte gegen unbedingte Aussage als Prüfbedarf,
- zwei unabhängige Quellen → `bestätigt`,
- Kopie als Beleg, aber nicht als unabhängige Quelle,
- Gegenrichtung und Verneinung → `widersprüchlich` mit Grund,
- Quellenreputation aus echten Ergebnissen, sonst `vorläufig`,
- Idempotenz und atomarer Rebuild.

**Getrennte Claim- und pp-Baseline:** Der allgemeine Claim-Korpus enthält 34
reale RSS-Meldungen aus dem Seed-Snapshot. Die fünf gezielten pp-Meldungen aus
echten Google-News-RSS-Suchen liegen separat in
`tests/fixtures/nexus_pp_probe_korpus.json`. Dadurch bleiben die
34-Meldungen-Metriken mit der ursprünglichen Basis vergleichbar; pp-Werte
werden nicht in die allgemeinen Precision-/Recall-Werte eingemischt.

Allgemeiner Claim-Korpus (34 Meldungen):

| Messwert | Ergebnis |
|---|---:|
| Erwartete Claims | 4 |
| Erkannte Claims | 2 |
| Vollständig richtige Claims | 1 |
| Claim-Precision | 0.5 |
| Claim-Recall | 0.25 |

Die drei Abweichungen sind `seed-021` (BBC, „My mortgage is going up…“: Subjekt
`uk` statt `mortgage going month how`, Metrik `interest rate` statt `rates`)
sowie `seed-023` (BBC, „AI stocks climb…“) und `seed-024` (BBC, „Why the US
midterms…“), bei denen der Claim nicht erkannt wurde. Reproduzierbar mit:

```bash
python scripts/nexus_claim_baseline.py \
  --output-dir artifacts/nexus-claim-baseline
```

**pp_probe (5 Meldungen, getrennt):** Die fünf Fälle stammen aus echten
Google-News-RSS-Suchen: zwei deutschsprachige Treffer nach „Prozentpunkte“
(Tagesschau und Spiegel) sowie drei englischsprachige Treffer nach
„percentage points“ (CBS News, ERR und Tax Foundation). Die Originalseiten
wurden am 15. bzw. 16. November 2026 geprüft; alle fünf RSS-Titel enthalten
einen konkreten pp-Wert. Die Extraktion erkennt alle fünf Einheiten. Für die
strengen pp-Metriken ist die erkannte Einheit `pp` die Zulassungsbedingung;
zusätzlich werden Subjekt, Metrik, Richtung, Wert und Negation einzeln
verglichen. Die Einheit steht als eigene Zeile in der Feldtabelle, die strikte
Quote hängt aber auch von den fünf weiteren Feldern ab. Ein nicht vollständig
passender vorhergesagter pp-Claim zählt als FP, ein nicht vollständig passender
erwarteter pp-Claim als FN; bei Feldfehlern kann derselbe Fall als FP und FN
zählen. Der Bericht weist TP, FP und FN für jeden Fall einzeln aus
(`tp`/`fp`/`fn` in `messwerte.json`).

| Messwert | Ergebnis |
|---|---:|
| Erwartete pp-Claims | 5 |
| Vorhergesagte pp-Claims | 5 |
| Korrekte pp-Einheiten (nur Einheit) | 5 |
| TP (strikt) | 5 |
| FP (strikt) | 0 |
| FN (strikt) | 0 |
| pp-Precision (nur Einheit) | 1.0 |
| pp-Recall (nur Einheit) | 1.0 |
| pp-Precision (strikt) | 1.0 |
| pp-Recall (strikt) | 1.0 |

Strikte Feldtreffer (jeweils 5 geprüft):

| Feld | Treffer | Geprüft |
|---|---:|---:|
| `einheit` | 5 | 5 |
| `subjekt` | 5 | 5 |
| `metrik` | 5 | 5 |
| `richtung` | 5 | 5 |
| `wert` | 5 | 5 |
| `negiert` | 5 | 5 |

Die pp-Fälle sind `rss-pp-001` („US-Notenbank Fed erhöht den Leitzins um 0,25
Prozentpunkte“), `rss-pp-002` („USA: Notenbank Fed senkt Leitzins um 0,25
Prozentpunkte“), `rss-pp-003` („Federal Reserve lowers interest rates by 0.50
percentage points in first cut since 2020“), `rss-pp-004` („European Central
Bank cuts key interest rates by 0.25 percentage points“) und `rss-pp-005`
(„Tariffs Increased Retail Prices of Imports by 7 Percentage Points Prior to
Supreme Court Ruling“). Die Stichprobe ist gezielt und klein (n=5); sie belegt,
dass der Messpfad für deutsche und englische pp-Angaben funktioniert, ist aber
**keine repräsentative Schätzung** der pp-Genauigkeit im gesamten
Nachrichtenstrom. In diesem Lauf gibt es weder auf der Einheiten- noch auf der
strikten Feldebene pp-spezifische False Positives oder False Negatives.
Reproduzierbar mit:

```bash
python scripts/nexus_claim_baseline.py \
  --korpus tests/fixtures/nexus_pp_probe_korpus.json \
  --output-dir artifacts/nexus-pp-probe
```

**Optional: gemischte Ansicht.** Wer die fünf pp-Meldungen bewusst zusammen
mit den 34 Claim-Meldungen sehen will, schaltet die Diagnoseansicht explizit
ein. Sie ist kein Standardlauf und ersetzt keine der beiden Baselines:

```bash
python scripts/nexus_claim_baseline.py --gemischt \
  --output-dir artifacts/nexus-gemischt
```

Die Auswertung umfasst dann 39 Meldungen; die pp-Fälle beeinflussen
Claim-Precision, Claim-Recall und Claim-Yield. Der Bericht kennzeichnet die
Ansicht als `gemischt` und als „Nur Diagnose“.

Die tatsächliche Abdeckung der 32 englischen Registerfeeds — Abruferfolg,
Aktualität und pp-Ausbeute — steht als [Matrix in FEED-ABDECKUNG.md](FEED-ABDECKUNG.md).

**Echter lokaler Lauf** mit zwölf produktiven Quellen (u. a. EZB, Fed, Bank of
England, Bank of Japan, BBC, Guardian, WHO, UN):

| Messwert | Ergebnis |
|---|---|
| Meldungen | 446 |
| gespeichert | 415 |
| Dubletten | 31 |
| Fehler | 0 |
| Kernaussagen | 12 |
| Belege | 15 |
| `unbestätigt` | 11 |
| `teilweise` | 1 |
| `bestätigt` | 0 |
| Widersprüche | 0 |
| Quellen im Reputations-Snapshot | 47 |

Die 0 Widersprüche sind kein Beweis, dass keine existieren: In diesem Lauf
haben die Feeds keine gegensätzlichen Aussagen zum selben Subjekt und
derselben Metrik geliefert. Die Erkennung ist mit kontrollierten Gegenbeispielen
getestet. Die 47 Quellen sind `vorläufig`, weil noch kein Forschungsauftrag
abgeschlossen wurde; die Reputation ist derzeit Registerprior plus echte
Artikelbasis, keine gemessene Trefferquote.

---

## 7. Browser-Prüfung: 24 Befunde im 250-%-Lauf (360 px)

Ein lokaler 250-%-Lauf meldete 24 Befunde. Die Meldungen stammen aus
**`360px/lab`**. Ein separater 240-px-Durchgang in normaler Schrift war mit
`240px: 12/12` grün; er war kein 250-%-Lauf. Die Zuordnung zum 240-px-Lauf war
falsch.

| Gruppe | Anzahl | Befund |
|---|---:|---|
| Home/Live-Region | 2 | `Home` kehrt nicht zum ersten Punkt zurück (`0` statt `0.0`); die Live-Region ist danach leer. |
| Tooltip-Position | 1 | Leerer Tooltip ausserhalb des Viewports (`29–47 × 3955–3965` bei `360 × 900`). |
| Startpunkt | 5 | Datum `—`; Kapital `USD 0`; Prozentwert, Hochstand und Abstand nicht lesbar. |
| Viertelpunkt | 5 | Datum `—`; Kapital `USD 0`; Prozentwert, Hochstand und Abstand nicht lesbar. |
| Mittelpunkt | 5 | Datum `—`; Kapital `USD 0`; Prozentwert, Hochstand und Abstand nicht lesbar. |
| Dreiviertelpunkt | 5 | Datum `—`; Kapital `USD 0`; Prozentwert, Hochstand und Abstand nicht lesbar. |
| Shift+Tab | 1 | Erwartetes vorheriges Element und tatsächlich fokussiertes Element stimmen nicht überein (`donchianlookback=20 A` statt `donchian lookback=20`). |
| **Summe** | **24** | |

Ursache war der 8-Sekunden-Auto-Refresh: Er baute die fokussierte Kapitalkurve
neu auf und setzte Fokus, Tooltip und Live-Region zurück. Die 24 Meldungen sind
Folge dieses einen Zustandsverlusts. Die App pausiert den Refresh jetzt bei
Fokus im sichtbaren Lab-Detail (insbesondere auf der Kapitalkurve) nur den
Ansichts-Render; Daten und Kopfzeile werden weiter aktualisiert. Ein Fokus auf
einem Lab-Knopf in der Liste oder im ausgeblendeten Lab-Detail blockiert den
Render nicht. Die drei Refresh-Fälle (sichtbare Kurve, Lab-Knopf,
ausgeblendetes Lab-Detail) laufen als eigener deterministischer 360px/lab-Lauf
mit echter /api/report-Antwort (HTTP 200, Marker); dieser Lauf ist ohne Befund.
Der vollständige 12-Ansichten-Standardlauf wurde nach dieser Verschärfung
nicht erneut ausgeführt.

## 7a. Prüfungen zum pausierten Lab-Render

Der 250-%-Lauf prüft das Verhalten beim pausierten Render mit eigenen
Prüfungen. Sie laufen als Teil der Profile `voll` und `seed-tastatur` und sind
im Check-Manifest als Pflichtfälle hinterlegt:

- **Lab-Guard** (`text250.lab-guard`): Die Regel wird direkt über
  `window.pausiertRenderWegenLabDetail` geprüft. Fokus auf Liste, Tab, `body`
  und ein ausgeblendetes Lab dürfen den Render nicht blockieren, Fokus im
  sichtbaren Lab-Detail muss es. Zusätzlich wird die Regel am echten Fokus
  geprüft.
- **Lab-Pause** (`text250.lab-pause`): Bei pausiertem Render müssen die neuen
  Daten übernommen werden, der Status `#labNeu` sichtbar und als höfliche
  Live-Region angekündigt sein, ohne dass die Liste neu gezeichnet wird. Beim
  Verlassen des Details wird sofort neu gezeichnet, der Status verschwindet
  und der Fokus bleibt in der Liste.
- **Listen-Umsortierung** (`text250.listen-umsortierung`): Der Refresh dreht
  die Kandidatenreihenfolge um. Derselbe Kandidat bleibt ausgewählt, der
  fokussierte DOM-Knoten bleibt bestehen (Marke überlebt) und die
  Scrollposition steht.
- **Refresh-Takt** (`text250.refresh-takt`): Während eine Antwort offen ist,
  startet der Takt keinen zweiten Aufruf; im Hintergrundtab lädt er nicht, beim
  Zurückkehren sofort.

Die Prüfungen sichern bei Befunden einen Screenshot und einen
Playwright-Trace (`text250-*-trace.zip`) im Diagnose-Artefakt.

Der erfolgreiche CI-Job `text250` aus Run `43811966526` verwendete denselben
Seed und denselben Lab-Code, lief mit 74,39 s aber etwas schneller als der
lokale Lauf mit 80 s. Der 8-Sekunden-Takt traf dort deshalb nicht das
fokussierte Lab-Fenster; der CI-Erfolg ist kein Gegenbeweis für den lokalen
Befund.

## 8. Nächster Schritt

Die Phasen 4 und 5 sind umgesetzt: Die Claims sind die Eingabe für persistente
Missionen mit fünf Aufgaben, Lease, Retry, Gegenargumenten und Bericht. Siehe
[PHASE-4.md](PHASE-4.md) und [PHASE-5.md](PHASE-5.md). Die Missionen rufen
keine neuen Quellen ab und ersetzen keine Semantik. Auf der Oracle-VM läuft
weiterhin der alte Stand, bis dort gepullt und der Nachtlauf neu gestartet
wird.
