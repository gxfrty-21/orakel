#!/usr/bin/env node
/**
 * API-Vertrag des Widerspruchs – ohne Browser prüfbar.
 *
 * Der E2E-Test nutzt ``apiBefund`` für den Positivfall und für den
 * Negativfall «fehlende API-Zeile». Die Funktion ist hier ausgelagert, damit
 * pytest den Vertrag unabhängig vom Browser absichern kann.
 *
 * Geprüft wird:
 *   - die Antwort ist ok,
 *   - der erwartete Widerspruch (Grund, Quellen, bp-Werte) ist vorhanden,
 *   - die Sicherheit stimmt,
 *   - der Widerspruch kommt für claim_id + Grund genau einmal vor,
 *   - der zugehörige Claim steht in ``claims.top`` und ist widersprüchlich.
 *
 * Aufruf (CLI, für Tests und Proben):
 *   node scripts/widerspruch-api-pruefung.mjs --status status.json
 *   node scripts/widerspruch-api-pruefung.mjs --status status.json --erwartet erwartet.json
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const ERWARTET = {
  grund: 'Richtung steigt gegen sinkt',
  sicherheit: 0.8,
  quelleA: 'e2e-a.example',
  quelleB: 'e2e-b.example',
  wertA: 450,
  wertB: 400,
};

/**
 * Prüft eine ``/api/nexus/status``-Antwort gegen den erwarteten Widerspruch.
 * Gibt ``{ widerspruch, claim }`` zurück und wirft bei Vertragsverletzungen
 * einen ``Error`` mit sprechender Meldung.
 */
export function apiBefund(status, erwartet = ERWARTET) {
  if (!status || status.ok !== true) {
    throw new Error('API-Antwort ist nicht ok');
  }
  const claims = status.claims || {};
  const widersprueche = Array.isArray(claims.widersprueche)
    ? claims.widersprueche
    : [];
  const passend = widersprueche.find(w =>
    w.grund === erwartet.grund &&
    w.quelle_a === erwartet.quelleA &&
    w.quelle_b === erwartet.quelleB &&
    Number(w.wert_a_bp) === erwartet.wertA &&
    Number(w.wert_b_bp) === erwartet.wertB
  );
  if (!passend) {
    throw new Error(
      'API enthält den erwarteten Widerspruch nicht: ' +
      JSON.stringify(widersprueche)
    );
  }
  if (Number(passend.sicherheit) !== erwartet.sicherheit) {
    throw new Error(
      `API-Widerspruchssicherheit ${passend.sicherheit} statt ${erwartet.sicherheit}`
    );
  }
  const gleiche = widersprueche.filter(w =>
    Number(w.claim_id) === Number(passend.claim_id) && w.grund === passend.grund
  );
  if (gleiche.length > 1) {
    throw new Error(
      `API enthält den Widerspruch claim_id ${passend.claim_id}, ` +
      `«${passend.grund}» mehrfach (${gleiche.length}×)`
    );
  }
  const claim = (claims.top || []).find(c => Number(c.id) === Number(passend.claim_id));
  if (!claim) {
    throw new Error(`API-Claim ${passend.claim_id} fehlt in claims.top`);
  }
  if (claim.status !== 'widersprüchlich') {
    throw new Error(`API-Claim ${claim.id} hat Status ${claim.status}`);
  }
  return { widerspruch: passend, claim };
}

function argumente(argv) {
  const opts = { status: '', erwartet: '' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--status') opts.status = argv[++i];
    else if (arg === '--erwartet') opts.erwartet = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/widerspruch-api-pruefung.mjs ' +
        '--status PFAD [--erwartet PFAD]');
      process.exit(0);
    } else {
      throw new Error(`Unbekannte Option: ${arg}`);
    }
  }
  if (!opts.status) throw new Error('--status fehlt');
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
  const status = lies(opt.status, 'Status');
  const erwartet = opt.erwartet ? lies(opt.erwartet, 'Erwartung') : ERWARTET;
  const { widerspruch, claim } = apiBefund(status, erwartet);
  console.log(
    `Widerspruch-API OK: Claim ${claim.id}, «${widerspruch.grund}», ` +
    `${widerspruch.quelle_a} ↔ ${widerspruch.quelle_b}, ` +
    `${erwartet.wertA} bp ↔ ${erwartet.wertB} bp`
  );
}

if (resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (fehler) {
    console.error(fehler instanceof Error ? fehler.message : fehler);
    process.exit(1);
  }
}
