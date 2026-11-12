#!/usr/bin/env python3
"""Kurzer, wiederaufsetzbarer Soak-Monitor für den Railway-Dauerbetrieb.

Der Monitor fragt den öffentlichen Health-Endpunkt jede Minute ab und holt
alle zehn Minuten den vollständigen Betriebszustand über Railway-SSH. Die
Messreihen und eine fortlaufend aktualisierte Zusammenfassung landen unter
``artifacts/`` und werden nicht versioniert.
"""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HEALTH_URL = "https://orakel-production-fb18.up.railway.app/api/health"
RAILWAY_CMD = [
    "npx",
    "--yes",
    "@railway/cli@latest",
    "ssh",
    "--service",
    "orakel",
    "--environment",
    "production",
    "--",
    "sh",
    "-lc",
    "cd /app && ORAKEL_DB_PFAD=/data/orakel.db "
    "python -m orakel --config /app/config.toml betrieb --json",
]
STOP = threading.Event()


def jetzt() -> datetime:
    return datetime.now(timezone.utc)


def iso(wert: datetime | None = None) -> str:
    return (wert or jetzt()).isoformat(timespec="seconds")


def zahl(wert: Any) -> float | None:
    return float(wert) if isinstance(wert, (int, float)) else None


def health_holen(timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(HEALTH_URL, headers={"User-Agent": "orakel-soak-monitor/1"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as antwort:
            rohtext = antwort.read().decode("utf-8")
            daten = json.loads(rohtext)
            return {
                "ts": iso(),
                "ts_epoch": time.time(),
                "ok": True,
                "http": int(getattr(antwort, "status", 200)),
                "dauer_ms": round((time.monotonic() - start) * 1000),
                "daten": daten,
            }
    except Exception as exc:
        return {
            "ts": iso(),
            "ts_epoch": time.time(),
            "ok": False,
            "fehler": f"{type(exc).__name__}: {exc}",
            "dauer_ms": round((time.monotonic() - start) * 1000),
        }


def deep_holen(timeout: float) -> dict[str, Any]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            RAILWAY_CMD,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip().splitlines()
            letzte = " | ".join(stderr[-3:]) if stderr else "kein stderr"
            raise RuntimeError(f"Railway-SSH rc={proc.returncode}: {letzte}")
        text = proc.stdout or ""
        start_json = text.find("{")
        if start_json < 0:
            raise RuntimeError("kein JSON in der SSH-Antwort")
        daten = json.loads(text[start_json:])
        return {
            "ts": iso(),
            "ok": True,
            "dauer_ms": round((time.monotonic() - start) * 1000),
            "daten": daten,
        }
    except Exception as exc:
        return {
            "ts": iso(),
            "ok": False,
            "fehler": f"{type(exc).__name__}: {exc}",
            "dauer_ms": round((time.monotonic() - start) * 1000),
        }


def anhaengen(pfad: Path, zeile: dict[str, Any]) -> None:
    with pfad.open("a", encoding="utf-8") as datei:
        datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")
        datei.flush()


def _health_daten(zeilen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [z["daten"] for z in zeilen if z.get("ok") and isinstance(z.get("daten"), dict)]


def _deep_daten(zeilen: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [z["daten"] for z in zeilen if z.get("ok") and isinstance(z.get("daten"), dict)]


def _betrieb(daten: dict[str, Any]) -> dict[str, Any]:
    return daten.get("betrieb") if isinstance(daten.get("betrieb"), dict) else {}


def _markdown_zusammenfassung(
    start: datetime,
    ende: datetime,
    health: list[dict[str, Any]],
    deep: list[dict[str, Any]],
    out: Path,
) -> str:
    hd = _health_daten(health)
    dd = _deep_daten(deep)
    fehler_health = [z for z in health if not z.get("ok")]
    fehler_deep = [z for z in deep if not z.get("ok")]
    status = Counter(str(_betrieb(d).get("status") or "unbekannt") for d in hd)
    commits = sorted({str(d.get("commit")) for d in hd if d.get("commit")})
    takte = sorted({str(_betrieb(d).get("letzter_takt")) for d in hd
                    if _betrieb(d).get("letzter_takt")})
    paper = sorted({str(d.get("paper_tick")) for d in hd if d.get("paper_tick")})
    warnungen = [_betrieb(d).get("warnungen") for d in hd]
    hinweise = [_betrieb(d).get("hinweise") for d in hd]
    db_werte = [zahl(_betrieb(d).get("db_mb")) for d in hd]
    db_werte = [x for x in db_werte if x is not None]
    rss_werte = [zahl(_betrieb(d).get("rss_mb")) for d in hd]
    rss_werte = [x for x in rss_werte if x is not None]
    luecken = []
    for a, b in zip(hd, hd[1:]):
        luecken.append(float(b.get("ts_epoch", 0)) - float(a.get("ts_epoch", 0)))

    job_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "max_fehler": 0, "max_backoff": 0, "letzter_erfolg": None,
        "letzter_fehler": "", "fehlertexte": set(),
    })
    laeufe: dict[tuple[str, Any], dict[str, Any]] = {}
    deep_warnungen: set[tuple[str, str, str]] = set()
    for d in dd:
        for job in d.get("jobs") or []:
            if not isinstance(job, dict):
                continue
            name = str(job.get("name") or "?")
            s = job_stats[name]
            s["max_fehler"] = max(s["max_fehler"], int(job.get("fehlschluesse") or 0))
            s["max_backoff"] = max(s["max_backoff"], int(job.get("backoff_sekunden") or 0))
            if job.get("letzter_erfolg"):
                s["letzter_erfolg"] = job["letzter_erfolg"]
            fehler = job.get("letzter_fehler") or {}
            if isinstance(fehler, dict) and fehler.get("text"):
                s["letzter_fehler"] = str(fehler["text"])
                s["fehlertexte"].add(str(fehler["text"]))
            elif fehler:
                s["letzter_fehler"] = str(fehler)
                s["fehlertexte"].add(str(fehler))
        for lauf in d.get("letzte_laeufe") or []:
            if isinstance(lauf, dict):
                laeufe[(str(lauf.get("job")), lauf.get("id"))] = lauf
        for w in d.get("warnungen") or []:
            if isinstance(w, dict):
                deep_warnungen.add((str(w.get("stufe")), str(w.get("job")),
                                    str(w.get("text"))))

    lauf_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for lauf in laeufe.values():
        lauf_counts[str(lauf.get("job"))][str(lauf.get("status"))] += 1
    spider_runs = sorted(
        (lauf for lauf in laeufe.values() if lauf.get("job") == "spider"),
        key=lambda x: str(x.get("zeit") or ""),
    )

    def minmax(werte: list[float]) -> str:
        if not werte:
            return "keine Messwerte"
        return f"min {min(werte):.2f}, max {max(werte):.2f}, zuletzt {werte[-1]:.2f}"

    zeilen = [
        "# Orakel Dauerbetrieb – Soak",
        "",
        f"- Start: `{iso(start)}`",
        f"- Ende: `{iso(ende)}`",
        f"- Laufzeit: `{(ende - start).total_seconds():.0f} s`",
        f"- Health-Samples: `{len(health)}` (Fehler: `{len(fehler_health)}`)",
        f"- Tiefen-Samples: `{len(deep)}` (Fehler: `{len(fehler_deep)}`)",
        f"- Commit(s): `{', '.join(commits) or 'keine'}`",
        "",
        "## Takt und Health",
        "",
        f"- Status: `{', '.join(f'{k}={v}' for k, v in sorted(status.items())) or 'keine'} `",
        f"- Verschiedene Taktzeitpunkte: `{len(takte)}`",
        f"- Verschiedene Paper-Tick-Zeitpunkte: `{len(paper)}`",
        f"- Maximale Health-Lücke: `{max(luecken):.1f} s`" if luecken else "- Maximale Health-Lücke: `keine`",
        f"- Warnungen (max.): `{max([int(x) for x in warnungen if isinstance(x, int)] or [0])}`",
        f"- Hinweise (max.): `{max([int(x) for x in hinweise if isinstance(x, int)] or [0])}`",
        "",
        "## Ressourcen",
        "",
        f"- DB: `{minmax(db_werte)} MB`",
        f"- Prozess-RSS: `{minmax(rss_werte)} MB`",
        "",
        "## Jobs, Backoff und Spider",
        "",
        "| Job | Läufe ok | Fehler | übersprungen | max. Fehlversuche | max. Backoff | letzter Erfolg |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for name in sorted(job_stats):
        s = job_stats[name]
        counts = lauf_counts.get(name, Counter())
        zeilen.append(
            f"| `{name}` | {counts.get('ok', 0)} | {counts.get('fehler', 0)} | "
            f"{counts.get('uebersprungen', 0)} | {s['max_fehler']} | "
            f"{s['max_backoff']} s | `{s['letzter_erfolg'] or '–'}` |"
        )
    zeilen += ["", "### Spider-Läufe", ""]
    if spider_runs:
        for lauf in spider_runs:
            zeilen.append(
                f"- `{lauf.get('zeit')}`: **{lauf.get('status')}** "
                f"({lauf.get('dauer_ms')} ms)"
                + (f" – {lauf.get('fehler')}" if lauf.get("fehler") else "")
            )
    else:
        zeilen.append("- Keine Spider-Läufe in den Tiefen-Samples.")
    zeilen += ["", "## Tiefe Warnungen", ""]
    if deep_warnungen:
        for stufe, job, text in sorted(deep_warnungen):
            zeilen.append(f"- `{stufe}` / `{job}`: {text}")
    else:
        zeilen.append("- Keine Warnungen in den Tiefen-Samples.")
    zeilen += ["", "## Auffälligkeiten", ""]
    auffaellig = []
    if fehler_health:
        auffaellig.append(f"{len(fehler_health)} Health-Abrufe fehlgeschlagen")
    if fehler_deep:
        auffaellig.append(f"{len(fehler_deep)} Tiefenabrufe fehlgeschlagen")
    if luecken and max(luecken) > 180:
        auffaellig.append(f"Health-Lücke {max(luecken):.0f} s > 180 s")
    if any(k != "laeuft" for k in status):
        auffaellig.append("Taktstatus war nicht durchgehend `laeuft`")
    if any(int(x) for x in warnungen if isinstance(x, int)):
        auffaellig.append("Health meldete Warnungen")
    if any(s["max_backoff"] for s in job_stats.values()):
        auffaellig.append("Mindestens ein Job hatte Backoff")
    if not auffaellig:
        auffaellig.append("Keine Auffälligkeiten.")
    zeilen += [f"- {x}" for x in auffaellig]
    zeilen += ["", f"_Messreihen: `{out / 'health.jsonl'}` und `{out / 'betrieb.jsonl'}`._", ""]
    return "\n".join(zeilen)


def zusammenfassung_schreiben(
    start: datetime, health: list[dict[str, Any]], deep: list[dict[str, Any]],
    out: Path, ende: datetime | None = None,
) -> None:
    text = _markdown_zusammenfassung(start, ende or jetzt(), health, deep, out)
    ziel = out / "summary.md"
    tmp = out / ".summary.md.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(ziel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-hours", type=float, default=24.0)
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    parser.add_argument("--deep-interval-seconds", type=float, default=600.0)
    parser.add_argument("--health-timeout", type=float, default=20.0)
    parser.add_argument("--ssh-timeout", type=float, default=75.0)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    if args.duration_hours <= 0 or args.interval_seconds <= 0:
        parser.error("Dauer und Intervall müssen positiv sein")

    start = jetzt()
    out = args.output_dir or Path("artifacts") / f"soak-{start.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    health: list[dict[str, Any]] = []
    deep: list[dict[str, Any]] = []
    health_pfad = out / "health.jsonl"
    deep_pfad = out / "betrieb.jsonl"

    def stoppe(_signum: int, _frame: Any) -> None:
        STOP.set()

    signal.signal(signal.SIGINT, stoppe)
    signal.signal(signal.SIGTERM, stoppe)

    print(f"SOAK_START {iso(start)}", flush=True)
    print(f"OUTPUT_DIR {out}", flush=True)
    print(f"DAUER {args.duration_hours:g} h, HEALTH {args.interval_seconds:g} s, "
          f"DEEP {args.deep_interval_seconds:g} s", flush=True)

    deadline = time.monotonic() + args.duration_hours * 3600
    next_deep = time.monotonic()
    while not STOP.is_set() and time.monotonic() < deadline:
        h = health_holen(args.health_timeout)
        health.append(h)
        anhaengen(health_pfad, h)
        if h["ok"]:
            b = _betrieb(h["daten"])
            print(f"{h['ts']} health status={b.get('status')} "
                  f"takt={b.get('letzter_takt')} paper={h['daten'].get('paper_tick')} "
                  f"warn={b.get('warnungen')} hinweis={b.get('hinweise')} "
                  f"db={b.get('db_mb')} rss={b.get('rss_mb')}", flush=True)
        else:
            print(f"{h['ts']} health FEHLER {h.get('fehler')}", flush=True)

        if time.monotonic() >= next_deep:
            d = deep_holen(args.ssh_timeout)
            deep.append(d)
            anhaengen(deep_pfad, d)
            if d["ok"]:
                daten = d["daten"]
                jobs = daten.get("jobs") or []
                print(f"{d['ts']} deep takt={daten.get('takt', {}).get('status')} "
                      f"spider={next((j.get('letzter_erfolg') for j in jobs if j.get('name') == 'spider'), None)} "
                      f"warnungen={len(daten.get('warnungen') or [])}", flush=True)
            else:
                print(f"{d['ts']} deep FEHLER {d.get('fehler')}", flush=True)
            next_deep = time.monotonic() + args.deep_interval_seconds

        zusammenfassung_schreiben(start, health, deep, out)
        rest = min(args.interval_seconds, max(0.0, deadline - time.monotonic()))
        if rest > 0:
            STOP.wait(rest)

    ende = jetzt()
    zusammenfassung_schreiben(start, health, deep, out, ende)
    print(f"SOAK_ENDE {iso(ende)} samples={len(health)} deep={len(deep)} "
          f"summary={out / 'summary.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
