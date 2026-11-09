from __future__ import annotations

import pytest

from orakel.nexus.feeds import parse_feed
from orakel.nexus.quellen import Quelle

QUELLE = Quelle(id="test", name="Test", typ="rss",
                url="https://example.com/feed/", land="DE", sprache="de",
                thema="test")

RSS2 = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>EZB laesst Leitzins unveraendert</title>
  <link>https://example.com/artikel/1</link>
  <description>&lt;p&gt;Die EZB liess den Zins am Donnerstag unveraendert.&lt;/p&gt;</description>
  <pubDate>Mon, 03 Nov 2025 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Ohne Link</title>
</item>
</channel></rss>"""

RDF = b"""<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
<channel rdf:about="https://example.com/feed/"><title>Test</title></channel>
<item rdf:about="https://example.com/a/2">
  <title>Deutsche Welle Meldung</title>
  <link>https://example.com/a/2</link>
  <description>Kurzer Text.</description>
</item>
</rdf:RDF>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
  <title>Atom Eintrag</title>
  <link href="/artikel/3"/>
  <updated>2025-11-03T10:00:00Z</updated>
  <summary>Zusammenfassung.</summary>
</entry>
</feed>"""


def test_rss2_wird_gelesen_und_gesaeubert():
    meldungen = parse_feed(RSS2, QUELLE)
    assert len(meldungen) == 1
    m = meldungen[0]
    assert m.titel == "EZB laesst Leitzins unveraendert"
    assert m.url == "https://example.com/artikel/1"
    assert "<p>" not in m.zusammenfassung
    assert m.veroeffentlicht and "2025" in m.veroeffentlicht
    assert len(m.kennung) == 32


def test_rdf_wird_gelesen():
    meldungen = parse_feed(RDF, QUELLE)
    assert len(meldungen) == 1
    assert meldungen[0].titel == "Deutsche Welle Meldung"
    assert meldungen[0].url == "https://example.com/a/2"


def test_atom_wird_gelesen_und_relativer_link_aufgeloest():
    meldungen = parse_feed(ATOM, QUELLE)
    assert len(meldungen) == 1
    assert meldungen[0].url == "https://example.com/artikel/3"
    assert meldungen[0].quelle_id == "test"
    assert meldungen[0].sprache == "de"


def test_kaputtes_xml_wirft_parsefehler():
    with pytest.raises(Exception):
        parse_feed(b"<rss><channel>", QUELLE)


def test_leerer_feed_liefert_keine_meldungen():
    leer = b'<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    assert parse_feed(leer, QUELLE) == []
