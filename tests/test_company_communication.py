from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from orakel.company import api
from orakel.company.memory import AgentMemory, MemoryError
from orakel.company.messaging import (
    MessageError, MessageRateLimitError, MessagingService,
)
from orakel.company.runtime import CompanyRuntime
from orakel.company.store import CompanyStore
from orakel.db import Facts


def _store(cfg) -> tuple[Facts, CompanyStore]:
    db = Facts(cfg.db_pfad)
    store = CompanyStore(db)
    store.sync_roster()
    return db, store


def test_direkte_nachricht_thread_quittung_und_postfach(cfg):
    _, store = _store(cfg)
    service = MessagingService(store)

    gesendet = service.send(
        sender="A1", recipient="A2", kind="handoff",
        subject="Artikel an Knowledge Center",
        body="Bitte prüfen und im Vault verlinken.",
        evidence=["task:7", "article:4821"], requires_ack=True,
    )

    assert gesendet["to_agents"] == ["A2"]
    assert gesendet["thread_id"].startswith("thr_")
    message_id = gesendet["message_ids"][0]
    message = api.nachricht(store, message_id)
    assert message is not None
    assert message["nachricht"]["from_agent"] == "A1"
    assert message["nachricht"]["to_agent"] == "A2"
    assert message["nachricht"]["evidence"] == ["task:7", "article:4821"]
    assert message["nachricht"]["requires_ack"] is True

    postfach = api.nachrichten(store, agent="A2", nur_offen=True)
    assert postfach["gesamt"] == 1
    assert postfach["nachrichten"][0]["id"] == message_id
    assert postfach["threads"][0]["teilnehmer"] == ["A1", "A2"]

    bestaetigt = service.ack(message_id, "A2")
    assert bestaetigt["ack_at"]
    assert api.nachrichten(store, agent="A2", nur_offen=True)["gesamt"] == 0
    # Wiederholtes Quittieren ist idempotent, aber ein fremder Agent darf nicht.
    assert service.ack(message_id, "A2")["ack_at"] == bestaetigt["ack_at"]
    with pytest.raises(MessageError):
        service.ack(message_id, "A3")

    antwort = service.send(
        sender="A2", recipient="A1", kind="answer",
        subject="Artikel geprüft", body="Ergebnis ist belegt.",
        thread_id=gesendet["thread_id"],
    )
    threads = api.nachrichten(store, thread_id=gesendet["thread_id"])
    assert antwort["thread_id"] == gesendet["thread_id"]
    assert threads["gesamt"] == 2
    assert {m["id"] for m in threads["nachrichten"]} == {
        message_id, antwort["message_ids"][0],
    }


def test_abteilungsnachricht_und_broadcast_regeln(cfg):
    _, store = _store(cfg)
    service = MessagingService(store)

    abteilung = service.send(
        sender="A1", recipient="dept:A", kind="status",
        subject="Lage", body="Kurze Lage für die Abteilung.",
    )
    assert len(abteilung["to_agents"]) == 10
    assert all(agent.startswith("A") for agent in abteilung["to_agents"])

    with pytest.raises(MessageError):
        service.send(
            sender="A2", recipient="dept:A", kind="status",
            subject="Nicht erlaubt", body="Mitglied darf nicht adressieren.",
        )
    with pytest.raises(MessageError):
        service.send(
            sender="A2", recipient="all", kind="status",
            subject="Nicht erlaubt", body="Kein Broadcast-Recht.",
        )

    broadcast = service.send(
        sender="S1", recipient="all", kind="status",
        subject="Tageslage", body="Kurzer Status an alle Agenten.",
    )
    assert len(broadcast["to_agents"]) == 103


def test_broadcast_rate_limit_ist_persistent_und_pro_absender(cfg):
    _, store = _store(cfg)
    service = MessagingService(store)

    erster = service.send(sender="A1", recipient="all", kind="status",
                          subject="Lage", body="Erster Broadcast.")
    assert erster["broadcast"] is True
    assert len(erster["to_agents"]) == 103

    with pytest.raises(MessageRateLimitError) as fehler:
        service.send(sender="A1", recipient="all", kind="status",
                     subject="Nochmal", body="Zu schnell.")
    assert fehler.value.limit == "cooldown"
    assert fehler.value.retry_after > 0

    # Direkte und Abteilungsnachrichten teilen das Broadcast-Limit nicht.
    service.send(sender="A1", recipient="A2", subject="Direkt", body="Direkt.")
    service.send(sender="A1", recipient="dept:A", subject="Abteilung",
                 body="Abteilung.")
    # Ein anderer berechtigter Absender hat sein eigenes Budget.
    service.send(sender="S1", recipient="all", subject="Lage S1",
                 body="Eigener Broadcast.")

    # Der gleiche Absender bleibt auch nach einem neuen Store-Service limitiert.
    with pytest.raises(MessageRateLimitError):
        MessagingService(CompanyStore(store.facts)).send(
            sender="A1", recipient="all", subject="Neu", body="Immer noch zu schnell.",
        )


