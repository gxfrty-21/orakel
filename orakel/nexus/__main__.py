"""CLI: ``python -m orakel.nexus status|hole|nacht|bewertung|mission``."""

from __future__ import annotations

import argparse
import json
import os
import sys

from ..db import Facts
from ..knowledge import Vault
from .abruf import Abrufer, HttpCache
from .bewertung import claims_auffrischen
from .feeds import parse_feed
from .graph import ZEITRAEUME, graph_auffrischen, graph_daten
from .kalibrierung import kalibrierung_auffrischen, prognose_anlegen
from .hackernews import meldungen as hn_meldungen
from .missionen import Missionen
from .nacht import nachtlauf
from .quellen import lade_register
from .status import gesamt_status


def _status(args: argparse.Namespace) -> int:
    quellen = lade_register(args.register)
    cache = HttpCache(args.db)
    daten = gesamt_status(cache, quellen, Facts(args.db))
    print(json.dumps(daten, ensure_ascii=False, indent=2))
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


def _nacht(args: argparse.Namespace) -> int:
    bericht = nachtlauf(
        args.db,
        register_pfad=args.register,
        backup_ordner=args.backup_ordner,
        domain=args.domain,
        limit=args.limit,
        behalten_tage=args.behalten_tage,
        warnung_url=args.warnung_url,
        warnung_art=args.warnung_art,
        ping_url=args.ping_url,
    )
    print(json.dumps(bericht, ensure_ascii=False, indent=2))
    return 0 if bericht.get("ok") else 1


def _bewertung(args: argparse.Namespace) -> int:
    quellen = lade_register(args.register)
    ergebnis = claims_auffrischen(Facts(args.db), quellen)
    print(json.dumps(ergebnis, ensure_ascii=False, indent=2))
    return 0


def _graph(args: argparse.Namespace) -> int:
    db = Facts(args.db)
    aufbau = graph_auffrischen(db)
    daten = graph_daten(db, args.zeitraum)
    print(json.dumps({"ok": True, "aufbau": aufbau, "graph": daten},
                     ensure_ascii=False, indent=2))
    return 0


def _kalibrierung(args: argparse.Namespace) -> int:
    ergebnis = kalibrierung_auffrischen(Facts(args.db))
    print(json.dumps(ergebnis, ensure_ascii=False, indent=2))
    return 0


