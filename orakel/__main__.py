from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .config import RisikoGrenzen, load_config
from .kern.data import df_aus_db, lade_csv, synthetische_kerzen
from .kern.db import Facts
from .knowledge import Vault


def _cfg(pfad: str):
    return load_config(pfad)


def _schema_pruefen(konfig) -> int | None:
    """Prüft das Schema vor dem Lauf; bei altem Bestand Meldung und Exit 2.

    Gilt für jeden Befehl, der die Datenbank anfasst, nicht nur für ``serve``:
    Auch ``pruefen``, ``konferenz``, ``unternehmen`` und ``daten`` würden sonst
    mit einem ``no such column`` aus dem Traceback abbrechen.
    """
    from .kern.db import initialisiere
    from .kern.migrationen import AltesSchemaFehler, startmeldung

    try:
        # Schema und Migrationen vor dem Lauf prüfen: Ein alter Bestand endet so
        # als eigene Meldung statt als Traceback mitten im Ablauf.
        initialisiere(konfig.db_pfad)
    except AltesSchemaFehler as fehler:
        print(startmeldung(fehler, konfig.db_pfad), file=sys.stderr)
        return 2
    return None


def cmd_daten(args: argparse.Namespace) -> int:
    cfg = _cfg(args.config)
    if (code := _schema_pruefen(cfg)) is not None:
        return code
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

    if (code := _schema_pruefen(_cfg(args.config))) is not None:
        return code
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


