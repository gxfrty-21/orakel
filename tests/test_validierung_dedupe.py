"""Identische Richter-Ergebnisse werden nur einmal in der Fakten-DB gehalten.

Ohne diese Prüfung legt jeder Engine-Lauf dieselben Validierungen und Trades
erneut an; jede Zählung über ``validierungen`` oder ``trades`` würde dann mit
der Zahl der Läufe wachsen, ohne dass sich am Markt etwas geändert hat.
"""
from __future__ import annotations

from orakel.kern.db import Facts

SCHLUESSEL = "ema_cross|fast=10,slow=100"
TRADES = [
    {"einstieg": "2024-01-02 10:00:00", "ausstieg": "2024-01-02 12:00:00",
     "stueck": 10.0, "netto": 12.5, "rendite_pct": 0.4, "grund": "Signal"},
    {"einstieg": "2024-01-03 09:00:00", "ausstieg": "2024-01-03 09:45:00",
     "stueck": 10.0, "netto": -5.0, "rendite_pct": -0.2, "grund": "Stop"},
]


def _speichern(db: Facts, lauf: str, *, trades=TRADES, urteil: str = "abgelehnt") -> int:
    return db.validierung_speichern(
        "US500", "ema_cross", SCHLUESSEL, {"fast": 10, "slow": 100},
        urteil, "Test", {"out_of_sample": {"profit_factor": 1.1}, "gruende": []},
        trades, lauf=lauf,
    )


def test_identischer_lauf_erzeugt_keine_zweite_validierung(cfg):
    db = Facts(cfg.db_pfad)
    erste = _speichern(db, "L1")
    zweite = _speichern(db, "L2")

    assert zweite == erste
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM validierungen").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == len(TRADES)
        assert c.execute("SELECT lauf FROM validierungen").fetchone()[0] == "L2"


def test_erstellt_und_lauf_wandern_gemeinsam(cfg, monkeypatch):
    db = Facts(cfg.db_pfad)
    erste = _speichern(db, "L1")
    monkeypatch.setattr("orakel.kern.db.jetzt", lambda: "2026-01-02T03:04:05+00:00")
    zweite = _speichern(db, "L2")

    assert zweite == erste
    with db.conn() as c:
        zeile = c.execute(
            "SELECT erstellt, lauf FROM validierungen WHERE id=?", (erste,)
        ).fetchone()
    assert zeile["erstellt"] == "2026-01-02T03:04:05+00:00"
    assert zeile["lauf"] == "L2"


def test_geaendertes_urteil_ueberschreibt_die_fruehere_bewertung_nicht(cfg):
    db = Facts(cfg.db_pfad)
    erste = _speichern(db, "L1", urteil="bestanden")
    zweite = _speichern(db, "L2", urteil="abgelehnt")

    assert zweite != erste
    with db.conn() as c:
        zeilen = [(int(r["id"]), r["urteil"], r["lauf"])
                  for r in c.execute("SELECT id, urteil, lauf FROM validierungen ORDER BY id")]
        assert zeilen == [(erste, "bestanden", "L1"), (zweite, "abgelehnt", "L2")]
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 2 * len(TRADES)


def test_geaenderte_trades_ergeben_eine_neue_validierung(cfg):
    db = Facts(cfg.db_pfad)
    erste = _speichern(db, "L1")
    andere = [dict(TRADES[0], netto=99.0)]
    zweite = _speichern(db, "L2", trades=andere)

    assert zweite != erste
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM validierungen").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == len(TRADES) + 1


def test_ohne_trades_entscheidet_das_urteil(cfg):
    db = Facts(cfg.db_pfad)
    erste = _speichern(db, "L1", trades=[], urteil="abgelehnt")
    zweite = _speichern(db, "L2", trades=[], urteil="abgelehnt")
    dritte = _speichern(db, "L3", trades=[], urteil="bestanden")

    assert zweite == erste
    assert dritte != erste
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM validierungen").fetchone()[0] == 2
