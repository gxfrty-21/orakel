from __future__ import annotations

import base64
import hashlib

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


def test_config_wird_nur_einmal_geladen(cfg, monkeypatch):
    aufrufe: list[str] = []

    def zaehle(pfad):
        aufrufe.append(pfad)
        return cfg

    monkeypatch.setattr(web, "load_config", zaehle)
    client = TestClient(web.create_app())

    for _ in range(3):
        assert client.get("/api/company/paper-guard").status_code == 200

    assert len(aufrufe) == 1


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
