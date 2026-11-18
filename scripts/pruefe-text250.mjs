#!/usr/bin/env node
/**
 * Prüflauf für 250 % Textskalierung im Orakel-Dashboard.
 *
 * Für jede Ansicht werden die berechneten Schriftgrössen und Zeilenhöhen in
 * `main` mit 2,5 multipliziert — so wie es eine Browser-Textskalierung tut.
 * Danach wird geprüft, ob Inhalte seitlich aus ihrem Kasten oder aus dem
 * Viewport laufen. Tabellen werden zusätzlich mit langen deutschen Komposita
 * belastet und als Karten geprüft. Im Spider-Tab rendert der Lauf
 * deterministische Claim-Metadaten samt Widerspruchsgrund, Sicherheit,
 * normalisierten Vergleichswerten und beteiligten Quellen und prüft deren
 * horizontale Grenzen.
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
 *   --bilder <verzeichnis> Schreibt bei Befunden je Ansicht und Breite Screenshot und HTML
 *   Die Seite samt Kopf und Navigation wird zusätzlich bei 240 px auf Umbruch
 *   und horizontalen Überlauf geprüft.
 *   --bild-praefix <name>  Gibt Screenshots und HTML einen eindeutigen Namenspräfix
 *   --selbsttest-cluster   Prüft mehrere gleichzeitige Cluster-Fehler und eindeutige Screenshotnamen
 *   --selbsttest-agent      Prüft einen fehlenden Agenten samt Screenshotpfad
 *
 * Zusätzlich wird die Kopfzeile bei 1024 px auf horizontalen Überlauf und
 * einen sichtbaren «Lauf starten»-Button geprüft. Bei 1440 px wird die
 * kompakte Abteilungslegende auf vollständige, überlauffreie Darstellung
 * geprüft. Der Auto-Refresh der Lab-Kurve wird über eine echte
 * /api/report-Antwort mit HTTP 200 und sichtbarem Datenmarker geprüft; Fokus,
 * Tooltip, Live-Region und Zeiger müssen dabei unverändert bleiben.
 */

import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { chromium } from 'playwright';

const LANGS = 'Donaudampfschifffahrtsgesellschaftskapitänsmützenhalterungsverordnung';
const LANGES_LABEL = 'Bevölkerungsentwicklungsprognoseberechnungsgrundlagenverordnung';
const STANDARD_ANSICHTEN = ['overview', 'risk', 'lab', 'strat', 'research', 'globe', 'betrieb', 'ship', 'spider', 'kb', 'agents', 'konf'];
const WARTEZEIT = {
  overview: 300, risk: 350, lab: 400, strat: 500, research: 500, globe: 1300,
  betrieb: 750, ship: 1500, spider: 650, kb: 1500, agents: 500, konf: 500,
};

// Deterministische Browser-Testdaten für die Claim-Karte. Der Seed enthält
// keine Claims; die Daten werden nur im Browser gerendert und nie in SQLite
// geschrieben. Die langen Metadaten belasten die schmalen Viewports.
const CLAIM_TESTDATEN = {
  claims: {
    top: [
      {
        id: 900001,
        kernaussage: 'Test-Claim: Die Inflation sinkt im Juli 2026, falls die Konjunktur nicht einbricht.',
        thema: 'makro',
        quellen: 2,
        belege: 3,
        zeitraum: '2026-07',
        bedingung: 'falls die Konjunktur nicht einbricht und die Notenbank den Kurs bestätigt',
        sicherheit: 0.8,
        status: 'widersprüchlich',
        bestaetigungsgrad: 0.42,
      },
      {
        id: 900002,
        kernaussage: 'Test-Claim ohne Bedingung mit einem langen Titel für den schmalen Viewport',
        thema: 'markt',
        quellen: 1,
        belege: 1,
        zeitraum: '',
        bedingung: '',
        sicherheit: 0.9,
        status: 'teilweise',
        bestaetigungsgrad: 0.55,
      },
    ],
    widersprueche: [{
      claim_id: 900001,
      grund: 'Richtung steigt gegen sinkt (Bedingung gegen unbedingte Aussage)',
      sicherheit: 0.7,
      quelle_a: 'a.example',
      quelle_b: 'b.example',
    }, {
      claim_id: 900001,
      grund: 'Abweichender Zahlenwert bei gleicher Einheit',
      sicherheit: 0.65,
      quelle_a: 'c.example',
      quelle_b: 'd.example',
      wert_a_bp: 450,
      wert_b_bp: 440,
    }],
    statistik: {
      gesamt: 2,
      belege: 4,
      nach_status: { bestätigt: 0, teilweise: 1, widersprüchlich: 1 },
      widersprueche: 2,
    },
  },
  reputation: [],
};

// Zusätzliche Daten für den Umbruchtest mit bewusst überlangen Quellenhosts.
// Sie werden ebenfalls nur im Browser gerendert; die normalen Claim-Erwartungen
// bleiben unverändert.
const LANGE_QUELLEN_TESTDATEN = JSON.parse(JSON.stringify(CLAIM_TESTDATEN));
for (const [index, widerspruch] of LANGE_QUELLEN_TESTDATEN.claims.widersprueche.entries()) {
  widerspruch.quelle_a = index === 0
    ? 'sehr-lange-quellen-domain-mit-vielen-segmenten.nachrichtenagentur.example.com'
    : 'a'.repeat(140) + '.example.net';
  widerspruch.quelle_b = 'noch-laengere-quellen-domain-mit-subdomain-und-hyphen.nachrichtenarchiv.example.org';
}
// Zusätzliche Fälle mit genau einem sehr langen Host und einer kurzen
// Gegenseite. Sie belasten die Zeile bei 280 und 320 px unabhängig vom
// bisherigen Langhost-Paar.
LANGE_QUELLEN_TESTDATEN.claims.widersprueche.push({
  claim_id: 900001,
  grund: 'Einzelner sehr langer Host gegen kurze Quelle',
  sicherheit: 0.6,
  quelle_a: 'ein-sehr-langer-hostname-mit-vielen-subdomains-und-hyphen.nachrichtenagentur.example.net',
  quelle_b: 'kurz.example',
});
// Extremfall ohne jeden Punkt oder Bindestrich: Der Host darf nur an
// beliebigen Zeichen umbrechen, nicht an DNS-Trennern.
LANGE_QUELLEN_TESTDATEN.claims.widersprueche.push({
  claim_id: 900001,
  grund: 'Host ohne Punkt oder Bindestrich gegen kurze Quelle',
  sicherheit: 0.6,
  quelle_a: 'quellenhostohnebindestrichundohnepunkt'.repeat(3),
  quelle_b: 'kurz.example',
});

