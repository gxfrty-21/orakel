"""Kosten je Seite: Kommission pro Stück oder Forex-Spread in Pips.

Backtest und Paper-Takt buchen dieselben Kosten; die Formel steht deshalb nur
hier. Die Instrumentenklasse bestimmt Modell, Pip-Grösse und Spread
(``INSTRUMENTE``): Devisen zahlen den halben quotierten Spread, Stück-
Instrumente eine Kommission. Nur Devisenpaare haben ein Profil; alles andere —
auch Indizes — nutzt die Werte aus ``[kosten]``.

- ``spread``: ``menge * spread_pips * pip_groesse / 2``; keine Kommission.
- ``stueck``: ``max(min_commission, menge * commission_per_share)``.

Beispiel EURUSD: 1 Pip = 0.0001, quotierter Spread 1.0 Pip. 18'500 Einheiten
kosten 0.93 USD je Seite. Das Stück-Modell mit 0.005 je Einheit verlangte
92.50 USD je Seite — rund 46 Basispunkte, die keine Forex-Strategie verdient.

Der Pip-Wert gilt in der Kurswährung des Symbols. Notiert das Paar in der
Kontowährung (EURUSD bei USD-Konto), ist der Betrag direkt brauchbar; ist die
Kontowährung die Basiswährung (USDJPY bei USD-Konto), wird durch den Kurs
geteilt. Fehlt für eine Drittwährung der Kurs zur Kontowährung (etwa EURGBP
bei USD-Konto), meldet die Funktion einen Fehler statt einer falschen Zahl.
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


# Kleine, bewusst explizite Zuordnung für Devisen. Alles andere fällt auf
# [kosten] zurück; für Indizes gibt es keinen belegten Spread-Wert.
INSTRUMENTE: dict[str, Instrument] = {
    "fx": Instrument("fx", "spread", 0.0001, 1.0),
    "fx_jpy": Instrument("fx_jpy", "spread", 0.01, 1.0),
}


# Währungscodes, an denen sich ein Devisenpaar erkennen lässt. Metalle wie
# XAU oder XAG fehlen bewusst: Sie haben andere Pip-Grössen als Devisen.
WAEHRUNGEN = frozenset({
    "USD", "EUR", "JPY", "GBP", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK",
    "DKK", "PLN", "CZK", "HUF", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH",
})


def _waehrungspaar(symbol: str | None) -> tuple[str, str] | None:
    """Basis- und Kurswährung eines Devisenpaars, sonst ``None``.

    Broker-Suffixe wie ``EURUSDm``, ``EURUSD_RAW`` oder ``EURUSD.pro`` werden
    ignoriert: Massgeblich sind die ersten sechs Buchstaben, und beide Hälften
    müssen bekannte Währungscodes sein.
    """
    text = str(symbol or "").upper().strip()
    name = text.split("_")[0].split(".")[0].split("-")[0].strip()
    if len(name) < 6 or not name[:6].isalpha():
        return None
    basis, quote = name[:3], name[3:6]
    if basis in WAEHRUNGEN and quote in WAEHRUNGEN:
        return basis, quote
    return None


def instrument(symbol: str | None) -> Instrument | None:
    """Leitet die Instrumentenklasse aus dem Symbol ab.

    Broker-Suffixe (``EURUSDm``, ``EURUSD_RAW``, ``EURUSD.pro``) ändern die
    Klasse nicht. Erkannt wird ein Paar aus zwei bekannten Währungscodes; ist
    die Kurswährung ``JPY``, gilt ein Pip von 0.01 statt 0.0001. Alles andere
    — auch Indizes und Metalle — ist unbekannt und nutzt die Konfiguration.
    """
    paar = _waehrungspaar(symbol)
    if paar is None:
        return None
    return INSTRUMENTE["fx_jpy"] if paar[1] == "JPY" else INSTRUMENTE["fx"]


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


def _in_kontowaehrung(betrag: float, cfg: Config, symbol: str | None,
                      kurs: float | None) -> float:
    """Rechnet einen Spread-Betrag aus der Kurswährung in die Kontowährung um.

    ``kurs`` ist der Preis des Symbols (Kurswährung je Basiswährung). Bei
    USDJPY und USD-Konto wird der in JPY gerechnete Betrag also durch den
    USDJPY-Kurs geteilt; bei EURUSD ist keine Umrechnung nötig.
    """
    kontowaehrung = cfg.waehrung.upper()
    paar = _waehrungspaar(symbol)
    if paar is None:
        return betrag
    basis, quote = paar
    if quote == kontowaehrung:
        return betrag
    if basis != kontowaehrung:
        raise ValueError(
            f"Kosten für {symbol} brauchen einen Kurs {quote}/{kontowaehrung}; "
            "ohne ihn wäre der Betrag in der falschen Währung."
        )
    if kurs is None or float(kurs) <= 0:
        raise ValueError(
            f"Kosten für {symbol} brauchen den Kurs, um {quote} in "
            f"{kontowaehrung} umzurechnen."
        )
    return betrag / float(kurs)


def kosten_je_seite(menge: float, cfg: Config, symbol: str | None = None, *,
                   kurs: float | None = None) -> float:
    """Kosten einer Seite (Kauf oder Verkauf) in Kontowährung.

    Mit ``symbol`` gilt das Profil der Instrumentenklasse; ohne Symbol oder bei
    unbekanntem Instrument die Werte aus ``[kosten]``. ``kurs`` ist der Preis
    des Symbols und wird nur gebraucht, wenn der Spread in einer anderen
    Währung als der Kontowährung anfällt (etwa USDJPY bei USD-Konto).
    """
    k = cfg["kosten"]
    profil = instrument(symbol)
    if modell_fuer(cfg, symbol) == "spread":
        spread = profil.spread_pips if profil else float(k.get("spread_pips", 0.0))
        pip = profil.pip_groesse if profil else float(k.get("pip_groesse", 0.0001))
        betrag = abs(menge) * spread * pip / 2.0
        return _in_kontowaehrung(betrag, cfg, symbol, kurs)
    return max(
        float(k["min_commission"]),
        abs(menge) * float(k["commission_per_share"]),
    )
