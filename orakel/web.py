from __future__ import annotations

import base64
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import agents
from .config import load_config
from .db import Facts
from .globe import STANDARD_ZEITRAUM, baue_globe
from .intel import IntelNetz, auftrag_aendern, weiterleitung_aendern
from .knowledge import Vault
from .paper import tick
from .pipeline import lauf as engine_lauf
from .report import baue_bericht
from .scheduler import Takt, _kontext
from .spider import Spider

STATIC = Path(__file__).parent / "web" / "static"
BERICHT = Path("dashboard.json")
_sperre = threading.Lock()


def _basic_ok(kopf: str, benutzer: str, passwort: str) -> bool:
    """Prüft HTTP-Basic in konstanter Zeit. Leere Zugangsdaten sind nie gültig."""
    if not benutzer or not passwort or not kopf or not kopf.lower().startswith("basic "):
        return False
    try:
        roh = base64.b64decode(kopf.split(" ", 1)[1], validate=True).decode("utf-8")
    except Exception:
        return False
    name, trenner, pw = roh.partition(":")
    if not trenner:
        return False
    # Bytes statt str: compare_digest unterstützt keine Nicht-ASCII-Strings.
    return (secrets.compare_digest(name.encode("utf-8"), benutzer.encode("utf-8"))
            and secrets.compare_digest(pw.encode("utf-8"), passwort.encode("utf-8")))


def _bericht(cfg_pfad: str) -> dict[str, Any]:
    """Baut den Bericht live aus der Fakten-Datenbank (Dashboard ist nur ein Spiegel)."""
    cfg = load_config(cfg_pfad)
    db = Facts(cfg.db_pfad)
    basis = db.zustand("bericht_basis") or {}
    bericht = baue_bericht(
        cfg, db,
        modus=basis.get("modus", "backtest"),
        datenquelle=basis.get("datenquelle", "kein Lauf"),
        qualitaet=basis.get("qualitaet") or [],
        plan=basis.get("plan") or [],
        fehler=basis.get("fehler") or [],
    )
    bericht["agenten"] = basis.get("agenten") or []
    bericht["markt"] = basis.get("markt") or {"symbole": [], "korrelation": []}
    konferenz = db.letzte_konferenz()
    bericht["konferenz"] = konferenz["protokoll"] if konferenz else basis.get("konferenz")
    spider = dict(db.zustand("spider_letzter_lauf") or {})
    spider.setdefault("artikel", [])
    if not spider["artikel"]:
        import json as _json

        zeilen = []
        for r in db.artikel(12):
            eintrag = dict(r)
            try:
                eintrag["symbole"] = ", ".join(_json.loads(eintrag.get("symbole") or "[]"))
            except Exception:
                eintrag["symbole"] = ""
            zeilen.append(eintrag)
        spider["artikel"] = zeilen
    spider["statistik"] = db.artikel_statistik()
    bericht["spider"] = spider
    bericht["paper"] = {
        "letzter_tick": db.zustand("paper_letzter_tick"),
        "positionen": [dict(p) for p in db.positionen()],
        "konto": db.zustand("paper_konto"),
    }
    return bericht