/** Prüft die Claim-Metadaten und horizontale Überläufe auf einer eigenen Seite. */
async function pruefeClaimMetadaten(browser, url, breite) {
  const page = await browser.newPage({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
  const seitenfehler = [];
  page.on('pageerror', err => seitenfehler.push(`Seite: ${err}`));
  try {
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.locator('.nav[data-v="spider"]').click();
    await page.waitForTimeout(WARTEZEIT.spider);
    return [...seitenfehler, ...await pruefeClaimMetadatenAufSeite(page)];
  } finally {
    await page.close();
  }
}

/** Prüft bei 240 px alle gewählten Ansichten in normaler Schrift. */
async function pruefe240Ansichten(browser, url, ansichten) {
  const page = await browser.newPage({ viewport: { width: 240, height: 900 }, deviceScaleFactor: 1 });
  const befund = [];
  const ergebnisse = [];
  const seitenfehler = [];
  page.on('pageerror', err => seitenfehler.push(String(err)));
  try {
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.waitForTimeout(250);
    for (const ansicht of ansichten) {
      const nav = page.locator(`.nav[data-v="${ansicht}"]`);
      if (await nav.count()) await nav.click();
      else await page.evaluate(v => zeige(v), ansicht);
      await page.waitForTimeout(WARTEZEIT[ansicht]);
      if (ansicht === 'ship') {
        await page.waitForFunction(() => {
          const text = document.querySelector('#companyTag')?.textContent || '';
          return /live|API-FEHLER|keine Daten/.test(text);
        }, null, { timeout: 5000 });
      }
      const stand = await page.evaluate(() => {
        const top = document.querySelector('.top');
        const side = document.querySelector('.side');
        const sideKasten = side?.getBoundingClientRect();
        const navs = side ? [...side.querySelectorAll('.nav')] : [];
        return {
          viewport: innerWidth,
          doc: document.documentElement.scrollWidth,
          top: top?.scrollWidth || 0,
          topClient: top?.clientWidth || 0,
          side: side?.scrollWidth || 0,
          sideClient: side?.clientWidth || 0,
          navAnzahl: navs.length,
          navAussen: sideKasten ? navs.filter(n => {
            const kasten = n.getBoundingClientRect();
            return kasten.left < sideKasten.left - 1 || kasten.right > sideKasten.right + 1;
          }).length : 0,
        };
      });
      const ansichtBefund = [];
      if (stand.doc > stand.viewport + 1) {
        ansichtBefund.push(`Seite ${stand.doc}>${stand.viewport}`);
      }
      if (stand.top > stand.topClient + 1) {
        ansichtBefund.push(`Kopf ${stand.top}>${stand.topClient}`);
      }
      if (stand.side > stand.sideClient + 1) {
        ansichtBefund.push(`Navigation ${stand.side}>${stand.sideClient}`);
      }
      if (stand.navAnzahl !== 10) {
        ansichtBefund.push(`Navigationspunkte ${stand.navAnzahl} statt 10`);
      }
      if (stand.navAussen) {
        ansichtBefund.push(`Navigationspunkte ausserhalb ${stand.navAussen}`);
      }
      ergebnisse.push({ ansicht, ...stand, ok: ansichtBefund.length === 0 });
      if (ansichtBefund.length) {
        befund.push(`240px/${ansicht}: ${ansichtBefund.join(', ')}`);
      } else {
        console.log(`240px/${ansicht}: OK · Seite ${stand.doc}px · Kopf ${stand.top}/${stand.topClient} · Navigation ${stand.side}/${stand.sideClient}`);
      }
    }
    if (seitenfehler.length) befund.push(`240px/Seitenfehler: ${seitenfehler.join('; ')}`);
    const ok = ergebnisse.filter(e => e.ok).length;
    console.log(`240px: ${ok}/${ergebnisse.length} Ansichten ohne horizontalen Überlauf`);
    return { befund, ergebnisse };
  } finally {
    await page.close();
  }
}

/** Prüft Widerspruchsgrund und -sicherheit in der gerenderten Claim-Karte. */
async function pruefeClaimWiderspruchsdetails(page) {
  return page.evaluate(() => {
    const details = [...document.querySelectorAll('#bewertungClaims .claimWiderspruch')];
    if (!details.length) return ['Widerspruchsdetails fehlen'];
    const befunde = [];
    details.forEach((detail, index) => {
      const grund = detail.querySelector('.claimWiderspruchGrund');
      if (!grund || !grund.textContent.trim()) {
        befunde.push(`Widerspruch ${index + 1}: Widerspruchsgrund fehlt`);
      }
      const sicherheit = detail.querySelector('.claimWiderspruchSicherheit');
      const text = (sicherheit?.textContent || '').replace(/\s+/g, ' ').trim();
      if (!/^Widerspruchssicherheit:\s*\d(?:[.,]\d+)?$/.test(text)) {
        befunde.push(`Widerspruch ${index + 1}: Widerspruchssicherheit fehlt`);
      }
    });
    return befunde;
  });
}

/** Prüft den Umbruch der Quellenzeile mit sehr langen Hostnamen. */
async function pruefeLangeQuellen(page) {
  await page.evaluate(daten => window.zeichneBewertung(daten), LANGE_QUELLEN_TESTDATEN);
  await page.waitForTimeout(80);
  const langhosts = LANGE_QUELLEN_TESTDATEN.claims.widersprueche.map(widerspruch => widerspruch.quelle_a);
  return page.evaluate((erwarteteLanghosts) => {
    const befund = [];
    const liste = document.querySelector('#bewertungClaims');
    if (!liste) return ['Claim-Liste #bewertungClaims fehlt'];
    const panel = document.querySelector('#bewertungPanel');
    const panelKasten = panel?.getBoundingClientRect();
    const quellen = [...liste.querySelectorAll('.claimWiderspruchQuellen')];
    if (quellen.length !== erwarteteLanghosts.length) {
      befund.push(`Quellenzeilen mit Langhosts: ${quellen.length} statt ${erwarteteLanghosts.length}`);
    }
    for (const [index, q] of quellen.entries()) {
      if (!q.getClientRects().length) {
        befund.push(`Quellenzeile ${index + 1}: nicht sichtbar`);
        continue;
      }
      if (erwarteteLanghosts[index] && !q.textContent.includes(erwarteteLanghosts[index])) {
        befund.push(`Quellenzeile ${index + 1}: Langhost fehlt`);
      }
      if (q.scrollWidth > q.clientWidth + 1) {
        befund.push(`Quellenzeile ${index + 1}: horizontaler Überlauf (${q.scrollWidth}>${q.clientWidth})`);
      }
      const pfeil = q.querySelector('.claimWiderspruchPfeil');
      if (!pfeil) {
        befund.push(`Quellenzeile ${index + 1}: Trenner fehlt`);
      } else {
        const pfeilKasten = pfeil.getBoundingClientRect();
        const quellSpans = [...q.querySelectorAll('.claimWiderspruchQuelle')];
        const pfeilAufQuellzeile = quellSpans.some(s => [...s.getClientRects()].some(r =>
          r.bottom > pfeilKasten.top + 1 && r.top < pfeilKasten.bottom - 1
        ));
        if (!pfeilAufQuellzeile) befund.push(`Quellenzeile ${index + 1}: Trenner steht allein`);
      }
      if (panelKasten) {
        const kasten = q.getBoundingClientRect();
        if (kasten.left < panelKasten.left - 1 || kasten.right > panelKasten.right + 1) {
          befund.push(`Quellenzeile ${index + 1}: ausserhalb des Panels`);
        }
      }
    }
    const viewport = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > viewport + 1) {
      befund.push(`Seite mit Langhosts: horizontaler Überlauf (${document.documentElement.scrollWidth}>${viewport})`);
    }
    return befund;
  }, langhosts);
}

/** Misst die bereits geöffnete Spider-Seite mit den Claim-Testdaten. */
async function pruefeClaimMetadatenAufSeite(page) {
  if (!await page.evaluate(() => typeof window.zeichneBewertung === 'function')) {
    return ['Claim-Renderer zeichneBewertung fehlt'];
  }
  await page.evaluate(daten => window.zeichneBewertung(daten), CLAIM_TESTDATEN);
  await page.waitForTimeout(80);
  const befund = await page.evaluate(() => {
    const befund = [];
    const liste = document.querySelector('#bewertungClaims');
    if (!liste) return ['Claim-Liste #bewertungClaims fehlt'];
    const karten = [...liste.querySelectorAll('.li')];
    const metas = [...liste.querySelectorAll('.claimMeta')];
    const widersprueche = [...liste.querySelectorAll('.claimWiderspruch')];
    if (karten.length !== 2) befund.push(`Claim-Karten: ${karten.length} statt 2`);
    if (metas.length !== 2) befund.push(`Claim-Metadaten: ${metas.length} statt 2`);
    for (const [index, meta] of metas.entries()) {
      const text = meta.textContent.replace(/\s+/g, ' ').trim();
      for (const label of ['Zeitraum:', 'Bedingung:', 'Extraktionssicherheit:']) {
        if (!text.includes(label)) befund.push(`Claim ${index + 1}: ${label} fehlt`);
      }
    }
    if (metas[0] && !metas[0].textContent.includes('2026-07')) {
      befund.push('Claim 1: Zeitraumwert 2026-07 fehlt');
    }
    if (metas[0] && !metas[0].textContent.includes('0.80')) {
      befund.push('Claim 1: Extraktionssicherheit 0.80 fehlt');
    }
    if (widersprueche.length !== 2) {
      befund.push(`Widerspruchsdetails: ${widersprueche.length} statt 2`);
    } else {
      const erwarteteGruende = [
        'Richtung steigt gegen sinkt (Bedingung gegen unbedingte Aussage)',
        'Abweichender Zahlenwert bei gleicher Einheit',
      ];
      const erwarteteSicherheit = ['0.70', '0.65'];
      const erwarteteQuellen = [['a.example', 'b.example'], ['c.example', 'd.example']];
      const erwarteteVergleiche = [null, ['450.00 bp', '440.00 bp']];
      for (const [index, detail] of widersprueche.entries()) {
        const text = detail.textContent.replace(/\s+/g, ' ').trim();
        if (!text.includes(erwarteteGruende[index])) {
          befund.push(`Widerspruch ${index + 1}: Widerspruchsgrund fehlt`);
        }
        if (!text.includes('Widerspruchssicherheit:')) {
          befund.push(`Widerspruch ${index + 1}: Widerspruchssicherheit fehlt`);
        }
        if (!text.includes(erwarteteSicherheit[index])) {
          befund.push(`Widerspruch ${index + 1}: Widerspruchssicherheit ${erwarteteSicherheit[index]} fehlt`);
        }
        const [quelleA, quelleB] = erwarteteQuellen[index] || [];
        if (!quelleA || !quelleB || !text.includes(`Quellen: ${quelleA}`) || !text.includes(quelleB)) {
          befund.push(`Widerspruch ${index + 1}: beteiligte Quellen fehlen`);
        }
        const vergleich = detail.querySelector('.claimWiderspruchWerte');
        const erwarteterVergleich = erwarteteVergleiche[index];
        if (erwarteterVergleich) {
          if (!vergleich) {
            befund.push(`Widerspruch ${index + 1}: normalisierte Vergleichswerte fehlen`);
          } else {
            const vergleichText = vergleich.textContent.replace(/\s+/g, ' ').trim();
            for (const wert of erwarteterVergleich) {
              if (!vergleichText.includes(wert)) {
                befund.push(`Widerspruch ${index + 1}: Vergleichswert ${wert} fehlt`);
              }
            }
          }
        } else if (vergleich) {
          befund.push(`Widerspruch ${index + 1}: unerwartete Vergleichswerte`);
        }
      }
    }

    const viewport = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > viewport + 1) {
      befund.push(`Seite hat horizontalen Überlauf (${document.documentElement.scrollWidth}>${viewport})`);
    }
    if (innerWidth <= 260) {
      const top = document.querySelector('.top');
      const side = document.querySelector('.side');
      if (!top) {
        befund.push('Kopfzeile fehlt');
      } else if (top.scrollWidth > top.clientWidth + 1) {
        befund.push(`Kopfzeile läuft horizontal über (${top.scrollWidth}>${top.clientWidth})`);
      }
      if (!side) {
        befund.push('Navigationsleiste fehlt');
      } else {
        if (side.scrollWidth > side.clientWidth + 1) {
          befund.push(`Navigationsleiste läuft horizontal über (${side.scrollWidth}>${side.clientWidth})`);
        }
        const rahmen = side.getBoundingClientRect();
        const navs = [...side.querySelectorAll('.nav')];
        if (navs.length !== 10) befund.push(`Navigationspunkte: ${navs.length} statt 10`);
        const ausserhalb = navs.filter(nav => {
          const kasten = nav.getBoundingClientRect();
          return kasten.left < rahmen.left - 1 || kasten.right > rahmen.right + 1;
        });
        if (ausserhalb.length) {
          befund.push(`Navigationspunkte ausserhalb der Leiste: ${ausserhalb.length}`);
        }
      }
    }
    const panel = document.querySelector('#bewertungPanel');
    if (innerWidth <= 260 && panel) {
      for (const [name, selector] of [
        ['KPI-Grid', '#bewertungKpis'],
        ['Claim-Grid', '.grid2'],
      ]) {
        const grid = panel.querySelector(selector);
        if (!grid) {
          befund.push(`${name} fehlt`);
          continue;
        }
        const spalten = getComputedStyle(grid).gridTemplateColumns.trim().split(/\s+/).filter(Boolean).length;
        if (spalten !== 1) befund.push(`${name}: ${spalten} statt 1 Spalte bei 240 px`);
      }
    }
    const flaechen = panel ? [panel, ...panel.querySelectorAll('*')] : [liste];
    for (const el of flaechen) {
      if (!el.getClientRects().length) continue;
      const kasten = el.getBoundingClientRect();
      const name = el.tagName.toLowerCase()
        + (el.id ? '#' + el.id : '')
        + (el.className ? '.' + String(el.className).trim().split(/\s+/).join('.') : '');
      if (kasten.left < -1 || kasten.right > viewport + 1) {
        befund.push(`${name}: außerhalb des Viewports (${Math.round(kasten.left)}–${Math.round(kasten.right)} bei ${viewport})`);
      }
      if (el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        befund.push(`${name}: Inhalt ${el.scrollWidth}>${el.clientWidth}`);
      }
    }
    return befund.slice(0, 20);
  });
  return [...befund, ...await pruefeLangeQuellen(page)];
}

