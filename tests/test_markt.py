from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from orakel.markt import korrelation_max, markt_uebersicht


def kurse(n: int = 600, drift: float = 0.0, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2025-01-01", periods=n, freq="15min", tz="UTC")
    close = 100 * np.exp(np.cumsum(np.full(n, drift) + rng.standard_normal(n) * 0.001))
    return pd.DataFrame({
        "ts": ts, "open": close * 0.999, "high": close * 1.002,
        "low": close * 0.998, "close": close, "volume": 10.0,
    })


def test_marktuebersicht_liefert_kennzahlen():
    daten = {"EURUSD": kurse(600, 0.0002), "US500": kurse(600, 0.0, seed=2)}
    m = markt_uebersicht(daten)

    assert len(m["symbole"]) == 2
    for s in m["symbole"]:
        assert s["kurs"] > 0
        assert s["regime"] in {"Trend auf", "Trend ab", "Seitwärts", "Stress", "zu wenig Daten", "unklar"}
        assert s["stadt"] in {"Frankfurt", "New York", "London", "Tokio", "unbekannt"}
        assert s["kerzen"] == 600


def test_korrelation_erkennt_gleiche_reihe():
    df = kurse(400, 0.0001, seed=3)
    m = markt_uebersicht({"AAA": df, "BBB": df.copy()})
    assert m["korrelation"], "Es muss mindestens ein Paar geben"
    assert abs(m["korrelation"][0]["wert"] - 1.0) < 0.01


def test_leere_daten_brechen_nicht():
    m = markt_uebersicht({})
    assert m["symbole"] == []
    assert m["korrelation"] == []


def test_korrelation_max_erkennt_identische_reihe():
    df = kurse(400, seed=5)
    wert = korrelation_max("AAA", {"AAA": df, "BBB": df.copy()}, ["BBB"])
    assert wert == pytest.approx(1.0, abs=0.01)


def test_korrelation_max_ohne_vergleichsbasis_ist_none():
    df = kurse(400, seed=6)
    assert korrelation_max("AAA", {"AAA": df}, []) is None
    # Eine offene Position im selben Symbol ist keine Vergleichsbasis
    assert korrelation_max("AAA", {"AAA": df}, ["AAA"]) is None
    # Unbekanntes Symbol oder zu wenig gemeinsame Kerzen
    assert korrelation_max("AAA", {"AAA": df}, ["XXX"]) is None
    assert korrelation_max("AAA", {"AAA": kurse(40), "BBB": kurse(40)}, ["BBB"]) is None


def test_korrelation_max_nimmt_den_groessten_betrag():
    a = kurse(400, seed=1)
    b = kurse(400, seed=2)
    wert = korrelation_max("AAA", {"AAA": a, "BBB": b, "CCC": a.copy()}, ["BBB", "CCC"])
    assert wert is not None and wert > 0.9
