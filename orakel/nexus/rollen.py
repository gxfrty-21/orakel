"""15 deterministische Nexus-Prüfrollen.

Die Rollen sind keine LLM-Persönlichkeiten. Jede prüft eine konkrete,
nachvollziehbare Eigenschaft der Mission und schreibt ihr Ergebnis in
``agenten_laeufe``. Eine Rolle ohne Befund ist ein gültiges Ergebnis.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from ..db import Facts

STATUS_ERLAUBT = {"bestätigt", "teilweise", "unbestätigt", "widersprüchlich"}
BEFUND = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _b(art: str, text: str, claim_id: int | None = None,
       schwere: str = "warnung") -> dict[str, Any]:
    return {"art": art, "text": text, "claim_id": claim_id, "schwere": schwere}


def _claims(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return ctx["pruefung"].get("claims") or []


def _zeit(text: object) -> datetime | None:
    try:
        wert = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    if wert.tzinfo is None:
        wert = wert.replace(tzinfo=timezone.utc)
    return wert


def _quellenlage(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    claims = _claims(ctx)
    if not claims:
        return [_b("datenluecke", "Keine passende Kernaussage für diese Mission.",
                   schwere="hoch")]
    return []


def _unabhaengigkeit(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _b("unabhaengigkeit",
           f"«{c['kernaussage']}» hat nur {int(c.get('hosts_unabhaengig') or 0)} "
           "unabhängigen Host.", int(c["id"]))
        for c in _claims(ctx) if int(c.get("hosts_unabhaengig") or 0) < 2
    ]


def _kopien(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        n = sum(1 for b in (c.get("belege_detail") or []) if b.get("ist_kopie"))
        if n:
            raus.append(_b("kopie", f"{n} Kopie(n) zu «{c['kernaussage']}».",
                           int(c["id"])))
    return raus


def _widerspruch(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _b("widerspruch",
           f"Widerspruch zu «{w['kernaussage']}»: {w['grund']} "
           f"({w['quelle_a']} ↔ {w['quelle_b']}).",
           int(w["claim_id"]), "hoch")
        for w in (ctx["pruefung"].get("widersprueche") or [])
    ]


def _zahlenkonflikt(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        werte = sorted({round(float(b["wert"]), 6) for b in (c.get("belege_detail") or [])
                        if b.get("wert") is not None})
        if len(werte) > 1:
            raus.append(_b("zahlenkonflikt",
                           f"Mehrere Werte zu «{c['kernaussage']}»: "
                           f"{', '.join(str(w) for w in werte)}.", int(c["id"]),
                           "hoch"))
    return raus


def _aktualitaet(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    jetzt = ctx["jetzt"]
    for c in _claims(ctx):
        zeit = _zeit(c.get("aktualisiert"))
        if zeit is None:
            raus.append(_b("aktualitaet",
                           f"Zeitstempel für «{c['kernaussage']}» fehlt oder ist ungültig.",
                           int(c["id"])))
        elif (jetzt - zeit).days > 30:
            raus.append(_b("aktualitaet",
                           f"«{c['kernaussage']}» ist älter als 30 Tage.",
                           int(c["id"])))
    return raus


def _reputation(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        reps = [float(b.get("reputation") or 0) for b in (c.get("belege_detail") or [])]
        if not reps:
            raus.append(_b("reputation", f"Keine Reputation zu «{c['kernaussage']}».",
                           int(c["id"])))
        elif sum(reps) / len(reps) < 0.6:
            raus.append(_b("reputation",
                           f"Durchschnittsreputation zu «{c['kernaussage']}» "
                           f"ist {sum(reps) / len(reps):.2f} (< 0,60).", int(c["id"])))
    return raus


def _abdeckung(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    lage = ctx["lage"]
    if lage.get("auswahl") == "keine":
        return [_b("abdeckung", "Suchbegriffe ohne Treffer im Claim-Bestand.",
                   schwere="hoch")]
    if lage.get("auswahl") == "breit":
        return [_b("abdeckung", "Keine unterscheidbaren Suchbegriffe; breite Auswahl.",
                   schwere="hinweis")]
    return []


def _gegenargument(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return list(ctx.get("gegenargumente") or [])


def _gegenbeleg(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _b("gegenbeleg", f"Prüfbedarf bei «{c['kernaussage']}».",
           int(c["id"]))
        for c in _claims(ctx) if c.get("pruefbedarf")
    ]


def _herkunft(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        if not c.get("hosts"):
            raus.append(_b("herkunft", f"Kein Host zu «{c['kernaussage']}».",
                           int(c["id"]), "hoch"))
        for b in (c.get("belege_detail") or []):
            if not b.get("host") or not b.get("quelle_id"):
                raus.append(_b("herkunft", f"Beleg ohne Host/Quelle zu "
                                           f"«{c['kernaussage']}».", int(c["id"])))
                break
    return raus


def _zeitfenster(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        erst = _zeit(c.get("erstmals"))
        akt = _zeit(c.get("aktualisiert"))
        if erst and akt and akt < erst:
            raus.append(_b("zeitfenster",
                           f"«{c['kernaussage']}» wurde vor ihrer ersten Sichtung aktualisiert.",
                           int(c["id"])))
    return raus


def _reputationsabgleich(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        if c.get("status") != "bestätigt":
            continue
        reps = [float(b.get("reputation") or 0) for b in (c.get("belege_detail") or [])]
        if reps and max(reps) < 0.5:
            raus.append(_b("reputation",
                           f"«{c['kernaussage']}» ist bestätigt, aber alle Belege "
                           "haben Reputation < 0,50.", int(c["id"]), "hoch"))
    return raus


def _datenintegritaet(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        if c.get("status") not in STATUS_ERLAUBT:
            raus.append(_b("datenintegritaet",
                           f"Unbekannter Status «{c.get('status')}» zu "
                           f"«{c['kernaussage']}».", int(c["id"]), "hoch"))
        grad = float(c.get("bestaetigungsgrad") or 0)
        if not 0 <= grad <= 1:
            raus.append(_b("datenintegritaet",
                           f"Bestätigungsgrad {grad} außerhalb 0–1.", int(c["id"]),
                           "hoch"))
    return raus


def _zahlenintegritaet(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    raus = []
    for c in _claims(ctx):
        for b in (c.get("belege_detail") or []):
            if b.get("wert") is not None and not b.get("einheit"):
                raus.append(_b("zahlenintegritaet",
                               f"Wert ohne Einheit zu «{c['kernaussage']}».",
                               int(c["id"])))
                break
    return raus


@dataclass(frozen=True, slots=True)
class Rolle:
    kennung: str
    name: str
    aufgabe: str
    pruefer: BEFUND


ROSTEN: tuple[Rolle, ...] = (
    Rolle("N1", "Quellenlage", "Anzahl und Status der Kernaussagen prüfen", _quellenlage),
    Rolle("N2", "Unabhängigkeit", "Unabhängige Hosts je Kernaussage zählen", _unabhaengigkeit),
    Rolle("N3", "Kopien", "Kopien als nicht unabhängige Belege markieren", _kopien),
    Rolle("N4", "Widerspruch", "Erkannte Widersprüche sammeln", _widerspruch),
    Rolle("N5", "Zahlenkonflikt", "Abweichende Werte zum selben Claim prüfen", _zahlenkonflikt),
    Rolle("N6", "Aktualität", "Alter und Zeitstempel der Claims prüfen", _aktualitaet),
    Rolle("N7", "Reputation", "Belegreputation und Vorläufigkeit prüfen", _reputation),
    Rolle("N8", "Abdeckung", "Suchbegriffe und Datenlücke prüfen", _abdeckung),
    Rolle("N9", "Gegenargument", "Alternativerklärungen aus Belegen ableiten", _gegenargument),
    Rolle("N10", "Gegenbeleg", "Prüfbedarf und fehlende Gegenbelege finden", _gegenbeleg),
    Rolle("N11", "Herkunft", "Host und Quelle jedes Belegs prüfen", _herkunft),
    Rolle("N12", "Zeitfenster", "Erst- und Aktualisierungszeit vergleichen", _zeitfenster),
    Rolle("N13", "Reputationsabgleich", "Bestätigung gegen Quellenreputation prüfen", _reputationsabgleich),
    Rolle("N14", "Datenintegrität", "Status und Bestätigungsgrad validieren", _datenintegritaet),
    Rolle("N15", "Zahlenintegrität", "Wert und Einheit der Belege prüfen", _zahlenintegritaet),
)


def lauf(db: Facts, mission: dict[str, Any], lage: dict[str, Any],
         pruefung: dict[str, Any], gegenargumente: list[dict[str, Any]],
         jetzt: datetime) -> dict[str, Any]:
    ctx = {"mission": mission, "lage": lage, "pruefung": pruefung,
           "gegenargumente": gegenargumente, "jetzt": jetzt}
    agenten: list[dict[str, Any]] = []
    befunde: list[dict[str, Any]] = []
    for rolle in ROSTEN:
        try:
            gefunden = rolle.pruefer(ctx)
            fehler = ""
        except Exception as exc:  # eine Rolle stoppt die andere nicht
            gefunden = [_b("rollenfehler", f"{role_name(rolle)}: {type(exc).__name__}",
                           schwere="hoch")]
            fehler = type(exc).__name__
        for befund in gefunden:
            befund["rolle"] = rolle.kennung
            befund["rolle_name"] = rolle.name
        befunde.extend(gefunden)
        text = (f"{len(gefunden)} Befund(e)" if gefunden else "geprüft, kein Befund")
        if fehler:
            text += f"; Fehler {fehler}"
        agenten.append({
            "kennung": rolle.kennung, "name": rolle.name,
            "aufgabe": rolle.aufgabe, "befunde": gefunden,
            "status": "fehler" if fehler else ("befund" if gefunden else "ok"),
            "ergebnis": text,
        })
        try:
            db.agenten_lauf(f"B:{rolle.kennung}:{rolle.name}", "B", rolle.aufgabe,
                            text[:240], not gefunden and not fehler)
        except Exception:
            pass
    return {"rollen": len(ROSTEN), "agenten": agenten, "befunde": befunde,
            "befundzahl": len(befunde)}


def role_name(rolle: Rolle) -> str:
    return f"{rolle.kennung} {rolle.name}"
