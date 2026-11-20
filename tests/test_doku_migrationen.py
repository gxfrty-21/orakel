"""Führt die beiden Befehle aus ``docs/MIGRATIONEN.md`` wirklich aus.

Der Test liest die Zeilen aus dem Abschnitt «Stand und Rückweg», kopiert
``seed/orakel-seed.db`` in ein temporäres Verzeichnis, migriert die Kopie
vollständig und startet dann genau diese Befehle als Unterprozess. Geprüft
werden Exit-Code, Stand, offene Migrationen und die angekündigte Sicherung
samt ihrem Inhalt. Eine reine Text- oder Syntaxprüfung der Doku genügt damit
nicht mehr.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from orakel.kern import migrationen

WURZEL = Path(__file__).resolve().parent.parent
DOKU = WURZEL / "docs" / "MIGRATIONEN.md"
SEED = WURZEL / "seed" / "orakel-seed.db"
VOLLER_STAND = ", ".join(m.stand for m in migrationen.dateien())


def _doku_befehle() -> list[str]:
    """Die beiden dokumentierten Zeilen des Abschnitts «Stand und Rückweg»."""
    text = DOKU.read_text(encoding="utf-8")
    abschnitt = text.split("## Stand und Rückweg", 1)[1].split("\n## ", 1)[0]
    zeilen = [zeile.strip() for zeile in abschnitt.splitlines()
              if zeile.strip().startswith(".venv/bin/python -m orakel migration")]
    assert len(zeilen) == 2, zeilen
    return zeilen


def _stand(pfad: Path) -> list[int]:
    return migrationen.angewendet(pfad)


def _probe(tmp_path: Path) -> Path:
    """Seed-Kopie mit eigener ``config.toml``, vollständig migriert."""
    db = tmp_path / "orakel.db"
    shutil.copyfile(SEED, db)
    config = (WURZEL / "config.toml").read_text(encoding="utf-8")
    config, ersetzt = re.subn(r'(?m)^db_pfad = "orakel\.db"$', f'db_pfad = "{db}"', config)
    assert ersetzt == 1, "config.toml: db_pfad nicht eindeutig ersetzt"
    (tmp_path / "config.toml").write_text(config, encoding="utf-8")
    migrationen.anwenden(db)
    assert _stand(db) == [m.nummer for m in migrationen.dateien()]
    return db


def _fuehre_aus(befehl: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Startet die dokumentierte Zeile mit dem laufenden Interpreter."""
    teile = befehl.split()
    assert teile[0] == ".venv/bin/python", befehl
    umgebung = {k: v for k, v in os.environ.items() if k != "ORAKEL_DB_PFAD"}
    umgebung["PYTHONPATH"] = str(WURZEL)
    return subprocess.run([sys.executable, *teile[1:]], cwd=cwd, env=umgebung,
                          capture_output=True, text=True, timeout=300)


def test_status_befehl_laeuft_auf_der_seed_kopie(tmp_path):
    befehl = _doku_befehle()[0]
    db = _probe(tmp_path)
    sicherungen_vorher = set(tmp_path.glob("*.bak"))

    lauf = _fuehre_aus(befehl, tmp_path)

    assert lauf.returncode == 0, lauf.stderr
    assert f"orakel: Datenbank {db}" in lauf.stdout
    assert f"orakel: Stand {VOLLER_STAND}" in lauf.stdout
    assert "orakel: Offen keine" in lauf.stdout
    assert _stand(db) == [m.nummer for m in migrationen.dateien()]
    assert set(tmp_path.glob("*.bak")) == sicherungen_vorher, "Status hat die Datenbank verändert"


def test_zurueck_befehl_rollt_zurueck_und_sichert_vorher(tmp_path):
    befehl = _doku_befehle()[1]
    db = _probe(tmp_path)

    lauf = _fuehre_aus(befehl, tmp_path)

    assert lauf.returncode == 0, lauf.stderr
    assert "orakel: Zurückgerollt" in lauf.stdout
    for zurueck in (m.stand for m in migrationen.dateien() if m.nummer > 2):
        assert zurueck in lauf.stdout, lauf.stdout
    assert "orakel: Neuer Stand 0001_basis, 0002_company" in lauf.stdout
    assert _stand(db) == [1, 2]

    treffer = re.search(r"^orakel: Sicherung (.+)$", lauf.stdout, re.MULTILINE)
    assert treffer is not None, lauf.stdout
    sicherung = Path(treffer.group(1).strip())
    assert sicherung.is_file()
    assert sicherung.parent == tmp_path
    assert re.fullmatch(r"orakel\.db\.vor-migration-\d{8}-\d{6}\.bak", sicherung.name)
    assert _stand(sicherung) == [m.nummer for m in migrationen.dateien()], (
        "Sicherung muss den Stand vor dem Rückweg halten")
