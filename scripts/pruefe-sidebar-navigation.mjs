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
 *   - die Desktop-Sidebar bleibt auf langen Ansichten beim Scrollen sichtbar,
 *   - der aktive Link bleibt auch in der intern scrollenden Sidebar sichtbar,
 *   - echte Viewport-Wechsel 1024 × 500 → 1280 × 800 → 1024 × 500,
 *   - der Querformat-Grenzfall 901 × 500,
 *   - eine explizite Änderung der Header-Höhe mit Neuberechnung der max-height,
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

async function pruefeStickySidebar(page) {
  for (const route of ['lab', 'spider', 'kb']) {
    await page.goto(`${opts.url}/?v=sticky-${route}#/${route}`, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
    await warteAufRoute(page, route);

    const position = await page.evaluate(() => {
      const liste = document.querySelector('.nav-liste');
      return {
        position: getComputedStyle(liste).position,
        top: Math.round(liste.getBoundingClientRect().top),
      };
    });
    pruefe(position.position === 'sticky', `Sidebar ist auf #/${route} nicht sticky (${position.position})`);

    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(80);
    const stand = await page.evaluate(() => {
      const liste = document.querySelector('.nav-liste');
      const kasten = liste.getBoundingClientRect();
      const links = [...liste.querySelectorAll('.nav[data-v]')];
      return {
        scrollY: Math.round(scrollY),
        top: Math.round(kasten.top),
        bottom: Math.round(kasten.bottom),
        links: links.length,
        sichtbareLinks: links.filter(link => {
          const linkKasten = link.getBoundingClientRect();
          return linkKasten.top >= 0 && linkKasten.bottom <= innerHeight;
        }).length,
      };
    });
    pruefe(stand.scrollY > 0, `#/${route} ist nicht lang genug für den Sticky-Test`);
    pruefe(stand.top >= -1 && stand.top <= 1,
      `Sidebar beginnt auf #/${route} nach dem Scrollen bei ${stand.top} px statt am oberen Rand`);
    pruefe(stand.bottom > 0, `Sidebar ist auf #/${route} nach dem Scrollen nicht sichtbar`);
    pruefe(stand.sichtbareLinks === stand.links,
      `Auf #/${route} sind nach dem Scrollen nur ${stand.sichtbareLinks}/${stand.links} Links sichtbar`);
  }

  await page.locator('.nav[data-v="overview"]').click();
  await warteAufRoute(page, 'overview');

  const aktiverStand = async () => page.evaluate(() => {
    const liste = document.querySelector('.nav-liste');
    const aktiv = liste?.querySelector('.nav[aria-current="page"]');
    if (!liste || !aktiv) return { text: '', inListe: false, imViewport: false, listenUnten: 0, listenAbstand: 0, maxHoehe: 0, viewportHoehe: innerHeight, scrollTop: 0 };
    const listenKasten = liste.getBoundingClientRect();
    const linkKasten = aktiv.getBoundingClientRect();
    return {
      text: aktiv.querySelector('b')?.textContent?.trim() || '',
      inListe: linkKasten.top >= listenKasten.top - 1 && linkKasten.bottom <= listenKasten.bottom + 1,
      imViewport: linkKasten.top >= -1 && linkKasten.bottom <= innerHeight + 1,
      listenUnten: Math.round(listenKasten.bottom),
      listenAbstand: Math.round(liste.offsetTop),
      maxHoehe: Math.round(parseFloat(getComputedStyle(liste).maxHeight)),
      viewportHoehe: innerHeight,
      scrollTop: Math.round(liste.scrollTop),
    };
  });

  const warteAufDynamischeHoehe = () => page.waitForFunction(() => {
    const liste = document.querySelector('.nav-liste');
    if (!liste) return false;
    const maxHoehe = parseFloat(getComputedStyle(liste).maxHeight);
    return Math.abs(maxHoehe - (innerHeight - liste.offsetTop)) <= 1;
  });

  const pruefeDynamischeHoehe = (stand, kontext) => {
    pruefe(Math.abs(stand.maxHoehe - (stand.viewportHoehe - stand.listenAbstand)) <= 1,
      `${kontext}: max-height ${stand.maxHoehe} px passt nicht zu ${stand.viewportHoehe} - ${stand.listenAbstand} px`);
    pruefe(stand.listenUnten <= stand.viewportHoehe + 1,
      `${kontext}: Linkliste endet bei ${stand.listenUnten} px ausserhalb des Viewports`);
  };

  const fadeStand = async () => page.evaluate(() => {
    const liste = document.querySelector('.nav-liste');
    if (!liste) return { ueberlaeuft: false, oben: false, unten: false, scrollbarWidth: '', scrollbarColor: '', scrollTop: 0 };
    const stil = getComputedStyle(liste);
    return {
      ueberlaeuft: liste.scrollHeight > liste.clientHeight + 1,
      oben: liste.classList.contains('fade-oben'),
      unten: liste.classList.contains('fade-unten'),
      scrollbarWidth: stil.scrollbarWidth,
      scrollbarColor: stil.scrollbarColor,
      scrollTop: Math.round(liste.scrollTop),
    };
  });

  const setzeListeScroll = async ziel => {
    await page.evaluate(position => {
      const liste = document.querySelector('.nav-liste');
      if (position === 'oben') liste.scrollTop = 0;
      else if (position === 'unten') liste.scrollTop = liste.scrollHeight;
      else liste.scrollTop = Math.round((liste.scrollHeight - liste.clientHeight) / 2);
    }, ziel);
    await page.waitForTimeout(60);
  };

  const pruefeVertikaleAffordanz = async kontext => {
    let fade = await fadeStand();
    pruefe(fade.ueberlaeuft, `${kontext}: Linkliste überläuft nicht für den Fade-Test`);
    pruefe(fade.scrollbarWidth === 'thin', `${kontext}: Scrollbar ist nicht schmal (${fade.scrollbarWidth})`);
    pruefe(fade.scrollbarColor !== 'auto' && fade.scrollbarColor !== '',
      `${kontext}: Scrollbar hat keine sichtbare Farbe (${fade.scrollbarColor})`);

    await setzeListeScroll('oben');
    fade = await fadeStand();
    pruefe(fade.scrollTop === 0, `${kontext}: Liste steht nicht am oberen Ende`);
    pruefe(fade.oben === false, `${kontext}: Oben-Fade bleibt am oberen Ende sichtbar`);
    pruefe(fade.unten === true, `${kontext}: Unten-Fade fehlt am oberen Ende`);

    await setzeListeScroll('unten');
    fade = await fadeStand();
    pruefe(fade.scrollTop > 0, `${kontext}: Liste steht nicht am unteren Ende`);
    pruefe(fade.oben === true, `${kontext}: Oben-Fade fehlt am unteren Ende`);
    pruefe(fade.unten === false, `${kontext}: Unten-Fade bleibt am unteren Ende sichtbar`);

    await setzeListeScroll('mitte');
    fade = await fadeStand();
    pruefe(fade.oben === true && fade.unten === true,
      `${kontext}: Fades fehlen in der Mitte`);
    notiere(`vertikale Scroll-Affordanz bei ${kontext}: Überlauf und beide Enden geprüft`);
  };

  for (const breite of [1280, 1024]) {
    await page.setViewportSize({ width: breite, height: 500 });
    await page.goto(`${opts.url}/?v=sticky-kurz-${breite}#/kb`, { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
    await warteAufRoute(page, 'kb');
    await warteAufDynamischeHoehe();

    let kurz = await aktiverStand();
    pruefe(kurz.text === 'Wissensbank', `Kurzer Viewport ${breite}: aktiver Link ist «${kurz.text}» statt «Wissensbank»`);
    pruefe(kurz.scrollTop > 0, `Kurzer Viewport ${breite}: die Linkliste wurde für den Deep-Link nicht intern gescrollt`);
    pruefe(kurz.inListe, `Kurzer Viewport ${breite}: aktiver Link liegt nach dem Deep-Link ausserhalb der Linkliste`);
    pruefe(kurz.imViewport, `Kurzer Viewport ${breite}: aktiver Link liegt nach dem Deep-Link ausserhalb des Viewports`);
    pruefeDynamischeHoehe(kurz, `Kurzer Viewport ${breite}`);

    await page.locator('.nav[data-v="overview"]').click();
    await warteAufRoute(page, 'overview');
    await page.evaluate(() => history.back());
    await warteAufRoute(page, 'kb');
    kurz = await aktiverStand();
    pruefe(kurz.text === 'Wissensbank', `Kurzer Viewport ${breite}: aktiver Link nach Zurück ist «${kurz.text}» statt «Wissensbank»`);
    pruefe(kurz.inListe && kurz.imViewport,
      `Kurzer Viewport ${breite}: aktiver Link ist nach Zurück nicht sichtbar`);
    pruefeDynamischeHoehe(kurz, `Kurzer Viewport ${breite} nach Zurück`);
    notiere(`aktiver Sidebar-Link bei ${breite} × 500 px nach Deep-Link und Zurück sichtbar`);
  }

  await pruefeVertikaleAffordanz('1024 × 500');

  // 901 × 500 liegt wegen der Querformat-Regel (max-width: 950px und
  // max-height: 500px) noch im Querformat-Modus. Dort gibt es keine intern
  // scrollende Desktop-Liste; der aktive Link muss trotzdem sichtbar sein.
  await page.setViewportSize({ width: 901, height: 500 });
  await page.goto(`${opts.url}/?v=sticky-grenze-901#/kb`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
  await warteAufRoute(page, 'kb');

  const grenze901 = async () => page.evaluate(() => {
    const nav = document.querySelector('#hauptnav');
    const liste = document.querySelector('.nav-liste');
    const aktiv = liste?.querySelector('.nav[aria-current="page"]');
    if (!nav || !liste || !aktiv) return { text: '', imViewport: false, imNav: false, internScrollbar: false };
    const navKasten = nav.getBoundingClientRect();
    const linkKasten = aktiv.getBoundingClientRect();
    return {
      text: aktiv.querySelector('b')?.textContent?.trim() || '',
      imViewport: linkKasten.top >= -1 && linkKasten.bottom <= innerHeight + 1,
      imNav: linkKasten.left >= navKasten.left - 1 && linkKasten.right <= navKasten.right + 1,
      internScrollbar: liste.scrollHeight > liste.clientHeight + 1,
    };
  });

  let grenze = await grenze901();
  pruefe(grenze.text === 'Wissensbank', `901 × 500: aktiver Link ist «${grenze.text}» statt «Wissensbank»`);
  pruefe(grenze.imViewport, '901 × 500: aktiver Link liegt ausserhalb des Viewports');
  pruefe(grenze.imNav, '901 × 500: aktiver Link liegt ausserhalb der Navigation');
  pruefe(!grenze.internScrollbar, '901 × 500: Querformat-Navigation scrollt unerwartet intern');

  await page.locator('.nav[data-v="overview"]').click();
  await warteAufRoute(page, 'overview');
  await page.evaluate(() => history.back());
  await warteAufRoute(page, 'kb');
  grenze = await grenze901();
  pruefe(grenze.text === 'Wissensbank' && grenze.imViewport && grenze.imNav,
    '901 × 500: aktiver Link ist nach Zurück nicht sichtbar');
  notiere('901 × 500: Querformat-Grenzfall hält den aktiven Link sichtbar');

  // Echte Viewport-Wechsel ohne Reload: Die Karte muss ihre Höhe und den
  // aktiven Link nach jedem Schritt neu berechnen.
  await page.setViewportSize({ width: 1024, height: 500 });
  await page.goto(`${opts.url}/?v=resize-start#/kb`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelectorAll('#hauptnav .nav[data-v]').length === 10);
  await warteAufRoute(page, 'kb');
  await warteAufDynamischeHoehe();

  let resizeStand = await aktiverStand();
  pruefeDynamischeHoehe(resizeStand, 'Resize-Start 1024 × 500');
  pruefe(resizeStand.text === 'Wissensbank' && resizeStand.inListe && resizeStand.imViewport,
    'Resize-Start 1024 × 500: aktiver Link ist nicht sichtbar');

  await page.setViewportSize({ width: 1280, height: 800 });
  await warteAufDynamischeHoehe();
  await page.waitForTimeout(80);
  resizeStand = await aktiverStand();
  pruefeDynamischeHoehe(resizeStand, 'Resize 1280 × 800');
  pruefe(resizeStand.text === 'Wissensbank' && resizeStand.inListe && resizeStand.imViewport,
    'Resize 1280 × 800: aktiver Link ist nicht sichtbar');
  const ohneUeberlauf = await fadeStand();
  pruefe(!ohneUeberlauf.ueberlaeuft, 'Resize 1280 × 800: Liste überläuft unerwartet');
  pruefe(!ohneUeberlauf.oben && !ohneUeberlauf.unten,
    'Resize 1280 × 800: Fades bleiben ohne Überlauf sichtbar');

  await page.setViewportSize({ width: 1024, height: 500 });
  await warteAufDynamischeHoehe();
  await page.waitForTimeout(80);
  resizeStand = await aktiverStand();
  pruefeDynamischeHoehe(resizeStand, 'Resize zurück zu 1024 × 500');
  pruefe(resizeStand.text === 'Wissensbank' && resizeStand.inListe && resizeStand.imViewport,
    'Resize zurück zu 1024 × 500: aktiver Link ist nicht sichtbar');
  pruefe(resizeStand.scrollTop > 0, 'Resize zurück zu 1024 × 500: Liste wurde nicht intern gescrollt');
  notiere('echte Resize-Übergänge 1024 × 500 → 1280 × 800 → 1024 × 500 geprüft');

  // Explizite Höhenänderung der Kopfzeile: Der ResizeObserver muss die
  // verfügbare Listenhöhe neu berechnen und den aktiven Link nachziehen.
  const vorHeader = await aktiverStand();
  await page.evaluate(() => {
    document.querySelector('.top').style.minHeight = '140px';
  });
  await warteAufDynamischeHoehe();
  await page.waitForTimeout(80);
  const nachHeader = await aktiverStand();
  pruefe(nachHeader.listenAbstand > vorHeader.listenAbstand,
    `Header-Höhe: Listenposition blieb bei ${nachHeader.listenAbstand} px`);
  pruefe(nachHeader.maxHoehe < vorHeader.maxHoehe,
    `Header-Höhe: max-height blieb bei ${nachHeader.maxHoehe} px`);
  pruefeDynamischeHoehe(nachHeader, 'Header-Höhe 140 px');
  pruefe(nachHeader.text === 'Wissensbank' && nachHeader.inListe && nachHeader.imViewport,
    'Header-Höhe: aktiver Link ist nicht sichtbar');
  notiere('Header-Höhe 140 px: max-height und aktiver Link neu berechnet');

  await page.evaluate(() => {
    document.querySelector('.top').style.minHeight = '';
  });
  await warteAufDynamischeHoehe();
  await page.waitForTimeout(80);
  const nachHeaderZurueck = await aktiverStand();
  pruefeDynamischeHoehe(nachHeaderZurueck, 'Header-Höhe zurückgesetzt');
  pruefe(nachHeaderZurueck.text === 'Wissensbank' && nachHeaderZurueck.inListe && nachHeaderZurueck.imViewport,
    'Header-Höhe zurückgesetzt: aktiver Link ist nicht sichtbar');
  notiere('Header-Höhe zurückgesetzt: max-height und aktiver Link weiter sichtbar');

  await page.setViewportSize({ width: 1280, height: 800 });
  notiere('Desktop-Sidebar bleibt auf Lab, Spider und Wissensbank sichtbar und bedienbar');
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

    await pruefeStickySidebar(page);
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
