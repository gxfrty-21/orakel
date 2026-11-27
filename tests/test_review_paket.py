from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_konsistenz_bricht_bei_abweichender_deutscher_testzahl(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    ziel = tmp_path / "dateien" / "docs"
    ziel.mkdir(parents=True)
    (ziel / "REVIEW-DOSSIER.md").write_text(
        "| Tests | **380 bestanden**, 0 fehlgeschlagen |\n", encoding="utf-8")

    with pytest.raises(modul.Abweichung, match="380"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_konsistenz_akzeptiert_deutsche_testzahl_und_verhaeltnisse(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    ziel = tmp_path / "dateien" / "docs"
    ziel.mkdir(parents=True)
    (ziel / "REVIEW-DOSSIER.md").write_text(
        "| Tests | **402 bestanden**, 0 fehlgeschlagen |\n"
        "Widerspruch-E2E-Negativtest: 3/3 bestanden.\n", encoding="utf-8")

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


def test_konsistenz_prueft_ci_lauf_id_in_zahlform(tmp_path, monkeypatch):
    """Auch "CI-Lauf 123456789" ohne URL wird gegen den Commit geprüft."""
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "EVIDENZ.md").write_text("CI-Lauf 123456789.\n", encoding="utf-8")

    monkeypatch.setattr(modul, "ci_lauf",
                        lambda run_id: {"run_id": int(run_id), "head_sha": "a" * 40})
    modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)

    monkeypatch.setattr(modul, "ci_lauf",
                        lambda run_id: {"run_id": int(run_id), "head_sha": "b" * 40})
    with pytest.raises(modul.Abweichung, match="123456789"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz)


def test_ci_lauf_ids_trennt_zahl_von_url_und_laufzeit():
    modul = _modul()
    ids = modul.ci_lauf_ids(
        "CI: https://github.com/example/repo/actions/runs/111222333\n"
        "CI-Lauf 444555666, Laufzeit 4000 s\n")

    assert ids == {"111222333", "444555666"}


def test_pruefbericht_enthaelt_nur_gemessene_werte(tmp_path):
    """Der CI-Bericht zitiert nur Hashes und Testzahl aus EVIDENZ/MANIFEST."""
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    quelle = tmp_path / "dateien" / "README.md"
    quelle.parent.mkdir(parents=True)
    quelle.write_text("inhalt\n", encoding="utf-8")
    echt = hashlib.sha256(quelle.read_bytes()).hexdigest()
    eintraege = [
        {"target": "dateien/README.md", "sha256": echt, "herkunft": "commit"},
        {"target": "belege/evidenz-pytest.log", "sha256": evidenz["dateien"][0]["sha256"],
         "herkunft": "beleg"},
    ]

    pfad = modul.schreibe_pruefbericht(str(tmp_path), "a" * 40, "main", eintraege, evidenz,
                                       {"run_id": 123456789, "conclusion": "success",
                                        "head_sha": "a" * 40})

    text = Path(pfad).read_text(encoding="utf-8")
    assert "402 passed" in text and echt[:16] in text
    assert "actions/runs/123456789" in text
    modul.pruefe_hauptdokument(str(tmp_path))
    modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz,
                            {"dateien/README.md": echt},
                            lauf=lambda run_id: {"run_id": int(run_id), "head_sha": "a" * 40})

    evidenz["testzahl"] = 999
    with pytest.raises(modul.Abweichung, match="999"):
        modul.pruefe_konsistenz(str(tmp_path), "a" * 40, evidenz,
                                {"dateien/README.md": echt})


