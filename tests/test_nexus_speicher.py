from __future__ import annotations

from pathlib import Path

from orakel.db import Facts
from orakel.nexus.dedup import titel_hash
from orakel.nexus.feeds import Meldung
from orakel.nexus.quellen import Quelle
from orakel.nexus.speicher import MeldungSpeicher

QUELLE = Quelle(id="test", name="Testquelle", typ="rss",
                url="https://example.com/feed/", land="DE", sprache="de",
                thema="test", gewicht=0.8)


def _meldung(titel: str, url: str, zusammenfassung: str = "",
             sprache: str = "de") -> Meldung:
    return Meldung(quelle_id=QUELLE.id, titel=titel, url=url,
                   veroeffentlicht=None, zusammenfassung=zusammenfassung,
                   sprache=sprache, land="DE")


def test_neue_meldung_landet_in_artikel_und_nexus(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    ergebnis = MeldungSpeicher(db).speichere(
        _meldung("EZB lässt Leitzins unverändert",
                 "https://example.com/a",
                 "Die EZB lässt den Leitzins unverändert und warnt vor Inflation."),
        QUELLE,
    )

    assert ergebnis.status == "neu"
    assert ergebnis.artikel_id
    artikel = db.artikel()
    assert len(artikel) == 1
    assert artikel[0]["titel"] == "EZB lässt Leitzins unverändert"
    assert artikel[0]["quelle"] == "Testquelle"
    assert artikel[0]["qualitaet"] == 0.8

    zeilen = db.nexus_meldungen()
    assert len(zeilen) == 1
    assert zeilen[0]["artikel_id"] == ergebnis.artikel_id
    assert zeilen[0]["ist_original"] == 1
    assert "EZB" in zeilen[0]["zusammenfassung"]
    assert zeilen[0]["sprache"] == "de"
    assert len(zeilen[0]["simhash"]) == 16

    statistik = db.nexus_statistik()
    assert statistik["gesamt"] == 1
    assert statistik["originale"] == 1
    assert statistik["dubletten"] == 0


def test_dieselbe_meldung_wird_nicht_doppelt_gespeichert(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    speicher = MeldungSpeicher(db)
    meldung = _meldung("EZB lässt Leitzins unverändert",
                       "https://example.com/a", "Kurzer Text.")
    assert speicher.speichere(meldung, QUELLE).status == "neu"
    assert speicher.speichere(meldung, QUELLE).status == "wiederholung"

    assert len(db.artikel()) == 1
    assert len(db.nexus_meldungen()) == 1
    assert db.nexus_statistik()["dubletten"] == 0


def test_kopie_wird_verlinkt_und_nicht_als_zweiter_artikel_gespeichert(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    speicher = MeldungSpeicher(db)
    original = _meldung(
        "EZB lässt Leitzins unverändert",
        "https://example.com/a",
        "Die Europäische Zentralbank lässt den Leitzins unverändert "
        "und warnt vor Inflation.",
    )
    kopie = _meldung(
        "EZB lässt den Leitzins unverändert",
        "https://example.com/b",
        "Die Europäische Zentralbank lässt den Leitzins unverändert "
        "und warnt vor der Inflation.",
    )

    neu = speicher.speichere(original, QUELLE)
    dublette = speicher.speichere(kopie, QUELLE)

    assert neu.status == "neu"
    assert dublette.status == "dublette"
    assert dublette.artikel_id == neu.artikel_id
    assert dublette.cluster_id == neu.cluster_id
    assert len(db.artikel()) == 1

    zeilen = db.nexus_meldungen()
    assert len(zeilen) == 2
    assert sum(1 for z in zeilen if z["ist_original"] == 1) == 1
    assert sum(1 for z in zeilen if z["ist_original"] == 0) == 1
    statistik = db.nexus_statistik()
    assert statistik["dubletten"] == 1
    assert statistik["dublettenquote"] == 0.5


def test_verschiedene_meldungen_bleiben_getrennt(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    speicher = MeldungSpeicher(db)
    a = _meldung("EZB lässt Leitzins unverändert", "https://example.com/a",
                 "Die Europäische Zentralbank lässt den Leitzins unverändert.")
    b = _meldung("Goldpreis steigt deutlich", "https://example.com/b",
                 "Der Goldpreis steigt nach schwachen US-Arbeitsmarktdaten deutlich.")

    assert speicher.speichere(a, QUELLE).status == "neu"
    assert speicher.speichere(b, QUELLE).status == "neu"
    assert len(db.artikel()) == 2
    assert db.nexus_statistik()["dubletten"] == 0


def test_index_erkennt_kopien_auch_nach_neustart(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    original = _meldung(
        "EZB lässt Leitzins unverändert",
        "https://example.com/a",
        "Die Europäische Zentralbank lässt den Leitzins unverändert "
        "und warnt vor Inflation.",
    )
    MeldungSpeicher(db).speichere(original, QUELLE)

    kopie = _meldung(
        "EZB lässt den Leitzins unverändert",
        "https://example.com/b",
        "Die Europäische Zentralbank lässt den Leitzins unverändert "
        "und warnt vor der Inflation.",
    )
    ergebnis = MeldungSpeicher(db).speichere(kopie, QUELLE)
    assert ergebnis.status == "dublette"
    assert len(db.artikel()) == 1


def test_sprache_wird_aus_dem_text_erkannt(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    speicher = MeldungSpeicher(db)
    deutsch = _meldung(
        "EZB lässt Leitzins unverändert",
        "https://example.com/de",
        "Die EZB lässt den Leitzins unverändert. Die Inflation ist nicht das einzige Thema.",
    )
    englisch = _meldung(
        "ECB leaves rates unchanged",
        "https://example.com/en",
        "The ECB left the interest rate unchanged. Inflation is not the only issue.",
    )

    assert speicher.speichere(deutsch, QUELLE).sprache == "de"
    assert speicher.speichere(englisch, QUELLE).sprache == "en"


def test_alte_artikel_werden_als_dublette_verlinkt(tmp_path: Path):
    db = Facts(tmp_path / "orakel.db")
    titel = "EZB lässt Leitzins unverändert"
    url = "https://example.com/alt"
    alt_id = db.artikel_speichern(
        "Alter Spider", "rss", titel, url, None, "Alter Text.", 0.7, [],
        titel_hash(titel),
    )
    assert alt_id

    neu = MeldungSpeicher(db).speichere(
        _meldung(titel, url, "Neuer Text."), QUELLE)
    assert neu.status == "dublette"
    assert neu.artikel_id == alt_id
    assert len(db.artikel()) == 1
    assert db.nexus_statistik()["dubletten"] == 1
