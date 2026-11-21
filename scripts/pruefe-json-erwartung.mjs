#!/usr/bin/env node
/**
 * Prüft eine JSON-Ergebnisdatei gegen explizit erwartete Werte.
 *
 * Aufruf:
 *   node scripts/pruefe-json-erwartung.mjs DATEI pfad=wert [pfad=wert …]
 *
 * ``pfad`` ist ein Punktpfad (z. B. ``negativ.erkannt``). ``wert`` wird als
 * ``true``/``false``/``null``, sonst als Zahl oder Zeichenkette gelesen.
 * Fehlende Pfade, falsche Typen oder abweichende Werte beenden den Lauf mit
 * Exit-Code 1. Damit ersetzt die Prüfung Logstring-Greps: Ein stilles
 * Überspringen hinterlässt keine passende JSON-Datei und fällt hier auf.
 */

import { readFileSync } from 'node:fs';

const [datei, ...paare] = process.argv.slice(2);
if (!datei || paare.length === 0) {
  console.error('Aufruf: node scripts/pruefe-json-erwartung.mjs DATEI pfad=wert [pfad=wert …]');
  process.exit(2);
}

let daten;
try {
  daten = JSON.parse(readFileSync(datei, 'utf8'));
} catch (fehler) {
  console.error(`Ergebnisdatei ${datei} ist nicht lesbar: ${fehler.message}`);
  process.exit(1);
}

function hole(pfad) {
  return pfad.split('.').reduce(
    (wert, schluessel) => (wert && typeof wert === 'object' ? wert[schluessel] : undefined),
    daten,
  );
}

function erwartet(roh) {
  if (roh === 'true') return true;
  if (roh === 'false') return false;
  if (roh === 'null') return null;
  const zahl = Number(roh);
  return roh !== '' && Number.isFinite(zahl) ? zahl : roh;
}

let fehler = 0;
for (const paar of paare) {
  const trenner = paar.indexOf('=');
  if (trenner <= 0) {
    console.error(`Ungültige Erwartung «${paar}»; Format pfad=wert`);
    fehler += 1;
    continue;
  }
  const pfad = paar.slice(0, trenner);
  const soll = erwartet(paar.slice(trenner + 1));
  const ist = hole(pfad);
  if (ist === undefined) {
    console.error(`Fehlt: ${pfad}`);
    fehler += 1;
  } else if (ist !== soll) {
    console.error(`Abweichung bei ${pfad}: «${JSON.stringify(ist)}» statt «${JSON.stringify(soll)}»`);
    fehler += 1;
  } else {
    console.log(`OK ${pfad}=${JSON.stringify(ist)}`);
  }
}

if (fehler) process.exit(1);
console.log(`JSON-Erwartung OK: ${datei} (${paare.length} Werte)`);
