"""Tests für die Lauf-Warteschlange (Bereich 4.4)."""
from __future__ import annotations

import time
from datetime import timedelta

from fastapi.testclient import TestClient

from orakel import lauf_queue, scheduler, web
from orakel.kern.db import Facts, jetzt


def test_post_lauf_antwortet_unter_200_ms(cfg, monkeypatch):
    """Der Endpunkt legt nur an; er wartet nicht auf die Engine."""
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    app = web.create_app("unbenutzt.toml", hintergrund=False)

    with TestClient(app) as client:
        beginn = time.perf_counter()
        antwort = client.post("/api/lauf?modus=backtest")
        dauer = time.perf_counter() - beginn

    assert antwort.status_code == 202
    assert dauer < 0.2, f"POST /api/lauf brauchte {dauer * 1000:.0f} ms"
    daten = antwort.json()
    assert daten["ok"] is True
    assert daten["status"] == "offen"
    assert daten["id"] > 0


def test_get_lauf_liefert_status_und_404(cfg, monkeypatch):
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    app = web.create_app("unbenutzt.toml", hintergrund=False)

    with TestClient(app) as client:
        lauf_id = client.post("/api/lauf?modus=backtest").json()["id"]
        antwort = client.get(f"/api/lauf/{lauf_id}")
        fehlt = client.get("/api/lauf/999999")

    assert antwort.status_code == 200
    assert antwort.json()["status"] == "offen"
    assert antwort.headers["cache-control"] == "no-store"
    assert fehlt.status_code == 404


def test_arbeiter_verarbeitet_auftrag_und_schreibt_ergebnis(cfg):
    db = Facts(cfg.db_pfad)
    aufrufe: list[dict] = []

    def engine(**kwargs):
        aufrufe.append(kwargs)
        return {"dauer_sekunden": 0.01, "validierungen": [{}], "plan": [{}, {}],
                "fehler": []}

    lauf_id = lauf_queue.anlegen(db, modus="backtest", spider=True)
    verarbeitet = lauf_queue.verarbeite_einen(db, "unbenutzt.toml", engine=engine)

    assert verarbeitet == lauf_id
    assert aufrufe == [{"cfg_pfad": "unbenutzt.toml", "modus": "backtest",
                        "mit_spider": True}]
    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FERTIG
    assert stand["ergebnis"] == {"dauer": 0.01, "validierungen": 1, "plan": 2,
                                 "fehler": 0}
    assert stand["gestartet"] and stand["beendet"]
    assert lauf_queue.anlegen_wenn_frei(db)[1] is None


def test_fehlerhafter_auftrag_wird_als_fehler_verbucht(cfg):
    db = Facts(cfg.db_pfad)

    def kaputt(**_kwargs):
        raise RuntimeError("Backtest abgebrochen")

    lauf_id = lauf_queue.anlegen(db)

    verarbeitet = lauf_queue.verarbeite_einen(db, "unbenutzt.toml", engine=kaputt)

    assert verarbeitet == lauf_id
    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FEHLER
    assert "Backtest abgebrochen" in stand["fehler"]
    assert lauf_queue.anlegen_wenn_frei(db)[1] is None
    assert any("Auftrag" in zeile["text"] for zeile in db.ereignisse())


def test_ohne_auftrag_passiert_nichts(cfg):
    db = Facts(cfg.db_pfad)

    assert lauf_queue.verarbeite_einen(db, "unbenutzt.toml",
                                       engine=lambda **_k: {}) is None


def test_zweiter_start_liefert_409_mit_bestehender_id(cfg, monkeypatch):
    """Doppelklick reiht keinen zweiten Backtest ein, sondern nennt den ersten."""
    monkeypatch.setattr(web, "load_config", lambda _pfad: cfg)
    app = web.create_app("unbenutzt.toml", hintergrund=False)

    with TestClient(app) as client:
        erster = client.post("/api/lauf?modus=backtest")
        zweiter = client.post("/api/lauf?modus=backtest")
        dritter = client.post("/api/lauf?modus=paper")

    assert erster.status_code == 202
    lauf_id = erster.json()["id"]
    assert zweiter.status_code == 409
    assert zweiter.json()["ok"] is False
    assert zweiter.json()["id"] == lauf_id
    assert zweiter.json()["status"] == "offen"
    assert "bereits" in zweiter.json()["fehler"]
    assert dritter.status_code == 409
    assert dritter.json()["id"] == lauf_id
    assert lauf_queue.anlegen_wenn_frei(Facts(cfg.db_pfad)) == (lauf_id, lauf_queue.OFFEN)


