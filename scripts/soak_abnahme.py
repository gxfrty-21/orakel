#!/usr/bin/env python3
"""Reproduzierbarer 24-Stunden-Soak-Bericht für den Orakel-Dauerbetrieb.

Zwei Modi:

* ``--simulieren``: 24 Stunden virtuelle Zeit in 288 Fünf-Minuten-Takten.
  Alle Jobs sind deterministische Stubs; es gibt keine Netzwerk- oder
  Broker-Aufrufe. Das prüft den Scheduler, die Persistenz und die
  Betriebsgrenzen, nicht die echte Wall-Clock-Stabilität.
* ``--verzeichnis``: wertet die von ``scripts/soak_monitor.py`` erzeugten
  ``health.jsonl``- und ``betrieb.jsonl``-Messreihen eines echten
  24-Stunden-Laufs aus, einschließlich Audit-Kette, Company-Queue und
  Backup-Restore aus den Tiefen-Samples.

Der Bericht wird als Markdown und die Rohwerte als JSON geschrieben.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orakel.betrieb import Betrieb  # noqa: E402
from orakel.company.store import CompanyStore  # noqa: E402
from orakel.config import load_config  # noqa: E402
from orakel.kern.db import Facts  # noqa: E402

SIM_TAKTE = 24 * 12
SIM_SCHRITT_SEKUNDEN = 300
MAX_HEALTH_LUECKE_SEKUNDEN = 180.0
MAX_HEALTH_FEHLER = 5
MIN_HEALTH_SAMPLES = 1380
MIN_PAPER_TICKS = 288
MAX_DB_MB = 512.0
MAX_RSS_MB = 768.0
MIN_FREIER_SPEICHER_MB = 256.0
MAX_QUEUE_ALTER_SEKUNDEN = 3600.0
MAX_BACKUP_ALTER_SEKUNDEN = 48 * 3600.0
SPIDER_STUNDEN = [0, 6, 12, 18]


class VirtuelleUhr:
    def __init__(self, start: datetime) -> None:
        self.jetzt = start

    def __call__(self) -> datetime:
        return self.jetzt

    def plus(self, sekunden: float) -> None:
        self.jetzt += timedelta(seconds=sekunden)


def _commit() -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],  # noqa: S607 - Programmname und Argumente sind fest verdrahtet
            capture_output=True, text=True, timeout=5, check=False,
        )
        commit = (proc.stdout or "").strip() or "unbekannt"
        status = subprocess.run(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
            ["git", "-C", str(ROOT), "status", "--porcelain"],  # noqa: S607 - Programmname und Argumente sind fest verdrahtet
            capture_output=True, text=True, timeout=5, check=False,
        )
        return f"{commit}+dirty" if (status.stdout or "").strip() else commit
    except Exception:
        return "unbekannt"


def _jsonl(pfad: Path) -> list[dict[str, Any]]:
    if not pfad.exists():
        return []
    zeilen: list[dict[str, Any]] = []
    for nummer, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1):
        if not zeile.strip():
            continue
        try:
            wert = json.loads(zeile)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{pfad}:{nummer}: ungültiges JSON: {exc}") from exc
        if isinstance(wert, dict):
            zeilen.append(wert)
    return zeilen


def _health_daten(zeilen: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [z["daten"] for z in zeilen
            if z.get("ok") and isinstance(z.get("daten"), dict)]


def _betrieb(daten: dict[str, Any]) -> dict[str, Any]:
    wert = daten.get("betrieb")
    return wert if isinstance(wert, dict) else {}


def _zahl(wert: Any) -> float | None:
    return float(wert) if isinstance(wert, (int, float)) else None

def _zeit(wert: Any) -> datetime | None:
    try:
        zeit = datetime.fromisoformat(str(wert))
    except (TypeError, ValueError):
        return None
    return zeit.replace(tzinfo=timezone.utc) if zeit.tzinfo is None else zeit.astimezone(timezone.utc)


def _max(werte: Iterable[float | None]) -> float | None:
    echte = [w for w in werte if w is not None]
    return max(echte) if echte else None


def _min(werte: Iterable[float | None]) -> float | None:
    echte = [w for w in werte if w is not None]
    return min(echte) if echte else None


def _kriterium(name: str, schwelle: str, wert: Any, bestanden: bool) -> dict[str, Any]:
    return {"name": name, "schwelle": schwelle, "wert": wert, "bestanden": bool(bestanden)}


def _simulation(config_pfad: Path) -> dict[str, Any]:
    start = datetime(2026, 11, 15, 0, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix="orakel-soak-") as tmp:
        cfg = load_config(config_pfad)
        cfg._d["basis"]["db_pfad"] = str(Path(tmp) / "orakel-soak.db")
        cfg._d["basis"]["vault_ordner"] = str(Path(tmp) / "vault")
        cfg._d["basis"]["daten_ordner"] = str(Path(tmp) / "daten")
        # Genug Platz für 24 Stunden Jobprotokoll, damit die Zählung nicht
        # durch die produktive Trim-Grenze abgeschnitten wird.
        cfg._d["betrieb"]["max_laeufe"] = 5000
        db = Facts(cfg.db_pfad)
        uhr = VirtuelleUhr(start)

        # Zuerst den echten Plan lesen, dann alle Jobs durch Stubs ersetzen.
        basis = Betrieb(cfg, db, jetzt_funktion=uhr)
        aufrufe: Counter[str] = Counter()
        spider_zeiten: list[datetime] = []

        def stub(name: str):
            def lauf() -> dict[str, Any]:
                aufrufe[name] += 1
                if name == "spider":
                    spider_zeiten.append(uhr.jetzt)
                return {"ok": True, "job": name, "zeit": uhr.jetzt.isoformat()}
            return lauf

        jobs = {job.name: stub(job.name) for job in basis.jobs}
        betrieb = Betrieb(cfg, db, jetzt_funktion=uhr, jobs=jobs)

        # Ein absichtlich offener synthetischer Task macht das Queue-Alter
        # messbar. Er ist kein Produktionsnachweis und wird nicht abgearbeitet.
        store = CompanyStore(db)
        store.sync_roster()
        queue_task = store.enqueue(
            task_key="soak:queue:1", assigned_to="A1", dept="A",
            title="Soak-Warteschlange", description="Bleibt für die Altersmessung offen.",
        )
        with db.conn() as c:
            c.execute(
                "UPDATE agent_tasks SET created_at=?, updated_at=? WHERE id=?",
                (start.isoformat(), start.isoformat(), queue_task),
            )

        db_werte: list[float | None] = []
        rss_werte: list[float | None] = []
        frei_werte: list[float | None] = []
        takt_status: list[str] = []
        health_status: list[str] = []
        health_gaps: list[float] = []
        letzte_health: datetime | None = None
        uebersprungen = 0
        for _ in range(SIM_TAKTE):
            antwort = betrieb.takt()
            takt_status.append(str(antwort.get("betrieb", {}).get("status")))
            uebersprungen += len(antwort.get("betrieb", {}).get("uebersprungen") or {})
            zustand = betrieb.status_daten(uhr.jetzt)
            ressourcen = zustand.get("ressourcen") or {}
            db_werte.append(_zahl(ressourcen.get("db_mb")))
            rss_werte.append(_zahl(ressourcen.get("rss_mb")))
            frei_werte.append(_zahl(ressourcen.get("freier_speicher_mb")))
            # Virtuelle Health-Samples im Minutentakt; keine echten Netzabrufe.
            for minute in range(5):
                hzustand = betrieb.status_daten(uhr.jetzt)
                health_status.append(str((hzustand.get("takt") or {}).get("status")))
                if letzte_health is not None:
                    health_gaps.append((uhr.jetzt - letzte_health).total_seconds())
                letzte_health = uhr.jetzt
                if minute < 4:
                    uhr.plus(60)
            uhr.plus(60)

        ende = uhr.jetzt
        zustand = betrieb.status_daten(ende)
        takt = zustand.get("takt") or {}
        jobs_am_ende = zustand.get("jobs") or []
        max_fehler = max((int(j.get("fehlschluesse") or 0) for j in jobs_am_ende), default=0)
        max_backoff = max((int(j.get("backoff_sekunden") or 0) for j in jobs_am_ende), default=0)
        audit_ok = store.audit_chain_ok()
        spider_stunden = sorted({
            int((zeit - start).total_seconds() // 3600) for zeit in spider_zeiten
        })
        dauer_stunden = (ende - start).total_seconds() / 3600
        max_db = _max(db_werte)
        max_rss = _max(rss_werte)
        min_frei = _min(frei_werte)
        max_health_gap = max(health_gaps) if health_gaps else None
        queue_offen = store.tasks("queued", limit=5000)
        queue_alter = [
            (ende - zeit).total_seconds()
            for task in queue_offen
            if (zeit := _zeit(task.get("created_at"))) is not None
        ]
        queue_age_max = max(queue_alter) if queue_alter else None
        db_start = db_werte[0] if db_werte else None
        db_ende = db_werte[-1] if db_werte else None
        db_wachstum = (round(db_ende - db_start, 3)
                       if db_start is not None and db_ende is not None else None)
        nicht_spider = {name: n for name, n in aufrufe.items() if name != "spider"}

        kriterien = [
            _kriterium("Dauer", "24 h virtuelle Zeit", f"{dauer_stunden:.2f} h",
                       abs(dauer_stunden - 24.0) < 0.01),
            _kriterium("Takte", f"{SIM_TAKTE} Fünf-Minuten-Takte", len(takt_status),
                       len(takt_status) == SIM_TAKTE),
            _kriterium("Taktstatus", "durchgehend ok", f"{takt_status.count('ok')}/{len(takt_status)}",
                       bool(takt_status) and all(x == "ok" for x in takt_status)),
            _kriterium("Takt-Monitor", "laeuft", takt.get("status"),
                       takt.get("status") == "laeuft"),
            _kriterium("Job-Fehler", "0", max_fehler, max_fehler == 0),
            _kriterium("Job-Backoff", "0 s", max_backoff, max_backoff == 0),
            _kriterium("Ressourcen-Skips", "0", uebersprungen, uebersprungen == 0),
            _kriterium("DB-Wachstum", f"< {MAX_DB_MB:g} MB", max_db,
                       max_db is not None and max_db < MAX_DB_MB),
            _kriterium("Prozess-RSS", f"< {MAX_RSS_MB:g} MB", max_rss,
                       max_rss is not None and max_rss < MAX_RSS_MB),
            _kriterium("Freier Speicher", f"> {MIN_FREIER_SPEICHER_MB:g} MB", min_frei,
                       min_frei is not None and min_frei > MIN_FREIER_SPEICHER_MB),
            _kriterium("Spider-Zeitplan", "0, 6, 12, 18 Uhr", spider_stunden,
                       spider_stunden == SPIDER_STUNDEN),
            _kriterium("Fünf-Minuten-Jobs", "je 288 Läufe",
                       dict(sorted(nicht_spider.items())),
                       bool(nicht_spider) and all(n == SIM_TAKTE for n in nicht_spider.values())),
            _kriterium("Health-Simulation", "1440 Samples, Lücke <= 60 s",
                       f"{len(health_status)} / {max_health_gap}s",
                       len(health_status) == SIM_TAKTE * 5
                       and max_health_gap is not None and max_health_gap <= 60),
            _kriterium("Audit-Kette", "ok", audit_ok, audit_ok),
        ]
        return {
            "modus": "simulation",
            "start": start.isoformat(),
            "ende": ende.isoformat(),
            "commit": _commit(),
            "kriterien": kriterien,
            "metriken": {
                "dauer_stunden": round(dauer_stunden, 3),
                "takte": len(takt_status),
                "job_aufrufe": dict(sorted(aufrufe.items())),
                "spider_stunden": spider_stunden,
                "max_db_mb": max_db,
                "db_start_mb": db_start,
                "db_ende_mb": db_ende,
                "db_wachstum_mb": db_wachstum,
                "max_rss_mb": max_rss,
                "min_freier_speicher_mb": min_frei,
                "health_samples": len(health_status),
                "max_health_luecke_s": max_health_gap,
                "health_status": dict(sorted(Counter(health_status).items())),
                "job_fehler": max_fehler,
                "job_backoff_s": max_backoff,
                "audit_ok": audit_ok,
                "queue_offen": len(queue_offen),
                "queue_alter_max_s": queue_age_max,
                "uebersprungen": uebersprungen,
            },
            "hinweise": [
                "Simulation mit virtueller Uhr und deterministischen Stub-Jobs.",
                "Health-Samples sind virtuelle 60-s-Abfragen, keine echten Netzabrufe.",
                "Queue-Alter stammt aus einem absichtlich offenen synthetischen Task.",
                "Kein echter Wanduhr-, Netzwerk- oder Broker-Test.",
                "Der reale Nachweis bleibt ein 24-Stunden-Lauf mit soak_monitor.py.",
            ],
        }


def _echter_soak(verzeichnis: Path) -> dict[str, Any]:
    health = _jsonl(verzeichnis / "health.jsonl")
    deep = _jsonl(verzeichnis / "betrieb.jsonl")
    hd = _health_daten(health)
    dd = [z["daten"] for z in deep
          if z.get("ok") and isinstance(z.get("daten"), dict)]

    zeiten = sorted(float(z.get("ts_epoch", 0)) for z in health
                    if isinstance(z.get("ts_epoch"), (int, float)))
    luecken = [b - a for a, b in zip(zeiten, zeiten[1:])]
    max_luecke = max(luecken) if luecken else None
    dauer_stunden = ((zeiten[-1] - zeiten[0]) / 3600) if len(zeiten) >= 2 else 0.0
    fehler_health = sum(1 for z in health if not z.get("ok"))
    status = Counter(str(_betrieb(d).get("status") or "unbekannt") for d in hd)
    commits = sorted({str(d.get("commit")) for d in hd if d.get("commit")})
    paper_ticks = {str(d.get("paper_tick")) for d in hd if d.get("paper_tick")}
    paper_zeiten = [_zeit(d.get("paper_tick")) for d in hd if d.get("paper_tick")]
    paper_zeiten = [zeit for zeit in paper_zeiten if zeit is not None]
    letzte_health_zeit = (datetime.fromtimestamp(zeiten[-1], timezone.utc)
                          if zeiten else None)
    paper_alter = (round((letzte_health_zeit - max(paper_zeiten)).total_seconds(), 1)
                   if paper_zeiten and letzte_health_zeit else None)

    db_werte = [_zahl(_betrieb(d).get("db_mb")) for d in hd]
    rss_werte = [_zahl(_betrieb(d).get("rss_mb")) for d in hd]
    frei_werte = [_zahl((d.get("ressourcen") or {}).get("freier_speicher_mb")) for d in dd]
    max_db = _max(db_werte)
    max_rss = _max(rss_werte)
    min_frei = _min(frei_werte)

    deep_jobs = [job for d in dd for job in (d.get("jobs") or [])
                 if isinstance(job, dict)]
    max_fehler = max((int(j.get("fehlschluesse") or 0) for j in deep_jobs), default=0)
    max_backoff = max((int(j.get("backoff_sekunden") or 0) for j in deep_jobs), default=0)
    company_werte = [d["company"] for d in dd if isinstance(d.get("company"), dict)]
    audit_ok = bool(company_werte) and all(
        c.get("audit_ok") is True for c in company_werte
    )
    queue_dead = max((int(c.get("dead_letter") or 0) for c in company_werte), default=0)
    queue_blocked = max((int(c.get("blocked") or 0) for c in company_werte), default=0)
    queue_alter = _max(_zahl(c.get("queue_alter_max_s")) for c in company_werte)
    queue_fehler = [str(c.get("fehler")) for c in company_werte if c.get("fehler")]
    queue_ok = (
        bool(company_werte)
        and not queue_fehler
        and queue_dead == 0
        and queue_blocked == 0
        and (queue_alter is None or queue_alter <= MAX_QUEUE_ALTER_SEKUNDEN)
    )
    backup_werte = [d["backup"] for d in dd if isinstance(d.get("backup"), dict)]
    backup_alter = _max(_zahl(b.get("alter_s")) for b in backup_werte)
    backup_integrity = sorted({
        str(b.get("integrity")) for b in backup_werte if b.get("integrity") is not None
    })
    backup_restore_ok = bool(backup_werte) and all(
        b.get("ok") is True and b.get("restore_ok") is True
        and b.get("integrity") == "ok" for b in backup_werte
    )
    backup_ok = (
        backup_restore_ok
        and backup_alter is not None
        and backup_alter <= MAX_BACKUP_ALTER_SEKUNDEN
    )
    laeufe = [lauf for d in dd for lauf in (d.get("letzte_laeufe") or [])
              if isinstance(lauf, dict)]
    uebersprungen = sum(1 for lauf in laeufe if lauf.get("status") == "uebersprungen")
    fehler_laeufe = sum(1 for lauf in laeufe if lauf.get("status") == "fehler")

    kriterien = [
        _kriterium("Dauer", ">= 23,5 h Wanduhr", f"{dauer_stunden:.2f} h",
                   dauer_stunden >= 23.5),
        _kriterium("Health-Samples", f">= {MIN_HEALTH_SAMPLES}", len(health),
                   len(health) >= MIN_HEALTH_SAMPLES),
        _kriterium("Health-Fehler", f"<= {MAX_HEALTH_FEHLER}", fehler_health,
                   fehler_health <= MAX_HEALTH_FEHLER),
        _kriterium("Max. Health-Lücke", f"<= {MAX_HEALTH_LUECKE_SEKUNDEN:g} s",
                   max_luecke, max_luecke is not None and max_luecke <= MAX_HEALTH_LUECKE_SEKUNDEN),
        _kriterium("Taktstatus", "durchgehend laeuft",
                   dict(sorted(status.items())),
                   bool(hd) and status == Counter({"laeuft": len(hd)})),
        _kriterium("Commit stabil", "genau 1 Commit", commits, len(commits) == 1),
        _kriterium("Paper-Ticks", f">= {MIN_PAPER_TICKS} verschiedene Zeitpunkte",
                   len(paper_ticks), len(paper_ticks) >= MIN_PAPER_TICKS),
        _kriterium("Letzter Paper-Tick", "<= 300 s vor Ende", paper_alter,
                   paper_alter is not None and paper_alter <= 300),
        _kriterium("Tiefen-Samples", "alle erfolgreich",
                   {"gesamt": len(deep), "ok": len(dd)},
                   bool(deep) and len(dd) == len(deep)),
        _kriterium("Job-Fehler", "0", max_fehler, bool(deep_jobs) and max_fehler == 0),
        _kriterium("Job-Backoff", "0 s", max_backoff, bool(deep_jobs) and max_backoff == 0),
        _kriterium("Ressourcen-Skips", "0", uebersprungen,
                   bool(laeufe) and uebersprungen == 0),
        _kriterium("Fehlerhafte Jobläufe", "0", fehler_laeufe,
                   bool(laeufe) and fehler_laeufe == 0),
        _kriterium("Audit-Kette", "alle Tiefen-Samples ok",
                   {"samples": len(company_werte),
                    "ok": sum(c.get("audit_ok") is True for c in company_werte)},
                   audit_ok),
        _kriterium("Company-Queue",
                   f"0 dead-letter, 0 blocked, max. Alter <= {MAX_QUEUE_ALTER_SEKUNDEN:g} s",
                   {"samples": len(company_werte), "dead_letter": queue_dead,
                    "blocked": queue_blocked, "alter_s": queue_alter,
                    "fehler": queue_fehler},
                   queue_ok),
        _kriterium("Backup-Restore",
                   f"Backup vorhanden, integrity ok, Restore-Probe ok, Alter <= {MAX_BACKUP_ALTER_SEKUNDEN / 3600:g} h",
                   {"samples": len(backup_werte), "integrity": backup_integrity,
                    "restore_ok": backup_restore_ok, "alter_s": backup_alter},
                   backup_ok),
        _kriterium("DB-Wachstum", f"< {MAX_DB_MB:g} MB", max_db,
                   max_db is not None and max_db < MAX_DB_MB),
        _kriterium("Prozess-RSS", f"< {MAX_RSS_MB:g} MB", max_rss,
                   max_rss is not None and max_rss < MAX_RSS_MB),
        _kriterium("Freier Speicher", f"> {MIN_FREIER_SPEICHER_MB:g} MB", min_frei,
                   min_frei is not None and min_frei > MIN_FREIER_SPEICHER_MB),
    ]

    return {
        "modus": "wanduhr",
        "start": (datetime.fromtimestamp(zeiten[0], timezone.utc).isoformat()
                  if zeiten else None),
        "ende": (datetime.fromtimestamp(zeiten[-1], timezone.utc).isoformat()
                 if zeiten else None),
        "commit": commits[0] if len(commits) == 1 else ", ".join(commits) or "unbekannt",
        "kriterien": kriterien,
        "metriken": {
            "health_samples": len(health),
            "health_fehler": fehler_health,
            "max_health_luecke_s": max_luecke,
            "tiefen_samples": len(deep),
            "tiefen_samples_ok": len(dd),
            "paper_ticks": len(paper_ticks),
            "paper_tick_alter_s": paper_alter,
            "job_fehler": max_fehler,
            "job_backoff_s": max_backoff,
            "uebersprungen": uebersprungen,
            "fehlerhafte_joblaeufe": fehler_laeufe,
            "audit_ok": audit_ok,
            "queue_dead_letter": queue_dead,
            "queue_blocked": queue_blocked,
            "queue_alter_max_s": queue_alter,
            "queue_fehler": queue_fehler,
            "backup_integrity": backup_integrity,
            "backup_restore_ok": backup_restore_ok,
            "backup_alter_s": backup_alter,
            "max_db_mb": max_db,
            "max_rss_mb": max_rss,
            "min_freier_speicher_mb": min_frei,
        },
        "hinweise": [
            "Wanduhr-Auswertung der vorhandenen health.jsonl/betrieb.jsonl.",
            "Audit-Kette, Company-Queue und Backup-Restore stammen aus den Tiefen-Samples.",
            "Fehlende Tiefen-Samples machen Audit-, Queue- und Backup-Kriterien nicht bestanden.",
            "Der Backup-Restore prüft eine Kopie des neuesten Backups, nicht das Live-Restore-Verfahren.",
        ],
    }


def _markdown(daten: dict[str, Any]) -> str:
    bestanden = all(k["bestanden"] for k in daten["kriterien"])
    titel = ("# Orakel 24-Stunden-Soak – Simulation"
             if daten["modus"] == "simulation"
             else "# Orakel 24-Stunden-Soak – Wanduhr")
    zeilen = [
        titel,
        "",
        f"**Ergebnis:** {'BESTANDEN' if bestanden else 'NICHT BESTANDEN'}",
        f"**Modus:** {'Beschleunigte Simulation mit virtueller Uhr' if daten['modus'] == 'simulation' else 'Echter Wanduhr-Lauf'}",
        f"**Commit:** `{daten['commit']}`",
        f"**Start:** `{daten['start']}`",
        f"**Ende:** `{daten['ende']}`",
        "",
        "## Abnahmekriterien",
        "",
        "| Kriterium | Schwelle | Messwert | Status |",
        "|---|---|---|---|",
    ]
    for k in daten["kriterien"]:
        wert = k["wert"]
        if isinstance(wert, (dict, list)):
            wert = json.dumps(wert, ensure_ascii=False)
        zeilen.append(
            f"| {k['name']} | {k['schwelle']} | `{wert}` | "
            f"{'OK' if k['bestanden'] else 'FEHLER'} |"
        )
    met = daten["metriken"]
    queue = (f"{met.get('queue_offen')} offen, max. "
             f"{met.get('queue_alter_max_s')} s"
             if "queue_offen" in met else "nicht gemessen")
    zeilen += [
        "",
        "## Betriebskennzahlen",
        "",
        f"- Health-Samples: `{met.get('health_samples', 'nicht gemessen')}`",
        f"- Maximale Health-Lücke: `{met.get('max_health_luecke_s', 'nicht gemessen')} s`",
        f"- Job-Fehler: `{met.get('job_fehler', 'nicht gemessen')}`",
        f"- Job-Backoff: `{met.get('job_backoff_s', 'nicht gemessen')} s`",
        f"- Queue: `{queue}`",
        f"- Audit-Kette: `{met.get('audit_ok', 'nicht gemessen')}`",
        f"- Queue dead-letter/blocked: `{met.get('queue_dead_letter', 'nicht gemessen')}` / `{met.get('queue_blocked', 'nicht gemessen')}`",
        f"- Queue-Alter: `{met.get('queue_alter_max_s', 'nicht gemessen')} s`",
        f"- Backup-Integrität: `{met.get('backup_integrity', 'nicht gemessen')}`",
        f"- Backup-Restore: `{met.get('backup_restore_ok', 'nicht gemessen')}`",
        f"- Backup-Alter: `{met.get('backup_alter_s', 'nicht gemessen')} s`",
        f"- DB-Wachstum: `{met.get('db_wachstum_mb', 'nicht gemessen')} MB`",
        f"- DB-Maximum: `{met.get('max_db_mb', 'nicht gemessen')} MB`",
        "",
        "## Messwerte",
        "",
        "```json",
        json.dumps(met, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Einordnung",
        "",
    ]
    zeilen += [f"- {hinweis}" for hinweis in daten["hinweise"]]
    zeilen += [
        "",
        "## Reproduktion",
        "",
        "```bash",
        "# Beschleunigte Simulation (keine Wanduhr):",
        "python scripts/soak_abnahme.py --simulieren",
        "",
        "# Echter 24-Stunden-Lauf (Wanduhr, Railway/SSH nötig):",
        "python scripts/soak_monitor.py --duration-hours 24 --output-dir artifacts/soak-24h",
        "python scripts/soak_abnahme.py --verzeichnis artifacts/soak-24h",
        "```",
        "",
        "_Der Simulationslauf ersetzt keinen echten Dauerbetrieb. Für die "
        "Abnahme zählt nur ein abgeschlossener Wanduhr-Lauf mit gültigen "
        "Health- und Tiefen-Samples._",
        "",
    ]
    return "\n".join(zeilen)


def _schreiben(daten: dict[str, Any], ziel: Path) -> None:
    ziel.mkdir(parents=True, exist_ok=True)
    (ziel / "messwerte.json").write_text(
        json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (ziel / "report.md").write_text(_markdown(daten), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--simulieren", action="store_true",
                       help="24 h virtuelle Zeit deterministisch simulieren")
    group.add_argument("--verzeichnis", type=Path,
                       help="Verzeichnis mit health.jsonl und betrieb.jsonl auswerten")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    if args.simulieren:
        daten = _simulation(args.config)
        ziel = args.output_dir or (
            Path("artifacts") / f"soak-simulation-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
    else:
        if not args.verzeichnis.exists():
            parser.error(f"Verzeichnis fehlt: {args.verzeichnis}")
        daten = _echter_soak(args.verzeichnis)
        ziel = args.output_dir or args.verzeichnis

    _schreiben(daten, ziel)
    bestanden = all(k["bestanden"] for k in daten["kriterien"])
    print(f"SOAK_BERICHT {ziel / 'report.md'}")
    print(f"ERGEBNIS {'BESTANDEN' if bestanden else 'NICHT BESTANDEN'}")
    return 0 if bestanden else 1


if __name__ == "__main__":
    sys.exit(main())
