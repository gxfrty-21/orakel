from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

SPALTEN = ["ts", "open", "high", "low", "close", "volume"]

# Importiert werden nur Zeitrahmen, die auch anderswo vorkommen. Bewertet
# (Richter, Paper) wird M15; die anderen liegen für spätere Auswertungen bereit.
ZEITRAHMEN_MINUTEN = {"M1": 1, "M5": 5, "M15": 15, "H1": 60}
ZEITRAHMEN = tuple(ZEITRAHMEN_MINUTEN)


def kerzen_minimum(basis: int, zeitrahmen: str) -> int:
    """Rechnet die M15-Mindestzahl ``basis`` auf ``zeitrahmen`` um.

    ``min_kerzen`` gilt in der Konfiguration für M15 (1200 Kerzen ≈ zwei
    Wochen). Dieselbe Zahl im H1-Raster wären 50 Tage; der Richter braucht
    deshalb die zum gelesenen Raster passende Mindestzahl.
    """
    minuten = ZEITRAHMEN_MINUTEN.get(zeitrahmen.upper())
    if minuten is None:
        raise ValueError(f"Unbekannter Zeitrahmen: {zeitrahmen}")
    return max(1, int(round(basis * 15 / minuten)))

# MT5 exportiert Datum als YYYY.MM.DD; ISO-Dateien kommen zusätzlich vor (das
# «T» wird vor dem Parsen zum Leerzeichen). Bewusst nur diese Formen: eine
# Tag/Monat-Vertauschung soll nicht still passieren. Reine Datumsangaben fehlen
# absichtlich: daraus würde eine Mitternachtskerze, und ein Tagesexport landete
# unbemerkt als M15 in der Datenbank.
ZEITFORMATE = (
    "%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
)

# MT5 exportiert je nach Sprache unterschiedliche Kopfzeilen; die spitzen
# Klammern der MT5-Form werden vor dem Nachschlagen entfernt. Datum und Zeit
# können getrennt sein (MT5-Standard) und werden zusammengeführt.
ALIASE: dict[str, str] = {
    "date": "_datum", "datetime": "ts", "time": "_zeit", "datum": "_datum", "zeit": "_zeit",
    "open": "open", "eröffnung": "open", "eroeffnung": "open",
    "high": "high", "hoch": "high", "low": "low", "tief": "low",
    "close": "close", "schluss": "close",
    "tickvol": "volume", "vol": "volume", "volume": "volume", "volumen": "volume",
}


@dataclass(slots=True)
class Datenqualitaet:
    symbol: str
    ok: bool
    kerzen: int
    von: str | None = None
    bis: str | None = None
    fehler: list[str] = field(default_factory=list)
    warnungen: list[str] = field(default_factory=list)
    timeframe: str = "M15"
    # Kerzen je Kalenderjahr; dient der Importausgabe und der Warnung bei
    # vollständig fehlenden Jahren.
    jahre: dict[str, int] = field(default_factory=dict)

    def als_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "ok": self.ok, "kerzen": self.kerzen,
            "von": self.von, "bis": self.bis,
            "fehler": list(self.fehler), "warnungen": list(self.warnungen),
        }


def _normalisiere_spalten(df: pd.DataFrame) -> pd.DataFrame:
    umbenannt: dict[str, str] = {}
    for spalte in df.columns:
        schluessel = str(spalte).strip().strip("<>").strip().lower()
        if schluessel in ALIASE:
            umbenannt[spalte] = ALIASE[schluessel]
    df = df.rename(columns=umbenannt)
    # MT5 exportiert <TICKVOL> und <VOL> — beide würden zu "volume". Erste behalten.
    df = df.loc[:, ~df.columns.duplicated()]
    if "_datum" in df.columns and "_zeit" in df.columns:
        df["ts"] = df["_datum"].astype(str).str.strip() + " " + df["_zeit"].astype(str).str.strip()
    elif "_datum" in df.columns and "ts" not in df.columns:
        # MT5 kann Datum und Uhrzeit auch in einer Spalte liefern.
        df["ts"] = df["_datum"]
    df = df.drop(columns=[c for c in ("_datum", "_zeit") if c in df.columns])
    fehlend = [s for s in ("ts", "open", "high", "low", "close") if s not in df.columns]
    if fehlend:
        raise ValueError(f"CSV: Spalten fehlen: {', '.join(fehlend)} (gefunden: {list(df.columns)})")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[SPALTEN]


