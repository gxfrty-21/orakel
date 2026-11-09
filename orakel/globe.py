"""Intelligence-Graph für die Weltkugel.

Der Graph ist keine zweite Datenhaltung: Jeder Knoten und jede Kante wird beim
Abruf aus SQLite bzw. dem Obsidian-Vault abgeleitet. Wo eine Zuordnung eine
Heuristik des Systems ist (Themen-Routing), wird sie im Feld ``derived``
markiert. Es werden keine Aktivitäten erfunden.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import Config
from .db import Facts, jetzt
from .intel import ABTEILUNG, THEMEN

SOURCE_CHANNELS = [
    {"id": "news", "name": "News Intelligence", "short": "News",
     "hint": "Presse, Wirtschaft und Nachrichten", "color": "#6fd9ff"},
    {"id": "market", "name": "Market Intelligence", "short": "Markt",
     "hint": "Unternehmen, Kurse und Marktberichte", "color": "#5fe0c8"},
    {"id": "science", "name": "Scientific Research", "short": "Wissenschaft",
     "hint": "Studien, Papiere und empirische Forschung", "color": "#9fb7ff"},
    {"id": "books", "name": "Books & Publications", "short": "Bücher",
     "hint": "Bücher und Fachpublikationen", "color": "#c6a8ff"},
    {"id": "video", "name": "Video Intelligence", "short": "Video",
     "hint": "Video- und Transkriptquellen", "color": "#ff9e8a"},
    {"id": "macro", "name": "Economic Data", "short": "Makro",
     "hint": "Notenbanken, Konjunktur und Wirtschaftsdaten", "color": "#e8c46a"},
    {"id": "external", "name": "External Research", "short": "Extern",
     "hint": "Externe Research- und Datenquellen", "color": "#83e6b0"},
]

DEPARTMENTS = [
    {"id": "D", "name": "Trading Floor", "short": "Trading",
     "hint": "Markt, Signale und Ausführung", "color": "#5fe0c8"},
    {"id": "C", "name": "Laboratory", "short": "Labor",
     "hint": "Strategien und Validierung", "color": "#9fb7ff"},
    {"id": "E", "name": "Research Department", "short": "Research",
     "hint": "Hypothesen und Untersuchungen", "color": "#c6a8ff"},
    {"id": "F", "name": "Risk Management", "short": "Risk",
     "hint": "Grenzen, Sperren und Datenqualität", "color": "#ff9e8a"},
    {"id": "G", "name": "Knowledge Center", "short": "Knowledge",
     "hint": "Vault, Gedächtnis und Wissensnetz", "color": "#e8c46a"},
]

DEPARTMENT_BY_CODE = {d["id"]: d for d in DEPARTMENTS}
DEPARTMENT_BY_NAME = {d["name"]: d for d in DEPARTMENTS}
ALL_DEPARTMENTS = {
    "A": "Hauptzentrale", "B": "Spider Intelligence", "C": "Laboratory",
    "D": "Trading Floor", "E": "Research Department", "F": "Risk Management",
    "G": "Knowledge Center", "H": "Entwicklungsabteilung",
}
THEMA_NAME = {
    "strategie": "Strategie", "risiko": "Risiko", "wissenschaft": "Wissenschaft",
    "unternehmen": "Unternehmen", "makro": "Makro", "markt": "Markt",
    "allgemein": "Allgemein",
}
NODE_COLORS = {
    "article": "#6fd9ff", "research": "#e8c46a", "insight": "#c6a8ff",
    "market": "#5fe0c8", "forward": "#9fb7ff", "demo": "#8b97a5",
}
ZEITRAEUME: dict[str, dict[str, Any]] = {
    "24h": {"key": "24h", "label": "24 Stunden", "short": "24 h",
            "hours": 24, "detail": "24 h"},
    "7d": {"key": "7d", "label": "7 Tage", "short": "7 Tage",
           "hours": 24 * 7, "detail": "7 Tagen"},
    "30d": {"key": "30d", "label": "30 Tage", "short": "30 Tage",
            "hours": 24 * 30, "detail": "30 Tagen"},
}
STANDARD_ZEITRAUM = "24h"


def _parse_zeit(wert: Any) -> datetime | None:
    if not wert:
        return None
    try:
        zeit = datetime.fromisoformat(str(wert))
        if zeit.tzinfo is None:
            zeit = zeit.replace(tzinfo=timezone.utc)
        return zeit.astimezone(timezone.utc)
    except Exception:
        return None


def _alter_stunden(wert: Any, jetzt_utc: datetime) -> float | None:
    zeit = _parse_zeit(wert)
    if zeit is None:
        return None
    return max(0.0, (jetzt_utc - zeit).total_seconds() / 3600)


def _json_wert(wert: Any, standard: Any) -> Any:
    try:
        return json.loads(wert) if isinstance(wert, str) else (wert or standard)
    except Exception:
        return standard


def _sauber(text: Any, max_len: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:max_len]


def _thema(text: str) -> str:
    klein = text.lower()
    for thema, woerter in THEMEN.items():
        if any(wort in klein for wort in woerter):
            return thema
    return "allgemein"


def _kanal(typ: str, quelle: str) -> str:
    text = f"{typ} {quelle}".lower()
    if any(wort in text for wort in ("notenbank", "makro", "wirtschaft", "economic", "fed", "ezb")):
        return "macro"
    if any(wort in text for wort in ("unternehmensbericht", "unternehmen", "markt", "market", "sec ")):
        return "market"
    if any(wort in text for wort in ("wissenschaft", "studie", "research", "arxiv", "paper")):
        return "science"
    if "video" in text:
        return "video"
    if any(wort in text for wort in ("buch", "book", "publication")):
        return "books"
    if any(wort in text for wort in ("extern", "nber", "ssrn")):
        return "external"
    return "news"


def _relevanz(qualitaet: float, geholt: Any, symbole: list[str], jetzt_utc: datetime) -> float:
    """Nachvollziehbare Heuristik: Quellenqualität, Aktualität, Symbolbezug."""
    alter = _alter_stunden(geholt, jetzt_utc)
    aktuell = 0.0 if alter is None else max(0.0, 1.0 - alter / (24 * 14))
    return round(min(1.0, 0.55 * float(qualitaet or 0.0) + 0.30 * aktuell
                     + 0.15 * (1.0 if symbole else 0.0)), 2)


def _im_zeitraum(wert: Any, jetzt_utc: datetime, stunden: float) -> bool:
    alter = _alter_stunden(wert, jetzt_utc)
    return alter is not None and alter <= stunden


def _fenster(zeitraum: Any) -> dict[str, Any]:
    key = str(zeitraum or "").strip().lower()
    return ZEITRAEUME.get(key, ZEITRAEUME[STANDARD_ZEITRAUM])


def _quelle_aktiv(letzte: Any, jetzt_utc: datetime, stunden: float = 24) -> bool:
    return _im_zeitraum(letzte, jetzt_utc, stunden)


def _basis_node(art: str, kennung: str) -> dict[str, Any]:
    return {"id": kennung, "type": art, "color": NODE_COLORS.get(art, "#8b97a5")}


def _vault_dateien(cfg: Config) -> list[Path]:
    wurzel = Path(getattr(cfg, "vault_ordner", "vault")) / "70-Wissen"
    if not wurzel.exists():
        return []
    return sorted(wurzel.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)


def _vault_knoten(cfg: Config, orders: list[dict[str, Any]], jetzt_utc: datetime,
                  stunden: float = 24) -> list[dict[str, Any]]:
    dateien = _vault_dateien(cfg)[:200]
    if not dateien:
        return []
    knoten: list[dict[str, Any]] = []
    for datei in dateien:
        try:
            text = datei.read_text(encoding="utf-8")[:12000]
        except Exception:
            continue
        titel = datei.stem.replace("-", " ")
        erstellt = datetime.fromtimestamp(datei.stat().st_mtime, tz=timezone.utc).isoformat()
        tags: list[str] = []
        verlinkt: list[str] = []
        if text.startswith("---"):
            teile = text.split("---", 2)
            if len(teile) >= 3:
                for zeile in teile[1].splitlines():
                    if ":" not in zeile:
                        continue
                    schluessel, wert = zeile.split(":", 1)
                    wert = wert.strip()
                    if schluessel.strip() == "titel":
                        try:
                            titel = json.loads(wert)
                        except Exception:
                            titel = wert.strip('"')
                    elif schluessel.strip() == "erstellt":
                        erstellt = wert.strip()
                    elif schluessel.strip() == "tags":
                        tags = [t.strip() for t in wert.strip("[]").split(",") if t.strip()]
        if not _im_zeitraum(erstellt, jetzt_utc, stunden):
            continue
        for treffer in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", text):
            if treffer.strip() and treffer.strip() not in verlinkt:
                verlinkt.append(treffer.strip())
        order_bezug = next((o for o in orders if o["kennung"] in titel or o["kennung"] in text[:2000]), None)
        knoten.append({
            **_basis_node("insight", f"vault:{datei.stem}"),
            "title": _sauber(titel, 180),
            "category": "Wissensnetzwerk",
            "source": "Obsidian Vault",
            "time": erstellt,
            "relevance": None,
            "status": "verknüpft",
            "department": "Knowledge Center",
            "department_code": "G",
            "summary": f"Vault-Notiz · {', '.join(tags[:4]) if tags else 'ohne Tags'}",
            "detail": f"Pfad: vault/70-Wissen/{datei.name}",
            "tags": tags,
            "related": verlinkt[:8],
            "order_id": order_bezug["kennung"] if order_bezug else None,
            "demo": False,
        })
        if len(knoten) >= 14:
            break
    return knoten


def _demo_knoten() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sichtbar gekennzeichnete Beispieldaten; niemals als Live-Aktivität gelabelt."""
    knoten = [
        {**_basis_node("demo", "demo:research"),
         "title": "Beispiel: Scientific Research", "category": "Demo",
         "source": "Demo-Modus", "time": jetzt(), "relevance": 0.72,
         "status": "Demo", "department": "Research Department", "department_code": "E",
         "summary": "Beispielknoten, weil noch keine echte Informationsquelle verbunden ist.",
         "detail": "Dieser Knoten ist keine echte Meldung.", "demo": True},
        {**_basis_node("demo", "demo:news"),
         "title": "Beispiel: News Intelligence", "category": "Demo",
         "source": "Demo-Modus", "time": jetzt(), "relevance": 0.58,
         "status": "Demo", "department": "Trading Floor", "department_code": "D",
         "summary": "Beispielknoten für den Eingang einer Meldung.",
         "detail": "Dieser Knoten ist keine echte Meldung.", "demo": True},
        {**_basis_node("demo", "demo:vault"),
         "title": "Beispiel: Wissensnetzwerk", "category": "Demo",
         "source": "Demo-Modus", "time": jetzt(), "relevance": None,
         "status": "Demo", "department": "Knowledge Center", "department_code": "G",
         "summary": "Beispielknoten für eine Erkenntnis aus dem Vault.",
         "detail": "Dieser Knoten ist keine echte Vault-Notiz.", "demo": True},
    ]
    kanten = [
        {"from": "source:science", "to": "demo:research", "kind": "ingest",
         "active": False, "derived": True, "label": "Demo"},
        {"from": "source:news", "to": "demo:news", "kind": "ingest",
         "active": False, "derived": True, "label": "Demo"},
        {"from": "demo:vault", "to": "dept:G", "kind": "knowledge",
         "active": False, "derived": True, "label": "Demo"},
    ]
    return knoten, kanten


