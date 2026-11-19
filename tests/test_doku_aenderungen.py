"""Regressionstests für die Doku-Diff-Ermittlung im changes-Job.

Die Tests legen ein temporäres Git-Repository an und führen das Skript aus,
das der Workflow verwendet. Der Force-Push-Fall wird mit einer nicht
erreichbaren BEFORE_SHA simuliert; ein gültiger Bereich bleibt eng auf den
tatsächlichen Diff begrenzt.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJEKT = Path(__file__).resolve().parents[1]
SKRIPT = PROJEKT / "scripts" / "ermittle-doku-aenderungen.sh"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo mit leerzeichen"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "CI-Test")
    _git(repo, "config", "user.email", "ci-test@example.invalid")

    (repo / "docs").mkdir()
    (repo / "docs" / "notiz.md").write_text("# Notiz\n", encoding="utf-8")
    (repo / "code.py").write_text("print('alt')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "Doku und Code")

    (repo / "code.py").write_text("print('neu')\n", encoding="utf-8")
    _git(repo, "add", "code.py")
    _git(repo, "commit", "-q", "-m", "Nur Code")
    return repo


def _ausfuehren(repo: Path, before_sha: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "EVENT_NAME": "push",
            "BEFORE_SHA": before_sha,
            "PUSH_SHA": _git(repo, "rev-parse", "HEAD").stdout.strip(),
            "BASE_SHA": "",
            "HEAD_SHA": "",
        }
    )
    return subprocess.run(
        ["bash", str(SKRIPT)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_nicht_erreichbare_before_sha_prueft_den_ganzen_baum(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    ergebnis = _ausfuehren(repo, "deadbeef" * 5)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.strip() == "doku=true"


def test_gueltige_before_sha_bleibt_auf_dem_diff(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    before = _git(repo, "rev-parse", "HEAD~1").stdout.strip()

    ergebnis = _ausfuehren(repo, before)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert ergebnis.stdout.strip() == "doku=false"
