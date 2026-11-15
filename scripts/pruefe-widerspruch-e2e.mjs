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
 */

import { chromium } from 'playwright';

const ERWARTET = {
  grund: 'Richtung steigt gegen sinkt',
  sicherheit: 0.8,
  quelleA: 'e2e-a.example',
  quelleB: 'e2e-b.example',
  wertA: 450,
  wertB: 400,
};

function argumente(argv) {
  const opts = { url: process.env.ORAKEL_URL || 'http://127.0.0.1:3200' };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-widerspruch-e2e.mjs [--url URL]');
      process.exit(0);
    } else {
      console.error(`Unbekannte Option: ${arg}`);
      process.exit(2);
    }
  }
  opts.url = opts.url.replace(/\/$/, '');
  return opts;
}

function apiBefund(status) {
  if (!status || status.ok !== true) {
    throw new Error('API-Antwort ist nicht ok');
  }
  const claims = status.claims || {};
  const widersprueche = claims.widersprueche || [];
  const passend = widersprueche.find(w =>
    w.grund === ERWARTET.grund &&
    w.quelle_a === ERWARTET.quelleA &&
    w.quelle_b === ERWARTET.quelleB &&
    Number(w.wert_a_bp) === ERWARTET.wertA &&
    Number(w.wert_b_bp) === ERWARTET.wertB
  );
  if (!passend) {
    throw new Error(
      'API enthält den erwarteten Widerspruch nicht: ' +
      JSON.stringify(widersprueche)
    );
  }
  if (Number(passend.sicherheit) !== ERWARTET.sicherheit) {
    throw new Error(
      `API-Widerspruchssicherheit ${passend.sicherheit} statt ${ERWARTET.sicherheit}`
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

    const karte = await page.evaluate(({ grund }) => {
      const details = [...document.querySelectorAll('#bewertungClaims .li .claimWiderspruch')];
      const detail = details.find(d =>
        (d.querySelector('.claimWiderspruchGrund')?.textContent || '').trim() === grund
      );
      if (!detail) return { gefunden: false };
      const card = detail.closest('.li');
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
    }, { grund: widerspruch.grund });

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
    if (seitenfehler.length) {
      throw new Error(`Seitenfehler: ${seitenfehler.join('; ')}`);
    }
    console.log(
      `Widerspruch-E2E OK: Claim ${claim.id}, «${widerspruch.grund}», ` +
      `${widerspruch.quelle_a} ↔ ${widerspruch.quelle_b}, ` +
      `${ERWARTET.wertA} bp ↔ ${ERWARTET.wertB} bp`
    );
  } finally {
    await browser.close();
  }
}

main().catch(fehler => {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
});
