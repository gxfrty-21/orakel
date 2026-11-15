"""Strukturierte Agentenkommunikation.

Die Zustellung ist bewusst eng: direkte Nachrichten, Abteilungsnachrichten
(nur Leitung/Sekretariat) und Broadcasts (nur A1/S1–S3). Jede Nachricht landet
in SQLite und wird mit einem Audit-Event versehen; es gibt keinen freien
Netzwerk- oder Shell-Kanal.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from .policy import PRIVATE_KEY_MUSTER, SECRET_MUSTER
from .store import CompanyStore

KINDS = frozenset({
    "task_request", "task_result", "question", "answer", "handoff",
    "review_request", "review_result", "alert", "decision", "status",
})
PRIORITIES = frozenset({"niedrig", "normal", "hoch", "dringend"})
BROADCAST_AGENTS = frozenset({"A1", "S1", "S2", "S3"})
MAX_SUBJECT = 200
MAX_BODY = 8000
MAX_EVIDENCE = 50
MAX_EVIDENCE_LAENGE = 200
THREAD_MUSTER = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


class MessageError(ValueError):
    """Ungültiger Nachrichtenentwurf oder unzulässiger Empfänger."""


def _text(wert: Any, feld: str, *, max_laenge: int) -> str:
    text = str(wert or "").strip()
    if not text:
        raise MessageError(f"{feld} darf nicht leer sein")
    if len(text) > max_laenge:
        raise MessageError(f"{feld} ist länger als {max_laenge} Zeichen")
    return text


def _zeitpunkt(wert: Any) -> str | None:
    if wert in (None, ""):
        return None
    try:
        zeit = datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except ValueError as exc:
        raise MessageError("expires_at muss ein ISO-8601-Zeitpunkt sein") from exc
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    if zeit <= datetime.now(timezone.utc):
        raise MessageError("expires_at muss in der Zukunft liegen")
    return zeit.astimezone(timezone.utc).replace(microsecond=0).isoformat()


class MessagingService:
    """Validiert und speichert Agentennachrichten."""

    def __init__(self, store: CompanyStore) -> None:
        self.store = store

    def _profil(self, agent_id: Any) -> dict[str, Any]:
        kennung = str(agent_id or "").strip().upper()
        if not kennung:
            raise MessageError("Absender oder Empfänger fehlt")
        profil = self.store.profil(kennung)
        if not profil:
            raise MessageError(f"Unbekannter Agent: {kennung}")
        if not bool(profil["active"]):
            raise MessageError(f"Agent ist nicht aktiv: {kennung}")
        return profil

    def _empfaenger(self, sender: dict[str, Any], ziel: Any) -> list[str]:
        roh = str(ziel or "").strip()
        if not roh:
            raise MessageError("Empfänger fehlt")
        normal = roh.lower()
        if normal in {"all", "alle", "broadcast"}:
            if sender["agent_id"] not in BROADCAST_AGENTS:
                raise MessageError("Broadcast ist nur A1 oder S1–S3 erlaubt")
            return [str(p["agent_id"]) for p in self.store.profile_alle() if p["active"]]
        if normal.startswith("dept:"):
            code = roh.split(":", 1)[1].strip().upper()
            if not code:
                raise MessageError("Abteilung fehlt")
            if sender["rank"] != "sekretariat" and sender["dept"] != code:
                raise MessageError("Abteilungsnachricht nur für die eigene Abteilung")
            if sender["rank"] not in {"leitung", "sekretariat"}:
                raise MessageError("Abteilungsnachricht nur Leitung oder Sekretariat erlaubt")
            empfaenger = [
                str(p["agent_id"]) for p in self.store.profile_alle()
                if p["active"] and str(p["dept"]) == code
            ]
            if not empfaenger:
                raise MessageError(f"Unbekannte oder leere Abteilung: {code}")
            return empfaenger
        ziel_profil = self._profil(roh)
        if ziel_profil["agent_id"] == sender["agent_id"]:
            raise MessageError("Ein Agent kann sich nicht selbst adressieren")
        return [str(ziel_profil["agent_id"])]

    def send(
        self,
        *,
        sender: Any,
        recipient: Any,
        subject: Any,
        body: Any,
        kind: str = "status",
        evidence: Sequence[Any] = (),
        requires_ack: bool = False,
        priority: str = "normal",
        thread_id: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Speichert eine direkte, Abteilungs- oder Broadcast-Nachricht."""
        von = self._profil(sender)
        ziel = self._empfaenger(von, recipient)
        art = str(kind or "").strip().lower()
        if art not in KINDS:
            raise MessageError(f"Unbekannte Nachrichtenart: {art}")
        prio = str(priority or "normal").strip().lower()
        if prio not in PRIORITIES:
            raise MessageError(f"Unbekannte Priorität: {prio}")
        betreff = _text(subject, "Betreff", max_laenge=MAX_SUBJECT)
        inhalt = _text(body, "Inhalt", max_laenge=MAX_BODY)
        for wert in (betreff, inhalt):
            if SECRET_MUSTER.search(wert) or PRIVATE_KEY_MUSTER.search(wert):
                raise MessageError("Nachricht enthält ein mögliches Secret")

        if isinstance(evidence, str) or not isinstance(evidence, Sequence):
            raise MessageError("evidence muss eine Liste sein")
        belege: list[str] = []
        for beleg in evidence:
            text = str(beleg or "").strip()
            if not text or len(text) > MAX_EVIDENCE_LAENGE:
                raise MessageError("Ungültiger Evidence-Eintrag")
            belege.append(text)
        if len(belege) > MAX_EVIDENCE:
            raise MessageError(f"Zu viele Evidence-Einträge (max. {MAX_EVIDENCE})")

        if thread_id:
            thread = str(thread_id).strip()
            if not THREAD_MUSTER.fullmatch(thread):
                raise MessageError("Ungültige thread_id")
        else:
            thread = "thr_" + uuid.uuid4().hex[:16]
        ablauf = _zeitpunkt(expires_at)

        ids: list[int] = []
        for empf in ziel:
            ids.append(self.store.nachricht_speichern(
                thread_id=thread,
                from_agent=str(von["agent_id"]),
                to_agent=empf,
                kind=art,
                subject=betreff,
                body=inhalt,
                evidence=belege,
                requires_ack=bool(requires_ack),
                priority=prio,
                expires_at=ablauf,
            ))
        self.store.append_event(str(von["agent_id"]), None, "message_sent", {
            "thread_id": thread,
            "to_agents": ziel,
            "message_ids": ids,
            "kind": art,
            "requires_ack": bool(requires_ack),
        })
        nachrichten = [self.store.nachricht(i) for i in ids]
        return {
            "thread_id": thread,
            "message_ids": ids,
            "to_agents": ziel,
            "messages": [dict(n) for n in nachrichten if n],
        }

    def ack(self, message_id: int, agent_id: Any) -> dict[str, Any]:
        """Bestätigt eine Nachricht ausschliesslich für ihren Empfänger."""
        agent = self._profil(agent_id)
        try:
            kennung = int(message_id)
        except (TypeError, ValueError) as exc:
            raise MessageError("Ungültige Nachrichten-ID") from exc
        nachricht = self.store.nachricht(kennung)
        if not nachricht:
            raise MessageError("Nachricht nicht gefunden")
        if str(nachricht["to_agent"]) != str(agent["agent_id"]):
            raise MessageError("Nur der Empfänger darf diese Nachricht bestätigen")
        if not nachricht["ack_at"]:
            if nachricht["expires_at"]:
                ablauf = datetime.fromisoformat(str(nachricht["expires_at"]).replace("Z", "+00:00"))
                if ablauf.tzinfo is None:
                    ablauf = ablauf.replace(tzinfo=timezone.utc)
                if ablauf <= datetime.now(timezone.utc):
                    raise MessageError("Nachricht ist abgelaufen")
            self.store.nachricht_quittieren(kennung, str(agent["agent_id"]))
            self.store.append_event(str(agent["agent_id"]), None, "message_ack", {
                "message_id": kennung,
                "thread_id": nachricht["thread_id"],
            })
            nachricht = self.store.nachricht(kennung)
        return dict(nachricht or {})

    def inbox(self, agent_id: Any, *, nur_offen: bool = True,
              limit: int = 100) -> list[dict[str, Any]]:
        agent = self._profil(agent_id)
        return self.store.nachrichten_gefiltert(
            agent=str(agent["agent_id"]), nur_offen=nur_offen,
            limit=max(1, min(500, int(limit))),
        )