def baue_globe(cfg: Config, db: Facts, zeitraum: str = STANDARD_ZEITRAUM) -> dict[str, Any]:
    """Baut den Intelligence-Graph für das gewählte Zeitfenster aus SQLite/Vault."""
    fenster = _fenster(zeitraum)
    stunden = float(fenster["hours"])
    jetzt_utc = datetime.now(timezone.utc)
    quellen = {s["id"]: {**s, "count": 0, "last_seen": None} for s in SOURCE_CHANNELS}
    knoten: list[dict[str, Any]] = []
    kanten: list[dict[str, Any]] = []
    flows: list[dict[str, Any]] = []

    # Zeitgestempelte Daten werden serverseitig gefiltert, bevor der Graph entsteht.
    # Die höheren Limits decken auch das 30-Tage-Fenster ab; angezeigt wird nur das Fenster.
    artikel_alle = [dict(r) for r in db.artikel(1000)]
    artikel = [a for a in artikel_alle if _im_zeitraum(a.get("geholt"), jetzt_utc, stunden)]
    auftraege_alle = [dict(r) for r in db.intel_auftraege(500)]
    auftraege = [o for o in auftraege_alle if _im_zeitraum(o.get("zeit"), jetzt_utc, stunden)]
    weiterleitungen_alle = [dict(r) for r in db.intel_weiterleitungen(500)]
    weiterleitungen = [w for w in weiterleitungen_alle if _im_zeitraum(w.get("zeit"), jetzt_utc, stunden)]
    agenten_alle = [dict(r) for r in db.agenten_laeufe(1000)]
    agenten = [a for a in agenten_alle if _im_zeitraum(a.get("zeit"), jetzt_utc, stunden)]
    ereignisse_alle = [dict(r) for r in db.ereignisse(1000)]
    ereignisse = [e for e in ereignisse_alle if _im_zeitraum(e.get("zeit"), jetzt_utc, stunden)]

    # ---------- Artikel / Informationen ----------
    with db.conn() as c:
        analysiert = {int(r["artikel_id"]) for r in c.execute("SELECT artikel_id FROM intel_inhalte")}
    artikel_knoten: dict[int, dict[str, Any]] = {}
    for artikel_id, row in enumerate(artikel):
        art_id = int(row["id"])
        symbole = _json_wert(row["symbole"], [])
        if not isinstance(symbole, list):
            symbole = []
        thema = _thema(f"{row['titel']} {row['zusammenfassung'] or ''} {row['typ'] or ''}")
        dept_code, dept_name = ABTEILUNG.get(thema, ("G", "Knowledge Center"))
        kanal = _kanal(str(row["typ"] or ""), str(row["quelle"] or ""))
        qualitaet = float(row["qualitaet"] or 0.0)
        node = {
            **_basis_node("article", f"article:{art_id}"),
            "title": _sauber(row["titel"], 220),
            "category": THEMA_NAME.get(thema, thema.title()),
            "source": _sauber(row["quelle"], 120),
            "channel": kanal,
            "time": row["geholt"],
            "published": row["veroeffentlicht"],
            "relevance": _relevanz(qualitaet, row["geholt"], symbole, jetzt_utc),
            "status": "analysiert" if art_id in analysiert else "gespeichert",
            "department": dept_name,
            "department_code": dept_code,
            "summary": _sauber(row["zusammenfassung"], 500) or "Keine Zusammenfassung gespeichert.",
            "detail": f"Quelle: {row['quelle']} · Typ: {row['typ']}",
            "url": row["url"],
            "symbols": symbole,
            "quality": round(qualitaet, 2),
            "derived_department": True,
            "demo": False,
        }
        knoten.append(node)
        artikel_knoten[art_id] = node
        q = quellen[kanal]
        q["count"] += 1
        if not q["last_seen"] or str(row["geholt"] or "") > str(q["last_seen"]):
            q["last_seen"] = row["geholt"]
        kanten.append({
            "from": f"source:{kanal}", "to": node["id"], "kind": "ingest",
            "active": _quelle_aktiv(row["geholt"], jetzt_utc, stunden), "derived": False,
            "label": "Eingang",
        })
        kanten.append({
            "from": node["id"], "to": f"dept:{dept_code}", "kind": "routing",
            "active": art_id in analysiert and _quelle_aktiv(row["geholt"], jetzt_utc, stunden),
            "derived": True, "label": "Themen-Routing",
        })
        if _quelle_aktiv(row["geholt"], jetzt_utc, stunden) and len(flows) < 18:
            flows.append({
                "id": f"flow:info:{art_id}", "from": f"source:{kanal}", "to": "hub",
                "kind": "information", "active": True, "time": row["geholt"],
                "label": "Neue Information", "node_id": node["id"],
                "detail": node["title"],
            })

    # Artikel, die über Symbole tatsächlich verbunden sind.
    relationen = 0
    ids = list(artikel_knoten)
    for pos, a_id in enumerate(ids):
        for b_id in ids[pos + 1:]:
            if relationen >= 10:
                break
            gemeinsame = set(artikel_knoten[a_id].get("symbols") or []) & set(artikel_knoten[b_id].get("symbols") or [])
            if gemeinsame:
                kanten.append({
                    "from": f"article:{a_id}", "to": f"article:{b_id}", "kind": "relation",
                    "active": False, "derived": False, "label": ", ".join(sorted(gemeinsame)),
                })
                relationen += 1

    # ---------- Forschungsaufträge ----------
    offene_auftraege = 0
    for row in auftraege:
        dept_code = str(row["abteilung"] or "")
        dept_name = ALL_DEPARTMENTS.get(dept_code, dept_code or "unbekannt")
        ist_offen = row["status"] == "offen"
        offene_auftraege += int(ist_offen)
        node = {
            **_basis_node("research", f"order:{row['kennung']}"),
            "title": _sauber(row["titel"], 220),
            "category": "Forschungsauftrag",
            "source": "Research Queue",
            "time": row["zeit"],
            "relevance": 1.0 if ist_offen else 0.82,
            "status": row["status"],
            "department": dept_name,
            "department_code": dept_code,
            "summary": _sauber(row["problem"] or row["hypothese"] or row["frage"], 500),
            "detail": _sauber(row["ergebnis"] or row["untersuchung"], 600) or "Noch kein Ergebnis gespeichert.",
            "symbol": row["bezug_symbol"],
            "demo": False,
        }
        knoten.append(node)
        if dept_code in DEPARTMENT_BY_CODE:
            kanten.append({
                "from": node["id"], "to": f"dept:{dept_code}", "kind": "assignment",
                "active": ist_offen, "derived": False, "label": "Auftrag",
            })
        quellen_urls = _json_wert(row["quellen"], [])
        if isinstance(quellen_urls, list):
            for url in quellen_urls:
                treffer = next((a for a in artikel_knoten.values() if a.get("url") == url), None)
                if treffer:
                    kanten.append({
                        "from": node["id"], "to": treffer["id"], "kind": "evidence",
                        "active": False, "derived": False, "label": "Quelle",
                    })
        if ist_offen and len(flows) < 24:
            flows.append({
                "id": f"flow:order:{row['kennung']}", "from": node["id"],
                "to": f"dept:{dept_code}" if dept_code in DEPARTMENT_BY_CODE else "hub",
                "kind": "research", "active": True, "time": row["zeit"],
                "label": "Aktiver Auftrag", "node_id": node["id"],
                "detail": node["title"],
            })

    # ---------- Weiterleitungen ----------
    for row in weiterleitungen:
        ziel_name = str(row["an"] or "")
        ziel = DEPARTMENT_BY_NAME.get(ziel_name)
        node = {
            **_basis_node("forward", f"forward:{row['kennung']}"),
            "title": _sauber(row["betreff"], 220),
            "category": "Weiterleitung",
            "source": _sauber(row["von"], 120),
            "time": row["zeit"],
            "relevance": 0.9 if row["status"] != "erledigt" else 0.6,
            "status": row["status"],
            "department": ziel_name or "Knowledge Center",
            "department_code": ziel["id"] if ziel else "G",
            "summary": f"Weiterleitung von {row['von']} an {ziel_name or 'unbekannt'}.",
            "detail": f"Status: {row['status']}",
            "demo": False,
        }
        knoten.append(node)
        kanten.append({"from": "hub", "to": node["id"], "kind": "forward",
                       "active": row["status"] != "erledigt", "derived": False,
                       "label": "Weiterleitung"})
        if ziel:
            kanten.append({"from": node["id"], "to": f"dept:{ziel['id']}", "kind": "forward",
                           "active": row["status"] != "erledigt", "derived": False,
                           "label": "Ziel"})
            if row["status"] != "erledigt" and len(flows) < 28:
                flows.append({
                    "id": f"flow:forward:{row['kennung']}", "from": "hub",
                    "to": f"dept:{ziel['id']}", "kind": "forward", "active": True,
                    "time": row["zeit"], "label": "Weiterleitung", "node_id": node["id"],
                    "detail": node["title"],
                })

    # ---------- Markt-Knoten ----------
    basis = db.zustand("bericht_basis") or {}
    markt = basis.get("markt") or {}
    marktsymbole = markt.get("symbole") or []
    markt_stand = markt.get("stand") or jetzt()
    for symbol in marktsymbole[:4]:
        kurs = symbol.get("kurs")
        change = symbol.get("aenderung_24h_pct")
        node = {
            **_basis_node("market", f"market:{symbol.get('symbol')}"),
            "title": str(symbol.get("symbol") or "Markt"),
            "category": "Markt",
            "source": "SQLite-Kerzen",
            "time": markt_stand,
            "relevance": None,
            "status": str(symbol.get("regime") or "unbekannt"),
            "department": "Trading Floor",
            "department_code": "D",
            "summary": f"Kurs {kurs} · 24 h {change} % · ATR {symbol.get('atr_pct')} %",
            "detail": f"{symbol.get('stadt')} · {symbol.get('kerzen')} Kerzen · Datenquelle: {basis.get('datenquelle', 'unbekannt')}",
            "market": {key: symbol.get(key) for key in ("kurs", "aenderung_24h_pct", "atr_pct", "regime", "stadt", "kerzen")},
            "demo": False,
        }
        knoten.append(node)
        kanten.append({"from": "source:market", "to": node["id"], "kind": "market",
                       "active": _quelle_aktiv(markt_stand, jetzt_utc, stunden), "derived": False,
                       "label": "Marktdaten"})
        kanten.append({"from": node["id"], "to": "dept:D", "kind": "market",
                       "active": _quelle_aktiv(markt_stand, jetzt_utc, stunden), "derived": True,
                       "label": "Trading Floor"})
    if marktsymbole:
        q = quellen["market"]
        q["count"] += len(marktsymbole)
        if not q["last_seen"] or str(markt_stand) > str(q["last_seen"]):
            q["last_seen"] = markt_stand

    # ---------- Wissensnetzwerk ----------
    vault_knoten = _vault_knoten(cfg, auftraege, jetzt_utc, stunden)
    knoten.extend(vault_knoten)
    for node in vault_knoten:
        kanten.append({"from": node["id"], "to": "dept:G", "kind": "knowledge",
                       "active": False, "derived": False, "label": "Vault"})
        if node.get("order_id"):
            kanten.append({"from": node["id"], "to": f"order:{node['order_id']}", "kind": "documentation",
                           "active": False, "derived": False, "label": "Dokumentation"})

    # ---------- Agenten und Abteilungen ----------
    agent_pro_abteilung: dict[str, list[dict[str, Any]]] = {}
    for row in agenten:
        agent_pro_abteilung.setdefault(str(row["abteilung"]), []).append(row)
    for abteilung, rows in agent_pro_abteilung.items():
        if abteilung in DEPARTMENT_BY_CODE and rows:
            letzter = rows[0]
            if _im_zeitraum(letzter["zeit"], jetzt_utc, stunden) and len(flows) < 30:
                flows.append({
                    "id": f"flow:agent:{abteilung}", "from": "hub",
                    "to": f"dept:{abteilung}", "kind": "agent", "active": True,
                    "time": letzter["zeit"], "label": "Agentenlauf",
                    "node_id": None, "detail": _sauber(letzter["ergebnis"], 200),
                })

    # ---------- Quellen- und Abteilungsstatus ----------
    quellen_liste: list[dict[str, Any]] = []
    for index, basis_quelle in enumerate(SOURCE_CHANNELS):
        q = quellen[basis_quelle["id"]]
        aktiv = _quelle_aktiv(q["last_seen"], jetzt_utc, stunden) if q["count"] else False
        quellen_liste.append({
            **basis_quelle, "slot": index, "count": q["count"],
            "last_seen": q["last_seen"], "active": aktiv,
            "status": "aktiv" if aktiv else ("verbunden" if q["count"] else "keine Daten"),
        })
        kanten.append({"from": f"source:{q['id']}", "to": "hub", "kind": "channel",
                       "active": aktiv, "derived": False, "label": "Datenkanal"})
        flows.append({"id": f"channel:source:{q['id']}", "from": f"source:{q['id']}",
                      "to": "hub", "kind": "channel", "active": aktiv,
                      "time": q["last_seen"], "label": "Datenkanal",
                      "node_id": None, "detail": "Eingehender Kanal"})

    dept_liste: list[dict[str, Any]] = []
    for index, basis_dept in enumerate(DEPARTMENTS):
        rows = agent_pro_abteilung.get(basis_dept["id"], [])
        letzte = rows[0]["zeit"] if rows else None
        aktiv = bool(rows and _im_zeitraum(letzte, jetzt_utc, stunden))
        dept_liste.append({
            **basis_dept, "slot": index, "agent_runs": len(rows),
            "open_orders": sum(1 for o in auftraege if o.get("abteilung") == basis_dept["id"] and o.get("status") == "offen"),
            "last_seen": letzte, "active": aktiv,
            "status": "aktiv" if aktiv else ("bereit" if rows else "keine Aktivität"),
        })
        kanten.append({"from": "hub", "to": f"dept:{basis_dept['id']}", "kind": "channel",
                       "active": aktiv, "derived": False, "label": "Datenkanal"})
        flows.append({"id": f"channel:dept:{basis_dept['id']}", "from": "hub",
                      "to": f"dept:{basis_dept['id']}", "kind": "channel", "active": aktiv,
                      "time": letzte, "label": "Datenkanal", "node_id": None,
                      "detail": "Ausgehender Kanal"})

    # Kanal-Endpunkte sind echte Graph-Knoten; die Kugel selbst ist der Hub.
    for q in quellen_liste:
        knoten.append({
            **_basis_node("source", f"source:{q['id']}"), "title": q["name"],
            "category": "Quelle", "source": q["name"], "time": q["last_seen"],
            "relevance": None, "status": q["status"], "department": "—",
            "department_code": "", "summary": q["hint"], "count": q["count"],
            "active": q["active"], "demo": False,
        })
    for d in dept_liste:
        knoten.append({
            **_basis_node("department", f"dept:{d['id']}"), "title": d["name"],
            "category": "Abteilung", "source": "Orakel", "time": d["last_seen"],
            "relevance": None, "status": d["status"], "department": d["name"],
            "department_code": d["id"], "summary": d["hint"],
            "agent_runs": d["agent_runs"], "open_orders": d["open_orders"],
            "active": d["active"], "demo": False,
        })

    # ---------- Aktivität ----------
    events_24h = sum(1 for e in ereignisse_alle if (_alter_stunden(e.get("zeit"), jetzt_utc) or 999) <= 24)
    articles_24h = sum(1 for a in artikel_alle if (_alter_stunden(a.get("geholt"), jetzt_utc) or 999) <= 24)
    orders_24h = sum(1 for o in auftraege_alle if (_alter_stunden(o.get("zeit"), jetzt_utc) or 999) <= 24)
    agents_24h = sum(1 for a in agenten_alle if (_alter_stunden(a.get("zeit"), jetzt_utc) or 999) <= 24)
    articles_zeitraum = len(artikel)
    orders_zeitraum = len(auftraege)
    agents_zeitraum = len(agenten)
    events_zeitraum = len(ereignisse)
    letzte_zeit = next((e.get("zeit") for e in ereignisse if e.get("zeit")), None)
    if not letzte_zeit and artikel:
        letzte_zeit = artikel[0]["geholt"]
    if articles_zeitraum or orders_zeitraum or agents_zeitraum or events_zeitraum or weiterleitungen or vault_knoten:
        zustand, label = "aktiv", "AKTIV"
    elif knoten or quellen_liste:
        zustand, label = "ruhig", "RUHIG"
    else:
        zustand, label = "leer", "KEINE AKTIVITÄT"
    aktivitaet = {
        "state": zustand, "label": label,
        "detail": (f"{articles_zeitraum} neue Informationen · {agents_zeitraum} Agentenläufe · "
                   f"{events_zeitraum} Ereignisse in {fenster['detail']}"),
        "window": fenster,
        "articles": articles_zeitraum, "orders": orders_zeitraum,
        "agents": agents_zeitraum, "events": events_zeitraum,
        "articles_24h": articles_24h, "orders_24h": orders_24h,
        "agents_24h": agents_24h, "events_24h": events_24h,
        "last_event": letzte_zeit,
    }

    # ---------- Demo nur, wenn es wirklich keinerlei echte Daten gibt ----------
    demo = not (artikel_alle or auftraege_alle or weiterleitungen_alle or agenten_alle
                or ereignisse_alle or marktsymbole or _vault_dateien(cfg))
    if demo:
        demo_nodes, demo_edges = _demo_knoten()
        knoten.extend(demo_nodes)
        kanten.extend(demo_edges)
        for q in quellen_liste:
            q["status"] = "Demo"
        for d in dept_liste:
            d["status"] = "Demo"

    # Hub ist die Kugel selbst und wird nicht als Datenpunkt gezeichnet.
    knoten.insert(0, {
        "id": "hub", "type": "hub", "title": "Orakel Intelligence Core",
        "color": "#5fe0c8", "category": "Core", "source": "Orakel",
        "time": jetzt(), "relevance": None, "status": "online",
        "department": "—", "department_code": "", "summary": "Zentrale Intelligence-Kugel.",
        "detail": "Alle Kanäle laufen hier zusammen.", "demo": demo,
    })

    # Kanal-Flows ans Ende, damit konkrete Informationen zuerst bleiben.
    flows = [f for f in flows if f.get("kind") != "channel"] + [f for f in flows if f.get("kind") == "channel"]
    flows.sort(key=lambda f: str(f.get("time") or ""), reverse=True)

    nodes_by_id = {n["id"]: n for n in knoten}
    kanten = [k for k in kanten if k.get("from") in nodes_by_id and k.get("to") in nodes_by_id]
    counts = {
        "nodes": len(knoten) - 1,
        "edges": len(kanten),
        "articles": len(artikel_knoten),
        "orders": len(auftraege),
        "open_orders": offene_auftraege,
        "insights": len(vault_knoten),
        "markets": len(marktsymbole),
        "sources": sum(1 for q in quellen_liste if q["count"]),
        "agents": len(agenten),
        "forwards": len(weiterleitungen),
        "events": len(ereignisse),
        "events_24h": events_24h,
    }
    return {
        "schema": 1,
        "window": fenster,
        "mode": "demo" if demo else "live",
        "demo": demo,
        "demo_hinweis": ("Noch keine echte Datenquelle verbunden. Die grauen Knoten sind "
                         "ausdrücklich Beispieldaten.") if demo else None,
        "generated_at": jetzt(),
        "sources": quellen_liste,
        "departments": dept_liste,
        "nodes": knoten,
        "edges": kanten,
        "flows": flows[:32],
        "activity": aktivitaet,
        "counts": counts,
        "legend": [
            {"id": "article", "label": "Information", "color": NODE_COLORS["article"]},
            {"id": "research", "label": "Forschungsauftrag", "color": NODE_COLORS["research"]},
            {"id": "insight", "label": "Vault-Erkenntnis", "color": NODE_COLORS["insight"]},
            {"id": "market", "label": "Markt", "color": NODE_COLORS["market"]},
        ],
    }
