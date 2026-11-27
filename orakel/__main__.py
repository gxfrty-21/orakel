from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

from .config import RisikoGrenzen, load_config
from .kern.data import (
    ZEITRAHMEN,
    ZEITRAHMEN_MINUTEN,
    df_aus_bloecken,
    df_aus_db,
    pruefe_daten,
    synthetische_kerzen,
    zerlege_dateiname,
)
from .kern.datenimport import (
    ParallelerImport,
    frische_text,
    importiere_datei,
    internes_symbol,
    vorhandener_import,
)
from .kern.db import Facts, Kerzenkonflikte
from .kern.robustheit import STANDARD_LAEUFE, STANDARD_SEED
from .knowledge import Vault


def _cfg(pfad: str):
    return load_config(pfad)


def _versatz(text: str) -> float:
    """Parst einen festen Broker-Versatz wie ``+03:00`` oder ``-05:00``."""
    treffer = re.fullmatch(r"([+-])(\d{2}):(\d{2})", text.strip())
    if not treffer:
        raise argparse.ArgumentTypeError(
            "Erwartet wird ein Versatz wie +03:00 oder -05:00."
        )
    stunden, minuten = int(treffer.group(2)), int(treffer.group(3))
    if minuten > 59 or stunden > 14 or (stunden == 14 and minuten):
        raise argparse.ArgumentTypeError(
            "Der Versatz muss zwischen -14:00 und +14:00 liegen."
        )
    wert = stunden + minuten / 60
    return -wert if treffer.group(1) == "-" else wert


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


def _pipeline_lauf(**kwargs) -> dict | None:
    """Führt die Pipeline aus und übersetzt einen DatenFehler in Exit-Code 1."""
    from .pipeline import DatenFehler, lauf

    try:
        return lauf(**kwargs)
    except DatenFehler as exc:
        print(f"FEHLER {exc}", file=sys.stderr)
        return None


