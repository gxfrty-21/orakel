from __future__ import annotations

import hashlib
import importlib.util
import json
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


def test_ci_lauf_ohne_gh_nutzt_http(monkeypatch):
    """Die Lauf-ID wird per HTTPS geprüft; das CLI wird nicht gebraucht."""
    modul = _modul()
    monkeypatch.setattr(modul, "repo_slug", lambda: "example/repo")
    monkeypatch.setattr(modul, "_http_json", lambda url: {
        "head_sha": "a" * 40, "conclusion": "success", "event": "push"})

    def kein_gh(*_args, **_kwargs):
        raise AssertionError("gh darf für CI-Läufe nicht aufgerufen werden")

    monkeypatch.setattr(modul.subprocess, "run", kein_gh)

    lauf = modul.ci_lauf("123")

    assert lauf["run_id"] == 123
    assert lauf["head_sha"] == "a" * 40


def test_konsistenz_prueft_ci_lauf_ohne_gh(tmp_path, monkeypatch):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "EVIDENZ.md").write_text(
        "CI: https://github.com/example/repo/actions/runs/123456\n", encoding="utf-8")

    monkeypatch.setattr(modul, "ci_lauf",
                        lambda run_id: {"run_id": int(run_id), "head_sha": "a" * 40})
    modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)

    monkeypatch.setattr(modul, "ci_lauf",
                        lambda run_id: {"run_id": int(run_id), "head_sha": "b" * 40})
    with pytest.raises(modul.Abweichung, match="123456"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_konsistenz_prueft_quellenhash_gegen_manifest(tmp_path):
    """Ein Hash in der Doku muss zum Manifest und zur Commit-Quelle passen."""
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    quelle = tmp_path / "dateien" / "README.md"
    quelle.parent.mkdir(parents=True)
    quelle.write_text("inhalt\n", encoding="utf-8")
    echt = hashlib.sha256(quelle.read_bytes()).hexdigest()
    (tmp_path / "MANIFEST.json").write_text(json.dumps({"files": [
        {"target": "dateien/README.md", "sha256": echt}]}), encoding="utf-8")
    (tmp_path / "ORAKEL-REVIEW-PAKET.md").write_text(
        f"`dateien/README.md` (`{echt[:16]}…`)\n", encoding="utf-8")

    modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz,
                            {"dateien/README.md": echt})

    with pytest.raises(modul.Abweichung, match="README.md"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz,
                                {"dateien/README.md": "0" * 64})


def test_hauptdokument_hoechstens_200_zeilen(tmp_path):
    modul = _modul()
    dokument = tmp_path / "ORAKEL-REVIEW-PAKET.md"

    dokument.write_text("\n".join(["Zeile"] * 200) + "\n", encoding="utf-8")
    modul.pruefe_hauptdokument(str(tmp_path))

    dokument.write_text("\n".join(["Zeile"] * 201) + "\n", encoding="utf-8")
    with pytest.raises(modul.Abweichung, match="201"):
        modul.pruefe_hauptdokument(str(tmp_path))


def test_evidenz_testzahl_muss_zum_protokoll_passen(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    evidenz["testzahl"] = 999
    (tmp_path / "EVIDENZ.json").write_text(json.dumps(evidenz), encoding="utf-8")

    with pytest.raises(modul.Abweichung, match="999"):
        modul.pruefe_evidenz(str(tmp_path), "a" * 40)


def test_pruefen_erzwingt_evidenz_im_tempbau(tmp_path, monkeypatch):
    """Ohne vorhandenes Paket wird die Testzahl immer neu gemessen."""
    modul = _modul()
    aufrufe: list[dict] = []

    def bau_merken(freigabe, commit, branch, ausgabe, **kwargs):
        aufrufe.append(kwargs)
        return [], "0" * 64

    monkeypatch.setattr(modul, "lade_freigabe", lambda: {
        "quellen": [{"quelle": "README.md", "ziel": "dateien/README.md"}]})
    monkeypatch.setattr(modul, "pruefe_commit", lambda _commit: ("a" * 40, "main"))
    monkeypatch.setattr(modul, "baue", bau_merken)
    monkeypatch.setattr(sys, "argv", ["baue_review_paket.py", "--pruefen",
                                      "--ausgabe", str(tmp_path / "paket")])

    assert modul.main() == 0
    assert aufrufe and aufrufe[0]["evidenz_bauen"] is True


def test_veraenderte_evidenzdatei_faellt_auf(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "belege" / "evidenz-pytest.log").write_text("402 passed in 1.00s\n",
                                                           encoding="utf-8")

    with pytest.raises(modul.Abweichung, match="verändert"):
        modul.pruefe_evidenz_dateien(str(tmp_path), evidenz)
