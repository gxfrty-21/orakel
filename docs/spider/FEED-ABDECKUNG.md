# Abdeckung der englischen Nexus-Feeds

**Stand:** 17. November 2026, 08:11 UTC
**Grundlage:** `orakel/nexus/register.toml`
**Umfang:** 32 Quellen mit `sprache = "en"` (31 RSS/Atom, 1 JSON-API)

Diese Matrix prüft die tatsächlich im Nexus-Register konfigurierten englischen
Quellen. Der alte Spider mit seinen sieben Feeds aus `config.toml` ist nicht
Teil dieser Messung; die fünf pp-Google-News-Suchen aus dem pp-Probe-Korpus
sind ebenfalls keine registrierten Feeds.

## Methode

- Jede Quelle wurde am 17. November 2026 um 08:11 UTC real abgerufen
  (`OrakelNexus/0.1`, Timeout 25 s, Obergrenze 2 MB).
- RSS/Atom wurde mit dem produktiven Parser `orakel.nexus.feeds.parse_feed`
  gelesen. Hacker News wurde als JSON-API über `topstories.json` und das erste
  Top-Item geprüft.
- **Aktualität:** neuester Datumswert im Feed (`pubDate`, `dc:date`,
  `Atom published` oder `updated`), Alter in Tagen relativ zum Abrufzeitpunkt.
  `frisch` = höchstens 7 Tage, `veraltet` = mehr als 30 Tage.
- **pp-Ausbeute:** `pp-Titel` zählt explizite pp-Schreibweisen im Titel
  (`Prozentpunkt…`, `percentage point…`, eigenständiges `pp`). `pp-Claims`
  zählt zusätzlich die erfolgreiche Produktiv-Extraktion aus Titel, sonst aus
  dem ersten Satz der Zusammenfassung. Die Einheit muss dabei `pp` sein.
- Ein HTTP-Erfolg allein gilt nicht als inhaltlicher Erfolg. Entscheidend sind
  zusätzlich valides XML und mindestens ein Eintrag.

## Zusammenfassung

| Kennzahl | Ergebnis |
|---|---:|
| Englische Quellen insgesamt | 32 |
| davon RSS/Atom | 31 |
| davon JSON-API | 1 |
| HTTP-Erfolg | 32/32 |
| RSS/Atom mit mindestens einem Eintrag | 30/31 |
| RSS-Einträge insgesamt | 1.036 |
| RSS-Einträge mit Datum | 1.035 |
| Frisch (≤ 7 Tage) | 27/32 |
| 8–30 Tage | 0/32 |
| Älter als 30 Tage | 4/32 |
| Ohne Aktualitätsbewertung | 1/32 |
| pp-Titel in RSS-Einträgen | 0 |
| pp-Claims in RSS-Einträgen | 0 |
| RSS-Quellen mit pp-Ausbeute | 0/31 |

Länderverteilung: US 16, GB 8, EU 2, JP/CH/QA/DE/HK/CN je 1.
Themenverteilung: Nachrichten 8, Markt 7, Notenbank 4, Technologie 4,
Wissenschaft 3, Geldpolitik 2, Gesundheit/Statistik/Energie/Krypto je 1.

## Matrix

`pp` = pp-Titel / pp-Claims. `Alter` in Tagen seit dem neuesten Feed-Eintrag.
Bei Hacker News bezieht sich das Datum auf das erste Top-Item, nicht auf eine
chronologische Sortierung.

