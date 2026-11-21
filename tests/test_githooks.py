"""Tests für die Pfadlogik des versionierten Pre-Commit-Hooks.

Der Hook wird in temporären Git-Repositories ausgeführt. Dadurch prüfen die
Tests unabhängig von der echten Projekt-Historie, dass der Hook seine Wurzel
auch aus einem Unterordner findet, nur die vorgesehenen Pfade auslöst und das
projektlokale Python verwendet.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PROJEKT = Path(__file__).resolve().parents[1]
HOOK = PROJEKT / ".githooks" / "pre-commit"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
        ["git", *args],  # noqa: S607 - Programmname und Argumente sind fest verdrahtet
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _neues_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo mit leerzeichen"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Hook-Test")
    _git(repo, "config", "user.email", "hook-test@example.invalid")
    (repo / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo, "add", ".gitkeep")
    _git(repo, "commit", "-q", "-m", "initial")

    hook_ziel = repo / ".githooks" / "pre-commit"
    hook_ziel.parent.mkdir()
    shutil.copy2(HOOK, hook_ziel)

    fake_python = repo / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$@" >> "$HOOK_LOG"\n'
        'exit "${HOOK_EXIT:-0}"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    return repo


def _hook_ausfuehren(repo: Path, cwd: Path, log: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOOK_LOG"] = str(log)
    env["HOOK_EXIT"] = "0"
    return subprocess.run(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
        [str(repo / ".githooks" / "pre-commit")],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )


def _aufrufe(log: Path) -> list[str]:
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8").splitlines()


def test_hook_findet_die_repo_wurzel_aus_einem_unterordner(tmp_path: Path) -> None:
    repo = _neues_repo(tmp_path)
    unterordner = repo / "docs" / "unterordner"
    unterordner.mkdir(parents=True)
    (repo / "docs" / "notiz.md").write_text("# Test\n", encoding="utf-8")
    _git(repo, "add", "docs/notiz.md")
    log = tmp_path / "aufrufe.log"

    ergebnis = _hook_ausfuehren(repo, unterordner, log)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert _aufrufe(log) == [str(repo / "scripts" / "pruefe_doku.py")]


def test_hook_fuehrt_bei_geaendertem_pruefskript_den_negativtest_aus(tmp_path: Path) -> None:
    repo = _neues_repo(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "pruefe_doku.py").write_text("# Fake\n", encoding="utf-8")
    _git(repo, "add", "scripts/pruefe_doku.py")
    unterordner = repo / "scripts"
    log = tmp_path / "aufrufe.log"

    ergebnis = _hook_ausfuehren(repo, unterordner, log)

    assert ergebnis.returncode == 0, ergebnis.stderr
    aufrufe = _aufrufe(log)
    assert aufrufe.count(str(repo / "scripts" / "pruefe_doku.py")) == 2
    assert "--negativtest" in aufrufe


def test_hook_ignoriert_nicht_relevante_pfade(tmp_path: Path) -> None:
    repo = _neues_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    _git(repo, "add", "src/app.py")
    log = tmp_path / "aufrufe.log"

    ergebnis = _hook_ausfuehren(repo, repo / "src", log)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert _aufrufe(log) == []


def test_hook_ignoriert_aehnliche_dateinamen(tmp_path: Path) -> None:
    repo = _neues_repo(tmp_path)
    (repo / "docs").mkdir()
    (repo / "docs" / "notiz.md.bak").write_text("# Alt\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "pruefe_doku.py.bak").write_text("# Alt\n", encoding="utf-8")
    _git(repo, "add", "docs/notiz.md.bak", "scripts/pruefe_doku.py.bak")
    log = tmp_path / "aufrufe.log"

    ergebnis = _hook_ausfuehren(repo, repo / "docs", log)

    assert ergebnis.returncode == 0, ergebnis.stderr
    assert _aufrufe(log) == []