def _prognose(args: argparse.Namespace) -> int:
    try:
        forecast = prognose_anlegen(
            Facts(args.db), args.aussage, args.erwartung,
            zeithorizont=args.zeithorizont, konfidenz=args.konfidenz,
            symbol=args.symbol, toleranz_pct=args.toleranz_pct,
            mission_kennung=args.mission, claim_id=args.claim_id,
        )
    except ValueError as exc:
        print(json.dumps({"ok": False, "fehler": str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps({"ok": True, "prognose": forecast},
                     ensure_ascii=False, indent=2))
    return 0


def _mission(args: argparse.Namespace) -> int:
    missionen = Missionen(Facts(args.db), vault=Vault(args.vault))
    try:
        mission = missionen.anlegen(args.titel, args.auftrag, args.prioritaet)
    except ValueError as exc:
        print(json.dumps({"ok": False, "fehler": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    ergebnis = missionen.weiterarbeiten(args.max, mission["kennung"]) if args.start else {}
    print(json.dumps({"ok": True, "mission": ergebnis.get("mission") or
                      Facts(args.db).nexus_mission(mission["kennung"]),
                      "lauf": ergebnis}, ensure_ascii=False, indent=2))
    return 0


def _missionen(args: argparse.Namespace) -> int:
    print(json.dumps({
        "missionen": Facts(args.db).nexus_missionen(args.limit),
        "statistik": Facts(args.db).nexus_mission_statistik(),
    }, ensure_ascii=False, indent=2))
    return 0


def _mission_lauf(args: argparse.Namespace) -> int:
    db = Facts(args.db)
    if args.kennung and db.nexus_mission(args.kennung) is None:
        print(json.dumps({"ok": False, "fehler": f"Unbekannte Mission: {args.kennung}"},
                         ensure_ascii=False, indent=2))
        return 2
    ergebnis = Missionen(db, vault=Vault(args.vault)).weiterarbeiten(args.max, args.kennung)
    print(json.dumps({"ok": True, **ergebnis}, ensure_ascii=False, indent=2))
    return 0


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

    nacht = unter.add_parser("nacht", help="Nachtlauf: Meldungen speichern, Backup, DNS/TLS")
    nacht.add_argument("--db", default="orakel.db")
    nacht.add_argument("--register", default=None)
    nacht.add_argument("--backup-ordner", default="backups")
    nacht.add_argument("--behalten-tage", type=int, default=14)
    nacht.add_argument("--domain", default=os.environ.get("ORAKEL_DOMAIN") or None)
    nacht.add_argument("--warnung-url", default=os.environ.get("ORAKEL_WARNUNG_URL") or None)
    nacht.add_argument("--warnung-art", choices=("json", "text"),
                       default=os.environ.get("ORAKEL_WARNUNG_ART", "json"))
    nacht.add_argument("--ping-url", default=os.environ.get("ORAKEL_PING_URL") or None)
    nacht.add_argument("--limit", type=int, default=None)
    nacht.set_defaults(funktion=_nacht)

    bewertung = unter.add_parser("bewertung", help="Kernaussagen und Quellenreputation neu berechnen")
    bewertung.add_argument("--db", default="orakel.db")
    bewertung.add_argument("--register", default=None)
    bewertung.set_defaults(funktion=_bewertung)

    graph = unter.add_parser("graph", help="Wissensgraph neu aufbauen und anzeigen")
    graph.add_argument("--db", default="orakel.db")
    graph.add_argument("--zeitraum", choices=tuple(ZEITRAEUME), default="7d")
    graph.set_defaults(funktion=_graph)

    kalibrierung = unter.add_parser("kalibrierung", help="Prognosen prüfen und Kalibrierung anzeigen")
    kalibrierung.add_argument("--db", default="orakel.db")
    kalibrierung.set_defaults(funktion=_kalibrierung)

    prognose = unter.add_parser("prognose", help="Prüfbare Marktprognose anlegen")
    prognose.add_argument("--db", default="orakel.db")
    prognose.add_argument("--aussage", required=True)
    prognose.add_argument("--erwartung", choices=("steigt", "sinkt", "unveraendert"),
                          required=True)
    prognose.add_argument("--symbol", required=True)
    prognose.add_argument("--zeithorizont", default="24h")
    prognose.add_argument("--konfidenz", type=float, default=0.5)
    prognose.add_argument("--toleranz-pct", type=float, default=0.1)
    prognose.add_argument("--mission", default=None)
    prognose.add_argument("--claim-id", type=int, default=None)
    prognose.set_defaults(funktion=_prognose)

    mission = unter.add_parser("mission", help="Mission anlegen und optional starten")
    mission.add_argument("--db", default="orakel.db")
    mission.add_argument("--vault", default=os.environ.get("ORAKEL_VAULT", "vault"))
    mission.add_argument("--titel", required=True)
    mission.add_argument("--auftrag", required=True)
    mission.add_argument("--prioritaet", choices=("niedrig", "mittel", "hoch", "kritisch"),
                         default="mittel")
    mission.add_argument("--start", action="store_true")
    mission.add_argument("--max", type=int, default=10)
    mission.set_defaults(funktion=_mission)

    missionen = unter.add_parser("missionen", help="Missionen und Queue-Statistik anzeigen")
    missionen.add_argument("--db", default="orakel.db")
    missionen.add_argument("--limit", type=int, default=20)
    missionen.set_defaults(funktion=_missionen)

    mission_lauf = unter.add_parser("mission-lauf", help="Fällige Missionen ausführen")
    mission_lauf.add_argument("--db", default="orakel.db")
    mission_lauf.add_argument("--vault", default=os.environ.get("ORAKEL_VAULT", "vault"))
    mission_lauf.add_argument("--kennung", default=None)
    mission_lauf.add_argument("--max", type=int, default=10)
    mission_lauf.set_defaults(funktion=_mission_lauf)

    args = parser.parse_args(argv)
    return int(args.funktion(args))


if __name__ == "__main__":
    sys.exit(main())
