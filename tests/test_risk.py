from __future__ import annotations

from dataclasses import replace

from orakel.config import RisikoGrenzen
from orakel.kern.risk import KontoZustand, Order, Risikomanager, positionsgroesse


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


def test_margin_und_hebel_lassen_das_risiko_die_groesse_bestimmen(cfg):
    g = replace(RisikoGrenzen.aus_config(cfg), max_position_pct=500.0,
                max_gross_exposure_pct=500.0, max_hebel=5.0)

    # Stop 0.5 % entfernt: 1 % Risiko will 2'000 Stück (2-faches Nominal).
    # Ohne Margin hätte der Bargeld-Deckel nur 900 Stück erlaubt.
    assert positionsgroesse(100_000, 100_000, 100.0, 99.5, g) == 2_000
    # Sehr enger Stop: Das Risiko will 10'000 Stück, der 5-fache Hebel mit
    # 10 % Margin-Puffer deckelt bei (90'000 × 5) / 100 = 4'500 Stück.
    assert positionsgroesse(100_000, 100_000, 100.0, 99.9, g) == 4_500
    # Bleibt nur der Margin-Puffer übrig, entsteht keine Position.
    assert positionsgroesse(100_000, 10_000, 100.0, 99.5, g) == 0


def test_manager_prueft_margin_statt_bargeld(cfg):
    g = replace(RisikoGrenzen.aus_config(cfg), max_position_pct=500.0,
                max_gross_exposure_pct=500.0, max_hebel=5.0)
    manager = Risikomanager(g)

    # 2-faches Nominal braucht 40 % Margin: gedeckt.
    assert manager.pruefe(Order("EURUSD", "kaufen", 2_000, 100.0), konto()).genehmigt
    # 5-faches Nominal bindet das ganze Konto als Margin: unter dem Puffer.
    zu_gross = manager.pruefe(Order("EURUSD", "kaufen", 5_000, 100.0), konto())
    assert not zu_gross.genehmigt
    assert any("Freie Margin" in x for x in zu_gross.gruende)


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
