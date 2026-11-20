"""Führt die beiden Befehle aus ``docs/MIGRATIONEN.md`` wirklich aus.

Der Test liest die beiden ``python -c``-Zeilen aus dem Abschnitt «Stand und
Rückweg», kopiert ``seed/orakel-seed.db`` in ein temporäres Verzeichnis und
startet genau diese Zeilen als Unterprozess gegen eine ``config.toml``, die auf
die Kopie zeigt. Geprüft werden Exit-Code, Stand, Rückweg und die angekündigte
Sicherung samt ihrem Inhalt. Eine reine Text- oder Syntaxprüfung der Doku
genügt damit nicht mehr.
"""
from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from orakel.kern import migrationen

WURZEL = Path(__file__).resolve().parent.parent
DOKU = WURZEL / "docs" / "MIGRATIONEN.md"
SEED = WURZEL / "seed" / "orakel-seed.db"


def _doku_befehle() -> list[str]:
    """Die beiden dokumentierten Zeilen des Abschnitts «Stand und Rückweg»."""
    text = DOKU.read_text(encoding="utf-8")
    abschnitt = text.split("## Stand und Rückweg", 1)[1].split("\n## ", 1)[0]
    zeilen = [zeile.strip() for zeile in abschnitt.splitlines()
              if zeile.strip().startswith(".venv/bin/python -c")]
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
    assert _stand(db) == [1, 2, 3]
    return db


def _fuehre_aus(befehl: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Startet die dokumentierte Zeile mit dem laufenden Interpreter."""
    teile = shlex.split(befehl)
    assert teile[0] == ".venv/bin/python", befehl
    umgebung = {k: v for k, v in os.environ.items() if k != "ORAKEL_DB_PFAD"}
    umgebung["PYTHONPATH"] = str(WURZEL)
    return subprocess.run([sys.executable, *teile[1:]], cwd=cwd, env=umgebung,
                          capture_output=True, text=True, timeout=300)


def test_stand_befehl_laeuft_auf_der_seed_kopie(tmp_path):
    befehl = _doku_befehle()[0]
    db = _probe(tmp_path)
    sicherungen_vorher = set(tmp_path.glob("*.bak"))

    lauf = _fuehre_aus(befehl, tmp_path)

    assert lauf.returncode == 0, lauf.stderr
    assert ast.literal_eval(lauf.stdout) == [1, 2, 3]
    assert _stand(db) == [1, 2, 3]
    assert set(tmp_path.glob("*.bak")) == sicherungen_vorher, \
        "Status hat die Datenbank verändert"


def test_zurueck_befehl_rollt_zurueck_und_sichert_vorher(tmp_path):
    befehl = _doku_befehle()[1]
    db = _probe(tmp_path)

    lauf = _fuehre_aus(befehl, tmp_path)

    assert lauf.returncode == 0, lauf.stderr
    ergebnis = ast.literal_eval(lauf.stdout)
    assert ergebnis["zurueckgerollt"] == [3]
    assert _stand(db) == [1, 2]

    sicherung = Path(ergebnis["backup"])
    assert sicherung.is_file()
    assert sicherung.parent == tmp_path
    assert re.fullmatch(r"orakel\.db\.vor-migration-\d{8}-\d{6}\.bak", sicherung.name)
    assert _stand(sicherung) == [1, 2, 3], \
        "Sicherung muss den Stand vor dem Rückweg halten"
