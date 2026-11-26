from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import migrationen


def jetzt() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _json_wert(text: str, standard: Any = None) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return standard


def _forecast_aus_zeile(zeile: sqlite3.Row) -> dict[str, Any]:
    """Trennt Prognose und Prüfergebnis für die API, ohne Werte zu erfinden."""
    daten = dict(zeile)
    result_id = daten.pop("result_id", None)
    ergebnis = None
    if result_id is not None:
        ergebnis = {
            "id": int(result_id),
            "eingetreten": (None if daten.get("result_eingetreten") is None
                            else int(daten["result_eingetreten"])),
            "messwert": daten.get("result_messwert"),
            "geprueft_am": daten.get("result_geprueft_am"),
            "notiz": daten.get("result_notiz") or "",
        }
    for schluessel in list(daten):
        if schluessel.startswith("result_"):
            daten.pop(schluessel)
    daten["ergebnis"] = ergebnis
    return daten


_INITIALISIERT: set[str] = set()
_INIT_SPERRE = threading.Lock()


def initialisiere(pfad: str | Path) -> None:
    """Wendet offene Migrationen an – einmal pro Pfad und Prozess.

    Früher lief das Schema bei jeder ``Facts``-Instanz und damit bei fast jeder
    HTTP-Anfrage. Die Migrationen selbst sind nummeriert und in
    ``schema_migrationen`` protokolliert; siehe ``orakel/kern/migrationen.py``.
    """
    datei = Path(pfad)
    schluessel = str(datei.resolve())
    with _INIT_SPERRE:
        if schluessel in _INITIALISIERT:
            return
        datei.parent.mkdir(parents=True, exist_ok=True)
        migrationen.anwenden(datei)
        _INITIALISIERT.add(schluessel)


@dataclass(slots=True)
class Kerzenkonflikte:
    """Abweichende Überschneidungen eines Imports; dient nur der Meldung."""

    anzahl: int = 0
    beispiele: list[str] = field(default_factory=list)

    def merke(self, ts: str) -> None:
        self.anzahl += 1
        if len(self.beispiele) < 3:
            self.beispiele.append(ts)


