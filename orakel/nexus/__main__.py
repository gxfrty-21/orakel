"""CLI: ``python -m orakel.nexus status`` und ``... hole``.

``hole`` ruft echte Quellen ab und zeigt, was ankommt. Es speichert noch keine
Artikel in der Fakten-DB — das kommt mit der Dubletten-Erkennung in Phase 2.
"""

from __future__ import annotations

import argparse
import json
import sys

from .abruf import Abrufer, HttpCache
from .feeds import parse_feed
from .hackernews import meldungen as hn_meldungen
from .quellen import lade_register
from .status import gesamt_status


def _status(args: argparse.Namespace) -> int:
    quellen = lade_register(args.register)
    cache = HttpCache(args.db)
    print(json.dumps(gesamt_status(cache, quellen), ensure_ascii=False, indent=2))
    return 0


def _hole(args: argparse.Namespace) -> int:
    quellen = [q for q in lade_register(args.register) if q.aktiv]
    if args.nur:
        quellen = [q for q in quellen if q.id == args.nur]
    cache = HttpCache(args.db)
    abrufer = Abrufer(cache, args.user_agent, timeout=args.timeout,
                      min_abstand_sekunden=args.abstand)
    if args.hn:
        treffer = hn_meldungen(abrufer, limit=args.limit)
        print(json.dumps({
            "hn": len(treffer),
            "meldungen": [{"titel": m.titel, "punkte": m.punkte, "url": m.url}
                          for m in treffer[:10]],
        }, ensure_ascii=False, indent=2))
        return 0

    zeilen = []
    gesamt = 0
    fehler = 0
    for quelle in quellen[: args.limit]:
        ergebnis = abrufer.hole(quelle)
        anzahl = 0
        if ergebnis.ok and ergebnis.inhalt:
            try:
                anzahl = len(parse_feed(ergebnis.inhalt, quelle))
            except Exception as exc:
                anzahl = 0
                ergebnis.fehler = f"Parse-Fehler: {type(exc).__name__}"
        if not ergebnis.ok:
            fehler += 1
        gesamt += anzahl
        zeilen.append({
            "id": quelle.id,
            "status": ergebnis.status,
            "aus_cache": ergebnis.aus_cache,
            "meldungen": anzahl,
            "fehler": ergebnis.fehler,
            "ms": ergebnis.dauer_ms,
        })
    print(json.dumps({"quellen": len(zeilen), "meldungen": gesamt, "fehler": fehler,
                      "detail": zeilen}, ensure_ascii=False, indent=2))
    return 1 if fehler and not gesamt else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m orakel.nexus")
    unter = parser.add_subparsers(dest="befehl", required=True)

    status = unter.add_parser("status", help="Register und Cache anzeigen")
    status.add_argument("--db", default="orakel.db")
    status.add_argument("--register", default=None)
    status.set_defaults(funktion=_status)

    hole = unter.add_parser("hole", help="Quellen wirklich abrufen")
    hole.add_argument("--db", default="orakel.db")
    hole.add_argument("--register", default=None)
    hole.add_argument("--limit", type=int, default=5)
    hole.add_argument("--nur", default=None)
    hole.add_argument("--hn", action="store_true", help="Hacker News abrufen")
    hole.add_argument("--timeout", type=float, default=15.0)
    hole.add_argument("--abstand", type=float, default=1.0)
    hole.add_argument("--user-agent", default="OrakelNexus/0.1 (Feed-Abruf)")
    hole.set_defaults(funktion=_hole)

    args = parser.parse_args(argv)
    return int(args.funktion(args))


if __name__ == "__main__":
    sys.exit(main())
