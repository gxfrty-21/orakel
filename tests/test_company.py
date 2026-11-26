from __future__ import annotations

import sqlite3
import uuid
from collections import Counter
from dataclasses import replace

import pytest
from hypothesis import HealthCheck, example, given, settings

from paper_strategies import paper_erlaubt, paper_konfiguration
from orakel.company.handlers import HandlerResult, run_handler
from orakel.company.policy import ERLAUBTE_TASK_TYPES, CompanyPolicy, PolicyError
from orakel.company.roster import PROFILES, profile_by_id, validate_roster
from orakel.company.runtime import TASK_TYPES, CompanyRuntime
from orakel.company.store import CompanyStore, StoreError
from orakel.kern.db import Facts


def _db(cfg) -> Facts:
    return Facts(cfg.db_pfad)


def _store(cfg) -> tuple[Facts, CompanyStore]:
    db = _db(cfg)
    store = CompanyStore(db)
    store.sync_roster()
    return db, store


def _audit_kaputt(monkeypatch, store: CompanyStore) -> None:
    def kaputt(*args, **kwargs):
        raise RuntimeError("Audit nicht erreichbar")

    monkeypatch.setattr(store, "_append_event_im_transaktion", kaputt)


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


def test_b_agenten_erhalten_ihren_fachhandler():
    from orakel.agents import ROSTER, _handler_fuer

    erwartet = {"B6": "dubletten", "B7": "mehrdeutig", "B9": "weiterleitungen"}
    gefunden = {kennung: _handler_fuer(kennung, aufgabe)
                for kennung, _, _, aufgabe in ROSTER if kennung in erwartet}
    assert gefunden == erwartet


def test_h_agenten_erhalten_ihren_eigenen_handler():
    from orakel.agents import ROSTER, _handler_fuer

    erwartet = {
        "H2": "konfiguration", "H3": "test", "H4": "schema",
        "H5": "performance", "H6": "paper_sperre", "H7": "fehler",
        "H8": "version", "H10": "regression",
    }
    gefunden = {kennung: _handler_fuer(kennung, aufgabe)
                for kennung, _, _, aufgabe in ROSTER if kennung in erwartet}
    assert gefunden == erwartet


def test_h_handler_pruefen_ihre_eigene_aufgabe(cfg):
    from orakel import SCHEMA, __version__
    from orakel.agents import _hdl_fehler, _hdl_performance, _hdl_regression, _hdl_version

    db = _db(cfg)
    ctx = {"cfg": cfg, "db": db}

    assert _hdl_performance(ctx) == (False, "keine Laufzeit gemessen")
    db.zustand_setzen("letzter_lauf", {"dauer": 12.5})
    assert _hdl_performance(ctx) == (True, "letzter Lauf 12.50 s")

    assert _hdl_fehler(ctx) == (False, "keine Ereignisse protokolliert")
    db.ereignis("info", "Test", "gestartet")
    db.ereignis("fehler", "Test", "kaputt")
    assert _hdl_fehler(ctx) == (True, "Fehler: 1, Ereignisse: 2")

    assert _hdl_version(ctx) == (True, f"Version {__version__}, Schema {SCHEMA}")

    assert _hdl_regression(ctx) == (False, "keine zwei Läufe zum Vergleich")
    db.agenten_lauf("H10:Test", "H", "Test", "gleich", True)
    db.agenten_lauf("H10:Test", "H", "Test", "gleich", True)
    assert _hdl_regression(ctx) == (True, "1 von 1 Agenten unverändert")
    db.agenten_lauf("H10:Test", "H", "Test", "anders", True)
    assert _hdl_regression(ctx) == (True, "0 von 1 Agenten unverändert")


def test_h3_respektiert_die_test_sperre(cfg, monkeypatch):
    from orakel.agents import _hdl_test

    assert _hdl_test({"cfg": cfg}) == (
        False, "Test-Suite als Agenten-Subprozess ist in Phase 1 deaktiviert")

    cfg._d.setdefault("unternehmen", {})["allow_tests"] = True

    class Ergebnis:
        returncode = 0
        stdout = "731 passed in 1s\n"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Ergebnis())
    assert _hdl_test({"cfg": cfg}) == (True, "731 passed in 1s")


