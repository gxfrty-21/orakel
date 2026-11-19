"""Prüft den Ergebnis-Prüfer des Widerspruch-E2E gegen Manifest und Fixtures."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]
PRUEFER = WURZEL / "scripts" / "pruefe-widerspruch-e2e-ergebnis.mjs"
MANIFEST = WURZEL / "scripts" / "widerspruch-e2e-required-checks.json"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _node() -> str:
    pfad = shutil.which("node")
    if not pfad:
        pytest.skip("node ist nicht installiert")
    return pfad


def _pruefe(ergebnis: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _node(),
            str(PRUEFER),
            "--ergebnis",
            str(ergebnis),
            "--pflicht",
            str(MANIFEST),
            "--profil",
            "voll",
        ],
        capture_output=True,
        text=True,
        cwd=WURZEL,
        check=False,
    )


def test_manifest_hat_genau_drei_pflichtfaelle() -> None:
    daten = json.loads(MANIFEST.read_text(encoding="utf-8"))
    profil = daten["profiles"]["voll"]
    ids = [eintrag["id"] for eintrag in profil["checks"]]
    assert len(ids) == 3
    assert len(set(ids)) == 3
    assert profil["counters"]["negativ"] == 3


def test_gueltiges_ergebnis_besteht() -> None:
    lauf = _pruefe(FIXTURES / "widerspruch-e2e-ergebnis-gut.json")
    assert lauf.returncode == 0, lauf.stderr
    assert "3/3" in lauf.stdout


def test_mutierte_fixture_wird_als_fehler_erkannt() -> None:
    lauf = _pruefe(FIXTURES / "widerspruch-e2e-ergebnis-mutiert.json")
    assert lauf.returncode == 1
    ausgabe = lauf.stdout + lauf.stderr
    assert "widerspruch-e2e.negativ.dom-fehlt" in ausgabe
    assert "negativ: erwartet 3, tatsächlich 2" in ausgabe
