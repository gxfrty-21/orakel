#!/usr/bin/env python3
"""Reproduzierbare Baseline für die Nexus-Claim-Extraktion.

Der Korpus liegt als versionierte JSON-Datei vor und enthält reale RSS-Meldungen
aus dem Seed-Snapshot. Die Baseline nutzt bewusst die aktuelle, produktive
Extraktion; sie ist keine neue Heuristik und keine LLM-Auswertung.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orakel.nexus.bewertung import _aussage_aus_text, _erster_satz

STANDARD_KORPUS = ROOT / "tests" / "fixtures" / "nexus_claim_korpus.json"
FELDER = ("thema", "subjekt", "metrik", "richtung", "wert", "einheit", "negiert")


def lade_korpus(pfad: str | Path = STANDARD_KORPUS) -> dict[str, Any]:
    datei = Path(pfad)
    daten = json.loads(datei.read_text(encoding="utf-8"))
    if not isinstance(daten, dict) or not isinstance(daten.get("meldungen"), list):
        raise ValueError("Korpus braucht ein Objekt mit einer Meldungsliste")
    return daten


def _aktuelle_aussage(meldung: dict[str, Any]) -> dict[str, Any] | None:
    """Genau der heutige Produktivpfad: Titel, sonst erster Satz der Summary."""
    aussage = _aussage_aus_text(str(meldung.get("titel") or ""))
    if aussage is None:
        aussage = _aussage_aus_text(_erster_satz(str(meldung.get("zusammenfassung") or "")))
    return aussage


def _text_normalisieren(wert: object) -> str:
    text = str(wert or "").lower()
    text = (text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


def _subjekt_passt(erwartet: object, vorhergesagt: object) -> bool:
    """Erwartete Subjekt-Tokens müssen im vorhergesagten Subjekt enthalten sein."""
    soll = set(_text_normalisieren(erwartet).split())
    ist = set(_text_normalisieren(vorhergesagt).split())
    return bool(soll) and soll <= ist


def _ist_pp(einheit: object) -> bool:
    """Erkennt die Einheit pp unabhängig von Gross-/Kleinschreibung oder Langform."""
    return _text_normalisieren(einheit) == "pp"


def _feld_passt(feld: str, erwartet: object, vorhergesagt: object) -> bool:
    if feld == "subjekt":
        return _subjekt_passt(erwartet, vorhergesagt)
    if feld == "wert":
        if erwartet is None or vorhergesagt is None:
            return erwartet is None and vorhergesagt is None
        try:
            return abs(float(erwartet) - float(vorhergesagt)) < 1e-9
        except (TypeError, ValueError):
            return False
    if feld == "einheit":
        return _text_normalisieren(erwartet) == _text_normalisieren(vorhergesagt)
    if feld == "negiert":
        return bool(erwartet) is bool(vorhergesagt)
    return _text_normalisieren(erwartet) == _text_normalisieren(vorhergesagt)


def bewerte(korpus: dict[str, Any]) -> dict[str, Any]:
    """Vergleicht die aktuelle Extraktion mit den manuell gesetzten Goldfeldern."""
    meldungen = korpus["meldungen"]
    einzelfaelle: list[dict[str, Any]] = []
    erwartete_claims = 0
    erkannte_claims = 0
    richtige_claims = 0
    falsch_positive = 0
    uebersehene_claims = 0
    erkannt_aber_feldfehler = 0
    pp_erwartet = 0
    pp_vorhergesagt = 0
    pp_richtig = 0
    pp_faelle: list[dict[str, Any]] = []
    feldtreffer = {feld: 0 for feld in FELDER}
    feldgesamt = {feld: 0 for feld in FELDER}

    for meldung in meldungen:
        erwartet = meldung["erwartet"]
        vorhergesagt = _aktuelle_aussage(meldung)
        soll_claim = bool(erwartet["claim"])
        ist_claim = vorhergesagt is not None
        erwartete_claims += int(soll_claim)
        erkannte_claims += int(ist_claim)

        soll_pp = soll_claim and _ist_pp(erwartet.get("einheit"))
        ist_pp = ist_claim and _ist_pp(vorhergesagt.get("einheit")) if vorhergesagt else False
        pp_erwartet += int(soll_pp)
        pp_vorhergesagt += int(ist_pp)
        if soll_pp and ist_pp:
            pp_richtig += 1
        if soll_pp or ist_pp:
            if soll_pp and not ist_pp:
                pp_abweichung = "pp nicht erkannt"
            elif not soll_pp and ist_pp:
                pp_abweichung = "unerwartete pp-Einheit"
            else:
                pp_abweichung = "–"
            pp_faelle.append({
                "id": meldung["id"],
                "titel": meldung["titel"],
                "erwartet_pp": soll_pp,
                "erkannt_pp": ist_pp,
                "claim_erkannt": ist_claim,
                "abweichung": pp_abweichung,
            })

        abweichungen: list[str] = []
        treffer: dict[str, bool] = {}
        if soll_claim:
            for feld in FELDER:
                feldgesamt[feld] += 1
                if not ist_claim:
                    treffer[feld] = False
                    continue
                passt = _feld_passt(feld, erwartet.get(feld), vorhergesagt.get(feld))
                treffer[feld] = passt
                if passt:
                    feldtreffer[feld] += 1
                else:
                    abweichungen.append(
                        f"{feld}: erwartet={erwartet.get(feld)!r}, "
                        f"vorhergesagt={vorhergesagt.get(feld)!r}"
                    )
        if soll_claim and ist_claim:
            korrekt = all(treffer.values())
            richtige_claims += int(korrekt)
            if not korrekt:
                erkannt_aber_feldfehler += 1
        elif soll_claim and not ist_claim:
            uebersehene_claims += 1
            abweichungen.append("Claim nicht erkannt")
            korrekt = False
        elif not soll_claim and ist_claim:
            falsch_positive += 1
            abweichungen.append("Unerwarteter Claim")
            korrekt = False
        else:
            korrekt = True

        einzelfaelle.append({
            "id": meldung["id"],
            "quelle": meldung["quelle"],
            "titel": meldung["titel"],
            "erwartet_claim": soll_claim,
            "erkannt_claim": ist_claim,
            "korrekt": korrekt,
            "abweichungen": abweichungen,
        })

    gesamt = len(meldungen)
    return {
        "korpus_version": korpus.get("version"),
        "stand": korpus.get("stand"),
        "meldungen": gesamt,
        "erwartete_claims": erwartete_claims,
        "erkannte_claims": erkannte_claims,
        "richtige_claims": richtige_claims,
        "falsch_positive": falsch_positive,
        "uebersehene_claims": uebersehene_claims,
        "erkannt_aber_feldfehler": erkannt_aber_feldfehler,
        "claim_precision": round(richtige_claims / erkannte_claims, 4)
        if erkannte_claims else None,
        "claim_recall": round(richtige_claims / erwartete_claims, 4)
        if erwartete_claims else None,
        "claim_yield": round(erkannte_claims / gesamt, 4) if gesamt else None,
        "erwartete_claim_quote": round(erwartete_claims / gesamt, 4) if gesamt else None,
        "pp_erwartet": pp_erwartet,
        "pp_vorhergesagt": pp_vorhergesagt,
        "pp_richtig": pp_richtig,
        "pp_precision": round(pp_richtig / pp_vorhergesagt, 4)
        if pp_vorhergesagt else None,
        "pp_recall": round(pp_richtig / pp_erwartet, 4)
        if pp_erwartet else None,
        "pp_faelle": pp_faelle,
        "feldtreffer": feldtreffer,
        "feldgesamt": feldgesamt,
        "einzelfaelle": einzelfaelle,
    }


def _bericht(ergebnis: dict[str, Any], korpus: dict[str, Any]) -> str:
    zeilen = [
        "# Nexus-Claim-Baseline",
        "",
        f"**Korpus:** {ergebnis['meldungen']} reale RSS-Meldungen  ",
        f"**Stand:** {ergebnis['stand']}  ",
        "**Extraktion:** aktueller Produktivpfad (`Titel`, sonst erster Satz)",
        "",
        "## Kennzahlen",
        "",
        "| Kennzahl | Wert |",
        "|---|---:|",
        f"| Meldungen | {ergebnis['meldungen']} |",
        f"| Erwartete Claims | {ergebnis['erwartete_claims']} |",
        f"| Erkannte Claims | {ergebnis['erkannte_claims']} |",
        f"| Richtige Claims (alle Felder) | {ergebnis['richtige_claims']} |",
        f"| Falsch-positive Claims | {ergebnis['falsch_positive']} |",
        f"| Übersehene Claims | {ergebnis['uebersehene_claims']} |",
        f"| Erkannt, aber Feldfehler | {ergebnis['erkannt_aber_feldfehler']} |",
        f"| Claim-Precision | {ergebnis['claim_precision']} |",
        f"| Claim-Recall | {ergebnis['claim_recall']} |",
        f"| Claim-Yield | {ergebnis['claim_yield']} |",
        f"| Erwartete Claim-Quote | {ergebnis['erwartete_claim_quote']} |",
        "",
        "## pp-Erkennung",
        "",
        "Die pp-Kennzahlen zählen die Einheit `pp` unabhängig von den übrigen",
        "Claim-Feldern. Ein erwarteter pp-Claim, der nicht erkannt wird, zählt als",
        "False Negative; ein vorhergesagter pp-Claim ohne pp-Gold zählt als False",
        "Positive. Die Werte sind nur definiert, wenn der jeweilige Nenner grösser",
        "als null ist.",
        "",
        "| Kennzahl | Wert |",
        "|---|---:|",
        f"| Erwartete pp-Claims | {ergebnis['pp_erwartet']} |",
        f"| Vorhergesagte pp-Claims | {ergebnis['pp_vorhergesagt']} |",
        f"| Korrekte pp-Einheiten | {ergebnis['pp_richtig']} |",
        f"| pp-Precision | {ergebnis['pp_precision'] if ergebnis['pp_precision'] is not None else 'n/a'} |",
        f"| pp-Recall | {ergebnis['pp_recall'] if ergebnis['pp_recall'] is not None else 'n/a'} |",
        "",
    ]
    if ergebnis["pp_faelle"]:
        zeilen += ["| ID | Erwartet pp | Erkannt pp | Claim erkannt | Abweichung |",
                   "|---|---:|---:|---:|---|"]
        for fall in ergebnis["pp_faelle"]:
            zeilen.append(
                f"| `{fall['id']}` | {fall['erwartet_pp']} | {fall['erkannt_pp']} | "
                f"{fall['claim_erkannt']} | {fall['abweichung']} |"
            )
        zeilen.append("")
    else:
        zeilen += [
            "Es gibt keine pp-Fälle im Korpus. Eine pp-spezifische Precision/Recall",
            "ist daher nicht messbar; die Tabelle enthält keine pp-Fehlfälle.",
            "",
        ]
    zeilen += ["## Feldtreffer",
        "",
        "Alle erwarteten Claims; ein fehlender Claim zählt als Feldnicht-Treffer.",
        "Subjekt gilt als Treffer, wenn alle erwarteten Subjekt-Tokens im",
        "vorhergesagten Subjekt enthalten sind.",
        "",
        "| Feld | Treffer | Geprüft |",
        "|---|---:|---:|",
    ]
    for feld in FELDER:
        zeilen.append(
            f"| `{feld}` | {ergebnis['feldtreffer'][feld]} | "
            f"{ergebnis['feldgesamt'][feld]} |"
        )
    zeilen += ["", "## Einzelfälle", "", "| ID | Erwartet | Erkannt | Korrekt | Abweichung |",
               "|---|---:|---:|---:|---|"]
    for fall in ergebnis["einzelfaelle"]:
        abweichung = "; ".join(fall["abweichungen"]) or "–"
        zeilen.append(
            f"| `{fall['id']}` | {fall['erwartet_claim']} | {fall['erkannt_claim']} | "
            f"{fall['korrekt']} | {abweichung} |"
        )
    zeilen += [
        "",
        "## Grenzen",
        "",
        "- Der Korpus ist ein Snapshot aus `seed/orakel-seed.db`; er ist keine",
        "  laufende Produktionsstichprobe.",
        "- Die Goldfelder wurden manuell aus Titel und Zusammenfassung gesetzt.",
        "- Ein fehlender Claim kann auch bedeuten, dass die Meldung bewusst als",
        "  Verwaltungs- oder Verfahrensmeldung eingeordnet wurde.",
        "- Die Baseline prüft keine Volltexte, Embeddings oder Widerspruchsketten.",
        "",
        f"_Korpus: {korpus.get('beschreibung', '')}_",
        "",
    ]
    return "\n".join(zeilen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--korpus", type=Path, default=STANDARD_KORPUS)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "artifacts" / "nexus-claim-baseline")
    args = parser.parse_args()
    korpus = lade_korpus(args.korpus)
    ergebnis = bewerte(korpus)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "messwerte.json").write_text(
        json.dumps(ergebnis, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "report.md").write_text(
        _bericht(ergebnis, korpus), encoding="utf-8",
    )
    print(f"Korpus: {ergebnis['meldungen']} Meldungen")
    print(f"Erwartete/erkannte/richtige Claims: "
          f"{ergebnis['erwartete_claims']}/{ergebnis['erkannte_claims']}/"
          f"{ergebnis['richtige_claims']}")
    print(f"Claim-Precision: {ergebnis['claim_precision']}, "
          f"Claim-Recall: {ergebnis['claim_recall']}")
    print(f"Bericht: {args.output_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
