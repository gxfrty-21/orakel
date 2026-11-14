#!/usr/bin/env node
/**
 * Automatisierter Touch-Test für die Schiffsansicht.
 *
 * Geprüft werden echte Touch-Events über das Chromium-DevTools-Protokoll:
 *   - Ein-Finger-Pan verschiebt das Schiff,
 *   - Zwei-Finger-Pinch zoomt danach hinein,
 *   - Tippen auf einen Raum öffnet die Ops-Details,
 *   - die Abteilungslegende startet schmal eingeklappt und lässt sich aufklappen,
 *   - kein Agent erscheint gleichzeitig in mehreren Schiffsclustern.
 *
 * Der Test ist für die Seed-Datenbank gedacht und läuft ohne Test-Framework.
 *
 * Aufruf:
 *   node scripts/pruefe-touch.mjs [--url http://127.0.0.1:3000] [--bilder artifacts/touch]
 */

import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright';

const opts = {
  url: 'http://127.0.0.1:3000',
  bilder: null,
};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--url') opts.url = argv[++i];
  else if (argv[i] === '--bilder') opts.bilder = argv[++i];
  else if (argv[i] === '--hilfe' || argv[i] === '-h') {
    console.log('Aufruf: node scripts/pruefe-touch.mjs [--url URL] [--bilder VERZEICHNIS]');
    process.exit(0);
  } else {
    console.error(`Unbekannte Option: ${argv[i]}`);
    process.exit(2);
  }
}
opts.url = opts.url.replace(/\/$/, '');
if (opts.bilder) mkdirSync(opts.bilder, { recursive: true });

function pruefe(bedingung, meldung) {
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

async function ladeSchiff(page) {
  await page.goto(`${opts.url}/?v=touch`, { waitUntil: 'networkidle' });
  await page.locator('.nav[data-v="ship"]').tap();
  await page.waitForFunction(() => document.querySelectorAll('#shipWorld .agent-room').length === 103);
  await page.waitForFunction(() => /\d+\s*%/.test(document.querySelector('#shipZoomWert')?.textContent || ''));
  await page.waitForTimeout(300);
}

async function pruefeCluster(page) {
  return page.evaluate(() => {
    const clusters = [...document.querySelectorAll('#shipWorld .ship-dept')];
    const vorkommen = new Map();
    let raeume = 0;
    for (const cluster of clusters) {
      const code = cluster.querySelector('.ship-dept-code')?.textContent?.trim() || '?';
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

async function mitte(page) {
  const box = await page.locator('#shipViewport').boundingBox();
  pruefe(box && box.width > 200 && box.height > 200, 'Schiffsviewport ist nicht sichtbar');
  return {
    cx: Math.round(box.x + box.width / 2),
    cy: Math.round(box.y + box.height / 2),
  };
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

    // Frisch laden, damit der Tipp-Test wieder die volle Fit-Ansicht hat.
    await ladeSchiff(page);
    const ersterRaum = page.locator('#shipWorld .agent-room').first();
    const raumName = (await ersterRaum.locator('.ar-sign b').innerText()).trim();
    await ersterRaum.tap();
    await page.waitForTimeout(450);
    const auswahl = await page.evaluate(() => ({
      on: document.querySelectorAll('#shipWorld .agent-room.on').length,
      kicker: document.querySelector('#shipSideInhalt .sd-kicker')?.textContent?.trim() || '',
      legend: document.querySelectorAll('#shipLegend [data-dept]').length,
      scrollW: document.documentElement.scrollWidth,
      viewportW: innerWidth,
    }));
    pruefe(auswahl.on === 1, `Tippen hat keinen Raum ausgewählt (${auswahl.on})`);
    pruefe(auswahl.kicker.startsWith('AGENTENRAUM'),
      `Tippen hat die Ops-Details nicht geöffnet (${auswahl.kicker})`);
    pruefe(auswahl.legend === 11, `Legende zeigt ${auswahl.legend} statt 11 Abteilungen`);
    pruefe(auswahl.scrollW === auswahl.viewportW, 'Seite hat horizontalen Überlauf');

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
    pruefe(kopfText.includes('SEKTOREN') && kopfText.includes('11 ABTEILUNGEN'),
      `Legendenkopf ist nicht kompakt (${kopfText})`);
    pruefe(sichtbareDepts === 11,
      `Aufgeklappte Legende zeigt ${sichtbareDepts} statt 11 Abteilungen`);

    if (opts.bilder) {
      await page.screenshot({ path: join(opts.bilder, 'touch-final.png'), fullPage: true });
    }
    erfolgreich = true;
    console.log(`Touch OK: Pan ${Math.round(Math.abs(nachPan.x - vorPan.x))} px · Pinch ${(vorPinch.zoom * 100).toFixed(0)} % → ${(nachPinch.zoom * 100).toFixed(0)} % · ${cluster.clusters} Cluster ohne Doppelung · Tippen öffnet ${raumName}`);
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
