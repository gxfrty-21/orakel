"""Unternehmensschicht des Orakel-Raumschiffs.

Phase 1: Profile, Aufgabenqueue, Policy und ein expliziter Company-Lauf.
Noch keine 3D-Welt, keine LLM-Anbindung und keine echten Broker-Orders.
"""

from .roster import PROFILES, Profile, all_profiles, profile_by_id, validate_roster
from .store import CompanyStore
from .policy import CompanyPolicy, PolicyError
from .messaging import MessageError, MessageRateLimitError, MessagingService
from .memory import AgentMemory, MemoryError
from .runtime import CompanyRuntime

__all__ = [
    "PROFILES",
    "Profile",
    "all_profiles",
    "profile_by_id",
    "validate_roster",
    "CompanyStore",
    "CompanyPolicy",
    "PolicyError",
    "MessagingService",
    "MessageError",
    "MessageRateLimitError",
    "AgentMemory",
    "MemoryError",
    "CompanyRuntime",
]
