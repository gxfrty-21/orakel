# Automatisierter Chromium-Touch-Test: Ergebnis

**Stand:** 15. November 2026\
**Ergebnis:** bestanden\
**Basis:** Branch `test/legende-querformat-desktop`, Basis-Commit `853330a`; die Regressionstests lagen im Arbeitsbaum noch uncommittet vor\
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

Der Lauf prüft vier mobile Viewports mit `deviceScaleFactor: 3`, `isMobile` und
`hasTouch`: 390 × 844, 360 × 800, 844 × 390 (Querformat) und 320 × 700. Die
Raumgrössen werden nach «Fit» gemessen; die Prüfung schlägt fehl, wenn Räume
oder Abteilungen ausserhalb des Schiffsviewports liegen.

## Ergebnis

```text
Touch OK: Pan 52 px · Pinch 24 % → 59 % · 11 Cluster ohne Doppelung · Tippen öffnet Atlas · Filter A 10 Räume / gelöst · Fit 390 px 24 % · min. 24.4×25.5 px · 103/103 sichtbar · Porträt 360×800 22 % · min. 22.4×23.3 px · 103/103 sichtbar · Querformat 844×390 30 % · min. 31.4×32.7 px · 103/103 sichtbar · Fit 320 px 19 % · min. 19.6×20.4 px · 103/103 sichtbar
```

Damit bestanden:

- Ein-Finger-Pan verschiebt das Schiff um 52 px, ohne den Zoom zu verändern.
- Zwei-Finger-Pinch zoomt von 24 % auf 59 %.
- Elf Abteilungscluster enthalten 103 eindeutige Agentenräume ohne Doppelung.
- Ein Tap öffnet den Agentenraum «Atlas» und markiert genau eine Auswahl.
- Der Legendenfilter für Abteilung A hebt zehn Räume hervor und lässt sich
  wieder lösen.
- «Fit» zeigt in allen vier Viewports 103 von 103 Räumen; die kleinsten
  Raumgrössen bleiben innerhalb der erwarteten Mindestwerte.

## Kompakte Abteilungslegende im Querformat

Der Lauf bei 844 × 390 prüft zusätzlich die kompakte Abteilungslegende:

- Die Legende ist im breiten Querformat standardmässig offen.
- Der Kopf nennt «SEKTOREN», «FILTER» und «11 ABTEILUNGEN».
- Alle elf Abteilungen sind sichtbar.
- Der Legendenkasten und seine Einträge laufen nicht horizontal über.

Dieselbe Kopf- und Überlaufprüfung besteht im Porträt bei 360 × 800, nachdem
die Legende per Tap aufgeklappt wurde.

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
