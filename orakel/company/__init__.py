"""Unternehmensschicht des Orakel-Raumschiffs.

Phase 1: Profile, Aufgabenqueue, Policy und ein expliziter Company-Lauf.
Noch keine 3D-Welt, keine LLM-Anbindung und keine echten Broker-Orders.
"""

from .roster import PROFILES, Profile, all_profiles, profile_by_id, validate_roster
from .store import CompanyStore
from .policy import CompanyPolicy, PolicyError
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
    "CompanyRuntime",
]
