from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass
import math
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
    def richter_zeitrahmen(self) -> str:
        """Zeitrahmen, den der Richter bewertet; der Paper-Takt bleibt bei M15."""
        return str(self._d["basis"].get("richter_zeitrahmen", "M15")).upper()

    def bars_pro_jahr_fuer(self, zeitrahmen: str) -> int:
        """Skaliert die M15-Basis aus [basis] auf den bewerteten Zeitrahmen."""
        from .kern.data import ZEITRAHMEN_MINUTEN
        minuten = ZEITRAHMEN_MINUTEN.get(zeitrahmen.upper())
        if minuten is None:
            raise ValueError(f"Unbekannter Zeitrahmen: {zeitrahmen}")
        return int(self.bars_pro_jahr * 15 / minuten)

    def mit_bars_pro_jahr(self, bars: int) -> Config:
        """Kopie mit angepasster Jahresbasis, ohne die geladene Konfiguration zu ändern."""
        daten = copy.deepcopy(self._d)
        daten.setdefault("basis", {})["bars_pro_jahr"] = bars
        return Config(daten, self.pfad)

    def min_kerzen_fuer(self, zeitrahmen: str) -> int:
        """Skaliert die M15-Mindestzahl aus [daten] auf den Zeitrahmen."""
        from .kern.data import kerzen_minimum
        return kerzen_minimum(int(self["daten"].get("min_kerzen", 1)), zeitrahmen)

    def fuer_zeitrahmen(self, zeitrahmen: str) -> Config:
        """Kopie mit Jahresbasis und Mindestkerzen des gelesenen Zeitrahmens.

        Beide Werte gelten in der Konfiguration für M15. Der Richter muss mit
        dem Raster rechnen, das er tatsächlich liest; die geladene Konfiguration
        bleibt unverändert.
        """
        daten = copy.deepcopy(self._d)
        daten.setdefault("basis", {})["bars_pro_jahr"] = self.bars_pro_jahr_fuer(zeitrahmen)
        if "daten" in daten:
            daten["daten"]["min_kerzen"] = self.min_kerzen_fuer(zeitrahmen)
        return Config(daten, self.pfad)

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


def _zahl(daten: dict[str, Any], abschnitt: str, schluessel: str, *,
          minimum: float | None = None, maximum: float | None = None,
          ganzzahl: bool = False, standard: float | None = None) -> float:
    """Liest eine Zahl und prüft Typ und Wertebereich.

    Fehlt der Schlüssel, wird ``standard`` verwendet (nur für optionale Werte).
    """
    werte = daten.get(abschnitt) or {}
    if schluessel not in werte:
        if standard is None:
            raise ValueError(f'config.toml: [{abschnitt}] {schluessel} fehlt')
        return standard
    wert = werte[schluessel]
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        raise ValueError(f'config.toml: [{abschnitt}] {schluessel} muss eine Zahl sein, '
                         f'ist aber {wert!r}')
    if ganzzahl:
        if int(wert) != wert:
            raise ValueError(f'config.toml: [{abschnitt}] {schluessel} muss eine Ganzzahl sein, '
                             f'ist aber {wert!r}')
    zahl = float(wert)
    if not math.isfinite(zahl):
        raise ValueError(f'config.toml: [{abschnitt}] {schluessel} muss endlich sein')
    if minimum is not None and zahl < minimum:
        raise ValueError(f'config.toml: [{abschnitt}] {schluessel} muss >= {minimum} sein, '
                         f'ist aber {zahl}')
    if maximum is not None and zahl > maximum:
        raise ValueError(f'config.toml: [{abschnitt}] {schluessel} muss <= {maximum} sein, '
                         f'ist aber {zahl}')
    return zahl


