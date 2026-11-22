#!/usr/bin/env python3
"""Holt MT5-Historie direkt aus dem laufenden Terminal und schreibt MT5-CSV.

Läuft nur unter Windows: Das Paket ``MetaTrader5`` spricht per IPC mit einem
installierten, angemeldeten Terminal. Es steht deshalb bewusst nicht in
``requirements.txt``; die Installation erfolgt im venv des Windows-Rechners.
Kerzen entstehen im Format, das ``orakel daten --csv`` liest; Ticks bekommen
mit ``--format ticks`` ein eigenes Archivformat.
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
TICK_KOPFZEILE = ("<DATE>\t<TIME>\t<MSEC>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>"
                  "\t<VOLUME_REAL>\t<FLAGS>")


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


def _zeitraeume(von: date, bis: date) -> Iterator[tuple[int, int]]:
    """Zerlegt den Bereich in Monatsfenster.

    Das Terminal liefert nur geladene Kerzen; kleinere Fenster fragen weniger
    auf einmal ab und umgehen die Grenze aus «Max. bars in chart».
    """
    lauf = date(von.year, von.month, 1)
    while lauf <= bis:
        naechster = date(lauf.year + lauf.month // 12, lauf.month % 12 + 1, 1)
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


def _inhalt(kerze: Any) -> tuple[float, ...]:
    return tuple(float(kerze[feld]) for feld in
                 ("open", "high", "low", "close", "tick_volume", "real_volume", "spread"))


def _hole(mt5: Any, symbol: str, rahmen: str, von: date, bis: date) -> list[str]:
    konstante = getattr(mt5, f"TIMEFRAME_{rahmen}", None)
    if konstante is None:
        raise AbrufFehler(f"Zeitrahmen {rahmen} kennt das Terminal nicht.")
    kerzen: dict[tuple[int, tuple[float, ...]], Any] = {}
    for anfang, ende in _zeitraeume(von, bis):
        roh = mt5.copy_rates_range(symbol, konstante, anfang, ende)
        if roh is None:
            raise AbrufFehler(
                f"copy_rates_range({symbol}, {rahmen}) lieferte nichts: {_letzter_fehler(mt5)}"
            )
        for kerze in roh:
            # Beide Fassungen der Herbststunde tragen dieselbe Serverzeit; nur
            # gleiche Zeit *und* gleiche Werte sind dieselbe Kerze aus einem
            # überlappenden Block.
            kerzen[(int(kerze["time"]), _inhalt(kerze))] = kerze
    # Stabil nach Serverzeit sortiert; innerhalb gleicher Zeitstempel bleibt die
    # Reihenfolge des Terminals: Bei der Herbst-Rückstellung steht so die
    # Sommerzeit-Fassung vor der Standardzeit-Fassung.
    reihenfolge = sorted(kerzen.values(), key=lambda kerze: int(kerze["time"]))
    return [_zeile(kerze) for kerze in reihenfolge]


def _tick_zeile(tick: Any) -> str:
    # Server-Wandzeit wie beim Kerzen-CSV, zusätzlich die Millisekunde.
    stamp = datetime.fromtimestamp(int(tick["time"]), tz=timezone.utc)
    return "\t".join([
        stamp.strftime("%Y.%m.%d"),
        stamp.strftime("%H:%M:%S"),
        f"{int(tick['time_msc']) % 1000:03d}",
        repr(float(tick["bid"])),
        repr(float(tick["ask"])),
        repr(float(tick["last"])),
        str(int(tick["volume"])),
        repr(float(tick["volume_real"])),
        str(int(tick["flags"])),
    ])


def _tick_inhalt(tick: Any) -> tuple[int, float, float, float, int, float, int]:
    return (int(tick["time_msc"]), float(tick["bid"]), float(tick["ask"]),
            float(tick["last"]), int(tick["volume"]),
            float(tick["volume_real"]), int(tick["flags"]))


def _hole_ticks(mt5: Any, symbol: str, von: date, bis: date) -> list[str]:
    """Holt Ticks monatsweise; exakte Dubletten aus Grenzfenstern fallen weg."""
    flag = int(getattr(mt5, "COPY_TICKS_ALL", 0))
    ticks: dict[tuple[int, float, float, float, int, float, int], Any] = {}
    for anfang, ende in _zeitraeume(von, bis):
        roh = mt5.copy_ticks_range(symbol, anfang, ende, flag)
        if roh is None:
            raise AbrufFehler(
                f"copy_ticks_range({symbol}) lieferte nichts: {_letzter_fehler(mt5)}"
            )
        for tick in roh:
            ticks[_tick_inhalt(tick)] = tick
    reihenfolge = sorted(
        ticks.values(), key=lambda tick: (int(tick["time"]), int(tick["time_msc"]))
    )
    return [_tick_zeile(tick) for tick in reihenfolge]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MT5-Historie direkt aus dem Terminal als Kerzen- oder Tick-CSV nach daten/ schreiben."
    )
    parser.add_argument("--symbol", required=True, help="Broker-Symbol, z. B. EURUSD (auch EURUSD.a)")
    parser.add_argument("--zeitrahmen", choices=RAHMEN, default="M15",
                        help="Kerzen-Zeitrahmen (bei --format ticks ohne Wirkung)")
    parser.add_argument("--format", choices=("kerzen", "ticks"), default="kerzen",
                        help="Ausgabeformat: MT5-Kerzen-CSV (Standard) oder Tick-CSV")
    parser.add_argument("--von", required=True, type=date.fromisoformat, metavar="JJJJ-MM-TT")
    parser.add_argument("--bis", type=date.fromisoformat, metavar="JJJJ-MM-TT",
                        help="Standard: heute (UTC)")
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
        if args.format == "ticks":
            zeilen = _hole_ticks(mt5, args.symbol, args.von, bis)
            if not zeilen:
                raise AbrufFehler(
                    f"keine Ticks für {args.symbol} zwischen {args.von} und {bis}"
                )
            dateiname = f"{args.symbol.upper()}_ticks.csv"
            kopfzeile = TICK_KOPFZEILE
            einheit = "Ticks"
        else:
            zeilen = _hole(mt5, args.symbol, args.zeitrahmen, args.von, bis)
            if not zeilen:
                raise AbrufFehler(
                    f"keine Kerzen für {args.symbol} {args.zeitrahmen} zwischen {args.von} und {bis}"
                )
            dateiname = f"{args.symbol.upper()}_{args.zeitrahmen}.csv"
            kopfzeile = KOPFZEILE
            einheit = "Kerzen"
        ziel = Path(args.ausgabe) / dateiname
        ziel.parent.mkdir(parents=True, exist_ok=True)
        try:
            ziel.write_text("\n".join([kopfzeile, *zeilen]) + "\n", encoding="utf-8")
        except OSError as exc:
            raise AbrufFehler(f"{ziel} nicht schreibbar: {exc}") from exc
        print(f"{ziel}: {len(zeilen)} {einheit} ({args.von} bis {bis})")
        return 0
    except AbrufFehler as exc:
        print(f"FEHLER {exc}", file=sys.stderr)
        return 1
    finally:
        if gestartet:
            mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