def test_broadcast_tageslimit_ist_konfigurierbar(cfg):
    _, store = _store(cfg)
    store.policy_setzen("broadcast_cooldown_sekunden", 0)
    store.policy_setzen("broadcast_max_pro_tag", 2)
    service = MessagingService(store)

    for nummer in (1, 2):
        service.send(sender="A1", recipient="all", kind="status",
                     subject=f"Lage {nummer}", body="Kurzer Status.")

    with pytest.raises(MessageRateLimitError) as fehler:
        service.send(sender="A1", recipient="all", kind="status",
                     subject="Lage 3", body="Tageslimit.")
    assert fehler.value.limit == "tag"
    assert fehler.value.retry_after > 0


def _alter_nachricht(store: CompanyStore, message_id: int,
                     minuten: int = 120) -> None:
    alt = (datetime.now(timezone.utc) - timedelta(minutes=minuten)).replace(
        microsecond=0).isoformat()
    with store.facts.conn() as c:
        c.execute("UPDATE agent_messages SET created_at=? WHERE id=?",
                  (alt, int(message_id)))


def test_offene_acks_werden_erinnert_und_nicht_doppelt(cfg):
    _, store = _store(cfg)
    service = MessagingService(store)
    gesendet = service.send(
        sender="B1", recipient="G1", kind="handoff",
        subject="Bitte prüfen", body="Bitte im Vault prüfen.",
        evidence=["article:1"], requires_ack=True,
    )
    message_id = gesendet["message_ids"][0]

    # Vor Ablauf der Erinnerungsfrist passiert nichts.
    assert service.erinnere_offene_acks()["erinnert"] == 0
    _alter_nachricht(store, message_id)

    ergebnis = service.erinnere_offene_acks()
    assert ergebnis["erinnert"] == 1
    nachrichten = api.nachrichten(store, thread_id=gesendet["thread_id"])
    erinnerungen = [m for m in nachrichten["nachrichten"]
                    if not m["requires_ack"]]
    assert len(erinnerungen) == 1
    erinnerung = erinnerungen[0]
    assert erinnerung["from_agent"] == "B1"
    assert erinnerung["to_agent"] == "G1"
    assert erinnerung["thread_id"] == gesendet["thread_id"]
    assert erinnerung["subject"].startswith("Erinnerung:")
    assert erinnerung["evidence"] == [f"message:{message_id}"]
    assert erinnerung["ack_at"] is None

    wiederholt = service.erinnere_offene_acks()
    assert wiederholt["erinnert"] == 0
    assert wiederholt["uebersprungen"]["max_erreicht"] == 1
    # Auch ein neuer Service liest die Erinnerung aus der persistenten Historie.
    assert MessagingService(CompanyStore(store.facts)).erinnere_offene_acks()[
        "erinnert"] == 0

    service.ack(message_id, "G1")
    assert service.erinnere_offene_acks()["erinnert"] == 0


def test_company_lauf_fuehrt_die_erinnerungen_aus(cfg):
    db, store = _store(cfg)
    service = MessagingService(store)
    gesendet = service.send(
        sender="B1", recipient="G1", kind="handoff",
        subject="Bitte prüfen", body="Bitte prüfen.", requires_ack=True,
    )
    _alter_nachricht(store, gesendet["message_ids"][0])

    ergebnis = CompanyRuntime(cfg, db, store=store, max_workers=1).run(
        tag="2026-11-15", max_tasks=0,
    )

    assert ergebnis["erinnerungen"]["erinnert"] == 1
    assert store.audit_chain_ok()