def _trenner(kopf: str) -> str:
    """Trenner aus der Kopfzeile; MT5 schreibt Tabulatoren, andere Komma/Semikolon."""
    if "\t" in kopf:
        return "\t"
    if kopf.count(";") > kopf.count(","):
        return ";"
    if "," in kopf:
        return ","
    raise ValueError("CSV: Trennzeichen nicht erkannt (Tabulator, Semikolon oder Komma nötig).")


def _zeitstempel(reihen: pd.Series, zeitzone: str | None = None,
                 versatz_stunden: float | None = None) -> pd.Series:
    """Parst MT5- und ISO-Zeitstempel zeilenweise mit festen Formaten.

    Zeilenweise, weil ein zusammengeführter Export mit und ohne Sekunden
    vorkommen kann; geraten wird trotzdem nichts. Ohne ``zeitzone`` und ohne
    ``versatz_stunden`` gilt die Serverzeit als UTC, mit ``zeitzone`` als
    Ortszeit dieser IANA-Zone (inkl. Sommerzeit), mit ``versatz_stunden`` als
    Serverzeit eines festen Broker-Versatzes.
    """
    text = (reihen.astype(str).str.strip()
            .str.replace(r"\s+", " ", regex=True)
            .str.replace("T", " ", regex=False))
    geparst = pd.Series(pd.NaT, index=reihen.index, dtype="datetime64[ns]")
    for format_ in ZEITFORMATE:
        offen = geparst.isna()
        if not offen.any():
            break
        geparst[offen] = pd.to_datetime(text[offen], format=format_, errors="coerce")
    schlecht = geparst.isna()
    if schlecht.any():
        beispiele = ", ".join(text[schlecht].head(3).tolist())
        raise ValueError(
            f"CSV: {int(schlecht.sum())} Zeitstempel nicht lesbar ({beispiele}). "
            "Erwartet wird YYYY.MM.DD HH:MM[:SS] oder ISO 8601 mit Uhrzeit, in einer "
            "Spalte oder getrennt in Datum und Zeit."
        )
    return _nach_utc(geparst, zeitzone, versatz_stunden)


def _nach_utc(geparst: pd.Series, zeitzone: str | None,
              versatz_stunden: float | None = None) -> pd.Series:
    """Wandelt naive Serverzeit in UTC um.

    ``versatz_stunden`` ist der feste Broker-Versatz (Serverzeit = UTC + Versatz),
    z. B. ``3`` für einen Server auf UTC+3. Er ersetzt die IANA-Zone, weil beide
    Angaben zusammen nicht eindeutig wären.
    """
    if versatz_stunden is not None:
        if zeitzone:
            raise ValueError(
                "CSV: server_zeitzone und server_versatz_stunden schliessen sich aus — "
                "entweder eine IANA-Zone oder ein fester Broker-Versatz."
            )
        return (geparst - pd.Timedelta(hours=float(versatz_stunden))).dt.tz_localize("UTC")
    if not zeitzone:
        return geparst.dt.tz_localize("UTC")
    try:
        zone = ZoneInfo(zeitzone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"CSV: unbekannte Zeitzone «{zeitzone}». Erwartet wird eine IANA-Zone "
            "wie Europe/Athens."
        ) from exc
    # Bei der Rückstellung im Herbst wiederholt MT5 die Wandzeit. In
    # Exportreihenfolge ist die frühere Fassung die Sommerzeit-, die spätere die
    # Standardzeitstunde; so bleiben beide Stunden erhalten, statt als Dublette
    # zusammenzufallen. Eine absteigend sortierte Datei dreht diese Reihenfolge —
    # erkannt am ersten und letzten Zeitstempel. Ausserhalb einer Wiederholung
    # ist das Merkmal bedeutungslos.
    wiederholt = geparst.duplicated(keep="first").to_numpy()
    ambiguous = wiederholt if geparst.iloc[0] > geparst.iloc[-1] else ~wiederholt
    lokalisiert = geparst.dt.tz_localize(zone, ambiguous=ambiguous, nonexistent="NaT")
    fehlt = lokalisiert.isna()
    if fehlt.any():
        beispiele = ", ".join(
            geparst[fehlt].dt.strftime("%Y-%m-%d %H:%M:%S").head(3).tolist()
        )
        raise ValueError(
            f"CSV: {int(fehlt.sum())} Zeitstempel liegen in der Sommerzeitlücke von "
            f"«{zeitzone}» und existieren dort nicht ({beispiele}). Prüfe "
            "server_zeitzone oder exportiere mit festem Broker-Versatz "
            "(--server-versatz-stunden)."
        )
    return lokalisiert.dt.tz_convert("UTC")