def _importiere_csv(cfg, db: Facts, args: argparse.Namespace) -> int:
    """Importiert beliebig viele MT5-Dateien und prüft danach die ganze Reihe.

    Jede Datei darf ein Teilzeitraum sein (MT5 exportiert oft blockweise);
    doppelte Zeitstempel ersetzt die Datenbank. Geprüft wird die
    zusammengeführte Reihe, sonst würde jeder kleine Block als «zu wenig
    Kerzen» gelten.
    """
    dateien = [Path(p) for p in args.csv]
    max_alter = getattr(args, "max_alter_stunden", None)
    if max_alter is not None and (not math.isfinite(max_alter) or max_alter <= 0):
        print("FEHLER --max-alter-stunden muss grösser als 0 sein.", file=sys.stderr)
        return 2
    frisch = bool(getattr(args, "frisch", False)) or max_alter is not None
    zeitzone = args.server_zeitzone or cfg["daten"].get("server_zeitzone") or None
    if args.server_versatz is not None and args.server_versatz_stunden is not None:
        print("FEHLER --server-versatz und --server-versatz-stunden schliessen sich aus — "
              "nur eine Versatzangabe.", file=sys.stderr)
        return 2
    versatz = args.server_versatz
    if versatz is None:
        versatz = args.server_versatz_stunden
    if versatz is None:
        versatz = cfg["daten"].get("server_versatz_stunden")
    if zeitzone and versatz is not None:
        print("FEHLER server_zeitzone und ein fester Broker-Versatz schliessen sich aus — "
              "entweder eine IANA-Zone oder --server-versatz/--server-versatz-stunden.",
              file=sys.stderr)
        return 2
    vorgabe = args.symbol[0].upper() if args.symbol else None
    if vorgabe and len(dateien) > 1:
        print("--symbol gilt nur bei einer Datei; sonst kommt das Symbol aus dem Dateinamen.",
              file=sys.stderr)
        return 2

    fehler = 0
    uebersprungen = 0
    geprueft: list[tuple[str, str]] = []
    for datei in dateien:
        try:
            symbol, zeitrahmen = zerlege_dateiname(datei)
        except ValueError as exc:
            print(f"FEHLER {datei.name}: {exc}", file=sys.stderr)
            db.ereignis("fehler", "Daten", f"{datei.name}: {exc}")
            return 2
        symbol = internes_symbol(vorgabe or symbol, cfg["daten"])
        zeitrahmen = args.zeitrahmen or zeitrahmen
        konflikte = Kerzenkonflikte()
        try:
            ergebnis = importiere_datei(
                db, datei, symbol, zeitrahmen,
                daten_cfg=cfg["daten"], zeitzone=zeitzone, versatz=versatz,
                max_alter_stunden=max_alter, frisch=frisch,
                konflikte=konflikte)
        except ParallelerImport as exc:
            # Zwei Prozesse dürfen dieselbe Datei gleichzeitig anliefern. Der
            # zweite verliert das Rennen um den eindeutigen Prüfsummen-Schlüssel;
            # seine Kerzen wurden mit der Transaktion zurückgerollt.
            try:
                ergebnis = vorhandener_import(
                    db, exc.sha256, symbol, zeitrahmen,
                    daten_cfg=cfg["daten"], zeitzone=zeitzone, versatz=versatz,
                    max_alter_stunden=max_alter, frisch=frisch)
            except (OSError, ValueError) as exc2:
                print(f"FEHLER {datei.name}: {exc2}", file=sys.stderr)
                db.ereignis("fehler", "Daten", f"{datei.name}: {exc2}")
                fehler += 1
                continue
            if ergebnis is None:
                print(f"FEHLER {datei.name}: doppelter Importeintrag konnte "
                      "nicht zugeordnet werden.", file=sys.stderr)
                db.ereignis("fehler", "Daten",
                            f"{datei.name}: doppelter Importeintrag")
                fehler += 1
                continue
        except (OSError, ValueError) as exc:
            print(f"FEHLER {datei.name}: {exc}", file=sys.stderr)
            db.ereignis("fehler", "Daten", f"{datei.name}: {exc}")
            fehler += 1
            continue
        if ergebnis.uebersprungen:
            print(f"{datei.name}: bereits importiert "
                  f"(SHA-256 {ergebnis.sha256[:12]}…), übersprungen.")
            if ergebnis.kennzahl:
                print(f"  Frische: {frische_text(ergebnis.kennzahl)}")
            uebersprungen += 1
            if (symbol, zeitrahmen) not in geprueft:
                geprueft.append((symbol, zeitrahmen))
            continue
        db.ereignis("info", "Daten",
                    f"{datei.name}: {ergebnis.kerzen} Kerzen für {symbol} "
                    f"{zeitrahmen} importiert")
        print(f"{datei.name}: {ergebnis.kerzen} Kerzen gelesen")
        if ergebnis.kennzahl:
            print(f"  Frische: {frische_text(ergebnis.kennzahl)} — "
                  f"{'frisch' if ergebnis.kennzahl['frisch'] else 'veraltet'}")
        if ergebnis.konflikte.anzahl:
            probe = ergebnis.konflikte.beispiele[0]
            print(f"  Warnung: abweichende Kerzen: {ergebnis.konflikte.anzahl} "
                  f"(z. B. {probe}); gespeicherte Werte werden ersetzt.")
            db.ereignis("warnung", "Daten",
                        f"{datei.name}: {ergebnis.konflikte.anzahl} abweichende "
                        "Kerzen ersetzt, "
                        f"z. B. {probe}")
        if (symbol, zeitrahmen) not in geprueft:
            geprueft.append((symbol, zeitrahmen))

    if not geprueft:
        if uebersprungen:
            print("Alle Dateien waren bereits importiert.")
            return 0
        print("Nichts importiert.", file=sys.stderr)
        return 1
    if versatz is not None:
        print(f"Serverzeit UTC{versatz:+g} h → UTC")
    elif zeitzone:
        print(f"Serverzeit {zeitzone} → UTC")
    db.zustand_setzen("datenquelle", "csv")

    for symbol, zeitrahmen in geprueft:
        df = df_aus_bloecken(db.kerzen_bloecke(symbol, zeitrahmen))
        q = pruefe_daten(df, symbol, cfg, timeframe=zeitrahmen)
        print(f"{'OK' if q.ok else 'FEHLER'} {symbol} {zeitrahmen}: {q.kerzen} Kerzen, "
              f"{q.von or '–'} bis {q.bis or '–'}")
        if len(q.jahre) > 1:
            print("  Abdeckung: " + ", ".join(
                f"{jahr}: {anzahl}" for jahr, anzahl in q.jahre.items()))
        for text in q.fehler:
            print("  Fehler: " + text)
        for text in q.warnungen:
            print("  Warnung: " + text)
            db.ereignis("warnung", "Daten", f"{symbol} {zeitrahmen}: {text}")
        if not q.ok:
            fehler += 1
        if zeitrahmen not in {"M15", cfg.richter_zeitrahmen}:
            print(f"  Hinweis: Paper liest M15, der Richter {cfg.richter_zeitrahmen}; "
                  f"{zeitrahmen} wird gespeichert, aber nicht bewertet.")
    return 1 if fehler else 0


