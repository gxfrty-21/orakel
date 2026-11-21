"""Kosten je Seite: Kommission pro Stück oder Forex-Spread in Pips.

Backtest und Paper-Takt buchen dieselben Kosten; die Formel steht deshalb nur
hier. ``[kosten] modell`` wählt sie:

- ``stueck``: Aktien und andere Stück-Instrumente. Kommission je Stück,
  mindestens ``min_commission``.
- ``spread``: Devisen und CFDs. Der quotierte Spread wird je Seite zur Hälfte
  bezahlt: ``menge * spread_pips * pip_groesse / 2``. Eine Kommission fällt
  dabei nicht an.

Beispiel EURUSD: 1 Pip = 0.0001, quotierter Spread 1.0 Pip. 18'500 Einheiten
kosten 0.93 USD je Seite. Das Stück-Modell mit 0.005 je Einheit verlangte
92.50 USD je Seite — rund 46 Basispunkte, die keine Forex-Strategie verdient.
"""

from __future__ import annotations

from ..config import Config

MODELLE = ("stueck", "spread")


def kostenmodell(cfg: Config) -> str:
    """Gibt das konfigurierte Kostenmodell zurück (Standard: ``stueck``)."""
    modell = str(cfg["kosten"].get("modell", "stueck"))
    if modell not in MODELLE:
        raise ValueError(
            "[kosten] modell muss 'stueck' oder 'spread' sein, "
            f"ist aber {modell!r}"
        )
    return modell


def kosten_je_seite(menge: float, cfg: Config) -> float:
    """Kosten einer Seite (Kauf oder Verkauf) in Kontowährung."""
    k = cfg["kosten"]
    if kostenmodell(cfg) == "spread":
        return (
            abs(menge)
            * float(k.get("spread_pips", 0.0))
            * float(k.get("pip_groesse", 0.0001))
            / 2.0
        )
    return max(
        float(k["min_commission"]),
        abs(menge) * float(k["commission_per_share"]),
    )
