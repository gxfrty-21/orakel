from __future__ import annotations

import base64

from orakel.web import _basic_ok


def kopf(benutzer: str, passwort: str) -> str:
    return "Basic " + base64.b64encode(f"{benutzer}:{passwort}".encode()).decode()


def test_basic_auth_akzeptiert_nur_richtige_daten():
    assert _basic_ok(kopf("orakel", "geheim"), "orakel", "geheim")
    assert _basic_ok(kopf("orakel", "ge:heim"), "orakel", "ge:heim")
    assert _basic_ok(kopf("orakel", "Paßwört"), "orakel", "Paßwört")
    assert not _basic_ok(kopf("orakel", "falsch"), "orakel", "geheim")
    assert not _basic_ok(kopf("anderer", "geheim"), "orakel", "geheim")


def test_basic_auth_lehnt_kaputte_und_leere_header_ab():
    assert not _basic_ok("", "orakel", "geheim")
    assert not _basic_ok("Bearer token", "orakel", "geheim")
    assert not _basic_ok("Basic !!!", "orakel", "geheim")
    assert not _basic_ok("Basic " + base64.b64encode(b"ohne-doppelpunkt").decode(),
                         "orakel", "geheim")
    assert not _basic_ok(kopf("orakel", "geheim"), "", "")
