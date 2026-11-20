"""Wacht darüber, dass das Typtor für den Handelskern nicht still verschwindet."""
from __future__ import annotations

import configparser
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
KERN = ["orakel/paper.py", "orakel/risk.py", "orakel/backtest.py", "orakel/judge.py"]


def _mypy_ini() -> configparser.ConfigParser:
    leser = configparser.ConfigParser()
    gelesen = leser.read(WURZEL / "mypy.ini", encoding="utf-8")
    assert gelesen, "mypy.ini fehlt"
    return leser


def test_mypy_prueft_genau_den_handelskern():
    abschnitt = _mypy_ini()["mypy"]
    dateien = [teil.strip() for teil in abschnitt["files"].split(",")]

    assert dateien == KERN
    for datei in dateien:
        assert (WURZEL / datei).is_file()


def test_mypy_prueft_schaerfer_als_der_standard():
    abschnitt = _mypy_ini()["mypy"]

    for schalter in ("check_untyped_defs", "disallow_untyped_defs",
                     "disallow_incomplete_defs", "no_implicit_optional",
                     "warn_redundant_casts", "warn_unused_ignores",
                     "strict_equality"):
        assert abschnitt.getboolean(schalter) is True, schalter


def test_ci_fuehrt_das_typtor_aus():
    workflow = (WURZEL / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")

    assert "\n  mypy:\n" in workflow
    assert "python -m mypy" in workflow


def test_werkzeuge_sind_gepinnt():
    text = (WURZEL / "requirements-dev.txt").read_text(encoding="utf-8")
    gepinnt = {zeile.strip() for zeile in text.splitlines()}

    assert any(zeile.startswith("mypy==") for zeile in gepinnt)
    # Ohne pandas-stubs meldet mypy die pandas-Importe als untypisiert.
    assert any(zeile.startswith("pandas-stubs==") for zeile in gepinnt)
