# Schutz von `main`

Seit dem 12. November 2026 gilt das Repository-Ruleset
`main: PR und gruene CI` (ID 27124760, Status `active`, Ziel `refs/heads/main`).
Am 17. November 2026 wurde es von drei auf **sechs Required Checks**
erweitert; die drei bisherigen Checks bleiben unverändert bestehen.

## PR-Pflicht

- Änderungen erreichen `main` nur über einen Pull Request.
- Erlaubte Merge-Methoden: Merge-Commit, Squash und Rebase.
- Review-Threads müssen vor dem Merge aufgelöst sein; veraltete Freigaben
  werden bei einem neuen Push verworfen.
- Pflichtfreigaben: 0. Die PR-Pflicht ist damit auch im Ein-Personen-Repository
  durchsetzbar; sie ersetzt keine zweite Person.
- Der Branch muss aktuell sein (`strict`): Der PR-Head muss den aktuellen
  Stand von `main` enthalten, sonst ist der Merge blockiert.

## Required Checks

| Check | Job in `.github/workflows/tests.yml` | Belegte Wirkung |
|---|---|---|
| `Doku-relevante Änderungen ermitteln` | `changes` | Ermittelt, ob Doku-Prüfungen nötig sind |
| `Doku-Prüfung` | `doku` | Relative Links, Markdown- und HTML-Anker, alte Begriffe |
| `pytest` | `pytest` | Python-Testsuite |
| `text250` | `text250` | 240-px-/250-%-Layout, Claims, Refresh, Tooltip, Tastatur, Widerspruch-E2E |
| `Touch-Test` | `touch` | Touch-Ziele und mobile Bedienung |
| `docker` | `docker` | Dockerfile inklusive Seed-Datenbank |

`pytest`, `docker`, `Doku-Prüfung`, `text250` und `Touch-Test` sind die
Pflichtprüfungen aus [AGENTS.md](../AGENTS.md) Abschnitt 3. Der
Ermittlungsschritt ist zusätzlich erforderlich, damit die vorgelagerte
Entscheidung über die Doku-Prüfung nicht unbemerkt ausfallen kann.

Die Doku-Prüfung läuft nur bei doku-relevanten Änderungen
(`if: needs.changes.outputs.doku == 'true'`). Ein übersprungener Job meldet
laut GitHub-Dokumentation `Success` und blockiert den Merge auch als
Required Check nicht; belegt an PR #179, dessen Check `Doku-Prüfung` auf
`830167b` mit `skipped` abgeschlossen ist und der anschließend gemergt wurde.

## Weitere Regeln

- Keine Force-Pushes (`non_fast_forward`).
- Kein Löschen des Branches (`deletion`).
- Kein Bypass, auch nicht für Administratoren: `bypass_actors` ist leer,
  `current_user_can_bypass` steht auf `never`.

Die Prüfungen laufen als GitHub-Actions-Workflow `tests.yml`. Railway baut
`main` nach dem Merge automatisch.
