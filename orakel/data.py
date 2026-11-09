from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SPALTEN = ["ts", "open", "high", "low", "close", "volume"]

# MT5 exportiert je nach Sprache/Klickpfad unterschiedliche Kopfzeilen.
# Datum und Zeit können getrennt sein (MT5-Standard) und werden zusammengeführt.
ALIASE: dict[str, str] = {
    "date": "_datum", "datetime": "ts", "time": "_zeit", "datum": "_datum", "zeit": "_zeit",
    "<date>": "_datum", "<time>": "_zeit", "<datetime>": "ts",
    "open": "open", "<open>": "open", "eröffnung": "open", "eroeffnung": "open",
    "high": "high", "<high>": "high", "hoch": "high",
    "low": "low", "<low>": "low", "tief": "low",
    "close": "close", "<close>": "close", "schluss": "close",
    "tickvol": "volume", "<tickvol>": "volume", "tickvolume": "volume",
    "vol": "volume", "<vol>": "volume", "volume": "volume", "volumen": "volume",
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

    def als_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "ok": self.ok, "kerzen": self.kerzen,
            "von": self.von, "bis": self.bis,
            "fehler": list(self.fehler), "warnungen": list(self.warnungen),
        }


def _normalisiere_spalten(df: pd.DataFrame) -> pd.DataFrame:
    umbenannt: dict[str, str] = {}
    for spalte in df.columns:
        schluessel = str(spalte).strip().lower()
        if schluessel in ALIASE:
            umbenannt[spalte] = ALIASE[schluessel]
    df = df.rename(columns=umbenannt)
    # MT5 exportiert <TICKVOL> und <VOL> — beide würden zu "volume". Erste behalten.
    df = df.loc[:, ~df.columns.duplicated()]
    if "_datum" in df.columns and "_zeit" in df.columns:
        df["ts"] = df["_datum"].astype(str).str.strip() + " " + df["_zeit"].astype(str).str.strip()
    elif "_datum" in df.columns and "ts" not in df.columns:
        df["ts"] = df["_datum"]
    elif "_zeit" in df.columns and "ts" not in df.columns:
        df["ts"] = df["_zeit"]
    df = df.drop(columns=[c for c in ("_datum", "_zeit") if c in df.columns])
    fehlend = [s for s in ("ts", "open", "high", "low", "close") if s not in df.columns]
    if fehlend:
        raise ValueError(f"CSV: Spalten fehlen: {', '.join(fehlend)} (gefunden: {list(df.columns)})")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[SPALTEN].copy()


def lade_csv(pfad: str | Path, trenner: str | None = None) -> pd.DataFrame:
    """Liest einen MT5-Export. Erkennt Komma- und Semikolon-Trenner."""
    p = Path(pfad)
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if trenner is None:
        kopf = text.splitlines()[0] if text.splitlines() else ""
        trenner = ";" if kopf.count(";") > kopf.count(",") else ("," if "," in kopf else "\t")
    from io import StringIO

    roh = pd.read_csv(StringIO(text), sep=trenner)
    df = _normalisiere_spalten(roh)
    # MT5 kann Datum und Zeit in einer oder zwei Spalten liefern; _normalisiere_spalten
    # behält die erste "ts"-Spalte, daher hier robust parsen.
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce", format="mixed")
    if df["ts"].isna().any():
        # Zweispaltige Variante: Datum + Uhrzeit wurden als eigene Spalten gelesen.
        raise ValueError("CSV: Zeitstempel nicht lesbar. Bitte als eine Spalte exportieren.")
    for spalte in ("open", "high", "low", "close", "volume"):
        df[spalte] = pd.to_numeric(df[spalte], errors="coerce")
    df = df.dropna(subset=["ts", "open", "high", "low", "close"])
    df = df.drop_duplicates(subset="ts", keep="last").sort_values("ts").reset_index(drop=True)
    return df


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

    if len(df) < int(grenzen["min_kerzen"]):
        q.fehler.append(f"Nur {len(df)} Kerzen, mindestens {grenzen['min_kerzen']} nötig")

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
    if len(luecken):
        median = float(luecken.median())
        if median > 0:
            grosse = luecken[luecken > median * 3]
            anteil = len(grosse) / len(luecken) * 100
            if anteil > float(grenzen["max_luecke_pct"]):
                q.warnungen.append(f"{anteil:.1f} % Lücken im Zeitraster (Wochenenden/Feiertage?)")

    spruenge = df["close"].pct_change().abs() * 100
    if len(spruenge.dropna()):
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

    drifts = np.array(drifts[:kerzen])
    vols = np.array(vols[:kerzen])
    # sehr leichte Autokorrelation: genug Struktur für Trendfolge, aber keine
    # unrealistischen Wunderkurven (wird vom Zufallsvergleich sonst entlarvt)
    schocks = rng.standard_normal(kerzen)
    for i in range(1, kerzen):
        schocks[i] = 0.03 * schocks[i - 1] + 0.97 * schocks[i]
    rets = drifts + vols * schocks

    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.empty_like(close)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    spanne = np.abs(rng.standard_normal(kerzen)) * vols * close * 0.9 + close * 0.0002
    high = np.maximum(open_, close) + spanne
    low = np.minimum(open_, close) - spanne
    volume = rng.integers(500, 5000, kerzen).astype(float)

    ts = pd.date_range(start=start, periods=kerzen, freq=f"{timeframe_minuten}min", tz="UTC")
    return pd.DataFrame(
        {"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def df_aus_db(zeilen: list[Any]) -> pd.DataFrame:
    if not zeilen:
        return pd.DataFrame(columns=SPALTEN)
    df = pd.DataFrame([dict(r) for r in zeilen])
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="mixed")
    return df[SPALTEN]