def cmd_daten(args: argparse.Namespace) -> int:
    cfg = _cfg(args.config)
    if (code := _schema_pruefen(cfg)) is not None:
        return code
    db = Facts(cfg.db_pfad)
    cfg.daten_ordner.mkdir(parents=True, exist_ok=True)

    if args.csv:
        return _importiere_csv(cfg, db, args)

    zeitrahmen = args.zeitrahmen or "M15"
    for i, symbol in enumerate(args.symbol or ["EURUSD", "US500"]):
        df = synthetische_kerzen(symbol, kerzen=args.kerzen, seed=7 + i * 13,
                                 timeframe_minuten=ZEITRAHMEN_MINUTEN[zeitrahmen])
        n = db.kerzen_speichern_df(symbol, zeitrahmen, df)
        print(f"{n} synthetische Kerzen erzeugt: {symbol}")
    db.zustand_setzen("datenquelle", "synthetisch")
    db.ereignis("warnung", "Daten", "Synthetische Kerzen erzeugt — nur zum Testen der Abläufe")
    return 0


def cmd_transport_bootstrap(args: argparse.Namespace) -> int:
    """Setzt den Bootstrap-Marker nach dem kontrollierten CLI-Import."""
    from . import transport

    cfg = _cfg(args.config)
    if (code := _schema_pruefen(cfg)) is not None:
        return code
    db = Facts(cfg.db_pfad)
    fehler = 0
    for symbol in args.symbol:
        try:
            marker = transport.bootstrap_freigeben(
                db, cfg, symbol, args.zeitrahmen, quelle="cli")
        except ValueError as exc:
            print(f"FEHLER {symbol} {args.zeitrahmen}: {exc}", file=sys.stderr)
            fehler += 1
            continue
        print(
            f"Bootstrap-Marker gesetzt: {marker['symbol']} {marker['zeitrahmen']}, "
            f"{marker['kerzen']} Kerzen von {marker['von']} bis {marker['bis']}",
        )
    return 1 if fehler else 0


