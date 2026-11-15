"""Strukturierte Agentenkommunikation.

Die Zustellung ist bewusst eng: direkte Nachrichten, Abteilungsnachrichten
(nur Leitung/Sekretariat) und Broadcasts (nur A1/S1–S3). Jede Nachricht landet
in SQLite und wird mit einem Audit-Event versehen; es gibt keinen freien
Netzwerk- oder Shell-Kanal.
"""

from __future__ import annotations

import json
import math
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
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

# Ein Broadcast ist an alle aktiven Profile adressiert. Ältere Audit-Events
# tragen noch kein explizites Merkmal; ab dieser Empfängerzahl werden sie als
# Broadcast erkannt. Abteilungen haben derzeit höchstens zehn Mitglieder.
BROADCAST_MIN_EMPFAENGER = 20
BROADCAST_COOLDOWN_SEKUNDEN = 900
BROADCAST_MAX_PRO_TAG = 10
ACK_ERINNERUNG_NACH_MINUTEN = 30
ACK_ERINNERUNG_WIEDERHOLEN_MINUTEN = 120
ACK_ERINNERUNGEN_MAX = 1

# Der Lock verhindert, dass zwei parallele HTTP-Anfragen im selben Prozess
# gleichzeitig am Limit vorbeikommen. Die Historie bleibt in SQLite persistent.
_BROADCAST_LOCK = threading.RLock()
_REMINDER_LOCK = threading.RLock()


class MessageError(ValueError):
    """Ungültiger Nachrichtenentwurf oder unzulässiger Empfänger."""


class MessageRateLimitError(MessageError):
    """Ein Broadcast wurde durch das persistente Rate-Limit abgelehnt."""

    def __init__(self, grund: str, *, retry_after: int = 0, limit: str = "") -> None:
        super().__init__(grund)
        self.retry_after = max(0, int(retry_after))
        self.limit = limit


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


def _zeit_lesen(wert: Any) -> datetime | None:
    try:
        zeit = datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.astimezone(timezone.utc)


def _policy_int(store: CompanyStore, key: str, standard: int) -> int:
    try:
        return max(0, int(store.policy(key, standard)))
    except (TypeError, ValueError):
        return max(0, int(standard))