function argumente(argv) {
  const opts = {
    url: process.env.ORAKEL_URL || 'http://127.0.0.1:3000',
    breiten: [360, 320, 280],
    ansichten: [...STANDARD_ANSICHTEN],
    tabellen: true,
    bilder: null,
    bildPraefix: '',
    negativtest: false,
    selbsttestCluster: false,
    selbsttestAgent: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--url') opts.url = argv[++i];
    else if (arg === '--breiten') opts.breiten = argv[++i].split(',').map(Number).filter(n => n >= 200);
    else if (arg === '--ansichten') opts.ansichten = argv[++i].split(',').map(s => s.trim()).filter(Boolean);
    else if (arg === '--ohne-tabellen') opts.tabellen = false;
    else if (arg === '--bilder') opts.bilder = argv[++i];
    else if (arg === '--bild-praefix') {
      opts.bildPraefix = artefaktSlug(argv[++i] || '').slice(0, 40);
      if (!opts.bildPraefix) { console.error('--bild-praefix benötigt einen Namen.'); process.exit(2); }
    }
    else if (arg === '--negativtest') opts.negativtest = true;
    else if (arg === '--selbsttest-cluster') opts.selbsttestCluster = true;
    else if (arg === '--selbsttest-agent') opts.selbsttestAgent = true;
    else if (arg === '--hilfe' || arg === '-h') {
      console.log('Aufruf: node scripts/pruefe-text250.mjs [--url URL] [--breiten 360,320,280]\n' +
        '       [--ansichten overview,risk,lab,strat,research,globe,betrieb,ship,spider,kb,agents,konf] [--ohne-tabellen]\n' +
        '       [--bilder <verzeichnis>] [--bild-praefix <name>] [--negativtest] [--selbsttest-cluster] [--selbsttest-agent]\n' +
        '       Die Seite samt Kopf und Navigation wird zusätzlich bei 240 px geprüft.');
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

/**
 * Prüft die neuen Company-Schreibwege über die Web-API im Browserkontext:
 * direkte Nachricht senden, als Empfänger quittieren und einen persönlichen
 * Gedächtniseintrag anlegen bzw. aktualisieren. Die Werte sind pro Lauf
 * eindeutig; geschrieben wird ausschliesslich in die Datenbank des laufenden
 * Testservers.
 */
async function pruefeCompanySchreibwege(page) {
  const lauf = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  const subject = `Web-Schreibtest ${lauf}`;
  const body = `Automatischer Schreibtest ${lauf}.`;
  const key = `web-schreibtest-${lauf}`;
  const wert = { quelle: 'pruefe-text250', lauf };
  const aktualisiert = { ...wert, status: 'aktualisiert' };

  const ergebnis = await page.evaluate(async ({ subject, body, key, wert, aktualisiert }) => {
    const befunde = [];
    const anfrage = async (pfad, optionen = {}) => {
      try {
        const antwort = await fetch(pfad, {
          cache: 'no-store',
          ...optionen,
          headers: { 'Content-Type': 'application/json', ...(optionen.headers || {}) },
        });
        const inhalt = await antwort.json().catch(() => ({}));
        return { status: antwort.status, ok: antwort.ok, inhalt };
      } catch (fehler) {
        return { status: 0, ok: false, inhalt: {}, fehler: String(fehler) };
      }
    };

    const memoryPost = await anfrage('/api/company/agents/A1/memories', {
      method: 'POST',
      body: JSON.stringify({ scope: 'profile', key, value: wert }),
    });
    if (!memoryPost.ok || !memoryPost.inhalt.ok) {
      befunde.push(`Gedächtnis anlegen: HTTP ${memoryPost.status}${memoryPost.fehler ? ` (${memoryPost.fehler})` : ''}`);
    } else {
      const eintrag = memoryPost.inhalt.erinnerung || {};
      if (eintrag.agent_id !== 'A1' || eintrag.scope !== 'profile' || eintrag.key !== key
          || !eintrag.value || eintrag.value.lauf !== wert.lauf) {
        befunde.push('Gedächtnis anlegen liefert den falschen Eintrag zurück');
      }
    }

    const memoryUpdate = await anfrage('/api/company/agents/A1/memories', {
      method: 'POST',
      body: JSON.stringify({ scope: 'profile', key, value: aktualisiert }),
    });
    if (!memoryUpdate.ok || !memoryUpdate.inhalt.ok) {
      befunde.push(`Gedächtnis aktualisieren: HTTP ${memoryUpdate.status}`);
    }
    const memoryGet = await anfrage('/api/company/agents/A1/memories?scope=profile');
    if (!memoryGet.ok || !memoryGet.inhalt.ok) {
      befunde.push(`Gedächtnis lesen: HTTP ${memoryGet.status}`);
    } else {
      const treffer = (memoryGet.inhalt.erinnerungen || []).filter(e => e.key === key);
      if (treffer.length !== 1) {
        befunde.push(`Gedächtnis-Upsert hinterlässt ${treffer.length} statt 1 Eintrag`);
      } else if (!treffer[0].value || treffer[0].value.status !== 'aktualisiert') {
        befunde.push('Gedächtnis-Upsert hat den Wert nicht aktualisiert');
      }
    }

    const messagePost = await anfrage('/api/company/messages', {
      method: 'POST',
      body: JSON.stringify({
        from_agent: 'A1', to_agent: 'A2', kind: 'status', subject, body,
        evidence: [`web:${key}`], requires_ack: true,
      }),
    });
    let messageId = null;
    if (!messagePost.ok || !messagePost.inhalt.ok) {
      befunde.push(`Nachricht senden: HTTP ${messagePost.status}${messagePost.fehler ? ` (${messagePost.fehler})` : ''}`);
    } else {
      const ids = messagePost.inhalt.message_ids || [];
      messageId = ids.length === 1 ? Number(ids[0]) : null;
      if (!Number.isInteger(messageId) || messageId <= 0) {
        befunde.push(`Nachricht senden liefert ${ids.length} statt 1 gültige Nachricht`);
        messageId = null;
      } else {
        const nachricht = (messagePost.inhalt.messages || [])[0] || {};
        if (nachricht.id !== messageId || nachricht.from_agent !== 'A1'
            || nachricht.to_agent !== 'A2' || nachricht.subject !== subject
            || nachricht.requires_ack !== true || nachricht.ack_at !== null
            || JSON.stringify(nachricht.evidence) !== JSON.stringify([`web:${key}`])) {
          befunde.push('Gesendete Nachricht hat nicht die erwarteten Felder');
        }
      }
    }

    if (messageId === null) {
      befunde.push('Quittung konnte ohne gültige Nachrichten-ID nicht geprüft werden');
    } else {
      const ack = await anfrage(`/api/company/messages/${messageId}/ack`, {
        method: 'POST',
        body: JSON.stringify({ agent_id: 'A2' }),
      });
      if (!ack.ok || !ack.inhalt.ok) {
        befunde.push(`Nachricht quittieren: HTTP ${ack.status}${ack.fehler ? ` (${ack.fehler})` : ''}`);
      } else if (!ack.inhalt.nachricht || !ack.inhalt.nachricht.ack_at) {
        befunde.push('Quittung liefert keinen Quittungszeitpunkt zurück');
      }

      const offen = await anfrage('/api/company/messages?agent=A2&nur_offen=true');
      if (!offen.ok || !offen.inhalt.ok) {
        befunde.push(`Offene Nachrichten lesen: HTTP ${offen.status}`);
      } else if ((offen.inhalt.nachrichten || []).some(m => Number(m.id) === messageId)) {
        befunde.push('Quittierte Nachricht erscheint weiterhin als offen');
      }

      const detail = await anfrage(`/api/company/messages/${messageId}`);
      if (!detail.ok || !detail.inhalt.ok) {
        befunde.push(`Nachricht nach Quittung lesen: HTTP ${detail.status}`);
      } else if (!detail.inhalt.nachricht || !detail.inhalt.nachricht.ack_at) {
        befunde.push('Quittung ist nicht persistent gespeichert');
      }
    }

    return { befunde, geprueft: befunde.length ? 0 : 3 };
  }, { subject, body, key, wert, aktualisiert });
  return ergebnis;
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
      if (el.closest('.px-ship')) continue;             // Pixel-Art ist eine feste Zeichnung; Agentendetails skalieren rechts.
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

/**
 * Der 8-Sekunden-Auto-Refresh darf eine fokussierte Lab-Kurve nicht neu
 * aufbauen: Sonst gehen Fokus, Tooltip und Live-Region mitten in der
 * Tastaturbedienung verloren. Der Test wartet deterministisch auf eine echte
 * /api/report-Antwort, verlangt HTTP 200 und einen kontrollierten Marker im
 * Kopfbereich. Damit ist belegt, dass der Refresh tatsächlich Daten verarbeitet
 * hat, ohne dass die fokussierte Kurve neu gerendert wurde.
 */
async function pruefeLabAutoRefresh(page, ansicht, optionen = {}) {
  const befunde = [];
  const svg = page.locator(`#v-${ansicht} .wfoKurveFlaeche svg`);
  if (!(await svg.count())) return ['Auto-Refresh-Prüfung ohne Kapitalkurve'];
  await page.mouse.move(0, 0);
  await svg.evaluate(el => el.focus());
  await page.waitForTimeout(100);
  const lese = () => page.evaluate((ansicht) => {
    const box = document.querySelector(`#v-${ansicht} .wfoKurveFlaeche`);
    const svg = box.querySelector('svg');
    return {
      fokus: document.activeElement === svg,
      text: box.querySelector('.wfoKurveTipp').innerText.replace(/\s+/g, ' ').trim(),
      live: box.querySelector('.wfoKurveLive').textContent.trim(),
      zeiger: box.querySelector('.wfoKurveZeiger').getAttribute('x1'),
    };
  }, ansicht);
  const vorher = await lese();
  if (!vorher.fokus || !vorher.text || !vorher.live) {
    befunde.push('Auto-Refresh-Prüfung konnte die Kapitalkurve nicht fokussieren');
    return befunde;
  }
  if (optionen.erzwingeRerender) {
    // Negativfall: Fokus verlassen, damit der Guard den Ansichts-Render nicht
    // mehr pausiert und die Kurve beim nächsten Refresh neu zeichnet.
    await svg.evaluate(el => el.blur());
    await page.mouse.move(0, 0);
  }

  const marker = `refresh-probe-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const timeout = Symbol('refresh-timeout');
  let meldeRefresh;
  let routeFehler = null;
  const antwortVersprechen = new Promise(resolve => { meldeRefresh = resolve; });
  const handler = async route => {
    try {
      const antwort = await route.fetch();
      if (!antwort.ok()) {
        await route.fulfill({ response: antwort });
        meldeRefresh({ status: antwort.status(), ok: false });
        return;
      }
      const daten = await antwort.json();
      if (!daten || typeof daten !== 'object' || Array.isArray(daten)) {
        throw new Error('Bericht ist kein JSON-Objekt');
      }
      daten.datenquelle = marker;
      await route.fulfill({ response: antwort, json: daten });
      meldeRefresh({ status: antwort.status(), ok: true });
    } catch (fehler) {
      routeFehler = fehler instanceof Error ? fehler.message : String(fehler);
      await route.abort().catch(() => {});
      meldeRefresh(null);
    }
  };
  await page.route('**/api/report', handler);
  let timeoutId;
  const timeoutVersprechen = new Promise(resolve => {
    timeoutId = setTimeout(() => resolve(timeout), 12000);
  });
  const antwort = await Promise.race([antwortVersprechen, timeoutVersprechen]);
  clearTimeout(timeoutId);
  if (antwort === timeout) {
    befunde.push('Auto-Refresh lieferte innerhalb von 12 Sekunden keine Antwort');
  } else if (!antwort) {
    befunde.push(`Auto-Refresh-Antwort konnte nicht geprüft werden${routeFehler ? ` (${routeFehler})` : ''}`);
  } else if (!antwort.ok || antwort.status !== 200) {
    befunde.push(`Auto-Refresh antwortet mit HTTP ${antwort.status}`);
  } else {
    const markerSichtbar = await page.waitForFunction(
      m => (document.querySelector('#banner')?.textContent || '').includes(m),
      marker, { timeout: 3000 },
    ).then(() => true).catch(() => false);
    if (!markerSichtbar) befunde.push('Auto-Refresh-Daten wurden nicht gerendert');
  }
  await page.unroute('**/api/report', handler).catch(() => {});

  const nachher = await lese();
  if (!nachher.fokus) befunde.push('Auto-Refresh nimmt der Kapitalkurve den Fokus');
  if (nachher.text !== vorher.text) befunde.push(`Auto-Refresh verändert den Tooltip («${nachher.text || 'leer'}» statt «${vorher.text}»)`);
  if (nachher.live !== vorher.live) befunde.push(`Auto-Refresh verändert die Live-Region («${nachher.live || 'leer'}» statt «${vorher.live}»)`);
  if (nachher.zeiger !== vorher.zeiger) befunde.push(`Auto-Refresh verschiebt den Zeiger (${nachher.zeiger} statt ${vorher.zeiger})`);
  return befunde;
}

/**
 * Negativtest für den Refresh-Guard: Er muss ausbleibenden Refresh und ein
 * erzwungenes Re-Render der Lab-Kurve als Befund erkennen. Beide Fehlerbilder
 * werden gezielt injiziert; nur wenn der Guard sie meldet, ist er wirksam.
 */
async function pruefeLabAutoRefreshNegativ(browser, url, breite) {
  const befunde = [];
  const oeffne = async (initSkript = null) => {
    const page = await browser.newPage({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
    if (initSkript) await page.addInitScript(initSkript);
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    const nav = page.locator('.nav[data-v="lab"]');
    if (await nav.count()) await nav.click();
    else await page.evaluate(() => zeige('lab'));
    await page.waitForTimeout(WARTEZEIT.lab);
    await skaliere(page, 2.5);
    await page.waitForTimeout(150);
    return page;
  };

  // 1. Ausbleibender Refresh: Der Acht-Sekunden-Aufruf wird vor dem Laden
  //    blockiert. Der Guard darf nicht stillschweigend bestehen.
  const ohne = await oeffne(() => {
    const original = window.setInterval;
    window.setInterval = (fn, ms, ...rest) => {
      if (ms === 8000) return 0;
      return original(fn, ms, ...rest);
    };
  });
  try {
    const ohneBefunde = await pruefeLabAutoRefresh(ohne, 'lab');
    if (!ohneBefunde.some(text => /keine Antwort/.test(text))) {
      befunde.push(`Negativtest erkennt ausbleibenden Refresh nicht («${ohneBefunde.join('; ') || 'keine Befunde'}»)`);
    }
  } finally {
    await ohne.close();
  }

  // 2. Erzwungenes Re-Render: Nach dem Verlassen des Fokus muss der Guard den
  //    Fokusverlust als Befund melden, statt den Refresh stillschweigend
  //    durchzuwinken.
  const mit = await oeffne();
  try {
    const mitBefunde = await pruefeLabAutoRefresh(mit, 'lab', { erzwingeRerender: true });
    if (mitBefunde.some(text => /nicht gerendert/.test(text))) {
      befunde.push(`Erzwungenes Re-Render blieb aus («${mitBefunde.join('; ')}»)`);
    } else if (!mitBefunde.some(text => /Fokus/.test(text))) {
      befunde.push(`Negativtest erkennt erzwungenes Re-Render nicht («${mitBefunde.join('; ') || 'keine Befunde'}»)`);
    }
  } finally {
    await mit.close();
  }

  return befunde;
}

/**
 * Zwei Regressionstests für den Lab-Guard: Ein Fokus auf der Lab-Liste oder auf
 * einem Lab-Tab liegt in #v-lab, aber ausserhalb von #labDetail und darf den
 * Ansichts-Render nicht blockieren. Die API-Antwort erhält einen eindeutigen
 * Marker in allen Kandidatensymbolen; ein Rückfall auf einen breiten
 * #v-lab-Guard überspringt den Render und der Marker fehlt in #labList.
 *
 * Der frühere dritte Fall mit ausgeblendetem Lab entfällt: Chromium setzt den
 * Fokus beim Ausblenden auf body. Der Zustand «Fokus in #labDetail, während
 * #v-lab hidden ist» liesse sich nur durch Überschreiben von
 * document.activeElement herstellen und prüfte damit eine im Browser
 * unerreichbare Situation; einen Guard-Fehler, den die beiden echten
 * Fokustests nicht schon melden, erkennt er nicht.
 */
const LAB_FOKUS_VARIANTEN = [
  { id: 'liste', label: 'die Lab-Liste', element: 'Lab-Listeneintrag', selektor: '#labList .li' },
  { id: 'tab', label: 'einen Lab-Tab', element: 'Lab-Tab', selektor: '#labTabs .tab' },
];

/**
 * Fokussiert das erste Element der Variante und belegt, dass der Fokus in
 * #v-lab, aber ausserhalb von #labDetail liegt. Nur so unterscheidet der
 * Refresh-Test den schmalen Guard von einem breiten #v-lab-Guard.
 */
async function fokussiereLabAusserhalbDetail(page, variante) {
  const ziel = page.locator(variante.selektor).first();
  if (!(await ziel.count())) return [`Lab-Fokus-Prüfung ohne ${variante.element}`];
  // Nur sichtbare Knoten sind echte Fokusziele; ein ausgeblendeter Eintrag
  // liesse sich nicht fokussieren und dürfte keinen Test bestehen.
  const sichtbar = await ziel.evaluate(el => {
    if (el.closest('[hidden]')) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  });
  if (!sichtbar) return [`Lab-Fokus-Prüfung: ${variante.element} ist nicht sichtbar`];
  await ziel.focus();
  const stand = await page.evaluate(selektor => {
    const a = document.activeElement;
    const treffer = a?.closest?.(selektor);
    return {
      imZiel: Boolean(treffer),
      imDetail: Boolean(a?.closest?.('#labDetail')),
      tag: a ? a.tagName : '',
      text: treffer ? treffer.innerText.replace(/\s+/g, ' ').trim().slice(0, 60) : '',
    };
  }, variante.selektor);
  if (!stand.imZiel || stand.imDetail) {
    return [`Lab-Fokus-Prüfung konnte keinen ${variante.element} ausserhalb von #labDetail fokussieren (${stand.tag}, «${stand.text}»)`];
  }
  return [];
}

/**
 * Fokus, Scrollposition und Auswahl der Lab-Liste vor und nach dem Refresh.
 * `scrollen` setzt vorher eine mittlere Position; ist die Liste kürzer als ihr
 * Rahmen, bleibt es bei 0. Nach dem Neuaufbau müssen alle drei Werte gleich
 * sein, sonst springt die Liste beim Ablesen zurück oder verliert den Fokus.
 */
async function erhebeLabListenzustand(page, selektor, scrollen = false) {
  return page.evaluate(([sel, sc]) => {
    const liste = document.querySelector('#labList');
    if (liste && sc) liste.scrollTop = Math.min(120, Math.max(0, liste.scrollHeight - liste.clientHeight));
    const a = document.activeElement;
    const ziel = a?.closest?.(sel) || null;
    const sichtbar = el => {
      if (!el || el.closest('[hidden]')) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
    };
    return {
      fokus: ziel ? (ziel.dataset.k ?? ziel.textContent.trim()) : null,
      fokusSichtbar: sichtbar(ziel),
      scroll: liste ? liste.scrollTop : null,
      auswahl: liste?.querySelector('.li.on')?.dataset.k ?? null,
    };
  }, [selektor, scrollen]);
}

async function pruefeLabFokusAutoRefresh(browser, url, breite, variante, bilderPfad = null) {
  const befunde = [];
  const seitenfehler = [];
  const context = await browser.newContext({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on('pageerror', err => seitenfehler.push(String(err)));
  // Trace nur bei Befunden sichern; er hält Fokusverlauf und DOM-Snapshots fest.
  await context.tracing.start({ screenshots: true, snapshots: true });
  try {
    // Die Playwright-Uhr wird vor dem Laden installiert. Damit lässt sich der
    // echte 8-Sekunden-Interval-Callback gezielt auslösen, ohne auf den Takt
    // zu warten oder zwischen Fokus und Refresh ein Zeitfenster zu öffnen.
    await page.clock.install();
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.locator('.nav[data-v="lab"]').click();
    // Sichtbarkeit als eigene Bedingung melden; ein Timeout allein wäre nicht
    // von einem fehlenden Element zu unterscheiden.
    const listeSichtbar = await page.locator('#labList .li').first()
      .waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
    if (!listeSichtbar) return [`Lab-Fokus-Prüfung (${variante.label}): die Lab-Liste ist nicht sichtbar (versteckte Knoten zählen nicht)`];
    if (!await waehleKurvenKandidat(page)) return [`Lab-Fokus-Prüfung (${variante.label}) ohne Kapitalkurve`];

    const fokusBefunde = await fokussiereLabAusserhalbDetail(page, variante);
    if (fokusBefunde.length) return [...befunde, ...fokusBefunde];
    const zustandVorher = await erhebeLabListenzustand(page, variante.selektor, true);

    const marker = `refresh-${variante.id}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const timeout = Symbol('lab-fokus-refresh-timeout');
    let meldeRefresh;
    let routeFehler = null;
    const antwortVersprechen = new Promise(resolve => { meldeRefresh = resolve; });
    const handler = async route => {
      try {
        const antwort = await route.fetch();
        if (!antwort.ok()) {
          await route.fulfill({ response: antwort });
          meldeRefresh({ status: antwort.status(), ok: false });
          return;
        }
        const daten = await antwort.json();
        if (!daten || typeof daten !== 'object' || Array.isArray(daten)) {
          throw new Error('Bericht ist kein JSON-Objekt');
        }
        if (!Array.isArray(daten.validierungen) || daten.validierungen.length === 0) {
          throw new Error('Bericht enthält keine Validierungen');
        }
        for (const kandidat of daten.validierungen) {
          if (kandidat && typeof kandidat === 'object') kandidat.symbol = marker;
        }
        daten.datenquelle = marker;
        await route.fulfill({ response: antwort, json: daten });
        meldeRefresh({ status: antwort.status(), ok: true });
      } catch (fehler) {
        routeFehler = fehler instanceof Error ? fehler.message : String(fehler);
        await route.abort().catch(() => {});
        meldeRefresh(null);
      }
    };
    await page.route('**/api/report', handler);
    await page.clock.runFor(8000);
    let timeoutId;
    const timeoutVersprechen = new Promise(resolve => {
      timeoutId = setTimeout(() => resolve(timeout), 5000);
    });
    const antwort = await Promise.race([antwortVersprechen, timeoutVersprechen]);
    clearTimeout(timeoutId);
    if (antwort === timeout) {
      befunde.push(`Lab-Fokus-Auto-Refresh (${variante.label}) lieferte nach dem Vorspulen keine Antwort`);
    } else if (!antwort) {
      befunde.push(`Lab-Fokus-Auto-Refresh-Antwort (${variante.label}) konnte nicht geprüft werden${routeFehler ? ` (${routeFehler})` : ''}`);
    } else if (!antwort.ok || antwort.status !== 200) {
      befunde.push(`Lab-Fokus-Auto-Refresh (${variante.label}) antwortet mit HTTP ${antwort.status}`);
    } else {
      await page.waitForFunction(
        m => (document.querySelector('#labList')?.textContent || '').includes(m),
        marker, { timeout: 3000 },
      ).catch(() => {});
      // Marker nur an sichtbaren Knoten werten: textContent allein zählt auch
      // ausgeblendete Einträge und würde einen stummen Render verdecken.
      const beleg = await page.evaluate(m => {
        const sichtbar = el => {
          if (!el || el.closest('[hidden]')) return false;
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const liste = [...document.querySelectorAll('#labList .li')]
          .some(li => sichtbar(li) && (li.textContent || '').includes(m));
        const banner = document.querySelector('#banner');
        return { liste, banner: sichtbar(banner) && (banner.textContent || '').includes(m) };
      }, marker);
      if (!beleg.banner) befunde.push(`Lab-Fokus-Auto-Refresh-Daten (${variante.label}) wurden nicht sichtbar verarbeitet`);
      if (!beleg.liste) {
        befunde.push(`Auto-Refresh hält die Lab-Liste bei Fokus auf ${variante.label} an (breiter #v-lab-Guard?) oder der Marker steht nur in versteckten Knoten`);
      } else {
        // Der Neuaufbau ersetzt die Listeneinträge; Fokus, Scrollposition und
        // Auswahl müssen ihn überstehen.
        const zustandNachher = await erhebeLabListenzustand(page, variante.selektor);
        if (zustandNachher.fokus !== zustandVorher.fokus) {
          befunde.push(`Auto-Refresh verliert den Fokus auf ${variante.label} (${zustandVorher.fokus === null ? 'kein Fokus' : `«${zustandVorher.fokus}»`} → ${zustandNachher.fokus === null ? 'kein Fokus' : `«${zustandNachher.fokus}»`})`);
        }
        if (zustandNachher.scroll !== zustandVorher.scroll) {
          befunde.push(`Auto-Refresh setzt die Scrollposition der Lab-Liste zurück (${zustandVorher.scroll} → ${zustandNachher.scroll})`);
        }
        if (zustandNachher.auswahl !== zustandVorher.auswahl) {
          befunde.push(`Auto-Refresh verliert die Auswahl in der Lab-Liste (${zustandVorher.auswahl} → ${zustandNachher.auswahl})`);
        }
        if (zustandNachher.fokusSichtbar !== true) {
          befunde.push(`Auto-Refresh lässt den Fokus auf ${variante.label} in einem unsichtbaren Knoten zurück`);
        }
      }
    }
    await page.unroute('**/api/report', handler).catch(() => {});
  } catch (fehler) {
    befunde.push(`Lab-Fokus-Prüfung (${variante.label}) fehlgeschlagen: ${fehler instanceof Error ? fehler.message : fehler}`);
  } finally {
    if (seitenfehler.length) befunde.push(`Lab-Fokus-Seitenfehler (${variante.label}): ${seitenfehler.join('; ')}`);
    await schreibeFehlerbeleg(context, page, befunde, bilderPfad, `lab-fokus-${breite}px-${variante.id}`).catch(() => {});
    await context.close();
  }
  return befunde;
}

/**
 * Legt bei Befunden einen Screenshot und einen Playwright-Trace ab, damit sich
 * Fokusverlust und versteckte Marker nachvollziehen lassen. Ohne Befund wird
 * der Trace verworfen und nichts geschrieben.
 */
async function schreibeFehlerbeleg(context, page, befunde, bilderPfad, name) {
  if (!befunde.length || !bilderPfad) {
    await context.tracing.stop().catch(() => {});
    return;
  }
  mkdirSync(bilderPfad, { recursive: true });
  const basis = join(bilderPfad, `text250-${name}`);
  await page.screenshot({ path: `${basis}.png`, fullPage: true }).catch(() => {});
  await context.tracing.stop({ path: `${basis}-trace.zip` }).catch(() => {});
  console.log(`Belege (${name}): ${basis}.png, ${basis}-trace.zip`);
}

/**
 * Prüft die Guard-Regel direkt statt nur über den Fokusverlauf: Liste, Tab und
 * body dürfen den Render nicht blockieren, das Lab-Detail samt Inhalt schon.
 * Der ausgeblendete Fall wird über den echten DOM-Zustand (#v-lab hidden) und
 * einen explizit übergebenen Knoten geprüft; document.activeElement bleibt
 * unangetastet. Zusätzlich muss die Regel am echten Fokus dasselbe liefern.
 */
async function pruefeLabGuardLogik(browser, url, breite, bilderPfad = null) {
  const befunde = [];
  const context = await browser.newContext({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on('pageerror', err => befunde.push(`Lab-Guard-Seitenfehler: ${err}`));
  await context.tracing.start({ screenshots: true, snapshots: true });
  try {
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.locator('.nav[data-v="lab"]').click();
    const listeSichtbar = await page.locator('#labList .li').first()
      .waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
    if (!listeSichtbar) {
      befunde.push('Lab-Guard-Prüfung: die Lab-Liste ist nicht sichtbar (versteckte Knoten zählen nicht)');
      return befunde;
    }
    if (!await waehleKurvenKandidat(page)) befunde.push('Lab-Guard-Prüfung ohne Kapitalkurve');

    const stand = await page.evaluate(() => {
      const guard = window.pausiertRenderWegenLabDetail;
      if (typeof guard !== 'function') return { guard: false };
      const teile = {
        liste: document.querySelector('#labList .li'),
        tab: document.querySelector('#labTabs .tab'),
        detail: document.querySelector('#labDetail'),
        vLab: document.querySelector('#v-lab'),
      };
      const fehlend = Object.entries(teile).filter(([, el]) => !el).map(([name]) => name);
      if (fehlend.length) return { guard: true, fehlend };
      const { liste, tab, detail, vLab } = teile;
      const innen = detail.firstElementChild || detail;
      const ergebnis = {
        guard: true,
        direkt: {
          liste: guard(liste),
          tab: guard(tab),
          detail: guard(detail),
          innen: guard(innen),
          body: guard(document.body),
          leer: guard(null),
        },
      };
      // Ausgeblendetes Lab: echter DOM-Zustand, kein activeElement-Eingriff.
      const vorherHidden = vLab.hidden;
      vLab.hidden = true;
      ergebnis.versteckt = { detail: guard(detail), innen: guard(innen) };
      vLab.hidden = vorherHidden;
      // Default-Parameter am echten Fokus prüfen.
      liste.focus();
      ergebnis.aktivListe = guard();
      const hatteTabindex = detail.hasAttribute('tabindex');
      detail.tabIndex = -1;
      detail.focus();
      ergebnis.aktivDetail = guard();
      if (!hatteTabindex) detail.removeAttribute('tabindex');
      liste.focus();
      return ergebnis;
    });

    if (!stand.guard) {
      befunde.push('Guard-Funktion pausiertRenderWegenLabDetail fehlt');
    } else if (stand.fehlend) {
      befunde.push(`Lab-Guard-Prüfung ohne Knoten: ${stand.fehlend.join(', ')}`);
    } else {
      for (const [name, wert] of Object.entries(stand.direkt)) {
        const erwartet = name === 'detail' || name === 'innen';
        if (wert !== erwartet) befunde.push(`Guard(${name}) liefert ${wert}, erwartet ${erwartet}`);
      }
      for (const [name, wert] of Object.entries(stand.versteckt)) {
        if (wert !== false) befunde.push(`Guard(${name}) blockiert bei ausgeblendetem Lab (${wert}), erwartet false`);
      }
      if (stand.aktivListe !== false) befunde.push('Guard blockiert bei Fokus auf der Lab-Liste');
      if (stand.aktivDetail !== true) befunde.push('Guard blockiert nicht bei Fokus im sichtbaren Lab-Detail');
    }
  } catch (fehler) {
    befunde.push(`Lab-Guard-Prüfung fehlgeschlagen: ${fehler instanceof Error ? fehler.message : fehler}`);
  } finally {
    await schreibeFehlerbeleg(context, page, befunde, bilderPfad, `lab-guard-${breite}px`).catch(() => {});
    await context.close();
  }
  return befunde;
}

/**
 * Pausiert der Ansichts-Render wegen Fokus im sichtbaren Lab-Detail, müssen
 * neue Daten sichtbar und für Screenreader angekündigt werden (#labNeu als
 * höfliche Live-Region). Beim Verlassen des Details wird sofort gezeichnet,
 * ohne den nächsten Acht-Sekunden-Takt abzuwarten.
 */
async function pruefeLabPauseHinweis(browser, url, breite, bilderPfad = null) {
  const befunde = [];
  const context = await browser.newContext({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  page.on('pageerror', err => befunde.push(`Lab-Pause-Seitenfehler: ${err}`));
  await context.tracing.start({ screenshots: true, snapshots: true });
  try {
    await page.clock.install();
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.locator('.nav[data-v="lab"]').click();
    const listeSichtbar = await page.locator('#labList .li').first()
      .waitFor({ state: 'visible', timeout: 5000 }).then(() => true).catch(() => false);
    if (!listeSichtbar) {
      befunde.push('Lab-Pause-Prüfung: die Lab-Liste ist nicht sichtbar (versteckte Knoten zählen nicht)');
      return befunde;
    }
    await page.locator('#labDetail .card').first().waitFor({ state: 'visible', timeout: 5000 });

    const hinweisVorher = await page.evaluate(() => {
      const el = document.querySelector('#labNeu');
      if (!el) return { vorhanden: false };
      return {
        vorhanden: true,
        hidden: el.hidden,
        text: el.textContent.trim(),
        role: el.getAttribute('role'),
        live: el.getAttribute('aria-live'),
      };
    });
    if (!hinweisVorher.vorhanden) return [...befunde, 'Lab-Pause-Prüfung ohne Statuselement #labNeu'];
    if (hinweisVorher.role !== 'status' || hinweisVorher.live !== 'polite') {
      befunde.push(`Status ist keine höfliche Live-Region (role=${hinweisVorher.role}, aria-live=${hinweisVorher.live})`);
    }
    if (!hinweisVorher.hidden || hinweisVorher.text) befunde.push('Status ist ohne ausstehende Daten bereits sichtbar');

    const fokusDetail = await page.evaluate(() => {
      const detail = document.querySelector('#labDetail');
      if (!detail) return false;
      detail.tabIndex = -1;
      detail.focus();
      return document.activeElement === detail;
    });
    if (!fokusDetail) return [...befunde, 'Fokus liess sich nicht ins sichtbare Lab-Detail setzen'];

    const marker = `pause-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const handler = async route => {
      try {
        const antwort = await route.fetch();
        const daten = await antwort.json();
        if (!daten || typeof daten !== 'object' || !Array.isArray(daten.validierungen)) {
          throw new Error('Bericht enthält keine Validierungen');
        }
        for (const kandidat of daten.validierungen) {
          if (kandidat && typeof kandidat === 'object') kandidat.symbol = marker;
        }
        daten.datenquelle = marker;
        await route.fulfill({ response: antwort, json: daten });
      } catch {
        await route.abort().catch(() => {});
      }
    };
    await page.route('**/api/report', handler);
    await page.clock.runFor(8000);
    await page.waitForFunction(
      m => (document.querySelector('#banner')?.textContent || '').includes(m),
      marker, { timeout: 3000 },
    ).catch(() => {});
    await page.waitForTimeout(200);

    const leseStand = m => page.evaluate(stand => {
      const sichtbar = el => {
        if (!el || el.closest('[hidden]')) return false;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
      };
      const el = document.querySelector('#labNeu');
      return {
        banner: (document.querySelector('#banner')?.textContent || '').includes(stand),
        listeMarker: [...document.querySelectorAll('#labList .li')]
          .some(li => sichtbar(li) && (li.textContent || '').includes(stand)),
        hinweisSichtbar: sichtbar(el) && (el?.textContent || '').includes('Neue Daten'),
        hinweisText: (el?.textContent || '').trim(),
        fokusInListe: Boolean(document.activeElement?.closest?.('#labList .li')),
        fokusImDetail: Boolean(document.activeElement?.closest?.('#labDetail')),
      };
    }, m);
    const pausiert = await leseStand(marker);
    if (!pausiert.banner) befunde.push('Pausierter Render: neue Daten wurden nicht übernommen');
    if (pausiert.listeMarker) befunde.push('Pausierter Render: die Lab-Liste wurde trotz Fokus im Detail neu gezeichnet');
    if (!pausiert.hinweisSichtbar) befunde.push(`Pausierter Render: kein sichtbarer Status «neue Daten» (${pausiert.hinweisText || 'leer'})`);
    if (!pausiert.fokusImDetail) befunde.push('Fokus lag vor dem Verlassen nicht mehr im Detail');

    // Verlassen des Details: sofortiges Neuzeichnen ohne Zeitsprung.
    await page.locator('#labList .li').first().focus();
    await page.waitForTimeout(300);
    const danach = await leseStand(marker);
    if (!danach.listeMarker) befunde.push('Nach dem Verlassen des Details wurde nicht sofort neu gezeichnet');
    if (danach.hinweisSichtbar || danach.hinweisText) befunde.push('Status bleibt nach dem Neuzeichnen stehen');
    if (!danach.fokusInListe) befunde.push('Neuzeichnen nach dem Verlassen des Details verliert den Fokus');
  } catch (fehler) {
    befunde.push(`Lab-Pause-Prüfung fehlgeschlagen: ${fehler instanceof Error ? fehler.message : fehler}`);
  } finally {
    await schreibeFehlerbeleg(context, page, befunde, bilderPfad, `lab-pause-${breite}px`).catch(() => {});
    await context.close();
  }
  return befunde;
}

/**
 * Der Acht-Sekunden-Takt darf sich bei langsamen Antworten nicht überlappen,
 * im Hintergrundtab nicht laden und beim Zurückkehren sofort nachladen. Der
 * Takt läuft über die Playwright-Uhr; die Sichtbarkeit wird über document.hidden
 * und ein echtes visibilitychange-Event gesteuert.
 */
async function pruefeRefreshTakt(browser, url, breite) {
  const befunde = [];
  const page = await browser.newPage({ viewport: { width: breite, height: 900 }, deviceScaleFactor: 1 });
  page.on('pageerror', err => befunde.push(`Seitenfehler: ${err}`));
  let anfragen = 0;
  let halten = false;
  const offen = [];
  const freigeben = () => offen.splice(0).forEach(loesen => loesen());
  try {
    await page.clock.install();
    await page.route('**/api/report', async route => {
      anfragen++;
      try {
        const antwort = await route.fetch();
        if (halten) await new Promise(resolve => offen.push(resolve));
        await route.fulfill({ response: antwort });
      } catch {
        // Seite wird geschlossen oder die Route abgebrochen; kein Befund.
      }
    });
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    const start = anfragen;

    // 1. Single-flight: Die erste Antwort bleibt offen; zwei weitere Takte
    //    dürfen keinen zweiten Aufruf starten.
    halten = true;
    await page.clock.runFor(8000);
    await page.waitForTimeout(50);
    if (anfragen !== start + 1) befunde.push(`Takt startet keinen Aufruf (${anfragen - start} statt 1)`);
    await page.clock.runFor(16000);
    await page.waitForTimeout(50);
    if (anfragen !== start + 1) befunde.push(`Überlappender Refresh: ${anfragen - start} parallele Aufrufe`);

    // 2. Nach dem Auflösen lädt der nächste Takt wieder. Ab hier werden
    //    Antworten nicht mehr gehalten, damit der Takt deterministisch läuft;
    //    die Überlappungsfreiheit ist oben bereits belegt.
    halten = false;
    freigeben();
    await page.waitForTimeout(300);
    const nachAufloesen = anfragen;
    let taktAufrufe = 0;
    for (let i = 0; i < 3 && taktAufrufe === 0; i++) {
      await page.clock.runFor(8000);
      await page.waitForTimeout(150);
      taktAufrufe = anfragen - nachAufloesen;
    }
    if (taktAufrufe !== 1) befunde.push(`Takt lädt nach aufgelöster Antwort nicht weiter (${taktAufrufe} Aufrufe)`);
    freigeben();
    await page.waitForTimeout(300);

    // 3. Hintergrundtab: kein Aufruf; Zurückkehren lädt sofort nach.
    const versteckt = await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
      document.dispatchEvent(new Event('visibilitychange'));
      return document.hidden;
    });
    if (!versteckt) befunde.push('Sichtbarkeit liess sich nicht auf «versteckt» setzen');
    const vorHintergrund = anfragen;
    await page.clock.runFor(24000);
    await page.waitForTimeout(50);
    if (anfragen !== vorHintergrund) befunde.push(`Refresh läuft im Hintergrundtab weiter (${anfragen - vorHintergrund} Aufrufe)`);
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForTimeout(50);
    if (anfragen !== vorHintergrund + 1) befunde.push(`Beim Zurückkehren fehlt das sofortige Nachladen (${anfragen - vorHintergrund} Aufrufe)`);
  } catch (fehler) {
    befunde.push(`Takt-Prüfung fehlgeschlagen: ${fehler instanceof Error ? fehler.message : fehler}`);
  } finally {
    freigeben();
    await page.waitForTimeout(100).catch(() => {});
    await page.unroute('**/api/report').catch(() => {});
    await page.close();
  }
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
 * ein fehlender oder doppelter Buchstabe sowie ein Agent in mehreren Clustern
 * müssen auffallen.
 */
async function pruefeSchiffCluster(page) {
  await page.waitForFunction(() => {
    const tag = document.querySelector('#companyTag')?.textContent || '';
    return document.querySelectorAll('#shipWorld .px-dept').length > 0
      || /API-FEHLER|keine Daten/.test(tag);
  }, null, { timeout: 5000 }).catch(() => {});

  const stand = await page.evaluate(() => {
    const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
    const gruppen = cluster.map(el => ({
      code: (el.querySelector('.px-dept-head b')?.textContent || '').trim(),
      agenten: el.querySelectorAll('.px-room[data-agent]').length,
      ids: [...el.querySelectorAll('.px-room[data-agent]')].map(raum => raum.dataset.agent).filter(Boolean),
    })).filter(g => g.code);
    return {
      anzahl: cluster.length,
      sichtbar: cluster.filter(el => el.getClientRects().length > 0).length,
      codes: gruppen.map(g => g.code),
      agenten: Object.fromEntries(gruppen.map(g => [g.code, g.agenten])),
      ids: gruppen.flatMap(g => g.ids),
      doppeltImCluster: gruppen.flatMap(g => {
        const gesehen = new Set();
        return g.ids.filter(id => {
          if (gesehen.has(id)) return true;
          gesehen.add(id);
          return false;
        }).map(id => ({ id, code: g.code }));
      }),
    };
  });

  const erwartet = { A:10, B:10, C:10, D:10, E:10, F:10, G:10, H:10, I:10, J:10, S:3 };
  const codes = Object.keys(erwartet);
  const erwarteteAgenten = Object.values(erwartet).reduce((summe, anzahl) => summe + anzahl, 0);
  const befunde = [];
  if (stand.doppeltImCluster.length) {
    const beschreibung = stand.doppeltImCluster.map(e => `${e.id} (${e.code})`).join(', ');
    befunde.push(`Raumschiff: Agent ${beschreibung} erscheint doppelt im selben Cluster`);
  }
  if (stand.ids.length !== erwarteteAgenten) {
    befunde.push(`Raumschiff: ${stand.ids.length} statt ${erwarteteAgenten} Agenten insgesamt`);
  }
  const eindeutigeIds = new Set(stand.ids).size;
  if (eindeutigeIds !== erwarteteAgenten) {
    befunde.push(`Raumschiff: ${eindeutigeIds} statt ${erwarteteAgenten} eindeutige Agenten-IDs`);
  }
  if (stand.anzahl !== codes.length) befunde.push(`Raumschiff: ${stand.anzahl} statt ${codes.length} Abteilungscluster`);
  if (stand.sichtbar !== codes.length) befunde.push(`Raumschiff: ${stand.sichtbar} statt ${codes.length} sichtbare Abteilungscluster`);
  const fehlend = codes.filter(code => !stand.codes.includes(code));
  if (fehlend.length) befunde.push(`Raumschiff: Abteilung ${fehlend.join(', ')} fehlt`);
  const unbekannt = stand.codes.filter(code => !codes.includes(code));
  if (unbekannt.length) befunde.push(`Raumschiff: unbekannte Abteilung ${unbekannt.join(', ')}`);
  const doppelteImCluster = new Set(stand.doppeltImCluster.map(e => e.id));
  const mehrfach = [...new Set(stand.ids.filter((id, i) => stand.ids.indexOf(id) !== i))]
    .filter(id => !doppelteImCluster.has(id));
  if (mehrfach.length) befunde.push(`Raumschiff: Agent ${mehrfach.join(', ')} erscheint in mehreren Clustern`);
  for (const [code, soll] of Object.entries(erwartet)) {
    if (!(code in stand.agenten)) continue;
    if (stand.agenten[code] !== soll) {
      befunde.push(`Raumschiff: Abteilung ${code} hat ${stand.agenten[code]} statt ${soll} Agenten`);
    }
  }
  return befunde;
}

/**
 * Misst die geöffnete Ops-Abteilungslegende auf horizontale Überläufe.
 * Geprüft werden der Legendenkasten selbst und die Positionen der
 * Abteilungseinträge relativ zu seinem Rahmen.
 */
async function pruefeLegendeUeberlauf(page) {
  const stand = await page.evaluate(() => {
    const el = document.querySelector('#shipLegend');
    if (!el || !el.open || !el.getClientRects().length) return null;
    const rahmen = el.getBoundingClientRect();
    const eintraege = [...el.querySelectorAll('[data-dept]')].map(b => {
      const r = b.getBoundingClientRect();
      return { code: (b.dataset.dept || '').trim(), links: r.left, rechts: r.right, breite: r.width };
    });
    return {
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      ausserhalb: eintraege.filter(e => e.breite > 0 && (e.links < rahmen.left - 1 || e.rechts > rahmen.right + 1)),
      rahmen: { links: rahmen.left, rechts: rahmen.right },
    };
  });
  if (!stand) return [];
  const befunde = [];
  if (stand.scrollWidth > stand.clientWidth + 1) {
    befunde.push(`Raumschiff: geöffnete Ops-Abteilungslegende läuft horizontal über (${stand.scrollWidth}>${stand.clientWidth})`);
  }
  if (stand.ausserhalb.length) {
    const codes = stand.ausserhalb.map(e => e.code || '?').join(', ');
    befunde.push(`Raumschiff: geöffnete Ops-Abteilungslegende hat Einträge ausserhalb des Rahmens (${codes})`);
  }
  return befunde;
}

/**
 * Prüft die Ops-Abteilungslegende im Schiff: elf Einträge, kompakter Kopf,
 * auf schmalen Seed-Breiten eingeklappt sowie per Tastatur aufklappbar und
 * ohne horizontale Überläufe.
 */
async function pruefeOpsLegende(page) {
  const stand = await page.evaluate(() => {
    const el = document.querySelector('#shipLegend');
    if (!el) return null;
    const kopf = el.querySelector('summary');
    const depts = [...el.querySelectorAll('[data-dept]')];
    return {
      sichtbar: !el.hidden && el.getClientRects().length > 0,
      schmal: window.matchMedia('(max-width:760px)').matches,
      offen: el.open,
      kopf: (kopf?.innerText || '').replace(/\s+/g, ' ').trim(),
      anzahl: depts.length,
      codes: depts.map(b => (b.querySelector('b')?.textContent || '').trim().split('·')[0].trim()),
    };
  });
  if (!stand) return ['Raumschiff: Ops-Abteilungslegende fehlt'];

  const befunde = [];
  if (!stand.sichtbar) {
    befunde.push('Raumschiff: Ops-Abteilungslegende ist nicht sichtbar');
    return befunde;
  }
  const erwartet = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'S'];
  if (stand.anzahl !== erwartet.length) {
    befunde.push(`Raumschiff: Ops-Abteilungslegende zeigt ${stand.anzahl} statt ${erwartet.length} Abteilungen`);
  }
  const fehlend = erwartet.filter(code => !stand.codes.includes(code));
  const unbekannt = stand.codes.filter(code => !erwartet.includes(code));
  if (fehlend.length) befunde.push(`Raumschiff: Ops-Abteilungslegende ohne Abteilung ${fehlend.join(', ')}`);
  if (unbekannt.length) befunde.push(`Raumschiff: Ops-Abteilungslegende mit unbekannter Abteilung ${unbekannt.join(', ')}`);
  if (!/SEKTOREN/.test(stand.kopf)) befunde.push('Raumschiff: Ops-Abteilungslegende ohne «SEKTOREN» im Kopf');
  if (!/FILTER/.test(stand.kopf)) befunde.push('Raumschiff: Ops-Abteilungslegende ohne «FILTER» im Kopf');
  if (!/11 ABTEILUNGEN/.test(stand.kopf)) befunde.push(`Raumschiff: Ops-Abteilungslegende ohne «11 ABTEILUNGEN» im Kopf («${stand.kopf}»)`);

  if (!stand.schmal) {
    if (!stand.offen) befunde.push('Raumschiff: Ops-Abteilungslegende ist auf breiten Bildschirmen eingeklappt');
    if (stand.offen) befunde.push(...await pruefeLegendeUeberlauf(page));
    return befunde;
  }
  if (stand.offen) befunde.push('Raumschiff: Ops-Abteilungslegende startet auf schmalen Bildschirmen offen');

  const kopf = page.locator('#shipLegend > summary');
  if (!(await kopf.count())) {
    befunde.push('Raumschiff: Ops-Abteilungslegende hat keinen aufklappbaren Kopf');
    return befunde;
  }
  await kopf.focus();
  await page.keyboard.press('Enter');
  await page.waitForTimeout(150);
  const auf = await page.evaluate(() => {
    const el = document.querySelector('#shipLegend');
    const depts = [...el.querySelectorAll('[data-dept]')];
    return {
      offen: el.open,
      sichtbar: depts.filter(b => b.getClientRects().length > 0).length,
    };
  });
  if (!auf.offen) befunde.push('Raumschiff: Ops-Abteilungslegende lässt sich per Tastatur nicht aufklappen');
  if (auf.sichtbar !== erwartet.length) {
    befunde.push(`Raumschiff: aufgeklappte Ops-Abteilungslegende zeigt ${auf.sichtbar} statt ${erwartet.length} Abteilungen`);
  }
  if (auf.offen) {
    befunde.push(...await pruefeLegendeUeberlauf(page));
    await page.keyboard.press('Enter');
    await page.waitForTimeout(100);
    const zu = await page.evaluate(() => document.querySelector('#shipLegend').open);
    if (zu) befunde.push('Raumschiff: Ops-Abteilungslegende lässt sich per Tastatur nicht wieder einklappen');
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
          const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
          if (cluster.length !== 11) throw new Error('Schiffscluster nicht vollständig gefunden');
          const s = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'S');
          if (!s) throw new Error('Schiffscluster S nicht gefunden');
          s.remove();
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Abteilung leer',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
          const a = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
          if (!a) throw new Error('Schiffscluster A nicht gefunden');
          const raeume = [...a.querySelectorAll('.px-room[data-agent]')];
          if (!raeume.length) throw new Error('Agentenräume in Cluster A nicht gefunden');
          raeume.forEach(el => el.remove());
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Agent fehlt',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
          const a = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
          if (!a) throw new Error('Schiffscluster A nicht gefunden');
          const raeume = [...a.querySelectorAll('.px-room[data-agent]')];
          if (raeume.length !== 10) throw new Error(`Schiffscluster A hat ${raeume.length} statt 10 Agentenräume`);
          raeume[0].remove();
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Agent zusätzlich',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
          const a = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
          const b = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'B');
          if (!a || !b) throw new Error('Schiffscluster A und B nicht gefunden');
          const raum = a.querySelector('.px-room[data-agent]');
          const ziel = b.querySelector('.px-floor');
          if (!raum || !ziel) throw new Error('Agentenraum oder Zielcluster nicht gefunden');
          ziel.appendChild(raum.cloneNode(true));
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Agent doppelt',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
          const a = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
          const b = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'B');
          if (!a || !b) throw new Error('Schiffscluster A und B nicht gefunden');
          const raumA = a.querySelector('.px-room[data-agent]');
          const raumB = b.querySelector('.px-room[data-agent]');
          if (!raumA || !raumB) throw new Error('Agentenräume in A oder B nicht gefunden');
          const id = raumA.dataset.agent;
          if (!id || raumB.dataset.agent === id) throw new Error('Keine unterschiedlichen Agenten-IDs gefunden');
          raumB.dataset.agent = id;
          const raeume = document.querySelectorAll('#shipWorld .px-room[data-agent]');
          if (raeume.length !== 103) throw new Error(`Doppelte ID hat die Agentenzahl auf ${raeume.length} verändert`);
        }),
      },
      {
        ansicht: 'ship',
        name: 'Raumschiff-Agent doppelt im selben Cluster',
        mutieren: () => page.evaluate(() => {
          const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
          const a = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
          if (!a) throw new Error('Schiffscluster A nicht gefunden');
          const raeume = [...a.querySelectorAll('.px-room[data-agent]')];
          if (raeume.length < 2) throw new Error(`Schiffscluster A hat ${raeume.length} statt mindestens 2 Agentenräume`);
          const id = raeume[0].dataset.agent;
          if (!id || raeume[1].dataset.agent === id) throw new Error('Keine unterschiedlichen Agenten-IDs im selben Cluster gefunden');
          raeume[1].dataset.agent = id;
          const alle = document.querySelectorAll('#shipWorld .px-room[data-agent]');
          if (alle.length !== 103) throw new Error(`Doppelte ID im selben Cluster hat die Agentenzahl auf ${alle.length} verändert`);
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
      // Beide Claim-Fälle injizieren zuerst dieselben Testdaten. So wird
      // jeweils genau ein fehlendes Detail geprüft, nicht ein gemeinsamer Fehler.
      {
        ansicht: 'spider',
        name: 'Widerspruchsgrund fehlt',
        vorbereiten: () => page.evaluate(daten => window.zeichneBewertung(daten), CLAIM_TESTDATEN),
        pruefen: () => pruefeClaimWiderspruchsdetails(page),
        mutieren: () => page.evaluate(() => {
          const el = document.querySelector('#bewertungClaims .claimWiderspruchGrund');
          if (!el) throw new Error('Widerspruchsgrund nicht gefunden');
          el.remove();
        }),
      },
      {
        ansicht: 'spider',
        name: 'Widerspruchssicherheit fehlt',
        vorbereiten: () => page.evaluate(daten => window.zeichneBewertung(daten), CLAIM_TESTDATEN),
        pruefen: () => pruefeClaimWiderspruchsdetails(page),
        mutieren: () => page.evaluate(() => {
          const el = document.querySelector('#bewertungClaims .claimWiderspruchSicherheit');
          if (!el) throw new Error('Widerspruchssicherheit nicht gefunden');
          el.remove();
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
      if (fall.vorbereiten) await fall.vorbereiten();
      const pruefe = fall.pruefen || (() => pruefeInhalte(page, fall.ansicht));
      const sauber = await pruefe();
      if (!sauber || sauber.length) {
        throw new Error(`${fallName}: sauberer Zustand meldet bereits Befunde: ${(sauber || []).join('; ')}`);
      }

      await fall.mutieren();
      const befund = await pruefe();
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

function schiffsclusterBildName(breite, nummer, meldung, praefix = '') {
  const detail = meldung
    .replace(/^\d+px\/[^:]+:\s*/, '')
    .replace(/^Raumschiff:\s*/, '');
  return `${praefix}${breite}px-ship-cluster-${String(nummer).padStart(2, '0')}-${artefaktSlug(detail) || 'befund'}.png`;
}


function befundTextPfad(opt) {
  const praefix = opt.bildPraefix ? `${opt.bildPraefix}-` : '';
  return join(opt.bilder, `${praefix}text250-befunde.txt`);
}

async function schreibeDiagnose(page, opt, breite, ansicht, neue) {
  if (!opt.bilder || !neue.length) return { bilder: [], html: null };
  const praefix = opt.bildPraefix ? `${opt.bildPraefix}-` : '';
  const html = join(opt.bilder, `${praefix}${breite}px-${ansicht}.html`);
  writeFileSync(html, await page.content());
  console.log(`HTML: ${html}`);

  const bilder = [];
  const clusterFehler = ansicht === 'ship'
    ? neue.filter(text => /\/ship:\s*Raumschiff:/.test(text))
    : [];
  if (clusterFehler.length) {
    for (const [index, meldung] of clusterFehler.entries()) {
      const datei = join(opt.bilder, schiffsclusterBildName(breite, index + 1, meldung, praefix));
      if (bilder.includes(datei)) throw new Error(`Doppelter Screenshot-Name: ${datei}`);
      await page.screenshot({ path: datei, fullPage: true });
      bilder.push(datei);
      console.log(`Screenshot: ${datei}`);
    }
    const weitere = neue.filter(text => !clusterFehler.includes(text));
    if (weitere.length) {
      const datei = join(opt.bilder,
        `${praefix}${breite}px-ship-layout-${artefaktSlug(weitere[0]) || 'befund'}.png`);
      await page.screenshot({ path: datei, fullPage: true });
      bilder.push(datei);
      console.log(`Screenshot: ${datei}`);
    }
  } else {
    const datei = join(opt.bilder, `${praefix}${breite}px-${ansicht}.png`);
    await page.screenshot({ path: datei, fullPage: true });
    bilder.push(datei);
    console.log(`Screenshot: ${datei}`);
  }
  const befundDatei = befundTextPfad(opt);
  const kopf = existsSync(befundDatei) && statSync(befundDatei).size > 0
    ? ''
    : `# Text250-Befunde\n\nURL: ${page.url()}\n\n`;
  const eintrag = [
    `## ${breite}px / ${ansicht}`,
    `Zeit: ${new Date().toISOString()}`,
    `Befunde: ${neue.length}`,
    ...neue.map((text, index) => `${index + 1}. ${text}`),
    `HTML: ${html}`,
    `Screenshots: ${bilder.length ? bilder.join(', ') : 'keine'}`,
    '',
    '',
  ].join('\n');
  appendFileSync(befundDatei, kopf + eintrag);
  console.log(`Befunde: ${befundDatei}`);
  return { bilder, html };
}

async function pruefeScreenshotSelbsttest(url, bilderPfad, bildPraefix = '') {
  if (!bilderPfad) throw new Error('--selbsttest-cluster benötigt --bilder <verzeichnis>');
  mkdirSync(bilderPfad, { recursive: true });
  writeFileSync(befundTextPfad({ bilder: bilderPfad, bildPraefix }), '');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 360, height: 900 }, deviceScaleFactor: 1 });
    await page.goto(`${url}/?v=selbsttest-cluster`, { waitUntil: 'domcontentloaded' });
    await page.locator('.nav[data-v="ship"]').click();
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 10000 },
    );
    await page.waitForFunction(() => document.querySelectorAll('#shipWorld .px-dept').length === 11,
      null, { timeout: 10000 });
    // Der erste Datenrender darf den absichtlich entfernten Cluster nicht
    // gleich wieder einsetzen; danach bleibt das DOM bis zum 8-s-Refresh stabil.
    await page.waitForTimeout(1000);
    await page.evaluate(() => {
      const cluster = [...document.querySelectorAll('#shipWorld .px-dept')];
      const s = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'S');
      const a = cluster.find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
      if (!s || !a) throw new Error('Schiffscluster S oder A nicht gefunden');
      s.remove();
      const raeume = [...a.querySelectorAll('.px-room[data-agent]')];
      if (raeume.length !== 10) throw new Error(`Schiffscluster A hat ${raeume.length} statt 10 Agentenräume`);
      raeume[0].remove();
    });
    const befunde = await pruefeSchiffCluster(page);
    const fehlend = befunde.find(text => text.includes('Abteilung S fehlt'));
    if (!fehlend) throw new Error(`Fehlender Cluster S wurde nicht gemeldet: ${befunde.join('; ')}`);
    if (befunde.length < 2) {
      throw new Error(`Mehrfachbefund wurde nicht erzeugt: ${befunde.join('; ')}`);
    }
    const neue = befunde.map(text => `360px/ship: ${text}`);
    const { bilder, html } = await schreibeDiagnose(page, { bilder: bilderPfad, bildPraefix }, 360, 'ship', neue);
    if (bilder.length !== neue.length) {
      throw new Error(`Nicht für jeden Befund ein Screenshot: ${neue.length} Befunde, ${bilder.length} Bilder`);
    }
    if (new Set(bilder).size !== bilder.length) {
      throw new Error(`Doppelte Screenshot-Namen: ${bilder.join(', ')}`);
    }
    const sBild = bilder.find(datei => datei.includes('abteilung-s-fehlt'));
    if (!sBild) {
      throw new Error(`Screenshot für fehlenden Cluster S fehlt: ${bilder.join(', ')}`);
    }
    for (const datei of bilder) {
      if (!existsSync(datei) || statSync(datei).size === 0) {
        throw new Error(`Screenshot ist leer oder fehlt: ${datei}`);
      }
    }
    if (!html || !existsSync(html) || statSync(html).size === 0) {
      throw new Error(`HTML-Diagnose ist leer oder fehlt: ${html}`);
    }
    const befundDatei = befundTextPfad({ bilder: bilderPfad, bildPraefix });
    if (!existsSync(befundDatei) || statSync(befundDatei).size === 0) {
      throw new Error(`Befunddatei ist leer oder fehlt: ${befundDatei}`);
    }
    const befundText = readFileSync(befundDatei, 'utf8');
    for (const erwartet of ['Abteilung S fehlt', '99 statt 103', 'Screenshots:']) {
      if (!befundText.includes(erwartet)) {
        throw new Error(`Befunddatei enthält ${erwartet} nicht: ${befundDatei}`);
      }
    }
    console.log(`Selbsttest OK: fehlender Schiffscluster S · ${bilder.length} gleichzeitige Cluster-Befunde · eindeutige Screenshotnamen · ${sBild} · ${befundDatei}`);
  } finally {
    await browser.close();
  }
}

async function pruefeAgentScreenshotSelbsttest(url, bilderPfad, bildPraefix = '') {
  if (!bilderPfad) throw new Error('--selbsttest-agent benötigt --bilder <verzeichnis>');
  mkdirSync(bilderPfad, { recursive: true });
  writeFileSync(befundTextPfad({ bilder: bilderPfad, bildPraefix }), '');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 360, height: 900 }, deviceScaleFactor: 1 });
    await page.goto(`${url}/?v=selbsttest-agent`, { waitUntil: 'domcontentloaded' });
    await page.locator('.nav[data-v="ship"]').click();
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 10000 },
    );
    await page.waitForFunction(() => document.querySelectorAll('#shipWorld .px-dept').length === 11,
      null, { timeout: 10000 });
    await page.waitForTimeout(1000);
    await page.evaluate(() => {
      const a = [...document.querySelectorAll('#shipWorld .px-dept')]
        .find(el => (el.querySelector('.px-dept-head b')?.textContent || '').trim() === 'A');
      if (!a) throw new Error('Schiffscluster A nicht gefunden');
      const raeume = [...a.querySelectorAll('.px-room[data-agent]')];
      if (raeume.length !== 10) throw new Error(`Schiffscluster A hat ${raeume.length} statt 10 Agentenräume`);
      raeume[0].remove();
    });
    const befunde = await pruefeSchiffCluster(page);
    const fehlend = befunde.find(text => text.includes('Abteilung A hat 9 statt 10 Agenten'));
    if (!fehlend) throw new Error(`Fehlender Agent in Cluster A wurde nicht gemeldet: ${befunde.join('; ')}`);
    const neue = [`360px/ship: ${fehlend}`];
    const { bilder, html } = await schreibeDiagnose(page, { bilder: bilderPfad, bildPraefix }, 360, 'ship', neue);
    const praefix = bildPraefix ? `${bildPraefix}-` : '';
    const erwartet = join(bilderPfad, `${praefix}360px-ship-cluster-01-abteilung-a-hat-9-statt-10-agenten.png`);
    if (!bilder.includes(erwartet)) {
      throw new Error(`Screenshotpfad fehlt: erwartet ${erwartet}, erhalten ${bilder.join(', ')}`);
    }
    if (!existsSync(erwartet) || statSync(erwartet).size === 0) {
      throw new Error(`Screenshot ist leer oder fehlt: ${erwartet}`);
    }
    if (!html || !existsSync(html) || statSync(html).size === 0) {
      throw new Error(`HTML-Diagnose ist leer oder fehlt: ${html}`);
    }
    const befundDatei = befundTextPfad({ bilder: bilderPfad, bildPraefix });
    if (!existsSync(befundDatei) || !readFileSync(befundDatei, 'utf8').includes('Abteilung A hat 9 statt 10 Agenten')) {
      throw new Error(`Befunddatei enthält den fehlenden Agenten nicht: ${befundDatei}`);
    }
    console.log(`Selbsttest OK: fehlender Agent in Cluster A · ${erwartet} · ${befundDatei}`);
  } finally {
    await browser.close();
  }
}

