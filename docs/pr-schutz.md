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

Alle sechs Checks sind im Ruleset an die GitHub-Actions-App gebunden
(`integration_id: 15368`, App-Slug `github-actions`). Ein fremder
Commit-Status mit identischem Namen — aus einem anderen CI-System oder manuell
gesetzt — erfüllt den Gate damit nicht: GitHub akzeptiert für diese Checks nur
Statusmeldungen der Actions-App. Die Bindung wurde am 19. November 2026
gesetzt; vorher genügte der reine Kontextname.

Die Doku-Prüfung läuft nur bei doku-relevanten Änderungen
(`if: needs.changes.outputs.doku == 'true'`). Ein übersprungener Job meldet
laut GitHub-Dokumentation `Success` und blockiert den Merge auch als
Required Check nicht; belegt an PR #179, dessen Check `Doku-Prüfung` auf
`830167b` mit `skipped` abgeschlossen ist und der anschließend gemergt wurde.

## Pflichtverweis auf diese Datei

`README.md` muss diese Dokumentation über einen **sichtbaren** Link nennen.
`scripts/pruefe_doku.py` prüft das bei jeder Doku-Prüfung über
`PFLICHT_VERWEISE`.

Als sichtbarer Link gelten:

- Inline-Link: `[Schutz](docs/pr-schutz.md)`
- HTML-Link: `<a href="docs/pr-schutz.md">Schutz</a>`
- tatsächlich verwendete Referenz: `[Schutz][ref]`, `[Schutz][]` oder
  `[Schutz]` zusammen mit einer passenden Definition
  `[ref]: docs/pr-schutz.md`

Nicht ausreichend:

- eine reine Referenzdefinition ohne Verwendung, etwa
  `[ref]: docs/pr-schutz.md`
- Bildziele: `![Schutz](docs/pr-schutz.md)` und
  `<img src="docs/pr-schutz.md">`

`python scripts/pruefe_doku.py --negativtest` belegt, dass ein fehlender
Pflichtverweis erkannt wird; dieser Lauf gehört zur Doku-Prüfung, sobald das
Prüfskript geändert wurde.

## Weitere Regeln

- Keine Force-Pushes (`non_fast_forward`).
- Kein Löschen des Branches (`deletion`).
- Kein Bypass, auch nicht für Administratoren: `bypass_actors` ist leer,
  `current_user_can_bypass` steht auf `never`.

Die Prüfungen laufen als GitHub-Actions-Workflow `tests.yml`. Railway baut
`main` nach dem Merge automatisch.
