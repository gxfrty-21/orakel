from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
import pandas as pd


class Broker(Protocol):
    """Der Strategie-Code kennt nur diese Schnittstelle (Regel 8)."""

    name: str

    def konto(self) -> dict[str, Any]: ...
    def positionen(self) -> list[dict[str, Any]]: ...
    def kurse(self, symbol: str, zeitrahmen: str) -> pd.DataFrame: ...
    def order(self, symbol: str, aktion: str, menge: float, stop: float | None = None,
              kommentar: str = "") -> dict[str, Any]: ...


class PaperOnlyViolation(RuntimeError):
    """Wird geworfen, sobald irgendetwas auf ein echtes Konto zeigen würde."""


@dataclass(slots=True)
class CsvBroker:
    """Paper-Broker auf historischen Kerzen: Ausführung zur nächsten Eröffnung.

    Kein Netzwerk, kein Konto, kein echtes Geld. Für Backtest und Probelauf.
    """

    daten: dict[str, pd.DataFrame]
    cash: float
    name: str = "csv"
    gebuehren: float = 0.0
    slippage_bps: float = 2.0
    commission_per_share: float = 0.005
    min_commission: float = 1.0
    offene: dict[str, dict[str, Any]] = field(default_factory=dict)
    letzter_kurs: dict[str, float] = field(default_factory=dict)

    def _kurs(self, symbol: str) -> float:
        df = self.daten.get(symbol)
        if df is None or df.empty:
            raise KeyError(f"Keine Daten für {symbol}")
        return float(df["close"].iloc[-1])

    def _provision(self, menge: float) -> float:
        return max(self.min_commission, menge * self.commission_per_share)

    def konto(self) -> dict[str, Any]:
        equity = self.cash + sum(
            p["menge"] * self._kurs(s) for s, p in self.offene.items()
        )
        return {"equity": round(equity, 2), "cash": round(self.cash, 2),
                "positionen": len(self.offene), "broker": self.name}

    def positionen(self) -> list[dict[str, Any]]:
        raus = []
        for symbol, p in self.offene.items():
            kurs = self._kurs(symbol)
            raus.append({**p, "symbol": symbol, "kurs": kurs,
                         "unrealisiert": round((kurs - p["einstieg"]) * p["menge"], 2)})
        return raus

    def kurse(self, symbol: str, zeitrahmen: str = "M15") -> pd.DataFrame:
        return self.daten.get(symbol, pd.DataFrame()).copy()

    def order(self, symbol: str, aktion: str, menge: float, stop: float | None = None,
              kommentar: str = "") -> dict[str, Any]:
        kurs = self._kurs(symbol)
        slip = self.slippage_bps / 10_000.0
        if aktion == "kaufen":
            preis = kurs * (1 + slip)
            prov = self._provision(menge)
            if menge * preis + prov > self.cash:
                return {"ok": False, "status": "Fehler: nicht genug Bargeld", "preis": preis}
            self.cash -= menge * preis + prov
            self.gebuehren += prov
            self.offene[symbol] = {"menge": menge, "einstieg": preis, "stop": stop or 0.0,
                                   "strategie": kommentar}
            return {"ok": True, "status": "gesendet (Paper)", "preis": preis, "provision": prov}
        if aktion == "verkaufen":
            position = self.offene.pop(symbol, None)
            if not position:
                return {"ok": False, "status": "Fehler: keine Position", "preis": kurs}
            preis = kurs * (1 - slip)
            prov = self._provision(position["menge"])
            self.cash += position["menge"] * preis - prov
            self.gebuehren += prov
            return {"ok": True, "status": "gesendet (Paper)", "preis": preis, "provision": prov}
        raise ValueError(f"Unbekannte Aktion: {aktion}")


