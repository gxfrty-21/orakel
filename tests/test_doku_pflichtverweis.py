"""Tests für den Pflichtverweis auf die Schutz-Dokumentation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJEKT = Path(__file__).resolve().parents[1]
SKRIPT = PROJEKT / "scripts" / "pruefe_doku.py"


def _lade_pruefer():
    spec = importlib.util.spec_from_file_location("pruefe_doku_pflicht", SKRIPT)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


@pytest.mark.parametrize(
    ("markup", "erwartete_fehler"),
    [
        ("[Schutz](docs/pr-schutz.md)", 0),
        ("![Schutz](docs/pr-schutz.md)", 1),
        ('<img src="docs/pr-schutz.md">', 1),
        ('<a href="docs/pr-schutz.md">Schutz</a>', 0),
        ("[Schutz][ref]\n[ref]: docs/pr-schutz.md", 0),
        ("[ref]: docs/pr-schutz.md", 1),
        ("![Schutz][ref]\n[ref]: docs/pr-schutz.md", 1),
        ("[Schutz][]\n[Schutz]: docs/pr-schutz.md", 0),
        ("[Schutz]\n[Schutz]: docs/pr-schutz.md", 0),
    ],
)
def test_pflichtverweis_akzeptiert_nur_sichtbare_links(
    tmp_path: Path, markup: str, erwartete_fehler: int
) -> None:
    pruefer = _lade_pruefer()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "pr-schutz.md").write_text("# Schutz\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(f"# Haupt\n{markup}\n", encoding="utf-8")

    _, _, _, befunde = pruefer.pruefe(tmp_path)

    pflicht_fehler = [befund for befund in befunde if "Pflichtverweis" in befund]
    assert len(pflicht_fehler) == erwartete_fehler
