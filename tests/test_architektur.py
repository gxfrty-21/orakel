"""Hält die Grenze zwischen Handelskern und Oberfläche (Bereich 4.1).

Der Vertrag steht zusätzlich in ``.importlinter`` und läuft als eigener
CI-Job. Dieser Test prüft dieselbe Regel ohne Zusatzpaket, damit ein Verstoss
schon im normalen ``pytest``-Lauf auffällt.
"""
from __future__ import annotations

import ast
from pathlib import Path

KERN = Path(__file__).resolve().parents[1] / "orakel" / "kern"

ERWARTETE_MODULE = {
    "backtest", "data", "db", "judge", "markt", "metrics", "migrationen", "paper",
    "risk", "strategies",
}

# Module, die der Kern niemals importieren darf.
VERBOTEN = {
    "orakel.web", "orakel.__main__", "orakel.agents", "orakel.betrieb",
    "orakel.company", "orakel.globe", "orakel.intel", "orakel.knowledge",
    "orakel.nexus", "orakel.pipeline", "orakel.report", "orakel.scheduler",
    "orakel.seed", "orakel.sekretariat", "orakel.spider", "orakel.watchdog",
}


def _zielmodul(knoten: ast.ImportFrom) -> str:
    """Absoluter Modulname einer relativen Importzeile in orakel/kern."""
    if knoten.level == 1:
        basis = "orakel.kern"
    elif knoten.level == 2:
        basis = "orakel"
    else:
        basis = ""
    teile = [teil for teil in (basis, knoten.module or "") if teil]
    return ".".join(teile)


def _verstoesse(quelle: str, dateiname: str = "beispiel.py") -> list[str]:
    baum = ast.parse(quelle, filename=dateiname)
    treffer: list[str] = []
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.ImportFrom):
            ziel = _zielmodul(knoten)
        elif isinstance(knoten, ast.Import):
            ziel = ""
        else:
            continue
        namen = [ziel] if ziel else []
        if isinstance(knoten, ast.Import):
            namen = [alias.name for alias in knoten.names
                     if alias.name.startswith("orakel")]
        for name in namen:
            for verboten in VERBOTEN:
                if name == verboten or name.startswith(verboten + "."):
                    treffer.append(f"{dateiname}:{knoten.lineno} {name}")
    return treffer


def test_kern_importiert_keine_ui_module():
    verstoesse: list[str] = []
    for pfad in sorted(KERN.glob("*.py")):
        verstoesse += _verstoesse(pfad.read_text(encoding="utf-8"), pfad.name)

    assert verstoesse == [], "Kern importiert Oberfläche: " + ", ".join(verstoesse)


def test_kern_enthaelt_genau_die_handelsmodule():
    gefunden = {pfad.stem for pfad in KERN.glob("*.py")} - {"__init__"}
    assert gefunden == ERWARTETE_MODULE


def test_pruefung_erkennt_echten_verstoss():
    """Der Wächter darf nicht stillschweigend grün sein."""
    quelle = "from ..web import create_app\nfrom ..kern import paper\n"

    treffer = _verstoesse(quelle)

    assert treffer == ["beispiel.py:1 orakel.web"], treffer
