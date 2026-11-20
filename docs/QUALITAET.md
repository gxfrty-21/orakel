# Qualitätstor: Lint, Typen und Coverage

Drei eigene CI-Jobs in `.github/workflows/tests.yml` prüfen den Code, ohne die
bestehenden Tests anzutasten: `ruff`, `mypy` und `Coverage Handelskern`. Jeder
Job lässt sich lokal mit denselben Befehlen nachvollziehen.

## ruff

`ruff.toml` aktiviert drei Regelsätze:

| Regel | Bedeutung |
|---|---|
| `BLE001` | `except Exception`/`except BaseException` ohne Not |
| `S110` | `try`/`except`/`pass` schluckt den Fehler still |
| `S` | Sicherheitsregeln aus flake8-bandit (SQL, `subprocess`, `urlopen`, XML …) |

Lokal:

```bash
.venv/bin/python -m ruff check .
```

`assert` ist in `tests/` das Prüfmittel und deshalb dort von `S101`
ausgenommen. Für die Sicherheitsregeln trägt jede Fundstelle eine
`# noqa: <Regel> - <Grund>`-Zeile; die Gründe nennen die tatsächliche
Absicherung, etwa «nur `?`-Platzhalter, Werte als Parameter» bei
`S608`.

### Altbestand bei `BLE001`/`S110`

23 Module aus der Zeit vor diesem Tor fangen bewusst breit ab: Ein Fehler in
einer Quelle, einem Job oder einer Ansicht darf den übrigen Ablauf nicht
beenden. Diese Module stehen als Schuldenliste in `ruff.toml` unter
`per-file-ignores`; die Liste soll schrumpfen. Nicht ausgenommen sind
`orakel/kern/`, alle Tests, alle Skripte ausser den Soak-Werkzeugen und jedes
neue Modul. Ein neuer blinder Fang in einem nicht gelisteten Modul lässt den
Job scheitern.

## mypy

`mypy.ini` prüft den Handelskern: `orakel/kern/paper.py`, `risk.py`,
`backtest.py` und `judge.py`; die von ihnen importierten Kernmodule zieht mypy
mit hinein. Web, Agenten und Nexus bleiben aussen vor, weil ihre Typisierung
für ein Tor über Nacht nicht reicht und nur `ignore`-Zeilen erzeugen würde.

Lokal:

```bash
.venv/bin/mypy
```

## Coverage-Untergrenze

Der Job `Coverage Handelskern` misst die vier Kernmodule gemeinsam und bricht
unter **85 %** ab:

```bash
.venv/bin/python -m pytest -q \
  --cov=orakel.kern.paper --cov=orakel.kern.risk \
  --cov=orakel.kern.backtest --cov=orakel.kern.judge \
  --cov-report=term-missing --cov-fail-under=85
```

Stand bei Einführung (Commit dieses Bereichs):

| Modul | Coverage |
|---|---|
| `orakel/kern/paper.py` | 95 % |
| `orakel/kern/risk.py` | 90 % |
| `orakel/kern/backtest.py` | 94 % |
| `orakel/kern/judge.py` | 82 % |
| **zusammen** | **89 %** |

Die Untergrenze liegt vier Punkte unter dem Stand, damit ein Umbau nicht sofort
scheitert, aber ein Absinken unter 85 % auffällt. Die Tests selbst bleiben
unverändert; die Grenze wird nicht durch Ausschlüsse oder `pragma: no cover`
erreicht. Wer die Coverage senkt, muss die Grenze im Workflow bewusst
mitändern — das ist im Diff sichtbar.

## Was das Tor nicht prüft

- Keine Stil- oder Formatregeln (`E`, `W`, `I`, …) und kein Formatter.
- Keine Typisierung von Web, Agenten, Nexus oder Skripten.
- Keine Coverage für Module ausserhalb des Handelskerns.
- Keine Sicherheitsprüfung von Abhängigkeiten (`pip-audit` o. Ä.).
