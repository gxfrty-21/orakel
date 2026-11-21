#!/usr/bin/env python3
"""Baut und prüft das Review-Paket aus einem sauberen Commit.

Der Builder nimmt ausschliesslich Pfade aus ``scripts/review-paket-freigabe.json``
auf, liest sie über ``git show <commit>:<pfad>`` (nicht aus dem Arbeitsbaum),
schreibt die Kopien und prüft sie anschliessend byteweise per SHA-256. ZIP und
Manifest entstehen deterministisch (sortiert, feste mtime, Deflate 9). Jede
Abweichung — fremde Datei, fehlende Freigabe, Hash-Differenz, Manifest- oder
ZIP-Lücke — beendet den Lauf mit Exit-Code 1.

Aufrufe:
    python scripts/baue_review_paket.py            # Paket bauen und prüfen
    python scripts/baue_review_paket.py --pruefen  # nur prüfen (CI)

``--pytest-log PFAD`` übernimmt ein vorhandenes pytest-Protokoll (CI-Artefakt)
statt die Suite erneut zu starten; ``--pytest-exit-code PFAD`` nennt dazu die
Datei mit dem Exit-Code des Laufs, ``--junit PFAD`` bleibt die zweite Quelle.

``--pruefen`` prüft ein vorhandenes Paket gegen den Commit. Existiert noch kein
Paket (CI ohne ``artifacts/``), baut der Builder in ein temporäres Verzeichnis,
schreibt dort einen Bericht aus den gemessenen Werten und prüft Quellen, Hashes,
ZIP und diesen Bericht.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FREIGABE = os.path.join(WURZEL, 'scripts', 'review-paket-freigabe.json')
STANDARD_AUSGABE = os.path.join(WURZEL, 'artifacts', 'review-paket-orakel')
ZIP_NAME = 'ORAKEL-REVIEW-PAKET.zip'
MANIFEST_NAME = 'MANIFEST.json'
PROVENIENZ_NAME = 'PROVENIENZ.json'
FESTE_ZEIT = (2026, 11, 18, 0, 0, 0)
NEBEN_DATEIEN = {MANIFEST_NAME, PROVENIENZ_NAME, ZIP_NAME, ZIP_NAME + '.sha256'}
EVIDENZ_MD = 'EVIDENZ.md'
MUSTER_TESTZAHL = re.compile(r'(\d+)\s+passed')
MUSTER_ERGEBNIS = re.compile(r'(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)\b')
MUSTER_JUNIT = re.compile(r'<testsuite\b[^>]*\btests="(\d+)"')
MUSTER_EVIDENZ_HASH = re.compile(r'`((?:belege|dateien)/[^`]+)`\s*\(`([0-9a-f]{8,64})')
MUSTER_RUN = re.compile(r'/actions/runs/(\d+)')
# Lauf-IDs stehen in Berichten auch als Zahl ("CI-Lauf 123456789"), nicht nur
# als URL. Ab sechs Ziffern, damit Jahreszahlen und kurze Nummern auffallen.
MUSTER_RUN_NUMMER = re.compile(r'\b(?:CI-Lauf|Lauf(?:-ID)?|Run(?:-ID)?)[ \t:#]*(\d{6,})\b')
HAUPTDOKUMENT = 'ORAKEL-REVIEW-PAKET.md'
MAX_HAUPTDOKUMENT_ZEILEN = 200
API_BASIS = 'https://api.github.com'

# Nachweise, die der Generator selbst ausführt. Reihenfolge = Reihenfolge im Bericht.
PRUEFUNGEN = (
    ('pytest', ('-m', 'pytest', '-q', 'tests'), 'belege/evidenz-pytest.log'),
    ('doku', ('scripts/pruefe_doku.py',), 'belege/evidenz-doku.log'),
)


class Abweichung(Exception):
    """Freigabe-, Hash- oder Strukturabweichung; führt zu Exit-Code 1."""


def git(*args: str) -> bytes:
    r = subprocess.run(['git', '-c', 'safe.directory=*', '-C', WURZEL, *args], capture_output=True)  # noqa: S603, S607 - Programmaufruf mit fester Argumentliste, ohne Shell; Programmname und Argumente sind fest verdrahtet
    if r.returncode != 0:
        raise Abweichung(f'git {" ".join(args)} fehlgeschlagen: {r.stderr.decode(errors="replace").strip()}')
    return r.stdout


def sha256(daten: bytes) -> str:
    return hashlib.sha256(daten).hexdigest()


def sha256_datei(pfad: str) -> str:
    with open(pfad, 'rb') as f:
        return sha256(f.read())


def pruefe_pfad(pfad: str, art: str) -> str:
    """Weist absolute Pfade, ``..`` und Backslashes zurück."""
    if not pfad or pfad.startswith('/') or '\\' in pfad or '..' in pfad.split('/'):
        raise Abweichung(f'{art} {pfad!r} ist kein relativer Pfad ohne "..".')
    return pfad


def lade_freigabe() -> dict:
    try:
        daten = json.load(open(FREIGABE, encoding='utf-8'))
    except FileNotFoundError as fehler:
        raise Abweichung(f'Freigabeliste fehlt: {FREIGABE}') from fehler
    if daten.get('schema') != 'review-paket-freigabe.v1':
        raise Abweichung(f'Unbekanntes Freigabe-Schema: {daten.get("schema")!r}')
    quellen = daten.get('quellen') or []
    if not quellen:
        raise Abweichung('Freigabeliste enthält keine Quellen.')
    ziele, urspruenge = set(), set()
    for eintrag in quellen:
        quelle = pruefe_pfad(eintrag.get('quelle', ''), 'Quelle')
        ziel = pruefe_pfad(eintrag.get('ziel', ''), 'Ziel')
        if not ziel.startswith('dateien/'):
            raise Abweichung(f'Ziel {ziel!r} muss unter dateien/ liegen.')
        if ziel in ziele:
            raise Abweichung(f'Ziel {ziel!r} ist doppelt freigegeben.')
        if quelle in urspruenge:
            raise Abweichung(f'Quelle {quelle!r} ist doppelt freigegeben.')
        ziele.add(ziel)
        urspruenge.add(quelle)
    for name in daten.get('dokumente') or []:
        pruefe_pfad(name, 'Dokument')
    for name in daten.get('belege') or []:
        if not pruefe_pfad(name, 'Beleg').startswith('belege/'):
            raise Abweichung(f'Beleg {name!r} muss unter belege/ liegen.')
    return daten


def pruefe_commit(commit: str) -> tuple[str, str]:
    kopf = git('rev-parse', 'HEAD').decode().strip()
    gewaehlt = git('rev-parse', f'{commit}^{{commit}}').decode().strip()
    if gewaehlt != kopf:
        raise Abweichung(f'Commit {gewaehlt[:7]} ist nicht HEAD ({kopf[:7]}); '
                         'das Paket darf nur den geprüften Stand abbilden.')
    schmutzig = git('status', '--porcelain', '--untracked-files=no').decode().strip()
    if schmutzig:
        raise Abweichung('Arbeitsbaum ist nicht sauber:\n' + schmutzig)
    return gewaehlt, git('rev-parse', '--abbrev-ref', 'HEAD').decode().strip()


def quell_eintraege(freigabe: dict, commit: str) -> list[dict]:
    eintraege = []
    for eintrag in freigabe['quellen']:
        daten = git('show', f'{commit}:{eintrag["quelle"]}')
        eintraege.append({
            'target': eintrag['ziel'],
            'source': eintrag['quelle'],
            'sha256': sha256(daten),
            'bytes': len(daten),
            'daten': daten,
            'herkunft': 'commit',
        })
    return eintraege


def beleg_eintraege(freigabe: dict, ausgabe: str) -> list[dict]:
    eintraege, fehlend = [], []
    for name in (freigabe.get('belege') or []) + (freigabe.get('dokumente') or []):
        pfad = os.path.join(ausgabe, name)
        if not os.path.exists(pfad):
            fehlend.append(name)
            continue
        eintraege.append({
            'target': name,
            'sha256': sha256_datei(pfad),
            'bytes': os.path.getsize(pfad),
            'herkunft': 'beleg' if name.startswith('belege/') else 'paketdokument',
        })
    if fehlend:
        print('Hinweis: nicht vorhanden und daher nicht im Paket: '
              + ', '.join(sorted(fehlend)), file=sys.stderr)
    return eintraege


def schreibe_kopien(eintraege: list[dict], ausgabe: str) -> None:
    for e in eintraege:
        pfad = os.path.join(ausgabe, e['target'])
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, 'wb') as f:
            f.write(e['daten'])
        kopie = sha256_datei(pfad)
        if kopie != e['sha256']:
            raise Abweichung(f'Kopie {e["target"]} weicht nach dem Schreiben ab '
                             f'({kopie[:12]} != {e["sha256"][:12]}).')


def pruefe_kopien(eintraege: list[dict], ausgabe: str) -> None:
    fehlend, abweichend = [], []
    for e in eintraege:
        pfad = os.path.join(ausgabe, e['target'])
        if not os.path.exists(pfad):
            fehlend.append(e['target'])
        elif sha256_datei(pfad) != e['sha256']:
            abweichend.append(e['target'])
    if fehlend:
        raise Abweichung('Kopien fehlen: ' + ', '.join(sorted(fehlend)[:8]))
    if abweichend:
        raise Abweichung('Kopien weichen vom Commit ab: ' + ', '.join(sorted(abweichend)[:8]))


def pruefe_unerlaubte_dateien(freigabe: dict, ausgabe: str) -> None:
    erlaubt = {e['ziel'] for e in freigabe['quellen']}
    erlaubt |= set(freigabe.get('belege') or [])
    erlaubt |= set(freigabe.get('dokumente') or [])
    unerlaubt = []
    for wurzel, _, dateien in os.walk(ausgabe):
        for name in dateien:
            relativ = os.path.relpath(os.path.join(wurzel, name), ausgabe).replace(os.sep, '/')
            if relativ in NEBEN_DATEIEN:
                continue
            if relativ.startswith('ORAKEL-REVIEW-PAKET-') and relativ.endswith('.zip'):
                continue  # gesicherte Vorgängerpakete
            if relativ not in erlaubt:
                unerlaubt.append(relativ)
    if unerlaubt:
        raise Abweichung('Nicht freigegebene Dateien im Paket: ' + ', '.join(sorted(unerlaubt)[:8]))


def schreibe_manifest(eintraege: list[dict], ausgabe: str, commit: str, branch: str,
                      freigabe: dict, evidenz: dict | None = None,
                      ci: dict | None = None) -> None:
    status = {
        'commit': 'geprüfte Quelle aus dem Commit',
        'beleg': 'Belegprotokoll im Paket',
        'paketdokument': 'Paketdokument im Paket',
    }
    liste = [{
        'target': e['target'],
        'sha256': e['sha256'],
        'bytes': e['bytes'],
        'herkunft': e['herkunft'],
        'status': status.get(e['herkunft'], e['herkunft']),
        **({'source': e['source'], 'commit': commit} if e['herkunft'] == 'commit' else {}),
    } for e in sorted(eintraege, key=lambda x: x['target'])]
    pruefungen = []
    evidenz_pfad = os.path.join(ausgabe, 'EVIDENZ.json')
    if os.path.exists(evidenz_pfad):
        for eintrag in json.load(open(evidenz_pfad, encoding='utf-8')).get('dateien', []):
            pruefungen.append({
                'name': eintrag['name'],
                'befehl': eintrag['befehl'],
                'exit_code': eintrag['exit_code'],
                'ergebnis': eintrag.get('log', ''),
                'log': eintrag['target'],
                'log_sha256': eintrag['sha256'],
            })
    gruppen = []
    for gruppe in freigabe.get('gruppen') or []:
        passend = [e for e in eintraege if e['target'].startswith(gruppe['praefix'])]
        gruppen.append({
            'name': gruppe['name'],
            'praefix': gruppe['praefix'],
            'zweck': gruppe['zweck'],
            'dateien': len(passend),
            'bytes': sum(e['bytes'] for e in passend),
        })
    manifest = {
        'schema': 'review-paket.v6',
        'commit': commit,
        'branch': branch,
        'dirty': False,
        'arbeitsbaum': 'sauber',
        'freigabe': 'scripts/review-paket-freigabe.json',
        'builder': 'scripts/baue_review_paket.py',
        'generated_at': '2026-11-18T00:00:00Z',
        'quellgruppen': gruppen,
        'testzahl': (evidenz or {}).get('testzahl'),
        'ci': ci,
        'pruefungen': sorted(pruefungen, key=lambda p: p['name']),
        'files': liste,
    }
    with open(os.path.join(ausgabe, MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')


def umgebung() -> dict:
    """Python- und Node-Fassung des Baus; nur zur Nachvollziehbarkeit."""
    node = 'nicht verfügbar'
    # Voller Pfad zum Programm, damit kein Eintrag aus PATH aufgelöst wird (S607).
    knoten = shutil.which('node')
    if knoten:
        try:
            r = subprocess.run([knoten, '--version'],  # noqa: S603 - Programmpfad vorher per shutil.which ermittelt, Argument fest
                               capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                node = r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {'python': sys.version.split()[0], 'node': node}


def datei_eintrag(ausgabe: str, name: str) -> dict:
    """Manifest-Eintrag für eine Datei, die im Paketordner liegt."""
    pfad = os.path.join(ausgabe, name)
    return {'target': name, 'sha256': sha256_datei(pfad),
            'bytes': os.path.getsize(pfad), 'herkunft': 'paketdokument'}


def schreibe_provenienz(eintraege: list[dict], ausgabe: str, commit: str,
                        branch: str, eintraege_im_zip: int) -> None:
    """Schreibt PROVENIENZ.json in das Paket.

    Der ZIP-Hash kann nicht in der Datei stehen, die im ZIP liegt (Zirkel).
    Er steht deshalb ausschliesslich in ``ORAKEL-REVIEW-PAKET.zip.sha256``;
    ``zip.sha256`` verweist darauf.
    """
    provenienz = {
        'schema': 'review-paket-provenienz.v4',
        'commit': commit,
        'branch': branch,
        'dirty': False,
        'arbeitsbaum': 'sauber',
        'builder': 'scripts/baue_review_paket.py',
        'freigabe': 'scripts/review-paket-freigabe.json',
        'generated_at': '2026-11-18T00:00:00Z',
        'umgebung': umgebung(),
        'zip': {
            'name': ZIP_NAME,
            'sha256': None,
            'sha256_datei': ZIP_NAME + '.sha256',
            'eintraege': eintraege_im_zip,
            'deterministisch': True,
        },
        'reproduktion': {
            'bau': 'python scripts/baue_review_paket.py --commit %s' % commit,
            'pruefung': 'python scripts/baue_review_paket.py --pruefen',
        },
        'quellen': [{'source': e['source'], 'target': e['target'], 'commit': commit}
                    for e in sorted(eintraege, key=lambda x: x['target'])
                    if e['herkunft'] == 'commit'],
        'belege': [{'target': e['target'], 'sha256': e['sha256'], 'herkunft': e['herkunft']}
                   for e in sorted(eintraege, key=lambda x: x['target'])
                   if e['herkunft'] == 'beleg'],
        'dateien': [{'target': e['target'], 'sha256': e['sha256'], 'bytes': e['bytes'],
                     'herkunft': e['herkunft']}
                    for e in sorted(eintraege, key=lambda x: x['target'])],
    }
    with open(os.path.join(ausgabe, PROVENIENZ_NAME), 'w', encoding='utf-8') as f:
        json.dump(provenienz, f, ensure_ascii=False, indent=2)
        f.write('\n')


VERBOTEN = ('.env', '.db', '.sqlite', '.sqlite3', '.pem', '.key', 'id_rsa')


def pruefe_evidenz(ausgabe: str, commit: str) -> None:
    """EVIDENZ.json muss denselben Commit nennen wie das Paket."""
    pfad = os.path.join(ausgabe, 'EVIDENZ.json')
    if not os.path.exists(pfad):
        raise Abweichung('EVIDENZ.json fehlt im Paketordner.')
    daten = json.load(open(pfad, encoding='utf-8'))
    quelle = (daten.get('quelle') or {})
    genannt = str(quelle.get('commit', ''))
    if not genannt:
        raise Abweichung('EVIDENZ.json nennt keinen Quellcommit.')
    if not commit.startswith(genannt) and genannt != commit:
        raise Abweichung(f'EVIDENZ.json nennt Commit {genannt[:7]} statt {commit[:7]}.')
    if quelle.get('dirty') is not False:
        raise Abweichung('EVIDENZ.json weist den Arbeitsbaum nicht als sauber aus.')
    pytest_eintraege = [e for e in daten.get('dateien') or [] if e.get('name') == 'pytest']
    if not pytest_eintraege:
        raise Abweichung('EVIDENZ.json enthält keinen pytest-Nachweis.')
    for eintrag in pytest_eintraege:
        log_pfad = os.path.join(ausgabe, eintrag['target'])
        if not os.path.exists(log_pfad):
            raise Abweichung(f'pytest-Protokoll fehlt: {eintrag["target"]}')
        ergebnis = ergebnis_aus_log(open(log_pfad, encoding='utf-8').read()) or {}
        gemessen = ergebnis.get('passed')
        if gemessen is None:
            raise Abweichung(f'pytest-Protokoll {eintrag["target"]} enthält keine Zeile '
                             '"N passed".')
        if gemessen != daten.get('testzahl'):
            raise Abweichung(f'EVIDENZ.json nennt {daten.get("testzahl")} Tests, das '
                             f'Protokoll misst {gemessen}.')
        if 'uebersprungen' in daten and ergebnis.get('skipped', 0) != daten['uebersprungen']:
            raise Abweichung(f'EVIDENZ.json nennt {daten["uebersprungen"]} übersprungene '
                             f'Tests, das Protokoll {ergebnis.get("skipped", 0)}.')


def letzte_zeile(text: str) -> str:
    """Letzte nicht leere Zeile eines Protokolls (die Ergebniszeile)."""
    zeilen = [z.strip() for z in text.splitlines() if z.strip()]
    return zeilen[-1] if zeilen else ''


def testzahl_aus_log(text: str) -> int | None:
    """Liest die Testzahl aus der pytest-Schlusszeile (``402 passed``)."""
    treffer = MUSTER_TESTZAHL.findall(text)
    return int(treffer[-1]) if treffer else None


def ergebnis_aus_log(text: str) -> dict[str, int] | None:
    """Zählt alle Zustände der pytest-Schlusszeile (``417 passed, 2 skipped``).

    ``skipped`` gehört zur Gesamtzahl der Tests, nicht zu den bestandenen;
    ``failed``, ``errors`` und ``xfailed`` sind Abbruchgründe.
    """
    zahlen: dict[str, int] = {}
    for zahl, zustand in MUSTER_ERGEBNIS.findall(letzte_zeile(text)):
        if zustand == 'error':
            zustand = 'errors'
        zahlen[zustand] = zahlen.get(zustand, 0) + int(zahl)
    return zahlen or None


def testzahl_aus_junit(pfad: str) -> int:
    """Summiert die ``tests``-Angaben eines JUnit-XML (eine Quelle, kein Raten)."""
    try:
        text = open(pfad, encoding='utf-8').read()
    except FileNotFoundError as fehler:
        raise Abweichung(f'JUnit-Bericht fehlt: {pfad}') from fehler
    zahlen = [int(n) for n in MUSTER_JUNIT.findall(text)]
    if not zahlen:
        raise Abweichung(f'JUnit-Bericht ohne tests-Angabe: {pfad}')
    return sum(zahlen)


def befehl_text(argv: tuple[str, ...]) -> str:
    """Befehl für die Doku, ohne absoluten Interpreterpfad."""
    return 'python ' + ' '.join(argv)


def _lies(pfad: str, was: str) -> str:
    """Liest eine vorhandene Evidenzdatei oder bricht mit klarem Befund ab."""
    try:
        return open(pfad, encoding='utf-8').read()
    except OSError as fehler:
        raise Abweichung(f'{was} fehlt oder ist nicht lesbar: {pfad}') from fehler


def _exit_code_aus_datei(pfad: str | None) -> int:
    """Exit-Code des übernommenen Laufs; ohne Datei gibt es keinen Nachweis."""
    if not pfad:
        raise Abweichung('--pytest-log braucht --pytest-exit-code mit dem Exit-Code '
                         'des Laufs.')
    inhalt = _lies(pfad, 'Exit-Code-Datei').strip()
    try:
        return int(inhalt)
    except ValueError as fehler:
        raise Abweichung(f'Exit-Code-Datei {pfad} enthält keine Zahl: {inhalt!r}') from fehler


PYTEST_ARTEFAKT_BEFEHL = 'python -m pytest -q tests --junitxml=artifacts/pytest/junit.xml'


def fuehre_evidenz_aus(ausgabe: str, commit: str, branch: str,
                       junit: str | None = None,
                       pytest_log: str | None = None,
                       pytest_exit_code: str | None = None) -> dict:
    """Führt die Nachweise aus und schreibt Protokolle, EVIDENZ.json und EVIDENZ.md.

    Die Testzahl stammt aus dem Protokoll bzw. dem JUnit-Bericht; sie wird nirgends
    von Hand eingetragen. Mit ``pytest_log`` wird ein vorhandenes Protokoll aus dem
    CI-Job übernommen, statt die Suite erneut zu starten; der Exit-Code kommt dann
    aus ``pytest_exit_code``. Schlägt ein Nachweis fehl oder widersprechen sich Log
    und JUnit-Bericht, bricht der Bau ab.
    """
    dateien, protokolle = [], {}
    for name, argv, ziel in PRUEFUNGEN:
        if name == 'pytest' and pytest_log:
            text = _lies(pytest_log, 'pytest-Protokoll')
            exit_code = _exit_code_aus_datei(pytest_exit_code)
            befehl = PYTEST_ARTEFAKT_BEFEHL
            herkunft = 'Job pytest (Artefakt)'
        else:
            lauf = subprocess.run([sys.executable, *argv], cwd=WURZEL,  # noqa: S603 - argv stammt aus der Konstante PRUEFUNGEN, nie aus Eingaben
                                  capture_output=True, text=True)
            text = lauf.stdout + lauf.stderr
            exit_code = lauf.returncode
            befehl = befehl_text(argv)
            herkunft = 'lokaler Lauf'
        pfad = os.path.join(ausgabe, ziel)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write(text)
        dateien.append({
            'name': name,
            'target': ziel,
            'commit': commit,
            'befehl': befehl,
            'herkunft': herkunft,
            'exit_code': exit_code,
            'sha256': sha256_datei(pfad),
            'bytes': os.path.getsize(pfad),
            'log': letzte_zeile(text),
        })
        protokolle[name] = text
    dateien.append(_strategie_nachweis(ausgabe, commit))
    pytest_eintrag = next(d for d in dateien if d['name'] == 'pytest')
    protokoll = protokolle['pytest']
    ergebnis = ergebnis_aus_log(protokoll)
    if not ergebnis or 'passed' not in ergebnis:
        raise Abweichung('pytest-Protokoll enthält keine Zeile "N passed".')
    for zustand in ('failed', 'errors', 'xfailed'):
        if ergebnis.get(zustand):
            raise Abweichung(f'pytest meldet {ergebnis[zustand]} {zustand}; ein Nachweis '
                             'zählt nur ohne fehlgeschlagene oder erwartet '
                             'fehlschlagende Tests.')
    bestanden = ergebnis['passed']
    uebersprungen = ergebnis.get('skipped', 0)
    gesamt = bestanden + uebersprungen
    if junit:
        aus_junit = testzahl_aus_junit(junit)
        if aus_junit != gesamt:
            raise Abweichung(f'JUnit-Bericht nennt {aus_junit} Tests, Protokoll und Skips '
                             f'ergeben {gesamt} (passed + skipped).')
    if pytest_eintrag['exit_code'] != 0:
        raise Abweichung(f'pytest endete mit Exit {pytest_eintrag["exit_code"]}: '
                         f'{pytest_eintrag["log"]}')
    evidenz = {
        'schema': 'review-paket-evidenz.v3',
        'generated_at': '2026-11-19T00:00:00Z',
        'quelle': {'commit': commit, 'branch': branch, 'dirty': False},
        'umgebung': umgebung(),
        'testzahl': bestanden,
        'uebersprungen': uebersprungen,
        'gesamt': gesamt,
        'dateien': dateien,
    }
    with open(os.path.join(ausgabe, 'EVIDENZ.json'), 'w', encoding='utf-8') as f:
        json.dump(evidenz, f, ensure_ascii=False, indent=2)
        f.write('\n')
    with open(os.path.join(ausgabe, EVIDENZ_MD), 'w', encoding='utf-8') as f:
        f.write(rendere_evidenz_md(evidenz))
    return evidenz


def _strategie_nachweis(ausgabe: str, commit: str) -> dict:
    """Erzeugt den Strategie-Bericht als Teil der Evidenz (Kopie der Seed-Datenbank)."""
    seed = os.path.join(WURZEL, 'seed', 'orakel-seed.db')
    if not os.path.exists(seed):
        raise Abweichung('seed/orakel-seed.db fehlt — Strategie-Bericht nicht erzeugbar.')
    ziel = os.path.join(ausgabe, 'belege')
    os.makedirs(ziel, exist_ok=True)
    log_pfad = os.path.join(ziel, 'evidenz-strategie.log')
    with tempfile.TemporaryDirectory(prefix='strategie-') as temp:
        quelle = os.path.join(temp, 'quelle.db')
        shutil.copyfile(seed, quelle)
        lauf = subprocess.run([sys.executable, '-m', 'orakel', 'strategie-bericht',  # noqa: S603 - fester Programmaufruf ohne Shell
                               '--db', quelle,
                               '--quelle', 'seed/orakel-seed.db (Simulation, keine Marktaussage)',
                               '--ausgabe', ziel],
                              cwd=WURZEL, capture_output=True, text=True)
    text = lauf.stdout + lauf.stderr
    with open(log_pfad, 'w', encoding='utf-8') as f:
        f.write(text)
    if lauf.returncode != 0:
        raise Abweichung(f'Strategie-Bericht endete mit Exit {lauf.returncode}: '
                         f'{letzte_zeile(text)}')
    return {
        'name': 'strategie',
        'target': 'belege/evidenz-strategie.log',
        'commit': commit,
        'befehl': 'python -m orakel strategie-bericht --db seed/orakel-seed.db '
                  '--ausgabe belege',
        'exit_code': lauf.returncode,
        'sha256': sha256_datei(log_pfad),
        'bytes': os.path.getsize(log_pfad),
        'log': next((z.strip() for z in text.splitlines()
                     if z.strip().startswith('Strategie-Bericht:')), letzte_zeile(text)),
    }


def rendere_evidenz_md(evidenz: dict) -> str:
    """Erzeugt EVIDENZ.md ausschliesslich aus EVIDENZ.json (eine Quelle)."""
    quelle = evidenz['quelle']
    zeilen = [
        '# Evidenz',
        '',
        f"Alle Nachweise beziehen sich auf Commit `{quelle['commit']}` "
        f"(Branch `{quelle['branch']}`, Arbeitsbaum sauber, `dirty: false`). "
        'Zahlen und Hashes dieser Datei stammen aus den Protokollen und den Dateien '
        'selbst; der Generator bricht ab, sobald eine Angabe davon abweicht.',
        '',
        *herkunft_zeilen(evidenz),
        '',
        f"Gemessene Testzahl: **{evidenz['testzahl']}** (`pytest`).",
        *uebersprungene_zeilen(evidenz),
        '',
        '| Nachweis | Befehl | Exit | Ergebniszeile | Protokoll (SHA-256) |',
        '|---|---|---:|---|---|',
    ]
    for eintrag in evidenz['dateien']:
        zeilen.append(f"| {eintrag['name']} | `{eintrag['befehl']}` | {eintrag['exit_code']} | "
                      f"{eintrag['log']} | `{eintrag['target']}` (`{eintrag['sha256'][:16]}…`) |")
    zeilen += [
        '',
        '## Nachvollziehen',
        '',
        '```bash',
    ]
    zeilen += [eintrag['befehl'] for eintrag in evidenz['dateien']]
    zeilen += [
        '```',
        '',
        'Die Protokolle liegen unter `belege/` im Paket; ihre SHA-256 stehen in der '
        'Tabelle und in `MANIFEST.json`.',
        '',
    ]
    return '\n'.join(zeilen)


def uebersprungene_zeilen(evidenz: dict) -> list[str]:
    """Weist übersprungene Tests aus, statt sie als bestanden mitzuzählen."""
    anzahl = evidenz.get('uebersprungen') or 0
    if not anzahl:
        return []
    return ['', f"Übersprungen: **{anzahl}** Tests; sie zählen zur Gesamtzahl "
                f"{evidenz.get('gesamt', evidenz['testzahl'] + anzahl)}, nicht zu den "
                'bestandenen.']


def herkunft_zeilen(evidenz: dict) -> list[str]:
    """Nennt übernommene Nachweise, damit kein fremder Lauf als eigener gilt."""
    fremd = [e for e in evidenz['dateien'] if e.get('herkunft') != 'lokaler Lauf']
    if not fremd:
        return []
    return ['Übernommen: ' + ', '.join(
        f"{e['name']} aus {e.get('herkunft', 'unbekannt')} (`{e['befehl']}`)"
        for e in fremd) + '. Die übrigen Nachweise hat der Generator lokal erzeugt.', '']


def repo_slug() -> str:
    """``owner/name`` aus der CI-Umgebung oder der Origin-URL."""
    aus_ci = os.environ.get('GITHUB_REPOSITORY')
    if aus_ci:
        return aus_ci
    url = git('remote', 'get-url', 'origin').decode().strip()
    treffer = re.search(r'[:/]([^/:]+/[^/]+?)(?:\.git)?$', url)
    if not treffer:
        raise Abweichung(f'Origin-URL nicht lesbar: {url}')
    return treffer.group(1)


def _http_json(url: str) -> dict:
    """Liest JSON über HTTPS; Token aus ``GITHUB_TOKEN``/``GH_TOKEN``, wenn gesetzt."""
    teile = urllib.parse.urlsplit(url)
    if teile.scheme != 'https' or f'{teile.scheme}://{teile.netloc}' != API_BASIS:
        raise Abweichung(f'Unerwartete API-Adresse: {url} — erlaubt ist nur {API_BASIS}.')
    kopf = {'Accept': 'application/vnd.github+json',
            'User-Agent': 'orakel-review-paket'}
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if token:
        kopf['Authorization'] = f'Bearer {token}'
    anfrage = urllib.request.Request(url, headers=kopf)  # noqa: S310 - Schema und Host sind oben auf API_BASIS geprüft
    with urllib.request.urlopen(anfrage, timeout=20) as antwort:  # noqa: S310 - dito: nur HTTPS auf API_BASIS
        return json.loads(antwort.read().decode('utf-8'))


def ci_lauf(run_id: str) -> dict:
    """Fragt Lauf-ID, Head-Commit und Ergebnis direkt über HTTPS ab.

    Bewusst ohne ``gh``: Der Check läuft damit auch dort, wo das CLI fehlt.
    Ist die API nicht erreichbar, bricht der Lauf ab, statt den Nachweis
    stillschweigend zu überspringen.
    """
    try:
        lauf_id = int(run_id)
    except (TypeError, ValueError) as fehler:
        raise Abweichung(f'CI-Lauf {run_id!r} ist keine Zahl.') from fehler
    url = f'{API_BASIS}/repos/{repo_slug()}/actions/runs/{lauf_id}'
    try:
        daten = _http_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as fehler:
        raise Abweichung(f'CI-Lauf {lauf_id} nicht abrufbar ({url}): {fehler}') from fehler
    if not daten.get('head_sha'):
        raise Abweichung(f'CI-Lauf {lauf_id} nennt keinen Head-Commit.')
    return {'run_id': lauf_id, 'head_sha': daten['head_sha'],
            'conclusion': daten.get('conclusion'), 'event': daten.get('event')}


def ci_lauf_ids(text: str) -> set[str]:
    """Sammelt CI-Lauf-IDs in URL- und Zahlenform ("CI-Lauf 123456789")."""
    return set(MUSTER_RUN.findall(text)) | set(MUSTER_RUN_NUMMER.findall(text))


def pruefe_konsistenz(ausgabe: str, commit: str, evidenz: dict | None,
                      quellen: dict[str, str] | None = None,
                      lauf=None) -> None:
    """Prüft Doku und Manifest gegen die Quellen: Hashes, Testzahl, CI-Lauf-IDs.

    ``quellen`` bildet Zielpfade auf den frisch aus dem Commit gelesenen
    SHA-256 ab. Damit werden auch Quellhashes geprüft, die in ``MANIFEST.json``
    oder in der Doku stehen — nicht nur die Protokolle aus ``EVIDENZ.json``.
    CI-Lauf-IDs werden über HTTPS geprüft, ohne ``gh``; ``lauf`` ersetzt den
    Abruf in Tests. Läuft nach jedem Bau und bei ``--pruefen``;
    jede Abweichung beendet den Lauf.
    """
    lauf = lauf or ci_lauf
    soll: dict[str, str] = {}
    manifest_pfad = os.path.join(ausgabe, MANIFEST_NAME)
    if os.path.exists(manifest_pfad):
        manifest = json.load(open(manifest_pfad, encoding='utf-8'))
        for eintrag in manifest.get('files', []):
            soll[eintrag['target']] = eintrag['sha256']
    if evidenz:
        for eintrag in evidenz['dateien']:
            soll.setdefault(eintrag['target'], eintrag['sha256'])
    for ziel, echt in (quellen or {}).items():
        if ziel in soll and soll[ziel] != echt:
            raise Abweichung(f'Manifest-Hash für {ziel} passt nicht zur Quelle im Commit '
                             f'{commit[:7]}.')
        soll[ziel] = echt
        kopie = os.path.join(ausgabe, ziel)
        if os.path.exists(kopie) and sha256_datei(kopie) != echt:
            raise Abweichung(f'Kopie {ziel} weicht von der Quelle im Commit ab.')
    md_pfade = [os.path.join(ausgabe, n) for n in sorted(os.listdir(ausgabe))
                if n.endswith('.md') and os.path.isfile(os.path.join(ausgabe, n))]
    for pfad in md_pfade:
        text = open(pfad, encoding='utf-8').read()
        name = os.path.basename(pfad)
        for ziel, praefix in MUSTER_EVIDENZ_HASH.findall(text):
            echt = soll.get(ziel)
            if echt is None:
                raise Abweichung(f'{name} nennt Hash zu unbekannter Datei {ziel!r}.')
            if not echt.startswith(praefix):
                raise Abweichung(f'{name}: Hash {praefix}… passt nicht zu {ziel} ({echt[:16]}…).')
        if evidenz:
            for zahl in MUSTER_TESTZAHL.findall(text):
                if int(zahl) != evidenz['testzahl']:
                    raise Abweichung(f'{name} nennt {zahl} passed, gemessen sind '
                                     f'{evidenz["testzahl"]}.')
        for run_id in sorted(ci_lauf_ids(text)):
            ergebnis = lauf(run_id)
            if ergebnis['head_sha'] != commit:
                raise Abweichung(f'{name} nennt CI-Lauf {run_id} auf '
                                 f'{ergebnis["head_sha"][:7]}, Paket-Commit ist {commit[:7]}.')


def schreibe_pruefbericht(ausgabe: str, commit: str, branch: str,
                          eintraege: list[dict], evidenz: dict | None,
                          ci: dict | None = None) -> str:
    """Schreibt einen kurzen Bericht ausschliesslich aus gemessenen Werten.

    Im CI gibt es kein ``artifacts/``-Verzeichnis mit Paketdokumenten; ohne
    Dokument hätte ``pruefe_konsistenz`` nichts zu prüfen. Der Bericht nennt
    nur Werte aus MANIFEST/EVIDENZ und dem geprüften CI-Lauf, damit die
    Konsistenzprüfung auch dort echte Angaben prüft. Gibt den Pfad zurück.
    """
    quellen = [e for e in eintraege if e.get('herkunft') == 'commit']
    belege = [e for e in eintraege if e.get('herkunft') == 'beleg']
    zeilen = [
        '# Prüfbericht des Review-Pakets', '',
        f'Commit: `{commit}` (Branch `{branch}`), Paketdateien: {len(eintraege)} '
        f'({len(quellen)} Quellen, {len(belege)} Belege).', '',
        '## Gemessene Nachweise', '',
    ]
    if evidenz:
        zeilen.append(f'- Testzahl: {evidenz["testzahl"]} passed.')
        for eintrag in evidenz.get('dateien', []):
            zeilen.append(f'- Beleg `{eintrag["target"]}` (`{eintrag["sha256"][:16]}`).')
    if ci:
        zeilen.append(f'- CI: https://github.com/{repo_slug()}/actions/runs/'
                      f'{ci["run_id"]} ({ci.get("conclusion") or "offen"}).')
    zeilen += ['', '## Quellen (Auszug)', '']
    for eintrag in sorted(quellen, key=lambda e: e['target'])[:10]:
        zeilen.append(f'- `{eintrag["target"]}` (`{eintrag["sha256"][:16]}`).')
    zeilen += ['', 'Alle Angaben stammen aus MANIFEST.json und EVIDENZ.json; '
               'der Bericht enthält keine Schätzungen.', '']
    pfad = os.path.join(ausgabe, HAUPTDOKUMENT)
    with open(pfad, 'w', encoding='utf-8') as f:
        f.write('\n'.join(zeilen))
    return pfad


def pruefe_hauptdokument(ausgabe: str) -> None:
    """Das Hauptdokument bleibt lesbar: höchstens 200 Zeilen."""
    pfad = os.path.join(ausgabe, HAUPTDOKUMENT)
    if not os.path.exists(pfad):
        return
    with open(pfad, encoding='utf-8') as f:
        zeilen = sum(1 for _ in f)
    if zeilen > MAX_HAUPTDOKUMENT_ZEILEN:
        raise Abweichung(f'{HAUPTDOKUMENT} hat {zeilen} Zeilen; erlaubt sind höchstens '
                         f'{MAX_HAUPTDOKUMENT_ZEILEN}.')
    print(f'Hauptdokument: {zeilen} Zeilen (Grenze {MAX_HAUPTDOKUMENT_ZEILEN}).')


def pruefe_evidenz_dateien(ausgabe: str, evidenz: dict) -> None:
    """Jede in EVIDENZ.json genannte Datei muss byteweise unverändert sein."""
    for eintrag in evidenz['dateien']:
        pfad = os.path.join(ausgabe, eintrag['target'])
        if not os.path.exists(pfad):
            raise Abweichung(f'Evidenz-Datei fehlt: {eintrag["target"]}')
        if sha256_datei(pfad) != eintrag['sha256']:
            raise Abweichung(f'Evidenz-Datei {eintrag["target"]} wurde nach dem Schreiben '
                             'verändert.')


def pruefe_verbotene_inhalte(zip_pfad: str) -> None:
    """Keine Zugangsdaten, Datenbanken oder Schlüssel im ZIP."""
    with zipfile.ZipFile(zip_pfad) as z:
        treffer = [n for n in z.namelist()
                   if os.path.basename(n).lower().endswith(VERBOTEN)]
        if treffer:
            raise Abweichung('ZIP enthält verbotene Dateien: ' + ', '.join(sorted(treffer)[:8]))


def baue_zip(eintraege: list[dict], ausgabe: str) -> str:
    zip_pfad = os.path.join(ausgabe, ZIP_NAME)
    with zipfile.ZipFile(zip_pfad, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for e in sorted(eintraege, key=lambda x: x['target']):
            info = zipfile.ZipInfo(e['target'], date_time=FESTE_ZEIT)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            with open(os.path.join(ausgabe, e['target']), 'rb') as f:
                z.writestr(info, f.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return zip_pfad


def pruefe_zip(eintraege: list[dict], ausgabe: str) -> str:
    zip_pfad = os.path.join(ausgabe, ZIP_NAME)
    if not os.path.exists(zip_pfad):
        raise Abweichung(f'{ZIP_NAME} fehlt in {ausgabe}.')
    with zipfile.ZipFile(zip_pfad) as z:
        if z.testzip() is not None:
            raise Abweichung('ZIP ist beschädigt (CRC-Fehler).')
        namen = set(z.namelist())
        soll = {e['target'] for e in eintraege}
        if namen != soll:
            fehlend = sorted(soll - namen)[:5]
            extra = sorted(namen - soll)[:5]
            raise Abweichung(f'ZIP-Inhalt weicht vom Manifest ab (fehlt: {fehlend}, extra: {extra}).')
        for e in eintraege:
            if sha256(z.read(e['target'])) != e['sha256']:
                raise Abweichung(f'ZIP-Eintrag {e["target"]} weicht vom erwarteten Hash ab.')
    return sha256_datei(zip_pfad)


def baue(freigabe: dict, commit: str, branch: str, ausgabe: str,
         evidenz_bauen: bool = False,
         junit: str | None = None, ci: dict | None = None,
         pytest_log: str | None = None,
         pytest_exit_code: str | None = None) -> tuple[list[dict], str]:
    quellen = quell_eintraege(freigabe, commit)
    schreibe_kopien(quellen, ausgabe)
    for e in quellen:
        e.pop('daten', None)
    os.makedirs(ausgabe, exist_ok=True)
    evidenz = None
    if evidenz_bauen:
        evidenz = fuehre_evidenz_aus(ausgabe, commit, branch, junit,
                                     pytest_log=pytest_log,
                                     pytest_exit_code=pytest_exit_code)
    weitere = beleg_eintraege(freigabe, ausgabe)
    eintraege = quellen + weitere
    pruefe_unerlaubte_dateien(freigabe, ausgabe)
    if os.path.exists(os.path.join(ausgabe, 'EVIDENZ.json')):
        pruefe_evidenz(ausgabe, commit)
    if evidenz is None and os.path.exists(os.path.join(ausgabe, 'EVIDENZ.json')):
        evidenz = json.load(open(os.path.join(ausgabe, 'EVIDENZ.json'), encoding='utf-8'))
    if evidenz:
        pruefe_evidenz_dateien(ausgabe, evidenz)
    schreibe_provenienz(eintraege, ausgabe, commit, branch, len(eintraege) + 2)
    eintraege.append(datei_eintrag(ausgabe, PROVENIENZ_NAME))
    schreibe_manifest(eintraege, ausgabe, commit, branch, freigabe, evidenz, ci)
    manifest_eintrag = datei_eintrag(ausgabe, MANIFEST_NAME)
    baue_zip(eintraege + [manifest_eintrag], ausgabe)
    pruefe_verbotene_inhalte(os.path.join(ausgabe, ZIP_NAME))
    zip_sha = sha256_datei(os.path.join(ausgabe, ZIP_NAME))
    with open(os.path.join(ausgabe, ZIP_NAME + '.sha256'), 'w', encoding='utf-8') as f:
        f.write(f'{zip_sha}  {ZIP_NAME}\n')
    pruefe_zip(eintraege + [manifest_eintrag], ausgabe)
    pruefe_hauptdokument(ausgabe)
    pruefe_konsistenz(ausgabe, commit, evidenz,
                      {e['target']: e['sha256'] for e in quellen})
    return eintraege, zip_sha


def pruefe(freigabe: dict, commit: str, ausgabe: str) -> tuple[list[dict], str]:
    quellen = quell_eintraege(freigabe, commit)
    for e in quellen:
        e.pop('daten', None)
    pruefe_kopien(quellen, ausgabe)
    weitere = beleg_eintraege(freigabe, ausgabe)
    eintraege = quellen + weitere
    pruefe_unerlaubte_dateien(freigabe, ausgabe)
    pruefe_evidenz(ausgabe, commit)
    evidenz = json.load(open(os.path.join(ausgabe, 'EVIDENZ.json'), encoding='utf-8'))
    pruefe_evidenz_dateien(ausgabe, evidenz)
    manifest_pfad = os.path.join(ausgabe, MANIFEST_NAME)
    if not os.path.exists(manifest_pfad):
        raise Abweichung('MANIFEST.json fehlt im Paketordner.')
    manifest = json.load(open(manifest_pfad, encoding='utf-8'))
    if manifest.get('commit') != commit:
        raise Abweichung(f'Manifest nennt Commit {str(manifest.get("commit"))[:7]} statt {commit[:7]}.')
    if manifest.get('dirty') is not False:
        raise Abweichung('Manifest ist nicht als sauber (dirty: false) ausgewiesen.')
    laut_manifest = {e['target']: e['sha256'] for e in manifest.get('files', [])}
    for e in eintraege:
        if laut_manifest.get(e['target']) != e['sha256']:
            raise Abweichung(f'Manifest-Hash für {e["target"]} weicht ab.')
    if PROVENIENZ_NAME not in laut_manifest:
        raise Abweichung('Manifest führt PROVENIENZ.json nicht auf.')
    prov = json.load(open(os.path.join(ausgabe, PROVENIENZ_NAME), encoding='utf-8'))
    if prov.get('commit') != commit:
        raise Abweichung('PROVENIENZ.json nennt einen anderen Commit.')
    zip_pfad = os.path.join(ausgabe, ZIP_NAME)
    if not os.path.exists(zip_pfad):
        raise Abweichung(f'{ZIP_NAME} fehlt in {ausgabe}.')
    manifest_eintrag = datei_eintrag(ausgabe, MANIFEST_NAME)
    eintraege = eintraege + [datei_eintrag(ausgabe, PROVENIENZ_NAME)]
    zip_sha = pruefe_zip(eintraege + [manifest_eintrag], ausgabe)
    pruefe_verbotene_inhalte(zip_pfad)
    sidecar = os.path.join(ausgabe, ZIP_NAME + '.sha256')
    if not os.path.exists(sidecar):
        raise Abweichung('ZIP-Prüfsummendatei fehlt.')
    if open(sidecar, encoding='utf-8').read().split()[0] != zip_sha:
        raise Abweichung('ZIP-Prüfsummendatei passt nicht zum ZIP.')
    if manifest.get('testzahl') != evidenz.get('testzahl'):
        raise Abweichung('Manifest-Testzahl weicht von EVIDENZ.json ab.')
    pruefe_hauptdokument(ausgabe)
    pruefe_konsistenz(ausgabe, commit, evidenz,
                      {e['target']: e['sha256'] for e in quellen})
    return eintraege, zip_sha


def main() -> int:
    ap = argparse.ArgumentParser(description='Review-Paket aus freigegebenen Quellen bauen und prüfen.')
    ap.add_argument('--commit', default='HEAD', help='muss HEAD sein (Standard: HEAD)')
    ap.add_argument('--ausgabe', default=STANDARD_AUSGABE)
    ap.add_argument('--pruefen', action='store_true', help='nur prüfen, nichts schreiben')
    ap.add_argument('--evidenz', action='store_true',
                    help='Nachweise ausführen und EVIDENZ.json/EVIDENZ.md neu erzeugen '
                         '(im --pruefen-Lauf ohne Paket immer aktiv)')
    ap.add_argument('--junit', default=None, help='JUnit-XML des pytest-Laufs (eine Testzahl)')
    ap.add_argument('--pytest-log', default=None,
                    help='vorhandenes pytest-Protokoll übernehmen (CI-Artefakt) statt '
                         'die Suite erneut zu starten')
    ap.add_argument('--pytest-exit-code', default=None,
                    help='Datei mit dem Exit-Code des Laufs, zu dem --pytest-log gehört')
    ap.add_argument('--ci-run', default=None, help='CI-Lauf-ID, deren Head-Commit geprüft wird')
    args = ap.parse_args()

    try:
        freigabe = lade_freigabe()
        commit, branch = pruefe_commit(args.commit)
        ausgabe = os.path.abspath(args.ausgabe)
        ci = None
        if args.ci_run:
            ci = ci_lauf(args.ci_run)
            if ci['head_sha'] != commit:
                raise Abweichung(f'CI-Lauf {args.ci_run} gehört zu {ci["head_sha"][:7]}, '
                                 f'nicht zum Paket-Commit {commit[:7]}.')
            if ci.get('conclusion') not in (None, 'success'):
                raise Abweichung(f'CI-Lauf {args.ci_run} endete mit {ci["conclusion"]}.')
        if args.pruefen and os.path.exists(os.path.join(ausgabe, MANIFEST_NAME)):
            eintraege, zip_sha = pruefe(freigabe, commit, ausgabe)
        elif args.pruefen:
            # CI hat kein artifacts/-Verzeichnis: nur die Quellen prüfen.
            with tempfile.TemporaryDirectory(prefix='review-paket-') as temp:
                # Auch ohne ``--evidenz``: Im Prüflauf muss die Testzahl aus einem
                # echten pytest-Protokoll stammen, nicht aus einer alten Datei.
                eintraege, zip_sha = baue(freigabe, commit, branch, temp,
                                          evidenz_bauen=True, junit=args.junit, ci=ci,
                                          pytest_log=args.pytest_log,
                                          pytest_exit_code=args.pytest_exit_code)
                # Ohne Paketdokumente hätte ``pruefe_konsistenz`` nichts zu prüfen.
                # Der Bericht entsteht aus den gerade gemessenen Werten und wird
                # anschliessend mit denselben Prüfungen wie ein echtes Paket geprüft.
                evidenz = json.load(open(os.path.join(temp, 'EVIDENZ.json'),
                                         encoding='utf-8'))
                schreibe_pruefbericht(temp, commit, branch, eintraege, evidenz, ci)
                pruefe_hauptdokument(temp)
                pruefe_konsistenz(temp, commit, evidenz,
                                  {e['target']: e['sha256'] for e in eintraege
                                   if e.get('herkunft') == 'commit'})
        else:
            os.makedirs(ausgabe, exist_ok=True)
            eintraege, zip_sha = baue(freigabe, commit, branch, ausgabe,
                                      evidenz_bauen=args.evidenz, junit=args.junit, ci=ci,
                                      pytest_log=args.pytest_log,
                                      pytest_exit_code=args.pytest_exit_code)
    except Abweichung as fehler:
        print(f'Review-Paket FEHLER: {fehler}', file=sys.stderr)
        return 1

    quellen = sum(1 for e in eintraege if e['herkunft'] == 'commit')
    belege = sum(1 for e in eintraege if e['herkunft'] == 'beleg')
    dokumente = sum(1 for e in eintraege if e['herkunft'] == 'paketdokument')
    print(f'Review-Paket OK: {len(eintraege)} Dateien ({quellen} Quellen, {belege} Belege, '
          f'{dokumente} Dokumente) · Commit {commit[:7]} · ZIP {zip_sha[:16]}…')
    return 0


if __name__ == '__main__':
    sys.exit(main())
