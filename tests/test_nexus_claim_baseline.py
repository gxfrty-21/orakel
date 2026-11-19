from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _modul(name: str, datei: Path):
    spec = importlib.util.spec_from_file_location(name, datei)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def test_allgemeiner_claim_korpus_hat_34_eindeutige_meldungen():
    modul = _modul("nexus_claim_korpus_test", ROOT / "scripts" / "nexus_claim_baseline.py")
    korpus = modul.lade_korpus()

    meldungen = korpus["meldungen"]
    assert korpus["typ"] == "claim"
    assert len(meldungen) == 34
    assert len({m["id"] for m in meldungen}) == len(meldungen)
    assert all(m["id"].startswith("seed-") for m in meldungen)
    assert sum(bool(m["erwartet"]["claim"]) for m in meldungen) == 4
    for meldung in meldungen:
        assert meldung["quelle"]
        assert meldung["titel"]
        assert meldung["zusammenfassung"]
        assert meldung["erwartet"]["begruendung"]
        assert set(meldung["erwartet"]) == {
            "claim", "thema", "subjekt", "metrik", "richtung",
            "wert", "einheit", "negiert", "begruendung",
        }


def test_pp_probe_hat_fuenf_gezielte_pp_meldungen():
    modul = _modul("nexus_pp_probe_korpus_test", ROOT / "scripts" / "nexus_claim_baseline.py")
    korpus = modul.lade_korpus(modul.PP_PROBE_KORPUS)

    meldungen = korpus["meldungen"]
    assert korpus["typ"] == "pp_probe"
    assert len(meldungen) == 5
    assert [m["id"] for m in meldungen] == [
        "rss-pp-001", "rss-pp-002", "rss-pp-003", "rss-pp-004", "rss-pp-005",
    ]
    assert all(m["erwartet"]["claim"] for m in meldungen)
    assert all(m["erwartet"]["einheit"] == "pp" for m in meldungen)
    assert all(m["erwartet"]["begruendung"] for m in meldungen)


def test_allgemeine_baseline_ist_reproduzierbar_und_zeigt_die_luecken():
    modul = _modul("nexus_claim_baseline_test", ROOT / "scripts" / "nexus_claim_baseline.py")
    korpus = modul.lade_korpus()

    erster = modul.bewerte(korpus)
    zweiter = modul.bewerte(korpus)

    assert erster == zweiter
    assert erster["meldungen"] == 34
    assert erster["erwartete_claims"] == 4
    assert erster["erkannte_claims"] == 2
    assert erster["richtige_claims"] == 1
    assert erster["falsch_positive"] == 0
    assert erster["uebersehene_claims"] == 2
    assert erster["erkannt_aber_feldfehler"] == 1
    assert erster["claim_precision"] == 0.5
    assert erster["claim_recall"] == 0.25
    assert erster["feldgesamt"]["thema"] == 4
    assert erster["feldtreffer"]["thema"] == 2
    assert erster["pp_erwartet"] == 0
    assert erster["pp_vorhergesagt"] == 0
    assert erster["pp_faelle"] == []
    assert erster["pp_precision"] is None
    assert erster["pp_recall"] is None
    assert erster["pp_tp"] == 0
    assert erster["pp_fp"] == 0
    assert erster["pp_fn"] == 0
    assert erster["pp_strict_precision"] is None
    assert erster["pp_strict_recall"] is None
    assert erster["pp_feldtreffer"] == {feld: 0 for feld in modul.PP_FELDER}
    assert erster["pp_feldgesamt"] == {feld: 0 for feld in modul.PP_FELDER}

    abweichungen = {
        fall["id"]: "; ".join(fall["abweichungen"])
        for fall in erster["einzelfaelle"]
        if not fall["korrekt"]
    }
    assert "seed-021" in abweichungen
    assert "metrik" in abweichungen["seed-021"]
    assert "subjekt" in abweichungen["seed-021"]
    assert "seed-023" in abweichungen
    assert "seed-024" in abweichungen
    assert "Claim nicht erkannt" in abweichungen["seed-023"]
    assert "Claim nicht erkannt" in abweichungen["seed-024"]