def zerlege_dateiname(pfad: str | Path) -> tuple[str, str]:
    """Symbol und Zeitrahmen aus einem Namen wie ``EURUSD_M15.csv``.

    Ohne bekannten Zeitrahmen im Namen gilt M15; das ist der Zeitrahmen, den
    Richter und Paper lesen.
    """
    stamm = Path(pfad).stem
    vorne, _, hinten = stamm.rpartition("_")
    if vorne and hinten.upper() in ZEITRAHMEN:
        return vorne.upper(), hinten.upper()
    return stamm.split("_")[0].upper(), "M15"


def lade_csv(pfad: str | Path, server_zeitzone: str | None = None,
             server_versatz_stunden: float | None = None) -> pd.DataFrame:
    """Liest einen MT5-Export mit Tabulator, Komma oder Semikolon.

    Kopfzeilen dürfen englisch oder deutsch sein (siehe ``ALIASE``); ``<VOL>``
    und ``<SPREAD>`` werden ignoriert, ``<TICKVOL>`` wird zu ``volume``. Fehlt
    eine Volumenspalte, steht 0. Ohne ``server_zeitzone`` gilt die Serverzeit
    als UTC, sonst als Ortszeit dieser IANA-Zone; ``server_versatz_stunden``
    verschiebt stattdessen um einen festen Broker-Offset. Zeilen mit unlesbaren Preisen
    führen zu einem Fehler statt zu stillschweigend fehlenden Kerzen; doppelte
    Zeitstempel werden zusammengeführt (der letzte gewinnt), die Reihe wird
    sortiert.
    """
    p = Path(pfad)
    sep, kodierung = _trenner_und_kodierung(p)
    roh = pd.read_csv(p, sep=sep, encoding=kodierung)
    return _verarbeite(_normalisiere_spalten(roh), server_zeitzone, p.name,
                       server_versatz_stunden)


def _trenner_und_kodierung(p: Path) -> tuple[str, str]:
    with p.open("r", encoding="utf-8-sig", errors="replace") as datei:
        kopf = datei.readline()
    if not kopf.strip():
        raise ValueError(f"CSV: {p.name} ist leer.")
    return _trenner(kopf), _kodierung(p)


def _kodierung(p: Path) -> str:
    # Ältere MT5-Installationen schreiben ANSI (cp1252), z. B. «Eröffnung».
    with p.open("rb") as datei:
        probe = datei.readline()
    try:
        probe.decode("utf-8-sig")
    except UnicodeDecodeError:
        return "cp1252"
    return "utf-8-sig"


def _verarbeite(df: pd.DataFrame, zeitzone: str | None, name: str,
                versatz_stunden: float | None = None) -> pd.DataFrame:
    """Prüft und normalisiert einen Block; unlesbare Zeilen brechen ab."""
    df["ts"] = _zeitstempel(df["ts"], zeitzone, versatz_stunden)
    for spalte in ("open", "high", "low", "close", "volume"):
        df[spalte] = pd.to_numeric(df[spalte], errors="coerce")

    unlesbar = df[["open", "high", "low", "close"]].isna().any(axis=1)
    if unlesbar.any():
        raise ValueError(
            f"CSV: {int(unlesbar.sum())} Kerzen mit unlesbaren Preisen. "
            "Erwartet werden Zahlen mit Dezimalpunkt, z. B. 1.03500."
        )
    df["volume"] = df["volume"].fillna(0.0)
    df = df.drop_duplicates(subset="ts", keep="last").sort_values("ts").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"CSV: {name} enthält keine vollständigen Kerzen.")
    return df


