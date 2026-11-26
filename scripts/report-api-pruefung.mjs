#!/usr/bin/env node
/**
 * Bericht-Vertrag des Dashboards – ohne Browser prüfbar.
 *
 * ``--url`` holt ``/api/report`` und prüft die Form, auf die sich Cockpit,
 * Papier- und Spider-Ansicht verlassen. Eine leere Datenbank liefert ``null``
 * bei Beträgen und Equity; geprüft wird deshalb die Struktur, nicht ein
 * bestimmter Wert. So deckt die browsorfreie Prüfung neben dem Widerspruch
 * auch den Bericht ab, aus dem die Oberfläche ihre Kennzahlen zieht.
 *
 * Aufruf:
 *   node scripts/report-api-pruefung.mjs --url http://127.0.0.1:3300
 */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const FENSTER = ['heute', '7t', '1m'];

function objekt(wert, pfad) {
  if (!wert || typeof wert !== 'object' || Array.isArray(wert)) {
    throw new Error(`${pfad} fehlt oder ist kein Objekt`);
  }
  return wert;
}

function liste(wert, pfad) {
  if (!Array.isArray(wert)) {
    throw new Error(`${pfad} fehlt oder ist keine Liste`);
  }
  return wert;
}

function zahlOderNull(wert, pfad) {
  if (wert !== null && typeof wert !== 'number') {
    throw new Error(`${pfad} ist weder Zahl noch null: ${JSON.stringify(wert)}`);
  }
  return wert;
}

/**
 * Prüft eine ``/api/report``-Antwort gegen den Vertrag der Oberfläche.
 * Gibt ``{schema, modus, positionen, artikel}`` zurück und wirft bei
 * Vertragsverletzungen einen ``Error`` mit sprechender Meldung.
 */
export function reportBefund(bericht) {
  const d = objekt(bericht, 'Bericht');
  if (typeof d.schema !== 'number') {
    throw new Error(`Bericht-Schema fehlt oder ist keine Zahl: ${JSON.stringify(d.schema)}`);
  }
  if (typeof d.modus !== 'string' || !d.modus) {
    throw new Error('Bericht ohne Modus');
  }
  if (typeof d.erstellt !== 'string' || !d.erstellt) {
    throw new Error('Bericht ohne Erstellungszeit');
  }

  const cockpit = objekt(d.cockpit, 'cockpit');
  const konto = objekt(cockpit.konto, 'cockpit.konto');
  zahlOderNull(konto.equity, 'cockpit.konto.equity');
  if (typeof konto.start_kapital !== 'number') {
    throw new Error('cockpit.konto.start_kapital ist keine Zahl');
  }
  const gewinn = objekt(cockpit.gewinn, 'cockpit.gewinn');
  for (const fenster of FENSTER) {
    const teil = objekt(gewinn[fenster], `cockpit.gewinn.${fenster}`);
    zahlOderNull(teil.betrag, `cockpit.gewinn.${fenster}.betrag`);
    zahlOderNull(teil.pct, `cockpit.gewinn.${fenster}.pct`);
    liste(teil.verlauf, `cockpit.gewinn.${fenster}.verlauf`);
  }
  const positionen = liste(cockpit.positionen, 'cockpit.positionen');
  zahlOderNull(cockpit.positionen_ergebnis, 'cockpit.positionen_ergebnis');

  const paper = objekt(d.paper, 'paper');
  const papierPositionen = liste(paper.positionen, 'paper.positionen');
  if (paper.letzter_tick !== null && typeof paper.letzter_tick !== 'string') {
    throw new Error('paper.letzter_tick ist weder Text noch null');
  }
  // Ein Lauf ohne Paper-Tick hat noch kein Konto; dann ist null erlaubt.
  if (paper.konto === null && paper.letzter_tick !== null) {
    throw new Error('paper.konto fehlt, obwohl ein Paper-Tick gespeichert ist');
  }
  if (paper.konto !== null) objekt(paper.konto, 'paper.konto');

  const spider = objekt(d.spider, 'spider');
  const artikel = liste(spider.artikel, 'spider.artikel');
  if (typeof spider.quellen !== 'number') {
    throw new Error('spider.quellen ist keine Zahl');
  }

  return {
    schema: d.schema,
    modus: d.modus,
    positionen: positionen.length,
    papierPositionen: papierPositionen.length,
    artikel: artikel.length,
  };
}

function argumente(argv) {
  const opts = { url: '' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/report-api-pruefung.mjs --url URL');
      process.exit(0);
    } else {
      throw new Error(`Unbekannte Option: ${arg}`);
    }
  }
  if (!opts.url) throw new Error('--url fehlt');
  return opts;
}

async function ladeBericht(url) {
  const basis = String(url).replace(/\/$/, '');
  let antwort;
  try {
    antwort = await fetch(`${basis}/api/report`, { cache: 'no-store' });
  } catch (fehler) {
    throw new Error(`Bericht-Abruf ${basis} fehlgeschlagen: ${fehler.message}`);
  }
  if (!antwort.ok) {
    throw new Error(`Bericht-Abruf ${basis}/api/report lieferte HTTP ${antwort.status}`);
  }
  try {
    return await antwort.json();
  } catch (fehler) {
    throw new Error(`Bericht-Antwort von ${basis} ist kein JSON: ${fehler.message}`);
  }
}

async function main() {
  const opt = argumente(process.argv.slice(2));
  const befund = reportBefund(await ladeBericht(opt.url));
  console.log(
    `Report-API OK: Schema ${befund.schema}, Modus ${befund.modus}, ` +
    `${befund.positionen} Positionen, ${befund.papierPositionen} Papier-Positionen, ` +
    `${befund.artikel} Artikel`
  );
}

if (resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  try {
    await main();
  } catch (fehler) {
    console.error(fehler instanceof Error ? fehler.message : fehler);
    process.exit(1);
  }
}
