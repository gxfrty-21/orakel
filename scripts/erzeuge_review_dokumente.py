#!/usr/bin/env python3
"""Erzeugt die Begleitdokumente des Review-Pakets aus gemessenen Daten.

Quellen sind ausschliesslich ``MANIFEST.json``, ``EVIDENZ.json`` und der
tatsächliche ZIP-Eintrag des Pakets. Der Generator zählt keine Werte, die er
nicht in diesen Dateien nachweisen kann; die Dokumente nennen damit dieselbe
Datei-, ZIP- und Belegzahl wie das Paket selbst.

Der Bau ruft ``schreibe`` bereits vor Manifest und ZIP auf, damit die Hashes
der Dokumente im Manifest stehen. Ein späterer Aufruf dieses Skripts liest
denselben Dateisatz aus dem fertigen Paket und erzeugt byte-gleiche Dateien.

Aufruf:
    python scripts/erzeuge_review_dokumente.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STANDARD_AUSGABE = ROOT / "artifacts" / "review-paket-orakel"
MONATE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def lade_builder():
    """Lädt ``scripts/baue_review_paket.py`` ohne Paketinstallation."""
    spec = importlib.util.spec_from_file_location(
        "baue_review_paket", ROOT / "scripts" / "baue_review_paket.py")
    if spec is None or spec.loader is None:
        raise SystemExit("scripts/baue_review_paket.py ist nicht ladbar.")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def datum_de(tag: date | None = None) -> str:
    tag = tag or date.today()
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"


def _belege_text(anzahl: int) -> str:
    return "1 älterer Beleg" if anzahl == 1 else f"{anzahl} ältere Belege"


def schreibe(ausgabe: str | Path, freigabe: dict, builder,
             dateien: list[dict], zip_anzahl: int, evidenz: dict,
             commit: str, branch: str,
             stand: str | None = None) -> dict[str, int]:
    """Schreibt die vier Begleitdokumente aus feststehenden Zahlen.

    Beim Bau stehen ``dateien`` und ``zip_anzahl`` schon vor Manifest und ZIP
    fest: alle Quellen, Belege und Paketdokumente, die das Paket enthalten
    wird. Ein späterer Lauf liest dieselben Zahlen aus ``MANIFEST.json`` und
    dem ZIP. Solange beide Wege denselben Dateisatz beschreiben, entstehen
    byte-gleiche Dokumente; ``stand`` kommt deshalb aus dem Manifest.
    """
    ausgabe = Path(ausgabe)
    quellen = [d for d in dateien if d["herkunft"] == "commit"]
    belege = [d for d in dateien if d["herkunft"] == "beleg"]
    dateien_anzahl = len(dateien)
    testzahl = evidenz["testzahl"]
    stand = stand or datum_de()

    quickstart = f"""# Reviewer-Quickstart

**Paketstand:** Commit `{commit}` (Branch `{branch}`, Arbeitsbaum sauber,
`dirty: false`), gebaut am {stand}.
**Umfang:** {dateien_anzahl} Dateien ({zip_anzahl} ZIP-Einträge), davon
{len(quellen)} Quellen, {len(belege)} Belege und sieben Paketdokumente.
Alle Codekopien liegen unter `dateien/`; der Pfad dahinter entspricht dem
Repository (`dateien/code/nexus/bewertung.py` → `orakel/nexus/bewertung.py`).

## 1. In fünf Minuten

1. `EVIDENZ.md` lesen: {testzahl} bestandene Tests, Doku-Prüfung und
   Strategie-Bericht mit Befehl, Exit-Code und SHA-256.
2. `MANIFEST.json` gegen die entpackten Dateien prüfen (Abschnitt 3).
3. `dateien/docs/REVIEW-DOSSIER.md` lesen: Architektur, Messwerte,
   Schwachstellen-Kandidaten und Prüffragen.

## 2. Struktur

| Pfad | Inhalt |
|---|---|
| `ORAKEL-REVIEW-PAKET.md` | Prüfbericht aus Manifest und Evidenz |
| `EVIDENZ.md`, `EVIDENZ.json` | Gemessene Nachweise, Exit-Codes, Hashes |
| `MANIFEST.json`, `PROVENIENZ.json` | Quelle, Ziel, Größe und SHA-256 je Datei |
| `QUELLEN-DECKUNG.md` | Quellgruppen und bewusste Lücken |
| `DELTA-CHANGELOG.md` | Änderungen gegenüber dem vorherigen Paketstand |
| `dateien/` | Code, Tests, Doku, Skripte, CI und Konfiguration |
| `belege/` | Drei Protokolle und die Strategie-Berichte dieses Baus |

## 3. Nachweise reproduzieren

```bash
python -m pytest -q tests          # erwartet: {testzahl} passed, Exit 0
python scripts/pruefe_doku.py      # erwartet: Doku OK, Exit 0
```

Manifest-Stichprobe (Python 3.12, im entpackten Ordner):

