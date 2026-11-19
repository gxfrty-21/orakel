"""Long-/Short-Bewertung und Konservativität ohne aktuelle Kurse.

Der Paper-Takt ist Long-only: ``Facts.position_setzen`` lehnt Mengen <= 0 ab.
Die Bewertungsfunktion muss trotzdem richtungsabhängig rechnen, damit ein
Altbestand mit negativer Menge (Short) nicht wie eine Long-Position bewertet
wird. Fehlende oder veraltete Kurse dürfen die Equity nie erhöhen.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest

from orakel.db import Facts
from orakel.paper import _equity, _positionswert, kurs_max_alter_stunden, tick

from test_paper_datenqualitaet import baue_df, ende_jetzt


def pos(symbol: str, menge: float, einstieg: float) -> dict:
    return {"symbol": symbol, "menge": menge, "einstieg": einstieg}


def insert_short(db: Facts, symbol: str, menge: float, einstieg: float) -> None:
    """Simuliert einen Altbestand mit negativer Menge direkt in SQLite."""
    with db.conn() as c:
        c.execute(
            "INSERT INTO positionen(symbol,menge,einstieg,stop,strategie,eroeffnet)"
            " VALUES (?,?,?,?,?,?)",
            (symbol, -abs(menge), einstieg, 1.0,
             json.dumps({"schluessel": "alt", "validierung_id": 0}), "2026-01-01T00:00:00+00:00"),
        )


# ---------- Richtung und Kurspfad ----------

def test_long_steigender_kurs_gewinnt():
    assert _positionswert(pos("A", 10, 100.0), {"A": 120.0}, {}) == 120.0
    assert _equity(0.0, [pos("A", 10, 100.0)], {"A": 120.0}, {}) == (1200.0, False)


def test_long_fallender_kurs_verliert():
    assert _equity(0.0, [pos("A", 10, 100.0)], {"A": 80.0}, {}) == (800.0, False)


def test_short_steigender_kurs_erhoeht_die_schuld():
    # Short: 10 Stück verkauft, Kurs steigt 100 -> 120, Rückkauf teurer.
    assert _equity(5000.0, [pos("A", -10, 100.0)], {"A": 120.0}, {}) == (3800.0, False)


def test_short_fallender_kurs_gewinnt():
    assert _equity(5000.0, [pos("A", -10, 100.0)], {"A": 80.0}, {}) == (4200.0, False)


# ---------- Fehlende Kurse ----------

def test_fehlender_kurs_long_bewertet_kleineren_wert():
    assert _positionswert(pos("A", 10, 100.0), {}, {}) == 100.0
    assert _equity(0.0, [pos("A", 10, 100.0)], {}, {}) == (1000.0, True)


def test_fehlender_kurs_short_bewertet_groesseren_wert():
    # Ohne Ersatzkurs ist der Einstieg die einzige bekannte Größe: -1000.
    assert _positionswert(pos("A", -10, 100.0), {}, {}) == 100.0
    assert _equity(0.0, [pos("A", -10, 100.0)], {}, {}) == (-1000.0, True)


# ---------- Veraltete Kurse (kein aktueller Kurs, Ersatz vorhanden) ----------

def test_veralteter_kurs_long_nutzt_kleineren_wert():
    assert _positionswert(pos("A", 10, 100.0), {}, {"A": 50.0}) == 50.0
    assert _positionswert(pos("A", 10, 100.0), {}, {"A": 150.0}) == 100.0


def test_veralteter_kurs_short_nutzt_groesseren_wert():
    # Ein gefallener Altkurs darf den Short nicht besser machen: max(100, 50).
    assert _positionswert(pos("A", -10, 100.0), {}, {"A": 50.0}) == 100.0
    assert _positionswert(pos("A", -10, 100.0), {}, {"A": 150.0}) == 150.0


# ---------- Mehrere Positionen ----------

def test_mehrere_longs_summeren_sich():
    equity, unsicher = _equity(1000.0, [pos("A", 10, 100.0), pos("B", 5, 50.0)],
                               {"A": 110.0, "B": 60.0}, {})
    assert equity == pytest.approx(1000.0 + 1100.0 + 300.0)
    assert unsicher is False


def test_mehrere_shorts_summeren_sich():
    equity, unsicher = _equity(1000.0, [pos("A", -10, 100.0), pos("B", -5, 50.0)],
                               {"A": 90.0, "B": 40.0}, {})
    assert equity == pytest.approx(1000.0 - 900.0 - 200.0)
    assert unsicher is False


def test_gemischte_long_und_short_positionen():
    equity, unsicher = _equity(1000.0, [pos("A", 10, 100.0), pos("B", -5, 50.0)],
                               {"A": 110.0, "B": 60.0}, {})
    assert equity == pytest.approx(1000.0 + 1100.0 - 300.0)
    assert unsicher is False


def test_mehrere_positionen_eine_ohne_aktuellen_kurs():
    equity, unsicher = _equity(
        0.0,
        [pos("A", 10, 100.0), pos("B", 5, 50.0)],
        {"A": 120.0},
        {"B": 40.0},
    )
    assert unsicher is True
    assert equity == pytest.approx(1200.0 + 5 * 40.0)


# ---------- Long-only-Grenze und Takt-Integration ----------

def test_position_setzen_lehnt_nichtpositive_menge_ab(cfg):
    db = Facts(cfg.db_pfad)
    for menge in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            db.position_setzen("A", menge, 100.0, 90.0, "{}", "2026-01-01T00:00:00+00:00")
    assert db.positionen() == []


def test_kursgrenze_ist_zeitrahmenabhaengig():
    assert kurs_max_alter_stunden({}, "M1") == 0.5
    assert kurs_max_alter_stunden({}, "M5") == 2.0
    assert kurs_max_alter_stunden({}, "M15") == 4.0
    assert kurs_max_alter_stunden({}, "H1") == 24.0
    assert kurs_max_alter_stunden({}, "unbekannt") == 4.0


def test_kursgrenze_laesst_sich_global_und_pro_zeitrahmen_ueberschreiben():
    assert kurs_max_alter_stunden({"max_kurs_alter_stunden": 8.0}, "M15") == 8.0
    cfg = {"max_kurs_alter_stunden": 8.0, "max_kurs_alter_stunden_m15": 1.5}
    assert kurs_max_alter_stunden(cfg, "M15") == 1.5
    assert kurs_max_alter_stunden(cfg, "H1") == 8.0


def test_fuenf_stunden_alte_m15_kerze_gilt_als_veraltet(cfg):
    df = baue_df([100.0] * 5, ende=ende_jetzt() - pd.Timedelta(hours=5))
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern("TEST", "M15", df.to_dict("records"))
    db.position_setzen("TEST", 10.0, 100.0, 1.0, "{}", "2026-01-01T00:00:00+00:00")

    ergebnis = tick(cfg, db)

    assert "alt" in ergebnis["datenprobleme"]["TEST"]
    assert ergebnis["konto"]["bewertung_unsicher"] is True


def test_legacy_short_wird_im_takt_konservativ_bewertet(cfg):
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern("TEST", "M15", baue_df([120.0]).to_dict("records"))
    insert_short(db, "TEST", 10.0, 100.0)

    ergebnis = tick(cfg, db)

    assert ergebnis["konto"]["cash"] == pytest.approx(cfg.start_kapital)
    assert ergebnis["konto"]["equity"] == pytest.approx(cfg.start_kapital - 1200.0)
    assert ergebnis["konto"]["bewertung_unsicher"] is False


def test_legacy_short_ohne_kurs_bewertet_hoeheren_wert(cfg):
    db = Facts(cfg.db_pfad)
    insert_short(db, "TEST", 10.0, 100.0)
    db.kerzen_speichern("TEST", "M15",
                        baue_df([150.0], ende=ende_jetzt() - pd.Timedelta(days=2)).to_dict("records"))

    ergebnis = tick(cfg, db)

    assert ergebnis["konto"]["equity"] == pytest.approx(cfg.start_kapital - 1500.0)
    assert ergebnis["konto"]["bewertung_unsicher"] is True
