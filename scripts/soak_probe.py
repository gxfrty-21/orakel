#!/usr/bin/env python3
"""Tiefen-Probe für den Soak-Monitor.

Wird über Railway-SSH an den Zielhost gepipet und als ``python -`` ausgeführt.
Sie liest den Betriebszustand, prüft die Audit-Kette, misst die Company-Queue
und testet das neueste SQLite-Backup durch eine Kopie in einem temporären
Verzeichnis. Es werden keine Produktionsdaten verändert.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orakel.betrieb import betrieb_status
from orakel.company.store import CompanyStore
from orakel.config import load_config
from orakel.kern.db import Facts

OFFENE_STATES = ("proposed", "queued", "accepted", "running", "review", "blocked")
QUEUE_MESS_TABELLEN = ("artikel", "trades", "agent_events", "agent_tasks")


def _zeit(wert: Any) -> datetime | None:
    if not wert:
        return None
    text = str(wert).replace("Z", "+00:00")
    try:
        zeit = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (zeit.replace(tzinfo=timezone.utc) if zeit.tzinfo is None
            else zeit.astimezone(timezone.utc))


def _company(db: Facts) -> dict[str, Any]:
    store = CompanyStore(db)
    with db.conn() as c:
        counts = {str(r["state"]): int(r["n"]) for r in c.execute(
            "SELECT state, COUNT(*) n FROM agent_tasks GROUP BY state"
        )}
        rows = list(c.execute(
            "SELECT id, state, created_at FROM agent_tasks "
            "WHERE state IN (?,?,?,?,?,?)", OFFENE_STATES
        ))
    jetzt = datetime.now(timezone.utc)
    alter = [
        (jetzt - zeit).total_seconds()
        for row in rows
        if (zeit := _zeit(row["created_at"])) is not None
    ]
    return {
        "audit_ok": bool(store.audit_chain_ok()),
        "tasks": counts,
        "queue_offen": len(rows),
        "queue_alter_max_s": round(max(alter), 1) if alter else None,
        "dead_letter": counts.get("dead_letter", 0),
        "blocked": counts.get("blocked", 0),
        "fehler": None,
    }


def _backup(ordner: Path) -> dict[str, Any]:
    if not ordner.exists():
        return {"ok": False, "fehler": "Backup-Ordner fehlt", "pfad": str(ordner)}
    dateien = sorted(
        ordner.glob("orakel-*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not dateien:
        return {"ok": False, "fehler": "kein SQLite-Backup gefunden", "pfad": str(ordner)}
    quelle = dateien[0]
    jetzt = datetime.now(timezone.utc)
    alter = (jetzt - datetime.fromtimestamp(quelle.stat().st_mtime, timezone.utc)).total_seconds()
    try:
        with tempfile.TemporaryDirectory(prefix="orakel-soak-restore-") as tmp:
            ziel = Path(tmp) / "restore.db"
            shutil.copy2(quelle, ziel)
            con = sqlite3.connect(ziel)
            try:
                integritaet = str(con.execute("PRAGMA integrity_check").fetchone()[0])
                vorhanden = {
                    str(r[0]) for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                tabellen = {
                    name: int(con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])  # noqa: S608 - Tabellenname ist eine feste interne Liste
                    for name in QUEUE_MESS_TABELLEN if name in vorhanden
                }
            finally:
                con.close()
    except Exception as exc:
        return {
            "ok": False,
            "pfad": str(quelle),
            "bytes": quelle.stat().st_size,
            "alter_s": round(alter, 1),
            "integrity": None,
            "restore_ok": False,
            "tabellen": {},
            "fehler": f"Restore-Probe fehlgeschlagen: {type(exc).__name__}: {exc}",
        }
    return {
        "ok": integritaet == "ok",
        "pfad": str(quelle),
        "bytes": quelle.stat().st_size,
        "alter_s": round(alter, 1),
        "integrity": integritaet,
        "restore_ok": integritaet == "ok",
        "tabellen": tabellen,
        "fehler": None if integritaet == "ok" else "Integritätsprüfung fehlgeschlagen",
    }


def main() -> int:
    try:
        cfg = load_config(os.environ.get("ORAKEL_CONFIG", "/app/config.toml"))
        db = Facts(str(cfg.db_pfad))
        daten = betrieb_status(cfg, db)
        daten["company"] = _company(db)
        daten["backup"] = _backup(
            Path(os.environ.get("ORAKEL_BACKUP_ORDNER", "/data/backups"))
        )
        print(json.dumps(daten, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({
            "fehler": f"{type(exc).__name__}: {exc}",
            "company": {"audit_ok": None, "fehler": f"{type(exc).__name__}"},
            "backup": {"ok": False, "restore_ok": False, "fehler": f"{type(exc).__name__}"},
        }, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