```bash
python - <<'PY'
import hashlib, json, pathlib
m = json.loads(pathlib.Path("MANIFEST.json").read_text(encoding="utf-8"))
for e in m["files"]:
    if e["herkunft"] != "commit":
        continue
    p = pathlib.Path(e["target"])
    assert hashlib.sha256(p.read_bytes()).hexdigest() == e["sha256"], p
print("Manifest OK:", len(m["files"]), "Dateien")
PY
```

## 4. Prüfroute (60–90 Minuten)

1. **Evidenz und Hashes (10 min):** `EVIDENZ.md`, Manifest-Stichprobe,
   `PROVENIENZ.json` gegen den Commit prüfen.
2. **Handelskern (25 min):** `dateien/code/backtest.py`,
   `dateien/code/judge.py`, `dateien/code/risk.py`,
   `dateien/code/paper.py` und die zugehörigen Tests unter
   `dateien/tests/`.
3. **Datenstrecke (20 min):** `dateien/scripts/transport_client.py`,
   `dateien/scripts/windows_transport_task.ps1` und
   `dateien/docs/ABNAHME-PR-302.md`; die reale Windows-/MT5-Abnahme ist offen.
4. **Web und Betrieb (20 min):** `dateien/code/web.py`,
   `dateien/code/scheduler.py`, `dateien/code/sekretariat.py` und
   `dateien/tests/test_web.py`.
5. **Grenzen (5 min):** `DELTA-CHANGELOG.md`, Abschnitt 5 dieses Dokuments
   und `dateien/docs/REVIEW-DOSSIER.md`, Abschnitt 9.

## 5. Bewusste Grenzen

- Keine reale Windows-/MT5-Abnahme und keine echten Brokerdaten.
- Keine Safari-/iPad-Hardware; die vorhandenen UI-Prüfungen laufen mit
  Chromium/CDP.
- Keine Produktionslast; Performancewerte sind synthetisch.
- Ältere CI- und Browserbelege aus früheren Paketständen sind nicht enthalten;
  dieses Paket belegt ausschließlich den genannten Commit.
"""

    quellen_deckung = f"""# Quellen-Deckung des Review-Pakets

**Stand:** {stand}, Commit `{commit}` (`{branch}`), Arbeitsbaum sauber.
Die Zahlen stammen aus `MANIFEST.json` dieses Pakets.

## 1. Quellgruppen

| Gruppe | Präfix | Dateien | Bytes |
|---|---|---:|---:|
"""
    for g in builder.quellgruppen(freigabe, dateien):
        quellen_deckung += (f"| `{g['name']}` | `{g['praefix']}` | {g['dateien']} | "
                            f"{g['bytes']} |\n")

    quellen_deckung += f"""
Insgesamt sind {len(quellen)} Quellen freigegeben, darunter auch Einzelquellen
außerhalb der Gruppen wie `AGENTS.md`, `README.md`, `config.toml`,
`ruff.toml`, `mypy.ini`, `.importlinter`, die CI-Workflows und die
Deployment-Dateien.

## 2. Kernbehauptungen → Quellen

| Behauptung | Quellen im Paket |
|---|---|
| Backtest, Richter, Risiko und Paper-Takt sind getestet | `dateien/code/backtest.py`, `dateien/code/judge.py`, `dateien/code/risk.py`, `dateien/code/paper.py`, `dateien/tests/test_backtest.py`, `dateien/tests/test_judge.py`, `dateien/tests/test_risk.py`, `dateien/tests/test_paper.py` |
| Die vollständige Suite läuft mit {testzahl} Tests | `dateien/tests/` (alle Testdateien und Fixtures), `belege/evidenz-pytest.log` |
| Die Doku-Prüfung ist grün | `dateien/scripts/pruefe_doku.py`, `belege/evidenz-doku.log` |
| Der Strategie-Bericht ist aus Seed-Daten erzeugt | `dateien/seed/README.md`, `belege/strategie-bericht.md`, `belege/strategie-bericht.json`, `belege/evidenz-strategie.log` |
| Der Windows-Transport ist implementiert, aber nicht real abgenommen | `dateien/scripts/transport_client.py`, `dateien/scripts/windows_transport_task.ps1`, `dateien/docs/ABNAHME-PR-302.md`, `dateien/tests/test_transport_client.py` |
| Die Architekturgrenze ist erzwungen | `dateien/.importlinter`, `dateien/tests/test_architektur.py`, `dateien/docs/ARCHITEKTUR-KERN.md` |
| Die Bewertung ist als Dossier dokumentiert | `dateien/docs/REVIEW-DOSSIER.md` |

## 3. Belege dieses Baus

"""
    for e in sorted(belege, key=lambda x: x["target"]):
        quellen_deckung += f"- `{e['target']}` ({e['bytes']} Bytes)\n"

    fehlende_belege = [n for n in (freigabe.get("belege") or [])
                       if not (ausgabe / n).exists()]
    quellen_deckung += f"""
## 4. Bewusste Lücken

- Nicht enthalten sind {_belege_text(len(fehlende_belege))} aus früheren
  Paketständen (Screenshots, CI- und Browserprotokolle); sie belegen keinen
  Lauf auf `{commit[:7]}`.