def test_erinnerung_wiederholt_sich_bis_zum_konfigurierten_maximum(cfg):
    _, store = _store(cfg)
    store.policy_setzen("ack_erinnerung_wiederholen_minuten", 1)
    store.policy_setzen("ack_erinnerungen_max", 2)
    service = MessagingService(store)
    gesendet = service.send(
        sender="B1", recipient="G1", kind="handoff",
        subject="Bitte prüfen", body="Bitte prüfen.", requires_ack=True,
    )
    _alter_nachricht(store, gesendet["message_ids"][0])
    jetzt = datetime.now(timezone.utc)

    assert service.erinnere_offene_acks(jetzt_wert=jetzt)["erinnert"] == 1
    assert service.erinnere_offene_acks(jetzt_wert=jetzt)["erinnert"] == 0
    spaeter = jetzt + timedelta(minutes=2)
    assert service.erinnere_offene_acks(jetzt_wert=spaeter)["erinnert"] == 1
    assert service.erinnere_offene_acks(
        jetzt_wert=spaeter + timedelta(minutes=2))["erinnert"] == 0


def test_ungueltige_nachrichten_werden_abgelehnt(cfg):
    _, store = _store(cfg)
    service = MessagingService(store)

    with pytest.raises(MessageError):
        service.send(sender="GIBT-ES-NICHT", recipient="A2",
                     subject="Test", body="Test")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="GIBT-ES-NICHT",
                     subject="Test", body="Test")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A1",
                     subject="Test", body="Test")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", kind="unbekannt",
                     subject="Test", body="Test")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", subject="",
                     body="Test")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", subject="Zugang",
                     body="api_key=abcdefgh12345")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", subject="Test",
                     body="Test", evidence="task:1")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", subject="Test",
                     body="Test", priority="sofort")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", subject="Test",
                     body="Test", expires_at="2000-01-01T00:00:00Z")
    with pytest.raises(MessageError):
        service.send(sender="A1", recipient="A2", subject="Test",
                     body="Test", thread_id="ungültig mit Leerzeichen")


def test_persoenliches_gedaechtnis_ist_getrennt_und_versioniert(cfg):
    _, store = _store(cfg)
    memory = AgentMemory(store)

    angelegt = memory.set("A1", "profile", "praeferenz",
                          {"symbol": "EURUSD", "notiz": "bevorzugt"})
    assert angelegt["agent_id"] == "A1"
    assert angelegt["scope"] == "profile"
    assert angelegt["value"] == {"symbol": "EURUSD", "notiz": "bevorzugt"}

    assert memory.get("A1", "profile", "praeferenz") == angelegt
    assert memory.list("A1", scope="profile")[0]["key"] == "praeferenz"
    assert memory.list("A2") == []
    assert memory.get("A2", "profile", "praeferenz") is None

    geaendert = memory.set("A1", "profile", "praeferenz",
                           {"symbol": "EURUSD", "notiz": "aktualisiert"})
    assert geaendert["value"]["notiz"] == "aktualisiert"
    assert len(memory.list("A1", scope="profile")) == 1

    memory.set("A1", "working", "task:7", {"ref": "task:7", "state": "done"})
    assert {e["scope"] for e in memory.list("A1")} == {"profile", "working"}

    assert memory.delete("A1", "working", "task:7") is True
    assert memory.get("A1", "working", "task:7") is None
    assert memory.delete("A1", "working", "task:7") is False


def test_gedaechtnis_prueft_agent_scope_key_und_secrets(cfg):
    _, store = _store(cfg)
    memory = AgentMemory(store)

    with pytest.raises(MemoryError):
        memory.set("GIBT-ES-NICHT", "profile", "x", 1)
    with pytest.raises(MemoryError):
        memory.set("A1", "profil mit leerzeichen", "x", 1)
    with pytest.raises(MemoryError):
        memory.set("A1", "profile", "x mit leerzeichen", 1)
    with pytest.raises(MemoryError):
        memory.set("A1", "profile", "geheim", "token=abcdefgh12345")


def test_api_liefert_erinnerungen_und_offene_nachrichten(cfg):
    _, store = _store(cfg)
    memory = AgentMemory(store)
    MessagingService(store).send(
        sender="B1", recipient="G1", kind="handoff",
        subject="Handoff", body="Bitte prüfen.",
        evidence=["article:1"], requires_ack=True,
    )
    memory.set("G1", "profile", "thema", {"name": "Volatilität"})

    detail = api.agent_detail(store, "g1")
    assert detail is not None
    assert detail["erinnerungen"][0]["value"] == {"name": "Volatilität"}
    assert any(source.startswith("memory:profile:") for source in detail["source_refs"])
    assert len(detail["nachrichten"]) == 1

    erinnerungen = api.erinnerungen(store, "G1", scope="profile")
    assert erinnerungen is not None
    assert erinnerungen["gesamt"] == 1
    assert erinnerungen["erinnerungen"][0]["key"] == "thema"
    assert api.erinnerungen(store, "GIBT-ES-NICHT") is None