def test_h4_prueft_den_bericht_gegen_schema_2(cfg):
    from orakel.agents import _hdl_schema
    from orakel.report import baue_bericht

    db = _db(cfg)
    bericht = baue_bericht(cfg, db)
    assert _hdl_schema({"bericht": bericht}) == (True, "Schema 2 gültig")
    assert _hdl_schema({})[0] is False


def test_import_handler_laedt_aktuelle_kernmodule():
    from orakel.agents import _hdl_import

    ok, ergebnis = _hdl_import({})
    assert ok, ergebnis
    assert ergebnis == "5 Kernmodule ladbar"


def test_schiff_zahlen_nennen_elf_cluster_und_103_agenten(cfg):
    _, store = _store(cfg)

    assert store.schiff_zahlen() == {"cluster": 11, "agenten": 103}


def test_migration_erhaelt_bestehende_daten(cfg):
    db = Facts(cfg.db_pfad)
    db.artikel_speichern(
        "Testquelle", "nachrichten", "Alter Artikel", "https://example.com/alt",
        None, "Bestand", 0.9, ["EURUSD"], "hash-alt",
    )
    db.agenten_lauf("A1:Koordinator", "A", "Bestandsaufgabe", "altes Ergebnis", True)

    with db.conn() as c:
        # user_version spiegelt seit 4.3 die höchste angewendete Migration.
        assert c.execute("PRAGMA user_version").fetchone()[0] >= 1
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


def test_enqueue_lehnt_anderen_task_type_bei_vorhandenem_task_key_ab(cfg):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:key:typkonflikt",
        assigned_to="A1",
        dept="A",
        title="Ursprünglicher Task",
        task_type="daily_check",
    )

    with pytest.raises(StoreError, match="Task-Key.*bereits.*Task-Typ"):
        store.enqueue(
            task_key="test:key:typkonflikt",
            assigned_to="A1",
            dept="A",
            title="Konflikt",
            task_type="paper_guard",
        )

    task = store.task(task_id)
    assert task is not None
    assert task["task_type"] == "daily_check"
    assert store.task_counts() == {"queued": 1}


@pytest.mark.parametrize(
    "task_type",
    [None, 42, 3.14, ["daily_check"], {"name": "daily_check"}],
)
def test_enqueue_blockiert_nicht_string_task_type_vor_dem_schreiben(cfg, task_type):
    db, store = _store(cfg)

    with pytest.raises(StoreError, match="Unbekannter Task-Typ"):
        store.enqueue(
            task_key=f"test:enqueue:nicht-string:{type(task_type).__name__}",
            assigned_to="A1",
            dept="A",
            title="Darf nicht in die Queue",
            task_type=task_type,
        )

    assert store.task_counts() == {}


def test_enqueue_blockiert_unbekannten_task_type_vor_dem_schreiben(cfg):
    db, store = _store(cfg)

    with pytest.raises(StoreError, match="Unbekannter Task-Typ"):
        store.enqueue(
            task_key="test:enqueue:unbekannt",
            assigned_to="A1",
            dept="A",
            title="Darf nicht in die Queue",
            task_type="real_order",
        )

    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM agent_tasks").fetchone()["n"] == 0
    assert store.events() == []


def test_audit_fehler_rollt_task_status_zurueck(cfg, monkeypatch):
    _, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:atomic:1", assigned_to="A1", dept="A", title="Atomar",
    )
    assert store.claim_next("worker-atomic")["id"] == task_id

    def audit_kaputt(*args, **kwargs):
        raise RuntimeError("Audit nicht erreichbar")

    monkeypatch.setattr(store, "_append_event_im_transaktion", audit_kaputt)
    with pytest.raises(RuntimeError, match="Audit nicht erreichbar"):
        store.complete(
            task_id, result="darf nicht committet werden", evidence=["task:atomic"],
        )

    task = store.task(task_id)
    assert task is not None
    assert task["state"] == "running"
    assert not any(e["kind"] == "task_done" for e in store.events(task_id))
    assert store.audit_chain_ok()


