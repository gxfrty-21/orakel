"""HTTPS-Transport für abgeschlossene MT5-Tagesblöcke.

Der Endpunkt ist ein dünner Adapter auf den bestehenden CSV-Importkern. Er
authentifiziert den Windows-Rechner mit einem zweckgebundenen Bearer-Token,
prüft Dateiname, Grösse und Body-Hash und importiert die Datei in **einer**
Transaktion. Erst danach werden die zusammengeführte Reihe, ihre Frische und
ihre Datenqualität geprüft; ein Fehler rollt Kerzen und Ledger gemeinsam zurück.

Der Bootstrap-Marker wird nicht vom Client gesetzt. Er wird nach dem
kontrollierten CLI-Import mit ``orakel transport-bootstrap`` angelegt und
verliert seine Gültigkeit, wenn die zugehörige Kerzenreihe nicht mehr zum
gespeicherten Ledger-Stand passt.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import Config
from .kern.data import df_aus_bloecken, frische_kennzahl, pruefe_daten
from .kern.db import Facts, jetzt
from .kern.datenimport import (
    FrischeFehler,
    ParallelerImport,
    importiere_datei,
    internes_symbol,
    versatz_schluessel,
)

LOGGER = logging.getLogger(__name__)

TRANSPORT_PFAD = "/api/daten/import"
BOOTSTRAP_PREFIX = "transport_bootstrap"
TOKEN_MINDESTLAENGE = 32
STANDARD_MAX_BYTES = 5 * 1024 * 1024
RESERVE_BYTES = 50 * 1024 * 1024

_DATEINAME = re.compile(
    r"(?P<symbol>[A-Za-z0-9][A-Za-z0-9._-]{0,31})_"
    r"(?P<zeitrahmen>M1|M5|M15|M30|H1|H4|D1)_"
    r"(?P<datum>\d{8})\.csv"
)
_KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")


class TransportFehler(Exception):
    """Fehler mit HTTP-Status und stabilem Code für den Windows-Client."""

    def __init__(self, status_code: int, code: str, text: str, *,
                 retry_after: int | None = None) -> None:
        super().__init__(text)
        self.status_code = status_code
        self.code = code
        self.text = text
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class TransportKonfiguration:
    aktiv: bool
    token: str
    key_id: str
    max_bytes: int

    @property
    def einsatzbereit(self) -> bool:
        # Ein kurzer Token ist ein Konfigurationsfehler, kein Freibrief.
        return self.aktiv and len(self.token) >= TOKEN_MINDESTLAENGE


def _wahrheit(wert: str | None) -> bool:
    return str(wert or "").strip().lower() in {"1", "true", "ja", "yes", "an"}


def lade_transport_konfiguration() -> TransportKonfiguration:
    """Liest die Transportgrenzen aus der Umgebung; Secrets werden nie geloggt."""
    roh_mb = os.environ.get("ORAKEL_TRANSPORT_MAX_MB", "").strip()
    try:
        max_mb = int(roh_mb) if roh_mb else STANDARD_MAX_BYTES // (1024 * 1024)
    except ValueError:
        max_mb = 5
    max_mb = max(1, min(max_mb, 50))
    return TransportKonfiguration(
        aktiv=_wahrheit(os.environ.get("ORAKEL_TRANSPORT_AKTIV")),
        token=os.environ.get("ORAKEL_TRANSPORT_TOKEN", "").strip(),
        key_id=os.environ.get("ORAKEL_TRANSPORT_KEY_ID", "").strip(),
        max_bytes=max_mb * 1024 * 1024,
    )


def erlaubte_symbole(db: Facts) -> frozenset[str]:
    """Explizite Allowlist oder die bereits in der DB bekannten Symbole."""
    roh = os.environ.get("ORAKEL_TRANSPORT_SYMBOLE", "")
    if roh.strip():
        return frozenset(
            eintrag.strip().upper()
            for eintrag in roh.split(",")
            if eintrag.strip()
        )
    return frozenset(str(symbol).upper() for symbol in db.symbole())


def zerlege_transport_dateiname(dateiname: str) -> tuple[str, str, str]:
    """Validiert ``SYMBOL_TF_JJJJMMTT.csv`` und liefert die Bestandteile."""
    name = str(dateiname or "").strip()
    if len(name) > 128:
        raise TransportFehler(400, "dateiname_ungueltig", "Dateiname ist zu lang.")
    treffer = _DATEINAME.fullmatch(name)
    if treffer is None:
        raise TransportFehler(
            400, "dateiname_ungueltig",
            "Dateiname muss SYMBOL_TF_JJJJMMTT.csv entsprechen.",
        )
    datum = treffer.group("datum")
    try:
        datetime.strptime(datum, "%Y%m%d")
    except ValueError as exc:
        raise TransportFehler(400, "datum_ungueltig",
                              "Datum im Dateinamen ist ungültig.") from exc
    return (treffer.group("symbol").upper(),
            treffer.group("zeitrahmen").upper(), datum)


def bootstrap_schluessel(symbol: str, zeitrahmen: str) -> str:
    return f"{BOOTSTRAP_PREFIX}:{symbol.upper()}:{zeitrahmen.upper()}"


def bootstrap_marker(db: Facts, symbol: str, zeitrahmen: str) -> dict[str, Any] | None:
    wert = db.zustand(bootstrap_schluessel(symbol, zeitrahmen))
    return wert if isinstance(wert, dict) else None


def bootstrap_gesetzt(db: Facts, symbol: str, zeitrahmen: str) -> bool:
    """Marker nur gültig, wenn die tatsächliche Kerzenreihe ihn noch deckt."""
    marker = bootstrap_marker(db, symbol, zeitrahmen)
    if not marker:
        return False
    try:
        # Der Marker sichert die Mindesthistorie, nicht jede einzelne Kerze:
        # Eine fehlende Delta-Kerze repariert die Ledger-Reconciliation; eine
        # materiell verkürzte Reihe fällt hier als fehlender Bootstrap auf.
        mindest = int(marker.get("mindest_kerzen") or marker.get("kerzen") or 0)
    except (TypeError, ValueError):
        return False
    bis = str(marker.get("bis") or "")
    return db.kerzen_abgedeckt(
        symbol.upper(), zeitrahmen.upper(), mindest=mindest, bis=bis)


def bootstrap_freigeben(
    db: Facts, cfg: Config, symbol: str, zeitrahmen: str, *,
    quelle: str = "cli",
) -> dict[str, Any]:
    """Prüft die ganze Reihe und setzt danach den persistenten Marker.

    Der Aufruf ist der kontrollierte Bootstrap nach dem CLI-Import. Die
    Frischeprüfung bleibt Sache des Transport-Gates; für eine historische,
    vollständige Reihe darf der Marker auch bei alten Kerzen gesetzt werden.
    """
    symbol = symbol.strip().upper()
    zeitrahmen = zeitrahmen.strip().upper()
    if not symbol:
        raise ValueError("Symbol fehlt.")
    df = df_aus_bloecken(db.kerzen_bloecke(symbol, zeitrahmen))
    q = pruefe_daten(df, symbol, cfg, timeframe=zeitrahmen)
    if not q.ok:
        raise ValueError(
            "Bootstrap abgelehnt: " + "; ".join(q.fehler)
            if q.fehler else "Bootstrap abgelehnt: keine prüfbaren Kerzen."
        )
    marker = {
        "symbol": symbol,
        "zeitrahmen": zeitrahmen,
        "kerzen": int(q.kerzen),
        "mindest_kerzen": min(int(q.kerzen), cfg.min_kerzen_fuer(zeitrahmen)),
        "von": q.von,
        "bis": q.bis,
        "gesetzt_am": jetzt(),
        "quelle": str(quelle)[:80],
    }
    db.zustand_setzen(bootstrap_schluessel(symbol, zeitrahmen), marker)
    db.ereignis(
        "info", "Transport",
        f"Bootstrap-Marker gesetzt: {symbol} {zeitrahmen}, "
        f"{q.kerzen} Kerzen bis {q.bis}",
    )
    return marker


def _token_ok(header: str, token: str) -> bool:
    art, trenner, wert = str(header or "").strip().partition(" ")
    if not trenner or art.lower() != "bearer" or not wert:
        return False
    return secrets.compare_digest(wert.strip().encode("utf-8"), token.encode("utf-8"))


def _autorisieren(request: Request, konfiguration: TransportKonfiguration) -> str:
    if not _token_ok(request.headers.get("authorization", ""), konfiguration.token):
        raise TransportFehler(401, "token_ungueltig", "Bearer-Token fehlt oder ist ungültig.")
    key_id = str(request.headers.get("x-orakel-key-id", "")).strip()
    if not key_id:
        raise TransportFehler(400, "key_id_fehlt", "X-Orakel-Key-Id fehlt.")
    if not _KEY_ID.fullmatch(key_id):
        raise TransportFehler(400, "key_id_ungueltig", "X-Orakel-Key-Id ist ungültig.")
    if konfiguration.key_id and not secrets.compare_digest(
            key_id.encode("utf-8"), konfiguration.key_id.encode("utf-8")):
        raise TransportFehler(403, "key_id_ungueltig", "X-Orakel-Key-Id ist nicht freigegeben.")
    return key_id


def _content_length(request: Request, max_bytes: int) -> int:
    roh = str(request.headers.get("content-length", "")).strip()
    if not roh:
        raise TransportFehler(400, "content_length_fehlt", "Content-Length fehlt.")
    try:
        laenge = int(roh)
    except ValueError as exc:
        raise TransportFehler(400, "content_length_ungueltig",
                              "Content-Length ist keine Zahl.") from exc
    if laenge <= 0:
        raise TransportFehler(400, "datei_leer", "Der Upload ist leer.")
    if laenge > max_bytes:
        raise TransportFehler(
            413, "datei_zu_gross",
            f"Der Upload überschreitet die Grenze von {max_bytes} Bytes.",
        )
    return laenge


def _medientyp_ok(request: Request) -> None:
    typ = str(request.headers.get("content-type", "")).split(";", 1)[0].strip().lower()
    if typ not in {"text/csv", "application/octet-stream"}:
        raise TransportFehler(
            415, "medientyp_nicht_erlaubt",
            "Content-Type muss text/csv oder application/octet-stream sein.",
        )


def _pruefe_platz(cfg: Config, max_bytes: int) -> None:
    """Früh warnen, bevor eine Temp-Datei das Volume füllt."""
    ordner = cfg.daten_ordner
    try:
        ordner.mkdir(parents=True, exist_ok=True)
        frei = shutil.disk_usage(ordner).free
    except OSError as exc:
        raise TransportFehler(507, "speicherplatz",
                              "Speicherplatz konnte nicht geprüft werden.") from exc
    benoetigt = 2 * int(max_bytes) + RESERVE_BYTES
    if frei < benoetigt:
        raise TransportFehler(
            507, "speicherplatz",
            "Zu wenig freier Speicher für Upload und Import.",
        )


def _zeitzone(cfg: Config) -> str | None:
    return str(cfg["daten"].get("server_zeitzone") or "").strip() or None


def _versatz(cfg: Config) -> float | None:
    wert = cfg["daten"].get("server_versatz_stunden")
    return None if wert is None else float(wert)


def _audit(db: Facts, key_id: str, dateiname: str, sha256: str,
           ergebnis: Any, dauer_ms: int, *, status: str) -> None:
    try:
        db.ereignis(
            "info" if status == "ok" else "warnung",
            "Transport",
            f"{status}: key={key_id} datei={dateiname} sha256={sha256[:16]} "
            f"symbol={ergebnis.symbol} tf={ergebnis.zeitrahmen} "
            f"kerzen={ergebnis.kerzen} uebersprungen={ergebnis.uebersprungen} "
            f"dauer={dauer_ms}ms",
        )
    except Exception:  # noqa: BLE001 - der Commit darf nicht wegen Audit scheitern
        LOGGER.exception("Transport-Audit konnte nicht geschrieben werden")


async def _speichere_temp(request: Request, ziel: Path, max_bytes: int,
                          erwartet: int) -> tuple[int, str]:
    """Streamt den Body in eine ``.part``-Datei und berechnet den SHA-256."""
    summe = hashlib.sha256()
    gesamt = 0
    with ziel.open("wb") as datei:
        async for block in request.stream():
            if not block:
                continue
            gesamt += len(block)
            if gesamt > max_bytes:
                raise TransportFehler(413, "datei_zu_gross",
                                      "Der Upload ist grösser als angekündigt.")
            datei.write(block)
            summe.update(block)
    if gesamt != erwartet:
        raise TransportFehler(
            400, "content_length_abweichung",
            "Die tatsächliche Body-Grösse weicht von Content-Length ab.",
        )
    return gesamt, summe.hexdigest()


def _importiere_serie(
    db: Facts, cfg: Config, pfad: Path, symbol: str, zeitrahmen: str,
    *, teilwiederherstellung: bool = False,
) -> tuple[Any, Any, dict[str, Any] | None]:
    """Importiert und prüft die zusammengeführte Reihe in einer Transaktion."""
    with db.conn() as c:
        try:
            ergebnis = importiere_datei(
                db, pfad, symbol, zeitrahmen,
                daten_cfg=cfg["daten"], zeitzone=_zeitzone(cfg),
                versatz=_versatz(cfg), c=c,
            )
        except ParallelerImport as exc:
            raise TransportFehler(
                409, "import_belegt",
                "Dieselbe Datei wird bereits parallel importiert.",
                retry_after=1,
            ) from exc
        df = df_aus_bloecken(db.kerzen_bloecke(symbol, zeitrahmen, c=c))
        q = pruefe_daten(
            df, symbol, cfg, timeframe=zeitrahmen,
            # Eine exakt gebuchte Datei darf nach Totalverlust zunächst nur
            # ihren eigenen Block wiederherstellen. Die Mindesthistorie bleibt
            # sonst unangetastet; der Bootstrap-Marker wird dadurch nicht
            # gültig und neue Deltas bleiben gesperrt.
            mindest_kerzen=0 if teilwiederherstellung else None,
        )
        if teilwiederherstellung:
            mindestens = cfg.min_kerzen_fuer(zeitrahmen)
            if len(df) < mindestens:
                q.warnungen.append(
                    f"Teilwiederherstellung: {len(df)} von mindestens "
                    f"{mindestens} Kerzen ({zeitrahmen.upper()}); "
                    "Bootstrap bleibt bis zur vollständigen Reihe gesperrt."
                )
        if not q.ok:
            fehler = "; ".join(q.fehler) if q.fehler else "unbekannter Datenfehler"
            raise TransportFehler(
                400, "datenqualitaet",
                f"Zusammengeführte Reihe abgelehnt: {fehler}",
            )
        kennzahl = frische_kennzahl(
            df["ts"].iloc[-1], cfg["daten"], zeitrahmen)
        if kennzahl and not kennzahl["frisch"]:
            raise FrischeFehler(
                f"jüngste Kerze {kennzahl['alter_stunden']:.1f} h alt "
                f"(Grenze {kennzahl['max_alter_stunden']:.1f} h) — "
                "Daten veraltet; Import abgelehnt."
            )
        # Wie der CLI-Import erst nach bestandener Reihenprüfung: Ab jetzt
        # liest die Pipeline die CSV-/Transportreihe statt synthetischer Kerzen.
        db.zustand_setzen("datenquelle", "csv", c=c)
    return ergebnis, q, kennzahl


def _bewahre_datei(temp: Path, cfg: Config, dateiname: str) -> Path:
    """Verschiebt die geprüfte Datei atomar in den ordnerlesbaren Bereich."""
    ziel = cfg.daten_ordner / dateiname
    ziel.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temp, ziel)
    return ziel


async def verarbeite_anfrage(request: Request, cfg: Config) -> JSONResponse:
    """Prüft und importiert einen Upload; alle Fehler bleiben als JSON klar."""
    beginn = time.monotonic()
    konfiguration = lade_transport_konfiguration()
    if not konfiguration.einsatzbereit:
        return _fehlerantwort(TransportFehler(
            503, "transport_deaktiviert",
            "Der Datentransport ist nicht aktiviert oder nicht konfiguriert.",
        ))

    db: Facts | None = None
    temp: Path | None = None
    key_id = ""
    dateiname = ""
    sha256 = ""
    try:
        key_id = _autorisieren(request, konfiguration)
        dateiname = str(request.headers.get("x-orakel-dateiname", "")).strip()
        symbol, zeitrahmen, _datum = zerlege_transport_dateiname(dateiname)
        symbol = internes_symbol(symbol, cfg["daten"])
        erwartete_summe = str(
            request.headers.get("x-orakel-content-sha256", "")
        ).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", erwartete_summe):
            raise TransportFehler(
                400, "hash_fehlt",
                "X-Orakel-Content-SHA256 muss ein SHA-256 in Hex sein.",
            )
        request_id = str(request.headers.get("x-orakel-request-id", "")).strip()
        if request_id and not _REQUEST_ID.fullmatch(request_id):
            raise TransportFehler(400, "request_id_ungueltig",
                                  "X-Orakel-Request-Id ist ungültig.")
        if zeitrahmen not in {"M15", cfg.richter_zeitrahmen}:
            raise TransportFehler(
                400, "zeitrahmen_nicht_erlaubt",
                f"Zeitrahmen {zeitrahmen} ist für den Transport nicht freigegeben.",
            )
        _medientyp_ok(request)
        laenge = _content_length(request, konfiguration.max_bytes)

        db = Facts(cfg.db_pfad)
        # Ein exakt bereits gebuchter Block darf nach einem Teil-Restore auch
        # dann erneut eingespielt werden, wenn die Kerzenreihe ganz fehlt und
        # der Bootstrap-Marker deshalb ungültig ist. Neue Hashes haben keine
        # solche Buchung und bleiben am Bootstrap-Gate. Der hier verwendete
        # Header-Hash entscheidet nur über den Pfad; der tatsächliche Body-Hash
        # wird nach dem Empfang erneut geprüft.
        bestehende_buchung = db.datenimport_finden(
            erwartete_summe, symbol, zeitrahmen,
            _zeitzone(cfg) or "", versatz_schluessel(_versatz(cfg)),
        )
        # Eine bereits gebuchte Reihe bleibt als Symbol bekannt, auch wenn
        # ihre Kerzen gerade vollständig fehlen. Dann erreicht ein neuer Hash
        # wenigstens das Bootstrap-Gate (409) statt fälschlich als unbekanntes
        # Symbol abgewiesen zu werden.
        bekannte_reihe = (bestehende_buchung is not None
                          or db.datenimport_vorhanden(symbol, zeitrahmen))
        if symbol not in erlaubte_symbole(db) and not bekannte_reihe:
            raise TransportFehler(
                400, "symbol_nicht_erlaubt",
                f"Symbol {symbol} ist für den Transport nicht freigegeben.",
            )
        if not bootstrap_gesetzt(db, symbol, zeitrahmen) and bestehende_buchung is None:
            raise TransportFehler(
                409, "bootstrap_erforderlich",
                f"Für {symbol} {zeitrahmen} fehlt ein gültiger Bootstrap-Marker.",
            )
        _pruefe_platz(cfg, laenge)

        inbox = cfg.daten_ordner / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        temp = inbox / f"{uuid.uuid4().hex}.part"
        _, sha256 = await _speichere_temp(
            request, temp, konfiguration.max_bytes, laenge)
        if not secrets.compare_digest(sha256, erwartete_summe):
            raise TransportFehler(
                400, "hash_mismatch",
                "Der SHA-256 des Bodys stimmt nicht mit dem Header überein.",
            )

        try:
            ergebnis, q, kennzahl = _importiere_serie(
                db, cfg, temp, symbol, zeitrahmen,
                teilwiederherstellung=bool(bestehende_buchung),
            )
        except FrischeFehler as exc:
            raise TransportFehler(409, "daten_veraltet", str(exc)) from exc

        _bewahre_datei(temp, cfg, dateiname)
        dauer_ms = int((time.monotonic() - beginn) * 1000)
        _audit(db, key_id, dateiname, sha256, ergebnis, dauer_ms, status="ok")
        antwort = {
            "ok": True,
            "code": "bereits_vorhanden" if ergebnis.uebersprungen else "importiert",
            "datei": dateiname,
            "symbol": ergebnis.symbol,
            "zeitrahmen": ergebnis.zeitrahmen,
            "kerzen": ergebnis.kerzen,
            "von": ergebnis.von,
            "bis": ergebnis.bis,
            "uebersprungen": bool(ergebnis.uebersprungen),
            "sha256": sha256,
            "frische": kennzahl,
            "warnungen": list(q.warnungen),
            "dauer_ms": dauer_ms,
        }
        if request_id:
            antwort["request_id"] = request_id
        return JSONResponse(antwort, headers={"Cache-Control": "no-store"})
    except TransportFehler as exc:
        if db is not None and key_id:
            try:
                db.ereignis(
                    "warnung", "Transport",
                    f"abgelehnt: key={key_id} datei={dateiname or '-'} "
                    f"code={exc.code}",
                )
            except Exception:  # noqa: BLE001 - Fehlerantwort bleibt wichtiger
                LOGGER.exception("Transport-Ablehnung konnte nicht auditiert werden")
        return _fehlerantwort(exc)
    except sqlite3.IntegrityError:
        return _fehlerantwort(TransportFehler(
            409, "import_belegt",
            "Der Import kollidiert mit einer parallelen Buchung.",
            retry_after=1,
        ))
    except ValueError as exc:
        return _fehlerantwort(TransportFehler(
            400, "eingabe", str(exc) or "Der Upload ist ungültig."))
    except OSError:
        fehler_id = uuid.uuid4().hex
        LOGGER.exception("Transport-Dateifehler %s", fehler_id)
        return _fehlerantwort(TransportFehler(
            500, "interner_fehler", f"Interner Fehler ({fehler_id})"))
    except Exception:  # noqa: BLE001 - keine internen Pfade an den Client
        fehler_id = uuid.uuid4().hex
        LOGGER.exception("Transportfehler %s", fehler_id)
        return _fehlerantwort(TransportFehler(
            500, "interner_fehler", f"Interner Fehler ({fehler_id})"))
    finally:
        if temp is not None:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Temp-Datei konnte nicht entfernt werden: %s", temp)


def _fehlerantwort(fehler: TransportFehler) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if fehler.retry_after is not None:
        headers["Retry-After"] = str(max(1, int(fehler.retry_after)))
    return JSONResponse(
        {"ok": False, "fehler": fehler.text, "code": fehler.code},
        status_code=fehler.status_code,
        headers=headers,
    )


def registriere_transport(app: FastAPI, cfg: Config) -> None:
    """Hängt den Endpunkt an die bestehende App; die Route bleibt ein Adapter."""

    @app.post(TRANSPORT_PFAD)
    async def daten_import(request: Request) -> JSONResponse:
        return await verarbeite_anfrage(request, cfg)