def test_pruefen_ohne_paket_erzeugt_und_prueft_den_bericht(tmp_path, monkeypatch):
    """--pruefen im CI prüft einen Bericht aus dem frisch gemessenen Lauf."""
    modul = _modul()
    gerufen: list[str] = []

    def bau(freigabe, commit, branch, ausgabe, **_kwargs):
        Path(ausgabe).mkdir(parents=True, exist_ok=True)
        (Path(ausgabe) / "EVIDENZ.json").write_text(
            json.dumps({"testzahl": 7, "dateien": []}), encoding="utf-8")
        return [{"target": "dateien/README.md", "sha256": "a" * 64, "herkunft": "commit"}], "0" * 64

    monkeypatch.setattr(modul, "lade_freigabe", lambda: {
        "quellen": [{"quelle": "README.md", "ziel": "dateien/README.md"}]})
    monkeypatch.setattr(modul, "pruefe_commit", lambda _commit: ("a" * 40, "main"))
    monkeypatch.setattr(modul, "baue", bau)
    monkeypatch.setattr(modul, "schreibe_pruefbericht",
                        lambda ausgabe, *_a, **_k: gerufen.append(ausgabe))
    monkeypatch.setattr(sys, "argv", ["baue_review_paket.py", "--pruefen",
                                      "--ausgabe", str(tmp_path / "paket")])

    assert modul.main() == 0
    assert len(gerufen) == 1 and Path(gerufen[0]).name


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
        Path(ausgabe).mkdir(parents=True, exist_ok=True)
        (Path(ausgabe) / "EVIDENZ.json").write_text(
            json.dumps({"testzahl": 7, "dateien": []}), encoding="utf-8")
        return [], "0" * 64

    monkeypatch.setattr(modul, "lade_freigabe", lambda: {
        "quellen": [{"quelle": "README.md", "ziel": "dateien/README.md"}]})
    monkeypatch.setattr(modul, "pruefe_commit", lambda _commit: ("a" * 40, "main"))
    monkeypatch.setattr(modul, "baue", bau_merken)
    monkeypatch.setattr(sys, "argv", ["baue_review_paket.py", "--pruefen",
                                      "--ausgabe", str(tmp_path / "paket")])

    assert modul.main() == 0
    assert aufrufe and aufrufe[0]["evidenz_bauen"] is True


def _artefakt(tmp_path: Path, *, protokoll: str = "7 passed in 1.20s\n",
              exit_code: str = "0"):
    """Dateien, wie sie der pytest-Job als Artefakt ablegt."""
    ordner = tmp_path / "artefakt"
    ordner.mkdir(parents=True, exist_ok=True)
    log = ordner / "pytest.log"
    log.write_text(protokoll, encoding="utf-8")
    code = ordner / "exit_code"
    code.write_text(exit_code + "\n", encoding="utf-8")
    return log, code


class _NichtStarten:
    """Ersatz für ``subprocess``: der Testlauf darf im Test nicht starten."""

    SubprocessError = subprocess.SubprocessError

    @staticmethod
    def run(argv, **_kwargs):
        if list(argv[1:3]) == ["-m", "pytest"] or str(argv[0]).endswith("pytest"):
            pytest.fail("pytest wurde erneut gestartet")
        # Übrige Nachweise (z. B. der Strategie-Bericht) werden simuliert; der
        # Test prüft allein, dass pytest nicht ein zweites Mal startet.
        return SimpleNamespace(returncode=0, stdout="Nachweis OK\n", stderr="")


def test_evidenz_uebernimmt_das_ci_protokoll(tmp_path, monkeypatch):
    """Ein vorhandenes Protokoll ersetzt den eigenen pytest-Lauf."""
    modul = _modul()
    log, code = _artefakt(tmp_path)
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    evidenz = modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                       pytest_log=str(log), pytest_exit_code=str(code))

    kopie = tmp_path / "paket" / "belege" / "evidenz-pytest.log"
    assert evidenz["testzahl"] == 7
    assert kopie.read_text(encoding="utf-8") == log.read_text(encoding="utf-8")
    eintrag = evidenz["dateien"][0]
    assert eintrag["herkunft"] == "Job pytest (Artefakt)"
    assert eintrag["exit_code"] == 0
    assert eintrag["befehl"] == modul.PYTEST_ARTEFAKT_BEFEHL
    assert "Job pytest (Artefakt)" in (
        tmp_path / "paket" / "EVIDENZ.md").read_text(encoding="utf-8")


