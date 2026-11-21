#!/usr/bin/env node
/**
 * Company-Übersicht des Dashboards – ohne Browser prüfbar.
 *
 * ``--url`` holt ``/api/company/overview`` und prüft die Form, aus der die
 * Raumschiff-Ansicht ihre Kennzahlen zieht: Agentenzahl, Statuszähler,
 * offene Aufgaben und Abteilungen. ``aufgaben.offen`` ist die Zahl, die im
 * Dashboard als «offene Aufgaben» steht; sie muss zu den Einzelstaaten und
 * zur Liste der offenen Aufgaben passen. Die Prüfung achtet auf Struktur und
 * Zählkonsistenz, nicht auf bestimmte Werte: Eine frische Datenbank hat
 * null offene Aufgaben, eine laufende mehr.
 *
 * Aufruf:
 *   node scripts/company-api-pruefung.mjs --url http://127.0.0.1:3300
 */

import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const STATUS_FELDER = ['aktiv', 'blockiert', 'wartend', 'frei', 'inaktiv'];
const OFFENE_STATES = ['proposed', 'queued', 'accepted', 'running', 'review', 'blocked'];

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

function anzahl(wert, pfad) {
  if (typeof wert !== 'number' || !Number.isInteger(wert) || wert < 0) {
    throw new Error(`${pfad} ist keine nichtnegative ganze Zahl: ${JSON.stringify(wert)}`);
  }
  return wert;
}

function text(wert, pfad) {
  if (typeof wert !== 'string' || !wert) {
    throw new Error(`${pfad} fehlt oder ist kein Text`);
  }
  return wert;
}

/**
 * Prüft eine ``/api/company/overview``-Antwort gegen den Vertrag des
 * Dashboards. Gibt ``{dataState, agenten, offen, abteilungen, offeneAufgaben}``
 * zurück und wirft bei Vertragsverletzungen einen ``Error``.
 */
export function companyBefund(uebersicht) {
  const d = objekt(uebersicht, 'Company-Übersicht');
  if (d.ok !== true) {
    throw new Error('Company-Übersicht ist nicht ok');
  }
  const dataState = text(d.data_state, 'data_state');
  if (dataState !== 'live' && dataState !== 'empty') {
    throw new Error(`data_state ist weder live noch empty: ${JSON.stringify(dataState)}`);
  }
  const erstellt = text(d.generated_at, 'generated_at');
  if (Number.isNaN(Date.parse(erstellt))) {
    throw new Error(`generated_at ist kein Zeitpunkt: ${JSON.stringify(erstellt)}`);
  }
  for (const quelle of liste(d.source_refs, 'source_refs')) {
    text(quelle, 'source_refs-Eintrag');
  }

  const profile = objekt(d.profile, 'profile');
  const gesamt = anzahl(profile.gesamt, 'profile.gesamt');
  anzahl(profile.aktiv, 'profile.aktiv');
  anzahl(profile.inaktiv, 'profile.inaktiv');

  const status = objekt(d.agenten_status, 'agenten_status');
  const statusSumme = STATUS_FELDER.reduce(
    (summe, feld) => summe + anzahl(status[feld], `agenten_status.${feld}`), 0);
  if (statusSumme !== profile.aktiv) {
    throw new Error(
      `agenten_status summiert ${statusSumme} statt profile.aktiv ${profile.aktiv}`);
  }

  const aufgaben = objekt(d.aufgaben, 'aufgaben');
  const offen = anzahl(aufgaben.offen, 'aufgaben.offen');
  anzahl(aufgaben.dead_letter, 'aufgaben.dead_letter');
  const nachStatus = objekt(aufgaben.nach_status, 'aufgaben.nach_status');
  const offenAusStatus = OFFENE_STATES.reduce(
    (summe, state) => summe + anzahl(nachStatus[state] ?? 0, `aufgaben.nach_status.${state}`), 0);
  if (offenAusStatus !== offen) {
    throw new Error(
      `aufgaben.offen ist ${offen}, die offenen Einzelstaaten summieren ${offenAusStatus}`);
  }

  const offeneAufgaben = liste(d.offene_aufgaben, 'offene_aufgaben');
  if (offeneAufgaben.length > 10) {
    throw new Error(`offene_aufgaben enthält ${offeneAufgaben.length} statt höchstens 10`);
  }
  for (const [index, aufgabe] of offeneAufgaben.entries()) {
    const pfad = `offene_aufgaben[${index}]`;
    const eintrag = objekt(aufgabe, pfad);
    anzahl(eintrag.id, `${pfad}.id`);
    text(eintrag.title, `${pfad}.title`);
    const state = text(eintrag.state, `${pfad}.state`);
    if (!OFFENE_STATES.includes(state)) {
      throw new Error(`${pfad}.state ist nicht offen: ${JSON.stringify(state)}`);
    }
    text(eintrag.state_text, `${pfad}.state_text`);
    anzahl(eintrag.priority, `${pfad}.priority`);
  }

  const abteilungen = liste(d.abteilungen, 'abteilungen');
  for (const [index, abteilung] of abteilungen.entries()) {
    const pfad = `abteilungen[${index}]`;
    const eintrag = objekt(abteilung, pfad);
    text(eintrag.code, `${pfad}.code`);
    text(eintrag.name, `${pfad}.name`);
    for (const feld of ['agenten', 'offen', 'laeuft', 'blockiert']) {
      anzahl(eintrag[feld], `${pfad}.${feld}`);
    }
  }

  if (d.letzte_konferenz !== null) {
    objekt(d.letzte_konferenz, 'letzte_konferenz');
  }
  liste(d.offene_entscheidungen, 'offene_entscheidungen');
  anzahl(d.offene_entscheidungen_gesamt, 'offene_entscheidungen_gesamt');
  if (typeof d.audit_ok !== 'boolean') {
    throw new Error('audit_ok fehlt oder ist kein Wahrheitswert');
  }

  return {
    dataState,
    agenten: gesamt,
    offen,
    abteilungen: abteilungen.length,
    offeneAufgaben: offeneAufgaben.length,
  };
}

function argumente(argv) {
  const opts = { url: '' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/company-api-pruefung.mjs --url URL');
      process.exit(0);
    } else {
      throw new Error(`Unbekannte Option: ${arg}`);
    }
  }
  if (!opts.url) throw new Error('--url fehlt');
  return opts;
}

async function ladeUebersicht(url) {
  const basis = String(url).replace(/\/$/, '');
  let antwort;
  try {
    antwort = await fetch(`${basis}/api/company/overview`, { cache: 'no-store' });
  } catch (fehler) {
    throw new Error(`Company-Abruf ${basis} fehlgeschlagen: ${fehler.message}`);
  }
  if (!antwort.ok) {
    throw new Error(
      `Company-Abruf ${basis}/api/company/overview lieferte HTTP ${antwort.status}`);
  }
  try {
    return await antwort.json();
  } catch (fehler) {
    throw new Error(`Company-Antwort von ${basis} ist kein JSON: ${fehler.message}`);
  }
}

async function main() {
  const opt = argumente(process.argv.slice(2));
  const befund = companyBefund(await ladeUebersicht(opt.url));
  console.log(
    `Company-API OK: ${befund.dataState}, ${befund.agenten} Agenten, ` +
    `${befund.offen} offen, ${befund.abteilungen} Abteilungen, ` +
    `${befund.offeneAufgaben} offene Aufgaben in der Liste`
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
