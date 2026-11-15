# Automatisierte Touch-Emulation: Chromium und WebKit

**Stand:** 15. November 2026\
**Ergebnis:** Chromium bestanden; WebKit-Emulation bestanden, **kein Safari-Hardwaretest**\
**Basis:** Chromium-Lauf auf Branch `test/legende-querformat-desktop`, Basis-Commit `61cad36`; WebKit-Lauf auf `main` (Basis `95c6a48`)\
**Echte iPad-Safari-Prüfung:** offen – kein physisches Gerät verfügbar\
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

## WebKit-Emulation: ausdrücklich kein Safari-Hardwaretest

**Wichtig:** Dieser Lauf verwendet **Playwright WebKit 27.2 auf Linux/GTK unter
Xvfb**, nicht Safari auf iOS/iPadOS. Die iPad- und iPhone-User-Agents sind
emuliert; es gab weder ein physisches Gerät noch Safari-Werkzeugleiste,
Seitenzoom, Geräterotation oder echte Finger-Touch-Hardware.

Der Lauf am 15. November 2026 verwendete eine frische Seed-Kopie und dieselbe
Schiffsansicht. Gemessen wurde nach «Fit»:

| Viewport (emuliert) | Modus | Weltbreite | Raumhöhe | Zoom | Kleinster Raum | Sichtbar |
|---|---|---:|---:|---:|---:|---:|
| 1100 × 800 | Gross | 2400 px | 150 px | 21 % | 31,8 × 32,2 px | 103/103 |
| 1100 × 1400 | Gross | 2400 px | 150 px | 22 % | 33,0 × 33,4 px | 103/103 |
| 1194 × 834 (iPad Pro 11 quer) | Gross | 2400 px | 150 px | 24 % | 35,0 × 35,4 px | 103/103 |
| 390 × 844 (iPhone) | Kompakt | 1500 px | 108 px | 24 % | 24,4 × 25,5 px | 103/103 |

Zusätzlich bestanden:

- alle elf Abteilungen sichtbar; Legende ohne Eigen- oder Seitenüberlauf
- Raumauswahl mit genau einem Treffer und geöffneten Ops-Details
- Filter A mit einer hervorgehobenen Abteilung und zehn Räumen
- Moduswechsel **1100 → 900 → 1100 px**: 2400/150 px → 1500/108 px →
  2400/150 px, jeweils 103 Räume
- keine App- oder Seitenfehler

Grenzen dieses Emulationslaufs:

- Der Legendenfilter wurde per DOM-Klick ausgelöst; bei 1100 × 1400 und
  390 × 844 musste der Test für einzelne Tippziele ebenfalls auf DOM-Klick
  zurückfallen. Pinch und Pan wurden nicht geprüft.
- WebKit meldete für eine Umgebungsressource `TLS support is not available`;
  das ist kein Fehler der Schiffsansicht.
- Die Werte sind WebKit-CSS-Pixel auf Linux, keine Safari-Messung auf einem
  iPad oder iPhone. Die manuelle [Safari-Checkliste](IPHONE-SAFARI-CHECKLISTE.md)
  bleibt für echte Hardware und Safari-Verhalten erforderlich.

## Grenzen

Die Chromium- und WebKit-Läufe sind **Browser-Emulationen**, keine Tests auf
einem iPhone oder iPad. Die WebKit-Emulation ist ausdrücklich **kein
Safari-Hardwaretest**. Nicht abgedeckt sind echtes Safari-Verhalten,
Safari-Seitenzoom, die Safari-Werkzeugleiste, das Drehen eines physischen Geräts
und das Trefferhalten mit einem echten Finger. Diese Punkte bleiben der
[manuellen Safari-Checkliste](IPHONE-SAFARI-CHECKLISTE.md) vorbehalten.

Der Lauf ist read-only: Es werden keine schreibenden Aktionen wie «Lauf starten»
ausgelöst.

## Echte iPad-Safari-Prüfung: offene Hardware-Unterschiede

**Status: nicht ausgeführt.** In der Cloud-Umgebung ist kein physisches iPad
und kein Safari verfügbar. Die WebKit-Emulation ersetzt diese Abnahme nicht;
insbesondere der 2400-px-Grossmodus wurde nur auf Linux-WebKit mit emulierten
Viewports geprüft. Die folgenden Unterschiede bleiben offen:

| Unterschied | Was die Emulation nicht abdeckt |
|---|---|
| Safari-Rendering und GPU | Safari auf iPadOS nutzt eine andere WebKit-/GPU-/Font-Pipeline als WebKitGTK unter Xvfb. Pixelkunst, Canvas-Schärfe, Farben und Compositing können abweichen. |
| Dynamische Safari-Leisten und Safe Areas | Adress- und Werkzeugleiste verändern die sichtbare Höhe; Notch/Dynamic Island, Home-Indikator und Safe Areas beeinflussen den Schiffsviewport. |
| Echte Touch-Hardware | Pinch, Pan, Palm-/Mehrfingerverhalten und das Trefferhalten mit einem echten Finger wurden nicht geprüft. Der WebKit-Lauf testete keinen Pinch/Pan; der Legendenfilter und einzelne Tippziele liefen über DOM-Klicks. |
| Rotation und Split View | Die reale Geräterotation, Stage Manager, Split View und Slide Over wurden nicht ausgeführt. Der Moduswechsel wurde nur als Viewport-Resize im WebKit-Test geprüft. |
| Safari-Seitenzoom und Schriftgrösse | Website-Zoom, dynamische Textgrösse, Inhaltsblocker und Safari-Sonderverhalten sind nicht Teil der Emulation. |
| Performance und Thermik | Speicher, GPU-Takt, Thermik und Bildrate eines iPads beim 2400-px-Grossmodus wurden nicht gemessen. |
| Produktionskontext | Authentifizierung, Railway-Deploy und die tatsächlich ausgelieferte URL wurden nicht auf einem iPad geprüft. |

Bereits emuliert geprüft sind die 2400-px-Bühne mit 150 px hohen Agentenräumen,
103/103 sichtbare Räume, elf Abteilungen, die Raumauswahl, der Filter A und der
Moduswechsel 1100 → 900 → 1100 px (siehe oben). Diese Ergebnisse sagen nichts
über echtes Safari-Verhalten auf einem iPad aus.

Für die Abnahme die [Safari-Checkliste](IPHONE-SAFARI-CHECKLISTE.md) verwenden;
die Kästchen für das iPad-Querformat und die Rotation bleiben offen, bis ein
passendes Gerät (mindestens 1100 CSS-px breit im Querformat, z. B. iPad Pro 11"
oder iPad Air 11") mit der Ziel-URL und dem Ziel-Commit geprüft wurde.

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