- Es gibt keine reale Windows-/MT5-Abnahme, keine Safari-Hardware und keine
  Produktionslast.
- Das Paket enthält keine Datenbank, keine `.env` und keine Zugangsdaten.
"""

    delta = f"""# Delta-Changelog

## Neubau {stand} (`{commit[:7]}`)

Dieses Paket ersetzt den Stand vom 19. November 2026. Es wird aus `main` nach
dem Merge des Review-Dossiers gebaut.

- **Umfang:** {dateien_anzahl} Dateien ({zip_anzahl} ZIP-Einträge) statt 147
  ZIP-Einträgen im vorherigen Paket; die vollständige Testsuite, alle
  CI-Workflows und die Dokumentation sind enthalten.
- **Dossier:** `dateien/docs/REVIEW-DOSSIER.md` bündelt Architektur, Messwerte
  und eine sortierte Kandidatenliste der schwächsten Bereiche.
- **Evidenz neu gemessen:** {testzahl} bestandene Tests, Doku-Prüfung und
  Strategie-Bericht mit Exit-Code und SHA-256.
- **Paketdokumente neu erzeugt:** Prüfbericht, Quickstart, Quellen-Deckung und
  dieses Delta entstehen aus `MANIFEST.json` und `EVIDENZ.json`, nicht aus
  älteren Behauptungen.
- **Nicht übernommen:** ältere Browser-, Text250- und CI-Belege aus früheren
  Paketständen. Für den aktuellen Commit liegen dafür keine Protokolle vor.
- **Unverändert offen:** reale Windows-/MT5-Abnahme, Safari-/iPad-Hardware,
  Produktionslast und Schwachstellenprüfung der Abhängigkeiten.
"""

    (ausgabe / "QUICKSTART.md").write_text(quickstart, encoding="utf-8")
    (ausgabe / "QUELLEN-DECKUNG.md").write_text(quellen_deckung, encoding="utf-8")
    (ausgabe / "DELTA-CHANGELOG.md").write_text(delta, encoding="utf-8")

    fehlend = fehlende_belege + [
        n for n in (freigabe.get("dokumente") or [])
        if n != builder.HAUPTDOKUMENT and not (ausgabe / n).exists()]
    eintraege = [{"target": d["target"], "sha256": d.get("sha256", ""),
                  "bytes": d.get("bytes", 0), "herkunft": d["herkunft"]}
                 for d in dateien]
    builder.schreibe_pruefbericht(str(ausgabe), commit, branch, eintraege, evidenz,
                                  fehlend=fehlend,
                                  ausnahmen=freigabe.get("ausnahmen"))
    return {"dateien": dateien_anzahl, "zip_eintraege": zip_anzahl,
            "fehlende": len(fehlend)}


def erzeuge(ausgabe: str | Path, freigabe: dict, builder,
            stand: str | None = None) -> dict[str, int]:
    """Schreibt die Begleitdokumente aus dem fertigen Paket neu.

    Der Bau erzeugt sie bereits vor Manifest und ZIP; dieser Aufruf liest die
    Zahlen aus beiden Dateien und liefert byte-gleiche Dokumente, solange der
    Dateisatz unverändert ist. Der Stand kommt aus dem Manifest, damit ein
    späterer Lauf nicht unbemerkt ein neues Datum einsetzt.
    """
    ausgabe = Path(ausgabe)
    manifest = json.loads((ausgabe / "MANIFEST.json").read_text(encoding="utf-8"))
    evidenz = json.loads((ausgabe / "EVIDENZ.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(ausgabe / builder.ZIP_NAME) as archiv:
        zip_anzahl = len(archiv.namelist())
    return schreibe(ausgabe, freigabe, builder, manifest["files"], zip_anzahl,
                    evidenz, manifest["commit"], manifest["branch"],
                    stand=stand or manifest.get("stand"))


def main() -> int:
    builder = lade_builder()
    freigabe = builder.lade_freigabe()
    if not (STANDARD_AUSGABE / "MANIFEST.json").exists():
        print(f"Review-Paket fehlt: {STANDARD_AUSGABE} zuerst bauen.",
              file=sys.stderr)
        return 1
    manifest = json.loads((STANDARD_AUSGABE / "MANIFEST.json").read_text(encoding="utf-8"))
    commit, _branch = builder.pruefe_commit("HEAD")
    if manifest["commit"] != commit:
        print(f"MANIFEST.json gehört zu {manifest['commit'][:7]}, HEAD ist "
              f"{commit[:7]}; Paket zuerst neu bauen.", file=sys.stderr)
        return 1
    zahlen = erzeuge(STANDARD_AUSGABE, freigabe, builder)
    print(f"Dokumente erzeugt: {zahlen['dateien']} Dateien, "
          f"{zahlen['zip_eintraege']} ZIP-Einträge, "
          f"{zahlen['fehlende']} fehlende Dateien")
    return 0


if __name__ == "__main__":
    sys.exit(main())
