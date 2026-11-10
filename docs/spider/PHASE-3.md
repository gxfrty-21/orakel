# Phase 3 — Quellenreputation, Kernaussagen und Widersprüche

**Stand:** 10. November 2026
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
   Kernaussage.
2. **Muster prüfen.** Eine Aussage braucht eine **Metrik** oder einen
   **konkreten Wert**; ohne Richtung muss mindestens der Wert bleiben. Fragen,
   Rechtsfloskeln („not for distribution“) und passive Verwaltungsmeldungen
   („Minutes … held“) werden verworfen.
3. **Gruppieren.** Der `claim_key` lautet `thema|subjekt|metrik`. Subjekt und
   Metrik werden aus normalisierten Wörtern gebildet; Monate, Zahlen und
   Prozentzeichen fliegen aus dem Subjekt. Bekannte Namen werden vereinheitlicht
   (`ECB`/`EZB` → `ezb`, `Bank of England` → `boe`).
4. **Bestätigungsgrad berechnen.** Nur **Originale verschiedener Hosts** zählen
   als unabhängige Quellen. Kopien bleiben als Belege sichtbar, bestätigen aber
   nichts.
5. **Widersprüche markieren.** Verglichen werden nur unterschiedliche Hosts
   innerhalb von sieben Tagen. Erkannt werden entgegengesetzte Richtungen
   (`steigt`/`sinkt`), `unverändert` gegen Veränderung und Verneinung gegen
   Behauptung. Jeder Widerspruch behält Grund und Sicherheit.
6. **Quellenreputation fortschreiben.** Sie startet beim Registergewicht und
   der echten Artikelqualität. Abgeschlossene Forschungsaufträge liefern
   `bestätigt`/`widerlegt`; erkannte Widersprüche werden gedämpft eingerechnet.
   Ohne Ergebnis bleibt die Quelle ausdrücklich `vorläufig`.

---

## 2. Datenmodell

| Tabelle | Inhalt |
|---|---|
| `nexus_claims` | eine Zeile je normalisierter Kernthese: `claim_key`, `kernaussage`, `quellen`, `belege`, `widersprueche`, `bestaetigungsgrad`, `status` |
| `nexus_claim_quellen` | jede Meldung zur These: `meldung_key`, `artikel_id`, `quelle_id`, `host`, `aussage`, `richtung`, `wert`, `einheit`, `negiert`, `ist_kopie`, Reputations-Snapshot |
| `nexus_widersprueche` | Paar aus zwei Meldungen, Grund, Sicherheit; keine automatische „Wahrheit“ |
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
**Kernaussagen** zeigt dieselben Zahlen. Ein Fehler in der Bewertung macht den
Lauf `ok=false`, ohne gespeicherte Meldungen zu verlieren.

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
- **Widerspruch ist Prüfbedarf, keine Wahrheit.** Die Erkennung deckt nur
  Richtung und Verneinung ab; Zahlenkonflikte und feine Abschwächungen nicht.
- **Quellenreputation ist keine Trefferquote.** Sie startet mit einem Prior
  und wird nur durch echte Auftrags-Ergebnisse belastbar. Im breiten Lauf gab
  es noch keine abgeschlossenen Aufträge; alle Quellen waren `vorläufig`.
- **Kein Claim ist auch ein Ergebnis.** 431 von 446 Meldungen im letzten Lauf
  hatten kein prüfbares Muster. Sie werden nicht künstlich zu Aussagen gemacht.

---

## 6. Tests und echter Lauf

**162 Tests grün** (10. November 2026), darunter
`tests/test_nexus_bewertung.py` mit:

- Richtung, Wert, Metrik und Subjekt aus echten Schlagzeilen,
- `lässt`/`hält` als „unverändert“, Verneinung getrennt von Richtung,
- Fragen, Rechtsfloskeln und passive Minutenmeldungen ohne Claim,
- Monats- und Prozentreste nicht im Subjekt,
- zwei unabhängige Quellen → `bestätigt`,
- Kopie als Beleg, aber nicht als unabhängige Quelle,
- Gegenrichtung und Verneinung → `widersprüchlich` mit Grund,
- Quellenreputation aus echten Ergebnissen, sonst `vorläufig`,
- Idempotenz und atomarer Rebuild.

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

## 7. Nächster Schritt

Phase 4 ist umgesetzt: Die Claims sind die Eingabe für persistente Missionen
mit drei Aufgaben, Lease, Retry und Bericht. Siehe [PHASE-4.md](PHASE-4.md).
Die Missionen rufen keine neuen Quellen ab und ersetzen keine Semantik. Auf der
Oracle-VM läuft weiterhin der alte Stand, bis dort gepullt und der Nachtlauf
neu gestartet wird.
