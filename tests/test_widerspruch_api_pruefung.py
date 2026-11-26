"""Sichert den API-Vertrag des Widerspruchs ohne Browser-E2E ab.

Die Fälle laufen gegen ``scripts/widerspruch-api-pruefung.mjs``, dieselbe
Funktion, die der E2E-Test für Positivfall und Negativfall nutzt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

WURZEL = Path(__file__).resolve().parents[1]
MODUL = WURZEL / "scripts" / "widerspruch-api-pruefung.mjs"

WIDERSPRUCH: dict[str, Any] = {
    "claim_id": 7,
    "grund": "Richtung steigt gegen sinkt",
    "sicherheit": 0.8,
    "quelle_a": "e2e-a.example",
    "quelle_b": "e2e-b.example",
    "wert_a_bp": 450,
    "wert_b_bp": 400,
}


def _node() -> str:
    pfad = shutil.which("node")
    if not pfad:
        pytest.skip("node ist nicht installiert")
    return pfad


def _status(
    widersprueche: list[dict[str, Any]] | None = None,
    top: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "claims": {
            "top": top if top is not None else [
                {"id": 7, "kernaussage": "Richtung steigt", "status": "widersprüchlich"}
            ],
            "widersprueche": (
                [dict(WIDERSPRUCH)] if widersprueche is None else widersprueche
            ),
        },
    }


def _pruefe(status: dict[str, Any], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    datei = tmp_path / "status.json"
    datei.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    return subprocess.run(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
        [_node(), str(MODUL), "--status", str(datei)],
        capture_output=True,
        # Node schreibt UTF-8; ohne feste Kodierung dekodiert Windows mit cp1252
        # und macht aus «×» ein Ersatzzeichen.
        text=True,
        encoding="utf-8",
        cwd=WURZEL,
        check=False,
    )


def test_gueltige_antwort_besteht(tmp_path: Path) -> None:
    lauf = _pruefe(_status(), tmp_path)
    assert lauf.returncode == 0, lauf.stderr
    assert "Widerspruch-API OK: Claim 7" in lauf.stdout


def test_fehlende_zeile_wird_als_fehler_erkannt(tmp_path: Path) -> None:
    lauf = _pruefe(_status(widersprueche=[]), tmp_path)
    assert lauf.returncode == 1
    assert "API enthält den erwarteten Widerspruch nicht" in lauf.stderr


def test_falsche_claim_id_wird_als_fehler_erkannt(tmp_path: Path) -> None:
    lauf = _pruefe(_status(widersprueche=[dict(WIDERSPRUCH, claim_id=999)]), tmp_path)
    assert lauf.returncode == 1
    assert "API-Claim 999 fehlt in claims.top" in lauf.stderr


def test_doppelte_zeile_wird_als_fehler_erkannt(tmp_path: Path) -> None:
    lauf = _pruefe(_status(widersprueche=[dict(WIDERSPRUCH), dict(WIDERSPRUCH)]), tmp_path)
    assert lauf.returncode == 1
    assert "mehrfach (2×)" in lauf.stderr
