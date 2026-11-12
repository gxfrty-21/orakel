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
        return ziel

    def index(self, eintraege: dict[str, int]) -> Path:
        zeilen = ["# Wissenszentrum", "", f"Stand: {_jetzt()}", "", "| Bereich | Notizen |", "|---|---|"]
        zeilen += [f"| {name} | {anzahl} |" for name, anzahl in eintraege.items()]
        ziel = self.wurzel / ORDNER["index"] / "index.md"
        ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        return ziel

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
