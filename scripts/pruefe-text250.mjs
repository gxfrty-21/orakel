#!/usr/bin/env node
/**
 * Prüflauf für 250 % Textskalierung im Orakel-Dashboard.
 *
 * Für jede Ansicht werden die berechneten Schriftgrössen und Zeilenhöhen in
 * `main` mit 2,5 multipliziert — so wie es eine Browser-Textskalierung tut.
 * Danach wird geprüft, ob Inhalte seitlich aus ihrem Kasten oder aus dem
 * Viewport laufen. Tabellen werden zusätzlich mit langen deutschen Komposita
 * belastet und als Karten geprüft.
 *
 * Voraussetzung: laufendes Dashboard mit Daten, z. B.:
 *   cp seed/orakel-seed.db /tmp/orakel-text250.db
 *   ORAKEL_DB_PFAD=/tmp/orakel-text250.db python -m orakel serve --port 3000
 *   npm ci --prefix scripts && npm --prefix scripts exec playwright install chromium
 *   node scripts/pruefe-text250.mjs
 *
 * Optionen:
 *   --url <adresse>        Standard http://127.0.0.1:3000
 *   --breiten 360,320,280  Standard 360,320,280
 *   --ansichten lab,kb     Standard alle sieben Ansichten
 *   --ohne-tabellen        Nur Seitenüberläufe prüfen, Tabellen überspringen
 *   --bilder <verzeichnis> Schreibt bei Befunden je Ansicht und Breite einen Screenshot
 */

import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright';

const LANGS = 'Donaudampfschifffahrtsgesellschaftskapitänsmützenhalterungsverordnung';
const LANGES_LABEL = 'Bevölkerungsentwicklungsprognoseberechnungsgrundlagenverordnung';
const STANDARD_ANSICHTEN = ['overview', 'risk', 'lab', 'betrieb', 'spider', 'globe', 'kb'];
const WARTEZEIT = { overview: 300, risk: 350, lab: 400, betrieb: 750, spider: 650, globe: 1300, kb: 1500 };

function argumente(argv) {
  const opts = {
    url: process.env.ORAKEL_URL || 'http://127.0.0.1:3000',
    breiten: [360, 320, 280],
    ansichten: [...STANDARD_ANSICHTEN],
    tabellen: true,
    bilder: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--breiten') opts.breiten = argv[++i].split(',').map(Number).filter(n => n >= 200);
    else if (arg === '--ansichten') opts.ansichten = argv[++i].split(',').map(s => s.trim()).filter(Boolean);
    else if (arg === '--ohne-tabellen') opts.tabellen = false;
    else if (arg === '--bilder') opts.bilder = argv[++i];
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250.mjs [--url URL] [--breiten 360,320,280]\n' +
        '       [--ansichten overview,risk,lab,betrieb,spider,globe,kb] [--ohne-tabellen]\n' +
        '       [--bilder <verzeichnis>]');
      process.exit(0);
    }
    else { console.error(`Unbekannte Option: ${arg}`); process.exit(2); }
  }
  opts.url = opts.url.replace(/\/$/, '');
  if (!opts.breiten.length) { console.error('Keine gültigen Breiten angegeben.'); process.exit(2); }
  if (!opts.ansichten.length) { console.error('Keine Ansichten angegeben.'); process.exit(2); }
  for (const ansicht of opts.ansichten) {
    if (!(ansicht in WARTEZEIT)) { console.error(`Unbekannte Ansicht: ${ansicht}`); process.exit(2); }
  }
  return opts;
}

