from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _modul(name: str, datei: Path):
    spec = importlib.util.spec_from_file_location(name, datei)
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def test_claim_korpus_hat_30_bis_50_eindeutige_meldungen():
    modul = _modul("nexus_claim_korpus_test", ROOT / "scripts" / "nexus_claim_baseline.py")
    korpus = modul.lade_korpus()

    meldungen = korpus["meldungen"]
    assert 30 <= len(meldungen) <= 50
    assert len({m["id"] for m in meldungen}) == len(meldungen)
    assert sum(bool(m["erwartet"]["claim"]) for m in meldungen) == 9
    for meldung in meldungen:
        assert meldung["quelle"]
        assert meldung["titel"]
        assert meldung["zusammenfassung"]
        assert meldung["erwartet"]["begruendung"]
        assert set(meldung["erwartet"]) == {
            "claim", "thema", "subjekt", "metrik", "richtung",
            "wert", "einheit", "negiert", "begruendung",
        }


def test_claim_baseline_ist_reproduzierbar_und_zeigt_die_luecken():
    modul = _modul("nexus_claim_baseline_test", ROOT / "scripts" / "nexus_claim_baseline.py")
    korpus = modul.lade_korpus()

    erster = modul.bewerte(korpus)
    zweiter = modul.bewerte(korpus)

    assert erster == zweiter
    assert erster["meldungen"] == 39
    assert erster["erwartete_claims"] == 9
    assert erster["erkannte_claims"] == 7
    assert erster["richtige_claims"] == 6
    assert erster["falsch_positive"] == 0
    assert erster["uebersehene_claims"] == 2
    assert erster["erkannt_aber_feldfehler"] == 1
    assert erster["claim_precision"] == 0.8571
    assert erster["claim_recall"] == 0.6667
    assert erster["feldgesamt"]["thema"] == 9
    assert erster["feldtreffer"]["thema"] == 7
    assert erster["pp_erwartet"] == 5
    assert erster["pp_vorhergesagt"] == 5
    assert erster["pp_richtig"] == 5
    assert erster["pp_precision"] == 1.0
    assert erster["pp_recall"] == 1.0
    assert [fall["id"] for fall in erster["pp_faelle"]] == [
        "rss-pp-001", "rss-pp-002", "rss-pp-003", "rss-pp-004", "rss-pp-005",
    ]
    assert all(fall["erwartet_pp"] and fall["erkannt_pp"] for fall in erster["pp_faelle"])

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
