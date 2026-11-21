#!/usr/bin/env node
/**
 * End-to-End-Prüfung: Widerspruch von der API bis in die Claim-Karte.
 *
 * Voraussetzung ist ein laufendes Dashboard mit der Testdatenbank aus
 * ``scripts/seed_widerspruch.py``. Der Test liest den echten
 * ``/api/nexus/status``-Response, den die Spider-Ansicht selbst anfordert,
 * öffnet danach die Widerspruchskarte und vergleicht Grund, Sicherheit,
 * Quellen und normalisierte bp-Werte mit der API-Antwort.
 *
 * Aufruf:
 *   node scripts/pruefe-widerspruch-e2e.mjs --url http://127.0.0.1:3300
 *   node scripts/pruefe-widerspruch-e2e.mjs --url http://127.0.0.1:3300 --negativtest
 *
 * ``--negativtest`` prüft zusätzlich, dass der Kartenprüfer eine im DOM
 * verfälschte und eine entfernte Widerspruchszeile als Fehler erkennt und
 * dass der API-Prüfer eine aus der API-Antwort entfernte Zeile ablehnt.
 *
 * Erwartungen und API-Vertragsprüfung liegen gemeinsam in
 * ``widerspruch-api-pruefung.mjs``; derselbe Vertrag läuft browsorfrei in
 * ``tests/test_widerspruch_api_pruefung.py``.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { chromium } from 'playwright';

import { ERWARTET, apiBefund } from './widerspruch-api-pruefung.mjs';

function argumente(argv) {
  const opts = {
    url: process.env.ORAKEL_URL || 'http://127.0.0.1:3200',
    negativtest: false,
    ergebnis: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--negativtest') opts.negativtest = true;
    else if (arg === '--ergebnis') opts.ergebnis = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-widerspruch-e2e.mjs [--url URL] [--negativtest] [--ergebnis DATEI]');
      process.exit(0);
    } else {
      console.error(`Unbekannte Option: ${arg}`);
      process.exit(2);
    }
  }
  opts.url = opts.url.replace(/\/$/, '');
  return opts;
}

async function leseWiderspruchKarte(page, claim) {
  return page.evaluate(({ kernaussage }) => {
    const karten = [...document.querySelectorAll('#bewertungClaims .li')];
    const card = karten.find(k =>
      (k.textContent || '').replace(/\s+/g, ' ').includes(kernaussage)
    );
    const detail = card?.querySelector('.claimWiderspruch');
    if (!detail) return { gefunden: false };
    return {
      gefunden: true,
      sichtbar: Boolean(card?.getClientRects().length) &&
        Boolean(detail.getClientRects().length),
      cardText: (card?.textContent || '').replace(/\s+/g, ' ').trim(),
      grund: (detail.querySelector('.claimWiderspruchGrund')?.textContent || '').trim(),
      sicherheit: (detail.querySelector('.claimWiderspruchSicherheit')?.textContent || '')
        .replace(/\s+/g, ' ').trim(),
      quellen: (detail.querySelector('.claimWiderspruchQuellen')?.textContent || '')
        .replace(/\s+/g, ' ').trim(),
      vergleich: (detail.querySelector('.claimWiderspruchWerte')?.textContent || '')
        .replace(/\s+/g, ' ').trim(),
    };
  }, { kernaussage: claim.kernaussage });
}

function pruefeWiderspruchKarte(karte, widerspruch, claim) {
  if (!karte.gefunden) throw new Error('Widerspruchsdetail fehlt in #bewertungClaims');
  if (!karte.sichtbar) throw new Error('Widerspruchskarte oder -detail ist nicht sichtbar');
  if (!karte.cardText.includes(claim.kernaussage)) {
    throw new Error(`Claim-Text fehlt in der Karte: «${claim.kernaussage}»`);
  }
  if (karte.grund !== widerspruch.grund) {
    throw new Error(`Karten-Grund «${karte.grund}» statt «${widerspruch.grund}»`);
  }
  const sicherheit = Number((karte.sicherheit.match(/[\d.,]+/) || [''])[0].replace(',', '.'));
  if (sicherheit !== Number(widerspruch.sicherheit)) {
    throw new Error(
      `Karten-Sicherheit ${karte.sicherheit} statt API ${widerspruch.sicherheit}`
    );
  }
  if (!karte.quellen.includes(widerspruch.quelle_a) ||
      !karte.quellen.includes(widerspruch.quelle_b)) {
    throw new Error(`Karten-Quellen fehlen: ${karte.quellen}`);
  }
  const vergleichszahlen = (karte.vergleich.match(/\d+(?:[.,]\d+)?/g) || [])
    .map(zahl => Number(zahl.replace(',', '.')));
  if (!vergleichszahlen.includes(ERWARTET.wertA) ||
      !vergleichszahlen.includes(ERWARTET.wertB)) {
    throw new Error(`Karten-Vergleichswerte fehlen: ${karte.vergleich}`);
  }
}

function erwarteFehler(funktion, teil) {
  try {
    funktion();
  } catch (fehler) {
    const text = fehler instanceof Error ? fehler.message : String(fehler);
    if (text.includes(teil)) return;
    throw new Error(`Negativtest: falscher Fehler «${text}», erwartet «${teil}»`);
  }
  throw new Error(`Negativtest: erwarteter Fehler «${teil}» blieb aus`);
}

async function pruefeNegativfaelle(page, widerspruch, claim, status) {
  const details = [];
  const falscheZeile = await page.evaluate(({ kernaussage }) => {
    const karten = [...document.querySelectorAll('#bewertungClaims .li')];
    const card = karten.find(k =>
      (k.textContent || '').replace(/\s+/g, ' ').includes(kernaussage)
    );
    const detail = card?.querySelector('.claimWiderspruch');
    const grund = detail?.querySelector('.claimWiderspruchGrund');
    if (!grund) return false;
    grund.textContent = 'Falscher Widerspruchsgrund';
    return true;
  }, { kernaussage: claim.kernaussage });
  if (!falscheZeile) throw new Error('Negativtest-Vorbereitung: Widerspruchszeile fehlt');
  const karteFalsch = await leseWiderspruchKarte(page, claim);
  erwarteFehler(() => pruefeWiderspruchKarte(karteFalsch, widerspruch, claim), 'Karten-Grund');
  details.push('falsche DOM-Zeile');

  const entfernteZeile = await page.evaluate(({ kernaussage }) => {
    const karten = [...document.querySelectorAll('#bewertungClaims .li')];
    const card = karten.find(k =>
      (k.textContent || '').replace(/\s+/g, ' ').includes(kernaussage)
    );
    const detail = card?.querySelector('.claimWiderspruch');
    if (!detail) return false;
    detail.remove();
    return true;
  }, { kernaussage: claim.kernaussage });
  if (!entfernteZeile) throw new Error('Negativtest-Vorbereitung: Widerspruchszeile fehlt');
  const karteFehlt = await leseWiderspruchKarte(page, claim);
  erwarteFehler(() => pruefeWiderspruchKarte(karteFehlt, widerspruch, claim),
    'Widerspruchsdetail fehlt');
  details.push('fehlende DOM-Zeile');

  const apiKopie = structuredClone(status);
  const apiClaims = apiKopie.claims || {};
  const apiZeilen = Array.isArray(apiClaims.widersprueche)
    ? apiClaims.widersprueche
    : [];
  apiClaims.widersprueche = apiZeilen.filter(w =>
    !(Number(w.claim_id) === Number(widerspruch.claim_id) &&
      w.grund === widerspruch.grund)
  );
  apiKopie.claims = apiClaims;
  if (apiClaims.widersprueche.length === apiZeilen.length) {
    throw new Error('Negativtest-Vorbereitung: API-Widerspruchszeile fehlt bereits');
  }
  erwarteFehler(() => apiBefund(apiKopie),
    'API enthält den erwarteten Widerspruch nicht');
  details.push('fehlende API-Zeile');
  if (details.length !== 3) {
    throw new Error(`Negativtest: ${details.length} statt 3 Fälle ausgeführt`);
  }
  console.log(
    `Widerspruch-E2E-Negativtest OK: 3/3 (${details.join(', ')} erkannt)`
  );
  return details;
}

async function main() {
  const opt = argumente(process.argv.slice(2));
  const browser = await chromium.launch({ headless: true });
  const seitenfehler = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    page.on('pageerror', fehler => seitenfehler.push(String(fehler)));
    await page.goto(`${opt.url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );

    const nav = page.locator('.nav[data-v="spider"]');
    if (!await nav.count()) throw new Error('Spider-Navigation fehlt');

    // Der Browser selbst lädt den Status; genau diese Antwort wird geprüft.
    const statusAntwort = page.waitForResponse(
      antwort => antwort.request().method() === 'GET' &&
        (() => {
          try { return new URL(antwort.url()).pathname === '/api/nexus/status'; }
          catch { return false; }
        })(),
      { timeout: 15000 },
    );
    await nav.click();
    const antwort = await statusAntwort;
    if (!antwort.ok()) throw new Error(`/api/nexus/status antwortet mit HTTP ${antwort.status()}`);
    const status = await antwort.json();
    const { widerspruch, claim } = apiBefund(status);

    await page.waitForFunction(
      grund => [...document.querySelectorAll('#bewertungClaims .li .claimWiderspruch')]
        .some(detail => (detail.textContent || '').includes(grund)),
      widerspruch.grund,
      { timeout: 10000 },
    );

    const karte = await leseWiderspruchKarte(page, claim);
    pruefeWiderspruchKarte(karte, widerspruch, claim);
    if (seitenfehler.length) {
      throw new Error(`Seitenfehler: ${seitenfehler.join('; ')}`);
    }
    console.log(
      `Widerspruch-E2E OK: Claim ${claim.id}, «${widerspruch.grund}», ` +
      `${widerspruch.quelle_a} ↔ ${widerspruch.quelle_b}, ` +
      `${ERWARTET.wertA} bp ↔ ${ERWARTET.wertB} bp`
    );
    const ergebnis = {
      ok: true,
      positiv: { geprueft: 1, widersprueche: 1 },
      negativ: null,
    };
    if (opt.negativtest) {
      const details = await pruefeNegativfaelle(page, widerspruch, claim, status);
      ergebnis.negativ = {
        faelle: details.length,
        erkannt: details.length,
        details,
      };
    }
    if (opt.ergebnis) {
      mkdirSync(dirname(opt.ergebnis), { recursive: true });
      writeFileSync(opt.ergebnis, JSON.stringify(ergebnis, null, 2) + '\n');
    }
  } finally {
    await browser.close();
  }
}

main().catch(fehler => {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
});
