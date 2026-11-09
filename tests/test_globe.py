from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from orakel.db import Facts
from orakel.globe import _kanal, _thema, baue_globe


def _cfg(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(vault_ordner=str(tmp_path / "vault"))


def test_leere_datenbank_ist_klar_als_demo_markiert(tmp_path):
    db = Facts(tmp_path / "leer.db")
    graph = baue_globe(_cfg(tmp_path), db)

    assert graph["demo"] is True
    assert graph["mode"] == "demo"
    assert len(graph["sources"]) == 7
    assert any(node["demo"] for node in graph["nodes"] if node["id"].startswith("demo:"))
    assert graph["activity"]["state"] in {"ruhig", "leer"}


def test_echte_daten_erzeugen_knoten_kanten_und_flows(tmp_path):
    vault = tmp_path / "vault" / "70-Wissen"
    vault.mkdir(parents=True)
    (vault / "beispiel.md").write_text(
        f"---\ntitel: \"Beispiel-Erkenntnis\"\nerstellt: {datetime.now(timezone.utc).isoformat()}\n"
        "kategorie: wissen\ntags: [test]\n---\n\n# Beispiel-Erkenntnis\n\nInhalt.\n",
        encoding="utf-8",
    )
    db = Facts(tmp_path / "daten.db")
    db.artikel_speichern(
        "Test Wire", "notenbank", "Zinsen bleiben unverändert", "https://example.test/a",
        None, "Die Notenbank hält den Leitzins stabil.", 0.8, ["EURUSD"], "hash-a",
    )
    db.intel_auftrag_speichern({
        "kennung": "RS-TEST-0001", "abteilung": "C", "titel": "Testauftrag",
        "problem": "Testproblem", "status": "offen",
    })

    graph = baue_globe(_cfg(tmp_path), db)

    assert graph["demo"] is False
    assert graph["counts"]["articles"] == 1
    assert graph["counts"]["orders"] == 1
    assert graph["counts"]["insights"] == 1
    ids = {node["id"] for node in graph["nodes"]}
    assert "source:macro" in ids
    assert "dept:C" in ids
    assert "hub" in ids
    assert any(node["id"].startswith("article:") for node in graph["nodes"])
    assert any(edge["from"] == "source:macro" and edge["to"].startswith("article:")
               for edge in graph["edges"])
    assert all(edge["from"] in ids and edge["to"] in ids for edge in graph["edges"])
    assert graph["activity"]["state"] == "aktiv"


def _artikel_mit_zeit(db: Facts, titel: str, url: str, geholt: str) -> None:
    db.artikel_speichern(
        "Test Wire", "nachrichten", titel, url, None,
        "Eine Meldung für den Zeitfilter.", 0.8, [], f"hash-{url}",
    )
    with db.conn() as c:
        c.execute("UPDATE artikel SET geholt=? WHERE url=?", (geholt, url))


def test_zeitraum_filtert_graph_und_aktivitaet(tmp_path):
    db = Facts(tmp_path / "zeit.db")
    alt = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    neu = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _artikel_mit_zeit(db, "Alte Meldung", "https://example.test/alt", alt)
    _artikel_mit_zeit(db, "Neue Meldung", "https://example.test/neu", neu)
    db.intel_auftrag_speichern({
        "kennung": "RS-ZEIT-0001", "abteilung": "C", "titel": "Alter Auftrag",
        "problem": "Zeitfilter prüfen", "status": "offen", "zeit": alt,
    })
    db.agenten_lauf("E:test", "E", "Zeitfilter prüfen", "Alter Lauf", True)
    with db.conn() as c:
        c.execute("UPDATE agenten_laeufe SET zeit=?", (alt,))

    g24 = baue_globe(_cfg(tmp_path), db, "24h")
    g7 = baue_globe(_cfg(tmp_path), db, "7d")
    g30 = baue_globe(_cfg(tmp_path), db, "30d")

    assert g24["window"]["key"] == "24h"
    assert [g["counts"]["articles"] for g in (g24, g7, g30)] == [1, 1, 2]
    assert [g["counts"]["orders"] for g in (g24, g7, g30)] == [0, 0, 1]
    assert [g["counts"]["agents"] for g in (g24, g7, g30)] == [0, 0, 1]
    assert g30["activity"]["articles"] == 2
    assert "7 Tagen" in g7["activity"]["detail"]
    assert g30["activity"]["window"]["label"] == "30 Tage"
    news = next(s for s in g30["sources"] if s["id"] == "news")
    assert news["count"] == 2
    assert g24["demo"] is False and g7["demo"] is False and g30["demo"] is False


def test_alter_artikel_im_leeren_zeitfenster_ist_kein_demo(tmp_path):
    db = Facts(tmp_path / "alt.db")
    alt = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    _artikel_mit_zeit(db, "Nur alte Meldung", "https://example.test/nur-alt", alt)

    graph = baue_globe(_cfg(tmp_path), db, "24h")

    assert graph["demo"] is False
    assert graph["counts"]["articles"] == 0
    assert graph["activity"]["articles"] == 0
    assert graph["activity"]["state"] == "ruhig"
    assert any(node["id"].startswith("source:") for node in graph["nodes"])


def test_kanal_und_thema_sind_nachvollziehbar():
    assert _kanal("notenbank", "Federal Reserve Press") == "macro"
    assert _kanal("unternehmensbericht", "SEC Press") == "market"
    assert _kanal("nachrichten", "BBC Business") == "news"
    assert _thema("Die Notenbank senkt den Zins") == "makro"
    assert _thema("Neues Backtest-Modell") == "strategie"
    assert _thema("Ein unbekannter Text") == "allgemein"