def test_waehrend_der_arbeit_entsteht_kein_zweiter_auftrag(cfg):
    """Auch ein aktiver Auftrag blockiert; die Arbeit sieht ihn als aktiv."""
    db = Facts(cfg.db_pfad)
    lauf_id, blockiert = lauf_queue.anlegen_wenn_frei(db)
    assert blockiert is None
    waehrend: list[tuple[int, str | None]] = []

    def engine(**_kwargs):
        waehrend.append(lauf_queue.anlegen_wenn_frei(db, modus="paper"))
        return {"dauer_sekunden": 0.01}

    lauf_queue.verarbeite_einen(db, "unbenutzt.toml", engine=engine)

    assert waehrend == [(lauf_id, lauf_queue.AKTIV)]
    assert lauf_queue.stand(db, lauf_id)["status"] == lauf_queue.FERTIG


def test_nach_abschluss_startet_wieder_ein_auftrag(cfg):
    db = Facts(cfg.db_pfad)
    erster, blockiert = lauf_queue.anlegen_wenn_frei(db)
    assert blockiert is None
    lauf_queue.abschliessen(db, erster, {"dauer_sekunden": 0.01})

    zweiter, wieder_blockiert = lauf_queue.anlegen_wenn_frei(db)

    assert wieder_blockiert is None
    assert zweiter != erster
    assert lauf_queue.stand(db, erster)["status"] == lauf_queue.FERTIG
    assert lauf_queue.stand(db, zweiter)["status"] == lauf_queue.OFFEN


def _aktiviere(db: Facts, lauf_id: int, gestartet: str) -> None:
    """Setzt einen Auftrag direkt auf aktiv, wie es ein Absturz hinterlässt."""
    with db.conn() as c:
        c.execute("UPDATE laeufe SET status = ?, gestartet = ? WHERE id = ?",
                  (lauf_queue.AKTIV, gestartet, lauf_id))


def test_takt_reiht_beim_start_aktive_auftraege_wieder_ein(cfg, monkeypatch):
    """Ein Absturzrest wird beim Start des Hintergrund-Loops wieder «offen»."""
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)
    _aktiviere(db, lauf_id, "2020-01-01T00:00:00")
    runden: list[int] = []

    def stub(db, cfg_pfad="unbenutzt.toml", engine=None):
        runden.append(1)
        return None

    monkeypatch.setattr(scheduler, "verarbeite_einen", stub)
    loop = scheduler.Takt(cfg, db, cfg_pfad="unbenutzt.toml", takt_aktiv=False)
    loop.start()
    grenze = time.monotonic() + 5
    try:
        while time.monotonic() < grenze:
            if runden:
                break
            time.sleep(0.05)
    finally:
        loop.stoppe()
        loop.join(timeout=2)

    stand = lauf_queue.stand(db, lauf_id)
    assert runden                         # die Schleife lief nach dem Reset
    assert stand["status"] == lauf_queue.OFFEN
    assert stand["gestartet"] is None
    assert stand["beendet"] is None
    assert any("wieder offen" in zeile["text"] for zeile in db.ereignisse())
    assert lauf_queue.anlegen_wenn_frei(db) == (lauf_id, lauf_queue.OFFEN)


