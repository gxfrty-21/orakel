from __future__ import annotations

from datetime import datetime, timezone

from orakel.db import Facts
from orakel.nexus.kalibrierung import (
    kalibrierung_auffrischen,
    kalibrierung_statistik,
    prognose_anlegen,
    pruefe_prognosen,
    prognosen_aus_intel,
)

JETZT = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)
SPAETER = datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc)


def _kerze(ts: str, close: float) -> dict[str, object]:
    return {"ts": ts, "open": close, "high": close, "low": close,
            "close": close, "volume": 1}


def _db_mit_kurs(tmp_path) -> Facts:
    db = Facts(tmp_path / "orakel.db")
    db.kerzen_speichern("EURUSD", "M15", [_kerze("2026-11-10T09:00:00+00:00", 1.10)])
    return db


def test_faellige_prognosen_werden_gegen_echte_kerzen_geprueft(tmp_path):
    db = _db_mit_kurs(tmp_path)
    steigt = prognose_anlegen(
        db, "EURUSD steigt", "steigt", zeithorizont="1h",
        konfidenz=0.8, symbol="EURUSD", jetzt_wert=JETZT,
    )
    sinkt = prognose_anlegen(
        db, "EURUSD sinkt", "sinkt", zeithorizont="1h",
        konfidenz=0.2, symbol="EURUSD", jetzt_wert=JETZT,
    )
    assert steigt["status"] == "offen"
    assert sinkt["status"] == "offen"

    db.kerzen_speichern("EURUSD", "M15", [_kerze("2026-11-10T10:30:00+00:00", 1.12)])
    assert pruefe_prognosen(db, SPAETER) == 2

    rows = {row["kennung"]: row for row in db.nexus_forecasts(10)}
    assert rows[steigt["kennung"]]["ergebnis"]["eingetreten"] == 1
    assert rows[sinkt["kennung"]]["ergebnis"]["eingetreten"] == 0
    assert rows[steigt["kennung"]]["status"] == "eingetreten"
    assert rows[sinkt["kennung"]]["status"] == "nicht_eingetreten"

    statistik = kalibrierung_statistik(db)
    assert statistik["geprueft"] == 2
    assert statistik["treffer"] == 1
    assert statistik["trefferquote"] == 0.5
    assert statistik["brier"] == 0.04


def test_offene_prognose_wird_nicht_vor_faelligkeit_geprueft(tmp_path):
    db = _db_mit_kurs(tmp_path)
    forecast = prognose_anlegen(
        db, "EURUSD steigt", "steigt", zeithorizont="2h",
        konfidenz=0.7, symbol="EURUSD", jetzt_wert=JETZT,
    )
    db.kerzen_speichern("EURUSD", "M15", [_kerze("2026-11-10T10:30:00+00:00", 1.12)])
    assert pruefe_prognosen(db, SPAETER) == 0
    assert db.nexus_forecast(forecast["kennung"])["status"] == "offen"


def test_intel_auftraege_werden_als_prognosen_importiert(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    db.intel_auftrag_speichern({
        "kennung": "RS-20261110-0001",
        "zeit": "2026-11-10T09:00:00+00:00",
        "abteilung": "D",
        "titel": "Meldungslage zu EURUSD prüfen",
        "hypothese": "Die Meldungslage geht mit mindestens einem ATR Bewegung einher.",
        "art": "markt",
        "bezug_symbol": "EURUSD",
        "kurs_bei_erstellung": 1.1,
        "atr_bei_erstellung": 0.01,
        "status": "bestätigt",
        "ergebnis": "Bewegung war größer als ein ATR.",
    })
    assert prognosen_aus_intel(db, SPAETER)["abgeschlossen"] == 1
    forecast = db.nexus_forecasts(10)[0]
    assert forecast["auftrag_id"] is not None
    assert forecast["konfidenz"] == 0.5
    assert forecast["ergebnis"]["eingetreten"] == 1
    assert forecast["status"] == "eingetreten"

    db.intel_status_setzen("RS-20261110-0001", "widerlegt", "Bewegung blieb aus.")
    kalibrierung_auffrischen(db, SPAETER)
    forecast = db.nexus_forecasts(10)[0]
    assert forecast["ergebnis"]["eingetreten"] == 0
    assert forecast["status"] == "nicht_eingetreten"
    assert kalibrierung_statistik(db)["brier"] == 0.25


def test_verworfene_intel_auftraege_zaehlen_nicht_als_fehlprognose(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    db.intel_auftrag_speichern({
        "kennung": "RS-20261110-0002",
        "zeit": "2026-11-10T09:00:00+00:00",
        "abteilung": "C",
        "titel": "Ablehnungsgrund prüfen",
        "hypothese": "Der Ablehnungsgrund tritt erneut auf.",
        "art": "strategie",
        "status": "verworfen",
        "ergebnis": "Keine nächste Validierung vorhanden.",
    })
    prognosen_aus_intel(db, SPAETER)
    forecast = db.nexus_forecasts(10)[0]
    assert forecast["status"] == "unpruefbar"
    assert forecast["ergebnis"] is None
    statistik = kalibrierung_statistik(db)
    assert statistik["geprueft"] == 0
    assert statistik["unpruefbar"] == 1
    assert statistik["brier"] is None


def test_ohne_stichprobe_bleibt_brier_offen(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    statistik = kalibrierung_statistik(db)
    assert statistik["geprueft"] == 0
    assert statistik["brier"] is None
    assert statistik["trefferquote"] is None
    assert "keine Aussage" in statistik["hinweis"]
