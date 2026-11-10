from __future__ import annotations

from datetime import datetime, timezone

from orakel.db import Facts
from orakel.nexus.missionen import Missionen
from orakel.nexus.raum import raum_daten

ZEIT_TEXT = "2026-11-10T09:00:00+00:00"
JETZT = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _db_mit_claim(tmp_path) -> Facts:
    db = Facts(tmp_path / "orakel.db")
    quellen = [
        {"quelle_id": "a", "name": "Quelle A", "host": "a.example", "gewicht": 0.8,
         "artikel": 1, "analysiert": 1, "bestaetigt": 0, "widerlegt": 0,
         "widersprueche": 0, "reputation": 0.8, "vertrauen": "vorläufig",
         "aktualisiert": ZEIT_TEXT},
        {"quelle_id": "b", "name": "Quelle B", "host": "b.example", "gewicht": 0.8,
         "artikel": 1, "analysiert": 1, "bestaetigt": 0, "widerlegt": 0,
         "widersprueche": 0, "reputation": 0.8, "vertrauen": "vorläufig",
         "aktualisiert": ZEIT_TEXT},
    ]
    claims = [{
        "id": 1, "claim_key": "makro|ezb|leitzins",
        "kernaussage": "EZB hebt den Leitzins auf 4,5 Prozent",
        "thema": "makro", "subjekt": "ezb", "metrik": "leitzins",
        "quellen": 2, "belege": 2, "widersprueche": 0,
        "bestaetigungsgrad": 0.82, "status": "bestätigt",
        "erstmals": ZEIT_TEXT, "aktualisiert": ZEIT_TEXT,
    }]
    claim_quellen = [
        {"id": 1, "claim_id": 1, "meldung_key": "m-a", "artikel_id": 1,
         "quelle_id": "a", "host": "a.example",
         "aussage": "EZB hebt den Leitzins auf 4,5 Prozent", "richtung": "steigt",
         "wert": 4.5, "einheit": "%", "negiert": 0, "ist_kopie": 0,
         "reputation": 0.8, "erstellt": ZEIT_TEXT},
        {"id": 2, "claim_id": 1, "meldung_key": "m-b", "artikel_id": 2,
         "quelle_id": "b", "host": "b.example",
         "aussage": "EZB erhöht den Leitzins auf 4,5 Prozent", "richtung": "steigt",
         "wert": 4.5, "einheit": "%", "negiert": 0, "ist_kopie": 0,
         "reputation": 0.8, "erstellt": ZEIT_TEXT},
    ]
    db.nexus_bewertung_ersetzen(quellen, claims, claim_quellen, [])
    return db


def test_leerer_raum_erfindet_keine_aktivitaet(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    daten = raum_daten(db, "7d", JETZT)

    assert daten["ok"] is True
    assert daten["graph"]["knoten"] == []
    assert daten["graph"]["kanten"] == []
    assert daten["zahlen"]["knoten"] == 0
    assert daten["zahlen"]["kanten"] == 0
    assert daten["zahlen"]["missionen"] == 0
    assert daten["aktivitaet"]["status"] == "leer"
    assert daten["aktivitaet"]["events"] == []
    assert daten["aktivitaet"]["gespeichert"] == 0
    assert "Keine Missionen" in daten["aktivitaet"]["detail"]


def test_raum_zeigt_graph_und_echte_ereignisse(tmp_path):
    db = _db_mit_claim(tmp_path)
    Missionen(db, jetzt_funktion=lambda: JETZT).anlegen(
        "EZB Leitzins", "Prüfe die aktuelle Datenlage zum Leitzins der EZB.",
    )

    daten = raum_daten(db, "7d", JETZT)

    assert daten["graph"]["statistik"]["knoten"] == 4
    assert daten["graph"]["statistik"]["kanten"] == 3
    assert daten["zahlen"]["claims"] == 1
    assert daten["zahlen"]["missionen"] == 1
    assert daten["aktivitaet"]["status"] == "ruhig"
    assert daten["aktivitaet"]["laufend"] == 0
    assert daten["aktivitaet"]["tasks_aktiv"] == 0
    arten = {e["art"] for e in daten["aktivitaet"]["events"]}
    assert arten == {"mission", "claim", "quelle"}
    assert any("Mission angelegt" == e["titel"] for e in daten["aktivitaet"]["events"])
    assert any(e["referenz"] == "claim:1" for e in daten["aktivitaet"]["events"])
    assert all(e["id"] and e["zeit"] for e in daten["aktivitaet"]["events"])


def test_laufende_mission_macht_den_raum_aktiv(tmp_path):
    db = _db_mit_claim(tmp_path)
    mission = Missionen(db, jetzt_funktion=lambda: JETZT).anlegen(
        "EZB Leitzins", "Prüfe die aktuelle Datenlage zum Leitzins der EZB.",
    )
    with db.conn() as c:
        c.execute(
            "UPDATE nexus_missionen SET status='laufend', gestartet=? WHERE kennung=?",
            (JETZT.isoformat(timespec="seconds"), mission["kennung"]),
        )

    daten = raum_daten(db, "7d", JETZT)

    assert daten["aktivitaet"]["status"] == "aktiv"
    assert daten["aktivitaet"]["laufend"] == 1
    assert "Mission gestartet" in {
        e["titel"] for e in daten["aktivitaet"]["events"]
    }
    assert daten["zahlen"]["offen"] == 0


def test_zeitfenster_blendet_alte_aktivitaet_aus_ohne_sie_zu_loeschen(tmp_path):
    db = _db_mit_claim(tmp_path)
    Missionen(db, jetzt_funktion=lambda: JETZT).anlegen(
        "EZB Leitzins", "Prüfe die aktuelle Datenlage zu Leitzins und Geldpolitik.",
    )

    spaeter = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    daten = raum_daten(db, "24h", spaeter)

    assert daten["graph"]["knoten"] == []
    assert daten["aktivitaet"]["events"] == []
    assert daten["aktivitaet"]["gespeichert"] > 0
    assert daten["aktivitaet"]["detail"] == "Keine Aktivität im gewählten Zeitraum."
    assert daten["zahlen"]["missionen"] == 1
