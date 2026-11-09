from __future__ import annotations

from orakel.db import Facts
from orakel.knowledge import Vault
from orakel.spider import Spider, _qualitaet, _symbole_erkennen

RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item>
  <title>EZB laesst Leitzins unveraendert</title>
  <link>https://www.ecb.europa.eu/press/pr/date/2025/html/x.de.html</link>
  <description>&lt;p&gt;Die Europaeische Zentralbank hat den Leitzins am Donnerstag unveraendert gelassen.
  Analysten rechneten mit einer Senkung um 25 Basispunkte. Der Euro reagierte kaum.&lt;/p&gt;</description>
  <pubDate>Mon, 03 Nov 2025 10:00:00 GMT</pubDate>
</item>
<item>
  <title>Gold erreicht neues Hoch</title>
  <link>https://example.com/gold</link>
  <description>Goldpreis steigt um 2 Prozent.</description>
</item>
</channel></rss>"""


def test_rss_parsing_und_qualitaet(cfg):
    db = Facts(cfg.db_pfad)
    spider = Spider(cfg, db, Vault(cfg.vault_ordner),
                    abrufer=lambda url, t, ua: RSS, schlaf=lambda s: None)
    ergebnis = spider.lauf()

    assert ergebnis["gelesen"] == 2
    assert ergebnis["neu"] == 2
    artikel = db.artikel(10)
    titel = {a["titel"] for a in artikel}
    assert "EZB laesst Leitzins unveraendert" in titel
    ezb = next(a for a in artikel if "EZB" in a["titel"])
    assert "EURUSD" in ezb["symbole"]
    assert ezb["qualitaet"] > 0.5
    assert ezb["url"].startswith("https://")


def test_dubletten_werden_nicht_doppelt_gespeichert(cfg):
    db = Facts(cfg.db_pfad)
    spider = Spider(cfg, db, Vault(cfg.vault_ordner),
                    abrufer=lambda url, t, ua: RSS, schlaf=lambda s: None)
    assert spider.lauf()["neu"] == 2
    assert spider.lauf()["neu"] == 0
    assert db.artikel_statistik()["gesamt"] == 2


def test_robots_txt_verbot_wird_respektiert(cfg):
    db = Facts(cfg.db_pfad)

    def abrufer(url: str, timeout: int, user_agent: str) -> bytes:
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nDisallow: /"
        return RSS

    spider = Spider(cfg, db, Vault(cfg.vault_ordner), abrufer=abrufer, schlaf=lambda s: None)
    assert spider.lauf()["neu"] == 0
    assert db.artikel_statistik()["gesamt"] == 0


def test_qualitaet_straft_sensationssprache():
    serioes = _qualitaet(0.95, "https://www.ecb.europa.eu/press/a", "EZB senkt Zins",
                         "Die EZB senkte den Leitzins um 25 Basispunkte am 3.11.2025. " * 8)
    reisserisch = _qualitaet(0.95, "https://example.com/a", "GARANTIERT REICH!!!",
                             "So verdoppelst du dein Geld — sicher reich in 7 Tagen!!!")
    assert serioes > reisserisch


HTML = (b"<html><head><title>EZB</title><script>var a=1;</script></head>"
        b"<body><nav>Menue</nav><article><h1>EZB</h1><p>Die Europaeische Zentralbank liess "
        b"den Leitzins unveraendert. Der Euro reagierte kaum auf die Entscheidung.</p>"
        b"</article><footer>Impressum</footer></body></html>")


def test_volltext_wird_analysiert(cfg):
    db = Facts(cfg.db_pfad)

    def abrufer(url: str, timeout: int, user_agent: str) -> bytes:
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nAllow: /"
        if "feed" in url:
            return RSS
        return HTML

    spider = Spider(cfg, db, Vault(cfg.vault_ordner), abrufer=abrufer, schlaf=lambda s: None)
    ergebnis = spider.lauf()

    assert ergebnis["analysiert"] == 2
    zeile = db.artikel(1)[0]
    inhalt = db.artikel_inhalt(zeile["id"])
    assert "Zentralbank" in inhalt
    assert "var a=1" not in inhalt and "Impressum" not in inhalt


def test_symbolzuordnung():
    assert "EURUSD" in _symbole_erkennen("Die EZB und der Euro")
    assert "XAUUSD" in _symbole_erkennen("Goldpreis auf Rekordhoch")
    assert _symbole_erkennen("Wetter in Berlin") == []
