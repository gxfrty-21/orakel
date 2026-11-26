from __future__ import annotations

import json
import socket
import sys

import pandas as pd
import pytest

from orakel.kern import paper as paper_mod
from orakel.kern.db import Facts
from orakel.kern.paper import tick


def steigende_kerzen(n: int = 400, start: float = 100.0) -> pd.DataFrame:
    # Aktuelle Zeitstempel: Der Takt bewertet nur Kurse innerhalb der
    # Aktualitätsgrenze aus [daten] als belastbar.
    ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("15min"),
                       periods=n, freq="15min", tz="UTC")
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


def test_takt_ohne_broker_und_netzwerk(cfg, monkeypatch):
    """Der Paper-Takt bleibt eine reine SQLite-Simulation."""
    db, _ = aufbau(cfg)

    class KeinBroker:
        def __getattr__(self, name):
            raise AssertionError(f"Paper-Takt hat Broker-Attribut {name} benutzt")

    def kein_netzwerk(*args, **kwargs):
        raise AssertionError("Paper-Takt hat eine Netzwerkverbindung geöffnet")

    monkeypatch.setitem(sys.modules, "orakel.brokers", KeinBroker())
    monkeypatch.setattr(socket, "socket", kein_netzwerk)
    monkeypatch.setattr(socket, "create_connection", kein_netzwerk)

    ergebnis = tick(cfg, db)

    assert ergebnis["konto"]["positionen"] == 1
    assert len(db.positionen()) == 1


@pytest.mark.parametrize("paper_konfiguration", [
    None,  # [paper] fehlt vollständig
    {"order_freigabe": False},  # broker fehlt
    {"broker": "unbekannt", "order_freigabe": False},
    {"broker": "", "order_freigabe": False},
    {"broker": "mt5", "order_freigabe": False},
])
def test_takt_laeuft_ohne_broker_konfiguration_und_mit_unbekannten_werten(
    cfg, paper_konfiguration,
):
    """Der Paper-Takt hängt nicht von Broker-Konfiguration oder Freigabe ab."""
    if paper_konfiguration is None:
        cfg._d.pop("paper", None)
    else:
        cfg._d["paper"] = dict(paper_konfiguration)

    db, _ = aufbau(cfg)
    ergebnis = tick(cfg, db)

    assert ergebnis["konto"]["positionen"] == 1
    assert len(db.positionen()) == 1
    assert db.positionen()[0]["symbol"] == "TEST"


@pytest.mark.parametrize("abschnitte", [
    ("risiko",),
    ("kosten",),
    ("risiko", "kosten"),
])
def test_takt_meldet_fehlende_risiko_oder_kostenabschnitte(cfg, abschnitte):
    db, _ = aufbau(cfg)
    for abschnitt in abschnitte:
        cfg._d.pop(abschnitt)

    with pytest.raises(ValueError, match=r"Paper-Takt:.*fehlen") as exc:
        tick(cfg, db)

    for abschnitt in abschnitte:
        assert f"[{abschnitt}]" in str(exc.value)
    assert db.positionen() == []
    assert db.zustand("paper_konto") is None


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


def test_paper_wertet_h1_strategie_nicht_auf_m15_aus(cfg, monkeypatch):
    """Auch bei H1-Richter bleibt der Paper-Takt beim M15-Raster."""
    cfg._d.setdefault("basis", {})["richter_zeitrahmen"] = "H1"
    cfg._d["research"].update({
        "h1_retest_lookback": [5],
        "h1_retest_fenster": [5],
        "h1_retest_stop_puffer_pct": [0.01],
    })
    db, _ = aufbau(cfg)
    vid = db.validierung_speichern(
        "TEST", "h1_retest",
        "h1_retest|lookback=5,retest_fenster=5,stop_puffer_pct=0.01",
        {"lookback": 5, "retest_fenster": 5, "stop_puffer_pct": 0.01},
        "bestanden", "Test",
        {"out_of_sample": {"profit_factor": 1.4}, "gruende": []},
        lauf="L1",
    )
    db.auswahl_setzen(
        "TEST", "h1_retest|lookback=5,retest_fenster=5,stop_puffer_pct=0.01", vid,
    )
    assert "h1_retest" in paper_mod.strategien(cfg)

    gesehen: list[str | None] = []
    original = paper_mod.strategien

    def merken(instanz, **kwargs):
        gesehen.append(kwargs.get("zeitrahmen"))
        return original(instanz, **kwargs)

    monkeypatch.setattr(paper_mod, "strategien", merken)
    ergebnis = tick(cfg, db)

    assert gesehen and all(zeitrahmen == "M15" for zeitrahmen in gesehen)
    assert db.positionen() == []
    assert ergebnis["konto"]["positionen"] == 0


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
