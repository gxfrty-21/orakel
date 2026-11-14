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
 *   --ansichten lab,kb     Standard alle zwölf Ansichten
 *   --ohne-tabellen        Nur Seitenüberläufe prüfen, Tabellen überspringen
 *   --bilder <verzeichnis> Schreibt bei Befunden je Ansicht und Breite einen Screenshot
 */

import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright';

const LANGS = 'Donaudampfschifffahrtsgesellschaftskapitänsmützenhalterungsverordnung';
const LANGES_LABEL = 'Bevölkerungsentwicklungsprognoseberechnungsgrundlagenverordnung';
const STANDARD_ANSICHTEN = ['overview', 'risk', 'lab', 'strat', 'research', 'globe', 'betrieb', 'ship', 'spider', 'kb', 'agents', 'konf'];
const WARTEZEIT = {
  overview: 300, risk: 350, lab: 400, strat: 500, research: 500, globe: 1300,
  betrieb: 750, ship: 1500, spider: 650, kb: 1500, agents: 500, konf: 500,
};

function argumente(argv) {
  const opts = {
    url: process.env.ORAKEL_URL || 'http://127.0.0.1:3000',
    breiten: [360, 320, 280],
    ansichten: [...STANDARD_ANSICHTEN],
    tabellen: true,
    bilder: null,
    negativtest: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--breiten') opts.breiten = argv[++i].split(',').map(Number).filter(n => n >= 200);
    else if (arg === '--ansichten') opts.ansichten = argv[++i].split(',').map(s => s.trim()).filter(Boolean);
    else if (arg === '--ohne-tabellen') opts.tabellen = false;
    else if (arg === '--bilder') opts.bilder = argv[++i];
    else if (arg === '--negativtest') opts.negativtest = true;
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250.mjs [--url URL] [--breiten 360,320,280]\n' +
        '       [--ansichten overview,risk,lab,strat,research,globe,betrieb,ship,spider,kb,agents,konf] [--ohne-tabellen]\n' +
        '       [--bilder <verzeichnis>] [--negativtest]');
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
      text: tipp.innerText.replace(/\s+/g, ' ').trim(),
      live: box.querySelector('.wfoKurveLive').textContent.trim(),
    };
  }, ansicht);
  const betrag = t => {
    const m = String(t).match(/USD\s([0-9'’]+)/);
    return m ? `USD ${m[1]}` : '';
  };
  const kapital = t => {
    const m = String(t).match(/Kapital USD\s([0-9'’]+)/);
    return m ? `USD ${m[1]}` : '';
  };
  const datum = t => (String(t).match(/\b\d{2}\.\d{2}\.\d{4}\b/) || [''])[0];
  const prozent = t => {
    const m = String(t).match(/([+-]?\d+(?:[.,]\d+)?)\s*%/);
    return m ? String(Number(m[1].replace(',', '.'))) : '';
  };
  const liveProzent = t => {
    if (/unverändert seit Start/.test(t)) return '0';
    const m = String(t).match(/(plus|minus)\s+([0-9'’]+(?:[.,][0-9]+)?)\s+Prozent/);
    if (!m) return '';
    const v = Number(m[2].replace(/['’]/g, '').replace(',', '.'));
    return String(m[1] === 'minus' ? -v : v);
  };
  if (!zurueck.sichtbar) befunde.push('Tooltip erscheint nach erneutem Überfahren nicht');
  if (!betrag(zurueck.text)) befunde.push('Tooltip nennt nach erneutem Überfahren keinen Kapitalstand');
  if (!/Kapital USD\s/.test(zurueck.live)) befunde.push('Live-Region bleibt nach erneutem Überfahren ohne Kapitalstand');
  else if (betrag(zurueck.text) && kapital(zurueck.live) !== betrag(zurueck.text)) befunde.push(`Live-Region nennt nach erneutem Überfahren nicht den Wert des Tooltips («${zurueck.live}» statt «${betrag(zurueck.text)}»)`);
  if (!datum(zurueck.text)) befunde.push('Tooltip nennt nach erneutem Überfahren kein Datum');
  else if (datum(zurueck.live) !== datum(zurueck.text)) befunde.push(`Live-Region nennt nach erneutem Überfahren nicht das Datum des Tooltips (${datum(zurueck.live) || '—'} statt ${datum(zurueck.text)})`);
  if (!prozent(zurueck.text) || !liveProzent(zurueck.live)) befunde.push(`Prozentwert nach erneutem Überfahren nicht lesbar (Tooltip «${zurueck.text}», Live «${zurueck.live}»)`);
  else if (liveProzent(zurueck.live) !== prozent(zurueck.text)) befunde.push(`Live-Region nennt nach erneutem Überfahren nicht den Prozentwert des Tooltips (${liveProzent(zurueck.live)} statt ${prozent(zurueck.text)})`);
  const hoch = t => (String(t).match(/Hoch bis hier USD\s([0-9'’]+)/) || [''])[1] || '';
  const liveHoch = t => (String(t).match(/bisherigen Hoch von USD\s([0-9'’]+)/) || [''])[1] || '';
  const abstand = t => {
    if (/\bam Hoch\b/.test(t)) return '0';
    const m = String(t).match(/([0-9'’]+(?:[.,][0-9]+)?)\s*%\s*darunter/);
    return m ? String(Number(m[1].replace(/['’]/g, '').replace(',', '.'))) : '';
  };
  const liveAbstand = t => {
    if (/\bam bisherigen Hoch\b/.test(t)) return '0';
    const m = String(t).match(/([0-9'’]+(?:[.,][0-9]+)?)\s+Prozent unter dem bisherigen Hoch/);
    return m ? String(Number(m[1].replace(/['’]/g, '').replace(',', '.'))) : '';
  };
  if (hoch(zurueck.text) && liveHoch(zurueck.live) && hoch(zurueck.text) !== liveHoch(zurueck.live)) befunde.push(`Live-Region nennt nach erneutem Überfahren nicht den Hochstand des Tooltips (USD ${liveHoch(zurueck.live)} statt USD ${hoch(zurueck.text)})`);
  if (abstand(zurueck.text) === '' || liveAbstand(zurueck.live) === '') befunde.push(`Abstand zum Hoch nach erneutem Überfahren nicht lesbar (Tooltip «${zurueck.text}», Live «${zurueck.live}»)`);
  else if (liveAbstand(zurueck.live) !== abstand(zurueck.text)) befunde.push(`Live-Region nennt nach erneutem Überfahren nicht den Abstand zum Hoch des Tooltips (${liveAbstand(zurueck.live)} % statt ${abstand(zurueck.text)} %)`);

  // Zusätzlich einen Punkt unter dem Hoch prüfen: der Abstand muss positiv sein.
  let unterHoch = null;
  for (const anteil of [0.25, 0.75, 0.1, 0.9, 0.02, 0.98]) {
    await page.mouse.move(r.x + r.width * anteil, r.y + r.height / 2);
    await page.waitForTimeout(120);
    const s = await page.evaluate((ansicht) => {
      const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
      const tipp = box.querySelector('.wfoKurveTipp');
      const cs = getComputedStyle(tipp);
      return {
        sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
        text: tipp.innerText.replace(/\s+/g, ' ').trim(),
        live: box.querySelector('.wfoKurveLive').textContent.trim(),
      };
    }, ansicht);
    if (abstand(s.text) !== '' && Number(abstand(s.text)) > 0) { unterHoch = s; break; }
  }
  if (!unterHoch) {
    befunde.push('Kein Punkt unter dem Hoch mit positivem Abstand gefunden');
  } else {
    if (!unterHoch.sichtbar) befunde.push('Tooltip erscheint am Punkt unter dem Hoch nicht');
    const liveWert = liveAbstand(unterHoch.live);
    if (liveWert === '') befunde.push(`Abstand am Punkt unter dem Hoch nicht lesbar (Live «${unterHoch.live}»)`);
    else if (liveWert !== abstand(unterHoch.text)) befunde.push(`Live-Region nennt am Punkt unter dem Hoch nicht den Abstand des Tooltips (${liveWert} % statt ${abstand(unterHoch.text)} %)`);
    else if (!(Number(liveWert) > 0)) befunde.push('Abstand am Punkt unter dem Hoch ist nicht positiv');
    const kapitalText = betrag(unterHoch.text), hochText = hoch(unterHoch.text);
    if (!kapitalText || !hochText) {
      befunde.push('Kapitalstand oder Hochstand am Punkt unter dem Hoch nicht lesbar');
    } else {
      const zahl = s => Number(String(s).replace(/['’]/g, ''));
      const kapitalWert = zahl(kapitalText.replace(/^USD\s/, ''));
      const hochWert = zahl(hochText);
      const gerechnet = Math.round(Math.abs((kapitalWert - hochWert) / hochWert * 100) * 10) / 10;
      if (gerechnet !== Number(abstand(unterHoch.text))) befunde.push(`Abstand am Punkt unter dem Hoch passt nicht zu Kapitalstand und Hochstand (${gerechnet} % statt ${abstand(unterHoch.text)} %)`);
    }
  }

  // Am gezeichneten Hochpunkt muss der Abstand rechnerisch 0 % sein.
  const hochPunkt = await page.evaluate((ansicht) => {
    const svg = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche svg`);
    const points = (svg?.querySelector('polyline')?.getAttribute('points') || '').trim();
    if (!points) return null;
    const punkte = points.split(/\s+/).map(p => p.split(',').map(Number)).filter(p => p.length === 2 && p.every(Number.isFinite));
    if (!punkte.length) return null;
    const hoch = punkte.reduce((a, b) => b[1] < a[1] ? b : a);
    return { x: hoch[0], breite: svg.viewBox.baseVal.width };
  }, ansicht);
  if (!hochPunkt) {
    befunde.push('Hochpunkt der Kurve nicht gefunden');
  } else {
    await page.mouse.move(r.x + r.width * (hochPunkt.x / hochPunkt.breite), r.y + r.height / 2);
    await page.waitForTimeout(120);
    const amHoch = await page.evaluate((ansicht) => {
      const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
      const tipp = box.querySelector('.wfoKurveTipp');
      const cs = getComputedStyle(tipp);
      return {
        sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
        text: tipp.innerText.replace(/\s+/g, ' ').trim(),
        live: box.querySelector('.wfoKurveLive').textContent.trim(),
      };
    }, ansicht);
    if (!amHoch.sichtbar) befunde.push('Tooltip erscheint am Hochpunkt nicht');
    else if (!/\bam Hoch\b/.test(amHoch.text)) befunde.push(`Tooltip am Hochpunkt nennt keinen Hochstand («${amHoch.text}»)`);
    const kapitalText = betrag(amHoch.text), hochText = hoch(amHoch.text);
    if (!kapitalText || !hochText) {
      befunde.push('Kapitalstand oder Hochstand am Hochpunkt nicht lesbar');
    } else {
      const zahl = s => Number(String(s).replace(/['’]/g, ''));
      const kapitalWert = zahl(kapitalText.replace(/^USD\s/, ''));
      const hochWert = zahl(hochText);
      const gerechnet = Math.round(Math.abs((kapitalWert - hochWert) / hochWert * 100) * 10) / 10;
      if (gerechnet !== 0) befunde.push(`Abstand am Hochpunkt ist nicht 0 (${gerechnet} % aus Kapitalstand und Hochstand)`);
      if (abstand(amHoch.text) !== '0') befunde.push(`Abstand am Hochpunkt wird nicht als 0 % angezeigt («${abstand(amHoch.text) || '—'} %»)`);
      if (liveAbstand(amHoch.live) !== '0') befunde.push(`Live-Region nennt am Hochpunkt nicht 0 % («${amHoch.live}»)`);
    }
  }
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
    const alle = [...document.querySelectorAll('.wfoKurveLive')];
    if (alle.length !== flaechen.length) befunde.push(`${alle.length} Live-Regionen für ${flaechen.length} Kapitalkurven`);
    alle.forEach((live, i) => {
      const rolle = live.getAttribute('role');
      const modus = live.getAttribute('aria-live');
      if (rolle !== 'status') befunde.push(`Live-Region ${i + 1} hat role="${rolle || '—'}" statt "status"`);
      if (modus !== 'polite') befunde.push(`Live-Region ${i + 1} hat aria-live="${modus || '—'}" statt "polite"`);
      let el = live, versteckt = null;
      while (el) {
        if ((el.getAttribute('aria-hidden') || '').toLowerCase() === 'true') { versteckt = el; break; }
        el = el.parentElement;
      }
      if (versteckt) befunde.push(`Live-Region ${i + 1} ist aria-hidden${versteckt === live ? '' : ` (über ${versteckt.tagName.toLowerCase()})`}`);
      const beschreibe = e => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${e.classList.length ? '.' + [...e.classList].slice(0, 2).join('.') : ''}`;
      let vorfahr = live.parentElement;
      while (vorfahr) {
        const cs = getComputedStyle(vorfahr);
        if (cs.display === 'none') { befunde.push(`Live-Region ${i + 1} liegt in einem display:none-Vorfahren (${beschreibe(vorfahr)})`); break; }
        if (cs.visibility === 'hidden') { befunde.push(`Live-Region ${i + 1} liegt in einem visibility:hidden-Vorfahren (${beschreibe(vorfahr)})`); break; }
        vorfahr = vorfahr.parentElement;
      }
    });
    return befunde;
  });
}

/** Die vier Eckwerte im aria-label müssen zur sichtbaren Fusszeile passen. */
async function pruefeAriaWerte(page, ansicht) {
  return page.evaluate((ansicht) => {
    const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
    const fuss = box && box.closest('.wfoKurve').querySelector('.wfoKurveFuss');
    const aria = (box && box.querySelector('svg') && box.querySelector('svg').getAttribute('aria-label')) || '';
    const text = fuss ? fuss.innerText.replace(/\s+/g, ' ').trim() : '';
    const wert = (t, name) => (t.match(new RegExp(`${name}\\s+USD\\s+([0-9'’]+)`)) || [])[1] || '';
    const befunde = [];
    for (const name of ['Start', 'Tief', 'Hoch', 'Ende']) {
      const a = wert(aria, name);
      const f = wert(text, name);
      if (!a) befunde.push(`aria-label nennt ${name} nicht mit USD-Betrag`);
      else if (!f) befunde.push(`Fusszeile nennt ${name} nicht mit USD-Betrag`);
      else if (a !== f) befunde.push(`aria-label nennt ${name} USD ${a}, Fusszeile USD ${f}`);
    }
    return befunde;
  }, ansicht);
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
    const csSvg = getComputedStyle(svg);
    const tr = tipp.getBoundingClientRect();
    const br = box.getBoundingClientRect();
    return {
      fokus: document.activeElement === svg,
      fokussierbar: svg.getAttribute('tabindex') === '0',
      ring: csSvg.outlineStyle !== 'none' && parseFloat(csSvg.outlineWidth) > 0 && csSvg.outlineColor !== 'rgba(0, 0, 0, 0)',
      outline: `${csSvg.outlineStyle} ${csSvg.outlineWidth} ${csSvg.outlineColor}`,
      aria: svg.getAttribute('aria-label') || '',
      sichtbar: cs.visibility === 'visible' && Number(cs.opacity) > 0.9,
      text: tipp.innerText.replace(/\s+/g, ' ').trim(),
      live: live.textContent.trim(),
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
  if (tab.erreicht && !stand.ring) befunde.push(`Fokusring der Kapitalkurve fehlt (outline ${stand.outline})`);
  if (!/Pfeiltasten/.test(stand.aria)) befunde.push('aria-label der Kurve nennt die Pfeiltasten nicht');
  if (!/Home[^.]{0,40}Ende/.test(stand.aria)) befunde.push('aria-label der Kurve nennt Home und Ende nicht');
  befunde.push(...await pruefeAriaWerte(page, ansicht));
  if (!stand.sichtbar) befunde.push('Tooltip erscheint beim Fokus nicht');
  if (!/USD\s/.test(stand.text) || !/\d{2}\.\d{2}\.\d{4}/.test(stand.text)) befunde.push(`Tooltip beim Fokus unvollständig: «${stand.text}»`);
  if (!/USD\s/.test(stand.live)) befunde.push('Live-Region bleibt beim Fokus leer');
  if (!/\d{2}\.\d{2}\.\d{4}/.test(stand.live)) befunde.push('Live-Region ohne Datum beim Fokus');
  const a11y = await page.locator(`#v-${ansicht} .wfoKurveFlaeche`).ariaSnapshot();
  const statusZeile = a11y.split('\n').find(z => /^\s*-\s+status:/.test(z)) || '';
  if (stand.live && !statusZeile) befunde.push('Live-Region fehlt im Accessibility-Baum (kein status-Knoten)');
  else if (stand.live && !statusZeile.includes(stand.live)) befunde.push(`Live-Region erscheint im Accessibility-Baum nicht mit ihrem Text («${statusZeile.trim()}» statt «${stand.live}»)`);
  befunde.push(...await pruefeKurvenHinweis(page, ansicht));
  befunde.push(...await pruefeLiveVerborgen(page, ansicht));
  befunde.push(...lageBefunde(stand));
  const betrag = t => (String(t).match(/USD\s[0-9'’.,]+/) || [''])[0];
  const betragZahl = t => (String(t).match(/USD\s([0-9'’]+)/) || [''])[1] || '';
  const alsZahl = s => Number(String(s).replace(/['’]/g, ''));
  const ariaWert = name => ((stand.aria.split(name + ' USD ')[1] || '').match(/^[0-9'’]+/) || [''])[0];
  const startZeiger = stand.zeiger;
  const startLive = stand.live;
  const scrollStart = stand.scrollY;

  await page.keyboard.press('ArrowRight');
  await page.waitForTimeout(80);
  stand = await lese();
  if (stand.zeiger === startZeiger) befunde.push('Pfeil rechts bewegt den Zeiger nicht');
  if (!/USD\s/.test(stand.live)) befunde.push('Live-Region bleibt nach Pfeil rechts leer');
  else if (betrag(stand.text) && !stand.live.includes(betrag(stand.text))) befunde.push(`Live-Region nennt nicht den Wert des Tooltips («${stand.live}» statt «${betrag(stand.text)}»)`);
  const a11yNach = await page.locator(`#v-${ansicht} .wfoKurveFlaeche`).ariaSnapshot();
  const statusNach = a11yNach.split('\n').find(z => /^\s*-\s+status:/.test(z)) || '';
  if (!statusNach) befunde.push('Status-Knoten fehlt nach Pfeil rechts im Accessibility-Baum');
  else if (!stand.live || !statusNach.includes(stand.live)) befunde.push(`Status-Knoten nennt nach Pfeil rechts nicht den Text der Live-Region («${statusNach.trim()}» statt «${stand.live}»)`);
  else if (stand.live !== startLive && statusNach === statusZeile) befunde.push('Status-Knoten bleibt trotz geändertem Live-Text nach Pfeil rechts unverändert');
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

  // Extremwerte direkt aus den API-Daten des gewählten Kandidaten bestimmen.
  let apiPunkte = [];
  const api = await page.evaluate(async () => {
    const antwort = await fetch('/api/report');
    const bericht = antwort.ok ? await antwort.json() : null;
    const li = document.querySelector('#labList .li.on');
    return {
      ok: Boolean(bericht),
      status: antwort.status,
      validierungen: bericht?.validierungen || [],
      name: li?.querySelector('b')?.textContent.trim() || '',
      parameter: li?.querySelector('small')?.textContent.trim() || '',
    };
  });
  const parameterText = p => Object.entries(p || {}).map(([a, b]) => `${a}=${b}`).join(', ');
  const kandidat = api.validierungen.find(c => `${c.symbol} · ${c.strategie}` === api.name && parameterText(c.parameter) === api.parameter);
  if (!api.ok) {
    befunde.push(`API-Daten für die Extremwerte nicht lesbar (HTTP ${api.status})`);
  } else if (!kandidat) {
    befunde.push(`Gewählter Kandidat «${api.name}» nicht in den API-Daten gefunden`);
  } else {
    const roh = (kandidat.kapitalkurve || []).filter(p => Array.isArray(p) && Number.isFinite(Number(p[1])));
    const schritt = Math.max(1, Math.ceil(roh.length / 240));
    const punkte = roh.filter((_, i) => i % schritt === 0);
    if (punkte.length && punkte[punkte.length - 1] !== roh[roh.length - 1]) punkte.push(roh[roh.length - 1]);
    apiPunkte = punkte;
    const gezeichnet = await page.evaluate((ansicht) => {
      const verlauf = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche polyline`);
      const points = verlauf?.getAttribute('points')?.trim() || '';
      return points ? points.split(/\s+/).length : 0;
    }, ansicht);
    if (gezeichnet !== punkte.length) befunde.push(`Kurve zeichnet ${gezeichnet} Punkte, die API-Ausdünnung ergibt ${punkte.length}`);
    const werte = punkte.map(p => Number(p[1]));
    if (werte.length < 2) {
      befunde.push('Extremwerte der API-Punkte liessen sich nicht ermitteln');
    } else {
      const tief = ariaWert('Tief'), hoch = ariaWert('Hoch');
      const tiefWert = Math.round(Math.min(...werte)), hochWert = Math.round(Math.max(...werte));
      if (tief && alsZahl(tief) !== tiefWert) befunde.push(`aria-label Tief USD ${tief} stimmt nicht mit dem Minimum der API-Punkte (USD ${tiefWert}) überein`);
      if (hoch && alsZahl(hoch) !== hochWert) befunde.push(`aria-label Hoch USD ${hoch} stimmt nicht mit dem Maximum der API-Punkte (USD ${hochWert}) überein`);
    }
  }

  await page.keyboard.press('Home');
  await page.waitForTimeout(80);
  const anfang = await lese();
  if (anfang.zeiger !== startZeiger) befunde.push(`Home kehrt nicht zum ersten Punkt zurück (${anfang.zeiger} statt ${startZeiger})`);
  if (anfang.live !== startLive) befunde.push(`Live-Region kehrt bei Home nicht zur Startansage zurück («${anfang.live}» statt «${startLive}»)`);
  befunde.push(...lageBefunde(anfang));

  const ariaStart = ariaWert('Start'), ariaEnde = ariaWert('Ende');
  const tippStart = betragZahl(anfang.text), tippEnde = betragZahl(ende.text);
  if (ariaStart && tippStart && ariaStart !== tippStart) befunde.push(`aria-label Start USD ${ariaStart} stimmt nicht mit Tooltip bei Home (USD ${tippStart}) überein`);
  if (ariaEnde && tippEnde && ariaEnde !== tippEnde) befunde.push(`aria-label Ende USD ${ariaEnde} stimmt nicht mit Tooltip bei Ende (USD ${tippEnde}) überein`);

  // Start, Viertel, Mitte, Dreiviertel und Ende gegen die API-Zeitstempel prüfen.
  if (apiPunkte.length >= 2) {
    const apiDatum = t => String(t || '').slice(0, 10).split('-').reverse().join('.');
    const apiWert = p => Math.round(Number(p[1]));
    const tooltipDatum = t => (String(t).match(/\b\d{2}\.\d{2}\.\d{4}\b/) || [''])[0];
    const tooltipWert = t => alsZahl(betragZahl(t));
    const tooltipProzent = t => {
      const m = String(t).match(/([+-]?\d+(?:[.,]\d+)?)\s*%/);
      return m ? Number(m[1].replace(',', '.')) : null;
    };
    const liveProzent = t => {
      if (/unverändert seit Start/.test(t)) return 0;
      const m = String(t).match(/(plus|minus)\s+([0-9'’]+(?:[.,]\d+)?)\s+Prozent/);
      return m ? Number(m[2].replace(/['’]/g, '').replace(',', '.')) * (m[1] === 'minus' ? -1 : 1) : null;
    };
    const tooltipAbstand = t => {
      if (/\bam Hoch\b/.test(t)) return 0;
      const m = String(t).match(/([0-9'’]+(?:[.,]\d+)?)\s*%\s*darunter/);
      return m ? Number(m[1].replace(/['’]/g, '').replace(',', '.')) : null;
    };
    const liveAbstand = t => {
      if (/\bam bisherigen Hoch\b/.test(t)) return 0;
      const m = String(t).match(/([0-9'’]+(?:[.,]\d+)?)\s+Prozent unter dem bisherigen Hoch/);
      return m ? Number(m[1].replace(/['’]/g, '').replace(',', '.')) : null;
    };
    const tooltipHoch = t => {
      const m = String(t).match(/Hoch bis hier USD\s*([0-9'’]+)/);
      return m ? Number(m[1].replace(/['’]/g, '')) : null;
    };
    const liveHoch = t => {
      const m = String(t).match(/Hoch von USD\s*([0-9'’]+)/);
      return m ? Number(m[1].replace(/['’]/g, '')) : null;
    };
    const startWert = Number(apiPunkte[0][1]);
    const erwarteterProzent = p => Math.abs(startWert) > 1e-9 ? Math.round((Number(p[1]) - startWert) / startWert * 100 * 10) / 10 || 0 : 0;
    let spitze = -Infinity;
    const hochWerte = apiPunkte.map(p => {
      spitze = Math.max(spitze, Number(p[1]));
      return spitze;
    });
    const erwarteterAbstand = (p, hoch) => Math.abs(Number(hoch)) > 1e-9 ? Math.round((Number(hoch) - Number(p[1])) / Number(hoch) * 100 * 10) / 10 || 0 : 0;
    const pruefeApi = (name, text, p, live, hoch) => {
      if (tooltipDatum(text) !== apiDatum(p[0])) befunde.push(`${name}: Tooltip-Datum ${tooltipDatum(text) || '—'} statt API ${apiDatum(p[0])}`);
      if (tooltipWert(text) !== apiWert(p)) befunde.push(`${name}: Tooltip-Kapital USD ${tooltipWert(text)} statt API USD ${apiWert(p)}`);
      const berechnet = erwarteterProzent(p);
      const tProzent = tooltipProzent(text);
      if (tProzent == null) befunde.push(`${name}: Tooltip-Prozent nicht lesbar`);
      else if (tProzent !== berechnet) befunde.push(`${name}: Tooltip-Prozent ${tProzent} statt berechnet ${berechnet} % ab Start`);
      const erwartetesHoch = Math.round(Number(hoch));
      const tHoch = tooltipHoch(text);
      if (tHoch == null) befunde.push(`${name}: Tooltip-Hochstand nicht lesbar`);
      else if (tHoch !== erwartetesHoch) befunde.push(`${name}: Tooltip-Hochstand USD ${tHoch} statt fortgeschriebenem API-Hoch USD ${erwartetesHoch}`);
      const abstand = erwarteterAbstand(p, hoch);
      const tAbstand = tooltipAbstand(text);
      if (tAbstand == null) befunde.push(`${name}: Tooltip-Abstand nicht lesbar`);
      else if (tAbstand !== abstand) befunde.push(`${name}: Tooltip-Abstand ${tAbstand} statt berechnet ${abstand} % zum Hoch`);
      if (live) {
        if (tooltipDatum(live) !== apiDatum(p[0])) befunde.push(`${name}: Live-Datum ${tooltipDatum(live) || '—'} statt API ${apiDatum(p[0])}`);
        if (tooltipWert(live) !== apiWert(p)) befunde.push(`${name}: Live-Kapital USD ${tooltipWert(live)} statt API USD ${apiWert(p)}`);
        const lProzent = liveProzent(live);
        if (lProzent == null) befunde.push(`${name}: Live-Prozent nicht lesbar`);
        else if (lProzent !== berechnet) befunde.push(`${name}: Live-Prozent ${lProzent} statt berechnet ${berechnet} % ab Start`);
        const lHoch = liveHoch(live);
        if (lHoch == null) befunde.push(`${name}: Live-Hochstand nicht lesbar`);
        else if (lHoch !== erwartetesHoch) befunde.push(`${name}: Live-Hochstand USD ${lHoch} statt fortgeschriebenem API-Hoch USD ${erwartetesHoch}`);
        const lAbstand = liveAbstand(live);
        if (lAbstand == null) befunde.push(`${name}: Live-Abstand nicht lesbar`);
        else if (lAbstand !== abstand) befunde.push(`${name}: Live-Abstand ${lAbstand} statt berechnet ${abstand} % zum Hoch`);
      }
    };
    pruefeApi('Startpunkt', anfang.text, apiPunkte[0], anfang.live, hochWerte[0]);
    pruefeApi('Endpunkt', ende.text, apiPunkte[apiPunkte.length - 1], ende.live, hochWerte[hochWerte.length - 1]);
    const n = apiPunkte.length - 1;
    const proben = [
      ['Viertelpunkt', Math.floor(n * 0.25)],
      ['Mittelpunkt', Math.floor(n / 2)],
      ['Dreiviertelpunkt', Math.floor(n * 0.75)],
    ];
    const kasten = await svg.boundingBox();
    if (!kasten) {
      befunde.push('Kurve für die Stichprobenpunkte nicht sichtbar');
    } else {
      for (const [name, index] of proben) {
        await page.mouse.move(kasten.x + kasten.width * (index / n), kasten.y + kasten.height / 2);
        await page.waitForTimeout(120);
        const stand = await lese();
        pruefeApi(name, stand.text, apiPunkte[index], stand.live, hochWerte[index]);
      }
      // Dieselben fünf Stichproben per Tastatur ansteuern: Home, dann mit
      // Pfeil rechts bis Viertel, Mitte und Dreiviertel, zuletzt Ende.
      await svg.evaluate(el => el.focus());
      await page.keyboard.press('Home');
      await page.waitForTimeout(80);
      let tastaturIndex = 0;
      let tastaturStand = await lese();
      pruefeApi('Tastatur-Startpunkt', tastaturStand.text, apiPunkte[0], tastaturStand.live, hochWerte[0]);
      for (const [name, index] of [...proben, ['Endpunkt', n]]) {
        while (tastaturIndex < index) {
          await page.keyboard.press('ArrowRight');
          tastaturIndex++;
        }
        await page.waitForTimeout(60);
        tastaturStand = await lese();
        pruefeApi(`Tastatur-${name}`, tastaturStand.text, apiPunkte[index], tastaturStand.live, hochWerte[index]);
      }
    }
  }

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

  await svg.evaluate(el => el.focus());
  await page.waitForTimeout(60);
  const leseWeiter = () => page.evaluate((ansicht) => {
    const a = document.activeElement;
    const svg = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche svg`);
    const klasse = a && a.className ? String(a.className.baseVal ?? a.className).split(' ')[0] : '';
    const cs = a ? getComputedStyle(a) : null;
    const r = a ? a.getBoundingClientRect() : null;
    return {
      kurve: a === svg,
      body: !a || a === document.body,
      sichtbar: !!a && a !== document.body && r.width > 0 && r.height > 0 && cs.visibility !== 'hidden',
      ring: !!cs && cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 && cs.outlineColor !== 'rgba(0, 0, 0, 0)',
      outline: cs ? `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}` : '—',
      name: a ? `${a.tagName}${klasse ? '.' + klasse : ''}«${(a.innerText || a.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 30)}»` : 'nichts',
    };
  }, ansicht);
  await page.keyboard.press('Tab');
  await page.waitForTimeout(80);
  let weiter = await leseWeiter();
  if (weiter.kurve) befunde.push('Tab bleibt auf der Kapitalkurve');
  else if (weiter.body) {
    // Am Ende der Tab-Reihenfolge springt der Browser auf body; der nächste Tab muss weiterführen.
    await page.keyboard.press('Tab');
    await page.waitForTimeout(80);
    weiter = await leseWeiter();
    if (weiter.kurve || weiter.body) befunde.push('Tab führt von der Kapitalkurve zu keinem nächsten Element');
  }
  if (!weiter.kurve && !weiter.body) {
    if (!weiter.sichtbar) befunde.push(`Fokussiertes Element nach Tab ist nicht sichtbar (${weiter.name})`);
    else if (!weiter.ring) befunde.push(`Fokusring fehlt nach Tab-Wechsel (${weiter.name}: outline ${weiter.outline})`);
  }

  await svg.evaluate(el => el.blur());
  await page.waitForTimeout(80);
  const nach = await lese();
  if (nach.sichtbar) befunde.push('Tooltip bleibt nach dem Verlassen sichtbar');
  if (nach.live) befunde.push('Live-Region bleibt nach dem Verlassen gefüllt');
  if (nach.ring) befunde.push(`Fokusring der Kapitalkurve bleibt nach dem Verlassen sichtbar (outline ${nach.outline})`);
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

/**
 * Prüft, ob alle elf sichtbaren Abteilungscluster des Raumschiffs gerendert
 * sind. Die Cluster kommen aus der Company-API und werden asynchron geladen;
 * ein fehlender oder doppelter Buchstabe muss auffallen.
 */
async function pruefeSchiffCluster(page) {
  await page.waitForFunction(() => {
    const tag = document.querySelector('#companyTag')?.textContent || '';
    return document.querySelectorAll('#shipWorld .ship-dept').length > 0
      || /API-FEHLER|keine Daten/.test(tag);
  }, null, { timeout: 5000 }).catch(() => {});

  const stand = await page.evaluate(() => {
    const cluster = [...document.querySelectorAll('#shipWorld .ship-dept')];
    const gruppen = cluster.map(el => ({
      code: (el.querySelector('.ship-dept-code')?.textContent || '').trim(),
      agenten: el.querySelectorAll('.agent-room').length,
    })).filter(g => g.code);
    return {
      anzahl: cluster.length,
      sichtbar: cluster.filter(el => el.getClientRects().length > 0).length,
      codes: gruppen.map(g => g.code),
      agenten: Object.fromEntries(gruppen.map(g => [g.code, g.agenten])),
    };
  });

  const erwartet = { A:10, B:10, C:10, D:10, E:10, F:10, G:10, H:10, I:10, J:10, S:3 };
  const codes = Object.keys(erwartet);
  const befunde = [];
  if (stand.anzahl !== codes.length) befunde.push(`Raumschiff: ${stand.anzahl} statt ${codes.length} Abteilungscluster`);
  if (stand.sichtbar !== codes.length) befunde.push(`Raumschiff: ${stand.sichtbar} statt ${codes.length} sichtbare Abteilungscluster`);
  const fehlend = codes.filter(code => !stand.codes.includes(code));
  if (fehlend.length) befunde.push(`Raumschiff: Abteilung ${fehlend.join(', ')} fehlt`);
  const unbekannt = stand.codes.filter(code => !codes.includes(code));
  if (unbekannt.length) befunde.push(`Raumschiff: unbekannte Abteilung ${unbekannt.join(', ')}`);
  for (const [code, soll] of Object.entries(erwartet)) {
    if (!(code in stand.agenten)) continue;
    if (stand.agenten[code] !== soll) {
      befunde.push(`Raumschiff: Abteilung ${code} hat ${stand.agenten[code]} statt ${soll} Agenten`);
    }
  }
  return befunde;
}

/**
 * Prüft die Kerndaten der inhaltlichen Ansichten gegen /api/report.
 * Layout wird separat gemessen; hier zählt, dass die richtigen Zahlen und
 * Datensätze aus dem Bericht tatsächlich in der Ansicht ankommen.
 */
async function pruefeInhalte(page, ansicht) {
  if (ansicht === 'ship') return pruefeSchiffCluster(page);
  if (!['strat', 'research', 'agents', 'konf'].includes(ansicht)) return null;

  const daten = await page.evaluate(async (ansicht) => {
    let antwort;
    try {
      antwort = await fetch('/api/report', { cache: 'no-store' });
    } catch (fehler) {
      return { fehler: `API-Bericht nicht erreichbar (${fehler.message})` };
    }
    if (!antwort.ok) return { fehler: `API-Bericht antwortet mit HTTP ${antwort.status}` };
    const d = await antwort.json();
    const v = d.validierungen || [];
    if (ansicht === 'strat') {
      return {
        bestanden: v.filter(x => x.urteil === 'bestanden')
          .map(x => ({
            symbol: x.symbol,
            strategie: x.strategie,
            out_of_sample: x.out_of_sample || {},
            holdout_kennzahlen: (x.holdout || {}).kennzahlen || {},
          })),
        auswahl: (d.auswahl || []).map(x => ({ symbol: x.symbol, schluessel: x.schluessel })),
      };
    }
    if (ansicht === 'research') {
      const dq = d.datenqualitaet || [], plan = d.plan || [], wissen = d.wissen || {};
      return {
        dqGesamt: dq.length,
        dqOk: dq.filter(q => q.ok).length,
        validierungen: v.length,
        bestanden: v.filter(x => x.urteil === 'bestanden').length,
        abgelehnt: v.filter(x => x.urteil === 'abgelehnt').length,
        planJa: plan.filter(p => p.genehmigt).length,
        planNein: plan.filter(p => !p.genehmigt).length,
        probelauf: plan.filter(p => String(p.status || '').startsWith('Probelauf')).length,
        wissenTypen: (wissen.typen || []).length,
        entscheide: (d.entscheide || []).length,
      };
    }
    if (ansicht === 'agents') {
      return { runs: (d.agenten || []).map(r => ({ abteilung: r.abteilung, agent: r.agent, aufgabe: r.aufgabe, ok: r.ok })) };
    }
    return { konferenz: d.konferenz || null };
  }, ansicht);

  if (daten.fehler) return [daten.fehler];
  if (ansicht === 'agents') return pruefeAgentenInhalte(page, daten.runs);

  return page.evaluate(({ ansicht, daten }) => {
    const befunde = [];
    const sauber = el => (el && el.textContent || '').replace(/\s+/g, ' ').trim();
    const txt = wert => String(wert ?? '').replace(/\s+/g, ' ').trim();
    const alle = sel => [...document.querySelectorAll(sel)];
    const eins = sel => document.querySelector(sel);

    if (ansicht === 'strat') {
      const liste = alle('#stratList .li');
      const detail = eins('#stratDetail');
      if (!daten.bestanden.length) {
        if (!/Keine bestandene Strategie/.test(sauber(eins('#stratList')))) befunde.push('Leerer Strategienzustand fehlt in der Liste');
        if (!/keine Strategie freigegeben/i.test(sauber(detail))) befunde.push('Leerer Strategienzustand fehlt im Detail');
        return befunde;
      }
      if (liste.length !== daten.bestanden.length) {
        befunde.push(`Strategienliste: ${liste.length} statt ${daten.bestanden.length} bestandene Einträge`);
      }
      for (const v of daten.bestanden) {
        const name = `${v.symbol} · ${v.strategie}`;
        if (!liste.some(li => sauber(li.querySelector('b')).replace(/^★\s*/, '') === name)) {
          befunde.push(`Bestandene Strategie «${name}» fehlt in der Liste`);
        }
      }
      const aktiv = eins('#stratList .li.on');
      const detailName = sauber(eins('#stratDetail h2'));
      if (!aktiv) befunde.push('Keine aktive Strategie in der Liste markiert');
      else if (detailName !== sauber(aktiv.querySelector('b')).replace(/^★\s*/, '')) {
        befunde.push(`Strategiedetail zeigt «${detailName}» statt der markierten Strategie`);
      }
      const kpiLabels = alle('#stratDetail .kpis .kpi .l').map(sauber);
      const erwarteteKpis = ['Profit Factor Walk-Forward', 'Trefferquote Walk-Forward', 'Max. Drawdown Walk-Forward', 'Trades Walk-Forward', 'Profit Factor Holdout'];
      if (kpiLabels.length !== erwarteteKpis.length || kpiLabels.some((x, i) => x !== erwarteteKpis[i])) {
        befunde.push(`Strategie-KPIs unvollständig (${kpiLabels.join(', ') || 'keine'})`);
      }
      const num = (wert, stellen = 2) => (wert == null || isNaN(wert)) ? '–'
        : Number(wert).toLocaleString('de-CH', { minimumFractionDigits: stellen, maximumFractionDigits: stellen });
      const pct = (wert, stellen = 1) => wert == null ? '–' : num(wert, stellen) + ' %';
      const gewaehlt = daten.bestanden.find(x => `${x.symbol} · ${x.strategie}` === detailName);
      if (!gewaehlt) {
        befunde.push(`Strategiedetail «${detailName}» nicht in den bestandenen Berichtsdaten gefunden`);
      } else {
        const o = gewaehlt.out_of_sample || {}, h = gewaehlt.holdout_kennzahlen || {};
        const erwarteteWerte = [num(o.profit_factor), pct(o.trefferquote_pct), pct(o.max_drawdown_pct), String(o.trades ?? '–'), num(h.profit_factor)];
        const werte = alle('#stratDetail .kpis .kpi .v').map(sauber);
        if (werte.length !== erwarteteWerte.length || werte.some((x, i) => x !== erwarteteWerte[i])) {
          befunde.push(`Strategie-KPI-Werte weichen ab (${werte.join(' · ') || 'keine'} statt ${erwarteteWerte.join(' · ')})`);
        }
      }
      const tabelle = eins('#stratDetail table.tbl');
      const zeilen = tabelle ? [...tabelle.querySelectorAll('tbody tr')].map(tr => sauber(tr.cells[0])) : [];
      const erwarteteZeilen = ['Nettogewinn gesamt', 'Rendite gesamt', 'Kaufen und Halten (ungesehen)', 'Gebühren gesamt', 'Zeit im Markt'];
      if (zeilen.length !== erwarteteZeilen.length || zeilen.some((x, i) => x !== erwarteteZeilen[i])) {
        befunde.push(`Strategie-Kerntabelle unvollständig (${zeilen.join(', ') || 'keine'})`);
      }
      if (daten.auswahl.length && !liste.some(li => sauber(li.querySelector('b')).startsWith('★'))) {
        befunde.push('Ausgewählte Strategie ist in der Liste nicht mit ★ markiert');
      }
      return befunde;
    }

    if (ansicht === 'research') {
      const stationen = alle('#flow .station');
      const erwarteteNamen = ['Daten', 'Research', 'Validierung', 'Risiko', 'Ausführung', 'Wissensbank'];
      if (stationen.length !== erwarteteNamen.length) befunde.push(`Research-Ablauf: ${stationen.length} statt ${erwarteteNamen.length} Stationen`);
      stationen.forEach((station, i) => {
        if (sauber(station.querySelector('.nr')) !== String(i + 1).padStart(2, '0')) befunde.push(`Station ${i + 1}: Nummer fehlt oder ist falsch`);
        if (sauber(station.querySelector('b')) !== erwarteteNamen[i]) befunde.push(`Station ${i + 1}: «${sauber(station.querySelector('b'))}» statt «${erwarteteNamen[i]}»`);
        if (station.querySelectorAll('small').length < 2) befunde.push(`Station ${i + 1}: Beschreibung fehlt`);
      });
      const texte = stationen.map(sauber);
      const erwartet = [
        `${daten.dqOk}/${daten.dqGesamt} Symbole`,
        `${daten.validierungen} Kandidaten`,
        `${daten.bestanden} bestanden · ${daten.abgelehnt} abgelehnt`,
        `${daten.planJa} genehmigt · ${daten.planNein} abgelehnt`,
        `${daten.probelauf} Probelauf`,
        `${daten.wissenTypen} Typen · ${daten.entscheide} Entscheide`,
      ];
      erwartet.forEach((text, i) => {
        if (!texte[i] || !texte[i].includes(text)) befunde.push(`Station ${i + 1}: erwartet «${text}», angezeigt «${texte[i] || 'nichts'}»`);
      });
      const prinzipien = alle('#principles .reasons');
      if (prinzipien.length !== 6) befunde.push(`Research-Grundsätze: ${prinzipien.length} statt 6`);
      if (!/Paper-Trading/.test(sauber(eins('#principles')))) befunde.push('Research-Grundsätze nennen Paper-Trading nicht');
      return befunde;
    }

    const k = daten.konferenz;
    const body = eins('#konfBody');
    if (!k) {
      if (!/Noch keine Konferenz abgehalten/.test(sauber(body))) befunde.push('Leerer Konferenzzustand fehlt');
      return befunde;
    }
    const panels = alle('#konfBody .panel');
    if (panels.length !== 4) befunde.push(`Konferenz: ${panels.length} statt 4 Panels`);
    const titel = panels.map(p => sauber(p.querySelector('.ph')?.firstChild || p.querySelector('.ph')));
    const erwarteteTitel = ['Protokoll', 'Berichte der Abteilungen', 'Diskussion', 'Massnahmen'];
    if (titel.join('|') !== erwarteteTitel.join('|')) befunde.push(`Konferenz-Panels: «${titel.join(' · ')}»`);
    const beschluss = sauber(eins('#konfBody .card h2'));
    if (beschluss !== txt(k.beschluss)) befunde.push(`Konferenz-Beschluss «${beschluss}» statt «${txt(k.beschluss)}»`);
    const modus = sauber(eins('#konfBody .card .sub'));
    if (!modus.includes(`Modus: ${txt(k.modus)}`)) befunde.push(`Konferenz-Modus fehlt («${modus}»)`);
    const panelMit = name => panels.find(p => sauber(p.querySelector('.ph')?.firstChild || p.querySelector('.ph')).startsWith(name));
    const berichtePanel = panelMit('Berichte der Abteilungen');
    const diskussionPanel = panelMit('Diskussion');
    const massnahmenPanel = panelMit('Massnahmen');
    const berichte = berichtePanel ? [...berichtePanel.querySelectorAll('.li')] : [];
    const diskussion = diskussionPanel ? [...diskussionPanel.querySelectorAll('.li')] : [];
    const berichteApi = k.berichte || [], diskussionApi = k.diskussion || [];
    if (berichte.length !== berichteApi.length) befunde.push(`Konferenz-Berichte: ${berichte.length} statt ${berichteApi.length}`);
    if (diskussion.length !== diskussionApi.length) befunde.push(`Konferenz-Diskussion: ${diskussion.length} statt ${diskussionApi.length}`);
    berichte.forEach((li, i) => {
      const b = berichteApi[i] || {};
      if (sauber(li.querySelector('b')) !== txt(b.name)) befunde.push(`Konferenz-Bericht ${i + 1}: Name «${sauber(li.querySelector('b'))}» statt «${txt(b.name)}»`);
      if (!sauber(li.querySelector('small')).includes(txt(b.text))) befunde.push(`Konferenz-Bericht ${i + 1}: Text fehlt oder weicht ab`);
      if (sauber(li.querySelector('.pill')) !== txt(b.abteilung)) befunde.push(`Konferenz-Bericht ${i + 1}: Abteilung «${sauber(li.querySelector('.pill'))}» statt «${txt(b.abteilung)}»`);
    });
    diskussion.forEach((li, i) => {
      const d = diskussionApi[i] || {};
      if (sauber(li.querySelector('b')) !== `${txt(d.von)} → ${txt(d.an)}`) befunde.push(`Konferenz-Diskussion ${i + 1}: Absender/Empfänger weicht ab`);
      if (!sauber(li.querySelector('small')).includes(txt(d.text))) befunde.push(`Konferenz-Diskussion ${i + 1}: Text fehlt oder weicht ab`);
    });
    const tabelle = massnahmenPanel?.querySelector('table.tbl');
    if (!tabelle) befunde.push('Konferenz-Massnahmentabelle fehlt');
    else {
      const kopf = [...tabelle.querySelectorAll('thead th')].map(sauber);
      const erwarteterKopf = ['Massnahme', 'Begründung', 'Testplan', 'Verantwortlich'];
      if (kopf.join('|') !== erwarteterKopf.join('|')) befunde.push(`Massnahmen-Kopf: «${kopf.join(' · ')}»`);
      const zeilen = [...tabelle.querySelectorAll('tbody tr')];
      const massnahmen = k.massnahmen || [];
      if (zeilen.length !== massnahmen.length) befunde.push(`Konferenz-Massnahmen: ${zeilen.length} statt ${massnahmen.length}`);
      const felder = ['beschreibung', 'begruendung', 'testplan', 'verantwortlicher'];
      zeilen.forEach((tr, i) => {
        const masse = massnahmen[i] || {};
        if (tr.cells.length !== 4) { befunde.push(`Konferenz-Massnahme ${i + 1}: ${tr.cells.length} statt 4 Spalten`); return; }
        felder.forEach((feld, spalte) => {
          if (sauber(tr.cells[spalte]) !== txt(masse[feld])) {
            befunde.push(`Konferenz-Massnahme ${i + 1}: ${feld} «${sauber(tr.cells[spalte])}» statt «${txt(masse[feld])}»`);
          }
        });
      });
    }
    return befunde;
  }, { ansicht, daten });
}

async function pruefeAgentenInhalte(page, runs) {
  const befunde = [];
  const erwartet = [
    ['A', 'Hauptzentrale'], ['B', 'Spider Intelligence'], ['C', 'Labor'], ['D', 'Trading Floor'],
    ['E', 'Forschungsabteilung'], ['F', 'Risikomanagement'], ['G', 'Wissenszentrum'], ['H', 'Entwicklungsabteilung'],
  ];
  const tabs = page.locator('#depTabs .tab');
  const tabAnzahl = await tabs.count();
  if (tabAnzahl !== erwartet.length) befunde.push(`Agentenraum: ${tabAnzahl} statt ${erwartet.length} Abteilungstabs`);
  const tabTexte = (await tabs.allTextContents()).map(t => t.replace(/\s+/g, ' ').trim());
  erwartet.forEach(([key, name], i) => {
    if (tabTexte[i] !== `${key} · ${name}`) befunde.push(`Abteilungstab ${i + 1}: «${tabTexte[i] || 'fehlt'}» statt «${key} · ${name}»`);
  });
  const aktiverTab = await page.locator('#depTabs .tab.on').first().textContent();
  const aktiverKey = (aktiverTab || '').split('·')[0].trim();
  const aktiveRuns = runs.filter(r => r.abteilung === aktiverKey);
  const startTag = await page.locator('#agTag').textContent();
  if (!(startTag || '').includes(`${aktiveRuns.length} Agenten`)) {
    befunde.push(`Agenten-Kopfzeile «${(startTag || '').trim()}» nennt nicht ${aktiveRuns.length} Agenten der aktiven Abteilung`);
  }
  const aktivitaet = await page.locator('#agRuns .li').count();
  if (aktivitaet !== Math.min(runs.length, 40)) befunde.push(`Agenten-Aktivität: ${aktivitaet} statt ${Math.min(runs.length, 40)} Einträge`);

  for (let i = 0; i < Math.min(tabAnzahl, erwartet.length); i++) {
    const [key, name] = erwartet[i];
    await tabs.nth(i).click();
    await page.waitForTimeout(80);
    const meine = runs.filter(r => r.abteilung === key);
    const stand = await page.evaluate(() => {
      const sauber = el => (el && el.textContent || '').replace(/\s+/g, ' ').trim();
      return {
        tag: sauber(document.querySelector('#agTag')),
        anzahl: document.querySelectorAll('#agList .li').length,
        leer: !!document.querySelector('#agList .empty'),
        namen: [...document.querySelectorAll('#agList .li b')].map(sauber).filter(Boolean),
      };
    });
    if (stand.anzahl !== meine.length) befunde.push(`${key} ${name}: ${stand.anzahl} statt ${meine.length} Agenten`);
    if (!meine.length && !stand.leer) befunde.push(`${key} ${name}: Leerzustand fehlt`);
    if (meine.length && stand.leer) befunde.push(`${key} ${name}: Liste zeigt trotz ${meine.length} Läufen einen Leerzustand`);
    if (!stand.tag.includes(`${meine.length} Agenten`)) befunde.push(`${key} ${name}: Kopfzahl «${stand.tag}» nennt nicht ${meine.length} Agenten`);
    for (const lauf of meine.slice(0, 5)) {
      const agentName = String(lauf.agent || '').split(':')[1] || lauf.agent;
      if (agentName && !stand.namen.includes(agentName)) befunde.push(`${key} ${name}: Agent «${agentName}» fehlt in der Liste`);
    }
  }
  if (tabAnzahl) await tabs.first().click();
  return befunde;
}

/**
 * Schreibt absichtlich falsche Kerndaten ins DOM und verlangt, dass
 * pruefeInhalte sie erkennt. So kann die Inhaltsprüfung nicht stillschweigend
 * leer laufen, wenn eine Ansicht oder ein Selektor einmal wegfällt.
 */
async function pruefeNegativtest(url) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
  const seitenfehler = [];
  page.on('pageerror', err => seitenfehler.push(String(err)));

  try {
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.waitForTimeout(250);

    const faelle = [
      {
        ansicht: 'strat',
        name: 'Strategie-KPI',
        mutieren: () => page.evaluate(() => {
          const el = document.querySelector('#stratDetail .kpis .kpi .v');
          if (!el) throw new Error('Strategie-KPI nicht gefunden');
          el.textContent = '999.999';
        }),
      },
      {
        ansicht: 'research',
        name: 'Research-Zahl',
        mutieren: () => page.evaluate(() => {
          const el = document.querySelector('#flow .station:nth-child(2) small');
          if (!el) throw new Error('Research-Zahl nicht gefunden');
          el.textContent = '9999 Kandidaten';
        }),
      },
      {
        ansicht: 'agents',
        name: 'Agenten-Kopfzahl',
        mutieren: () => page.evaluate(() => {
          const el = document.querySelector('#agTag');
          if (!el) throw new Error('Agenten-Kopfzeile nicht gefunden');
          el.textContent = '999 Agenten · 0 ohne Befund';
        }),
      },
      {
        ansicht: 'agents',
        name: 'Agenten-Abteilungstab',
        mutieren: () => page.evaluate(() => {
          const tabs = [...document.querySelectorAll('#depTabs .tab')];
          if (!tabs.length) throw new Error('Abteilungstabs nicht gefunden');
          tabs[tabs.length - 1].remove();
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Abteilungscluster',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .ship-dept')];
          if (cluster.length !== 11) throw new Error('Schiffscluster nicht vollständig gefunden');
          const s = cluster.find(el => (el.querySelector('.ship-dept-code')?.textContent || '').trim() === 'S');
          if (!s) throw new Error('Schiffscluster S nicht gefunden');
          s.remove();
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Abteilung leer',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .ship-dept')];
          const a = cluster.find(el => (el.querySelector('.ship-dept-code')?.textContent || '').trim() === 'A');
          if (!a) throw new Error('Schiffscluster A nicht gefunden');
          const raeume = [...a.querySelectorAll('.agent-room')];
          if (!raeume.length) throw new Error('Agentenräume in Cluster A nicht gefunden');
          raeume.forEach(el => el.remove());
        }),
      },
      {
        ansicht: 'konf',
        name: 'Konferenz-Testplan',
        mutieren: () => page.evaluate(() => {
          const el = document.querySelector('#konfBody table.tbl tbody tr td:nth-child(3)');
          if (!el) throw new Error('Konferenz-Testplan nicht gefunden');
          el.textContent = 'FALSCH 9999';
        }),
      },
    ];

    const erkannt = [];
    for (const [index, fall] of faelle.entries()) {
      const fallName = fall.name || fall.ansicht;
      // Jeder Fall startet auf einer frischen Seite: Der Acht-Sekunden-Refresh
      // darf eine absichtliche DOM-Mutation nicht zwischenzeitlich zurücksetzen.
      if (index > 0) {
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.waitForFunction(
          () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
          null, { timeout: 15000 },
        );
        await page.waitForTimeout(250);
      }
      const nav = page.locator(`.nav[data-v="${fall.ansicht}"]`);
      if (await nav.count()) await nav.click();
      else await page.evaluate(v => zeige(v), fall.ansicht);
      await page.waitForTimeout(WARTEZEIT[fall.ansicht] || 500);
      const sauber = await pruefeInhalte(page, fall.ansicht);
      if (!sauber || sauber.length) {
        throw new Error(`${fallName}: sauberer Zustand meldet bereits Befunde: ${(sauber || []).join('; ')}`);
      }

      await fall.mutieren();
      const befund = await pruefeInhalte(page, fall.ansicht);
      if (!befund || !befund.length) {
        throw new Error(`${fallName}: absichtlich falscher Inhalt wurde nicht erkannt`);
      }
      erkannt.push(fallName);
      console.log(`Negativtest ${fallName}: erkannt – ${befund[0]}`);
    }

    if (seitenfehler.length) throw new Error(`Seitenfehler: ${seitenfehler.join('; ')}`);
    console.log(`Negativtest OK: ${erkannt.length}/${faelle.length} falsche Inhalte erkannt`);
  } finally {
    await browser.close();
  }
}

async function main() {
  const opt = argumente(process.argv.slice(2));
  const { validierungen } = await pruefeServer(opt.url);
  if (opt.negativtest) {
    await pruefeNegativtest(opt.url);
    return;
  }
  console.log(`250-%-Prüflauf: ${opt.ansichten.length} Ansichten × ${opt.breiten.length} Breiten · ${validierungen} Validierungen im Bericht`);
  if (opt.bilder) mkdirSync(opt.bilder, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const fehler = [];
  const hinweise = new Set();
  let tabellenGesamt = 0, zellenGesamt = 0, bilderGesamt = 0, tooltipGesamt = 0, tastaturGesamt = 0, inhaltGesamt = 0;

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
        const nav = page.locator(`.nav[data-v="${ansicht}"]`);
        if (await nav.count()) await nav.click();
        else await page.evaluate(v => zeige(v), ansicht);
        await page.waitForTimeout(WARTEZEIT[ansicht]);
        if (ansicht === 'ship') {
          // Die Company-API wird beim Öffnen asynchron geladen. Auf ihren
          // Endzustand warten, damit die Messung nicht die Ladeansicht trifft.
          await page.waitForFunction(() => {
            const text = document.querySelector('#companyTag')?.textContent || '';
            return /live|API-FEHLER|keine Daten/.test(text);
          }, null, { timeout: 5000 });
        }
        let kurveGefunden = null;
        if (ansicht === 'lab') kurveGefunden = await waehleKurvenKandidat(page);
        await skaliere(page, 2.5);
        await page.waitForTimeout(150);

        const vorher = fehler.length;
        const ansichtBefund = await messeAnsicht(page, ansicht, breite);
        if (!ansichtBefund.gerendert) ansichtBefund.befunde.push('Ansicht wurde nicht gerendert');
        for (const text of ansichtBefund.befunde) fehler.push(`${breite}px/${ansicht}: ${text}`);

        const inhaltsBefunde = await pruefeInhalte(page, ansicht);
        if (inhaltsBefunde) {
          inhaltGesamt++;
          for (const text of inhaltsBefunde) fehler.push(`${breite}px/${ansicht}: ${text}`);
        }

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
  console.log(`OK: keine Überläufe${opt.tabellen ? ` · ${tabellenGesamt} Tabellen mit ${zellenGesamt} Zellen geprüft` : ''}${inhaltGesamt ? ` · Inhalte ${inhaltGesamt}× geprüft` : ''}${tooltipGesamt ? ` · Tooltip ${tooltipGesamt}× geprüft` : ''}${tastaturGesamt ? ` · Tastatur ${tastaturGesamt}× geprüft` : ''}${bilderGesamt ? ` · ${bilderGesamt} Screenshots` : ''}`);
}

main().catch(fehler => {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
});
