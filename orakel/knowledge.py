from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ORDNER = {
    "index": "00-Index",
    "daten": "10-Daten",
    "strategien": "20-Strategien",
    "validierungen": "30-Validierungen",
    "entscheide": "40-Entscheide",
    "konferenz": "50-Konferenz",
    "fehler": "60-Fehler",
    "wissen": "70-Wissen",
}


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß\- ]+", "", text).strip().replace(" ", "-")
    return re.sub(r"-{2,}", "-", s)[:80].lower() or "notiz"


def _jetzt() -> str:
    return datetime.now(timezone.utc).astimezone().replace(microsecond=0).isoformat()


def _ohne_frontmatter(text: str) -> str:
    if text.startswith("---"):
        ende = text.find("\n---", 3)
        if ende != -1:
            return text[ende + 4:]
    return text


def _wikilinks(text: str) -> list[str]:
    """Liest Obsidian-Wikilinks aus dem Notiztext, ohne Codeblöcke."""
    ohne_code = re.sub(r"```.*?```", " ", text, flags=re.S)
    return [m.group(1).strip() for m in re.finditer(r"!?\[\[([^\]]+)\]\]", ohne_code)]


def _auszug(text: str, limit: int = 220) -> str:
    """Kurzer, lesbarer Text für die Knotenvorschau."""
    text = _ohne_frontmatter(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"!?\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_>`]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


class Vault:
    """Obsidian-kompatibles Langzeitgedächtnis.

    Jede Notiz hat Frontmatter, Tags und [[Links]]. Gleiche Titel überschreiben
    sich, damit keine Duplikate entstehen.
    """

    def __init__(self, ordner: str | Path) -> None:
        self.wurzel = Path(ordner)
        self.wurzel.mkdir(parents=True, exist_ok=True)
        for unter in ORDNER.values():
            (self.wurzel / unter).mkdir(parents=True, exist_ok=True)

    def notiz(
        self,
        kategorie: str,
        titel: str,
        inhalt: str,
        tags: Iterable[str] = (),
        quelle: str | None = None,
        verlinkt: Iterable[str] = (),
    ) -> Path:
        unter = ORDNER.get(kategorie, ORDNER["wissen"])
        ziel = self.wurzel / unter / f"{_slug(titel)}.md"
        kopf = [
            "---",
            f"titel: {json.dumps(titel, ensure_ascii=False)}",
            f"erstellt: {_jetzt()}",
            f"kategorie: {kategorie}",
            f"tags: [{', '.join(sorted({t for t in tags if t}))}]",
        ]
        if quelle:
            kopf.append(f"quelle: {json.dumps(quelle, ensure_ascii=False)}")
        kopf.append("---")
        text = "\n".join(kopf) + f"\n\n# {titel}\n\n{inhalt.strip()}\n"
        if verlinkt:
            text += "\n## Verknüpft\n" + "\n".join(
                f"- [[{_slug(v)}|{v}]]" for v in verlinkt if v
            ) + "\n"
        ziel.write_text(text, encoding="utf-8")
        # Die Übersicht soll nie hinter dem Vault zurückbleiben.
        self.index(self.zaehle())
        return ziel

    def index(self, eintraege: dict[str, int]) -> Path:
        zeilen = ["# Wissenszentrum", "", f"Stand: {_jetzt()}", "", "| Bereich | Notizen |", "|---|---|"]
        zeilen += [f"| {name} | {anzahl} |" for name, anzahl in eintraege.items()]
        ziel = self.wurzel / ORDNER["index"] / "index.md"
        ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        return ziel

    def graph(self) -> dict[str, Any]:
        """Baut einen Obsidian-Graphen aus den echten Markdown-Notizen.

        Nur vorhandene Notizen und echte Wikilinks werden zu Knoten und Kanten.
        Ein Link auf eine fehlende Notiz bleibt als unaufgelöster Knoten sichtbar.
        """
        notizen: list[dict[str, Any]] = []
        fehler: list[str] = []
        for kategorie, unter in ORDNER.items():
            for pfad in sorted((self.wurzel / unter).glob("*.md")):
                try:
                    text = pfad.read_text(encoding="utf-8")
                except Exception as exc:
                    fehler.append(f"{pfad.name}: {exc}")
                    continue
                titel = pfad.stem
                m = re.search(r"^titel:\s*(.*)$", text, re.M)
                if m:
                    try:
                        titel = str(json.loads(m.group(1)))
                    except Exception:
                        titel = m.group(1).strip().strip('"') or titel
                tags: list[str] = []
                m = re.search(r"^tags:\s*\[(.*?)\]\s*$", text, re.M)
                if m:
                    tags = [t.strip().strip("'\"") for t in m.group(1).split(",") if t.strip()]
                erstellt = None
                m = re.search(r"^erstellt:\s*(.*)$", text, re.M)
                if m:
                    erstellt = m.group(1).strip() or None
                rel = pfad.relative_to(self.wurzel).as_posix()
                notizen.append({
                    "id": rel, "titel": titel, "ordner": unter, "kategorie": kategorie,
                    "tags": tags, "erstellt": erstellt, "pfad": rel,
                    "auszug": _auszug(text), "_text": text, "unaufgeloest": False,
                    "ausgehend": 0, "eingehend": 0, "grad": 0,
                })

        nach_stamm: dict[str, list[str]] = {}
        nach_pfad: dict[str, str] = {}
        nach_id = {n["id"]: n for n in notizen}
        for n in notizen:
            p = Path(n["id"])
            nach_pfad[p.with_suffix("").as_posix().casefold()] = n["id"]
            nach_stamm.setdefault(p.stem.casefold(), []).append(n["id"])

        kanten: list[dict[str, str]] = []
        gesehen: set[tuple[str, str]] = set()
        unaufgeloest: dict[str, dict[str, Any]] = {}
        for n in notizen:
            for roh in _wikilinks(n.pop("_text", "")):
                ziel = roh.split("|", 1)[0].split("#", 1)[0].strip()
                if not ziel or ziel.startswith("^"):
                    continue
                schluessel = ziel.replace("\\", "/").removeprefix("./").removesuffix(".md").casefold()
                ziel_id = nach_pfad.get(schluessel)
                if ziel_id is None:
                    kandidaten = nach_stamm.get(Path(schluessel).stem.casefold(), [])
                    ziel_id = sorted(kandidaten)[0] if kandidaten else None
                if ziel_id is None:
                    kurz = re.sub(r"[^a-z0-9äöüß-]+", "-", schluessel).strip("-") or "unbekannt"
                    ziel_id = f"unaufgeloest:{kurz}"
                    unaufgeloest.setdefault(ziel_id, {
                        "id": ziel_id, "titel": ziel, "ordner": "Unaufgelöst",
                        "kategorie": "unaufgeloest", "tags": [], "erstellt": None,
                        "pfad": None, "auszug": "", "unaufgeloest": True,
                        "ausgehend": 0, "eingehend": 0, "grad": 0,
                    })
                if ziel_id == n["id"] or (n["id"], ziel_id) in gesehen:
                    continue
                gesehen.add((n["id"], ziel_id))
                kanten.append({"von": n["id"], "nach": ziel_id, "art": "wikilink"})
                n["ausgehend"] += 1
                if ziel_id in unaufgeloest:
                    unaufgeloest[ziel_id]["eingehend"] += 1
                else:
                    nach_id[ziel_id]["eingehend"] += 1

        knoten = notizen + list(unaufgeloest.values())
        for n in knoten:
            n["grad"] = n["ausgehend"] + n["eingehend"]
        ordner = [{"name": unter, "anzahl": sum(1 for n in notizen if n["ordner"] == unter)}
                  for unter in ORDNER.values()]
        ordner = [o for o in ordner if o["anzahl"]]
        ohne = sum(1 for n in notizen if n["grad"] == 0)
        hinweis = ""
        if not notizen:
            hinweis = "Der Vault enthält noch keine Markdown-Notizen."
        elif not kanten:
            hinweis = "Noch keine Wikilinks im Vault; der Graph zeigt nur Einzelnotizen."
        return {
            "generiert": _jetzt(),
            "knoten": knoten,
            "kanten": kanten,
            "ordner": ordner,
            "statistik": {
                "notizen": len(notizen), "links": len(kanten),
                "unaufgeloest": len(unaufgeloest), "ohne_verknuepfung": ohne,
            },
            "hinweis": hinweis,
            "fehler": fehler,
        }

    def notizen(self, kategorie: str, limit: int = 50) -> list[dict[str, Any]]:
        """Liest Notizen einer Kategorie, neueste zuerst (nur Frontmatter + Text)."""
        unter = ORDNER.get(kategorie, ORDNER["wissen"])
        dateien = sorted((self.wurzel / unter).glob("*.md"),
                         key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        raus: list[dict[str, Any]] = []
        for pfad in dateien:
            text = pfad.read_text(encoding="utf-8")
            titel, erstellt, tags = pfad.stem, None, []
            m = re.search(r"^titel: (.*)$", text, re.M)
            if m:
                try:
                    titel = json.loads(m.group(1))
                except Exception:
                    pass
            m = re.search(r"^tags: \[(.*)\]$", text, re.M)
            if m:
                tags = [t.strip() for t in m.group(1).split(",") if t.strip()]
            m = re.search(r"^erstellt: (.*)$", text, re.M)
            if m:
                erstellt = m.group(1).strip()
            raus.append({"titel": titel, "erstellt": erstellt, "tags": tags,
                         "text": text, "pfad": str(pfad)})
        return raus

    def zaehle(self) -> dict[str, int]:
        raus: dict[str, int] = {}
        for kategorie, unter in ORDNER.items():
            raus[kategorie] = len(list((self.wurzel / unter).glob("*.md")))
        return raus