def test_fail_reaktiviert_erledigte_task_nicht(cfg):
    _, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:atomic:2", assigned_to="A1", dept="A", title="Bleibt erledigt",
    )
    assert store.claim_next("worker-done")["id"] == task_id
    store.complete(task_id, result="belegt", evidence=["task:done"])

    with pytest.raises(StoreError, match="Zustand done"):
        store.fail(task_id, "verspäteter Fehler")

    task = store.task(task_id)
    assert task is not None
    assert task["state"] == "done"
    assert not any(e["kind"] == "task_failed" for e in store.events(task_id))
    assert store.audit_chain_ok()


def test_audit_fehler_rollt_enqueue_zurueck(cfg, monkeypatch):
    db, store = _store(cfg)
    _audit_kaputt(monkeypatch, store)

    with pytest.raises(RuntimeError, match="Audit nicht erreichbar"):
        store.enqueue(
            task_key="test:atomic:enqueue", assigned_to="A1", dept="A", title="Kein Task",
        )

    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM agent_tasks").fetchone()["n"] == 0
    assert store.events() == []


def test_audit_fehler_rollt_block_zurueck(cfg, monkeypatch):
    _, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:atomic:block", assigned_to="A1", dept="A", title="Blockade",
    )
    assert store.claim_next("worker-block")["id"] == task_id
    _audit_kaputt(monkeypatch, store)

    with pytest.raises(RuntimeError, match="Audit nicht erreichbar"):
        store.block(task_id, "darf nicht committet werden")

    task = store.task(task_id)
    assert task is not None
    assert task["state"] == "running"
    assert not any(e["kind"] == "task_blocked" for e in store.events(task_id))
    assert store.audit_chain_ok()


def test_audit_fehler_rollt_lease_recovery_zurueck(cfg, monkeypatch):
    _, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:atomic:lease", assigned_to="A1", dept="A", title="Lease",
    )
    assert store.claim_next("worker-lease", lease_seconds=-1)["id"] == task_id
    _audit_kaputt(monkeypatch, store)

    with pytest.raises(RuntimeError, match="Audit nicht erreichbar"):
        store.recover_expired()

    task = store.task(task_id)
    assert task is not None
    assert task["state"] == "running"
    assert not any(e["kind"] == "lease_recovered" for e in store.events())
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


def test_policy_blockiert_mt5_und_unbekannten_broker(cfg):
    policy = CompanyPolicy(cfg)
    # MT5 ist auch ohne Order-Freigabe kein Paper-Broker.
    cfg._d["paper"].update({"broker": "mt5", "order_freigabe": False})
    assert not policy.paper_only()
    assert not policy.check_action("paper_order").allowed

    cfg._d["paper"].update({"broker": "mt5", "order_freigabe": True})
    assert not policy.paper_only()
    assert not policy.check_action("paper_order").allowed

    cfg._d["paper"].update({"broker": "unbekannt", "order_freigabe": False})
    assert not policy.paper_only()
    assert not policy.check_action("paper_order").allowed


def test_policy_fail_closed_bei_fehlenden_oder_ungueltigen_paper_werten(cfg):
    policy = CompanyPolicy(cfg)
    faelle = [
        {},  # [paper] fehlt vollständig
        {"broker": "csv"},  # order_freigabe fehlt
        {"order_freigabe": False},  # broker fehlt
        {"broker": "csv", "order_freigabe": None},
        {"broker": "csv", "order_freigabe": "false"},
        {"broker": "csv", "order_freigabe": 0},
        {"broker": "", "order_freigabe": False},
    ]
    for paper in faelle:
        cfg._d["paper"] = dict(paper)
        assert not policy.paper_only(), paper
        assert not policy.check_action("paper_order").allowed, paper

    cfg._d["paper"] = {"broker": "csv", "order_freigabe": False}
    assert policy.paper_only()
    cfg._d["paper"] = {"broker": "mock", "order_freigabe": False}
    assert policy.paper_only()


def test_paper_guards_verwenden_dieselbe_fail_closed_policy(cfg):
    from orakel.agents import _hdl_paper_sperre
    from orakel.company.handlers import _paper_guard

    policy = CompanyPolicy(cfg)
    ctx = {"cfg": cfg, "policy": policy}
    assert _paper_guard(ctx).ok
    assert _hdl_paper_sperre(ctx)[0]

    cfg._d["paper"].update({"broker": "mt5", "order_freigabe": False})
    policy = CompanyPolicy(cfg)
    ctx = {"cfg": cfg, "policy": policy}
    assert not _paper_guard(ctx).ok
    assert not _hdl_paper_sperre(ctx)[0]


