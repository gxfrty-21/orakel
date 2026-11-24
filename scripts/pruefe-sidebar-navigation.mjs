#!/usr/bin/env node
/**
 * Browser-Test für die Sidebar-Navigation.
 *
 * Geprüft werden:
 *   - die zehn unveränderten Bereiche und ihre stabilen Links,
 *   - der Start auf «Übersicht» mit genau einem aria-current="page",
 *   - Deep-Links wie #/lab und #/spider nach einem direkten Aufruf,
 *   - der Browser-Verlauf mit Zurück und Vorwärts,
 *   - die Fokussierung der jeweiligen Überschrift nach Maus- und Tastaturwahl,
 *   - der Skip-Link «Zum Inhalt» als erste Tastaturstation,
 *   - ein unbekannter Hash fällt auf «Übersicht» zurück,
 *   - der aktive Link bleibt auf schmalen Viewports sichtbar,
 *   - die Rand-Fades zeigen nur die Richtung mit weiteren Bereichen,
 *   - die Querformat-Navigation öffnet sich beim Verlassen des Raumschiffs.
 *
 * Der Test ist für die Seed-Datenbank gedacht und läuft ohne Test-Framework.
 *
 * Aufruf:
 *   node scripts/pruefe-sidebar-navigation.mjs [--url http://127.0.0.1:3000] [--ergebnis DATEI]
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { chromium } from 'playwright';

const opts = {
  url: 'http://127.0.0.1:3000',
  ergebnis: null,
};
const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--url') opts.url = argv[++i];
  else if (argv[i] === '--ergebnis') opts.ergebnis = argv[++i];
  else if (argv[i] === '--hilfe' || argv[i] === '-h') {
    console.log('Aufruf: node scripts/pruefe-sidebar-navigation.mjs [--url URL] [--ergebnis DATEI]');
    process.exit(0);
  } else {
    console.error(`Unbekannte Option: ${argv[i]}`);
    process.exit(2);
  }
}
opts.url = opts.url.replace(/\/$/, '');

const ERWARTETE_BEREICHE = [
  ['overview', 'Übersicht'],
  ['risk', 'Risiko & Daten'],
  ['lab', 'Lab'],
  ['strat', 'Strategien'],
  ['research', 'Research'],
  ['globe', 'Weltkugel'],
  ['betrieb', 'Betrieb'],
  ['ship', 'Raumschiff'],
  ['spider', 'Spider'],
  ['kb', 'Wissensbank'],
];

let pruefungen = 0;
const schritte = [];
const seitenfehler = [];

function pruefe(bedingung, meldung) {
  pruefungen += 1;
  if (!bedingung) throw new Error(meldung);
}

function notiere(text) {
  schritte.push(text);
  console.log(`OK: ${text}`);
}

async function warteAufRoute(page, route) {
  await page.waitForFunction(
    ziel => location.hash === `#/${ziel}`,
    route,
    { timeout: 5000 },
  );
}

async function zustand(page, erwartet) {
  const stand = await page.evaluate((ziel) => {
    const sichtbar = [...document.querySelectorAll('.view')].filter(s => !s.hidden);
    const aktiv = [...document.querySelectorAll('#hauptnav .nav.on')];
    const current = [...document.querySelectorAll('#hauptnav .nav[aria-current="page"]')];
    const fokus = document.activeElement;
    const überschrift = document.querySelector(`#v-${ziel} h1`);
    return {
      hash: location.hash,
      sichtbareIds: sichtbar.map(s => s.id),
      aktiveBereiche: aktiv.map(a => a.dataset.v),
      currentBereiche: current.map(a => a.dataset.v),
      titel: document.title,
      fokusTag: fokus?.tagName || '',
      fokusId: fokus?.id || '',
      fokusKlasse: typeof fokus?.className === 'string' ? fokus.className : '',
      fokusIstUeberschrift: fokus === überschrift,
      ueberschrift: überschrift?.textContent?.trim() || '',
    };
  }, erwartet);
  return stand;
}

async function oeffne(page, suffix = '') {
  await page.goto(`${opts.url}/?v=navigation${suffix}`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
  await warteAufRoute(page, 'overview');
}

async function pruefeSchmaleNavigation(browser) {
  for (const breite of [360, 768]) {
    const seite = await browser.newPage({ viewport: { width: breite, height: 800 } });
    seite.on('pageerror', fehler => seitenfehler.push(fehler.message));
    try {
      await seite.goto(`${opts.url}/?v=schmal-${breite}#/kb`, { waitUntil: 'networkidle' });
      await seite.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
      await warteAufRoute(seite, 'kb');

      const messe = async () => seite.evaluate(() => {
        const nav = document.querySelector('#hauptnav');
        const aktiv = nav?.querySelector('.nav[aria-current="page"]');
        if (!nav || !aktiv) return { aktiv: '', sichtbar: false, ueberlaeuft: false, fadeLinks: false, fadeRechts: false };
        const navKasten = nav.getBoundingClientRect();
        const linkKasten = aktiv.getBoundingClientRect();
        return {
          aktiv: aktiv.querySelector('b')?.textContent?.trim() || '',
          sichtbar: linkKasten.left >= navKasten.left - 1 && linkKasten.right <= navKasten.right + 1,
          ueberlaeuft: nav.scrollWidth > nav.clientWidth + 1,
          fadeLinks: nav.classList.contains('fade-links'),
          fadeRechts: nav.classList.contains('fade-rechts'),
        };
      });

      let stand = await messe();
      pruefe(stand.aktiv === 'Wissensbank', `Aktiver Link bei ${breite} px ist «${stand.aktiv}» statt «Wissensbank»`);
      pruefe(stand.ueberlaeuft, `Navigation bei ${breite} px überläuft nicht horizontal`);
      pruefe(stand.sichtbar, `Aktiver Link bei ${breite} px liegt ausserhalb des sichtbaren Ausschnitts`);
      pruefe(stand.fadeRechts === false, `Rechts-Fade bleibt bei ${breite} px am rechten Ende sichtbar`);
      pruefe(stand.fadeLinks === true, `Links-Fade fehlt bei ${breite} px am rechten Ende`);

      await seite.reload({ waitUntil: 'networkidle' });
      await warteAufRoute(seite, 'kb');
      stand = await messe();
      pruefe(stand.sichtbar, `Aktiver Link bei ${breite} px ist nach Reload nicht sichtbar`);
      pruefe(stand.fadeRechts === false, `Rechts-Fade bleibt bei ${breite} px nach Reload sichtbar`);

      await seite.evaluate(() => {
        const nav = document.querySelector('#hauptnav');
        nav.scrollLeft = 100;
        nav.dispatchEvent(new Event('scroll'));
      });
      stand = await messe();
      pruefe(stand.fadeLinks && stand.fadeRechts,
        `Richtungsabhängige Ränder fehlen bei ${breite} px in der Mitte`);

      await seite.locator('.nav[data-v="overview"]').click();
      await warteAufRoute(seite, 'overview');
      stand = await messe();
      pruefe(stand.fadeLinks === false, `Links-Fade bleibt bei ${breite} px am linken Ende sichtbar`);
      pruefe(stand.fadeRechts === true, `Rechts-Fade fehlt bei ${breite} px am linken Ende`);

      await seite.evaluate(() => history.back());
      await warteAufRoute(seite, 'kb');
      stand = await messe();
      pruefe(stand.sichtbar, `Aktiver Link bei ${breite} px ist nach Zurück nicht sichtbar`);
      pruefe(stand.fadeRechts === false, `Rechts-Fade bleibt bei ${breite} px nach Zurück sichtbar`);
      notiere(`aktiver Sidebar-Link und richtungsabhängige Ränder bei ${breite} px geprüft`);
    } finally {
      await seite.close();
    }
  }
}

async function pruefeQuerformatNavigation(browser) {
  const seite = await browser.newPage({ viewport: { width: 900, height: 450 } });
  seite.on('pageerror', fehler => seitenfehler.push(fehler.message));
  try {
    await seite.goto(`${opts.url}/?v=querformat`, { waitUntil: 'networkidle' });
    await seite.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
    await warteAufRoute(seite, 'overview');

    const navZustand = async () => seite.evaluate(() => {
      const nav = document.querySelector('#hauptnav');
      const toggle = document.querySelector('#navToggle');
      return {
        eingeklappt: document.body.classList.contains('nav-eingeklappt'),
        navDisplay: nav ? getComputedStyle(nav).display : 'fehlt',
        expanded: toggle?.getAttribute('aria-expanded') || '',
      };
    });

    await seite.locator('.nav[data-v="ship"]').click();
    await warteAufRoute(seite, 'ship');
    await seite.waitForFunction(() => document.body.classList.contains('nav-eingeklappt'));
    let stand = await navZustand();
    pruefe(stand.eingeklappt, 'Querformat klappt die Navigation im Raumschiff nicht ein');
    pruefe(stand.navDisplay === 'none', `Navigation im Raumschiff ist bei 900x450 sichtbar: ${stand.navDisplay}`);
    pruefe(stand.expanded === 'false', `aria-expanded im Raumschiff ist «${stand.expanded}» statt «false»`);

    await seite.evaluate(() => history.back());
    await warteAufRoute(seite, 'overview');
    await seite.waitForFunction(() => !document.body.classList.contains('nav-eingeklappt'));
    stand = await navZustand();
    pruefe(!stand.eingeklappt, 'Querformat öffnet die Navigation nach dem Verlassen des Raumschiffs nicht');
    pruefe(stand.navDisplay !== 'none', 'Navigation bleibt nach dem Verlassen des Raumschiffs ausgeblendet');
    pruefe(stand.expanded === 'true', `aria-expanded nach dem Verlassen ist «${stand.expanded}» statt «true»`);

    await seite.locator('#navToggle').click();
    await seite.waitForFunction(() => document.body.classList.contains('nav-eingeklappt'));
    await seite.locator('#navToggle').click();
    await seite.waitForFunction(() => !document.body.classList.contains('nav-eingeklappt'));
    notiere('Querformat-Navigation öffnet nach dem Raumschiff und lässt sich weiter umschalten');
  } finally {
    await seite.close();
  }
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('pageerror', fehler => seitenfehler.push(fehler.message));

  try {
    await oeffne(page);

    const links = await page.locator('#hauptnav .nav[data-v]').evaluateAll(nodes =>
      nodes.map(link => ({
        v: link.dataset.v,
        text: link.querySelector('b')?.textContent?.trim() || '',
        href: link.getAttribute('href'),
      })));
    pruefe(links.length === 10, `Sidebar enthält ${links.length} statt 10 Bereiche`);
    for (const [v, text] of ERWARTETE_BEREICHE) {
      const link = links.find(eintrag => eintrag.v === v);
      pruefe(Boolean(link), `Bereich ${v} fehlt`);
      pruefe(link.text === text, `Bereich ${v} heisst «${link.text}» statt «${text}»`);
      pruefe(link.href === `#/${v}`, `Bereich ${v} verlinkt auf «${link.href}» statt «#/${v}»`);
    }
    notiere('zehn unveränderte Bereiche mit stabilen Deep-Links');

    let stand = await zustand(page, 'overview');
    pruefe(stand.hash === '#/overview', `Start-Hash ist «${stand.hash}» statt «#/overview»`);
    pruefe(stand.sichtbareIds.length === 1 && stand.sichtbareIds[0] === 'v-overview',
      `Startansicht ist nicht ausschließlich Übersicht: ${stand.sichtbareIds.join(', ')}`);
    pruefe(stand.currentBereiche.length === 1 && stand.currentBereiche[0] === 'overview',
      `aria-current beim Start: ${stand.currentBereiche.join(', ') || 'fehlt'}`);
    pruefe(stand.titel.includes('Übersicht'), `Dokumenttitel nennt nicht Übersicht: ${stand.titel}`);
    notiere('Startroute, aria-current und Dokumenttitel');

    await page.locator('.nav[data-v="lab"]').click();
    await warteAufRoute(page, 'lab');
    stand = await zustand(page, 'lab');
    pruefe(stand.sichtbareIds.length === 1 && stand.sichtbareIds[0] === 'v-lab',
      `Lab ist nach dem Klick nicht allein sichtbar: ${stand.sichtbareIds.join(', ')}`);
    pruefe(stand.aktiveBereiche.length === 1 && stand.aktiveBereiche[0] === 'lab',
      `Falscher aktiver Bereich nach Lab-Klick: ${stand.aktiveBereiche.join(', ') || 'fehlt'}`);
    pruefe(stand.currentBereiche.length === 1 && stand.currentBereiche[0] === 'lab',
      `aria-current nach Lab-Klick: ${stand.currentBereiche.join(', ') || 'fehlt'}`);
    pruefe(stand.fokusIstUeberschrift, 'Fokus liegt nach dem Lab-Klick nicht auf der Lab-Überschrift');
    pruefe(stand.titel.includes('Lab'), `Dokumenttitel nennt nicht Lab: ${stand.titel}`);
    notiere('Mausklick setzt Route, aria-current und Fokus auf die Überschrift');

    await page.locator('.nav[data-v="spider"]').click();
    await warteAufRoute(page, 'spider');
    await page.evaluate(() => history.back());
    await page.waitForFunction(() => location.hash === '#/lab');
    stand = await zustand(page, 'lab');
    pruefe(stand.sichtbareIds[0] === 'v-lab', 'Zurück führt nicht zur Lab-Ansicht');
    pruefe(stand.fokusIstUeberschrift, 'Fokus fehlt nach dem Zurück-Wechsel');

    await page.evaluate(() => history.forward());
    await page.waitForFunction(() => location.hash === '#/spider');
    stand = await zustand(page, 'spider');
    pruefe(stand.sichtbareIds[0] === 'v-spider', 'Vorwärts führt nicht zur Spider-Ansicht');
    pruefe(stand.fokusIstUeberschrift, 'Fokus fehlt nach dem Vorwärts-Wechsel');
    notiere('Browser-Verlauf mit Zurück und Vorwärts');

    await page.goto(`${opts.url}/?v=deep#/spider`, { waitUntil: 'networkidle' });
    await warteAufRoute(page, 'spider');
    stand = await zustand(page, 'spider');
    pruefe(stand.sichtbareIds[0] === 'v-spider', 'Direktaufruf #/spider zeigt nicht Spider');
    pruefe(stand.currentBereiche.length === 1 && stand.currentBereiche[0] === 'spider',
      'Direktaufruf setzt aria-current nicht auf Spider');
    notiere('Deep-Link über direkten Seitenaufruf');

    await page.reload({ waitUntil: 'networkidle' });
    await warteAufRoute(page, 'spider');
    stand = await zustand(page, 'spider');
    pruefe(stand.sichtbareIds[0] === 'v-spider', 'Reload auf #/spider zeigt nicht Spider');
    pruefe(stand.currentBereiche.length === 1 && stand.currentBereiche[0] === 'spider',
      'Reload setzt aria-current nicht auf Spider');
    notiere('Reload behält die tief verlinkte Ansicht');

    await page.goto(`${opts.url}/?v=unbekannt#/gibtsnicht`, { waitUntil: 'networkidle' });
    await warteAufRoute(page, 'overview');
    stand = await zustand(page, 'overview');
    pruefe(stand.sichtbareIds[0] === 'v-overview', 'Unbekannter Hash fällt nicht auf Übersicht zurück');
    pruefe(stand.currentBereiche[0] === 'overview', 'Unbekannter Hash setzt aria-current nicht zurück');
    notiere('unbekannte Route fällt auf Übersicht zurück');

    await page.goto(`${opts.url}/?v=tastatur`, { waitUntil: 'networkidle' });
    await warteAufRoute(page, 'overview');
    await page.keyboard.press('Tab');
    const ersterFokus = await page.evaluate(() => ({
      klasse: typeof document.activeElement?.className === 'string' ? document.activeElement.className : '',
      text: document.activeElement?.textContent?.trim() || '',
    }));
    pruefe(ersterFokus.klasse.includes('skip-link'),
      `Erste Tastaturstation ist nicht der Skip-Link: «${ersterFokus.klasse}» / «${ersterFokus.text}»`);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => location.hash === '#inhalt');
    const inhalt = await page.evaluate(() => ({
      id: document.activeElement?.id || '',
      tag: document.activeElement?.tagName || '',
    }));
    pruefe(inhalt.id === 'inhalt' && inhalt.tag === 'MAIN',
      `Skip-Link fokussiert nicht main#inhalt: ${inhalt.tag}#${inhalt.id}`);
    notiere('Skip-Link ist erste Tastaturstation und fokussiert den Inhalt');

    await page.goto(`${opts.url}/?v=enter`, { waitUntil: 'networkidle' });
    await warteAufRoute(page, 'overview');
    await page.locator('.nav[data-v="research"]').focus();
    await page.keyboard.press('Enter');
    await warteAufRoute(page, 'research');
    await page.waitForTimeout(50);
    stand = await zustand(page, 'research');
    pruefe(stand.sichtbareIds[0] === 'v-research', 'Enter auf Research öffnet nicht Research');
    pruefe(stand.currentBereiche[0] === 'research', 'Enter setzt aria-current nicht auf Research');
    pruefe(stand.fokusIstUeberschrift, 'Enter setzt den Fokus nicht auf die Research-Überschrift');
    notiere('Tastaturwahl per Enter mit Fokus auf der Überschrift');

    await pruefeSchmaleNavigation(browser);
    await pruefeQuerformatNavigation(browser);

    pruefe(seitenfehler.length === 0,
      `Seitenfehler: ${seitenfehler.join(' | ')}`);
    notiere('keine JavaScript-Seitenfehler');

    const ergebnis = {
      schema: 'sidebar-navigation.v1',
      ok: true,
      checks: pruefungen,
      schritte,
      url: opts.url,
      generated_at: new Date().toISOString(),
    };
    if (opts.ergebnis) {
      mkdirSync(dirname(opts.ergebnis), { recursive: true });
      writeFileSync(opts.ergebnis, `${JSON.stringify(ergebnis, null, 2)}\n`);
      console.log(`Ergebnis geschrieben: ${opts.ergebnis}`);
    }
    console.log(`Sidebar-Navigation OK: ${pruefungen} Prüfungen`);
  } finally {
    await browser.close();
  }
}

main().catch(fehler => {
  console.error(`Sidebar-Navigation FEHLGESCHLAGEN: ${fehler.message}`);
  process.exitCode = 1;
});