def test_evidenz_verweigert_fremden_exit_code(tmp_path, monkeypatch):
    """Ein Protokoll mit Exit 1 ist kein bestandener Nachweis."""
    modul = _modul()
    log, code = _artefakt(tmp_path, exit_code="1")
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    with pytest.raises(modul.Abweichung, match="Exit 1"):
        modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                 pytest_log=str(log), pytest_exit_code=str(code))


def test_evidenz_ohne_exit_code_datei_bricht_ab(tmp_path, monkeypatch):
    """Ohne Exit-Code ist der übernommene Lauf nicht belegt."""
    modul = _modul()
    log, _code = _artefakt(tmp_path)
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    with pytest.raises(modul.Abweichung, match="pytest-exit-code"):
        modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                 pytest_log=str(log))


def test_evidenz_prueft_das_artefakt_gegen_junit(tmp_path, monkeypatch):
    """JUnit-Bericht und übernommenes Protokoll müssen dieselbe Zahl nennen."""
    modul = _modul()
    log, code = _artefakt(tmp_path)
    junit = tmp_path / "artefakt" / "junit.xml"
    junit.write_text('<testsuite name="pytest" tests="8" />', encoding="utf-8")
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    with pytest.raises(modul.Abweichung, match="JUnit-Bericht nennt 8"):
        modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                 junit=str(junit), pytest_log=str(log),
                                 pytest_exit_code=str(code))


def test_veraenderte_evidenzdatei_faellt_auf(tmp_path):
    modul = _modul()
    evidenz = _evidenz(tmp_path)
    (tmp_path / "belege" / "evidenz-pytest.log").write_text("402 passed in 1.00s\n",
                                                           encoding="utf-8")

    with pytest.raises(modul.Abweichung, match="verändert"):
        modul.pruefe_evidenz_dateien(str(tmp_path), evidenz)


def test_ergebnis_zaehlt_alle_zustaende_der_schlusszeile():
    modul = _modul()

    assert modul.ergebnis_aus_log("417 passed, 2 skipped in 38.81s\n") == {
        "passed": 417, "skipped": 2}
    assert modul.ergebnis_aus_log("1 failed, 4 passed in 0.10s\n") == {
        "failed": 1, "passed": 4}
    assert modul.ergebnis_aus_log("kein Ergebnis") is None


def test_evidenz_zaehlt_skips_zur_gesamtzahl(tmp_path, monkeypatch):
    """Skips zählen zur JUnit-Gesamtzahl, nicht zu den bestandenen Tests."""
    modul = _modul()
    log, code = _artefakt(tmp_path, protokoll="5 passed, 1 skipped in 1.00s\n")
    junit = tmp_path / "artefakt" / "junit.xml"
    junit.write_text('<testsuite name="pytest" tests="6" />', encoding="utf-8")
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    evidenz = modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                       junit=str(junit), pytest_log=str(log),
                                       pytest_exit_code=str(code))

    assert (evidenz["testzahl"], evidenz["uebersprungen"], evidenz["gesamt"]) == (5, 1, 6)
    text = (tmp_path / "paket" / "EVIDENZ.md").read_text(encoding="utf-8")
    assert "Übersprungen: **1** Tests" in text
    assert "Gesamtzahl 6" in text


def test_evidenz_meldet_widerspruch_bei_skips(tmp_path, monkeypatch):
    """Ein JUnit-Bericht ohne den Skip fällt auf."""
    modul = _modul()
    log, code = _artefakt(tmp_path, protokoll="5 passed, 1 skipped in 1.00s\n")
    junit = tmp_path / "artefakt" / "junit.xml"
    junit.write_text('<testsuite name="pytest" tests="5" />', encoding="utf-8")
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    with pytest.raises(modul.Abweichung, match="passed \\+ skipped"):
        modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                 junit=str(junit), pytest_log=str(log),
                                 pytest_exit_code=str(code))


