#!/usr/bin/env python3
"""Prüft relative Markdown-Links, Pflichtverweise, Markdown- und HTML-Anker, alte Schiffsbegriffe und englische Altnamen der Agentenabteilungen.

Der Lauf ist bewusst ohne Zusatzpakete nutzbar, damit er in der CI schnell
bleibt. Relative Pfade werden vom jeweiligen Dokument aus aufgelöst. Bei
Links mit Sprungmarke wird zusätzlich geprüft, ob die Zielseite eine
passende Markdown-Überschrift oder HTML-Überschrift mit id-Attribut besitzt.
Weblinks und Mailto-Links werden übersprungen.
"""
from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
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

# Englische Namen, die durch die deutschen Abteilungsnamen ersetzt wurden.
# B «Spider Intelligence» und D «Trading Floor» sind weiterhin aktuell und
# stehen deshalb nicht in dieser Liste.
ENGLISCHE_ALTNAMEN = (
    (re.compile(r"\bCommand Center\b", re.IGNORECASE), "Command Center"),
    (re.compile(r"\bInnovation Laboratory\b", re.IGNORECASE), "Innovation Laboratory"),
    (re.compile(r"\bResearch Department\b", re.IGNORECASE), "Research Department"),
    (re.compile(r"\bRisk Management\b", re.IGNORECASE), "Risk Management"),
    (re.compile(r"\bKnowledge Center\b", re.IGNORECASE), "Knowledge Center"),
    (re.compile(r"\bEngineering Department\b", re.IGNORECASE), "Engineering Department"),
    (re.compile(r"\bGlobal Intelligence Observatory\b", re.IGNORECASE), "Global Intelligence Observatory"),
    (re.compile(r"\bSecurity Operations\b", re.IGNORECASE), "Security Operations"),
    (re.compile(r"\bExecutive Secretariat\b", re.IGNORECASE), "Executive Secretariat"),
)

# Diese älteren Planungsdokumente beschreiben den historischen 3D-Prototyp
# und die damaligen englischen Raumnamen. Sie sind keine aktuelle Agentendoku.
HISTORISCHE_DOKUMENTE = {
    Path("docs/raumschiff/MASTERPLAN.md"),
    Path("docs/raumschiff/RAUMBUCH.md"),
}

# Diese Dokumente müssen aus einem sichtbaren Einstieg verlinkt bleiben.
PFLICHT_VERWEISE = (
    (Path("README.md"), Path("docs/pr-schutz.md")),
)

INLINE_LINK = re.compile(
    r"!?\[[^\]]*\]\(\s*(<[^>]+>|[^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\s*\)"
)
REFERENCE_LINK = re.compile(
    r"^[ \t]{0,3}\[[^\]]+\]:[ \t]*(<[^>]+>|\S+)", re.MULTILINE
)
REFERENZ_DEFINITION = re.compile(
    r"^[ \t]{0,3}\[([^\]]+)\]:[ \t]*(<[^>]+>|\S+)", re.MULTILINE
)
REFERENZ_VERWENDUNG = re.compile(r"(?<!!)\[([^\]]*)\]\[([^\]]*)\]")
REFERENZ_KURZ = re.compile(r"(?<![!\]])\[([^\]]+)\](?!\s*:)(?![\[(])")
HTML_LINK = re.compile(
    r"\b(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE
)
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
ATX_HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+[ \t]*)?$")
SETEXT_HEADING = re.compile(r"^[ \t]{0,3}(=+|-+)[ \t]*$")
HTML_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _HtmlAnkerParser(HTMLParser):
    """Sammelt explizite id-Attribute von HTML-Überschriften."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anker: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() not in HTML_HEADING_TAGS:
            return
        for name, wert in attrs:
            if name.lower() != "id" or wert is None:
                continue
            wert = html.unescape(wert).strip()
            if wert:
                self.anker.add(wert)


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


def _html_ueberschriften_anker(text: str) -> set[str]:
    """Liefert explizite id-Attribute aus HTML-Überschriften."""
    parser = _HtmlAnkerParser()
    parser.feed(_maskiere_code(text))
    parser.close()
    return parser.anker


def _ueberschriften_anker(text: str) -> set[str]:
    """Bildet die Anker der Überschriften einer Datei.

    Markdown-Überschriften erhalten GitHub-ähnliche Anker. HTML-Überschriften
    zählen über ihr explizites id-Attribut. Fenced Code, Inline-Code und
    HTML-Kommentare dürfen keine Scheinüberschriften beisteuern; einfache
    Hervorhebungen werden für den Anker wie gerenderter Text behandelt.
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
    anker.update(_html_ueberschriften_anker(text))
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


