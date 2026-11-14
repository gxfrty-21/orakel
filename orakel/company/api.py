"""Lese-API der Company-Schicht.

Die Funktionen liefern ausschliesslich Daten aus SQLite. Sie erzeugen keine
Tasks, starten keine Handler und verändern keinen Zustand. Jede Antwort nennt
Datenstand, Erzeugungszeit und Quellen; fehlende Daten bleiben leer statt
erfunden zu werden.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .store import CompanyStore

OFFENE_STATES = ("proposed", "queued", "accepted", "running", "review", "blocked")
ALLE_STATES = (
    "proposed", "queued", "accepted", "running", "review", "blocked",
    "done", "failed", "dead_letter", "cancelled",
)
STATUS_TEXT = {
    "proposed": "vorgeschlagen",
    "queued": "wartet",
    "accepted": "angenommen",
    "running": "läuft",
    "review": "in Prüfung",
    "blocked": "blockiert",
    "done": "erledigt",
    "failed": "fehlgeschlagen",
    "dead_letter": "endgültig fehlgeschlagen",
    "cancelled": "abgebrochen",
}


def _jetzt() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _meta(data_state: str, quellen: list[str]) -> dict[str, Any]:
    return {
        "ok": True,
        "data_state": data_state,
        "generated_at": _jetzt(),
        "source_refs": list(dict.fromkeys(q for q in quellen if q)),
    }


def _json_list(roh: Any) -> list[Any]:
    try:
        wert = json.loads(roh or "[]")
    except (TypeError, ValueError):
        return []
    return wert if isinstance(wert, list) else []


def _aufgabe(row: Any, *, mit_profil: bool = False) -> dict[str, Any]:
    daten = {
        "id": int(row["id"]),
        "task_key": row["task_key"],
        "parent_id": row["parent_id"],
        "created_by": row["created_by"],
        "assigned_to": row["assigned_to"],
        "dept": row["dept"],
        "title": row["title"],
        "description": row["description"],
        "task_type": row["task_type"],
        "priority": int(row["priority"]),
        "state": row["state"],
        "state_text": STATUS_TEXT.get(str(row["state"]), str(row["state"])),
        "autonomy_level": int(row["autonomy_level"]),
        "attempts": int(row["attempts"]),
        "max_attempts": int(row["max_attempts"]),
        "due_at": row["due_at"],
        "acceptance": row["acceptance"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
        "error": row["error"],
        "result": row["result"],
        "evidence": _json_list(row["evidence_json"]),
    }
    if mit_profil:
        daten["rufname"] = row["rufname"]
        daten["dept_name"] = row["dept_name"]
    return daten


def _offene_zaehlung(zaehlung: dict[str, int]) -> int:
    return sum(int(zaehlung.get(state, 0)) for state in OFFENE_STATES)


def uebersicht(store: CompanyStore) -> dict[str, Any]:
    """Kennzahlen, Agentenstatus, letzte Konferenz und offene Entscheidungen."""
    db = store.facts
    platzhalter = ",".join("?" for _ in OFFENE_STATES)
    with db.conn() as c:
        profile_gesamt = int(c.execute(
            "SELECT COUNT(*) n FROM agent_profiles").fetchone()["n"])
        profile_aktiv = int(c.execute(
            "SELECT COUNT(*) n FROM agent_profiles WHERE active=1").fetchone()["n"])
        dept_rows = list(c.execute(
            "SELECT dept, dept_name, COUNT(*) n FROM agent_profiles"
            " GROUP BY dept, dept_name ORDER BY dept"))
        status_rows = c.execute(
            f"""
            SELECT
              SUM(CASE WHEN o.offen IS NULL THEN 1 ELSE 0 END) AS frei,
              SUM(CASE WHEN o.offen > 0 AND o.laeuft > 0 THEN 1 ELSE 0 END) AS aktiv,
              SUM(CASE WHEN o.offen > 0 AND o.laeuft = 0 AND o.blockiert > 0
                       THEN 1 ELSE 0 END) AS blockiert,
              SUM(CASE WHEN o.offen > 0 AND o.laeuft = 0 AND o.blockiert = 0
                       THEN 1 ELSE 0 END) AS wartend
            FROM agent_profiles p
            LEFT JOIN (
              SELECT assigned_to,
                SUM(CASE WHEN state='running' THEN 1 ELSE 0 END) AS laeuft,
                SUM(CASE WHEN state='blocked' THEN 1 ELSE 0 END) AS blockiert,
                COUNT(*) AS offen
              FROM agent_tasks
              WHERE state IN ({platzhalter})
              GROUP BY assigned_to
            ) o ON o.assigned_to = p.agent_id
            WHERE p.active=1
            """,
            OFFENE_STATES,
        ).fetchone()
        task_rows = list(c.execute(
            "SELECT state, COUNT(*) n FROM agent_tasks GROUP BY state"))
        dept_task_rows = list(c.execute(
            f"SELECT dept, state, COUNT(*) n FROM agent_tasks"
            f" WHERE state IN ({platzhalter}) GROUP BY dept, state",
            OFFENE_STATES))
        offene_rows = list(c.execute(
            f"""
            SELECT t.*, p.rufname, p.dept_name FROM agent_tasks t
            LEFT JOIN agent_profiles p ON p.agent_id=t.assigned_to
            WHERE t.state IN ({platzhalter})
            ORDER BY t.priority DESC, t.due_at IS NULL, t.due_at, t.id
            LIMIT 10
            """,
            OFFENE_STATES))
        letzte_konferenz = c.execute(
            "SELECT id, scheduled_date, started_at, ended_at, phase, quorum, status"
            " FROM conference_sessions ORDER BY scheduled_date DESC, id DESC LIMIT 1"
        ).fetchone()
        entscheidungen = list(c.execute(
            "SELECT id, level, title, kind, status, owner, deadline, rationale, created_at"
            " FROM company_decisions WHERE status='offen'"
            " ORDER BY deadline IS NULL, deadline, id DESC LIMIT 20"))
        entscheidungen_gesamt = int(c.execute(
            "SELECT COUNT(*) n FROM company_decisions WHERE status='offen'"
        ).fetchone()["n"])

    zaehlung = {state: 0 for state in ALLE_STATES}
    for row in task_rows:
        zaehlung[str(row["state"])] = int(row["n"])
    offen = _offene_zaehlung(zaehlung)

    abteilungen: dict[str, dict[str, Any]] = {}
    for row in dept_rows:
        abteilungen[str(row["dept"])] = {
            "code": row["dept"],
            "name": row["dept_name"],
            "agenten": int(row["n"]),
            "offen": 0,
            "laeuft": 0,
            "blockiert": 0,
        }
    for row in dept_task_rows:
        eintrag = abteilungen.get(str(row["dept"]))
        if eintrag is None:
            continue
        state = str(row["state"])
        anzahl = int(row["n"])
        if state in OFFENE_STATES:
            eintrag["offen"] += anzahl
        if state == "running":
            eintrag["laeuft"] += anzahl
        if state == "blocked":
            eintrag["blockiert"] += anzahl

    status = {
        "aktiv": int(status_rows["aktiv"] or 0),
        "blockiert": int(status_rows["blockiert"] or 0),
        "wartend": int(status_rows["wartend"] or 0),
        "frei": int(status_rows["frei"] or 0),
        "inaktiv": max(0, profile_gesamt - profile_aktiv),
    }
    quellen = ["company:profiles", "company:tasks"]
    konferenz = dict(letzte_konferenz) if letzte_konferenz else None
    if konferenz:
        quellen.append(f"conference:{konferenz['id']}")
    if entscheidungen:
        quellen.extend(f"company:decision:{r['id']}" for r in entscheidungen[:3])

    return {
        **_meta("live" if profile_gesamt else "empty", quellen),
        "profile": {
            "gesamt": profile_gesamt,
            "aktiv": profile_aktiv,
            "inaktiv": status["inaktiv"],
        },
        "agenten_status": status,
        "abteilungen": list(abteilungen.values()),
        "aufgaben": {
            "offen": offen,
            "dead_letter": zaehlung["dead_letter"],
            "nach_status": zaehlung,
        },
        "offene_aufgaben": [_aufgabe(r, mit_profil=True) for r in offene_rows],
        "letzte_konferenz": konferenz,
        "offene_entscheidungen": [dict(r) for r in entscheidungen],
        "offene_entscheidungen_gesamt": entscheidungen_gesamt,
        "letzter_lauf": db.zustand("company_letzter_lauf"),
        "audit_ok": store.audit_chain_ok(),
    }


def agenten(store: CompanyStore) -> dict[str, Any]:
    """Alle Profile mit aktuellem Status, offenen Aufgaben und letzter Aufgabe."""
    db = store.facts
    platzhalter = ",".join("?" for _ in OFFENE_STATES)
    with db.conn() as c:
        profile = list(c.execute(
            "SELECT * FROM agent_profiles ORDER BY dept, agent_id"))
        offene = list(c.execute(
            f"SELECT * FROM agent_tasks WHERE state IN ({platzhalter})"
            " ORDER BY priority DESC, id", OFFENE_STATES))
        letzte = list(c.execute(
            """
            SELECT t.* FROM agent_tasks t
            JOIN (SELECT assigned_to, MAX(id) AS letzte_id
                  FROM agent_tasks GROUP BY assigned_to) m
              ON m.letzte_id = t.id
            """))

    offen_je_agent: dict[str, dict[str, int]] = defaultdict(
        lambda: {"offen": 0, "laeuft": 0, "blockiert": 0})
    for row in offene:
        eintrag = offen_je_agent[str(row["assigned_to"])]
        eintrag["offen"] += 1
        if row["state"] == "running":
            eintrag["laeuft"] += 1
        if row["state"] == "blocked":
            eintrag["blockiert"] += 1
    letzte_je_agent = {str(row["assigned_to"]): row for row in letzte}

    liste: list[dict[str, Any]] = []
    zaehlung = {"laeuft": 0, "blockiert": 0, "wartet": 0, "frei": 0, "inaktiv": 0}
    for row in profile:
        agent_id = str(row["agent_id"])
        aktiv = bool(row["active"])
        aufgaben = offen_je_agent.get(agent_id, {"offen": 0, "laeuft": 0, "blockiert": 0})
        if not aktiv:
            status = "inaktiv"
            status_text = "inaktiv"
        elif aufgaben["laeuft"]:
            status = "laeuft"
            status_text = "läuft"
        elif aufgaben["blockiert"]:
            status = "blockiert"
            status_text = "blockiert"
        elif aufgaben["offen"]:
            status = "wartet"
            status_text = "wartet auf Aufgabe"
        else:
            status = "frei"
            status_text = "frei"
        zaehlung[status] += 1
        letzte_row = letzte_je_agent.get(agent_id)
        letzte_task = _aufgabe(letzte_row) if letzte_row else None
        if letzte_task and len(letzte_task["result"]) > 500:
            letzte_task["result"] = letzte_task["result"][:500] + "…"
        liste.append({
            "agent_id": agent_id,
            "rufname": row["rufname"],
            "dept": row["dept"],
            "dept_name": row["dept_name"],
            "role": row["role"],
            "rank": row["rank"],
            "mission": row["mission"],
            "station": row["station"],
            "avatar": row["avatar"],
            "autonomy": int(row["autonomy"]),
            "active": aktiv,
            "reports_to": row["reports_to"],
            "backup": row["backup"],
            "status": status,
            "status_text": status_text,
            "offene_aufgaben": aufgaben["offen"],
            "davon_laufend": aufgaben["laeuft"],
            "davon_blockiert": aufgaben["blockiert"],
            "letzte_task": letzte_task,
            "quellen": [f"agent:{agent_id}"] + (
                [f"task:{letzte_task['id']}"] if letzte_task else []),
        })

    return {
        **_meta("live" if liste else "empty", ["company:profiles", "company:tasks"]),
        "agenten": liste,
        "gesamt": len(liste),
        "status": zaehlung,
    }


def aufgaben(
    store: CompanyStore,
    *,
    dept: str | None = None,
    state: str | None = None,
    mindestprioritaet: int | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Aufgabenqueue; ohne Statusfilter nur offene Aufgaben."""
    gewaehlt = (state or "offen").strip().lower()
    if gewaehlt == "offen":
        filter_sql = f"t.state IN ({','.join('?' for _ in OFFENE_STATES)})"
        parameter: list[Any] = list(OFFENE_STATES)
    elif gewaehlt == "alle":
        filter_sql = "1=1"
        parameter = []
    elif gewaehlt in ALLE_STATES:
        filter_sql = "t.state=?"
        parameter = [gewaehlt]
    else:
        raise ValueError(f"Unbekannter Status: {state}")

    abteilung = (dept or "").strip().upper()
    if abteilung:
        filter_sql += " AND t.dept=?"
        parameter.append(abteilung)
    if mindestprioritaet is not None:
        minimum = int(mindestprioritaet)
        if minimum < 0 or minimum > 100:
            raise ValueError("mindestprioritaet muss zwischen 0 und 100 liegen")
        filter_sql += " AND t.priority>=?"
        parameter.append(minimum)
    grenze = max(1, min(500, int(limit)))

    with store.facts.conn() as c:
        gesamt = int(c.execute(
            f"SELECT COUNT(*) n FROM agent_tasks t WHERE {filter_sql}",
            parameter).fetchone()["n"])
        rows = list(c.execute(
            f"""
            SELECT t.*, p.rufname, p.dept_name FROM agent_tasks t
            LEFT JOIN agent_profiles p ON p.agent_id=t.assigned_to
            WHERE {filter_sql}
            ORDER BY t.priority DESC, t.due_at IS NULL, t.due_at, t.id
            LIMIT ?
            """,
            [*parameter, grenze]))
        zaehlung = {r["state"]: int(r["n"]) for r in c.execute(
            "SELECT state, COUNT(*) n FROM agent_tasks GROUP BY state")}

    zaehlung_vollstaendig = {state: zaehlung.get(state, 0) for state in ALLE_STATES}
    return {
        **_meta("live" if gesamt else "empty",
                [f"task:{r['id']}" for r in rows[:20]] or ["company:tasks"]),
        "aufgaben": [_aufgabe(r, mit_profil=True) for r in rows],
        "gesamt": gesamt,
        "offen": _offene_zaehlung(zaehlung),
        "zaehlung": zaehlung_vollstaendig,
        "filter": {
            "dept": abteilung or None,
            "state": gewaehlt,
            "mindestprioritaet": mindestprioritaet,
            "limit": grenze,
        },
    }
