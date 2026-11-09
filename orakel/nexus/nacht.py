"""Nachtlauf des Nexus.

Dieser Lauf ersetzt keinen Menschen und erfindet nichts. Er erledigt die
wiederkehrende, echte Arbeit:

1. Quellen abrufen, deren Intervall abgelaufen ist (Cache-Metadaten).
2. Unveränderte Quellen über 304 überspringen, ohne sie neu zu parsen.
3. Ein konsistentes SQLite-Backup ziehen und prüfen.
4. Optional DNS, TLS-Zertifikat und Health-Endpunkt der eigenen Domain prüfen.

Er speichert noch **keine** Artikel in der Fakten-DB — das kommt mit der
Dubletten-Erkennung in Phase 2. Bis dahin hält der Lauf Cache und Backup
aktuell und protokolliert ehrlich, was er gesehen hat.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import ssl
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..db import Facts
from .abruf import Abrufer, CacheEintrag, HttpCache
from .feeds import parse_feed
from .quellen import Quelle, lade_register

STANDARD_BACKUP_ORDNER = Path("backups")
STANDARD_BEHALTEN_TAGE = 14


@dataclass(slots=True)
class _Zaehler:
    faellig: int = 0
    abgerufen: int = 0
    unveraendert: int = 0
    fehler: int = 0
    meldungen: int = 0


def ist_faellig(eintrag: CacheEintrag | None, intervall_minuten: int,
                jetzt: datetime) -> bool:
    """Eine Quelle ohne Cache-Eintrag ist immer fällig."""
    if eintrag is None:
        return True
    try:
        zuletzt = datetime.fromisoformat(eintrag.abgerufen_am)
    except (TypeError, ValueError):
        return True
    if zuletzt.tzinfo is None:
        zuletzt = zuletzt.replace(tzinfo=timezone.utc)
    return jetzt - zuletzt >= timedelta(minutes=intervall_minuten)


def _backup(db_pfad: Path, ordner: Path, jetzt: datetime,
            behalten_tage: int) -> dict[str, object]:
    ordner.mkdir(parents=True, exist_ok=True)
    ziel = ordner / f"orakel-{jetzt:%Y-%m-%d}.db"

    quelle = sqlite3.connect(db_pfad)
    kopie = sqlite3.connect(ziel)
    try:
        quelle.backup(kopie)
    finally:
        kopie.close()
        quelle.close()

    pruefung = sqlite3.connect(ziel)
    try:
        integrity = str(pruefung.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        pruefung.close()

    grenze = jetzt - timedelta(days=behalten_tage)
    entfernt: list[str] = []
    for datei in sorted(ordner.glob("orakel-*.db")):
        if datei == ziel:
            continue
        alter = datetime.fromtimestamp(datei.stat().st_mtime, timezone.utc)
        if alter < grenze:
            datei.unlink()
            entfernt.append(datei.name)

    return {"pfad": str(ziel), "bytes": ziel.stat().st_size,
            "integrity": integrity, "entfernt": entfernt}


def dns_und_tls(domain: str, timeout: float = 10.0) -> dict[str, object]:
    """Prüft A/AAAA, Zertifikat und Health — ohne Zugangsdaten."""
    ergebnis: dict[str, object] = {"domain": domain, "ok": False}
    try:
        infos = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
        ergebnis["ips"] = sorted({info[4][0] for info in infos})
    except Exception as exc:
        ergebnis["fehler"] = f"DNS: {type(exc).__name__}"
        return ergebnis

    try:
        kontext = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=timeout) as roh:
            with kontext.wrap_socket(roh, server_hostname=domain) as tls:
                zertifikat = tls.getpeercert()
        ablauf = datetime.strptime(zertifikat["notAfter"], "%b %d %H:%M:%S %Y %Z")
        ablauf = ablauf.replace(tzinfo=timezone.utc)
        ergebnis["zertifikat_bis"] = ablauf.isoformat()
        ergebnis["tage_rest"] = (ablauf - datetime.now(timezone.utc)).days
    except Exception as exc:
        ergebnis["fehler"] = f"TLS: {type(exc).__name__}"
        return ergebnis

    try:
        with urllib.request.urlopen(f"https://{domain}/api/health", timeout=timeout) as antwort:
            ergebnis["health_status"] = int(antwort.status)
    except Exception as exc:
        ergebnis["fehler"] = f"Health: {type(exc).__name__}"
        return ergebnis

    ergebnis["ok"] = True
    return ergebnis


def _sende(url: str, body: bytes | None, content_type: str,
           methode: str, timeout: float) -> tuple[bool, str | None]:
    """Sendet eine Meldung. Gibt (erfolg, fehlername) zurück, wirft nie."""
    try:
        anfrage = urllib.request.Request(
            url, data=body, method=methode,
            headers={"Content-Type": content_type,
                     "User-Agent": "OrakelNexus/0.1 (Nachtlauf)"},
        )
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
            return 200 <= int(antwort.status) < 300, None
    except Exception as exc:
        return False, type(exc).__name__


def _warnung_text(bericht: dict[str, object]) -> str:
    teile = [
        f"Orakel-Nachtlauf fehlgeschlagen: {bericht.get('fehler', 0)} Fehler "
        f"bei {bericht.get('faellig', 0)} Quellen."
    ]
    backup = bericht.get("backup")
    if isinstance(backup, dict) and backup.get("fehler"):
        teile.append(f"Backup: {backup['fehler']}.")
    domain = bericht.get("domain")
    if isinstance(domain, dict) and not domain.get("ok"):
        teile.append(f"Domain: {domain.get('fehler', 'unbekannt')}.")
    teile.append(f"Zeit: {bericht.get('zeit')}.")
    return " ".join(teile)


def _warnung_senden(url: str, bericht: dict[str, object], art: str,
                    timeout: float) -> dict[str, object]:
    text = _warnung_text(bericht)
    if art == "text":
        # ntfy und einfache Webhooks erwarten reinen Text.
        body = text.encode("utf-8")
        ctype = "text/plain; charset=utf-8"
    else:
        # Slack/Mattermost lesen "text", Discord "content".
        body = json.dumps({"text": text, "content": text, "ok": False,
                           "zeit": bericht.get("zeit"),
                           "fehler": bericht.get("fehler", 0)}).encode("utf-8")
        ctype = "application/json"
    erfolg, fehler = _sende(url, body, ctype, "POST", timeout)
    return {"gesendet": erfolg, "fehler": fehler}


def _ping_senden(url: str, ok: bool, timeout: float) -> dict[str, object]:
    """Dead-man's-Switch: Erfolg = GET, Fehler = POST /fail, wie bei Healthchecks."""
    ziel = url if ok else url.rstrip("/") + "/fail"
    methode = "GET" if ok else "POST"
    erfolg, fehler = _sende(ziel, None if ok else b"", "text/plain", methode, timeout)
    # Die URL selbst ist ein Secret und landet bewusst nicht im Bericht.
    return {"gesendet": erfolg, "fehler": fehler, "art": "ok" if ok else "fail"}


