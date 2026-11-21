"""Cockpit: die vier Zahlen der Übersicht, ausschliesslich aus SQLite."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from orakel import cockpit
from orakel.config import Config
from orakel.kern.db import Facts

JETZT = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
ZURICH = ZoneInfo("Europe/Zurich")


def _konto(db: Facts, zeit: datetime, equity: float, cash: float = 1000.0) -> None:
    with db.conn() as c:
        c.execute(
            "INSERT INTO konto(zeit,equity,cash,positionen,hoechststand) VALUES (?,?,?,?,?)",
            (zeit.isoformat(), equity, cash, 0, equity),
        )


def _kerze(db: Facts, symbol: str, ts: datetime, close: float) -> None:
    with db.conn() as c:
        c.execute(
            "INSERT INTO kerzen(symbol,zeitrahmen,ts,open,high,low,close,volume)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (symbol, "M15", ts.isoformat(), close, close, close, close, 1.0),
        )


@pytest.fixture
def db(cfg: Config) -> Facts:
    return Facts(cfg.db_pfad)


def test_leere_db_erfindet_keine_zahlen(cfg: Config, db: Facts) -> None:
    block = cockpit.cockpit_block(cfg, db, jetzt=JETZT)
    assert block["konto"]["equity"] is None
    assert block["konto"]["cash"] is None
    assert block["konto"]["start_kapital"] == cfg.start_kapital
    assert block["positionen"] == []
    assert block["positionen_ergebnis"] is None
    for zeitraum in ("heute", "7t", "1m"):
        gewinn = block["gewinn"][zeitraum]
        assert gewinn["betrag"] is None
        assert gewinn["pct"] is None
        assert gewinn["verlauf"] == []
    assert block["bot"]["zustand"] == "nie"
    assert block["bot"]["letzter_takt"] is None
    assert block["bot"]["alter_sekunden"] is None


def test_gewinn_heute_7t_und_1m(cfg: Config, db: Facts) -> None:
    tagesbeginn = JETZT.astimezone(ZURICH).replace(hour=0, minute=0, second=0, microsecond=0)
    _konto(db, tagesbeginn.astimezone(timezone.utc) - timedelta(days=20), 100_000.0)
    _konto(db, tagesbeginn.astimezone(timezone.utc) - timedelta(minutes=1), 101_000.0)
    _konto(db, tagesbeginn.astimezone(timezone.utc) + timedelta(hours=1), 102_000.0)
    _konto(db, JETZT - timedelta(days=8), 99_000.0)
    _konto(db, JETZT - timedelta(minutes=5), 103_000.0)

    block = cockpit.cockpit_block(cfg, db, jetzt=JETZT)
    heute, woche, monat = (block["gewinn"][k] for k in ("heute", "7t", "1m"))

    assert block["konto"]["equity"] == 103_000.0
    assert heute["basis"] == 101_000.0
    assert heute["betrag"] == 2_000.0
    assert heute["pct"] == pytest.approx(1.98, abs=0.01)
    assert heute["seit_start"] is False
    assert heute["seit"] == tagesbeginn.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    # Für 7 Tage zählt der letzte Wert vor der Grenze, also der von vor 8 Tagen.
    assert woche["basis"] == 99_000.0
    assert woche["betrag"] == 4_000.0
    assert monat["basis"] == 100_000.0
    assert monat["betrag"] == 3_000.0
    assert monat["pct"] == pytest.approx(3.0)


def test_start_im_zeitraum_nimmt_das_startkapital(cfg: Config, db: Facts) -> None:
    _konto(db, JETZT - timedelta(hours=2), cfg.start_kapital)
    _konto(db, JETZT - timedelta(minutes=10), cfg.start_kapital + 500.0)

    block = cockpit.cockpit_block(cfg, db, jetzt=JETZT)
    for zeitraum in ("heute", "7t", "1m"):
        gewinn = block["gewinn"][zeitraum]
        assert gewinn["seit_start"] is True, zeitraum
        assert gewinn["basis"] == cfg.start_kapital, zeitraum
        assert gewinn["betrag"] == 500.0, zeitraum
        assert gewinn["verlauf"][0][0] <= (JETZT - timedelta(hours=2)).isoformat()


def test_verlauf_bleibt_bei_hoechstens_120_punkten(cfg: Config, db: Facts) -> None:
    for i in range(300):
        _konto(db, JETZT - timedelta(minutes=300 - i), 100_000.0 + i)

    block = cockpit.cockpit_block(cfg, db, jetzt=JETZT)
    for zeitraum in ("heute", "7t", "1m"):
        verlauf = block["gewinn"][zeitraum]["verlauf"]
        assert 2 <= len(verlauf) <= cockpit.MAX_PUNKTE, zeitraum
        assert verlauf[0][0] <= verlauf[-1][0]


def test_botstatus_laeuft_steht_gestoppt_und_nie(cfg: Config, db: Facts) -> None:
    assert cockpit.cockpit_block(cfg, db, jetzt=JETZT)["bot"]["zustand"] == "nie"

    db.zustand_setzen("paper_letzter_tick", (JETZT - timedelta(seconds=30)).isoformat())
    laeuft = cockpit.cockpit_block(cfg, db, jetzt=JETZT)["bot"]
    assert laeuft["zustand"] == "laeuft"
    assert laeuft["alter_sekunden"] == 30

    db.zustand_setzen("paper_letzter_tick", (JETZT - timedelta(hours=3)).isoformat())
    steht = cockpit.cockpit_block(cfg, db, jetzt=JETZT)["bot"]
    assert steht["zustand"] == "steht"
    assert steht["alter_sekunden"] == 3 * 3600

    db.zustand_setzen("risiko_stopp", {"grund": "Drawdown 10 % überschritten"})
    gestoppt = cockpit.cockpit_block(cfg, db, jetzt=JETZT)["bot"]
    assert gestoppt["zustand"] == "gestoppt"
    assert "Drawdown" in gestoppt["text"]


def test_offene_position_mit_letztem_kurs(cfg: Config, db: Facts) -> None:
    db.position_setzen("AAPL", 10.0, 100.0, 90.0, "ema", (JETZT - timedelta(days=1)).isoformat())
    _kerze(db, "AAPL", JETZT - timedelta(minutes=15), 110.0)
    _kerze(db, "AAPL", JETZT, 112.0)

    block = cockpit.cockpit_block(cfg, db, jetzt=JETZT)
    (position,) = block["positionen"]
    assert position["symbol"] == "AAPL"
    assert position["kurs"] == 112.0
    assert position["wert"] == 1_120.0
    assert position["ergebnis"] == 120.0
    assert position["ergebnis_pct"] == pytest.approx(12.0)
    assert block["positionen_ergebnis"] == 120.0
