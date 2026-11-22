from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class Order:
    symbol: str
    aktion: str  # "kaufen" | "verkaufen"
    menge: float
    kurs: float
    strategie: str = ""
    stop: float | None = None


@dataclass(slots=True)
class KontoZustand:
    equity: float
    cash: float
    hoechststand: float
    tagesstart_equity: float
    positionen: list[dict] = field(default_factory=list)
    # Grösste Korrelation des geplanten Symbols zu einer offenen Position.
    # None = keine Vergleichsbasis; der Wert wird pro Auftrag gesetzt.
    letzte_korrelation: float | None = None

    @property
    def engagement_pct(self) -> float:
        if self.equity <= 0:
            return 0.0
        gebunden = sum(float(p.get("menge", 0)) * float(p.get("kurs", 0)) for p in self.positionen)
        return gebunden / self.equity * 100

    @property
    def drawdown_pct(self) -> float:
        if self.hoechststand <= 0:
            return 0.0
        return max(0.0, (self.hoechststand - self.equity) / self.hoechststand * 100)

    @property
    def tagesverlust_pct(self) -> float:
        if self.tagesstart_equity <= 0:
            return 0.0
        return max(0.0, (self.tagesstart_equity - self.equity) / self.tagesstart_equity * 100)


@dataclass(slots=True)
class Pruefung:
    genehmigt: bool
    gruende: list[str]

    def als_dict(self) -> dict:
        return {"genehmigt": self.genehmigt, "gruende": list(self.gruende)}


def positionsgroesse(equity: float, cash: float, preis: float, stop: float, grenzen) -> float:
    """Einzige Stelle, an der Positionsgrössen entstehen.

    Backtest und Paper-Trading nutzen exakt dieselbe Funktion (Regel 8).
    Die Risikomenge (1 % bis zum Stop) wird voll ausgeschöpft. Begrenzt wird
    sie durch die Margin-Buchung (Nominal / ``max_leverage`` aus dem freien
    Bargeld) und die explizite Hebelgrenze; einen separaten Nominaldeckel gibt
    es nicht mehr.
    """
    if preis <= 0 or equity <= 0 or grenzen.max_leverage <= 0:
        return 0.0
    abstand = preis - stop
    if abstand <= 0:
        return 0.0
    nach_risiko = equity * grenzen.risk_per_trade_pct / 100.0 / abstand
    verfuegbar = max(0.0, cash - equity * grenzen.min_cash_pct / 100.0)
    nach_margin = verfuegbar * grenzen.max_leverage / preis
    nach_hebel = equity * grenzen.max_leverage / preis
    return float(np.floor(min(nach_risiko, nach_margin, nach_hebel)))


class Risikomanager:
    """Unabhängige Instanz. Sie darf jeden Kauf ablehnen — Verkäufe nie."""

    def __init__(self, grenzen) -> None:
        self.g = grenzen

    # ---------- Handelsstopp ----------
    def stopp_grund(self, konto: KontoZustand) -> str | None:
        if konto.drawdown_pct >= self.g.max_drawdown_pct:
            return (f"Drawdown {konto.drawdown_pct:.2f} % erreicht die Grenze von "
                    f"{self.g.max_drawdown_pct} %")
        if konto.tagesverlust_pct >= self.g.max_daily_loss_pct:
            return (f"Tagesverlust {konto.tagesverlust_pct:.2f} % erreicht die Grenze von "
                    f"{self.g.max_daily_loss_pct} %")
        return None

    # ---------- Auftragsprüfung ----------
    def pruefe(self, order: Order, konto: KontoZustand) -> Pruefung:
        # Verkäufe bauen Risiko ab und sind immer erlaubt.
        if order.aktion == "verkaufen":
            return Pruefung(True, ["Verkauf baut Risiko ab und ist immer erlaubt"])

        gruende: list[str] = []
        stopp = self.stopp_grund(konto)
        if stopp:
            return Pruefung(False, [f"Handelsstopp: {stopp}"])

        if order.menge <= 0:
            return Pruefung(False, ["Menge ist null (Stop-Abstand zu gross oder Bargeld zu knapp)"])

        if len(konto.positionen) >= self.g.max_open_positions:
            gruende.append(f"Zu viele offene Positionen ({len(konto.positionen)} von max. "
                           f"{self.g.max_open_positions})")

        wert = order.menge * order.kurs
        if konto.equity > 0:
            margin = wert / self.g.max_leverage
            if margin > konto.cash + 1e-9:
                gruende.append(f"Margin {margin:.2f} übersteigt das freie Bargeld "
                               f"{konto.cash:.2f} (max. Hebel {self.g.max_leverage:g})")
            rest_cash = konto.cash - margin
            if rest_cash < konto.equity * self.g.min_cash_pct / 100.0 - 1e-9:
                gruende.append(f"Freies Bargeld würde unter {self.g.min_cash_pct} % fallen")
            neu_engagement = konto.engagement_pct + wert / konto.equity * 100
            hebelgrenze = self.g.max_leverage * 100.0
            if neu_engagement > hebelgrenze + 1e-9:
                gruende.append(f"Gesamtengagement würde {neu_engagement:.1f} % erreichen "
                               f"(max. Hebel {self.g.max_leverage:g} = {hebelgrenze:g} %)")

        if konto.letzte_korrelation is not None and abs(konto.letzte_korrelation) > self.g.max_correlation:
            gruende.append(f"Korrelation {konto.letzte_korrelation:.2f} zu einer offenen Position "
                           f"über max. {self.g.max_correlation}")

        if gruende:
            return Pruefung(False, gruende)
        return Pruefung(True, [
            f"Risiko pro Trade {self.g.risk_per_trade_pct} % eingehalten (Stop gesetzt)",
            f"Offene Positionen {len(konto.positionen)} von max. {self.g.max_open_positions}",
            f"Gesamtengagement {konto.engagement_pct:.1f} % von max. "
            f"{self.g.max_leverage * 100:g} % (Hebel {self.g.max_leverage:g})",
        ])
