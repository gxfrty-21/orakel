"""Marktübersicht für die Weltkugel. Alle Zahlen kommen aus den Kerzen in SQLite."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

# Reale Handelsplätze je Symbol — die Kugel zeigt echte Orte, keine Dekoration.
REGIONEN: dict[str, tuple[str, float, float]] = {
    "EURUSD": ("Frankfurt", 50.11, 8.68),
    "GBPUSD": ("London", 51.51, -0.13),
    "USDJPY": ("Tokio", 35.68, 139.69),
    "US500": ("New York", 40.71, -74.01),
    "US30": ("New York", 40.71, -74.01),
    "NAS100": ("New York", 40.71, -74.01),
    "GER40": ("Frankfurt", 50.11, 8.68),
    "XAUUSD": ("London", 51.51, -0.13),
    "XTIUSD": ("London", 51.51, -0.13),
    "BTCUSD": ("Tokio", 35.68, 139.69),
}


def _regime(df: pd.DataFrame, atr_pct: float) -> str:
    """Einfache, nachvollziehbare Einordnung — keine Prognose."""
    if len(df) < 120:
        return "zu wenig Daten"
    close = df["close"]
    ema_kurz = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema_lang = close.ewm(span=100, adjust=False).mean().iloc[-1]
    if not ema_lang:
        return "unklar"
    abstand = (ema_kurz / ema_lang - 1) * 100
    schwelle = 0.12

    atr_reihe = (df["high"] - df["low"]).rolling(14).mean()
    if len(atr_reihe.dropna()) > 50:
        rang = float((atr_reihe.dropna() < atr_pct * close.iloc[-1] / 100).mean())
    else:
        rang = 0.5

    if rang > 0.9:
        return "Stress"
    if abstand > schwelle:
        return "Trend auf"
    if abstand < -schwelle:
        return "Trend ab"
    return "Seitwärts"


def markt_uebersicht(daten: dict[str, pd.DataFrame]) -> dict[str, Any]:
    symbole: list[dict[str, Any]] = []
    reihen: dict[str, pd.Series] = {}

    for symbol, df in sorted(daten.items()):
        if df is None or df.empty:
            continue
        close = df["close"].astype(float)
        letzter = float(close.iloc[-1])
        vor_24h = float(close.iloc[-97]) if len(close) > 97 else float(close.iloc[0])
        atr = float((df["high"] - df["low"]).rolling(14).mean().iloc[-1] or 0.0)
        atr_pct = atr / letzter * 100 if letzter else 0.0
        stadt, lat, lon = REGIONEN.get(symbol, ("unbekannt", 0.0, 0.0))
        symbole.append({
            "symbol": symbol,
            "kurs": round(letzter, 5),
            "aenderung_24h_pct": round((letzter / vor_24h - 1) * 100, 2) if vor_24h else 0.0,
            "atr_pct": round(atr_pct, 3),
            "regime": _regime(df, atr_pct),
            "kerzen": int(len(df)),
            "von": str(df["ts"].iloc[0])[:19],
            "bis": str(df["ts"].iloc[-1])[:19],
            "stadt": stadt,
            "lat": lat,
            "lon": lon,
        })
        reihen[symbol] = close.pct_change()

    korrelationen: list[dict[str, Any]] = []
    namen = list(reihen)
    for i, a in enumerate(namen):
        for b in namen[i + 1:]:
            paar = pd.concat([reihen[a], reihen[b]], axis=1).dropna().tail(500)
            if len(paar) < 50:
                continue
            wert = float(paar.iloc[:, 0].corr(paar.iloc[:, 1]))
            if np.isfinite(wert):
                korrelationen.append({"a": a, "b": b, "wert": round(wert, 2)})
    korrelationen.sort(key=lambda k: -abs(k["wert"]))

    return {
        "symbole": symbole,
        "korrelation": korrelationen[:12],
        "stand": str(pd.Timestamp.now(tz="UTC"))[:19],
        "hinweis": "Kugel und Knoten sind Darstellung. Jede Zahl stammt aus den importierten Kerzen.",
    }


def korrelation_max(symbol: str, daten: dict[str, pd.DataFrame], offene: list[str],
                    fenster: int = 500) -> float | None:
    """Grösste Korrelation eines Symbols zu den offenen Positionen.

    Gleiche Rechnung wie in `markt_uebersicht` (Pearson auf Renditen, letzte
    `fenster` Kerzen), damit die Zahl im Dashboard und die Sperre im Risiko
    dieselbe Grundlage haben. Gibt None zurück, wenn keine vergleichbare
    offene Position existiert — dann greift die Sperre nicht.
    """
    df = daten.get(symbol)
    if df is None or df.empty or not offene:
        return None
    eigene = df["close"].astype(float).pct_change()
    werte: list[float] = []
    for anderes in offene:
        if anderes == symbol:
            continue
        fremd_df = daten.get(anderes)
        if fremd_df is None or fremd_df.empty:
            continue
        paar = pd.concat([eigene, fremd_df["close"].astype(float).pct_change()],
                         axis=1).dropna().tail(fenster)
        if len(paar) < 50:
            continue
        wert = float(paar.iloc[:, 0].corr(paar.iloc[:, 1]))
        if np.isfinite(wert):
            werte.append(wert)
    if not werte:
        return None
    return max(werte, key=abs)
