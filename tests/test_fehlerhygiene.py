from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orakel import web

WURZEL = Path(__file__).resolve().parents[1]


def _stille_handler(datei: Path) -> list[int]:
    """Zeilen, an denen ein breiter except-Block nur pass/continue/break tut."""
    baum = ast.parse(datei.read_text(encoding="utf-8"), filename=str(datei))
    zeilen: list[int] = []
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.ExceptHandler):
            continue
        typ = knoten.type
        breit = typ is None or (
            isinstance(typ, ast.Name) and typ.id in {"Exception", "BaseException"}
        )
        if not breit:
            continue
        rumpf = [s for s in knoten.body
                 if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        if rumpf and all(isinstance(s, (ast.Pass, ast.Continue, ast.Break)) for s in rumpf):
            zeilen.append(knoten.lineno)
    return zeilen


def test_kein_except_block_schluckt_fehler_still():
    treffer = []
    for datei in sorted((WURZEL / "orakel").rglob("*.py")):
        for zeile in _stille_handler(datei):
            treffer.append(f"{datei.relative_to(WURZEL)}:{zeile}")

    assert treffer == [], (
        "Diese except-Blöcke verwerfen den Fehler ohne Meldung; bitte einordnen, "
        "eng fassen oder protokollieren: " + ", ".join(treffer)
    )


def test_interne_fehlertexte_gehen_nicht_an_den_client(cfg, monkeypatch):
    def kaputt(*_args, **_kwargs):
        raise RuntimeError("geheimer/pfad/zur/datenbank.sqlite")

    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    monkeypatch.setattr(web, "tick", kaputt)
    client = TestClient(web.create_app())

    antwort = client.post("/api/paper")

    assert antwort.status_code == 500
    assert "geheimer/pfad" not in antwort.text
    assert "datenbank.sqlite" not in antwort.text
    assert re.search(r"Interner Fehler \([0-9a-f]{32}\)", antwort.text)


def test_fehlerantworten_tragen_einen_stabilen_code(cfg, monkeypatch):
    """Clients reagieren auf ``code``, nicht auf den flüchtigen Text."""

    def kaputt(*_args, **_kwargs):
        raise RuntimeError("geheimer/pfad/zur/datenbank.sqlite")

    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    monkeypatch.setattr(web, "tick", kaputt)
    client = TestClient(web.create_app())

    daten = client.post("/api/paper").json()

    assert daten["ok"] is False
    assert daten["code"] == "interner_fehler"
    assert web._fehler_code(ValueError("Betrag fehlt")) == "eingabe"
    assert web._fehler_code(web.NutzerFehler("Betrag fehlt")) == "eingabe"


def test_eigene_validierungsfehler_bleiben_lesbar(cfg, monkeypatch):
    def ungueltig(*_args, **_kwargs):
        raise ValueError("Zeitrahmen muss M15 oder H1 sein")

    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    monkeypatch.setattr(web, "tick", ungueltig)
    client = TestClient(web.create_app())

    antwort = client.post("/api/paper")

    assert "Zeitrahmen muss M15 oder H1 sein" in antwort.text


def test_str_exc_steht_nur_noch_im_helfer():
    quelle = (WURZEL / "orakel" / "web.py").read_text(encoding="utf-8")

    assert quelle.count("str(exc)") == 1
    assert "def _fehler_text(exc: Exception) -> str:" in quelle