async function pruefeKopfzeile(browser, url) {
  const page = await browser.newPage({ viewport: { width: 1024, height: 900 }, deviceScaleFactor: 1 });
  const befunde = [];
  try {
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.waitForTimeout(250);
    const stand = await page.evaluate(() => {
      const top = document.querySelector('.top');
      const button = document.querySelector('#runBtn');
      const r = button.getBoundingClientRect();
      return {
        topScroll: top.scrollWidth,
        topClient: top.clientWidth,
        documentScroll: document.documentElement.scrollWidth,
        viewport: innerWidth,
        button: { links: r.left, rechts: r.right, oben: r.top, unten: r.bottom },
      };
    });
    if (stand.topScroll > stand.topClient + 1) {
      befunde.push(`Kopfzeile läuft horizontal über (${stand.topScroll}>${stand.topClient})`);
    }
    if (stand.documentScroll > stand.viewport + 1) {
      befunde.push(`Seite hat horizontalen Überlauf (${stand.documentScroll}>${stand.viewport})`);
    }
    const b = stand.button;
    if (b.links < 0 || b.rechts > stand.viewport || b.oben < 0 || b.unten > 900) {
      befunde.push(`«Lauf starten» ist nicht sichtbar (${Math.round(b.links)}–${Math.round(b.rechts)})`);
    }
  } finally {
    await page.close();
  }
  return befunde;
}