def test_warteschlange_laeuft_wenn_der_takt_aktiv_ist(cfg, monkeypatch):
    """Takt und Warteschlange teilen sich den Loop; ein Auftrag wird trotzdem fertig."""
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)
    takt_schritte: list[bool] = []

    def takt_stub(self, erzwungen=None):
        takt_schritte.append(True)
        return {}

    echt = lauf_queue.verarbeite_einen

    def mit_engine(db, cfg_pfad="unbenutzt.toml", engine=None):
        return echt(db, cfg_pfad, engine=lambda **_k: {"dauer_sekunden": 0.01})

    monkeypatch.setattr(scheduler.Betrieb, "takt", takt_stub)
    monkeypatch.setattr(scheduler, "verarbeite_einen", mit_engine)
    loop = scheduler.Takt(cfg, db, cfg_pfad="unbenutzt.toml", takt_aktiv=True)
    loop.start()
    grenze = time.monotonic() + 5
    try:
        while time.monotonic() < grenze:
            if lauf_queue.stand(db, lauf_id)["status"] == lauf_queue.FERTIG:
                break
            time.sleep(0.05)
    finally:
        loop.stoppe()
        loop.join(timeout=2)

    assert takt_schritte                  # der Betriebstakt lief im selben Loop
    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FERTIG
    assert stand["ergebnis"] == {"dauer": 0.01, "validierungen": 0, "plan": 0, "fehler": 0}


def test_reset_laesst_andere_zustaende_unberuehrt(cfg):
    db = Facts(cfg.db_pfad)
    aktiv_id = lauf_queue.anlegen(db)
    _aktiviere(db, aktiv_id, jetzt())
    fertig_id = lauf_queue.anlegen(db)
    lauf_queue.abschliessen(db, fertig_id, {"dauer": 0.1})
    fehler_id = lauf_queue.anlegen(db)
    lauf_queue.scheitern(db, fehler_id, "Testfehler")

    assert lauf_queue.zuruecksetzen(db) == [aktiv_id]
    assert lauf_queue.stand(db, aktiv_id)["status"] == lauf_queue.OFFEN
    assert lauf_queue.stand(db, aktiv_id)["gestartet"] is None
    assert lauf_queue.stand(db, fertig_id)["status"] == lauf_queue.FERTIG
    assert lauf_queue.stand(db, fehler_id)["status"] == lauf_queue.FEHLER
    assert lauf_queue.zuruecksetzen(db) == []


def test_frischer_aktiver_auftrag_bleibt_stehen(cfg):
    """Innerhalb der Grenze wird nichts angefasst: Der Lauf könnte echt sein."""
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)
    _aktiviere(db, lauf_id, jetzt())

    assert lauf_queue.verwerfe_haengende(db) == []
    assert lauf_queue.stand(db, lauf_id)["status"] == lauf_queue.AKTIV
    assert lauf_queue.anlegen_wenn_frei(db) == (lauf_id, lauf_queue.AKTIV)


def test_grenze_entscheidet_ueber_verwerfen(cfg):
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)
    _aktiviere(db, lauf_id, "2020-01-01T00:00:00")

    assert lauf_queue.verwerfe_haengende(db, grenze=timedelta(days=3650)) == []
    assert lauf_queue.stand(db, lauf_id)["status"] == lauf_queue.AKTIV

    assert lauf_queue.verwerfe_haengende(db, grenze=timedelta(minutes=30)) == [lauf_id]
    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FEHLER
    assert "30 Minuten" in stand["fehler"]


def test_verarbeite_einen_zaehlt_den_versuch(cfg):
    """Jeder Startversuch wird gezählt; die Grenze hängt daran."""
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)

    lauf_queue.verarbeite_einen(db, "unbenutzt.toml", engine=lambda **_k: {})

    assert lauf_queue.stand(db, lauf_id)["versuche"] == 1


def test_nach_max_versuchen_wird_der_auftrag_verworfen(cfg):
    """Ein Lauf, der den Prozess wiederholt mitnimmt, blockiert nicht ewig."""
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)
    with db.conn() as c:
        c.execute(
            "UPDATE laeufe SET status = ?, gestartet = ?, versuche = ? WHERE id = ?",
            (lauf_queue.AKTIV, "2020-01-01T00:00:00", lauf_queue.MAX_VERSUCHE, lauf_id),
        )

    assert lauf_queue.zuruecksetzen(db) == []       # nicht wieder eingereiht

    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.FEHLER
    assert stand["beendet"] is not None
    assert f"{lauf_queue.MAX_VERSUCHE} Versuchen" in stand["fehler"]
    assert any("Versuchen als Fehler" in zeile["text"] for zeile in db.ereignisse())


