from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import pytest

from orakel.db import Facts
from orakel.intel import (IntelNetz, _thema, auftrag_aendern, lage, relevanz,
                          weiterleitung_aendern)
from orakel.knowledge import Vault
from orakel.report import baue_bericht


def netz(cfg) -> IntelNetz:
    return IntelNetz(cfg, Facts(cfg.db_pfad), Vault(cfg.vault_ordner))


def artikel(db: Facts, titel: str, url: str, symbole: tuple[str, ...] = ("EURUSD",),
            quali: float = 0.8, typ: str = "notenbank",
            text: str = "Die Europäische Zentralbank liess den Leitzins unveraendert.") -> int:
    aid = db.artikel_speichern(
        "Testquelle", typ, titel, url, "Mon, 03 Nov 2025 10:00:00 GMT",
        text, quali, list(symbole), titel,
    )
    assert aid
    return int(aid)


def test_thema_und_relevanz(cfg):
    assert _thema("Die EZB lässt den Zins unverändert") == "makro"
    assert _thema("Neue Studie zum Momentum-Signal") == "strategie"
    db = Facts(cfg.db_pfad)
    zeile = db.artikel_by_ids([artikel(db, "EZB hält Zins", "https://a.example/1")])[0]
    wert = relevanz(zeile)
    assert 0 < wert <= 1


def test_weiterleitung_bekommt_eigene_kennung_und_status(cfg):
    n = netz(cfg)
    ids = [artikel(n.db, f"EZB Meldung {i}", f"https://a.example/{i}") for i in range(2)]
    ids += [artikel(n.db, f"US500 Ausblick {i}", f"https://b.example/{i}", symbole=("US500",))
            for i in range(2)]
    ergebnis = n.verarbeite(ids)

    assert ergebnis["weiterleitungen"] >= 2
    wl = n.db.intel_weiterleitungen(10)
    assert all(w["kennung"].startswith("WL-") for w in wl)
    assert len({w["kennung"] for w in wl}) == len(wl), "Jede Weiterleitung braucht eine eigene Kennung"
    assert wl[0]["status"] == "neu"
    assert wl[0]["an"] in {"Trading Floor", "Labor", "Forschungsabteilung",
                           "Risikomanagement", "Wissenszentrum"}

    # Ein Auftrag für die Abteilung quittiert deren offene Weiterleitungen.
    n.auftrag(abteilung="D", titel="US500 prüfen", art="markt", bezug_symbol="US500")
    status = {w["an"]: w["status"] for w in n.db.intel_weiterleitungen(10)}
    assert status.get("Trading Floor") == "übernommen"


def test_forschungsauftrag_hat_alle_felder_und_notiz(cfg):
    n = netz(cfg)
    ids = [artikel(n.db, f"EZB Meldung {i}", f"https://a.example/e{i}") for i in range(3)]
    ids.append(artikel(n.db, "EZB Zweitquelle", "https://b.example/e1"))
    ergebnis = n.verarbeite(ids)

    assert ergebnis["auftraege"], "Bei 4 Meldungen aus 2 Quellen muss ein Auftrag entstehen"
    o = n.db.intel_auftraege(5)[0]
    for feld in ("problem", "information", "quellen", "frage", "hypothese",
                 "untersuchung", "nutzen", "risiko"):
        assert o[feld], feld
    assert json.loads(o["quellen"])
    assert o["status"] == "offen"
    assert o["kennung"].startswith("RS-")
    assert list(Path(cfg.vault_ordner).rglob("*.md"))


def test_kein_zweiter_offener_auftrag(cfg):
    n = netz(cfg)
    erst = n.auftrag(abteilung="C", titel="X", art="strategie",
                     bezug_symbol="EURUSD", bezug_schluessel="k")
    zweit = n.auftrag(abteilung="C", titel="X", art="strategie",
                      bezug_symbol="EURUSD", bezug_schluessel="k")
    assert erst and zweit is None
    assert len(n.db.intel_auftraege(10)) == 1
    # Auch ein abgeschlossener Auftrag wird sieben Tage lang nicht wiederholt.
    n.db.intel_status_setzen(erst, "bestätigt", "belegt")
    assert n.auftrag(abteilung="C", titel="X", art="strategie",
                     bezug_symbol="EURUSD", bezug_schluessel="k") is None


def test_lernschleife_bestaetigt_und_widerlegt(cfg):
    n = netz(cfg)
    kennung = n.auftrag(abteilung="C", titel="Ablehnungsgrund prüfen", art="strategie",
                        bezug_symbol="EURUSD", bezug_schluessel="s1",
                        problem="p", hypothese="h", quellen=["https://a.example/x"])
    assert kennung
    time.sleep(1.05)  # damit die neue Validierung sicher nach dem Auftrag liegt
    n.db.validierung_speichern("EURUSD", "ema_cross", "s1", {}, "abgelehnt", "Test",
                               {"gruende": ["Zu wenig Trades"]}, lauf="L1")
    ergebnis = n.lernschleife()

    assert ergebnis["bestaetigt"] == 1
    assert n.db.intel_auftrag(kennung)["status"] == "bestätigt"

    kennung2 = n.auftrag(abteilung="C", titel="Zweiter Kandidat", art="strategie",
                         bezug_symbol="EURUSD", bezug_schluessel="s2",
                         problem="p", hypothese="h")
    time.sleep(1.05)
    n.db.validierung_speichern("EURUSD", "ema_cross", "s2", {}, "bestanden", "Test",
                               {"gruende": []}, lauf="L1")
    n.lernschleife()
    assert n.db.intel_auftrag(kennung2)["status"] == "widerlegt"


