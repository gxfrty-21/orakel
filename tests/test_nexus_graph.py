from __future__ import annotations

from datetime import datetime, timezone

from orakel.db import Facts
from orakel.nexus.graph import graph_auffrischen, graph_daten

ZEIT = "2026-11-10T05:00:00+00:00"
JETZT = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _db_mit_claim(tmp_path) -> Facts:
    db = Facts(tmp_path / "orakel.db")
    quellen = [
        {"quelle_id": "a", "name": "Quelle A", "host": "a.example", "gewicht": 0.8,
         "artikel": 1, "analysiert": 1, "bestaetigt": 0, "widerlegt": 0,
         "widersprueche": 0, "reputation": 0.8, "vertrauen": "vorläufig",
         "aktualisiert": ZEIT},
        {"quelle_id": "b", "name": "Quelle B", "host": "b.example", "gewicht": 0.8,
         "artikel": 1, "analysiert": 1, "bestaetigt": 0, "widerlegt": 0,
         "widersprueche": 0, "reputation": 0.8, "vertrauen": "vorläufig",
         "aktualisiert": ZEIT},
    ]
    claims = [{
        "id": 1, "claim_key": "makro|ezb|leitzins",
        "kernaussage": "EZB hebt den Leitzins auf 4,5 Prozent",
        "thema": "makro", "subjekt": "ezb", "metrik": "leitzins",
        "quellen": 2, "belege": 2, "widersprueche": 0,
        "bestaetigungsgrad": 0.82, "status": "bestätigt",
        "erstmals": ZEIT, "aktualisiert": ZEIT,
    }]
    claim_quellen = [
        {"id": 1, "claim_id": 1, "meldung_key": "m-a", "artikel_id": 1,
         "quelle_id": "a", "host": "a.example",
         "aussage": "EZB hebt den Leitzins auf 4,5 Prozent", "richtung": "steigt",
         "wert": 4.5, "einheit": "%", "negiert": 0, "ist_kopie": 0,
         "reputation": 0.8, "erstellt": ZEIT},
        {"id": 2, "claim_id": 1, "meldung_key": "m-b", "artikel_id": 2,
         "quelle_id": "b", "host": "b.example",
         "aussage": "EZB erhöht den Leitzins auf 4,5 Prozent", "richtung": "steigt",
         "wert": 4.5, "einheit": "%", "negiert": 0, "ist_kopie": 0,
         "reputation": 0.8, "erstellt": ZEIT},
    ]
    widersprueche = [{
        "id": 1, "claim_id": 1, "meldung_a": "m-a", "meldung_b": "m-b",
        "quelle_a": "a.example", "quelle_b": "b.example",
        "grund": "Richtung steigt gegen sinkt", "sicherheit": 0.8,
        "erstellt": ZEIT,
    }]
    db.nexus_bewertung_ersetzen(quellen, claims, claim_quellen, widersprueche)
    return db


def test_graph_wird_persistiert_und_aus_db_gelesen(tmp_path):
    db = _db_mit_claim(tmp_path)
    aufbau = graph_auffrischen(db)
    assert aufbau["kanten"] == 4
    assert aufbau["arten"]["gehoert_zu"] == 1
    assert aufbau["arten"]["belegt_durch"] == 2
    assert aufbau["arten"]["widerspruch"] == 1

    daten = graph_daten(db, "7d", JETZT)
    assert daten["ok"] is True
    assert daten["statistik"]["knoten"] == 4
    assert daten["statistik"]["kanten"] == 4
    assert {k["art"] for k in daten["kanten"]} == {
        "gehoert_zu", "belegt_durch", "widerspruch",
    }
    assert any(k["typ"] == "claim" for k in daten["knoten"])
    assert any(k["typ"] == "quelle" for k in daten["knoten"])


def test_graph_rebuild_ist_idempotent(tmp_path):
    db = _db_mit_claim(tmp_path)
    graph_auffrischen(db)
    erster = graph_daten(db, "alle", JETZT)
    graph_auffrischen(db)
    zweiter = graph_daten(db, "alle", JETZT)

    assert erster["statistik"] == zweiter["statistik"]
    assert [(k["von"], k["nach"], k["art"]) for k in erster["kanten"]] == [
        (k["von"], k["nach"], k["art"]) for k in zweiter["kanten"]
    ]


def test_zeitfilter_nutzt_den_echten_kantenzeitpunkt(tmp_path):
    db = _db_mit_claim(tmp_path)
    graph_auffrischen(db)

    assert graph_daten(db, "24h", JETZT)["statistik"]["kanten"] == 4
    assert graph_daten(db, "24h", datetime(2026, 11, 12, 12, tzinfo=timezone.utc))[
        "statistik"
    ]["kanten"] == 0


def test_leerer_graph_erfindet_keine_knoten(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    aufbau = graph_auffrischen(db)
    daten = graph_daten(db, "7d", JETZT)

    assert aufbau["kanten"] == 0
    assert daten["kanten"] == []
    assert daten["knoten"] == []
    assert "Noch keine Graphkanten" in daten["hinweis"]
