from __future__ import annotations

import pytest

from orakel.nexus.quellen import Quelle, lade_register, pruefe_register, statistik


def _quelle(**abweichung) -> Quelle:
    basis = {
        "id": "test", "name": "Test", "typ": "rss",
        "url": "https://example.com/feed.xml", "land": "DE",
        "sprache": "de", "thema": "nachrichten",
    }
    basis.update(abweichung)
    return Quelle(**basis)


def test_register_hat_mindestens_40_quellen():
    quellen = lade_register()
    assert len(quellen) >= 40
    assert len({q.id for q in quellen}) == len(quellen)


def test_register_deckt_mehrere_sprachen_laender_und_themen_ab():
    quellen = lade_register()
    assert {"de", "en", "fr", "es", "it"} <= {q.sprache for q in quellen}
    assert {"DE", "US", "GB", "FR", "IT", "ES", "CN"} <= {q.land for q in quellen}
    assert {"notenbank", "markt", "wissenschaft", "technologie"} <= {q.thema for q in quellen}


def test_register_enthaelt_notenbanken_und_hacker_news():
    ids = {q.id for q in lade_register()}
    assert {"ecb-press", "fed-press", "boe-news", "boj-news", "hn-top"} <= ids


def test_alle_quellen_haben_absolute_https_urls():
    for q in lade_register():
        assert q.url.startswith("https://"), q.id
        assert q.gewicht > 0 and q.intervall_minuten >= 5, q.id


def test_doppelte_id_wird_erkannt():
    fehler = pruefe_register([_quelle(id="a"), _quelle(id="a")])
    assert any("doppelte id" in f for f in fehler)


def test_unbekannter_typ_wird_erkannt():
    fehler = pruefe_register([_quelle(typ="email")])
    assert any("unbekannter Typ" in f for f in fehler)


def test_ungueltige_url_wird_erkannt():
    fehler = pruefe_register([_quelle(url="ftp://example.com/feed")])
    assert any("ungültige URL" in f for f in fehler)


def test_sprache_land_gewicht_und_intervall_werden_geprueft():
    fehler = pruefe_register([
        _quelle(id="a", sprache="deutsch"),
        _quelle(id="b", land="Deutschland"),
        _quelle(id="c", gewicht=1.5),
        _quelle(id="d", intervall_minuten=1),
    ])
    assert len(fehler) == 4


def test_leeres_register_wird_gemeldet():
    assert pruefe_register([]) == ["Register ist leer"]


def test_fehlendes_pflichtfeld_nennt_die_quelle(tmp_path):
    pfad = tmp_path / "register.toml"
    pfad.write_text('[[quelle]]\nid = "x"\nname = "X"\ntyp = "rss"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="Pflichtfeld"):
        lade_register(pfad)


def test_statistik_summiert_korrekt():
    daten = statistik(lade_register())
    assert daten["gesamt"] == sum(daten["nach_typ"].values())
    assert daten["gesamt"] == sum(daten["nach_sprache"].values())
    assert daten["nach_typ"]["rss"] >= 40
    assert daten["nach_typ"]["json_api"] == 1
