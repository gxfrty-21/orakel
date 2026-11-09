from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STANDARD_PFAD = Path("config.toml")


class Config:
    """Dünne, typisierte Hülle um config.toml."""

    def __init__(self, daten: dict[str, Any], pfad: Path) -> None:
        self._d = daten
        self.pfad = pfad

    def abschnitt(self, name: str) -> dict[str, Any]:
        return dict(self._d.get(name, {}))

    def wert(self, abschnitt: str, schluessel: str) -> Any:
        return self._d[abschnitt][schluessel]

    def __getitem__(self, name: str) -> dict[str, Any]:
        return self.abschnitt(name)

    # Bequeme Kurzformen für häufig gebrauchte Werte
    @property
    def db_pfad(self) -> Path:
        return Path(self._d["basis"]["db_pfad"])

    @property
    def daten_ordner(self) -> Path:
        return Path(self._d["basis"]["daten_ordner"])

    @property
    def vault_ordner(self) -> Path:
        return Path(self._d["basis"]["vault_ordner"])

    @property
    def start_kapital(self) -> float:
        return float(self._d["basis"]["start_kapital"])

    @property
    def bars_pro_jahr(self) -> int:
        return int(self._d["basis"].get("bars_pro_jahr", 24960))

    @property
    def waehrung(self) -> str:
        return str(self._d["basis"]["waehrung"])


def _umgebung(daten: dict[str, Any]) -> dict[str, Any]:
    """Überschreibt Speicherpfade per Umgebung — nötig für das /data-Volume im Container."""
    basis = daten.setdefault("basis", {})
    for schluessel, variable in (
        ("db_pfad", "ORAKEL_DB_PFAD"),
        ("daten_ordner", "ORAKEL_DATEN_ORDNER"),
        ("vault_ordner", "ORAKEL_VAULT_ORDNER"),
    ):
        wert = os.environ.get(variable)
        if wert:
            basis[schluessel] = wert
    return daten


def load_config(pfad: str | Path = STANDARD_PFAD) -> Config:
    p = Path(pfad)
    if not p.exists():
        raise FileNotFoundError(f"Konfiguration fehlt: {p}")
    with p.open("rb") as fh:
        daten = tomllib.load(fh)
    daten = _umgebung(daten)
    for pflicht in ("basis", "risiko", "kosten", "daten", "validierung", "research"):
        if pflicht not in daten:
            raise ValueError(f"config.toml: Abschnitt [{pflicht}] fehlt")
    return Config(daten, p)


@dataclass(frozen=True, slots=True)
class RisikoGrenzen:
    """Die harten Grenzen. Werden im Backtest und im Paper-Broker identisch geprüft."""

    risk_per_trade_pct: float
    max_drawdown_pct: float
    max_open_positions: int
    max_daily_loss_pct: float
    max_gross_exposure_pct: float
    max_position_pct: float
    min_cash_pct: float
    max_correlation: float
    correlation_lookback: int
    atr_stop_multiple: float

    @classmethod
    def aus_config(cls, cfg: Config) -> "RisikoGrenzen":
        r = cfg["risiko"]
        return cls(
            risk_per_trade_pct=float(r["risk_per_trade_pct"]),
            max_drawdown_pct=float(r["max_drawdown_pct"]),
            max_open_positions=int(r["max_open_positions"]),
            max_daily_loss_pct=float(r["max_daily_loss_pct"]),
            max_gross_exposure_pct=float(r["max_gross_exposure_pct"]),
            max_position_pct=float(r["max_position_pct"]),
            min_cash_pct=float(r["min_cash_pct"]),
            # deutscher Schlüssel in config.toml, englischer als Rückfall
            max_correlation=float(r.get("max_korrelation", r.get("max_correlation", 0.85))),
            correlation_lookback=int(r["correlation_lookback"]),
            atr_stop_multiple=float(r["atr_stop_multiple"]),
        )

    def als_dict(self) -> dict[str, Any]:
        return {
            "risk_per_trade_pct": self.risk_per_trade_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "max_open_positions": self.max_open_positions,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "max_gross_exposure_pct": self.max_gross_exposure_pct,
            "max_position_pct": self.max_position_pct,
            "min_cash_pct": self.min_cash_pct,
            "max_correlation": self.max_correlation,
            "correlation_lookback": self.correlation_lookback,
            "atr_stop_multiple": self.atr_stop_multiple,
        }