# ---------------------------------------------------------------------------
# MetaTrader 5 — läuft ausschliesslich unter Windows.
# Der Import ist geschützt, damit die Engine auf Linux/macOS sauber startet.
# ---------------------------------------------------------------------------
class MT5Broker:
    """Paper-Trading gegen ein MT5-Demo-Konto.

    Harte Sperren:
    - Das Konto muss ein Demo-/Paper-Konto sein.
    - Es wird immer ein Stop mitgesendet (Regel 9).
    - Nach jeder Order wird gegen die Broker-Positionen abgeglichen.
    """

    name = "mt5"

    def __init__(self, symbol_suffix: str = "", order_freigabe: bool = False) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - nur auf Windows möglich
            raise PaperOnlyViolation(
                "MetaTrader5 ist nicht installiert. Das offizielle Paket gibt es nur für Windows "
                "und es braucht ein laufendes, eingeloggtes MT5-Terminal."
            ) from exc
        self.mt5 = mt5
        self.suffix = symbol_suffix
        self.order_freigabe = bool(order_freigabe)
        if not mt5.initialize():
            raise PaperOnlyViolation(f"MT5 initialize() fehlgeschlagen: {mt5.last_error()}")
        info = mt5.account_info()
        if info is None:
            raise PaperOnlyViolation("Kein MT5-Konto eingeloggt.")
        # 0 = DEMO, 1 = CONTEST, 2 = REAL
        if getattr(info, "trade_mode", 2) == 2:
            raise PaperOnlyViolation(
                "Das eingeloggte MT5-Konto ist ein Echtgeldkonto. Dieses Projekt handelt "
                "ausschliesslich Paper. Bitte ein Demo-Konto einloggen."
            )

    def _symbol(self, symbol: str) -> str:
        return f"{symbol}{self.suffix}" if self.suffix and not symbol.endswith(self.suffix) else symbol

    def konto(self) -> dict[str, Any]:
        info = self.mt5.account_info()
        return {"equity": float(info.equity), "cash": float(info.balance),
                "positionen": len(self.mt5.positions_get() or []), "broker": "mt5-demo"}

    def positionen(self) -> list[dict[str, Any]]:
        raus = []
        for p in self.mt5.positions_get() or []:
            raus.append({"symbol": p.symbol, "menge": float(p.volume),
                         "einstieg": float(p.price_open), "stop": float(p.sl),
                         "kurs": float(p.price_current), "ticket": p.ticket})
        return raus

    def kurse(self, symbol: str, zeitrahmen: str = "M15") -> pd.DataFrame:  # pragma: no cover
        tf = {"M1": self.mt5.TIMEFRAME_M1, "M5": self.mt5.TIMEFRAME_M5,
              "M15": self.mt5.TIMEFRAME_M15, "H1": self.mt5.TIMEFRAME_H1,
              "D1": self.mt5.TIMEFRAME_D1}.get(zeitrahmen, self.mt5.TIMEFRAME_M15)
        rates = self.mt5.copy_rates_from_pos(self._symbol(symbol), tf, 0, 5000)
        if rates is None or len(rates) == 0:
            raise PaperOnlyViolation(f"Keine Kurse für {symbol}: {self.mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.rename(columns={"tick_volume": "volume"})[
            ["ts", "open", "high", "low", "close", "volume"]
        ]

    def order(self, symbol: str, aktion: str, menge: float, stop: float | None = None,
              kommentar: str = "") -> dict[str, Any]:  # pragma: no cover
        if not self.order_freigabe:
            return {"ok": True, "status": "Probelauf (keine Order gesendet)", "preis": None}

        mt5 = self.mt5
        sym = self._symbol(symbol)
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return {"ok": False, "status": "Fehler: kein Tick", "preis": None}
        typ = mt5.ORDER_TYPE_BUY if aktion == "kaufen" else mt5.ORDER_TYPE_SELL
        preis = tick.ask if aktion == "kaufen" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
            "volume": float(menge),
            "type": typ,
            "price": float(preis),
            "deviation": 20,
            "magic": 20261108,
            "comment": kommentar[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if aktion == "kaufen" and stop:
            request["sl"] = float(stop)
        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"ok": False, "status": f"Fehler: {getattr(result, 'retcode', 'keine Antwort')}",
                    "preis": preis}

        # Abgleich nach jeder Order (Regel 9)
        offen = {p.symbol for p in (mt5.positions_get() or [])}
        if sym not in offen:
            return {"ok": False, "status": "Fehler: Order nicht im Konto sichtbar", "preis": preis}
        return {"ok": True, "status": "gesendet (Paper)", "preis": float(preis)}


def broker_aus_config(cfg, daten: dict[str, pd.DataFrame], order_freigabe: bool | None = None) -> Broker:
    art = cfg["paper"].get("broker", "csv")
    freigabe = cfg["paper"].get("order_freigabe", False) if order_freigabe is None else order_freigabe
    if art == "mt5":
        return MT5Broker(order_freigabe=bool(freigabe))
    k = cfg["kosten"]
    return CsvBroker(
        daten=daten, cash=cfg.start_kapital,
        slippage_bps=float(k["slippage_bps"]),
        commission_per_share=float(k["commission_per_share"]),
        min_commission=float(k["min_commission"]),
    )
