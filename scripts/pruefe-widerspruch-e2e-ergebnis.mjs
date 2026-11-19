#!/usr/bin/env node
/**
 * Prüft das JSON-Ergebnis des Widerspruch-E2E gegen das Manifest.
 *
 * Aufruf:
 *   node scripts/pruefe-widerspruch-e2e-ergebnis.mjs \
 *     --ergebnis artifacts/widerspruch-e2e/negativtest-ergebnis.json \
 *     --pflicht scripts/widerspruch-e2e-required-checks.json \
 *     --profil voll
 *
 * Geprüft werden das Schema, eindeutige Fall-IDs, der Zähler «negativ» und
 * jeder Pflichtfall: er muss im Ergebnis stehen und den Status «passed» haben.
 * Fehlt ein Fall oder ist er fehlgeschlagen, endet der Prüfer mit Exit 1.
 */

import { readFileSync } from 'node:fs';

const ERGEBNIS_SCHEMA = 'widerspruch-e2e-result.v1';
const MANIFEST_SCHEMA = 'widerspruch-e2e-check-manifest.v1';
const NEGATIV_PRAEFIX = 'widerspruch-e2e.negativ.';

function argumente(argv) {
  const opts = { ergebnis: '', pflicht: '', profil: 'voll' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--ergebnis') opts.ergebnis = argv[++i];
    else if (arg === '--pflicht') opts.pflicht = argv[++i];
    else if (arg === '--profil') opts.profil = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-widerspruch-e2e-ergebnis.mjs ' +
        '--ergebnis PFAD --pflicht PFAD [--profil NAME]');
      process.exit(0);
    } else {
      throw new Error(`Unbekannte Option: ${arg}`);
    }
  }
  if (!opts.ergebnis) throw new Error('--ergebnis fehlt');
  if (!opts.pflicht) throw new Error('--pflicht fehlt');
  return opts;
}

function lies(pfad, bezeichnung) {
  try {
    return JSON.parse(readFileSync(pfad, 'utf8'));
  } catch (fehler) {
    throw new Error(`${bezeichnung} «${pfad}» nicht lesbar: ${fehler.message}`);
  }
}

function main() {
  const opt = argumente(process.argv.slice(2));
  const ergebnis = lies(opt.ergebnis, 'Ergebnis');
  const manifest = lies(opt.pflicht, 'Check-Manifest');

  if (ergebnis.schema !== ERGEBNIS_SCHEMA) {
    throw new Error(`Unerwartetes Ergebnis-Schema: ${ergebnis.schema || 'fehlt'}`);
  }
  if (manifest.schema !== MANIFEST_SCHEMA) {
    throw new Error(`Unerwartetes Manifest-Schema: ${manifest.schema || 'fehlt'}`);
  }
  const profil = manifest.profiles?.[opt.profil];
  if (!profil || !Array.isArray(profil.checks) || profil.checks.length === 0) {
    throw new Error(`Manifest-Profil «${opt.profil}» hat keine gültigen Pflichtfälle`);
  }

  const faelle = Array.isArray(ergebnis.faelle) ? ergebnis.faelle : [];
  const nachId = new Map();
  const doppelt = [];
  for (const fall of faelle) {
    if (!fall || typeof fall.id !== 'string' || !fall.id) {
      throw new Error('Ergebnis enthält einen Fall ohne gültige ID');
    }
    if (nachId.has(fall.id)) doppelt.push(fall.id);
    nachId.set(fall.id, fall);
  }
  if (doppelt.length) {
    throw new Error(`Doppelte Fall-IDs im Ergebnis: ${[...new Set(doppelt)].join(', ')}`);
  }

  const fehlend = [];
  const fehlgeschlagen = [];
  for (const check of profil.checks) {
    const fall = nachId.get(check.id);
    if (!fall) {
      fehlend.push(check.id);
    } else if (fall.status !== 'passed') {
      fehlgeschlagen.push(
        `${check.id} (${fall.status || 'ohne Status'}${fall.details ? `: ${fall.details}` : ''})`
      );
    }
  }

  const negativErwartet = Number(profil.counters?.negativ ?? profil.checks.length);
  const negativBestanden = faelle.filter(
    fall => fall.id.startsWith(NEGATIV_PRAEFIX) && fall.status === 'passed'
  ).length;
  const zaehlerAbweichung = negativBestanden === negativErwartet
    ? ''
    : `negativ: erwartet ${negativErwartet}, tatsächlich ${negativBestanden}`;

  if (fehlend.length || fehlgeschlagen.length || zaehlerAbweichung) {
    if (fehlend.length) {
      console.error(`Fehlende Pflichtfälle (${fehlend.length}):`);
      for (const id of fehlend) console.error(`  ✗ ${id} (nicht ausgeführt)`);
    }
    if (fehlgeschlagen.length) {
      console.error(`Fehlgeschlagene Pflichtfälle (${fehlgeschlagen.length}):`);
      for (const zeile of fehlgeschlagen) console.error(`  ✗ ${zeile}`);
    }
    if (zaehlerAbweichung) console.error(`Zähler weicht ab: ${zaehlerAbweichung}`);
    process.exit(1);
  }

  console.log(
    `Widerspruch-E2E-Ergebnis OK: ${profil.checks.length}/${profil.checks.length} ` +
    `Pflichtfälle bestanden · negativ ${negativBestanden}/${negativErwartet}`
  );
}

try {
  main();
} catch (fehler) {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
}
