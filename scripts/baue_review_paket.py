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
import re
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
EVIDENZ_MD = 'EVIDENZ.md'
MUSTER_TESTZAHL = re.compile(r'(\d+)\s+passed')
MUSTER_JUNIT = re.compile(r'<testsuite\b[^>]*\btests="(\d+)"')
MUSTER_EVIDENZ_HASH = re.compile(r'`(belege/[^`]+)`\s*\(`([0-9a-f]{8,64})')
MUSTER_RUN = re.compile(r'/actions/runs/(\d+)')
MUSTER_COMMIT = re.compile(r'\b([0-9a-f]{7,40})\b')

# Nachweise, die der Generator selbst ausführt. Reihenfolge = Reihenfolge im Bericht.
PRUEFUNGEN = (
    ('pytest', ('-m', 'pytest', '-q'), 'belege/evidenz-pytest.log'),
    ('doku', ('scripts/pruefe_doku.py',), 'belege/evidenz-doku.log'),
)


class Abweichung(Exception):
    """Freigabe-, Hash- oder Strukturabweichung; führt zu Exit-Code 1."""


def git(*args: str) -> bytes:
    r = subprocess.run(['git', '-c', 'safe.directory=*', '-C', WURZEL, *args], capture_output=True)
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
    try:
        r = subprocess.run(['node', '--version'], capture_output=True, text=True, timeout=10)
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


def letzte_zeile(text: str) -> str:
    """Letzte nicht leere Zeile eines Protokolls (die Ergebniszeile)."""
    zeilen = [z.strip() for z in text.splitlines() if z.strip()]
    return zeilen[-1] if zeilen else ''


def testzahl_aus_log(text: str) -> int | None:
    """Liest die Testzahl aus der pytest-Schlusszeile (``402 passed``)."""
    treffer = MUSTER_TESTZAHL.findall(text)
    return int(treffer[-1]) if treffer else None


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


def fuehre_evidenz_aus(ausgabe: str, commit: str, branch: str,
                       junit: str | None = None) -> dict:
    """Führt die Nachweise aus und schreibt Protokolle, EVIDENZ.json und EVIDENZ.md.

    Die Testzahl stammt aus dem Protokoll bzw. dem JUnit-Bericht; sie wird nirgends
    von Hand eingetragen. Schlägt ein Nachweis fehl oder widersprechen sich Log und
    JUnit-Bericht, bricht der Bau ab.
    """
    dateien = []
    for name, argv, ziel in PRUEFUNGEN:
        lauf = subprocess.run([sys.executable, *argv], cwd=WURZEL, capture_output=True, text=True)
        text = lauf.stdout + lauf.stderr
        pfad = os.path.join(ausgabe, ziel)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, 'w', encoding='utf-8') as f:
            f.write(text)
        dateien.append({
            'name': name,
            'target': ziel,
            'commit': commit,
            'befehl': befehl_text(argv),
            'exit_code': lauf.returncode,
            'sha256': sha256_datei(pfad),
            'bytes': os.path.getsize(pfad),
            'log': letzte_zeile(text),
        })
    pytest_eintrag = next(d for d in dateien if d['name'] == 'pytest')
    aus_log = testzahl_aus_log(open(os.path.join(ausgabe, pytest_eintrag['target']),
                                    encoding='utf-8').read())
    if aus_log is None:
        raise Abweichung('pytest-Protokoll enthält keine Zeile "N passed".')
    if junit:
        aus_junit = testzahl_aus_junit(junit)
        if aus_junit != aus_log:
            raise Abweichung(f'JUnit-Bericht nennt {aus_junit} Tests, das Protokoll {aus_log}.')
    if pytest_eintrag['exit_code'] != 0:
        raise Abweichung(f'pytest endete mit Exit {pytest_eintrag["exit_code"]}: '
                         f'{pytest_eintrag["log"]}')
    evidenz = {
        'schema': 'review-paket-evidenz.v3',
        'generated_at': '2026-11-19T00:00:00Z',
        'quelle': {'commit': commit, 'branch': branch, 'dirty': False},
        'umgebung': umgebung(),
        'testzahl': aus_log,
        'dateien': dateien,
    }
    with open(os.path.join(ausgabe, 'EVIDENZ.json'), 'w', encoding='utf-8') as f:
        json.dump(evidenz, f, ensure_ascii=False, indent=2)
        f.write('\n')
    with open(os.path.join(ausgabe, EVIDENZ_MD), 'w', encoding='utf-8') as f:
        f.write(rendere_evidenz_md(evidenz))
    return evidenz


