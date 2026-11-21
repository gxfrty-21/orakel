#!/usr/bin/env python3
"""Holt MT5-Historie direkt aus dem laufenden Terminal und schreibt MT5-CSV.

Läuft nur unter Windows: Das Paket ``MetaTrader5`` spricht per IPC mit einem
installierten, angemeldeten Terminal. Es steht deshalb bewusst nicht in
``requirements.txt``; die Installation erfolgt im venv des Windows-Rechners.
Geschrieben wird genau das Format, das ``orakel daten --csv`` liest.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

WURZEL = Path(__file__).resolve().parents[1]
RAHMEN = ("M1", "M5", "M15", "H1")
KOPFZEILE = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"


class AbrufFehler(RuntimeError):
    """Fehler, den das Skript als Meldung statt als Traceback ausgibt."""


def _terminal() -> Any:
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise AbrufFehler(
            "MetaTrader5 fehlt. Das Paket gibt es nur für Windows (64-Bit-Python) "
            "und es braucht ein laufendes, angemeldetes MT5-Terminal. "
            "Installation im Windows-venv: python -m pip install MetaTrader5"
        ) from exc
    return mt5


def _letzter_fehler(mt5: Any) -> str:
    fehler = getattr(mt5, "last_error", lambda: None)()
    return f"{fehler}" if fehler else "ohne Meldung"


def _sekunden(tag: date, *, tagesende: bool = False) -> int:
    zeit = time(23, 59, 59) if tagesende else time(0, 0, 0)
    return int(datetime.combine(tag, zeit, tzinfo=timezone.utc).timestamp())


def _zeitraeume(von: date, bis: date, raster: str) -> Iterator[tuple[int, int]]:
    """Zerlegt den Bereich in Monats- oder Jahresfenster.

    Das Terminal liefert nur geladene Kerzen; kleinere Fenster fragen weniger
    auf einmal ab und umgehen die Grenze aus «Max. bars in chart».
    """
    lauf = date(von.year, von.month, 1) if raster == "monat" else date(von.year, 1, 1)
    while lauf <= bis:
        if raster == "monat":
            naechster = date(lauf.year + lauf.month // 12, lauf.month % 12 + 1, 1)
        else:
            naechster = date(lauf.year + 1, 1, 1)
        anfang = max(lauf, von)
        ende = min(naechster - timedelta(days=1), bis)
        yield _sekunden(anfang), _sekunden(ende, tagesende=True)
        lauf = naechster


def _zeile(kerze: Any) -> str:
    # Die Zeit kommt als Sekunden der Server-Wandzeit; UTC-Formatierung gibt sie
    # unverändert aus, egal welche Zone der Windows-Rechner eingestellt hat.
    stamp = datetime.fromtimestamp(int(kerze["time"]), tz=timezone.utc)
    return "\t".join([
        stamp.strftime("%Y.%m.%d"),
        stamp.strftime("%H:%M:%S"),
        repr(float(kerze["open"])),
        repr(float(kerze["high"])),
        repr(float(kerze["low"])),
        repr(float(kerze["close"])),
        str(int(kerze["tick_volume"])),
        str(int(kerze["real_volume"])),
        str(int(kerze["spread"])),
    ])


def _hole(mt5: Any, symbol: str, rahmen: str, von: date, bis: date, raster: str) -> list[str]:
    konstante = getattr(mt5, f"TIMEFRAME_{rahmen}", None)
    if konstante is None:
        raise AbrufFehler(f"Zeitrahmen {rahmen} kennt das Terminal nicht.")
    kerzen: dict[int, Any] = {}
    for anfang, ende in _zeitraeume(von, bis, raster):
        roh = mt5.copy_rates_range(symbol, konstante, anfang, ende)
        if roh is None:
            raise AbrufFehler(
                f"copy_rates_range({symbol}, {rahmen}) lieferte nichts: {_letzter_fehler(mt5)}"
            )
        for kerze in roh:
            kerzen[int(kerze["time"])] = kerze
    return [_zeile(kerzen[stamp]) for stamp in sorted(kerzen)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MT5-Historie direkt aus dem Terminal als MT5-CSV nach daten/ schreiben."
    )
    parser.add_argument("--symbol", required=True, help="Broker-Symbol, z. B. EURUSD (auch EURUSD.a)")
    parser.add_argument("--zeitrahmen", choices=RAHMEN, default="M15")
    parser.add_argument("--von", required=True, type=date.fromisoformat, metavar="JJJJ-MM-TT")
    parser.add_argument("--bis", type=date.fromisoformat, metavar="JJJJ-MM-TT",
                        help="Standard: heute (UTC)")
    parser.add_argument("--abschnitte", choices=("monat", "jahr"), default="monat",
                        help="Abfragefenster; kleinere Fenster umgehen die Terminal-Historie")
    parser.add_argument("--ausgabe", default=str(WURZEL / "daten"),
                        help="Zielordner (Standard: daten/ im Repository)")
    parser.add_argument("--terminal-pfad", metavar="PFAD",
                        help="terminal64.exe, falls das Terminal nicht automatisch startet")
    args = parser.parse_args(argv)
    bis = args.bis or datetime.now(timezone.utc).date()
    if bis < args.von:
        print("FEHLER --bis liegt vor --von.", file=sys.stderr)
        return 1

    try:
        mt5 = _terminal()
    except AbrufFehler as exc:
        print(f"FEHLER {exc}", file=sys.stderr)
        return 1

    gestartet = False
    try:
        pfad = {"path": args.terminal_pfad} if args.terminal_pfad else {}
        if not mt5.initialize(**pfad):
            raise AbrufFehler(f"Terminal nicht erreichbar: {_letzter_fehler(mt5)}")
        gestartet = True
        if not mt5.symbol_select(args.symbol, True):
            raise AbrufFehler(
                f"Symbol {args.symbol} nicht im Market Watch: {_letzter_fehler(mt5)}"
            )
        zeilen = _hole(mt5, args.symbol, args.zeitrahmen, args.von, bis, args.abschnitte)
        if not zeilen:
            raise AbrufFehler(
                f"keine Kerzen für {args.symbol} {args.zeitrahmen} zwischen {args.von} und {bis}"
            )
        ziel = Path(args.ausgabe) / f"{args.symbol.upper()}_{args.zeitrahmen}.csv"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text("\n".join([KOPFZEILE, *zeilen]) + "\n", encoding="utf-8")
        print(f"{ziel}: {len(zeilen)} Kerzen ({args.von} bis {bis})")
        return 0
    except AbrufFehler as exc:
        print(f"FEHLER {exc}", file=sys.stderr)
        return 1
    finally:
        if gestartet:
            mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
