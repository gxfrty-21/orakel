"""Config-Guards: ungültige Werte werden beim Laden abgelehnt.

Die Tests decken Standard- und Nutzerkonfiguration, fehlende Abschnitte,
fehlende Pflichtwerte, falsche Typen, negative/Null-/Extremwerte, Slippage-
Grenzen, unvollständige TOML-Dateien und Zeitrahmen-Grenzen ab.
"""
from __future__ import annotations

import pytest

from orakel.config import Config, load_config, validiere_config


def basis_config() -> dict:
    return {
        "basis": {"start_kapital": 100000.0, "waehrung": "USD",
                  "zeitzone": "Europe/Zurich", "db_pfad": "orakel.db",
                  "daten_ordner": "daten", "vault_ordner": "vault",
                  "datenquelle": "synthetisch", "bars_pro_jahr": 24960},
        "risiko": {"risk_per_trade_pct": 1.0, "max_drawdown_pct": 10.0,
                   "max_open_positions": 15, "max_daily_loss_pct": 10.0,
                   "max_gross_exposure_pct": 100.0, "max_position_pct": 20.0,
                   "min_cash_pct": 10.0, "max_korrelation": 0.85,
                   "correlation_lookback": 500, "atr_stop_multiple": 2.0},
        "kosten": {"commission_per_share": 0.005, "min_commission": 1.0,
                   "slippage_bps": 2.0},
        "daten": {"min_kerzen": 1200, "max_luecke_pct": 5.0,
                  "max_sprung_pct": 25.0, "max_alter_tage": 5,
                  "max_kurs_alter_stunden_m15": 4.0},
        "validierung": {"train_anteil": 0.7},
        "research": {"ema_fast": [10]},
    }


def test_standardkonfiguration_ist_gueltig():
    validiere_config(basis_config())


def test_nutzerkonfiguration_mit_zeitrahmen_ist_gueltig():
    daten = basis_config()
    daten["daten"].update({"max_kurs_alter_stunden_m1": 0.5,
                           "max_kurs_alter_stunden_m5": 2.0,
                           "max_kurs_alter_stunden_h1": 24.0})
    daten["risiko"]["risiko_stopp_freigabe_takte"] = 3
    validiere_config(daten)


def test_fehlender_optionaler_datenabschnitt_ist_gueltig():
    daten = basis_config()
    del daten["daten"]
    validiere_config(daten)


def test_fehlender_pflichtwert_wird_abgelehnt():
    daten = basis_config()
    del daten["risiko"]["max_open_positions"]
    with pytest.raises(ValueError, match="max_open_positions fehlt"):
        validiere_config(daten)


def test_falscher_datentyp_wird_abgelehnt():
    daten = basis_config()
    daten["kosten"]["slippage_bps"] = "zwei"
    with pytest.raises(ValueError, match="muss eine Zahl sein"):
        validiere_config(daten)
    daten = basis_config()
    daten["risiko"]["max_open_positions"] = True
    with pytest.raises(ValueError, match="muss eine Zahl sein"):
        validiere_config(daten)


def test_negative_werte_werden_abgelehnt():
    for abschnitt, schluessel, wert in [
        ("kosten", "commission_per_share", -0.01),
        ("kosten", "slippage_bps", -1.0),
        ("risiko", "risk_per_trade_pct", -1.0),
        ("risiko", "atr_stop_multiple", -2.0),
    ]:
        daten = basis_config()
        daten[abschnitt][schluessel] = wert
        with pytest.raises(ValueError):
            validiere_config(daten)


def test_null_werte_werden_abgelehnt_wo_sie_unsinnig_sind():
    for abschnitt, schluessel in [
        ("basis", "start_kapital"),
        ("risiko", "risk_per_trade_pct"),
        ("risiko", "max_drawdown_pct"),
        ("risiko", "max_daily_loss_pct"),
        ("risiko", "max_open_positions"),
        ("risiko", "correlation_lookback"),
    ]:
        daten = basis_config()
        daten[abschnitt][schluessel] = 0
        with pytest.raises(ValueError):
            validiere_config(daten)


