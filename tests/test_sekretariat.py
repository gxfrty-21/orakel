from __future__ import annotations

import re
from pathlib import Path

import pytest

from orakel import sekretariat as sek
from orakel.db import Facts
from orakel.knowledge import Vault


@pytest.fixture
def db(tmp_path: Path) -> Facts:
    return Facts(tmp_path / "orakel.db")


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "vault")


def _thema(thema: str = "Muster A", art: str = "muster", **extra) -> dict:
    basis = {
        "thema": thema, "art": art, "leiter": "S1", "netto": -120.5, "rendite": -0.8,
        "gemacht": "12 Trades mit EMA-Filter", "besser": "Filter enger fassen",
        "gelernt": "weniger Fehlsignale",
    }
    basis.update(extra)
    return basis


def _agenda(monkeypatch, *themen: dict) -> None:
    monkeypatch.setattr(sek, "agenda", lambda db, grenze=6: {"themen": list(themen)})


def _notiz(vault: Vault, titel: str, inhalt: str, datum: str, kategorie: str = "konferenz",
           tags: tuple[str, ...] = ("sitzung",)) -> Path:
    p = vault.notiz(kategorie, titel, inhalt, tags=list(tags))
    t = p.read_text(encoding="utf-8")
    t = re.sub(r"^erstellt: .*$", f"erstellt: {datum}", t, count=1, flags=re.M)
    p.write_text(t, encoding="utf-8")
    return p


def test_sitzung_start_aus_agenda(db, monkeypatch):
    _agenda(monkeypatch, _thema())

    s = sek.sitzung_start(db)

    assert s["status"] == "laeuft"
    t = s["themen"][0]
    assert t["index"] == 0
    assert t["phase"] == "rede" and t["schritt"] == 0
    assert [b["von"] for b in t["beitraege"]] == ["S1", "S2", "S3"]
    assert t["empfehlung"] == t["massnahme"] and t["empfehlung"]
    assert sek.sitzung(db)["status"] == "laeuft"


def test_sitzung_ohne_start_ist_offen(db):
    s = sek.sitzung(db)
    assert s["status"] == "offen" and s["themen"] == []


def test_drei_wortmeldungen_dann_abstimmung_und_beschluss(db, monkeypatch):
    _agenda(monkeypatch, _thema())
    sek.sitzung_start(db)

    for erwartet in (1, 2):
        s = sek.sitzung_weiter(db)
        t = s["themen"][0]
        assert t["phase"] == "rede" and t["schritt"] == erwartet

    # Die dritte Wortmeldung schliesst die Rede und öffnet die Abstimmung.
    s = sek.sitzung_weiter(db)
    assert s["themen"][0]["phase"] == "abstimmung"
    assert s["themen"][0]["schritt"] == 3
    assert s["themen"][0]["ergebnis"] is None

    s = sek.sitzung_weiter(db)
    t = s["themen"][0]
    assert t["phase"] == "ergebnis"
    assert t["ergebnis"] == "annehmen"
    assert t["zaehlung"] == {"annehmen": 3, "ablehnen": 0, "vertagen": 0}

    entscheid = s["entscheide"][0]
    assert entscheid["entscheid"] == "annehmen"
    kennung = entscheid["mission"]
    assert kennung.startswith("MS-")
    assert entscheid["abteilung"] == "C:Labor"
    with db.conn() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM nexus_tasks WHERE mission_id="
            "(SELECT id FROM nexus_missionen WHERE kennung=?)", (kennung,)).fetchone()[0]
    assert n == 3


def test_entschiedenes_thema_wechselt_zum_naechsten(db, monkeypatch):
    _agenda(monkeypatch, _thema("Erstes"), _thema("Zweites"))
    sek.sitzung_start(db)
    for _ in range(4):
        sek.sitzung_weiter(db)
    s = sek.sitzung_weiter(db)
    assert s["themen"][0]["status"] == "annehmen"
    assert s["aktiv"] == 1
    assert s["themen"][1]["status"] == "offen"


def test_befund_ohne_termin_wird_vertagt_und_gemerkt(db, monkeypatch):
    _agenda(monkeypatch, _thema("Offener Befund", art="befund", termin=None))
    sek.sitzung_start(db)
    for _ in range(4):
        s = sek.sitzung_weiter(db)
    assert s["themen"][0]["ergebnis"] == "vertagen"

    liste = db.zustand("sekretariat_vertagt")
    assert len(liste) == 1
    assert liste[0]["thema"] == "Offener Befund"
    assert liste[0]["art"] == "befund"
    assert liste[0]["vertagt_am"]


