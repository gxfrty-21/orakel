from __future__ import annotations

from datetime import datetime

import pytest

from orakel.company import api
from orakel.company.store import CompanyStore
from orakel.db import Facts


def _store(cfg) -> tuple[Facts, CompanyStore]:
    db = Facts(cfg.db_pfad)
    store = CompanyStore(db)
    store.sync_roster()
    return db, store


def _beispiel_queue(store: CompanyStore) -> dict[str, int]:
    t1 = store.enqueue(task_key="api:A1", assigned_to="A1", dept="A", title="Läuft",
                       priority=90)
    t2 = store.enqueue(task_key="api:A2", assigned_to="A2", dept="A", title="Blockiert",
                       priority=80)
    t3 = store.enqueue(task_key="api:A3", assigned_to="A3", dept="A", title="Wartet",
                       priority=70)
    t4 = store.enqueue(task_key="api:A4", assigned_to="A4", dept="A", title="Erledigt",
                       priority=75)
    assert store.claim_next("w1")["id"] == t1
    assert store.claim_next("w2")["id"] == t2
    store.block(t2, "Testblockade")
    assert store.claim_next("w3")["id"] == t4
    store.complete(t4, result="belegtes Ergebnis", evidence=["task:test"])
    return {"laeuft": t1, "blockiert": t2, "wartet": t3, "erledigt": t4}


def test_uebersicht_liefert_kennzahlen_status_und_offene_aufgaben(cfg):
    _, store = _store(cfg)
    ids = _beispiel_queue(store)
    store.entscheidung_speichern(
        level=2, title="Testentscheid", kind="project", rationale="belegt",
        owner="A1", evidence=["task:test"],
    )

    daten = api.uebersicht(store)

    assert daten["ok"] is True
    assert daten["data_state"] == "live"
    datetime.fromisoformat(daten["generated_at"])
    assert "company:profiles" in daten["source_refs"]
    assert "company:tasks" in daten["source_refs"]
    assert daten["profile"] == {"gesamt": 103, "aktiv": 103, "inaktiv": 0}
    assert daten["agenten_status"] == {
        "aktiv": 1, "blockiert": 1, "wartend": 1, "frei": 100, "inaktiv": 0,
    }
    assert daten["aufgaben"]["offen"] == 3
    assert daten["aufgaben"]["dead_letter"] == 0
    assert daten["aufgaben"]["nach_status"]["running"] == 1
    assert daten["aufgaben"]["nach_status"]["blocked"] == 1
    assert daten["aufgaben"]["nach_status"]["queued"] == 1
    assert daten["aufgaben"]["nach_status"]["done"] == 1
    assert [t["id"] for t in daten["offene_aufgaben"]] == [
        ids["laeuft"], ids["blockiert"], ids["wartet"],
    ]
    assert daten["offene_aufgaben"][0]["rufname"] == "Atlas"
    a = next(d for d in daten["abteilungen"] if d["code"] == "A")
    assert a == {"code": "A", "name": "Command Center", "agenten": 10,
                 "offen": 3, "laeuft": 1, "blockiert": 1}
    assert daten["offene_entscheidungen_gesamt"] == 1
    assert daten["offene_entscheidungen"][0]["title"] == "Testentscheid"
    assert daten["letzte_konferenz"] is None
    assert daten["audit_ok"] is True


def test_agentenstatus_und_letzte_aufgabe(cfg):
    _, store = _store(cfg)
    ids = _beispiel_queue(store)

    daten = api.agenten(store)

    assert daten["gesamt"] == 103
    assert len(daten["agenten"]) == 103
    assert daten["status"] == {
        "laeuft": 1, "blockiert": 1, "wartet": 1, "frei": 100, "inaktiv": 0,
    }
    nach_id = {a["agent_id"]: a for a in daten["agenten"]}
    laeuft = nach_id["A1"]
    assert laeuft["status"] == "laeuft"
    assert laeuft["status_text"] == "läuft"
    assert laeuft["offene_aufgaben"] == 1
    assert laeuft["letzte_task"]["id"] == ids["laeuft"]
    assert laeuft["letzte_task"]["state"] == "running"
    assert f"task:{ids['laeuft']}" in laeuft["quellen"]

    blockiert = nach_id["A2"]
    assert blockiert["status"] == "blockiert"
    assert blockiert["davon_blockiert"] == 1
    assert blockiert["letzte_task"]["error"] == "Testblockade"

    wartet = nach_id["A3"]
    assert wartet["status"] == "wartet"
    assert wartet["letzte_task"]["id"] == ids["wartet"]

    frei = nach_id["A4"]
    assert frei["status"] == "frei"
    assert frei["offene_aufgaben"] == 0
    assert frei["letzte_task"]["state"] == "done"
    assert frei["letzte_task"]["result"] == "belegtes Ergebnis"


def test_aufgaben_filtert_offen_status_abteilung_und_prioritaet(cfg):
    _, store = _store(cfg)
    ids = _beispiel_queue(store)

    offen = api.aufgaben(store)
    assert offen["gesamt"] == 3
    assert offen["data_state"] == "live"
    assert offen["filter"]["state"] == "offen"
    assert [t["id"] for t in offen["aufgaben"]] == [
        ids["laeuft"], ids["blockiert"], ids["wartet"],
    ]
    assert all(t["state"] != "done" for t in offen["aufgaben"])

    erledigt = api.aufgaben(store, state="done")
    assert erledigt["gesamt"] == 1
    assert erledigt["aufgaben"][0]["id"] == ids["erledigt"]
    assert erledigt["aufgaben"][0]["state_text"] == "erledigt"

    assert api.aufgaben(store, dept="B")["gesamt"] == 0
    assert api.aufgaben(store, dept="B")["data_state"] == "empty"
    assert api.aufgaben(store, dept="a")["gesamt"] == 3
    assert api.aufgaben(store, mindestprioritaet=90)["gesamt"] == 1
    assert api.aufgaben(store, mindestprioritaet=90)["aufgaben"][0]["id"] == ids["laeuft"]
    assert api.aufgaben(store, limit=2)["gesamt"] == 3
    assert len(api.aufgaben(store, limit=2)["aufgaben"]) == 2
    assert api.aufgaben(store, state="alle")["gesamt"] == 4

    with pytest.raises(ValueError):
        api.aufgaben(store, state="unbekannt")
    with pytest.raises(ValueError):
        api.aufgaben(store, mindestprioritaet=101)


def test_leere_company_daten_bleiben_leer(cfg):
    db = Facts(cfg.db_pfad)
    store = CompanyStore(db)

    uebersicht = api.uebersicht(store)
    assert uebersicht["data_state"] == "empty"
    assert uebersicht["profile"]["gesamt"] == 0
    assert uebersicht["agenten_status"] == {
        "aktiv": 0, "blockiert": 0, "wartend": 0, "frei": 0, "inaktiv": 0,
    }
    assert uebersicht["offene_aufgaben"] == []

    agenten = api.agenten(store)
    assert agenten["data_state"] == "empty"
    assert agenten["gesamt"] == 0
    assert agenten["agenten"] == []

    aufgaben = api.aufgaben(store)
    assert aufgaben["data_state"] == "empty"
    assert aufgaben["gesamt"] == 0
    assert aufgaben["aufgaben"] == []
