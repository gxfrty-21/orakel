#!/usr/bin/env python3
"""Reproduzierbare Messung von Import und Richterlauf auf synthetischen Daten.

Das Skript erzeugt eine deterministische Fünfjahres-M15-Reihe (Seed 42,
Werktage 2021-11-22 bis 2026-11-20) und legt sie als ein oder mehrere Symbole
in einem eigenen Arbeitsordner ab. Import und Richterlauf laufen jeweils als
getrennte Prozesse; gemessen werden Wanduhrzeit und Spitzen-RSS getrennt.

Die bestehende ``orakel.db`` wird nie geöffnet: Konfiguration, SQLite-Datei,
Datenordner und Vault liegen ausschliesslich im Arbeitsordner. Ohne
``--arbeitsordner`` wird ein temporärer Ordner unter ``artifacts/`` angelegt und
nach dem Lauf entfernt.

Die Reihe ist synthetisch und keine Marktaussage. Sie dient nur als Hausnummer
für Laufzeit und Speicherbedarf bei gleicher Datenmenge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, time as tageszeit, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

START = date(2021, 11, 22)
ENDE = date(2026, 11, 20)
SEED = 42
STANDARD_SYMBOLE = 4
ZIEL_ZEILEN_2_1_MIO = 2_100_000
ENDE_2_1_MIO = datetime(2026, 11, 20, 23, 45, tzinfo=timezone.utc)
MODUS_STANDARD = "standard"
MODUS_2_1_MIO = "2-1-mio"
KOPF = "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"

RICHTER_CODE = """
import sys
from orakel.config import RisikoGrenzen, load_config
from orakel.kern.data import df_aus_db
from orakel.kern.db import Facts
from orakel.kern.judge import beurteile_walk_forward
from orakel.kern.strategies import strategien

cfg = load_config(sys.argv[1])
db = Facts(cfg.db_pfad)
grenzen = RisikoGrenzen.aus_config(cfg)
anzahl = 0
for symbol in db.symbole():
    df = df_aus_db(db.kerzen(symbol, "M15"))
    for strategie in strategien(cfg).values():
        urteil = beurteile_walk_forward(df, symbol, strategie, cfg, grenzen)
        anzahl += 1
        print(f"{symbol} {strategie.name}: {urteil.urteil}")
print(f"Richterprüfungen: {anzahl}")
"""

IMPORT_CODE = r"""
import json
import sys
from pathlib import Path

from orakel.kern.data import lade_csv, lade_csv_bloecke, mit_taktpruefung
from orakel.kern.db import Facts

variante, csv_pfad, db_pfad = sys.argv[1:4]
db = Facts(Path(db_pfad))
if variante == "block":
    anzahl = db.kerzen_speichern_bloecke(
        "SYN1", "M15", mit_taktpruefung(lade_csv_bloecke(csv_pfad), "M15")
    )
else:
    df = lade_csv(csv_pfad)
    anzahl = db.kerzen_speichern("SYN1", "M15", df.to_dict("records"))
