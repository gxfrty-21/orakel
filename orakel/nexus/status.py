"""Status des Nexus: was im Register steht und was der Cache weiß."""

from __future__ import annotations

from .abruf import HttpCache
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


def gesamt_status(cache: HttpCache, quellen: list[Quelle]) -> dict[str, object]:
    return {"ok": True, "register": register_status(quellen), "cache": cache_status(cache)}
