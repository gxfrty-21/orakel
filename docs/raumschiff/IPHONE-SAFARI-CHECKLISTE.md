# Manuelle iPhone-Safari-Prüfung: Pan, Pinch und Tippen

**Gilt für:** die Schiffsansicht `#v-ship` mit 103 Agentenräumen in elf Abteilungen\
**Zweck:** Abnahme der echten Touch-Bedienung auf iPhone und Safari; ergänzt den
automatisierten Chromium-Touch-Test\
**Automatischer Gegenpart:** [`scripts/pruefe-touch.mjs`](../../scripts/pruefe-touch.mjs)\
**Letzter Emulationslauf:** [Chromium-Touch-Ergebnisse](TOUCH-EMULATION.md)\
**Stand:** 15. November 2026

## 1. Grenzen dieser Prüfung

Der automatisierte Lauf prüft 390 × 844, 360 × 800, 844 × 390 und 320 × 700 in
Chromium mit emulierten Touch-Events. Diese Checkliste prüft, was dort nicht
sichtbar wird: echte Safari-Gesten, Seitenzoom, die Safari-Werkzeugleiste,
Drehen des Geräts und das Trefferhalten mit dem Finger. Sie ist **read-only**:
«Lauf starten» und andere schreibende Aktionen werden nicht angetippt.

## 2. Gerät und Umgebung

Diese Checkliste wird pro Gerät und Orientierung einmal ausgefüllt. Wenn nur ein
iPhone verfügbar ist, mindestens dieses Gerät in **Porträt und Querformat**
prüfen.

| Feld | Eintrag |
|---|---|
| Gerät | z. B. iPhone SE (3. Gen.) oder iPhone 15 |
| iOS-Version | |
| Safari-Version | |
| Getestete URL | |
| Commit/Deploy | |
| Tester:in | |
| Datum | |

Empfohlene Abdeckung:

- **iPhone SE (2./3. Gen.):** 375 × 667 CSS-Pixel im Porträt, 667 × 375 im Querformat.
- **iPhone 14/15:** 390 × 844 CSS-Pixel im Porträt, 844 × 390 im Querformat.

Die tatsächliche Safari-Viewport-Höhe ändert sich mit ein- und ausgeblendeter
Werkzeugleiste. Deshalb nach dem Laden kurz warten, bis die Leiste stabil ist.

## 3. Vorbereitung

- [ ] Produktions-URL öffnen: <https://orakel-production-fb18.up.railway.app/>
      (oder die URL der zu prüfenden Instanz). Nur verwenden, wenn dort der
      gewünschte Commit deployt ist.
- [ ] Basic-Auth-Anmeldung mit den Zugangsdaten aus dem Passwortmanager
      abschliessen. **Keine Zugangsdaten in dieses Dokument schreiben.**
- [ ] In Safari den Website-Zoom auf 100 % stellen (`aA` in der Adressleiste).
- [ ] Die Bildschirmsperre/Orientierungssperre ausschalten.
- [ ] «Raumschiff» öffnen und warten, bis 103 Räume und elf Abteilungen geladen
      sind. Es darf kein Lade- oder Fehlerzustand sichtbar bleiben.
- [ ] «Fit» antippen. Die Zoom-Anzeige zeigt einen Prozentwert; alle 103 Räume
      und elf Abteilungen liegen im Schiffsviewport.
- [ ] Kein horizontaler Seitenüberlauf: Die Seite lässt sich nicht seitlich
      verschieben und die Safari-Werkzeugleiste bleibt bedienbar.

> **Orientierung:** Die Spalten **P** (Porträt) und **L** (Querformat) werden
> getrennt abgehakt. Die Erwartungen gelten in beiden Orientierungen, sofern
> eine Zeile nichts anderes sagt. Für jede Zeile bei Bedarf zuerst «Fit»
> antippen und die Ausgangslage wiederherstellen.

## 4. Pan — ein Finger verschiebt das Schiff