def lade_csv_bloecke(pfad: str | Path, server_zeitzone: str | None = None,
                     block: int = 200_000,
                     server_versatz_stunden: float | None = None) -> Iterator[pd.DataFrame]:
    """Liest eine grosse Datei tageweise blockweise statt ganz auf einmal.

    Blöcke enden an einem Datumswechsel. Bei der Herbst-Rückstellung liegen so
    beide Fassungen derselben Uhrzeit im selben Block und bleiben trennbar; der
    Import schreibt blockweise in die Datenbank und prüft danach wie bisher die
    zusammengeführte Reihe. Die Datei muss nach Datum sortiert sein (auf- oder
    absteigend); verschränkte Tage brechen mit Meldung ab, weil die Blockgrenze
    sonst die beiden Herbstfassungen trennen würde.
    """
    p = Path(pfad)
    sep, kodierung = _trenner_und_kodierung(p)

    puffer: pd.DataFrame | None = None
    gesehen: set[str] = set()
    for roh in pd.read_csv(p, sep=sep, encoding=kodierung, chunksize=block):
        df = _normalisiere_spalten(roh)
        if puffer is not None:
            df = pd.concat([puffer, df], ignore_index=True)
        tage = df["ts"].astype(str).str[:10]
        # Jeder Tag darf nur einen zusammenhängenden Lauf bilden; sonst könnte
        # die Blockgrenze die beiden Fassungen der Herbststunde trennen und eine
        # davon still als Standardzeit umrechnen.
        wechsel = tage.ne(tage.shift())
        laeufe = set(tage[wechsel])
        if len(laeufe) != int(wechsel.sum()) or laeufe & gesehen:
            raise ValueError(
                f"CSV: {p.name} ist nicht nach Datum sortiert (ein Datum "
                "erscheint in mehreren Abschnitten). Bitte die Datei auf- oder "
                "absteigend sortieren; sonst würden die Herbststunden getrennt."
            )
        # Der letzte Tag wird erst mit dem nächsten Block verarbeitet.
        ab = int((tage == tage.iloc[-1]).to_numpy().argmax())
        puffer = df.iloc[ab:].reset_index(drop=True)
        rest = df.iloc[:ab]
        if len(rest):
            gesehen.update(tage.iloc[:ab])
            yield _verarbeite(rest, server_zeitzone, p.name, server_versatz_stunden)
    if puffer is not None and len(puffer):
        yield _verarbeite(puffer, server_zeitzone, p.name, server_versatz_stunden)


# Vor dem Schreiben werden höchstens so viele Tagesblöcke gepuffert, bis
# mindestens so viele Abstände für ein Takturteil vorliegen.
TAKT_MINDESTABSTAENDE = 10
TAKT_MAX_BLOECKE = 5


def takt_fehler(ts: pd.Series, timeframe: str, *, mindest_abstaende: int = 0) -> str | None:
    """Meldet ein Zeitraster, das nicht zum angegebenen Zeitrahmen passt.

    Der Median ist robust gegen Wochenenden, Feiertage und Handelspausen:
    einzelne lange Abstände verschieben ihn nicht. Weicht er trotzdem vom
    angegebenen Raster ab, ist die Datei anders getaktet, als sie heisst — eine
    als M15 benannte H1-Datei würde sonst still als M15 gelten. Mit
    ``mindest_abstaende`` wird erst geurteilt, wenn genug Abstände vorliegen.
    """
    luecken = ts.diff().dt.total_seconds().dropna()
    if len(luecken) < max(1, mindest_abstaende):
        return None
    median = float(luecken.median())
    erwartet = ZEITRAHMEN_MINUTEN.get(timeframe.upper())
    if not erwartet or median <= 0:
        return None
    soll = erwartet * 60
    if 0.75 * soll <= median <= 1.5 * soll:
        return None
    return (f"Median-Abstand {median / 60:.0f} Min passt nicht zu {timeframe.upper()} "
            f"(erwartet {erwartet} Min) — Datei im passenden Zeitrahmen ablegen?")