def test_pp_probe_baseline_ist_reproduzierbar_und_vollstaendig():
    modul = _modul("nexus_pp_probe_baseline_test", ROOT / "scripts" / "nexus_claim_baseline.py")
    korpus = modul.lade_korpus(modul.PP_PROBE_KORPUS)

    erster = modul.bewerte(korpus)
    zweiter = modul.bewerte(korpus)

    assert erster == zweiter
    assert erster["meldungen"] == 5
    assert erster["erwartete_claims"] == 5
    assert erster["erkannte_claims"] == 5
    assert erster["richtige_claims"] == 5
    assert erster["falsch_positive"] == 0
    assert erster["uebersehene_claims"] == 0
    assert erster["erkannt_aber_feldfehler"] == 0
    assert erster["claim_precision"] == 1.0
    assert erster["claim_recall"] == 1.0
    assert erster["pp_erwartet"] == 5
    assert erster["pp_vorhergesagt"] == 5
    assert erster["pp_richtig"] == 5
    assert erster["pp_precision"] == 1.0
    assert erster["pp_recall"] == 1.0
    assert erster["pp_tp"] == 5
    assert erster["pp_fp"] == 0
    assert erster["pp_fn"] == 0
    assert erster["pp_strict_precision"] == 1.0
    assert erster["pp_strict_recall"] == 1.0
    assert [fall["id"] for fall in erster["pp_faelle"]] == [
        "rss-pp-001", "rss-pp-002", "rss-pp-003", "rss-pp-004", "rss-pp-005",
    ]
    assert all(fall["erwartet_pp"] and fall["erkannt_pp"] for fall in erster["pp_faelle"])
    assert all(fall["strict_korrekt"] and fall["status"] == "TP"
               for fall in erster["pp_faelle"])
    assert all(erster["pp_feldtreffer"][feld] == 5 for feld in modul.PP_FELDER)
    assert all(erster["pp_feldgesamt"][feld] == 5 for feld in modul.PP_FELDER)
    assert all(erster["feldtreffer"][feld] == 5 for feld in modul.FELDER)
    assert all(erster["feldgesamt"][feld] == 5 for feld in modul.FELDER)


@pytest.mark.parametrize(
    ("feld", "falscher_wert"),
    [
        ("subjekt", "falsches subjekt"),
        ("metrik", "falsche metrik"),
        ("wert", 99.0),
        ("richtung", "sinkt"),
    ],
)
def test_pp_strikte_feldfehler_zaehlen_als_fp_und_fn(feld, falscher_wert):
    modul = _modul(
        f"nexus_pp_strict_{feld}_test",
        ROOT / "scripts" / "nexus_claim_baseline.py",
    )
    korpus = copy.deepcopy(modul.lade_korpus(modul.PP_PROBE_KORPUS))
    fall = next(m for m in korpus["meldungen"] if m["id"] == "rss-pp-001")
    fall["erwartet"][feld] = falscher_wert

    ergebnis = modul.bewerte(korpus)

    assert ergebnis["pp_erwartet"] == 5
    assert ergebnis["pp_vorhergesagt"] == 5
    assert ergebnis["pp_richtig"] == 5
    assert ergebnis["pp_tp"] == 4
    assert ergebnis["pp_fp"] == 1
    assert ergebnis["pp_fn"] == 1
    assert ergebnis["pp_strict_precision"] == 0.8
    assert ergebnis["pp_strict_recall"] == 0.8
    assert ergebnis["pp_feldtreffer"][feld] == 4
    assert ergebnis["pp_feldgesamt"][feld] == 5
    for anderes_feld in modul.PP_FELDER:
        if anderes_feld != feld:
            assert ergebnis["pp_feldtreffer"][anderes_feld] == 5

    pp_fall = next(f for f in ergebnis["pp_faelle"] if f["id"] == "rss-pp-001")
    assert pp_fall["strict_korrekt"] is False
    assert pp_fall["status"] == "FP+FN"
    assert any(feld in fehler for fehler in pp_fall["feldfehler"])


def test_pp_vorhersage_ohne_gold_zaehlt_als_fp():
    modul = _modul(
        "nexus_pp_strict_fp_test",
        ROOT / "scripts" / "nexus_claim_baseline.py",
    )
    korpus = copy.deepcopy(modul.lade_korpus(modul.PP_PROBE_KORPUS))
    fall = next(m for m in korpus["meldungen"] if m["id"] == "rss-pp-001")
    fall["erwartet"]["einheit"] = "%"

    ergebnis = modul.bewerte(korpus)

    assert ergebnis["pp_erwartet"] == 4
    assert ergebnis["pp_vorhergesagt"] == 5
    assert ergebnis["pp_richtig"] == 4
    assert ergebnis["pp_tp"] == 4
    assert ergebnis["pp_fp"] == 1
    assert ergebnis["pp_fn"] == 0
    assert ergebnis["pp_strict_precision"] == 0.8
    assert ergebnis["pp_strict_recall"] == 1.0

    pp_fall = next(f for f in ergebnis["pp_faelle"] if f["id"] == "rss-pp-001")
    assert pp_fall["erwartet_pp"] is False
    assert pp_fall["erkannt_pp"] is True
    assert pp_fall["status"] == "FP"
    assert pp_fall["strict_korrekt"] is False
