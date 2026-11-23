from __future__ import annotations

from orakel import __main__ as cli
from orakel.kern.db import Facts


def _kandidat_anlegen(cfg, kerzen) -> int:
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern_df("TEST", "M15", kerzen)
    return db.validierung_speichern(
        symbol="TEST",
        strategie="donchian",
        schluessel="donchian|lookback=20",
        parameter={"lookback": 20},
        urteil="bestanden",
        beschreibung="Testkandidat",
        bericht={},
    )


def test_robustheit_cli_laedt_kandidat_und_gibt_kennzahlen_aus(
    cfg, kerzen, monkeypatch, capsys,
):
    kandidat = _kandidat_anlegen(cfg, kerzen)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    code = cli.main([
        "robustheit", "--kandidat", str(kandidat), "--laeufe", "2", "--seed", "7",
    ])

    ausgabe = capsys.readouterr().out
    assert code == 0
    assert f"Kandidat {kandidat}: TEST · donchian · lookback=20" in ausgabe
    assert "2 Läufe" in ausgabe
    assert "Basis: Drawdown" in ausgabe
    assert "Drawdown: p50" in ausgabe
    assert "Profit Factor: p50" in ausgabe


def test_robustheit_cli_meldet_unbekannten_kandidaten(cfg, monkeypatch, capsys):
    Facts(cfg.db_pfad)
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)

    code = cli.main(["robustheit", "--kandidat", "999999", "--laeufe", "1"])

    assert code == 2
    assert "nicht gefunden" in capsys.readouterr().err
