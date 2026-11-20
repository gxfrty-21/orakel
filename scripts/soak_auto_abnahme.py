#!/usr/bin/env python3
"""Wartet auf das Ende eines Soak-Monitors und startet die Abnahme.

Der Watcher ist absichtlich ein separater Prozess: Ein bereits laufender
24-Stunden-Monitor muss nicht neu gestartet werden. Nach dem Monitor-Ende
ruft er ``soak_abnahme.py`` auf und schreibt Ergebnis, Exit-Code und Log in
den Soak-Ordner.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ABNAHME = ROOT / "scripts" / "soak_abnahme.py"
MIN_REGULAER_ANTEIL = 0.98


def jetzt() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def laeuft(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    stat = Path(f"/proc/{pid}/stat")
    try:
        teile = stat.read_text(encoding="utf-8").split()
    except OSError:
        return True
    return len(teile) < 3 or teile[2] != "Z"


def _monitor_status(ausgabe: Path) -> dict[str, Any] | None:
    pfad = ausgabe / "monitor-status.json"
    try:
        wert = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return wert if isinstance(wert, dict) else None


def _health_dauer(ausgabe: Path) -> float | None:
    pfad = ausgabe / "health.jsonl"
    zeiten: list[float] = []
    try:
        zeilen = pfad.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for zeile in zeilen:
        try:
            wert = json.loads(zeile)
        except (ValueError, TypeError):
            continue
        ts = wert.get("ts_epoch") if isinstance(wert, dict) else None
        if isinstance(ts, (int, float)):
            zeiten.append(float(ts))
    return max(zeiten) - min(zeiten) if len(zeiten) >= 2 else None


def monitor_ausgang(ausgabe: Path, soll_dauer_sekunden: float) -> dict[str, Any]:
    """Unterscheidet einen regulären Abschluss von einem vorzeitigen Abbruch."""
    status = _monitor_status(ausgabe)
    if status is not None:
        if status.get("regulaer") is True:
            return {
                "monitor_ausgang": "regulaer",
                "monitor_abbruch": False,
                "monitor_dauer_s": status.get("dauer_sekunden"),
                "monitor_soll_dauer_s": round(soll_dauer_sekunden, 1),
                "monitor_status_quelle": "monitor-status.json",
                "monitor_abbruch_grund": None,
            }
        if status.get("abbruch") is True or status.get("regulaer") is False:
            return {
                "monitor_ausgang": "abgebrochen",
                "monitor_abbruch": True,
                "monitor_dauer_s": status.get("dauer_sekunden"),
                "monitor_soll_dauer_s": round(soll_dauer_sekunden, 1),
                "monitor_status_quelle": "monitor-status.json",
                "monitor_abbruch_grund": (
                    status.get("abbruch_grund") or "Monitor meldet vorzeitigen Abbruch"
                ),
            }

    # Fallback für einen bereits laufenden, älteren Monitor ohne Statusdatei.
    dauer = _health_dauer(ausgabe)
    regulaer = (
        dauer is not None
        and soll_dauer_sekunden > 0
        and dauer >= soll_dauer_sekunden * MIN_REGULAER_ANTEIL
    )
    return {
        "monitor_ausgang": "regulaer" if regulaer else "abgebrochen",
        "monitor_abbruch": not regulaer,
        "monitor_dauer_s": round(dauer, 1) if dauer is not None else None,
        "monitor_soll_dauer_s": round(soll_dauer_sekunden, 1),
        "monitor_status_quelle": "health-fallback",
        "monitor_abbruch_grund": None if regulaer else (
            "Keine ausreichende Health-Messreihe für die Soll-Dauer"
        ),
    }


def _status_schreiben(status_datei: Path, status: dict[str, Any]) -> None:
    tmp = status_datei.with_suffix(status_datei.suffix + ".tmp")
    tmp.write_text(
        json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(status_datei)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monitor-pid", type=int, required=True,
                        help="PID des laufenden soak_monitor.py")
    parser.add_argument("--verzeichnis", type=Path,
                        default=Path("artifacts/soak-24h"))
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--duration-hours", type=float, default=24.0,
                        help="Soll-Dauer des Monitors für die Abbruch-Erkennung")
    parser.add_argument("--status-datei", type=Path, default=None)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds muss positiv sein")
    if args.duration_hours <= 0:
        parser.error("--duration-hours muss positiv sein")

    ausgabe = args.verzeichnis
    status_datei = args.status_datei or ausgabe / "abnahme-status.json"
    log_datei = ausgabe / "abnahme.log"
    ausgabe.mkdir(parents=True, exist_ok=True)
    status_datei.parent.mkdir(parents=True, exist_ok=True)

    print(f"ABNAHME_WATCHER_START {jetzt()} monitor_pid={args.monitor_pid} "
          f"verzeichnis={ausgabe}", flush=True)
    while laeuft(args.monitor_pid):
        time.sleep(args.poll_seconds)

    beginn = jetzt()
    ausgang = monitor_ausgang(ausgabe, args.duration_hours * 3600)
    print(f"MONITOR_BEENDET {beginn} ausgang={ausgang['monitor_ausgang']} "
          f"quelle={ausgang['monitor_status_quelle']}", flush=True)

    if ausgang["monitor_abbruch"]:
        status: dict[str, Any] = {
            **ausgang,
            "monitor_pid": args.monitor_pid,
            "monitor_beendet": beginn,
            "abnahme_ende": jetzt(),
            "abnahme_gestartet": False,
            "exit_code": 1,
            "bestanden": False,
            "bericht": None,
            "messwerte": None,
            "stdout": "",
            "stderr": "",
            "grund": "Monitor vorzeitig beendet; keine Abnahme gestartet",
        }
        _status_schreiben(status_datei, status)
        log = (
            f"ABNAHME_NICHT_GESTARTET {status['abnahme_ende']}\n"
            f"MONITOR_AUSGANG {ausgang['monitor_ausgang']}\n"
            f"MONITOR_GRUND {ausgang['monitor_abbruch_grund']}\n"
            f"EXIT_CODE 1\n"
            f"ERGEBNIS NICHT BESTANDEN\n"
            f"STATUS {status_datei}\n"
        )
        log_datei.write_text(log, encoding="utf-8")
        print(log, end="", flush=True)
        return 1

    proc = subprocess.run(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
        [sys.executable, str(ABNAHME), "--verzeichnis", str(ausgabe)],
        capture_output=True, text=True, check=False,
    )
    exit_code = int(proc.returncode)
    bestanden = exit_code == 0
    status = {
        **ausgang,
        "monitor_pid": args.monitor_pid,
        "monitor_beendet": beginn,
        "abnahme_gestartet": True,
        "abnahme_ende": jetzt(),
        "exit_code": exit_code,
        "bestanden": bestanden,
        "bericht": str(ausgabe / "report.md"),
        "messwerte": str(ausgabe / "messwerte.json"),
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }
    _status_schreiben(status_datei, status)
    log = (
        f"ABNAHME_ENDE {status['abnahme_ende']}\n"
        f"MONITOR_AUSGANG {ausgang['monitor_ausgang']}\n"
        f"EXIT_CODE {exit_code}\n"
        f"ERGEBNIS {'BESTANDEN' if bestanden else 'NICHT BESTANDEN'}\n"
        f"BERICHT {status['bericht']}\n"
        f"MESSWERTE {status['messwerte']}\n"
        f"STATUS {status_datei}\n"
        f"{status['stdout']}\n"
    )
    log_datei.write_text(log, encoding="utf-8")
    print(log, end="", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
