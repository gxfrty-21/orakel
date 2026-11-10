from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import load_config
from .data import lade_csv, synthetische_kerzen
from .db import Facts
from .knowledge import Vault


def _cfg(pfad: str):
    return load_config(pfad)


def cmd_daten(args: argparse.Namespace) -> int:
    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    cfg.daten_ordner.mkdir(parents=True, exist_ok=True)

    if args.csv:
        datei = Path(args.csv)
        df = lade_csv(datei)
        symbol = args.symbol or datei.stem.split("_")[0].upper()
        n = db.kerzen_speichern(symbol, args.zeitrahmen, df.to_dict("records"))
        db.zustand_setzen("datenquelle", "csv")
        db.ereignis("info", "Daten", f"{datei.name}: {n} Kerzen für {symbol} importiert")
        print(f"{n} Kerzen importiert: {symbol} ({df['ts'].iloc[0]} bis {df['ts'].iloc[-1]})")
        return 0

    for i, symbol in enumerate(args.symbol or ["EURUSD", "US500"]):
        df = synthetische_kerzen(symbol, kerzen=args.kerzen, seed=7 + i * 13)
        n = db.kerzen_speichern(symbol, args.zeitrahmen, df.to_dict("records"))
        print(f"{n} synthetische Kerzen erzeugt: {symbol}")
    db.zustand_setzen("datenquelle", "synthetisch")
    db.ereignis("warnung", "Daten", "Synthetische Kerzen erzeugt — nur zum Testen der Abläufe")
    return 0