def _relative_ziele(
    text: str, *, ohne_bilder: bool = False, ohne_definitionen: bool = False
):
    """Liefert (Zeilennummer, Ziel) für alle lokalen Linkziele.

    Mit ``ohne_bilder`` bleiben Bildreferenzen (``![]()`` und ``<img src>``)
    außen vor; mit ``ohne_definitionen`` werden Referenzdefinitionen
    ausgelassen. Für den Pflichtverweis zählt nur ein sichtbarer Link.
    """
    maskiert = _maskiere_code(text)
    for muster in (INLINE_LINK, REFERENCE_LINK, HTML_LINK):
        for treffer in muster.finditer(maskiert):
            if ohne_bilder:
                roh = treffer.group(0).lstrip()
                if roh.startswith("!") or roh.lower().startswith("src"):
                    continue
            if ohne_definitionen and muster is REFERENCE_LINK:
                continue
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


def _normalisiere_referenz(label: str) -> str:
    return " ".join(label.split()).casefold()


def _referenzziele(text: str) -> list[str]:
    """Liefert Ziele tatsächlich verwendeter Referenzlinks."""
    sichtbar = _maskiere_code(text)
    definitionen: dict[str, str] = {}
    for treffer in REFERENZ_DEFINITION.finditer(sichtbar):
        label = _normalisiere_referenz(treffer.group(1))
        ziel = treffer.group(2).strip()
        if ziel.startswith("<") and ziel.endswith(">"):
            ziel = ziel[1:-1].strip()
        if label and ziel:
            definitionen.setdefault(label, ziel)

    ziele: list[str] = []
    for treffer in REFERENZ_VERWENDUNG.finditer(sichtbar):
        label = treffer.group(2).strip() or treffer.group(1)
        ziel = definitionen.get(_normalisiere_referenz(label))
        if ziel:
            ziele.append(ziel)
    for treffer in REFERENZ_KURZ.finditer(sichtbar):
        ziel = definitionen.get(_normalisiere_referenz(treffer.group(1)))
        if ziel:
            ziele.append(ziel)
    return ziele


def _lokales_linkziel(root: Path, datei: Path, ziel: str) -> Path | None:
    """Löst ein lokales Linkziel für den Pflichtverweis auf."""
    pfad = unquote(ziel.partition("#")[0].split("?", 1)[0])
    if not pfad:
        return None
    try:
        kandidat = (root / pfad.lstrip("/")) if pfad.startswith("/") else (datei.parent / pfad)
        return kandidat.resolve()
    except OSError:
        return None


def _pruefe_pflicht_verweise(root: Path) -> list[str]:
    """Prüft, dass zentrale Dokumente aus ihrem Einstieg verlinkt bleiben."""
    befunde: list[str] = []
    for quelle, ziel in PFLICHT_VERWEISE:
        datei = root / quelle
        ziel_datei = root / ziel
        if not ziel_datei.is_file():
            befunde.append(f"{quelle}: Pflichtziel «{ziel}» fehlt")
            continue
        try:
            text = datei.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as fehler:
            befunde.append(f"{quelle}: konnte für Pflichtverweis nicht gelesen werden ({fehler})")
            continue
        erwartet = ziel_datei.resolve()
        ziele = [
            link
            for _, link in _relative_ziele(
                text, ohne_bilder=True, ohne_definitionen=True
            )
        ]
        ziele.extend(_referenzziele(text))
        verlinkt = any(_lokales_linkziel(root, datei, ziel) == erwartet for ziel in ziele)
        if not verlinkt:
            befunde.append(f"{quelle}: Pflichtverweis auf «{ziel}» fehlt")
    return befunde


def _doku_dateien(root: Path) -> list[Path]:
    """Versionierte Markdown-Dateien; der Vault ist generiert und zählt nicht."""
    if (root / ".git").exists():
        try:
            roh = subprocess.check_output(  # noqa: S603 - Programmaufruf mit fester Argumentliste, ohne Shell
                ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],  # noqa: S607 - Programmname und Argumente sind fest verdrahtet
                stderr=subprocess.DEVNULL,
            )
            return sorted(root / p for p in roh.decode("utf-8").split("\0") if p)
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
            pass
    return sorted(
        p for p in root.rglob("*.md")
        if not any(teil in SKIP_DIRS for teil in p.relative_to(root).parts[:-1])
    )


