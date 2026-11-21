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


def _pflicht_fehler(tmp_path: Path, markup: str) -> list[str]:
    """Prüft ein Minimalprojekt und liefert nur die Pflichtverweis-Befunde."""
    pruefer = _lade_pruefer()
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "pr-schutz.md").write_text("# Schutz\n", encoding="utf-8")
    (tmp_path / "docs" / "anderes.md").write_text("# Anderes\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(f"# Haupt\n{markup}\n", encoding="utf-8")

    _, _, _, befunde = pruefer.pruefe(tmp_path)

    return [befund for befund in befunde if "Pflichtverweis" in befund]


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
    assert len(_pflicht_fehler(tmp_path, markup)) == erwartete_fehler


@pytest.mark.parametrize(
    ("markup", "erwartete_fehler"),
    [
        # Genutzte Referenz auf das Pflichtziel, zusätzlich eine ungenutzte
        # Definition auf dasselbe Ziel: gültig, kein Pflichtverweis-Fehler.
        (
            "[Schutz][schutz]\n"
            "[schutz]: docs/pr-schutz.md\n"
            "[ungenutzt]: docs/pr-schutz.md",
            0,
        ),
        # Nur eine fremde Referenz genutzt, die Pflichtdefinition bleibt
        # ungenutzt: der Pflichtverweis fehlt trotz vorhandener Definition.
        (
            "[Andere][anderes]\n"
            "[anderes]: docs/anderes.md\n"
            "[schutz]: docs/pr-schutz.md",
            1,
        ),
    ],
)
def test_pflichtverweis_trennt_genutzte_von_ungenutzten_definitionen(
    tmp_path: Path, markup: str, erwartete_fehler: int
) -> None:
    assert len(_pflicht_fehler(tmp_path, markup)) == erwartete_fehler


@pytest.mark.parametrize(
    ("markup", "erwartete_fehler"),
    [
        # Label steht nur im Linktext eines Inline-Links auf ein anderes Ziel:
        # kein sichtbarer Pflichtlink, der Pflichtverweis fehlt.
        (
            "[Anderes [ref]](docs/anderes.md)\n[ref]: docs/pr-schutz.md",
            1,
        ),
        (
            "[Anderes [ref] hier](docs/anderes.md)\n[ref]: docs/pr-schutz.md",
            1,
        ),
        # Label steht nur im Alttext eines Bildes.
        ("![Alt [ref]](bild.png)\n[ref]: docs/pr-schutz.md", 1),
        # Label steht nur im Linktext eines Referenzlinks auf ein anderes Ziel.
        (
            "[Anderes [ref]][ziel]\n"
            "[ziel]: docs/anderes.md\n"
            "[ref]: docs/pr-schutz.md",
            1,
        ),
        # Gültig: Shortcut-Link mit Text dahinter.
        ("[Schutz] ist hier verlinkt\n[Schutz]: docs/pr-schutz.md", 0),
        # Gültig: sichtbarer Inline-Link, dessen Linktext das Label enthält.
        ("[[ref]](docs/pr-schutz.md)\n[ref]: docs/pr-schutz.md", 0),
        # Gültig: Vollreferenz unverändert.
        ("[Schutz][ref]\n[ref]: docs/pr-schutz.md", 0),
    ],
)
def test_pflichtverweis_ignoriert_labels_in_fremden_linktexten(
    tmp_path: Path, markup: str, erwartete_fehler: int
) -> None:
    assert len(_pflicht_fehler(tmp_path, markup)) == erwartete_fehler
