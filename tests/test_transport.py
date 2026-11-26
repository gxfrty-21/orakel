from __future__ import annotations

import argparse
import hashlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from orakel import transport, web
from orakel.kern.data import synthetische_kerzen
from orakel.kern.db import Facts

TOKEN = "transport-test-token-" + "x" * 32
KEY_ID = "windows-1"
SYMBOL = "EURUSD"
TF = "M15"


def _frische_m15(kerzen: int = 1250, alter_stunden: float = 1.0) -> pd.DataFrame:
    ende = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=alter_stunden)
    start = ende - pd.Timedelta(minutes=15 * (kerzen - 1))
    reihe = synthetische_kerzen(
        "X", kerzen=kerzen, seed=11, start=start.isoformat())
    # Die CSV schreibt Sekunden; ohne diese Normalisierung wären dieselben
    # Minuten in DB und Upload wegen der Mikrosekunden verschiedene Zeitstempel.
    reihe["ts"] = reihe["ts"].dt.floor("min")
    return reihe


def _als_mt5(df: pd.DataFrame) -> bytes:
    zeilen = [
        "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>"
    ]
    for r in df.itertuples(index=False):
        zeilen.append(
            f"{r.ts:%Y.%m.%d}\t{r.ts:%H:%M:%S}\t{r.open}\t{r.high}\t{r.low}"
            f"\t{r.close}\t{int(r.volume)}\t0\t2")
    return ("\n".join(zeilen) + "\n").encode("utf-8")


def _dateiname(df: pd.DataFrame, symbol: str = SYMBOL, tf: str = TF) -> str:
    return f"{symbol}_{tf}_{pd.Timestamp(df['ts'].iloc[-1]):%Y%m%d}.csv"


def _headers(body: bytes, dateiname: str, *, token: str = TOKEN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Orakel-Key-Id": KEY_ID,
        "X-Orakel-Content-SHA256": hashlib.sha256(body).hexdigest(),
        "X-Orakel-Dateiname": dateiname,
        "Content-Type": "text/csv",
    }


def _transport_aktiv(monkeypatch, *, aktiv: bool = True) -> None:
    monkeypatch.setenv(
        "ORAKEL_TRANSPORT_AKTIV", "1" if aktiv else "0")
    monkeypatch.setenv("ORAKEL_TRANSPORT_TOKEN", TOKEN)
    monkeypatch.setenv("ORAKEL_TRANSPORT_KEY_ID", KEY_ID)
    monkeypatch.setenv("ORAKEL_TRANSPORT_SYMBOLE", SYMBOL)


def _client(cfg, monkeypatch) -> TestClient:
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    return TestClient(web.create_app("unbenutzt.toml", hintergrund=False))


def _bootstrap(db: Facts, cfg) -> dict:
    return transport.bootstrap_freigeben(db, cfg, SYMBOL, TF)


def _post(client: TestClient, df: pd.DataFrame, *, headers=None):
    body = _als_mt5(df)
    return client.post(
        transport.TRANSPORT_PFAD,
        content=body,
        headers=headers or _headers(body, _dateiname(df)),
    )


def test_gueltiger_upload_importiert_und_prueft_die_zusammengefuehrte_reihe(
        cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1200])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        antwort = _post(client, reihe.iloc[-100:])

    assert antwort.status_code == 200, antwort.text
    daten = antwort.json()
    assert daten["ok"] is True
    assert daten["code"] == "importiert"
    assert daten["uebersprungen"] is False
    assert daten["kerzen"] == 100
    assert daten["frische"]["frisch"] is True
    assert len(db.datenimporte()) == 1
    assert len(db.kerzen(SYMBOL, TF)) == 1250
    assert db.zustand("datenquelle") == "csv"
    assert (cfg.daten_ordner / daten["datei"]).exists()
    assert not list((cfg.daten_ordner / "inbox").iterdir())
    assert TOKEN not in " ".join(str(z["text"]) for z in db.ereignisse())


def test_identischer_upload_ist_idempotent(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1200])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        erst = _post(client, reihe.iloc[-100:])
        zweit = _post(client, reihe.iloc[-100:])

    assert erst.status_code == 200, erst.text
    assert zweit.status_code == 200, zweit.text
    assert zweit.json()["uebersprungen"] is True
    assert zweit.json()["code"] == "bereits_vorhanden"
    assert len(db.datenimporte()) == 1
    assert len(db.kerzen(SYMBOL, TF)) == 1250


def test_ohne_bootstrap_kein_import(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1200])
    client = _client(cfg, monkeypatch)

    with client:
        antwort = _post(client, reihe.iloc[-100:])

    assert antwort.status_code == 409
    assert antwort.json()["code"] == "bootstrap_erforderlich"
    assert db.datenimporte() == []
    assert len(db.kerzen(SYMBOL, TF)) == 1200


