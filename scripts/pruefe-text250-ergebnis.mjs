#!/usr/bin/env node
/**
 * Prüft das maschinenlesbare Ergebnis von `pruefe-text250.mjs` gegen das
 * Pflichtmanifest. CI wertet damit explizite Fall-IDs aus, nicht Zähler wie
 * «Claims 4×» oder Suchtexte im Klartextlog.
 *
 * Aufruf:
 *   node scripts/pruefe-text250-ergebnis.mjs \
 *     --ergebnis artifacts/text250/ergebnis.json \
 *     --pflicht scripts/text250-required-checks.json
 */

import { existsSync, readFileSync } from 'node:fs';

function leseArgumente(argv) {
  const opts = {
    ergebnis: 'artifacts/text250/ergebnis.json',
    pflicht: 'scripts/text250-required-checks.json',
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--ergebnis') opts.ergebnis = argv[++i];
    else if (arg === '--pflicht') opts.pflicht = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250-ergebnis.mjs [--ergebnis <json>] [--pflicht <json>]');
      process.exit(0);
    } else {
      console.error(`Unbekannte Option: ${arg}`);
      process.exit(2);
    }
  }
  return opts;
}

function leseJson(pfad, bezeichnung) {
  if (!existsSync(pfad)) {
    throw new Error(`${bezeichnung} fehlt: ${pfad}`);
  }
  try {
    return JSON.parse(readFileSync(pfad, 'utf8'));
  } catch (fehler) {
    throw new Error(`${bezeichnung} ist kein gültiges JSON (${pfad}): ${fehler.message}`);
  }
}

function main() {
  const opts = leseArgumente(process.argv.slice(2));
  const ergebnis = leseJson(opts.ergebnis, 'Text250-Ergebnis');
  const pflicht = leseJson(opts.pflicht, 'Text250-Pflichtmanifest');

  if (ergebnis.schema !== 'text250-result.v1') {
    throw new Error(`Unerwartetes Ergebnis-Schema: ${ergebnis.schema || 'fehlt'}`);
  }
  if (pflicht.schema !== 'text250-required-checks.v1') {
    throw new Error(`Unerwartetes Pflicht-Schema: ${pflicht.schema || 'fehlt'}`);
  }
  if (!Array.isArray(ergebnis.cases)) {
    throw new Error('Text250-Ergebnis enthält kein cases-Array');
  }
  if (!Array.isArray(pflicht.checks) || pflicht.checks.length === 0) {
    throw new Error('Text250-Pflichtmanifest enthält keine checks');
  }

  const nachId = new Map();
  const doppelt = [];
  for (const fall of ergebnis.cases) {
    if (!fall || typeof fall.id !== 'string' || !fall.id) {
      throw new Error('Text250-Ergebnis enthält einen Fall ohne gültige ID');
    }
    if (nachId.has(fall.id)) doppelt.push(fall.id);
    nachId.set(fall.id, fall);
  }
  if (doppelt.length) {
    throw new Error(`Doppelte Fall-IDs im Text250-Ergebnis: ${[...new Set(doppelt)].join(', ')}`);
  }

  const fehlend = [];
  const fehlgeschlagen = [];
  const gesehen = new Set();
  for (const eintrag of pflicht.checks) {
    if (!eintrag || typeof eintrag.id !== 'string' || !eintrag.id) {
      throw new Error('Text250-Pflichtmanifest enthält einen Eintrag ohne gültige ID');
    }
    if (gesehen.has(eintrag.id)) {
      throw new Error(`Doppelte Pflicht-ID: ${eintrag.id}`);
    }
    gesehen.add(eintrag.id);
    const fall = nachId.get(eintrag.id);
    if (!fall) {
      fehlend.push(eintrag.id);
    } else if (fall.status !== 'passed') {
      fehlgeschlagen.push(`${eintrag.id} (${fall.status || 'ohne Status'}${fall.details ? `: ${fall.details}` : ''})`);
    }
  }

  if (fehlend.length || fehlgeschlagen.length) {
    if (fehlend.length) {
      console.error(`Fehlende Pflichtfälle (${fehlend.length}):`);
      for (const id of fehlend) console.error(`  ✗ ${id}`);
    }
    if (fehlgeschlagen.length) {
      console.error(`Fehlgeschlagene Pflichtfälle (${fehlgeschlagen.length}):`);
      for (const text of fehlgeschlagen) console.error(`  ✗ ${text}`);
    }
    process.exit(1);
  }

  console.log(`Text250-Pflichtprüfung OK: ${pflicht.checks.length}/${pflicht.checks.length} Fälle explizit bestanden`);
}

try {
  main();
} catch (fehler) {
  console.error(`Text250-Pflichtprüfung FEHLER: ${fehler instanceof Error ? fehler.message : fehler}`);
  process.exit(1);
}
