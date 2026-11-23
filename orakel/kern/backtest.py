from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ..config import Config, RisikoGrenzen
from .kosten import kosten_je_seite, notional_in_kontowaehrung
from .metrics import kennzahlen
from .risk import positionsgroesse
from .strategies import Signalplan, atr


@dataclass(slots=True)
class BacktestErgebnis:
    trades: list[dict[str, Any]] = field(default_factory=list)
    kapital: list[float] = field(default_factory=list)
    kapitalkurve: list[list[Any]] = field(default_factory=list)
    kennzahlen: dict[str, Any] = field(default_factory=dict)
    zeit_im_markt_pct: float = 0.0
    warnungen: list[str] = field(default_factory=list)


def backtest(
    df: pd.DataFrame,
    signale: np.ndarray | Signalplan,
    cfg: Config,
    grenzen: RisikoGrenzen,
    start: int = 0,
    ende: int | None = None,
    startkapital: float | None = None,
    stop_art: str = "atr",
    symbol: str = "",
) -> BacktestErgebnis:
    """Long-only, ein Instrument, Kerze für Kerze.

    Regeln:
    - Signal an Kerze i -> Ausführung zur Eröffnung von Kerze i+1 (kein Look-Ahead).
    - Stop liegt beim Einstieg fest (ATR-Abstand) und wird innerhalb der Kerze geprüft.
    - Lücke unter den Stop -> Ausführung zur Eröffnung (realistisch schlechter).
    - Kosten: Kommission pro Stück oder halber Spread (``kosten.py``) plus
      Slippage in Basispunkten; Pip-Grösse und Spread kommen aus dem
      Instrumentenprofil des Symbols.
    """
    if len(df) < 3:
        return BacktestErgebnis(kennzahlen={}, warnungen=["Zu wenig Kerzen"])

    plan = signale if isinstance(signale, Signalplan) else Signalplan.aus_ziel(signale)
    ziel = np.asarray(plan.ziel, dtype=float)
    if len(ziel) != len(df):
        return BacktestErgebnis(kennzahlen={}, warnungen=["Signallänge passt nicht zu df"])
    stop_serie: np.ndarray | None = None
    reentry_sperre = bool(plan.reentry_sperre)
    if plan.stop is not None:
        stop_serie = np.asarray(plan.stop, dtype=float)
        if len(stop_serie) != len(df):
            return BacktestErgebnis(kennzahlen={}, warnungen=["Stop-Länge passt nicht zu df"])

    start = max(0, int(start))
    ende = len(df) if ende is None else min(len(df), int(ende))
    kapital_start = float(startkapital if startkapital is not None else cfg.start_kapital)
    slip = float(cfg["kosten"]["slippage_bps"]) / 10_000.0
    finanzierung_bps = max(
        0.0, float(cfg["kosten"].get("finanzierung_bps_pro_tag", 0.0))
    )
    # Bei ausgeschalteter Finanzierung bleibt das Array leer; der letzte
    # Finanzierungstag ist dann None und verhindert jeden Zugriff darauf.
    kalendertage = (
        pd.to_datetime(df["ts"], utc=True).dt.date.to_numpy()
        if finanzierung_bps > 0
        else np.empty(0, dtype=object)
    )
    atr_serie = atr(df, 14).to_numpy(dtype=float)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    ts = df["ts"].astype(str).to_numpy()

    cash = kapital_start
    stueck = 0.0
    einstieg = stop = 0.0
    einstieg_prov = 0.0
    einstieg_ts = ""
    gebuehren = 0.0
    finanzierung = 0.0
    finanzierung_handel = 0.0
    finanzierung_notional = 0.0
    letzter_finanzierungstag: date | None = None
    trades: list[dict[str, Any]] = []
    kapital: list[float] = []
    kurve: list[list[Any]] = []
    bars_im_markt = 0
    equity_hoechst = kapital_start
    gesperrt = False
    warnungen: list[str] = []

    def warnen(text: str) -> None:
        if len(warnungen) < 5:
            warnungen.append(text)

    def stop_fuer_einstieg(i: int, preis: float) -> float | None:
        if stop_serie is not None:
            wert = float(stop_serie[i])
            if not math.isfinite(wert) or wert <= 0:
                warnen(f"Ungültiger Stop im Signalplan an Bar {i}")
                return None
            if wert >= preis:
                warnen(f"Stop im Signalplan nicht unter dem Einstieg an Bar {i}")
                return None
            return wert
        if atr_serie[i] > 0:
            wert = preis - grenzen.atr_stop_multiple * atr_serie[i]
            return wert if wert > 0 else None
        return None

    def finanzierung_buchen(bar: int) -> None:
        """Bucht offene UTC-Kalendertage auf das Einstiegsnotional.

        Vereinfachung: Buchung am UTC-Datumswechsel, nicht am
        Broker-Rollover; jeder Kalendertag zählt, kein Triple-Swap. Das
        Notional ist in Kontowährung umgerechnet und wird nicht täglich neu
        bewertet. Details in docs/H1-RETEST-SPEZIFIKATION.md.
        """
        nonlocal cash, finanzierung, finanzierung_handel, letzter_finanzierungstag
        if stueck <= 0 or letzter_finanzierungstag is None:
            return
        # Die Differenz zum zuletzt abgerechneten Tag sind die neu
        # angebrochenen Kalendertage; derselbe Tag wird nicht doppelt belastet.
        tag = kalendertage[bar]
        neue = (tag - letzter_finanzierungstag).days
        if neue <= 0:
            return
        betrag = neue * finanzierung_bps / 10_000.0 * finanzierung_notional
        cash -= betrag
        finanzierung += betrag
        finanzierung_handel += betrag
        letzter_finanzierungstag = tag

    def schliessen(bar: int, preis: float, grund: str) -> None:
        nonlocal cash, stueck, gebuehren
        if stueck <= 0:
            return
        finanzierung_buchen(bar)
        prov = kosten_je_seite(stueck, cfg, symbol, kurs=preis)
        cash += stueck * preis - prov
        gebuehren += prov
        # Beide Provisionen sind bezahlt; die Einstiegsseite wurde beim Kauf bewertet.
        netto = (stueck * (preis - einstieg) - einstieg_prov - prov
                 - finanzierung_handel)
        basis = stueck * einstieg
        trades.append({
            "einstieg": einstieg_ts[:19],
            "ausstieg": str(ts[bar])[:19],
            "stueck": round(stueck, 2),
            "netto": round(netto, 2),
            "rendite_pct": round(netto / basis * 100, 2) if basis else 0.0,
            "grund": grund,
        })
        stueck = 0.0

    i = start
    while i < ende - 1:
        if stueck <= 0:
            if gesperrt and ziel[i] <= 0:
                gesperrt = False
            if ziel[i] > 0 and not gesperrt:
                fill = i + 1
                preis = o[fill] * (1 + slip)
                stop_preis = stop_fuer_einstieg(i, preis)
                if stop_preis is not None:
                    equity = cash
                    menge = positionsgroesse(equity, cash, preis, stop_preis, grenzen)
                    if menge > 0:
                        notional = (
                            notional_in_kontowaehrung(menge, preis, cfg, symbol)
                            if finanzierung_bps > 0 else 0.0
                        )
                        prov = kosten_je_seite(menge, cfg, symbol, kurs=preis)
                        if menge * preis + prov <= cash:
                            cash -= menge * preis + prov
                            gebuehren += prov
                            stueck = menge
                            einstieg = preis
                            stop = stop_preis
                            einstieg_prov = prov
                            einstieg_ts = str(ts[fill])
                            finanzierung_handel = 0.0
                            finanzierung_notional = notional
                            letzter_finanzierungstag = (
                                kalendertage[fill] if finanzierung_bps > 0 else None
                            )
                            # Stop noch in der Einstiegskerze möglich
                            if l[fill] <= stop:
                                schliessen(fill, min(o[fill], stop) * (1 - slip), "Stop (Einstiegskerze)")
                                if reentry_sperre:
                                    # Ein neutrales Ziel in der Fill-Kerze hebt die Sperre
                                    # sofort wieder auf; ein positives Ziel bleibt gesperrt.
                                    gesperrt = ziel[fill] > 0
                equity_hoechst = max(equity_hoechst, cash)
            kapital.append(cash + stueck * c[i])
            kurve.append([str(ts[i])[:19], round(cash + stueck * c[i], 2)])
            i += 1
            continue

        bars_im_markt += 1
        finanzierung_buchen(i)
        # 1) Stop innerhalb der Kerze
        if l[i] <= stop:
            schliessen(i, min(o[i], stop) * (1 - slip), "Stop")
            if reentry_sperre:
                gesperrt = ziel[i] > 0
        # 2) Signal beendet die Position -> nächste Eröffnung
        elif ziel[i] <= 0 and i + 1 < ende:
            schliessen(i + 1, o[i + 1] * (1 - slip), "Signal")
        else:
            equity_hoechst = max(equity_hoechst, cash + stueck * c[i])

        kapital.append(cash + stueck * c[i])
        kurve.append([str(ts[i])[:19], round(cash + stueck * c[i], 2)])
        i += 1

    # Offene Position zum letzten Schlusskurs schliessen (Bewertung, kein Signal)
    if stueck > 0:
        schliessen(ende - 1, c[ende - 1] * (1 - slip), "Ende der Daten")
        kapital[-1] = cash
        kurve[-1][1] = round(cash, 2)

    zeit_im_markt = bars_im_markt / max(1, len(kapital)) * 100
    az = kennzahlen(trades, kapital, gebuehren, kapital_start, cfg.bars_pro_jahr,
                    zeit_im_markt, finanzierung=finanzierung)
    return BacktestErgebnis(
        trades=trades, kapital=kapital, kapitalkurve=kurve, kennzahlen=az,
        zeit_im_markt_pct=round(zeit_im_markt, 1), warnungen=warnungen,
    )
