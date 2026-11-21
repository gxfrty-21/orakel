"""Hält die Grenze zwischen Handelskern und Oberfläche (Bereich 4.1).

Der Vertrag steht zusätzlich in ``.importlinter`` und läuft als eigener
CI-Job. Dieser Test prüft dieselbe Regel ohne Zusatzpaket, damit ein Verstoss
schon im normalen ``pytest``-Lauf auffällt.

Zusätzlich liest er die verbotenen Module direkt aus ``.importlinter`` und
hält den Docstring von ``orakel/kern/__init__.py`` dagegen: Eine dort
behauptete Erlaubnis, die der Vertrag verbietet, fällt damit auf. Anlass war
ein Docstring, der ``orakel.seed`` als gemeinsame Basis nannte, während der
Vertrag es ausdrücklich sperrt.
"""
from __future__ import annotations

import ast
import configparser
import re
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
KERN = WURZEL / "orakel" / "kern"
VERTRAG = WURZEL / ".importlinter"
INIT = KERN / "__init__.py"
MODULNAME = re.compile(r"\borakel(?:\.[a-z_][a-z0-9_]*)+")

ERWARTETE_MODULE = {
    "backtest", "data", "db", "judge", "kosten", "markt", "metrics", "migrationen",
    "paper", "risk", "strategies",
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


def _vertrag() -> list[str]:
    """Verbotene Module aus dem Import-Linter-Vertrag in ``.importlinter``."""
    leser = configparser.ConfigParser()
    leser.read(VERTRAG, encoding="utf-8")
    abschnitte = [name for name in leser.sections() if "kern" in name]
    assert abschnitte, f"Kein Kern-Vertrag in {VERTRAG.name}"
    roh = leser.get(abschnitte[0], "forbidden_modules", fallback="")
    return [zeile.strip() for zeile in roh.splitlines() if zeile.strip()]


def _docstring() -> str:
    return ast.get_docstring(ast.parse(INIT.read_text(encoding="utf-8"))) or ""


def _erlaubt_satz(text: str) -> str:
    """Der Satz, der die erlaubten Importe nennt («… darf … importieren»)."""
    for satz in re.split(r"(?<=\.)\s+", " ".join(text.split())):
        if "darf" in satz and "importieren" in satz:
            return satz
    return ""


def _ist_verboten(modul: str, verboten: list[str]) -> bool:
    return any(modul == eintrag or modul.startswith(eintrag + ".")
               for eintrag in verboten)


def _docstring_fehler(text: str, verboten: list[str]) -> list[str]:
    """Widersprüche zwischen Kern-Docstring und Vertrag (leer = stimmig).

    Der Docstring darf nur ``orakel.config`` als gemeinsame Basis nennen und
    sonst ausschliesslich Module, die der Vertrag verbietet. Eine Aussage wie
    «erlaubt sind orakel.config und orakel.seed» fällt damit auf, obwohl sie
    sprachlich plausibel klingt.
    """
    satz = _erlaubt_satz(text)
    if not satz:
        return ["Docstring nennt keinen Satz mit den erlaubten Importen"]
    erlaubt = set(MODULNAME.findall(satz))
    fehler = [f"erlaubt {modul}, obwohl .importlinter es verbietet"
              for modul in sorted(erlaubt) if _ist_verboten(modul, verboten)]
    if "orakel.config" not in erlaubt:
        fehler.append("nennt die gemeinsame Basis orakel.config nicht")
    for modul in sorted(set(MODULNAME.findall(text)) - erlaubt - {"orakel.config"}):
        if not _ist_verboten(modul, verboten):
            fehler.append(f"nennt {modul}, das weder erlaubt noch im Vertrag verboten ist")
    return fehler


def test_vertrag_und_test_kennen_dieselben_verbote():
    """Die harte Liste im Test darf nicht vom Vertrag abweichen."""
    assert set(_vertrag()) == VERBOTEN


def test_docstring_des_kerns_passt_zum_vertrag():
    assert _docstring_fehler(_docstring(), _vertrag()) == []


def test_docstring_pruefung_erkennt_falsche_erlaubnis():
    """Der alte, falsche Docstring muss auffallen."""
    alt = (
        "Der Kern darf ausschliesslich Module aus diesem Paket sowie die gemeinsame "
        "Basis (``orakel.config``, ``orakel.seed``) importieren. Alles, was Web, "
        "Agenten, Nexus oder Raumschiff betrifft, bleibt draussen."
    )

    fehler = _docstring_fehler(alt, _vertrag())

    assert any("orakel.seed" in zeile for zeile in fehler), fehler
