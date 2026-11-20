#!/usr/bin/env python3
"""Legt einen deterministischen Widerspruch für den Browser-E2E-Test an.

Das Skript arbeitet auf einer Kopie der Seed-Datenbank. Es speichert zwei
gegenläufige Meldungen über den normalen Nexus-Pfad und baut Claims,
Widersprüche und Quellenreputation mit ``claims_auffrischen`` neu auf. Damit
enthält die Testdatenbank genau die Daten, die später über API und Karte
geprüft werden.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orakel.kern.db import Facts
from orakel.nexus.bewertung import claims_auffrischen
from orakel.nexus.dedup import titel_hash
from orakel.nexus.quellen import Quelle

ZEIT = "2026-11-10T05:00:00+00:00"
GRUND = "Richtung steigt gegen sinkt"
QUELLE_A = "e2e-a.example"
QUELLE_B = "e2e-b.example"


def _quelle(kennung: str, host: str) -> Quelle:
    return Quelle(
        id=kennung,
        name=f"E2E Quelle {kennung}",
        typ="rss",
        url=f"https://{host}/feed.xml",
        land="DE",
        sprache="de",
        thema="test",
        gewicht=0.8,
    )


def _meldung(db: Facts, key: str, quelle: Quelle, titel: str, url: str) -> None:
    artikel_id = db.artikel_speichern(
        quelle.name, "rss", titel, url, None, titel, 0.8, [], titel_hash(titel)
    )
    if artikel_id is None:
        raise RuntimeError(f"Testmeldung {key} ist bereits vorhanden")
    gespeichert = db.nexus_meldung_speichern(
        key, artikel_id, key, "0" * 16, "de", 0.9, "test", True,
        quelle.id, titel, titel, url, ZEIT,
    )
    if not gespeichert:
        raise RuntimeError(f"Testmeldung {key} konnte nicht gespeichert werden")


def seed(db_pfad: Path) -> dict[str, object]:
    db_pfad.parent.mkdir(parents=True, exist_ok=True)
    db = Facts(db_pfad)
    quelle_a = _quelle("e2e-a", QUELLE_A)
    quelle_b = _quelle("e2e-b", QUELLE_B)
    _meldung(
        db, "e2e-a", quelle_a,
        "EZB hebt den Leitzins auf 4,5 Prozent",
        f"https://{QUELLE_A}/meldung-a",
    )
    _meldung(
        db, "e2e-b", quelle_b,
        "EZB senkt den Leitzins auf 4,0 Prozent",
        f"https://{QUELLE_B}/meldung-b",
    )

    ergebnis = claims_auffrischen(db, [quelle_a, quelle_b])
    passende = [
        w for w in db.nexus_widersprueche(50)
        if w["grund"] == GRUND
        and w["quelle_a"] == QUELLE_A
        and w["quelle_b"] == QUELLE_B
        and w["wert_a_bp"] == 450.0
        and w["wert_b_bp"] == 400.0
    ]
    if len(passende) != 1:
        raise RuntimeError(
            f"Erwartet genau einen Testwiderspruch, gefunden: {len(passende)}"
        )
    widerspruch = passende[0]
    return {
        "claim_id": widerspruch["claim_id"],
        "kernaussage": widerspruch["kernaussage"],
        "grund": widerspruch["grund"],
        "sicherheit": widerspruch["sicherheit"],
        "quelle_a": widerspruch["quelle_a"],
        "quelle_b": widerspruch["quelle_b"],
        "wert_a_bp": widerspruch["wert_a_bp"],
        "wert_b_bp": widerspruch["wert_b_bp"],
        "bewertung": {
            "kernaussagen": ergebnis["kernaussagen"],
            "widersprueche": ergebnis["widersprueche"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path, help="Ziel-Datenbank (muss eine Kopie sein)")
    args = parser.parse_args()
    if not args.db.exists():
        parser.error("Die Ziel-Datenbank existiert nicht; bitte zuerst eine Seed-Kopie anlegen")
    try:
        erwartet = seed(args.db)
    except RuntimeError as exc:
        print(f"Seed FEHLER: {exc}", file=sys.stderr)
        return 1
    print("Seed OK: " + json.dumps(erwartet, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
