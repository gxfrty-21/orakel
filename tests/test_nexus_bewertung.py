from __future__ import annotations

import pytest

from orakel.db import Facts
from orakel.nexus.bewertung import (_aussage_aus_text, claims_auffrischen,
                                    extrahiere_aussage, quellen_reputation)
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