def cmd_pruefen(args: argparse.Namespace) -> int:
    from .pipeline import lauf

    bericht = lauf(cfg_pfad=args.config, modus=args.modus, quelle=args.quelle,
                   bericht_pfad=args.bericht, mit_konferenz=not args.ohne_konferenz,
                   mit_spider=args.mit_spider)
    bestanden = sum(1 for v in bericht["validierungen"] if v["urteil"] == "bestanden")
    print(f"Modus: {bericht['modus']} · Datenquelle: {bericht['datenquelle']}")
    print(f"Geprüft: {len(bericht['validierungen'])} · bestanden: {bestanden} · "
          f"Auswahl: {len(bericht['auswahl'])} · Plan: {len(bericht['plan'])}")
    print(f"Bericht: {args.bericht} ({bericht['dauer_sekunden']} s)")
    if bestanden == 0:
        print("Keine Strategie hat den Richter bestanden — es wird nicht gehandelt.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app

    app = create_app(args.config, takt=args.takt)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_konferenz(args: argparse.Namespace) -> int:
    from . import agents
    from .pipeline import lauf

    bericht = lauf(cfg_pfad=args.config, modus="backtest", mit_konferenz=True)
    protokoll = bericht.get("konferenz") or {}
    print(protokoll.get("beschluss", "Keine Konferenz erzeugt"))
    for m in protokoll.get("massnahmen", []):
        print(f"- {m['beschreibung']} ({m['verantwortlich']})")
    return 0


def cmd_unternehmen(args: argparse.Namespace) -> int:
    from .company.runtime import CompanyRuntime
    from .company.store import CompanyStore

    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    store = CompanyStore(db)
    store.sync_roster()
    if args.status:
        s = store.stats()
        print(f"Profile: {s['profile']}")
        print("Abteilungen: " + ", ".join(f"{k}:{v}" for k, v in s['abteilungen'].items()))
        print("Tasks: " + ", ".join(f"{k}:{v}" for k, v in sorted(s['tasks'].items())))
        print(f"Audit-Kette: {'ok' if s['audit_ok'] else 'defekt'}")
        return 0
    ergebnis = CompanyRuntime(cfg, db, store=store).run(max_tasks=args.max_tasks)
    print(f"Company-Lauf {ergebnis['tag']}: {ergebnis['profile']} Profile, "
          f"{ergebnis['tasks_erzeugt']} Tagesaufgaben, "
          f"{ergebnis['tasks_verarbeitet']} verarbeitet, "
          f"{ergebnis['dauer_sekunden']} s")
    print("Status: " + ", ".join(f"{k}:{v}" for k, v in sorted(ergebnis['states'].items())))
    print(f"Audit-Kette: {'ok' if ergebnis['audit_ok'] else 'defekt'} · "
          f"Paper-only: {'ja' if ergebnis['paper_only'] else 'NEIN'}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    print(f"Datenbank: {cfg.db_pfad}")
    print(f"Symbole:   {', '.join(db.symbole()) or 'keine'}")
    print(f"Letzter Lauf: {db.zustand('letzter_lauf')}")
    stopp = db.zustand("risiko_stopp")
    print(f"Risikostatus: {'GESTOPPT — ' + stopp.get('grund', '') if stopp else 'aktiv'}")
    konf = db.letzte_konferenz()
    if konf:
        print(f"Letzte Konferenz: {konf['zeit']} — {konf['protokoll'].get('beschluss', '')}")
    vault = Vault(cfg.vault_ordner)
    print(f"Vault:     {sum(vault.zaehle().values())} Notizen in {cfg.vault_ordner}")
    return 0


def cmd_spider(args: argparse.Namespace) -> int:
    from .spider import Spider

    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    ergebnis = Spider(cfg, db, Vault(cfg.vault_ordner)).lauf()
    db.zustand_setzen("spider_letzter_lauf", ergebnis)
    print(f"Quellen: {ergebnis['quellen']} · gelesen: {ergebnis['gelesen']} · "
          f"neu: {ergebnis['neu']} · analysiert: {ergebnis.get('analysiert', 0)} · "
          f"Notizen: {ergebnis['notizen']}")
    for f in ergebnis.get("fehler") or []:
        print(f"  Fehler: {f}")
    for a in ergebnis.get("top") or []:
        print(f"  [{a['qualitaet']:.2f}] {a['quelle']}: {a['titel'][:90]}")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    from .paper import tick

    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    ergebnis = tick(cfg, db)
    print(f"Paper-Takt: Equity {ergebnis['konto']['equity']:.2f} · "
          f"Bargeld {ergebnis['konto']['cash']:.2f} · Positionen {ergebnis['konto']['positionen']}")
    if ergebnis["gestoppt"]:
        print("Handelsstopp aktiv — neue Käufe blockiert.")
    for e in ergebnis["ereignisse"]:
        print(f"  {e}")
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    from .betrieb import Betrieb

    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    betrieb = Betrieb(cfg, db)
    intervall = betrieb.takt_sekunden
    print(f"Dauerbetrieb: Takt alle {intervall} s. Beenden mit Strg+C.")
    erster = True
    try:
        while True:
            ergebnis = betrieb.takt(
                erzwungen={"spider"} if erster and args.mit_spider else None)
            erster = False
            konto = ergebnis.get("paper", {}).get("konto", {})
            if konto:
                print(f"[{ergebnis.get('paper', {}).get('zeit', '')}] Equity "
                      f"{konto.get('equity', '–')} · Positionen "
                      f"{konto.get('positionen', '–')}")
            b = ergebnis.get("betrieb", {})
            print(f"  Takt {b.get('takt_nummer', '–')}: "
                  f"{b.get('status', '–')} · {b.get('dauer_ms', 0)} ms")
            time.sleep(intervall)
    except KeyboardInterrupt:
        print("Dauerbetrieb beendet.")
    return 0


def cmd_betrieb(args: argparse.Namespace) -> int:
    from .betrieb import betrieb_status

    cfg = _cfg(args.config)
    daten = betrieb_status(cfg, Facts(cfg.db_pfad))
    if args.json:
        print(json.dumps(daten, ensure_ascii=False, indent=2))
        return 0
    takt = daten["takt"]
    res = daten["ressourcen"]
    grenzen = res["limits"]
    print(f"Takt: {takt['status']} · zuletzt {takt['letzter'] or 'nie'} · "
          f"alle {takt['intervall_sekunden']} s")
    print(f"Ressourcen: DB {res['db_mb']:.1f}/{grenzen['max_db_mb']:g} MB · "
          f"RSS {res['rss_mb'] if res['rss_mb'] is not None else '–'}/"
          f"{grenzen['max_rss_mb']:g} MB · frei {res['freier_speicher_mb'] or '–'} MB")
    for job in daten["jobs"]:
        naechster = job["naechster_versuch"] or 'sofort'
        print(f"  {job['name']:<12} {job['zustand']:<10} "
              f"Intervall {job['intervall_sekunden']:>6} s · nächster {naechster}"
              + (f" · Fehler {job['fehlschluesse']}" if job["fehlschluesse"] else ""))
    for warnung in daten["warnungen"]:
        print(f"  [{warnung['stufe']}] {warnung['text']}")
    print(f"Letzte 24 h: {daten['statistik']['gesamt']} Läufe · "
          f"{daten['statistik']['fehler']} Fehler · "
          f"{daten['statistik']['uebersprungen']} übersprungen")
    return 0


def cmd_stopp_aufheben(args: argparse.Namespace) -> int:
    if not args.bestaetigen:
        print("Nur nach Prüfung: --bestaetigen anhängen.")
        return 1
    cfg = _cfg(args.config)
    db = Facts(cfg.db_pfad)
    db.zustand_loeschen("risiko_stopp")
    db.ereignis("warnung", "Risiko", "Handelsstopp manuell aufgehoben")
    print("Handelsstopp aufgehoben. Neue Käufe werden wieder geprüft.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orakel", description="Orakel Trading-Engine (Paper only)")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="befehl", required=True)

    d = sub.add_parser("daten", help="CSV importieren oder synthetische Kerzen erzeugen")
    d.add_argument("--csv")
    d.add_argument("--symbol", nargs="*")
    d.add_argument("--zeitrahmen", default="M15")
    d.add_argument("--kerzen", type=int, default=6000)
    d.set_defaults(func=cmd_daten)

    pr = sub.add_parser("pruefen", help="Vollständigen Lauf ausführen (Research, Richter, Plan)")
    pr.add_argument("--modus", default="backtest", choices=["backtest", "paper", "simulation"])
    pr.add_argument("--quelle", default=None)
    pr.add_argument("--bericht", default="dashboard.json")
    pr.add_argument("--ohne-konferenz", action="store_true")
    pr.add_argument("--mit-spider", action="store_true", help="Recherche mitlaufen lassen")
    pr.set_defaults(func=cmd_pruefen)

    s = sub.add_parser("serve", help="Dashboard im Browser starten")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--takt", action="store_true", help="Paper-Takt im Hintergrund starten")
    s.set_defaults(func=cmd_serve)

    sp = sub.add_parser("spider", help="Spider Intelligence: Quellen abrufen und prüfen")
    sp.set_defaults(func=cmd_spider)

    pa = sub.add_parser("paper", help="Einen Paper-Takt ausführen")
    pa.set_defaults(func=cmd_paper)

    da = sub.add_parser("daemon", help="Dauerbetrieb: Paper-Takt und Mitternachtskonferenz")
    da.add_argument("--mit-spider", action="store_true")
    da.set_defaults(func=cmd_daemon)

    be = sub.add_parser("betrieb", help="Betriebsplan, Backoff und Ressourcen anzeigen")
    be.add_argument("--json", action="store_true", help="vollständige Monitoringdaten")
    be.set_defaults(func=cmd_betrieb)

    k = sub.add_parser("konferenz", help="Mitternachtskonferenz jetzt abhalten")
    k.set_defaults(func=cmd_konferenz)

    st = sub.add_parser("status", help="Zustand aus der Fakten-Datenbank")
    st.set_defaults(func=cmd_status)

    u = sub.add_parser("unternehmen", help="Company-Schicht: 103 Profile, Queue, Policy")
    u.add_argument("--status", action="store_true", help="nur Profile und Queue anzeigen")
    u.add_argument("--max-tasks", type=int, default=None, help="Lauf begrenzen (Test/Demo)")
    u.set_defaults(func=cmd_unternehmen)

    sa = sub.add_parser("stopp-aufheben", help="Handelsstopp nach Prüfung aufheben")
    sa.add_argument("--bestaetigen", action="store_true")
    sa.set_defaults(func=cmd_stopp_aufheben)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
