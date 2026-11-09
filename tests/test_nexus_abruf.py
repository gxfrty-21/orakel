from __future__ import annotations

import http.server
import threading

import pytest

from orakel.nexus.abruf import Abrufer, HttpCache
from orakel.nexus.quellen import Quelle

FEED = b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title></channel></rss>'


class _Handler(http.server.BaseHTTPRequestHandler):
    etag = '"v1"'
    last_modified = "Mon, 03 Nov 2025 10:00:00 GMT"
    fehler_zaehler = 0

    def log_message(self, *args):  # noqa: D401 - Testserver bleibt leise
        return

    def _senden(self, status: int, ctype: str = "application/rss+xml",
                body: bytes = b"", extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for name, wert in (extra or {}).items():
            self.send_header(name, wert)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server verlangt den Namen
        if self.path == "/feed.xml":
            if self.headers.get("If-None-Match") == self.etag:
                self._senden(304, extra={"ETag": self.etag})
                return
            self._senden(200, body=FEED,
                         extra={"ETag": self.etag, "Last-Modified": self.last_modified})
        elif self.path == "/html":
            self._senden(200, "text/html; charset=utf-8", b"<html>Fehler</html>")
        elif self.path == "/gross":
            self._senden(200, body=b"x" * 5000)
        elif self.path == "/fehler":
            type(self).fehler_zaehler += 1
            self._senden(500, "text/plain", b"kaputt")
        else:
            self._senden(404, "text/plain", b"weg")


@pytest.fixture
def server():
    _Handler.fehler_zaehler = 0
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _quelle(url: str) -> Quelle:
    return Quelle(id="t", name="Test", typ="rss", url=url,
                  land="DE", sprache="de", thema="test")


def _abrufer(tmp_path, **abweichung) -> Abrufer:
    basis = dict(min_abstand_sekunden=0.0, timeout=5.0)
    basis.update(abweichung)
    return Abrufer(HttpCache(tmp_path / "cache.db"), "Test/1.0", **basis)


def test_erster_abruf_speichert_etag_und_zweiter_bekommt_304(server, tmp_path):
    abrufer = _abrufer(tmp_path)
    quelle = _quelle(f"{server}/feed.xml")

    erst = abrufer.hole(quelle)
    assert erst.ok and erst.status == 200
    assert erst.inhalt == FEED
    assert erst.etag == '"v1"'

    zweit = abrufer.hole(quelle)
    assert zweit.ok and zweit.status == 304
    assert zweit.aus_cache is True
    assert zweit.inhalt is None

    cache = HttpCache(tmp_path / "cache.db")
    assert cache.hole(f"{server}/feed.xml").status == 200
    assert cache.statistik()["anzahl"] == 1


def test_html_statt_feed_wird_abgelehnt(server, tmp_path):
    ergebnis = _abrufer(tmp_path).hole(_quelle(f"{server}/html"))
    assert not ergebnis.ok
    assert "HTML" in (ergebnis.fehler or "")


def test_groessenlimit_greift(server, tmp_path):
    ergebnis = _abrufer(tmp_path, max_bytes=1000).hole(_quelle(f"{server}/gross"))
    assert not ergebnis.ok
    assert "Bytes" in (ergebnis.fehler or "")


def test_fehlerbudget_pausiert_den_host(server, tmp_path):
    abrufer = _abrufer(tmp_path, fehlerbudget=2, pause_sekunden=600)
    quelle = _quelle(f"{server}/fehler")

    assert abrufer.hole(quelle).fehler == "HTTP 500"
    assert abrufer.hole(quelle).fehler == "HTTP 500"
    assert abrufer.pausiert(quelle.url)

    dritter = abrufer.hole(quelle)
    assert "pausiert" in (dritter.fehler or "")
    assert _Handler.fehler_zaehler == 2


def test_cache_statistik_ist_leer_ohne_abruf(tmp_path):
    daten = HttpCache(tmp_path / "cache.db").statistik()
    assert daten["anzahl"] == 0
    assert daten["bytes"] == 0
