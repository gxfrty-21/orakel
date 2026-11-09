from __future__ import annotations

from collections import Counter

import pytest

from orakel.company.policy import CompanyPolicy, PolicyError
from orakel.company.roster import PROFILES, profile_by_id, validate_roster
from orakel.company.runtime import CompanyRuntime
from orakel.company.store import CompanyStore
from orakel.db import Facts


def _db(cfg) -> Facts:
    return Facts(cfg.db_pfad)


def _store(cfg) -> tuple[Facts, CompanyStore]:
    db = _db(cfg)
    store = CompanyStore(db)
    store.sync_roster()
    return db, store


def test_roster_hat_103_eindeutige_profile():
    assert len(PROFILES) == 103
    assert validate_roster() == []
    assert Counter(p.dept for p in PROFILES if p.dept in "ABCDEFGHIJ") == {
        "A": 10, "B": 10, "C": 10, "D": 10, "E": 10,
        "F": 10, "G": 10, "H": 10, "I": 10, "J": 10,
    }
    assert len([p for p in PROFILES if p.dept == "S"]) == 3
    assert len({p.agent_id for p in PROFILES}) == 103
    assert len({p.rufname for p in PROFILES}) == 103


def test_migration_erhaelt_bestehende_daten(cfg):
    db = Facts(cfg.db_pfad)
    db.artikel_speichern(
        "Testquelle", "nachrichten", "Alter Artikel", "https://example.com/alt",
        None, "Bestand", 0.9, ["EURUSD"], "hash-alt",
    )
    db.agenten_lauf("A1:Koordinator", "A", "Bestandsaufgabe", "altes Ergebnis", True)

    with db.conn() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
        tabellen = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"agent_profiles", "agent_tasks", "agent_events"} <= tabellen

    store = CompanyStore(db)
    assert store.sync_roster() == 103
    assert db.artikel_statistik()["gesamt"] == 1
    assert len(db.agenten_laeufe()) == 1


def test_queue_ist_idempotent_und_durchlaeuft_den_lifecycle(cfg):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:A1:1", assigned_to="A1", dept="A", title="Test",
        task_type="daily_check", acceptance="ok",
    )
    assert store.enqueue(
        task_key="test:A1:1", assigned_to="A1", dept="A", title="Test",
        task_type="daily_check", acceptance="ok",
    ) == task_id

    task = store.claim_next("worker-test")
    assert task is not None
    assert task["id"] == task_id
    assert task["state"] == "running"
    assert task["attempts"] == 1

    store.complete(task_id, result="belegtes Ergebnis", evidence=["task:test"],
                   output={"ok": True})
    fertig = store.task(task_id)
    assert fertig is not None
    assert fertig["state"] == "done"
    assert fertig["result"] == "belegtes Ergebnis"
    assert store.audit_chain_ok()


def test_queue_beachtet_abhaengigkeiten(cfg):
    _, store = _store(cfg)
    t1 = store.enqueue(task_key="test:dep:1", assigned_to="A1", dept="A",
                       title="zuerst", priority=10)
    t2 = store.enqueue(task_key="test:dep:2", assigned_to="A2", dept="A",
                       title="danach", priority=99)
    store.add_dependency(t2, t1)
    assert store.claim_next("w1")["id"] == t1
    store.complete(t1, result="ok", evidence=["task:dep"])
    assert store.claim_next("w2")["id"] == t2


def test_policy_blockiert_echte_orders_und_freie_shell(cfg):
    policy = CompanyPolicy(cfg)
    assert policy.paper_only()
    assert not policy.check_action("real_order").allowed
    assert policy.check_action("change_risk").owner_required
    assert not policy.check_action("shell").allowed
    assert not policy.check_action("read_secret").allowed
    assert policy.check_action("paper_order").allowed
    with pytest.raises(PolicyError):
        policy.check_task(profile_by_id("H3"), "test_suite")
    with pytest.raises(PolicyError):
        policy.validate_output("api_key=abcdefgh12345", ["task:1"])


def test_company_lauf_verarbeitet_alle_103_aufgaben(cfg):
    db = _db(cfg)
    runtime = CompanyRuntime(cfg, db, max_workers=2)
    ids = runtime.seed_daily_tasks("2026-11-08")
    assert len(ids) == 103
    assert len(set(ids)) == 103
    assert len(runtime.seed_daily_tasks("2026-11-08")) == 103

    ergebnis = runtime.run(tag="2026-11-08")
    assert ergebnis["profile"] == 103
    assert ergebnis["tasks_erzeugt"] == 103
    assert ergebnis["tasks_verarbeitet"] == 103
    assert sum(ergebnis["states"].values()) == 103
    assert ergebnis["audit_ok"] is True
    assert ergebnis["paper_only"] is True
    assert all(state not in {"queued", "running"} for state in ergebnis["states"])
    # Jeder Versuch ist ein echter append-only-Lauf; Retries erzeugen zusätzliche
    # Zeilen. Entscheidend ist, dass jeder der 103 Agenten mindestens einmal lief.
    laeufe = db.agenten_laeufe(limit=300)
    assert len(laeufe) >= 103
    assert {r["agent"] for r in laeufe} == {
        f"{p.agent_id}:{p.role}" for p in PROFILES
    }
    assert db.zustand("company_letzter_lauf")["tasks_verarbeitet"] == 103


def test_audit_kette_erkennt_manipulation(cfg):
    db, store = _store(cfg)
    store.enqueue(task_key="test:audit:1", assigned_to="A1", dept="A",
                  title="Audit")
    assert store.audit_chain_ok()
    with db.conn() as c:
        c.execute("UPDATE agent_events SET payload_json='{}' WHERE id=1")
    assert not store.audit_chain_ok()
