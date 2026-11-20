"""Die Befehle in ``docs/MIGRATIONEN.md`` bleiben ohne festen Datenbankpfad."""
from __future__ import annotations

import re
from pathlib import Path

DOKU = Path(__file__).resolve().parent.parent / "docs" / "MIGRATIONEN.md"


def _befehle() -> list[str]:
    """Die dokumentierten ``python -c``-Zeilen (genau zwei erwartet)."""
    zeilen = [zeile for zeile in DOKU.read_text(encoding="utf-8").splitlines()
              if zeile.startswith(".venv/bin/python -c")]
    assert len(zeilen) == 2, zeilen
    return zeilen


def test_befehle_nehmen_den_pfad_aus_der_konfiguration():
    for zeile in _befehle():
        assert "load_config(sys.argv[1]).db_pfad" in zeile
        assert "config.toml" in zeile
        assert "'orakel.db'" not in zeile


def test_befehlscode_ist_gueltiges_python():
    for zeile in _befehle():
        treffer = re.search(r'-c "([^"]+)"', zeile)
        assert treffer is not None, zeile
        compile(treffer.group(1), "<docs/MIGRATIONEN.md>", "exec")
