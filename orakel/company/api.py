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


def _json_obj(roh: Any) -> dict[str, Any]:
    try:
        wert = json.loads(roh or "{}")
    except (TypeError, ValueError):
        return {}
    return wert if isinstance(wert, dict) else {}


def _status_profil(aktiv: bool, offen: int, laeuft: int, blockiert: int) -> tuple[str, str]:
    if not aktiv:
        return "inaktiv", "inaktiv"
    if laeuft:
        return "laeuft", "läuft"
    if blockiert:
        return "blockiert", "blockiert"
    if offen:
        return "wartet", "wartet auf Aufgabe"
    return "frei", "frei"


def _profil(row: Any) -> dict[str, Any]:
    return {
        "agent_id": row["agent_id"],
        "rufname": row["rufname"],
        "dept": row["dept"],
        "dept_name": row["dept_name"],
        "role": row["role"],
        "rank": row["rank"],
        "mission": row["mission"],
        "station": row["station"],
        "avatar": row["avatar"],
        "autonomy": int(row["autonomy"]),
        "active": bool(row["active"]),
        "reports_to": row["reports_to"],
        "backup": row["backup"],
        "data_scope": _json_list(row["data_scope_json"]),
        "tools": _json_list(row["tools_json"]),
        "memory_scope": row["memory_scope"],
        "kpi": row["kpi"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _nachricht(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "thread_id": row["thread_id"],
        "from_agent": row["from_agent"],
        "to_agent": row["to_agent"],
        "from_rufname": row["from_rufname"] if "from_rufname" in row.keys() else None,
        "from_dept": row["from_dept"] if "from_dept" in row.keys() else None,
        "to_rufname": row["to_rufname"] if "to_rufname" in row.keys() else None,
        "to_dept": row["to_dept"] if "to_dept" in row.keys() else None,
        "kind": row["kind"],
        "priority": row["priority"],
        "subject": row["subject"],
        "body": row["body"],
        "evidence": _json_list(row["evidence_json"]),
        "requires_ack": bool(row["requires_ack"]),
        "ack_at": row["ack_at"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }


def nachricht(store: CompanyStore, message_id: int) -> dict[str, Any] | None:
    """Eine einzelne Nachricht im API-Format."""
    row = store.nachricht(int(message_id))
    if row is None:
        return None
    return {
        **_meta("live", [f"message:{int(message_id)}"]),
        "nachricht": _nachricht(row),
    }


def agent_detail(store: CompanyStore, agent_id: str) -> dict[str, Any] | None:
    """Profil, aktuelle Aufgabe, Historie und Nachrichten eines Agenten."""
    kennung = (agent_id or "").strip().upper()
    row = store.profil(kennung)
    if not row:
        return None
    aufgaben = store.tasks_fuer_agent(kennung, limit=50)
    nachrichten = store.nachrichten_fuer_agent(kennung, limit=25)
    erinnerungen = store.erinnerungen(kennung, limit=50)
    offene = [t for t in aufgaben if t["state"] in OFFENE_STATES]
    laufend = [t for t in offene if t["state"] == "running"]
    blockiert = [t for t in offene if t["state"] == "blocked"]
    aktuell = ([max(laufend, key=lambda t: (int(t["priority"]), int(t["id"])))]
               if laufend else
               [max(offene, key=lambda t: (int(t["priority"]), int(t["id"])))]
               if offene else [])
    status, status_text = _status_profil(bool(row["active"]), len(offene),
                                        len(laufend), len(blockiert))
    quellen = [f"agent:{kennung}"]
    quellen.extend(f"task:{t['id']}" for t in aufgaben[:20])
    quellen.extend(f"message:{m['id']}" for m in nachrichten[:10])
    quellen.extend(f"memory:{e['scope']}:{e['key']}" for e in erinnerungen[:10])
    return {
        **_meta("live", quellen),
        "profil": _profil(row),
        "status": status,
        "status_text": status_text,
        "offene_aufgaben": [_aufgabe(t) for t in offene],
        "aktuelle_aufgabe": _aufgabe(aktuell[0]) if aktuell else None,
        "historie": [_aufgabe(t) for t in aufgaben],
        "nachrichten": [_nachricht(m) for m in nachrichten],
        "erinnerungen": erinnerungen,
        "zaehlung": {
            "offen": len(offene),
            "laeuft": len(laufend),
            "blockiert": len(blockiert),
        },
    }


def erinnerungen(store: CompanyStore, agent_id: str,
                 *, scope: str | None = None, limit: int = 200) -> dict[str, Any] | None:
    """Persönliche Erinnerungen eines Agenten, getrennt nach Scope."""
    kennung = (agent_id or "").strip().upper()
    if not store.profil(kennung):
        return None
    bereich = (scope or "").strip() or None
    eintraege = store.erinnerungen(kennung, scope=bereich,
                                   limit=max(1, min(500, int(limit))))
    return {
        **_meta("live" if eintraege else "empty",
                [f"memory:{e['scope']}:{e['key']}" for e in eintraege[:20]]
                or [f"memory:{kennung}"]),
        "agent_id": kennung,
        "erinnerungen": eintraege,
        "gesamt": len(eintraege),
        "filter": {"scope": bereich, "limit": max(1, min(500, int(limit)))},
    }


def nachrichten(
    store: CompanyStore,
    *,
    agent: str | None = None,
    dept: str | None = None,
    thread_id: str | None = None,
    seit: str | None = None,
    nur_offen: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Nachrichten und Threads, filterbar nach Agent, Abteilung und Zeitpunkt."""
    kennung = (agent or "").strip().upper() or None
    abteilung = (dept or "").strip().upper() or None
    thread = (thread_id or "").strip() or None
    grenze = max(1, min(500, int(limit)))
    seit_iso = None
    if seit:
        try:
            zeit = datetime.fromisoformat(seit.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("seit muss ein ISO-8601-Zeitpunkt sein") from exc
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        seit_iso = zeit.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    rows = store.nachrichten_gefiltert(agent=kennung, dept=abteilung,
                                       thread_id=thread, seit=seit_iso,
                                       nur_offen=nur_offen, limit=grenze)
    liste = [_nachricht(r) for r in rows]
    threads: dict[str, dict[str, Any]] = {}
    for nachricht in liste:
        eintrag = threads.setdefault(nachricht["thread_id"], {
            "thread_id": nachricht["thread_id"],
            "anzahl": 0,
            "letzte": nachricht["created_at"],
            "teilnehmer": set(),
        })
        eintrag["anzahl"] += 1
        if nachricht["created_at"] > eintrag["letzte"]:
            eintrag["letzte"] = nachricht["created_at"]
        eintrag["teilnehmer"].update([nachricht["from_agent"], nachricht["to_agent"]])
    thread_liste = []
    for eintrag in threads.values():
        thread_liste.append({**eintrag, "teilnehmer": sorted(eintrag["teilnehmer"])})
    thread_liste.sort(key=lambda t: (t["letzte"], t["thread_id"]), reverse=True)

    return {
        **_meta("live" if liste else "empty", [f"message:{m['id']}" for m in liste[:20]]
                or ["company:messages"]),
        "nachrichten": liste,
        "threads": thread_liste,
        "gesamt": len(liste),
        "filter": {
            "agent": kennung,
            "dept": abteilung,
            "thread_id": thread,
            "seit": seit_iso,
            "nur_offen": nur_offen,
            "limit": grenze,
        },
    }


def _konferenz_leer() -> dict[str, Any]:
    return {
        **_meta("empty", ["company:conference"]),
        "konferenz": None,
        "teilnahme": [],
        "beitraege": [],
        "abstimmungen": [],
        "entscheidungen": [],
        "massnahmen": [],
    }


def konferenz(store: CompanyStore) -> dict[str, Any]:
    """Letzte Konferenz mit Teilnahme, Beiträgen, Abstimmungen und Massnahmen."""
    with store.facts.conn() as c:
        session = c.execute(
            "SELECT * FROM conference_sessions ORDER BY scheduled_date DESC, id DESC LIMIT 1"
        ).fetchone()
        if not session:
            return _konferenz_leer()
        session_id = int(session["id"])
        teilnahme = list(c.execute(
            """
            SELECT a.*, p.rufname, p.dept, p.dept_name
            FROM conference_attendance a
            LEFT JOIN agent_profiles p ON p.agent_id=a.agent_id
            WHERE a.session_id=? ORDER BY a.role, a.agent_id
            """, (session_id,)))
        beitraege = list(c.execute(
            """
            SELECT s.*, p.rufname, p.dept, p.dept_name
            FROM conference_statements s
            LEFT JOIN agent_profiles p ON p.agent_id=s.agent_id
            WHERE s.session_id=? ORDER BY s.id
            """, (session_id,)))
        abstimmungen = list(c.execute(
            """
            SELECT v.*, d.title AS decision_title, d.status AS decision_status
            FROM conference_votes v
            LEFT JOIN company_decisions d ON d.id=v.decision_id
            WHERE v.session_id=? ORDER BY v.id
            """, (session_id,)))
        entscheidungen = list(c.execute(
            "SELECT * FROM company_decisions WHERE session_id=? ORDER BY id",
            (session_id,)))
        massnahmen = list(c.execute(
            """
            SELECT a.*, d.title AS decision_title
            FROM company_actions a
            LEFT JOIN company_decisions d ON d.id=a.decision_id
            WHERE d.session_id=? ORDER BY a.id
            """, (session_id,)))

    daten = dict(session)
    daten["protocol"] = _json_obj(daten.pop("protocol_json", None))
    quellen = [f"conference:{session_id}"]
    quellen.extend(f"decision:{r['id']}" for r in entscheidungen)
    quellen.extend(f"action:{r['id']}" for r in massnahmen)
    return {
        **_meta("live", quellen),
        "konferenz": daten,
        "teilnahme": [{
            **dict(r), "present": bool(r["present"]),
        } for r in teilnahme],
        "beitraege": [{
            **dict(r), "evidence": _json_list(r["evidence_json"]),
        } for r in beitraege],
        "abstimmungen": [dict(r) for r in abstimmungen],
        "entscheidungen": [{
            **dict(r), "evidence": _json_list(r["evidence_json"]),
        } for r in entscheidungen],
        "massnahmen": [dict(r) for r in massnahmen],
    }


def raeume(store: CompanyStore) -> dict[str, Any]:
    """2D-Raumregister: Abteilungen, Gemeinschaftsräume und Agentenräume."""
    profile = store.profile_alle()
    if not profile:
        return {
            **_meta("empty", ["company:profiles", "company:tasks"]),
            "abteilungen": [], "gemeinschaftsraeume": [],
            "agentenraeume": [], "dynamischer_status": [],
            "gesamt": {"abteilungen": 0, "gemeinschaftsraeume": 0, "agentenraeume": 0},
        }
    platzhalter = ",".join("?" for _ in OFFENE_STATES)
    with store.facts.conn() as c:
        aufgaben = list(c.execute(
            f"SELECT * FROM agent_tasks WHERE state IN ({platzhalter})", OFFENE_STATES))
        status_rows = list(c.execute("SELECT * FROM room_state ORDER BY room_id"))
        letzte_konferenz = c.execute(
            "SELECT id, scheduled_date, phase, status FROM conference_sessions"
            " ORDER BY scheduled_date DESC, id DESC LIMIT 1"
        ).fetchone()

    offen_je_agent: dict[str, dict[str, int]] = defaultdict(
        lambda: {"offen": 0, "laeuft": 0, "blockiert": 0})
    task_je_agent: dict[str, Any] = {}
    for task in aufgaben:
        agent_id = str(task["assigned_to"])
        zaehler = offen_je_agent[agent_id]
        zaehler["offen"] += 1
        if task["state"] == "running":
            zaehler["laeuft"] += 1
        if task["state"] == "blocked":
            zaehler["blockiert"] += 1
        bisher = task_je_agent.get(agent_id)
        if (bisher is None
                or (task["state"] == "running" and bisher["state"] != "running")
                or (task["state"] == bisher["state"]
                    and int(task["priority"]) > int(bisher["priority"]))):
            task_je_agent[agent_id] = task

    depts: dict[str, dict[str, Any]] = {}
    agentenraeume = []
    for p in profile:
        agent_id = str(p["agent_id"])
        zaehler = offen_je_agent.get(agent_id, {"offen": 0, "laeuft": 0, "blockiert": 0})
        status, status_text = _status_profil(
            bool(p["active"]), zaehler["offen"], zaehler["laeuft"], zaehler["blockiert"])
        task = task_je_agent.get(agent_id)
        d = depts.setdefault(str(p["dept"]), {
            "room_id": f"dept:{p['dept']}", "typ": "abteilung", "code": p["dept"],
            "name": p["dept_name"], "agenten": 0, "offene_aufgaben": 0,
            "laeuft": 0, "blockiert": 0,
        })
        d["agenten"] += 1
        d["offene_aufgaben"] += zaehler["offen"]
        d["laeuft"] += zaehler["laeuft"]
        d["blockiert"] += zaehler["blockiert"]
        agentenraeume.append({
            "room_id": f"agent:{agent_id}", "typ": "agent", "agent_id": agent_id,
            "station_id": p["station"], "name": p["rufname"], "dept": p["dept"],
            "dept_name": p["dept_name"], "status": status, "status_text": status_text,
            "offene_aufgaben": zaehler["offen"], "laeuft": zaehler["laeuft"],
            "blockiert": zaehler["blockiert"],
            "task_id": int(task["id"]) if task else None,
            "task_title": task["title"] if task else None,
        })

    for d in depts.values():
        d["status"], d["status_text"] = _status_profil(
            True, int(d["offene_aufgaben"]), int(d["laeuft"]), int(d["blockiert"]))

    gemeinschaft = [{
        "room_id": "common:agents", "typ": "gemeinschaft", "name": "Agentenraum",
        "agenten": len(profile), "status": "live", "status_text": "live",
    }]
    if letzte_konferenz:
        gemeinschaft.append({
            "room_id": "common:conference", "typ": "gemeinschaft", "name": "Konferenz",
            "session_id": int(letzte_konferenz["id"]),
            "scheduled_date": letzte_konferenz["scheduled_date"],
            "phase": letzte_konferenz["phase"], "status": letzte_konferenz["status"],
            "status_text": letzte_konferenz["status"],
        })

    quellen = ["company:profiles", "company:tasks"]
    if letzte_konferenz:
        quellen.append(f"conference:{letzte_konferenz['id']}")
    quellen.extend(f"room_state:{r['room_id']}" for r in status_rows)
    return {
        **_meta("live", quellen),
        "abteilungen": list(depts.values()),
        "gemeinschaftsraeume": gemeinschaft,
        "agentenraeume": agentenraeume,
        "dynamischer_status": [dict(r) for r in status_rows],
        "gesamt": {
            "abteilungen": len(depts), "gemeinschaftsraeume": len(gemeinschaft),
            "agentenraeume": len(agentenraeume),
        },
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
