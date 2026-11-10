from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orakel.watchdog import bewerte

JETZT = datetime(2026, 11, 10, 20, 0, 0, tzinfo=timezone.utc)


def _health(alter_sekunden: int | None = 30, status: str = "laeuft",
            ok: bool = True) -> dict:
    letzter = (
        (JETZT - timedelta(seconds=alter_sekunden)).isoformat()
        if alter_sekunden is not None else None
    )
    return {
        "ok": ok,
        "betrieb": {
            "status": status,
            "letzter_takt": letzter,
            "warnungen": 0,
            "hinweise": 0,
        },
        "commit": "abc123",
    }


def test_frischer_takt_ist_ok():
    ergebnis = bewerte(_health(30), JETZT, 300)

    assert ergebnis["ok"] is True
    assert ergebnis["reason"] == "frisch"
    assert ergebnis["takt_alter_sekunden"] == 30


def test_zu_alter_takt_wird_erkannt():
    ergebnis = bewerte(_health(301), JETZT, 300)

    assert ergebnis["ok"] is False
    assert ergebnis["reason"] == "takt_zu_alt"
    assert "301" in ergebnis["detail"]


def test_ausgeschalteter_takt_wird_erkannt():
    ergebnis = bewerte(_health(None, status="aus"), JETZT, 300)

    assert ergebnis["ok"] is False
    assert ergebnis["reason"] == "takt_status_aus"


def test_fehlender_takt_wird_erkannt():
    ergebnis = bewerte(_health(None, status="laeuft"), JETZT, 300)

    assert ergebnis["ok"] is False
    assert ergebnis["reason"] == "takt_fehlt"


def test_health_ok_false_wird_erkannt():
    ergebnis = bewerte(_health(30, ok=False), JETZT, 300)

    assert ergebnis["ok"] is False
    assert ergebnis["reason"] == "health_nicht_ok"