| ID | Aktion | Erwartetes Ergebnis | P | L |
|---|---|---|---|---|
| PAN-1 | Mit **einem Finger** im Schiff viewport nach rechts und unten ziehen (ca. 50 px). | Das Schiff folgt der Bewegung. Die Zoom-Anzeige bleibt unverändert. Es öffnet sich kein Agentenraum. | [ ] | [ ] |
| PAN-2 | Die Geste auf einem Agentenraum beginnen und mindestens 30 px ziehen. | Das Schiff verschiebt sich; der Raum wird **nicht** geöffnet. Erst ein anschliessender, ruhiger Tap öffnet ihn. | [ ] | [ ] |
| PAN-3 | Abwechselnd an alle vier Ränder des Schiffs viewports ziehen. | Das Schiff bleibt innerhalb des Viewports; die Seite scrollt nicht horizontal, löst kein Zurück/Vorwärts aus und die Safari-Leiste bleibt sichtbar. | [ ] | [ ] |
| PAN-4 | Bei sichtbarem Schiff vom Porträt ins Querformat drehen und zurück. | Nach ca. 0,5 s ist die Ansicht automatisch neu eingepasst; alle Räume und Abteilungen sind sichtbar, die Zoom-Anzeige ist aktuell. | [ ] | [ ] |
| PAN-5 | Nach dem Pan kurz warten und einen Raum antippen. | Der Tap wird nicht durch die vorherige Pan-Geste unterdrückt; der Raum öffnet sich. | [ ] | [ ] |

## 5. Pinch — zwei Finger zoomen

| ID | Aktion | Erwartetes Ergebnis | P | L |
|---|---|---|---|---|
| PIN-1 | Zwei Finger im Schiff viewport ansetzen und auseinanderziehen. | Die Zoom-Anzeige steigt, die Räume werden grösser, der Zoom folgt ungefähr dem Mittelpunkt der Finger. Der Safari-Seitenzoom bleibt 100 %. | [ ] | [ ] |
| PIN-2 | Zwei Finger wieder zusammenziehen. | Die Zoom-Anzeige sinkt, die Räume werden kleiner, die Ansicht bleibt gefüllt und reagiert ohne Sprung. Der Safari-Seitenzoom bleibt 100 %. | [ ] | [ ] |
| PIN-3 | Mehrfach stark auseinanderziehen und anschliessend mehrfach zusammenziehen. | Der Pinch-Zoom bleibt im Bereich **22 % bis 250 %**; «Fit» darf auf sehr schmalen Viewports darunter liegen. Die Anzeige läuft nicht über die Grenzen hinaus, die Seite friert nicht ein und «Fit» stellt die vollständige Ansicht wieder her. | [ ] | [ ] |
| PIN-4 | Während des Pinch die Safari-Werkzeugleiste und die Adressleiste beobachten. | Nur das Schiff zoomt; die Webseite selbst wird nicht gezoomt, nicht neu geladen und scrollt nicht seitlich. | [ ] | [ ] |
| PIN-5 | Nach dem Pinch ca. 0,5 s warten und einen Raum antippen. | Der Tap funktioniert; der Raum öffnet sich und die Legende markiert seine Abteilung. | [ ] | [ ] |

## 6. Tippen — Räume, Legende und Filter