def _ist_broadcast_event(payload: dict[str, Any]) -> bool:
    if payload.get("broadcast") is True:
        return True
    # Rückwärtskompatibel: ältere Events tragen nur die Empfängerliste.
    ziele = payload.get("to_agents")
    return isinstance(ziele, list) and len(ziele) >= BROADCAST_MIN_EMPFAENGER


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

    def _empfaenger(self, sender: dict[str, Any], ziel: Any) -> tuple[list[str], bool]:
        roh = str(ziel or "").strip()
        if not roh:
            raise MessageError("Empfänger fehlt")
        normal = roh.lower()
        if normal in {"all", "alle", "broadcast"}:
            if sender["agent_id"] not in BROADCAST_AGENTS:
                raise MessageError("Broadcast ist nur A1 oder S1–S3 erlaubt")
            return ([str(p["agent_id"]) for p in self.store.profile_alle() if p["active"]],
                    True)
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
            return empfaenger, False
        ziel_profil = self._profil(roh)
        if ziel_profil["agent_id"] == sender["agent_id"]:
            raise MessageError("Ein Agent kann sich nicht selbst adressieren")
        return [str(ziel_profil["agent_id"])], False

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
        ziel, broadcast = self._empfaenger(von, recipient)
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
        jetzt = datetime.now(timezone.utc).replace(microsecond=0)

        # Prüfung und Einfügen liegen für Broadcasts unter einem Prozess-Lock.
        # Die Historie selbst bleibt in SQLite und überlebt Neustarts.
        if broadcast:
            with _BROADCAST_LOCK:
                self._pruefe_broadcast_limit(von, jetzt)
                ids = self._speichere(
                    von=von, ziel=ziel, thread=thread, art=art, betreff=betreff,
                    inhalt=inhalt, belege=belege, requires_ack=bool(requires_ack),
                    prio=prio, ablauf=ablauf,
                )
                self._audit_versand(von, ziel, ids, thread, art,
                                    broadcast, bool(requires_ack))
        else:
            ids = self._speichere(
                von=von, ziel=ziel, thread=thread, art=art, betreff=betreff,
                inhalt=inhalt, belege=belege, requires_ack=bool(requires_ack),
                prio=prio, ablauf=ablauf,
            )
            self._audit_versand(von, ziel, ids, thread, art,
                                broadcast, bool(requires_ack))

        nachrichten = [self.store.nachricht(i) for i in ids]
        return {
            "thread_id": thread,
            "message_ids": ids,
            "to_agents": ziel,
            "broadcast": broadcast,
            "messages": [dict(n) for n in nachrichten if n],
        }

    def _speichere(
        self, *, von: dict[str, Any], ziel: list[str], thread: str, art: str,
        betreff: str, inhalt: str, belege: list[str], requires_ack: bool,
        prio: str, ablauf: str | None,
    ) -> list[int]:
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
                requires_ack=requires_ack,
                priority=prio,
                expires_at=ablauf,
            ))
        return ids

    def _audit_versand(self, von: dict[str, Any], ziel: list[str], ids: list[int],
                       thread: str, art: str, broadcast: bool,
                       requires_ack: bool) -> None:
        self.store.append_event(str(von["agent_id"]), None, "message_sent", {
            "thread_id": thread,
            "to_agents": ziel,
            "message_ids": ids,
            "kind": art,
            "requires_ack": requires_ack,
            "broadcast": broadcast,
        })

    def _pruefe_broadcast_limit(self, sender: dict[str, Any], jetzt: datetime) -> None:
        """Prüft Cooldown und 24-Stunden-Limit anhand der Audit-Historie."""
        cooldown = _policy_int(self.store, "broadcast_cooldown_sekunden",
                               BROADCAST_COOLDOWN_SEKUNDEN)
        max_tag = _policy_int(self.store, "broadcast_max_pro_tag",
                              BROADCAST_MAX_PRO_TAG)
        if cooldown <= 0 and max_tag <= 0:
            return
        fenster = max(86400 if max_tag > 0 else 0, cooldown)
        seit = (jetzt - timedelta(seconds=fenster)).replace(microsecond=0).isoformat()
        events = self.store.nachrichten_events(
            agent_id=str(sender["agent_id"]), seit=seit,
        )
        zeitpunkte: list[datetime] = []
        for event in events:
            try:
                payload = json.loads(event.get("payload_json") or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict) or not _ist_broadcast_event(payload):
                continue
            zeit = _zeit_lesen(event.get("ts"))
            if zeit is not None:
                zeitpunkte.append(zeit)
        if not zeitpunkte:
            return
        if cooldown > 0:
            letzte = max(zeitpunkte)
            rest = cooldown - (jetzt - letzte).total_seconds()
            if rest > 0:
                sekunden = max(1, math.ceil(rest))
                raise MessageRateLimitError(
                    f"Broadcast-Cooldown aktiv: nächster Broadcast in {sekunden} s",
                    retry_after=sekunden, limit="cooldown",
                )
        if max_tag > 0:
            tag_seit = jetzt - timedelta(days=1)
            im_tag = [zeit for zeit in zeitpunkte if zeit >= tag_seit]
            if len(im_tag) >= max_tag:
                aelteste = min(im_tag)
                sekunden = max(1, math.ceil(
                    (aelteste + timedelta(days=1) - jetzt).total_seconds()))
                raise MessageRateLimitError(
                    f"Broadcast-Tageslimit erreicht ({max_tag}/24 h)",
                    retry_after=sekunden, limit="tag",
                )

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

    def erinnere_offene_acks(
        self, *, jetzt_wert: datetime | None = None, limit: int = 50,
    ) -> dict[str, Any]:
        """Erinnert einmalig an fällige, noch offene Quittungen.

        Erinnerungen sind normale direkte Nachrichten im ursprünglichen Thread,
        aber selbst nicht quittungspflichtig. Ein ``message_reminder``-Audit-
        Event verhindert doppelte Erinnerungen und macht den Lauf beobachtbar.
        """
        with _REMINDER_LOCK:
            jetzt = _zeit_lesen(jetzt_wert or datetime.now(timezone.utc))
            if jetzt is None:
                jetzt = datetime.now(timezone.utc).replace(microsecond=0)
            nach_minuten = _policy_int(
                self.store, "ack_erinnerung_nach_minuten",
                ACK_ERINNERUNG_NACH_MINUTEN,
            )
            wiederholen = _policy_int(
                self.store, "ack_erinnerung_wiederholen_minuten",
                ACK_ERINNERUNG_WIEDERHOLEN_MINUTEN,
            )
            maximum = _policy_int(
                self.store, "ack_erinnerungen_max", ACK_ERINNERUNGEN_MAX,
            )
            if nach_minuten <= 0 or maximum <= 0:
                return {
                    "ok": True, "geprueft": 0, "erinnert": 0,
                    "uebersprungen": {}, "fehler": [],
                    "generated_at": jetzt.isoformat(),
                }

            vor = (jetzt - timedelta(minutes=nach_minuten)).replace(
                microsecond=0).isoformat()
            offene = self.store.offene_ack_nachrichten(
                vor=vor, jetzt=jetzt.isoformat(),
                limit=max(1, min(200, int(limit))),
            )
            verlauf: dict[int, list[datetime]] = {}
            for event in self.store.erinnerungs_events():
                try:
                    payload = json.loads(event.get("payload_json") or "{}")
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                kennung = payload.get("message_id")
                zeit = _zeit_lesen(event.get("ts"))
                if kennung is None or zeit is None:
                    continue
                try:
                    verlauf.setdefault(int(kennung), []).append(zeit)
                except (TypeError, ValueError):
                    continue

            uebersprungen = {
                "max_erreicht": 0, "intervall": 0,
                "absender_inaktiv": 0, "empfaenger_inaktiv": 0,
                "nicht_mehr_offen": 0,
            }
            fehler: list[dict[str, Any]] = []
            erinnert = 0
            for row in offene:
                try:
                    message_id = int(row["id"])
                except (TypeError, ValueError):
                    continue
                bisher = verlauf.get(message_id, [])
                if len(bisher) >= maximum:
                    uebersprungen["max_erreicht"] += 1
                    continue
                if wiederholen > 0 and bisher:
                    naechste = max(bisher) + timedelta(minutes=wiederholen)
                    if jetzt < naechste:
                        uebersprungen["intervall"] += 1
                        continue

                # Zwischen Scan und Versand kann quittiert worden sein.
                aktuell = self.store.nachricht(message_id)
                if (not aktuell or not aktuell.get("requires_ack")
                        or aktuell.get("ack_at")):
                    uebersprungen["nicht_mehr_offen"] += 1
                    continue
                ablauf = _zeit_lesen(aktuell.get("expires_at"))
                if ablauf is not None and ablauf <= jetzt:
                    uebersprungen["nicht_mehr_offen"] += 1
                    continue

                absender = self.store.profil(str(row["from_agent"]))
                empfaenger = self.store.profil(str(row["to_agent"]))
                if not absender or not bool(absender.get("active")):
                    uebersprungen["absender_inaktiv"] += 1
                    continue
                if not empfaenger or not bool(empfaenger.get("active")):
                    uebersprungen["empfaenger_inaktiv"] += 1
                    continue

                betreff = f"Erinnerung: {row['subject']}"[:MAX_SUBJECT]
                inhalt = (
                    f"Automatische Erinnerung: Die Nachricht «{row['subject']}» "
                    f"vom {row['created_at']} ist noch nicht quittiert. Bitte "
                    "quittiere sie im Raumschiff-Detail.\n\n"
                    f"Ursprüngliche Nachricht: message:{message_id}"
                )
                try:
                    gesendet = self.send(
                        sender=str(absender["agent_id"]),
                        recipient=str(empfaenger["agent_id"]),
                        subject=betreff,
                        body=inhalt,
                        kind="alert",
                        evidence=[f"message:{message_id}"],
                        requires_ack=False,
                        priority=(str(row["priority"])
                                  if str(row["priority"]) in {"hoch", "dringend"}
                                  else "normal"),
                        thread_id=str(row["thread_id"]),
                    )
                except MessageError as exc:
                    fehler.append({"message_id": message_id, "fehler": str(exc)})
                    continue

                reminder_ids = list(gesendet.get("message_ids") or [])
                self.store.append_event(
                    str(absender["agent_id"]), None, "message_reminder", {
                        "message_id": message_id,
                        "reminder_id": reminder_ids[0] if reminder_ids else None,
                        "thread_id": row["thread_id"],
                        "nummer": len(bisher) + 1,
                    },
                )
                erinnert += 1

            return {
                "ok": True,
                "geprueft": len(offene),
                "erinnert": erinnert,
                "uebersprungen": uebersprungen,
                "fehler": fehler[:10],
                "generated_at": jetzt.isoformat(),
            }
