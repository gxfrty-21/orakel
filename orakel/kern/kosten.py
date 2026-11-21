"""Kosten je Seite: Kommission pro Stück oder Forex-Spread in Pips.

Backtest und Paper-Takt buchen dieselben Kosten; die Formel steht deshalb nur
hier. Die Instrumentenklasse bestimmt Modell, Pip-Grösse und Spread
(``INSTRUMENTE``): Devisen zahlen den halben quotierten Spread, Stück-
Instrumente eine Kommission. Unbekannte Symbole nutzen die Werte aus
``[kosten]``.

- ``spread``: ``menge * spread_pips * pip_groesse / 2``; keine Kommission.
- ``stueck``: ``max(min_commission, menge * commission_per_share)``.

Beispiel EURUSD: 1 Pip = 0.0001, quotierter Spread 1.0 Pip. 18'500 Einheiten
kosten 0.93 USD je Seite. Das Stück-Modell mit 0.005 je Einheit verlangte
92.50 USD je Seite — rund 46 Basispunkte, die keine Forex-Strategie verdient.

Der Pip-Wert gilt in der Kurswährung des Symbols. Bei USDJPY ist das JPY; eine
Umrechnung in die Kontowährung findet nicht statt (die synthetischen Kurse
liegen nahe 1, daher fällt das im Paper-Betrieb nicht ins Gewicht).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Config

MODELLE = ("stueck", "spread")


@dataclass(frozen=True)
class Instrument:
    """Kostenprofil einer Instrumentenklasse."""

    klasse: str
    modell: str
    pip_groesse: float
    spread_pips: float


# Kleine, bewusst explizite Zuordnung. Alles andere fällt auf [kosten] zurück.
INSTRUMENTE: dict[str, Instrument] = {
    "fx": Instrument("fx", "spread", 0.0001, 1.0),
    "fx_jpy": Instrument("fx_jpy", "spread", 0.01, 1.0),
    "index": Instrument("index", "spread", 1.0, 0.5),
}
INDEZES = frozenset({"US500", "US30", "NAS100", "GER40", "DE40", "UK100", "JP225"})


def instrument(symbol: str | None) -> Instrument | None:
    """Leitet die Instrumentenklasse aus dem Symbol ab.

    Broker-Zusätze hinter einem Punkt (``EURUSD.a``) werden ignoriert. Sechs
    Buchstaben gelten als Devisenpaar; endet es auf ``JPY``, ist ein Pip 0.01
    statt 0.0001. Indizes stehen in ``INDEZES``; alles andere ist unbekannt und
    nutzt die Konfiguration.
    """
    if not symbol:
        return None
    name = str(symbol).upper().split(".")[0].strip()
    if len(name) == 6 and name.isalpha():
        return INSTRUMENTE["fx_jpy"] if name.endswith("JPY") else INSTRUMENTE["fx"]
    if name in INDEZES:
        return INSTRUMENTE["index"]
    return None


def kostenmodell(cfg: Config) -> str:
    """Gibt das konfigurierte Standardmodell zurück (Standard: ``stueck``)."""
    modell = str(cfg["kosten"].get("modell", "stueck"))
    if modell not in MODELLE:
        raise ValueError(
            "[kosten] modell muss 'stueck' oder 'spread' sein, "
            f"ist aber {modell!r}"
        )
    return modell


def modell_fuer(cfg: Config, symbol: str | None = None) -> str:
    """Kostenmodell des Symbols, sonst das konfigurierte Standardmodell."""
    profil = instrument(symbol)
    return profil.modell if profil else kostenmodell(cfg)


def kosten_je_seite(menge: float, cfg: Config, symbol: str | None = None) -> float:
    """Kosten einer Seite (Kauf oder Verkauf) in Kontowährung.

    Mit ``symbol`` gilt das Profil der Instrumentenklasse; ohne Symbol oder bei
    unbekanntem Instrument die Werte aus ``[kosten]``.
    """
    k = cfg["kosten"]
    profil = instrument(symbol)
    if modell_fuer(cfg, symbol) == "spread":
        spread = profil.spread_pips if profil else float(k.get("spread_pips", 0.0))
        pip = profil.pip_groesse if profil else float(k.get("pip_groesse", 0.0001))
        return abs(menge) * spread * pip / 2.0
    return max(
        float(k["min_commission"]),
        abs(menge) * float(k["commission_per_share"]),
    )
