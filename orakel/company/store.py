"""Persistenz der Unternehmensschicht.

Die Fakten-Datenbank bleibt die einzige DB. `CompanyStore` nutzt deren
Verbindungen und legt nur die neuen Company-Tabellen an.
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence

from ..db import Facts
from .policy import ERLAUBTE_TASK_TYPES
from .roster import Profile, all_profiles


def jetzt() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def spaeter(sekunden: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=sekunden)).replace(
        microsecond=0).isoformat()


class StoreError(RuntimeError):
    """Ungültiger Queue-/Profilzustand."""


def _erinnerung(row: Any) -> dict[str, Any]:
    try:
        wert = json.loads(row["value_json"])
    except (TypeError, ValueError):
        wert = None
    return {
        "agent_id": row["agent_id"],
        "scope": row["scope"],
        "key": row["key"],
        "value": wert,
        "updated_at": row["updated_at"],
    }


class CompanyStore:
    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self._event_lock = threading.RLock()

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        with self.facts.conn() as c:
            c.execute("PRAGMA foreign_keys=ON")
            yield c

    def _append_event_im_transaktion(
        self, c: Any, agent_id: str, task_id: int | None, kind: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Schreibt ein Audit-Event in die bereits offene Transaktion.

        Der Aufrufer hält ``_event_lock`` und eine ``BEGIN IMMEDIATE``-
        Transaktion. Dadurch werden Task-Status und Audit-Event gemeinsam
        committet oder gemeinsam zurückgerollt.
        """
        last = c.execute("SELECT hash FROM agent_events ORDER BY id DESC LIMIT 1").fetchone()
        prev = str(last["hash"]) if last else "GENESIS"
        ts = jetzt()
        roh = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"))
        material = f"{prev}|{ts}|{agent_id}|{task_id or ''}|{kind}|{roh}"
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        c.execute(
            "INSERT INTO agent_events(ts,agent_id,task_id,kind,payload_json,prev_hash,hash)"
            " VALUES (?,?,?,?,?,?,?)",
            (ts, agent_id, task_id, kind, roh, prev, digest),
        )
        return digest

    # ---------- Profile ----------
    def sync_roster(self, profile: Sequence[Profile] | None = None) -> int:
        profile = list(profile if profile is not None else all_profiles())
        zeit = jetzt()
        with self._conn() as c:
            for p in profile:
                c.execute(
                    """
                    INSERT INTO agent_profiles(
                        agent_id, rufname, dept, dept_name, role, rank, mission,
                        station, avatar, autonomy, reports_to, backup, active,
                        data_scope_json, tools_json, memory_scope, kpi,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?)
                    ON CONFLICT(agent_id) DO UPDATE SET
                        rufname=excluded.rufname,
                        dept=excluded.dept,
                        dept_name=excluded.dept_name,
                        role=excluded.role,
                        rank=excluded.rank,
                        mission=excluded.mission,
                        station=excluded.station,
                        avatar=excluded.avatar,
                        autonomy=excluded.autonomy,
                        reports_to=excluded.reports_to,
                        backup=excluded.backup,
                        active=1,
                        data_scope_json=excluded.data_scope_json,
                        tools_json=excluded.tools_json,
                        memory_scope=excluded.memory_scope,
                        kpi=excluded.kpi,
                        updated_at=excluded.updated_at
                    """,
                    (
                        p.agent_id, p.rufname, p.dept, p.dept_name, p.role, p.rank,
                        p.mission, p.station, p.avatar, p.autonomy, p.reports_to,
                        p.backup, json.dumps(p.data_scope, ensure_ascii=False),
                        json.dumps(p.tools, ensure_ascii=False), p.memory_scope, p.kpi,
                        zeit, zeit,
                    ),
                )
        return len(profile)

    def profil(self, agent_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM agent_profiles WHERE agent_id=?", (agent_id,)).fetchone()
        return dict(r) if r else None

    def profile(self, agent_id: str) -> dict[str, Any] | None:
        return self.profil(agent_id)

    def profile_alle(self) -> list[dict[str, Any]]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM agent_profiles ORDER BY dept, agent_id")]

    def profile_anzahl(self) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) n FROM agent_profiles").fetchone()["n"])

    # ---------- Policy-Werte ----------
    def policy_setzen(self, schluessel: str, wert: Any, ebene: str = "weich",
                      geaendert_von: str = "SYSTEM") -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO company_policies(key,value_json,level,updated_by,updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,"
                " level=excluded.level, updated_by=excluded.updated_by,"
                " updated_at=excluded.updated_at",
                (schluessel, json.dumps(wert, ensure_ascii=False), ebene, geaendert_von, jetzt()),
            )

    def policy(self, schluessel: str, standard: Any = None) -> Any:
        with self._conn() as c:
            r = c.execute("SELECT value_json FROM company_policies WHERE key=?",
                          (schluessel,)).fetchone()
        return json.loads(r["value_json"]) if r else standard

    def policy_seed(self) -> None:
        defaults = {
            "max_tasks_pro_tag": 250,
            "max_projekte_pro_tag": 3,
            "max_offene_tasks_pro_agent": 3,
            "max_llm_minuten_pro_tag": 0,
            "max_worker": 4,
            "autonomie_budget_version": 1,
            # Broadcasts sind teuer: ein kurzer Abstand schützt vor Wiederholungen,
            # das Tageslimit vor einem versehentlichen Feuerwerk an alle 103 Agenten.
            "broadcast_cooldown_sekunden": 900,
            "broadcast_max_pro_tag": 10,
            # Offene Quittungen werden nach dieser Frist einmalig erinnert.
            "ack_erinnerung_nach_minuten": 30,
            "ack_erinnerung_wiederholen_minuten": 120,
            "ack_erinnerungen_max": 1,
        }
        for key, value in defaults.items():
            if self.policy(key) is None:
                self.policy_setzen(key, value)

    # ---------- Tasks ----------
    def enqueue(
        self,
        *,
        task_key: str,
        assigned_to: str,
        dept: str,
        title: str,
        description: str = "",
        task_type: str = "daily_check",
        priority: int = 50,
        created_by: str = "SYSTEM",
        parent_id: int | None = None,
        autonomy_level: int = 1,
        acceptance: str = "",
        input_data: dict[str, Any] | None = None,
        due_at: str | None = None,
        max_attempts: int = 3,
    ) -> int:
        if not isinstance(task_type, str) or task_type not in ERLAUBTE_TASK_TYPES:
            raise StoreError(f"Unbekannter Task-Typ: {task_type!r}")
        zeit = jetzt()
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                vorhanden = c.execute(
                    "SELECT id, task_type FROM agent_tasks WHERE task_key=?",
                    (task_key,),
                ).fetchone()
                if vorhanden:
                    vorhandener_typ = str(vorhanden["task_type"])
                    if vorhandener_typ != task_type:
                        raise StoreError(
                            f"Task-Key {task_key!r} ist bereits mit Task-Typ "
                            f"{vorhandener_typ!r} belegt"
                        )
                    return int(vorhanden["id"])
                cur = c.execute(
                    """
                    INSERT INTO agent_tasks(
                        task_key,parent_id,created_by,assigned_to,dept,title,description,
                        task_type,priority,state,autonomy_level,max_attempts,attempts,
                        due_at,acceptance,input_json,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,'queued',?,?,0,?,?,?,?,?)
                    """,
                    (
                        task_key, parent_id, created_by, assigned_to, dept, title, description,
                        task_type, int(priority), int(autonomy_level), int(max_attempts),
                        due_at, acceptance,
                        json.dumps(input_data or {}, ensure_ascii=False), zeit, zeit,
                    ),
                )
                task_id = int(cur.lastrowid or 0)
                self._append_event_im_transaktion(
                    c, "SYSTEM", task_id, "task_created", {
                        "task_key": task_key,
                        "assigned_to": assigned_to,
                        "task_type": task_type,
                    },
                )
        return task_id

    def task(self, task_id: int) -> dict[str, Any] | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
        return dict(r) if r else None

    def tasks(self, state: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self._conn() as c:
            if state:
                return [dict(r) for r in c.execute(
                    "SELECT * FROM agent_tasks WHERE state=? ORDER BY priority DESC, id LIMIT ?",
                    (state, limit))]
            return [dict(r) for r in c.execute(
                "SELECT * FROM agent_tasks ORDER BY id DESC LIMIT ?", (limit,))]

    def task_counts(self) -> dict[str, int]:
        with self._conn() as c:
            return {r["state"]: int(r["n"]) for r in c.execute(
                "SELECT state, COUNT(*) n FROM agent_tasks GROUP BY state")}

    def tasks_fuer_agent(self, agent_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM agent_tasks WHERE assigned_to=? ORDER BY id DESC LIMIT ?",
                (agent_id, limit))]

    def add_dependency(self, task_id: int, depends_on: int, kind: str = "success") -> None:
        if task_id == depends_on:
            raise StoreError("Eine Task kann nicht von sich selbst abhängen")
        with self._conn() as c:
            c.execute("INSERT OR IGNORE INTO agent_task_deps(task_id,depends_on,kind) VALUES (?,?,?)",
                      (task_id, depends_on, kind))

    def recover_expired(self, lease_seconds: int = 120) -> int:
        """Gibt abgelaufene Leases frei; harte Fehlschläge bleiben sichtbar."""
        grenze = jetzt()
        betroffen = 0
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                rows = list(c.execute(
                    "SELECT id, attempts, max_attempts FROM agent_tasks"
                    " WHERE state='running' AND lease_until IS NOT NULL AND lease_until < ?",
                    (grenze,),
                ))
                for row in rows:
                    neu = "dead_letter" if int(row["attempts"]) >= int(row["max_attempts"]) else "queued"
                    c.execute(
                        "UPDATE agent_tasks SET state=?, lease_until=NULL, lease_owner=NULL,"
                        " error=?, updated_at=? WHERE id=? AND state='running'",
                        (neu, "Lease abgelaufen", grenze, int(row["id"])),
                    )
                    betroffen += 1
                if betroffen:
                    self._append_event_im_transaktion(
                        c, "SYSTEM", None, "lease_recovered", {"tasks": betroffen},
                    )
        return betroffen

    def claim_next(self, worker: str, lease_seconds: int = 120) -> dict[str, Any] | None:
        until = spaeter(lease_seconds)
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                row = c.execute(
                    """
                    SELECT t.* FROM agent_tasks t
                    WHERE t.state='queued'
                      AND EXISTS (SELECT 1 FROM agent_profiles p
                                  WHERE p.agent_id=t.assigned_to AND p.active=1)
                      AND NOT EXISTS (SELECT 1 FROM agent_tasks r
                                      WHERE r.assigned_to=t.assigned_to
                                        AND r.state='running')
                      AND NOT EXISTS (
                          SELECT 1 FROM agent_task_deps d
                          JOIN agent_tasks p ON p.id=d.depends_on
                          WHERE d.task_id=t.id AND p.state <> 'done'
                      )
                    ORDER BY t.priority DESC, t.due_at IS NULL, t.due_at, t.id
                    LIMIT 1
                    """,
                ).fetchone()
                if not row:
                    return None
                cur = c.execute(
                    "UPDATE agent_tasks SET state='running', attempts=attempts+1,"
                    " lease_owner=?, lease_until=?, started_at=COALESCE(started_at,?),"
                    " updated_at=? WHERE id=? AND state='queued'",
                    (worker, until, jetzt(), jetzt(), int(row["id"])),
                )
                if cur.rowcount != 1:
                    return None
                aktuell = c.execute("SELECT * FROM agent_tasks WHERE id=?",
                                    (int(row["id"]),)).fetchone()
                task = dict(aktuell)
                self._append_event_im_transaktion(
                    c, task["assigned_to"], task["id"], "task_claimed", {
                        "worker": worker,
                        "attempt": task["attempts"],
                    },
                )
        return task

    def complete(
        self,
        task_id: int,
        *,
        result: str,
        evidence: Sequence[str],
        output: dict[str, Any] | None = None,
        reviewed_by: str = "policy",
    ) -> None:
        zeit = jetzt()
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                cur = c.execute(
                    "UPDATE agent_tasks SET state='done', result=?, evidence_json=?,"
                    " output_json=?, error='', finished_at=?, reviewed_by=?,"
                    " reviewed_at=?, lease_owner=NULL, lease_until=NULL, updated_at=?"
                    " WHERE id=? AND state='running'",
                    (result, json.dumps(list(evidence), ensure_ascii=False),
                     json.dumps(output or {}, ensure_ascii=False), zeit, reviewed_by, zeit,
                     zeit, task_id),
                )
                if cur.rowcount != 1:
                    raise StoreError(f"Task {task_id} ist nicht im Zustand running")
                task = c.execute("SELECT assigned_to FROM agent_tasks WHERE id=?",
                                 (task_id,)).fetchone()
                self._append_event_im_transaktion(
                    c, task["assigned_to"], task_id, "task_done", {
                        "result": result[:500],
                        "evidence": list(evidence),
                    },
                )

    def block(self, task_id: int, grund: str, evidence: Sequence[str] = ()) -> None:
        zeit = jetzt()
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                cur = c.execute(
                    "UPDATE agent_tasks SET state='blocked', result=?, error=?,"
                    " evidence_json=?, finished_at=?, lease_owner=NULL, lease_until=NULL,"
                    " updated_at=? WHERE id=? AND state IN ('running','queued','accepted')",
                    (grund, grund, json.dumps(list(evidence), ensure_ascii=False), zeit, zeit, task_id),
                )
                if cur.rowcount != 1:
                    raise StoreError(f"Task {task_id} kann nicht blockiert werden")
                task = c.execute("SELECT assigned_to FROM agent_tasks WHERE id=?",
                                 (task_id,)).fetchone()
                self._append_event_im_transaktion(
                    c, task["assigned_to"], task_id, "task_blocked", {"reason": grund},
                )

    def fail(self, task_id: int, fehler: str) -> str:
        """Markiert eine laufende oder wartende Aufgabe als fehlgeschlagen.

        Ein bereits abgeschlossener Task darf nicht wiederbelebt werden: Sonst
        könnte ein Fehler nach dem Commit von ``complete()`` dieselbe Aufgabe
        erneut in die Queue stellen.
        """
        zeit = jetzt()
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                row = c.execute("SELECT assigned_to, attempts, max_attempts, state"
                                " FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
                if not row:
                    raise StoreError(f"Unbekannte Task {task_id}")
                zustand = str(row["state"])
                if zustand not in {"running", "queued", "accepted"}:
                    raise StoreError(
                        f"Task {task_id} ist im Zustand {zustand} und kann nicht fehlschlagen"
                    )
                neu = "dead_letter" if int(row["attempts"]) >= int(row["max_attempts"]) else "queued"
                cur = c.execute(
                    "UPDATE agent_tasks SET state=?, error=?, result=?,"
                    " finished_at=CASE WHEN ?='dead_letter' THEN ? ELSE finished_at END,"
                    " lease_owner=NULL, lease_until=NULL, updated_at=?"
                    " WHERE id=? AND state IN ('running','queued','accepted')",
                    (neu, fehler, fehler, neu, zeit, zeit, task_id),
                )
                if cur.rowcount != 1:
                    raise StoreError(f"Task {task_id} konnte nicht fehlschlagen")
                self._append_event_im_transaktion(
                    c, row["assigned_to"], task_id, "task_failed",
                    {"error": fehler, "state": neu},
                )
        return neu

    # ---------- Events / Audit ----------
    def append_event(self, agent_id: str, task_id: int | None, kind: str,
                     payload: dict[str, Any] | None = None) -> str:
        """Append-only Event mit Hash-Kette. Die Kette ist absichtlich einfach prüfbar."""
        with self._event_lock:
            with self._conn() as c:
                c.execute("BEGIN IMMEDIATE")
                return self._append_event_im_transaktion(c, agent_id, task_id, kind, payload)

    def events(self, task_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            if task_id is None:
                rows = c.execute("SELECT * FROM agent_events ORDER BY id DESC LIMIT ?", (limit,))
            else:
                rows = c.execute("SELECT * FROM agent_events WHERE task_id=? ORDER BY id",
                                 (task_id,))
            return [dict(r) for r in rows]

    def audit_chain_ok(self) -> bool:
        """Prüft die gesamte Kette; ein fehlender oder veränderter Eintrag fällt auf."""
        with self._conn() as c:
            rows = list(c.execute(
                "SELECT id,ts,agent_id,task_id,kind,payload_json,prev_hash,hash"
                " FROM agent_events ORDER BY id"))
        prev = "GENESIS"
        for row in rows:
            material = (f"{prev}|{row['ts']}|{row['agent_id']}|{row['task_id'] or ''}|"
                        f"{row['kind']}|{row['payload_json']}")
            if row["prev_hash"] != prev:
                return False
            if hashlib.sha256(material.encode("utf-8")).hexdigest() != row["hash"]:
                return False
            prev = row["hash"]
        return True

    # ---------- Nachrichten / Entscheidungen (Phase 1 vorbereitet) ----------
    def nachricht_speichern(self, *, thread_id: str, from_agent: str, to_agent: str,
                            kind: str, subject: str, body: str,
                            evidence: Sequence[str] = (), requires_ack: bool = False,
                            priority: str = "normal", expires_at: str | None = None) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO agent_messages(thread_id,from_agent,to_agent,kind,priority,"
                "subject,body,evidence_json,requires_ack,created_at,expires_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (thread_id, from_agent, to_agent, kind, priority, subject, body,
                 json.dumps(list(evidence), ensure_ascii=False), int(requires_ack),
                 jetzt(), expires_at),
            )
            return int(cur.lastrowid or 0)

    def nachrichten(self, thread_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            if thread_id:
                return [dict(r) for r in c.execute(
                    "SELECT * FROM agent_messages WHERE thread_id=? ORDER BY id", (thread_id,))]
            return [dict(r) for r in c.execute(
                "SELECT * FROM agent_messages ORDER BY id DESC LIMIT ?", (limit,))]

    def nachrichten_gefiltert(self, *, agent: str | None = None, dept: str | None = None,
                              thread_id: str | None = None, seit: str | None = None,
                              nur_offen: bool = False,
                              limit: int = 100) -> list[dict[str, Any]]:
        """Nachrichten mit Profilnamen, optional nach Agent, Abteilung oder Zeit."""
        where: list[str] = []
        parameter: list[Any] = []
        if thread_id:
            where.append("m.thread_id=?")
            parameter.append(thread_id)
        if agent:
            if nur_offen:
                where.append("m.to_agent=? AND m.ack_at IS NULL")
                parameter.append(agent)
            else:
                where.append("(m.from_agent=? OR m.to_agent=?)")
                parameter.extend([agent, agent])
        elif nur_offen:
            where.append("m.ack_at IS NULL")
        if dept:
            where.append("(pfrom.dept=? OR pto.dept=?)")
            parameter.extend([dept, dept])
        if seit:
            where.append("m.created_at>=?")
            parameter.append(seit)
        sql = """
            SELECT m.*, pfrom.rufname AS from_rufname, pfrom.dept AS from_dept,
                   pto.rufname AS to_rufname, pto.dept AS to_dept
            FROM agent_messages m
            LEFT JOIN agent_profiles pfrom ON pfrom.agent_id=m.from_agent
            LEFT JOIN agent_profiles pto ON pto.agent_id=m.to_agent
        """
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.id DESC LIMIT ?"
        werte = [*parameter, max(1, min(500, int(limit)))]
        with self._conn() as c:
            return [dict(r) for r in c.execute(sql, werte)]

    def nachrichten_fuer_agent(self, agent_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.nachrichten_gefiltert(agent=agent_id, limit=limit)

    def nachricht(self, message_id: int) -> dict[str, Any] | None:
        """Eine einzelne Nachricht mit den Namen von Sender und Empfänger."""
        with self._conn() as c:
            row = c.execute(
                """
                SELECT m.*, pfrom.rufname AS from_rufname, pfrom.dept AS from_dept,
                       pto.rufname AS to_rufname, pto.dept AS to_dept
                FROM agent_messages m
                LEFT JOIN agent_profiles pfrom ON pfrom.agent_id=m.from_agent
                LEFT JOIN agent_profiles pto ON pto.agent_id=m.to_agent
                WHERE m.id=?
                """,
                (int(message_id),),
            ).fetchone()
        return dict(row) if row else None

    def nachricht_quittieren(self, message_id: int, agent_id: str) -> bool:
        """Setzt die Quittung ausschliesslich für den adressierten Empfänger."""
        with self._conn() as c:
            cur = c.execute(
                "UPDATE agent_messages SET ack_at=?"
                " WHERE id=? AND to_agent=? AND ack_at IS NULL",
                (jetzt(), int(message_id), agent_id),
            )
            return cur.rowcount == 1

    def nachrichten_events(self, *, agent_id: str, seit: str,
                           limit: int = 5000) -> list[dict[str, Any]]:
        """Versand-Events eines Absenders für das persistente Broadcast-Limit."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, ts, payload_json FROM agent_events"
                " WHERE agent_id=? AND kind='message_sent' AND ts>=?"
                " ORDER BY id DESC LIMIT ?",
                (agent_id, seit, max(1, min(5000, int(limit)))),
            )]

    def offene_ack_nachrichten(self, *, vor: str, jetzt: str,
                               limit: int = 100) -> list[dict[str, Any]]:
        """Offene Quittungen, die vor dem Erinnerungszeitpunkt eingegangen sind."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                """
                SELECT m.*, pfrom.rufname AS from_rufname, pfrom.dept AS from_dept,
                       pto.rufname AS to_rufname, pto.dept AS to_dept
                FROM agent_messages m
                LEFT JOIN agent_profiles pfrom ON pfrom.agent_id=m.from_agent
                LEFT JOIN agent_profiles pto ON pto.agent_id=m.to_agent
                WHERE m.requires_ack=1 AND m.ack_at IS NULL
                  AND m.created_at<=?
                  AND (m.expires_at IS NULL OR m.expires_at>?)
                ORDER BY m.created_at, m.id LIMIT ?
                """,
                (vor, jetzt, max(1, min(500, int(limit)))),
            )]

    def erinnerungs_events(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Erinnerungs-Events für die Idempotenz der automatischen Erinnerungen."""
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, ts, payload_json FROM agent_events"
                " WHERE kind='message_reminder' ORDER BY id DESC LIMIT ?",
                (max(1, min(5000, int(limit))),),
            )]

    # ---------- Persönliches Agenten-Gedächtnis ----------
    def erinnerung_setzen(self, *, agent_id: str, scope: str, key: str,
                          value: Any) -> dict[str, Any] | None:
        """Legt einen Schlüssel im persönlichen Gedächtnis an oder aktualisiert ihn."""
        with self._conn() as c:
            c.execute(
                "INSERT INTO agent_memories(agent_id,scope,key,value_json,updated_at)"
                " VALUES (?,?,?,?,?)"
                " ON CONFLICT(agent_id,scope,key) DO UPDATE SET"
                " value_json=excluded.value_json, updated_at=excluded.updated_at",
                (agent_id, scope, key,
                 json.dumps(value, ensure_ascii=False, sort_keys=True), jetzt()),
            )
        return self.erinnerung(agent_id, scope, key)

    def erinnerung(self, agent_id: str, scope: str, key: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM agent_memories WHERE agent_id=? AND scope=? AND key=?",
                (agent_id, scope, key),
            ).fetchone()
        return _erinnerung(row) if row else None

    def erinnerungen(self, agent_id: str, scope: str | None = None,
                     limit: int = 200) -> list[dict[str, Any]]:
        with self._conn() as c:
            if scope:
                rows = list(c.execute(
                    "SELECT * FROM agent_memories WHERE agent_id=? AND scope=?"
                    " ORDER BY updated_at DESC, key LIMIT ?",
                    (agent_id, scope, max(1, min(500, int(limit)))),
                ))
            else:
                rows = list(c.execute(
                    "SELECT * FROM agent_memories WHERE agent_id=?"
                    " ORDER BY updated_at DESC, key LIMIT ?",
                    (agent_id, max(1, min(500, int(limit)))),
                ))
        return [_erinnerung(row) for row in rows]

    def erinnerung_loeschen(self, agent_id: str, scope: str, key: str) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM agent_memories WHERE agent_id=? AND scope=? AND key=?",
                (agent_id, scope, key),
            )
            return cur.rowcount == 1

    def entscheidung_speichern(self, *, level: int, title: str, kind: str,
                               rationale: str, owner: str,
                               evidence: Sequence[str] = (), deadline: str | None = None,
                               session_id: int | None = None) -> int:
        zeit = jetzt()
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO company_decisions(session_id,level,title,kind,status,"
                "evidence_json,rationale,owner,deadline,created_at,updated_at)"
                " VALUES (?,?,?,?,'offen',?,?,?,?,?,?)",
                (session_id, level, title, kind, json.dumps(list(evidence), ensure_ascii=False),
                 rationale, owner, deadline, zeit, zeit),
            )
            return int(cur.lastrowid or 0)

    # ---------- Übersicht ----------
    def schiff_zahlen(self) -> dict[str, int]:
        """Cluster- und Agentenzahl für die öffentliche Health-/Smoke-Prüfung."""
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS agenten, COUNT(DISTINCT dept) AS cluster"
                " FROM agent_profiles"
            ).fetchone()
        return {"cluster": int(row["cluster"]), "agenten": int(row["agenten"])}

    def stats(self) -> dict[str, Any]:
        counts = self.task_counts()
        with self._conn() as c:
            profile = int(c.execute("SELECT COUNT(*) n FROM agent_profiles").fetchone()["n"])
            abteilungen = {r["dept"]: int(r["n"]) for r in c.execute(
                "SELECT dept, COUNT(*) n FROM agent_profiles GROUP BY dept ORDER BY dept")}
            blockiert = [dict(r) for r in c.execute(
                "SELECT id, assigned_to, title, error FROM agent_tasks"
                " WHERE state='blocked' ORDER BY id DESC LIMIT 10")]
        return {
            "profile": profile,
            "abteilungen": abteilungen,
            "tasks": counts,
            "blockiert": blockiert,
            "audit_ok": self.audit_chain_ok(),
        }
