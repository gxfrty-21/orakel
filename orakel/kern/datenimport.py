"""Gemeinsamer, idempotenter CSV-Import für CLI und Ordnerquelle.

Beide Importpfade buchen dieselbe SHA-256-Prüfsumme in ``datenimporte`` und
verwenden dieselbe Frischeprüfung. Der Aufrufer bestimmt die Transaktion:
die CLI importiert eine Datei je Transaktion, die Ordnerquelle alle Dateien
gemeinsam. Ein Fehler oder eine zu alte Datei rollt die jeweilige Transaktion
zurück, sodass keine halben Importe entstehen.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .data import frische_kennzahl, lade_csv_bloecke, mit_taktpruefung
from .db import Facts, Kerzenkonflikte


class FrischeFehler(ValueError):
    """Die jüngste Kerze einer Datei ist älter als die Frischegrenze."""


def internes_symbol(symbol: str, daten_cfg: dict[str, Any]) -> str:
    """Bildet einen Broker-Namen explizit auf das interne Symbol ab.

    Broker hängen oft Suffixe an (``EURUSDm``, ``EURUSD.a``). Eine automatische
    Suffix-Erkennung wäre gefährlich, weil sie verschiedene Instrumente
    vermischen kann. Deshalb gilt ausschliesslich die in ``[daten.symbol_map]``
    hinterlegte, explizite Zuordnung; ohne Eintrag bleibt der Name unverändert.
    """
    roh = str(symbol).strip().upper()
    mapping = {
        str(broker).strip().upper(): str(intern).strip().upper()
        for broker, intern in (daten_cfg.get("symbol_map") or {}).items()
    }
    ziel = mapping.get(roh, roh)
    return ziel or roh


class ParallelerImport(RuntimeError):
    """Eine andere Transaktion hat dieselbe Quelle gleichzeitig gebucht."""

    def __init__(self, sha256: str) -> None:
        super().__init__(
            "Dieselbe Datei wurde parallel importiert; der Import wurde "
            "zurückgerollt."
        )
        self.sha256 = sha256


@dataclass(slots=True)
class ImportErgebnis:
    """Was mit einer Datei geschehen ist; alle Zahlen stammen aus der DB."""

    datei: str
    symbol: str
    zeitrahmen: str
    sha256: str
    kerzen: int
    von: str
    bis: str
    kennzahl: dict[str, Any] | None
    uebersprungen: bool
    konflikte: Kerzenkonflikte = field(default_factory=Kerzenkonflikte)


def datei_sha256(pfad: str | Path) -> str:
    """SHA-256 der Rohdatei; Grundlage für den idempotenten Import."""
    summe = hashlib.sha256()
    with Path(pfad).open("rb") as datei:
        for block in iter(lambda: datei.read(1024 * 1024), b""):
            summe.update(block)
    return summe.hexdigest()


def versatz_schluessel(versatz: float | None) -> str:
    """Normalisiert den Broker-Versatz für den eindeutigen Import-Schlüssel."""
    if versatz is None:
        return ""
    return f"{float(versatz):g}"


def frische_text(kennzahl: dict[str, Any]) -> str:
    return (f"jüngste Kerze {kennzahl['alter_stunden']:.1f} h alt "
            f"(Grenze {kennzahl['max_alter_stunden']:.1f} h)")


def _pruefe_max_alter(max_alter_stunden: float | None) -> None:
    if max_alter_stunden is not None and (
            not math.isfinite(max_alter_stunden) or max_alter_stunden <= 0):
        raise ValueError("--max-alter-stunden muss grösser als 0 sein.")


def vorhandener_import(
    db: Facts, sha256: str, symbol: str, zeitrahmen: str, *,
    daten_cfg: dict[str, Any], zeitzone: str | None = None,
    versatz: float | None = None, max_alter_stunden: float | None = None,
    frisch: bool = False, c: sqlite3.Connection | None = None,
) -> ImportErgebnis | None:
    """Liefert die vorhandene Buchung oder ``None``; prüft dabei das Gate."""
    _pruefe_max_alter(max_alter_stunden)
    zeile = db.datenimport_finden(
        sha256, symbol, zeitrahmen, zeitzone or "", versatz_schluessel(versatz),
        c=c)
    if zeile is None:
        return None
    # Ein Ledger-Eintrag allein beweist keine Kerzen. Nach einem Teil-Restore
    # kann die Buchung vorhanden sein, obwohl Zeilen fehlen; dann muss die
    # Quelle erneut importiert werden. Innerhalb einer Transaktion wird die
    # alte Buchung entfernt, damit der neue Eintrag denselben Schlüssel nutzen
    # kann; ausserhalb bleibt die Reparatur dem nächsten Import überlassen.
    if not db.kerzen_abgedeckt(
            symbol, zeitrahmen, mindest=int(zeile["kerzen"] or 0),
            bis=str(zeile["bis"] or ""), von=str(zeile["von"] or ""), c=c):
        if c is not None:
            db.datenimport_entfernen(int(zeile["id"]), c=c)
        return None
    kennzahl = frische_kennzahl(
        zeile["bis"], daten_cfg, zeitrahmen,
        max_alter_stunden=max_alter_stunden)
    if (frisch or max_alter_stunden is not None) and kennzahl and not kennzahl["frisch"]:
        raise FrischeFehler(
            f"{frische_text(kennzahl)} — Daten veraltet; Import abgelehnt.")
    return ImportErgebnis(
        datei=zeile["datei"], symbol=symbol, zeitrahmen=zeitrahmen,
        sha256=sha256, kerzen=int(zeile["kerzen"]), von=zeile["von"],
        bis=zeile["bis"], kennzahl=kennzahl, uebersprungen=True)


def importiere_datei(
    db: Facts, datei: str | Path, symbol: str, zeitrahmen: str, *,
    daten_cfg: dict[str, Any], zeitzone: str | None = None,
    versatz: float | None = None, max_alter_stunden: float | None = None,
    frisch: bool = False, c: sqlite3.Connection | None = None,
    konflikte: Kerzenkonflikte | None = None,
) -> ImportErgebnis:
    """Importiert eine CSV idempotent; ohne ``c`` in einer eigenen Transaktion."""
    _pruefe_max_alter(max_alter_stunden)
    pfad = Path(datei)
    if c is not None:
        return _importiere_auf_verbindung(
            db, pfad, symbol, zeitrahmen, daten_cfg=daten_cfg,
            zeitzone=zeitzone, versatz=versatz,
            max_alter_stunden=max_alter_stunden, frisch=frisch,
            c=c, konflikte=konflikte)
    with db.conn() as verbindung:
        return _importiere_auf_verbindung(
            db, pfad, symbol, zeitrahmen, daten_cfg=daten_cfg,
            zeitzone=zeitzone, versatz=versatz,
            max_alter_stunden=max_alter_stunden, frisch=frisch,
            c=verbindung, konflikte=konflikte)


def _importiere_auf_verbindung(
    db: Facts, pfad: Path, symbol: str, zeitrahmen: str, *,
    daten_cfg: dict[str, Any], zeitzone: str | None,
    versatz: float | None, max_alter_stunden: float | None,
    frisch: bool, c: sqlite3.Connection,
    konflikte: Kerzenkonflikte | None,
) -> ImportErgebnis:
    datei_hash = datei_sha256(pfad)
    vorhanden = vorhandener_import(
        db, datei_hash, symbol, zeitrahmen, daten_cfg=daten_cfg,
        zeitzone=zeitzone, versatz=versatz,
        max_alter_stunden=max_alter_stunden, frisch=frisch, c=c)
    if vorhanden is not None:
        return vorhanden

    konflikte = konflikte or Kerzenkonflikte()
    min_ts = None
    max_ts = None

    def bloecke():
        nonlocal min_ts, max_ts
        for block in mit_taktpruefung(
                lade_csv_bloecke(pfad, server_zeitzone=zeitzone,
                                 server_versatz_stunden=versatz),
                zeitrahmen):
            if not block.empty:
                block_min = block["ts"].min()
                block_max = block["ts"].max()
                if min_ts is None or block_min < min_ts:
                    min_ts = block_min
                if max_ts is None or block_max > max_ts:
                    max_ts = block_max
            yield block

    n = db.kerzen_speichern_bloecke(
        symbol, zeitrahmen, bloecke(), konflikte=konflikte, c=c)
    if not n:
        raise ValueError(f"CSV: {pfad.name} enthält keine vollständigen Kerzen.")
    kennzahl = frische_kennzahl(
        max_ts, daten_cfg, zeitrahmen,
        max_alter_stunden=max_alter_stunden)
    if (frisch or max_alter_stunden is not None) and kennzahl and not kennzahl["frisch"]:
        raise FrischeFehler(
            f"{frische_text(kennzahl)} — Daten veraltet; Import abgelehnt.")
    try:
        db.datenimport_merken(
            sha256=datei_hash, datei=pfad.name, symbol=symbol,
            zeitrahmen=zeitrahmen, zeitzone=zeitzone or "",
            versatz=versatz_schluessel(versatz), kerzen=n,
            von=str(min_ts), bis=str(max_ts), c=c)
    except sqlite3.IntegrityError as exc:
        raise ParallelerImport(datei_hash) from exc
    return ImportErgebnis(
        datei=pfad.name, symbol=symbol, zeitrahmen=zeitrahmen,
        sha256=datei_hash, kerzen=n, von=str(min_ts), bis=str(max_ts),
        kennzahl=kennzahl, uebersprungen=False, konflikte=konflikte)