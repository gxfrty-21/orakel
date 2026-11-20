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

``--pruefen`` prüft ein vorhandenes Paket gegen den Commit. Existiert noch kein
Paket (CI ohne ``artifacts/``), baut der Builder in ein temporäres Verzeichnis
und prüft dort Quellen, Hashes und ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FREIGABE = os.path.join(WURZEL, 'scripts', 'review-paket-freigabe.json')
STANDARD_AUSGABE = os.path.join(WURZEL, 'artifacts', 'review-paket-orakel')
ZIP_NAME = 'ORAKEL-REVIEW-PAKET.zip'
MANIFEST_NAME = 'MANIFEST.json'
PROVENIENZ_NAME = 'PROVENIENZ.json'
FESTE_ZEIT = (2026, 11, 18, 0, 0, 0)
NEBEN_DATEIEN = {MANIFEST_NAME, PROVENIENZ_NAME, ZIP_NAME, ZIP_NAME + '.sha256'}


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


def beleg_eintraege(freigabe: dict, ausgabe: str, pflicht: bool) -> list[dict]:
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
        if pflicht:
            raise Abweichung('Freigegebene Belege/Dokumente fehlen im Paketordner: '
                             + ', '.join(sorted(fehlend)))
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
                      freigabe: dict) -> None:
    liste = [{
        'target': e['target'],
        'sha256': e['sha256'],
        'bytes': e['bytes'],
        'herkunft': e['herkunft'],
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
        'pruefungen': sorted(pruefungen, key=lambda p: p['name']),
        'files': liste,
    }
    with open(os.path.join(ausgabe, MANIFEST_NAME), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')


def schreibe_provenienz(eintraege: list[dict], ausgabe: str, commit: str, branch: str, zip_sha: str) -> None:
    provenienz = {
        'schema': 'review-paket-provenienz.v3',
        'commit': commit,
        'branch': branch,
        'dirty': False,
        'arbeitsbaum': 'sauber',
        'builder': 'scripts/baue_review_paket.py',
        'freigabe': 'scripts/review-paket-freigabe.json',
        'generated_at': '2026-11-18T00:00:00Z',
        'zip': {
            'name': ZIP_NAME,
            'sha256': zip_sha,
            'bytes': os.path.getsize(os.path.join(ausgabe, ZIP_NAME)),
            'eintraege': len(eintraege),
            'deterministisch': True,
        },
        'reproduktion': {
            'bau': 'python scripts/baue_review_paket.py --commit %s' % commit,
            'pruefung': 'python scripts/baue_review_paket.py --pruefen',
        },
        'dateien': [{'target': e['target'], 'sha256': e['sha256'], 'bytes': e['bytes'],
                     'herkunft': e['herkunft']} for e in sorted(eintraege, key=lambda x: x['target'])],
    }
    with open(os.path.join(ausgabe, PROVENIENZ_NAME), 'w', encoding='utf-8') as f:
        json.dump(provenienz, f, ensure_ascii=False, indent=2)
        f.write('\n')


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
         pflicht: bool = False) -> tuple[list[dict], str]:
    quellen = quell_eintraege(freigabe, commit)
    schreibe_kopien(quellen, ausgabe)
    for e in quellen:
        e.pop('daten', None)
    weitere = beleg_eintraege(freigabe, ausgabe, pflicht=pflicht)
    eintraege = quellen + weitere
    pruefe_kopien(quellen, ausgabe)
    pruefe_unerlaubte_dateien(freigabe, ausgabe)
    schreibe_manifest(eintraege, ausgabe, commit, branch, freigabe)
    baue_zip(eintraege, ausgabe)
    zip_sha = sha256_datei(os.path.join(ausgabe, ZIP_NAME))
    with open(os.path.join(ausgabe, ZIP_NAME + '.sha256'), 'w', encoding='utf-8') as f:
        f.write(f'{zip_sha}  {ZIP_NAME}\n')
    schreibe_provenienz(eintraege, ausgabe, commit, branch, zip_sha)
    pruefe_zip(eintraege, ausgabe)
    return eintraege, zip_sha


def pruefe(freigabe: dict, commit: str, ausgabe: str) -> tuple[list[dict], str]:
    quellen = quell_eintraege(freigabe, commit)
    for e in quellen:
        e.pop('daten', None)
    pruefe_kopien(quellen, ausgabe)
    weitere = beleg_eintraege(freigabe, ausgabe, pflicht=False)
    eintraege = quellen + weitere
    pruefe_unerlaubte_dateien(freigabe, ausgabe)
    manifest_pfad = os.path.join(ausgabe, MANIFEST_NAME)
    if os.path.exists(manifest_pfad):
        manifest = json.load(open(manifest_pfad, encoding='utf-8'))
        if manifest.get('commit') != commit:
            raise Abweichung(f'Manifest nennt Commit {str(manifest.get("commit"))[:7]} statt {commit[:7]}.')
        if manifest.get('dirty') is not False:
            raise Abweichung('Manifest ist nicht als sauber (dirty: false) ausgewiesen.')
        laut_manifest = {e['target']: e['sha256'] for e in manifest.get('files', [])}
        for e in eintraege:
            if laut_manifest.get(e['target']) != e['sha256']:
                raise Abweichung(f'Manifest-Hash für {e["target"]} weicht ab.')
    zip_sha = pruefe_zip(eintraege, ausgabe) if os.path.exists(os.path.join(ausgabe, ZIP_NAME)) else 'ohne ZIP'
    return eintraege, zip_sha


def main() -> int:
    ap = argparse.ArgumentParser(description='Review-Paket aus freigegebenen Quellen bauen und prüfen.')
    ap.add_argument('--commit', default='HEAD', help='muss HEAD sein (Standard: HEAD)')
    ap.add_argument('--ausgabe', default=STANDARD_AUSGABE)
    ap.add_argument('--pruefen', action='store_true', help='nur prüfen, nichts schreiben')
    args = ap.parse_args()

    try:
        freigabe = lade_freigabe()
        commit, branch = pruefe_commit(args.commit)
        ausgabe = os.path.abspath(args.ausgabe)
        if args.pruefen and os.path.exists(os.path.join(ausgabe, MANIFEST_NAME)):
            eintraege, zip_sha = pruefe(freigabe, commit, ausgabe)
        elif args.pruefen:
            # CI hat kein artifacts/-Verzeichnis: nur die Quellen prüfen.
            with tempfile.TemporaryDirectory(prefix='review-paket-') as temp:
                eintraege, zip_sha = baue(freigabe, commit, branch, temp, pflicht=False)
        else:
            os.makedirs(ausgabe, exist_ok=True)
            eintraege, zip_sha = baue(freigabe, commit, branch, ausgabe)
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
