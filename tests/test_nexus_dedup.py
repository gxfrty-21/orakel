from __future__ import annotations

from orakel.nexus.dedup import (DedupIndex, hamming, jaccard, shingles, simhash,
                                titel_hash)

A = ("Die Europäische Zentralbank lässt den Leitzins unverändert "
     "und warnt vor Inflation.")
B = ("Die Europäische Zentralbank lässt den Leitzins unverändert "
     "und warnt vor der Inflation.")
C = "Goldpreis steigt nach schwachen US-Arbeitsmarktdaten deutlich."


def test_gleicher_text_hat_gleichen_simhash():
    assert simhash(A) == simhash(A)


def test_leicht_veraenderter_text_liegt_nahe():
    assert hamming(simhash(A), simhash(B)) <= 10
    assert jaccard(shingles(A), shingles(B)) >= 0.8


def test_fremder_text_liegt_weit_weg():
    assert hamming(simhash(A), simhash(C)) > 10
    assert jaccard(shingles(A), shingles(C)) < 0.2


def test_index_findet_die_kopie():
    index = DedupIndex(schwelle=10)
    index.hinzufuegen(simhash(A), "cluster-a", 7, "key-a", shingles(A))
    treffer = index.finde(simhash(B), shingles(B))
    assert treffer is not None
    assert treffer.cluster_id == "cluster-a"
    assert treffer.artikel_id == 7


def test_index_findet_keine_kopie_bei_fremdem_text():
    index = DedupIndex(schwelle=10)
    index.hinzufuegen(simhash(A), "cluster-a", 7, "key-a", shingles(A))
    assert index.finde(simhash(C), shingles(C)) is None


def test_index_ist_deterministisch_und_verhindert_doppelte_cluster():
    index = DedupIndex()
    index.hinzufuegen(123, "c1", 1, "k1", shingles(A))
    index.hinzufuegen(123, "c1", 1, "k1", shingles(A))
    assert len(index) == 1
    assert index.finde(123, shingles(A)).cluster_id == "c1"


def test_titel_hash_ignoriert_grossschreibung_und_satzzeichen():
    assert titel_hash("EZB lässt Leitzins unverändert!") == \
        titel_hash("ezb lässt leitzins unverändert")
    assert titel_hash("EZB lässt Leitzins unverändert") != \
        titel_hash("Goldpreis steigt")


def test_leerer_text_hat_hash_null():
    assert simhash("") == 0
