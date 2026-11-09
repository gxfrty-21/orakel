from __future__ import annotations

import json

import pandas as pd

from orakel.db import Facts
from orakel.paper import tick


def steigende_kerzen(n: int = 400, start: float = 100.0) -> pd.DataFrame:
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    close = [start * (1.0008 ** i) for i in range(n)]
    return pd.DataFrame({
        "ts": ts,
        "open": [c * 0.9998 for c in close],
        "high": [c * 1.0015 for c in close],
        "low": [c * 0.9985 for c in close],
        "close": close,
        "volume": [100.0] * n,
    })


def aufbau(cfg) -> tuple[Facts, int]:
    db = Facts(cfg.db_pfad)
    df = steigende_kerzen()
    db.kerzen_speichern("TEST", "M15", df.to_dict("records"))
    vid = db.validierung_speichern(
        "TEST", "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
        "bestanden", "Test", {"out_of_sample": {"profit_factor": 1.4}, "gruende": []},
        lauf="L1",
    )
    db.zustand_setzen("letzter_lauf_id", "L1")
    db.auswahl_setzen("TEST", "ema_cross|fast=10,slow=50", vid)
    return db, vid


def test_takt_eroeffnet_paper_position(cfg):
    db, _ = aufbau(cfg)
    ergebnis = tick(cfg, db)

    positionen = db.positionen()
    assert len(positionen) == 1
    assert positionen[0]["symbol"] == "TEST"
    assert positionen[0]["menge"] > 0
    assert ergebnis["konto"]["positionen"] == 1
    # Stop liegt unter dem Einstieg (Long) und Risiko ist begrenzt
    assert positionen[0]["stop"] < positionen[0]["einstieg"]
    assert db.letztes_konto() is not None


def test_stop_schliesst_position(cfg):
    db, _ = aufbau(cfg)
    tick(cfg, db)
    position = db.positionen()[0]
    stop = float(position["stop"])

    # Letzte Kerze bricht unter den Stop
    df = steigende_kerzen()
    letzte = df.iloc[-1].to_dict()
    letzte["low"] = stop * 0.95
    letzte["open"] = stop * 0.99
    db.kerzen_speichern("TEST", "M15", [letzte])

    tick(cfg, db)
    assert db.positionen() == []
    entscheide = [dict(e) for e in db.entscheide(5)]
    assert any(e["aktion"] == "verkaufen" and "Stop" in e["status"] for e in entscheide)
    assert any("Stop ausgelöst" in r["text"] for r in db.ereignisse(10))


def test_kein_zweiter_kauf_bei_offener_position(cfg):
    db, _ = aufbau(cfg)
    tick(cfg, db)
    menge_vorher = db.positionen()[0]["menge"]
    tick(cfg, db)
    assert len(db.positionen()) == 1
    assert db.positionen()[0]["menge"] == menge_vorher


def test_korrelation_verhindert_zweiten_kauf(cfg):
    """Zwei identisch laufende Symbole: der zweite Kauf wird vom Risiko gesperrt."""
    db = Facts(cfg.db_pfad)
    df = steigende_kerzen()
    for symbol in ("AAA", "BBB"):
        db.kerzen_speichern(symbol, "M15", df.to_dict("records"))

    vid = db.validierung_speichern(
        "AAA", "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
        "bestanden", "Test", {"out_of_sample": {"profit_factor": 1.4}, "gruende": []},
        lauf="L1",
    )
    db.auswahl_setzen("AAA", "ema_cross|fast=10,slow=50", vid)
    tick(cfg, db)
    assert [p["symbol"] for p in db.positionen()] == ["AAA"]

    vid_b = db.validierung_speichern(
        "BBB", "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
        "bestanden", "Test", {"out_of_sample": {"profit_factor": 1.4}, "gruende": []},
        lauf="L1",
    )
    db.auswahl_setzen("BBB", "ema_cross|fast=10,slow=50", vid_b)
    tick(cfg, db)

    # Nur die erste Position bleibt offen, der zweite Kauf wurde abgelehnt
    assert [p["symbol"] for p in db.positionen()] == ["AAA"]
    ablehnungen = [json.loads(e["gruende"]) for e in db.entscheide(20)
                   if e["symbol"] == "BBB" and not e["genehmigt"]]
    assert ablehnungen, "Der Kauf von BBB muss als abgelehnt protokolliert sein"
    assert any(any("Korrelation" in g for g in gruende) for gruende in ablehnungen)
