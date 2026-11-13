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
 */

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
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--breiten') opts.breiten = argv[++i].split(',').map(Number).filter(n => n >= 200);
    else if (arg === '--ansichten') opts.ansichten = argv[++i].split(',').map(s => s.trim()).filter(Boolean);
    else if (arg === '--ohne-tabellen') opts.tabellen = false;
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250.mjs [--url URL] [--breiten 360,320,280]\n' +
        '       [--ansichten overview,risk,lab,betrieb,spider,globe,kb] [--ohne-tabellen]');
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

  const browser = await chromium.launch({ headless: true });
  const fehler = [];
  let tabellenGesamt = 0, zellenGesamt = 0;

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
        await skaliere(page, 2.5);
        await page.waitForTimeout(150);

        const ansichtBefund = await messeAnsicht(page, ansicht, breite);
        if (!ansichtBefund.gerendert) ansichtBefund.befunde.push('Ansicht wurde nicht gerendert');
        for (const text of ansichtBefund.befunde) fehler.push(`${breite}px/${ansicht}: ${text}`);

        if (opt.tabellen) {
          const tabellenBefund = await stresseTabellen(page, ansicht, breite);
          tabellenGesamt += tabellenBefund.tabellen;
          zellenGesamt += tabellenBefund.zellen;
          for (const text of tabellenBefund.befunde) fehler.push(`${breite}px/${ansicht}: ${text}`);
        }
        for (const text of await pruefeZoom(page, ansicht)) fehler.push(`${breite}px/${ansicht}: ${text}`);
      }
      await page.close();
    }
  } finally {
    await browser.close();
  }

  if (fehler.length) {
    console.error(`\nBefunde: ${fehler.length}`);
    for (const zeile of fehler.slice(0, 120)) console.error(`  ✗ ${zeile}`);
    if (fehler.length > 120) console.error(`  … und ${fehler.length - 120} weitere`);
    process.exit(1);
  }
  console.log(`OK: keine Überläufe${opt.tabellen ? ` · ${tabellenGesamt} Tabellen mit ${zellenGesamt} Zellen geprüft` : ''}`);
}

main().catch(fehler => {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
});
