#!/usr/bin/env python3
"""Einmaliger Windows-Client für den Upload abgeschlossener MT5-Tagesblöcke.

Der Client läuft neben dem Server und spricht ausschliesslich den bereits
gemergten Endpunkt ``POST /api/daten/import`` an. Er exportiert genau einen
abgeschlossenen Server-Kalendertag, schreibt die Datei zuerst in einen
Staging-Bereich und hält den lokalen Fortschritt in einer atomar ersetzten
``state.json``. Der Server-Ledger bleibt die Wahrheit.

Der Token wird nie als Argument übergeben und nie in Zustand, Status oder Log
geschrieben. Er kommt aus der konfigurierten Umgebungsvariable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import sys
import time as time_mod
import tomllib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = 1
KOPFZEILE = (
    "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>"
    "\t<TICKVOL>\t<VOL>\t<SPREAD>"
)
ZEITRAHMEN = {"M15": 15, "H1": 60}
SYMBOL_MUSTER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
KEY_ID_MUSTER = re.compile(r"[A-Za-z0-9._-]{1,64}")
OFFENE_STATUS = frozenset({"vorbereitet", "wartend"})
ERFOLGS_STATUS = frozenset({"erfolgreich", "erfolgreich_degraded"})
MAX_VERSUCHE = 6


class ClientFehler(Exception):
    """Fehler mit definiertem Exit-Code und kurzem Grund für den Zustand."""

    code = 5

    def __init__(self, grund: str, text: str) -> None:
        super().__init__(text)
        self.grund = grund
        self.text = text


class KonfigurationsFehler(ClientFehler):
    code = 3


class ZustandsFehler(ClientFehler):
    code = 5


class Mt5Fehler(ClientFehler):
    code = 4


class GlobalFehler(ClientFehler):
    """Fehler, der alle Serien beendet (Auth, Transport, lokaler Zustand)."""

    code = 3


class SerienFehler(ClientFehler):
    code = 3

    def __init__(self, grund: str, text: str, *, quarantaene: bool = False) -> None:
        super().__init__(grund, text)
        self.quarantaene = quarantaene


class TransientFehler(ClientFehler):
    code = 2


@dataclass(frozen=True, slots=True)
class EndpointKonfiguration:
    url: str
    key_id: str
    token_env: str
    timeout_sekunden: float
    max_bytes: int


@dataclass(frozen=True, slots=True)
class ExportKonfiguration:
    symbole: tuple[str, ...]
    zeitrahmen: tuple[str, ...]
    server_zeitzone: str | None
    server_versatz_stunden: float | None
    terminal_pfad: str | None
    min_kerzen_pro_tag: dict[str, int]
    max_alter_stunden: dict[str, float]
    lookback_tage: int


@dataclass(frozen=True, slots=True)
class StateKonfiguration:
    pfad: Path
    sent_aufbewahrung_tage: int
    quarantaene_aufbewahrung_tage: int
    logs_aufbewahrung_tage: int


@dataclass(frozen=True, slots=True)
class RetryKonfiguration:
    http_versuche: int
    basis_sekunden: float
    retry_after_max_sekunden: int
    jitter_sekunden: float


@dataclass(frozen=True, slots=True)
class ClientKonfiguration:
    pfad: Path
    endpoint: EndpointKonfiguration
    export: ExportKonfiguration
    state: StateKonfiguration
    retry: RetryKonfiguration
    upload_start: str
    config_hash: str


@dataclass(frozen=True, slots=True)
class Kerze:
    zeit: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: int
    real_volume: int
    spread: int


@dataclass(frozen=True, slots=True)
class HttpAntwort:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> dict[str, Any] | None:
        try:
            wert = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return wert if isinstance(wert, dict) else None


@dataclass(frozen=True, slots=True)
class Klassifikation:
    art: str
    grund: str
    daten: dict[str, Any] | None
    retry_after: int | None = None
    quarantaene: bool = False
    global_stopp: bool = False


class NetzwerkFehler(Exception):
    """Transportfehler ohne HTTP-Antwort; wird als transient behandelt."""


class _KeineWeiterleitung(HTTPRedirectHandler):
    """Ein Redirect wird nicht verfolgt, damit der Bearer-Token nicht umgeleitet wird."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _abschnitt(daten: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    wert = daten.get(name)
    if wert is None:
        return {}
    if not isinstance(wert, Mapping):
        raise KonfigurationsFehler("konfiguration", f"[{name}] muss eine Tabelle sein.")
    return wert


def _text(daten: Mapping[str, Any], name: str, *, standard: str | None = None) -> str:
    wert = daten.get(name, standard)
    if not isinstance(wert, str) or not wert.strip():
        raise KonfigurationsFehler("konfiguration", f"{name} muss ein nichtleerer Text sein.")
    return wert.strip()


def _zahl(daten: Mapping[str, Any], name: str, *, standard: float | None = None,
          minimum: float | None = None, maximum: float | None = None) -> float:
    wert = daten.get(name, standard)
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise KonfigurationsFehler("konfiguration", f"{name} muss eine Zahl sein.")
    zahl = float(wert)
    if not math.isfinite(zahl):
        raise KonfigurationsFehler("konfiguration", f"{name} muss endlich sein.")
    if minimum is not None and zahl < minimum:
        raise KonfigurationsFehler("konfiguration", f"{name} muss mindestens {minimum} sein.")
    if maximum is not None and zahl > maximum:
        raise KonfigurationsFehler("konfiguration", f"{name} darf höchstens {maximum} sein.")
    return zahl


def _ganzzahl(daten: Mapping[str, Any], name: str, *, standard: int | None = None,
              minimum: int | None = None, maximum: int | None = None) -> int:
    zahl = _zahl(daten, name, standard=None if standard is None else float(standard),
                 minimum=None if minimum is None else float(minimum),
                 maximum=None if maximum is None else float(maximum))
    if not zahl.is_integer():
        raise KonfigurationsFehler("konfiguration", f"{name} muss eine Ganzzahl sein.")
    return int(zahl)


def _liste(daten: Mapping[str, Any], name: str) -> list[Any]:
    wert = daten.get(name)
    if not isinstance(wert, list):
        raise KonfigurationsFehler("konfiguration", f"{name} muss eine Liste sein.")
    return wert


def _expandiere(pfad: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(pfad)))


def _pruefe_zeitzone(zone: str) -> None:
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise KonfigurationsFehler("konfiguration", f"Unbekannte Zeitzone {zone}.") from exc