def _commit() -> str:
    """Aktueller Commit für den Bericht; ohne git (Container) leer."""
    import subprocess

    try:
        r = subprocess.run(['git', '-c', 'safe.directory=*', 'rev-parse', 'HEAD'],  # noqa: S607
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def cmd_strategie_bericht(args: argparse.Namespace) -> int:
    from .strategiebericht import erstelle_bericht, schreibe_bericht

    cfg = _cfg(args.config)
    db = Facts(Path(args.db) if args.db else cfg.db_pfad)
    grenzen = RisikoGrenzen.aus_config(cfg)
    symbole = args.symbol or db.symbole()
    mindestens = int(cfg["daten"]["min_kerzen"])
    daten = {symbol: df_aus_db(db.kerzen(symbol, "M15")) for symbol in symbole}
    daten = {symbol: df for symbol, df in daten.items() if len(df) >= mindestens}
    if not daten:
        print(f"Keine Kerzen mit mindestens {mindestens} Bars — Bericht nicht erstellt.")
        return 1

    quelle = args.quelle or (f"{args.db} (Datenbank)" if args.db else str(cfg.db_pfad))
    bericht = erstelle_bericht(daten, cfg, grenzen, quelle=quelle, commit=_commit())
    json_pfad, md_pfad = schreibe_bericht(bericht, args.ausgabe)
    z = bericht["zusammenfassung"]
    print(f"Strategie-Bericht: {z['kandidaten']} Kandidaten · bestanden {z['bestanden']} · "
          f"abgelehnt {z['abgelehnt']} · ohne Daten {z['ohne_ausreichende_daten']}")
    print(f"Geschrieben: {json_pfad} und {md_pfad}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .web import create_app

    konfig = _cfg(args.config)
    # Vor dem Serverstart, damit ein alter Bestand nicht als Lifespan-Traceback
    # von uvicorn endet.
    if (code := _schema_pruefen(konfig)) is not None:
        return code

    takt = bool(args.takt) or os.environ.get("ORAKEL_TAKT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    app = create_app(args.config, takt=takt, host=args.host)
    login = "aktiv" if os.environ.get("ORAKEL_AUTH_USER", "").strip() else "aus (nur Loopback)"
    print(f"orakel: Dashboard auf {args.host}:{args.port}, Login {login}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_konferenz(args: argparse.Namespace) -> int:
    from . import agents
    from .pipeline import lauf

    if (code := _schema_pruefen(_cfg(args.config))) is not None:
        return code
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
    if (code := _schema_pruefen(cfg)) is not None:
        return code
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
    from .kern.paper import tick

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


def _migrationsstaende(nummern: list[int], bekannt: dict[int, object]) -> str:
    """Nummern als lesbare Liste, mit Name, wo die Migration bekannt ist."""
    if not nummern:
        return "keine"
    return ", ".join(
        f"{nummer:04d}_{getattr(bekannt[nummer], 'name', '')}" if nummer in bekannt
        else f"{nummer:04d}"
        for nummer in nummern)


def cmd_migration(args: argparse.Namespace) -> int:
    """Stand der Schema-Migrationen zeigen oder bis zu einer Nummer zurückrollen.

    ``--status`` liest nur. ``--zurueck N`` rollt alles über ``N`` zurück und
    verlangt ``--bestaetigen``; ohne den Schalter wird nur der Plan gezeigt und
    nichts geändert. Der Datenbankpfad kommt aus ``config.toml``;
    ``ORAKEL_DB_PFAD`` sticht ihn. Die Funktion fasst bewusst kein ``Facts`` an:
    Das würde beim Öffnen die Migrationen sofort wieder anwenden.
    """
    from .kern import migrationen

    if args.status and args.zurueck is not None:
        print("--status und --zurueck schliessen sich aus.", file=sys.stderr)
        return 1
    if not args.status and args.zurueck is None:
        print("Bitte --status oder --zurueck N angeben.", file=sys.stderr)
        return 1

    pfad = Path(_cfg(args.config).db_pfad)
    if not pfad.exists():
        # Rein lesend: ``angewendet()`` würde die Datei per sqlite3 anlegen.
        print(f"orakel: Keine Datenbank unter {pfad} — keine Migrationen angewendet.",
              file=sys.stderr)
        return 1

    bekannt = {m.nummer: m for m in migrationen.dateien()}
    stand = migrationen.angewendet(pfad)
    print(f"orakel: Datenbank {pfad}")
    print(f"orakel: Stand {_migrationsstaende(stand, bekannt)}")

    if args.status:
        offen = [nummer for nummer in sorted(bekannt) if nummer not in stand]
        print(f"orakel: Offen {_migrationsstaende(offen, bekannt)}")
        return 0

    zurueck = sorted((nummer for nummer in stand if nummer > args.zurueck),
                     reverse=True)
    if not zurueck:
        print(f"orakel: Nichts zu tun — der Stand ist nicht über {args.zurueck:04d}.")
        return 0
    print(f"orakel: Geplant {_migrationsstaende(zurueck, bekannt)} "
          f"(zurückrollen bis {args.zurueck:04d})")
    ohne_down = [nummer for nummer in zurueck
                 if bekannt.get(nummer) is None or bekannt[nummer].runter is None]
    if ohne_down:
        print("orakel: Kein Downgrade hinterlegt für "
              + ", ".join(f"{nummer:04d}" for nummer in ohne_down), file=sys.stderr)
        print("orakel: Nichts geändert.", file=sys.stderr)
        return 1
    if not args.bestaetigen:
        print("orakel: Nichts geändert — nur nach Prüfung mit --bestaetigen ausführen.",
              file=sys.stderr)
        return 1

    try:
        ergebnis = migrationen.zurueckrollen(pfad, bis=args.zurueck)
    except migrationen.MigrationsFehler as fehler:
        # Jeder Schritt committet einzeln; ein Abbruch mitten im Lauf kann den
        # Stand also bereits verändert haben. Deshalb kein «nichts geändert».
        print(f"orakel: Rückrollen abgebrochen: {fehler}", file=sys.stderr)
        print("orakel: Stand bitte mit «orakel migration --status» prüfen.",
              file=sys.stderr)
        return 1

    zurueckgerollt = [int(nummer) for nummer in ergebnis["zurueckgerollt"] or []]
    print(f"orakel: Zurückgerollt {_migrationsstaende(zurueckgerollt, bekannt)}")
    print(f"orakel: Sicherung {ergebnis['backup']}")
    print(f"orakel: Neuer Stand "
          f"{_migrationsstaende(migrationen.angewendet(pfad), bekannt)}")
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

    sb = sub.add_parser("strategie-bericht",
                        help="Alle Strategien je Symbol prüfen und Bericht schreiben")
    sb.add_argument("--config", default="config.toml")
    sb.add_argument("--db", default=None, help="Datenbank mit Kerzen (Standard: config.toml)")
    sb.add_argument("--quelle", default=None, help="Bezeichnung der Datenquelle im Bericht")
    sb.add_argument("--symbol", nargs="*", default=None, help="Nur diese Symbole prüfen")
    sb.add_argument("--ausgabe", default="artifacts/strategie-bericht")
    sb.set_defaults(func=cmd_strategie_bericht)

    s = sub.add_parser("serve", help="Dashboard im Browser starten")
    # Ohne Zugangsdaten nur Loopback; Container setzen 0.0.0.0 ausdruecklich
    # (docker-entrypoint.sh) und brauchen dafuer ORAKEL_AUTH_USER/PASS.
    s.add_argument("--host", default="127.0.0.1",
                   help="Bindeadresse (Standard 127.0.0.1; Container: 0.0.0.0)")
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

    mi = sub.add_parser("migration", help="Schema-Migrationen anzeigen oder zurückrollen")
    mi.add_argument("--status", action="store_true",
                    help="Stand und offene Migrationen anzeigen (ändert nichts)")
    mi.add_argument("--zurueck", type=int, metavar="N",
                    help="Migrationen über Nummer N zurückrollen")
    mi.add_argument("--bestaetigen", action="store_true",
                    help="Rückrollen wirklich ausführen")
    mi.set_defaults(func=cmd_migration)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
