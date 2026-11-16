from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from orakel.db import Facts
from orakel.nexus.bewertung import (_aussage_aus_text, claims_auffrischen,
                                    extrahiere_aussage, quellen_reputation,
                                    wert_und_einheit)
from orakel.nexus.dedup import titel_hash
from orakel.nexus.quellen import Quelle

ZEIT = "2026-11-10T05:00:00+00:00"


def quelle(qid: str, name: str, host: str = "a.example", gewicht: float = 0.8) -> Quelle:
    return Quelle(
        id=qid, name=name, typ="rss", url=f"https://{host}/feed.xml",
        land="DE", sprache="de", thema="test", gewicht=gewicht,
    )


def meldung(db: Facts, key: str, q: Quelle, titel: str, url: str,
            artikel_id: int | None = None, original: bool = True) -> int:
    aid = artikel_id or db.artikel_speichern(
        q.name, "rss", titel, url, None, titel, 0.8, [], titel_hash(titel))
    assert aid
    assert db.nexus_meldung_speichern(
        key, int(aid), key, "0" * 16, "de", 0.9, "test", original,
        q.id, titel, titel, url, ZEIT,
    )
    return int(aid)


def test_aussage_erkennt_richtung_wert_und_subjekt():
    a = _aussage_aus_text("EZB hebt den Leitzins auf 4,5 Prozent")
    assert a is not None
    assert a["thema"] == "makro"
    assert a["subjekt"] == "ezb"
    assert a["metrik"] == "leitzins"
    assert a["richtung"] == "steigt"
    assert a["wert"] == 4.5
    assert a["einheit"] == "%"
    assert a["negiert"] is False


def test_laesst_ist_unveraendert_und_kein_subjektwort():
    a = _aussage_aus_text("EZB laesst den Leitzins unverändert")
    assert a is not None
    assert a["richtung"] == "unveraendert"
    assert a["subjekt"] == "ezb"


def test_verneinung_wird_getrennt_von_der_richtung_erkannt():
    a = _aussage_aus_text("EZB senkt den Leitzins nicht")
    assert a is not None
    assert a["richtung"] == "sinkt"
    assert a["negiert"] is True


def test_ohne_pruefbares_muster_keine_kernaussage():
    assert _aussage_aus_text(
        "Federal Reserve Board issues enforcement actions with former employee"
    ) is None
    assert _aussage_aus_text("Die EZB veröffentlicht einen Blogbeitrag") is None


@pytest.mark.parametrize("text", [
    "Not for distribution, directly or indirectly, in or into the United States",
    "Minutes of the Meeting of the Court of Directors held on 17 September 2026",
    "Senate advances bill to speed up projects from gas pipelines to clean energy",
])
def test_floskel_und_passiv_werden_nicht_zur_kernaussage(text):
    assert _aussage_aus_text(text) is None


def test_frage_ist_keine_kernaussage():
    assert _aussage_aus_text("How does it affect me if share prices fall?") is None
    assert _aussage_aus_text("What has gone wrong at Virgin Media O2?") is None


def test_prozentzahl_und_monat_verschwinden_aus_dem_subjekt():
    a = _aussage_aus_text("Bank Rate maintained at 3.75% - July 2026 Monetary Policy Summary")
    b = _aussage_aus_text("Bank Rate maintained at 3.75% - September 2026 Monetary Policy Summary")
    assert a is not None and b is not None
    assert "3.75" not in a["subjekt"]
    assert "july" not in a["subjekt"]
    assert a["subjekt"] == b["subjekt"]
    assert a["zeitraum"] == "2026-07"
    assert b["zeitraum"] == "2026-09"


def test_kernaussage_erkennt_zeitraum_bedingung_und_sicherheit():
    a = _aussage_aus_text(
        "EZB senkt den Leitzins im Juli 2026, falls die Inflation sinkt"
    )
    assert a is not None
    assert a["zeitraum"] == "2026-07"
    assert a["bedingung"] == "falls die inflation sinkt"
    assert a["sicherheit"] == 0.8
    assert a["subjekt"] == "ezb"


def test_relative_zeitangabe_wird_nicht_geraten():
    a = _aussage_aus_text("EZB senkt den Leitzins heute")
    assert a is not None
    assert a["zeitraum"] == ""
    assert a["bedingung"] == ""
    assert a["sicherheit"] == 0.9


