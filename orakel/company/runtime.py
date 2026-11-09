"""Company-Runtime für Phase 1.

Der Lauf erzeugt für jeden der 103 Agenten eine idempotente Tagesaufgabe,
verarbeitet sie mit einem kleinen Workerpool und schreibt Ergebnis sowie
Audit-Event. Es gibt keinen LLM-Aufruf und keine Broker-Order.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..config import Config, RisikoGrenzen
from ..db import Facts
from .handlers import HandlerResult, run_handler
from .policy import CompanyPolicy, PolicyError
from .roster import Profile, PROFILES, profile_by_id
from .store import CompanyStore

# Spezielle Task-Typen. Alle anderen Rollen laufen als daily_check.
TASK_TYPES = {
    "A5": "paper_guard",
    "H3": "test_suite",
    "I7": "correlation",
    "J3": "data_integrity",
    "J5": "secret_audit",
    "J7": "event_chain",
    "J8": "tool_guard",
    "J9": "paper_guard",
    "S1": "briefing",
    "S2": "briefing",
    "S3": "briefing",
}

PRIORITAETEN = {
    "A5": 95, "J9": 95,
    "F1": 90, "F10": 90, "J1": 88, "J2": 88, "J3": 88, "J4": 88,
    "J5": 88, "J6": 88, "J7": 88, "J8": 88, "J10": 86,
    "A1": 80, "A2": 80, "S1": 75, "S2": 70, "S3": 70,
}


class CompanyRuntime:
    def __init__(
        self,
        cfg: Config,
        db: Facts,
        *,
        store: CompanyStore | None = None,
        policy: CompanyPolicy | None = None,
        max_workers: int | None = None,
    ) -> None:
        self.cfg = cfg
        self.db = db
        self.store = store or CompanyStore(db)
        self.policy = policy or CompanyPolicy(cfg)
        konfiguriert = int(cfg.abschnitt("unternehmen").get("max_worker", 4))
        self.max_workers = max(1, min(6, int(max_workers or konfiguriert)))
        self._limit_lock = threading.Lock()
        self._verarbeitet = 0

    # ---------- Kontext für bestehende und neue Handler ----------
    def _validierungen(self) -> list[dict[str, Any]]:
        lauf = self.db.zustand("letzter_lauf_id")
        raus: list[dict[str, Any]] = []
        for r in self.db.letzte_validierungen(lauf):
            try:
                bericht = json.loads(r["bericht"])
            except Exception:
                bericht = {}
            bericht.update({
                "symbol": r["symbol"], "strategie": r["strategie"],
                "urteil": r["urteil"], "parameter": json.loads(r["parameter"]),
                "beschreibung": r["beschreibung"], "schluessel": r["schluessel"],
            })
            raus.append(bericht)
        return raus

    def kontext(self) -> dict[str, Any]:
        letztes = self.db.letztes_konto()
        equity = float(letztes["equity"]) if letztes else self.cfg.start_kapital
        hoechst = float(letztes["hoechststand"]) if letztes else self.cfg.start_kapital
        dd = (hoechst - equity) / hoechst * 100 if hoechst else 0.0
        return {
            "cfg": self.cfg,
            "db": self.db,
            "store": self.store,
            "policy": self.policy,
            "grenzen": RisikoGrenzen.aus_config(self.cfg),
            "validierungen": self._validierungen(),
            "qualitaet": [],
            "konto": {
                "equity": equity,
                "positionen": len(self.db.positionen()),
                "drawdown_pct": round(dd, 2),
            },
            "plan": [],
            "modus": "paper",
            "bericht": {},
        }

    # ---------- Tagesaufgaben ----------
    def seed_daily_tasks(self, tag: str | None = None) -> list[int]:
        tag = tag or datetime.now(
            ZoneInfo(self.cfg["basis"].get("zeitzone", "Europe/Zurich"))
        ).date().isoformat()
        self.store.sync_roster(PROFILES)
        self.store.policy_seed()
        budget = int(self.store.policy("max_tasks_pro_tag", 250))
        ids: list[int] = []
        for p in PROFILES:
            if len(ids) >= budget:
                break
            task_type = TASK_TYPES.get(p.agent_id, "daily_check")
            task_id = self.store.enqueue(
                task_key=f"daily:{tag}:{p.agent_id}",
                assigned_to=p.agent_id,
                dept=p.dept,
                title=p.role,
                description=p.mission,
                task_type=task_type,
                priority=PRIORITAETEN.get(p.agent_id, 50),
                autonomy_level=p.autonomy,
                acceptance="Ergebnis nicht leer; Beleg oder klarer Datenmangel; keine echte Order.",
                input_data={"tag": tag, "phase": 1, "paper_only": True},
                due_at=(datetime.now(timezone.utc) + timedelta(hours=24)).replace(
                    microsecond=0).isoformat(),
            )
            ids.append(task_id)
        return ids

    # ---------- Worker ----------
    def _claim(self, worker: str, max_tasks: int | None) -> dict[str, Any] | None:
        with self._limit_lock:
            if max_tasks is not None and self._verarbeitet >= max_tasks:
                return None
            self._verarbeitet += 1
        task = self.store.claim_next(worker)
        if task is None:
            with self._limit_lock:
                self._verarbeitet -= 1
        return task

    def _execute(self, task: dict[str, Any], ctx: dict[str, Any]) -> str:
        profile = profile_by_id(str(task["assigned_to"]))
        if profile is None:
            self.store.block(int(task["id"]), "Profil fehlt", ("company:profiles",))
            return "blocked"
        try:
            self.policy.check_task(profile, str(task["task_type"]))
        except PolicyError as exc:
            self.store.block(int(task["id"]), exc.grund, ("policy:task",))
            self.db.agenten_lauf(
                f"{profile.agent_id}:{profile.role}", profile.dept, profile.mission,
                f"blockiert: {exc.grund}", False,
            )
            return "blocked"

        try:
            ergebnis: HandlerResult = run_handler(profile, ctx)
        except Exception as exc:
            neu = self.store.fail(int(task["id"]), f"Handler-Ausnahme: {exc}")
            self.db.agenten_lauf(
                f"{profile.agent_id}:{profile.role}", profile.dept, profile.mission,
                f"Fehler: {exc}", False,
            )
            return "dead_letter" if neu == "dead_letter" else "failed"

        evidence = list(ergebnis.evidence) + [f"task:{task['id']}"]
        if ergebnis.ok:
            try:
                self.policy.validate_output(ergebnis.text, evidence)
            except PolicyError as exc:
                self.store.block(int(task["id"]), exc.grund, evidence)
                self.db.agenten_lauf(
                    f"{profile.agent_id}:{profile.role}", profile.dept, profile.mission,
                    f"blockiert: {exc.grund}", False,
                )
                return "blocked"
            self.store.complete(
                int(task["id"]),
                result=ergebnis.text,
                evidence=evidence,
                output={
                    "agent_id": profile.agent_id,
                    "rufname": profile.rufname,
                    "dept": profile.dept,
                    "handler": profile.handler,
                    "task_type": task["task_type"],
                    "summary": ergebnis.text,
                    "ok": True,
                },
                reviewed_by="policy",
            )
            self.db.agenten_lauf(
                f"{profile.agent_id}:{profile.role}", profile.dept, profile.mission,
                ergebnis.text, True,
            )
            return "done"

        if ergebnis.blocked:
            self.store.block(int(task["id"]), ergebnis.text, evidence)
            self.db.agenten_lauf(
                f"{profile.agent_id}:{profile.role}", profile.dept, profile.mission,
                f"blockiert: {ergebnis.text}", False,
            )
            return "blocked"

        neu = self.store.fail(int(task["id"]), ergebnis.text)
        self.db.agenten_lauf(
            f"{profile.agent_id}:{profile.role}", profile.dept, profile.mission,
            f"Fehler: {ergebnis.text}", False,
        )
        return "dead_letter" if neu == "dead_letter" else "failed"

    def run(self, *, tag: str | None = None, max_tasks: int | None = None) -> dict[str, Any]:
        start = time.monotonic()
        self.store.sync_roster(PROFILES)
        self.store.policy_seed()
        self.store.recover_expired()
        ids = self.seed_daily_tasks(tag)
        ctx = self.kontext()
        with self._limit_lock:
            self._verarbeitet = 0
        with ThreadPoolExecutor(max_workers=self.max_workers,
                                thread_name_prefix="orakel-company") as pool:
            futures = [
                pool.submit(self._worker, f"worker-{i + 1}", max_tasks, ctx)
                for i in range(self.max_workers)
            ]
            for future in futures:
                future.result()
        states = self.store.task_counts()
        terminal = sum(n for state, n in states.items()
                       if state in {"done", "blocked", "dead_letter", "failed", "cancelled"})
        summary = {
            "tag": tag or datetime.now(
                ZoneInfo(self.cfg["basis"].get("zeitzone", "Europe/Zurich"))
            ).date().isoformat(),
            "profile": self.store.profile_anzahl(),
            "tasks_erzeugt": len(ids),
            # Abgeschlossene Tasks, nicht Claim-Versuche. Retries werden separat
            # ausgewiesen, damit 103 Aufgaben nicht als 105 erscheinen.
            "tasks_verarbeitet": terminal,
            "task_versuche": self._verarbeitet,
            "states": states,
            "audit_ok": self.store.audit_chain_ok(),
            "paper_only": self.policy.paper_only(),
            "dauer_sekunden": round(time.monotonic() - start, 3),
        }
        self.db.zustand_setzen("company_letzter_lauf", summary)
        return summary

    def _worker(self, worker: str, max_tasks: int | None, ctx: dict[str, Any]) -> None:
        while True:
            task = self._claim(worker, max_tasks)
            if task is None:
                return
            try:
                self._execute(task, ctx)
            except Exception as exc:
                # Ein einzelner kaputter Handler darf die anderen 102 nicht stoppen.
                try:
                    self.store.fail(int(task["id"]), f"Runtime-Fehler: {exc}")
                except Exception:
                    pass
