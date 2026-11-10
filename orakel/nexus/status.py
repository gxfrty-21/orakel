"""Status des Nexus: was im Register steht und was der Cache weiß."""

from __future__ import annotations

from ..db import Facts
from .abruf import HttpCache
from .graph import graph_daten
from .kalibrierung import kalibrierung_statistik
from .quellen import Quelle, statistik


def register_status(quellen: list[Quelle]) -> dict[str, object]:
    daten = statistik(quellen)
    daten["sprachen"] = sorted({q.sprache for q in quellen})
    daten["laender"] = sorted({q.land for q in quellen})
    return daten


def cache_status(cache: HttpCache) -> dict[str, object]:
    daten = cache.statistik()
    bytes_gesamt = int(daten.get("bytes") or 0)
    daten["megabyte"] = round(bytes_gesamt / 1_048_576, 2)
    return daten


def gesamt_status(cache: HttpCache, quellen: list[Quelle],
                  db: Facts | None = None) -> dict[str, object]:
    daten: dict[str, object] = {
        "ok": True,
        "register": register_status(quellen),
        "cache": cache_status(cache),
    }
    if db is not None:
        daten["meldungen"] = db.nexus_statistik()
        daten["claims"] = {
            "statistik": db.nexus_claim_statistik(),
            "top": db.nexus_claims(12),
            "widersprueche": db.nexus_widersprueche(8),
        }
        daten["reputation"] = db.nexus_quellen_reputation()[:12]
        daten["missionen"] = {
            "statistik": db.nexus_mission_statistik(),
            "liste": db.nexus_missionen(20),
        }
        daten["graph"] = graph_daten(db, "7d")["statistik"]
        kalibrierung = kalibrierung_statistik(db)
        daten["kalibrierung"] = {
            **kalibrierung,
            "letzte": kalibrierung.get("letzte", [])[:5],
        }
    return daten