def pruefe(root: Path) -> tuple[list[Path], int, int, list[str]]:
    dateien = _doku_dateien(root)
    befunde: list[str] = []
    link_anzahl = 0
    anker_anzahl = 0
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
                continue
            pfad_teil, _, anker = ziel.partition("#")
            pfad = pfad_teil.split("?", 1)[0]
            if anker.strip() and (
                not pfad
                or unquote(pfad).lower().endswith(".md")
            ):
                anker_anzahl += 1

        for nummer, zeile in enumerate(text.splitlines(), 1):
            for muster, name in VERALTETE_BEGRIFFE:
                if muster.search(zeile):
                    befunde.append(f"{rel}:{nummer}: veralteter Raumschiff- oder Navigationsbegriff «{name}»")
            if rel not in HISTORISCHE_DOKUMENTE:
                for muster, name in ENGLISCHE_ALTNAMEN:
                    if muster.search(zeile):
                        befunde.append(f"{rel}:{nummer}: englischer Altname der Agentenabteilung «{name}»")
    befunde.extend(_pruefe_pflicht_verweise(root))
    return dateien, link_anzahl, anker_anzahl, befunde


def negativtest() -> int:
    """Prüft, dass kaputte Links, falsche Anker und alte Decks-Begriffe auffallen."""
    with tempfile.TemporaryDirectory(prefix="orakel-doku-") as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        (root / "docs" / "ok.md").write_text(
            "# Gültiges Ziel\n"
            "## 1. Test (Anker)\n"
            "## Use _italics_\n"
            "## foo_bar\n"
            "## Gültiges Ziel\n"
            "<h2 id=\"html-anker\">HTML-Anker</h2>\n"
            "<h3 id='html-einfach'>HTML-Anker mit einfachen Anführungszeichen</h3>\n"
            "<H4 ID=\"html-gross\">HTML-Anker in Grossschreibung</H4>\n"
            "<h2 id=\"html-anderer\">HTML-Text ist kein Anker</h2>\n"
            "```html\n"
            "<h2 id=\"html-im-code\">Kein Anker im Code</h2>\n"
            "```\n",
            encoding="utf-8",
        )
        (root / "docs" / "pr-schutz.md").write_text(
            "# Schutz von `main`\n",
            encoding="utf-8",
        )
        (root / "README.md").write_text(
            "# Haupt\n"
            "[Schutz](docs/pr-schutz.md)\n"
            "[gültig](docs/ok.md)\n"
            "[gültiger Dateianker](docs/ok.md#gültiges-ziel)\n"
            "[gültiger kodierter Anker](docs/ok.md#g%C3%BCltiges-ziel)\n"
            "[gültiger doppelter Anker](docs/ok.md#gültiges-ziel-1)\n"
            "[gültiger Satzzeichen-Anker](docs/ok.md#1-test-anker)\n"
            "[gültiger Kursiv-Anker](docs/ok.md#use-italics)\n"
            "[gültiger Unterstrich-Anker](docs/ok.md#foo_bar)\n"
            "[gültiger HTML-Anker](docs/ok.md#html-anker)\n"
            "[gültiger HTML-Anker mit einfachen Anführungszeichen](docs/ok.md#html-einfach)\n"
            "[gültiger HTML-Anker in Grossschreibung](docs/ok.md#html-gross)\n"
            "[gültiger Direktanker](#haupt)\n"
            "[fehlt](docs/fehlt.md)\n"
            "[falscher Dateianker](docs/ok.md#fehlt)\n"
            "[falscher HTML-Textanker](docs/ok.md#html-text-ist-kein-anker)\n"
            "[falscher HTML-Anker im Code](docs/ok.md#html-im-code)\n"
            "[falscher Direktanker](#fehlt)\n"
            "Das Schiff hat drei Decks.\n"
            "Die Deckkarte zeigt acht Stationen.\n"
            "Das Schiffsdeck ist alt.\n"
            "Der Navigationspunkt **Nexus** ist entfernt.\n"
            "Der Navigationspunkt **Agentenraum** ist entfernt.\n"
            "Der Navigationspunkt **Command-Center** ist entfernt.\n"
            "Die Kommandozentrale ist geschlossen.\n"
            "Die Abteilung Command Center wurde umbenannt.\n"
            "Die Abteilung Innovation Laboratory wurde umbenannt.\n"
            "Die Abteilung Research Department wurde umbenannt.\n"
            "Die Abteilung Risk Management wurde umbenannt.\n"
            "Die Abteilung Knowledge Center wurde umbenannt.\n"
            "Die Abteilung Engineering Department wurde umbenannt.\n"
            "Die Abteilung Global Intelligence Observatory wurde umbenannt.\n"
            "Die Abteilung Security Operations wurde umbenannt.\n"
            "Die Abteilung Executive Secretariat wurde umbenannt.\n",
            encoding="utf-8",
        )
        dateien, link_anzahl, anker_anzahl, befunde = pruefe(root)
        pflicht_bei_vorhandenem_link = [
            befund for befund in befunde if "Pflichtverweis" in befund
        ]
        readme = root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace(
                "[Schutz](docs/pr-schutz.md)\n", "", 1
            ),
            encoding="utf-8",
        )
        _, _, _, befunde_ohne_link = pruefe(root)
        pflicht_fehler = [
            befund for befund in befunde_ohne_link if "Pflichtverweis" in befund
        ]
        link_fehler = any("fehlende Datei" in befund for befund in befunde)
        anker_fehler = [befund for befund in befunde if "Überschriften-Anker" in befund]
        begriff_fehler = [befund for befund in befunde if "veralteter Raumschiff- oder Navigationsbegriff" in befund]
        altnamen_fehler = [befund for befund in befunde if "englischer Altname der Agentenabteilung" in befund]
        if (
            not link_fehler
            or pflicht_bei_vorhandenem_link
            or len(pflicht_fehler) != 1
            or len(anker_fehler) != 4
            or len(begriff_fehler) != 7
            or len(altnamen_fehler) != 9
            or anker_anzahl < 1
        ):
            print(
                "Dokutest FEHLGESCHLAGEN: erwartet wurden ein fehlender Link, "
                "ein fehlender Pflichtverweis, vier falsche Anker, sieben "
                "veraltete Begriffe, neun englische Altnamen und mindestens "
                "ein gültiger Ankerlink, gefunden: "
                f"{befunde_ohne_link or 'keine Befunde'} (gültige Ankerlinks: {anker_anzahl})",
                file=sys.stderr,
            )
            return 1
        print(
            f"Dokutest OK: {len(dateien)} Dateien, {link_anzahl} relative Links, "
            f"{anker_anzahl} gültige Ankerlinks, fehlender Link, fehlender "
            "Pflichtverweis, vier falsche Anker, sieben veraltete Raumschiff- "
            "und Navigationsbegriffe sowie neun englische Altnamen erkannt"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Prüft relative Doku-Links, Pflichtverweise, Markdown- und HTML-Anker, veraltete Raumschiff- und Navigationsbegriffe sowie englische Altnamen der Agentenabteilungen.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository-Wurzel (Standard: Projektordner)")
    parser.add_argument("--negativtest", action="store_true", help="Prüft die Prüfung mit absichtlich falschen Doku-Daten")
    args = parser.parse_args()
    if args.negativtest:
        return negativtest()

    dateien, link_anzahl, anker_anzahl, befunde = pruefe(args.root.resolve())
    for befund in befunde:
        print(befund, file=sys.stderr)
    if befunde:
        print(f"Doku-Prüfung fehlgeschlagen: {len(befunde)} Befund(e)", file=sys.stderr)
        return 1
    if anker_anzahl < 1:
        print(
            "Doku-Prüfung fehlgeschlagen: kein gültiger Ankerlink in der Dokumentation gefunden",
            file=sys.stderr,
        )
        return 1
    anker_wort = "gültiger Ankerlink" if anker_anzahl == 1 else "gültige Ankerlinks"
    print(
        f"Doku OK: {len(dateien)} Dateien, {link_anzahl} relative Links, "
        f"{anker_anzahl} {anker_wort}, 0 veraltete Raumschiff- und "
        "Navigationsbegriffe sowie 0 englische Altnamen geprüft"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