def mit_taktpruefung(bloecke: Iterable[pd.DataFrame], zeitrahmen: str) -> Iterator[pd.DataFrame]:
    """Prüft den Takt, bevor der erste Block in die Datenbank geht.

    Der Import schreibt eine Datei blockweise in einer Transaktion. Ohne diese
    Vorprüfung landeten falsch getaktete Kerzen (etwa H1 unter M15) zuerst in
    der Tabelle und fielen erst der Prüfung der zusammengeführten Reihe auf.
    """
    puffer: list[pd.DataFrame] = []
    abstaende = 0
    for block in bloecke:
        puffer.append(block)
        abstaende += max(0, len(block) - 1)
        if abstaende >= TAKT_MINDESTABSTAENDE or len(puffer) >= TAKT_MAX_BLOECKE:
            break
    if puffer:
        zusammen = pd.concat(puffer, ignore_index=True)
        fehler = takt_fehler(zusammen["ts"], zeitrahmen,
                             mindest_abstaende=TAKT_MINDESTABSTAENDE)
        if fehler:
            raise ValueError(fehler)
        yield from puffer
    yield from bloecke


def pruefe_daten(df: pd.DataFrame, symbol: str, cfg: Any, timeframe: str = "M15") -> Datenqualitaet:
    """Prüft Kerzen auf die Fehler, die Backtests systematisch verfälschen."""
    grenzen = cfg["daten"]
    q = Datenqualitaet(symbol=symbol, ok=True, kerzen=len(df), timeframe=timeframe)
    if df.empty:
        q.ok = False
        q.fehler.append("Keine Kerzen vorhanden")
        return q

    q.von = str(df["ts"].iloc[0])[:19]
    q.bis = str(df["ts"].iloc[-1])[:19]

    # Jahre zählen und vollständig fehlende Jahre benennen. Ein fehlendes Jahr
    # fällt sonst durch alle bisherigen Prüfungen: Der Median-Abstand bleibt
    # richtig, und ein einzelner Jahreswechsel liegt weit unter max_luecke_pct.
    # Bei einem Broker, dessen Historie abgeschnitten ist, wäre die mehrjährige
    # Reihe dann unbemerkt kürzer als gedacht. Bewusst eine Warnung, kein
    # Fehler: Eine Reihe mit einer Lücke bleibt für Backtests verwendbar.
    q.jahre = {str(int(jahr)): int(anzahl) for jahr, anzahl in
               df["ts"].dt.year.value_counts().sort_index().items()}
    erstes, letztes = min(int(j) for j in q.jahre), max(int(j) for j in q.jahre)
    ohne_kerzen = [jahr for jahr in range(erstes + 1, letztes) if str(jahr) not in q.jahre]
    if ohne_kerzen:
        q.warnungen.append(
            "Keine Kerzen in " + ", ".join(str(j) for j in ohne_kerzen)
            + " — mehrjährige Reihe unvollständig (Broker-Historie oder Exportgrenze?)"
        )

    mindestens = kerzen_minimum(int(grenzen["min_kerzen"]), timeframe)
    if len(df) < mindestens:
        q.fehler.append(
            f"Nur {len(df)} Kerzen, mindestens {mindestens} nötig ({timeframe.upper()})"
        )

    if df["ts"].duplicated().any():
        q.fehler.append("Doppelte Zeitstempel")
    if not df["ts"].is_monotonic_increasing:
        q.fehler.append("Zeitstempel nicht aufsteigend")

    unmoeglich = (df["high"] < df["low"]) | (df["high"] < df[["open", "close"]].max(axis=1)) | (
        df["low"] > df[["open", "close"]].min(axis=1)
    )
    if unmoeglich.any():
        q.fehler.append(f"{int(unmoeglich.sum())} Kerzen mit unmöglichem Hoch/Tief")

    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        q.fehler.append("Preise kleiner oder gleich null")

    luecken = df["ts"].diff().dt.total_seconds().dropna()
    median = float(luecken.median()) if len(luecken) else 0.0
    takt = takt_fehler(df["ts"], timeframe)
    if takt:
        q.fehler.append(takt)
    if median > 0:
        anteil = float((luecken > median * 3).mean()) * 100
        if anteil > float(grenzen["max_luecke_pct"]):
            q.warnungen.append(f"{anteil:.1f} % Lücken im Zeitraster (Wochenenden/Feiertage?)")

    spruenge = df["close"].pct_change().abs() * 100
    grosse_spruenge = spruenge[spruenge > float(grenzen["max_sprung_pct"])]
    if len(grosse_spruenge):
        q.warnungen.append(
            f"{len(grosse_spruenge)} Sprünge über {grenzen['max_sprung_pct']} % (Split oder Datenfehler?)"
        )

    if q.fehler:
        q.ok = False
    return q