async function pruefeServer(url) {
  let antwort;
  try {
    antwort = await fetch(`${url}/api/report`);
  } catch (fehler) {
    throw new Error(`Dashboard unter ${url} nicht erreichbar (${fehler.message}).\n` +
      'Starte es z. B. mit: ORAKEL_DB_PFAD=/tmp/orakel-text250.db python -m orakel serve --port 3000');
  }
  if (!antwort.ok) throw new Error(`${url}/api/report antwortet mit HTTP ${antwort.status}`);
  const bericht = await antwort.json();
  const validierungen = bericht.validierungen?.length ?? 0;
  if (!validierungen) {
    console.warn('Hinweis: Der Bericht enthält keine Validierungen. Die Prüfung deckt dann weniger Inhalte ab.');
  }
  return { validierungen };
}

/** Setzt die Textskalierung zurück und wendet den Faktor auf alle Elemente an. */
async function skaliere(page, faktor) {
  await page.evaluate((k) => {
    const elemente = [...document.querySelectorAll('main, main *')]
      .filter(el => !['CANVAS', 'SCRIPT', 'STYLE'].includes(el.tagName));
    for (const el of elemente) {
      el.style.removeProperty('font-size');
      el.style.removeProperty('line-height');
    }
    const werte = elemente.map(el => {
      const cs = getComputedStyle(el);
      return [el, parseFloat(cs.fontSize), parseFloat(cs.lineHeight)];
    });
    for (const [el, fs, lh] of werte) {
      if (fs > 0) el.style.fontSize = `${fs * k}px`;
      if (lh > 0) el.style.lineHeight = `${lh * k}px`;
    }
  }, faktor);
}

/** Meldet Elemente, die seitlich aus dem Kasten oder dem Viewport laufen. */
async function messeAnsicht(page, ansicht, breite) {
  return page.evaluate(({ ansicht, breite }) => {
    const bereich = document.querySelector('#v-' + ansicht);
    const befunde = [];
    if (!bereich) return { befunde: ['Ansicht nicht gefunden'], gerendert: false };
    const gerendert = bereich.querySelectorAll('.kpi, .panel, .card, .globe-rail-item').length > 0;

    for (const el of bereich.querySelectorAll('*')) {
      if (!el.getClientRects().length) continue;
      if (el.closest('table.tbl')) continue;            // Tabellen werden separat belastet.
      if (el.closest('.vault-zoom')) continue;          // Unsichtbares 44-px-Trefferziel.
      const cs = getComputedStyle(el);
      if (['auto', 'scroll'].includes(cs.overflowX)) continue;
      if (cs.textOverflow === 'ellipsis') continue;     // Absichtlich gekürzt.

      const kasten = el.getBoundingClientRect();
      if (kasten.right > innerWidth + 1) {
        befunde.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : ''} – rechts ${Math.round(kasten.right)}>${breite}`);
      } else if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        befunde.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : ''} – inhalt ${el.scrollWidth}>${el.clientWidth}`);
      }
    }
    return { befunde: befunde.slice(0, 20), gerendert };
  }, { ansicht, breite });
}

