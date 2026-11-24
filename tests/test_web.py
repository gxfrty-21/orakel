from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orakel import web
from orakel.company.store import CompanyStore
from orakel.kern.db import Facts
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


def test_import_der_web_app_braucht_keine_konfigurationsdatei(tmp_path):
    umgebung = dict(os.environ)
    umgebung["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    lauf = subprocess.run(
        [sys.executable, "-c", "from orakel.web import create_app"],
        cwd=tmp_path,
        env=umgebung,
        capture_output=True,
        text=True,
    )

    assert lauf.returncode == 0, lauf.stderr


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


def test_bericht_endpunkt_nutzt_geladene_konfiguration(cfg, monkeypatch):
    aufrufe: list[str] = []

    def zaehle(pfad):
        aufrufe.append(pfad)
        return cfg

    monkeypatch.setattr(web, "load_config", zaehle)
    client = TestClient(web.create_app())

    antwort = client.get("/api/report")

    assert antwort.status_code == 200
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


def test_serve_ohne_zugangsdaten_nur_auf_loopback(monkeypatch):
    monkeypatch.delenv("ORAKEL_AUTH_USER", raising=False)
    monkeypatch.delenv("ORAKEL_AUTH_PASS", raising=False)
    monkeypatch.delenv("ORAKEL_ALLOW_NO_AUTH", raising=False)

    for host in ("127.0.0.1", "localhost", "::1"):
        web.create_app(host=host)  # darf nicht werfen

    # Die Adressen werden hier nur übergeben; gebunden wird nichts (S104).
    for host in ("0.0.0.0", "192.168.0.10", "::"):  # noqa: S104 - Testdaten, kein Bind
        with pytest.raises(RuntimeError):
            web.create_app(host=host)


def test_serve_ohne_zugangsdaten_nie_extern_auch_nicht_mit_altlast(monkeypatch):
    monkeypatch.delenv("ORAKEL_AUTH_USER", raising=False)
    monkeypatch.delenv("ORAKEL_AUTH_PASS", raising=False)
    monkeypatch.setenv("ORAKEL_ALLOW_NO_AUTH", "1")

    # Eine alte Umgebungsvariable darf einen externen Bind ohne Login nicht
    # wieder freischalten; der Neustart muss fail-closed bleiben.
    with pytest.raises(RuntimeError):
        web.create_app(host="0.0.0.0")  # noqa: S104 - geprüft wird die Freigabe, kein Bind


def test_serve_mit_zugangsdaten_auf_externer_adresse(monkeypatch):
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")

    # Testabsicht: mit Zugangsdaten ist die externe Adresse erlaubt.
    web.create_app(host="0.0.0.0")  # noqa: S104 - geprüft wird die Freigabe, kein Bind


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

    # Voller Pfad zur Shell, damit kein Eintrag aus PATH aufgelöst wird (S607).
    shell = shutil.which("sh")
    assert shell is not None
    for allow_no_auth in (None, "1"):
        lauf_umgebung = dict(umgebung)
        if allow_no_auth is not None:
            lauf_umgebung["ORAKEL_ALLOW_NO_AUTH"] = allow_no_auth
        lauf = subprocess.run([shell, str(skript)], env=lauf_umgebung,  # noqa: S603 - fester Programmaufruf mit Argumentliste, ohne Shell
                              capture_output=True, text=True)

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