def synthetische_kerzen(
    symbol: str = "SYNTH", kerzen: int = 5000, seed: int = 7,
    start: str = "2024-01-01", timeframe_minuten: int = 15,
) -> pd.DataFrame:
    """Deterministische Testdaten mit Regimen (Trend, Seitwärts, Stress).

    Nur für den Test der Abläufe — niemals als Beweis für eine Strategie.
    """
    rng = np.random.default_rng(seed)
    regime_len = max(120, kerzen // 8)
    drifts: list[float] = []
    vols: list[float] = []
    while len(drifts) < kerzen:
        art = rng.choice(["trend_up", "trend_down", "range", "stress"], p=[0.34, 0.22, 0.34, 0.10])
        # Bewusst nahe am Random Walk: nur Volatilitätscluster, praktisch kein Drift.
        # Sonst entstehen Profit Factors, die es an echten Märkten nicht gibt — und
        # das Dashboard würde Scheinalpha zeigen.
        if art == "trend_up":
            d, v = 0.00003, 0.0010
        elif art == "trend_down":
            d, v = -0.00003, 0.0011
        elif art == "range":
            d, v = 0.0, 0.0009
        else:
            d, v = -0.00002, 0.0026
        drifts.extend([d] * regime_len)
        vols.extend([v] * regime_len)

    drifts_arr = np.array(drifts[:kerzen])
    vols_arr = np.array(vols[:kerzen])
    # sehr leichte Autokorrelation: genug Struktur für Trendfolge, aber keine
    # unrealistischen Wunderkurven (wird vom Zufallsvergleich sonst entlarvt)
    schocks = rng.standard_normal(kerzen)
    for i in range(1, kerzen):
        schocks[i] = 0.03 * schocks[i - 1] + 0.97 * schocks[i]
    rets = drifts_arr + vols_arr * schocks

    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.empty_like(close)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    spanne = np.abs(rng.standard_normal(kerzen)) * vols_arr * close * 0.9 + close * 0.0002
    high = np.maximum(open_, close) + spanne
    low = np.minimum(open_, close) - spanne
    volume = rng.integers(500, 5000, kerzen).astype(float)

    ts = pd.date_range(start=start, periods=kerzen, freq=f"{timeframe_minuten}min", tz="UTC")
    return pd.DataFrame(
        {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def df_aus_db(zeilen: Sequence[Any]) -> pd.DataFrame:
    return df_aus_bloecken([zeilen])


def df_aus_bloecken(bloecke: Iterable[Sequence[Any]]) -> pd.DataFrame:
    """Baut die Kerzen-Tabelle aus DB-Blöcken auf.

    Millionen Zeilen auf einmal als Dicts oder Row-Objekte zu materialisieren
    kostet ein Vielfaches; die Blockrahmen werden einzeln aufgebaut. Die
    zusammengeführte Tabelle entsteht am Ende einmal — ``pruefe_daten`` braucht
    sie vollständig.
    """
    teile: list[pd.DataFrame] = []
    for block in bloecke:
        if not len(block):
            continue
        df = pd.DataFrame.from_records(block, columns=SPALTEN)
        df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
        teile.append(df[SPALTEN])
    if not teile:
        return pd.DataFrame(columns=SPALTEN)
    return pd.concat(teile, ignore_index=True)
