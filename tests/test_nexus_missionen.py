from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orakel.db import Facts
from orakel.nexus.missionen import Missionen

ZEIT = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
ZEIT_TEXT = "2026-11-10T09:00:00+00:00"


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


def test_mission_laeuft_ueber_neustart_und_schreibt_bericht(tmp_path):
    db = _db_mit_claim(tmp_path)
    missionen = Missionen(db, jetzt_funktion=lambda: ZEIT)
    mission = missionen.anlegen(
        "EZB Leitzins", "Prüfe die aktuelle Datenlage zum Leitzins der EZB.",
    )

    assert mission["kennung"].startswith("MS-20261110-")
    assert [t["rolle"] for t in mission["tasks"]] == ["lage", "pruefung", "bericht"]
    erster = missionen.weiterarbeiten(max_tasks=1)
    assert erster["erledigt"] == 1
    zwischenstand = db.nexus_mission(mission["kennung"])
    assert zwischenstand["status"] == "offen"
    assert zwischenstand["fortschritt"] == 33
    assert [t["status"] for t in zwischenstand["tasks"]] == ["erledigt", "offen", "offen"]

    # Neue Instanz = simulierter Prozessneustart. Erledigte Arbeit wird nicht wiederholt.
    neustart = Missionen(db, jetzt_funktion=lambda: ZEIT + timedelta(seconds=5))
    rest = neustart.weiterarbeiten(max_tasks=10)
    assert rest["erledigt"] == 2
    fertig = db.nexus_mission(mission["kennung"])
    assert fertig["status"] == "abgeschlossen"
    assert fertig["fortschritt"] == 100
    assert all(t["status"] == "erledigt" for t in fertig["tasks"])
    assert "EZB Leitzins" in fertig["bericht"]["text"]
    assert "bestätigt" in fertig["bericht"]["text"]
    assert fertig["bericht"]["kennzahlen"]["claims"] == 1
    assert fertig["bericht"]["kennzahlen"]["hosts"] == 2


def test_mission_ohne_passende_claims_ist_eine_datenluecke(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    missionen = Missionen(db, jetzt_funktion=lambda: ZEIT)
    mission = missionen.anlegen(
        "Weltraumhafen", "Prüfe die Datenlage zu einem völlig neuen Thema.",
    )
    missionen.weiterarbeiten(max_tasks=10)
    fertig = db.nexus_mission(mission["kennung"])

    assert fertig["status"] == "abgeschlossen"
    assert fertig["bericht"]["kennzahlen"]["claims"] == 0
    assert "Keine passende Kernaussage" in fertig["bericht"]["text"]
    assert "keine Entwarnung" in fertig["bericht"]["text"]
    assert fertig["bericht"]["claims"] == []


def test_fehler_mit_backoff_und_dead_letter(tmp_path, monkeypatch):
    db = _db_mit_claim(tmp_path)
    jetzt = [ZEIT]

    def kaputt(self, mission):
        raise RuntimeError("Testfehler")

    monkeypatch.setattr(Missionen, "_lage", kaputt)
    missionen = Missionen(db, max_versuche=2, backoff_sekunden=10,
                          jetzt_funktion=lambda: jetzt[0])
    mission = missionen.anlegen(
        "EZB Leitzins", "Prüfe die Datenlage zum Leitzins der EZB.",
    )

    erster = missionen.weiterarbeiten(max_tasks=1)
    assert erster["fehler"] == 1
    assert erster["retries"] == 1
    assert erster["dead_letter"] == 0
    task = db.nexus_mission(mission["kennung"])["tasks"][0]
    assert task["versuche"] == 1
    assert task["status"] == "offen"
    assert task["fehler"].startswith("RuntimeError: Testfehler")
    assert task["faellig_am"] > ZEIT.isoformat(timespec="seconds")

    # Vor Ablauf des Backoffs wird nichts erneut versucht.
    assert missionen.weiterarbeiten(max_tasks=1)["ausgefuehrt"] == 0

    jetzt[0] = ZEIT + timedelta(seconds=11)
    letzter = missionen.weiterarbeiten(max_tasks=1)
    assert letzter["fehler"] == 1
    assert letzter["dead_letter"] == 1
    fertig = db.nexus_mission(mission["kennung"])
    assert fertig["status"] == "fehlgeschlagen"
    assert [t["status"] for t in fertig["tasks"]] == [
        "fehlgeschlagen", "blockiert", "blockiert",
    ]
    assert "Mission abgebrochen" in fertig["bericht"]["text"]


def test_abgelaufene_lease_wird_nach_neustart_zurueckgeholt(tmp_path):
    db = _db_mit_claim(tmp_path)
    missionen = Missionen(db, jetzt_funktion=lambda: ZEIT)
    mission = missionen.anlegen(
        "EZB Leitzins", "Prüfe die Datenlage zum Leitzins der EZB.",
    )

    # Simulierter Absturz: Die Aufgabe ist geleast, der Worker kommt nie zurück.
    geleast = db.nexus_task_naechste(
        ZEIT_TEXT, (ZEIT + timedelta(seconds=300)).isoformat(timespec="seconds"),
        mission["kennung"],
    )
    assert geleast is not None
    assert geleast["status"] == "laufend"

    neustart = Missionen(
        db, lease_sekunden=300,
        jetzt_funktion=lambda: ZEIT + timedelta(seconds=301),
    )
    ergebnis = neustart.weiterarbeiten(max_tasks=1)
    assert ergebnis["leases"] == 1
    assert ergebnis["erledigt"] == 1
    task = db.nexus_mission(mission["kennung"])["tasks"][0]
    assert task["status"] == "erledigt"
    assert task["versuche"] == 2


def test_prioritaet_kommt_vor_erstellungsreihenfolge(tmp_path):
    db = _db_mit_claim(tmp_path)
    missionen = Missionen(db, jetzt_funktion=lambda: ZEIT)
    niedrig = missionen.anlegen(
        "EZB Leitzins niedrig", "Prüfe die Datenlage zum Leitzins der EZB.",
        "niedrig",
    )
    kritisch = missionen.anlegen(
        "EZB Leitzins kritisch", "Prüfe die Datenlage zum Leitzins der EZB.",
        "kritisch",
    )

    task = db.nexus_task_naechste(
        ZEIT_TEXT, (ZEIT + timedelta(seconds=300)).isoformat(timespec="seconds"),
    )
    assert task is not None
    assert task["mission_kennung"] == kritisch["kennung"]
    assert task["mission_kennung"] != niedrig["kennung"]
