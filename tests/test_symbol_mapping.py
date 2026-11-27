from __future__ import annotations

import copy

import pytest

from orakel.config import validiere_config
from orakel.kern.datenimport import internes_symbol


def test_broker_suffix_wird_nur_explizit_zugeordnet():
    mapping = {"symbol_map": {"EURUSDm": "EURUSD", "US500.cash": "US500"}}

    assert internes_symbol("eurusdm", mapping) == "EURUSD"
    assert internes_symbol("US500.CASH", mapping) == "US500"
    # Ohne Eintrag wird nichts geraten: Der Broker-Name bleibt stehen.
    assert internes_symbol("EURUSD.a", mapping) == "EURUSD.A"


def test_symbol_map_muss_eindeutige_texte_enthalten(cfg):
    daten = copy.deepcopy(cfg._d)
    daten["daten"]["symbol_map"] = {"EURUSDm": ""}
    with pytest.raises(ValueError, match="symbol_map"):
        validiere_config(daten)

    daten["daten"]["symbol_map"] = {"EURUSDm": "EURUSD", "eurusdm": "US500"}
    with pytest.raises(ValueError, match="doppelt"):
        validiere_config(daten)

    daten["daten"]["symbol_map"] = "EURUSD"
    with pytest.raises(ValueError, match="Tabelle"):
        validiere_config(daten)


def test_gueltige_symbol_map_wird_akzeptiert(cfg):
    daten = copy.deepcopy(cfg._d)
    daten["daten"]["symbol_map"] = {"EURUSDm": "EURUSD"}

    validiere_config(daten)
