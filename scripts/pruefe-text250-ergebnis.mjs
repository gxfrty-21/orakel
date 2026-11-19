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
 *
 * `--selbsttest` prüft die Skip-Logik ohne Dateien: Ein Skip, der in
 * `allow_skips` steht, muss akzeptiert werden; ein Skip ausserhalb der
 * Erlaubnisliste muss als unerwartet erkannt werden.
 */

import { existsSync, readFileSync } from 'node:fs';

function leseArgumente(argv) {
  const opts = {
    ergebnis: 'artifacts/text250/ergebnis.json',
    pflicht: 'scripts/text250-required-checks.json',
    profil: 'voll',
    selbsttest: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--ergebnis') opts.ergebnis = argv[++i];
    else if (arg === '--pflicht') opts.pflicht = argv[++i];
    else if (arg === '--profil') opts.profil = argv[++i];
    else if (arg === '--selbsttest') opts.selbsttest = true;
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250-ergebnis.mjs '
        + '[--ergebnis <json>] [--pflicht <json>] [--profil <name>] [--selbsttest]');
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

/**
 * Vergleicht ein Ergebnisobjekt mit einem Manifest-Profil und liefert die
 * Abweichungen zurück. Schema- und Strukturfehler werfen; inhaltliche
 * Abweichungen bleiben als Listen beim Aufrufer, damit auch der Selbsttest
 * sie auswerten kann.
 */
function pruefeErgebnis(ergebnis, manifest, opts) {
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
  if (profile.allow_skips !== undefined && !Array.isArray(profile.allow_skips)) {
    throw new Error(`Manifest-Profil «${opts.profil}» hat kein gültiges allow_skips`);
  }
  const erlaubteSkips = new Set(profile.allow_skips || []);

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
      if (!erlaubteSkips.has(id)) {
        unerwarteteSkips.push(`${id}${fall.details ? `: ${fall.details}` : ''}`);
      }
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
  return { profile, fehlend, fehlgeschlagen, unerwarteteSkips, zaehlerAbweichungen };
}

function manifestFuerProfil(profil) {
  return {
    schema: 'text250-check-manifest.v2',
    profiles: { test: profil },
  };
}

function selbsttest() {
  const opts = { profil: 'test' };

  const erwartet = pruefeErgebnis(
    {
      schema: 'text250-result.v2',
      cases: [{ id: 'text250.erwartet', status: 'skipped' }],
      counters: {},
    },
    manifestFuerProfil({
      checks: [{ id: 'text250.erwartet' }],
      allow_skips: ['text250.erwartet'],
      counters: {},
    }),
    opts,
  );
  const erwartetFehler = [
    ...erwartet.fehlend,
    ...erwartet.fehlgeschlagen,
    ...erwartet.unerwarteteSkips,
    ...erwartet.zaehlerAbweichungen,
  ];
  if (erwartetFehler.length) {
    throw new Error(`Selbsttest: erwarteter Skip wurde nicht akzeptiert: ${erwartetFehler.join('; ')}`);
  }

  const unerwartet = pruefeErgebnis(
    {
      schema: 'text250-result.v2',
      cases: [
        { id: 'text250.pflicht', status: 'passed' },
        { id: 'text250.unerwartet', status: 'skipped' },
      ],
      counters: {},
    },
    manifestFuerProfil({
      checks: [{ id: 'text250.pflicht' }],
      allow_skips: [],
      counters: {},
    }),
    opts,
  );
  if (unerwartet.unerwarteteSkips.length !== 1
      || !unerwartet.unerwarteteSkips[0].startsWith('text250.unerwartet')) {
    throw new Error('Selbsttest: unerwarteter Skip wurde nicht erkannt '
      + `(${unerwartet.unerwarteteSkips.join('; ') || 'keine Meldung'})`);
  }
  if (unerwartet.fehlend.length || unerwartet.fehlgeschlagen.length
      || unerwartet.zaehlerAbweichungen.length) {
    throw new Error('Selbsttest: unerwarteter Skip erzeugte zusätzliche Abweichungen');
  }

  console.log('Selbsttest OK: erwarteter Skip erlaubt, unerwarteter Skip erkannt');
}

function main() {
  const opts = leseArgumente(process.argv.slice(2));
  if (opts.selbsttest) {
    selbsttest();
    return;
  }

  const ergebnis = leseJson(opts.ergebnis, 'Text250-Ergebnis');
  const manifest = leseJson(opts.pflicht, 'Text250-Check-Manifest');
  const { profile, fehlend, fehlgeschlagen, unerwarteteSkips, zaehlerAbweichungen } =
    pruefeErgebnis(ergebnis, manifest, opts);

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