def test_evidenz_lehnt_fehlgeschlagene_tests_ab(tmp_path, monkeypatch):
    """Ein Lauf mit Fehlschlägen ist kein Nachweis, auch mit Exit 0."""
    modul = _modul()
    log, code = _artefakt(tmp_path, protokoll="1 failed, 4 passed in 1.00s\n")
    monkeypatch.setattr(modul, "PRUEFUNGEN", (
        ("pytest", ("-m", "pytest", "-q", "tests"), "belege/evidenz-pytest.log"),))
    monkeypatch.setattr(modul, "subprocess", _NichtStarten)

    with pytest.raises(modul.Abweichung, match="1 failed"):
        modul.fuehre_evidenz_aus(str(tmp_path / "paket"), "a" * 40, "main",
                                 pytest_log=str(log), pytest_exit_code=str(code))


# Diese Dateien gehören zum Review-Paket, liegen aber nicht unter einem der
# Pflichtpräfixe. Die Liste ist bewusst starr: Kommt eine Datei hinzu, muss sie
# hier und in scripts/review-paket-freigabe.json auftauchen. Reine Meta-Dateien
# der Wurzel stehen stattdessen mit Begründung unter "ausnahmen".
PFLICHTDATEIEN = {
    ".githooks/pre-commit", ".importlinter",
    "AGENTS.md", "DEPLOY.md", "Dockerfile", "RAILWAY.md", "README.md", "config.toml",
    "docker-compose.yml", "docker-entrypoint.sh", "mypy.ini",
    "requirements-dev.in", "requirements-dev.txt", "requirements.in", "requirements.txt",
    "ruff.toml", "seed/README.md",
}


def _freigabe(quelle: str) -> dict:
    return {"schema": "review-paket-freigabe.v1",
            "quellen": [{"quelle": quelle, "ziel": f"dateien/{quelle}"}]}


def _paketordner(tmp_path: Path) -> None:
    (tmp_path / "dateien").mkdir()
    (tmp_path / "dateien" / "README.md").write_text("x", encoding="utf-8")


def test_freigabe_deckt_module_tests_doku_und_skripte_ab():
    """Neue Dateien dürfen nicht still aus dem Paket fallen."""
    modul = _modul()
    freigabe = modul.lade_freigabe()
    freigegeben = {e["quelle"] for e in freigabe["quellen"]}
    ausnahmen = {e["quelle"]: e["grund"] for e in freigabe.get("ausnahmen") or []}
    dateien = modul.git('ls-files').decode().split()
    pflicht = [p for p in dateien
               if p.startswith(("orakel/", "tests/", "docs/", "scripts/", "deploy/",
                                ".github/workflows/"))
               or p in PFLICHTDATEIEN
               # Wurzeldateien erfasst kein Präfix: Sie brauchen entweder einen
               # Platz im Paket oder eine begründete Ausnahme.
               or "/" not in p]

    assert pflicht, "git ls-files lieferte keine Dateien"
    fehlend = sorted(set(pflicht) - freigegeben - set(ausnahmen))
    assert not fehlend, f"Weder im Paket noch begründet ausgenommen: {fehlend}"

    # Ausnahmen gelten nur für Wurzeldateien und nie für etwas, das ohnehin im
    # Paket liegt; Code, Tests, Doku, Skripte und CI lassen sich nicht ausnehmen.
    assert freigegeben.isdisjoint(ausnahmen), sorted(freigegeben & set(ausnahmen))
    assert not [name for name in ausnahmen if "/" in name], sorted(ausnahmen)
    for name, grund in ausnahmen.items():
        assert name in dateien, f"Ausnahme {name} existiert nicht"
        assert grund.strip(), f"Ausnahme {name} nennt keinen Grund"


def test_hauptdokument_darf_keinen_fremden_commit_nennen(tmp_path):
    modul = _modul()
    _paketordner(tmp_path)
    dokument = tmp_path / "ORAKEL-REVIEW-PAKET.md"

    dokument.write_text(f"Review-Commit: `{'a' * 40}`\n", encoding="utf-8")
    modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))

    dokument.write_text("Review-Commit: `deadbeef1`\n", encoding="utf-8")
    with pytest.raises(modul.Abweichung, match="fremden Commit"):
        modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))


