#!/usr/bin/env python3
"""Prüft relative Markdown-Links, Überschriften-Anker und veraltete Schiffsbegriffe.

Der Lauf ist bewusst ohne Zusatzpakete nutzbar, damit er in der CI schnell
bleibt. Relative Pfade werden vom jeweiligen Dokument aus aufgelöst. Bei
Links mit Sprungmarke wird zusätzlich geprüft, ob die Zielseite eine
passende Überschrift besitzt. Weblinks und Mailto-Links werden übersprungen.
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    ".git", ".venv", "node_modules", "artifacts", "__pycache__",
    ".pytest_cache", ".next", "dist", "build", "target",
}

# Begriffe, die eine frühere Decks-Zählung oder Navigation beschreiben. Die
# aktuellen Planungsdokumente dürfen historische acht Decks erwähnen, solange
# sie klar als Planung gekennzeichnet sind; diese konkreten Kurzformen sind
# dagegen irreführend für die aktuelle 103-Raum-Ansicht.
VERALTETE_BEGRIFFE = (
    (re.compile(r"\b(?:drei|3)\s+Decks?\b", re.IGNORECASE), "drei Decks"),
    (re.compile(r"\b(?:zwei|2)\s+Decks?\b", re.IGNORECASE), "zwei Decks"),
    (re.compile(r"\bDecks?\s+[ABC]\b", re.IGNORECASE), "Deck A/B/C"),
    (re.compile(r"\bSchiffsdecks?\b", re.IGNORECASE), "Schiffsdeck"),
    (re.compile(r"\bDecks?karte\b", re.IGNORECASE), "Deckkarte"),
    (re.compile(r"\bKommandozentrale\b", re.IGNORECASE), "Kommandozentrale"),
    (re.compile(
        r"\bNavigationspunkt\s+\**(?:Nexus|Command[- ]Center|Agentenraum|Konferenz)\b",
        re.IGNORECASE,
    ), "veralteter Navigationspunkt"),
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
ATX_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$")
SETEXT_HEADING = re.compile(r"^[ \t]{0,3}(=+|-+)[ \t]*$")


def _blank(text: str) -> str:
    """Ersetzt Zeichen durch Leerzeichen, behält aber Zeilenumbrüche."""
    return re.sub(r"[^\n]", " ", text)


def _maskiere_fenced(text: str) -> str:
    """Blendet Fenced Code aus, ohne Zeilenumbrüche zu verschieben."""
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
    return "".join(zeilen)


def _maskiere_kommentare(text: str) -> str:
    return re.sub(r"<!--.*?-->", lambda m: _blank(m.group(0)), text, flags=re.DOTALL)


def _maskiere_code(text: str) -> str:
    """Blendet Fenced Code, Inline-Code und HTML-Kommentare aus."""
    text = _maskiere_fenced(text)
    text = _maskiere_kommentare(text)
    text = re.sub(r"`+[^`\n]*`+", lambda m: _blank(m.group(0)), text)
    return text


def _sichtbar_im_markdown(text: str) -> str:
    """Lässt Markdown sichtbar, entfernt aber Codeblöcke und Kommentare."""
    return _maskiere_kommentare(_maskiere_fenced(text))


def _ueberschriften_anker(text: str) -> set[str]:
    """Bildet die GitHub-ähnlichen Anker der Überschriften einer Datei.

    Fenced Code darf keine Scheinüberschriften beisteuern. Inline-Code und
    einfache Hervorhebungen werden für den Anker wie gerenderter Text behandelt.
    """
    sichtbar = _sichtbar_im_markdown(text)
    zeilen = sichtbar.splitlines()
    roh = []
    for index, zeile in enumerate(zeilen):
        treffer = ATX_HEADING.match(zeile)
        if treffer:
            roh.append(treffer.group(2).strip())
            continue
        if (
            index + 1 < len(zeilen)
            and zeile.strip()
            and not SETEXT_HEADING.match(zeile)
            and SETEXT_HEADING.match(zeilen[index + 1])
        ):
            roh.append(zeile.strip())
    anker: set[str] = set()
    for text_roh in roh:
        basis = _slug(text_roh)
        if not basis:
            continue
        wert = basis
        nummer = 0
        while wert in anker:
            nummer += 1
            wert = f"{basis}-{nummer}"
        anker.add(wert)
    return anker


def _slug(text: str) -> str:
    """Erzeugt einen GitHub-ähnlichen Anker aus gerendertem Überschriftentext."""
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", text)
    text = text.replace("`", "")
    for marker in ("**", "__", "~~", "*", "~"):
        text = text.replace(marker, "")
    # Einzelne Unterstriche sind Markdown-kursiv, wenn sie ein Wort einrahmen;
    # Unterstriche innerhalb eines Wortes bleiben dagegen Teil des Textes.
    text = re.sub(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)", r"\1", text)
    text = text.replace("\u00a0", " ").lower().strip()
    zeichen = []
    for zeichen_teil in text:
        if (
            zeichen_teil.isalnum()
            or zeichen_teil in "-_ "
            or unicodedata.combining(zeichen_teil)
        ):
            zeichen.append(zeichen_teil)
    return "".join(zeichen).replace(" ", "-")


def _datei_anker(datei: Path, cache: dict[Path, set[str] | None]) -> set[str] | None:
    schluessel = datei.resolve()
    if schluessel not in cache:
        try:
            cache[schluessel] = _ueberschriften_anker(datei.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            cache[schluessel] = None
    return cache[schluessel]


def _pruefe_anker(
    datei: Path,
    anker: str,
    ziel: str,
    cache: dict[Path, set[str] | None],
) -> str | None:
    vorhanden = _datei_anker(datei, cache)
    if vorhanden is None:
        return f"relativer Link «{ziel}»: Ziel konnte für die Ankerprüfung nicht gelesen werden"
    if unquote(anker).strip() not in vorhanden:
        return f"relativer Link «{ziel}» zeigt auf keinen vorhandenen Überschriften-Anker «{anker}»"
    return None


def _relative_ziele(text: str):
    """Liefert (Zeilennummer, Ziel) für alle lokalen Linkziele."""
    maskiert = _maskiere_code(text)
    for muster in (INLINE_LINK, REFERENCE_LINK, HTML_LINK):
        for treffer in muster.finditer(maskiert):
            ziel = treffer.group(1).strip()
            if ziel.startswith("<") and ziel.endswith(">"):
                ziel = ziel[1:-1].strip()
            if not ziel:
                continue
            if ziel.startswith("//") or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", ziel):
                continue  # http(s), mailto, data usw.
            zeile = text.count("\n", 0, treffer.start()) + 1
            yield zeile, ziel


def _pruefe_link(
    root: Path,
    datei: Path,
    ziel: str,
    anker_cache: dict[Path, set[str] | None],
) -> str | None:
    """Gibt einen Befund zurück, wenn Ziel oder Überschriften-Anker fehlen."""
    pfad_teil, _, anker = ziel.partition("#")
    pfad = unquote(pfad_teil.split("?", 1)[0])
    anker = unquote(anker).strip()
    if not pfad:
        if not anker:
            return None
        return _pruefe_anker(datei, anker, ziel, anker_cache)
    if "{{" in pfad or "${" in pfad:
        return None
    try:
        kandidat = root / pfad.lstrip("/") if pfad.startswith("/") else datei.parent / pfad
        aufgeloest = kandidat.resolve()
        aufgeloest.relative_to(root.resolve())
    except (OSError, ValueError):
        return f"relativer Link «{ziel}» liegt ausserhalb des Repositories"
    if not aufgeloest.exists():
        return f"relativer Link «{ziel}» zeigt auf eine fehlende Datei oder ein fehlendes Verzeichnis"
    if anker and aufgeloest.is_file() and aufgeloest.suffix.lower() == ".md":
        return _pruefe_anker(aufgeloest, anker, ziel, anker_cache)
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
    anker_cache: dict[Path, set[str] | None] = {}
    for datei in dateien:
        rel = datei.relative_to(root)
        try:
            text = datei.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as fehler:
            befunde.append(f"{rel}: konnte nicht gelesen werden ({fehler})")
            continue

        for zeile, ziel in _relative_ziele(text):
            link_anzahl += 1
            befund = _pruefe_link(root, datei, ziel, anker_cache)
            if befund:
                befunde.append(f"{rel}:{zeile}: {befund}")

        for nummer, zeile in enumerate(text.splitlines(), 1):
            for muster, name in VERALTETE_BEGRIFFE:
                if muster.search(zeile):
                    befunde.append(f"{rel}:{nummer}: veralteter Raumschiff- oder Navigationsbegriff «{name}»")
    return dateien, link_anzahl, befunde


def negativtest() -> int:
    """Prüft, dass kaputte Links, falsche Anker und ein alter Decks-Begriff auffallen."""
    with tempfile.TemporaryDirectory(prefix="orakel-doku-") as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "ok.md").write_text(
            "# Gültiges Ziel\n"
            "## 1. Test (Anker)\n"
            "## Use _italics_\n"
            "## foo_bar\n"
            "## Gültiges Ziel\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "# Haupt\n"
            "[gültig](docs/ok.md)\n"
            "[gültiger Dateianker](docs/ok.md#gültiges-ziel)\n"
            "[gültiger kodierter Anker](docs/ok.md#g%C3%BCltiges-ziel)\n"
            "[gültiger doppelter Anker](docs/ok.md#gültiges-ziel-1)\n"
            "[gültiger Satzzeichen-Anker](docs/ok.md#1-test-anker)\n"
            "[gültiger Kursiv-Anker](docs/ok.md#use-italics)\n"
            "[gültiger Unterstrich-Anker](docs/ok.md#foo_bar)\n"
            "[gültiger Direktanker](#haupt)\n"
            "[fehlt](docs/fehlt.md)\n"
            "[falscher Dateianker](docs/ok.md#fehlt)\n"
            "[falscher Direktanker](#fehlt)\n"
            "Das Schiff hat drei Decks.\n"
            "Die Deckkarte zeigt acht Stationen.\n"
            "Das Schiffsdeck ist alt.\n"
            "Der Navigationspunkt **Nexus** ist entfernt.\n"
            "Der Navigationspunkt **Agentenraum** ist entfernt.\n"
            "Der Navigationspunkt **Command Center** ist entfernt.\n"
            "Die Kommandozentrale ist geschlossen.\n",
            encoding="utf-8",
        )
        dateien, link_anzahl, befunde = pruefe(root)
        link_fehler = any("fehlende Datei" in befund for befund in befunde)
        anker_fehler = [befund for befund in befunde if "Überschriften-Anker" in befund]
        begriff_fehler = [befund for befund in befunde if "veralteter Raumschiff- oder Navigationsbegriff" in befund]
        if not link_fehler or len(anker_fehler) != 2 or len(begriff_fehler) != 7:
            print(
                "Dokutest FEHLGESCHLAGEN: erwartet wurden ein fehlender Link, "
                "zwei falsche Anker und sieben veraltete Begriffe, gefunden: "
                f"{befunde or 'keine Befunde'}",
                file=sys.stderr,
            )
            return 1
        print(
            f"Dokutest OK: {len(dateien)} Dateien, {link_anzahl} relative Links, "
            "fehlender Link, zwei falsche Anker und sieben veraltete Raumschiff- und Navigationsbegriffe erkannt"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prüft relative Doku-Links, Überschriften-Anker und veraltete Raumschiff- und Navigationsbegriffe.")
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
        "0 veraltete Raumschiff- und Navigationsbegriffe geprüft"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