def cmd_pruefen(args: argparse.Namespace) -> int:
    if (code := _schema_pruefen(_cfg(args.config))) is not None:
        return code
    bericht = _pipeline_lauf(cfg_pfad=args.config, modus=args.modus, quelle=args.quelle,
                             bericht_pfad=args.bericht,
                             mit_konferenz=not args.ohne_konferenz,
                             mit_spider=args.mit_spider,
                             frisch=bool(getattr(args, "frisch", False)),
                             max_alter_stunden=getattr(args, "max_alter_stunden", None))
    if bericht is None:
        return 1
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
    zeitrahmen = cfg.richter_zeitrahmen
    # Dieselbe Reihe, Jahresbasis und Mindestzahl wie im Richter, nicht fest M15.
    urteil_cfg = cfg.fuer_zeitrahmen(zeitrahmen)
    mindestens = cfg.min_kerzen_fuer(zeitrahmen)
    daten = {symbol: df_aus_db(db.kerzen(symbol, zeitrahmen)) for symbol in symbole}
    daten = {symbol: df for symbol, df in daten.items() if len(df) >= mindestens}
    if not daten:
        print(f"Keine {zeitrahmen}-Kerzen mit mindestens {mindestens} Bars — "
              "Bericht nicht erstellt.")
        return 1

    quelle = args.quelle or (f"{args.db} (Datenbank)" if args.db else str(cfg.db_pfad))
    bericht = erstelle_bericht(daten, urteil_cfg, grenzen, quelle=quelle, commit=_commit())
    json_pfad, md_pfad = schreibe_bericht(bericht, args.ausgabe)
    z = bericht["zusammenfassung"]
    print(f"Strategie-Bericht: {z['kandidaten']} Kandidaten · bestanden {z['bestanden']} · "
          f"abgelehnt {z['abgelehnt']} · ohne Daten {z['ohne_ausreichende_daten']}")
    print(f"Geschrieben: {json_pfad} und {md_pfad}")
    return 0


def _kennzahl_text(wert: float | None) -> str:
    return "–" if wert is None else f"{float(wert):.2f}"


def _anteil_text(wert: float | None) -> str:
    return "–" if wert is None else f"{float(wert) * 100:.1f} %"


def cmd_robustheit(args: argparse.Namespace) -> int:
    """Prüft einen festgelegten Kandidaten aus ``validierungen``.

    Der Kandidat wird nicht neu ausgewählt: Symbol, Strategie und Parameter
    stammen aus der gespeicherten Validierung. Der Test liest nur Kerzen und
    schreibt weder Urteil noch Auswahl zurück.
    """
    from .kern.robustheit import perturbationstest
    from .kern.strategies import strategien

    cfg = _cfg(args.config)
    db_pfad = Path(args.db) if args.db else cfg.db_pfad
    if not db_pfad.is_file():
        print(f"FEHLER Datenbank nicht gefunden: {db_pfad}", file=sys.stderr)
        return 2

    db = Facts(db_pfad)
    zeile = db.validierung(int(args.kandidat))
    if zeile is None:
        print(f"FEHLER Kandidat {args.kandidat} nicht gefunden.", file=sys.stderr)
        return 2

    try:
        parameter = json.loads(zeile["parameter"])
    except (TypeError, ValueError):
        print(f"FEHLER Kandidat {args.kandidat}: Parameter sind kein gültiges JSON.",
              file=sys.stderr)
        return 2
    if not isinstance(parameter, dict):
        print(f"FEHLER Kandidat {args.kandidat}: Parameter müssen ein Objekt sein.",
              file=sys.stderr)
        return 2

    zeitrahmen = cfg.richter_zeitrahmen
    strategie = strategien(cfg, zeitrahmen=zeitrahmen).get(str(zeile["strategie"]))
    if strategie is None:
        print(f"FEHLER Kandidat {args.kandidat}: unbekannte Strategie "
              f"{zeile['strategie']!r}.", file=sys.stderr)
        return 2

    symbol = str(zeile["symbol"])
    df = df_aus_db(db.kerzen(symbol, zeitrahmen))
    mindestens = cfg.min_kerzen_fuer(zeitrahmen)
    if len(df) < mindestens:
        print(f"FEHLER {symbol} {zeitrahmen}: {len(df)} Kerzen, "
              f"mindestens {mindestens} erwartet.", file=sys.stderr)
        return 2

    urteil_cfg = cfg.fuer_zeitrahmen(zeitrahmen)
    try:
        ergebnis = perturbationstest(
            df, strategie, parameter, urteil_cfg,
            RisikoGrenzen.aus_config(urteil_cfg),
            laeufe=int(args.laeufe), seed=int(args.seed), symbol=symbol,
        )
    except (KeyError, TypeError, ValueError) as fehler:
        print(f"FEHLER Robustheitstest: {fehler}", file=sys.stderr)
        return 2

    parameter_text = ", ".join(f"{k}={v}" for k, v in sorted(parameter.items()))
    print(f"Kandidat {args.kandidat}: {symbol} · {strategie.name} · {parameter_text}")
    print(f"Urteil: {zeile['urteil']} · Zeitrahmen: {zeitrahmen} · "
          f"{ergebnis.laeufe} Läufe ({ergebnis.laeufe_mit_trades} mit Trades)")
    print(f"Basis: Drawdown {_kennzahl_text(ergebnis.basis_drawdown_pct)} % · "
          f"Profit Factor {_kennzahl_text(ergebnis.basis_profit_factor)}")
    print(f"Drawdown: p50 {_kennzahl_text(ergebnis.drawdown_p50_pct)} % · "
          f"p95 {_kennzahl_text(ergebnis.drawdown_p95_pct)} % · "
          f"max {_kennzahl_text(ergebnis.drawdown_max_pct)} %")
    print(f"Profit Factor: p50 {_kennzahl_text(ergebnis.profit_factor_p50)} · "
          f"p05 {_kennzahl_text(ergebnis.profit_factor_p05)} · "
          f"über 1: {_anteil_text(ergebnis.profit_factor_ueber_1_anteil)}")
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
    if (code := _schema_pruefen(_cfg(args.config))) is not None:
        return code
    bericht = _pipeline_lauf(
        cfg_pfad=args.config, modus="backtest", mit_konferenz=True,
        frisch=bool(getattr(args, "frisch", False)),
        max_alter_stunden=getattr(args, "max_alter_stunden", None))
    if bericht is None:
        return 1
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


