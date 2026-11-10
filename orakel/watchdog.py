"""Externer Takt-Watchdog für den Orakel-Dauerbetrieb.

Der Watchdog läuft außerhalb von Railway (GitHub Actions) und liest nur den
öffentlichen Health-Endpunkt. Er meldet einen Takt, der nicht mehr läuft oder
dessen letzter erfolgreicher Takt zu lange zurückliegt. Die Benachrichtigung
erfolgt über ein GitHub-Issue; der Workflow schließt es nach der Erholung
wieder.

Der Health-Endpunkt bleibt bewusst ohne Login erreichbar. Der Watchdog braucht
deshalb weder Railway-Token noch Dashboard-Zugangsdaten.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

STANDARD_URL = "https://orakel-production-fb18.up.railway.app/api/health"
STANDARD_MAX_ALTER_SEKUNDEN = 300.0


def _jetzt() -> datetime:
    return datetime.now(timezone.utc)


def _iso(wert: datetime) -> str:
    return wert.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _zeit(wert: object) -> datetime | None:
    if wert is None or str(wert).strip() == "":
        return None
    try:
        zeit = datetime.fromisoformat(str(wert).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if zeit.tzinfo is None:
        zeit = zeit.replace(tzinfo=timezone.utc)
    return zeit.astimezone(timezone.utc)


def bewerte(
    daten: dict[str, Any],
    jetzt_wert: datetime | None = None,
    max_alter_sekunden: float = STANDARD_MAX_ALTER_SEKUNDEN,
) -> dict[str, Any]:
    """Bewertet eine Health-Antwort ohne Netzwerkzugriff.

    ``ok`` ist nur dann wahr, wenn der Health-Endpunkt selbst ``ok: true``
    meldet, der Taktstatus ``laeuft`` ist und der letzte Takt nicht älter als
    ``max_alter_sekunden`` ist.
    """
    jetzt = jetzt_wert or _jetzt()
    max_alter = max(1.0, float(max_alter_sekunden))
    betrieb = daten.get("betrieb") if isinstance(daten.get("betrieb"), dict) else {}
    status = betrieb.get("status")
    letzter_text = betrieb.get("letzter_takt")
    letzter = _zeit(letzter_text)
    alter = (
        round((jetzt - letzter).total_seconds(), 1)
        if letzter is not None else None
    )

    ergebnis: dict[str, Any] = {
        "ok": False,
        "checked_at": _iso(jetzt),
        "health_ok": daten.get("ok") is True,
        "status": status,
        "letzter_takt": letzter_text,
        "takt_alter_sekunden": alter,
        "max_alter_sekunden": max_alter,
        "warnungen": betrieb.get("warnungen"),
        "hinweise": betrieb.get("hinweise"),
        "commit": daten.get("commit"),
        "reason": "",
        "detail": "",
    }

    if daten.get("ok") is not True:
        ergebnis["reason"] = "health_nicht_ok"
        ergebnis["detail"] = "Der Health-Endpunkt meldet nicht ok=true."
    elif status != "laeuft":
        ergebnis["reason"] = f"takt_status_{status or 'unbekannt'}"
        ergebnis["detail"] = (
            f"Der Taktstatus ist {status!r} statt 'laeuft'."
        )
    elif letzter is None:
        ergebnis["reason"] = "takt_fehlt"
        ergebnis["detail"] = "Der Health-Endpunkt nennt keinen gültigen letzten Takt."
    elif alter is not None and alter > max_alter:
        ergebnis["reason"] = "takt_zu_alt"
        ergebnis["detail"] = (
            f"Der letzte Takt ist {alter:.0f} s alt; das Limit liegt bei "
            f"{max_alter:.0f} s."
        )
    else:
        ergebnis["ok"] = True
        ergebnis["reason"] = "frisch"
        ergebnis["detail"] = (
            f"Der Takt läuft; der letzte Takt ist {alter:.0f} s alt "
            f"(Limit {max_alter:.0f} s)." if alter is not None else "Der Takt läuft."
        )
    return ergebnis


def _abruf_fehler(jetzt: datetime, reason: str, detail: str,
                  url: str) -> dict[str, Any]:
    return {
        "ok": False,
        "checked_at": _iso(jetzt),
        "health_url": url,
        "health_ok": False,
        "status": None,
        "letzter_takt": None,
        "takt_alter_sekunden": None,
        "max_alter_sekunden": None,
        "warnungen": None,
        "hinweise": None,
        "commit": None,
        "reason": reason,
        "detail": detail,
    }


def pruefe(
    url: str = STANDARD_URL,
    max_alter_sekunden: float = STANDARD_MAX_ALTER_SEKUNDEN,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Holt den Health-Endpunkt und bewertet ihn."""
    jetzt = _jetzt()
    anfrage = urllib.request.Request(
        url, headers={"User-Agent": "orakel-takt-watchdog/1"}
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
            rohtext = antwort.read().decode("utf-8")
        daten = json.loads(rohtext)
        if not isinstance(daten, dict):
            raise ValueError("Health-Antwort ist kein JSON-Objekt")
    except urllib.error.HTTPError as exc:
        return _abruf_fehler(
            jetzt, f"http_{exc.code}",
            f"Der Health-Endpunkt antwortet mit HTTP {exc.code}.", url,
        )
    except Exception as exc:
        return _abruf_fehler(
            jetzt, "abruf_fehlgeschlagen",
            f"{type(exc).__name__}: {exc}", url,
        )
    ergebnis = bewerte(daten, jetzt, max_alter_sekunden)
    ergebnis["health_url"] = url
    return ergebnis


def _env_float(name: str, standard: float) -> float:
    try:
        return float(os.environ.get(name, standard))
    except (TypeError, ValueError):
        return standard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("ORAKEL_HEALTH_URL", STANDARD_URL),
        help="Health-Endpunkt (Standard: ORAKEL_HEALTH_URL oder Produktion)",
    )
    parser.add_argument(
        "--max-age-seconds",
        type=float,
        default=_env_float("ORAKEL_WATCHDOG_MAX_AGE_SECONDS",
                           STANDARD_MAX_ALTER_SEKUNDEN),
        help="Maximales Alter des letzten Takts in Sekunden (Standard: 300)",
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0,
        help="HTTP-Timeout in Sekunden (Standard: 20)",
    )
    parser.add_argument("--json", action="store_true", help="JSON ausgeben")
    args = parser.parse_args(argv)
    if args.max_age_seconds <= 0:
        parser.error("--max-age-seconds muss positiv sein")
    if args.timeout <= 0:
        parser.error("--timeout muss positiv sein")

    ergebnis = pruefe(args.url, args.max_age_seconds, args.timeout)
    if args.json:
        print(json.dumps(ergebnis, ensure_ascii=False, indent=2))
    elif ergebnis["ok"]:
        print(f"OK: {ergebnis['detail']}")
    else:
        print(f"WATCHDOG-FEHLER: {ergebnis['reason']}: {ergebnis['detail']}")
    return 0 if ergebnis["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
