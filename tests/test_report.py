from __future__ import annotations

import json

from orakel.db import Facts
from orakel.report import baue_bericht, schreibe_bericht


def test_bericht_hat_schema_2(cfg, tmp_path):
    db = Facts(cfg.db_pfad)
    db.ereignis("info", "Test", "Hallo")
    bericht = baue_bericht(cfg, db, modus="backtest", datenquelle="test",
                           qualitaet=[{"symbol": "X", "ok": True, "kerzen": 10, "von": "a",
                                       "bis": "b", "fehler": [], "warnungen": []}],
                           plan=[], fehler=[])

    for schluessel in ("schema", "modus", "erstellt", "datenquelle", "konto", "risiko",
                       "risiko_grenzen", "validierungen", "auswahl", "plan", "entscheide",
                       "ereignisse", "fehler", "datenqualitaet", "wissen", "kosten", "live"):
        assert schluessel in bericht, schluessel

    assert bericht["schema"] == 2
    assert bericht["risiko_grenzen"]["risk_per_trade_pct"] == 1.0
    assert bericht["risiko_grenzen"]["max_drawdown_pct"] == 10.0
    assert bericht["risiko_grenzen"]["max_open_positions"] == 15
    assert isinstance(bericht["live"]["gruende"], list) and bericht["live"]["gruende"]


def test_bericht_liefert_die_korrelationsschwelle(cfg):
    """Die Oberfläche markiert Paare über genau dieser Schwelle."""
    db = Facts(cfg.db_pfad)
    bericht = baue_bericht(cfg, db)
    assert bericht["risiko_grenzen"]["max_correlation"] == 0.85
    assert bericht["risiko_grenzen"]["correlation_lookback"] == 60


def test_bericht_ist_json_serialisierbar(cfg, tmp_path):
    db = Facts(cfg.db_pfad)
    bericht = baue_bericht(cfg, db)
    ziel = schreibe_bericht(bericht, tmp_path / "dashboard.json")
    gelesen = json.loads(ziel.read_text(encoding="utf-8"))
    assert gelesen["schema"] == 2


def test_wissensbank_zaehlt_urteile(cfg):
    db = Facts(cfg.db_pfad)
    db.validierung_speichern("X", "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
                             "bestanden", "Test", {"out_of_sample": {"profit_factor": 1.4},
                                                   "gruende": []}, lauf="L1")
    db.validierung_speichern("X", "ema_cross", "ema_cross|fast=20,slow=100", {"fast": 20, "slow": 100},
                             "abgelehnt", "Test", {"out_of_sample": {}, "gruende": ["Zu wenig Trades"]},
                             lauf="L1")
    bericht = baue_bericht(cfg, db)
    db.zustand_setzen("letzter_lauf_id", "L1")
    bericht = baue_bericht(cfg, db)
    typen = bericht["wissen"]["typen"]
    assert len(typen) == 1
    assert typen[0]["tests"] == 2
    assert typen[0]["bestanden"] == 1
    assert typen[0]["quote_pct"] == 50.0