def test_policy_blockiert_unbekannten_task_type(cfg):
    policy = CompanyPolicy(cfg)
    with pytest.raises(PolicyError, match="Unbekannter Task-Typ"):
        policy.check_task(profile_by_id("A1"), "unbekannt")
    assert set(TASK_TYPES.values()) <= ERLAUBTE_TASK_TYPES


def test_run_handler_blockiert_unbekannten_handler(cfg):
    profil = replace(profile_by_id("A1"), handler="gibt_es_nicht")

    ergebnis = run_handler(profil, {"cfg": cfg, "policy": CompanyPolicy(cfg)})

    assert not ergebnis.ok
    assert ergebnis.blocked
    assert "kein Handler" in ergebnis.text


def test_runtime_handler_ausnahme_wird_dead_letter(cfg, monkeypatch):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:handler-exception",
        assigned_to="A1",
        dept="A",
        title="Handler-Ausnahme",
        task_type="daily_check",
        max_attempts=1,
    )
    task = store.claim_next("worker-handler-exception")
    assert task is not None
    runtime = CompanyRuntime(cfg, db, store=store)

    def kaputt(*args, **kwargs):
        raise RuntimeError("Handler absichtlich kaputt")

    monkeypatch.setattr("orakel.company.runtime.run_handler", kaputt)

    assert runtime._execute(task, runtime.kontext()) == "dead_letter"

    gespeichert = store.task(task_id)
    assert gespeichert is not None
    assert gespeichert["state"] == "dead_letter"
    assert "Handler-Ausnahme" in gespeichert["error"]
    assert not any(e["kind"] == "task_done" for e in store.events(task_id))


def test_runtime_handler_ergebnis_ohne_evidenz_wird_blockiert(cfg, monkeypatch):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:handler-ohne-evidenz",
        assigned_to="A1",
        dept="A",
        title="Handler ohne Evidenz",
        task_type="daily_check",
        max_attempts=1,
    )
    task = store.claim_next("worker-handler-ohne-evidenz")
    assert task is not None
    runtime = CompanyRuntime(cfg, db, store=store)
    monkeypatch.setattr(
        "orakel.company.runtime.run_handler",
        lambda *args, **kwargs: HandlerResult(True, "Nicht leerer Bericht", ()),
    )

    assert runtime._execute(task, runtime.kontext()) == "blocked"

    gespeichert = store.task(task_id)
    assert gespeichert is not None
    assert gespeichert["state"] == "blocked"
    assert "Ergebnis ohne Beleg" in gespeichert["error"]
    assert not any(e["kind"] == "task_done" for e in store.events(task_id))


def test_runtime_handler_ausnahme_erst_failed_dann_dead_letter(cfg, monkeypatch):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:handler-retry",
        assigned_to="A1",
        dept="A",
        title="Handler-Ausnahme mit Retry",
        task_type="daily_check",
        max_attempts=2,
    )
    runtime = CompanyRuntime(cfg, db, store=store)

    def kaputt(*args, **kwargs):
        raise RuntimeError("Handler absichtlich kaputt")

    monkeypatch.setattr("orakel.company.runtime.run_handler", kaputt)

    erster = store.claim_next("worker-handler-retry-1")
    assert erster is not None
    assert runtime._execute(erster, runtime.kontext()) == "failed"

    zwischenstand = store.task(task_id)
    assert zwischenstand is not None
    assert zwischenstand["state"] == "queued"
    assert zwischenstand["attempts"] == 1
    assert "Handler-Ausnahme" in zwischenstand["error"]
    assert not any(e["kind"] == "task_done" for e in store.events(task_id))

    zweiter = store.claim_next("worker-handler-retry-2")
    assert zweiter is not None
    assert zweiter["attempts"] == 2
    assert runtime._execute(zweiter, runtime.kontext()) == "dead_letter"

    endstand = store.task(task_id)
    assert endstand is not None
    assert endstand["state"] == "dead_letter"
    assert endstand["attempts"] == 2
    assert "Handler-Ausnahme" in endstand["error"]
    assert sum(e["kind"] == "task_failed" for e in store.events(task_id)) == 2
    assert not any(e["kind"] == "task_done" for e in store.events(task_id))


