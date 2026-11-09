from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import Config, RisikoGrenzen
from .metrics import kennzahlen
from .strategies import atr


@dataclass(slots=True)
class BacktestErgebnis:
    trades: list[dict[str, Any]] = field(default_factory=list)
    kapital: list[float] = field(default_factory=list)
    kapitalkurve: list[list[Any]] = field(default_factory=list)
    kennzahlen: dict[str, Any] = field(default_factory=dict)
    zeit_im_markt_pct: float = 0.0
    warnungen: list[str] = field(default_factory=list)


def _kosten(stueck: float, cfg: Config) -> float:
    k = cfg["kosten"]
    return max(float(k["min_commission"]), stueck * float(k["commission_per_share"]))


def backtest(
    df: pd.DataFrame,
    signale: np.ndarray,
    cfg: Config,
    grenzen: RisikoGrenzen,
    start: int = 0,
    ende: int | None = None,
    startkapital: float | None = None,
    stop_art: str = "atr",
) -> BacktestErgebnis:
    """Long-only, ein Instrument, Kerze für Kerze.

    Regeln:
    - Signal an Kerze i -> Ausführung zur Eröffnung von Kerze i+1 (kein Look-Ahead).
    - Stop liegt beim Einstieg fest (ATR-Abstand) und wird innerhalb der Kerze geprüft.
    - Lücke unter den Stop -> Ausführung zur Eröffnung (realistisch schlechter).
    - Kosten: Kommission pro Stück (mind. Minimum) + Slippage in Basispunkten.
    """
    if len(df) < 3:
        return BacktestErgebnis(kennzahlen={}, warnungen=["Zu wenig Kerzen"])

    start = max(0, int(start))
    ende = len(df) if ende is None else min(len(df), int(ende))
    kapital_start = float(startkapital if startkapital is not None else cfg.start_kapital)
    slip = float(cfg["kosten"]["slippage_bps"]) / 10_000.0
    atr_serie = atr(df, 14).to_numpy(dtype=float)
    o = df["open"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    ts = df["ts"].astype(str).to_numpy()

    cash = kapital_start
    stueck = 0.0
    einstieg = stop = 0.0
    einstieg_ts = ""
    gebuehren = 0.0
    trades: list[dict[str, Any]] = []
    kapital: list[float] = []
    kurve: list[list[Any]] = []
    bars_im_markt = 0
    equity_hoechst = kapital_start

    def schliessen(bar: int, preis: float, grund: str) -> None:
        nonlocal cash, stueck, gebuehren
        if stueck <= 0:
            return
        prov = _kosten(stueck, cfg)
        cash += stueck * preis - prov
        gebuehren += prov
        netto = stueck * (preis - einstieg) - prov - _kosten(stueck, cfg)
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
            if signale[i] > 0 and atr_serie[i] > 0:
                fill = i + 1
                preis = o[fill] * (1 + slip)
                abstand = grenzen.atr_stop_multiple * atr_serie[i]
                stop_preis = preis - abstand
                if stop_preis > 0 and abstand > 0:
                    equity = cash
                    risiko_betrag = equity * grenzen.risk_per_trade_pct / 100.0
                    nach_risiko = risiko_betrag / abstand
                    nach_deckel = equity * grenzen.max_position_pct / 100.0 / preis
                    nach_cash = max(0.0, cash * (1 - grenzen.min_cash_pct / 100.0)) / preis
                    menge = float(np.floor(min(nach_risiko, nach_deckel, nach_cash)))
                    if menge > 0:
                        prov = _kosten(menge, cfg)
                        if menge * preis + prov <= cash:
                            cash -= menge * preis + prov
                            gebuehren += prov
                            stueck = menge
                            einstieg = preis
                            stop = stop_preis
                            einstieg_ts = str(ts[fill])
                            # Stop noch in der Einstiegskerze möglich
                            if l[fill] <= stop:
                                schliessen(fill, min(o[fill], stop) * (1 - slip), "Stop (Einstiegskerze)")
                equity_hoechst = max(equity_hoechst, cash)
            kapital.append(cash + stueck * c[i])
            kurve.append([str(ts[i])[:19], round(cash + stueck * c[i], 2)])
            i += 1
            continue

        bars_im_markt += 1
        # 1) Stop innerhalb der Kerze
        if l[i] <= stop:
            schliessen(i, min(o[i], stop) * (1 - slip), "Stop")
        # 2) Signal beendet die Position -> nächste Eröffnung
        elif signale[i] <= 0 and i + 1 < ende:
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
    az = kennzahlen(trades, kapital, gebuehren, kapital_start, cfg.bars_pro_jahr, zeit_im_markt)
    return BacktestErgebnis(
        trades=trades, kapital=kapital, kapitalkurve=kurve, kennzahlen=az,
        zeit_im_markt_pct=round(zeit_im_markt, 1),
    )