def test_extrahiere_aussage_nutzt_quelle_und_kopie_status(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    q = quelle("a", "Quelle A")
    aid = meldung(db, "m1", q, "EZB hebt den Leitzins auf 4,5 Prozent",
                  "https://a.example/1")
    a = extrahiere_aussage(db.nexus_meldung("m1"), {"a": q})
    assert a is not None
    assert a.artikel_id == aid
    assert a.host == "a.example"
    assert a.ist_kopie is False
    assert a.claim_key == "makro|ezb|leitzins"

    meldung(db, "m2", q, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1", artikel_id=aid, original=False)
    kopie = extrahiere_aussage(db.nexus_meldung("m2"), {"a": q})
    assert kopie is not None
    assert kopie.ist_kopie is True


def test_quellenreputation_kommt_aus_ergebnissen_und_bleibt_sonst_vorlaeufig(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    q = quelle("a", "Quelle A", gewicht=0.8)
    meldung(db, "m-a", q, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1")
    db.intel_quelle_pflegen("Quelle A", bestaetigt=3, widerlegt=1)

    rep = quellen_reputation(db, [q])["a"]
    assert rep["artikel"] == 1
    assert rep["bestaetigt"] == 3
    assert rep["widerlegt"] == 1
    assert rep["vertrauen"] == "belegt"
    assert 0.7 < rep["reputation"] < 0.9

    ohne = quellen_reputation(db, [quelle("b", "Quelle B", gewicht=0.8)])["b"]
    assert ohne["vertrauen"] == "vorläufig"
    assert ohne["reputation"] == 0.8


def test_zwei_unabhaengige_quellen_bestaetigen_eine_kernaussage(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB erhöht den Leitzins auf 4,5 Prozent",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["meldungen"] == 2
    assert ergebnis["kernaussagen"] == 1
    assert ergebnis["belege"] == 2
    assert ergebnis["widersprueche"] == 0
    assert ergebnis["nach_status"] == {"bestätigt": 1}

    claim = db.nexus_claims(5)[0]
    assert claim["quellen"] == 2
    assert claim["belege"] == 2
    assert claim["status"] == "bestätigt"
    assert claim["bestaetigungsgrad"] >= 0.7
    assert {r["quelle_id"] for r in db.nexus_quellen_reputation()} == {"a", "b"}


def test_kopie_ist_beleg_aber_keine_unabhaengige_bestaetigung(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a = quelle("a", "Quelle A")
    aid = meldung(db, "m-a", a, "EZB hebt den Leitzins auf 4,5 Prozent",
                  "https://a.example/1")
    meldung(db, "m-kopie", a, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1", artikel_id=aid, original=False)

    ergebnis = claims_auffrischen(db, [a])
    # Die Kopie bleibt als Beleg sichtbar, zählt aber nicht als zweite Quelle.
    assert ergebnis["belege"] == 2
    claim = db.nexus_claims(5)[0]
    assert claim["quellen"] == 1
    assert claim["status"] == "unbestätigt"


def test_bestehende_datenbank_erhaelt_strukturierte_spalten(tmp_path):
    pfad = tmp_path / "alt.db"
    with sqlite3.connect(pfad) as c:
        c.executescript("""
        CREATE TABLE nexus_claims (
            id INTEGER PRIMARY KEY, claim_key TEXT NOT NULL UNIQUE,
            kernaussage TEXT NOT NULL, thema TEXT NOT NULL, subjekt TEXT NOT NULL,
            metrik TEXT NOT NULL DEFAULT '', quellen INTEGER NOT NULL DEFAULT 0,
            belege INTEGER NOT NULL DEFAULT 0, widersprueche INTEGER NOT NULL DEFAULT 0,
            bestaetigungsgrad REAL NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'unbestätigt',
            erstmals TEXT NOT NULL, aktualisiert TEXT NOT NULL
        );
        CREATE TABLE nexus_claim_quellen (
            id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL,
            meldung_key TEXT NOT NULL, artikel_id INTEGER NOT NULL,
            quelle_id TEXT NOT NULL, host TEXT NOT NULL, aussage TEXT NOT NULL,
            richtung TEXT NOT NULL, wert REAL, einheit TEXT NOT NULL DEFAULT '',
            negiert INTEGER NOT NULL DEFAULT 0, ist_kopie INTEGER NOT NULL DEFAULT 0,
            reputation REAL NOT NULL DEFAULT 0.5, erstellt TEXT NOT NULL,
            UNIQUE(claim_id, meldung_key)
        );
        CREATE TABLE nexus_widersprueche (
            id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL,
            meldung_a TEXT NOT NULL, meldung_b TEXT NOT NULL,
            quelle_a TEXT NOT NULL, quelle_b TEXT NOT NULL,
            grund TEXT NOT NULL, sicherheit REAL NOT NULL,
            erstellt TEXT NOT NULL
        );
        """)
    db = Facts(pfad)
    with db.conn() as c:
        for tabelle in ("nexus_claims", "nexus_claim_quellen"):
            spalten = {r["name"] for r in c.execute(f"PRAGMA table_info({tabelle})")}
            assert {"zeitraum", "bedingung", "sicherheit"} <= spalten
        spalten = {r["name"] for r in c.execute(
            "PRAGMA table_info(nexus_widersprueche)")}
        assert {"wert_a_bp", "wert_b_bp"} <= spalten


def test_gegenlaeufige_richtungen_werden_als_widerspruch_markiert(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins auf 4,0 Prozent",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 1
    assert ergebnis["nach_status"] == {"widersprüchlich": 1}
    claim = db.nexus_claims(5)[0]
    assert claim["status"] == "widersprüchlich"
    assert claim["quellen"] == 2
    assert claim["widersprueche"] == 1
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Richtung steigt gegen sinkt"
    assert wid["quelle_a"] == "a.example"
    assert wid["quelle_b"] == "b.example"
    assert wid["wert_a_bp"] == 450.0
    assert wid["wert_b_bp"] == 400.0


def test_gleiche_metrik_mit_verschiedenen_zeitraeumen_ist_kein_widerspruch(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins im September 2026 auf 4,0 Prozent",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["kernaussagen"] == 2
    assert ergebnis["widersprueche"] == 0
    assert {c["zeitraum"] for c in db.nexus_claims(5)} == {"2026-07", "2026-09"}
    assert all("zeitraum=" in c["claim_key"] for c in db.nexus_claims(5))


def test_unterschiedliche_bedingungen_sind_kein_harter_widerspruch(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB senkt den Leitzins, falls die Inflation sinkt",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins, falls das Wachstum sinkt",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["kernaussagen"] == 1
    assert ergebnis["widersprueche"] == 0
    claim = db.nexus_claims(5)[0]
    assert claim["bedingung"] == "falls die inflation sinkt"
    belege = db.nexus_claim_quellen_fuer([claim["id"]])
    assert {b["bedingung"] for b in belege} == {
        "falls die inflation sinkt", "falls das wachstum sinkt",
    }


def test_unbekannter_zeitraum_wird_nicht_erfunden(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins heute", "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins heute", "https://b.example/1")

    claims_auffrischen(db, [a, b])
    claim = db.nexus_claims(5)[0]
    assert claim["zeitraum"] == ""
    assert "zeitraum=" not in claim["claim_key"]
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Richtung steigt gegen sinkt"


def test_unbekannter_zeitraum_gilt_nicht_als_gleicher_zeitraum(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026", "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins", "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["kernaussagen"] == 2
    assert ergebnis["widersprueche"] == 0
    assert {c["zeitraum"] for c in db.nexus_claims(5)} == {"", "2026-07"}


def test_nicht_umrechenbare_einheiten_erzeugen_keinen_zahlenkonflikt(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Milliarden",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 0
    claim = db.nexus_claims(5)[0]
    belege = db.nexus_claim_quellen_fuer([claim["id"]])
    assert {b["einheit"] for b in belege} == {"%", "mrd"}


def test_prozent_und_basispunkte_sind_gleichwertig(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 450 Basispunkte",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 0
    belege = db.nexus_claim_quellen_fuer([db.nexus_claims(5)[0]["id"]])
    assert {b["einheit"] for b in belege} == {"%", "bp"}
    assert {b["wert"] for b in belege} == {4.5, 450.0}


def test_prozent_und_basispunkte_konflikt_bei_abweichung(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 440 Basispunkte",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 1
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Zahlenwert 4.5 % (450 bp) gegen 440 bp"
    assert wid["sicherheit"] == 0.9
    assert wid["wert_a_bp"] == 450.0
    assert wid["wert_b_bp"] == 440.0


def test_bps_wird_als_basispunkt_erkannt():
    a = _aussage_aus_text("EZB hebt den Leitzins auf 450 bps")
    assert a is not None
    assert a["wert"] == 450.0
    assert a["einheit"] == "bp"


@pytest.mark.parametrize("text", [
    "EZB hebt den Leitzins auf 4,5 pp",
    "EZB hebt den Leitzins auf 4,5pp",
    "EZB hebt den Leitzins auf 4,5 Prozentpunkte",
])
def test_prozentpunkte_werden_als_pp_erkannt(text):
    a = _aussage_aus_text(text)
    assert a is not None
    assert a["wert"] == 4.5
    assert a["einheit"] == "pp"


@pytest.mark.parametrize("text", [
    "The Federal Reserve cuts rates by 0.25 percentage points",
    "The Federal Reserve cuts rates by 0.25 percentage point",
])
def test_englische_percentage_points_werden_als_pp_erkannt(text):
    a = _aussage_aus_text(text)
    assert a is not None
    assert a["wert"] == 0.25
    assert a["einheit"] == "pp"


@pytest.mark.parametrize("text", [
    "The Federal Reserve cuts rates by 0.25 Percentage Points",
    "The Federal Reserve cuts rates by 0.25 PERCENTAGE POINT",
    "The Federal Reserve cuts rates by 0.25 percentage-points",
    "The Federal Reserve cuts rates by 0.25 PERCENTAGE-POINT",
])
def test_englische_percentage_points_schreibvarianten_sind_pp(text):
    assert wert_und_einheit(text) == (0.25, "pp")


@pytest.mark.parametrize("text", [
    "Die Gruppe meldet 5 Apps",
    "Die Kipppunkte liegen bei 5 Kipppunkten",
    "Die Grappa-Flasche kostet 5 Grappas",
])
def test_pp_in_fremdwoertern_ist_keine_einheit(text):
    assert wert_und_einheit(text) == (None, "")


def test_prozentzeichen_in_fremdwort_ist_keine_einheit():
    assert wert_und_einheit("Die Gruppe meldet 5 %Zahl") == (None, "")


def test_pp_fremdwoerter_in_echten_rss_schlagzeilen_sind_keine_einheit():
    """Reale RSS-Titel mit pp-Fremdwörtern dürfen keine pp-Einheit ergeben."""
    pfad = Path(__file__).parent / "fixtures" / "nexus_pp_fremdwoerter_rss.json"
    daten = json.loads(pfad.read_text(encoding="utf-8"))

    assert daten["version"] == 1
    assert daten["abgerufen"] == "2026-11-16"
    meldungen = daten["meldungen"]
    assert len(meldungen) == 7
    assert len({m["id"] for m in meldungen}) == len(meldungen)

    for eintrag in meldungen:
        titel = eintrag["titel"]
        assert eintrag["fremdwort"].casefold() in titel.casefold()
        aussage = _aussage_aus_text(titel)
        assert aussage is None or aussage["einheit"] != "pp"


def test_prozentzeichen_wird_erkannt():
    a = _aussage_aus_text("EZB hebt den Leitzins auf 4,5 %")
    assert a is not None
    assert a["wert"] == 4.5
    assert a["einheit"] == "%"


def test_prozentpunkte_und_prozent_sind_gleichwertig(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozentpunkte",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozent",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 0
    belege = db.nexus_claim_quellen_fuer([db.nexus_claims(5)[0]["id"]])
    assert {b["einheit"] for b in belege} == {"pp", "%"}
    assert {b["wert"] for b in belege} == {4.5}


def test_prozentpunkte_und_basispunkte_sind_gleichwertig(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozentpunkte",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 450 Basispunkte",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 0
    belege = db.nexus_claim_quellen_fuer([db.nexus_claims(5)[0]["id"]])
    assert {b["einheit"] for b in belege} == {"pp", "bp"}
    assert {b["wert"] for b in belege} == {4.5, 450.0}


def test_prozentpunkte_und_basispunkte_konflikt_bei_abweichung(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozentpunkte",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 440 Basispunkte",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 1
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Zahlenwert 4.5 pp (450 bp) gegen 440 bp"
    assert wid["sicherheit"] == 0.9
    assert wid["wert_a_bp"] == 450.0
    assert wid["wert_b_bp"] == 440.0


def test_zahlenkonflikt_bei_gleicher_richtung_und_gleichem_zeitraum(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins im Juli 2026 auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB hebt den Leitzins im Juli 2026 auf 4,0 Prozent",
            "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 1
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Zahlenwert 4.5 % gegen 4 %"
    assert wid["sicherheit"] == 0.9
    assert wid["wert_a_bp"] == 450.0
    assert wid["wert_b_bp"] == 400.0


def test_widerspruchssicherheit_nutzt_die_schwaechere_kernaussage(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB 4,5 Prozent", "https://a.example/1")
    meldung(db, "m-b", b, "EZB 4,0 Prozent", "https://b.example/1")

    claims_auffrischen(db, [a, b])
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Zahlenwert 4.5 % gegen 4 %"
    assert wid["sicherheit"] == 0.6


def test_bedingte_gegen_unbedingte_aussage_ist_ein_pruefbedarf(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB senkt den Leitzins, falls die Inflation sinkt",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins", "https://b.example/1")

    ergebnis = claims_auffrischen(db, [a, b])
    assert ergebnis["widersprueche"] == 1
    claim = db.nexus_claims(5)[0]
    assert claim["bedingung"] == "falls die inflation sinkt"
    assert claim["sicherheit"] == 0.8
    beleg = db.nexus_claim_quellen_fuer([claim["id"]])[0]
    assert beleg["bedingung"] == "falls die inflation sinkt"
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Bedingung gegen unbedingte Aussage"
    assert wid["sicherheit"] == 0.5


def test_verneinung_gegen_behauptung_ist_ein_widerspruch(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB senkt den Leitzins", "https://a.example/1")
    meldung(db, "m-b", b, "EZB senkt den Leitzins nicht", "https://b.example/1")

    claims_auffrischen(db, [a, b])
    wid = db.nexus_widersprueche(5)[0]
    assert wid["grund"] == "Verneinung gegen Behauptung"
    assert wid["sicherheit"] == 0.6


def test_ohne_kernaussage_bleiben_claims_leer_aber_reputation_sichtbar(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a = quelle("a", "Quelle A")
    meldung(db, "m-a", a, "Federal Reserve issues enforcement actions",
            "https://a.example/1")

    ergebnis = claims_auffrischen(db, [a])
    assert ergebnis["meldungen"] == 1
    assert ergebnis["meldungen_mit_claim"] == 0
    assert ergebnis["kernaussagen"] == 0
    assert ergebnis["ohne_kernaussage"] == 1
    assert db.nexus_claims(5) == []
    assert len(db.nexus_quellen_reputation()) == 1


def test_bewertung_ist_idempotent(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a, b = quelle("a", "Quelle A", "a.example"), quelle("b", "Quelle B", "b.example")
    meldung(db, "m-a", a, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1")
    meldung(db, "m-b", b, "EZB erhöht den Leitzins auf 4,5 Prozent",
            "https://b.example/1")

    erster = claims_auffrischen(db, [a, b])
    erste_statistik = db.nexus_claim_statistik()
    erster_claim = db.nexus_claims(5)[0]
    zweiter = claims_auffrischen(db, [a, b])
    zweite_statistik = db.nexus_claim_statistik()
    zweiter_claim = db.nexus_claims(5)[0]

    assert erster == zweiter
    assert erste_statistik == zweite_statistik
    assert {k: erster_claim[k] for k in ("claim_key", "status", "quellen", "belege")} == \
           {k: zweiter_claim[k] for k in ("claim_key", "status", "quellen", "belege")}
    assert len(db.nexus_claims(10)) == 1


def test_leerer_rebuild_entfernt_claims_ohne_quellenprior_zu_verlieren(tmp_path):
    db = Facts(tmp_path / "orakel.db")
    a = quelle("a", "Quelle A")
    meldung(db, "m-a", a, "EZB hebt den Leitzins auf 4,5 Prozent",
            "https://a.example/1")
    claims_auffrischen(db, [a])
    assert db.nexus_claims(5)

    ergebnis = claims_auffrischen(db, [])
    assert ergebnis["kernaussagen"] == 1  # Meldung bleibt, Quelle fällt auf unbekannt zurück
    assert db.nexus_quellen_reputation()

    # Ein wirklich leerer Bestand räumt die Tabellen, ohne zu erfinden.
    db2 = Facts(tmp_path / "leer.db")
    leer = claims_auffrischen(db2, [a])
    assert leer["kernaussagen"] == 0
    assert db2.nexus_claims(5) == []
    assert db2.nexus_claim_statistik()["gesamt"] == 0