@pytest.mark.parametrize(
    ("ergebnis", "erwarteter_zustand"),
    [
        (HandlerResult(True, "", ()), "blocked"),
        (HandlerResult(False, "kein Ergebnis", ()), "dead_letter"),
    ],
)
def test_runtime_nicht_lieferndes_handler_ergebnis_wird_nicht_done(
    cfg, monkeypatch, ergebnis, erwarteter_zustand,
):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key=f"test:handler-nicht-liefernd:{erwarteter_zustand}",
        assigned_to="A1",
        dept="A",
        title="Nicht lieferndes Ergebnis",
        task_type="daily_check",
        max_attempts=1,
    )
    task = store.claim_next(f"worker-nicht-liefernd-{erwarteter_zustand}")
    assert task is not None
    runtime = CompanyRuntime(cfg, db, store=store)

    monkeypatch.setattr(
        "orakel.company.runtime.run_handler",
        lambda *args, **kwargs: ergebnis,
    )

    assert runtime._execute(task, runtime.kontext()) == erwarteter_zustand

    gespeichert = store.task(task_id)
    assert gespeichert is not None
    assert gespeichert["state"] == erwarteter_zustand
    assert gespeichert["state"] != "done"
    assert not any(e["kind"] == "task_done" for e in store.events(task_id))


def test_runtime_blockiert_task_typ_passt_nicht_zum_profil(cfg):
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:dispatch:mismatch", assigned_to="A1", dept="A",
        title="Falscher Task-Typ", task_type="paper_guard",
    )
    task = store.claim_next("worker-mismatch")
    assert task is not None
    runtime = CompanyRuntime(cfg, db, store=store)

    assert runtime._execute(task, runtime.kontext()) == "blocked"

    blockiert = store.task(task_id)
    assert blockiert is not None
    assert blockiert["state"] == "blocked"
    assert "passt nicht" in blockiert["error"]


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
def test_paper_sperre_eigenschaft_alle_broker_freigabe_kombinationen(cfg, paper):
    """Generierte Eigenschaft: nur sichere Broker mit explizitem False sind Paper."""
    if paper is None:
        cfg._d.pop("paper", None)
    else:
        cfg._d["paper"] = paper
    policy = CompanyPolicy(cfg)
    erlaubt = paper_erlaubt(paper)

    assert policy.paper_only() is erlaubt
    assert policy.check_action("paper_order").allowed is erlaubt
    if erlaubt:
        policy.check_task(profile_by_id("A1"), "paper_guard")
    else:
        with pytest.raises(PolicyError):
            policy.check_task(profile_by_id("A1"), "paper_guard")


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
def test_runtime_paper_guard_eigenschaft_alle_broker_freigabe_kombinationen(cfg, paper):
    """Der Runtime-Dispatch folgt derselben generierten Broker-Eigenschaft."""
    if paper is None:
        cfg._d.pop("paper", None)
    else:
        cfg._d["paper"] = paper
    db, store = _store(cfg)
    erlaubt = paper_erlaubt(paper)
    task_id = store.enqueue(
        task_key=f"test:runtime-paper:{uuid.uuid4().hex}",
        assigned_to="A5",
        dept="A",
        title="Paper-Guard",
        task_type="paper_guard",
    )
    task = store.claim_next(f"worker-paper-{uuid.uuid4().hex}")
    assert task is not None and task["id"] == task_id
    runtime = CompanyRuntime(cfg, db, store=store)

    zustand = runtime._execute(task, runtime.kontext())

    assert zustand == ("done" if erlaubt else "blocked")
    gespeichert = store.task(task_id)
    assert gespeichert is not None
    assert gespeichert["state"] == ("done" if erlaubt else "blocked")
    if not erlaubt:
        assert "Paper-Sperre" in gespeichert["error"]


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
    store = CompanyStore(db)
    assert all(store.erinnerungen(p.agent_id, scope="working") for p in PROFILES)
    assert db.zustand("company_letzter_lauf")["tasks_verarbeitet"] == 103