def _normalisiere_server_versatz(argv: list[str]) -> list[str]:
    """Verbinde ``--server-versatz`` mit einem negativen Wert ohne ``=``.

    argparse hält ``-05:00`` sonst für eine Option. Nur die exakte negative
    Kurzform wird umgeschrieben; ``--server-versatz +03:00`` und
    ``--server-versatz=-05:00`` bleiben unverändert.
    """
    ergebnis: list[str] = []
    i = 0
    while i < len(argv):
        if (argv[i] == "--server-versatz" and i + 1 < len(argv)
                and re.fullmatch(r"-\d{2}:\d{2}", argv[i + 1])):
            ergebnis.append(f"--server-versatz={argv[i + 1]}")
            i += 2
            continue
        ergebnis.append(argv[i])
        i += 1
    return ergebnis


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orakel", description="Orakel Trading-Engine (Paper only)")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="befehl", required=True)

    d = sub.add_parser("daten", help="CSV importieren oder synthetische Kerzen erzeugen")
    d.add_argument("--csv", nargs="+", help="eine oder mehrere MT5-CSV-Dateien")
    d.add_argument("--symbol", nargs="*")
    d.add_argument("--zeitrahmen", choices=ZEITRAHMEN, default=None,
                   help="Standard: aus dem Dateinamen (z. B. EURUSD_M15.csv), sonst M15")
    versatz = d.add_mutually_exclusive_group()
    versatz.add_argument("--server-zeitzone", default=None, metavar="IANA-ZONE",
                         help="Zeitzone der MT5-Serverzeit, z. B. Europe/Athens; Standard: UTC; "
                              "nicht mit einem festen Versatz kombinierbar")
    versatz.add_argument("--server-versatz", type=_versatz, default=None, metavar="±HH:MM",
                         help="fester Broker-Versatz als +03:00 oder -05:00 "
                              "(auch --server-versatz=-05:00); nicht mit "
                              "--server-zeitzone oder --server-versatz-stunden kombinierbar")
    versatz.add_argument("--server-versatz-stunden", type=float, default=None, metavar="STUNDEN",
                         help="fester Broker-Versatz der MT5-Serverzeit in Stunden, z. B. 3 oder -5; "
                              "nicht mit --server-zeitzone oder --server-versatz kombinierbar")
    d.add_argument("--kerzen", type=int, default=6000)
    d.add_argument("--frisch", action="store_true",
                   help="Import ablehnen, wenn die jüngste Kerze älter als die "
                        "Frischegrenze ist; historische Blöcke ohne diese Option importieren")
    d.add_argument("--max-alter-stunden", type=float, default=None, metavar="STUNDEN",
                   help="Frischegrenze überschreiben (impliziert --frisch)")
    d.set_defaults(func=cmd_daten)

    tb = sub.add_parser(
        "transport-bootstrap",
        help="Bootstrap-Marker für den HTTPS-Transport nach dem CLI-Import setzen",
    )
    tb.add_argument("--symbol", nargs="+", required=True,
                    help="ein oder mehrere bereits importierte Symbole")
    tb.add_argument("--zeitrahmen", choices=ZEITRAHMEN, default="M15",
                    help="Zeitrahmen der bereits importierten Reihe (Standard: M15)")
    tb.set_defaults(func=cmd_transport_bootstrap)

    pr = sub.add_parser("pruefen", help="Vollständigen Lauf ausführen (Research, Richter, Plan)")
    pr.add_argument("--modus", default="backtest", choices=["backtest", "paper", "simulation"])
    pr.add_argument("--quelle", default=None)
    pr.add_argument("--bericht", default="dashboard.json")
    pr.add_argument("--ohne-konferenz", action="store_true")
    pr.add_argument("--mit-spider", action="store_true", help="Recherche mitlaufen lassen")
    pr.add_argument("--frisch", action="store_true",
                    help="CSV-Ordner nur importieren, wenn die jüngste Kerze je Datei "
                         "frisch ist; historische Ordner ohne diese Option importieren")
    pr.add_argument("--max-alter-stunden", type=float, default=None, metavar="STUNDEN",
                    help="Frischegrenze für den CSV-Ordner überschreiben (impliziert --frisch)")
    pr.set_defaults(func=cmd_pruefen)

    sb = sub.add_parser("strategie-bericht",
                        help="Alle Strategien je Symbol prüfen und Bericht schreiben")
    sb.add_argument("--config", default="config.toml")
    sb.add_argument("--db", default=None, help="Datenbank mit Kerzen (Standard: config.toml)")
    sb.add_argument("--quelle", default=None, help="Bezeichnung der Datenquelle im Bericht")
    sb.add_argument("--symbol", nargs="*", default=None, help="Nur diese Symbole prüfen")
    sb.add_argument("--ausgabe", default="artifacts/strategie-bericht")
    sb.set_defaults(func=cmd_strategie_bericht)

    rb = sub.add_parser("robustheit",
                        help="Monte-Carlo-Perturbation für einen festgelegten Kandidaten")
    rb.add_argument("--db", default=None,
                    help="Datenbank mit Kandidat und Kerzen (Standard: config.toml)")
    rb.add_argument("--kandidat", type=int, required=True,
                    help="ID des Kandidaten aus der Tabelle validierungen")
    rb.add_argument("--laeufe", type=int, default=STANDARD_LAEUFE,
                    help=f"Anzahl der Perturbationsläufe (Standard: {STANDARD_LAEUFE})")
    rb.add_argument("--seed", type=int, default=STANDARD_SEED,
                    help=f"Zufallsseed (Standard: {STANDARD_SEED})")
    rb.set_defaults(func=cmd_robustheit)

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
    k.add_argument("--frisch", action="store_true",
                   help="CSV-Ordner nur importieren, wenn die jüngste Kerze je Datei frisch ist")
    k.add_argument("--max-alter-stunden", type=float, default=None, metavar="STUNDEN",
                   help="Frischegrenze für den CSV-Ordner überschreiben (impliziert --frisch)")
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

    werte = sys.argv[1:] if argv is None else argv
    args = p.parse_args(_normalisiere_server_versatz(list(werte)))
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
