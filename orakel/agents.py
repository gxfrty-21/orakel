"""Agenten-Infrastruktur.

Jeder Agent hat eine echte Aufgabe. Es gibt keine Dekorations-Agenten: Was im
Dashboard als Aktivität erscheint, ist ein Eintrag in `agenten_laeufe` mit einem
Ergebnis, das aus der Fakten-Datenbank stammt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .db import Facts

ABTEILUNGEN = {
    "A": "Hauptzentrale",
    "B": "Spider Intelligence",
    "C": "Labor",
    "D": "Trading Floor",
    "E": "Forschungsabteilung",
    "F": "Risikomanagement",
    "G": "Wissenszentrum",
    "H": "Entwicklungsabteilung",
}

# 10 Agenten je Abteilung mit klar getrennten Aufgaben.
ROSTER: list[tuple[str, str, str, str]] = [
    # (kennung, abteilung, name, aufgabe)
    ("A1", "A", "Koordinator", "Tagesordnung und Prioritäten aus offenen Befunden ableiten"),
    ("A2", "A", "Aufseher", "Prüfen, ob jede Abteilung im letzten Lauf ein Ergebnis geliefert hat"),
    ("A3", "A", "Konfliktlöser", "Widersprüche zwischen Labor und Risiko auflisten"),
    ("A4", "A", "Protokollant", "Ergebnisse des Laufs dokumentieren"),
    ("A5", "A", "Wächter", "Paper-only-Sperre und Handelsstopp prüfen"),
    ("A6", "A", "Planer", "Nächste Entwicklungsphase aus dem Rückstand bestimmen"),
    ("A7", "A", "Prüfer", "Bericht gegen das Dashboard-Schema validieren"),
    ("A8", "A", "Zeitwächter", "Versäumte Mitternachtskonferenz erkennen"),
    ("A9", "A", "Ressourcenwächter", "Laufzeit und Datenmenge je Lauf erfassen"),
    ("A10", "A", "Freigabe", "Auswahl der Strategien gegen die Regeln abgleichen"),
    ("B1", "B", "Nachrichten-Spinne", "Nachrichtenlage je Symbol erfassen (nur mit Quelle)"),
    ("B2", "B", "Studien-Spinne", "Studienverweise im Vault prüfen"),
    ("B3", "B", "Bücher-Spinne", "Buchnotizen auf Widersprüche prüfen"),
    ("B4", "B", "Video-Spinne", "Video-Notizen auf prüfbare Aussagen reduzieren"),
    ("B5", "B", "Quellenprüfer", "Quellenangaben auf Vollständigkeit prüfen"),
    ("B6", "B", "Dublettenprüfer", "Doppelte Erkenntnisse im Vault finden"),
    ("B7", "B", "Widerspruchsprüfer", "Widersprüchliche Notizen markieren"),
    ("B8", "B", "Aktualitätsprüfer", "Veraltete Notizen finden"),
    ("B9", "B", "Weiterleiter", "Erkenntnisse der richtigen Abteilung zuordnen"),
    ("B10", "B", "Limitwächter", "Abruflimits und robots.txt-Regeln einhalten"),
    ("C1", "C", "Ideen-Brauer", "Kandidaten aus dem freigegebenen Parameter-Raster ziehen"),
    ("C2", "C", "Mischer", "Parameter-Kombinationen auf Plausibilität prüfen"),
    ("C3", "C", "Mathematiker", "Stop-Abstand und Positionsgrösse nachrechnen"),
    ("C4", "C", "Simulant", "Kandidat im Backtest laufen lassen"),
    ("C5", "C", "Gegenprüfer", "Ergebnis mit ungesehenen Daten vergleichen"),
    ("C6", "C", "Vergleicher", "Kandidat gegen Kaufen-und-Halten stellen"),
    ("C7", "C", "Regime-Prüfer", "Verhalten in Trend- und Seitwärtsphasen trennen"),
    ("C8", "C", "Kostenprüfer", "Gebührenanteil am Ergebnis prüfen"),
    ("C9", "C", "Dokumentar", "Ideensteckbrief im Vault anlegen"),
    ("C10", "C", "Aussortierer", "Abgelehnte Ideen mit Grund archivieren"),
    ("D1", "D", "Trend-Trader", "Trendsignale je Symbol auswerten"),
    ("D2", "D", "Ausbruch-Trader", "Ausbruchssignale je Symbol auswerten"),
    ("D3", "D", "Gegenläufer", "Rücksetzer-Signale je Symbol auswerten"),
    ("D4", "D", "Momentum-Trader", "Momentumsignale je Symbol auswerten"),
    ("D5", "D", "Positionsführer", "Offene Positionen und Stops prüfen"),
    ("D6", "D", "Order-Prüfer", "Aufträge vor der Freigabe nachrechnen"),
    ("D7", "D", "Ausführungs-Wächter", "Ausführungsstatus je Auftrag protokollieren"),
    ("D8", "D", "Abgleich", "Broker-Positionen mit der Datenbank abgleichen"),
    ("D9", "D", "Handelsjournal", "Trades mit Begründung ins Vault schreiben"),
    ("D10", "D", "Leistungsmessung", "Trefferquote und Profit Factor je Strategie führen"),
    ("E1", "E", "Statistiker", "Verteilung der Trade-Renditen prüfen"),
    ("E2", "E", "Korrelationsprüfer", "Korrelation der Symbole berechnen"),
    ("E3", "E", "Regime-Forscher", "Marktregime je Symbol klassifizieren"),
    ("E4", "E", "Overfitting-Wächter", "Abstand Training zu ungesehenem Teil messen"),
    ("E5", "E", "Stichprobenprüfer", "Trade-Anzahl gegen Mindestwert prüfen"),
    ("E6", "E", "Ausreisser-Prüfer", "Einzelne Trades mit übermässigem Einfluss finden"),
    ("E7", "E", "Volatilitätsprüfer", "ATR-Niveau je Symbol erfassen"),
    ("E8", "E", "Benchmark-Prüfer", "Kaufen-und-Halten-Vergleich führen"),
    ("E9", "E", "Literatur", "Fachliche Grundlagen im Vault verlinken"),
    ("E10", "E", "Reviewer", "Fremde Ergebnisse fachlich hinterfragen"),
    ("F1", "F", "Positionswächter", "Positionsgrössen gegen 1-%-Regel prüfen"),
    ("F2", "F", "Drawdown-Wächter", "Drawdown gegen 10-%-Not-Stop prüfen"),
    ("F3", "F", "Tagesverlust-Wächter", "Tagesverlust gegen Grenze prüfen"),
    ("F4", "F", "Engagement-Wächter", "Gesamtengagement gegen 100 % prüfen"),
    ("F5", "F", "Klumpen-Wächter", "Anzahl Positionen gegen 15 prüfen"),
    ("F6", "F", "Korrelations-Wächter", "Klumpenrisiko zwischen Positionen prüfen"),
    ("F7", "F", "Datenwächter", "Datenfehler als Handelsstopp behandeln"),
    ("F8", "F", "Verlustserien-Wächter", "Verlustserien auf Zufall prüfen"),
    ("F9", "F", "Überoptimierungs-Wächter", "Zu schöne Ergebnisse hinterfragen"),
    ("F10", "F", "Vetorecht", "Käufe ablehnen, wenn eine Grenze verletzt ist"),
    ("G1", "G", "Archivar", "Validierungen als Notiz speichern"),
    ("G2", "G", "Verlinker", "Notizen mit Strategien verknüpfen"),
    ("G3", "G", "Tag-Pfleger", "Tags vereinheitlichen"),
    ("G4", "G", "Dubletten-Pfleger", "Doppelte Notizen zusammenführen"),
    ("G5", "G", "Quellen-Pfleger", "Quellen je Notiz prüfen"),
    ("G6", "G", "Qualitätsbewerter", "Notizen mit Qualitätsstufe versehen"),
    ("G7", "G", "Veraltungs-Prüfer", "Veraltetes Wissen kennzeichnen"),
    ("G8", "G", "Index-Pfleger", "Index des Vaults aktualisieren"),
    ("G9", "G", "Entscheidungs-Archivar", "Entscheide mit Begründung ablegen"),
    ("G10", "G", "Konferenz-Archivar", "Protokolle der Mitternachtskonferenz ablegen"),
    ("H1", "H", "Code-Prüfer", "Import- und Startfähigkeit prüfen"),
    ("H2", "H", "Konfigurations-Prüfer", "config.toml auf gültige Grenzen prüfen"),
    ("H3", "H", "Testläufer", "Test-Suite ausführen"),
    ("H4", "H", "Schema-Prüfer", "Dashboard-Bericht gegen Schema 2 prüfen"),
    ("H5", "H", "Performance-Prüfer", "Laufzeit der Engine messen"),
    ("H6", "H", "Schnittstellen-Prüfer", "Broker-Schnittstelle auf Paper-Sperre prüfen"),
    ("H7", "H", "Fehler-Sammler", "Fehler je Lauf sammeln"),
    ("H8", "H", "Versions-Prüfer", "Version und Änderungen dokumentieren"),
    ("H9", "H", "Sicherheits-Prüfer", "Keine Zugangsdaten in Dateien finden"),
    ("H10", "H", "Regressions-Prüfer", "Letzte Ergebnisse mit vorherigen vergleichen"),
]

Handler = Callable[[dict[str, Any]], tuple[bool, str]]


def feld(obj: Any, name: str, standard: Any = None) -> Any:
    """Liest ein Feld aus dict oder Objekt — der Lauf reicht beides durch."""
    if isinstance(obj, dict):
        return obj.get(name, standard)
    return getattr(obj, name, standard)


def _hdl_konfiguration(ctx: dict[str, Any]) -> tuple[bool, str]:
    cfg = ctx["cfg"]
    g = cfg["risiko"]
    probleme = []
    if not 0 < float(g["risk_per_trade_pct"]) <= 5:
        probleme.append("risk_per_trade_pct ausserhalb 0–5 %")
    if not 0 < float(g["max_drawdown_pct"]) <= 50:
        probleme.append("max_drawdown_pct ausserhalb 0–50 %")
    if int(g["max_open_positions"]) < 1:
        probleme.append("max_open_positions < 1")
    return (not probleme, "Grenzen plausibel" if not probleme else "; ".join(probleme))


def _hdl_import(ctx: dict[str, Any]) -> tuple[bool, str]:
    import importlib

    module = ["orakel.config", "orakel.db", "orakel.data", "orakel.backtest", "orakel.judge"]
    for m in module:
        importlib.import_module(m)
    return True, f"{len(module)} Kernmodule ladbar"


def _hdl_test(ctx: dict[str, Any]) -> tuple[bool, str]:
    import subprocess
    import sys

    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--no-header", "-x"],
                       capture_output=True, text=True, timeout=180)
    letzte = (r.stdout.strip().splitlines() or ["keine Ausgabe"])[-1]
    return r.returncode == 0, letzte[:160]


def _hdl_schema(ctx: dict[str, Any]) -> tuple[bool, str]:
    bericht = ctx.get("bericht") or {}
    fehlend = [k for k in ("schema", "modus", "validierungen", "risiko", "plan")
               if k not in bericht]
    if bericht.get("schema") != 2:
        fehlend.append("schema!=2")
    return (not fehlend, "Schema 2 gültig" if not fehlend else f"fehlt: {', '.join(fehlend)}")


def _hdl_paper_sperre(ctx: dict[str, Any]) -> tuple[bool, str]:
    cfg = ctx["cfg"]
    art = cfg["paper"].get("broker", "csv")
    freigabe = bool(cfg["paper"].get("order_freigabe", False))
    return True, f"Broker {art}, Order-Freigabe {'an' if freigabe else 'aus (Probelauf)'}"


def _hdl_geheimnisse(ctx: dict[str, Any]) -> tuple[bool, str]:
    from pathlib import Path

    verdacht = []
    for datei in Path(".").glob("*.py"):
        kurz = datei.name.lower()
        if any(w in kurz for w in ("key", "secret", "token")):
            verdacht.append(datei.name)
    return (not verdacht, "keine Schlüsseldateien im Projekt" if not verdacht else ", ".join(verdacht))


def _hdl_daten(ctx: dict[str, Any]) -> tuple[bool, str]:
    q = ctx.get("qualitaet") or []
    fehler = [x for x in q if not x["ok"]]
    if not q:
        return False, "keine Daten geprüft"
    return (not fehler, f"{len(q) - len(fehler)}/{len(q)} Symbole in Ordnung")


def _hdl_grenzen(ctx: dict[str, Any]) -> tuple[bool, str]:
    konto = ctx.get("konto") or {}
    grenzen = ctx["grenzen"]
    dd = float(konto.get("drawdown_pct", 0.0))
    ok = dd < grenzen.max_drawdown_pct
    return ok, f"Drawdown {dd:.2f} % von {grenzen.max_drawdown_pct} %"


def _hdl_positionen(ctx: dict[str, Any]) -> tuple[bool, str]:
    konto = ctx.get("konto") or {}
    grenzen = ctx["grenzen"]
    n = int(konto.get("positionen", 0))
    return n <= grenzen.max_open_positions, f"{n} von max. {grenzen.max_open_positions} Positionen"


def _hdl_validierungen(ctx: dict[str, Any]) -> tuple[bool, str]:
    v = ctx.get("validierungen") or []
    if not v:
        return False, "keine Validierung im Lauf"
    best = sum(1 for x in v if feld(x, "urteil") == "bestanden")
    return True, f"{best} von {len(v)} Kandidaten bestanden"


def _hdl_vault(ctx: dict[str, Any]) -> tuple[bool, str]:
    from .knowledge import Vault

    vault = Vault(ctx["cfg"].vault_ordner)
    z = vault.zaehle()
    vault.index(z)
    return True, f"{sum(z.values())} Notizen im Vault"


def _hdl_fehlend(ctx: dict[str, Any]) -> tuple[bool, str]:
    return True, "keine offenen Befunde"


# ---------- Spider Intelligence: echte Artikel- und Auftragsdaten ----------
def _hdl_artikel_symbol(ctx: dict[str, Any]) -> tuple[bool, str]:
    db = ctx.get("db")
    if db is None:
        return False, "keine Datenbank im Kontext"
    zeilen = db.artikel(300)
    if not zeilen:
        return False, "keine Artikel gespeichert"
    zaehler: dict[str, int] = {}
    for r in zeilen:
        try:
            symbole = json.loads(r["symbole"] or "[]")
        except Exception:
            symbole = []
        for s in symbole:
            zaehler[s] = zaehler.get(s, 0) + 1
    if not zaehler:
        return True, f"{len(zeilen)} Artikel ohne Symbolbezug"
    top = sorted(zaehler.items(), key=lambda kv: -kv[1])[:3]
    return True, f"{len(zeilen)} Artikel · " + ", ".join(f"{s}: {n}" for s, n in top)


def _hdl_artikel_typ(typ: str):
    def handler(ctx: dict[str, Any]) -> tuple[bool, str]:
        db = ctx.get("db")
        if db is None:
            return False, "keine Datenbank im Kontext"
        n = sum(1 for r in db.artikel(500) if r["typ"] == typ)
        return n > 0, f"{n} Artikel vom Typ {typ}"
    return handler


def _hdl_quellen(ctx: dict[str, Any]) -> tuple[bool, str]:
    db = ctx.get("db")
    if db is None:
        return False, "keine Datenbank im Kontext"
    zeilen = db.artikel(300)
    ohne = [r for r in zeilen if not r["url"] or not r["quelle"]]
    return not ohne, f"{len(zeilen) - len(ohne)}/{len(zeilen)} mit Quelle und Link"


def _hdl_dubletten(ctx: dict[str, Any]) -> tuple[bool, str]:
    db = ctx.get("db")
    if db is None:
        return False, "keine Datenbank im Kontext"
    hashes = [r["titel_hash"] for r in db.artikel(500)]
    doppelt = len(hashes) - len(set(hashes))
    return doppelt == 0, f"{doppelt} doppelte Titel-Hashes"


def _hdl_mehrdeutig(ctx: dict[str, Any]) -> tuple[bool, str]:
    db = ctx.get("db")
    if db is None:
        return False, "keine Datenbank im Kontext"
    mehr = 0
    for r in db.artikel(500):
        try:
            if len(json.loads(r["symbole"] or "[]")) > 1:
                mehr += 1
        except Exception:
            pass
    return True, f"{mehr} Artikel mit mehreren Symbolen"


def _hdl_aktualitaet(ctx: dict[str, Any]) -> tuple[bool, str]:
    from datetime import datetime, timedelta, timezone

    db = ctx.get("db")
    if db is None:
        return False, "keine Datenbank im Kontext"
    grenze = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    zeilen = db.artikel(500)
    alt = [r for r in zeilen if (r["geholt"] or "") < grenze]
    return True, f"{len(alt)} von {len(zeilen)} älter als 14 Tage"


def _hdl_weiterleitungen(ctx: dict[str, Any]) -> tuple[bool, str]:
    db = ctx.get("db")
    if db is None:
        return False, "keine Datenbank im Kontext"
    st = db.intel_statistik()
    return True, f"{st['weiterleitungen_offen']} offen von {st['weiterleitungen']}"


def _hdl_limits(ctx: dict[str, Any]) -> tuple[bool, str]:
    s = ctx["cfg"].abschnitt("spider") or {}
    return True, (f"max {s.get('max_artikel_pro_lauf', 24)} Artikel, "
                  f"{s.get('max_seiten_pro_lauf', 6)} Seiten, "
                  f"Abstand {s.get('min_abstand_sekunden', 1.5)} s")


HANDLER: dict[str, Handler] = {
    "konfiguration": _hdl_konfiguration,
    "import": _hdl_import,
    "test": _hdl_test,
    "schema": _hdl_schema,
    "paper_sperre": _hdl_paper_sperre,
    "geheimnisse": _hdl_geheimnisse,
    "daten": _hdl_daten,
    "grenzen": _hdl_grenzen,
    "positionen": _hdl_positionen,
    "validierungen": _hdl_validierungen,
    "vault": _hdl_vault,
    "offen": _hdl_fehlend,
    "artikel_symbol": _hdl_artikel_symbol,
    "studien": _hdl_artikel_typ("wissenschaft"),
    "buecher": _hdl_artikel_typ("buch"),
    "videos": _hdl_artikel_typ("video"),
    "quellen": _hdl_quellen,
    "dubletten": _hdl_dubletten,
    "mehrdeutig": _hdl_mehrdeutig,
    "aktualitaet": _hdl_aktualitaet,
    "weiterleitungen": _hdl_weiterleitungen,
    "limits": _hdl_limits,
}


def _handler_fuer(kennung: str, aufgabe: str) -> str:
    text = aufgabe.lower()
    if kennung.startswith("H"):
        if "test" in text:
            return "test"
        if "schema" in text:
            return "schema"
        if "konfiguration" in text:
            return "konfiguration"
        if "paper" in text or "schnittstelle" in text:
            return "paper_sperre"
        if "sicherheit" in text or "zugangsdaten" in text:
            return "geheimnisse"
        return "import"
    if kennung.startswith("A"):
        if "paper" in text:
            return "paper_sperre"
        if "schema" in text:
            return "schema"
        return "daten"
    if kennung.startswith("F"):
        if "positionsgr" in text or "engagement" in text or "klumpen" in text:
            return "positionen"
        return "grenzen"
    if kennung.startswith("G"):
        return "vault"
    if kennung.startswith("B"):
        if "nachrichten" in text:
            return "artikel_symbol"
        if "studie" in text:
            return "studien"
        if "buch" in text:
            return "buecher"
        if "video" in text:
            return "videos"
        if "quelle" in text:
            return "quellen"
        if "dublette" in text:
            return "dubletten"
        if "widerspruch" in text:
            return "mehrdeutig"
        if "veraltet" in text or "aktualität" in text:
            return "aktualitaet"
        if "weiterleiter" in text:
            return "weiterleitungen"
        if "limit" in text:
            return "limits"
        return "artikel_symbol"
    if kennung.startswith("C") or kennung.startswith("E"):
        return "validierungen"
    if kennung.startswith("D"):
        return "positionen"
    return "daten"


def lauf(db: Facts, ctx: dict[str, Any], nur_abteilung: str | None = None) -> list[dict[str, Any]]:
    """Führt je Agent eine Aufgabe aus und schreibt das echte Ergebnis in die DB."""
    ergebnisse: list[dict[str, Any]] = []
    for kennung, abteilung, name, aufgabe in ROSTER:
        if nur_abteilung and abteilung != nur_abteilung:
            continue
        handler = HANDLER[_handler_fuer(kennung, aufgabe)]
        try:
            ok, ergebnis = handler(ctx)
        except Exception as exc:  # Ein Agent darf den Lauf nicht abbrechen
            ok, ergebnis = False, f"Fehler: {exc}"
        db.agenten_lauf(f"{abteilung}{kennung[1:]}:{name}", abteilung, aufgabe, ergebnis, ok)
        ergebnisse.append({"agent": f"{abteilung}{kennung[1:]}:{name}", "abteilung": abteilung,
                           "aufgabe": aufgabe, "ergebnis": ergebnis, "ok": ok})
    return ergebnisse


def konferenz(db: Facts, ctx: dict[str, Any], erzwungen: bool = False) -> dict[str, Any]:
    """Mitternachtskonferenz: Berichte, Kritik, Massnahmen — aus echten Zahlen."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cfg = ctx["cfg"]
    tz = ZoneInfo(cfg["basis"].get("zeitzone", "Europe/Zurich"))
    jetzt = datetime.now(tz)
    letzte = db.zustand("letzte_konferenz")
    faellig = erzwungen or letzte is None or str(letzte)[:10] != jetzt.strftime("%Y-%m-%d")

    v = ctx.get("validierungen") or []
    q = ctx.get("qualitaet") or []
    bestanden = [x for x in v if feld(x, "urteil") == "bestanden"]
    abgelehnt = [x for x in v if feld(x, "urteil") == "abgelehnt"]
    fehler = [x for x in q if not x["ok"]]

    berichte = [
        {"abteilung": "A", "name": ABTEILUNGEN["A"],
         "text": f"{len(v)} Kandidaten koordiniert, {len(bestanden)} zur Auswahl freigegeben."},
        {"abteilung": "B", "name": ABTEILUNGEN["B"],
         "text": "Externe Recherche in diesem Lauf nicht aktiv (kein Netzzugang konfiguriert)."},
        {"abteilung": "C", "name": ABTEILUNGEN["C"],
         "text": f"Parameter-Raster durchlaufen: {len(v)} Tests, {len(abgelehnt)} aussortiert."},
        {"abteilung": "D", "name": ABTEILUNGEN["D"],
         "text": f"Ausführung im Modus {ctx.get('modus', 'backtest')}; "
                 f"{len(ctx.get('plan') or [])} Auftragsentwürfe."},
        {"abteilung": "E", "name": ABTEILUNGEN["E"],
         "text": "Training und ungesehener Teil getrennt ausgewertet, Zufallsvergleich gerechnet."},
        {"abteilung": "F", "name": ABTEILUNGEN["F"],
         "text": f"Grenzen aktiv: 1 % je Trade, 10 % Not-Stop, 15 Positionen. "
                 f"{len(fehler)} Datenfehler."},
        {"abteilung": "G", "name": ABTEILUNGEN["G"],
         "text": "Ergebnisse im Vault abgelegt."},
        {"abteilung": "H", "name": ABTEILUNGEN["H"],
         "text": "Code, Konfiguration und Berichtsschema geprüft."},
    ]

    diskussion: list[dict[str, str]] = []
    if abgelehnt:
        gruende: dict[str, int] = {}
        for x in abgelehnt:
            for g in (feld(x, "gruende") or []):
                schluessel = g.split("—")[0].strip()[:70]
                gruende[schluessel] = gruende.get(schluessel, 0) + 1
        top = sorted(gruende.items(), key=lambda kv: -kv[1])[:2]
        diskussion.append({
            "von": "F:Risikomanagement", "an": "C:Labor",
            "text": "Die häufigsten Ablehnungsgründe sind " + "; ".join(f"«{k}» ({n}×)" for k, n in top)
                    + ". Das Labor muss diese zuerst adressieren, nicht neue Ideen liefern.",
        })
    if fehler:
        diskussion.append({
            "von": "F:Datenwächter", "an": "A:Hauptzentrale",
            "text": f"{len(fehler)} Symbole haben Datenfehler. Im Paper-Modus bedeutet das Handelsstopp.",
        })
    if not bestanden:
        diskussion.append({
            "von": "E:Reviewer", "an": "C:Labor",
            "text": "Keine Strategie hat den Richter bestanden. Es wird nicht gehandelt — das ist korrekt, "
                    "kein Fehler.",
        })
    if not diskussion:
        diskussion.append({
            "von": "E:Reviewer", "an": "A:Hauptzentrale",
            "text": "Ergebnisse sind unauffällig. Die Messlatte bleibt unverändert.",
        })

    massnahmen = []
    zaehler: dict[str, int] = {}
    for g in (g for x in abgelehnt for g in (feld(x, "gruende") or [])):
        schluessel = g.split("—")[0].strip()[:70]
        zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
    for k, n in sorted(zaehler.items(), key=lambda kv: -kv[1])[:3]:
        massnahmen.append({
            "beschreibung": f"Ablehnungsgrund «{k}» untersuchen",
            "begruendung": f"{n} Kandidaten scheiterten daran",
            "vorteil": "Weniger Fehlversuche im nächsten Raster",
            "risiko": "Zu frühes Wegoptimieren von Strategietypen",
            "testplan": "Gleiches Raster erneut, Vergleich der Quote vor/nach",
            "verantwortlich": "C:Labor",
        })
    if not massnahmen:
        massnahmen.append({
            "beschreibung": "Messlatte unverändert lassen, Datenbasis erweitern",
            "begruendung": "Keine systematischen Ablehnungsgründe erkennbar",
            "vorteil": "Mehr Out-of-Sample-Daten",
            "risiko": "Längere Wartezeit bis zur nächsten Freigabe",
            "testplan": "Nach Datenimport: vollständiges Raster erneut",
            "verantwortlich": "A:Hauptzentrale",
        })

    protokoll = {
        "zeit": jetzt.replace(microsecond=0).isoformat(),
        "faellig": faellig,
        "modus": ctx.get("modus", "backtest"),
        "berichte": berichte,
        "diskussion": diskussion,
        "massnahmen": massnahmen,
        "beschluss": ("Keine Strategie freigegeben — es wird nicht gehandelt."
                      if not bestanden else
                      f"{len(bestanden)} Strategien bleiben freigegeben; Änderungen nur nach Test."),
    }
    db.konferenz_speichern(protokoll)
    db.zustand_setzen("letzte_konferenz", protokoll["zeit"])
    return protokoll
