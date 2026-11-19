"""Tests für die Lauf-Warteschlange (Bereich 4.4)."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from orakel import lauf_queue, web
from orakel.kern.db import Facts


def test_post_lauf_antwortet_unter_200_ms(cfg, monkeypatch):
    """Der Endpunkt legt nur an; er wartet nicht auf die Engine."""
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    app = web.create_app("unbenutzt.toml", arbeiter=False)

    with TestClient(app) as client:
        beginn = time.perf_counter()
        antwort = client.post("/api/lauf?modus=backtest")
        dauer = time.perf_counter() - beginn

    assert antwort.status_code == 202
    assert dauer < 0.2, f"POST /api/lauf brauchte {dauer * 1000:.0f} ms"
    daten = antwort.json()
    assert daten["ok"] is True
    assert daten["status"] == "offen"
    assert daten["id"] > 0


def test_get_lauf_liefert_status_und_404(cfg, monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    app = web.create_app("unbenutzt.toml", arbeiter=False)

    with TestClient(app) as client:
        lauf_id = client.post("/api/lauf?modus=backtest").json()["id"]
        antwort = client.get(f"/api/lauf/{lauf_id}")
        fehlt = client.get("/api/lauf/999999")

    assert antwort.status_code == 200
    assert antwort.json()["status"] == "offen"
    assert antwort.headers["cache-control"] == "no-store"
    assert fehlt.status_code == 404


def test_arbeiter_verarbeitet_auftrag_und_schreibt_ergebnis(cfg):
    db = Facts(cfg.db_pfad)
    aufrufe: list[dict] = []

    def engine(**kwargs):
        aufrufe.append(kwargs)
        return {"dauer_sekunden": 0.01, "validierungen": [{}], "plan": [{}, {}],
                "fehler": []}

    lauf_id = lauf_queue.anlegen(db, modus="backtest", spider=True)
    ergebnis = lauf_queue.verarbeite_einen("unbenutzt.toml", db=db, engine=engine)

    assert ergebnis["id"] == lauf_id
    assert ergebnis["status"] == lauf_queue.FERTIG
    assert aufrufe == [{"cfg_pfad": "unbenutzt.toml", "modus": "backtest",
                        "mit_spider": True}]
    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FERTIG
    assert stand["ergebnis"] == {"dauer": 0.01, "validierungen": 1, "plan": 2,
                                 "fehler": 0}
    assert stand["gestartet"] and stand["beendet"]
    assert lauf_queue.offene_id(db) is None


def test_fehlerhafter_auftrag_wird_als_fehler_verbucht(cfg):
    db = Facts(cfg.db_pfad)

    def kaputt(**_kwargs):
        raise RuntimeError("Backtest abgebrochen")

    lauf_id = lauf_queue.anlegen(db)

    ergebnis = lauf_queue.verarbeite_einen("unbenutzt.toml", db=db, engine=kaputt)

    assert ergebnis == {"id": lauf_id, "status": lauf_queue.FEHLER}
    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FEHLER
    assert "Backtest abgebrochen" in stand["fehler"]
    assert lauf_queue.offene_id(db) is None
    assert any("Auftrag" in zeile["text"] for zeile in db.ereignisse())


def test_ohne_auftrag_passiert_nichts(cfg):
    db = Facts(cfg.db_pfad)

    assert lauf_queue.verarbeite_einen("unbenutzt.toml", db=db,
                                       engine=lambda **_k: {}) is None
