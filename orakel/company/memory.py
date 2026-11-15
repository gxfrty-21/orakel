"""Persönliche Agenten-Gedächtnisse.

Ein Eintrag gehört immer genau einem Agenten. Die Scopes sind frei benannt,
aber auf sichere, kurze Schlüssel begrenzt; der Vault bleibt das gemeinsame
Langzeitgedächtnis. Jede Änderung erzeugt ein Audit-Event, ohne den Wert selbst
im Event zu duplizieren.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .policy import PRIVATE_KEY_MUSTER, SECRET_MUSTER
from .store import CompanyStore

SCOPE_MUSTER = re.compile(r"^[A-Za-z0-9_.:/-]{1,80}$")
KEY_MUSTER = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
MAX_WERT_BYTES = 16_384


class MemoryError(ValueError):
    """Ungültiger Gedächtniseintrag."""


class AgentMemory:
    def __init__(self, store: CompanyStore) -> None:
        self.store = store

    def _profil(self, agent_id: Any) -> dict[str, Any]:
        kennung = str(agent_id or "").strip().upper()
        if not kennung:
            raise MemoryError("Agent fehlt")
        profil = self.store.profil(kennung)
        if not profil:
            raise MemoryError(f"Unbekannter Agent: {kennung}")
        return profil

    @staticmethod
    def _scope(wert: Any) -> str:
        scope = str(wert or "").strip()
        if not scope:
            raise MemoryError("Scope fehlt")
        if not SCOPE_MUSTER.fullmatch(scope):
            raise MemoryError("Scope enthält unzulässige Zeichen")
        return scope

    @staticmethod
    def _key(wert: Any) -> str:
        key = str(wert or "").strip()
        if not key:
            raise MemoryError("Key fehlt")
        if not KEY_MUSTER.fullmatch(key):
            raise MemoryError("Key enthält unzulässige Zeichen")
        return key

    def set(self, agent_id: Any, scope: Any, key: Any, value: Any) -> dict[str, Any]:
        """Legt einen persönlichen Eintrag an oder überschreibt ihn."""
        profil = self._profil(agent_id)
        bereich = self._scope(scope)
        schluessel = self._key(key)
        try:
            roh = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise MemoryError("Wert ist kein gültiges JSON") from exc
        if len(roh.encode("utf-8")) > MAX_WERT_BYTES:
            raise MemoryError(f"Wert ist grösser als {MAX_WERT_BYTES} Bytes")
        if SECRET_MUSTER.search(roh) or PRIVATE_KEY_MUSTER.search(roh):
            raise MemoryError("Gedächtniswert enthält ein mögliches Secret")
        eintrag = self.store.erinnerung_setzen(
            agent_id=str(profil["agent_id"]), scope=bereich, key=schluessel,
            value=value,
        )
        self.store.append_event(str(profil["agent_id"]), None, "memory_set", {
            "scope": bereich,
            "key": schluessel,
            "bytes": len(roh.encode("utf-8")),
        })
        return eintrag or {}

    def get(self, agent_id: Any, scope: Any, key: Any) -> dict[str, Any] | None:
        profil = self._profil(agent_id)
        return self.store.erinnerung(
            str(profil["agent_id"]), self._scope(scope), self._key(key),
        )

    def list(self, agent_id: Any, scope: Any = None,
             limit: int = 200) -> list[dict[str, Any]]:
        profil = self._profil(agent_id)
        bereich = self._scope(scope) if scope not in (None, "") else None
        return self.store.erinnerungen(
            str(profil["agent_id"]), scope=bereich,
            limit=max(1, min(500, int(limit))),
        )

    def delete(self, agent_id: Any, scope: Any, key: Any) -> bool:
        profil = self._profil(agent_id)
        bereich = self._scope(scope)
        schluessel = self._key(key)
        geloescht = self.store.erinnerung_loeschen(
            str(profil["agent_id"]), bereich, schluessel,
        )
        if geloescht:
            self.store.append_event(str(profil["agent_id"]), None, "memory_deleted", {
                "scope": bereich,
                "key": schluessel,
            })
        return geloescht