| ID | Aktion | Erwartetes Ergebnis | P | L |
|---|---|---|---|---|
| TAP-1 | Einen Agentenraum antippen (bei Fit oder nach dem Hineinzoomen). | Genau ein Raum ist markiert. Die Detailspalte zeigt den Agentenraum mit Name, Rolle, Abteilung und Status. Die Ops-Legende markiert dieselbe Abteilung. | [ ] | [ ] |
| TAP-2 | Einen Raum in einer **anderen** Abteilung antippen. | Die Markierung wechselt; die vorherige Auswahl wird entfernt, die Details werden ersetzt und die Legendenmarkierung zieht mit. Die Seite bleibt ohne horizontalen Überlauf. | [ ] | [ ] |
| TAP-3 | Im Porträt den Legendenkopf «SEKTOREN · FILTER» antippen. | Die Legende klappt auf und zeigt elf Abteilungen mit kompaktem Kopf. Ein erneuter Tap klappt sie wieder ein. | [ ] | [ ] |
| TAP-4 | Im Querformat die Legende prüfen. | Bei breiten iPhones (z. B. 844 CSS-px) ist sie standardmässig offen; bei schmalen Querformaten (z. B. iPhone SE, 667 CSS-px) bleibt sie eingeklappt und lässt sich wie im Porträt aufklappen. In beiden Fällen sind elf Abteilungen bedienbar. | [ ] | [ ] |
| TAP-5 | In der geöffneten Legende «A · Hauptzentrale» antippen. | Der Filter ist aktiv: Abteilung A wird hervorgehoben, die anderen Abteilungen werden gedimmt. Die bereits geöffneten Agentendetails bleiben stehen. | [ ] | [ ] |
| TAP-6 | Denselben Legendeneintrag erneut antippen. | Der Filter wird gelöst; die Dimmung endet. Die Markierung der zuletzt gewählten Abteilung bleibt sichtbar. | [ ] | [ ] |
| TAP-7 | Die Gemeinschaftsräume «Agentenraum» und «Konferenz» antippen. | Die Detailspalte wechselt in die jeweilige Übersicht; es gibt keinen Absturz und keine falsche Raumauswahl. | [ ] | [ ] |
| TAP-8 | Auf eine leere Fläche bzw. einen nicht interaktiven Bereich des Schiffs tippen. | Es wird kein Raum geöffnet, die Detailspalte bleibt unverändert und es erscheint kein JavaScript-Fehler. | [ ] | [ ] |
| TAP-9 | «Fit» antippen. | Alle 103 Räume und elf Abteilungen sind wieder vollständig sichtbar; die Zoom-Anzeige ist ein Prozentwert. | [ ] | [ ] |

## 7. Safari-Abschlussprüfung

- [ ] Nach allen Gesten ist der Safari-Seitenzoom weiterhin 100 %.
- [ ] Es gibt keinen horizontalen Seitenüberlauf und kein versehentliches
      Zurück/Vorwärts.
- [ ] Die Safari-Werkzeugleiste bleibt bedienbar; die Adressleiste ist sichtbar.
- [ ] Beim Drehen bleibt die Auswahl bzw. der Filterzustand nachvollziehbar;
      die Ansicht wird neu eingepasst.
- [ ] Bei aktiviertem Web Inspector (optional) erscheinen durch die Gesten
      keine neuen JavaScript-Fehler; bekannte Font- oder Netzwerkabweichungen
      werden separat notiert.
- [ ] Keine schreibende Aktion («Lauf starten» oder ähnliche) wurde ausgelöst.

## 8. Ergebnis und Fehlermeldung

**Gesamtergebnis:** [ ] bestanden · [ ] bestanden mit Hinweisen · [ ] nicht bestanden

Ein Befund ist besonders kritisch, wenn eine der folgenden Bedingungen auftritt:

- Safari zoomt die ganze Seite statt nur das Schiff.
- Ein Tap öffnet den falschen Raum oder löst eine schreibende Aktion aus.
- Die Seite scrollt horizontal oder verliert die Safari-Navigation.
- Pan oder Pinch lassen die Ansicht leer, eingefroren oder ohne Zoom-Anzeige zurück.
- Die Legende zeigt nach einem Tap nicht die gewählte Abteilung.

Bei einem Befund notieren:

| Feld | Eintrag |
|---|---|
| Gerät / iOS / Safari | |
| Orientierung | |
| URL und Commit/Deploy | |
| Schritte bis zum Fehler | |
| Erwartet / tatsächlich | |
| Zoom-Anzeige | |
| Screenshot | |
| Web-Inspector-Fehler (falls vorhanden) | |

Screenshot auf dem iPhone: **Seitentaste + Lauter** drücken. Keine Zugangsdaten
oder personenbezogenen Daten im Screenshot oder im Befund speichern.

## 9. Abnahme

| Prüfung | Ergebnis | Initialen | Datum |
|---|---|---|---|
| Vorbereitung | | | |
| Pan in Porträt und Querformat | | | |
| Pinch in Porträt und Querformat | | | |
| Tippen, Legende und Filter in Porträt und Querformat | | | |
| Safari-Abschlussprüfung | | | |

Diese manuelle Prüfung ersetzt den automatisierten Touch-Test nicht. Der
automatisierte Lauf bleibt die schnelle CI-Regression; diese Checkliste ist die
Abnahme auf echter Safari-Hardware.
