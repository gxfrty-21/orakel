from __future__ import annotations

import pytest

from orakel.config import RisikoGrenzen
from orakel.kern.risk import KontoZustand, Order, Risikomanager, positionsgroesse


def konto(**kw) -> KontoZustand:
    basis = dict(equity=100_000.0, cash=100_000.0, hoechststand=100_000.0,
                 tagesstart_equity=100_000.0, positionen=[])
    basis.update(kw)
    return KontoZustand(**basis)


def test_positionsgroesse_schoepft_das_risiko_bis_zum_stop_aus(cfg):
    g = RisikoGrenzen.aus_config(cfg)
    # 1 % von 100'000 = 1'000 Risiko, Stop-Abstand 2 -> 500 Stück.
    # Nominal 50'000, Margin bei 5x 10'000.
    assert positionsgroesse(100_000, 100_000, 100.0, 98.0, g) == 500
    # Bei grossem Stop-Abstand begrenzt weiterhin das Risiko.
    assert positionsgroesse(100_000, 100_000, 100.0, 50.0, g) == 20


def test_volle_risikomenge_bei_engem_stop(cfg):
    g = RisikoGrenzen.aus_config(cfg)
    # 1 % von 100'000 = 1'000 Risiko, Stop-Abstand 0.5 -> 2'000 Stück.
    # Nominal 200'000, Margin bei 5x 40'000; frei sind 90'000.
    # Der frühere 20-%-Deckel hätte nur 200 Stück (0.1 % Risiko) erlaubt.
    menge = positionsgroesse(100_000, 100_000, 100.0, 99.5, g)
    assert menge == 2_000
    assert menge * 0.5 == pytest.approx(1_000.0)


def test_margin_begrenzt_die_risikomenge(cfg):
    """Ein sehr enger Stop darf nicht mehr Nominal kaufen, als die Margin deckt."""
    g = RisikoGrenzen.aus_config(cfg)
    # 1 % Risiko bei 0.2 % Stop wären 5'000 Stück (Nominal 500'000, Margin
    # 100'000). Frei sind 90'000 -> 4'500 Stück, realisiertes Risiko 0.9 %.
    menge = positionsgroesse(100_000, 100_000, 100.0, 99.8, g)
    assert menge == 4_500
    assert menge * 0.2 == pytest.approx(900.0)
    assert menge * 0.2 <= 1_000.0


def test_hebelgrenze_begrenzt_trotz_grossem_bargeld(cfg):
    g = RisikoGrenzen.aus_config(cfg)
    # 1 % bei 0.1 % Stop wären 10'000 Stück; 5x Konto erlaubt höchstens 5'000.
    assert positionsgroesse(100_000, 1_000_000, 100.0, 99.9, g) == 5_000


def test_positionsgroesse_ohne_stop_ist_null(cfg):
    g = RisikoGrenzen.aus_config(cfg)
    assert positionsgroesse(100_000, 100_000, 100.0, 100.0, g) == 0


def test_kein_kauf_bei_15_offenen_positionen(cfg):
    g = RisikoGrenzen.aus_config(cfg)
    manager = Risikomanager(g)
    voll = [{"menge": 10, "kurs": 100.0} for _ in range(15)]
    pruefung = manager.pruefe(Order("EURUSD", "kaufen", 10, 100.0), konto(positionen=voll))
    assert not pruefung.genehmigt
    assert any("Zu viele offene Positionen" in g for g in pruefung.gruende)


def test_verkauf_ist_immer_erlaubt(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    gestoppt = konto(equity=80_000.0, hoechststand=100_000.0)
    assert manager.stopp_grund(gestoppt) is not None
    assert manager.pruefe(Order("EURUSD", "verkaufen", 10, 100.0), gestoppt).genehmigt


def test_not_stop_bei_zehn_prozent_drawdown(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    assert manager.stopp_grund(konto(equity=90_000.0)) is not None
    # Tagesstart mitverschieben, damit nur der Drawdown greift
    assert manager.stopp_grund(konto(equity=90_001.0, tagesstart_equity=90_001.0)) is None


def test_korrelation_ueber_grenze_lehnt_kauf_ab(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    pruefung = manager.pruefe(Order("US500", "kaufen", 10, 100.0),
                              konto(letzte_korrelation=0.92))
    assert not pruefung.genehmigt
    assert any("Korrelation" in g for g in pruefung.gruende)


def test_korrelation_im_betrag_und_unter_grenze(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    assert manager.pruefe(Order("US500", "kaufen", 10, 100.0),
                          konto(letzte_korrelation=0.20)).genehmigt
    # Starke Gegenbewegung ist ebenfalls Klumpenrisiko
    assert not manager.pruefe(Order("US500", "kaufen", 10, 100.0),
                              konto(letzte_korrelation=-0.90)).genehmigt


def test_margin_ueber_freiem_bargeld_wird_abgelehnt(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    # 100 Stück à 100 = 10'000 Nominal, Margin bei 5x = 2'000.
    # Bei 11'000 Bargeld blieben 9'000 < 10 % von 100'000.
    pruefung = manager.pruefe(Order("EURUSD", "kaufen", 100, 100.0),
                              konto(cash=11_000.0))
    assert not pruefung.genehmigt
    assert any("Bargeld" in g for g in pruefung.gruende)


def test_engagement_deckel_folgt_der_hebelgrenze(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    # 4500 Stück offen = 450 % Nominal; ein weiterer Kauf von 1000 Stück
    # würde 550 % erreichen und die 5x-Grenze reissen.
    offen = [{"menge": 4_500, "kurs": 100.0}]
    pruefung = manager.pruefe(Order("EURUSD", "kaufen", 1_000, 100.0),
                              konto(cash=1_000_000.0, positionen=offen))
    assert not pruefung.genehmigt
    assert any("Gesamtengagement" in g for g in pruefung.gruende)