class Facts:
    """Fakten-Datenbank. Jede Zahl im Dashboard stammt von hier."""

    def __init__(self, pfad: str | Path) -> None:
        self.pfad = Path(pfad)
        initialisiere(self.pfad)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self.pfad, timeout=30)
        c.execute("PRAGMA busy_timeout = 5000")
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    # ---------- Kerzen ----------
    def kerzen_speichern(self, symbol: str, zeitrahmen: str, reihen: Iterable[dict[str, Any]]) -> int:
        daten = [
            (symbol, zeitrahmen, str(r["ts"]), float(r["open"]), float(r["high"]),
             float(r["low"]), float(r["close"]), float(r.get("volume", 0) or 0))
            for r in reihen
        ]
        if not daten:
            return 0
        with self.conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO kerzen(symbol,zeitrahmen,ts,open,high,low,close,volume)"
                " VALUES (?,?,?,?,?,?,?,?)",
                daten,
            )
        return len(daten)

    def kerzen_speichern_df(self, symbol: str, zeitrahmen: str, df: Any) -> int:
        """Wie ``kerzen_speichern``, aber blockweise direkt aus einer Tabelle.

        Millionen Zeilen als Dicts oder Tupel zu materialisieren kostet ein
        Vielfaches des DataFrames; hier gehen die Spalten blockweise an
        ``executemany``.
        """
        if df.empty:
            return 0
        with self.conn() as c:
            return self._kerzen_block(c, symbol, zeitrahmen, df)

    def _kerzen_block(self, c: sqlite3.Connection, symbol: str, zeitrahmen: str, df: Any) -> int:
        sql = ("INSERT OR REPLACE INTO kerzen(symbol,zeitrahmen,ts,open,high,low,close,volume)"
               " VALUES (?,?,?,?,?,?,?,?)")
        for start in range(0, len(df), 50_000):
            block = df.iloc[start:start + 50_000]
            c.executemany(sql, zip(
                (symbol for _ in range(len(block))),
                (zeitrahmen for _ in range(len(block))),
                block["ts"].astype(str),
                block["open"].astype(float),
                block["high"].astype(float),
                block["low"].astype(float),
                block["close"].astype(float),
                block["volume"].fillna(0).astype(float),
            ))
        return len(df)

    def kerzen_speichern_bloecke(self, symbol: str, zeitrahmen: str,
                                 bloecke: Iterable[Any], *,
                                 konflikte: Kerzenkonflikte | None = None,
                                 c: sqlite3.Connection | None = None) -> int:
        """Schreibt Blöcke in einer Transaktion; bei einem Fehler bleibt nichts stehen.

        Mit ``konflikte`` werden gleiche Zeitstempel mit abweichenden
        OHLC-Werten gezählt, bevor ``INSERT OR REPLACE`` sie ersetzt. Mit ``c``
        läuft der Import in der bereits offenen Transaktion des Aufrufers; so
        können mehrere Dateien gemeinsam committet oder zurückgerollt werden.
        """
        if c is not None:
            return self._kerzen_bloecke_auf_verbindung(
                c, symbol, zeitrahmen, bloecke, konflikte)
        with self.conn() as verbindung:
            return self._kerzen_bloecke_auf_verbindung(
                verbindung, symbol, zeitrahmen, bloecke, konflikte)

    def _kerzen_bloecke_auf_verbindung(
        self, c: sqlite3.Connection, symbol: str, zeitrahmen: str,
        bloecke: Iterable[Any], konflikte: Kerzenkonflikte | None,
    ) -> int:
        anzahl = 0
        for block in bloecke:
            if konflikte is not None:
                self._abweichungen(c, symbol, zeitrahmen, block, konflikte)
            anzahl += self._kerzen_block(c, symbol, zeitrahmen, block)
        return anzahl

    def _abweichungen(self, c: sqlite3.Connection, symbol: str, zeitrahmen: str,
                      df: Any, konflikte: Kerzenkonflikte) -> None:
        """Zählt Kerzen, deren OHLC von der gespeicherten Fassung abweicht.

        ``INSERT OR REPLACE`` ersetzt gleiche Zeitstempel ohne Nachfrage; ein
        erneuter Export mit anderen Werten soll das nicht unbemerkt tun.
        """
        if df.empty:
            return
        ts = df["ts"].astype(str)
        vorhanden = {
            r["ts"]: (r["open"], r["high"], r["low"], r["close"])
            for r in c.execute(
                "SELECT ts,open,high,low,close FROM kerzen"
                " WHERE symbol=? AND zeitrahmen=? AND ts BETWEEN ? AND ?",
                (symbol, zeitrahmen, str(ts.min()), str(ts.max())),
            )
        }
        for zeile in df.itertuples(index=False):
            alt = vorhanden.get(str(zeile.ts))
            if alt is None:
                continue
            neu = (float(zeile.open), float(zeile.high), float(zeile.low),
                   float(zeile.close))
            if alt != neu:
                konflikte.merke(str(zeile.ts))

    def kerzen(self, symbol: str, zeitrahmen: str) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT ts,open,high,low,close,volume FROM kerzen"
                " WHERE symbol=? AND zeitrahmen=? ORDER BY ts",
                (symbol, zeitrahmen),
            ))

    def hat_kerzen(self, symbol: str, zeitrahmen: str, *,
                   c: sqlite3.Connection | None = None) -> bool:
        """Prüft ohne Laden der Reihe, ob mindestens eine Kerze existiert."""
        if c is not None:
            return c.execute(
                "SELECT 1 FROM kerzen WHERE symbol=? AND zeitrahmen=? LIMIT 1",
                (symbol, zeitrahmen),
            ).fetchone() is not None
        with self.conn() as verbindung:
            return verbindung.execute(
                "SELECT 1 FROM kerzen WHERE symbol=? AND zeitrahmen=? LIMIT 1",
                (symbol, zeitrahmen),
            ).fetchone() is not None

    def kerzen_bloecke(self, symbol: str, zeitrahmen: str,
                       groesse: int = 200_000, *,
                       c: sqlite3.Connection | None = None) -> Iterator[list[sqlite3.Row]]:
        """Liefert die Kerzen blockweise; für Millionen Zeilen schonender als ``kerzen``."""
        if c is not None:
            yield from self._kerzen_lese_bloecke_auf_verbindung(
                c, symbol, zeitrahmen, groesse)
            return
        with self.conn() as verbindung:
            yield from self._kerzen_lese_bloecke_auf_verbindung(
                verbindung, symbol, zeitrahmen, groesse)

    @staticmethod
    def _kerzen_lese_bloecke_auf_verbindung(
        c: sqlite3.Connection, symbol: str, zeitrahmen: str, groesse: int,
    ) -> Iterator[list[sqlite3.Row]]:
        cursor = c.execute(
            "SELECT ts,open,high,low,close,volume FROM kerzen"
            " WHERE symbol=? AND zeitrahmen=? ORDER BY ts",
            (symbol, zeitrahmen),
        )
        while True:
            block = cursor.fetchmany(groesse)
            if not block:
                return
            yield block

    def symbole(self) -> list[str]:
        with self.conn() as c:
            return [r["symbol"] for r in c.execute("SELECT DISTINCT symbol FROM kerzen ORDER BY symbol")]

    def kerzen_uebersicht(self) -> list[sqlite3.Row]:
        """Jüngste Kerze je Symbol und Zeitrahmen."""
        with self.conn() as c:
            return list(c.execute(
                "SELECT symbol, zeitrahmen, MAX(ts) AS juengste FROM kerzen "
                "GROUP BY symbol, zeitrahmen ORDER BY symbol, zeitrahmen"
            ))

    def juengste_kerze(self, symbol: str, zeitrahmen: str, *,
                       c: sqlite3.Connection | None = None) -> str | None:
        """Jüngster Zeitstempel einer Reihe, auch innerhalb einer Transaktion."""
        sql = "SELECT MAX(ts) FROM kerzen WHERE symbol=? AND zeitrahmen=?"
        if c is not None:
            zeile = c.execute(sql, (symbol, zeitrahmen)).fetchone()
        else:
            with self.conn() as verbindung:
                zeile = verbindung.execute(sql, (symbol, zeitrahmen)).fetchone()
        return None if zeile is None else zeile[0]

    # ---------- CSV-Importe ----------
    def datenimport_finden(
        self, sha256: str, symbol: str, zeitrahmen: str,
        zeitzone: str = "", versatz: str = "", *,
        c: sqlite3.Connection | None = None,
    ) -> sqlite3.Row | None:
        """Sucht einen bereits erfolgreich gebuchten Import derselben Quelle."""
        sql = (
            "SELECT * FROM datenimporte WHERE sha256=? AND symbol=?"
            " AND zeitrahmen=? AND zeitzone=? AND versatz=?"
        )
        werte = (sha256, symbol, zeitrahmen, zeitzone, versatz)
        if c is not None:
            return c.execute(sql, werte).fetchone()
        with self.conn() as verbindung:
            return verbindung.execute(sql, werte).fetchone()

    def datenimport_merken(
        self, *, sha256: str, datei: str, symbol: str, zeitrahmen: str,
        zeitzone: str = "", versatz: str = "", kerzen: int,
        von: str, bis: str, c: sqlite3.Connection | None = None,
    ) -> None:
        """Bucht eine Datei nach erfolgreichem Import; mit ``c`` transaktional."""
        sql = (
            "INSERT INTO datenimporte(sha256,datei,symbol,zeitrahmen,zeitzone,"
            "versatz,kerzen,von,bis,importiert_am) VALUES (?,?,?,?,?,?,?,?,?,?)"
        )
        werte = (sha256, datei, symbol, zeitrahmen, zeitzone, versatz,
                 int(kerzen), von, bis, jetzt())
        if c is not None:
            c.execute(sql, werte)
            return
        with self.conn() as verbindung:
            verbindung.execute(sql, werte)

    def datenimporte(self) -> list[sqlite3.Row]:
        """Alle gebuchten CSV-Importe, älteste zuerst (für Prüfung und Anzeige)."""
        with self.conn() as c:
            return list(c.execute("SELECT * FROM datenimporte ORDER BY id"))

    def datenimport_vorhanden(self, symbol: str, zeitrahmen: str, *,
                              c: sqlite3.Connection | None = None) -> bool:
        """Kennt der Ledger diese Reihe bereits, auch ohne aktuelle Kerzen?"""
        sql = "SELECT 1 FROM datenimporte WHERE symbol=? AND zeitrahmen=? LIMIT 1"
        werte = (symbol, zeitrahmen)
        if c is not None:
            return c.execute(sql, werte).fetchone() is not None
        with self.conn() as verbindung:
            return verbindung.execute(sql, werte).fetchone() is not None

    def datenimport_entfernen(self, import_id: int, *,
                              c: sqlite3.Connection | None = None) -> None:
        """Entfernt eine nicht mehr durch Kerzen gedeckte Ledger-Buchung.

        Nur die Reconciliation verwendet das: Der anschliessende Import legt
        dieselbe Quelle neu an. Innerhalb der Importtransaktion ist der Effekt
        bei einem Fehler automatisch zurückgerollt.
        """
        if c is not None:
            c.execute("DELETE FROM datenimporte WHERE id=?", (int(import_id),))
            return
        with self.conn() as verbindung:
            verbindung.execute("DELETE FROM datenimporte WHERE id=?", (int(import_id),))

    def kerzen_abgedeckt(self, symbol: str, zeitrahmen: str, *,
                         mindest: int, bis: str, von: str = "",
                         c: sqlite3.Connection | None = None) -> bool:
        """Prüft, ob eine Ledger-Buchung noch durch die Zielreihe gedeckt ist.

        Der Ledger kann nach einem Teil-Restore vorhanden sein, während Kerzen
        fehlen. Mit ``von``/``bis`` wird der Buchungsbereich gezählt, ohne
        ``von`` die gesamte Reihe (Bootstrap-Marker). Der gespeicherte
        Endzeitpunkt muss vorhanden sein und die Zahl der Kerzen mindestens der
        Buchung entsprechen. Das ist bewusst eine Plausibilitätsprüfung, kein
        Beweis für jede einzelne Kerze: Überlappende Importe dürfen die Zahl
        erhöhen.
        """
        if int(mindest) <= 0 or not str(bis or ""):
            return False
        sql = ("SELECT COUNT(*), MAX(ts) FROM kerzen"
               " WHERE symbol=? AND zeitrahmen=?")
        werte: list[Any] = [symbol, zeitrahmen]
        if str(von or ""):
            sql += " AND ts BETWEEN ? AND ?"
            werte.extend([str(von), str(bis)])
        if c is not None:
            zeile = c.execute(sql, tuple(werte)).fetchone()
        else:
            with self.conn() as verbindung:
                zeile = verbindung.execute(sql, tuple(werte)).fetchone()
        if zeile is None:
            return False
        anzahl = int(zeile[0] or 0)
        juengste = zeile[1]
        return anzahl >= int(mindest) and juengste is not None and str(juengste) >= str(bis)

    # ---------- Validierungen ----------
    def validierung_speichern(
        self, symbol: str, strategie: str, schluessel: str, parameter: dict[str, Any],
        urteil: str, beschreibung: str, bericht: dict[str, Any],
        trades: Sequence[dict[str, Any]] = (), lauf: str = "",
    ) -> int:
        """Speichert eine Bewertung; ein unverändertes Ergebnis bleibt eine Zeile.

        Der Richter rechnet bei jedem Lauf über dieselben Kerzen dasselbe
        Ergebnis. Ohne diese Prüfung entstünde je Takt eine neue Validierung
        samt vollständiger Trade-Liste: ``trades`` wüchse mit der Zahl der
        Läufe, und jede Zählung über die Tabelle wäre um genau diesen Faktor
        zu hoch.

        Gleich heisst: gleiche Konfiguration, gleiche Trades **und dasselbe
        Urteil**. Dann wird die vorhandene Zeile dem aktuellen Lauf
        zugeordnet; ``erstellt`` und ``lauf`` wandern gemeinsam, damit eine
        Zeile nie einen alten Erstellungszeitpunkt mit einem neuen Lauf trägt.
        Ein anderes Urteil ist eine neue Bewertung und wird eingefügt — die
        frühere Zeile bleibt mit ihrem Urteil und ihrem Lauf erhalten.
        """
        with self.conn() as c:
            gleich = self._gleiche_validierung(c, symbol, strategie, schluessel,
                                               urteil, trades)
            if gleich is not None:
                c.execute(
                    "UPDATE validierungen SET erstellt=?, lauf=?, parameter=?,"
                    " beschreibung=?, bericht=? WHERE id=?",
                    (jetzt(), lauf, json.dumps(parameter, ensure_ascii=False), beschreibung,
                     json.dumps(bericht, ensure_ascii=False), gleich),
                )
                return gleich
            cur = c.execute(
                "INSERT INTO validierungen(erstellt,lauf,symbol,strategie,schluessel,parameter,urteil,beschreibung,bericht)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (jetzt(), lauf, symbol, strategie, schluessel,
                 json.dumps(parameter, ensure_ascii=False),
                 urteil, beschreibung, json.dumps(bericht, ensure_ascii=False)),
            )
            vid = int(cur.lastrowid or 0)
            if trades:
                c.executemany(
                    "INSERT INTO trades(validierung_id,symbol,einstieg,ausstieg,stueck,netto,rendite_pct,grund)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    [(vid, symbol, t["einstieg"], t["ausstieg"], t["stueck"], t["netto"],
                      t["rendite_pct"], t["grund"]) for t in trades],
                )
        return vid

    @staticmethod
    def _gleiche_validierung(
        c: sqlite3.Connection, symbol: str, strategie: str, schluessel: str,
        urteil: str, trades: Sequence[dict[str, Any]],
    ) -> int | None:
        """id einer bereits gespeicherten, inhaltsgleichen Bewertung.

        Das Urteil gehört zur Identität: eine andere Bewertung darf die
        gespeicherte nicht ersetzen. Bei gleichem Urteil sind die Trades der
        Beleg — gleiche Konfiguration, gleiche Kurse und gleiche Ausstiege
        bedeuten dieselbe Bewertung. Ohne Trades bleibt nur das Urteil als
        Unterscheidung; feiner ist die Bewertung dann nicht belegt.
        """
        kandidaten = c.execute(
            "SELECT id, urteil FROM validierungen"
            " WHERE symbol=? AND strategie=? AND schluessel=? ORDER BY id",
            (symbol, strategie, schluessel),
        ).fetchall()
        if not kandidaten:
            return None
        neu = [(str(t["einstieg"]), str(t["ausstieg"]), float(t["stueck"]),
                float(t["netto"]), float(t["rendite_pct"]), str(t["grund"]))
               for t in trades]
        for zeile in kandidaten:
            if zeile["urteil"] != urteil:
                continue
            vid = int(zeile["id"])
            if not neu:
                return vid
            alt = [(str(r["einstieg"]), str(r["ausstieg"]), float(r["stueck"]),
                    float(r["netto"]), float(r["rendite_pct"]), str(r["grund"]))
                   for r in c.execute(
                       "SELECT einstieg,ausstieg,stueck,netto,rendite_pct,grund"
                       " FROM trades WHERE validierung_id=? ORDER BY id", (vid,))]
            if alt == neu:
                return vid
        return None

    def letzte_validierungen(self, lauf: str | None = None) -> list[sqlite3.Row]:
        with self.conn() as c:
            if lauf:
                return list(c.execute(
                    "SELECT * FROM validierungen WHERE lauf=? ORDER BY symbol, strategie", (lauf,)
                ))
            return list(c.execute(
                "SELECT * FROM validierungen WHERE id IN ("
                "SELECT MAX(id) FROM validierungen GROUP BY symbol, schluessel)"
                " ORDER BY symbol, strategie"
            ))

    def alle_validierungen(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM validierungen ORDER BY id DESC"))

    # ---------- Auswahl ----------
    def auswahl_setzen(self, symbol: str, schluessel: str, validierung_id: int) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO auswahl(symbol,schluessel,validierung_id,zeit) VALUES (?,?,?,?)",
                (symbol, schluessel, validierung_id, jetzt()),
            )

    def auswahl_loeschen(self, symbol: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM auswahl WHERE symbol=?", (symbol,))

    def auswahl(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM auswahl ORDER BY symbol"))

    # ---------- Entscheide ----------
    def entscheid_speichern(self, symbol: str, aktion: str, menge: float | None, kurs: float | None,
                            strategie: str | None, status: str, genehmigt: bool,
                            gruende: Sequence[str]) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO entscheide(zeit,symbol,aktion,menge,kurs,strategie,status,genehmigt,gruende)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (jetzt(), symbol, aktion, menge, kurs, strategie, status, int(genehmigt),
                 json.dumps(list(gruende), ensure_ascii=False)),
            )
            return int(cur.lastrowid or 0)

    def entscheide(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM entscheide ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- Ereignisse ----------
    def ereignis(self, stufe: str, quelle: str, text: str) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO ereignisse(zeit,stufe,quelle,text) VALUES (?,?,?,?)",
                      (jetzt(), stufe, quelle, text))

    def ereignisse(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM ereignisse ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- Konto ----------
    def konto_speichern(self, equity: float, cash: float, positionen: int, hoechststand: float) -> None:
        with self.conn() as c:
            c.execute("INSERT INTO konto(zeit,equity,cash,positionen,hoechststand) VALUES (?,?,?,?,?)",
                      (jetzt(), equity, cash, positionen, hoechststand))

    def letztes_konto(self) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM konto ORDER BY id DESC LIMIT 1").fetchone()

    # ---------- Agenten ----------
    def agenten_lauf(
        self, agent: str, abteilung: str, aufgabe: str, ergebnis: str, ok: bool, *,
        c: sqlite3.Connection | None = None,
    ) -> None:
        """Schreibt einen Agentenlauf.

        Mit ``c`` läuft der Insert in der bereits offenen Transaktion des
        Aufrufers; ohne ``c`` wird er wie bisher sofort committet. So kann der
        Lauf gemeinsam mit dem Task-Status gebucht oder zurückgerollt werden.
        """
        sql = ("INSERT INTO agenten_laeufe(zeit,agent,abteilung,aufgabe,ergebnis,ok)"
               " VALUES (?,?,?,?,?,?)")
        werte = (jetzt(), agent, abteilung, aufgabe, ergebnis, int(ok))
        if c is not None:
            c.execute(sql, werte)
            return
        with self.conn() as conn:
            conn.execute(sql, werte)

    def agenten_laeufe(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM agenten_laeufe ORDER BY id DESC LIMIT ?", (limit,)))

    # ---------- Positionen ----------
    def positionen(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM positionen ORDER BY symbol"))

    def position_setzen(self, symbol: str, menge: float, einstieg: float, stop: float,
                        strategie: str, eroeffnet: str) -> None:
        """Legt eine Long-Position an.

        Der Paper-Takt und der Backtest sind Long-only. Eine Menge <= 0 würde
        eine Short-Position ohne Richtungslogik erzeugen und wird deshalb
        abgelehnt, statt sie stillschweigend als Long zu buchen.
        """
        if not math.isfinite(float(menge)) or float(menge) <= 0:
            raise ValueError(f'Position {symbol}: Menge muss positiv und endlich sein, '
                             f'ist aber {menge!r}')
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO positionen(symbol,menge,einstieg,stop,strategie,eroeffnet)"
                " VALUES (?,?,?,?,?,?)",
                (symbol, menge, einstieg, stop, strategie, eroeffnet),
            )

    def position_loeschen(self, symbol: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM positionen WHERE symbol=?", (symbol,))

    def validierung(self, vid: int) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM validierungen WHERE id=?", (vid,)).fetchone()

    # ---------- Artikel (Spider Intelligence) ----------
    def artikel_speichern(
        self, quelle: str, typ: str, titel: str, url: str, veroeffentlicht: str | None,
        zusammenfassung: str, qualitaet: float, symbole: list[str], titel_hash: str,
        prioritaet: str = "", prioritaet_grund: str = "", erkannt: str | None = None,
    ) -> int | None:
        """Speichert einen Artikel und gibt seine id zurück. None = Dublette.

        `erkannt` ist der Zeitpunkt, an dem Orakel die Meldung gesehen hat —
        getrennt von `veroeffentlicht`, damit Verzögerungen sichtbar bleiben.
        """
        with self.conn() as c:
            bekannt = c.execute(
                "SELECT 1 FROM artikel WHERE url=? OR titel_hash=? LIMIT 1", (url, titel_hash)
            ).fetchone()
            if bekannt:
                return None
            cur = c.execute(
                "INSERT INTO artikel(geholt,quelle,typ,titel,url,veroeffentlicht,zusammenfassung,"
                "qualitaet,symbole,titel_hash,prioritaet,prioritaet_grund,erkannt)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (jetzt(), quelle, typ, titel, url, veroeffentlicht, zusammenfassung,
                 qualitaet, json.dumps(symbole, ensure_ascii=False), titel_hash,
                 prioritaet, prioritaet_grund, erkannt or jetzt()),
            )
            return int(cur.lastrowid or 0) or None

    def artikel_ohne_prioritaet(self, limit: int = 500) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM artikel WHERE prioritaet='' ORDER BY id DESC LIMIT ?", (limit,)
            ))

    def artikel_prioritaet_setzen(self, aid: int, prioritaet: str, grund: str) -> int:
        with self.conn() as c:
            return c.execute(
                "UPDATE artikel SET prioritaet=?, prioritaet_grund=? WHERE id=?",
                (prioritaet, grund, aid),
            ).rowcount

    def artikel(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM artikel ORDER BY id DESC LIMIT ?", (limit,)
            ))

    def artikel_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = c.execute("SELECT COUNT(*) n FROM artikel").fetchone()["n"]
            nach_typ = [dict(r) for r in c.execute(
                "SELECT typ, COUNT(*) n, AVG(qualitaet) q FROM artikel GROUP BY typ ORDER BY n DESC"
            )]
            nach_quelle = [dict(r) for r in c.execute(
                "SELECT quelle, COUNT(*) n FROM artikel GROUP BY quelle ORDER BY n DESC LIMIT 10"
            )]
        return {"gesamt": gesamt, "typen": nach_typ, "quellen": nach_quelle}

    def artikel_id_by_url_oder_hash(self, url: str, titel_hash: str) -> int | None:
        """Findet ein bereits vorhandenes Original, ohne es erneut zu speichern."""
        with self.conn() as c:
            zeile = c.execute(
                "SELECT id FROM artikel WHERE url=? OR titel_hash=? LIMIT 1",
                (url, titel_hash),
            ).fetchone()
        return int(zeile["id"]) if zeile else None

    # ---------- Nexus: Meldungen und Dubletten ----------
    def nexus_meldung(self, meldung_key: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM nexus_meldungen WHERE meldung_key=?", (meldung_key,)
            ).fetchone()

    def nexus_meldung_speichern(
        self, meldung_key: str, artikel_id: int, cluster_id: str, simhash: str,
        sprache: str, konfidenz: float, methode: str, ist_original: bool,
        quelle_id: str, titel: str, zusammenfassung: str, url: str,
        abgerufen_am: str,
    ) -> bool:
        """Speichert eine Meldung. False = key war schon vorhanden."""
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO nexus_meldungen(meldung_key,artikel_id,cluster_id,simhash,"
                "sprache,sprache_konfidenz,sprache_methode,ist_original,quelle_id,"
                "titel,zusammenfassung,url,abgerufen_am)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(meldung_key) DO NOTHING",
                (meldung_key, int(artikel_id), cluster_id, simhash, sprache,
                 float(konfidenz), methode, int(ist_original), quelle_id, titel,
                 zusammenfassung, url, abgerufen_am),
            )
            return bool(cur.rowcount)

    def nexus_originale(self) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT meldung_key, artikel_id, cluster_id, simhash, titel, "
                "zusammenfassung FROM nexus_meldungen WHERE ist_original=1 ORDER BY id"
            ))

    def nexus_meldungen(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM nexus_meldungen ORDER BY id DESC LIMIT ?", (limit,)
            ))

    def nexus_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_meldungen").fetchone()["n"])
            originale = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_meldungen WHERE ist_original=1"
            ).fetchone()["n"])
            cluster = int(c.execute(
                "SELECT COUNT(DISTINCT cluster_id) n FROM nexus_meldungen"
            ).fetchone()["n"])
            nach_sprache = [dict(r) for r in c.execute(
                "SELECT sprache, COUNT(*) n FROM nexus_meldungen "
                "GROUP BY sprache ORDER BY n DESC, sprache"
            )]
        dubletten = gesamt - originale
        return {
            "gesamt": gesamt,
            "originale": originale,
            "dubletten": dubletten,
            "dublettenquote": round(dubletten / gesamt, 3) if gesamt else 0.0,
            "cluster": cluster,
            "nach_sprache": nach_sprache,
        }

    def nexus_meldungen_alle(self) -> list[sqlite3.Row]:
        """Alle Meldungen für den deterministischen Bewertungs-Rebuild."""
        with self.conn() as c:
            return list(c.execute("SELECT * FROM nexus_meldungen ORDER BY id"))

    # ---------- Nexus Phase 3: Quellenreputation, Claims, Widersprüche ----------
    def nexus_bewertung_ersetzen(
        self,
        quellen: Sequence[dict[str, Any]],
        claims: Sequence[dict[str, Any]],
        claim_quellen: Sequence[dict[str, Any]],
        widersprueche: Sequence[dict[str, Any]],
    ) -> None:
        """Ersetzt den Bewertungsstand atomar. Kein halber Rebuild bleibt sichtbar."""
        with self.conn() as c:
            for tabelle in ("nexus_claim_quellen", "nexus_widersprueche",
                            "nexus_claims", "nexus_quellen_reputation"):
                c.execute(f"DELETE FROM {tabelle}")  # noqa: S608 - Tabellenname ist eine feste interne Liste
            if quellen:
                c.executemany(
                    "INSERT INTO nexus_quellen_reputation(quelle_id,name,host,gewicht,"
                    "artikel,analysiert,bestaetigt,widerlegt,widersprueche,reputation,"
                    "vertrauen,aktualisiert) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[k] for k in (
                        "quelle_id", "name", "host", "gewicht", "artikel",
                        "analysiert", "bestaetigt", "widerlegt", "widersprueche",
                        "reputation", "vertrauen", "aktualisiert")) for r in quellen],
                )
            def wert(zeile: dict[str, Any], schluessel: str) -> Any:
                if schluessel in ("zeitraum", "bedingung"):
                    return str(zeile.get(schluessel) or "")
                if schluessel == "sicherheit":
                    roh = zeile.get(schluessel)
                    return round(max(0.0, min(1.0, float(roh if roh is not None else 0.5))), 3)
                return zeile[schluessel]

            if claims:
                c.executemany(
                    "INSERT INTO nexus_claims(id,claim_key,kernaussage,thema,subjekt,"
                    "metrik,zeitraum,bedingung,sicherheit,quellen,belege,widersprueche,"
                    "bestaetigungsgrad,status,erstmals,aktualisiert) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(wert(r, k) for k in (
                        "id", "claim_key", "kernaussage", "thema", "subjekt",
                        "metrik", "zeitraum", "bedingung", "sicherheit", "quellen",
                        "belege", "widersprueche", "bestaetigungsgrad", "status",
                        "erstmals", "aktualisiert")) for r in claims],
                )
            if claim_quellen:
                c.executemany(
                    "INSERT INTO nexus_claim_quellen(id,claim_id,meldung_key,artikel_id,"
                    "quelle_id,host,aussage,richtung,wert,einheit,negiert,zeitraum,"
                    "bedingung,sicherheit,ist_kopie,reputation,erstellt) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(wert(r, k) for k in (
                        "id", "claim_id", "meldung_key", "artikel_id", "quelle_id",
                        "host", "aussage", "richtung", "wert", "einheit",
                        "negiert", "zeitraum", "bedingung", "sicherheit", "ist_kopie",
                        "reputation", "erstellt"))
                     for r in claim_quellen],
                )
            if widersprueche:
                c.executemany(
                    "INSERT INTO nexus_widersprueche(id,claim_id,meldung_a,meldung_b,"
                    "quelle_a,quelle_b,grund,sicherheit,wert_a_bp,wert_b_bp,erstellt) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [tuple(r[k] for k in (
                        "id", "claim_id", "meldung_a", "meldung_b", "quelle_a",
                        "quelle_b", "grund", "sicherheit"))
                     + (r.get("wert_a_bp"), r.get("wert_b_bp"), r["erstellt"])
                     for r in widersprueche],
                )

    def nexus_quellen_reputation(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM nexus_quellen_reputation "
                "ORDER BY reputation DESC, artikel DESC, name"
            )]

    def nexus_claims(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        with self.conn() as c:
            if status:
                zeilen = c.execute(
                    "SELECT * FROM nexus_claims WHERE status=? "
                    "ORDER BY bestaetigungsgrad DESC, quellen DESC, id DESC LIMIT ?",
                    (status, int(limit)),
                )
            else:
                zeilen = c.execute(
                    "SELECT * FROM nexus_claims "
                    "ORDER BY bestaetigungsgrad DESC, quellen DESC, id DESC LIMIT ?",
                    (int(limit),),
                )
            return [dict(r) for r in zeilen]

    def nexus_widersprueche(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT w.*, c.claim_key, c.kernaussage, c.status AS claim_status "
                "FROM nexus_widersprueche w JOIN nexus_claims c ON c.id=w.claim_id "
                "ORDER BY w.sicherheit DESC, w.id DESC LIMIT ?",
                (int(limit),),
            )
            return [dict(r) for r in zeilen]

    def nexus_claim_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = int(c.execute("SELECT COUNT(*) n FROM nexus_claims").fetchone()["n"])
            nach_status = {r["status"]: int(r["n"]) for r in c.execute(
                "SELECT status, COUNT(*) n FROM nexus_claims GROUP BY status")}
            belege = int(c.execute(
                "SELECT COALESCE(SUM(belege),0) n FROM nexus_claims").fetchone()["n"])
            widersprueche = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_widersprueche").fetchone()["n"])
            quellen = int(c.execute(
                "SELECT COUNT(*) n FROM nexus_quellen_reputation").fetchone()["n"])
            grad = c.execute(
                "SELECT COALESCE(AVG(bestaetigungsgrad),0) w FROM nexus_claims").fetchone()["w"]
        return {
            "gesamt": gesamt,
            "nach_status": nach_status,
            "belege": belege,
            "widersprueche": widersprueche,
            "quellen": quellen,
            "bestaetigungsgrad": round(float(grad or 0.0), 3),
        }

    # ---------- Nexus Phase 4: Missionen, Queue und Retry ----------
    def nexus_mission_zaehler(self, tag: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM nexus_missionen WHERE kennung LIKE ?",
                          (f"MS-{tag}-%",)).fetchone()
        return int(r["n"])

    def nexus_mission_kennung_existiert(self, kennung: str) -> bool:
        with self.conn() as c:
            return c.execute("SELECT 1 FROM nexus_missionen WHERE kennung=? LIMIT 1",
                             (kennung,)).fetchone() is not None

    def nexus_mission_anlegen(
        self, kennung: str, titel: str, auftrag: str, prioritaet: str,
        tasks: Sequence[dict[str, Any]], erstellt: str,
    ) -> dict[str, Any]:
        """Legt Mission und Aufgabenkette in einer Transaktion an."""
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO nexus_missionen(kennung,titel,auftrag,status,prioritaet,"
                "fortschritt,erstellt,bericht) VALUES (?,?,?,'offen',?,0,?,'')",
                (kennung, titel, auftrag, prioritaet, erstellt),
            )
            mission_id = int(cur.lastrowid or 0)
            vorgaenger: int | None = None
            for position, aufgabe in enumerate(tasks):
                cur = c.execute(
                    "INSERT INTO nexus_tasks(mission_id,position,rolle,ziel,status,"
                    "versuche,max_versuche,lease_bis,faellig_am,ergebnis,fehler,"
                    "abhaengig_von,erstellt,aktualisiert) "
                    "VALUES (?,?,?,?,'offen',0,?,NULL,?,'','',?,?,?)",
                    (mission_id, position, str(aufgabe["rolle"]), str(aufgabe["ziel"]),
                     int(aufgabe.get("max_versuche", 3)), erstellt,
                     vorgaenger, erstellt, erstellt),
                )
                vorgaenger = int(cur.lastrowid or 0)
        return self.nexus_mission(kennung) or {}

    def nexus_mission(self, kennung: str) -> dict[str, Any] | None:
        with self.conn() as c:
            zeile = c.execute("SELECT * FROM nexus_missionen WHERE kennung=?",
                              (kennung,)).fetchone()
            if not zeile:
                return None
            tasks = [dict(r) for r in c.execute(
                "SELECT * FROM nexus_tasks WHERE mission_id=? ORDER BY position, id",
                (int(zeile["id"]),),
            )]
        mission = dict(zeile)
        mission["bericht"] = _json_wert(mission.get("bericht") or "", {}) or {}
        for task in tasks:
            task["ergebnis"] = _json_wert(task.get("ergebnis") or "", {}) or {}
        mission["tasks"] = tasks
        return mission

    def nexus_missionen(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT m.*, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id) AS tasks, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id AND t.status='erledigt') AS erledigt, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id AND t.status='offen') AS offen, "
                "(SELECT COUNT(*) FROM nexus_tasks t WHERE t.mission_id=m.id AND t.status='fehlgeschlagen') AS fehlgeschlagen "
                "FROM nexus_missionen m "
                "ORDER BY CASE m.status WHEN 'laufend' THEN 0 WHEN 'offen' THEN 1 "
                "WHEN 'fehlgeschlagen' THEN 2 ELSE 3 END, m.erstellt DESC, m.id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        ergebnis = []
        for zeile in zeilen:
            eintrag = dict(zeile)
            eintrag["bericht_vorhanden"] = bool(eintrag.pop("bericht", ""))
            ergebnis.append(eintrag)
        return ergebnis

    def nexus_mission_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            gesamt = int(c.execute("SELECT COUNT(*) n FROM nexus_missionen").fetchone()["n"])
            nach_status = {r["status"]: int(r["n"]) for r in c.execute(
                "SELECT status, COUNT(*) n FROM nexus_missionen GROUP BY status")}
            tasks = {r["status"]: int(r["n"]) for r in c.execute(
                "SELECT status, COUNT(*) n FROM nexus_tasks GROUP BY status")}
            fortschritt = c.execute(
                "SELECT COALESCE(AVG(fortschritt),0) w FROM nexus_missionen").fetchone()["w"]
        return {"gesamt": gesamt, "nach_status": nach_status,
                "tasks": tasks, "fortschritt": round(float(fortschritt or 0.0), 1)}

    def nexus_task(self, task_id: int) -> dict[str, Any] | None:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung, m.titel, m.auftrag, m.prioritaet "
                "FROM nexus_tasks t JOIN nexus_missionen m ON m.id=t.mission_id WHERE t.id=?",
                (int(task_id),),
            ).fetchone()
        if not zeile:
            return None
        task = dict(zeile)
        task["ergebnis"] = _json_wert(task.get("ergebnis") or "", {}) or {}
        return task

    def nexus_task_naechste(self, jetzt: str, lease_bis: str,
                            mission_kennung: str | None = None) -> dict[str, Any] | None:
        """Least eine fällige Aufgabe atomar. Abhängigkeiten werden geprüft."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            bedingung = " AND m.kennung=?" if mission_kennung else ""
            args: list[Any] = [jetzt]
            if mission_kennung:
                args.append(mission_kennung)
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung, m.titel, m.auftrag, "  # noqa: S608 - SQL-Gerüst aus festen Spaltennamen, Werte als Parameter
                "m.prioritaet, m.status AS mission_status "
                "FROM nexus_tasks t JOIN nexus_missionen m ON m.id=t.mission_id "
                "WHERE t.status='offen' AND t.faellig_am<=? "
                "AND m.status IN ('offen','laufend') "
                "AND (t.abhaengig_von IS NULL OR EXISTS ("
                "  SELECT 1 FROM nexus_tasks v WHERE v.id=t.abhaengig_von AND v.status='erledigt'"
                ")) " + bedingung + " "
                "ORDER BY CASE m.prioritaet WHEN 'kritisch' THEN 0 WHEN 'hoch' THEN 1 "
                "WHEN 'mittel' THEN 2 ELSE 3 END, m.erstellt, t.position, t.id LIMIT 1",
                tuple(args),
            ).fetchone()
            if not zeile:
                return None
            c.execute(
                "UPDATE nexus_tasks SET status='laufend', versuche=versuche+1, "
                "lease_bis=?, aktualisiert=? WHERE id=?",
                (lease_bis, jetzt, int(zeile["id"])),
            )
            c.execute(
                "UPDATE nexus_missionen SET status='laufend', "
                "gestartet=COALESCE(gestartet, ?) WHERE id=?",
                (jetzt, int(zeile["mission_id"])),
            )
            task = dict(zeile)
            task["status"] = "laufend"
            task["versuche"] = int(zeile["versuche"]) + 1
            task["lease_bis"] = lease_bis
            return task

    def _mission_fehlerhaft(self, c: sqlite3.Connection, mission_id: int,
                             position: int, fehler: str, jetzt: str) -> None:
        """Blockiert Folgeschritte und markiert die Mission als abgebrochen."""
        c.execute(
            "UPDATE nexus_tasks SET status='blockiert', fehler=?, aktualisiert=?, "
            "fehlgeschlagen_am=? "
            "WHERE mission_id=? AND position>? AND status IN ('offen','laufend')",
            ("Vorgänger fehlgeschlagen", jetzt, jetzt, int(mission_id), int(position)),
        )
        zahlen = c.execute(
            "SELECT COUNT(*) gesamt, "
            "SUM(CASE WHEN status='erledigt' THEN 1 ELSE 0 END) erledigt "
            "FROM nexus_tasks WHERE mission_id=?", (int(mission_id),),
        ).fetchone()
        gesamt = int(zahlen["gesamt"] or 0)
        erledigt = int(zahlen["erledigt"] or 0)
        fortschritt = round(erledigt / gesamt * 100) if gesamt else 0
        bericht = json.dumps({
            "fehler": fehler,
            "text": f"Mission abgebrochen: {fehler}",
            "generiert": jetzt,
        }, ensure_ascii=False)
        c.execute(
            "UPDATE nexus_missionen SET status='fehlgeschlagen', fortschritt=?, "
            "beendet=?, bericht=? WHERE id=?",
            (fortschritt, jetzt, bericht, int(mission_id)),
        )

    def nexus_task_leases_loesen(self, jetzt: str) -> int:
        """Gibt abgelaufene Leases frei; nach dem letzten Versuch: Dead-Letter."""
        freigegeben = 0
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung FROM nexus_tasks t "
                "JOIN nexus_missionen m ON m.id=t.mission_id "
                "WHERE t.status='laufend' AND t.lease_bis IS NOT NULL AND t.lease_bis<?",
                (jetzt,),
            ).fetchall()
            for zeile in zeilen:
                task = dict(zeile)
                endgueltig = int(task["versuche"]) >= int(task["max_versuche"])
                if endgueltig:
                    c.execute(
                        "UPDATE nexus_tasks SET status='fehlgeschlagen', lease_bis=NULL, "
                        "fehler=?, aktualisiert=?, fehlgeschlagen_am=? WHERE id=?",
                        ("Lease abgelaufen; letzter Versuch verbraucht", jetzt, jetzt,
                         int(task["id"])),
                    )
                    self._mission_fehlerhaft(
                        c, int(task["mission_id"]), int(task["position"]),
                        "Lease abgelaufen; letzter Versuch verbraucht", jetzt,
                    )
                else:
                    c.execute(
                        "UPDATE nexus_tasks SET status='offen', lease_bis=NULL, "
                        "faellig_am=?, fehler=?, aktualisiert=? WHERE id=?",
                        (jetzt, "Lease abgelaufen; neuer Versuch", jetzt, int(task["id"])),
                    )
                    c.execute(
                        "UPDATE nexus_missionen SET status='offen' WHERE id=?",
                        (int(task["mission_id"]),),
                    )
                freigegeben += 1
        return freigegeben

    def nexus_task_erledigt(self, task_id: int, ergebnis: dict[str, Any],
                            bericht: dict[str, Any] | None, jetzt: str) -> dict[str, Any]:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung FROM nexus_tasks t "
                "JOIN nexus_missionen m ON m.id=t.mission_id WHERE t.id=?",
                (int(task_id),),
            ).fetchone()
            if not zeile:
                raise ValueError(f"Unbekannte Aufgabe: {task_id}")
            if zeile["status"] == "erledigt":
                kennung = str(zeile["mission_kennung"])
            else:
                c.execute(
                    "UPDATE nexus_tasks SET status='erledigt', lease_bis=NULL, "
                    "ergebnis=?, fehler='', aktualisiert=?, abgeschlossen_am=? WHERE id=?",
                    (json.dumps(ergebnis, ensure_ascii=False), jetzt, jetzt, int(task_id)),
                )
                zahlen = c.execute(
                    "SELECT COUNT(*) gesamt, "
                    "SUM(CASE WHEN status='erledigt' THEN 1 ELSE 0 END) erledigt "
                    "FROM nexus_tasks WHERE mission_id=?", (int(zeile["mission_id"]),),
                ).fetchone()
                gesamt = int(zahlen["gesamt"] or 0)
                erledigt = int(zahlen["erledigt"] or 0)
                fortschritt = round(erledigt / gesamt * 100) if gesamt else 0
                kennung = str(zeile["mission_kennung"])
                if erledigt >= gesamt:
                    c.execute(
                        "UPDATE nexus_missionen SET status='abgeschlossen', fortschritt=100, "
                        "beendet=?, bericht=? WHERE id=?",
                        (jetzt, json.dumps(bericht or {}, ensure_ascii=False),
                         int(zeile["mission_id"])),
                    )
                else:
                    c.execute(
                        "UPDATE nexus_missionen SET status='offen', fortschritt=? WHERE id=?",
                        (fortschritt, int(zeile["mission_id"])),
                    )
        return self.nexus_mission(kennung) or {}

    def nexus_task_fehler(self, task_id: int, fehler: str, faellig_am: str,
                          endgueltig: bool, jetzt: str) -> dict[str, Any]:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT t.*, m.kennung AS mission_kennung FROM nexus_tasks t "
                "JOIN nexus_missionen m ON m.id=t.mission_id WHERE t.id=?",
                (int(task_id),),
            ).fetchone()
            if not zeile:
                raise ValueError(f"Unbekannte Aufgabe: {task_id}")
            status = "fehlgeschlagen" if endgueltig else "offen"
            c.execute(
                "UPDATE nexus_tasks SET status=?, lease_bis=NULL, faellig_am=?, "
                "fehler=?, aktualisiert=? WHERE id=?",
                (status, faellig_am, fehler, jetzt, int(task_id)),
            )
            if endgueltig:
                self._mission_fehlerhaft(
                    c, int(zeile["mission_id"]), int(zeile["position"]),
                    fehler, jetzt,
                )
            else:
                c.execute("UPDATE nexus_missionen SET status='offen' WHERE id=?",
                          (int(zeile["mission_id"]),))
            kennung = str(zeile["mission_kennung"])
        return self.nexus_mission(kennung) or {}

    def nexus_claims_by_ids(self, ids: Sequence[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        platzhalter = ",".join("?" for _ in ids)
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT * FROM nexus_claims WHERE id IN ({platzhalter}) ORDER BY id",  # noqa: S608 - nur «?»-Platzhalter, Werte als Parameter
                tuple(int(i) for i in ids),
            )]

    def nexus_claim_quellen_fuer(self, claim_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not claim_ids:
            return []
        platzhalter = ",".join("?" for _ in claim_ids)
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT * FROM nexus_claim_quellen WHERE claim_id IN ({platzhalter}) "  # noqa: S608 - nur «?»-Platzhalter, Werte als Parameter
                "ORDER BY claim_id, id",
                tuple(int(i) for i in claim_ids),
            )]

    def nexus_widersprueche_fuer(self, claim_ids: Sequence[int]) -> list[dict[str, Any]]:
        if not claim_ids:
            return []
        platzhalter = ",".join("?" for _ in claim_ids)
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT w.*, c.claim_key, c.kernaussage FROM nexus_widersprueche w "  # noqa: S608 - SQL-Gerüst aus festen Spaltennamen, Werte als Parameter
                f"JOIN nexus_claims c ON c.id=w.claim_id WHERE w.claim_id IN ({platzhalter}) "
                "ORDER BY w.sicherheit DESC, w.id",
                tuple(int(i) for i in claim_ids),
            )]

    # ---------- Nexus Phase 6: Wissensgraph und Prognosen ----------
    def nexus_graph_ersetzen(self, kanten: Sequence[dict[str, Any]]) -> None:
        """Ersetzt den persistierten Graph atomar. Idempotenter Rebuild."""
        with self.conn() as c:
            c.execute("DELETE FROM nexus_edges")
            if kanten:
                c.executemany(
                    "INSERT INTO nexus_edges(von,nach,art,begruendung,sicherheit,erstellt)"
                    " VALUES (?,?,?,?,?,?)",
                    [(str(k["von"]), str(k["nach"]), str(k["art"]),
                      str(k.get("begruendung") or ""),
                      round(max(0.0, min(1.0, float(k.get("sicherheit", 0.5)))), 3),
                      str(k["erstellt"])) for k in kanten],
                )

    def nexus_graph_edges(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM nexus_edges ORDER BY erstellt, id"
            )]

    def nexus_forecast_zaehler(self, tag: str) -> int:
        with self.conn() as c:
            r = c.execute(
                "SELECT COUNT(*) n FROM nexus_forecasts WHERE kennung LIKE ?",
                (f"FC-{tag}-%",),
            ).fetchone()
        return int(r["n"])

    def nexus_forecast(self, kennung: str) -> dict[str, Any] | None:
        with self.conn() as c:
            zeile = c.execute(
                "SELECT f.*, r.id AS result_id, r.eingetreten AS result_eingetreten,"
                " r.messwert AS result_messwert, r.geprueft_am AS result_geprueft_am,"
                " r.notiz AS result_notiz FROM nexus_forecasts f"
                " LEFT JOIN nexus_forecast_results r ON r.forecast_id=f.id"
                " WHERE f.kennung=?",
                (kennung,),
            ).fetchone()
        return _forecast_aus_zeile(zeile) if zeile else None

    def nexus_forecast_anlegen(self, daten: dict[str, Any]) -> dict[str, Any]:
        """Legt eine Prognose an oder aktualisiert dieselbe Kennung."""
        felder = (
            "kennung", "auftrag_id", "mission_kennung", "claim_id", "aussage",
            "erwartung", "zeithorizont", "faellig_am", "konfidenz", "symbol",
            "basiswert", "toleranz_pct", "status", "erstellt", "aktualisiert",
        )
        werte = tuple(daten.get(feld) for feld in felder)
        with self.conn() as c:
            c.execute(
                "INSERT INTO nexus_forecasts(kennung,auftrag_id,mission_kennung,claim_id,"
                "aussage,erwartung,zeithorizont,faellig_am,konfidenz,symbol,basiswert,"
                "toleranz_pct,status,erstellt,aktualisiert) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(kennung) DO UPDATE SET "
                "auftrag_id=excluded.auftrag_id, mission_kennung=excluded.mission_kennung,"
                "claim_id=excluded.claim_id, aussage=excluded.aussage,"
                "erwartung=excluded.erwartung, zeithorizont=excluded.zeithorizont,"
                "faellig_am=excluded.faellig_am, konfidenz=excluded.konfidenz,"
                "symbol=excluded.symbol, basiswert=excluded.basiswert,"
                "toleranz_pct=excluded.toleranz_pct, status=excluded.status,"
                "aktualisiert=excluded.aktualisiert",
                werte,
            )
        return self.nexus_forecast(str(daten["kennung"])) or {}

    def nexus_forecast_status_setzen(self, kennung: str, status: str,
                                     aktualisiert: str) -> None:
        with self.conn() as c:
            c.execute(
                "UPDATE nexus_forecasts SET status=?, aktualisiert=? WHERE kennung=?",
                (status, aktualisiert, kennung),
            )

    def nexus_forecast_result_speichern(
        self, forecast_id: int, eingetreten: int | None, messwert: float | None,
        geprueft_am: str, notiz: str = "",
    ) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO nexus_forecast_results(forecast_id,eingetreten,messwert,"
                "geprueft_am,notiz) VALUES (?,?,?,?,?) "
                "ON CONFLICT(forecast_id) DO UPDATE SET eingetreten=excluded.eingetreten,"
                "messwert=excluded.messwert, geprueft_am=excluded.geprueft_am,"
                "notiz=excluded.notiz",
                (int(forecast_id), None if eingetreten is None else int(eingetreten),
                 messwert, geprueft_am, notiz[:2000]),
            )

    def nexus_forecast_result_loeschen(self, forecast_id: int) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM nexus_forecast_results WHERE forecast_id=?",
                      (int(forecast_id),))

    def nexus_forecasts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT f.*, r.id AS result_id, r.eingetreten AS result_eingetreten,"
                " r.messwert AS result_messwert, r.geprueft_am AS result_geprueft_am,"
                " r.notiz AS result_notiz FROM nexus_forecasts f"
                " LEFT JOIN nexus_forecast_results r ON r.forecast_id=f.id"
                " ORDER BY COALESCE(f.faellig_am, f.erstellt) DESC, f.id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_forecast_aus_zeile(z) for z in zeilen]

    def artikel_by_ids(self, ids: Sequence[int]) -> list[sqlite3.Row]:
        if not ids:
            return []
        platzhalter = ",".join("?" for _ in ids)
        with self.conn() as c:
            return list(c.execute(f"SELECT * FROM artikel WHERE id IN ({platzhalter})", tuple(ids)))  # noqa: S608 - nur «?»-Platzhalter, Werte als Parameter

    def artikel_aktualisieren(self, artikel_id: int, qualitaet: float, symbole: list[str]) -> None:
        with self.conn() as c:
            c.execute("UPDATE artikel SET qualitaet=?, symbole=? WHERE id=?",
                      (qualitaet, json.dumps(symbole, ensure_ascii=False), artikel_id))

    def artikel_inhalt_speichern(self, artikel_id: int, text: str) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO intel_inhalte(artikel_id,text,zeichen,analysiert)"
                " VALUES (?,?,?,?)",
                (artikel_id, text, len(text), jetzt()),
            )

    def artikel_inhalt(self, artikel_id: int) -> str:
        with self.conn() as c:
            r = c.execute("SELECT text FROM intel_inhalte WHERE artikel_id=?", (artikel_id,)).fetchone()
        return r["text"] if r else ""

    # ---------- Spider Intelligence: Aufträge ----------
    def intel_zaehler(self, prefix: str, tag: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM intel_auftraege WHERE kennung LIKE ?",
                          (f"{prefix}-{tag}-%",)).fetchone()
        return int(r["n"])

    def intel_auftrag_speichern(self, daten: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_auftraege(kennung,zeit,abteilung,titel,problem,information,"
                "quellen,frage,hypothese,untersuchung,nutzen,risiko,art,bezug_symbol,"
                "bezug_schluessel,kurs_bei_erstellung,atr_bei_erstellung,status,ergebnis,aktualisiert)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (daten["kennung"], daten.get("zeit") or jetzt(), daten["abteilung"],
                 daten["titel"], daten.get("problem", ""), daten.get("information", ""),
                 json.dumps(daten.get("quellen") or [], ensure_ascii=False),
                 daten.get("frage", ""), daten.get("hypothese", ""),
                 daten.get("untersuchung", ""), daten.get("nutzen", ""),
                 daten.get("risiko", ""), daten.get("art", "allgemein"),
                 daten.get("bezug_symbol"), daten.get("bezug_schluessel"),
                 daten.get("kurs_bei_erstellung"), daten.get("atr_bei_erstellung"),
                 daten.get("status", "offen"), daten.get("ergebnis", ""), jetzt()),
            )

    def intel_auftraege(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute("SELECT * FROM intel_auftraege ORDER BY id DESC LIMIT ?", (limit,)))

    def intel_auftrag(self, kennung: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute("SELECT * FROM intel_auftraege WHERE kennung=?", (kennung,)).fetchone()

    def intel_offener_auftrag(self, art: str, bezug_symbol: str | None = None,
                              bezug_schluessel: str | None = None) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM intel_auftraege WHERE status='offen' AND art=?"
                " AND COALESCE(bezug_symbol,'')=COALESCE(?,'')"
                " AND COALESCE(bezug_schluessel,'')=COALESCE(?,'') LIMIT 1",
                (art, bezug_symbol, bezug_schluessel),
            ).fetchone()

    def intel_auftrag_existiert(self, art: str, bezug_symbol: str | None = None,
                                bezug_schluessel: str | None = None, tage: int = 7) -> bool:
        """Verhindert Wiederholungen — auch nach Abschluss eines Auftrags."""
        grenze = (datetime.now(timezone.utc) - timedelta(days=tage)).replace(
            microsecond=0).astimezone().isoformat()
        with self.conn() as c:
            r = c.execute(
                "SELECT 1 FROM intel_auftraege WHERE art=?"
                " AND COALESCE(bezug_symbol,'')=COALESCE(?,'')"
                " AND COALESCE(bezug_schluessel,'')=COALESCE(?,'')"
                " AND zeit>? LIMIT 1",
                (art, bezug_symbol, bezug_schluessel, grenze),
            ).fetchone()
        return r is not None

    def intel_status_setzen(self, kennung: str, status: str, ergebnis: str) -> int:
        with self.conn() as c:
            cur = c.execute("UPDATE intel_auftraege SET status=?, ergebnis=?, aktualisiert=? WHERE kennung=?",
                            (status, ergebnis, jetzt(), kennung))
            return int(cur.rowcount or 0)

    def intel_weiterleitung_zaehler(self, tag: str) -> int:
        with self.conn() as c:
            r = c.execute("SELECT COUNT(*) n FROM intel_weiterleitungen WHERE kennung LIKE ?",
                          (f"WL-{tag}-%",)).fetchone()
        return int(r["n"])

    def intel_weiterleitung_status_setzen(self, an: str, von: str, zu: str) -> int:
        with self.conn() as c:
            cur = c.execute("UPDATE intel_weiterleitungen SET status=? WHERE an=? AND status=?",
                            (zu, an, von))
            return int(cur.rowcount or 0)

    def intel_weiterleitung_aendern(self, kennung: str, abteilung: str, status: str) -> int:
        with self.conn() as c:
            cur = c.execute("UPDATE intel_weiterleitungen SET an=?, status=? WHERE kennung=?",
                            (abteilung, status, kennung))
            return int(cur.rowcount or 0)

    def intel_weiterleitung_speichern(self, kennung: str, von: str, an: str,
                                      betreff: str, bezug: dict[str, Any]) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_weiterleitungen(kennung,zeit,von,an,betreff,bezug,status)"
                " VALUES (?,?,?,?,?,?,'neu')",
                (kennung, jetzt(), von, an, betreff,
                 json.dumps(bezug, ensure_ascii=False)),
            )

    def intel_weiterleitungen(self, limit: int = 50) -> list[sqlite3.Row]:
        with self.conn() as c:
            return list(c.execute(
                "SELECT * FROM intel_weiterleitungen ORDER BY id DESC LIMIT ?", (limit,)))

    def intel_quelle_pflegen(self, quelle: str, artikel: int = 0, analysiert: int = 0,
                             qualitaet: float = 0.0, bestaetigt: int = 0,
                             widerlegt: int = 0) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_quellen(quelle,artikel,analysiert,qualitaet_summe,"
                "bestaetigt,widerlegt,zuletzt) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(quelle) DO UPDATE SET"
                " artikel=artikel+excluded.artikel,"
                " analysiert=analysiert+excluded.analysiert,"
                " qualitaet_summe=qualitaet_summe+excluded.qualitaet_summe,"
                " bestaetigt=bestaetigt+excluded.bestaetigt,"
                " widerlegt=widerlegt+excluded.widerlegt,"
                " zuletzt=excluded.zuletzt",
                (quelle, artikel, analysiert, float(qualitaet), bestaetigt, widerlegt, jetzt()),
            )

    def intel_quelle_aus_artikeln(self) -> list[dict[str, Any]]:
        """Absolute Kennzahlen je Quelle aus allen Artikeln — idempotent, ohne Doppelzählung."""
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT a.quelle AS quelle, COUNT(*) AS artikel,"
                " SUM(CASE WHEN i.artikel_id IS NOT NULL THEN 1 ELSE 0 END) AS analysiert,"
                " SUM(a.qualitaet) AS qualitaet_summe"
                " FROM artikel a LEFT JOIN intel_inhalte i ON i.artikel_id = a.id"
                " GROUP BY a.quelle"
            ).fetchall()
        return [dict(r) for r in zeilen]

    def intel_quelle_abgleichen(self, quelle: str, artikel: int, analysiert: int,
                                qualitaet_summe: float) -> None:
        with self.conn() as c:
            c.execute(
                "INSERT INTO intel_quellen(quelle,artikel,analysiert,qualitaet_summe,"
                "bestaetigt,widerlegt,zuletzt) VALUES (?,?,?,?,0,0,?)"
                " ON CONFLICT(quelle) DO UPDATE SET artikel=excluded.artikel,"
                " analysiert=excluded.analysiert,"
                " qualitaet_summe=excluded.qualitaet_summe,"
                " zuletzt=excluded.zuletzt",
                (quelle, artikel, analysiert, float(qualitaet_summe), jetzt()),
            )

    def artikel_quelle(self, url: str) -> str | None:
        with self.conn() as c:
            r = c.execute("SELECT quelle FROM artikel WHERE url=? LIMIT 1", (url,)).fetchone()
        return r["quelle"] if r else None

    def intel_quellen(self) -> list[dict[str, Any]]:
        with self.conn() as c:
            zeilen = c.execute(
                "SELECT quelle, artikel, analysiert, bestaetigt, widerlegt,"
                " CASE WHEN artikel>0 THEN ROUND(qualitaet_summe/artikel,2) ELSE 0 END AS qualitaet,"
                " zuletzt FROM intel_quellen ORDER BY artikel DESC, quelle"
            ).fetchall()
        return [dict(r) for r in zeilen]

    def intel_statistik(self) -> dict[str, Any]:
        with self.conn() as c:
            auftraege = c.execute("SELECT COUNT(*) n FROM intel_auftraege").fetchone()["n"]
            nach_status = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) n FROM intel_auftraege GROUP BY status")}
            weiter = c.execute("SELECT COUNT(*) n FROM intel_weiterleitungen").fetchone()["n"]
            offen = c.execute(
                "SELECT COUNT(*) n FROM intel_weiterleitungen WHERE status='neu'").fetchone()["n"]
            analysiert = c.execute("SELECT COUNT(*) n FROM intel_inhalte").fetchone()["n"]
            quellen = c.execute("SELECT COUNT(*) n FROM intel_quellen").fetchone()["n"]
        return {"auftraege": auftraege, "nach_status": nach_status,
                "weiterleitungen": weiter, "weiterleitungen_offen": offen,
                "analysiert": analysiert, "quellen": quellen}

    def validierung_nach(self, symbol: str, schluessel: str, seit: str) -> sqlite3.Row | None:
        with self.conn() as c:
            return c.execute(
                "SELECT * FROM validierungen WHERE symbol=? AND schluessel=? AND erstellt>?"
                " ORDER BY id ASC LIMIT 1",
                (symbol, schluessel or "", seit),
            ).fetchone()

    # ---------- Konferenz ----------
    def konferenz_speichern(self, protokoll: dict[str, Any]) -> int:
        with self.conn() as c:
            cur = c.execute("INSERT INTO konferenzen(zeit,protokoll) VALUES (?,?)",
                            (jetzt(), json.dumps(protokoll, ensure_ascii=False)))
            return int(cur.lastrowid or 0)

    def letzte_konferenz(self) -> dict[str, Any] | None:
        with self.conn() as c:
            r = c.execute("SELECT * FROM konferenzen ORDER BY id DESC LIMIT 1").fetchone()
        if not r:
            return None
        return {"zeit": r["zeit"], "protokoll": json.loads(r["protokoll"])}

    # ---------- Zustand ----------
    def zustand_setzen(self, schluessel: str, wert: Any, *,
                       c: sqlite3.Connection | None = None) -> None:
        sql = "INSERT OR REPLACE INTO zustand(schluessel,wert) VALUES (?,?)"
        werte = (schluessel, json.dumps(wert, ensure_ascii=False))
        if c is not None:
            c.execute(sql, werte)
            return
        with self.conn() as verbindung:
            verbindung.execute(sql, werte)

    def zustand(self, schluessel: str, standard: Any = None) -> Any:
        with self.conn() as c:
            r = c.execute("SELECT wert FROM zustand WHERE schluessel=?", (schluessel,)).fetchone()
        return json.loads(r["wert"]) if r else standard

    def zustand_loeschen(self, schluessel: str) -> None:
        with self.conn() as c:
            c.execute("DELETE FROM zustand WHERE schluessel=?", (schluessel,))

    # ---------- Betrieb (Phase 8) ----------
    def betrieb_lauf_speichern(
        self, job: str, status: str, dauer_ms: int = 0,
        fehler: str = "", details: dict[str, Any] | None = None,
    ) -> int:
        with self.conn() as c:
            cur = c.execute(
                "INSERT INTO betrieb_laeufe(zeit,job,status,dauer_ms,fehler,details)"
                " VALUES (?,?,?,?,?,?)",
                (jetzt(), str(job)[:80], str(status)[:30], max(0, int(dauer_ms)),
                 str(fehler or "")[:1000],
                 json.dumps(details or {}, ensure_ascii=False, sort_keys=True)[:8000]),
            )
            return int(cur.lastrowid or 0)

    def betrieb_laeufe(self, limit: int = 50) -> list[dict[str, Any]]:
        grenze = max(1, min(int(limit), 500))
        with self.conn() as c:
            zeilen = list(c.execute(
                "SELECT * FROM betrieb_laeufe ORDER BY id DESC LIMIT ?", (grenze,)
            ))
        raus: list[dict[str, Any]] = []
        for zeile in zeilen:
            eintrag = dict(zeile)
            eintrag["details"] = _json_wert(eintrag.get("details") or "{}", {})
            raus.append(eintrag)
        return raus

    def betrieb_laeufe_trim(self, max_laeufe: int = 1000) -> int:
        """Hält das Jobprotokoll beschränkt; Fachdaten werden nicht berührt."""
        grenze = max(100, int(max_laeufe))
        with self.conn() as c:
            cur = c.execute(
                "DELETE FROM betrieb_laeufe WHERE id NOT IN ("
                "SELECT id FROM betrieb_laeufe ORDER BY id DESC LIMIT ?)",
                (grenze,),
            )
            return int(cur.rowcount or 0)

    def betrieb_statistik(self, stunden: int = 24) -> dict[str, Any]:
        seit = (datetime.now(timezone.utc) - timedelta(hours=max(1, int(stunden)))
                ).isoformat(timespec="seconds")
        with self.conn() as c:
            gesamt = int(c.execute(
                "SELECT COUNT(*) n FROM betrieb_laeufe WHERE zeit>=?", (seit,)
            ).fetchone()["n"])
            fehler = int(c.execute(
                "SELECT COUNT(*) n FROM betrieb_laeufe WHERE zeit>=? AND status='fehler'",
                (seit,),
            ).fetchone()["n"])
            uebersprungen = int(c.execute(
                "SELECT COUNT(*) n FROM betrieb_laeufe WHERE zeit>=? AND status='uebersprungen'",
                (seit,),
            ).fetchone()["n"])
        return {"stunden": int(stunden), "gesamt": gesamt, "fehler": fehler,
                "uebersprungen": uebersprungen}