def test_null_werte_sind_erlaubt_wo_sie_sinnvoll_sind():
    daten = basis_config()
    daten["kosten"].update({"commission_per_share": 0.0, "min_commission": 0.0,
                            "slippage_bps": 0.0})
    daten["risiko"]["min_cash_pct"] = 0.0
    daten["risiko"]["max_correlation"] = 0.0
    validiere_config(daten)


def test_extrem_hohe_werte_werden_begrenzt():
    daten = basis_config()
    daten["risiko"]["max_drawdown_pct"] = 1e9
    with pytest.raises(ValueError, match="max_drawdown_pct"):
        validiere_config(daten)
    daten = basis_config()
    daten["risiko"]["max_open_positions"] = 10**9
    validiere_config(daten)


def test_slippage_grenzwerte():
    for wert in (0.0, 9999.0, 9999.999):
        daten = basis_config()
        daten["kosten"]["slippage_bps"] = wert
        validiere_config(daten)
    for wert in (10_000.0, 10_001.0):
        daten = basis_config()
        daten["kosten"]["slippage_bps"] = wert
        with pytest.raises(ValueError, match="slippage_bps"):
            validiere_config(daten)


def test_ungueltige_risikoparameter():
    faelle = [
        ("risk_per_trade_pct", 101.0),
        ("max_position_pct", 1000.1),
        ("max_hebel", 0.9),
        ("min_cash_pct", 100.0),
        ("max_correlation", 1.1),
        ("max_correlation", -0.1),
        ("correlation_lookback", 1),
        ("risiko_stopp_freigabe_takte", 0),
    ]
    for schluessel, wert in faelle:
        daten = basis_config()
        daten["risiko"][schluessel] = wert
        with pytest.raises(ValueError):
            validiere_config(daten)


def test_korrelation_akzeptiert_beide_schluessel():
    daten = basis_config()
    del daten["risiko"]["max_korrelation"]
    daten["risiko"]["max_correlation"] = 0.9
    validiere_config(daten)


def test_unvollstaendige_toml_wird_beim_laden_abgelehnt(tmp_path):
    pfad = tmp_path / "config.toml"
    pfad.write_text('[basis]\nstart_kapital = 100000.0\ndb_pfad = "x.db"\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"Abschnitt \[risiko\] fehlt"):
        load_config(pfad)


def test_gueltige_toml_wird_geladen(tmp_path):
    daten = basis_config()
    pfad = tmp_path / "config.toml"
    zeilen = []
    for abschnitt, werte in daten.items():
        zeilen.append(f"[{abschnitt}]")
        for schluessel, wert in werte.items():
            if isinstance(wert, str):
                zeilen.append(f'{schluessel} = "{wert}"')
            elif isinstance(wert, list):
                zeilen.append(f"{schluessel} = {wert!r}")
            else:
                zeilen.append(f"{schluessel} = {wert!r}")
        zeilen.append("")
    pfad.write_text("\n".join(zeilen), encoding="utf-8")

    cfg = load_config(pfad)

    assert isinstance(cfg, Config)
    assert cfg.start_kapital == 100000.0


def test_takt_lehnt_ungueltige_slippage_ab(cfg):
    from orakel.kern.db import Facts
    from orakel.kern.paper import tick

    cfg._d["kosten"]["slippage_bps"] = 10_000.0
    with pytest.raises(ValueError, match="slippage_bps"):
        tick(cfg, Facts(cfg.db_pfad))


def test_zeitrahmen_grenzen_werden_validiert():
    daten = basis_config()
    daten["daten"]["max_kurs_alter_stunden_m15"] = 0
    with pytest.raises(ValueError, match="max_kurs_alter_stunden_m15"):
        validiere_config(daten)
