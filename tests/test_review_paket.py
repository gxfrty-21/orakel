from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _modul():
    name = "baue_review_paket_test"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "baue_review_paket.py")
    assert spec is not None and spec.loader is not None
    modul = importlib.util.module_from_spec(spec)
    sys.modules[name] = modul
    spec.loader.exec_module(modul)
    return modul


def _evidenz(tmp_path: Path, *, inhalt: str = "402 passed in 40.00s\n") -> dict:
    protokoll = tmp_path / "belege" / "evidenz-pytest.log"
    protokoll.parent.mkdir(parents=True, exist_ok=True)
    protokoll.write_text(inhalt, encoding="utf-8")
    return {
        "schema": "review-paket-evidenz.v3",
        "quelle": {"commit": "a" * 40, "branch": "main", "dirty": False},
        "testzahl": 402,
        "dateien": [{
            "name": "pytest",
            "target": "belege/evidenz-pytest.log",
            "befehl": "python -m pytest -q",
            "exit_code": 0,
            "sha256": hashlib.sha256(protokoll.read_bytes()).hexdigest(),
            "bytes": protokoll.stat().st_size,
            "log": "402 passed in 40.00s",
        }],
    }


def test_testzahl_wird_aus_der_schlusszeile_gelesen():
    modul = _modul()

    assert modul.testzahl_aus_log("...\n402 passed in 36.53s\n") == 402
    assert modul.testzahl_aus_log("kein Ergebnis") is None


def test_junit_ist_die_zweite_quelle_fuer_die_testzahl(tmp_path):
    modul = _modul()
    bericht = tmp_path / "pytest.xml"
    bericht.write_text('<testsuites><testsuite tests="402" failures="0"/></testsuites>',
                       encoding="utf-8")

    assert modul.testzahl_aus_junit(str(bericht)) == 402

    with pytest.raises(modul.Abweichung):
        modul.testzahl_aus_junit(str(tmp_path / "fehlt.xml"))


def test_evidenz_md_enthaelt_nur_gemessene_werte(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)

    text = modul.rendere_evidenz_md(evidenz)

    assert "**402**" in text
    assert evidenz["dateien"][0]["sha256"][:16] + "…" in text
    assert "belege/evidenz-pytest.log" in text


def test_konsistenz_akzeptiert_passende_angaben(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "EVIDENZ.md").write_text(modul.rendere_evidenz_md(evidenz), encoding="utf-8")

    modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_konsistenz_bricht_bei_abweichender_testzahl(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "ORAKEL-REVIEW-PAKET.md").write_text("Lauf: 380 passed\n", encoding="utf-8")

    with pytest.raises(modul.Abweichung, match="380"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_konsistenz_bricht_bei_falschem_hash(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "EVIDENZ.md").write_text(
        "| pytest | `python -m pytest -q` | 0 | 402 passed | "
        "`belege/evidenz-pytest.log` (`deadbeefdeadbeef…`) |\n",
        encoding="utf-8",
    )

    with pytest.raises(modul.Abweichung, match="deadbeef"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_konsistenz_ueberspringt_ci_laeufe_ohne_gh(tmp_path, monkeypatch):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "EVIDENZ.md").write_text(
        "CI: https://github.com/example/repo/actions/runs/123456\n", encoding="utf-8")
    monkeypatch.setattr(modul, "_gh_verfuegbar", lambda: False)

    modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_veraenderte_evidenzdatei_faellt_auf(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "belege" / "evidenz-pytest.log").write_text("402 passed in 1.00s\n",
                                                           encoding="utf-8")

    with pytest.raises(modul.Abweichung, match="verändert"):
        modul.pruefe_evidenz_dateien(str(tmp_path), evidenz)


def _dokumente(tmp_path: Path, inhalt: str, freigabe: dict | None = None) -> dict:
    (tmp_path / "ORAKEL-REVIEW-PAKET.md").write_text(inhalt, encoding="utf-8")
    return freigabe or {"quellen": [{"quelle": "orakel/web.py", "ziel": "dateien/orakel/web.py"}]}


def test_hauptdokument_darf_nur_den_review_commit_nennen(tmp_path):
    modul = _modul()
    freigabe = _dokumente(tmp_path, "Review: `" + "a" * 40 + "`\n")
    modul.pruefe_dokumente(str(tmp_path), "a" * 40, freigabe)

    freigabe = _dokumente(tmp_path, "Review: `" + "b" * 40 + "`\n")
    with pytest.raises(modul.Abweichung, match="fremden Commit"):
        modul.pruefe_dokumente(str(tmp_path), "a" * 40, freigabe)


def test_hauptdokument_darf_nicht_ueber_200_zeilen_wachsen(tmp_path):
    modul = _modul()
    freigabe = _dokumente(tmp_path, "Zeile\n" * 201)

    with pytest.raises(modul.Abweichung, match="Zeilen"):
        modul.pruefe_dokumente(str(tmp_path), "a" * 40, freigabe)


def test_hauptdokument_nennt_nur_dateien_aus_dem_paket(tmp_path):
    modul = _modul()
    freigabe = _dokumente(tmp_path, "Siehe `orakel/fehlt.py`.\n")

    with pytest.raises(modul.Abweichung, match="nicht im Paket"):
        modul.pruefe_dokumente(str(tmp_path), "a" * 40, freigabe)