print(json.dumps({"zeilen": anzahl}))
"""


@dataclass(frozen=True, slots=True)
class Messung:
    phase: str
    dauer_s: float
    rss_mb: float | None
    exit: int


def erzeuge_reihe(seed: int = SEED) -> list[tuple[datetime, float, float, float, float, int]]:
    """Erzeugt die deterministische Fünfjahresreihe (96 M15-Kerzen je Werktag)."""
    rng = np.random.default_rng(seed)
    preis = 1.10
    zeilen: list[tuple[datetime, float, float, float, float, int]] = []
    tag = START
    while tag <= ENDE:
        if tag.weekday() < 5:
            for i in range(96):
                zeit = datetime.combine(tag, tageszeit(0, 0), tzinfo=timezone.utc) + timedelta(
                    minutes=15 * i
                )
                open_ = preis
                close = max(0.5, open_ * (1.0 + float(rng.normal(0.0, 0.0004))))
                high = max(open_, close) * (1.0 + abs(float(rng.normal(0.0, 0.0001))))
                low = min(open_, close) * (1.0 - abs(float(rng.normal(0.0, 0.0001))))
                zeilen.append((zeit, open_, high, low, close, int(rng.integers(50, 500))))
                preis = close
        tag += timedelta(days=1)
    return zeilen


def erzeuge_grosse_reihe(pfad: Path, anzahl: int = ZIEL_ZEILEN_2_1_MIO,
                         seed: int = SEED) -> int:
    """Schreibt exakt ``anzahl`` lückenlose M15-Zeilen im MT5-TSV-Format.

    Die Nachmessung aus PR #245 verwendet 2.100.000 Zeilen bis
    ``2026-11-20 23:45 UTC``. Zeitstempel und Preise werden vektoriell erzeugt;
    die Datei wird zeilenweise geschrieben, damit der Speicherbedarf beim
    Erzeugen nicht von einem grossen DataFrame dominiert wird.
    """
    if anzahl < 2:
        raise ValueError("anzahl muss mindestens 2 sein")
    zeiten = pd.date_range(end=ENDE_2_1_MIO, periods=anzahl, freq="15min")
    rng = np.random.default_rng(seed)
    close = 1.10 * np.exp(np.cumsum(rng.normal(0.0, 0.0004, anzahl)))
    open_ = np.empty(anzahl, dtype=float)
    open_[0] = 1.10
    open_[1:] = close[:-1]
    spanne = np.abs(rng.normal(0.0, 0.0001, anzahl)) * close + 0.00002
    high = np.maximum(open_, close) + spanne
    low = np.minimum(open_, close) - spanne
    volume = rng.integers(50, 500, anzahl)

    tage = zeiten.strftime("%Y.%m.%d")
    uhrzeiten = zeiten.strftime("%H:%M:%S")
    with pfad.open("w", encoding="utf-8", newline="") as f:
        f.write(KOPF + "\n")
        for i in range(anzahl):
            f.write(
                f"{tage[i]}\t{uhrzeiten[i]}\t{open_[i]:.5f}\t{high[i]:.5f}\t"
                f"{low[i]:.5f}\t{close[i]:.5f}\t{int(volume[i])}\t0\t1\n"
            )
    return anzahl


def schreibe_csv(
    pfad: Path,
    zeilen: Sequence[tuple[datetime, float, float, float, float, int]],
) -> int:
    """Schreibt die Reihe im MT5-TSV-Format und liefert die Kerzenzahl."""
    with pfad.open("w", encoding="utf-8", newline="") as f:
        f.write(KOPF + "\n")
        for zeit, open_, high, low, close, vol in zeilen:
            f.write(
                f"{zeit:%Y.%m.%d}\t{zeit:%H:%M:%S}\t{open_:.5f}\t{high:.5f}\t"
                f"{low:.5f}\t{close:.5f}\t{vol}\t0\t1\n"
            )
    return len(zeilen)


def _toml_wert(wert: str | int | float) -> str:
    if isinstance(wert, str):
        return json.dumps(wert)
    return str(wert)


def _ersetze(text: str, schluessel: str, wert: str | int | float) -> str:
    """Ersetzt genau eine Zuweisung der Form ``schluessel = ...``."""
    muster = re.compile(
        rf"^{re.escape(schluessel)}[ \t]*=[ \t]*[^\s#]+",
        re.MULTILINE,
    )
    neu, anzahl = muster.subn(f"{schluessel} = {_toml_wert(wert)}", text)
    if anzahl != 1:
        raise ValueError(f"config.toml: erwartet genau eine Zuweisung für {schluessel}, "
                         f"gefunden {anzahl}")
    return neu


def isoliere_config(quelle: Path, ziel: Path, arbeitsordner: Path, *,
                    db_name: str = "orakel.db") -> Path:
    """Schreibt eine Config, deren DB, Daten und Vault nur im Arbeitsordner liegen."""
    arbeitsordner = arbeitsordner.resolve()
    if Path(db_name).name != db_name:
        raise ValueError("db_name muss ein Dateiname ohne Pfad sein")
    leer = arbeitsordner / "leer"
    vault = arbeitsordner / "vault"
    db = arbeitsordner / db_name
    leer.mkdir(parents=True, exist_ok=True)
    vault.mkdir(parents=True, exist_ok=True)

    text = quelle.read_text(encoding="utf-8")
    text = _ersetze(text, "daten_ordner", str(leer))
    text = _ersetze(text, "vault_ordner", str(vault))
    text = _ersetze(text, "db_pfad", str(db))
    text = _ersetze(text, "datenquelle", "csv")
    # Die feste Reihe soll nicht mit dem Kalender veralten; alle anderen
    # Prüfwerte kommen unverändert aus der Projekt-Config.
    text = _ersetze(text, "max_alter_tage", 36500)

    ziel = ziel.resolve()
    if not ziel.is_relative_to(arbeitsordner):
        raise ValueError("Die isolierte Config muss im Arbeitsordner liegen")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(text, encoding="utf-8")

    from orakel.config import load_config

    cfg = load_config(ziel)
    if cfg.db_pfad.resolve() != db:
        raise RuntimeError(f"Isolierung fehlgeschlagen: DB ist {cfg.db_pfad}, erwartet {db}")
    if cfg.db_pfad.resolve() == (ROOT / "orakel.db").resolve():
        raise RuntimeError("Die Projekt-Datenbank darf nicht als Bench-DB dienen")
    if cfg.daten_ordner.resolve() != leer or cfg.vault_ordner.resolve() != vault:
        raise RuntimeError("Daten- oder Vault-Ordner liegt ausserhalb des Arbeitsordners")
    if cfg["basis"]["datenquelle"] != "csv":
        raise RuntimeError("Die isolierte Config muss datenquelle = \"csv\" setzen")
    return ziel


def _arbeitsordner(pfad: Path | None) -> tuple[Path, bool]:
    """Liefert (Ordner, ist_temporaer); ein vorhandener Ordner muss leer sein."""
    if pfad is None:
        basis = ROOT / "artifacts"
        basis.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="orakel-messung-", dir=basis)), True

    ziel = pfad.resolve()
    if ziel == ROOT.resolve():
        raise SystemExit("--arbeitsordner darf nicht das Repository selbst sein")
    if ziel.exists():
        if not ziel.is_dir():
            raise SystemExit(f"--arbeitsordner ist keine Datei: {ziel}")
        if any(ziel.iterdir()):
            raise SystemExit(f"--arbeitsordner ist nicht leer: {ziel}")
    else:
        ziel.mkdir(parents=True)
    return ziel, False


def _hwm_mb(pid: int) -> float | None:
    """Liest den Spitzen-RSS (VmHWM) eines laufenden Prozesses unter Linux."""
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for zeile in status.splitlines():
        if zeile.startswith("VmHWM:"):
            return int(zeile.split()[1]) / 1024
    return None


def messen(phase: str, befehl: list[str], *, umgebung: dict[str, str]) -> Messung:
    """Startet einen Prozess und misst Wanduhrzeit und Spitzen-RSS getrennt."""
    start = time.perf_counter()
    prozess = subprocess.Popen(  # noqa: S603 - feste Argumentliste, keine Shell
        befehl, cwd=ROOT, env=umgebung
    )
    rss_mb = 0.0
    while prozess.poll() is None:
        wert = _hwm_mb(prozess.pid)
        if wert is not None:
            rss_mb = max(rss_mb, wert)
        time.sleep(0.02)
    code = prozess.wait()
    return Messung(phase=phase, dauer_s=time.perf_counter() - start,
                   rss_mb=rss_mb or None, exit=code)


def _umgebung() -> dict[str, str]:
    umgebung = os.environ.copy()
    alt = umgebung.get("PYTHONPATH")
    umgebung["PYTHONPATH"] = str(ROOT) + (os.pathsep + alt if alt else "")
    return umgebung


def _zeige(messungen: Sequence[Messung]) -> None:
    print(f"\n{'Phase':<34} {'Wanduhr':>10} {'Spitzen-RSS':>12}")
    print("-" * 60)
    for messung in messungen:
        rss = "n/a" if messung.rss_mb is None else f"{messung.rss_mb:.1f} MB"
        print(f"{messung.phase:<34} {messung.dauer_s:>8.2f} s {rss:>12}")


def _db_digest(db_pfad: Path) -> dict[str, object]:
    """Liest den Kerzeninhalt einer Bench-DB read-only und bildet einen Hash."""
    con = sqlite3.connect(f"file:{db_pfad}?mode=ro", uri=True)
    try:
        integritaet = con.execute("PRAGMA integrity_check").fetchone()[0]
        kopf = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT ts), MIN(ts), MAX(ts) FROM kerzen"
        ).fetchone()
        digest = hashlib.sha256()
        for zeile in con.execute(
            "SELECT symbol,zeitrahmen,ts,open,high,low,close,volume "
            "FROM kerzen ORDER BY symbol,zeitrahmen,ts"
        ):
            digest.update(("\x1f".join(str(wert) for wert in zeile) + "\n").encode())
        return {
            "integritaet": integritaet,
            "zeilen": kopf[0],
            "verschiedene_ts": kopf[1],
            "min_ts": kopf[2],
            "max_ts": kopf[3],
            "sha256": digest.hexdigest(),
        }
    finally:
        con.close()


def vergleiche_dbs(block: Path, zeilenweise: Path, cli: Path) -> dict[str, object]:
    """Vergleicht die Tabelle ``kerzen`` der drei Importvarianten logisch."""
    inhalte = {
        "blockweise": _db_digest(block),
        "zeilenweise": _db_digest(zeilenweise),
        "cli": _db_digest(cli),
    }
    return {
        **inhalte,
        "identisch": inhalte["blockweise"] == inhalte["zeilenweise"] == inhalte["cli"],
    }


def _messe_2_1_mio(args: argparse.Namespace, arbeitsordner: Path) -> int:
    """Misst die drei Importpfade für 2,1 Mio. Zeilen getrennt und vergleicht sie."""
    csv_pfad = arbeitsordner / "SYN1_M15.csv"
    print(f"Erzeuge 2,1-Mio.-Reihe bis {ENDE_2_1_MIO:%Y-%m-%d %H:%M} UTC, "
          f"Seed {args.seed} ...", flush=True)
    start = time.perf_counter()
    anzahl = erzeuge_grosse_reihe(csv_pfad, seed=args.seed)
    print(f"CSV: {anzahl} Zeilen in {time.perf_counter() - start:.2f} s, "
          f"{csv_pfad.stat().st_size / 1024 / 1024:.1f} MB", flush=True)

    cfg_pfade = {
        variante: isoliere_config(ROOT / "config.toml",
                                  arbeitsordner / f"config-{variante}.toml",
                                  arbeitsordner, db_name=f"{variante}.db")
        for variante in ("block", "zeilenweise", "cli")
    }
    db_pfade = {variante: arbeitsordner / f"{variante}.db" for variante in cfg_pfade}
    umgebung = _umgebung()
    messungen: list[Messung] = []

    for variante, bezeichnung in (("block", "Blockweise"),
                                  ("zeilenweise", "Zeilenweise"),
                                  ("cli", "CLI (blockweise)")):
        print(f"\n--- {bezeichnung} ---", flush=True)
        if variante == "cli":
            befehl = [sys.executable, "-m", "orakel", "--config",
                      str(cfg_pfade[variante]), "daten", "--csv", str(csv_pfad)]
        else:
            befehl = [sys.executable, "-c", IMPORT_CODE, variante, str(csv_pfad),
                      str(db_pfade[variante])]
        messung = messen(bezeichnung, befehl, umgebung=umgebung)
        messungen.append(messung)
        if messung.exit != 0:
            _zeige(messungen)
            print(f"\n{bezeichnung} fehlgeschlagen (Exit {messung.exit}).")
            return 1

    _zeige(messungen)
    vergleich = vergleiche_dbs(db_pfade["block"], db_pfade["zeilenweise"],
                               db_pfade["cli"])
    bericht = {
        "modus": MODUS_2_1_MIO,
        "zeilen_soll": ZIEL_ZEILEN_2_1_MIO,
        "seed": args.seed,
        "csv": str(csv_pfad),
        "datenbanken": {name: str(pfad) for name, pfad in db_pfade.items()},
        "messungen": [
            {"phase": m.phase, "wanduhr_s": round(m.dauer_s, 3),
             "spitzen_rss_mb": None if m.rss_mb is None else round(m.rss_mb, 1)}
            for m in messungen
        ],
        "vergleich": vergleich,
    }
    bericht_pfad = arbeitsordner / "bericht.json"
    bericht_pfad.write_text(json.dumps(bericht, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"\nVergleich Kerzeninhalt: "
          f"{'identisch' if vergleich['identisch'] else 'ABWEICHUNG'}")
    print(f"Bericht: {bericht_pfad}")
    print("Die bestehende orakel.db wurde nicht geöffnet; die drei Bench-DBs "
          "liegen im Arbeitsordner.")
    return 0 if vergleich["identisch"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synthetische Reihe: Import, Richterlauf oder 2,1-Mio.-Nachmessung."
    )
    parser.add_argument("--modus", choices=(MODUS_STANDARD, MODUS_2_1_MIO),
                        default=MODUS_STANDARD,
                        help="standard: Fünfjahresreihe mit Richterlauf; "
                             "2-1-mio: drei Importpfade mit 2.100.000 Zeilen vergleichen")
    parser.add_argument("--symbole", type=int, default=STANDARD_SYMBOLE, metavar="N",
                        help=f"Anzahl synthetischer Symbole (Standard: {STANDARD_SYMBOLE})")
    parser.add_argument("--seed", type=int, default=SEED, help=f"Zufallsseed (Standard: {SEED})")
    parser.add_argument("--arbeitsordner", type=Path, default=None,
                        help="leerer Ordner für Config/DB/CSV; ohne Angabe temporär unter artifacts/")
    args = parser.parse_args(argv)
    if args.symbole < 1:
        parser.error("--symbole muss mindestens 1 sein")
    if args.modus == MODUS_2_1_MIO and args.symbole != STANDARD_SYMBOLE:
        parser.error("--symbole gilt nur im Standardmodus")

    arbeitsordner, temporaer = _arbeitsordner(args.arbeitsordner)
    try:
        if args.modus == MODUS_2_1_MIO:
            return _messe_2_1_mio(args, arbeitsordner)

        print(f"Erzeuge synthetische Reihe: {START} bis {ENDE}, Seed {args.seed} ...", flush=True)
        zeilen = erzeuge_reihe(seed=args.seed)
        csv_pfade = []
        for i in range(1, args.symbole + 1):
            pfad = arbeitsordner / f"SYN{i}_M15.csv"
            schreibe_csv(pfad, zeilen)
            csv_pfade.append(pfad)

        cfg = isoliere_config(ROOT / "config.toml", arbeitsordner / "config.toml", arbeitsordner)
        db = arbeitsordner / "orakel.db"
        print(f"Daten: {len(zeilen)} Kerzen je Symbol, {args.symbole} Symbol(e), "
              f"{len(zeilen) * args.symbole} Kerzen gesamt", flush=True)
        print(f"Isolierte DB: {db}", flush=True)
        print(f"Python {platform.python_version()} · {platform.system()} {platform.release()} · "
              f"{os.cpu_count()} Kerne", flush=True)

        umgebung = _umgebung()
        messungen: list[Messung] = []

        print("\n--- Import ---", flush=True)
        import_messung = messen(
            "Import",
            [sys.executable, "-m", "orakel", "--config", str(cfg), "daten",
             "--csv", *(str(p) for p in csv_pfade)],
            umgebung=umgebung,
        )
        messungen.append(import_messung)
        if import_messung.exit != 0:
            _zeige(messungen)
            print(f"\nImport fehlgeschlagen (Exit {import_messung.exit}).")
            return 1

        print("\n--- Richter (nur Walk-Forward) ---", flush=True)
        richter_messung = messen(
            "Richter (nur Walk-Forward)",
            [sys.executable, "-c", RICHTER_CODE, str(cfg)],
            umgebung=umgebung,
        )
        messungen.append(richter_messung)
        if richter_messung.exit != 0:
            _zeige(messungen)
            print(f"\nRichterprüfung fehlgeschlagen (Exit {richter_messung.exit}).")
            return 1

        print("\n--- Vollständiger Lauf (orakel pruefen) ---", flush=True)
        voll_messung = messen(
            "Vollständiger Lauf",
            [sys.executable, "-m", "orakel", "--config", str(cfg), "pruefen",
             "--bericht", str(arbeitsordner / "bericht.json")],
            umgebung=umgebung,
        )
        messungen.append(voll_messung)
        if voll_messung.exit != 0:
            _zeige(messungen)
            print(f"\nVollständiger Lauf fehlgeschlagen (Exit {voll_messung.exit}).")
            return 1

        _zeige(messungen)
        print(f"\nImport je Symbol: {import_messung.dauer_s / args.symbole:.2f} s")
        print(f"Richter je Symbol (amortisiert): {richter_messung.dauer_s / args.symbole:.2f} s")
        print(f"Vollständiger Lauf je Symbol (amortisiert): "
              f"{voll_messung.dauer_s / args.symbole:.2f} s")
        print("\nDer Spitzen-RSS ist der höchste VmHWM des jeweiligen Prozesses, kein Summenwert.")
        print("Die bestehende orakel.db wurde nicht geöffnet; alle Pfade liegen im Arbeitsordner.")
        return 0
    finally:
        if temporaer:
            shutil.rmtree(arbeitsordner, ignore_errors=True)
        else:
            print(f"\nArbeitsordner behalten: {arbeitsordner}")


if __name__ == "__main__":
    raise SystemExit(main())
