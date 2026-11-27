"""MT5-Orderplanung ohne echten Orderpfad.

Das Projekt handelt nach ``AGENTS.md`` ausschliesslich Paper. Dieses Modul
schliesst die bisher fehlende Lücke zwischen Risikomanagement und einem
Broker-Auftrag: Es prüft Symbol-Metadaten, rundet Volumen auf den
Broker-Schritt, validiert Stop-Level und baut den vollständigen
``order_send``-Request. **Es ruft ``order_send`` bewusst nicht auf.** Der
einzige Gateway ist ein Trockenlauf, der jeden Sendeversuch ablehnt.

Damit ist die Ausführungsarchitektur vorhanden und testbar, ohne die
Paper-Sperre zu umgehen. Für einen späteren Demobetrieb muss die Policy
ausdrücklich geändert und ein separater, dann geprüfter Broker-Adapter
ergänzt werden.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .risk import positionsgroesse

# MT5-Konstanten (stabil über Terminalversionen). Sie werden hier als Zahlen
# geführt, damit das Modul ohne installiertes MetaTrader5 importierbar bleibt.
TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TIME_GTC = 0
ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
FUELLUNGEN = {"fok": ORDER_FILLING_FOK, "ioc": ORDER_FILLING_IOC,
              "return": ORDER_FILLING_RETURN}


class OrderFehler(ValueError):
    """Der Auftrag ist mit den gelieferten Symbol- oder Kontodaten nicht gültig."""


class PaperOnlyError(RuntimeError):
    """Ein echter Broker-Auftrag wurde versucht; die Paper-Sperre greift."""


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    """Die für eine Order relevanten Broker-Metadaten eines Symbols."""

    symbol: str
    digits: int
    point: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int = 0
    filling: str = "ioc"

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise OrderFehler("Symbolname fehlt")
        if self.digits < 0 or self.digits > 12:
            raise OrderFehler(f"{self.symbol}: ungültige Digits {self.digits}")
        if not math.isfinite(self.point) or self.point <= 0:
            raise OrderFehler(f"{self.symbol}: point muss positiv und endlich sein")
        if not math.isfinite(self.volume_min) or self.volume_min <= 0:
            raise OrderFehler(f"{self.symbol}: volume_min muss positiv sein")
        if not math.isfinite(self.volume_max) or self.volume_max < self.volume_min:
            raise OrderFehler(f"{self.symbol}: volume_max muss >= volume_min sein")
        if not math.isfinite(self.volume_step) or self.volume_step <= 0:
            raise OrderFehler(f"{self.symbol}: volume_step muss positiv sein")
        if self.stops_level < 0:
            raise OrderFehler(f"{self.symbol}: stops_level darf nicht negativ sein")
        if self.filling not in FUELLUNGEN:
            raise OrderFehler(f"{self.symbol}: unbekannte Füllungsart {self.filling!r}")


def _stellen(step: float) -> int:
    """Nachkommastellen, die ein Volumenschritt benötigt."""
    text = f"{step:.12f}".rstrip("0")
    return len(text.split(".", 1)[1]) if "." in text else 0


def normalisiere_volumen(menge: float, spec: SymbolSpec) -> float:
    """Rundet eine Stückzahl **nach unten** auf den Broker-Volumenschritt.

    Nach unten ist Pflicht: Aufrunden würde das im Risikokern berechnete
    Risiko überschreiten. Liegt das Ergebnis unter ``volume_min``, ist der
    Auftrag nicht ausführbar und es wird ``0.0`` geliefert.
    """
    if not math.isfinite(float(menge)) or menge <= 0:
        return 0.0
    schritte = math.floor(float(menge) / spec.volume_step + 1e-9)
    volumen = round(schritte * spec.volume_step, _stellen(spec.volume_step))
    if volumen + 1e-12 < spec.volume_min:
        return 0.0
    return round(min(volumen, spec.volume_max), _stellen(spec.volume_step))


@dataclass(frozen=True, slots=True)
class OrderPlan:
    """Ein vollständiger, noch nicht gesendeter MT5-Marktauftrag."""

    symbol: str
    volumen: float
    preis: float
    stop_loss: float
    take_profit: float | None
    risiko: float
    request: dict[str, Any]

    def als_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "volumen": self.volumen,
            "preis": self.preis,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risiko": round(self.risiko, 2),
            "request": dict(self.request),
        }


def plane_kauf(
    *,
    spec: SymbolSpec,
    ask: float,
    stop: float,
    equity: float,
    cash: float,
    grenzen: Any,
    take_profit: float | None = None,
    magic: int = 0,
    deviation: int = 20,
    kommentar: str = "",
) -> OrderPlan:
    """Baut aus einem risikogeprüften Kauf einen MT5-Request.

    Der Auftrag wird nur geplant. ``OrderPlan.request`` ist die exakte Struktur,
    die ein späterer, ausdrücklich freigegebener Adapter an ``order_send``
    übergeben würde.
    """
    if not math.isfinite(float(ask)) or ask <= 0:
        raise OrderFehler(f"{spec.symbol}: Ask muss positiv und endlich sein")
    if not math.isfinite(float(stop)) or stop <= 0:
        raise OrderFehler(f"{spec.symbol}: Stop muss positiv und endlich sein")
    if stop >= ask:
        raise OrderFehler(f"{spec.symbol}: Stop {stop} liegt nicht unter Ask {ask}")
    mindestabstand = spec.stops_level * spec.point
    if ask - stop < mindestabstand - 1e-12:
        raise OrderFehler(
            f"{spec.symbol}: Stop-Abstand {ask - stop:.6f} unterschreitet das "
            f"Broker-Stop-Level {mindestabstand:.6f}"
        )
    if take_profit is not None:
        if not math.isfinite(float(take_profit)) or take_profit <= ask:
            raise OrderFehler(f"{spec.symbol}: Take-Profit muss über Ask liegen")
        if take_profit - ask < mindestabstand - 1e-12:
            raise OrderFehler(f"{spec.symbol}: Take-Profit unterschreitet das Stop-Level")

    menge = positionsgroesse(float(equity), float(cash), float(ask), float(stop), grenzen)
    volumen = normalisiere_volumen(menge, spec)
    if volumen <= 0:
        raise OrderFehler(
            f"{spec.symbol}: berechnete Menge {menge:.6f} liegt unter dem "
            f"Broker-Minimum {spec.volume_min} oder ist null"
        )
    risiko = volumen * (ask - stop)
    risikogrenze = float(equity) * float(grenzen.risk_per_trade_pct) / 100.0
    if risiko > risikogrenze + 1e-9:
        raise OrderFehler(
            f"{spec.symbol}: Volumen {volumen} riskiert {risiko:.2f}, "
            f"Grenze {risikogrenze:.2f}"
        )

    request: dict[str, Any] = {
        "action": TRADE_ACTION_DEAL,
        "symbol": spec.symbol,
        "volume": volumen,
        "type": ORDER_TYPE_BUY,
        "price": float(ask),
        "sl": float(stop),
        "tp": float(take_profit) if take_profit is not None else 0.0,
        "deviation": max(0, int(deviation)),
        "magic": max(0, int(magic)),
        "comment": str(kommentar)[:31],
        "type_time": ORDER_TIME_GTC,
        "type_filling": FUELLUNGEN[spec.filling],
    }
    return OrderPlan(
        symbol=spec.symbol,
        volumen=volumen,
        preis=float(ask),
        stop_loss=float(stop),
        take_profit=float(take_profit) if take_profit is not None else None,
        risiko=risiko,
        request=request,
    )


@dataclass(frozen=True, slots=True)
class PositionsAbgleich:
    """Unterschiede zwischen lokalem Paper-Bestand und Broker-Bestand."""

    nur_lokal: tuple[str, ...] = ()
    nur_broker: tuple[str, ...] = ()
    abweichend: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (self.nur_lokal or self.nur_broker or self.abweichend)

    def als_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "nur_lokal": list(self.nur_lokal),
            "nur_broker": list(self.nur_broker),
            "abweichend": list(self.abweichend),
        }


def gleiche_positionen(
    lokal: Mapping[str, float], broker: Mapping[str, float], *,
    toleranz: float = 1e-9,
) -> PositionsAbgleich:
    """Vergleicht Positionsmengen je Symbol; erkennt fehlende und abweichende.

    Der Abgleich ist bewusst richtungsneutral: Ein lokaler Kauf ohne
    Broker-Position und eine Broker-Position ohne lokalen Eintrag sind beide
    ein Fehler und dürfen nicht stillschweigend als „bereits gebucht“ gelten.
    """
    lokal_n = {str(k).upper(): float(v) for k, v in lokal.items()}
    broker_n = {str(k).upper(): float(v) for k, v in broker.items()}
    nur_lokal = tuple(sorted(set(lokal_n) - set(broker_n)))
    nur_broker = tuple(sorted(set(broker_n) - set(lokal_n)))
    abweichend = tuple(sorted(
        symbol for symbol in set(lokal_n) & set(broker_n)
        if abs(lokal_n[symbol] - broker_n[symbol]) > toleranz
    ))
    return PositionsAbgleich(nur_lokal, nur_broker, abweichend)


class PaperOrderGateway:
    """Einziger Gateway: plant Aufträge, sendet aber nie einen echten Auftrag."""

    def senden(self, plan: OrderPlan) -> None:
        del plan
        raise PaperOnlyError(
            "Echte MT5-Orders sind durch AGENTS.md gesperrt. "
            "Der Request wurde nur geplant und nicht gesendet."
        )
