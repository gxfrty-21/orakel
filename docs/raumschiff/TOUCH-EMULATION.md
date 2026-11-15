# Automatisierter Chromium-Touch-Test: Ergebnis

**Stand:** 15. November 2026\
**Ergebnis:** bestanden\
**Basis:** Branch `test/legende-querformat-desktop`, Basis-Commit `61cad36`; Grossmodus und erweiterte Touch-Prüfungen liegen im Arbeitsbaum\
**Prüfling:** Schiffsansicht `#v-ship` mit 103 Agentenräumen in elf Abteilungen\
**Daten:** frische Kopie von `seed/orakel-seed.db`

## Umgebung

| Feld | Eintrag |
|---|---|
| Browser | Playwright Chromium 158.0.8127.18, headless |
| Betriebssystem | Ubuntu 24.04 |
| Server | `python -m orakel serve`, lokale Seed-Kopie |
| Testart | emulierte Touch-Events über das Chromium-DevTools-Protokoll |
| Testskript | [`scripts/pruefe-touch.mjs`](../../scripts/pruefe-touch.mjs) |

Der Lauf prüft sechs Viewports mit `deviceScaleFactor: 3`, `isMobile` und
`hasTouch`: 390 × 844, 360 × 800, 844 × 390 (Querformat), 320 × 700 sowie die
beiden Grossmodus-Viewports 1100 × 800 und 1100 × 1400. Bei den beiden letzten
ist zusätzlich die 2400-px-Bühne mit 150 px hohen Agentenräumen aktiv. Die
Raumgrössen werden nach «Fit» gemessen; die Prüfung schlägt fehl, wenn Räume
oder Abteilungen ausserhalb des Schiffsviewports liegen.

## Ergebnis

```text
Touch OK: Pan 52 px · Pinch 24 % → 59 % · 11 Cluster ohne Doppelung · Tippen öffnet Atlas · Filter A 10 Räume / gelöst · Fit 390 px 24 % · min. 24.4×25.5 px · 103/103 sichtbar · Porträt 360×800 22 % · min. 22.4×23.3 px · 103/103 sichtbar · Querformat 844×390 30 % · min. 31.4×32.7 px · 103/103 sichtbar · Gross 1100×800 21 % · min. 31.8×32.2 px · 103/103 sichtbar · Gross 1100×1400 22 % · min. 33.0×33.4 px · 103/103 sichtbar · Fit 320 px 19 % · min. 19.6×20.4 px · 103/103 sichtbar
```

Damit bestanden:

- Ein-Finger-Pan verschiebt das Schiff um 52 px, ohne den Zoom zu verändern.
- Zwei-Finger-Pinch zoomt von 24 % auf 59 %.
- Elf Abteilungscluster enthalten 103 eindeutige Agentenräume ohne Doppelung.
- Ein Tap öffnet den Agentenraum «Atlas» und markiert genau eine Auswahl.
- Der Legendenfilter für Abteilung A hebt zehn Räume hervor und lässt sich
  wieder lösen.
- «Fit» zeigt in allen sechs Viewports 103 von 103 Räumen; die kleinsten
  Raumgrössen bleiben innerhalb der erwarteten Mindestwerte.
- Im Grossmodus ist die Bühne 2400 px breit, die Agentenräume sind 150 px hoch,
  und die Messung ergibt 31,8 × 32,2 px bei 1100 × 800 sowie 33,0 × 33,4 px bei
  1100 × 1400. Der Modus schaltet beim Überschreiten der 1100-px-Grenze um.

## Kompakte Abteilungslegende im Querformat

Der Lauf bei 844 × 390 prüft zusätzlich die kompakte Abteilungslegende:

- Die Legende ist im breiten Querformat standardmässig offen.
- Der Kopf nennt «SEKTOREN», «FILTER» und «11 ABTEILUNGEN».
- Alle elf Abteilungen sind sichtbar.
- Der Legendenkasten, seine Einträge und die Seite selbst laufen nach dem Aufklappen nicht horizontal über.

Dieselbe Kopf- und Überlaufprüfung besteht im Porträt bei 360 × 800, nachdem
die Legende per Tap aufgeklappt wurde.

## Grossmodus 2400 px

Ab 1100 px Viewportbreite verwendet die Schiffsansicht die 2400-px-Fassung aus
dem Anhang: 150 px hohe Agentenräume, 180 px hohe Gemeinschaftsräume, 270 px
hohe Hangar-/Warp-Räume und 48 px breite Türen. Die reichere Anhang-Kunst wird
aus `ship-gross.js` geladen; die kompakte Fassung unter 1100 px bleibt bei ihrer
bisherigen Kunst. Der Wechsel löst ein Neuzeichnen und ein neues «Fit» aus.

Die 1100-px-Viewports sind keine echten Telefone. Sie prüfen die untere Grenze
des Grossmodus und seine Touch-Bedienung in Chromium; ein echtes Tablet oder
iPhone bleibt der manuellen Prüfung vorbehalten.

## Grenzen

Dieser Lauf ist eine **Chromium-Emulation**, kein Test auf einem iPhone. Nicht
abgedeckt sind echtes Safari-Verhalten, Safari-Seitenzoom, die Safari-Werkzeugleiste,
das Drehen eines physischen Geräts und das Trefferhalten mit einem echten Finger.
Diese Punkte bleiben der [manuellen iPhone-Safari-Checkliste](IPHONE-SAFARI-CHECKLISTE.md)
vorbehalten.

Der Lauf ist read-only: Es werden keine schreibenden Aktionen wie «Lauf starten»
ausgelöst.

## Reproduktion

```bash
cp seed/orakel-seed.db /tmp/orakel-touch.db
ORAKEL_DB_PFAD=/tmp/orakel-touch.db \
  .venv/bin/python -m orakel serve --host 127.0.0.1 --port 3211

# In einem zweiten Terminal:
node scripts/pruefe-touch.mjs \
  --url http://127.0.0.1:3211 --bilder artifacts/touch
```

In der CI übernimmt der Job `touch` dieselbe Prüfung auf `ubuntu-24.04`.