def nachtlauf(
    db_pfad: str | Path,
    register_pfad: str | Path | None = None,
    backup_ordner: str | Path | None = STANDARD_BACKUP_ORDNER,
    domain: str | None = None,
    user_agent: str = "OrakelNexus/0.1 (Nachtlauf)",
    limit: int | None = None,
    behalten_tage: int = STANDARD_BEHALTEN_TAGE,
    jetzt: datetime | None = None,
    abrufer: Abrufer | None = None,
    warnung_url: str | None = None,
    warnung_art: str = "json",
    ping_url: str | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    db_pfad = Path(db_pfad)
    jetzt = jetzt or datetime.now(timezone.utc)
    quellen = lade_register(register_pfad)
    cache = HttpCache(db_pfad)
    abrufer = abrufer or Abrufer(cache, user_agent, min_abstand_sekunden=1.0)

    faellig = [
        q for q in quellen
        if q.aktiv and ist_faellig(cache.hole(q.url), q.intervall_minuten, jetzt)
    ]
    if limit is not None:
        faellig = faellig[:limit]

    zaehler = _Zaehler(faellig=len(faellig))
    detail: list[dict[str, object]] = []
    for quelle in faellig:
        ergebnis = abrufer.hole(quelle)
        anzahl = 0
        if ergebnis.ok and ergebnis.inhalt:
            try:
                anzahl = len(parse_feed(ergebnis.inhalt, quelle))
            except Exception as exc:
                ergebnis.fehler = f"Parse: {type(exc).__name__}"
        if ergebnis.status == 304:
            zaehler.unveraendert += 1
        elif ergebnis.ok:
            zaehler.abgerufen += 1
        if not ergebnis.ok:
            zaehler.fehler += 1
        zaehler.meldungen += anzahl
        detail.append({"id": quelle.id, "status": ergebnis.status,
                       "meldungen": anzahl, "fehler": ergebnis.fehler,
                       "ms": ergebnis.dauer_ms})

    bericht: dict[str, object] = {
        "zeit": jetzt.isoformat(timespec="seconds"),
        "faellig": zaehler.faellig,
        "abgerufen": zaehler.abgerufen,
        "unveraendert": zaehler.unveraendert,
        "fehler": zaehler.fehler,
        "meldungen": zaehler.meldungen,
        "quellen": detail,
        "hinweis": "Noch keine Speicherung in artikel; das ist Phase 2.",
    }

    if backup_ordner:
        try:
            bericht["backup"] = _backup(db_pfad, Path(backup_ordner), jetzt, behalten_tage)
        except Exception as exc:
            bericht["backup"] = {"fehler": type(exc).__name__}

    if domain:
        bericht["domain"] = dns_und_tls(domain)

    backup = bericht.get("backup")
    backup_fehler = isinstance(backup, dict) and bool(backup.get("fehler"))
    domain = bericht.get("domain")
    domain_fehler = isinstance(domain, dict) and not domain.get("ok")
    bericht["ok"] = zaehler.fehler == 0 and not backup_fehler and not domain_fehler
    bericht["warnung_noetig"] = not bericht["ok"]

    if not bericht["ok"]:
        if warnung_url:
            bericht["warnung"] = _warnung_senden(warnung_url, bericht, warnung_art, timeout)
        else:
            bericht["warnung"] = {"gesendet": False,
                                  "grund": "keine Warnungs-URL konfiguriert"}
    if ping_url:
        bericht["ping"] = _ping_senden(ping_url, bool(bericht["ok"]), timeout)

    # Erst jetzt speichern: Der Zustand muss ok, Warnung und Ping enthalten.
    try:
        datenbank = Facts(db_pfad)
        datenbank.ereignis(
            "info" if bericht["ok"] else "warnung", "Nexus",
            f"Nachtlauf: {zaehler.faellig} fällig, {zaehler.abgerufen} abgerufen, "
            f"{zaehler.unveraendert} unverändert, {zaehler.meldungen} Meldungen, "
            f"{zaehler.fehler} Fehler, ok={bericht['ok']}",
        )
        datenbank.zustand_setzen("nexus_nacht", bericht)
    except Exception as exc:
        bericht["zustand_fehler"] = type(exc).__name__

    return bericht
