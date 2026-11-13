from __future__ import annotations

import pandas as pd

from orakel import judge
from orakel.backtest import BacktestErgebnis
from orakel.config import RisikoGrenzen
from orakel.judge import Urteil, _aufteilung, beurteile_walk_forward, pruefe_holdout
from orakel.strategies import strategien


def _ergebnis(df: pd.DataFrame, start: int, ende: int, *, gut: bool = True) -> BacktestErgebnis:
    trades = [
        {"einstieg": str(df["ts"].iloc[start])[:19], "ausstieg": str(df["ts"].iloc[ende - 1])[:19],
         "stueck": 1.0, "netto": 100.0 if gut else -100.0, "rendite_pct": 1.0, "grund": "Test"}
        for _ in range(20)
    ]
    return BacktestErgebnis(
        trades=trades,
        kapital=[100_000.0] * max(1, ende - start),
        kapitalkurve=[[str(df["ts"].iloc[i]), 100_000.0] for i in range(start, ende)],
        kennzahlen={
            "netto": 2_000.0 if gut else -2_000.0,
            "profit_factor": 1.5 if gut else 0.5,
            "max_drawdown_pct": 3.0 if gut else 20.0,
            "trades": 20,
            "gebuehren": 10.0,
            "sharpe": 1.0 if gut else -1.0,
            "rendite_pct": 2.0,
            "trefferquote_pct": 60.0,
            "zeit_im_markt_pct": 50.0,
        },
        zeit_im_markt_pct=50.0,
    )


def _fakes(monkeypatch, aufrufe: list[tuple[int, int, int]], *, gut: bool = True) -> None:
    def fake_backtest(df, signale, cfg, grenzen, start=0, ende=None, **kwargs):
        ende = len(df) if ende is None else int(ende)
        aufrufe.append((len(df), int(start), ende))
        return _ergebnis(df, int(start), ende, gut=gut)

    monkeypatch.setattr(judge, "backtest", fake_backtest)


def test_aufteilung_reserviert_letzte_kerzen_und_rolliert(cfg):
    auf = _aufteilung(10_000, {**cfg["validierung"], "holdout_anteil": 0.15,
                               "walk_forward_fenster": 3, "train_anteil": 0.7,
                               "min_fold_bars": 50})
    assert auf is not None
    dev, holdout, train, grenzen = auf
    assert (dev, holdout, train) == (8_500, 1_500, 5_950)
    assert grenzen[0] == train
    assert grenzen[-1] == dev
    assert all(a < b for a, b in zip(grenzen, grenzen[1:]))
    assert dev + holdout == 10_000


def test_walk_forward_oeffnet_holdout_nicht(cfg, kerzen, monkeypatch):
    cfg["validierung"]["zufallslaeufe"] = 0
    cfg["validierung"]["monte_carlo_laeufe"] = 0
    aufrufe: list[tuple[int, int, int]] = []
    _fakes(monkeypatch, aufrufe)
    strategie = strategien(cfg)["ema_cross"]
    grenzen = RisikoGrenzen.aus_config(cfg)

    u = beurteile_walk_forward(kerzen, "TEST", strategie, cfg, grenzen)

    dev, _, _, _ = _aufteilung(len(kerzen), cfg["validierung"])
    assert u.holdout == {}
    assert u.holdout_bestanden is None
    assert u.holdout_ab == str(kerzen["ts"].iloc[dev])[:19]
    assert u.walk_forward_folds
    assert all(ende <= dev for _, _, ende in aufrufe)
    assert u.walk_forward_folds[-1]["test_bis"] <= u.holdout_ab


def test_holdout_gate_nutzt_nur_letzten_block(cfg, kerzen, monkeypatch):
    aufrufe: list[tuple[int, int, int]] = []
    _fakes(monkeypatch, aufrufe, gut=True)
    strategie = strategien(cfg)["ema_cross"]
    grenzen = RisikoGrenzen.aus_config(cfg)
    dev, _, _, _ = _aufteilung(len(kerzen), cfg["validierung"])

    bestanden = Urteil("TEST", strategie.name, {"fast": 10, "slow": 50},
                       strategie.beschreibung, "bestanden")
    pruefe_holdout(bestanden, kerzen, strategie, cfg, grenzen)

    assert aufrufe == [(len(kerzen), dev, len(kerzen))]
    assert bestanden.holdout_bestanden is True
    assert bestanden.holdout["von"] == str(kerzen["ts"].iloc[dev])[:19]
    assert bestanden.holdout["bis"] == str(kerzen["ts"].iloc[-1])[:19]

    aufrufe.clear()
    _fakes(monkeypatch, aufrufe, gut=False)
    abgelehnt = Urteil("TEST", strategie.name, {"fast": 10, "slow": 50},
                       strategie.beschreibung, "bestanden")
    pruefe_holdout(abgelehnt, kerzen, strategie, cfg, grenzen)

    assert aufrufe == [(len(kerzen), dev, len(kerzen))]
    assert abgelehnt.holdout_bestanden is False
    assert abgelehnt.urteil == "abgelehnt"
    assert abgelehnt.holdout["gruende"]
    assert any("Holdout" in g for g in abgelehnt.gruende)
