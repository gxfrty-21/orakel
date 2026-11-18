#!/usr/bin/env node
/**
 * Prüft das maschinenlesbare Ergebnis von `pruefe-text250.mjs` gegen das
 * Check-Manifest. CI wertet damit erwartete Zähler, Pflichtfall-IDs und
 * unerwartete Skips aus, statt Zeilen im Klartextlog zu greppen.
 *
 * Aufruf:
 *   node scripts/pruefe-text250-ergebnis.mjs \
 *     --ergebnis artifacts/text250/ergebnis.json \
 *     --pflicht scripts/text250-required-checks.json \
 *     --profil voll
 */

import { existsSync, readFileSync } from 'node:fs';

function leseArgumente(argv) {
  const opts = {
    ergebnis: 'artifacts/text250/ergebnis.json',
    pflicht: 'scripts/text250-required-checks.json',
    profil: 'voll',
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--ergebnis') opts.ergebnis = argv[++i];
    else if (arg === '--pflicht') opts.pflicht = argv[++i];
    else if (arg === '--profil') opts.profil = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250-ergebnis.mjs '
        + '[--ergebnis <json>] [--pflicht <json>] [--profil <name>]');
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

function pruefeZaehler(erwartet, tatsaechlich) {
  if (!erwartet || typeof erwartet !== 'object' || Array.isArray(erwartet)) {
    throw new Error('Check-Manifest enthält für das Profil keine gültigen counters');
  }
  if (!tatsaechlich || typeof tatsaechlich !== 'object' || Array.isArray(tatsaechlich)) {
    throw new Error('Text250-Ergebnis enthält keine counters');
  }
  const abweichungen = [];
  for (const [name, soll] of Object.entries(erwartet)) {
    if (!Number.isInteger(soll) || soll < 0) {
      throw new Error(`Ungültiger erwarteter Zähler ${name}: ${soll}`);
    }
    const ist = tatsaechlich[name];
    if (!Number.isInteger(ist)) {
      abweichungen.push(`${name}: erwartet ${soll}, tatsächlich fehlt`);
    } else if (ist !== soll) {
      abweichungen.push(`${name}: erwartet ${soll}, tatsächlich ${ist}`);
    }
  }
  return abweichungen;
}

function main() {
  const opts = leseArgumente(process.argv.slice(2));
  const ergebnis = leseJson(opts.ergebnis, 'Text250-Ergebnis');
  const manifest = leseJson(opts.pflicht, 'Text250-Check-Manifest');

  if (ergebnis.schema !== 'text250-result.v2') {
    throw new Error(`Unerwartetes Ergebnis-Schema: ${ergebnis.schema || 'fehlt'}`);
  }
  if (manifest.schema !== 'text250-check-manifest.v2') {
    throw new Error(`Unerwartetes Manifest-Schema: ${manifest.schema || 'fehlt'}`);
  }
  if (!Array.isArray(ergebnis.cases)) {
    throw new Error('Text250-Ergebnis enthält kein cases-Array');
  }
  const profile = manifest.profiles?.[opts.profil];
  if (!profile) {
    const bekannt = Object.keys(manifest.profiles || {}).join(', ') || 'keine';
    throw new Error(`Unbekanntes Manifest-Profil «${opts.profil}» (bekannt: ${bekannt})`);
  }
  if (!Array.isArray(profile.checks) || profile.checks.length === 0) {
    throw new Error(`Manifest-Profil «${opts.profil}» enthält keine checks`);
  }
  const erlaubteSkips = new Set(profile.allow_skips || []);
  if (!Array.isArray(profile.allow_skips || [])) {
    throw new Error(`Manifest-Profil «${opts.profil}» hat kein gültiges allow_skips`);
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
  const unerwarteteSkips = [];
  const pflichtIds = new Set();
  for (const eintrag of profile.checks) {
    const id = typeof eintrag === 'string' ? eintrag : eintrag?.id;
    if (typeof id !== 'string' || !id) {
      throw new Error('Check-Manifest enthält einen Eintrag ohne gültige ID');
    }
    if (pflichtIds.has(id)) {
      throw new Error(`Doppelte Pflicht-ID im Profil «${opts.profil}»: ${id}`);
    }
    pflichtIds.add(id);
    const fall = nachId.get(id);
    if (!fall) {
      fehlend.push(`${id} (nicht ausgeführt)`);
    } else if (fall.status === 'skipped') {
      unerwarteteSkips.push(`${id}${fall.details ? `: ${fall.details}` : ''}`);
    } else if (fall.status !== 'passed') {
      fehlgeschlagen.push(`${id} (${fall.status || 'ohne Status'}${fall.details ? `: ${fall.details}` : ''})`);
    }
  }

  // Jeder Skip ist ein harter Fehler, solange das Profil ihn nicht ausdrücklich
  // erlaubt – auch für Fälle, die nicht als Pflichtfall eingetragen sind.
  for (const fall of ergebnis.cases) {
    if (fall.status === 'skipped' && !erlaubteSkips.has(fall.id) && !pflichtIds.has(fall.id)) {
      unerwarteteSkips.push(`${fall.id}${fall.details ? `: ${fall.details}` : ''}`);
    }
  }

  const zaehlerAbweichungen = pruefeZaehler(profile.counters, ergebnis.counters);

  if (fehlend.length || fehlgeschlagen.length || unerwarteteSkips.length || zaehlerAbweichungen.length) {
    if (fehlend.length) {
      console.error(`Fehlende Pflichtfälle (${fehlend.length}):`);
      for (const text of fehlend) console.error(`  ✗ ${text}`);
    }
    if (unerwarteteSkips.length) {
      console.error(`Unerwartete Skips (${unerwarteteSkips.length}):`);
      for (const text of unerwarteteSkips) console.error(`  ✗ ${text}`);
    }
    if (fehlgeschlagen.length) {
      console.error(`Fehlgeschlagene Pflichtfälle (${fehlgeschlagen.length}):`);
      for (const text of fehlgeschlagen) console.error(`  ✗ ${text}`);
    }
    if (zaehlerAbweichungen.length) {
      console.error(`Zählerabweichungen (${zaehlerAbweichungen.length}):`);
      for (const text of zaehlerAbweichungen) console.error(`  ✗ ${text}`);
    }
    process.exit(1);
  }

  console.log(`Text250-Manifest OK (Profil ${opts.profil}): `
    + `${profile.checks.length}/${profile.checks.length} Pflichtfälle bestanden, `
    + `${Object.keys(profile.counters).length} Zähler exakt, keine unerwarteten Skips`);
}

try {
  main();
} catch (fehler) {
  console.error(`Text250-Manifest FEHLER: ${fehler instanceof Error ? fehler.message : fehler}`);
  process.exit(1);
}
