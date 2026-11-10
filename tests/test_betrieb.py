from __future__ import annotations

from datetime import datetime, timedelta, timezone

from orakel.betrieb import Betrieb, betrieb_health
from orakel.db import Facts

START = datetime(2026, 11, 10, 0, 0, tzinfo=timezone.utc)


class Uhr:
    def __init__(self, start: datetime = START) -> None:
        self.jetzt = start

    def __call__(self) -> datetime:
        return self.jetzt

    def plus(self, sekunden: float) -> None:
        self.jetzt += timedelta(seconds=sekunden)


def _cfg_mit(cfg, **werte):
    cfg._d["betrieb"].update(werte)
    return cfg


def _job(daten: dict, name: str) -> dict:
    return next(j for j in daten["jobs"] if j["name"] == name)


def test_24h_simulation_haelt_das_spider_intervall_ein(cfg):
    cfg = _cfg_mit(cfg, spider_intervall_minuten=360)
    db = Facts(cfg.db_pfad)
    uhr = Uhr()
    aufrufe: list[datetime] = []

    def spider():
        aufrufe.append(uhr.jetzt)
        return {"neu": 1, "gelesen": 1, "quellen": 1}

    betrieb = Betrieb(cfg, db, jetzt_funktion=uhr, jobs={"spider": spider})
    # 24 Stunden in Fünf-Minuten-Schritten; der echte Takt wäre 60 Sekunden.
    for _ in range(24 * 12):
        betrieb.takt()
        uhr.plus(300)

    assert len(aufrufe) == 4
    assert [int((t - START).total_seconds() / 3600) for t in aufrufe] == [0, 6, 12, 18]
    assert len(db.betrieb_laeufe(20)) == 4


def test_fehler_backoff_ueberlebt_einen_neustart(cfg):
    cfg = _cfg_mit(cfg, backoff_basis_sekunden=60, spider_backoff_max_sekunden=3600)
    db = Facts(cfg.db_pfad)
    uhr = Uhr()
    aufrufe: list[str] = []

    def kaputt():
        aufrufe.append("fehler")
        raise RuntimeError("Netz weg")

    erster = Betrieb(cfg, db, jetzt_funktion=uhr, jobs={"spider": kaputt})
    antwort = erster.takt()
    assert "Netz weg" in antwort["spider"]["fehler"]

    daten = erster.status_daten(uhr.jetzt)
    spider = _job(daten, "spider")
    assert spider["fehlschluesse"] == 1
    assert spider["backoff_sekunden"] == 60
    assert spider["letzter_fehler"]["art"] == "RuntimeError"
    assert daten["ok"] is False
    assert len(db.betrieb_laeufe(10)) == 1
    assert db.betrieb_laeufe(10)[0]["status"] == "fehler"

    # Neuer Prozess, gleiche SQLite-Datei: der Backoff bleibt bestehen.
    uhr.plus(30)
    zweiter = Betrieb(cfg, db, jetzt_funktion=uhr,
                      jobs={"spider": lambda: {"neu": 0}})
    assert "spider" not in zweiter.takt()
    assert aufrufe == ["fehler"]

    uhr.plus(31)
    dritter = Betrieb(cfg, db, jetzt_funktion=uhr,
                      jobs={"spider": lambda: {"neu": 0, "gelesen": 1}})
    assert "spider" in dritter.takt()
    assert len(aufrufe) == 1
    assert _job(dritter.status_daten(uhr.jetzt), "spider")["fehlschluesse"] == 0


def test_ressourcengrenze_ueberspringt_schreibintensiven_job(cfg):
    cfg = _cfg_mit(cfg, max_db_mb=0.0001)
    db = Facts(cfg.db_pfad)
    uhr = Uhr()
    aufrufe: list[str] = []

    def spider():
        aufrufe.append("gelaufen")
        return {"neu": 1}

    betrieb = Betrieb(cfg, db, jetzt_funktion=uhr, jobs={"spider": spider})
    antwort = betrieb.takt()

    assert aufrufe == []
    assert "Datenbank" in antwort["spider"]["uebersprungen"]
    daten = betrieb.status_daten(uhr.jetzt)
    assert _job(daten, "spider")["zustand"] == "wartet"
    assert any("Datenbank" in w["text"] for w in daten["warnungen"])
    assert daten["letzte_laeufe"][0]["status"] == "uebersprungen"
    assert daten["letzte_laeufe"][0]["fehler"].startswith("Datenbank")


def test_health_zaehlt_info_hinweise_nicht_als_warnung(cfg):
    db = Facts(cfg.db_pfad)

    daten = betrieb_health(cfg, db)

    assert daten["status"] == "aus"
    assert daten["warnungen"] == 0
    assert daten["hinweise"] == 1


def test_monitoring_liefert_limits_protokoll_und_aktiven_takt(cfg):
    db = Facts(cfg.db_pfad)
    uhr = Uhr()
    betrieb = Betrieb(cfg, db, jetzt_funktion=uhr,
                      jobs={"paper": lambda: {"ok": True, "zeit": uhr.jetzt.isoformat()}})
    betrieb.takt()

    daten = betrieb.status_daten(uhr.jetzt)

    assert daten["ok"] is True
    assert daten["takt"]["aktiv"] is True
    assert daten["takt"]["status"] == "laeuft"
    assert daten["ressourcen"]["limits"]["max_db_mb"] == 512
    assert daten["ressourcen"]["db_mb"] > 0
    assert daten["letzte_laeufe"][0]["job"] == "paper"
    assert daten["letzte_laeufe"][0]["status"] == "ok"
    assert daten["daten"]["artikel"] == 0
    assert daten["warnungen"] == []
