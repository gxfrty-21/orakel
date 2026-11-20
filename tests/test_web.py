from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orakel import web
from orakel.company.store import CompanyStore
from orakel.db import Facts
from orakel.web import _basic_ok


def kopf(benutzer: str, passwort: str) -> str:
    return "Basic " + base64.b64encode(f"{benutzer}:{passwort}".encode()).decode()


def test_basic_auth_akzeptiert_nur_richtige_daten():
    assert _basic_ok(kopf("orakel", "geheim"), "orakel", "geheim")
    assert _basic_ok(kopf("orakel", "ge:heim"), "orakel", "ge:heim")
    assert _basic_ok(kopf("orakel", "Paßwört"), "orakel", "Paßwört")
    assert not _basic_ok(kopf("orakel", "falsch"), "orakel", "geheim")
    assert not _basic_ok(kopf("anderer", "geheim"), "orakel", "geheim")


def test_basic_auth_lehnt_kaputte_und_leere_header_ab():
    assert not _basic_ok("", "orakel", "geheim")
    assert not _basic_ok("Bearer token", "orakel", "geheim")
    assert not _basic_ok("Basic !!!", "orakel", "geheim")
    assert not _basic_ok("Basic " + base64.b64encode(b"ohne-doppelpunkt").decode(),
                         "orakel", "geheim")
    assert not _basic_ok(kopf("orakel", "geheim"), "", "")


def test_paper_guard_http_mit_basic_auth(cfg, monkeypatch):
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    client = TestClient(web.create_app())

    ohne_login = client.get("/api/company/paper-guard")
    assert ohne_login.status_code == 401
    assert ohne_login.headers["www-authenticate"].startswith("Basic")

    falsches_passwort = client.get(
        "/api/company/paper-guard", auth=("orakel", "falsch"),
    )
    assert falsches_passwort.status_code == 401

    antwort = client.get(
        "/api/company/paper-guard", auth=("orakel", "geheim"),
    )
    assert antwort.status_code == 200
    assert antwort.headers["cache-control"] == "no-store"
    daten = antwort.json()
    assert daten["ok"] is True
    assert daten["paper_only"] is True
    assert daten["paper_order_allowed"] is True
    assert daten["broker"] == "csv"
    assert daten["order_freigabe"] is False
    assert "config:paper" in daten["source_refs"]
    assert "policy:paper" in daten["source_refs"]


def _dateien_hash(ordner) -> dict[str, str]:
    return {
        datei.name: hashlib.sha256(datei.read_bytes()).hexdigest()
        for datei in sorted(ordner.iterdir())
        if datei.is_file()
    }


def test_paper_guard_http_hat_keine_schreibenden_seiteneffekte(cfg, monkeypatch):
    db = Facts(cfg.db_pfad)
    store = CompanyStore(db)
    store.sync_roster()
    store.enqueue(
        task_key="test:paper-guard:lesend",
        assigned_to="A1",
        dept="A",
        title="Bleibt unverändert",
    )
    vorher_dateien = _dateien_hash(cfg.db_pfad.parent)
    vorher_tasks = store.task_counts()
    vorher_events = len(store.events())

    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    client = TestClient(web.create_app())

    antwort = client.get(
        "/api/company/paper-guard", auth=("orakel", "geheim"),
    )

    assert antwort.status_code == 200
    assert _dateien_hash(cfg.db_pfad.parent) == vorher_dateien
    assert store.task_counts() == vorher_tasks
    assert len(store.events()) == vorher_events
    assert store.audit_chain_ok()


def test_serve_ohne_zugangsdaten_nur_auf_loopback(monkeypatch):
    monkeypatch.delenv("ORAKEL_AUTH_USER", raising=False)
    monkeypatch.delenv("ORAKEL_AUTH_PASS", raising=False)
    monkeypatch.delenv("ORAKEL_ALLOW_NO_AUTH", raising=False)

    for host in ("127.0.0.1", "localhost", "::1"):
        web.create_app(host=host)  # darf nicht werfen

    for host in ("0.0.0.0", "192.168.0.10", "::"):
        with pytest.raises(RuntimeError):
            web.create_app(host=host)


def test_serve_ohne_zugangsdaten_nur_mit_ausnahme_extern(monkeypatch):
    monkeypatch.delenv("ORAKEL_AUTH_USER", raising=False)
    monkeypatch.delenv("ORAKEL_AUTH_PASS", raising=False)
    monkeypatch.setenv("ORAKEL_ALLOW_NO_AUTH", "1")

    web.create_app(host="0.0.0.0")  # bewusste Ausnahme


def test_serve_mit_zugangsdaten_auf_externer_adresse(monkeypatch):
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")

    web.create_app(host="0.0.0.0")  # Login vorhanden: erlaubt


