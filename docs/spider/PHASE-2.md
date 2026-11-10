# Phase 2 — Spracherkennung, SimHash und Speicherung

**Stand:** 10. November 2026
**Grundlage:** `orakel/nexus/sprache.py`, `dedup.py`, `speicher.py`,
`orakel/db.py` (`nexus_meldungen`), `orakel/nexus/nacht.py`

---

## 1. Was jetzt passiert

Der Nachtlauf speichert Meldungen nicht mehr nur als Zahl. Für jede
Feed-Meldung:

1. **Sprache schätzen.** Zuerst über Schriftzeichen (Chinesisch, Japanisch,
   Koreanisch, Kyrillisch, Arabisch, Griechisch, Hebräisch, Devanagari), dann
   über Stoppwörter für Deutsch, Englisch, Französisch, Italienisch, Spanisch,
   Portugiesisch und Niederländisch. Bei kurzen oder unklaren Texten fällt das
   Ergebnis auf die Quellensprache zurück — mit niedriger Konfidenz und der
   Methode `quelle`.
2. **SimHash berechnen.** 64 Bit über Zeichen-5-Gramme. Das ist robuster
   gegen eingefügte Wörter als Wort-Shingles und funktioniert auch für
   Chinesisch, Japanisch und Koreanisch. Stabile Hashes über `blake2b`, damit
   der Wert nach einem Neustart gleich bleibt.
3. **Original oder Kopie bestimmen.** Der Index wird beim Start aus allen
   bereits gespeicherten Originalen aufgebaut. Ein Kandidat muss innerhalb
   von 10 Hamming-Bits liegen **und** eine Jaccard-Ähnlichkeit von mindestens
   0,55 haben. SimHash allein würde bei ähnlichem Wortschatz zu oft falsch
   alarmieren.
4. **Speichern.**
   - Das Original landet in `artikel` — mit Quelle, Typ, Titel, URL,
     Veröffentlichungsdatum, Zusammenfassung, Qualitäts-Prior und Titel-Hash.
   - Jede Meldung, auch jede Kopie, landet in `nexus_meldungen`. Die Kopie
     zeigt mit `artikel_id` auf das Original und hat `ist_original=0`.
   - Eine exakt schon gesehene Meldung (Quelle + Titel + URL) wird als
     `wiederholung` erkannt und nicht erneut geschrieben.

Die Dublettenquote ist damit messbar, ohne die Artikelliste mit Kopien zu
fluten.

---

## 2. Schema

`nexus_meldungen` ergänzt die bestehende `artikel`-Tabelle, ohne sie zu
verändern:

| Feld | Bedeutung |
|---|---|
| `meldung_key` | stabiler SHA-256 über Quelle, Titel und URL |
| `artikel_id` | Original in `artikel` |
| `cluster_id` | Kennung des Clusters (der Key des Originals) |
| `simhash` | 16 Hex-Zeichen |
| `sprache` | geschätzte Sprache |
| `sprache_konfidenz` | 0–0,95 |
| `sprache_methode` | `zeichen`, `stoppwoerter`, `quelle` oder `unbekannt` |
| `ist_original` | 1 = Original, 0 = Kopie |
| `quelle_id` | ID aus dem Register |
| `titel`, `url` | auch bei Kopien erhalten |
| `abgerufen_am` | Zeitpunkt des Laufs |

Indizes: `cluster_id`, `artikel_id`, `sprache`. Die Tabelle wird additiv beim
Öffnen der Fakten-DB angelegt; bestehende Zeilen bleiben unberührt.

---

## 3. Was das ehrlich nicht ist

- **Keine Übersetzung.** Die Sprache wird nur geschätzt, der Text bleibt in
  seiner Originalsprache.
- **Kein Verstehen.** SimHash erkennt Textähnlichkeit, keine Bedeutung. Eine
  Kopie ist eine Hypothese, kein Beweis.
- **Keine Entitäten, keine Claims, keine Quellenreputation.** Das ist Phase 3.
- **Keine Volltextanalyse.** Der Lauf speichert Titel und Zusammenfassung aus
  dem Feed, nicht die ganze Seite.
- **Kurze Texte sind schwach.** Unter etwa 10 Grammen greift der
  SimHash-Cluster bewusst nicht; dort entscheidet der exakte Titel-Hash.
- **Grenze der Schwelle.** 10 von 64 Bits plus Jaccard 0,55 ist eine
  Heuristik. Bei sehr ähnlichen Kurzmeldungen können falsche Kopien entstehen;
  die Quelle bleibt in `nexus_meldungen` sichtbar, sodass der Fehler prüfbar
  ist.
- **Portugiesisch/Niederländisch** sind nur über Stoppwörter abgedeckt; das
  Register führt derzeit keine Quellen in diesen Sprachen.

---

## 4. Schnittstellen

`GET /api/nexus/status` liefert zusätzlich:

```json
"meldungen": {
  "gesamt": 12,
  "originale": 10,
  "dubletten": 2,
  "dublettenquote": 0.167,
  "cluster": 10,
  "nach_sprache": [{"sprache": "en", "n": 7}, {"sprache": "de", "n": 5}]
}
```

Der Nachtlauf-Bericht enthält `gespeichert`, `dubletten`, `wiederholungen` und
`speicher_fehler`. Ein Speicherfehler macht den Lauf `ok=false`; der
Healthchecks-Fail-Ping greift dann wie bei einem Abruffehler.

---

## 5. Tests

- `tests/test_nexus_sprache.py`: Deutsch, Englisch, Französisch, Italienisch,
  Spanisch, Chinesisch, Japanisch, Koreanisch, Kyrillisch, kurzer Titel,
  leerer Text.
- `tests/test_nexus_dedup.py`: gleicher Hash, nahe Kopie, fremder Text,
  Cluster-Suche, deterministischer Index, Titel-Normalisierung.
- `tests/test_nexus_speicher.py`: Original, Wiederholung, Kopie, getrennte
  Meldungen, Index nach Neustart, Spracherkennung, alter Spider-Artikel.
- `tests/test_nexus_nacht.py`: Ende-zu-Ende mit einem Feed aus zwei gleichen
  Meldungen; zweiter Lauf erzeugt keine neue Zeile.

Ergebnis: **143 Tests grün** (10. November 2026). Echter lokaler Lauf mit
`--limit 3` gegen EZB-Press, EZB-Blog und Fed-Press: 50 Meldungen,
50 gespeichert, 0 Fehler, 0 Dubletten; die drei Quellen waren verschieden.
Spracherkennung: 50 × `en`, Konfidenz 0,95. Die Kopie-Erkennung ist mit zwei
identischen Feed-Einträgen und einer umformulierten Kopie getestet.

---

## 6. Nächster Schritt

Phase 3 ist umgesetzt: Quellenreputation, regelbasierte Kernaussagen,
Bestätigungsgrad und Widerspruchserkennung. Details und ehrliche Grenzen:
[PHASE-3.md](PHASE-3.md). Erst danach werden aus Meldungen belastbare Claims —
Phase 3 liefert dafür die erste, bewusst heuristische Stufe.