def test_abschluss_schreibt_protokoll_in_den_vault(db, vault, monkeypatch):
    _agenda(monkeypatch, _thema())
    sek.sitzung_start(db)
    for _ in range(4):
        sek.sitzung_weiter(db)

    s = sek.sitzung_abschluss(db, vault)

    assert s["status"] == "beendet"
    assert s["ergebnis"] == {"annehmen": 1, "ablehnen": 0, "vertagen": 0, "offen": 0}
    treffer, gesamt = sek.protokolle(vault)
    assert gesamt == 1
    assert "**Angenommen:** 1" in treffer[0]["inhalt"]
    assert "- [annehmen] Muster A" in treffer[0]["inhalt"]


def test_protokollsuche_filter_und_sortierung(vault):
    _notiz(vault, "Sitzung 2026-11-01T09:00",
           "**Angenommen:** 1\n\n- [annehmen] Alpha", "2026-11-01T09:00:00+00:00")
    _notiz(vault, "Sitzung 2026-11-12T18:00",
           "**Abgelehnt:** 2\n\n- [ablehnen] Beta", "2026-11-12T18:00:00+00:00")
    _notiz(vault, "Notiz ohne Sitzung", "**Angenommen:** 1", "2026-11-20T08:00:00+00:00",
           tags=("wissen",))

    alle, gesamt = sek.protokolle(vault)
    assert gesamt == 2
    assert [p["datum"] for p in alle] == ["2026-11-12", "2026-11-01"]

    alt, _ = sek.protokolle(vault, sortierung="alt")
    assert [p["datum"] for p in alt] == ["2026-11-01", "2026-11-12"]

    gefunden, _ = sek.protokolle(vault, suche="alpha")
    assert [p["datum"] for p in gefunden] == ["2026-11-01"]

    angenommen, _ = sek.protokolle(vault, entscheid="angenommen")
    assert [p["datum"] for p in angenommen] == ["2026-11-01"]
    abgelehnt, _ = sek.protokolle(vault, entscheid="abgelehnt")
    assert [p["datum"] for p in abgelehnt] == ["2026-11-12"]
    assert sek.protokolle(vault, entscheid="vertagt")[0] == []

    von, _ = sek.protokolle(vault, von="2026-11-05")
    assert [p["datum"] for p in von] == ["2026-11-12"]
    bis, _ = sek.protokolle(vault, bis="2026-11-05")
    assert [p["datum"] for p in bis] == ["2026-11-01"]


def test_vault_suche_mit_datums_und_entscheid_filter(vault):
    _notiz(vault, "Vaulttest Alt", "Alte Testnotiz.", "2026-11-01T09:00:00+00:00",
           kategorie="wissen", tags=("test",))
    _notiz(vault, "Vaulttest Entscheid", "**Angenommen:** 1\n\n- [annehmen] Testbeschluss",
           "2026-11-05T09:00:00+00:00", kategorie="wissen", tags=("test",))
    _notiz(vault, "Vaulttest Neu", "Neue Testnotiz.", "2026-11-10T09:00:00+00:00",
           kategorie="wissen", tags=("test",))

    alle, gesamt = sek.vault_suche(vault, suche="Vaulttest")
    assert gesamt == 3
    assert [p["titel"] for p in alle] == ["Vaulttest Neu", "Vaulttest Entscheid", "Vaulttest Alt"]

    angenommen, _ = sek.vault_suche(vault, suche="Vaulttest", entscheid="angenommen")
    assert [p["titel"] for p in angenommen] == ["Vaulttest Entscheid"]
    assert sek.vault_suche(vault, suche="Vaulttest", entscheid="abgelehnt")[0] == []

    bereich, _ = sek.vault_suche(vault, suche="Vaulttest", von="2026-11-05", bis="2026-11-10")
    assert [p["titel"] for p in bereich] == ["Vaulttest Neu", "Vaulttest Entscheid"]

    kombi, _ = sek.vault_suche(vault, suche="Vaulttest", entscheid="angenommen",
                               bis="2026-11-02")
    assert kombi == []
