from __future__ import annotations

import http.server
import json
import threading

import pytest

from orakel.nexus.abruf import Abrufer, HttpCache
from orakel.nexus.hackernews import meldungen, top_ids

ITEMS = {
    1: {"id": 1, "type": "story", "title": "Ein echter Beitrag",
        "url": "https://example.com/beitrag", "time": 1794240045,
        "score": 120, "descendants": 30, "by": "alice"},
    2: {"id": 2, "type": "story", "deleted": True, "title": "weg"},
    3: {"id": 3, "type": "comment", "title": "", "by": "bob"},
    4: {"id": 4, "type": "story", "title": "Ohne Link", "time": 1794240000,
        "score": 5, "descendants": 1, "by": "carol"},
}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def _json(self, daten) -> None:
        body = json.dumps(daten).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/v0/topstories.json":
            self._json([1, 2, 3, 4])
        elif self.path.startswith("/v0/item/"):
            try:
                kennung = int(self.path.rsplit("/", 1)[1].split(".")[0])
            except ValueError:
                self.send_response(404)
                self.end_headers()
                return
            self._json(ITEMS.get(kennung, {}))
        else:
            self.send_response(404)
            self.end_headers()


@pytest.fixture
def basis():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}/v0"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _abrufer(tmp_path) -> Abrufer:
    return Abrufer(HttpCache(tmp_path / "cache.db"), "Test/1.0",
                   min_abstand_sekunden=0.0, timeout=5.0)


def test_top_ids_liefert_die_liste(basis, tmp_path):
    assert top_ids(_abrufer(tmp_path), limit=3, basis=basis) == [1, 2, 3]


def test_meldungen_filtert_tote_und_kommentare(basis, tmp_path):
    raus = meldungen(_abrufer(tmp_path), limit=10, basis=basis)
    assert [m.id for m in raus] == [1, 4]
    assert raus[0].titel == "Ein echter Beitrag"
    assert raus[0].punkte == 120
    assert raus[1].url == "https://news.ycombinator.com/item?id=4"