def rendere_evidenz_md(evidenz: dict) -> str:
    """Erzeugt EVIDENZ.md ausschliesslich aus EVIDENZ.json (eine Quelle)."""
    quelle = evidenz['quelle']
    zeilen = [
        '# Evidenz',
        '',
        f"Alle Nachweise wurden vom Paket-Generator auf Commit `{quelle['commit']}` "
        f"(Branch `{quelle['branch']}`, Arbeitsbaum sauber, `dirty: false`) erzeugt. "
        'Zahlen und Hashes dieser Datei stammen aus den Protokollen und den Dateien '
        'selbst; der Generator bricht ab, sobald eine Angabe davon abweicht.',
        '',
        f"Gemessene Testzahl: **{evidenz['testzahl']}** (`pytest`).",
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


def repo_slug() -> str:
    """``owner/name`` aus der Origin-URL."""
    url = git('remote', 'get-url', 'origin').decode().strip()
    treffer = re.search(r'[:/]([^/:]+/[^/]+?)(?:\.git)?$', url)
    if not treffer:
        raise Abweichung(f'Origin-URL nicht lesbar: {url}')
    return treffer.group(1)


def ci_lauf(run_id: str) -> dict:
    """Fragt Lauf-ID, Head-Commit und Ergebnis über die GitHub-API ab."""
    r = subprocess.run(
        ['gh', 'api', f'repos/{repo_slug()}/actions/runs/{run_id}',
         '--jq', '{head_sha: .head_sha, conclusion: .conclusion, event: .event}'],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise Abweichung(f'CI-Lauf {run_id} nicht abrufbar: {r.stderr.strip()[:200]}')
    try:
        daten = json.loads(r.stdout)
    except json.JSONDecodeError as fehler:
        raise Abweichung(f'CI-Lauf {run_id} liefert kein JSON.') from fehler
    if not daten.get('head_sha'):
        raise Abweichung(f'CI-Lauf {run_id} nennt keinen Head-Commit.')
    return {'run_id': int(run_id), **daten}


def pruefe_konsistenz(ausgabe: str, commit: str, evidenz: dict | None) -> None:
    """Prüft Doku gegen Quellen: Hashes, Testzahl und CI-Lauf-IDs.

    Läuft nach jedem Bau und bei ``--pruefen``; jede Abweichung beendet den Lauf.
    """
    md_pfade = [os.path.join(ausgabe, n) for n in sorted(os.listdir(ausgabe))
                if n.endswith('.md') and os.path.isfile(os.path.join(ausgabe, n))]
    if not md_pfade:
        return
    ziel_hashes = {}
    if evidenz:
        ziel_hashes = {e['target']: e['sha256'] for e in evidenz['dateien']}
    for pfad in md_pfade:
        text = open(pfad, encoding='utf-8').read()
        name = os.path.basename(pfad)
        for ziel, praefix in MUSTER_EVIDENZ_HASH.findall(text):
            echt = ziel_hashes.get(ziel)
            if echt is None:
                raise Abweichung(f'{name} nennt Hash zu unbekanntem Protokoll {ziel!r}.')
            if not echt.startswith(praefix):
                raise Abweichung(f'{name}: Hash {praefix}… passt nicht zu {ziel} ({echt[:16]}…).')
        if evidenz:
            for zahl in MUSTER_TESTZAHL.findall(text):
                if int(zahl) != evidenz['testzahl']:
                    raise Abweichung(f'{name} nennt {zahl} passed, gemessen sind '
                                     f'{evidenz["testzahl"]}.')
        for run_id in set(MUSTER_RUN.findall(text)):
            if not _gh_verfuegbar():
                print(f'Hinweis: gh fehlt, CI-Lauf {run_id} aus {name} nicht geprüft.',
                      file=sys.stderr)
                continue
            lauf = ci_lauf(run_id)
            if lauf['head_sha'] != commit:
                raise Abweichung(f'{name} nennt CI-Lauf {run_id} auf '
                                 f'{lauf["head_sha"][:7]}, Paket-Commit ist {commit[:7]}.')


def _gh_verfuegbar() -> bool:
    try:
        r = subprocess.run(['gh', '--version'], capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
         pflicht: bool = False, evidenz_bauen: bool = False,
         junit: str | None = None, ci: dict | None = None) -> tuple[list[dict], str]:
    quellen = quell_eintraege(freigabe, commit)
    schreibe_kopien(quellen, ausgabe)
    for e in quellen:
        e.pop('daten', None)
    os.makedirs(ausgabe, exist_ok=True)
    evidenz = None
    if evidenz_bauen:
        evidenz = fuehre_evidenz_aus(ausgabe, commit, branch, junit)
    weitere = beleg_eintraege(freigabe, ausgabe, pflicht=pflicht)
    eintraege = quellen + weitere
    pruefe_kopien(quellen, ausgabe)
    pruefe_unerlaubte_dateien(freigabe, ausgabe)
    if pflicht or os.path.exists(os.path.join(ausgabe, 'EVIDENZ.json')):
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
    pruefe_konsistenz(ausgabe, commit, evidenz)
    return eintraege, zip_sha


def pruefe(freigabe: dict, commit: str, ausgabe: str) -> tuple[list[dict], str]:
    quellen = quell_eintraege(freigabe, commit)
    for e in quellen:
        e.pop('daten', None)
    pruefe_kopien(quellen, ausgabe)
    weitere = beleg_eintraege(freigabe, ausgabe, pflicht=False)
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
    pruefe_konsistenz(ausgabe, commit, evidenz)
    return eintraege, zip_sha


def main() -> int:
    ap = argparse.ArgumentParser(description='Review-Paket aus freigegebenen Quellen bauen und prüfen.')
    ap.add_argument('--commit', default='HEAD', help='muss HEAD sein (Standard: HEAD)')
    ap.add_argument('--ausgabe', default=STANDARD_AUSGABE)
    ap.add_argument('--pruefen', action='store_true', help='nur prüfen, nichts schreiben')
    ap.add_argument('--evidenz', action='store_true',
                    help='Nachweise ausführen und EVIDENZ.json/EVIDENZ.md neu erzeugen')
    ap.add_argument('--junit', default=None, help='JUnit-XML des pytest-Laufs (eine Testzahl)')
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
                eintraege, zip_sha = baue(freigabe, commit, branch, temp, pflicht=False,
                                          evidenz_bauen=args.evidenz, junit=args.junit, ci=ci)
        else:
            os.makedirs(ausgabe, exist_ok=True)
            eintraege, zip_sha = baue(freigabe, commit, branch, ausgabe,
                                      evidenz_bauen=args.evidenz, junit=args.junit, ci=ci)
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
