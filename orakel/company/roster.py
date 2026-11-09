"""Vollständiger 103er-Roster.

Die 80 bestehenden Rollen werden direkt aus `orakel.agents.ROSTER` gelesen,
damit Aufgaben und Handler nicht doppelt gepflegt werden. Die 20 neuen
Fachrollen (I/J) und die drei Sekretäre sind hier ausformuliert.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from .. import agents

ABTEILUNGEN = {
    "A": "Command Center",
    "B": "Spider Intelligence",
    "C": "Innovation Laboratory",
    "D": "Trading Floor",
    "E": "Research Department",
    "F": "Risk Management",
    "G": "Knowledge Center",
    "H": "Engineering Department",
    "I": "Global Intelligence Observatory",
    "J": "Security Operations",
    "S": "Executive Secretariat",
}

STATIONEN = {
    "A": "E6-01",
    "B": "E4-01",
    "C": "E5-01",
    "D": "E3-01",
    "E": "E5-02",
    "F": "E1-01",
    "G": "E0-01",
    "H": "E2-01",
    "I": "E6-03",
    "J": "E1-02",
    "S": "E7-03",
}

AVATARE = {
    "A": "analyst",
    "B": "analyst",
    "C": "analyst",
    "D": "trader",
    "E": "analyst",
    "F": "security",
    "G": "archivist",
    "H": "engineer",
    "I": "analyst",
    "J": "security",
    "S": "secretary",
}

# Individuelle Rufnamen. Die Reihenfolge entspricht der Reihenfolge in
# `agents.ROSTER`: pro Abteilung zehn Einträge.
NAMEN = {
    "A": ["Atlas", "Mara", "Sol", "Echo", "Vela", "Orion", "Nova", "Tessa", "Rune", "Lio"],
    "B": ["Lyra", "Falk", "Nia", "Silas", "Ines", "Argo", "Yara", "Emil", "Noor", "Juno"],
    "C": ["Ada", "Milo", "Thea", "Kenji", "Elin", "Pax", "Remy", "Sana", "Tao", "Vera"],
    "D": ["Luca", "Nils", "Amara", "Finn", "Ida", "Omar", "Leah", "Björn", "Sara", "Malik"],
    "E": ["Mira", "Jonas", "Anouk", "David", "Selin", "Paul", "Alina", "Hugo", "Ema", "Leo"],
    "F": ["Iris", "Karim", "Sina", "Tom", "Nadia", "Erik", "Zoe", "Amir", "Klara", "Boris"],
    "G": ["Edith", "Sami", "Ruth", "Noel", "Hana", "Miro", "Greta", "Ivo", "Leni", "Arne"],
    "H": ["Armin", "Nela", "Jari", "Selma", "Pius", "Anja", "Kuno", "Ravi", "Fine", "Oskar"],
    "I": ["Selina", "Marek", "Ayla", "Toni", "Chiara", "Dario", "Esra", "Luc", "Mai", "Sven"],
    "J": ["Helena", "Tarik", "Wen", "Liv", "Andor", "Nika", "Bo", "Sasha", "Elif", "Ron"],
}

STELLVERTRETUNGEN = {"A2", "B5", "C5", "D6", "E4", "F2", "G9", "H3", "I7", "J7"}

DATENSCOPE = {
    "A": ["tasks", "agent_runs", "config", "conference"],
    "B": ["artikel", "intel_inhalte", "intel_weiterleitungen", "vault"],
    "C": ["validierungen", "trades", "research", "vault"],
    "D": ["positionen", "trades", "entscheide", "konto"],
    "E": ["validierungen", "kerzen", "research", "vault"],
    "F": ["konto", "positionen", "risiko", "datenqualitaet"],
    "G": ["vault", "validierungen", "konferenzen"],
    "H": ["code", "config", "tests", "logs"],
    "I": ["kerzen", "artikel", "validierungen", "vault"],
    "J": ["auth_meta", "audit", "integrity", "config"],
    "S": ["profiles", "tasks", "conference", "reports"],
}


@dataclass(frozen=True, slots=True)
class Profile:
    agent_id: str
    rufname: str
    dept: str
    dept_name: str
    role: str
    rank: str
    mission: str
    station: str
    avatar: str
    autonomy: int
    reports_to: str
    backup: str
    handler: str
    data_scope: tuple[str, ...]
    tools: tuple[str, ...]
    memory_scope: str
    kpi: str


def _legacy_profile(kennung: str, abteilung: str, name: str, aufgabe: str) -> Profile:
    namensliste = NAMEN[abteilung]
    index = int(kennung[1:]) - 1
    rufname = namensliste[index]
    rang = "leitung" if index == 0 else ("stellvertretung" if kennung in STELLVERTRETUNGEN else "mitglied")
    chef = f"{abteilung}1"
    handler = agents._handler_fuer(kennung, aufgabe)
    return Profile(
        agent_id=kennung,
        rufname=rufname,
        dept=abteilung,
        dept_name=ABTEILUNGEN[abteilung],
        role=name,
        rank=rang,
        mission=aufgabe,
        station=STATIONEN[abteilung],
        avatar=AVATARE[abteilung] if rang != "leitung" else "director",
        autonomy=2 if rang == "leitung" else 1,
        reports_to="CEO" if rang == "leitung" else chef,
        backup=chef if rang == "stellvertretung" else "",
        handler=handler,
        data_scope=tuple(DATENSCOPE[abteilung]),
        tools=(f"legacy:{handler}",),
        memory_scope=f"vault/{abteilung}",
        kpi="Ergebnis mit Beleg; keine erfundenen Daten",
    )


NEUE_ROLLEN: list[tuple[str, str, str, str, str]] = [
    # (id, rufname, rolle, aufgabe, handler)
    ("I1", "Selina", "Observatory Director",
     "Globale Lage zusammenführen und Tagesbrief priorisieren", "observatory_director"),
    ("I2", "Marek", "FX- & Zinsanalyst",
     "EURUSD-/Zinsbezug aus Kursen und Artikeln prüfen", "fx_rates"),
    ("I3", "Ayla", "Aktien- & Indexanalyst",
     "Index- und Aktienkontext aus vorhandenen Symbolen bewerten", "equity_index"),
    ("I4", "Toni", "Rohstoff- & Energieanalyst",
     "Vorhandene Rohstoff-/Energiesymbole bewerten; sonst keine Daten", "commodities"),
    ("I5", "Chiara", "Kryptoanalyst",
     "Vorhandene Kryptosymbole bewerten; sonst keine Daten", "crypto"),
    ("I6", "Dario", "Geopolitik-Analyst",
     "Artikel regionenbezogen einordnen, ohne Spekulation", "geopolitics"),
    ("I7", "Esra", "Korrelations- & Contagion-Analyst",
     "Cross-Asset-Korrelationen aus vorhandenen Kerzen berechnen", "correlation"),
    ("I8", "Luc", "Regime- & Volatilitätsanalyst",
     "Globales Regime und ATR-Volatilität aus Kerzen beschreiben", "volatility"),
    ("I9", "Mai", "Signal-Fusions-Analyst",
     "Nur belegte Signale zusammenführen; keine Order erzeugen", "signal_fusion"),
    ("I10", "Sven", "Observatory-Archivar",
     "Tageslage mit Quellen im Vault-Index prüfen", "observatory_archive"),
    ("J1", "Helena", "Security Chief",
     "Security-Lage, Prioritäten und Vetos koordinieren", "security_chief"),
    ("J2", "Tarik", "Zugriffs- & Identitätsprüfer",
     "Auth-Konfiguration prüfen; keine Secrets anzeigen", "access_audit"),
    ("J3", "Wen", "Datenintegritäts-Prüfer",
     "Schema, Waisen, Dubletten und Zeitstempel prüfen", "data_integrity"),
    ("J4", "Liv", "Prompt-Injection- & Inhaltswächter",
     "Fremdinhalte auf Manipulationsversuche prüfen", "content_guard"),
    ("J5", "Andor", "Secret- & Abhängigkeitsprüfer",
     "Repo auf Secret-Dateien prüfen; Werte niemals ausgeben", "secret_audit"),
    ("J6", "Nika", "Incident-Responder",
     "Blockierte und fehlgeschlagene Tasks als Incidents prüfen", "incident_review"),
    ("J7", "Bo", "Audit-Trail-Prüfer",
     "Reihenfolge und Hash-Kette der Ereignisse prüfen", "event_chain"),
    ("J8", "Sasha", "Sandbox-Wächter",
     "Tool-Rechte prüfen; freie Shell und Fremdnetz blockieren", "tool_guard"),
    ("J9", "Elif", "Paper-Only-Enforcer",
     "Broker-/Order-Pfad auf Paper-Sperre prüfen; Veto", "paper_guard"),
    ("J10", "Ron", "Security-Archivar",
     "Security-Befunde redigiert dokumentieren", "security_archive"),
]

SEKRETAERE: list[tuple[str, str, str, str, str, str]] = [
    # (id, rufname, rolle, aufgabe, backup, reports_to)
    ("S1", "Elias", "Chief Executive Assistant",
     "Anfragen des CEO belegt beantworten und S2/S3 koordinieren", "S2", "CEO"),
    ("S2", "Clara", "Reporting Secretary",
     "Abteilungsberichte prüfen, verdichten und Tagesbrief erstellen", "S3", "S1"),
    ("S3", "Nora", "Executive Operations Secretary",
     "Aufgabenfluss, Blockaden und Übergaben der Abteilungen koordinieren", "S1", "S1"),
]


def _neue_profile() -> list[Profile]:
    profile: list[Profile] = []
    for kennung, rufname, rolle, aufgabe, handler in NEUE_ROLLEN:
        abteilung = kennung[0]
        rang = "leitung" if kennung.endswith("1") else (
            "stellvertretung" if kennung in STELLVERTRETUNGEN else "mitglied")
        profile.append(Profile(
            agent_id=kennung,
            rufname=rufname,
            dept=abteilung,
            dept_name=ABTEILUNGEN[abteilung],
            role=rolle,
            rank=rang,
            mission=aufgabe,
            station=STATIONEN[abteilung],
            avatar="director" if rang == "leitung" else AVATARE[abteilung],
            autonomy=2 if rang == "leitung" else 1,
            reports_to="CEO" if rang == "leitung" else f"{abteilung}1",
            backup=f"{abteilung}1" if rang == "stellvertretung" else "",
            handler=handler,
            data_scope=tuple(DATENSCOPE[abteilung]),
            tools=(f"company:{handler}",),
            memory_scope=f"vault/{abteilung}",
            kpi="Ergebnis mit Beleg; keine erfundenen Daten",
        ))
    return profile


def _sekretaere() -> list[Profile]:
    return [
        Profile(
            agent_id=kennung, rufname=rufname, dept="S",
            dept_name=ABTEILUNGEN["S"], role=rolle, rank="sekretariat",
            mission=aufgabe, station=STATIONEN["S"], avatar="secretary",
            autonomy=1, reports_to=reports_to, backup=backup,
            handler={
                "S1": "secretary_chief",
                "S2": "secretary_report",
                "S3": "secretary_ops",
            }[kennung],
            data_scope=tuple(DATENSCOPE["S"]),
            tools=("company:read", "company:message", "company:report"),
            memory_scope="vault/00-Index",
            kpi="Belegte, kurze und rechtzeitige Antwort",
        )
        for kennung, rufname, rolle, aufgabe, backup, reports_to in SEKRETAERE
    ]


@lru_cache(maxsize=1)
def all_profiles() -> tuple[Profile, ...]:
    legacy = [_legacy_profile(*eintrag) for eintrag in agents.ROSTER]
    profile = legacy + _neue_profile() + _sekretaere()
    return tuple(profile)


PROFILES: tuple[Profile, ...] = all_profiles()
PROFILE_BY_ID = {p.agent_id: p for p in PROFILES}


def profile_by_id(agent_id: str) -> Profile | None:
    return PROFILE_BY_ID.get(agent_id)


def validate_roster(profile: tuple[Profile, ...] | list[Profile] | None = None) -> list[str]:
    """Prüft die harten Strukturregeln und gibt eine Liste von Fehlern zurück."""
    profile = list(profile if profile is not None else PROFILES)
    fehler: list[str] = []
    if len(profile) != 103:
        fehler.append(f"Gesamtzahl {len(profile)} statt 103")
    fache = [p for p in profile if p.dept in "ABCDEFGHIJ"]
    if len(fache) != 100:
        fehler.append(f"Fachagenten {len(fache)} statt 100")
    pro_abteilung = Counter(p.dept for p in fache)
    for abteilung in "ABCDEFGHIJ":
        if pro_abteilung[abteilung] != 10:
            fehler.append(f"Abteilung {abteilung}: {pro_abteilung[abteilung]} statt 10")
    if len([p for p in profile if p.dept == "S"]) != 3:
        fehler.append("Sekretäre nicht 3")
    ids = [p.agent_id for p in profile]
    if len(ids) != len(set(ids)):
        fehler.append("Doppelte Agenten-IDs")
    namen = [p.rufname for p in profile]
    if len(namen) != len(set(namen)):
        fehler.append("Doppelte Rufnamen")
    for p in profile:
        if not p.mission.strip():
            fehler.append(f"{p.agent_id}: Aufgabe fehlt")
        if not p.station:
            fehler.append(f"{p.agent_id}: Station fehlt")
    return fehler
