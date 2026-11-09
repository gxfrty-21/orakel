"""Policy-Engine: harte Grenzen vor jeder Agentenaktion.

Die Regeln sind Code und Konfiguration, nicht nur ein Prompt. Insbesondere
Paper-only, fehlende freie Shell, keine Secrets und keine Produktionsdeploys
werden hier geprüft.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from ..config import Config
from .roster import Profile


class PolicyError(RuntimeError):
    def __init__(self, grund: str, *, owner_required: bool = False) -> None:
        super().__init__(grund)
        self.grund = grund
        self.owner_required = owner_required


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    grund: str
    owner_required: bool = False


SECRET_MUSTER = re.compile(
    r"(?i)(?:api[_-]?key|secret|passwort|password|token)\s*[:=]\s*[A-Za-z0-9_\-]{8,}"
)
PRIVATE_KEY_MUSTER = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")

RESERVIERTE_AKTIONEN = {
    "change_risk": "Risikogrenzen dürfen nur vom Owner geändert werden",
    "change_auth": "Auth- und Zugriffsregeln dürfen nur vom Owner geändert werden",
    "deploy": "Produktionsdeployment bleibt eine Owner-Entscheidung",
    "spend_money": "Kosten dürfen nicht ohne Owner-Freigabe entstehen",
    "delete_data": "Produktionsdaten dürfen nicht eigenmächtig gelöscht werden",
}


class CompanyPolicy:
    """Prüft Tasks, Aktionen und Ergebnisse gegen die Verfassung."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def paper_only(self) -> bool:
        paper = self.cfg.abschnitt("paper")
        broker = str(paper.get("broker", "csv")).lower()
        freigabe = bool(paper.get("order_freigabe", False))
        return broker in {"csv", "mock", "mt5"} and not freigabe

    def allow_test_suite(self) -> bool:
        return bool(self.cfg.abschnitt("unternehmen").get("allow_tests", False))

    def check_task(self, profile: Profile, task_type: str) -> None:
        if not profile.mission.strip():
            raise PolicyError(f"{profile.agent_id}: Aufgabe fehlt")
        if task_type in {"real_order", "broker_order", "live_order"}:
            raise PolicyError("Echte Broker-Orders sind dauerhaft ausgeschlossen")
        if task_type == "test_suite" and not self.allow_test_suite():
            raise PolicyError(
                "Test-Suite als Agenten-Subprozess ist in Phase 1 deaktiviert"
            )
        if task_type in {"paper_order", "paper_guard"} and not self.paper_only():
            raise PolicyError("Paper-Sperre ist nicht aktiv; autonome Aktion blockiert")

    def check_action(self, action: str, payload: dict[str, Any] | None = None) -> PolicyDecision:
        payload = payload or {}
        if action in {"real_order", "broker_order", "live_order"}:
            return PolicyDecision(False, "Echte Broker-Orders sind verboten")
        if action in {"read_secret", "read_secrets"}:
            return PolicyDecision(False, "Secrets dürfen von Agenten nicht gelesen werden")
        if action in {"shell", "subprocess", "eval"}:
            return PolicyDecision(False, "Freie Shell/Subprozesse sind für Agenten verboten")
        if action in {"network", "http_request"} and not payload.get("allowlisted", False):
            return PolicyDecision(False, "Nur freigegebene Spider-/Datenquellen sind erlaubt")
        if action in RESERVIERTE_AKTIONEN:
            return PolicyDecision(False, RESERVIERTE_AKTIONEN[action], owner_required=True)
        if action in {"write_code", "code_change"}:
            if payload.get("direct") or not payload.get("proposal", False):
                return PolicyDecision(
                    False,
                    "Codeänderungen nur als versionierter Vorschlag mit Tests/Review",
                    owner_required=False,
                )
            return PolicyDecision(True, "Codevorschlag erlaubt; kein direkter Live-Eingriff")
        if action in {"paper_order", "paper_trade"}:
            if not self.paper_only():
                return PolicyDecision(False, "Paper-Sperre ist nicht aktiv")
            return PolicyDecision(True, "Paper-only ist aktiv")
        if action in {"daily_check", "research", "report", "message", "read_company"}:
            return PolicyDecision(True, "Erlaubte operative Aktion")
        return PolicyDecision(False, f"Unbekannte Aktion ohne Allowlist: {action}")

    def require_action(self, action: str, payload: dict[str, Any] | None = None) -> None:
        entscheidung = self.check_action(action, payload)
        if not entscheidung.allowed:
            raise PolicyError(entscheidung.grund, owner_required=entscheidung.owner_required)

    def validate_output(self, text: str, evidence: Sequence[str]) -> None:
        if not text or not text.strip():
            raise PolicyError("Ergebnis ist leer")
        if SECRET_MUSTER.search(text) or PRIVATE_KEY_MUSTER.search(text):
            raise PolicyError("Ergebnis enthält ein mögliches Secret")
        # Ein Ergebnis darf ohne Beleg existieren, muss dann aber als solches
        # sichtbar bleiben; die Runtime markiert das als blockiert, nicht als
        # stillschweigend erfolgreich.
        if not evidence:
            raise PolicyError("Ergebnis ohne Beleg")
