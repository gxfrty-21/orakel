"""Tests für Datenqualität, Kosten und Ausführungszeitpunkt im Paper-Takt.

Jeder Test bildet einen zuvor bestätigten Fehler ab: Stop-Loss bei weniger als
30 Kerzen, Einstiegspreis als Ersatzkurs, fehlende Verkaufsslippage, Ausführung
zum Schlusskurs derselben Kerze, fehlende Risikostopp-Sperre und Tagesstart ohne
Marktwert.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from orakel.db import Facts
from orakel.paper import handelstag, tick


def ende_jetzt() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").floor("15min")


def baue_df(
    closes: list[float],
    *,
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    ende: pd.Timestamp | None = None,
) -> pd.DataFrame:
    n = len(closes)
    opens = opens if opens is not None else list(closes)
    highs = highs if highs is not None else [max(o, c) + 0.5 for o, c in zip(opens, closes)]
    lows = lows if lows is not None else [min(o, c) - 0.5 for o, c in zip(opens, closes)]
    ts = pd.date_range(end=ende or ende_jetzt(), periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "ts": ts, "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": [100.0] * n,
    })


def konto(cfg, df: pd.DataFrame | None = None, *, symbol: str = "TEST",
          menge: float = 10.0, einstieg: float = 100.0, stop: float = 95.0) -> Facts:
    db = Facts(cfg.db_pfad)
    if df is not None:
        db.kerzen_speichern(symbol, "M15", df.to_dict("records"))
    db.position_setzen(
        symbol, menge, einstieg, stop,
        json.dumps({"schluessel": "test", "validierung_id": 0}), "2026-01-01T00:00:00+00:00",
    )
    return db


def mit_auswahl(cfg, df: pd.DataFrame, *, symbol: str = "TEST") -> Facts:
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern(symbol, "M15", df.to_dict("records"))
    vid = db.validierung_speichern(
        symbol, "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
        "bestanden", "Test", {"out_of_sample": {"profit_factor": 1.4}, "gruende": []},
        lauf="L1",
    )
    db.auswahl_setzen(symbol, "ema_cross|fast=10,slow=50", vid)
    return db


def steigend(n: int = 120, start: float = 100.0) -> pd.DataFrame:
    return baue_df([start * (1.001 ** i) for i in range(n)])


def kosten(cfg, *, slippage_bps: float = 0.0, commission: float = 0.0,
           minimum: float = 0.0) -> None:
    cfg._d["kosten"] = {
        "commission_per_share": commission,
        "min_commission": minimum,
        "slippage_bps": slippage_bps,
    }


# ---------- A) Stop-Loss unabhängig von der Kerzenzahl ----------

def test_stop_loest_bei_einer_einzigen_gueltigen_kerze_aus(cfg):
    db = konto(cfg, baue_df([95.0], opens=[100.0], highs=[101.0], lows=[94.0]))
    ergebnis = tick(cfg, db)

    assert db.positionen() == []
    entscheid = dict(db.entscheide(1)[0])
    assert entscheid["aktion"] == "verkaufen"
    assert entscheid["kurs"] == pytest.approx(95.0)
    assert "Stop" in entscheid["status"]
    assert ergebnis["konto"]["positionen"] == 0


def test_stop_loest_bei_weniger_als_30_kerzen_aus(cfg):
    df = baue_df([100.0] * 9 + [93.0], highs=[100.5] * 10, lows=[99.5] * 9 + [92.0],
                 opens=[100.0] * 10)
    db = konto(cfg, df, stop=95.0)

    tick(cfg, db)

    assert db.positionen() == []


def test_kursluecke_unter_dem_stop_fuellt_zur_eroeffnung(cfg):
    db = konto(cfg, baue_df([80.0], opens=[80.0], highs=[81.0], lows=[79.0]), stop=95.0)

    tick(cfg, db)

    entscheid = dict(db.entscheide(1)[0])
    assert entscheid["kurs"] == pytest.approx(80.0)


# ---------- B) Fehlende und veraltete Kurse ----------

def test_fehlende_marktdaten_bleiben_offen_und_werden_gemeldet(cfg):
    db = konto(cfg, None)
    ergebnis = tick(cfg, db)

    assert len(db.positionen()) == 1
    assert ergebnis["datenprobleme"]["TEST"] == "keine Kerzen"
    assert ergebnis["konto"]["bewertung_unsicher"] is True
    assert ergebnis["einstiege_gesperrt"]
    assert any("keine belastbaren Kurse" in r["text"] for r in db.ereignisse(10))
    # Kein erfundener Kurs: Bewertung erfolgt zum Einstiegspreis und ist markiert.
    assert ergebnis["konto"]["equity"] == pytest.approx(cfg.start_kapital + 10 * 100.0)


def test_ungueltige_ohlc_werte_loesen_keinen_stop_aus(cfg):
    df = baue_df([100.0], opens=[100.0], highs=[90.0], lows=[110.0])
    db = konto(cfg, df, stop=95.0)

    ergebnis = tick(cfg, db)

    assert len(db.positionen()) == 1
    assert "ungültig" in ergebnis["datenprobleme"]["TEST"]


def test_veralteter_kurs_wird_erkannt_und_konservativ_bewertet(cfg):
    alt = ende_jetzt() - pd.Timedelta(days=3)
    df = baue_df([50.0] * 5, highs=[51.0] * 5, lows=[49.0] * 5, ende=alt)
    db = konto(cfg, df, menge=10, einstieg=100.0, stop=40.0)

    ergebnis = tick(cfg, db)

    assert "alt" in ergebnis["datenprobleme"]["TEST"]
    assert ergebnis["konto"]["bewertung_unsicher"] is True
    # min(letzter Kurs 50, Einstieg 100) — keine Aufwertung durch den Einstiegspreis.
    assert ergebnis["konto"]["equity"] == pytest.approx(cfg.start_kapital + 10 * 50.0)


def test_kauf_ohne_aktuelle_kurse_ist_gesperrt(cfg):
    alt = ende_jetzt() - pd.Timedelta(days=3)
    db = mit_auswahl(cfg, baue_df([100.0 * (1.001 ** i) for i in range(120)], ende=alt))

    tick(cfg, db)

    assert db.positionen() == []
    assert any("kein Einstieg" in r["text"] for r in db.ereignisse(10))


def test_unsichere_bewertung_blockiert_neue_einstiege(cfg):
    alt = ende_jetzt() - pd.Timedelta(days=3)
    db = konto(cfg, baue_df([50.0] * 5, highs=[51.0] * 5, lows=[49.0] * 5, ende=alt),
               menge=10, einstieg=100.0, stop=40.0)
    frisch = steigend(120)
    db.kerzen_speichern("NEU", "M15", frisch.to_dict("records"))
    vid = db.validierung_speichern(
        "NEU", "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
        "bestanden", "Test", {"gruende": []}, lauf="L1",
    )
    db.auswahl_setzen("NEU", "ema_cross|fast=10,slow=50", vid)

    ergebnis = tick(cfg, db)

    assert [p["symbol"] for p in db.positionen()] == ["TEST"]
    assert "Kursdaten unvollständig oder veraltet" in ergebnis["einstiege_gesperrt"]


# ---------- C) Slippage und Kommission auf beiden Seiten ----------

def test_verkauf_traegt_slippage_und_beide_kommissionen(cfg):
    kosten(cfg, slippage_bps=100.0, commission=1.0, minimum=0.0)
    db = konto(cfg, baue_df([90.0], opens=[100.0], highs=[101.0], lows=[90.0]),
               menge=10, einstieg=100.0, stop=95.0)

    ergebnis = tick(cfg, db)

    # fill = 95 * (1 - 0.01) = 94.05; Kommission 10 Stück * 1.0 je Seite
    assert ergebnis["konto"]["cash"] == pytest.approx(100_000 + 10 * 94.05 - 10.0)
    entscheid = dict(db.entscheide(1)[0])
    assert entscheid["kurs"] == pytest.approx(94.05)
    assert json.loads(entscheid["gruende"])[1] == "Netto -79.50"


def test_kauf_traegt_slippage_nach_oben(cfg):
    kosten(cfg, slippage_bps=50.0)
    df = steigend(120)
    df.loc[df.index[-1], "open"] = 200.0
    df.loc[df.index[-1], "high"] = 201.0
    df.loc[df.index[-1], "low"] = 199.0
    df.loc[df.index[-1], "close"] = 200.5
    db = mit_auswahl(cfg, df)

    tick(cfg, db)

    position = db.positionen()[0]
    assert position["einstieg"] == pytest.approx(200.0 * 1.005)


# ---------- D) Ausführung auf der Folgekerze ----------

def test_einstieg_fuellt_zur_eroeffnung_der_laufenden_kerze(cfg):
    df = steigend(120)
    df.loc[df.index[-1], "open"] = 321.0
    df.loc[df.index[-1], "high"] = 322.0
    df.loc[df.index[-1], "low"] = 320.0
    df.loc[df.index[-1], "close"] = 321.5
    db = mit_auswahl(cfg, df)

    tick(cfg, db)

    assert db.positionen()[0]["einstieg"] == pytest.approx(321.0)


def test_signalausstieg_fuellt_zur_eroeffnung_der_laufenden_kerze(cfg):
    fallend = [200.0 * (0.999 ** i) for i in range(120)]
    df = baue_df(fallend, opens=[c + 1.0 for c in fallend],
                 highs=[c + 2.0 for c in fallend], lows=[c - 2.0 for c in fallend])
    df.loc[df.index[-1], "open"] = 111.0
    df.loc[df.index[-1], "low"] = 110.9
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern("TEST", "M15", df.to_dict("records"))
    vid = db.validierung_speichern(
        "TEST", "ema_cross", "ema_cross|fast=10,slow=50", {"fast": 10, "slow": 50},
        "bestanden", "Test", {"gruende": []}, lauf="L1",
    )
    db.position_setzen("TEST", 10, 180.0, 50.0,
                       json.dumps({"schluessel": "ema_cross", "validierung_id": vid}),
                       "2026-01-01T00:00:00+00:00")

    tick(cfg, db)

    assert db.positionen() == []
    assert dict(db.entscheide(1)[0])["kurs"] == pytest.approx(111.0)


# ---------- E) Globaler Risikostopp ----------

def test_risikostopp_blockiert_jeden_einstieg(cfg):
    db = mit_auswahl(cfg, steigend(120))
    db.zustand_setzen("paper_konto", {
        "cash": 50_000.0, "hoechststand": 100_000.0, "tagesstart": 50_000.0,
        "datum": handelstag(),
    })

    ergebnis = tick(cfg, db)

    assert db.positionen() == []
    assert ergebnis["gestoppt"] is True
    assert "Risikostopp aktiv" in ergebnis["einstiege_gesperrt"]
    assert db.zustand("risiko_stopp") is not None


def test_tagesstart_bewertet_offene_positionen_zum_marktwert(cfg):
    gestern = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    db = konto(cfg, baue_df([200.0], opens=[199.0], highs=[201.0], lows=[198.0]),
               menge=1, einstieg=100.0, stop=50.0)
    db.zustand_setzen("paper_konto", {
        "cash": 1000.0, "hoechststand": 100_000.0, "tagesstart": 1000.0, "datum": gestern,
    })

    tick(cfg, db)

    assert db.zustand("paper_konto")["tagesstart"] == pytest.approx(1200.0)


def test_tagesstart_ohne_kurse_wird_als_unsicher_markiert(cfg):
    gestern = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    db = konto(cfg, None, menge=1, einstieg=100.0, stop=50.0)
    db.zustand_setzen("paper_konto", {
        "cash": 1000.0, "hoechststand": 100_000.0, "tagesstart": 1000.0, "datum": gestern,
    })

    tick(cfg, db)

    zustand = db.zustand("paper_konto")
    assert zustand["tagesstart"] == pytest.approx(1100.0)
    assert zustand["tagesstart_unsicher"] is True


def test_handelstag_rechnet_in_zuerich_ueber_die_zeitumstellung(cfg):
    winter = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    sommer = datetime(2026, 7, 15, 22, 30, tzinfo=timezone.utc)
    assert handelstag(winter) == "2026-01-16"
    assert handelstag(sommer) == "2026-07-16"
    # Tag der Umstellung: 00:30 UTC ist in Zürich bereits der neue Tag.
    assert handelstag(datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc)) == "2026-03-29"
    assert handelstag(datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)) == "2026-10-25"


def test_mehrere_positionen_mit_fehlendem_kurs(cfg):
    """Eine Position ohne Kurs wird konservativ bewertet, die andere zu Marktwert."""
    db = Facts(cfg.db_pfad)
    df = baue_df([120.0], opens=[119.0], highs=[121.0], lows=[118.0])
    db.kerzen_speichern("AAA", "M15", df.to_dict("records"))
    for symbol, menge in (("AAA", 10.0), ("BBB", 5.0)):
        db.position_setzen(symbol, menge, 100.0, 50.0,
                           json.dumps({"schluessel": "x", "validierung_id": 0}), "x")
    db.zustand_setzen("paper_konto", {
        "cash": 1000.0, "hoechststand": 100_000.0, "tagesstart": 1000.0,
        "datum": handelstag(),
    })

    ergebnis = tick(cfg, db)

    assert ergebnis["datenprobleme"] == {"BBB": "keine Kerzen"}
    assert ergebnis["konto"]["equity"] == pytest.approx(1000.0 + 10 * 120.0 + 5 * 100.0)
    assert ergebnis["konto"]["bewertung_unsicher"] is True


def test_risikostopp_bleibt_bei_fehlenden_kursen_aktiv(cfg):
    """Ohne belastbare Kurse darf ein bestehender Stopp nicht freigegeben werden."""
    db = konto(cfg, None, menge=1.0, einstieg=100.0, stop=50.0)
    db.zustand_setzen("paper_konto", {
        "cash": 100_000.0, "hoechststand": 100_000.0, "tagesstart": 100_000.0,
        "datum": handelstag(),
    })
    db.zustand_setzen("risiko_stopp", {"grund": "vorheriger Takt"})

    ergebnis = tick(cfg, db)

    assert db.zustand("risiko_stopp") is not None
    assert ergebnis["gestoppt"] is True
    assert any("bleibt aktiv" in r["text"] for r in db.ereignisse(10))