def validiere_config(daten: dict[str, Any]) -> None:
    """Lehnt unbrauchbare Konfigurationen beim Laden ab.

    Die Grenzen sind bewusst dieselben, die der Paper-Takt und der Backtest
    voraussetzen. Negative Kosten, Null-Risikogrenzen oder ein Kapital von null
    dürfen nicht erst im laufenden Takt auffallen.
    """
    basis = daten.get('basis') or {}
    kapital = _zahl(daten, 'basis', 'start_kapital', minimum=0.000001)
    if not isinstance(basis.get('db_pfad'), str) or not basis['db_pfad'].strip():
        raise ValueError('config.toml: [basis] db_pfad muss ein nicht-leerer Pfad sein')
    _zahl(daten, 'basis', 'bars_pro_jahr', minimum=1, ganzzahl=True, standard=24960)
    richter_tf = str(basis.get('richter_zeitrahmen', 'M15')).upper()
    from .kern.data import ZEITRAHMEN
    if richter_tf not in ZEITRAHMEN:
        raise ValueError(f"config.toml: [basis] richter_zeitrahmen muss einer von "
                         f"{', '.join(ZEITRAHMEN)} sein, ist aber {richter_tf!r}")

    _zahl(daten, 'risiko', 'risk_per_trade_pct', minimum=0.000001, maximum=100.0)
    _zahl(daten, 'risiko', 'max_drawdown_pct', minimum=0.000001, maximum=100.0)
    _zahl(daten, 'risiko', 'max_open_positions', minimum=1, ganzzahl=True)
    _zahl(daten, 'risiko', 'max_daily_loss_pct', minimum=0.000001, maximum=100.0)
    _zahl(daten, 'risiko', 'max_leverage', minimum=1.0, maximum=100.0)
    _zahl(daten, 'risiko', 'min_cash_pct', minimum=0.0, maximum=99.999999)
    risiko = daten.get('risiko') or {}
    if not any(k in risiko for k in ('max_korrelation', 'max_correlation')):
        raise ValueError('config.toml: [risiko] max_korrelation fehlt')
    for schluessel in ('max_korrelation', 'max_correlation'):
        if schluessel in risiko:
            _zahl(daten, 'risiko', schluessel, minimum=0.0, maximum=1.0)
    _zahl(daten, 'risiko', 'correlation_lookback', minimum=2, ganzzahl=True)
    _zahl(daten, 'risiko', 'atr_stop_multiple', minimum=0.000001)
    _zahl(daten, 'risiko', 'risiko_stopp_freigabe_takte', minimum=1, ganzzahl=True,
          standard=2.0)

    kosten = daten.get('kosten') or {}
    modell = kosten.get('modell', 'stueck')
    if modell not in ('stueck', 'spread'):
        raise ValueError("config.toml: [kosten] modell muss 'stueck' oder 'spread' "
                         f'sein, ist aber {modell!r}')
    _zahl(daten, 'kosten', 'commission_per_share', minimum=0.0)
    _zahl(daten, 'kosten', 'min_commission', minimum=0.0)
    _zahl(daten, 'kosten', 'slippage_bps', minimum=0.0, maximum=9999.999999)
    # Nur für modell = "spread": quotierter Spread in Pips und Pip-Grösse.
    _zahl(daten, 'kosten', 'spread_pips', minimum=0.0, standard=0.0)
    _zahl(daten, 'kosten', 'pip_groesse', minimum=0.000000001, standard=0.0001)

    if 'daten' in daten:
        _zahl(daten, 'daten', 'min_kerzen', minimum=1, ganzzahl=True, standard=1.0)
        _zahl(daten, 'daten', 'max_luecke_pct', minimum=0.0, maximum=100.0, standard=5.0)
        _zahl(daten, 'daten', 'max_sprung_pct', minimum=0.0, standard=25.0)
        _zahl(daten, 'daten', 'max_alter_tage', minimum=0.000001, standard=5.0)
        daten_abschnitt = daten.get('daten') or {}
        if daten_abschnitt.get('server_versatz_stunden') is not None:
            _zahl(daten, 'daten', 'server_versatz_stunden', minimum=-24.0, maximum=24.0)
            if daten_abschnitt.get('server_zeitzone'):
                raise ValueError('config.toml: [daten] server_zeitzone und '
                                 'server_versatz_stunden schliessen sich aus')
        for schluessel in ('max_kurs_alter_stunden', 'max_kurs_alter_stunden_m1',
                           'max_kurs_alter_stunden_m5', 'max_kurs_alter_stunden_m15',
                           'max_kurs_alter_stunden_h1'):
            if schluessel in (daten.get('daten') or {}):
                _zahl(daten, 'daten', schluessel, minimum=0.000001)
    if kapital <= 0:  # pragma: no cover - von _zahl bereits abgelehnt
        raise ValueError('config.toml: [basis] start_kapital muss positiv sein')


def load_config(pfad: str | Path = STANDARD_PFAD) -> Config:
    p = Path(pfad)
    if not p.exists():
        raise FileNotFoundError(f"Konfiguration fehlt: {p}")
    with p.open("rb") as fh:
        daten = tomllib.load(fh)
    daten = _umgebung(daten)
    for pflicht in ("basis", "risiko", "kosten", "validierung", "research"):
        if pflicht not in daten:
            raise ValueError(f"config.toml: Abschnitt [{pflicht}] fehlt")
    validiere_config(daten)
    return Config(daten, p)


@dataclass(frozen=True, slots=True)
class RisikoGrenzen:
    """Die harten Grenzen. Werden im Backtest und im Paper-Takt identisch geprüft."""

    risk_per_trade_pct: float
    max_drawdown_pct: float
    max_open_positions: int
    max_daily_loss_pct: float
    max_leverage: float
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
            max_leverage=float(r["max_leverage"]),
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
            "max_leverage": self.max_leverage,
            "min_cash_pct": self.min_cash_pct,
            "max_correlation": self.max_correlation,
            "correlation_lookback": self.correlation_lookback,
            "atr_stop_multiple": self.atr_stop_multiple,
        }
