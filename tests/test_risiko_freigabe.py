"""Risikostopp-Freigabe: kein Einzelkurs-Reset, belastbare Takte zählen.

Ein aktiver Stopp bleibt aktiv, solange die Bewertung unsicher ist. Erst
mehrere aufeinanderfolgende Takte mit vollständig aktuellen Kursen geben ihn
frei; fehlende Kurse setzen den Zähler zurück.
"""
from __future__ import annotations

from datetime import datetime, timezone

from orakel.db import Facts
from orakel.paper import tick

from test_paper_datenqualitaet import baue_df


def konto_mit_stopp(cfg) -> Facts:
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern("TEST", "M15", baue_df([100.0] * 10).to_dict("records"))
    db.position_setzen("TEST", 10.0, 100.0, 1.0, "{}", "2026-01-01T00:00:00+00:00")
    db.zustand_setzen("paper_konto", {
        "cash": 99_000.0, "hoechststand": 100_000.0,
        "tagesstart": 100_000.0, "datum": "2026-01-01",
    })
    db.zustand_setzen("risiko_stopp", {"grund": "vorheriger Drawdown",
                                       "gesunde_takte": 0})
    return db


def test_stopp_bleibt_nach_einem_gesunden_takt_aktiv(cfg):
    db = konto_mit_stopp(cfg)

    ergebnis = tick(cfg, db)

    assert db.zustand("risiko_stopp") is not None
    assert db.zustand("risiko_stopp")["gesunde_takte"] == 1
    assert ergebnis["gestoppt"] is True
    assert any("1/2" in r["text"] for r in db.ereignisse(10))


def test_stopp_wird_nach_zwei_gesunden_takten_freigegeben(cfg):
    db = konto_mit_stopp(cfg)

    tick(cfg, db)
    tick(cfg, db, datetime.now(timezone.utc))

    assert db.zustand("risiko_stopp") is None
    assert any("freigegeben" in r["text"] for r in db.ereignisse(10))


def test_fehlende_kurse_setzen_den_zaehler_zurueck(cfg):
    db = konto_mit_stopp(cfg)
    tick(cfg, db)
    assert db.zustand("risiko_stopp")["gesunde_takte"] == 1

    with db.conn() as c:
        c.execute("DELETE FROM kerzen")
    ergebnis = tick(cfg, db)

    assert ergebnis["gestoppt"] is True
    assert db.zustand("risiko_stopp") is not None
    assert db.zustand("risiko_stopp")["gesunde_takte"] == 0
    assert any("Bewertung unsicher" in r["text"] for r in db.ereignisse(10))


def test_konfigurierbare_freigabe_takte(cfg):
    cfg._d["risiko"]["risiko_stopp_freigabe_takte"] = 3
    db = konto_mit_stopp(cfg)

    tick(cfg, db)
    tick(cfg, db)
    assert db.zustand("risiko_stopp") is not None
    tick(cfg, db)

    assert db.zustand("risiko_stopp") is None


def test_aktiver_stopp_blockiert_einstieg_trotz_frischer_kurse(cfg):
    db = konto_mit_stopp(cfg)

    ergebnis = tick(cfg, db)

    assert ergebnis["gestoppt"] is True
    assert "Risikostopp aktiv" in ergebnis["einstiege_gesperrt"]