def test_bootstrap_wird_bei_materiell_verkürzter_reihe_ungueltig(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1200])
    _bootstrap(db, cfg)
    # Weniger als die konfigurierte Mindesthistorie: Der Marker ist nicht mehr
    # durch die tatsächliche Reihe gedeckt.
    with db.conn() as c:
        c.execute(
            "DELETE FROM kerzen WHERE symbol=? AND zeitrahmen=? AND ts IN ("
            "SELECT ts FROM kerzen WHERE symbol=? AND zeitrahmen=? ORDER BY ts LIMIT 1200)",
            (SYMBOL, TF, SYMBOL, TF),
        )
    client = _client(cfg, monkeypatch)

    with client:
        antwort = _post(client, reihe.iloc[-100:])

    assert antwort.status_code == 409
    assert antwort.json()["code"] == "bootstrap_erforderlich"


def test_alte_reihe_wird_nach_dem_import_zurueckgerollt(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    alt = _frische_m15(alter_stunden=24 * 365 * 3)
    db.kerzen_speichern_df(SYMBOL, TF, alt.iloc[:1250])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        antwort = _post(client, alt.iloc[-100:])

    assert antwort.status_code == 409
    assert antwort.json()["code"] == "daten_veraltet"
    assert db.datenimporte() == []
    assert len(db.kerzen(SYMBOL, TF)) == 1250
    assert db.zustand("datenquelle") is None
    assert not (cfg.daten_ordner / _dateiname(alt)).exists()


def test_ledger_ohne_kerzen_wird_repariert(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1200])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        assert _post(client, reihe.iloc[-100:]).status_code == 200
        eintrag = db.datenimporte()[0]
        # Eine Kerze aus genau dieser Buchung fehlt, der Rest der Reihe ist da.
        with db.conn() as c:
            c.execute(
                "DELETE FROM kerzen WHERE symbol=? AND zeitrahmen=? AND ts=?",
                (SYMBOL, TF, eintrag["bis"]),
            )
        assert len(db.kerzen(SYMBOL, TF)) == 1249
        antwort = _post(client, reihe.iloc[-100:])

    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["uebersprungen"] is False
    assert len(db.datenimporte()) == 1
    assert len(db.kerzen(SYMBOL, TF)) == 1250


def test_gebuchte_datei_repariert_fehlende_reihe_neue_deltas_bleiben_am_gate(
        cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1200])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        # Die volle Reihe ist als eine Datei gebucht.
        assert _post(client, reihe).status_code == 200
        assert len(db.datenimporte()) == 1

        # Die ganze Reihe fehlt; der Marker ist damit nicht mehr gedeckt.
        with db.conn() as c:
            c.execute("DELETE FROM kerzen WHERE symbol=? AND zeitrahmen=?",
                      (SYMBOL, TF))
        assert db.kerzen(SYMBOL, TF) == []

        # Auch ohne Symbol-Allowlist bleibt die Reihe über den Ledger bekannt.
        # Ein neuer Hash ist aber keine Reparatur der gebuchten Datei und muss
        # am Bootstrap-Gate scheitern.
        monkeypatch.delenv("ORAKEL_TRANSPORT_SYMBOLE", raising=False)
        neues_delta = reihe.iloc[-100:].copy()
        neues_delta["volume"] = neues_delta["volume"] + 1
        neu = _post(client, neues_delta)
        assert neu.status_code == 409
        assert neu.json()["code"] == "bootstrap_erforderlich"
        assert db.kerzen(SYMBOL, TF) == []
        assert len(db.datenimporte()) == 1

        # Die vorhandene Ledger-Buchung öffnet den Reparaturpfad.
        repariert = _post(client, reihe)

    assert repariert.status_code == 200, repariert.text
    assert repariert.json()["code"] == "importiert"
    assert len(db.kerzen(SYMBOL, TF)) == 1250
    assert len(db.datenimporte()) == 1
    assert db.zustand("datenquelle") == "csv"


def test_token_key_id_und_feature_flag(cfg, monkeypatch):
    _transport_aktiv(monkeypatch, aktiv=False)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1250])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)
    body = _als_mt5(reihe.iloc[-100:])
    dateiname = _dateiname(reihe)

    with client:
        deaktiviert = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, dateiname))
        assert deaktiviert.status_code == 503
        assert deaktiviert.json()["code"] == "transport_deaktiviert"

    monkeypatch.setenv("ORAKEL_TRANSPORT_AKTIV", "1")
    with client:
        falsch = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, dateiname, token="falsch"))  # noqa: S106 - Testtoken
        assert falsch.status_code == 401
        assert falsch.json()["code"] == "token_ungueltig"

        ohne_key = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers={k: v for k, v in _headers(body, dateiname).items()
                     if k != "X-Orakel-Key-Id"})
        assert ohne_key.status_code == 400
        assert ohne_key.json()["code"] == "key_id_fehlt"

        falscher_key = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers={**_headers(body, dateiname), "X-Orakel-Key-Id": "windows-2"})
        assert falscher_key.status_code == 403
        assert falscher_key.json()["code"] == "key_id_ungueltig"

        gueltig = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, dateiname))
        assert gueltig.status_code == 200, gueltig.text


