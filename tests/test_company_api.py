from __future__ import annotations

from datetime import datetime

import pytest
from hypothesis import HealthCheck, example, given, settings

from paper_strategies import paper_erlaubt, paper_konfiguration
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


@example(None)
@example({})
@example({"broker": "csv", "order_freigabe": False})
@example({"broker": "mt5", "order_freigabe": False})
@given(paper=paper_konfiguration())
@settings(
    max_examples=150,
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_api_paper_guard_generierte_kombinationen(cfg, paper):
    if paper is None:
        cfg._d.pop("paper", None)
    else:
        cfg._d["paper"] = paper

    daten = api.paper_guard(cfg)
    erlaubt = paper_erlaubt(paper)

    assert daten["ok"] is True
    assert daten["paper_only"] is erlaubt
    assert daten["paper_order_allowed"] is erlaubt
    if erlaubt:
        assert "Paper-only ist aktiv" in daten["grund"]
    else:
        assert "Paper-Sperre" in daten["grund"]


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


def test_agentendetail_liefert_profil_historie_und_nachrichten(cfg):
    _, store = _store(cfg)
    ids = _beispiel_queue(store)
    nachricht = store.nachricht_speichern(
        thread_id="thread:a1", from_agent="A1", to_agent="A2", kind="status",
        subject="Lage", body="Alles belegt.", evidence=[f"task:{ids['laeuft']}"],
        requires_ack=True,
    )

    daten = api.agent_detail(store, "a1")

    assert daten is not None
    assert daten["data_state"] == "live"
    assert daten["profil"]["agent_id"] == "A1"
    assert daten["profil"]["active"] is True
    assert daten["profil"]["data_scope"]
    assert daten["status"] == "laeuft"
    assert daten["aktuelle_aufgabe"]["id"] == ids["laeuft"]
    assert [t["id"] for t in daten["offene_aufgaben"]] == [ids["laeuft"]]
    assert {t["id"] for t in daten["historie"]} == {ids["laeuft"]}
    assert daten["nachrichten"][0]["id"] == nachricht
    assert daten["nachrichten"][0]["requires_ack"] is True
    assert daten["nachrichten"][0]["evidence"] == [f"task:{ids['laeuft']}"]
    assert f"agent:A1" in daten["source_refs"]
    assert api.agent_detail(store, "GIBT-ES-NICHT") is None


def test_nachrichten_filtert_agent_abteilung_thread_und_zeit(cfg):
    _, store = _store(cfg)
    m1 = store.nachricht_speichern(
        thread_id="thread:1", from_agent="A1", to_agent="A2", kind="status",
        subject="Erste", body="A1 an A2",
    )
    m2 = store.nachricht_speichern(
        thread_id="thread:1", from_agent="A2", to_agent="A3", kind="antwort",
        subject="Zweite", body="A2 an A3",
    )
    m3 = store.nachricht_speichern(
        thread_id="thread:2", from_agent="A1", to_agent="A3", kind="status",
        subject="Dritte", body="A1 an A3",
    )

    alle = api.nachrichten(store)
    assert alle["data_state"] == "live"
    assert alle["gesamt"] == 3
    assert [m["id"] for m in alle["nachrichten"]] == [m3, m2, m1]
    assert {t["thread_id"] for t in alle["threads"]} == {"thread:1", "thread:2"}
    assert next(t for t in alle["threads"] if t["thread_id"] == "thread:1")["anzahl"] == 2

    von_a1 = api.nachrichten(store, agent="a1")
    assert {m["id"] for m in von_a1["nachrichten"]} == {m1, m3}
    assert von_a1["filter"]["agent"] == "A1"
    assert api.nachrichten(store, dept="a")["gesamt"] == 3
    assert api.nachrichten(store, thread_id="thread:2")["gesamt"] == 1
    assert api.nachrichten(store, seit="2999-01-01T00:00:00Z")["data_state"] == "empty"
    with pytest.raises(ValueError):
        api.nachrichten(store, seit="gestern")


def test_konferenz_liefert_letzte_sitzung_und_leeren_zustand(cfg):
    db, store = _store(cfg)
    leer = api.konferenz(store)
    assert leer["data_state"] == "empty"
    assert leer["konferenz"] is None
    assert leer["teilnahme"] == []

    with db.conn() as c:
        session = c.execute(
            "INSERT INTO conference_sessions(scheduled_date,scheduled_at,phase,status,protocol_json)"
            " VALUES ('2026-11-14','2026-11-14T00:00:00+00:00','abschluss','beendet','{\"titel\":\"Test\"}')"
        ).lastrowid
        c.execute(
            "INSERT INTO conference_attendance(session_id,agent_id,present,role)"
            " VALUES (?, 'A1', 1, 'leiter')", (session,))
        c.execute(
            "INSERT INTO conference_statements(session_id,agent_id,kind,body,evidence_json,created_at)"
            " VALUES (?, 'A1', 'bericht', 'Belegt.', '[\"task:1\"]', '2026-11-14T00:01:00+00:00')",
            (session,))
        decision = c.execute(
            "INSERT INTO company_decisions(session_id,level,title,kind,status,evidence_json,"
            " rationale,owner,created_at,updated_at) VALUES (?, 2, 'Beschluss', 'project',"
            " 'offen', '[\"task:1\"]', 'Begründet', 'A1',"
            " '2026-11-14T00:02:00+00:00', '2026-11-14T00:02:00+00:00')",
            (session,)).lastrowid
        c.execute(
            "INSERT INTO conference_votes(session_id,decision_id,agent_id,vote,reason,created_at)"
            " VALUES (?, ?, 'A1', 'ja', 'Belegt', '2026-11-14T00:03:00+00:00')",
            (session, decision))
        c.execute(
            "INSERT INTO company_actions(decision_id,owner,status,created_at)"
            " VALUES (?, 'A1', 'offen', '2026-11-14T00:04:00+00:00')", (decision,))

    daten = api.konferenz(store)
    assert daten["data_state"] == "live"
    assert daten["konferenz"]["id"] == session
    assert daten["konferenz"]["protocol"] == {"titel": "Test"}
    assert daten["teilnahme"][0]["present"] is True
    assert daten["beitraege"][0]["evidence"] == ["task:1"]
    assert daten["abstimmungen"][0]["vote"] == "ja"
    assert daten["abstimmungen"][0]["decision_title"] == "Beschluss"
    assert daten["entscheidungen"][0]["evidence"] == ["task:1"]
    assert daten["massnahmen"][0]["decision_title"] == "Beschluss"
    assert f"conference:{session}" in daten["source_refs"]


def test_raeume_liefert_abteilungen_und_agentenstatus(cfg):
    db, store = _store(cfg)
    ids = _beispiel_queue(store)
    with db.conn() as c:
        c.execute(
            "INSERT INTO room_state(room_id,status,active_agents,last_event,updated_at)"
            " VALUES ('agent:A1','belegt',1,'task', '2026-11-14T00:00:00+00:00')")

    daten = api.raeume(store)

    assert daten["data_state"] == "live"
    assert daten["gesamt"] == {"abteilungen": 11, "gemeinschaftsraeume": 1, "agentenraeume": 103}
    a = next(d for d in daten["abteilungen"] if d["code"] == "A")
    assert a["agenten"] == 10
    assert a["offene_aufgaben"] == 3
    assert a["laeuft"] == 1 and a["blockiert"] == 1
    assert a["status"] == "laeuft"
    a1 = next(r for r in daten["agentenraeume"] if r["agent_id"] == "A1")
    assert a1["room_id"] == "agent:A1"
    assert a1["status"] == "laeuft"
    assert a1["task_id"] == ids["laeuft"]
    assert daten["gemeinschaftsraeume"][0]["room_id"] == "common:agents"
    assert daten["dynamischer_status"][0]["room_id"] == "agent:A1"
    assert any(q == "room_state:agent:A1" for q in daten["source_refs"])


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

    assert api.agent_detail(store, "A1") is None
    nachrichten = api.nachrichten(store)
    assert nachrichten["data_state"] == "empty"
    assert nachrichten["nachrichten"] == []
    assert nachrichten["threads"] == []
    raeume = api.raeume(store)
    assert raeume["data_state"] == "empty"
    assert raeume["gesamt"] == {
        "abteilungen": 0, "gemeinschaftsraeume": 0, "agentenraeume": 0,
    }
    assert raeume["agentenraeume"] == []