def test_alle_post_routen_verlangen_anmeldung(cfg, monkeypatch):
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    app = web.create_app()
    client = TestClient(app)

    post_pfade = sorted(
        re.sub(r"\{[^}]+\}", "x", route.path)
        for route in app.routes
        if "POST" in getattr(route, "methods", set())
    )
    assert len(post_pfade) >= 15

    for pfad in post_pfade:
        antwort = client.post(pfad)
        assert antwort.status_code == 401, pfad


def test_schreibende_anfrage_von_fremder_herkunft_wird_abgewiesen(cfg, monkeypatch):
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.delenv("ORAKEL_ERLAUBTE_ORIGINS", raising=False)
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    client = TestClient(web.create_app())
    auth = ("orakel", "geheim")

    fremder_origin = client.post(
        "/api/company/messages",
        headers={"Origin": "https://boese.example"},
        auth=auth,
    )
    assert fremder_origin.status_code == 403
    assert fremder_origin.json()["code"] == "herkunft_abgelehnt"

    fremder_referer = client.post(
        "/api/company/messages",
        headers={"Referer": "https://boese.example/formular"},
        auth=auth,
    )
    assert fremder_referer.status_code == 403

    eigene_herkunft = client.post(
        "/api/company/messages",
        headers={"Origin": "http://testserver"},
        auth=auth,
    )
    assert eigene_herkunft.status_code != 403

    lesend = client.get(
        "/api/company/paper-guard",
        headers={"Origin": "https://boese.example"},
        auth=auth,
    )
    assert lesend.status_code == 200


def test_container_entrypoint_bricht_ohne_zugangsdaten_ab():
    skript = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"
    umgebung = {
        schluessel: wert
        for schluessel, wert in os.environ.items()
        if schluessel not in {
            "ORAKEL_AUTH_USER", "ORAKEL_AUTH_PASS", "ORAKEL_ALLOW_NO_AUTH",
        }
    }

    lauf = subprocess.run(
        ["sh", str(skript)], env=umgebung, capture_output=True, text=True,
    )

    assert lauf.returncode == 1
    assert "ORAKEL_AUTH_USER" in lauf.stderr
    assert "fail-closed" in lauf.stderr


def test_erlaubte_herkuenfte_konfigurierbar(cfg, monkeypatch):
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setenv("ORAKEL_ERLAUBTE_ORIGINS", "https://ui.example")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    client = TestClient(web.create_app())

    antwort = client.post(
        "/api/company/messages",
        headers={"Origin": "https://ui.example"},
        auth=("orakel", "geheim"),
    )
    assert antwort.status_code != 403

    weiterhin_fremd = client.post(
        "/api/company/messages",
        headers={"Origin": "https://boese.example"},
        auth=("orakel", "geheim"),
    )
    assert weiterhin_fremd.status_code == 403


def test_serverfehler_ohne_innendetails(cfg, monkeypatch):
    """500 nennt keine Interna; der Fehler steht im Serverprotokoll."""
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)

    def kaputt(*_a, **_k):
        raise RuntimeError("/srv/geheim/orakel.db ist gesperrt (Code 4711)")

    monkeypatch.setattr(web, "tick", kaputt)
    client = TestClient(web.create_app())

    antwort = client.post("/api/paper", auth=("orakel", "geheim"))

    assert antwort.status_code == 500
    assert antwort.json() == {"ok": False, "fehler": web.INTERNER_FEHLER,
                              "code": "interner_fehler"}
    assert "/srv/geheim" not in antwort.text
    assert "4711" not in antwort.text
    assert "RuntimeError" not in antwort.text
    protokoll = [zeile["text"] for zeile in Facts(cfg.db_pfad).ereignisse()]
    assert any("/srv/geheim/orakel.db" in text for text in protokoll)


def test_serverfehler_bei_der_konferenz(cfg, monkeypatch):
    """Auch die Konferenz protokolliert und antwortet generisch."""
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)

    def kaputt(*_a, **_k):
        raise KeyError("interne_kennung")

    monkeypatch.setattr(web.agents, "konferenz", kaputt)
    client = TestClient(web.create_app())

    antwort = client.post("/api/konferenz", auth=("orakel", "geheim"))

    assert antwort.status_code == 500
    assert "interne_kennung" not in antwort.text
    assert antwort.json()["code"] == "interner_fehler"
    assert any("Konferenz über API fehlgeschlagen" in zeile["text"]
               for zeile in Facts(cfg.db_pfad).ereignisse())


def test_kaputter_json_body_bleibt_ein_400(cfg, monkeypatch):
    """Der verengte Except fängt weiterhin kaputte Bodys ab."""
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    client = TestClient(web.create_app())

    antwort = client.post("/api/nexus/mission", content=b"kein json",
                          headers={"Content-Type": "application/json"},
                          auth=("orakel", "geheim"))

    assert antwort.status_code == 400
    assert antwort.json()["fehler"] == "Ungültiger JSON-Body"
