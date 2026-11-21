"""API-Vertrag des Widerspruchs gegen eine laufende, geseedete API.

Die übrigen Fälle prüfen gespeicherte Status-Proben. Hier entscheidet das
Skript über echte ``/api/nexus/status``-Antworten: einmal über eine frische
Seed-Datenbank mit angelegtem Widerspruch, einmal über eine ohne. Browser und
Playwright sind dafür nicht nötig.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

import pytest

WURZEL = Path(__file__).resolve().parents[1]
MODUL = WURZEL / "scripts" / "widerspruch-api-pruefung.mjs"
SEED = WURZEL / "seed" / "orakel-seed.db"
SEED_SKRIPT = WURZEL / "scripts" / "seed_widerspruch.py"


def _node() -> str:
    pfad = shutil.which("node")
    if not pfad:
        pytest.skip("node ist nicht installiert")
    return pfad


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _status(url: str) -> dict[str, Any]:
    # Nur die Adresse des gerade gestarteten lokalen Servers, kein Nutzereingang.
    with urllib.request.urlopen(  # noqa: S310 - fester lokaler HTTP-Aufruf
            f"{url}/api/nexus/status", timeout=5) as antwort:
        return json.loads(antwort.read().decode("utf-8"))


@contextlib.contextmanager
def _api(tmp_path: Path, *, seed: bool) -> Iterator[str]:
    """Startet ``orakel serve`` auf einer Seed-Kopie und räumt sie wieder auf."""
    db = tmp_path / "orakel.db"
    shutil.copy(SEED, db)
    if seed:
        lauf = subprocess.run(  # noqa: S603 - fester Aufruf ohne Shell
            [sys.executable, str(SEED_SKRIPT), str(db)],
            capture_output=True, text=True, cwd=WURZEL, check=False,
        )
        assert lauf.returncode == 0, lauf.stderr

    port = _freier_port()
    log = (tmp_path / "server.log").open("w", encoding="utf-8")
    prozess = subprocess.Popen(  # noqa: S603 - fester Aufruf ohne Shell
        [sys.executable, "-m", "orakel", "serve",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=WURZEL, env={**os.environ, "ORAKEL_DB_PFAD": str(db)},
        stdout=log, stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        grenze = time.monotonic() + 30
        while time.monotonic() < grenze:
            if prozess.poll() is not None:
                log.close()
                pytest.fail("Server beendete sich: "
                            + (tmp_path / "server.log").read_text(encoding="utf-8"))
            try:
                _status(url)
                break
            except (urllib.error.URLError, OSError, json.JSONDecodeError):
                time.sleep(0.2)
        else:
            pytest.fail("API wurde nicht bereit: "
                        + (tmp_path / "server.log").read_text(encoding="utf-8"))
        yield url
    finally:
        prozess.terminate()
        try:
            prozess.wait(timeout=10)
        except subprocess.TimeoutExpired:
            prozess.kill()
            prozess.wait(timeout=10)
        log.close()


def _pruefe(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fester Programmaufruf ohne Shell
        [_node(), str(MODUL), "--url", url],
        capture_output=True, text=True, cwd=WURZEL, check=False,
    )


def test_live_api_bestaetigt_geseedeten_widerspruch(tmp_path):
    with _api(tmp_path, seed=True) as url:
        lauf = _pruefe(url)

    assert lauf.returncode == 0, lauf.stderr
    assert "Widerspruch-API OK" in lauf.stdout


def test_live_api_lehnt_antwort_ohne_widerspruch_ab(tmp_path):
    """Die frische Seed-Datenbank liefert ``ok``, aber keinen Widerspruch."""
    with _api(tmp_path, seed=False) as url:
        lauf = _pruefe(url)

    assert lauf.returncode == 1, lauf.stdout
    assert "API enthält den erwarteten Widerspruch nicht" in lauf.stderr