/** Belastet Tabellen mit langen Komposita und prüft Karten und Zellen. */
async function stresseTabellen(page, ansicht, breite) {
  await page.evaluate(({ ansicht, lang }) => {
    for (const tabelle of document.querySelectorAll(`#v-${ansicht} table.tbl`)) {
      if (!tabelle.getClientRects().length) continue;
      [...tabelle.querySelectorAll('tbody td')].forEach((td, i) => {
        if (i === 0) td.textContent = `${lang} ${td.textContent}`;
        else if (i === 1) td.textContent = lang;
      });
    }
  }, { ansicht, lang: LANGS });
  await page.waitForTimeout(150);
  return page.evaluate(({ ansicht, breite, langesLabel }) => {
    const befunde = [];
    let tabellen = 0, zellen = 0;
    for (const tabelle of document.querySelectorAll(`#v-${ansicht} table.tbl`)) {
      if (!tabelle.getClientRects().length) continue;
      tabellen++;
      const umlauf = tabelle.closest('.tw');
      if (umlauf && umlauf.scrollWidth > umlauf.clientWidth + 1) {
        befunde.push(`tabelle ${tabellen}: Behälter ${umlauf.scrollWidth}>${umlauf.clientWidth}`);
      }
      if (tabelle.scrollWidth > tabelle.clientWidth + 1) {
        befunde.push(`tabelle ${tabellen}: ${tabelle.scrollWidth}>${tabelle.clientWidth}`);
      }
      for (const zeile of tabelle.querySelectorAll('tbody tr')) {
        const zweite = zeile.children[1];
        if (zweite) zweite.setAttribute('data-label', langesLabel);
        if (zeile.scrollWidth > zeile.clientWidth + 1) {
          befunde.push(`tabelle ${tabellen}: Zeile ${zeile.scrollWidth}>${zeile.clientWidth}`);
        }
      }
      for (const zelle of tabelle.querySelectorAll('tbody td')) {
        zellen++;
        if (zelle.getClientRects().length && zelle.scrollWidth > zelle.clientWidth + 1) {
          befunde.push(`tabelle ${tabellen}: Zelle ${Math.round(zelle.getBoundingClientRect().width)} px, Inhalt ${zelle.scrollWidth}>${zelle.clientWidth}`);
        }
      }
    }
    return { befunde: befunde.slice(0, 20), tabellen, zellen, breite };
  }, { ansicht, breite, langesLabel: LANGES_LABEL });
}

/** Wählt im Lab einen Kandidaten, der eine Kapitalkurve zeigt. */
async function waehleKurvenKandidat(page) {
  const kurve = page.locator('#labDetail .wfoKurveFlaeche svg');
  if (await kurve.count()) return true;
  const eintraege = page.locator('#labList .li');
  for (let i = 0, n = await eintraege.count(); i < n; i++) {
    await eintraege.nth(i).click();
    await page.waitForTimeout(120);
    if (await kurve.count()) return true;
  }
  return false;
}

/** Prüft, ob der Tooltip im Chart-Kasten und im Viewport bleibt. */
function lageBefunde(stand) {
  const befunde = [];
  if (stand.links < stand.kastenLinks - 1 || stand.rechts > stand.kastenRechts + 1) {
    befunde.push(`Tooltip läuft aus dem Kasten (${Math.round(stand.links)}–${Math.round(stand.rechts)} statt ${Math.round(stand.kastenLinks)}–${Math.round(stand.kastenRechts)})`);
  }
  if (stand.oben < stand.kastenOben - 1 || stand.unten > stand.kastenUnten + 1) {
    befunde.push(`Tooltip läuft senkrecht aus dem Kasten (${Math.round(stand.oben)}–${Math.round(stand.unten)} statt ${Math.round(stand.kastenOben)}–${Math.round(stand.kastenUnten)})`);
  }
  if (stand.links < -1 || stand.rechts > stand.viewportBreite + 1 || stand.oben < -1 || stand.unten > stand.viewportHoehe + 1) {
    befunde.push(`Tooltip läuft aus dem Viewport (${Math.round(stand.links)}–${Math.round(stand.rechts)} × ${Math.round(stand.oben)}–${Math.round(stand.unten)} bei ${stand.viewportBreite}×${stand.viewportHoehe})`);
  }
  return befunde;
}