async function pruefeLegendeDesktop(browser, url) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const befunde = [];
  try {
    await page.goto(`${url}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(
      () => (document.querySelector('#cMode')?.textContent || '').trim().length > 2,
      null, { timeout: 15000 },
    );
    await page.locator('.nav[data-v="ship"]').click();
    await page.waitForFunction(
      () => document.querySelectorAll('#shipWorld .px-dept').length === 11
        && document.querySelector('#shipLegend')?.hidden === false,
      null, { timeout: 10000 },
    );
    await page.waitForTimeout(500);
    const stand = await page.evaluate(() => {
      const el = document.querySelector('#shipLegend');
      if (!el) return null;
      const side = document.querySelector('#shipSide');
      const rahmen = el.getBoundingClientRect();
      const seite = side?.getBoundingClientRect();
      return {
        sichtbar: el.getClientRects().length > 0,
        imPanel: !!seite && rahmen.left >= seite.left - 1 && rahmen.right <= seite.right + 1,
        seitenScroll: document.documentElement.scrollWidth,
        viewport: innerWidth,
      };
    });
    if (!stand) {
      befunde.push('Raumschiff: Ops-Abteilungslegende fehlt');
      return befunde;
    }
    if (!stand.sichtbar) befunde.push('Raumschiff: Ops-Abteilungslegende ist nicht sichtbar');
    if (!stand.imPanel) befunde.push('Raumschiff: Ops-Abteilungslegende steht nicht in der Ops-Konsole');
    if (stand.seitenScroll > stand.viewport + 1) {
      befunde.push(`Raumschiff: Seite hat horizontalen Überlauf (${stand.seitenScroll}>${stand.viewport})`);
    }
    befunde.push(...await pruefeOpsLegende(page));
  } finally {
    await page.close();
  }
  return befunde;
}

async function main() {
  const opt = argumente(process.argv.slice(2));
  const claimBreiten = [...new Set([...opt.breiten, 240])];
  const { validierungen } = await pruefeServer(opt.url);
  if (opt.selbsttestCluster) {
    await pruefeScreenshotSelbsttest(opt.url, opt.bilder, opt.bildPraefix);
    return;
  }
  if (opt.selbsttestAgent) {
    await pruefeAgentScreenshotSelbsttest(opt.url, opt.bilder, opt.bildPraefix);
    return;
  }
  if (opt.negativtest) {
    await pruefeNegativtest(opt.url);
    return;
  }
  console.log(`250-%-Prüflauf: ${opt.ansichten.length} Ansichten × ${opt.breiten.length} Breiten · ${validierungen} Validierungen im Bericht`);
  if (opt.bilder) {
    mkdirSync(opt.bilder, { recursive: true });
    writeFileSync(befundTextPfad(opt), '');
  }

  const browser = await chromium.launch({ headless: true });
  const fehler = [];
  const hinweise = new Set();
  let tabellenGesamt = 0, zellenGesamt = 0, bilderGesamt = 0, tooltipGesamt = 0, tastaturGesamt = 0, refreshGesamt = 0, refreshNegativGesamt = 0, labFokusGesamt = 0, listenRefreshGesamt = 0, labGuardGesamt = 0, labPauseGesamt = 0, taktGesamt = 0, inhaltGesamt = 0, agentenPruefungen = 0, legendeGesamt = 0, legendeDesktopGeprueft = 0, kopfGeprueft = 0, schmaleAnsichten = 0, schreibwegeGesamt = 0, claimPruefungen = 0;

  try {
    const kopfBefunde = await pruefeKopfzeile(browser, opt.url);
    if (kopfBefunde.length) {
      for (const text of kopfBefunde) fehler.push(`1024px/kopf: ${text}`);
    } else {
      kopfGeprueft++;
    }

    const schmaleErgebnis = await pruefe240Ansichten(browser, opt.url, opt.ansichten);
    schmaleAnsichten = schmaleErgebnis.ergebnisse.length;
    for (const text of schmaleErgebnis.befund) fehler.push(text);

    const desktopLegendeBefunde = await pruefeLegendeDesktop(browser, opt.url);
    if (desktopLegendeBefunde.length) {
      for (const text of desktopLegendeBefunde) fehler.push(`1440px/legende: ${text}`);
    } else {
      legendeDesktopGeprueft++;
    }

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

        const vorher = fehler.length;
        await skaliere(page, 2.5);
        await page.waitForTimeout(150);

        const ansichtBefund = await messeAnsicht(page, ansicht, breite);
        if (!ansichtBefund.gerendert) ansichtBefund.befunde.push('Ansicht wurde nicht gerendert');
        for (const text of ansichtBefund.befunde) fehler.push(`${breite}px/${ansicht}: ${text}`);

        const inhaltsBefunde = await pruefeInhalte(page, ansicht);
        if (inhaltsBefunde) {
          inhaltGesamt++;
          for (const text of inhaltsBefunde) fehler.push(`${breite}px/${ansicht}: ${text}`);
        }
        if (ansicht === 'ship') {
          agentenPruefungen++;
          legendeGesamt++;
          for (const text of await pruefeOpsLegende(page)) fehler.push(`${breite}px/${ansicht}: ${text}`);
        }

        if (ansicht === 'lab') {
          if (kurveGefunden) {
            const kurvenBefunde = await pruefeKurvenTooltip(page, ansicht, breite);
            if (kurvenBefunde) tooltipGesamt++;
            for (const text of kurvenBefunde || []) fehler.push(`${breite}px/${ansicht}: ${text}`);
            const tastaturBefunde = await pruefeKurvenTastatur(page, ansicht);
            if (tastaturBefunde) tastaturGesamt++;
            for (const text of tastaturBefunde || []) fehler.push(`${breite}px/${ansicht}: ${text}`);
            // Der Refresh wird bei 360 und 280 px geprüft; das CI-Gate verlangt
            // zwei erfolgreiche Prüfungen. Der Negativtest läuft einmal am
            // ersten Breitenwert, weil er beide Fehlerbilder unabhängig von der
            // Breite injiziert.
            if (breite === 360 || breite === 280) {
              const refreshBefunde = await pruefeLabAutoRefresh(page, ansicht);
              if (refreshBefunde.length === 0) refreshGesamt++;
              for (const text of refreshBefunde) fehler.push(`${breite}px/${ansicht}: ${text}`);
            }
            if (breite === opt.breiten[0]) {
              const refreshNegativBefunde = await pruefeLabAutoRefreshNegativ(browser, opt.url, breite);
              if (refreshNegativBefunde.length === 0) refreshNegativGesamt++;
              for (const text of refreshNegativBefunde) fehler.push(`${breite}px/lab-negativ: ${text}`);
              for (const variante of LAB_FOKUS_VARIANTEN) {
                const labFokusBefunde = await pruefeLabFokusAutoRefresh(browser, opt.url, breite, variante, opt.bilder);
                if (labFokusBefunde.length === 0) labFokusGesamt++;
                if (variante.id === 'liste' && labFokusBefunde.length === 0) listenRefreshGesamt++;
                for (const text of labFokusBefunde) fehler.push(`${breite}px/${ansicht}: ${text}`);
              }
              const labGuardBefunde = await pruefeLabGuardLogik(browser, opt.url, breite, opt.bilder);
              if (labGuardBefunde.length === 0) labGuardGesamt++;
              for (const text of labGuardBefunde) fehler.push(`${breite}px/lab-guard: ${text}`);
              const labPauseBefunde = await pruefeLabPauseHinweis(browser, opt.url, breite, opt.bilder);
              if (labPauseBefunde.length === 0) labPauseGesamt++;
              for (const text of labPauseBefunde) fehler.push(`${breite}px/lab-pause: ${text}`);
            }
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
          const { bilder } = await schreibeDiagnose(page, opt, breite, ansicht, fehler.slice(vorher));
          bilderGesamt += bilder.length;
        }
      }
      await page.close();

    }

    if (opt.ansichten.includes('spider')) {
      for (const breite of claimBreiten) {
        const claimBefunde = await pruefeClaimMetadaten(browser, opt.url, breite);
        if (claimBefunde.length) {
          for (const text of claimBefunde) fehler.push(`${breite}px/spider: ${text}`);
        } else {
          claimPruefungen++;
        }
      }
    }

    const taktBefunde = await pruefeRefreshTakt(browser, opt.url, opt.breiten[0]);
    if (taktBefunde.length === 0) taktGesamt++;
    for (const text of taktBefunde) fehler.push(`takt: ${text}`);

    const schreibPage = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 1 });
    schreibPage.on('pageerror', err => fehler.push(`schreibwege: ${err}`));
    await schreibPage.goto(`${opt.url}/`, { waitUntil: 'domcontentloaded' });
    const schreibBefunde = await pruefeCompanySchreibwege(schreibPage);
    schreibwegeGesamt += schreibBefunde.geprueft;
    for (const text of schreibBefunde.befunde) fehler.push(`schreibwege: ${text}`);
    await schreibPage.close();
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
  console.log(`OK: keine Überläufe${kopfGeprueft ? ` · Kopfzeile ${kopfGeprueft}× geprüft` : ''}${schmaleAnsichten ? ` · 240px ${schmaleAnsichten} Ansichten geprüft` : ''}${opt.tabellen ? ` · ${tabellenGesamt} Tabellen mit ${zellenGesamt} Zellen geprüft` : ''}${inhaltGesamt ? ` · Inhalte ${inhaltGesamt}× geprüft` : ''}${claimPruefungen ? ` · Claims ${claimPruefungen}× geprüft` : ''}${agentenPruefungen ? ` · Agenten ${agentenPruefungen}× geprüft` : ''}${legendeGesamt ? ` · Legende ${legendeGesamt}× geprüft` : ''}${legendeDesktopGeprueft ? ` · Desktop-Legende ${legendeDesktopGeprueft}× geprüft` : ''}${tooltipGesamt ? ` · Tooltip ${tooltipGesamt}× geprüft` : ''}${tastaturGesamt ? ` · Tastatur ${tastaturGesamt}× geprüft` : ''}${refreshGesamt ? ` · Refresh ${refreshGesamt}× geprüft (HTTP 200, Marker)` : ''}${refreshNegativGesamt ? ` · Refresh-Negativ ${refreshNegativGesamt}× geprüft` : ''}${labFokusGesamt ? ` · Lab-Fokus ${labFokusGesamt}× geprüft` : ''}${labGuardGesamt ? ` · Lab-Guard ${labGuardGesamt}× geprüft` : ''}${labPauseGesamt ? ` · Lab-Pause ${labPauseGesamt}× geprüft` : ''}${listenRefreshGesamt ? ` · Listen-Refresh ${listenRefreshGesamt}× geprüft` : ''}${taktGesamt ? ` · Refresh-Takt ${taktGesamt}× geprüft` : ''}${schreibwegeGesamt ? ` · Schreibwege ${schreibwegeGesamt}× geprüft` : ''}${bilderGesamt ? ` · ${bilderGesamt} Screenshots` : ''}`);
}

main().catch(fehler => {
  console.error(fehler instanceof Error ? fehler.message : fehler);
  process.exit(1);
});
