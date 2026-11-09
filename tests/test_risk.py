from __future__ import annotations

from orakel.config import RisikoGrenzen
from orakel.risk import KontoZustand, Order, Risikomanager, positionsgroesse


def konto(**kw) -> KontoZustand:
    basis = dict(equity=100_000.0, cash=100_000.0, hoechststand=100_000.0,
                 tagesstart_equity=100_000.0, positionen=[])
    basis.update(kw)
    return KontoZustand(**basis)


def test_positionsgroesse_haelt_risiko_und_deckel_ein(cfg):
    g = RisikoGrenzen.aus_config(cfg)
    # 1 % von 100'000 = 1'000 Risiko, Stop-Abstand 2 -> 500 Stück
    # Deckel 20 % von 100'000 = 20'000 / Kurs 100 -> 200 Stück
    assert positionsgroesse(100_000, 100_000, 100.0, 98.0, g) == 200
    # Bei grossem Stop-Abstand begrenzt das Risiko
    assert positionsgroesse(100_000, 100_000, 100.0, 50.0, g) == 20


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


def test_engagement_deckel_wird_geprueft(cfg):
    manager = Risikomanager(RisikoGrenzen.aus_config(cfg))
    # 90 % des Kontos bereits investiert -> weiterer Kauf von 20'000 würde 110 % ergeben
    offen = [{"menge": 900, "kurs": 100.0}]
    pruefung = manager.pruefe(Order("EURUSD", "kaufen", 200, 100.0),
                              konto(cash=10_000.0, positionen=offen))
    assert not pruefung.genehmigt
    assert any("Gesamtengagement" in g for g in pruefung.gruende)
