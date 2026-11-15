#!/usr/bin/env python3
"""Gezielter Backoff-Fehlerfall für den Orakel-Dauerbetrieb.

Der Lauf ist bewusst kein Teil der sauberen Soak-Abnahme: Ein Spider-Job
scheitert einmal, der Backoff wird geprüft, und nach Ablauf versucht der
Scheduler den Job erfolgreich erneut. Es gibt keinen Netzwerk- oder
Broker-Aufruf.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orakel.betrieb import Betrieb  # noqa: E402
from orakel.config import load_config  # noqa: E402
from orakel.db import Facts  # noqa: E402

START = datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
BACKOFF_SEKUNDEN = 60


class Uhr:
    def __init__(self, start: datetime = START) -> None:
        self.jetzt = start

    def __call__(self) -> datetime:
        return self.jetzt

    def plus(self, sekunden: float) -> None:
        self.jetzt += timedelta(seconds=sekunden)


def _job(daten: dict[str, Any], name: str) -> dict[str, Any]:
    return next(j for j in daten["jobs"] if j["name"] == name)


def _kriterium(name: str, soll: Any, ist: Any, ok: bool) -> dict[str, Any]:
    return {"name": name, "soll": soll, "ist": ist, "ok": bool(ok)}


def _report(daten: dict[str, Any]) -> str:
    bestanden = all(k["ok"] for k in daten["kriterien"])
    zeilen = [
        "# Orakel Backoff-Fehlerfall",
        "",
        "**Ergebnis:** " + ("BESTANDEN" if bestanden else "NICHT BESTANDEN"),
        "**Einordnung:** Gezielter, deterministischer Fehlerfall – **nicht** Teil "
        "der sauberen 24-Stunden-Soak-Abnahme.",
        f"**Start (virtuell):** `{daten['start']}`",
        f"**Backoff-Basis:** `{daten['backoff_sekunden']} s`",
        "",
        "## Ablauf",
        "",
        "1. Spider-Job scheitert beim ersten Takt mit einem kontrollierten Fehler.",
        "2. Der Scheduler setzt den nächsten Versuch auf +60 s.",
        "3. Bei +30 s läuft der Job nicht; der Backoff bleibt wirksam.",
        "4. Bei +61 s scheitert auch der zweite Versuch; der Backoff verdoppelt "
        "sich auf 120 s.",
        "5. Bei +180 s läuft der Job noch nicht; der zweite Backoff bleibt aktiv.",
        "6. Bei +182 s läuft der Job erfolgreich; der Fehlerzähler wird "
        "zurückgesetzt.",
        "",
        "## Kriterien",
        "",
        "| Kriterium | Soll | Ist | Status |",
        "|---|---|---|---|",
    ]
    for k in daten["kriterien"]:
        zeilen.append(
            f"| {k['name']} | `{k['soll']}` | `{k['ist']}` | "
            f"{'OK' if k['ok'] else 'FEHLER'} |"
        )
    zeilen += [
        "",
        "## Messwerte",
        "",
        "```json",
        json.dumps(daten["messwerte"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Abgrenzung",
        "",
        "- Kein Broker- oder Netzwerkaufruf.",
        "- Kein Teil der sauberen Soak-Abnahme und kein Ersatz für den "
        "24-Stunden-Wanduhr-Lauf.",
    ]
    return "\n".join(zeilen) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("artifacts/backoff-fehlerfall"))
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="orakel-backoff-") as tmp:
        cfg = load_config(ROOT / "config.toml")
        cfg._d["basis"]["db_pfad"] = str(Path(tmp) / "backoff.db")
        cfg._d["basis"]["vault_ordner"] = str(Path(tmp) / "vault")
        cfg._d["basis"]["daten_ordner"] = str(Path(tmp) / "daten")
        cfg._d["betrieb"]["backoff_basis_sekunden"] = BACKOFF_SEKUNDEN
        cfg._d["betrieb"]["spider_backoff_max_sekunden"] = 3600
        db = Facts(cfg.db_pfad)
        uhr = Uhr()
        aufrufe: list[str] = []

        def kaputt() -> dict[str, Any]:
            aufrufe.append("fehler")
            raise RuntimeError("gezielter Backoff-Testfehler")

        erster = Betrieb(cfg, db, jetzt_funktion=uhr, jobs={"spider": kaputt})
        antwort1 = erster.takt()
        status1 = _job(erster.status_daten(uhr.jetzt), "spider")
        naechster = datetime.fromisoformat(str(status1["naechster_versuch"]))
        if naechster.tzinfo is None:
            naechster = naechster.replace(tzinfo=timezone.utc)

        uhr.plus(30)
        zweiter = Betrieb(
            cfg, db, jetzt_funktion=uhr,
            jobs={"spider": lambda: {"neu": 1, "gelesen": 1, "quellen": 1}},
        )
        antwort2 = zweiter.takt()
        status2 = _job(zweiter.status_daten(uhr.jetzt), "spider")

        # +61 s: Der zweite Versuch scheitert ebenfalls. Der Fehlerzähler
        # steigt auf 2, der Backoff muss sich von 60 auf 120 s verdoppeln.
        uhr.plus(31)
        dritter = Betrieb(cfg, db, jetzt_funktion=uhr, jobs={"spider": kaputt})
        antwort3 = dritter.takt()
        status3 = _job(dritter.status_daten(uhr.jetzt), "spider")
        zweiter_naechster = datetime.fromisoformat(str(status3["naechster_versuch"]))
        if zweiter_naechster.tzinfo is None:
            zweiter_naechster = zweiter_naechster.replace(tzinfo=timezone.utc)

        # +180 s: ein Szenario direkt vor dem zweiten Retry.
        uhr.plus(119)
        vierter = Betrieb(
            cfg, db, jetzt_funktion=uhr,
            jobs={"spider": lambda: {"neu": 1, "gelesen": 1, "quellen": 1}},
        )
        antwort4 = vierter.takt()
        status4 = _job(vierter.status_daten(uhr.jetzt), "spider")

        # +182 s: Erst jetzt ist der zweite Backoff abgelaufen.
        uhr.plus(2)
        fuenfter = Betrieb(
            cfg, db, jetzt_funktion=uhr,
            jobs={"spider": lambda: {"neu": 1, "gelesen": 1, "quellen": 1}},
        )
        antwort5 = fuenfter.takt()
        status5 = _job(fuenfter.status_daten(uhr.jetzt), "spider")

        kriterien = [
            _kriterium("Fehler erkannt", "spider in Antwort1 mit Fehler",
                       antwort1.get("spider"),
                       "spider" in antwort1 and "fehler" in antwort1["spider"]),
            _kriterium("Fehlerzähler", 1, status1["fehlschluesse"],
                       status1["fehlschluesse"] == 1),
            _kriterium("Backoff gesetzt", f"{BACKOFF_SEKUNDEN} s",
                       status1["backoff_sekunden"],
                       status1["backoff_sekunden"] == BACKOFF_SEKUNDEN),
            _kriterium("Nächster Versuch", "Start + 60 s",
                       naechster.isoformat(),
                       naechster == START + timedelta(seconds=BACKOFF_SEKUNDEN)),
            _kriterium("Kein Lauf bei +30 s", "spider nicht ausgeführt",
                       "spider" not in antwort2,
                       "spider" not in antwort2),
            _kriterium("Backoff bleibt bei +30 s", "Backoff aktiv",
                       status2["zustand"],
                       status2["zustand"] == "backoff"),
            _kriterium("Zweiter Fehler erkannt", "spider in Antwort3 mit Fehler",
                       antwort3.get("spider"),
                       "spider" in antwort3 and "fehler" in antwort3["spider"]),
            _kriterium("Fehlerzähler nach zweitem Fehler", 2,
                       status3["fehlschluesse"],
                       status3["fehlschluesse"] == 2),
            _kriterium("Backoff verdoppelt", f"{2 * BACKOFF_SEKUNDEN} s",
                       status3["backoff_sekunden"],
                       status3["backoff_sekunden"] == 2 * status1["backoff_sekunden"]),
            _kriterium("Nächster Versuch nach zweitem Fehler", "Start + 181 s",
                       zweiter_naechster.isoformat(),
                       zweiter_naechster == START + timedelta(
                           seconds=3 * BACKOFF_SEKUNDEN + 1)),
            _kriterium("Kein Lauf vor zweitem Retry", "spider nicht ausgeführt",
                       "spider" not in antwort4,
                       "spider" not in antwort4),
            _kriterium("Backoff bleibt vor zweitem Retry", "120 s aktiv",
                       status4["backoff_sekunden"],
                       status4["backoff_sekunden"] == 2 * BACKOFF_SEKUNDEN),
            _kriterium("Retry bei +182 s", "spider erfolgreich",
                       antwort5.get("spider"),
                       "spider" in antwort5 and "fehler" not in antwort5["spider"]),
            _kriterium("Fehlerzähler zurückgesetzt", 0,
                       status5["fehlschluesse"],
                       status5["fehlschluesse"] == 0),
            _kriterium("Zwei Fehlversuche", "zwei Fehleraufrufe",
                       aufrufe, aufrufe == ["fehler", "fehler"]),
        ]
        daten = {
            "start": START.isoformat(),
            "backoff_sekunden": BACKOFF_SEKUNDEN,
            "kriterien": kriterien,
            "messwerte": {
                "aufrufe": aufrufe,
                "erster_status": status1,
                "zweiter_status": status2,
                "dritter_status": status3,
                "vierter_status": status4,
                "fuenfter_status": status5,
                "antworten": {
                    "erster": str(antwort1),
                    "zweiter": str(antwort2),
                    "dritter": str(antwort3),
                    "vierter": str(antwort4),
                    "fuenfter": str(antwort5),
                },
            },
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "messwerte.json").write_text(
        json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(_report(daten), encoding="utf-8")
    print(f"BACKOFF_BERICHT {args.output_dir / 'report.md'}")
    print("ERGEBNIS " + ("BESTANDEN" if all(k["ok"] for k in kriterien)
                         else "NICHT BESTANDEN"))
    return 0 if all(k["ok"] for k in kriterien) else 1


if __name__ == "__main__":
    raise SystemExit(main())