def test_hauptdokument_nennt_nur_dateien_aus_dem_paket(tmp_path):
    modul = _modul()
    _paketordner(tmp_path)
    dokument = tmp_path / "ORAKEL-REVIEW-PAKET.md"

    dokument.write_text("Prüfen: `README.md` und `dateien/README.md`.\n", encoding="utf-8")
    modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))

    dokument.write_text("Prüfen: `orakel/kern/risk.py`.\n", encoding="utf-8")
    with pytest.raises(modul.Abweichung, match="nicht im Paket"):
        modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))

    dokument.write_text("Prüfen: `dateien/fehlt.py`.\n", encoding="utf-8")
    with pytest.raises(modul.Abweichung, match="fehlende Datei"):
        modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))

    # Nach "## Nicht im Paket" darf das Dokument Fehlendes ausdrücklich nennen.
    dokument.write_text(f"Review-Commit: `{'a' * 40}`.\n\n## Nicht im Paket\n\n"
                        "- `orakel/kern/risk.py`\n", encoding="utf-8")
    modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))


def test_freigabe_lehnt_ausnahme_ohne_grund_und_doppelrolle_ab(tmp_path, monkeypatch):
    """Eine Ausnahme braucht einen Grund und darf nicht zugleich im Paket sein."""
    modul = _modul()
    pfad = tmp_path / "freigabe.json"
    monkeypatch.setattr(modul, "FREIGABE", str(pfad))

    def schreibe(ausnahmen):
        pfad.write_text(json.dumps({
            "schema": "review-paket-freigabe.v1",
            "quellen": [{"quelle": "README.md", "ziel": "dateien/README.md"}],
            "ausnahmen": ausnahmen}, ensure_ascii=False), encoding="utf-8")

    schreibe([{"quelle": ".gitignore", "grund": "Repository-Hygiene"}])
    assert modul.lade_freigabe()["ausnahmen"][0]["quelle"] == ".gitignore"

    schreibe([{"quelle": ".gitignore", "grund": "  "}])
    with pytest.raises(modul.Abweichung, match="keinen Grund"):
        modul.lade_freigabe()

    schreibe([{"quelle": "README.md", "grund": "doppelt"}])
    with pytest.raises(modul.Abweichung, match="zugleich freigegeben"):
        modul.lade_freigabe()

    schreibe([{"quelle": "orakel/web.py", "grund": "Code"}])
    with pytest.raises(modul.Abweichung, match="Wurzelverzeichnis"):
        modul.lade_freigabe()


def test_pruefbericht_nennt_ausnahmen_mit_grund(tmp_path):
    """Der Bericht weist bewusst ausgenommene Wurzeldateien mit Grund aus."""
    modul = _modul()
    text = Path(modul.schreibe_pruefbericht(
        str(tmp_path), "a" * 40, "main", [], None, None,
        ausnahmen=[{"quelle": ".gitignore", "grund": "Repository-Hygiene"}],
    )).read_text(encoding="utf-8")

    assert "## Nicht im Paket" in text
    assert "`.gitignore` – Repository-Hygiene" in text


def test_pruefbericht_listet_fehlende_paketdateien(tmp_path):
    """Der erzeugte Bericht nennt ausdrücklich, was im Paket fehlt."""
    modul = _modul()
    text = Path(modul.schreibe_pruefbericht(
        str(tmp_path), "a" * 40, "main", [], None, None,
        fehlend=["ORAKEL-REVIEW-PAKET.md", "belege/evidenz-pytest.log"],
    )).read_text(encoding="utf-8")

    assert "## Nicht im Paket" in text
    assert "`belege/evidenz-pytest.log`" in text and "`ORAKEL-REVIEW-PAKET.md`" in text


def test_fehlendes_hauptdokument_bricht_die_pruefung_nicht_ab(tmp_path):
    """Ein nicht vorhandenes Dokument wird als fehlend ausgewiesen, nicht geprüft."""
    modul = _modul()
    _paketordner(tmp_path)

    modul.pruefe_dokumente(str(tmp_path), "a" * 40, _freigabe("README.md"))
