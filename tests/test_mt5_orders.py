from __future__ import annotations

import pytest

from orakel.config import RisikoGrenzen
from orakel.kern.mt5_orders import (
    ORDER_FILLING_IOC,
    ORDER_TYPE_BUY,
    PaperOnlyError,
    PaperOrderGateway,
    OrderFehler,
    SymbolSpec,
    gleiche_positionen,
    normalisiere_volumen,
    plane_kauf,
)


def spec(**kw) -> SymbolSpec:
    basis = dict(symbol="EURUSD", digits=5, point=0.0001, volume_min=0.01,
                 volume_max=100.0, volume_step=0.01, stops_level=10, filling="ioc")
    basis.update(kw)
    return SymbolSpec(**basis)


def test_volumen_wird_auf_schritt_abgerundet():
    assert normalisiere_volumen(0.379, spec()) == 0.37
    assert normalisiere_volumen(0.019, spec()) == 0.01


def test_volumen_unter_minimum_wird_abgelehnt():
    assert normalisiere_volumen(0.004, spec()) == 0.0
    assert normalisiere_volumen(0.0, spec()) == 0.0
    assert normalisiere_volumen(float("nan"), spec()) == 0.0


def test_volumen_wird_auf_maximum_begrenzt():
    assert normalisiere_volumen(500.0, spec(volume_max=20.0)) == 20.0


def test_orderplan_enthaelt_vollstaendigen_mt5_request(cfg):
    plan = plane_kauf(
        spec=spec(), ask=1.1000, stop=1.0950, equity=100_000.0, cash=100_000.0,
        grenzen=RisikoGrenzen.aus_config(cfg), take_profit=1.1100,
        magic=4711, kommentar="Paper-Test",
    )

    assert plan.volumen > 0
    assert plan.risiko <= 1_000.0 + 1e-9
    assert plan.request["action"] == 1
    assert plan.request["type"] == ORDER_TYPE_BUY
    assert plan.request["symbol"] == "EURUSD"
    assert plan.request["price"] == 1.1
    assert plan.request["sl"] == 1.095
    assert plan.request["tp"] == 1.11
    assert plan.request["magic"] == 4711
    assert plan.request["type_filling"] == ORDER_FILLING_IOC


def test_stop_unter_broker_mindestabstand_wird_abgelehnt(cfg):
    with pytest.raises(OrderFehler, match="Stop-Level"):
        plane_kauf(spec=spec(), ask=1.1000, stop=1.09995, equity=100_000.0,
                   cash=100_000.0, grenzen=RisikoGrenzen.aus_config(cfg))


def test_stop_ueber_ask_und_ungueltiger_kurs_werden_abgelehnt(cfg):
    grenzen = RisikoGrenzen.aus_config(cfg)
    with pytest.raises(OrderFehler, match="nicht unter"):
        plane_kauf(spec=spec(), ask=1.1000, stop=1.1001, equity=100_000.0,
                   cash=100_000.0, grenzen=grenzen)
    with pytest.raises(OrderFehler, match="Ask"):
        plane_kauf(spec=spec(), ask=0.0, stop=1.0, equity=100_000.0,
                   cash=100_000.0, grenzen=grenzen)


def test_zu_kleines_volumen_wird_abgelehnt(cfg):
    with pytest.raises(OrderFehler, match="Broker-Minimum"):
        plane_kauf(spec=spec(volume_min=5.0, volume_step=1.0), ask=100.0, stop=99.0,
                   equity=1_000.0, cash=1_000.0,
                   grenzen=RisikoGrenzen.aus_config(cfg))


def test_gateway_sendet_niemals_einen_echten_auftrag(cfg):
    plan = plane_kauf(spec=spec(), ask=1.1000, stop=1.0950, equity=100_000.0,
                      cash=100_000.0, grenzen=RisikoGrenzen.aus_config(cfg))

    with pytest.raises(PaperOnlyError, match="gesperrt"):
        PaperOrderGateway().senden(plan)


def test_positionsabgleich_erkennt_fehlende_und_abweichende_positionen():
    abgleich = gleiche_positionen(
        {"eurusd": 1.0, "US500": 2.0}, {"EURUSD": 1.0, "US500": 2.5, "XAUUSD": 1.0},
    )

    assert not abgleich.ok
    assert abgleich.nur_lokal == ()
    assert abgleich.nur_broker == ("XAUUSD",)
    assert abgleich.abweichend == ("US500",)
    assert gleiche_positionen({"EURUSD": 1.0}, {"eurusd": 1.0}).ok