def test_ein_versuch_weniger_wird_noch_eingereiht(cfg):
    """Unterhalb der Grenze bleibt der Auftrag offen für einen neuen Versuch."""
    db = Facts(cfg.db_pfad)
    lauf_id = lauf_queue.anlegen(db)
    with db.conn() as c:
        c.execute(
            "UPDATE laeufe SET status = ?, gestartet = ?, versuche = ? WHERE id = ?",
            (lauf_queue.AKTIV, "2020-01-01T00:00:00", lauf_queue.MAX_VERSUCHE - 1, lauf_id),
        )

    assert lauf_queue.zuruecksetzen(db) == [lauf_id]

    stand = lauf_queue.stand(db, lauf_id)
    assert stand["status"] == lauf_queue.OFFEN
    assert stand["gestartet"] is None


def test_aufbewahrung_loescht_nur_alte_abgeschlossene(cfg):
    """Nach der Frist verschwinden fertige und fehlerhafte Aufträge, mehr nicht."""
    db = Facts(cfg.db_pfad)
    vor_frist = "2020-01-01T00:00:00+01:00"
    alt_fertig = lauf_queue.anlegen(db)
    alt_fehler = lauf_queue.anlegen(db)
    neu_fertig = lauf_queue.anlegen(db)
    offen = lauf_queue.anlegen(db)
    aktiv = lauf_queue.anlegen(db)
    with db.conn() as c:
        c.execute("UPDATE laeufe SET status = ?, beendet = ? WHERE id = ?",
                  (lauf_queue.FERTIG, vor_frist, alt_fertig))
        c.execute("UPDATE laeufe SET status = ?, beendet = ? WHERE id = ?",
                  (lauf_queue.FEHLER, vor_frist, alt_fehler))
        c.execute("UPDATE laeufe SET status = ?, beendet = ? WHERE id = ?",
                  (lauf_queue.FERTIG, jetzt(), neu_fertig))
        c.execute("UPDATE laeufe SET status = ?, gestartet = ? WHERE id = ?",
                  (lauf_queue.AKTIV, jetzt(), aktiv))

    assert lauf_queue.raeume_auf(db) == [alt_fertig, alt_fehler]

    assert lauf_queue.stand(db, alt_fertig) is None
    assert lauf_queue.stand(db, alt_fehler) is None
    assert lauf_queue.stand(db, neu_fertig)["status"] == lauf_queue.FERTIG
    assert lauf_queue.stand(db, offen)["status"] == lauf_queue.OFFEN
    assert lauf_queue.stand(db, aktiv)["status"] == lauf_queue.AKTIV
    assert any("Aufbewahrung" in zeile["text"] for zeile in db.ereignisse())


def test_takt_raeumt_in_der_ersten_runde_auf(cfg, monkeypatch):
    """Der eine Hintergrund-Loop ruft die Aufbewahrung ohne eigenen Takt auf."""
    db = Facts(cfg.db_pfad)
    aufgerufen: list[int] = []

    def merken(db, **_k):
        aufgerufen.append(1)
        return []

    monkeypatch.setattr(scheduler, "raeume_auf", merken)
    monkeypatch.setattr(scheduler, "verarbeite_einen",
                        lambda db, cfg_pfad="unbenutzt.toml", engine=None: None)
    loop = scheduler.Takt(cfg, db, cfg_pfad="unbenutzt.toml", takt_aktiv=False)
    loop.start()
    grenze = time.monotonic() + 5
    try:
        while time.monotonic() < grenze:
            if aufgerufen:
                break
            time.sleep(0.05)
    finally:
        loop.stoppe()
        loop.join(timeout=2)

    assert aufgerufen                       # erste Runde räumt auf