| ID | Quelle | Typ | Land | Thema | HTTP | Einträge | Neuester Eintrag (UTC) | Alter | pp | Befund |
|---|---|---|---:|---|---:|---:|---|---:|---:|---|
| `ecb-press` | EZB Pressemitteilungen | RSS | EU | notenbank | 200 | 15 | 2026-11-16 13:00 | 0.8 | 0 / 0 | frisch |
| `ecb-blog` | EZB Blog | RSS | EU | geldpolitik | 200 | 15 | 2026-11-12 10:00 | 4.9 | 0 / 0 | frisch |
| `fed-press` | Federal Reserve Press | RSS | US | notenbank | 200 | 20 | 2026-11-13 21:15 | 3.5 | 0 / 0 | frisch |
| `fed-monetary` | Federal Reserve Geldpolitik | RSS | US | geldpolitik | 200 | 15 | 2026-11-12 17:45 | 4.6 | 0 / 0 | frisch |
| `boe-news` | Bank of England News | RSS | GB | notenbank | 200 | 50 | 2026-11-13 09:00 | 4.0 | 0 / 0 | frisch |
| `boj-news` | Bank of Japan News | RSS | JP | notenbank | 200 | 45 | 2026-11-16 23:50 | 0.3 | 0 / 0 | frisch |
| `who-news` | WHO News | RSS | CH | gesundheit | 200 | 83 | 2026-10-10 07:49 | 38.0 | 0 / 0 | veraltet |
| `un-news` | UN News | RSS | US | nachrichten | 200 | 30 | 2026-11-16 12:00 | 0.8 | 0 / 0 | frisch |
| `bbc-business` | BBC Business | RSS | GB | markt | 200 | 55 | 2026-11-17 07:21 | 0.0 | 0 / 0 | frisch |
| `bbc-world` | BBC World | RSS | GB | nachrichten | 200 | 21 | 2026-11-17 08:06 | 0.0 | 0 / 0 | frisch |
| `guardian-business` | Guardian Business | RSS | GB | markt | 200 | 40 | 2026-11-17 08:00 | 0.0 | 0 / 0 | frisch |
| `guardian-world` | Guardian World | RSS | GB | nachrichten | 200 | 45 | 2026-11-17 07:42 | 0.0 | 0 / 0 | frisch |
| `nyt-business` | New York Times Business | RSS | US | markt | 200 | 49 | 2026-11-17 07:02 | 0.1 | 0 / 0 | frisch |
| `nyt-world` | New York Times World | RSS | US | nachrichten | 200 | 58 | 2026-11-17 07:18 | 0.0 | 0 / 0 | frisch |
| `cnbc-top` | CNBC Top Stories | RSS | US | markt | 200 | 30 | 2026-11-17 07:07 | 0.0 | 0 / 0 | frisch |
| `marketwatch` | MarketWatch Top Stories | RSS | US | markt | 200 | 10 | 2026-11-17 02:30 | 0.2 | 0 / 0 | frisch |
| `wsj-markets` | Wall Street Journal Markets | RSS | US | markt | 200 | 20 | 2025-01-27 19:26 | 658.5 | 0 / 0 | stark veraltet |
| `ft-home` | Financial Times Startseite | RSS | GB | markt | 200 | 12 | 2026-11-17 07:36 | 0.0 | 0 / 0 | frisch |
| `aljazeera` | Al Jazeera | RSS | QA | nachrichten | 200 | 25 | 2026-11-17 07:36 | 0.0 | 0 / 0 | frisch |
| `dw-en` | Deutsche Welle Englisch | RSS | DE | nachrichten | 200 | 132 | 2026-11-17 07:34 | 0.0 | 0 / 0 | frisch |
| `arstechnica` | Ars Technica | RSS | US | technologie | 200 | 20 | 2026-11-16 22:58 | 0.4 | 0 / 0 | frisch |
| `techcrunch` | TechCrunch | RSS | US | technologie | 200 | 20 | 2026-11-16 23:32 | 0.4 | 0 / 0 | frisch |
| `mit-tr` | MIT Technology Review | RSS | US | technologie | 200 | 10 | 2026-11-16 18:38 | 0.6 | 0 / 0 | frisch |
| `nature` | Nature | RSS | GB | wissenschaft | 200 | 75 | 2026-11-16 00:00 | 1.3 | 0 / 0 | frisch |
| `science-news` | Science News | RSS | US | wissenschaft | 200 | 9 | 2026-10-12 03:00 | 36.2 | 0 / 0 | veraltet |
| `arxiv-econ` | arXiv Economics | RSS | US | wissenschaft | 200 | 0 | – | – | 0 / 0 | leer |
| `ourworldindata` | Our World in Data | RSS | GB | statistik | 200 | 10 | 2026-11-16 00:00 | 1.3 | 0 / 0 | frisch |
| `eia` | US Energy Information Administration | RSS | US | energie | 200 | 27 | 2026-11-13 14:00 | 3.8 | 0 / 0 | frisch |
| `coindesk` | CoinDesk | RSS | US | krypto | 200 | 25 | 2026-11-17 07:38 | 0.0 | 0 / 0 | frisch |
| `scmp` | South China Morning Post | RSS | HK | nachrichten | 200 | 50 | 2026-11-17 08:06 | 0.0 | 0 / 0 | frisch |
| `xinhua-en` | Xinhua Englisch | RSS | CN | nachrichten | 200 | 20 | 2018-01-24 00:00 | 3219.3 | 0 / 0 | stark veraltet |
| `hn-top` | Hacker News Top Stories | JSON | US | technologie | 200 | 500 | Top-Item 2026-11-16 20:43 | 0.5 | – | frisch |

## Befunde

1. **Abruf:** Alle 32 Quellen antworteten mit HTTP 200. Die 31 RSS/Atom-Quellen
   wurden erfolgreich geparst; 30 lieferten mindestens einen Eintrag.
   `arxiv-econ` ist mit 0 Einträgen der einzige inhaltlich leere Feed.
2. **Aktualität:** 27 von 32 Quellen sind frisch. Vier RSS-Feeds sind älter als
   30 Tage: `who-news` (38 Tage), `science-news` (36 Tage), `wsj-markets`
   (658 Tage) und `xinhua-en` (3.219 Tage). `arxiv-econ` hat keinen Eintrag und
   damit keinen bewertbaren Zeitstempel. Besonders `wsj-markets` und
   `xinhua-en` sind trotz HTTP 200 praktisch keine aktuellen Nachrichtenquellen.
3. **pp-Ausbeute:** In 1.036 RSS-Einträgen gibt es **0 pp-Titel** und **0
   pp-Claims**. Keine der 31 konfigurierten englischen RSS-Quellen liefert in
   diesem Lauf einen pp-Fall. Das ist eine Abdeckungslücke der Registerfeeds,
   keine Aussage über die pp-Extraktion: Die fünf pp-Proben stammen aus
   gezielten Google-News-RSS-Suchen und sind nicht Teil dieses Registers.
4. **Breite:** Die 32 Quellen decken 9 Länder und 10 Themen ab; der Schwerpunkt
   liegt mit 16 US- und 8 GB-Quellen klar im englischsprachigen
   angelsächsischen Raum.

## Grenzen

- Die Matrix ist ein Snapshot vom 17. November 2026, 08:11 UTC. Feed-Inhalte
  und Zeitstempel ändern sich danach.
- Hacker News ist kein RSS-Feed. Die 500 Top-Stories wurden nur auf
  Abruferfolg und das erste Top-Item geprüft; eine pp-Ausbeute über alle
  HN-Titel wurde nicht erhoben und geht nicht in den pp-Nenner ein.
- Die pp-Ausbeute basiert auf Titel und erster Zusammenfassung, nicht auf
  Volltexten. Ein Artikel ohne pp im Feed-Titel kann im Volltext dennoch einen
  pp-Wert enthalten.
- HTTP 200 und valides XML belegen die technische Abrufbarkeit, nicht die
  inhaltliche Qualität oder eine Mindestaktualität.
- Der alte Spider mit `config.toml` ist nicht enthalten.