def test_lauf_bucht_den_versuch_vor_dem_abschluss(cfg, monkeypatch, caplog):
    """Ein einmaliger Schreibfehler beim Lauf-Protokoll darf keinen Task
    abschliessen, ohne dass der Agent in ``agenten_laeufe`` auftaucht."""
    db = _db(cfg)
    runtime = CompanyRuntime(cfg, db, max_workers=1)
    echt = db.agenten_lauf
    offen = {"J3": 1}

    def wackelig(agent, *args, **kwargs):
        if agent.startswith("J3:") and offen["J3"]:
            offen["J3"] -= 1
            raise sqlite3.OperationalError("database is locked")
        return echt(agent, *args, **kwargs)

    monkeypatch.setattr(db, "agenten_lauf", wackelig)
    with caplog.at_level("WARNING", logger="orakel.company.runtime"):
        ergebnis = runtime.run(tag="2026-11-09")

    assert offen["J3"] == 0  # der Fehler wurde tatsächlich ausgelöst
    assert "kann nicht fehlschlagen" not in caplog.text
    assert sum(ergebnis["states"].values()) == 103
    assert ergebnis["states"].get("done", 0) >= 1
    laeufe = {r["agent"] for r in db.agenten_laeufe(limit=300)}
    assert "J3:Datenintegritäts-Prüfer" in laeufe


@pytest.mark.parametrize("aktion", ["complete", "fail", "block"])
def test_lauf_und_task_status_werden_gemeinsam_zurueckgerollt(cfg, monkeypatch, aktion):
    """Ein Audit-Fehler darf weder den Task-Status noch den Lauf-Eintrag
    stehen lassen; beide Schreibungen gehören in dieselbe Transaktion."""
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key=f"test:atomic:{aktion}", assigned_to="A1", dept="A", title="Atomar",
    )
    assert store.claim_next("worker-atomic")["id"] == task_id
    lauf = {
        "agent": "A1:Koordinator", "abteilung": "A", "aufgabe": "Atomar",
        "ergebnis": "Testlauf", "ok": aktion == "complete",
    }
    _audit_kaputt(monkeypatch, store)

    with pytest.raises(RuntimeError, match="Audit nicht erreichbar"):
        if aktion == "complete":
            store.complete(task_id, result="belegt", evidence=["task:atomic"], lauf=lauf)
        elif aktion == "fail":
            store.fail(task_id, "Testfehler", lauf=lauf)
        else:
            store.block(task_id, "Testblockade", lauf=lauf)

    task = store.task(task_id)
    assert task is not None
    assert task["state"] == "running"
    assert db.agenten_laeufe() == []
    assert not any(e["kind"] in {"task_done", "task_failed", "task_blocked"}
                   for e in store.events(task_id))
    assert store.audit_chain_ok()


def test_worker_fallback_bucht_lauf_bei_bekanntem_profil(cfg, monkeypatch):
    """Eine unerwartete Ausnahme im Worker setzt den Task fehl und bucht den
    Lauf-Eintrag für das bekannte Profil in derselben Transaktion."""
    db, store = _store(cfg)
    task_id = store.enqueue(
        task_key="test:worker-fallback",
        assigned_to="A1",
        dept="A",
        title="Worker-Fallback",
        task_type="daily_check",
        max_attempts=1,
    )
    runtime = CompanyRuntime(cfg, db, store=store, max_workers=1)

    def kaputt(*_args, **_kwargs):
        raise RuntimeError("Worker absichtlich kaputt")

    monkeypatch.setattr(runtime, "_execute", kaputt)
    runtime._worker("worker-fallback", 1, runtime.kontext())

    task = store.task(task_id)
    assert task is not None
    assert task["state"] == "dead_letter"
    assert "Runtime-Fehler" in task["error"]
    laeufe = [r for r in db.agenten_laeufe() if r["agent"] == "A1:Koordinator"]
    assert len(laeufe) == 1
    assert laeufe[0]["ergebnis"] == "Fehler: Worker absichtlich kaputt"
    assert laeufe[0]["ok"] == 0


def test_audit_kette_erkennt_manipulation(cfg):
    db, store = _store(cfg)
    store.enqueue(task_key="test:audit:1", assigned_to="A1", dept="A",
                  title="Audit")
    assert store.audit_chain_ok()
    with db.conn() as c:
        c.execute("UPDATE agent_events SET payload_json='{}' WHERE id=1")
    assert not store.audit_chain_ok()
