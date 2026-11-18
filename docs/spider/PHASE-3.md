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
python -m orakel.nexus bewertung --db orakel.db
```

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
  240 px ist die untere
  geprüfte Breite und keine allgemeine Mindestbreite für alle anderen
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

**pp-Baseline im echten Claim-Korpus:** Der versionierte Korpus enthält 39
reale RSS-Meldungen, davon fünf gezielt ergänzte pp-Meldungen aus echten
Google-News-RSS-Suchen: zwei deutschsprachige Treffer nach „Prozentpunkte“
(Tagesschau und Spiegel) sowie drei englischsprachige Treffer nach
„percentage points“ (CBS News, ERR und Tax Foundation). Die Originalseiten
wurden am 15. bzw. 16. November 2026 geprüft; alle fünf RSS-Titel enthalten
einen konkreten pp-Wert. Die aktuelle Extraktion erkennt alle fünf Einheiten:

| Messwert | Ergebnis |
|---|---:|
| Erwartete pp-Claims | 5 |
| Vorhergesagte pp-Claims | 5 |
| Korrekte pp-Einheiten | 5 |
| pp-Precision | 1.0 |
| pp-Recall | 1.0 |

Die pp-Fälle sind `rss-pp-001` („US-Notenbank Fed erhöht den Leitzins um 0,25
Prozentpunkte“), `rss-pp-002` („USA: Notenbank Fed senkt Leitzins um 0,25
Prozentpunkte“), `rss-pp-003` („Federal Reserve lowers interest rates by 0.50
percentage points in first cut since 2020“), `rss-pp-004` („European Central
Bank cuts key interest rates by 0.25 percentage points“) und `rss-pp-005`
(„Tariffs Increased Retail Prices of Imports by 7 Percentage Points Prior to
Supreme Court Ruling“). Die Stichprobe ist gezielt und klein (n=5); sie belegt,
dass der Messpfad für deutsche und englische pp-Angaben funktioniert, ist aber
**keine repräsentative Schätzung** der pp-Genauigkeit im gesamten
Nachrichtenstrom. Es gibt in diesem Lauf keine pp-spezifischen False Positives
oder False Negatives.
Die allgemeinen Claim-Fehler sind `seed-021` (BBC, „My mortgage is going up…“:
Subjekt `uk` statt `mortgage going month how`, Metrik `interest rate` statt
`rates`) sowie `seed-023` (BBC, „AI stocks climb…“) und `seed-024` (BBC, „Why
the US midterms…“), bei denen der Claim nicht erkannt wurde. Die Gesamtwerte
liegen bei 9 erwarteten, 7 erkannten und 6 vollständig richtigen Claims
(Precision 0.8571, Recall 0.6667). Reproduzierbar mit
`python scripts/nexus_claim_baseline.py --output-dir artifacts/nexus-claim-baseline`.

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
`240px: 12/12` grün; er war kein 250-%-Lauf. Die Zuordnung zum 240-px-Lauf
war falsch.

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
der Lab-Liste, einem anderen Lab-Element oder in einem ausgeblendeten Lab
blockiert den Render nicht. Der deterministische Test mit echter
/api/report-Antwort (HTTP 200, Marker) ist ohne Befund. Der vollständige
Standardlauf lief nach dieser Verschärfung erneut über alle zwölf Ansichten bei
360, 320 und 280 px und endete ohne Befund; er meldete `Refresh 2× geprüft
(HTTP 200, Marker)`, `Refresh-Negativ 1× geprüft`, `Lab-Fokus 3× geprüft`,
`Listen-Refresh 1× geprüft` und `240px: 12/12 Ansichten ohne horizontalen
Überlauf`. Ein voller 250-%-Lauf bei 240 px ist nicht belegt.

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
