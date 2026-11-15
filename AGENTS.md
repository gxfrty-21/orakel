# AGENTS.md – verbindliche Regeln für dieses Repository

Diese Regeln gelten für alle Agenten, die im Orakel-Repository arbeiten. Eine
direkte Anweisung der Nutzerin oder des Nutzers hat Vorrang. Diese Datei darf
nicht benutzt werden, um Sicherheits-, Prüf- oder Paper-Trading-Grenzen zu
umgehen.

## 1. Projektgrenzen

- Dieses Projekt handelt **ausschliesslich Paper**. Es darf keinen Codepfad zu
  einer echten Broker-Order geben; die bestehende Paper-Sperre und
  `order_freigabe`-Logik werden nicht abgeschwächt.
- SQLite ist die einzige Wahrheit für Zahlen. Fehlende Daten bleiben leer;
  Kennzahlen, Kurse und Agentenzustände werden nicht erfunden oder geschätzt.
- Die Grundsätze aus [README.md](README.md) gelten: kein Look-Ahead, Kosten und
  Slippage in Backtests, fest verdrahteter Richter und keine KI-Änderung seiner
  Regeln.
- Bestehende Policy-, Audit-, Berechtigungs- und Freigabegrenzen werden nicht
  aufgeweicht. Schreibende Aktionen bleiben serverseitig validiert und
  protokolliert.
- Oberflächentexte und Dokumentation sind auf Deutsch. Bestehende deutsche
  Abteilungs- und Raumnamen werden beibehalten.
- Keine Secrets, Zugangsdaten, Session-Tokens oder privaten Schlüssel in Code,
  Dokumentation, Commits, Logs oder Chat. Konfiguration kommt aus Umgebungs-
  variablen oder einer nicht versionierten `.env`.

## 2. Vor einer Änderung

1. [README.md](README.md) und die betroffenen Dokumente, Tests und Skripte
   lesen. Keine Annahmen über APIs oder Datenmodelle treffen, wenn der Code
   sie beantworten kann.
2. `git status` und den relevanten Diff prüfen. Vorhandene Änderungen anderer
   Personen nicht überschreiben oder zurücksetzen.
3. Die kleinste Änderung umsetzen, die die Aufgabe vollständig erfüllt. Keine
   ungefragten Refactorings, neuen Seiten, Abhängigkeiten oder Features.
4. Bei unklarer Anforderung zuerst den vorhandenen Kontext ausschöpfen; nur
   dann eine kurze, konkrete Rückfrage stellen.
5. Keine `.env`, Datenbanken, Screenshots, Caches oder generierte Artefakte
   ungefragt versionieren.

## 3. Prüfungen

Vor jedem Commit mindestens:

```bash
git diff --check
```

Bei Markdown- oder Dokumentationsänderungen:

```bash
python scripts/pruefe_doku.py
```

Wird `scripts/pruefe_doku.py` selbst geändert, zusätzlich:

```bash
python scripts/pruefe_doku.py --negativtest
```

Bei Python-Änderungen die betroffenen Tests und bei grösseren Änderungen die
gesamte Suite ausführen:

```bash
.venv/bin/python -m pytest -q
```

Für Web-, Touch- oder Grossmodus-Änderungen die betroffenen vorhandenen
Prüfskripte und, soweit lokal möglich, den passenden CI-Job ausführen. Die
Pflichtprüfungen der CI sind `Doku-Prüfung`, `pytest`, `text250`, `Touch-Test`
und `docker`.

Grundsätze:

- Einen fehlgeschlagenen Test nicht überspringen, abschwächen oder mit einer
  Unterdrückung grün machen. Die Ursache beheben.
- Nur bestandene Prüfungen als bestanden melden. Kompilieren, Starten oder ein
  HTTP-Status beweisen keine Funktion.
- Fehler und nicht ausführbare Prüfungen ausdrücklich nennen.
- Chromium- und WebKit-Emulation sind **keine** Safari-Hardwaretests. Echte
  iPad-/iPhone-Ergebnisse dürfen nur mit Gerät, OS-, Safari-Version, URL,
  Commit und Messwerten als Hardwareprüfung dokumentiert werden. Die
  [Safari-Checkliste](docs/raumschiff/IPHONE-SAFARI-CHECKLISTE.md) bleibt für
  echte Hardware massgeblich.

## 4. Commits

- **Keine Commits ohne ausdrückliche Anforderung.**
- Vor dem Commit `git status`, den vollständigen Diff und die Prüfergebnisse
  kontrollieren. Nur beabsichtigte Dateien stagen.
- Nicht zusammengehörende Änderungen nicht in einen Commit mischen. Wenn
  Dokumentation, Tests und CI getrennt gewünscht sind, getrennte Commits
  anlegen.
- Commit-Titel auf Deutsch, knapp und im Imperativ; der Body erklärt das Warum.
- Keine leeren Commits. Ist die Änderung bereits committet, den vorhandenen
  Commit-Hash nennen, statt einen neuen Commit zu erzeugen.
- Kein `git commit --amend`, Rebase, Force-Push oder History-Rewrite ohne
  ausdrückliche Freigabe. Ein Aufteilen eines noch nicht gepushten Commits ist
  ebenfalls eine History-Änderung und vorher anzusagen.
- Keine Commits direkt auf `main` erzwingen. `main` ist geschützt und Änderungen
  laufen über einen Branch und einen Pull Request.

## 5. Push, Pull Request und Merge

- Push erst nach ausdrücklicher Aufforderung. Niemals `--force` auf gemeinsame
  Branches verwenden.
- Für Änderungen an `main`: neuen Branch von der aktuellen Basis anlegen,
  Branch pushen und einen Pull Request gegen `main` öffnen.
- Der PR-Text enthält:
  - was geändert wurde,
  - welche Prüfungen tatsächlich liefen und mit welchem Ergebnis,
  - welche Einschränkungen oder offenen Punkte bleiben.
- Erforderliche Status-Checks abwarten. Repository-Regeln nicht durch
  Admin-Rechte, Force-Push oder Deaktivieren von Checks umgehen.
- Einen Pull Request erst mergen, wenn die erforderlichen Checks grün sind und
  der Merge ausdrücklich verlangt wurde.
- Nach einem Merge den lokalen `main` per Fast-Forward aktualisieren. Branches
  nur löschen, wenn dies verlangt wurde oder die Aufgabe es eindeutig umfasst.

## 6. Dokumentation und Abschlussbericht

- Dokumentation bei Verhaltens-, UI- oder Prozessänderungen mitpflegen.
- Keine veralteten Fähigkeiten, erfundenen Messwerte oder ungeprüften
  Hardwareaussagen dokumentieren.
- Ein Abschlussbericht nennt:
  - die geänderten Dateien und den Commit-Hash,
  - die tatsächlich ausgeführten Prüfungen und deren Ergebnis,
  - PR-Nummer und Check-/Merge-Status, falls vorhanden,
  - verbleibende Einschränkungen und bewusst nicht ausgeführte Prüfungen.
- Nicht behaupten, etwas sei erledigt, geprüft oder deployed, wenn der
  entsprechende Schritt nicht erfolgreich abgeschlossen wurde.
