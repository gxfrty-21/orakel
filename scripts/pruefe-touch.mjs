#!/usr/bin/env node
/**
 * Automatisierter Touch-Test für die Schiffsansicht.
 *
 * Geprüft werden echte Touch-Events über das Chromium-DevTools-Protokoll:
 *   - Ein-Finger-Pan verschiebt das Schiff,
 *   - auch bei starkem Zoom bleibt der Schiffskörper nach dem Ziehen sichtbar,
 *   - Zwei-Finger-Pinch zoomt danach hinein,
 *   - Tippen auf einen Raum öffnet die Ops-Details,
 *   - die Abteilungslegende startet schmal eingeklappt und lässt sich aufklappen,
 *   - die Legende filtert die Räume der gewählten Abteilung im Schiff,
 *   - kein Agent erscheint gleichzeitig in mehreren Schiffsclustern,
 *   - die mobilen Raumgrössen bleiben erhalten,
 *   - nach «Fit» liegen alle 103 Räume und elf Abteilungen im Schiffsviewport.
 *   - ein zweiter Porträt-Viewport (360 × 800) und Querformat (844 × 390)
 *     bestehen Fit, Auswahl und Legendenfilter ebenfalls.
 *   - im Querformat ist die Navigation eingeklappt, die Ops-Seitenleiste steht
 *     unter dem Viewport, die Zoomleiste bleibt im sichtbaren Bereich und die
 *     kompakte Abteilungslegende ist vollständig und ohne Überlauf bedienbar.
 *   - der 2400-px-Grossmodus aktiviert sich ab 1100 px Viewportbreite und
 *     hält seine Räume nach «Fit» ebenfalls vollständig im Viewport.
 *
 * Der Test ist für die Seed-Datenbank gedacht und läuft ohne Test-Framework.
 *
 * Aufruf:
 *   node scripts/pruefe-touch.mjs [--url http://127.0.0.1:3000] [--bilder artifacts/touch]
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { chromium } from 'playwright';

const opts = {
  url: 'http://127.0.0.1:3000',
  bilder: null,
  ergebnis: null,
};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--url') opts.url = argv[++i];
  else if (argv[i] === '--bilder') opts.bilder = argv[++i];
  else if (argv[i] === '--ergebnis') opts.ergebnis = argv[++i];
  else if (argv[i] === '--hilfe' || argv[i] === '-h') {
    console.log('Aufruf: node scripts/pruefe-touch.mjs [--url URL] [--bilder VERZEICHNIS] [--ergebnis DATEI]');
    process.exit(0);
  } else {
    console.error(`Unbekannte Option: ${argv[i]}`);
    process.exit(2);
  }
}
opts.url = opts.url.replace(/\/$/, '');
if (opts.bilder) mkdirSync(opts.bilder, { recursive: true });

let pruefungen = 0;
const geprueft = {
  pan: false, pinch: false, tippen: false, legende: false,
  filter: false, fit390: false, fit320: false,
};

function pruefe(bedingung, meldung) {
  pruefungen += 1;
  if (!bedingung) throw new Error(meldung);
}

function artefaktSlug(text) {
  return String(text)
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80)
    .replace(/-+$/g, '');
}

function transformWerte(text) {
  const treffer = text.match(/translate\(([-\d.]+)px,\s*([-\d.]+)px\)\s*scale\(([-\d.]+)\)/);
  if (!treffer) throw new Error(`Unerwartete Schiffs-Transform: ${text}`);
  return { x: Number(treffer[1]), y: Number(treffer[2]), zoom: Number(treffer[3]) };
}

async function touch(cdp, type, punkte) {
  await cdp.send('Input.dispatchTouchEvent', {
    type,
    touchPoints: punkte.map(p => ({
      id: p.id,
      x: p.x,
      y: p.y,
      radiusX: 1,
      radiusY: 1,
      force: 1,
    })),
  });
}

async function schiffTransform(page) {
  return transformWerte(await page.locator('#shipWorld').evaluate(el => el.style.transform));
}

async function sichtbarerSchiffsteil(page) {
  return page.evaluate(() => {
    const schiff = document.querySelector('#shipWorld .px-ship');
    const viewport = document.querySelector('#shipViewport');
    if (!schiff || !viewport) return { breite: 0, hoehe: 0 };
    const s = schiff.getBoundingClientRect();
    const v = viewport.getBoundingClientRect();
    return {
      breite: Math.max(0, Math.min(s.right, v.right) - Math.max(s.left, v.left)),
      hoehe: Math.max(0, Math.min(s.bottom, v.bottom) - Math.max(s.top, v.top)),
    };
  });
}

async function ladeSchiff(page) {
  await page.goto(`${opts.url}/?v=touch`, { waitUntil: 'networkidle' });
  await page.locator('.nav[data-v="ship"]').tap();
  await page.waitForFunction(() => document.querySelectorAll('#shipWorld .px-room[data-agent]').length === 103);
  await page.waitForFunction(() => /\d+\s*%/.test(document.querySelector('#shipZoomWert')?.textContent || ''));
  await page.waitForTimeout(300);
}

async function pruefeCluster(page) {
  return page.evaluate(() => {
    const clusters = [...document.querySelectorAll('#shipWorld .px-dept')];
    const vorkommen = new Map();
    let raeume = 0;
    for (const cluster of clusters) {
      const code = cluster.querySelector('.px-dept-head b')?.textContent?.trim() || '?';
      for (const raum of cluster.querySelectorAll('[data-agent]')) {
        const id = raum.dataset.agent;
        raeume++;
        if (!vorkommen.has(id)) vorkommen.set(id, []);
        vorkommen.get(id).push(code);
      }
    }
    const mehrfach = [...vorkommen]
      .filter(([, codes]) => codes.length > 1)
      .map(([id, codes]) => `${id} (${codes.join(', ')})`);
    return {
      clusters: clusters.length,
      raeume,
      eindeutigeAgenten: vorkommen.size,
      ausserhalb: document.querySelectorAll('#shipWorld [data-agent]').length - raeume,
      mehrfach,
    };
  });
}

async function pruefeLegendeUeberlauf(page, label) {
  const stand = await page.evaluate(() => {
    const el = document.querySelector('#shipLegend');
    if (!el || !el.open || !el.getClientRects().length) return null;
    const rahmen = el.getBoundingClientRect();
    const eintraege = [...el.querySelectorAll('[data-dept]')]
      .map(b => b.getBoundingClientRect())
      .filter(r => r.width > 0 && r.height > 0);
    return {
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      ausserhalb: eintraege.filter(r =>
        r.left < rahmen.left - 1 || r.right > rahmen.right + 1).length,
      seitenScroll: document.documentElement.scrollWidth,
      viewport: innerWidth,
    };
  });
  pruefe(stand, `${label}: geöffnete Legende ist nicht sichtbar`);
  pruefe(stand.scrollWidth <= stand.clientWidth + 1,
    `${label}: Legende läuft horizontal über (${stand.scrollWidth}>${stand.clientWidth})`);
  pruefe(stand.ausserhalb === 0,
    `${label}: ${stand.ausserhalb} Legendeneinträge liegen ausserhalb des Legendenrahmens`);
  pruefe(stand.seitenScroll <= stand.viewport + 1,
    `${label}: Seite läuft nach dem Öffnen der Legende horizontal über (${stand.seitenScroll}>${stand.viewport})`);
}

async function pruefeFit(page, breite, minBreite, minHoehe) {
  await page.evaluate(() => document.querySelector('[data-ship-zoom="fit"]').click());
  await page.waitForTimeout(350);
  const fit = await page.evaluate(() => {
    const vp = document.querySelector('#shipViewport').getBoundingClientRect();
    const boxes = (selektor) => [...document.querySelectorAll(selektor)]
      .map(el => el.getBoundingClientRect());
    const ausserhalb = (liste) => liste.filter(r =>
      r.left < vp.left - 1 || r.top < vp.top - 1
      || r.right > vp.right + 1 || r.bottom > vp.bottom + 1).length;
    const raeume = boxes('#shipWorld .px-room[data-agent]');
    const abteilungen = boxes('#shipWorld .px-dept');
    return {
      zoom: document.querySelector('#shipZoomWert')?.textContent?.trim() || '',
      raeume: {
        anzahl: raeume.length,
        minBreite: Math.min(...raeume.map(r => r.width)),
        minHoehe: Math.min(...raeume.map(r => r.height)),
        ausserhalb: ausserhalb(raeume),
      },
      abteilungen: {
        anzahl: abteilungen.length,
        ausserhalb: ausserhalb(abteilungen),
      },
    };
  });
  pruefe(fit.raeume.anzahl === 103,
    `${breite} px: Fit zeigt ${fit.raeume.anzahl} statt 103 Räume`);
  pruefe(fit.abteilungen.anzahl === 11,
    `${breite} px: Fit zeigt ${fit.abteilungen.anzahl} statt 11 Abteilungen`);
  pruefe(fit.raeume.minBreite >= minBreite,
    `${breite} px: kleinster Raum ist ${fit.raeume.minBreite.toFixed(1)} px breit, erwartet mindestens ${minBreite} px`);
  pruefe(fit.raeume.minHoehe >= minHoehe,
    `${breite} px: kleinster Raum ist ${fit.raeume.minHoehe.toFixed(1)} px hoch, erwartet mindestens ${minHoehe} px`);
  pruefe(fit.raeume.ausserhalb === 0,
    `${breite} px: ${fit.raeume.ausserhalb} Räume liegen ausserhalb des Schiffsviewports`);
  pruefe(fit.abteilungen.ausserhalb === 0,
    `${breite} px: ${fit.abteilungen.ausserhalb} Abteilungen liegen ausserhalb des Schiffsviewports`);
  return fit;
}

async function mitte(page) {
  const box = await page.locator('#shipViewport').boundingBox();
  pruefe(box && box.width > 200 && box.height > 200, 'Schiffsviewport ist nicht sichtbar');
  return {
    cx: Math.round(box.x + box.width / 2),
    cy: Math.round(box.y + box.height / 2),
  };
}

async function pruefeMobilViewport(browser, konfiguration) {
  const { label, width, height, minBreite, minHoehe, gross = false } = konfiguration;
  const context = await browser.newContext({
    viewport: { width, height },
    screen: { width, height },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  });
  try {
    const page = await context.newPage();
    await ladeSchiff(page);
    const modus = await page.evaluate(() => {
      const world = document.querySelector('#shipWorld');
      const raum = world?.querySelector('.px-room[data-agent]');
      return {
        gross: world?.classList.contains('px-gross') || false,
        weltBreite: world?.offsetWidth || 0,
        raumHoehe: raum?.offsetHeight || 0,
      };
    });
    pruefe(modus.gross === gross,
      `${label}: Grossmodus ist ${modus.gross ? 'aktiv' : 'inaktiv'}, erwartet ${gross ? 'aktiv' : 'inaktiv'}`);
    if (gross) {
      pruefe(modus.weltBreite === 2400,
        `${label}: Grossmodus ist ${modus.weltBreite} px statt 2400 px breit`);
      pruefe(modus.raumHoehe === 150,
        `${label}: Grossmodus-Raum ist ${modus.raumHoehe} px statt 150 px hoch`);
    }
    const fit = await pruefeFit(page, `${width}×${height}`, minBreite, minHoehe);
    if (width > height && !gross) {
      const querformat = await page.evaluate(() => {
        const nav = document.querySelector('.side');
        const toggle = document.querySelector('#navToggle');
        const viewport = document.querySelector('#shipViewport').getBoundingClientRect();
        const side = document.querySelector('#shipSide').getBoundingClientRect();
        const zoom = document.querySelector('.ship-zoom').getBoundingClientRect();
        return {
          navDisplay: nav ? getComputedStyle(nav).display : 'fehlt',
          navExpanded: toggle?.getAttribute('aria-expanded'),
          toggleDisplay: toggle ? getComputedStyle(toggle).display : 'fehlt',
          sideUnterViewport: side.top >= viewport.bottom - 1,
          zoomPosition: getComputedStyle(document.querySelector('.ship-zoom')).position,
          zoomImBild: zoom.top >= 0 && zoom.bottom <= innerHeight,
          bodyKlasse: document.body.classList.contains('nav-eingeklappt'),
        };
      });
      pruefe(querformat.navDisplay === 'none',
        `${label}: Navigation ist im Querformat nicht eingeklappt (${querformat.navDisplay})`);
      pruefe(querformat.navExpanded === 'false' && querformat.bodyKlasse,
        `${label}: Navigation meldet den eingeklappten Zustand nicht`);
      pruefe(querformat.toggleDisplay !== 'none',
        `${label}: Navigationsschalter ist im Querformat nicht sichtbar`);
      pruefe(querformat.sideUnterViewport,
        `${label}: Ops-Seitenleiste steht nicht unter dem Schiffsviewport`);
      pruefe(querformat.zoomPosition === 'fixed' && querformat.zoomImBild,
        `${label}: Zoomleiste ist nicht fest im sichtbaren Bereich`);

      const toggle = page.locator('#navToggle');
      await toggle.tap();
      await page.waitForTimeout(150);
      const geoeffnet = await page.evaluate(() => ({
        display: getComputedStyle(document.querySelector('.side')).display,
        expanded: document.querySelector('#navToggle')?.getAttribute('aria-expanded'),
      }));
      pruefe(geoeffnet.display !== 'none' && geoeffnet.expanded === 'true',
        `${label}: Navigationsschalter öffnet die Navigation nicht`);
      await toggle.tap();
      await page.waitForTimeout(150);
    }
    const legende = page.locator('#shipLegend');
    const erwartetOffen = width > 760;
    const offen = await legende.evaluate(el => el.open);
    pruefe(offen === erwartetOffen,
      `${label}: Legende ist ${offen ? 'offen' : 'eingeklappt'}, erwartet ${erwartetOffen ? 'offen' : 'eingeklappt'}`);
    if (!offen) {
      await legende.locator('summary').tap();
      await page.waitForTimeout(200);
    }
    const sichtbareDepts = await legende.locator('[data-dept]').evaluateAll(nodes =>
      nodes.filter(n => {
        const r = n.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }).length);
    pruefe(sichtbareDepts === 11,
      `${label}: Legende zeigt ${sichtbareDepts} statt 11 Abteilungen`);
    const legendeStand = await legende.evaluate(el => ({
      offen: el.open,
      kopf: (el.querySelector('summary')?.innerText || '').replace(/\s+/g, ' ').trim(),
    }));
    pruefe(legendeStand.offen,
      `${label}: Legende ist nach dem Aufklappen nicht offen`);
    pruefe(/SEKTOREN/.test(legendeStand.kopf) && /FILTER/.test(legendeStand.kopf)
      && /11 ABTEILUNGEN/.test(legendeStand.kopf),
      `${label}: Legendenkopf ist nicht kompakt («${legendeStand.kopf}»)`);
    await pruefeLegendeUeberlauf(page, label);

    const raum = page.locator('#shipWorld .px-room[data-agent]').first();
    const raumName = (await raum.locator('.px-tag').innerText()).trim();
    await raum.tap();
    await page.waitForTimeout(350);
    const auswahl = await page.evaluate(() => ({
      on: document.querySelectorAll('#shipWorld .px-room[data-agent].on').length,
      kicker: document.querySelector('#shipSideInhalt .sd-kicker')?.textContent?.trim() || '',
      dept: document.querySelector('#shipWorld .px-room[data-agent].on')?.closest('.px-dept')?.dataset.dept || '',
      legendGewaehlt: document.querySelector('#shipLegend [data-dept].is-selected')?.dataset.dept || '',
      scrollW: document.documentElement.scrollWidth,
      viewportW: innerWidth,
    }));
    pruefe(auswahl.on === 1, `${label}: Tippen hat keinen Raum ausgewählt (${auswahl.on})`);
    pruefe(auswahl.kicker.startsWith('AGENTENRAUM'),
      `${label}: Tippen hat die Ops-Details nicht geöffnet (${auswahl.kicker})`);
    pruefe(auswahl.dept && auswahl.legendGewaehlt === auswahl.dept,
      `${label}: Legende markiert «${auswahl.legendGewaehlt}» statt «${auswahl.dept}»`);
    pruefe(auswahl.scrollW === auswahl.viewportW,
      `${label}: Seite hat horizontalen Überlauf (${auswahl.scrollW}>${auswahl.viewportW})`);

    const filterA = legende.locator('[data-dept="A"]');
    await filterA.tap();
    await page.waitForTimeout(200);
    const filter = await page.evaluate(() => {
      const world = document.querySelector('#shipWorld');
      return {
        aktiv: world?.classList.contains('filter-aktiv') || false,
        hervorgehoben: world?.querySelectorAll('.px-dept.is-filter-active').length || 0,
        raeume: world?.querySelectorAll('.px-dept.is-filter-active .px-room[data-agent]').length || 0,
      };
    });
    pruefe(filter.aktiv && filter.hervorgehoben === 1 && filter.raeume === 10,
      `${label}: Legendenfilter hebt ${filter.hervorgehoben} Abteilung mit ${filter.raeume} statt 10 Räumen hervor`);
    return { label, fit, raumName };
  } finally {
    await context.close();
  }
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    screen: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
  });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  let erfolgreich = false;
  let fehlerText = '';

  try {
    await ladeSchiff(page);
    // Mindestwerte knapp unter den gemessenen 24,4 × 25,5 px bei 390 px.
    const fit390 = await pruefeFit(page, 390, 24, 25);
    geprueft.fit390 = true;
    const cluster = await pruefeCluster(page);
    pruefe(cluster.mehrfach.length === 0,
      `Agenten erscheinen in mehreren Schiffsclustern: ${cluster.mehrfach.join('; ')}`);
    pruefe(cluster.ausserhalb === 0,
      `${cluster.ausserhalb} Agentenraum/-räume liegen ausserhalb der Schiffscluster`);
    pruefe(cluster.raeume === 103 && cluster.eindeutigeAgenten === 103,
      `Schiffscluster enthalten ${cluster.raeume} Räume von ${cluster.eindeutigeAgenten} Agenten`);
    const legende = page.locator('#shipLegend');
    pruefe(!(await legende.evaluate(el => el.open)),
      'Legende ist auf schmalen Bildschirmen standardmässig offen');
    const { cx, cy } = await mitte(page);

    // Ein Finger pannt. Der Zoom darf dabei unverändert bleiben.
    const vorPan = await schiffTransform(page);
    await touch(cdp, 'touchStart', [{ id: 1, x: cx, y: cy }]);
    await page.waitForTimeout(80);
    await touch(cdp, 'touchMove', [{ id: 1, x: cx + 52, y: cy + 30 }]);
    await page.waitForTimeout(120);
    await touch(cdp, 'touchEnd', []);
    await page.waitForTimeout(450);
    const nachPan = await schiffTransform(page);
    pruefe(Math.abs(nachPan.x - vorPan.x) >= 20,
      `Pan hat das Schiff nicht verschoben (${vorPan.x} → ${nachPan.x})`);
    pruefe(Math.abs(nachPan.zoom - vorPan.zoom) < 0.001, 'Pan hat den Zoom verändert');
    geprueft.pan = true;

    // Zwei Finger zoomen direkt nach dem Pan. Der Pinch startet in der
    // sichtbaren Viewport-Mitte und wird nach aussen geführt.
    const vorPinch = await schiffTransform(page);
    await touch(cdp, 'touchStart', [
      { id: 2, x: cx - 40, y: cy },
      { id: 3, x: cx + 40, y: cy },
    ]);
    await page.waitForTimeout(80);
    await touch(cdp, 'touchMove', [
      { id: 2, x: cx - 70, y: cy },
      { id: 3, x: cx + 70, y: cy },
    ]);
    await page.waitForTimeout(100);
    await touch(cdp, 'touchMove', [
      { id: 2, x: cx - 100, y: cy },
      { id: 3, x: cx + 100, y: cy },
    ]);
    await page.waitForTimeout(120);
    await touch(cdp, 'touchEnd', []);
    await page.waitForTimeout(450);
    const nachPinch = await schiffTransform(page);
    pruefe(nachPinch.zoom > vorPinch.zoom * 1.15,
      `Pinch hat nicht ausreichend gezoomt (${vorPinch.zoom} → ${nachPinch.zoom})`);
    geprueft.pinch = true;

    // Frisch laden, damit der Tipp-Test wieder die volle Fit-Ansicht hat.
    await ladeSchiff(page);
    const ersterRaum = page.locator('#shipWorld .px-room[data-agent]').first();
    const raumName = (await ersterRaum.locator('.px-tag').innerText()).trim();
    await ersterRaum.tap();
    await page.waitForTimeout(450);
    const auswahl = await page.evaluate(() => ({
      on: document.querySelectorAll('#shipWorld .px-room[data-agent].on').length,
      kicker: document.querySelector('#shipSideInhalt .sd-kicker')?.textContent?.trim() || '',
      legend: document.querySelectorAll('#shipLegend [data-dept]').length,
      dept: document.querySelector('#shipWorld .px-room[data-agent].on')?.closest('.px-dept')?.dataset.dept || '',
      legendGewaehlt: document.querySelector('#shipLegend [data-dept].is-selected')?.dataset.dept || '',
      legendSchatten: (() => {
        const b = document.querySelector('#shipLegend [data-dept].is-selected');
        return b ? getComputedStyle(b).boxShadow : '';
      })(),
      scrollW: document.documentElement.scrollWidth,
      viewportW: innerWidth,
    }));
    pruefe(auswahl.on === 1, `Tippen hat keinen Raum ausgewählt (${auswahl.on})`);
    pruefe(auswahl.kicker.startsWith('AGENTENRAUM'),
      `Tippen hat die Ops-Details nicht geöffnet (${auswahl.kicker})`);
    pruefe(auswahl.legend === 11, `Legende zeigt ${auswahl.legend} statt 11 Abteilungen`);
    pruefe(auswahl.dept && auswahl.legendGewaehlt === auswahl.dept,
      `Legende markiert Abteilung «${auswahl.legendGewaehlt}» statt der gewählten «${auswahl.dept}»`);
    pruefe(auswahl.legendSchatten && auswahl.legendSchatten !== 'none',
      'Die markierte Abteilung hat keine sichtbare Hervorhebung');
    pruefe(auswahl.scrollW === auswahl.viewportW, 'Seite hat horizontalen Überlauf');
    geprueft.tippen = true;

    // Die kompakte Legende muss sich per Tippen aufklappen lassen und dann
    // alle elf Abteilungen sichtbar machen.
    const legendeKopf = legende.locator('summary');
    await legendeKopf.tap();
    await page.waitForTimeout(200);
    const legendeAuf = await legende.evaluate(el => el.open);
    const kopfText = (await legendeKopf.innerText()).replace(/\s+/g, ' ').trim();
    const sichtbareDepts = await legende.locator('[data-dept]').evaluateAll(nodes =>
      nodes.filter(n => {
        const r = n.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }).length);
    pruefe(legendeAuf, 'Legende lässt sich nicht aufklappen');
    pruefe(kopfText.includes('SEKTOREN') && kopfText.includes('FILTER')
      && kopfText.includes('11 ABTEILUNGEN'),
      `Legendenkopf ist nicht kompakt (${kopfText})`);
    pruefe(sichtbareDepts === 11,
      `Aufgeklappte Legende zeigt ${sichtbareDepts} statt 11 Abteilungen`);
    await pruefeLegendeUeberlauf(page, 'Geöffnete Legende bei 390 px');
    geprueft.legende = true;

    // Die Legende ist ein Filter: ein Tippen hebt die Räume der Abteilung
    // hervor, ohne den bereits geöffneten Agenten in der Seitenleiste zu ersetzen.
    const filterA = legende.locator('[data-dept="A"]');
    const kickerVorFilter = await page.locator('#shipSideInhalt .sd-kicker').innerText();
    await filterA.tap();
    await page.waitForTimeout(250);
    const filterAn = await page.evaluate(() => {
      const btn = document.querySelector('#shipLegend [data-dept="A"]');
      const world = document.querySelector('#shipWorld');
      const aktiv = world?.querySelector('.px-dept.is-filter-active');
      const gedimmt = world?.querySelector('.px-dept:not(.is-filter-active)');
      const deckkraft = el => el ? Number(getComputedStyle(el).opacity) : null;
      return {
        gedrueckt: btn?.getAttribute('aria-pressed') === 'true',
        titel: btn?.title || '',
        aktivKlasse: btn?.classList.contains('is-active') || false,
        gewaehltKlasse: btn?.classList.contains('is-selected') || false,
        aktiv: world?.classList.contains('filter-aktiv') || false,
        hervorgehoben: world?.querySelectorAll('.px-dept.is-filter-active').length || 0,
        raeume: world?.querySelectorAll('.px-dept.is-filter-active .px-room[data-agent]').length || 0,
        gedimmt: world?.querySelectorAll('.px-dept:not(.is-filter-active)').length || 0,
        aktivDeckkraft: deckkraft(aktiv),
        gedimmtDeckkraft: deckkraft(gedimmt),
        seite: document.querySelector('#shipSideInhalt .sd-kicker')?.textContent?.trim() || '',
      };
    });
    pruefe(filterAn.gedrueckt, 'Legendenfilter meldet keinen aktiven Zustand');
    pruefe(filterAn.aktivKlasse, 'Legendenfilter wird in der Legende nicht hervorgehoben');
    pruefe(!filterAn.gewaehltKlasse, 'Legendenfilter trägt zusätzlich die Auswahlmarkierung');
    pruefe(filterAn.titel === 'Filter lösen', `Legendenfilter hat den Titel «${filterAn.titel}»`);
    pruefe(filterAn.aktiv, 'Legendenfilter aktiviert die Hervorhebung im Schiff nicht');
    pruefe(filterAn.hervorgehoben === 1 && filterAn.raeume === 10,
      `Legendenfilter hebt ${filterAn.hervorgehoben} Abteilung mit ${filterAn.raeume} statt 10 Räumen hervor`);
    pruefe(filterAn.gedimmt === 10,
      `Legendenfilter dimmt ${filterAn.gedimmt} statt 10 andere Abteilungen`);
    pruefe(filterAn.aktivDeckkraft === 1 && filterAn.gedimmtDeckkraft < 0.5,
      `Legendenfilter setzt die Deckkraft nicht (${filterAn.aktivDeckkraft} / ${filterAn.gedimmtDeckkraft})`);
    pruefe(filterAn.seite === kickerVorFilter,
      'Legendenfilter hat die geöffneten Agentendetails ersetzt');

    await filterA.tap();
    await page.waitForTimeout(150);
    const filterAus = await page.evaluate(() => {
      const btn = document.querySelector('#shipLegend [data-dept="A"]');
      const world = document.querySelector('#shipWorld');
      return {
        gedrueckt: btn?.getAttribute('aria-pressed') === 'true',
        titel: btn?.title || '',
        aktivKlasse: btn?.classList.contains('is-active') || false,
        gewaehltKlasse: btn?.classList.contains('is-selected') || false,
        aktiv: world?.classList.contains('filter-aktiv') || false,
        hervorgehoben: world?.querySelectorAll('.px-dept.is-filter-active').length || 0,
      };
    });
    pruefe(!filterAus.gedrueckt && !filterAus.aktiv && filterAus.hervorgehoben === 0,
      'Legendenfilter lässt sich durch erneutes Tippen nicht lösen');
    pruefe(!filterAus.aktivKlasse && filterAus.gewaehltKlasse,
      'Auswahlmarkierung kehrt nach dem Lösen des Filters nicht zur gewählten Abteilung zurück');
    pruefe(filterAus.titel === 'Abteilung im Schiff hervorheben',
      `Gelöster Legendenfilter hat den Titel «${filterAus.titel}»`);
    geprueft.filter = true;

    // Auch bei starkem Zoom darf kein Zug den Schiffskörper vollständig aus
    // dem Viewport schieben. Der Innenabstand der Bühne zählt nicht als Schiff.
    await page.locator('[data-ship-zoom="fit"]').click();
    for (let i = 0; i < 12; i++) await page.locator('[data-ship-zoom="in"]').click();
    await page.waitForTimeout(150);
    const grenzZoom = await schiffTransform(page);
    pruefe(grenzZoom.zoom > 1.5, `Grenztest zoomt nicht ausreichend (${grenzZoom.zoom})`);
    const grenzMitte = await mitte(page);
    await page.mouse.move(grenzMitte.cx, grenzMitte.cy);
    await page.mouse.down();
    await page.mouse.move(grenzMitte.cx, -3000, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(250);
    const sichtbar = await sichtbarerSchiffsteil(page);
    pruefe(sichtbar.breite >= 60 && sichtbar.hoehe >= 60,
      `Grenztest: nur ${sichtbar.breite.toFixed(1)}×${sichtbar.hoehe.toFixed(1)} px Schiff sichtbar`);
    await page.locator('[data-ship-zoom="fit"]').click();

    if (opts.bilder) {
      await page.screenshot({ path: join(opts.bilder, 'touch-final.png'), fullPage: true });
    }

    // Dieselben Mindestgrössen und die vollständige Fit-Sichtbarkeit zusätzlich
    // auf dem schmalen 320-px-Viewport prüfen.
    const mobilZusatz = [
      await pruefeMobilViewport(browser, {
        label: 'Porträt 360×800', width: 360, height: 800,
        minBreite: 22, minHoehe: 23,
      }),
      await pruefeMobilViewport(browser, {
        label: 'Querformat 844×390', width: 844, height: 390,
        minBreite: 31, minHoehe: 32,
      }),
      await pruefeMobilViewport(browser, {
        label: 'Gross 1100×800', width: 1100, height: 800,
        minBreite: 31, minHoehe: 32, gross: true,
      }),
      await pruefeMobilViewport(browser, {
        label: 'Gross 1100×1400', width: 1100, height: 1400,
        minBreite: 31, minHoehe: 31, gross: true,
      }),
    ];

    let fit320;
    const schmalContext = await browser.newContext({
      viewport: { width: 320, height: 700 },
      screen: { width: 320, height: 700 },
      deviceScaleFactor: 3,
      isMobile: true,
      hasTouch: true,
    });
    try {
      const schmalPage = await schmalContext.newPage();
      await ladeSchiff(schmalPage);
      // Mindestwerte knapp unter den gemessenen 19,8 × 20,5 px bei 320 px.
      fit320 = await pruefeFit(schmalPage, 320, 19.5, 20);
      geprueft.fit320 = true;
    } finally {
      await schmalContext.close();
    }

    erfolgreich = true;
    const fitText = (fit) => `${fit.zoom} · min. ${fit.raeume.minBreite.toFixed(1)}×${fit.raeume.minHoehe.toFixed(1)} px · ${fit.raeume.anzahl - fit.raeume.ausserhalb}/${fit.raeume.anzahl} sichtbar`;
    const zusatzText = mobilZusatz.map(z => `${z.label}${z.fit ? ' ' + fitText(z.fit) : ''}`).join(' · ');
    const ergebnis = {
      ok: true,
      fehler: 0,
      pruefungen,
      ...geprueft,
      viewports: 1 + mobilZusatz.length + 1,
    };
    if (opts.ergebnis) {
      mkdirSync(dirname(opts.ergebnis), { recursive: true });
      writeFileSync(opts.ergebnis, JSON.stringify(ergebnis, null, 2) + '\n');
    }
    console.log(`Touch OK: Pan ${Math.round(Math.abs(nachPan.x - vorPan.x))} px · Pinch ${(vorPinch.zoom * 100).toFixed(0)} % → ${(nachPinch.zoom * 100).toFixed(0)} % · ${cluster.clusters} Cluster ohne Doppelung · Tippen öffnet ${raumName} · Filter A 10 Räume / gelöst · Fit 390 px ${fitText(fit390)} · ${zusatzText} · Fit 320 px ${fitText(fit320)}`);
  } catch (fehler) {
    fehlerText = fehler instanceof Error ? fehler.message : String(fehler);
    throw fehler;
  } finally {
    if (!erfolgreich && opts.bilder) {
      const datei = join(opts.bilder, `touch-fehler-${artefaktSlug(fehlerText) || 'unbekannt'}.png`);
      await page.screenshot({ path: datei, fullPage: true }).catch(() => {});
    }
    await browser.close();
  }
}

main().catch(fehler => {
  console.error(`Touch-Test fehlgeschlagen: ${fehler.message}`);
  process.exit(1);
});