/** Überfährt die Kapitalkurve und prüft den Tooltip samt Lage im Kasten. */
async function pruefeKurvenTooltip(page, ansicht, breite) {
  const svg = page.locator(`#v-${ansicht} .wfoKurveFlaeche svg`);
  if (!(await svg.count())) return null;
  await svg.evaluate(el => el.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(120);
  const r = await svg.boundingBox();
  if (!r || !r.width) return ['Kurve hat keine sichtbare Fläche'];
  const befunde = [];
  for (const anteil of [0.5, 0.98]) {
    await page.mouse.move(r.x + r.width * anteil, r.y + r.height / 2);
    await page.waitForTimeout(120);
    const stand = await page.evaluate((ansicht) => {
      const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
      const tipp = box.querySelector('.wfoKurveTipp');
      const cs = getComputedStyle(tipp);
      const tr = tipp.getBoundingClientRect();
      const br = box.getBoundingClientRect();
      return {
        sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
        text: tipp.innerText.replace(/\s+/g, ' ').trim(),
        live: box.querySelector('.wfoKurveLive').textContent.trim(),
        links: tr.left, rechts: tr.right, oben: tr.top, unten: tr.bottom,
        kastenLinks: br.left, kastenRechts: br.right, kastenOben: br.top, kastenUnten: br.bottom,
        viewportBreite: innerWidth, viewportHoehe: innerHeight,
      };
    }, ansicht);
    const bei = Math.round(anteil * 100);
    if (!stand.sichtbar) befunde.push(`Tooltip erscheint bei ${bei} % der Breite nicht`);
    if (!/USD\s/.test(stand.text)) befunde.push(`Tooltip ohne Kapitalstand: «${stand.text}»`);
    if (!/\d{2}\.\d{2}\.\d{4}/.test(stand.text)) befunde.push(`Tooltip ohne Datum: «${stand.text}»`);
    if (!/USD\s/.test(stand.live)) befunde.push(`Live-Region bleibt bei ${bei} % der Breite leer`);
    befunde.push(...lageBefunde(stand));
  }

  // Zeiger vom Chart weg: Anzeige muss verschwinden.
  await page.mouse.move(1, 1);
  await page.waitForTimeout(120);
  const versteckt = await page.evaluate((ansicht) => {
    const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
    const tipp = box.querySelector('.wfoKurveTipp');
    const cs = getComputedStyle(tipp);
    return {
      sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
      aktiv: box.classList.contains('an'),
      inhalt: tipp.innerText.trim(),
      live: box.querySelector('.wfoKurveLive').textContent.trim(),
    };
  }, ansicht);
  if (versteckt.sichtbar) befunde.push('Tooltip bleibt nach dem Verlassen der Kurve sichtbar');
  if (versteckt.aktiv) befunde.push('Führungslinie bleibt nach dem Verlassen der Kurve eingeblendet');
  if (versteckt.inhalt) befunde.push('Tooltip-Inhalt bleibt nach dem Verlassen der Kurve stehen');
  if (versteckt.live) befunde.push('Live-Region bleibt nach dem Verlassen der Kurve gefüllt');

  // Erneut überfahren: Anzeige und Ansage müssen wiederkommen.
  await page.mouse.move(r.x + r.width / 2, r.y + r.height / 2);
  await page.waitForTimeout(120);
  const zurueck = await page.evaluate((ansicht) => {
    const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
    const tipp = box.querySelector('.wfoKurveTipp');
    const cs = getComputedStyle(tipp);
    return {
      sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
      live: box.querySelector('.wfoKurveLive').textContent.trim(),
    };
  }, ansicht);
  if (!zurueck.sichtbar) befunde.push('Tooltip erscheint nach erneutem Überfahren nicht');
  if (!/USD\s/.test(zurueck.live)) befunde.push('Live-Region bleibt nach erneutem Überfahren leer');
  return befunde;
}

/** Jede Kapitalkurve braucht genau eine Live-Region, keine mehr und keine weniger. */
async function pruefeLiveRegionen(page) {
  return page.evaluate(() => {
    const flaechen = [...document.querySelectorAll('.wfoKurveFlaeche')];
    if (!flaechen.length) return ['Keine Kapitalkurve für die Live-Region-Prüfung gefunden'];
    const befunde = [];
    flaechen.forEach((flaeche, i) => {
      const anzahl = flaeche.querySelectorAll('.wfoKurveLive').length;
      if (anzahl !== 1) befunde.push(`Kapitalkurve ${i + 1} hat ${anzahl} Live-Regionen statt einer`);
    });
    const gesamt = document.querySelectorAll('.wfoKurveLive').length;
    if (gesamt !== flaechen.length) befunde.push(`${gesamt} Live-Regionen für ${flaechen.length} Kapitalkurven`);
    return befunde;
  });
}

/** Der Hinweis unter der Kurve zeigt ← und → als echte kbd-Tasten. */
async function pruefeKurvenHinweis(page, ansicht) {
  return page.evaluate((ansicht) => {
    const svg = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche svg`);
    const box = svg && svg.closest('.wfoKurve');
    const hinweis = box && box.querySelector('.wfoKurveHinweis');
    if (!hinweis) return ['Kurven-Hinweis fehlt'];
    const tasten = [...hinweis.querySelectorAll('kbd')];
    const texte = tasten.map(k => k.textContent.trim());
    const ohneTasten = hinweis.cloneNode(true);
    ohneTasten.querySelectorAll('kbd').forEach(k => k.remove());
    const rest = ohneTasten.textContent.replace(/\s+/g, ' ').trim();
    const befunde = [];
    if (!texte.includes('←') || !texte.includes('→')) befunde.push(`Kurven-Hinweis ohne kbd-Tasten für ← und → («${hinweis.textContent.replace(/\s+/g, ' ').trim()}», kbd: ${texte.join(' ') || 'keine'})`);
    if (/[←→]/.test(rest)) befunde.push(`Pfeile stehen im Hinweis ausserhalb von kbd («${rest}»)`);
    tasten.forEach((k, i) => {
      const r = k.getBoundingClientRect();
      if (!r.width || !r.height || getComputedStyle(k).visibility === 'hidden') befunde.push(`kbd-Taste «${texte[i]}» ist nicht sichtbar`);
    });
    return befunde;
  }, ansicht);
}

/** Die Live-Region muss für Screenreader da, aber visuell verborgen sein. */
async function pruefeLiveVerborgen(page, ansicht) {
  const stand = await page.evaluate((ansicht) => {
    const live = document.querySelector(`#v-${ansicht} .wfoKurveLive`);
    const cs = getComputedStyle(live);
    const r = live.getBoundingClientRect();
    return {
      text: live.textContent.trim(),
      breite: r.width,
      hoehe: r.height,
      display: cs.display,
      visibility: cs.visibility,
      overflow: cs.overflow,
    };
  }, ansicht);
  const befunde = [];
  if (!/USD\s/.test(stand.text)) befunde.push('Live-Region ist beim Fokus nicht gefüllt');
  if (stand.display === 'none' || stand.visibility === 'hidden') befunde.push('Live-Region ist auch für Screenreader ausgeblendet');
  if (stand.breite > 1.5 || stand.hoehe > 1.5) befunde.push(`Live-Region ist sichtbar gross (${Math.round(stand.breite)}×${Math.round(stand.hoehe)} px)`);
  if (stand.overflow !== 'hidden') befunde.push(`Live-Region schneidet ihren Text nicht ab (overflow: ${stand.overflow})`);
  return befunde;
}

/** Tabbt von oben durch die Seite, bis die Kapitalkurve den Fokus hat. */
async function tabbeZurKurve(page, ansicht) {
  await page.evaluate(() => {
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(80);
  const grenze = 160;
  let schritte = 0;
  let letzter = '';
  let wiederholt = 0;
  for (let i = 0; i < grenze; i++) {
    await page.keyboard.press('Tab');
    schritte++;
    const info = await page.evaluate((ansicht) => {
      const a = document.activeElement;
      const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
      const svg = box && box.querySelector('svg');
      if (a && a !== svg) window.__text250VorKurve = a;
      const klasse = a && a.className ? String(a.className.baseVal ?? a.className).split(' ')[0] : '';
      return {
        kurve: !!svg && a === svg,
        name: a ? `${a.tagName}${klasse ? '.' + klasse : ''}«${(a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 30)}»` : 'nichts',
      };
    }, ansicht);
    if (info.kurve) return { erreicht: true, schritte, letzter: info.name };
    if (info.name === letzter) wiederholt++; else wiederholt = 0;
    letzter = info.name;
    if (wiederholt >= 3) break;
  }
  return { erreicht: false, schritte, letzter };
}

/** Tabbt zur Kurve und prüft Pfeiltasten, Home/Ende und die Live-Region. */
async function pruefeKurvenTastatur(page, ansicht) {
  const svg = page.locator(`#v-${ansicht} .wfoKurveFlaeche svg`);
  if (!(await svg.count())) return null;
  const befunde = [];
  befunde.push(...await pruefeLiveRegionen(page));
  await page.mouse.move(0, 0);
  await page.waitForTimeout(80);
  const lese = () => page.evaluate((ansicht) => {
    const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
    const svg = box.querySelector('svg');
    const tipp = box.querySelector('.wfoKurveTipp');
    const live = box.querySelector('.wfoKurveLive');
    const zeiger = box.querySelector('.wfoKurveZeiger');
    const cs = getComputedStyle(tipp);
    const tr = tipp.getBoundingClientRect();
    const br = box.getBoundingClientRect();
    return {
      fokus: document.activeElement === svg,
      fokussierbar: svg.getAttribute('tabindex') === '0',
      sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
      text: tipp.innerText.replace(/\s+/g, ' ').trim(),
      live: live.textContent.trim(),
      liveRolle: live.getAttribute('role'),
      liveModus: live.getAttribute('aria-live'),
      zeiger: zeiger.getAttribute('x1'),
      scrollY: Math.round(scrollY),
      links: tr.left, rechts: tr.right, oben: tr.top, unten: tr.bottom,
      kastenLinks: br.left, kastenRechts: br.right, kastenOben: br.top, kastenUnten: br.bottom,
      viewportBreite: innerWidth, viewportHoehe: innerHeight,
    };
  }, ansicht);

  const tab = await tabbeZurKurve(page, ansicht);
  if (!tab.erreicht) {
    befunde.push(`Kapitalkurve nach ${tab.schritte} Tab-Schritten nicht erreicht (zuletzt: ${tab.letzter})`);
    await svg.evaluate(el => el.focus());
  }
  await page.waitForTimeout(100);
  let stand = await lese();
  if (!stand.fokussierbar) befunde.push('Kurve ist nicht per Tab erreichbar (tabindex fehlt)');
  if (!stand.fokus) befunde.push('Kurve lässt sich nicht per Tastatur fokussieren');
  if (!stand.sichtbar) befunde.push('Tooltip erscheint beim Fokus nicht');
  if (!/USD\s/.test(stand.text) || !/\d{2}\.\d{2}\.\d{4}/.test(stand.text)) befunde.push(`Tooltip beim Fokus unvollständig: «${stand.text}»`);
  if (!/USD\s/.test(stand.live)) befunde.push('Live-Region bleibt beim Fokus leer');
  if (!/\d{2}\.\d{2}\.\d{4}/.test(stand.live)) befunde.push('Live-Region ohne Datum beim Fokus');
  if (stand.liveRolle !== 'status' && stand.liveModus !== 'polite') befunde.push('Live-Region ist nicht als Status/Polite markiert');
  befunde.push(...await pruefeKurvenHinweis(page, ansicht));
  befunde.push(...await pruefeLiveVerborgen(page, ansicht));
  befunde.push(...lageBefunde(stand));
  const betrag = t => (String(t).match(/USD\s[0-9'’.,]+/) || [''])[0];
  const startZeiger = stand.zeiger;
  const startLive = stand.live;
  const scrollStart = stand.scrollY;

  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(80);
  stand = await lese();
  if (stand.zeiger === startZeiger) befunde.push('Pfeil rechts bewegt den Zeiger nicht');
  if (!/USD\s/.test(stand.live)) befunde.push('Live-Region bleibt nach Pfeil rechts leer');
  else if (betrag(stand.text) && !stand.live.includes(betrag(stand.text))) befunde.push(`Live-Region nennt nicht den Wert des Tooltips («${stand.live}» statt «${betrag(stand.text)}»)`);
  if (stand.scrollY !== scrollStart) befunde.push(`Pfeil rechts scrollt die Seite (${scrollStart} → ${stand.scrollY})`);
  befunde.push(...lageBefunde(stand));

  await page.keyboard.press('End');
  await page.waitForTimeout(80);
  const ende = await lese();
  if (ende.zeiger === startZeiger) befunde.push('Ende springt nicht an den letzten Punkt');
  if (ende.live === startLive) befunde.push('Live-Region bleibt bei Ende unverändert');
  else if (betrag(ende.text) && !ende.live.includes(betrag(ende.text))) befunde.push(`Live-Region nennt bei Ende nicht den Wert des Tooltips («${ende.live}» statt «${betrag(ende.text)}»)`);
  if (ende.scrollY !== scrollStart) befunde.push(`Ende scrollt die Seite (${scrollStart} → ${ende.scrollY})`);
  befunde.push(...lageBefunde(ende));

  await page.keyboard.press('Home');
  await page.waitForTimeout(80);
  const anfang = await lese();
  if (anfang.zeiger !== startZeiger) befunde.push(`Home kehrt nicht zum ersten Punkt zurück (${anfang.zeiger} statt ${startZeiger})`);
  if (anfang.live !== startLive) befunde.push(`Live-Region kehrt bei Home nicht zur Startansage zurück («${anfang.live}» statt «${startLive}»)`);
  befunde.push(...lageBefunde(anfang));

  if (tab.erreicht) {
    await page.keyboard.press('Shift+Tab');
    await page.waitForTimeout(80);
    const zurueck = await page.evaluate((ansicht) => {
      const name = e => {
        const klasse = e && e.className ? String(e.className.baseVal ?? e.className).split(' ')[0] : '';
        return e ? `${e.tagName}${klasse ? '.' + klasse : ''}«${(e.innerText || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 30)}»` : 'nichts';
      };
      const vor = window.__text250VorKurve;
      return { korrekt: !!vor && document.activeElement === vor, vor: name(vor), jetzt: name(document.activeElement) };
    }, ansicht);
    if (!zurueck.korrekt) befunde.push(`Shift+Tab springt nicht zum vorherigen Element (erwartet ${zurueck.vor}, fokussiert ${zurueck.jetzt})`);
  }

  await svg.evaluate(el => el.blur());
  await page.waitForTimeout(80);
  const nach = await lese();
  if (nach.sichtbar) befunde.push('Tooltip bleibt nach dem Verlassen sichtbar');
  if (nach.live) befunde.push('Live-Region bleibt nach dem Verlassen gefüllt');
  return befunde;
}

/** Die Zoom-Knöpfe dürfen ihre Symbole nicht abschneiden. */
async function pruefeZoom(page, ansicht) {
  return page.evaluate((ansicht) => {
    return [...document.querySelectorAll(`#v-${ansicht} .vault-zoom button`)].map(btn => {
      const cs = getComputedStyle(btn);
      const bereich = document.createRange();
      bereich.selectNodeContents(btn);
      const textBreite = bereich.getBoundingClientRect().width;
      const innen = btn.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return { text: btn.textContent, textBreite: Math.round(textBreite), innen: Math.round(innen), passt: textBreite <= innen + 0.5 };
    }).filter(x => !x.passt).map(x => `Zoom-Knopf «${x.text}» schneidet ab (${x.textBreite}>${x.innen})`);
  }, ansicht);
}

async function main() {
  const opt = argumente(process.argv.slice(2));
  const { validierungen } = await pruefeServer(opt.url);
  console.log(`250-%-Prüflauf: ${opt.ansichten.length} Ansichten × ${opt.breiten.length} Breiten · ${validierungen} Validierungen im Bericht`);
  if (opt.bilder) mkdirSync(opt.bilder, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const fehler = [];
  const hinweise = new Set();
  let tabellenGesamt = 0, zellenGesamt = 0, bilderGesamt = 0, tooltipGesamt = 0, tastaturGesamt = 0;

  try {
    for (const breite of opt.breiten) {
      const page = await browser.newPage({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
      page.on('pageerror', err => fehler.push(`${breite}px: ${err}`));
      await page.goto(`${opt.url}/`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(
        () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
        null, { timeout: 15000 },
      );
      await page.waitForTimeout(250);

      for (const ansicht of opt.ansichten) {
        await page.click(`.nav[data-v="${ansicht}"]`);
        await page.waitForTimeout(WARTEZEIT[ansicht]);
        let kurveGefunden = null;
        if (ansicht === 'lab') kurveGefunden = await waehleKurvenKandidat(page);
        await skaliere(page, 2.5);
        await page.waitForTimeout(150);

        const vorher = fehler.length;
        const ansichtBefund = await messeAnsicht(page, ansicht, breite);
        if (!ansichtBefund.gerendert) ansichtBefund.befunde.push('Ansicht wurde nicht gerendert');
        for (const text of ansichtBefund.befunde) fehler.push(`${breite}px/${ansicht}: ${text}`);

        if (ansicht === 'lab') {
          if (kurveGefunden) {
            const kurvenBefunde = await pruefeKurvenTooltip(page, ansicht, breite);
            if (kurvenBefunde) tooltipGesamt++;
            for (const text of kurvenBefunde || []) fehler.push(`${breite}px/${ansicht}: ${text}`);
            const tastaturBefunde = await pruefeKurvenTastatur(page, ansicht);
            if (tastaturBefunde) tastaturGesamt++;
            for (const text of tastaturBefunde || []) fehler.push(`${breite}px/${ansicht}: ${text}`);
          } else {
            hinweise.add('Keine Kapitalkurve im Lab gefunden – Tooltip und Tastatur nicht geprüft.');
          }
        }

        if (opt.tabellen) {
          const tabellenBefund = await stresseTabellen(page, ansicht, breite);
          tabellenGesamt += tabellenBefund.tabellen;
          zellenGesamt += tabellenBefund.zellen;
          for (const text of tabellenBefund.befunde) fehler.push(`${breite}px/${ansicht}: ${text}`);
        }
        for (const text of await pruefeZoom(page, ansicht)) fehler.push(`${breite}px/${ansicht}: ${text}`);

        if (opt.bilder && fehler.length > vorher) {
          const datei = join(opt.bilder, `${breite}px-${ansicht}.png`);
          await page.screenshot({ path: datei, fullPage: true });
          bilderGesamt++;
          console.log(`Screenshot: ${datei}`);
        }
      }
      await page.close();
    }
  } finally {
    await browser.close();
  }

  for (const text of hinweise) console.warn(`Hinweis: ${text}`);

  if (fehler.length) {
    console.error(`\nBefunde: ${fehler.length}`);
    for (const zeile of fehler.slice(0, 120)) console.error(`  ✗ ${zeile}`);
    if (fehler.length > 120) console.error(`  … und ${fehler.length - 120} weitere`);
    process.exit(1);
  }
  console.log(`OK: keine Überläufe${opt.tabellen ? ` · ${tabellenGesamt} Tabellen mit ${zellenGesamt} Zellen geprüft` : ''}${tooltipGesamt ? ` · Tooltip ${tooltipGesamt}× geprüft` : ''}${tastaturGesamt ? ` · Tastatur ${tastaturGesamt}× geprüft` : ''}${bilderGesamt ? ` · ${bilderGesamt} Screenshots` : ''}`);
}

main().catch(fehler => {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
});