def _konfigurations_hash(endpoint: EndpointKonfiguration, export: ExportKonfiguration) -> str:
    inhalt = {
        "url": endpoint.url,
        "key_id": endpoint.key_id,
        "symbole": list(export.symbole),
        "zeitrahmen": list(export.zeitrahmen),
        "server_zeitzone": export.server_zeitzone,
        "server_versatz_stunden": export.server_versatz_stunden,
        "min_kerzen_pro_tag": export.min_kerzen_pro_tag,
        "max_alter_stunden": export.max_alter_stunden,
    }
    roh = json.dumps(inhalt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(roh).hexdigest()


def load_config(pfad: str | Path) -> ClientKonfiguration:
    """Lädt und validiert die TOML-Konfiguration; der Token bleibt draussen."""
    p = Path(pfad)
    try:
        daten = tomllib.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise KonfigurationsFehler("konfiguration", f"{p} ist nicht lesbar: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise KonfigurationsFehler("konfiguration", f"{p} ist kein gültiges TOML: {exc}") from exc

    roh_endpoint = _abschnitt(daten, "endpoint")
    url = _text(roh_endpoint, "url")
    geparst = urlparse(url)
    if geparst.scheme not in {"https", "http"} or not geparst.netloc:
        raise KonfigurationsFehler("konfiguration", "endpoint.url muss eine HTTP(S)-URL sein.")
    if geparst.scheme == "http" and geparst.hostname not in {"127.0.0.1", "::1"}:
        raise KonfigurationsFehler("konfiguration", "Unverschlüsseltes HTTP ist nur für 127.0.0.1 erlaubt.")
    if geparst.username is not None or geparst.password is not None:
        raise KonfigurationsFehler("konfiguration", "Zugangsdaten gehören nicht in die URL.")
    key_id = _text(roh_endpoint, "key_id")
    if not KEY_ID_MUSTER.fullmatch(key_id):
        raise KonfigurationsFehler("konfiguration", "endpoint.key_id ist ungültig.")
    token_env = _text(roh_endpoint, "token_env", standard="ORAKEL_TRANSPORT_TOKEN")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token_env):
        raise KonfigurationsFehler("konfiguration", "endpoint.token_env ist kein gültiger Variablenname.")
    timeout = _zahl(roh_endpoint, "timeout_sekunden", standard=60.0, minimum=1.0, maximum=600.0)
    max_bytes = _ganzzahl(roh_endpoint, "max_bytes", standard=5 * 1024 * 1024,
                          minimum=1024, maximum=50 * 1024 * 1024)

    roh_export = _abschnitt(daten, "export")
    symbole: list[str] = []
    for wert in _liste(roh_export, "symbole"):
        symbol = str(wert).strip().upper()
        if not SYMBOL_MUSTER.fullmatch(symbol):
            raise KonfigurationsFehler("konfiguration", f"Ungültiges Symbol {wert!r}.")
        if symbol in symbole:
            raise KonfigurationsFehler("konfiguration", f"Symbol {symbol} ist doppelt.")
        symbole.append(symbol)
    if not symbole:
        raise KonfigurationsFehler("konfiguration", "export.symbole darf nicht leer sein.")
    zeitrahmen: list[str] = []
    for wert in _liste(roh_export, "zeitrahmen"):
        tf = str(wert).strip().upper()
        if tf not in ZEITRAHMEN:
            raise KonfigurationsFehler("konfiguration", f"Zeitrahmen {wert!r} wird nicht unterstützt.")
        if tf in zeitrahmen:
            raise KonfigurationsFehler("konfiguration", f"Zeitrahmen {tf} ist doppelt.")
        zeitrahmen.append(tf)
    if "M15" not in zeitrahmen:
        raise KonfigurationsFehler("konfiguration", "M15 muss immer enthalten sein.")

    zone = roh_export.get("server_zeitzone")
    versatz = roh_export.get("server_versatz_stunden")
    if zone is not None and versatz is not None:
        raise KonfigurationsFehler("konfiguration", "server_zeitzone und server_versatz_stunden schliessen sich aus.")
    zone_text: str | None = None
    versatz_zahl: float | None = None
    if zone is not None:
        zone_text = str(zone).strip()
        if not zone_text:
            raise KonfigurationsFehler("konfiguration", "server_zeitzone ist leer.")
        _pruefe_zeitzone(zone_text)
    if versatz is not None:
        versatz_zahl = _zahl(roh_export, "server_versatz_stunden", minimum=-12.0, maximum=14.0)
    terminal_pfad = roh_export.get("terminal_pfad")
    if terminal_pfad is not None and not str(terminal_pfad).strip():
        terminal_pfad = None

    min_roh = roh_export.get("min_kerzen_pro_tag") or {}
    if not isinstance(min_roh, Mapping):
        raise KonfigurationsFehler("konfiguration", "min_kerzen_pro_tag muss eine Tabelle sein.")
    min_kerzen = {"M15": 90, "H1": 20}
    for tf in zeitrahmen:
        if tf in min_roh:
            min_kerzen[tf] = _ganzzahl(min_roh, tf, standard=min_kerzen[tf], minimum=1)

    alter_roh = roh_export.get("max_alter_stunden") or {}
    if not isinstance(alter_roh, Mapping):
        raise KonfigurationsFehler("konfiguration", "max_alter_stunden muss eine Tabelle sein.")
    max_alter = {"M15": 4.0, "H1": 24.0}
    for tf in zeitrahmen:
        if tf in alter_roh:
            max_alter[tf] = _zahl(alter_roh, tf, standard=max_alter[tf], minimum=0.01)

    lookback = _ganzzahl(roh_export, "lookback_tage", standard=10, minimum=1, maximum=31)
    export = ExportKonfiguration(
        symbole=tuple(symbole), zeitrahmen=tuple(zeitrahmen), server_zeitzone=zone_text,
        server_versatz_stunden=versatz_zahl,
        terminal_pfad=str(terminal_pfad).strip() if terminal_pfad else None,
        min_kerzen_pro_tag=min_kerzen, max_alter_stunden=max_alter, lookback_tage=lookback,
    )

    roh_state = _abschnitt(daten, "state")
    state_pfad = _expandiere(_text(roh_state, "pfad", standard="%LOCALAPPDATA%/Orakel/Transport"))
    state = StateKonfiguration(
        pfad=state_pfad,
        sent_aufbewahrung_tage=_ganzzahl(roh_state, "sent_aufbewahrung_tage", standard=30, minimum=1),
        quarantaene_aufbewahrung_tage=_ganzzahl(roh_state, "quarantaene_aufbewahrung_tage", standard=90, minimum=1),
        logs_aufbewahrung_tage=_ganzzahl(roh_state, "logs_aufbewahrung_tage", standard=30, minimum=1),
    )

    roh_retry = _abschnitt(daten, "retry")
    retry = RetryKonfiguration(
        http_versuche=_ganzzahl(roh_retry, "http_versuche", standard=2, minimum=1, maximum=2),
        basis_sekunden=_zahl(roh_retry, "basis_sekunden", standard=60.0, minimum=0.0, maximum=120.0),
        retry_after_max_sekunden=_ganzzahl(roh_retry, "retry_after_max_sekunden", standard=120, minimum=1, maximum=120),
        jitter_sekunden=_zahl(roh_retry, "jitter_sekunden", standard=2.0, minimum=0.0, maximum=30.0),
    )

    roh_schedule = _abschnitt(daten, "schedule")
    upload_start = _text(roh_schedule, "upload_start_server", standard="00:15")
    try:
        datetime.strptime(upload_start, "%H:%M")
    except ValueError as exc:
        raise KonfigurationsFehler("konfiguration", "upload_start_server muss HH:MM sein.") from exc

    endpoint = EndpointKonfiguration(
        url=url, key_id=key_id, token_env=token_env,
        timeout_sekunden=timeout, max_bytes=max_bytes,
    )
    return ClientKonfiguration(
        pfad=p, endpoint=endpoint, export=export, state=state, retry=retry,
        upload_start=upload_start,
        config_hash=_konfigurations_hash(endpoint, export),
    )


def _zone(cfg: ClientKonfiguration) -> timezone | ZoneInfo:
    if cfg.export.server_zeitzone:
        return ZoneInfo(cfg.export.server_zeitzone)
    if cfg.export.server_versatz_stunden is not None:
        return timezone(timedelta(hours=cfg.export.server_versatz_stunden))
    return timezone.utc


def _als_utc(zeit: datetime, cfg: ClientKonfiguration) -> datetime:
    return zeit.replace(tzinfo=_zone(cfg)).astimezone(timezone.utc)


def _zeitstempel(wert: Any) -> datetime:
    return datetime.fromtimestamp(int(wert), tz=timezone.utc).replace(tzinfo=None)


def _feld(obj: Any, name: str) -> Any:
    try:
        return obj[name]
    except (KeyError, IndexError, TypeError):
        return getattr(obj, name)


def _kerzen_aus_roh(roh: Sequence[Any]) -> list[Kerze]:
    gesehen: dict[tuple[Any, ...], Kerze] = {}
    for eintrag in roh:
        try:
            kerze = Kerze(
                zeit=_zeitstempel(_feld(eintrag, "time")),
                open=float(_feld(eintrag, "open")),
                high=float(_feld(eintrag, "high")),
                low=float(_feld(eintrag, "low")),
                close=float(_feld(eintrag, "close")),
                tick_volume=int(_feld(eintrag, "tick_volume")),
                real_volume=int(_feld(eintrag, "real_volume")),
                spread=int(_feld(eintrag, "spread")),
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise Mt5Fehler("mt5_kerze", f"MT5-Kerze ist unlesbar: {exc}") from exc
        gesehen[(kerze.zeit, kerze.open, kerze.high, kerze.low, kerze.close,
                 kerze.tick_volume, kerze.real_volume, kerze.spread)] = kerze
    return sorted(gesehen.values(), key=lambda k: k.zeit)


def _zeile(kerze: Kerze) -> str:
    return "\t".join([
        kerze.zeit.strftime("%Y.%m.%d"),
        kerze.zeit.strftime("%H:%M:%S"),
        repr(kerze.open), repr(kerze.high), repr(kerze.low), repr(kerze.close),
        str(kerze.tick_volume), str(kerze.real_volume), str(kerze.spread),
    ])


def _csv_bytes(kerzen: Sequence[Kerze]) -> bytes:
    return ("\n".join([KOPFZEILE, *(_zeile(k) for k in kerzen)]) + "\n").encode("utf-8")


def _tagesbereich(tag: date) -> tuple[int, int]:
    anfang = datetime.combine(tag, time(0, 0, 0), tzinfo=timezone.utc)
    ende = datetime.combine(tag, time(23, 59, 59), tzinfo=timezone.utc)
    return int(anfang.timestamp()), int(ende.timestamp())


def _dateiname(symbol: str, zeitrahmen: str, tag: date) -> str:
    return f"{symbol}_{zeitrahmen}_{tag:%Y%m%d}.csv"


def _sha256_datei(pfad: Path) -> str:
    summe = hashlib.sha256()
    with pfad.open("rb") as datei:
        for block in iter(lambda: datei.read(1024 * 1024), b""):
            summe.update(block)
    return summe.hexdigest()


def _pruefe_tagesblock(kerzen: Sequence[Kerze], tag: date, zeitrahmen: str,
                       cfg: ClientKonfiguration) -> None:
    if not kerzen:
        raise TransientFehler("keine_kerzen", f"Keine Kerzen für {tag}.")
    if any(k.zeit.date() != tag for k in kerzen):
        raise TransientFehler("fremder_tag", f"Der Block für {tag} enthält Kerzen eines anderen Tages.")
    if any(a.zeit > b.zeit for a, b in zip(kerzen, kerzen[1:])):
        raise TransientFehler("unsortiert", f"Der Block für {tag} ist nicht sortiert.")
    for kerze in kerzen:
        if (not all(math.isfinite(w) for w in (kerze.open, kerze.high, kerze.low, kerze.close))
                or min(kerze.open, kerze.high, kerze.low, kerze.close) <= 0
                or kerze.high < max(kerze.open, kerze.close, kerze.low)
                or kerze.low > min(kerze.open, kerze.close, kerze.high)):
            raise TransientFehler("datenqualitaet", f"Ungültige OHLC-Werte am {kerze.zeit}.")
    mindestens = cfg.export.min_kerzen_pro_tag[zeitrahmen]
    if len(kerzen) < mindestens:
        raise TransientFehler(
            "unvollstaendig",
            f"{tag} hat {len(kerzen)} Kerzen, erwartet mindestens {mindestens}; kein Upload.",
        )


def _pruefe_frische_zeit(zeit: datetime, tag: date, zeitrahmen: str,
                         cfg: ClientKonfiguration, jetzt: datetime) -> None:
    alter = (jetzt - _als_utc(zeit, cfg)).total_seconds() / 3600.0
    grenze = cfg.export.max_alter_stunden[zeitrahmen]
    if alter > grenze:
        raise SerienFehler(
            "daten_veraltet",
            f"{tag} ist mit {alter:.1f} h älter als die Grenze von {grenze:.1f} h; kein Upload.",
        )


def _pruefe_frische(kerze: Kerze, tag: date, zeitrahmen: str,
                    cfg: ClientKonfiguration, jetzt: datetime) -> None:
    _pruefe_frische_zeit(kerze.zeit, tag, zeitrahmen, cfg, jetzt)


def _server_jetzt(mt5: Any, symbol: str, zeitrahmen: str, cfg: ClientKonfiguration,
                  jetzt: datetime) -> date:
    """Kalendertag aus Terminaldaten, mit lokalem Serverkalender als Rückfall."""
    lokal = jetzt.astimezone(_zone(cfg)).date()
    tick_zeit: date | None = None
    try:
        tick = mt5.symbol_info_tick(symbol)
    except (AttributeError, OSError):
        tick = None
    if tick is not None:
        try:
            tick_zeit = _zeitstempel(_feld(tick, "time")).date()
        except (TypeError, ValueError, OverflowError):
            tick_zeit = None
    if tick_zeit is None:
        try:
            konstante = getattr(mt5, f"TIMEFRAME_{zeitrahmen}")
            roh = mt5.copy_rates_from_pos(symbol, konstante, 0, 1)
            if roh is not None and len(roh):
                tick_zeit = _kerzen_aus_roh(roh)[-1].zeit.date()
        except (AttributeError, OSError, TypeError, ValueError):
            tick_zeit = None
    return max(lokal, tick_zeit) if tick_zeit else lokal


def _finde_zieltag(mt5: Any, symbol: str, zeitrahmen: str, cfg: ClientKonfiguration,
                   jetzt: datetime) -> tuple[date, list[Kerze]]:
    heute = _server_jetzt(mt5, symbol, zeitrahmen, cfg, jetzt)
    konstante = getattr(mt5, f"TIMEFRAME_{zeitrahmen}", None)
    if konstante is None:
        raise Mt5Fehler("mt5_zeitrahmen", f"MT5 kennt den Zeitrahmen {zeitrahmen} nicht.")
    for abstand in range(1, cfg.export.lookback_tage + 1):
        tag = heute - timedelta(days=abstand)
        anfang, ende = _tagesbereich(tag)
        try:
            roh = mt5.copy_rates_range(symbol, konstante, anfang, ende)
        except (OSError, RuntimeError) as exc:
            raise Mt5Fehler("mt5_abruf", f"MT5-Abruf für {symbol} fehlgeschlagen: {exc}") from exc
        if roh is None:
            raise Mt5Fehler("mt5_abruf", f"MT5-Abruf für {symbol} lieferte keine Antwort.")
        kerzen = _kerzen_aus_roh(roh)
        if kerzen:
            return tag, kerzen
    raise Mt5Fehler(
        "mt5_keine_daten",
        f"Keine Kerzen für {symbol} {zeitrahmen} in den letzten {cfg.export.lookback_tage} Tagen.",
    )


def _leerer_zustand(config_hash: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "config_hash": config_hash, "serien": {}, "uploads": {}}


def _root(cfg: ClientKonfiguration) -> Path:
    return cfg.state.pfad


def _dateien_vorhanden(cfg: ClientKonfiguration) -> bool:
    for name in ("staging", "sent"):
        ordner = _root(cfg) / name
        if not ordner.is_dir():
            continue
        try:
            if any(p.is_file() and p.name != ".gitkeep" for p in ordner.iterdir()):
                return True
        except OSError:
            return True
    return False


def _sicherer_pfad(root: Path, relativ: str) -> Path:
    p = (root / relativ).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError as exc:
        raise ZustandsFehler("state_unlesbar", f"Pfad {relativ!r} verlässt den Zustandsordner.") from exc
    return p


def _lade_zustand(cfg: ClientKonfiguration, *, init_erlaubt: bool = False) -> dict[str, Any]:
    root = _root(cfg)
    root.mkdir(parents=True, exist_ok=True)
    pfad = root / "state.json"
    if not pfad.exists():
        if _dateien_vorhanden(cfg):
            raise ZustandsFehler("state_fehlt", "state.json fehlt, aber staging/ oder sent/ enthält Dateien.")
        if not init_erlaubt:
            raise ZustandsFehler("state_fehlt_init", "state.json fehlt; Initialisierung nur mit --init-state.")
        zustand = _leerer_zustand(cfg.config_hash)
        _speichere_zustand(cfg, zustand)
        return zustand
    try:
        roh = pfad.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ZustandsFehler("state_unlesbar", f"state.json ist nicht lesbar: {exc}") from exc
    try:
        zustand = json.loads(roh)
    except json.JSONDecodeError as exc:
        raise ZustandsFehler("state_unlesbar", f"state.json ist kein gültiges JSON: {exc}") from exc
    if not isinstance(zustand, dict):
        raise ZustandsFehler("state_unlesbar", "state.json enthält kein Objekt.")
    if zustand.get("schema") != SCHEMA:
        raise KonfigurationsFehler("schema", f"Unbekanntes state-Schema {zustand.get('schema')!r}.")
    if zustand.get("config_hash") != cfg.config_hash:
        raise KonfigurationsFehler("konfiguration", "state.json gehört zu einer anderen Konfiguration.")
    if not isinstance(zustand.get("serien"), dict) or not isinstance(zustand.get("uploads"), dict):
        raise ZustandsFehler("state_unlesbar", "state.json hat keine gültigen serien/uploads.")
    _pruefe_state_dateien(cfg, zustand)
    return zustand


def _pruefe_state_dateien(cfg: ClientKonfiguration, zustand: Mapping[str, Any]) -> None:
    root = _root(cfg)
    for schluessel, rec in zustand["uploads"].items():
        if not isinstance(rec, dict):
            raise ZustandsFehler("state_unlesbar", f"Upload {schluessel} ist kein Objekt.")
        dateiname = rec.get("dateiname")
        sha = rec.get("sha256")
        status = rec.get("status")
        if not isinstance(dateiname, str) or not dateiname or not isinstance(sha, str):
            raise ZustandsFehler("state_unlesbar", f"Upload {schluessel} hat keinen Dateinamen/Hash.")
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.csv", dateiname):
            raise ZustandsFehler("state_unlesbar", f"Upload {schluessel} hat einen ungültigen Dateinamen.")
        pfad: Path | None = None
        for relativ in (rec.get("staged_path"), f"staging/{dateiname}", f"sent/{dateiname}"):
            if not isinstance(relativ, str) or not relativ:
                continue
            kandidat = _sicherer_pfad(root, relativ)
            if kandidat.is_file():
                pfad = kandidat
                break
        if pfad is None:
            if status in OFFENE_STATUS:
                raise ZustandsFehler("datei_fehlt", f"Datei für offenen Upload {schluessel} fehlt.")
            continue
        try:
            ist_sha = _sha256_datei(pfad)
        except OSError as exc:
            raise ZustandsFehler("datei_fehlt", f"{pfad.name} ist nicht lesbar: {exc}") from exc
        if ist_sha != sha:
            raise ZustandsFehler(
                "hash_mismatch",
                f"Hash von {pfad.name} passt nicht zum Zustand ({schluessel}).",
            )


def _speichere_zustand(cfg: ClientKonfiguration, zustand: dict[str, Any]) -> None:
    root = _root(cfg)
    root.mkdir(parents=True, exist_ok=True)
    pfad = root / "state.json"
    tmp = root / "state.json.tmp"
    text = json.dumps(zustand, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        if pfad.exists():
            try:
                json.loads(pfad.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                pass
            else:
                shutil.copy2(pfad, root / "state.json.bak")
        tmp.write_text(text, encoding="utf-8")
        with tmp.open("rb+") as datei:
            os.fsync(datei.fileno())
        os.replace(tmp, pfad)
    except OSError as exc:
        raise ZustandsFehler("state_schreiben", f"state.json ist nicht schreibbar: {exc}") from exc


def _status_schreiben(cfg: ClientKonfiguration, status: str, grund: str | None = None,
                      details: Mapping[str, Any] | None = None) -> None:
    root = _root(cfg)
    try:
        root.mkdir(parents=True, exist_ok=True)
        daten = {
            "aktualisiert": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "grund": grund,
            "details": dict(details or {}),
        }
        tmp = root / "status.json.tmp"
        tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, root / "status.json")
    except OSError as exc:
        print(f"WARNUNG status.json nicht schreibbar: {exc}", file=sys.stderr)


def _log(cfg: ClientKonfiguration, ereignis: str, **felder: Any) -> None:
    root = _root(cfg)
    try:
        (root / "logs").mkdir(parents=True, exist_ok=True)
        zeile = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "ereignis": ereignis,
            **{k: v for k, v in felder.items() if v is not None},
        }
        with (root / "logs" / "transport.jsonl").open("a", encoding="utf-8") as datei:
            datei.write(json.dumps(zeile, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError as exc:
        print(f"WARNUNG Log nicht schreibbar: {exc}", file=sys.stderr)


class Dateisperre:
    """Prozessübergreifende Sperre ohne veraltete Lockfile-Reste."""

    def __init__(self, pfad: Path) -> None:
        self.pfad = pfad
        self._datei: Any = None

    def erwerben(self) -> bool:
        self.pfad.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._datei = self.pfad.open("a+b")
            self._datei.seek(0, os.SEEK_END)
            if self._datei.tell() == 0:
                self._datei.write(b"\0")
                self._datei.flush()
            self._datei.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._datei.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._datei.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, ImportError):
            self.freigeben()
            return False

    def freigeben(self) -> None:
        if self._datei is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._datei.seek(0)
                msvcrt.locking(self._datei.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._datei.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass
        finally:
            self._datei.close()
            self._datei = None


class HttpSender:
    """Stdlib-HTTP; Header und Token werden nie geloggt."""

    def send(self, url: str, body: bytes, headers: Mapping[str, str],
             timeout: float) -> HttpAntwort:
        anfrage = Request(url, data=body, headers=dict(headers), method="POST")  # noqa: S310
        try:
            with build_opener(_KeineWeiterleitung()).open(anfrage, timeout=timeout) as antwort:
                return HttpAntwort(antwort.status, dict(antwort.headers), antwort.read())
        except HTTPError as exc:
            return HttpAntwort(exc.code, dict(exc.headers or {}), exc.read())
        except (URLError, TimeoutError, OSError) as exc:
            raise NetzwerkFehler(str(exc)) from exc


def _header(wert: Mapping[str, str], name: str) -> str | None:
    for schluessel, inhalt in wert.items():
        if schluessel.lower() == name.lower():
            return inhalt
    return None


def _retry_after(antwort: HttpAntwort) -> int | None:
    roh = _header(antwort.headers, "Retry-After")
    if roh is None:
        return None
    try:
        return max(1, int(roh.strip()))
    except ValueError:
        return None


def _klassifiziere(antwort: HttpAntwort) -> Klassifikation:
    daten = antwort.json()
    code = str(daten.get("code") or "") if daten else ""
    retry = _retry_after(antwort)
    if antwort.status == 200:
        if daten and daten.get("ok") is True and code in {"importiert", "bereits_vorhanden"}:
            return Klassifikation("erfolg", code, daten)
        return Klassifikation("transient", "antwort_ungueltig", daten, retry_after=retry)
    if antwort.status == 409:
        if code == "bootstrap_erforderlich":
            return Klassifikation("blockiert", "bootstrap", daten)
        if code == "daten_veraltet":
            return Klassifikation("blockiert", "daten_veraltet", daten)
        if code == "import_belegt":
            return Klassifikation("transient", "import_belegt", daten, retry_after=retry)
        return Klassifikation("blockiert", "server_409", daten)
    if antwort.status in {401, 403}:
        return Klassifikation("global", "auth", daten, global_stopp=True)
    if antwort.status in {400, 413, 415}:
        quarantaene = antwort.status in {413, 415} or code in {"datenqualitaet", "hash_mismatch"}
        return Klassifikation("blockiert", code or f"server_{antwort.status}", daten,
                              quarantaene=quarantaene)
    if antwort.status == 503 and code == "transport_deaktiviert":
        return Klassifikation("global", "transport_deaktiviert", daten, global_stopp=True)
    if antwort.status == 429 or antwort.status >= 500:
        return Klassifikation("transient", f"server_{antwort.status}", daten, retry_after=retry)
    return Klassifikation("blockiert", f"server_{antwort.status}", daten)


def _wartezeit(cfg: ClientKonfiguration, retry_after: int | None) -> float:
    basis = cfg.retry.basis_sekunden if retry_after is None else float(retry_after)
    if cfg.retry.jitter_sekunden > 0:
        basis += secrets.SystemRandom().uniform(0.0, cfg.retry.jitter_sekunden)
    return max(0.0, min(basis, float(cfg.retry.retry_after_max_sekunden)))


def _upload_schluessel(symbol: str, zeitrahmen: str, tag: date) -> str:
    return f"{symbol}|{zeitrahmen}|{tag.isoformat()}"


def _upload_fuer(zustand: Mapping[str, Any], symbol: str, zeitrahmen: str,
                 tag: date) -> dict[str, Any] | None:
    wert = zustand["uploads"].get(_upload_schluessel(symbol, zeitrahmen, tag))
    return wert if isinstance(wert, dict) else None


def _blockiere_ohne_datei(cfg: ClientKonfiguration, zustand: dict[str, Any],
                          symbol: str, zeitrahmen: str, tag: date, grund: str) -> None:
    """Merkt einen dauerhaften Fehler auch dann, wenn noch keine Datei entstand."""
    key = _upload_schluessel(symbol, zeitrahmen, tag)
    rec = zustand["uploads"].get(key)
    if not isinstance(rec, dict):
        rec = {
            "symbol": symbol,
            "zeitrahmen": zeitrahmen,
            "handelstag": tag.isoformat(),
            "dateiname": _dateiname(symbol, zeitrahmen, tag),
            "sha256": "",
            "staged_path": None,
            "letzte_kerze": None,
        }
        zustand["uploads"][key] = rec
    rec["status"] = "blockiert"
    rec["grund"] = grund
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()
    _speichere_zustand(cfg, zustand)


def _offener_upload(zustand: Mapping[str, Any], symbol: str, zeitrahmen: str) -> dict[str, Any] | None:
    offen = [rec for rec in zustand["uploads"].values()
             if isinstance(rec, dict) and rec.get("symbol") == symbol
             and rec.get("zeitrahmen") == zeitrahmen and rec.get("status") in OFFENE_STATUS]
    if not offen:
        return None
    return sorted(offen, key=lambda rec: str(rec.get("handelstag", "")), reverse=True)[0]


def _datei_fuer_upload(cfg: ClientKonfiguration, rec: Mapping[str, Any]) -> Path | None:
    root = _root(cfg)
    dateiname = str(rec.get("dateiname") or "")
    for relativ in (rec.get("staged_path"), f"staging/{dateiname}", f"sent/{dateiname}"):
        if isinstance(relativ, str) and relativ:
            p = _sicherer_pfad(root, relativ)
            if p.is_file():
                return p
    return None


def _relativ(cfg: ClientKonfiguration, pfad: Path) -> str:
    try:
        return pfad.resolve().relative_to(_root(cfg).resolve()).as_posix()
    except ValueError as exc:
        raise ZustandsFehler("state_schreiben", f"{pfad} liegt ausserhalb des Zustandsordners.") from exc


def _nach_sent(cfg: ClientKonfiguration, rec: dict[str, Any]) -> None:
    root = _root(cfg)
    dateiname = str(rec["dateiname"])
    ziel = root / "sent" / dateiname
    quelle = _datei_fuer_upload(cfg, rec)
    if quelle is None:
        return
    try:
        ziel.parent.mkdir(parents=True, exist_ok=True)
        if quelle.resolve() == ziel.resolve():
            rec["staged_path"] = _relativ(cfg, ziel)
            return
        if ziel.exists():
            if _sha256_datei(ziel) != rec["sha256"]:
                raise ZustandsFehler("hash_mismatch", f"sent/{dateiname} hat einen anderen Hash.")
            quelle.unlink()
        else:
            os.replace(quelle, ziel)
        rec["staged_path"] = _relativ(cfg, ziel)
    except OSError as exc:
        _log(cfg, "sent_verschieben_fehlgeschlagen", datei=dateiname, fehler=str(exc))


def _synchronisiere_sent(cfg: ClientKonfiguration, zustand: dict[str, Any]) -> bool:
    geaendert = False
    for rec in zustand["uploads"].values():
        if isinstance(rec, dict) and rec.get("status") in ERFOLGS_STATUS:
            vorher = rec.get("staged_path")
            _nach_sent(cfg, rec)
            geaendert = geaendert or rec.get("staged_path") != vorher
    return geaendert


def _quarantaene(cfg: ClientKonfiguration, rec: dict[str, Any], fehler: str) -> None:
    root = _root(cfg)
    dateiname = str(rec["dateiname"])
    zielordner = root / "quarantine"
    zielordner.mkdir(parents=True, exist_ok=True)
    ziel = zielordner / dateiname
    quelle = _datei_fuer_upload(cfg, rec)
    try:
        if quelle is not None and quelle.resolve() != ziel.resolve():
            if ziel.exists():
                ziel = zielordner / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{dateiname}"
            os.replace(quelle, ziel)
        rec["staged_path"] = _relativ(cfg, ziel)
        fehler_datei = ziel.with_name(ziel.name + ".error.json")
        fehler_datei.write_text(
            json.dumps({"fehler": fehler, "zeit": datetime.now(timezone.utc).isoformat()},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        _log(cfg, "quarantaene_fehlgeschlagen", datei=dateiname, fehler=str(exc))


def _sende(cfg: ClientKonfiguration, sender: Any, rec: dict[str, Any], pfad: Path,
           token: str, zustand: dict[str, Any], schlaf: Callable[[float], None]) -> Klassifikation:
    body = pfad.read_bytes()
    if len(body) > cfg.endpoint.max_bytes:
        raise SerienFehler("datei_zu_gross", "Die Tagesdatei überschreitet die Grösse des Endpunkts.",
                           quarantaene=True)
    sha = hashlib.sha256(body).hexdigest()
    if sha != rec["sha256"]:
        raise ZustandsFehler("hash_mismatch", f"{pfad.name} hat sich seit dem Staging verändert.")
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Orakel-Key-Id": cfg.endpoint.key_id,
        "X-Orakel-Content-SHA256": sha,
        "X-Orakel-Dateiname": rec["dateiname"],
        "X-Orakel-Request-Id": rec.get("request_id") or uuid.uuid4().hex,
        "Content-Type": "text/csv",
        "Content-Length": str(len(body)),
    }
    rec["request_id"] = headers["X-Orakel-Request-Id"]
    for versuch in range(1, cfg.retry.http_versuche + 1):
        if int(rec.get("versuche") or 0) >= MAX_VERSUCHE:
            raise SerienFehler("budget", "Das Tagesbudget von sechs HTTP-Versuchen ist verbraucht.")
        rec["versuche"] = int(rec.get("versuche") or 0) + 1
        rec["status"] = "wartend"
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        _speichere_zustand(cfg, zustand)
        try:
            antwort = sender.send(cfg.endpoint.url, body, headers, cfg.endpoint.timeout_sekunden)
        except NetzwerkFehler as exc:
            if versuch < cfg.retry.http_versuche:
                schlaf(_wartezeit(cfg, None))
                continue
            return Klassifikation("transient", "netzwerk", None)
        klass = _klassifiziere(antwort)
        rec["http_status"] = antwort.status
        rec["server_code"] = klass.grund
        if klass.art == "erfolg":
            return klass
        if klass.art == "transient" and versuch < cfg.retry.http_versuche:
            schlaf(_wartezeit(cfg, klass.retry_after))
            continue
        return klass
    return Klassifikation("transient", "unbekannt", None)


def _server_kennzahlen(rec: dict[str, Any], klass: Klassifikation) -> None:
    daten = klass.daten or {}
    rec["server_sha256"] = daten.get("sha256")
    rec["warnungen"] = list(daten.get("warnungen") or [])
    rec["server_code"] = daten.get("code") or klass.grund


def _verarbeite_serie(cfg: ClientKonfiguration, zustand: dict[str, Any], mt5: Any,
                      sender: Any, symbol: str, zeitrahmen: str, token: str,
                      jetzt: datetime, schlaf: Callable[[float], None]) -> int:
    offen = _offener_upload(zustand, symbol, zeitrahmen)
    if offen is not None:
        tag = date.fromisoformat(str(offen["handelstag"]))
        rec = offen
        pfad = _datei_fuer_upload(cfg, rec)
        if pfad is None:
            raise ZustandsFehler("datei_fehlt", f"Offene Datei für {symbol} {zeitrahmen} fehlt.")
        letzte = str(rec.get("letzte_kerze") or "")
        if letzte:
            try:
                letzte_zeit = datetime.fromisoformat(letzte)
            except ValueError as exc:
                raise ZustandsFehler("state_unlesbar", "Ungültiger letzter Kerzenzeitstempel im Zustand.") from exc
            try:
                _pruefe_frische_zeit(letzte_zeit, tag, zeitrahmen, cfg, jetzt)
            except SerienFehler as exc:
                rec["status"] = "blockiert"
                rec["grund"] = exc.grund
                rec["updated_at"] = datetime.now(timezone.utc).isoformat()
                _speichere_zustand(cfg, zustand)
                raise
    else:
        tag, kerzen = _finde_zieltag(mt5, symbol, zeitrahmen, cfg, jetzt)
        erfolg = _upload_fuer(zustand, symbol, zeitrahmen, tag)
        if erfolg is not None and erfolg.get("status") in ERFOLGS_STATUS:
            _log(cfg, "tag_bereits_erfolgreich", symbol=symbol, zeitrahmen=zeitrahmen, tag=str(tag))
            return 0
        if erfolg is not None and erfolg.get("status") in {"blockiert", "quarantaene"}:
            _log(cfg, "tag_blockiert", symbol=symbol, zeitrahmen=zeitrahmen, tag=str(tag),
                 grund=erfolg.get("grund"))
            return 3
        _pruefe_tagesblock(kerzen, tag, zeitrahmen, cfg)
        try:
            _pruefe_frische(kerzen[-1], tag, zeitrahmen, cfg, jetzt)
        except SerienFehler as exc:
            _blockiere_ohne_datei(cfg, zustand, symbol, zeitrahmen, tag, exc.grund)
            raise
        body = _csv_bytes(kerzen)
        if len(body) > cfg.endpoint.max_bytes:
            raise SerienFehler("datei_zu_gross", "Die Tagesdatei überschreitet die Grösse des Endpunkts.",
                               quarantaene=True)
        dateiname = _dateiname(symbol, zeitrahmen, tag)
        staging = _root(cfg) / "staging" / dateiname
        staging.parent.mkdir(parents=True, exist_ok=True)
        tmp = staging.with_name(staging.name + ".part")
        try:
            tmp.write_bytes(body)
            with tmp.open("rb+") as datei:
                os.fsync(datei.fileno())
            os.replace(tmp, staging)
        except OSError as exc:
            raise ZustandsFehler("staging_schreiben", f"Staging-Datei nicht schreibbar: {exc}") from exc
        rec = {
            "symbol": symbol,
            "zeitrahmen": zeitrahmen,
            "handelstag": tag.isoformat(),
            "dateiname": dateiname,
            "sha256": hashlib.sha256(body).hexdigest(),
            "staged_path": f"staging/{dateiname}",
            "status": "vorbereitet",
            "grund": None,
            "versuche": 0,
            "http_status": None,
            "server_code": None,
            "server_sha256": None,
            "request_id": None,
            "warnungen": [],
            "letzte_kerze": kerzen[-1].zeit.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        }
        zustand["uploads"][_upload_schluessel(symbol, zeitrahmen, tag)] = rec
        _speichere_zustand(cfg, zustand)
        pfad = staging

    try:
        klass = _sende(cfg, sender, rec, pfad, token, zustand, schlaf)
    except SerienFehler as exc:
        rec["status"] = "quarantaene" if exc.quarantaene else "blockiert"
        rec["grund"] = exc.grund
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        if exc.quarantaene:
            _quarantaene(cfg, rec, exc.grund)
        _speichere_zustand(cfg, zustand)
        raise
    _server_kennzahlen(rec, klass)
    if klass.art == "erfolg":
        rec["status"] = "erfolgreich_degraded" if any(
            "Teilwiederherstellung" in str(w) for w in rec.get("warnungen", [])) else "erfolgreich"
        rec["grund"] = None
        rec["completed_at"] = datetime.now(timezone.utc).isoformat()
        rec["updated_at"] = rec["completed_at"]
        serie = zustand["serien"].setdefault(f"{symbol}|{zeitrahmen}", {})
        serie["symbol"] = symbol
        serie["zeitrahmen"] = zeitrahmen
        serie["letzter_erfolgreicher_handelstag"] = rec["handelstag"]
        serie["letzte_server_sha256"] = rec.get("server_sha256") or rec["sha256"]
        _speichere_zustand(cfg, zustand)
        _nach_sent(cfg, rec)
        _speichere_zustand(cfg, zustand)
        _log(cfg, "upload_erfolg", symbol=symbol, zeitrahmen=zeitrahmen,
             tag=rec["handelstag"], status=rec["status"], code=rec.get("server_code"))
        # Der Block ist gebucht; degraded ist ein Alarm, kein Retry-Grund.
        return 0
    if klass.art == "transient":
        rec["status"] = "wartend"
        rec["grund"] = klass.grund
        rec["updated_at"] = datetime.now(timezone.utc).isoformat()
        _speichere_zustand(cfg, zustand)
        _log(cfg, "upload_transient", symbol=symbol, zeitrahmen=zeitrahmen,
             tag=rec["handelstag"], grund=klass.grund, versuche=rec.get("versuche"))
        raise TransientFehler(klass.grund, f"{symbol} {zeitrahmen}: transienter Fehler {klass.grund}.")
    rec["status"] = "quarantaene" if klass.quarantaene else "blockiert"
    rec["grund"] = klass.grund
    rec["updated_at"] = datetime.now(timezone.utc).isoformat()
    if klass.quarantaene:
        _quarantaene(cfg, rec, klass.grund)
    _speichere_zustand(cfg, zustand)
    _log(cfg, "upload_blockiert", symbol=symbol, zeitrahmen=zeitrahmen,
         tag=rec["handelstag"], grund=klass.grund)
    if klass.global_stopp:
        raise GlobalFehler(klass.grund, f"{symbol} {zeitrahmen}: {klass.grund}; Lauf gestoppt.")
    raise SerienFehler(klass.grund, f"{symbol} {zeitrahmen}: {klass.grund}.",
                       quarantaene=klass.quarantaene)


def _terminal() -> Any:
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise Mt5Fehler(
            "mt5_fehlt",
            "MetaTrader5 fehlt. Das Paket gibt es nur für Windows (64-Bit-Python) "
            "und es braucht ein laufendes, angemeldetes MT5-Terminal.",
        ) from exc
    return mt5


def _starte_mt5(mt5: Any, cfg: ClientKonfiguration) -> None:
    pfad = {"path": cfg.export.terminal_pfad} if cfg.export.terminal_pfad else {}
    try:
        ok = mt5.initialize(**pfad)
    except (OSError, RuntimeError) as exc:
        raise Mt5Fehler("mt5_start", f"MT5-Terminal nicht erreichbar: {exc}") from exc
    if not ok:
        raise Mt5Fehler("mt5_start", "MT5-Terminal nicht erreichbar oder nicht angemeldet.")


def _token(cfg: ClientKonfiguration) -> str:
    wert = os.environ.get(cfg.endpoint.token_env, "").strip()
    if not wert:
        raise GlobalFehler("auth", f"Umgebungsvariable {cfg.endpoint.token_env} fehlt.")
    return wert


def _aufraeumen(cfg: ClientKonfiguration) -> None:
    root = _root(cfg)
    jetzt = datetime.now(timezone.utc)
    for ordner, tage in (("sent", cfg.state.sent_aufbewahrung_tage),
                         ("quarantine", cfg.state.quarantaene_aufbewahrung_tage),
                         ("logs", cfg.state.logs_aufbewahrung_tage)):
        pfad = root / ordner
        if not pfad.is_dir():
            continue
        for datei in pfad.iterdir():
            if not datei.is_file():
                continue
            try:
                alter = (jetzt - datetime.fromtimestamp(datei.stat().st_mtime, timezone.utc)).days
                if alter > tage:
                    datei.unlink()
            except OSError:
                continue


def run(cfg: ClientKonfiguration, *, mt5: Any = None, sender: Any = None,
        jetzt: datetime | None = None, schlaf: Callable[[float], None] = time_mod.sleep,
        token: str | None = None) -> int:
    """Führt genau einen Lauf aus und liefert den definierten Exit-Code."""
    jetzt = jetzt or datetime.now(timezone.utc)
    root = _root(cfg)
    root.mkdir(parents=True, exist_ok=True)
    sperre = Dateisperre(root / "lock")
    if not sperre.erwerben():
        _log(cfg, "lauf_bereits_aktiv")
        return 0
    mt5_obj = mt5
    gestartet = False
    try:
        try:
            zustand = _lade_zustand(cfg)
            if _synchronisiere_sent(cfg, zustand):
                _speichere_zustand(cfg, zustand)
            token_wert = token or _token(cfg)
            if mt5_obj is None:
                mt5_obj = _terminal()
                _starte_mt5(mt5_obj, cfg)
                gestartet = True
            _aufraeumen(cfg)
            sender = sender or HttpSender()
            codes: list[int] = []
            for symbol in cfg.export.symbole:
                if not mt5_obj.symbol_select(symbol, True):
                    raise Mt5Fehler("mt5_symbol", f"Symbol {symbol} nicht im Market Watch.")
                for zeitrahmen in cfg.export.zeitrahmen:
                    try:
                        codes.append(_verarbeite_serie(
                            cfg, zustand, mt5_obj, sender, symbol, zeitrahmen,
                            token_wert, jetzt, schlaf,
                        ))
                    except TransientFehler as exc:
                        codes.append(2)
                        _log(cfg, "serie_transient", symbol=symbol, zeitrahmen=zeitrahmen, grund=exc.grund)
                    except SerienFehler as exc:
                        codes.append(3)
                        _log(cfg, "serie_blockiert", symbol=symbol, zeitrahmen=zeitrahmen, grund=exc.grund)
            gesamt = 0
            if 5 in codes:
                gesamt = 5
            elif 4 in codes:
                gesamt = 4
            elif 3 in codes:
                gesamt = 3
            elif 2 in codes:
                gesamt = 2
            _status_schreiben(cfg, {0: "erfolg", 2: "transient", 3: "blockiert",
                                    4: "mt5_nicht_verfuegbar", 5: "fehler"}[gesamt],
                              details={"codes": codes, "serien": zustand.get("serien", {})})
            return gesamt
        except ZustandsFehler as exc:
            _status_schreiben(cfg, "state_reparatur_erforderlich", exc.grund)
            _log(cfg, "zustandsfehler", grund=exc.grund, text=exc.text)
            print(f"FEHLER {exc.text}", file=sys.stderr)
            return 5
        except KonfigurationsFehler as exc:
            _status_schreiben(cfg, "blockiert", exc.grund)
            _log(cfg, "konfigurationsfehler", grund=exc.grund, text=exc.text)
            print(f"FEHLER {exc.text}", file=sys.stderr)
            return 3
        except Mt5Fehler as exc:
            _status_schreiben(cfg, "mt5_nicht_verfuegbar", exc.grund)
            _log(cfg, "mt5_fehler", grund=exc.grund, text=exc.text)
            print(f"FEHLER {exc.text}", file=sys.stderr)
            return 4
        except GlobalFehler as exc:
            _status_schreiben(cfg, "blockiert", exc.grund)
            _log(cfg, "globaler_stopp", grund=exc.grund, text=exc.text)
            print(f"FEHLER {exc.text}", file=sys.stderr)
            return exc.code
    finally:
        if gestartet and mt5_obj is not None:
            try:
                mt5_obj.shutdown()
            except (OSError, RuntimeError):
                pass
        sperre.freigeben()


def _initialisiere_state(cfg: ClientKonfiguration) -> int:
    root = _root(cfg)
    root.mkdir(parents=True, exist_ok=True)
    if _dateien_vorhanden(cfg):
        print("FEHLER state.json fehlt, aber staging/ oder sent/ enthält Dateien. "
              "Zuerst Dateien prüfen und manuell nach quarantine/ verschieben.", file=sys.stderr)
        _status_schreiben(cfg, "state_reparatur_erforderlich", "state_fehlt")
        return 5
    if (root / "state.json").exists():
        print("FEHLER state.json existiert bereits; --init-state überschreibt nichts.", file=sys.stderr)
        return 5
    sperre = Dateisperre(root / "lock")
    if not sperre.erwerben():
        return 0
    try:
        _speichere_zustand(cfg, _leerer_zustand(cfg.config_hash))
        _status_schreiben(cfg, "erfolg", details={"hinweis": "leerer Zustand angelegt"})
        print(f"Leerer Zustand angelegt: {root / 'state.json'}")
        return 0
    finally:
        sperre.freigeben()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Abgeschlossene MT5-Tagesblöcke einmalig zum Orakel-Server hochladen."
    )
    parser.add_argument("--config", required=True, help="Pfad zur TOML-Konfiguration")
    parser.add_argument("--once", action="store_true", help="genau einen Lauf ausführen (Standard)")
    parser.add_argument("--init-state", action="store_true",
                        help="leeren Zustand nur bei leeren staging-/sent-Ordnern anlegen")
    parser.add_argument("--check-config", action="store_true",
                        help="Konfiguration prüfen, ohne MT5 oder HTTP zu starten")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except KonfigurationsFehler as exc:
        print(f"FEHLER {exc.text}", file=sys.stderr)
        return 3
    if args.check_config:
        print(
            f"Konfiguration gültig: {cfg.endpoint.url}, Symbole {', '.join(cfg.export.symbole)}, "
            f"Zeitrahmen {', '.join(cfg.export.zeitrahmen)}, Zustand {cfg.state.pfad}"
        )
        return 0
    if args.init_state:
        return _initialisiere_state(cfg)
    return run(cfg)


if __name__ == "__main__":
    raise SystemExit(main())