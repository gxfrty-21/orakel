"""Sekretariat: drei Agenten, die berichten, priorisieren und eskalieren.

Sie entscheiden nichts frei und sind keine Genehmigungshürde. Jede Antwort
stützt sich ausschliesslich auf Werte aus der Fakten-Datenbank; fehlt eine
Grundlage, wird das gesagt. Der Chatverlauf liegt in SQLite (Zustand), nicht
im Browser.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config
from .db import Facts, jetzt
from .knowledge import Vault

SEKRETAERE: list[dict[str, str]] = [
    {"id": "S1", "name": "Mira", "rolle": "Empfang & Koordination",
     "auftrag": "Offene Befunde, Artikel und Weiterleitungen sammeln"},
    {"id": "S2", "name": "Jonas", "rolle": "Berichte",
     "auftrag": "Läufe zu einem Tagesbericht verdichten"},
    {"id": "S3", "name": "Lea", "rolle": "CEO-Kommunikation",
     "auftrag": "Kritisches markieren und in die Konferenz legen"},
]
NAMEN = {s["id"]: s["name"] for s in SEKRETAERE}


def lage(db: Facts) -> dict[str, Any]:
    """Echter Zustand, aus dem die Sekretäre antworten."""
    basis = db.zustand("bericht_basis") or {}
    agenten = basis.get("agenten") or []
    spider = db.zustand("spider_letzter_lauf") or {}
    konf = db.letzte_konferenz()
    protokoll = (konf or {}).get("protokoll") or {}
    return {
        "agenten": len(agenten),
        "befunde": sum(1 for a in agenten if a.get("ok") is False),
        "artikel": (spider.get("statistik") or {}).get("gesamt", 0),
        "neu": spider.get("neu", 0),
        "stand": spider.get("stand"),
        "konferenz_zeit": (konf or {}).get("zeit"),
        "beschluss": protokoll.get("beschluss"),
        "massnahmen": len(protokoll.get("massnahmen") or []),
        "konto": (db.zustand("paper_konto") or {}).get("cash"),
        "fehler": len(basis.get("fehler") or []),
    }


def _zahlen(l: dict[str, Any]) -> str:
    return (f"{l['agenten']} Agentenläufe, {l['befunde']} Befunde, "
            f"{l['artikel']} Artikel im Bestand")


def antwort(db: Facts, sekretaer: str, frage: str) -> str:
    """Regelbasierte Antwort mit echten Zahlen. Kein Sprachmodell."""
    l = lage(db)
    text = (frage or "").strip().lower()
    name = NAMEN.get(sekretaer, "Sekretariat")

    if not text:
        return f"{name}: Ich brauche eine Frage, dann antworte ich mit dem aktuellen Stand."
    if any(w in text for w in ("befund", "fehler", "problem", "kritisch")):
        return (f"{name}: {l['befunde']} Befunde und {l['fehler']} gemeldete Fehler im letzten Lauf. "
                f"Offene Punkte stehen im Agentenraum und im Vault.")
    if any(w in text for w in ("artikel", "nachricht", "spinne", "quelle")):
        stand = (l["stand"] or "unbekannt").replace("T", " ")[:16]
        return (f"{name}: {l['artikel']} Artikel im Bestand, zuletzt {l['neu']} neu gespeichert "
                f"(Abruf {stand}). Die Quellenliste steht in der Spider-Ansicht.")
    if any(w in text for w in ("konferenz", "meeting", "mitternacht", "sitzung")):
        if not l["konferenz_zeit"]:
            return f"{name}: Noch keine Konferenz gespeichert."
        return (f"{name}: Letzte Konferenz {str(l['konferenz_zeit']).replace('T', ' ')[:16]}, "
                f"{l['massnahmen']} Massnahmen. Beschluss: {l['beschluss'] or 'kein Beschluss gespeichert'}.")
    if any(w in text for w in ("konto", "geld", "risiko", "paper")):
        konto = l["konto"]
        return (f"{name}: Konto {konto if konto is not None else 'KEINE DATEN'}. "
                "Es gilt Paper-Trading; es gibt keinen Pfad zu einer echten Broker-Order.")
    if any(w in text for w in ("status", "lage", "überblick", "stand")):
        return f"{name}: {_zahlen(l)}."
    return (f"{name}: Dazu habe ich keine gespeicherte Grundlage. "
            f"Aktuell: {_zahlen(l)}. Frag mich nach Befunden, Artikeln, Konferenz, Konto oder Status.")


def _dauer_minuten(einstieg: str, ausstieg: str) -> int | None:
    try:
        a = datetime.fromisoformat(str(einstieg))
        b = datetime.fromisoformat(str(ausstieg))
        return max(0, int((b - a).total_seconds() // 60))
    except Exception:
        return None


def _trade_thema(tr: dict[str, Any]) -> dict[str, Any]:
    """Ein einzelner Trade als Sitzungsthema."""
    gewinn = tr["netto"] >= 0
    dauer = tr["dauer"]
    if gewinn:
        besser = ("Der Ausstieg kam nach wenigen Minuten — prüfen, ob mehr drin gewesen wäre."
                  if dauer is not None and dauer < 120 else
                  "Die These hat getragen; Ausstieg und Positionsgrösse waren stimmig.")
        gelernt = "Das Muster gehört dokumentiert, damit es wiederholbar wird."
    else:
        if dauer is not None and dauer < 60:
            besser = "Länger auf Bestätigung warten; der Einstieg kam nach wenigen Minuten wieder heraus."
        elif abs(tr["rendite"]) >= 0.5:
            besser = "Positionsgrösse war für diese Schwankung zu hoch; kleiner einsteigen."
        elif tr["grund"].lower().startswith("stop"):
            besser = "Stop lag zu eng für die normale Tagesschwankung."
        else:
            besser = "These vor dem Eintritt schriftlich festhalten und den Ausstieg daran messen."
        gelernt = (f"Der Verlust blieb mit {abs(tr['rendite']):.2f}% innerhalb der Risikogrenze; "
                   "entscheidend ist, ob der Ausstieg regelkonform war."
                   if abs(tr["rendite"]) <= 1.0 else
                   "Die Schwelle zur Risikogrenze wurde überschritten — Regel prüfen.")
    return {
        "leiter": "S2", "art": "gewinn" if gewinn else "verlust",
        "rendite": tr["rendite"], "netto": tr["netto"],
        "dauer_minuten": dauer, "ausstieg_grund": tr["grund"],
        "thema": (f"Gewinn {tr['symbol']}: +{tr['rendite']:.2f}% ({tr['netto']:.2f})" if gewinn
                  else f"Verlust {tr['symbol']}: {tr['rendite']:.2f}% ({tr['netto']:.2f})"),
        "gemacht": (f"{tr['stueck']} Stück, Einstieg {str(tr['einstieg'])[:16]}, "
                    f"Ausstieg {str(tr['ausstieg'])[:16]}"),
        "besser": besser,
        "gelernt": gelernt,
    }


def agenda(db: Facts, grenze: int = 6) -> dict[str, Any]:
    """Sammelt die Themen für die nächste Sitzung aus echten Daten.

    Trades mit demselben Ausstiegsgrund werden zu einem Muster gebündelt;
    Verluste und Gewinne fliessen gemeinsam ein.
    """
    themen: list[dict[str, Any]] = []
    with db.conn() as c:
        zeilen = c.execute(
            "SELECT symbol, einstieg, ausstieg, stueck, netto, rendite_pct, grund "
            "FROM trades WHERE netto < 0 ORDER BY ausstieg DESC LIMIT 200"
        ).fetchall()
        gewinne = c.execute(
            "SELECT symbol, einstieg, ausstieg, stueck, netto, rendite_pct, grund "
            "FROM trades WHERE netto > 0 ORDER BY rendite_pct DESC LIMIT 40"
        ).fetchall()

    trades: list[dict[str, Any]] = []
    gesehen: set[tuple[Any, ...]] = set()
    for z in zeilen:
        symbol, einstieg, ausstieg, stueck, netto, rendite, grund = z[:7]
        schluessel = (symbol, einstieg, ausstieg, rendite, netto)
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        trades.append({"symbol": symbol, "einstieg": einstieg, "ausstieg": ausstieg,
                       "stueck": stueck, "netto": float(netto or 0),
                       "rendite": float(rendite or 0), "grund": str(grund or "ohne Angabe"),
                       "dauer": _dauer_minuten(einstieg, ausstieg)})
    gewinn_anzahl = 0
    for z in gewinne:
        symbol, einstieg, ausstieg, stueck, netto, rendite, grund = z[:7]
        schluessel = (symbol, einstieg, ausstieg, rendite, netto)
        if schluessel in gesehen or gewinn_anzahl >= 6:
            continue
        gesehen.add(schluessel)
        gewinn_anzahl += 1
        trades.append({"symbol": symbol, "einstieg": einstieg, "ausstieg": ausstieg,
                       "stueck": stueck, "netto": float(netto or 0),
                       "rendite": float(rendite or 0), "grund": str(grund or "ohne Angabe"),
                       "dauer": _dauer_minuten(einstieg, ausstieg)})

    gruppen: dict[str, list[dict[str, Any]]] = {}
    for tr in trades:
        gruppen.setdefault(tr["grund"], []).append(tr)

    for grund, liste in gruppen.items():
        anzahl = len(liste)
        verluste = sum(1 for x in liste if x["netto"] < 0)
        gewinne_n = anzahl - verluste
        summe = sum(x["netto"] for x in liste)
        schnitt = sum(x["rendite"] for x in liste) / anzahl
        dauerwerte = [x["dauer"] for x in liste if x["dauer"] is not None]
        schnitt_dauer = int(sum(dauerwerte) / len(dauerwerte)) if dauerwerte else None
        themen.append({
            "leiter": "S2", "art": "muster", "ausstieg_grund": grund,
            "rendite": schnitt, "netto": summe, "dauer_minuten": schnitt_dauer,
            "thema": f"Muster «{grund}»: {anzahl} Trades ({verluste} Verluste, {gewinne_n} Gewinne)",
            "gemacht": (f"Summe Netto {summe:+.2f}, durchschnittliche Rendite {schnitt:+.2f}%, "
                        f"{verluste} Verluste / {gewinne_n} Gewinne, durchschnittliche Dauer "
                        f"{schnitt_dauer if schnitt_dauer is not None else 'unbekannt'} Min."),
            "besser": ("Unterm Strich negativ — Ausstieg früher schliessen oder die These vorher prüfen."
                       if summe < 0 else
                       "Unterm Strich positiv — Muster beibehalten, Grösse und Dauer aber prüfen."),
            "gelernt": (f"Der Ausstiegsgrund «{grund}» allein erklärt die Ergebnisse nicht; "
                        "entscheidend ist, ob Dauer und Positionsgrösse zur These passen."),
            "trades": [{"symbol": x["symbol"], "einstieg": x["einstieg"],
                        "ausstieg": x["ausstieg"], "netto": round(x["netto"], 2),
                        "rendite": round(x["rendite"], 2), "dauer": x["dauer"],
                        "grund": x.get("grund")}
                       for x in liste],
        })

    # Einzelthemen: Verluste und Gewinne wechseln sich ab (je bis zu 6).
    verluste_liste = [tr for tr in trades if tr["netto"] < 0][:6]
    gewinne_liste = [tr for tr in trades if tr["netto"] > 0][:6]
    for i in range(max(len(verluste_liste), len(gewinne_liste))):
        if i < len(verluste_liste):
            themen.append(_trade_thema(verluste_liste[i]))
        if i < len(gewinne_liste):
            themen.append(_trade_thema(gewinne_liste[i]))

    l = lage(db)
    if l["befunde"]:
        themen.append({"leiter": "S1", "art": "befund",
                       "thema": f"{l['befunde']} offene Befunde aus dem Agentenlauf",
                       "gemacht": "Die Agenten haben Befunde gemeldet; Details stehen im Agentenraum.",
                       "besser": "Befunde vor der Sitzung abarbeiten, nicht in der Sitzung.",
                       "gelernt": "Offene Befunde sammeln sich, wenn kein Termin dafür gesetzt ist."})
    if l["fehler"]:
        themen.append({"leiter": "S1", "art": "fehler",
                       "thema": f"{l['fehler']} gemeldete Fehler",
                       "gemacht": "Fehler traten im letzten Lauf auf.",
                       "besser": "Ursache vor der nächsten Sitzung eingrenzen.",
                       "gelernt": "Fehler brauchen einen festen Platz in der Agenda."})
    if l["massnahmen"]:
        themen.append({"leiter": "S3", "art": "beschluss",
                       "thema": f"{l['massnahmen']} Massnahmen aus der letzten Konferenz",
                       "gemacht": f"Beschluss: {l['beschluss'] or 'kein Beschluss gespeichert'}",
                       "besser": "Umsetzung jeder Massnahme mit Datum versehen.",
                       "gelernt": "Beschlüsse ohne Termin werden nicht überprüft."})

    for v in _vertagt_liste(db):
        themen.insert(0, {**{k: v.get(k) for k in VERTAGT_FELDER},
                          "vertagt": True, "vertagt_am": v.get("vertagt_am")})

    # Befunde und Beschlüsse ohne Termin bekommen automatisch einen: eine
    # Woche ab heute, damit sie nicht dauerhaft vertagt werden.
    try:
        from .config import load_config
        vorlauf = max(1, int(load_config().abschnitt("betrieb")
                             .get("sekretariat_termin_tage", 7)))
    except Exception:
        vorlauf = 7
    frist = (datetime.fromisoformat(jetzt()).astimezone(timezone.utc)
             + timedelta(days=vorlauf)).date().isoformat()
    for t in themen:
        if t.get("art") in ("befund", "beschluss") and not t.get("termin"):
            t["termin"] = frist

    eintrag = {"zeit": jetzt(), "termin_tage": vorlauf, "themen": themen,
               "grundlage": {"verluste": sum(1 for x in trades if x["netto"] < 0),
                             "gewinne": gewinn_anzahl,
                             "muster": len(gruppen),
                             **{k: l[k] for k in ("befunde", "fehler", "massnahmen")}}}
    db.zustand_setzen("sekretariat_agenda", eintrag)
    return eintrag


VERTAGT_FELDER = ("leiter", "art", "thema", "gemacht", "besser", "gelernt",
                  "massnahme", "rendite", "netto", "dauer_minuten", "ausstieg_grund")


def _vertagt_liste(db: Facts) -> list[dict[str, Any]]:
    return list(db.zustand("sekretariat_vertagt") or [])


def _vertagt_hinzufuegen(db: Facts, thema: dict[str, Any]) -> None:
    """Merkt ein vertagtes Thema für die nächste Sitzung, ohne Duplikate."""
    schluessel = (thema.get("thema"), thema.get("art"))
    liste = [x for x in _vertagt_liste(db)
             if (x.get("thema"), x.get("art")) != schluessel]
    eintrag = {k: thema.get(k) for k in VERTAGT_FELDER}
    eintrag["vertagt_am"] = jetzt()
    liste.append(eintrag)
    db.zustand_setzen("sekretariat_vertagt", liste[-20:])


def _vertagt_entfernen(db: Facts, thema: dict[str, Any]) -> None:
    schluessel = (thema.get("thema"), thema.get("art"))
    liste = [x for x in _vertagt_liste(db)
             if (x.get("thema"), x.get("art")) != schluessel]
    db.zustand_setzen("sekretariat_vertagt", liste)


def _beitraege(thema: dict[str, Any]) -> list[dict[str, str]]:
    """Wortmeldungen der drei Sekretäre zu einem Thema — aus den Daten."""
    art = thema.get("art")
    if art == "verlust":
        return [
            {"von": "S1", "text": f"Zum Nachlesen, was tatsächlich passiert ist: {thema['gemacht']}."},
            {"von": "S2", "text": f"Meine Einordnung: {thema['besser']}"},
            {"von": "S3", "text": f"Das ist der Punkt für dich: {thema['gelernt']}"},
        ]
    if art == "muster":
        return [
            {"von": "S1", "text": f"Im Bündel: {thema['gemacht']}."},
            {"von": "S2", "text": f"Meine Einordnung: {thema['besser']}"},
            {"von": "S3", "text": f"Was daraus folgt: {thema['gelernt']}"},
        ]
    if art == "gewinn":
        return [
            {"von": "S1", "text": f"Was tatsächlich passiert ist: {thema['gemacht']}."},
            {"von": "S2", "text": f"Meine Einordnung: {thema['besser']}"},
            {"von": "S3", "text": f"Warum das zählt: {thema['gelernt']}"},
        ]
    if art == "befund":
        return [
            {"von": "S1", "text": "Die Befunde liegen im Agentenraum, ich habe sie vollständig gezählt."},
            {"von": "S2", "text": "Ich schlage vor, sie vor der Sitzung abzuarbeiten statt hier."},
            {"von": "S3", "text": "Offene Befunde sind kein Entscheid für dich, solange keine Grenze verletzt ist."},
        ]
    if art == "fehler":
        return [
            {"von": "S1", "text": "Fehler sind im letzten Lauf gemeldet worden."},
            {"von": "S2", "text": "Ohne Ursache gibt es keine belastbare Massnahme."},
            {"von": "S3", "text": "Bei wiederholten Fehlern stoppt der Paper-Betrieb; das ist keine Frage."},
        ]
    return [
        {"von": "S1", "text": f"Stand der letzten Sitzung: {thema['gemacht']}"},
        {"von": "S2", "text": f"Vorschlag zur Umsetzung: {thema['besser']}"},
        {"von": "S3", "text": f"Was daraus folgt: {thema['gelernt']}"},
    ]


def _empfehlung(thema: dict[str, Any]) -> str:
    art = thema.get("art")
    if art == "muster":
        return "Ausstiegsregel im Labor gegen Alternativen prüfen lassen."
    if art == "gewinn":
        return "Muster dokumentieren und im Labor auf Wiederholbarkeit prüfen lassen."
    if art == "verlust":
        return "Als Lernpunkt annehmen und die Regel im Labor prüfen lassen."
    if art == "befund":
        return "Vertagen, bis die Befunde abgearbeitet sind."
    if art == "fehler":
        return "Annehmen: Ursache eingrenzen, bevor weiter gehandelt wird."
    return "Annehmen, wenn ein Termin dafür gesetzt wird."


# Zuständige Abteilung je Themenart (Code: Name).
ABTEILUNG_JE_ART = {
    "muster": ("C", "Labor"),
    "gewinn": ("C", "Labor"),
    "verlust": ("C", "Labor"),
    "befund": ("A", "Hauptzentrale"),
    "fehler": ("H", "Entwicklungsabteilung"),
    "beschluss": ("F", "Risikomanagement"),
}


def _mission_anlegen(db: Facts, thema: dict[str, Any]) -> tuple[str, str]:
    """Legt für einen angenommenen Beschluss eine Mission mit Aufgabenkette an."""
    from datetime import datetime as _dt

    tag = _dt.now().strftime("%Y%m%d")
    nummer = db.nexus_mission_zaehler(tag) + 1
    while True:
        kennung = f"MS-{tag}-{nummer:03d}"
        if not db.nexus_mission_kennung_existiert(kennung):
            break
        nummer += 1
    code, name = ABTEILUNG_JE_ART.get(str(thema.get("art")), ("A", "Hauptzentrale"))
    massnahme = thema.get("massnahme") or thema.get("empfehlung") or ""
    auftrag = (f"Beschluss der Sitzung: {thema.get('thema')}\n"
               f"Massnahme: {massnahme}\n"
               f"Zuständige Abteilung: {code}:{name}\n"
               f"Grundlage: {thema.get('gemacht')}")
    tasks = [
        {"rolle": "lage", "ziel": f"Lage zum Beschluss «{thema.get('thema')}» prüfen",
         "max_versuche": 2},
        {"rolle": "pruefung", "ziel": f"Umsetzung prüfen: {massnahme}", "max_versuche": 2},
        {"rolle": "bericht", "ziel": f"Ergebnis an {name} melden", "max_versuche": 2},
    ]
    prioritaet = "hoch" if thema.get("art") == "fehler" else "normal"
    db.nexus_mission_anlegen(kennung, f"Sitzungsbeschluss: {thema.get('thema')}",
                             auftrag, prioritaet, tasks, jetzt())
    return kennung, f"{code}:{name}"


def _voten(t: dict[str, Any]) -> list[dict[str, str]]:
    """Stimmen der drei Sekretäre zur vorgeschlagenen Massnahme.

    Die Regeln sind fest und nachvollziehbar; sie hängen nur an den Daten des
    Themas, nicht an Stimmung oder Zufall.
    """
    art = t.get("art")
    if art == "muster":
        summe = float(t.get("netto") or 0)
        return [
            {"von": "S1", "entscheid": "annehmen",
             "grund": "Das Bündel ist vollständig aus den Trades abgeleitet."},
            {"von": "S2", "entscheid": "annehmen",
             "grund": "Das Muster ist mit echten Zahlen belegt."},
            {"von": "S3", "entscheid": "annehmen",
             "grund": (f"Unterm Strich {summe:+.2f} — die Regel gehört geprüft." if summe < 0
                       else f"Unterm Strich {summe:+.2f} — Muster bestätigt, weiter beobachten.")},
        ]
    if art == "gewinn":
        rendite = abs(float(t.get("rendite") or 0))
        return [
            {"von": "S1", "entscheid": "annehmen",
             "grund": "Der Trade ist vollständig dokumentiert."},
            {"von": "S2", "entscheid": "annehmen",
             "grund": "Ein belegtes Muster ist mehr wert als ein Zufallstreffer."},
            {"von": "S3", "entscheid": "annehmen" if rendite >= 0.5 else "vertagen",
             "grund": (f"{rendite:.2f}% sind gross genug für eine Regelprüfung." if rendite >= 0.5
                       else f"{rendite:.2f}% sind zu klein für ein belastbares Muster.")},
        ]
    if art == "verlust":
        rendite = abs(float(t.get("rendite") or 0))
        return [
            {"von": "S1", "entscheid": "annehmen",
             "grund": "Die Datenlage zum Trade ist vollständig."},
            {"von": "S2", "entscheid": "annehmen",
             "grund": "Das Muster steht im Bericht und die Regel ist prüfbar."},
            {"von": "S3", "entscheid": "annehmen" if rendite <= 1.0 else "ablehnen",
             "grund": (f"{rendite:.2f}% liegt innerhalb der Risikogrenze." if rendite <= 1.0
                       else f"{rendite:.2f}% überschreitet die Grenze; zuerst ins Labor.")},
        ]
    if art in ("befund", "beschluss") and not t.get("termin"):
        return [
            {"von": "S1", "entscheid": "vertagen",
             "grund": "Ohne Termin lässt sich der Befund nicht abarbeiten." if art == "befund"
                      else "Ohne Termin ist der Beschluss nicht überprüfbar."},
            {"von": "S2", "entscheid": "vertagen",
             "grund": "Das gehört mit Datum vor die Sitzung, nicht in sie."},
            {"von": "S3", "entscheid": "vertagen",
             "grund": "Ohne Termin keine Wirkung."},
        ]
    if art == "befund":
        return [
            {"von": "S1", "entscheid": "annehmen", "grund": "Befunde abarbeiten ist Koordination."},
            {"von": "S2", "entscheid": "vertagen", "grund": "Das gehört vor die Sitzung, nicht in sie."},
            {"von": "S3", "entscheid": "annehmen",
             "grund": "Solange keine Grenze verletzt ist, ist das kein Entscheid für den CEO."},
        ]
    if art == "fehler":
        return [
            {"von": "S1", "entscheid": "annehmen", "grund": "Fehler zuerst eingrenzen."},
            {"von": "S2", "entscheid": "annehmen", "grund": "Ohne Ursache keine belastbare Massnahme."},
            {"von": "S3", "entscheid": "annehmen",
             "grund": "Wiederholte Fehler stoppen den Paper-Betrieb."},
        ]
    if not t.get("termin"):
        return [
            {"von": "S1", "entscheid": "vertagen", "grund": "Ohne Termin keine Grundlage."},
            {"von": "S2", "entscheid": "vertagen", "grund": "Zuerst einen Termin festlegen."},
            {"von": "S3", "entscheid": "vertagen", "grund": "Ohne Termin keine Wirkung."},
        ]
    return [
        {"von": "S1", "entscheid": "annehmen", "grund": "Die Massnahme ist dokumentiert."},
        {"von": "S2", "entscheid": "annehmen", "grund": "Mit Termin ist sie überprüfbar."},
        {"von": "S3", "entscheid": "annehmen", "grund": "Der Termin macht sie überprüfbar."},
    ]


def _mehrheit(stimmen: list[dict[str, str]], leiter: str) -> tuple[str, dict[str, int]]:
    zaehler = {"annehmen": 0, "ablehnen": 0, "vertagen": 0}
    for s in stimmen:
        zaehler[s["entscheid"]] = zaehler.get(s["entscheid"], 0) + 1
    top = max(zaehler.values())
    kandidaten = [k for k, v in zaehler.items() if v == top]
    if len(kandidaten) == 1:
        return kandidaten[0], zaehler
    leitende = [s["entscheid"] for s in stimmen if s.get("von") == leiter]
    return (leitende[0] if leitende else kandidaten[0]), zaehler


def sitzung_start(db: Facts) -> dict[str, Any]:
    """Eröffnet die Sitzung aus der aktuellen Agenda."""
    a = agenda(db)
    themen = []
    for i, t in enumerate(a["themen"]):
        themen.append({**t, "index": i, "status": "offen", "phase": "rede",
                       "schritt": 0, "stimmen": [], "ergebnis": None,
                       "beitraege": _beitraege(t), "empfehlung": _empfehlung(t),
                       "massnahme": _empfehlung(t)})
    s = {"start": jetzt(), "status": "laeuft", "aktiv": 0,
         "themen": themen, "entscheide": []}
    db.zustand_setzen("sekretariat_sitzung", s)
    return s


def sitzung(db: Facts) -> dict[str, Any]:
    s = db.zustand("sekretariat_sitzung")
    return s if s else {"status": "offen", "themen": [], "entscheide": []}


def sitzung_weiter(db: Facts, vault: Vault | None = None) -> dict[str, Any]:
    """Ein Schritt der Moderation: nächste Wortmeldung, dann Abstimmung."""
    s = sitzung(db)
    if s.get("status") != "laeuft":
        raise ValueError("Keine laufende Sitzung")
    themen = s.get("themen") or []
    t = next((x for x in themen if x.get("index") == s.get("aktiv")), themen[0] if themen else None)
    if t is None:
        return sitzung_abschluss(db, vault)
    if t.get("status") != "offen":
        # Das aktive Thema ist entschieden: erst das Ergebnis stehen lassen,
        # beim nächsten Schritt das nächste offene Thema aufrufen.
        naechste = [x for x in themen if x.get("status") == "offen" and x["index"] > t["index"]] \
            or [x for x in themen if x.get("status") == "offen"]
        if not naechste:
            return sitzung_abschluss(db, vault)
        t = naechste[0]
        s["aktiv"] = t["index"]
    if t.get("phase") == "rede":
        if t.get("schritt", 0) < len(t.get("beitraege") or []):
            t["schritt"] = t.get("schritt", 0) + 1
        if t["schritt"] >= len(t.get("beitraege") or []):
            t["phase"] = "abstimmung"
            # Letzte Wortmeldung: die Abstimmung ist ein eigener Schritt.
            db.zustand_setzen("sekretariat_sitzung", s)
            return s
    if t.get("phase") == "abstimmung":
        stimmen = _voten(t)
        ergebnis, zaehler = _mehrheit(stimmen, str(t.get("leiter") or ""))
        t["stimmen"] = stimmen
        t["zaehlung"] = zaehler
        t["ergebnis"] = ergebnis
        t["phase"] = "ergebnis"
        t["status"] = ergebnis
        eintrag = {
            "index": t["index"], "thema": t["thema"], "leiter": t.get("leiter"),
            "entscheid": ergebnis, "zeit": jetzt(), "zaehlung": zaehler,
            "massnahme": t.get("massnahme"),
        }
        if ergebnis == "vertagen":
            _vertagt_hinzufuegen(db, t)
        elif t.get("vertagt"):
            _vertagt_entfernen(db, t)
        if ergebnis == "annehmen":
            try:
                kennung, abteilung = _mission_anlegen(db, t)
                eintrag["mission"] = kennung
                eintrag["abteilung"] = abteilung
            except Exception as exc:  # Sitzung darf daran nicht scheitern
                eintrag["mission_fehler"] = f"{type(exc).__name__}: {exc}"
        s.setdefault("entscheide", []).append(eintrag)
    db.zustand_setzen("sekretariat_sitzung", s)
    return s


def stimme(db: Facts, index: int, entscheid: str) -> dict[str, Any]:
    s = sitzung(db)
    if s.get("status") != "laeuft":
        raise ValueError("Keine laufende Sitzung")
    if entscheid not in ("annehmen", "ablehnen", "vertagen"):
        raise ValueError("Unbekannter Entscheid")
    themen = s.get("themen") or []
    if not (0 <= index < len(themen)):
        raise ValueError("Unbekanntes Thema")
    t = themen[index]
    if t.get("status") != "offen":
        raise ValueError("Thema ist bereits entschieden")
    t["status"] = entscheid
    s.setdefault("entscheide", []).append({
        "index": index, "thema": t["thema"], "leiter": t.get("leiter"),
        "entscheid": entscheid, "zeit": jetzt(),
    })
    db.zustand_setzen("sekretariat_sitzung", s)
    return s


def sitzung_mit_status(db: Facts) -> dict[str, Any]:
    """Sitzung mit dem aktuellen Status der weitergeleiteten Missionen."""
    s = sitzung(db)
    try:
        from .config import load_config
        s["alt_stunden"] = max(1, int(load_config().abschnitt("betrieb")
                                     .get("sekretariat_alt_stunden", 1)))
    except Exception:
        s["alt_stunden"] = 1
    for e in s.get("entscheide") or []:
        kennung = e.get("mission")
        if not kennung:
            continue
        try:
            m = db.nexus_mission(kennung)
        except Exception:
            m = None
        if m:
            e["mission_status"] = m.get("status")
            e["mission_fortschritt"] = m.get("fortschritt")
            e["mission_geaendert"] = m.get("aktualisiert")
            e["mission_tasks"] = [
                {"rolle": t.get("rolle"), "ziel": t.get("ziel"), "status": t.get("status"),
                 "ergebnis": t.get("ergebnis") or {},
                 "fehler": t.get("fehler"),
                 "geaendert": t.get("aktualisiert"),
                 "fehlgeschlagen_am": t.get("fehlgeschlagen_am"),
                 "abgeschlossen_am": (t.get("abgeschlossen_am")
                                      or (t.get("aktualisiert")
                                          if t.get("status") == "erledigt" else None))}
                for t in (m.get("tasks") or [])
            ]
        else:
            e["mission_status"] = "nicht gefunden"
    return s


def protokolle(vault: Vault, limit: int = 50, suche: str = "", entscheid: str = "",
               von: str = "", bis: str = "",
               sortierung: str = "neu") -> tuple[list[dict[str, Any]], int]:
    """Sitzungsprotokolle aus dem Vault — serverseitig gesucht und gefiltert.

    Rückgabe: (Treffer, Gesamtzahl der Sitzungsprotokolle ohne Filter).
    """
    text = (suche or "").strip().lower()
    label = {"angenommen": "Angenommen", "abgelehnt": "Abgelehnt",
             "vertagt": "Vertagt", "offen": "Offen"}.get(entscheid)
    wort = {"angenommen": "annehmen", "abgelehnt": "ablehnen",
            "vertagt": "vertagen"}.get(entscheid)

    alle: list[dict[str, Any]] = []
    for n in vault.notizen("konferenz", limit=1000):
        if "sitzung" not in [t.lower() for t in (n.get("tags") or [])]:
            continue
        inhalt = (n.get("text") or "").lstrip()
        if inhalt.startswith("---"):
            ende_kopf = inhalt.find("\n---", 3)
            if ende_kopf != -1:
                inhalt = inhalt[ende_kopf + 4:]
        inhalt = inhalt.strip()
        if inhalt.startswith("# "):
            inhalt = inhalt.split("\n", 1)[-1].lstrip()
        titel = n.get("titel") or ""
        m = re.search(r"(\d{4}-\d{2}-\d{2})", titel)
        datum = m.group(1) if m else str(n.get("erstellt") or "")[:10]
        alle.append({"titel": titel, "erstellt": n.get("erstellt"), "datum": datum,
                     "inhalt": inhalt[:4000]})

    def passt(p: dict[str, Any]) -> bool:
        datum = str(p.get("datum") or "")[:10]
        if von and datum < von:
            return False
        if bis and datum > bis:
            return False
        if text and text not in (((p.get("titel") or "") + " " + p["inhalt"]).lower()):
            return False
        if entscheid:
            treffer = bool(label and re.search(r"\*\*" + label + r":\*\*\s*[1-9]", p["inhalt"]))
            if wort and ("[" + wort + "]") in p["inhalt"]:
                treffer = True
            if not treffer:
                return False
        return True

    treffer = [p for p in alle if passt(p)]
    treffer.sort(key=lambda p: str(p.get("erstellt") or p.get("datum") or ""),
                 reverse=(sortierung != "alt"))
    return treffer[:max(1, limit)], len(alle)


def ueberstimmen(db: Facts, index: int, entscheid: str,
                 begruendung: str) -> dict[str, Any]:
    """CEO überstimmt einen Beschluss der Sekretäre — nur mit Begründung."""
    if entscheid not in ("annehmen", "ablehnen", "vertagen"):
        raise ValueError("Unbekannter Entscheid")
    begruendung = (begruendung or "").strip()[:300]
    if not begruendung:
        raise ValueError("Begründung fehlt")
    s = sitzung(db)
    if s.get("status") != "laeuft":
        raise ValueError("Keine laufende Sitzung")
    t = next((x for x in (s.get("themen") or []) if x.get("index") == index), None)
    if t is None:
        raise ValueError("Unbekanntes Thema")
    if t.get("status") == "offen":
        raise ValueError("Thema ist noch nicht entschieden")
    vorher = t.get("ergebnis")
    if vorher == entscheid:
        raise ValueError("Der Beschluss lautet bereits so")

    korrektur = {"zeit": jetzt(), "vorher": vorher, "entscheid": entscheid,
                 "begruendung": begruendung}
    t["ueberstimmung"] = korrektur
    t["ergebnis"] = entscheid
    t["status"] = entscheid
    if entscheid == "vertagen":
        _vertagt_hinzufuegen(db, t)
    elif t.get("vertagt"):
        _vertagt_entfernen(db, t)
    for e in reversed(s.get("entscheide") or []):
        if e.get("index") != index:
            continue
        e["vorher"] = vorher
        e["entscheid"] = entscheid
        e["ueberstimmung"] = korrektur
        if entscheid == "annehmen" and (not e.get("mission") or e.get("mission_storniert")):
            try:
                e["mission"], e["abteilung"] = _mission_anlegen(db, t)
                e.pop("mission_storniert", None)
            except Exception as exc:
                e["mission_fehler"] = f"{type(exc).__name__}: {exc}"
        if vorher == "annehmen" and entscheid != "annehmen" and e.get("mission"):
            try:
                with db.conn() as c:
                    c.execute("UPDATE nexus_missionen SET status='storniert' WHERE kennung=?",
                              (e["mission"],))
                e["mission_storniert"] = True
            except Exception:
                pass
        break
    db.zustand_setzen("sekretariat_sitzung", s)
    return s


def sitzung_abschluss(db: Facts, vault: Vault | None = None) -> dict[str, Any]:
    """Schliesst die Sitzung; Ergebnis und Entscheide landen im Vault."""
    s = sitzung(db)
    if not s.get("themen"):
        raise ValueError("Keine Sitzung vorhanden")
    offen = [t for t in s["themen"] if t.get("status") == "offen"]
    zaehler = {"annehmen": 0, "ablehnen": 0, "vertagen": 0}
    for e in s.get("entscheide") or []:
        zaehler[e["entscheid"]] = zaehler.get(e["entscheid"], 0) + 1
    s["status"] = "beendet"
    s["abschluss"] = jetzt()
    s["ergebnis"] = {**zaehler, "offen": len(offen)}
    text = (f"**Angenommen:** {zaehler['annehmen']}  \n**Abgelehnt:** {zaehler['ablehnen']}  \n"
            f"**Vertagt:** {zaehler['vertagen']}  \n**Offen:** {len(offen)}  \n\n")
    for e in s.get("entscheide") or []:
        text += f"- [{e['entscheid']}] {e['thema']} (Leitung {e['leiter']})\n"
        if e.get("ueberstimmung"):
            u = e["ueberstimmung"]
            text += (f"  - CEO-Überstimmung: {u.get('vorher')} → {u.get('entscheid')}, "
                     f"Begründung: «{u.get('begruendung')}»\n")
        if e.get("mission_storniert"):
            text += f"  - Mission {e.get('mission')} storniert\n"
    if vault is not None:
        try:
            vault.notiz("konferenz", f"Sitzung {str(s['start'])[:16]}", text,
                        tags=["sitzung", "sekretariat"])
        except Exception:
            pass
    db.zustand_setzen("sekretariat_sitzung", s)
    return s


def vault_suche(vault: Vault, suche: str = "", limit: int = 50, von: str = "",
                bis: str = "", sortierung: str = "neu"
                ) -> tuple[list[dict[str, Any]], int]:
    """Durchsucht alle Kategorien des Vaults, nicht nur die Sitzungsprotokolle."""
    text = (suche or "").strip().lower()
    treffer: list[dict[str, Any]] = []
    for kategorie in (vault.zaehle() or {}):
        if kategorie == "index":
            continue
        for n in vault.notizen(kategorie, limit=500):
            inhalt = (n.get("text") or "").lstrip()
            if inhalt.startswith("---"):
                ende = inhalt.find("\n---", 3)
                if ende != -1:
                    inhalt = inhalt[ende + 4:]
            inhalt = inhalt.strip()
            titel = n.get("titel") or ""
            if text and text not in (titel + " " + inhalt).lower():
                continue
            m = re.search(r"(\d{4}-\d{2}-\d{2})", titel)
            datum = m.group(1) if m else str(n.get("erstellt") or "")[:10]
            if von and datum < von:
                continue
            if bis and datum > bis:
                continue
            treffer.append({"kategorie": kategorie, "titel": titel, "datum": datum,
                            "erstellt": n.get("erstellt"), "inhalt": inhalt[:1500]})
    treffer.sort(key=lambda p: str(p.get("erstellt") or p.get("datum") or ""),
                 reverse=(sortierung != "alt"))
    return treffer[:max(1, limit)], len(treffer)