def test_lernschleife_marktauftrag_nutzt_kerzen(cfg):
    n = netz(cfg)
    kennung = n.auftrag(abteilung="D", titel="Meldungslage", art="markt",
                        bezug_symbol="EURUSD", kurs_bei_erstellung=100.0,
                        atr_bei_erstellung=0.5, problem="p", hypothese="h")
    ts = pd.date_range(pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=15),
                       periods=100, freq="15min")
    close = [100 + i * 0.02 for i in range(100)]
    df = pd.DataFrame({"ts": ts, "open": close, "close": close,
                       "high": [c + 0.1 for c in close], "low": [c - 0.1 for c in close],
                       "volume": 1.0})
    n.db.kerzen_speichern("EURUSD", "M15", df.to_dict("records"))

    ergebnis = n.lernschleife()
    assert ergebnis["bestaetigt"] == 1
    assert n.db.intel_auftrag(kennung)["status"] == "bestätigt"


def test_quellenstatistik_kommt_aus_den_artikeln(cfg):
    n = netz(cfg)
    aid = artikel(n.db, "EZB eins", "https://a.example/q1")
    n.db.artikel_inhalt_speichern(aid, "Volltext der Meldung " * 20)
    n.quellen_auffrischen()
    zeile = n.db.intel_quellen()[0]
    assert zeile["quelle"] == "Testquelle"
    assert zeile["artikel"] == 1 and zeile["analysiert"] == 1
    assert zeile["qualitaet"] == 0.8
    # Idempotent: ein zweiter Abgleich zählt nicht doppelt
    n.quellen_auffrischen()
    assert n.db.intel_quellen()[0]["artikel"] == 1


def test_weiterleitung_status_und_abteilung_setzbar(cfg):
    n = netz(cfg)
    kennung = n.weiterleiten("Labor", "Neue Strategieidee", {"artikel": 1})
    assert weiterleitung_aendern(n.db, kennung, "Risikomanagement", "übernommen") is True
    zeile = next(w for w in n.db.intel_weiterleitungen(10) if w["kennung"] == kennung)
    assert (zeile["an"], zeile["status"]) == ("Risikomanagement", "übernommen")

    # Unbekannte Werte werden abgelehnt und ändern nichts.
    with pytest.raises(ValueError):
        weiterleitung_aendern(n.db, kennung, "Vorstand", "neu")
    with pytest.raises(ValueError):
        weiterleitung_aendern(n.db, kennung, "Labor", "erledigt; DROP TABLE intel_weiterleitungen")
    assert weiterleitung_aendern(n.db, "WL-19990101-9999", "Labor", "neu") is False
    unveraendert = next(w for w in n.db.intel_weiterleitungen(10) if w["kennung"] == kennung)
    assert (unveraendert["an"], unveraendert["status"]) == ("Risikomanagement", "übernommen")


def test_auftrag_status_und_ergebnis_setzbar(cfg):
    n = netz(cfg)
    kennung = n.auftrag(abteilung="C", titel="Signal prüfen", art="strategie",
                        bezug_symbol="EURUSD", bezug_schluessel="a1")
    assert kennung
    assert auftrag_aendern(n.db, kennung, "widerlegt", "Die Validierung zeigt keinen Effekt.") is True
    auftrag = n.db.intel_auftrag(kennung)
    assert auftrag["status"] == "widerlegt"
    assert "keinen Effekt" in auftrag["ergebnis"]

    # Abschluss ohne Ergebnis wird abgelehnt, offen darf leer sein.
    with pytest.raises(ValueError):
        auftrag_aendern(n.db, kennung, "bestätigt", "   ")
    with pytest.raises(ValueError):
        auftrag_aendern(n.db, kennung, "fertig", "x")
    assert n.db.intel_auftrag(kennung)["status"] == "widerlegt"
    assert auftrag_aendern(n.db, kennung, "offen", "") is True
    assert n.db.intel_auftrag(kennung)["status"] == "offen"
    assert n.db.intel_auftrag(kennung)["ergebnis"] == ""
    assert auftrag_aendern(n.db, "RS-19990101-9999", "offen", "") is False


def test_lage_liefert_bearbeitungsoptionen(cfg):
    bericht = lage(Facts(cfg.db_pfad))
    assert {"neu", "übernommen", "erledigt"} <= set(bericht["weiterleitung_status"])
    assert {"offen", "bestätigt", "widerlegt", "verworfen"} <= set(bericht["auftrag_status"])
    assert "Labor" in bericht["abteilungen"]
    assert "Risikomanagement" in bericht["abteilungen"]


def test_bericht_enthaelt_intel_block(cfg):
    db = Facts(cfg.db_pfad)
    bericht = baue_bericht(cfg, db)
    assert {"statistik", "auftraege", "weiterleitungen", "quellen",
            "abteilungen", "weiterleitung_status", "auftrag_status"} <= set(bericht["intel"])
    assert bericht["intel"]["statistik"]["auftraege"] == 0