def test_basic_auth_und_transport_token_sind_getrennt(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    monkeypatch.setenv("ORAKEL_AUTH_USER", "orakel")
    monkeypatch.setenv("ORAKEL_AUTH_PASS", "geheim")
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1250])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        body = _als_mt5(reihe.iloc[-100:])
        antwort = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, _dateiname(reihe)))

    assert antwort.status_code == 200, antwort.text


def test_dateiname_symbol_zeitrahmen_und_hash_werden_abgewiesen(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1250])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)
    body = _als_mt5(reihe.iloc[-100:])
    gueltig = _dateiname(reihe)

    with client:
        pfad = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, "../../EURUSD_M15_20251126.csv"))
        assert pfad.status_code == 400
        assert pfad.json()["code"] == "dateiname_ungueltig"

        tf = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, f"{SYMBOL}_M5_20251126.csv"))
        assert tf.status_code == 400
        assert tf.json()["code"] == "zeitrahmen_nicht_erlaubt"

        symbol = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, "XAUUSD_M15_20251126.csv"))
        assert symbol.status_code == 400
        assert symbol.json()["code"] == "symbol_nicht_erlaubt"

        hash_falsch = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers={**_headers(body, gueltig),
                     "X-Orakel-Content-SHA256": "0" * 64})
        assert hash_falsch.status_code == 400
        assert hash_falsch.json()["code"] == "hash_mismatch"


def test_kaputte_csv_und_get_sind_klare_antworten(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1250])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)

    with client:
        kaputt = b"<DATE>\t<TIME>\t<OPEN>\n2025.01.01\t10:00\t1\n"
        antwort = client.post(
            transport.TRANSPORT_PFAD, content=kaputt,
            headers=_headers(kaputt, f"{SYMBOL}_{TF}_20250101.csv"))
        assert antwort.status_code == 400
        assert antwort.json()["code"] in {"eingabe", "datenqualitaet"}

        get = client.get(transport.TRANSPORT_PFAD)
        assert get.status_code == 405


def test_zu_grosser_upload_und_falscher_medientyp(cfg, monkeypatch):
    _transport_aktiv(monkeypatch)
    monkeypatch.setenv("ORAKEL_TRANSPORT_MAX_MB", "1")
    db = Facts(cfg.db_pfad)
    reihe = _frische_m15()
    db.kerzen_speichern_df(SYMBOL, TF, reihe.iloc[:1250])
    _bootstrap(db, cfg)
    client = _client(cfg, monkeypatch)
    body = b"x" * (1024 * 1024 + 1)
    dateiname = f"{SYMBOL}_{TF}_20251126.csv"

    with client:
        zu_gross = client.post(
            transport.TRANSPORT_PFAD, content=body,
            headers=_headers(body, dateiname))
        assert zu_gross.status_code == 413
        assert zu_gross.json()["code"] == "datei_zu_gross"

        falscher_typ = client.post(
            transport.TRANSPORT_PFAD, content=b"x",
            headers={**_headers(b"x", dateiname),
                     "Content-Type": "application/json"})
        assert falscher_typ.status_code == 415
        assert falscher_typ.json()["code"] == "medientyp_nicht_erlaubt"


def test_bootstrap_freigabe_lehnt_unvollstaendige_reihe_ab(cfg):
    db = Facts(cfg.db_pfad)
    db.kerzen_speichern_df(SYMBOL, TF, _frische_m15(kerzen=50))

    with pytest.raises(ValueError, match="Bootstrap abgelehnt"):
        transport.bootstrap_freigeben(db, cfg, SYMBOL, TF)

    assert transport.bootstrap_marker(db, SYMBOL, TF) is None


def test_cli_transport_bootstrap_setzt_den_marker(cfg, monkeypatch):
    from orakel import __main__ as cli

    db = Facts(cfg.db_pfad)
    db.kerzen_speichern_df(SYMBOL, TF, _frische_m15(kerzen=1250))
    monkeypatch.setattr(cli, "_cfg", lambda _pfad: cfg)
    monkeypatch.setattr(cli, "_schema_pruefen", lambda _cfg: None)
    monkeypatch.setattr(cli, "Facts", lambda _pfad: db)

    code = cli.cmd_transport_bootstrap(argparse.Namespace(
        config="unbenutzt.toml", symbol=[SYMBOL], zeitrahmen=TF, func=lambda _a: 0,
    ))

    assert code == 0
    marker = transport.bootstrap_marker(db, SYMBOL, TF)
    assert marker is not None
    assert marker["kerzen"] == 1250
    assert marker["quelle"] == "cli"


def test_cli_parser_kennt_transport_bootstrap(monkeypatch):
    from orakel import __main__ as cli

    gesehen: list[argparse.Namespace] = []
    monkeypatch.setattr(
        cli, "cmd_transport_bootstrap",
        lambda args: gesehen.append(args) or 0,
    )

    assert cli.main([
        "transport-bootstrap", "--symbol", "EURUSD", "US500",
        "--zeitrahmen", "M15",
    ]) == 0
    assert gesehen[0].symbol == ["EURUSD", "US500"]
    assert gesehen[0].zeitrahmen == "M15"
