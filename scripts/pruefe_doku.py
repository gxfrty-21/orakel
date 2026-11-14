#!/usr/bin/env python3
"""Prüft relative Markdown-Links und veraltete Raumschiff-Begriffe.

Der Lauf ist bewusst ohne Zusatzpakete nutzbar, damit er in der CI schnell
bleibt. Relative Pfade werden vom jeweiligen Dokument aus aufgelöst;
Weblinks, Mailto-Links und reine Sprungmarken werden übersprungen.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git", ".venv", "node_modules", "artifacts", "__pycache__",
    ".pytest_cache", ".next", "dist", "build", "target",
}

# Begriffe, die eine frühere Decks-Zählung beschreiben. Die aktuellen
# Planungsdokumente dürfen historische acht Decks erwähnen, solange sie klar
# als Planung gekennzeichnet sind; diese konkreten Kurzformen sind dagegen
# irreführend für die aktuelle 103-Raum-Ansicht.
VERALTETE_BEGRIFFE = (
    (re.compile(r"\b(?:drei|3)\s+Decks?\b", re.IGNORECASE), "drei Decks"),
    (re.compile(r"\b(?:zwei|2)\s+Decks?\b", re.IGNORECASE), "zwei Decks"),
    (re.compile(r"\bDecks?\s+[ABC]\b", re.IGNORECASE), "Deck A/B/C"),
)

INLINE_LINK = re.compile(
    r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
REFERENCE_LINK = re.compile(
    r"^[ \t]{0,3}\[[^\]]+\]:[ \t]*(<[^>]+>|\S+)", re.MULTILINE
)
HTML_LINK = re.compile(
    r"\b(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE
)
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def _blank(text: str) -> str:
    """Ersetzt Zeichen durch Leerzeichen, behält aber Zeilenumbrüche."""
    return re.sub(r"[^\n]", " ", text)


def _maskiere_code(text: str) -> str:
    """Blendet Fenced Code, Inline-Code und HTML-Kommentare aus."""
    zeilen = []
    fence: str | None = None
    fence_laenge = 0
    for zeile in text.splitlines(keepends=True):
        treffer = FENCE.match(zeile)
        if fence is None and treffer:
            fence = treffer.group(1)[0]
            fence_laenge = len(treffer.group(1))
            zeilen.append(_blank(zeile))
        elif fence is not None:
            zeilen.append(_blank(zeile))
            if treffer and treffer.group(1)[0] == fence and len(treffer.group(1)) >= fence_laenge:
                fence = None
        else:
            zeilen.append(zeile)
    text = "".join(zeilen)
    text = re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), text, flags=re.DOTALL)
    text = re.sub(r"`+[^`\n]*`+", lambda m: _blank(m.group(0)), text)
    return text


def _relative_ziele(text: str):
    """Liefert (Zeilennummer, Ziel) für alle lokalen Linkziele."""
    maskiert = _maskiere_code(text)
    for muster in (INLINE_LINK, REFERENCE_LINK, HTML_LINK):
        for treffer in muster.finditer(maskiert):
            ziel = treffer.group(1).strip()
            if ziel.startswith("<") and ziel.endswith(">"):
                ziel = ziel[1:-1].strip()
            if not ziel or ziel.startswith("#"):
                continue
            if ziel.startswith("//") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", ziel):
                continue  # http(s), mailto, data usw.
            zeile = text.count("\n", 0, treffer.start()) + 1
            yield zeile, ziel


def _pruefe_link(root: Path, datei: Path, ziel: str) -> str | None:
    """Gibt einen Befund zurück, wenn das relative Ziel nicht existiert."""
    pfad = unquote(ziel.split("#", 1)[0].split("?", 1)[0])
    if not pfad or "{{" in pfad or "${" in pfad:
        return None
    try:
        kandidat = root / pfad.lstrip("/") if pfad.startswith("/") else datei.parent / pfad
        aufgeloest = kandidat.resolve()
        aufgeloest.relative_to(root.resolve())
    except (OSError, ValueError):
        return f"relativer Link «{ziel}» liegt ausserhalb des Repositories"
    if not aufgeloest.exists():
        return f"relativer Link «{ziel}» zeigt auf eine fehlende Datei oder ein fehlendes Verzeichnis"
    return None


def _doku_dateien(root: Path) -> list[Path]:
    """Versionierte Markdown-Dateien; der Vault ist generiert und zählt nicht."""
    if (root / ".git").exists():
        try:
            roh = subprocess.check_output(
                ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
                stderr=subprocess.DEVNULL,
            )
            return sorted(root / p for p in roh.decode("utf-8").split("\0") if p)
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            pass
    return sorted(
        p for p in root.rglob("*.md")
        if not any(teil in SKIP_DIRS for teil in p.relative_to(root).parts[:-1])
    )


def pruefe(root: Path) -> tuple[list[Path], int, list[str]]:
    dateien = _doku_dateien(root)
    befunde: list[str] = []
    link_anzahl = 0
    for datei in dateien:
        rel = datei.relative_to(root)
        try:
            text = datei.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as fehler:
            befunde.append(f"{rel}: konnte nicht gelesen werden ({fehler})")
            continue

        for zeile, ziel in _relative_ziele(text):
            link_anzahl += 1
            befund = _pruefe_link(root, datei, ziel)
            if befund:
                befunde.append(f"{rel}:{zeile}: {befund}")

        for nummer, zeile in enumerate(text.splitlines(), 1):
            for muster, name in VERALTETE_BEGRIFFE:
                if muster.search(zeile):
                    befunde.append(f"{rel}:{nummer}: veralteter Raumschiff-Begriff «{name}»")
    return dateien, link_anzahl, befunde


def negativtest() -> int:
    """Prüft, dass ein kaputter Link und ein alter Decks-Begriff auffallen."""
    with tempfile.TemporaryDirectory(prefix="orakel-doku-") as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "ok.md").write_text("# Gültiges Ziel\n", encoding="utf-8")
        (root / "README.md").write_text(
            "[gültig](docs/ok.md)\n"
            "[fehlt](docs/fehlt.md)\n"
            "Das Schiff hat drei Decks.\n",
            encoding="utf-8",
        )
        dateien, link_anzahl, befunde = pruefe(root)
        link_fehler = any("fehlende Datei" in befund for befund in befunde)
        begriff_fehler = any("veralteter Raumschiff-Begriff" in befund for befund in befunde)
        if not link_fehler or not begriff_fehler:
            print(
                "Dokutest FEHLGESCHLAGEN: erwartet wurden ein fehlender Link und "
                f"ein veralteter Begriff, gefunden: {befunde or 'keine Befunde'}",
                file=sys.stderr,
            )
            return 1
        print(
            f"Dokutest OK: {len(dateien)} Dateien, {link_anzahl} relative Links, "
            "fehlender Link und veralteter Raumschiff-Begriff erkannt"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prüft relative Doku-Links und veraltete Raumschiff-Begriffe.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository-Wurzel (Standard: Projektordner)")
    parser.add_argument("--negativtest", action="store_true", help="Prüft die Prüfung mit absichtlich falschen Doku-Daten")
    args = parser.parse_args()
    if args.negativtest:
        return negativtest()

    dateien, link_anzahl, befunde = pruefe(args.root.resolve())
    for befund in befunde:
        print(befund, file=sys.stderr)
    if befunde:
        print(f"Doku-Prüfung fehlgeschlagen: {len(befunde)} Befund(e)", file=sys.stderr)
        return 1
    print(
        f"Doku OK: {len(dateien)} Dateien, {link_anzahl} relative Links und "
        "0 veraltete Raumschiff-Begriffe geprüft"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