def create_app(cfg_pfad: str = "config.toml", takt: bool = False) -> FastAPI:
    app = FastAPI(title="Orakel Trading-Engine", version="0.2.0")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    auth_benutzer = os.environ.get("ORAKEL_AUTH_USER", "").strip()
    auth_passwort = os.environ.get("ORAKEL_AUTH_PASS", "")
    if bool(auth_benutzer) != bool(auth_passwort):
        raise RuntimeError("ORAKEL_AUTH_USER und ORAKEL_AUTH_PASS müssen gemeinsam gesetzt sein.")

    if auth_benutzer:
        @app.middleware("http")
        async def _auth(request: Request, call_next):
            # Health bleibt offen, damit Container- und Uptime-Prüfungen ohne Login funktionieren.
            if request.url.path == "/api/health":
                return await call_next(request)
            if not _basic_ok(request.headers.get("authorization", ""),
                             auth_benutzer, auth_passwort):
                return JSONResponse(
                    {"ok": False, "fehler": "Anmeldung erforderlich"},
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Orakel", charset="UTF-8"'},
                )
            return await call_next(request)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/report")
    def report() -> JSONResponse:
        return JSONResponse(_bericht(cfg_pfad), headers={"Cache-Control": "no-store"})

    @app.get("/api/globe")
    def globe(zeitraum: str = STANDARD_ZEITRAUM) -> JSONResponse:
        cfg = load_config(cfg_pfad)
        return JSONResponse(baue_globe(cfg, Facts(cfg.db_pfad), zeitraum=zeitraum),
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        cfg = load_config(cfg_pfad)
        db = Facts(cfg.db_pfad)
        return {"ok": True, "letzter_lauf": db.zustand("letzter_lauf"),
                "halt": db.zustand("risiko_stopp"),
                "paper_tick": db.zustand("paper_letzter_tick"),
                "artikel": db.artikel_statistik()["gesamt"]}

    @app.post("/api/lauf")
    def starte_lauf(modus: str = "backtest", spider: bool = False) -> JSONResponse:
        if not _sperre.acquire(blocking=False):
            return JSONResponse({"ok": False, "fehler": "Ein Lauf ist bereits aktiv"}, status_code=409)
        try:
            ergebnis = engine_lauf(cfg_pfad=cfg_pfad, modus=modus, mit_spider=spider)
        finally:
            _sperre.release()
        return JSONResponse({"ok": True, "dauer": ergebnis.get("dauer_sekunden"),
                             "validierungen": len(ergebnis.get("validierungen", [])),
                             "plan": len(ergebnis.get("plan", []))})

    @app.post("/api/paper")
    def paper_tick() -> JSONResponse:
        cfg = load_config(cfg_pfad)
        db = Facts(cfg.db_pfad)
        try:
            ergebnis = tick(cfg, db)
        except Exception as exc:
            db.ereignis("fehler", "Takt", f"Paper-Takt über API fehlgeschlagen: {exc}")
            return JSONResponse({"ok": False, "fehler": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, **ergebnis})

    @app.post("/api/spider")
    def spider_lauf() -> JSONResponse:
        cfg = load_config(cfg_pfad)
        db = Facts(cfg.db_pfad)
        try:
            ergebnis = Spider(cfg, db, Vault(cfg.vault_ordner)).lauf()
        except Exception as exc:
            db.ereignis("fehler", "Spider", f"Recherche über API fehlgeschlagen: {exc}")
            return JSONResponse({"ok": False, "fehler": str(exc)}, status_code=500)
        db.zustand_setzen("spider_letzter_lauf", ergebnis)
        try:
            netz = IntelNetz(cfg, db, Vault(cfg.vault_ordner))
            ergebnis["intel"] = {**netz.verarbeite(ergebnis.get("neue_ids") or []),
                                 **netz.lernschleife()}
        except Exception as exc:
            db.ereignis("fehler", "Intel", f"Intelligence über API fehlgeschlagen: {exc}")
        return JSONResponse({"ok": True, **ergebnis})

    @app.post("/api/intel/auftrag")
    async def intel_auftrag(request: Request) -> JSONResponse:
        cfg = load_config(cfg_pfad)
        db = Facts(cfg.db_pfad)
        try:
            daten = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "fehler": "Ungültiger JSON-Body"}, status_code=400)
        if not isinstance(daten, dict):
            return JSONResponse({"ok": False, "fehler": "Ungültiger JSON-Body"}, status_code=400)
        kennung = str(daten.get("kennung") or "").strip()
        status = str(daten.get("status") or "").strip()
        ergebnis = str(daten.get("ergebnis") or "")
        try:
            geaendert = auftrag_aendern(db, kennung, status, ergebnis)
        except ValueError as exc:
            return JSONResponse({"ok": False, "fehler": str(exc)}, status_code=400)
        if not geaendert:
            return JSONResponse({"ok": False, "fehler": f"Unbekannter Auftrag: {kennung}"},
                                status_code=404)
        db.ereignis("intel", "Forschungsauftrag", f"{kennung} · {status}: {ergebnis[:120]}")
        return JSONResponse({"ok": True, "kennung": kennung, "status": status})

    @app.post("/api/intel/weiterleitung")
    def intel_weiterleitung(kennung: str, abteilung: str, status: str) -> JSONResponse:
        cfg = load_config(cfg_pfad)
        db = Facts(cfg.db_pfad)
        try:
            geaendert = weiterleitung_aendern(db, kennung, abteilung, status)
        except ValueError as exc:
            return JSONResponse({"ok": False, "fehler": str(exc)}, status_code=400)
        if not geaendert:
            return JSONResponse({"ok": False, "fehler": f"Unbekannte Weiterleitung: {kennung}"},
                                status_code=404)
        db.ereignis("intel", "Weiterleitung", f"{kennung} → {abteilung} · {status}")
        return JSONResponse({"ok": True, "kennung": kennung,
                             "abteilung": abteilung, "status": status})

    @app.post("/api/konferenz")
    def konferenz() -> JSONResponse:
        cfg = load_config(cfg_pfad)
        db = Facts(cfg.db_pfad)
        try:
            protokoll = agents.konferenz(db, _kontext(cfg, db), erzwungen=True)
        except Exception as exc:
            return JSONResponse({"ok": False, "fehler": str(exc)}, status_code=500)
        return JSONResponse({"ok": True, "beschluss": protokoll.get("beschluss")})

    if takt:
        @app.on_event("startup")
        def _starte_takt() -> None:  # pragma: no cover - Zeitverhalten
            cfg = load_config(cfg_pfad)
            Takt(cfg, Facts(cfg.db_pfad)).start()

    return app


app = create_app()
