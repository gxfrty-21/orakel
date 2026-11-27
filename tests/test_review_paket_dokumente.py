"""Tests für die Begleitdokumente des Review-Pakets.

Die Dokumente dürfen nur Zahlen nennen, die aus ``MANIFEST.json``, der
``EVIDENZ.json`` und dem tatsächlichen ZIP stammen. Der Test baut dafür ein
minimales Paket und prüft jede Zahl gegen die Quelle.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "erzeuge_review_dokumente.py"
BUILDER = ROOT / "scripts" / "baue_review_paket.py"


def _lade(pfad: Path, name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, pfad)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _paket(tmp_path: Path) -> Path:
    """Legt MANIFEST, EVIDENZ, ZIP und einen vorhandenen Beleg an."""
    dateien = [
        {"target": "dateien/README.md", "sha256": "a" * 64, "bytes": 3,
         "herkunft": "commit"},
        {"target": "dateien/tests/test_x.py", "sha256": "b" * 64, "bytes": 4,
         "herkunft": "commit"},
        {"target": "EVIDENZ.md", "sha256": "c" * 64, "bytes": 5,
         "herkunft": "paketdokument"},
    ]
    (tmp_path / "EVIDENZ.json").write_text(
        json.dumps({"testzahl": 7, "uebersprungen": 0, "dateien": []}),
        encoding="utf-8")
    (tmp_path / "EVIDENZ.md").write_text("# Evidenz\n", encoding="utf-8")
    (tmp_path / "MANIFEST.json").write_text(json.dumps({
        "schema": "review-paket.v6",
        "commit": "a" * 40,
        "branch": "main",
        "dirty": False,
        "quellgruppen": [
            {"name": "tests", "praefix": "dateien/tests/", "dateien": 1, "bytes": 4},
        ],
        "files": dateien,
    }), encoding="utf-8")
    (tmp_path / "belege").mkdir()
    (tmp_path / "belege" / "vorhanden.log").write_text("ok\n", encoding="utf-8")
    with zipfile.ZipFile(tmp_path / "ORAKEL-REVIEW-PAKET.zip", "w") as archiv:
        for name in ("EVIDENZ.md", "MANIFEST.json", "ORAKEL-REVIEW-PAKET.md",
                     "dateien/README.md"):
            archiv.writestr(name, "x")
    return tmp_path


def _freigabe() -> dict:
    return {
        "belege": ["belege/vorhanden.log", "belege/fehlt.log"],
        "dokumente": ["EVIDENZ.md"],
        "ausnahmen": [],
    }


def test_dokumente_nennen_dieselben_zahlen_wie_manifest_und_zip(tmp_path):
    paket = _paket(tmp_path)
    generator = _lade(GENERATOR, "erzeuge_review_dokumente_test")
    builder = _lade(BUILDER, "baue_review_paket_dokumente_test")

    zahlen = generator.erzeuge(paket, _freigabe(), builder, stand="1. Januar 2026")

    manifest = json.loads((paket / "MANIFEST.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(paket / "ORAKEL-REVIEW-PAKET.zip") as archiv:
        zip_eintraege = len(archiv.namelist())
    assert zahlen == {"dateien": len(manifest["files"]),
                      "zip_eintraege": zip_eintraege, "fehlende": 1}

    quickstart = (paket / "QUICKSTART.md").read_text(encoding="utf-8")
    treffer = re.search(r"(\d+) Dateien \((\d+) ZIP-Einträge\)", quickstart)
    assert treffer is not None
    assert int(treffer.group(1)) == len(manifest["files"])
    assert int(treffer.group(2)) == zip_eintraege

    quellen = (paket / "QUELLEN-DECKUNG.md").read_text(encoding="utf-8")
    assert "1 älterer Beleg" in quellen
    delta = (paket / "DELTA-CHANGELOG.md").read_text(encoding="utf-8")
    assert f"{len(manifest['files'])} Dateien ({zip_eintraege} ZIP-Einträge)" in delta

    bericht = (paket / "ORAKEL-REVIEW-PAKET.md").read_text(encoding="utf-8")
    assert f"Paketdateien: {len(manifest['files'])}" in bericht
    fehlend = bericht.partition("## Nicht im Paket")[2]
    assert "`belege/fehlt.log`" in fehlend
    assert "ORAKEL-REVIEW-PAKET.md" not in fehlend
    assert "`belege/vorhanden.log`" not in fehlend


def test_fehlende_belege_zaehlen_nicht_die_berichtsdatei_mit(tmp_path):
    """Der Bericht selbst ist kein fehlender Beleg; die Zahl bleibt stabil."""
    paket = _paket(tmp_path)
    generator = _lade(GENERATOR, "erzeuge_review_dokumente_test")
    builder = _lade(BUILDER, "baue_review_paket_dokumente_test")
    freigabe = _freigabe()
    freigabe["belege"] = ["belege/vorhanden.log"]

    zahlen = generator.erzeuge(paket, freigabe, builder, stand="1. Januar 2026")

    assert zahlen["fehlende"] == 0
    assert "Nicht enthalten sind 0 ältere Belege" in (
        paket / "QUELLEN-DECKUNG.md").read_text(encoding="utf-8")
