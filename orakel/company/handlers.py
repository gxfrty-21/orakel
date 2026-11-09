"""Datengebundene Agenten-Handler.

Legacy-Rollen verwenden die bestehenden Handler aus `orakel.agents`.
Neue I/J/S-Rollen lesen ausschließlich vorhandene Kurs-, Artikel-, Queue-,
Audit- oder Vault-Daten. Fehlen Daten, wird das als solches gemeldet.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .. import agents
from ..knowledge import Vault
from .roster import Profile


@dataclass(frozen=True, slots=True)
class HandlerResult:
    ok: bool
    text: str
    evidence: tuple[str, ...] = ()
    blocked: bool = False


def _db(ctx: dict[str, Any]) -> Any:
    return ctx["db"]


def _store(ctx: dict[str, Any]) -> Any:
    return ctx["store"]


def _letzte_kerzen(db: Any, symbol: str, mindestens: int = 20) -> tuple[str, list[dict[str, Any]]]:
    for zeitrahmen in ("M15", "H1", "D1"):
        rows = db.kerzen(symbol, zeitrahmen)
        if len(rows) >= mindestens:
            return zeitrahmen, [dict(r) for r in rows[-240:]]
    return "", []


def _alle_marktzeilen(db: Any) -> list[dict[str, Any]]:
    raus: list[dict[str, Any]] = []
    for symbol in db.symbole():
        tf, rows = _letzte_kerzen(db, symbol)
        if not rows:
            continue
        letzte = rows[-1]
        vorher = rows[-2]["close"] if len(rows) > 1 else letzte["close"]
        change = ((float(letzte["close"]) - float(vorher)) / float(vorher) * 100
                  if float(vorher) else 0.0)
        raus.append({
            "symbol": symbol,
            "zeitrahmen": tf,
            "ts": letzte["ts"],
            "close": float(letzte["close"]),
            "change_pct": round(change, 3),
            "rows": rows,
        })
    return raus


def _treffer(zeilen: Sequence[dict[str, Any]], begriffe: Sequence[str]) -> list[dict[str, Any]]:
    return [z for z in zeilen if any(b in z["symbol"].upper() for b in begriffe)]


def _markt_evidence(zeilen: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(f"market:{z['symbol']}:{z['ts']}" for z in zeilen[:8])


def _marktrolle(ctx: dict[str, Any], label: str, begriffe: Sequence[str]) -> HandlerResult:
    zeilen = _treffer(_alle_marktzeilen(_db(ctx)), begriffe)
    if not zeilen:
        return HandlerResult(False, f"keine {label} im vorhandenen Kursbestand", (), True)
    teile = [f"{z['symbol']} {z['close']:.4f} ({z['change_pct']:+.2f} %)" for z in zeilen[:8]]
    return HandlerResult(
        True,
        f"{label}: {len(zeilen)} Symbol(e): " + ", ".join(teile),
        _markt_evidence(zeilen),
    )


def _pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 20:
        return None
    a, b = list(a[-n:]), list(b[-n:])
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    return cov / (va ** 0.5 * vb ** 0.5)


def _renditen(rows: Sequence[dict[str, Any]]) -> list[float]:
    closes = [float(r["close"]) for r in rows]
    return [(b - a) / a for a, b in zip(closes, closes[1:]) if a]


def _observatory_director(ctx: dict[str, Any]) -> HandlerResult:
    store, db = _store(ctx), _db(ctx)
    s = store.stats()
    konf = db.letzte_konferenz()
    artikel = db.artikel_statistik()["gesamt"]
    zeilen = _alle_marktzeilen(db)
    text = (f"Profile {s['profile']}, Tasks {sum(s['tasks'].values())}, "
            f"Artikel {artikel}, Marktsymbole {len(zeilen)}, "
            f"letzte Konferenz {'vorhanden' if konf else 'keine'}.")
    evidence = ["company:profiles", "db:artikel", "company:tasks"]
    if konf:
        evidence.append(f"conference:{konf['zeit']}")
    return HandlerResult(True, text, tuple(evidence))


def _fx_rates(ctx: dict[str, Any]) -> HandlerResult:
    return _marktrolle(ctx, "FX-/Zinssymbole", ("EUR", "USD", "GBP", "JPY", "CHF", "US10", "US2"))


def _equity_index(ctx: dict[str, Any]) -> HandlerResult:
    return _marktrolle(ctx, "Aktien-/Indexsymbole", ("US500", "SPX", "NAS", "DAX", "AAPL", "MSFT", "NDX"))


def _commodities(ctx: dict[str, Any]) -> HandlerResult:
    return _marktrolle(ctx, "Rohstoff-/Energiesymbole", ("XAU", "XAG", "WTI", "BRENT", "OIL", "GAS"))


def _crypto(ctx: dict[str, Any]) -> HandlerResult:
    return _marktrolle(ctx, "Kryptosymbole", ("BTC", "ETH", "SOL", "XRP"))


def _geopolitics(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    artikel = db.artikel(300)
    if not artikel:
        return HandlerResult(False, "keine Artikel für eine Geopolitik-Einordnung", (), True)
    begriffe = re.compile(
        r"(?i)\b(geopolit|sanction|election|war|conflict|tariff|central bank|fed|ecb)\b"
    )
    treffer = []
    for a in artikel:
        text = f"{a['titel']} {a['zusammenfassung'] or ''}"
        if begriffe.search(text):
            treffer.append(a)
    ids = [int(a["id"]) for a in treffer[:8]]
    evidence = tuple(f"article:{i}" for i in ids)
    if not treffer:
        return HandlerResult(True, f"{len(artikel)} Artikel geprüft; keine Geopolitik-Treffer", (
            f"article_scan:{len(artikel)}",), False)
    quellen = ", ".join(sorted({str(a["quelle"]) for a in treffer[:8]}))
    return HandlerResult(True, f"{len(treffer)} Geopolitik-Treffer in {len(artikel)} Artikeln; Quellen: {quellen}", evidence)


def _correlation(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    zeilen = _alle_marktzeilen(db)
    reihen = {z["symbol"]: _renditen(z["rows"]) for z in zeilen}
    paare: list[tuple[float, str, str]] = []
    namen = [n for n, r in reihen.items() if len(r) >= 20]
    for i, a in enumerate(namen):
        for b in namen[i + 1:]:
            c = _pearson(reihen[a], reihen[b])
            if c is not None:
                paare.append((c, a, b))
    if not paare:
        return HandlerResult(False, "keine ausreichenden Kursreihen für Korrelationen", (), True)
    paare.sort(key=lambda x: -abs(x[0]))
    top = paare[:3]
    evidence = tuple(f"market:{a}:correlation" for _, a, _ in top)
    text = "; ".join(f"{a}/{b}: {c:+.2f}" for c, a, b in top)
    return HandlerResult(True, f"{len(paare)} Paare berechnet; stärkste: {text}", evidence)


def _volatility(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    zeilen = _alle_marktzeilen(db)
    if not zeilen:
        return HandlerResult(False, "keine Kerzen für eine Volatilitätsanalyse", (), True)
    teile = []
    for z in zeilen[:8]:
        rows = z["rows"]
        trs = []
        for prev, cur in zip(rows, rows[1:]):
            tr = max(
                float(cur["high"]) - float(cur["low"]),
                abs(float(cur["high"]) - float(prev["close"])),
                abs(float(cur["low"]) - float(prev["close"])),
            )
            trs.append(tr)
        atr = statistics.fmean(trs[-14:]) if trs else 0.0
        teile.append(f"{z['symbol']} ATR {atr:.4f}")
    return HandlerResult(
        True, "Volatilität aus echten Kerzen: " + ", ".join(teile),
        tuple(f"market:{z['symbol']}:{z['ts']}" for z in zeilen[:8]),
    )


def _signal_fusion(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    with db.conn() as c:
        rows = list(c.execute(
            "SELECT task_type, COUNT(*) n FROM agent_tasks"
            " WHERE dept='I' AND state='done' GROUP BY task_type ORDER BY task_type"))
    if not rows:
        return HandlerResult(False, "keine abgeschlossenen I-Ergebnisse für eine Fusion", (), True)
    text = ", ".join(f"{r['task_type']}/{r['state']}: {r['n']}" for r in rows)
    return HandlerResult(True, f"Fusion nur aus belegten I-Ergebnissen: {text}", ("company:observatory_tasks",))


def _observatory_archive(ctx: dict[str, Any]) -> HandlerResult:
    vault = Vault(ctx["cfg"].vault_ordner)
    z = vault.zaehle()
    return HandlerResult(
        True, f"Vault-Bestand: {sum(z.values())} Notizen; Observatory schreibt erst nach Review.",
        ("vault:index",),
    )


def _security_chief(ctx: dict[str, Any]) -> HandlerResult:
    s = _store(ctx).stats()
    blockiert = len(s["blockiert"])
    return HandlerResult(
        True,
        f"Security-Lage: {blockiert} sichtbare Blockaden, Audit-Kette "
        f"{'ok' if s['audit_ok'] else 'defekt'}, Paper-only "
        f"{'aktiv' if ctx['policy'].paper_only() else 'nicht aktiv'}.",
        ("company:security_stats", "audit:chain"),
    )


def _access_audit(ctx: dict[str, Any]) -> HandlerResult:
    user = bool(os.environ.get("ORAKEL_AUTH_USER", "").strip())
    pw = bool(os.environ.get("ORAKEL_AUTH_PASS", ""))
    ok = user == pw
    return HandlerResult(
        ok,
        f"Basic-Auth-Präsenz: Benutzer {'gesetzt' if user else 'nicht gesetzt'}, "
        f"Passwort {'gesetzt' if pw else 'nicht gesetzt'}; keine Werte ausgegeben.",
        ("env:auth_presence",),
        blocked=not ok,
    )


def _data_integrity(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    with db.conn() as c:
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        fk = list(c.execute("PRAGMA foreign_key_check"))
        profile = int(c.execute("SELECT COUNT(*) n FROM agent_profiles").fetchone()["n"])
        tasks = int(c.execute("SELECT COUNT(*) n FROM agent_tasks").fetchone()["n"])
    ok = integrity == "ok" and not fk
    return HandlerResult(
        ok,
        f"SQLite-Integrität: {integrity}; Fremdschlüsselprobleme: {len(fk)}; "
        f"Profile {profile}, Tasks {tasks}.",
        ("db:integrity",),
        blocked=not ok,
    )


def _content_guard(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    artikel = db.artikel(300)
    if not artikel:
        return HandlerResult(True, "keine Artikel zu prüfen", ("db:artikel",))
    muster = re.compile(
        r"(?i)(ignore (?:all )?(?:previous|prior) instructions|system prompt|"
        r"reveal (?:the )?secret|api[_-]?key|password)"
    )
    treffer = []
    for a in artikel:
        if muster.search(f"{a['titel']} {a['zusammenfassung'] or ''}"):
            treffer.append(int(a["id"]))
    if treffer:
        return HandlerResult(
            False, f"{len(treffer)} verdächtige Artikel isoliert; keine Ausführung.",
            tuple(f"article:{i}" for i in treffer[:10]), blocked=True,
        )
    return HandlerResult(True, f"{len(artikel)} Artikel geprüft; keine Injektionsmuster.",
                         (f"article_scan:{len(artikel)}",))


def _secret_audit(ctx: dict[str, Any]) -> HandlerResult:
    verdacht: list[str] = []
    namen = {".env", "id_rsa", "id_ed25519"}
    endungen = {".pem", ".key", ".p12", ".pfx"}
    for basis in (Path("."), Path("orakel"), Path("deploy")):
        if not basis.exists():
            continue
        for p in basis.iterdir():
            if not p.is_file():
                continue
            name = p.name.lower()
            if name in namen or p.suffix.lower() in endungen:
                if p.name.endswith((".example", ".sample", ".template")):
                    continue
                verdacht.append(str(p))
    if verdacht:
        return HandlerResult(
            False, "Secret-Verdacht in Dateinamen: " + ", ".join(sorted(verdacht)),
            tuple(f"file:{p}" for p in verdacht[:10]), blocked=True,
        )
    return HandlerResult(True, "keine Secret-Dateien in den geprüften Verzeichnissen", ("filesystem:secret_scan",))


def _incident_review(ctx: dict[str, Any]) -> HandlerResult:
    s = _store(ctx).stats()
    blocked = s["tasks"].get("blocked", 0)
    dead = s["tasks"].get("dead_letter", 0)
    return HandlerResult(
        True, f"Incident-Review: {blocked} blockiert, {dead} dead-letter; "
              f"keine automatische Löschung oder Freigabe.",
        ("company:tasks",),
    )


def _event_chain(ctx: dict[str, Any]) -> HandlerResult:
    ok = _store(ctx).audit_chain_ok()
    return HandlerResult(
        ok, f"Audit-Hash-Kette: {'ok' if ok else 'defekt'}", ("audit:chain",),
        blocked=not ok,
    )


def _tool_guard(ctx: dict[str, Any]) -> HandlerResult:
    policy = ctx["policy"]
    shell = policy.check_action("shell")
    netz = policy.check_action("network")
    ok = not shell.allowed and not netz.allowed
    return HandlerResult(
        ok,
        f"Tool-Allowlist: Shell {'erlaubt' if shell.allowed else 'blockiert'}, "
        f"Fremdnetz {'erlaubt' if netz.allowed else 'blockiert'}.",
        ("policy:tool_scope",), blocked=not ok,
    )


def _paper_guard(ctx: dict[str, Any]) -> HandlerResult:
    paper = ctx["cfg"].abschnitt("paper")
    broker = str(paper.get("broker", "csv"))
    freigabe = bool(paper.get("order_freigabe", False))
    ok = not freigabe
    return HandlerResult(
        ok,
        f"Paper-Guard: Broker {broker}, Order-Freigabe "
        f"{'aktiv — blockiert' if freigabe else 'aus'}; keine echte Order.",
        ("config:paper",), blocked=not ok,
    )


def _security_archive(ctx: dict[str, Any]) -> HandlerResult:
    with _db(ctx).conn() as c:
        n = int(c.execute(
            "SELECT COUNT(*) n FROM agent_tasks WHERE dept='J' AND state='done'"
        ).fetchone()["n"])
    return HandlerResult(True, f"{n} abgeschlossene Security-Prüfungen; keine Secrets gespeichert.",
                         ("company:security_tasks",))


def _secretary_chief(ctx: dict[str, Any]) -> HandlerResult:
    store, db = _store(ctx), _db(ctx)
    s = store.stats()
    konf = db.letzte_konferenz()
    return HandlerResult(
        True,
        f"CEO-Lage: {s['profile']} Agenten, Tasks {sum(s['tasks'].values())}, "
        f"blockiert {s['tasks'].get('blocked', 0)}, letzte Konferenz "
        f"{konf['zeit'] if konf else 'keine'}.",
        ("company:overview", "conference:latest"),
    )


def _secretary_report(ctx: dict[str, Any]) -> HandlerResult:
    db = _db(ctx)
    runs = db.agenten_laeufe(50)
    erfolgreich = sum(1 for r in runs if int(r["ok"]))
    validierungen = len(db.alle_validierungen())
    konf = db.letzte_konferenz()
    return HandlerResult(
        True,
        f"Bericht: {len(runs)} letzte Agentenläufe, {erfolgreich} ok, "
        f"{validierungen} Validierungen, Konferenz "
        f"{'vorhanden' if konf else 'keine'}.",
        ("db:agent_runs", "db:validierungen", "conference:latest"),
    )


def _secretary_ops(ctx: dict[str, Any]) -> HandlerResult:
    s = _store(ctx).stats()
    blockiert = s["blockiert"]
    grund = "; ".join(f"{b['assigned_to']}: {b['error'][:80]}" for b in blockiert[:3])
    return HandlerResult(
        True,
        f"Operations: {s['tasks'].get('done', 0)} erledigt, "
        f"{s['tasks'].get('blocked', 0)} blockiert, "
        f"{s['tasks'].get('dead_letter', 0)} dead-letter."
        + (f" Beispiele: {grund}" if grund else ""),
        ("company:queue_stats",),
    )


CUSTOM = {
    "observatory_director": _observatory_director,
    "fx_rates": _fx_rates,
    "equity_index": _equity_index,
    "commodities": _commodities,
    "crypto": _crypto,
    "geopolitics": _geopolitics,
    "correlation": _correlation,
    "volatility": _volatility,
    "signal_fusion": _signal_fusion,
    "observatory_archive": _observatory_archive,
    "security_chief": _security_chief,
    "access_audit": _access_audit,
    "data_integrity": _data_integrity,
    "content_guard": _content_guard,
    "secret_audit": _secret_audit,
    "incident_review": _incident_review,
    "event_chain": _event_chain,
    "tool_guard": _tool_guard,
    "paper_guard": _paper_guard,
    "security_archive": _security_archive,
    "secretary_chief": _secretary_chief,
    "secretary_report": _secretary_report,
    "secretary_ops": _secretary_ops,
}


def run_handler(profile: Profile, ctx: dict[str, Any]) -> HandlerResult:
    if profile.handler in CUSTOM:
        return CUSTOM[profile.handler](ctx)
    handler = agents.HANDLER.get(profile.handler)
    if handler is None:
        return HandlerResult(False, f"kein Handler für {profile.handler}", (), True)
    try:
        ok, text = handler(ctx)
    except Exception as exc:
        return HandlerResult(False, f"Handler-Fehler: {exc}", (), True)
    return HandlerResult(
        bool(ok), str(text), (f"handler:{profile.handler}",), blocked=not ok,
    )
