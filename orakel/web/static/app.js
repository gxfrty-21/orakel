/* Orakel Dashboard — liest /api/report (Schema 2) und /api/lauf. */
(() => {
const $ = s => document.querySelector(s);
const COL = { accent:'#5fe0c8', amber:'#e8b45a', good:'#62d68a', bad:'#e2616b', blue:'#8fb8ff', dim:'#55606d' };
let R = null, current = 'overview', labFilter = 'all', labSel = 0, stratSel = 0, depSel = 'A';
let globeView = null, globeFailed = false, globeWindow = '24h', globeRequest = 0, globeAbort = null, globeLoading = null;
let nachtDaten = null, nachtFehler = null;
let graphWindow = '7d', graphDaten = null, kalibrierungDaten = null;
let betriebDaten = null, betriebFehler = null, betriebTimer = null;
let companyDaten = null, companyFehler = null, companyTimer = null, companyLaden = false;
let shipAuswahl = { typ: 'overview' }, shipDeptFilter = null, shipZoom = 1, shipX = 0, shipY = 0, shipZoomInit = false;
const SHIP_GROSS_MQ = window.matchMedia('(min-width: 1100px)');
let shipGrossGerendert = null;
function shipGrossAktiv(){ return SHIP_GROSS_MQ.matches; }
let shipDetail = null, shipDetailFehler = null, shipDetailLaden = false;
let shipDetailFuer = null, shipDetailAnfrage = 0, shipNachrichtStatus = null, shipDraft = null;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v,d=2) => (v==null||isNaN(v)) ? '–' : Number(v).toLocaleString('de-CH',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct = (v,d=1) => v==null ? '–' : num(v,d)+' %';
const money = v => v==null ? '–' : 'USD '+num(v);
const cls = v => v==null ? 'na' : v>0 ? 'up' : v<0 ? 'dn' : '';
const params = p => Object.entries(p||{}).map(([a,b])=>a+'='+b).join(', ');
const MODE = {
  simulation:['SIMULATION','b-sim','Erfundene Kurse. Diese Zahlen sagen nichts über echte Märkte aus.'],
  backtest:['BACKTEST','b-bt','Echte historische Kurse, inklusive Gebühren und Slippage.'],
  paper:['PAPER TRADING','b-paper','Papiergeld, echte Kurse. Kein echtes Geld im Spiel.'],
  live:['LIVE','b-sim','Echtes Geld — in diesem Projekt gesperrt.'],
};
const DEP = { A:'Hauptzentrale', B:'Spider Intelligence', C:'Labor', D:'Trading Floor',
  E:'Forschungsabteilung', F:'Risikomanagement', G:'Wissenszentrum', H:'Entwicklungsabteilung' };

/* ---------- Navigation ---------- */
const navToggle = $('#navToggle');
const querformatAbfrage = window.matchMedia('(orientation: landscape) and (max-width: 950px) and (max-height: 500px)');
function querformatAktiv(){ return querformatAbfrage.matches; }
function setzeNavEingeklappt(eingeklappt){
  document.body.classList.toggle('nav-eingeklappt', Boolean(eingeklappt) && querformatAktiv());
  if(navToggle) navToggle.setAttribute('aria-expanded', String(!document.body.classList.contains('nav-eingeklappt')));
}
if(navToggle){
  navToggle.onclick = () => setzeNavEingeklappt(!document.body.classList.contains('nav-eingeklappt'));
  const syncNav = () => setzeNavEingeklappt(current === 'ship' && querformatAktiv());
  if(querformatAbfrage.addEventListener) querformatAbfrage.addEventListener('change', syncNav);
  else if(querformatAbfrage.addListener) querformatAbfrage.addListener(syncNav);
}
document.querySelectorAll('.nav').forEach(b => b.onclick = () => zeige(b.dataset.v));
function zeige(v){ current=v;
  if(v === 'ship') setzeNavEingeklappt(true);
  if(v !== 'globe' && globeView) globeView.setActive(false);
  if(v !== 'betrieb' && betriebTimer){ clearInterval(betriebTimer); betriebTimer = null; }
  if(v === 'betrieb' && !betriebTimer){
    ladeBetrieb();
    betriebTimer = setInterval(ladeBetrieb, 30000);
  }
  if(v !== 'ship' && companyTimer){ clearInterval(companyTimer); companyTimer = null; }
  if(v === 'ship' && !companyTimer){
    ladeCompany();
    companyTimer = setInterval(ladeCompany, 30000);
  }
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  document.querySelectorAll('.view').forEach(s=>s.hidden = s.id !== 'v-'+v);
  zeichne();
}
function zeichne(){
  if(!R) return;
  ({overview:renderOverview,risk:renderRisk,lab:renderLab,strat:renderStrat,
    research:renderFlow,kb:renderKb,agents:renderAgents,konf:renderKonf,
    globe:renderGlobe,betrieb:renderBetrieb,ship:renderShip,spider:renderSpider})[current]?.();
}
function tabelleKarten(){
  document.querySelectorAll('main table.tbl').forEach(t=>{
    if(t.closest('#types')) return;
    const ths = [...t.querySelectorAll('thead th')].map(th=>th.textContent.trim());
    if(!ths.length) return;
    t.classList.add('tblCards');
    t.querySelectorAll('tbody tr').forEach(tr=>{
      [...tr.children].forEach((td,i)=>{
        if(ths[i]) td.setAttribute('data-label', ths[i]);
      });
    });
  });
}
const tabellenBeobachter = new MutationObserver(tabelleKarten);
tabellenBeobachter.observe(document.querySelector('main'), {childList:true, subtree:true});
tabelleKarten();

/* ---------- Kopfzeile ---------- */
function renderTop(){
  if(!R) return;
  const m = MODE[R.modus] || ['UNBEKANNT','b-none',''];
  $('#cMode').innerHTML = `<span class="dot" style="background:${m[2]==='b-none'?COL.dim:m[1]==='b-sim'?COL.bad:m[1]==='b-paper'?COL.good:COL.blue}"></span>${m[0]}`;
  const halt = R.risiko?.status === 'gestoppt';
  $('#cRisk').innerHTML = `Risiko: <span class="${halt?'dn':'up'}">${halt?'GESTOPPT':'aktiv'}</span>`;
  $('#cAge').innerHTML = 'Stand: ' + esc((R.erstellt||'').replace('T',' ').slice(0,16));
  const b = $('#banner');
  b.className = 'banner ' + m[1];
  const fehler = (R.fehler||[]).length;
  b.innerHTML = `<b>${m[0]}</b>${esc(m[2])} Datenquelle: ${esc(R.datenquelle)}.` +
    (fehler ? ` <span class="dn">${fehler} Fehler im Lauf.</span>` : '');
}

/* ---------- Übersicht ---------- */
function renderOverview(){
  const v = R.validierungen||[], best = v.filter(x=>x.urteil==='bestanden');
  const k = R.konto, a = R.risiko?.auslastung||{}, L = R.risiko_grenzen||{};
  const kp = [
    ['Modus', MODE[R.modus]?.[0]||'–', `${v.length} Kandidaten geprüft`],
    ['Risiko', R.risiko?.status==='gestoppt' ? '<span class="dn">GESTOPPT</span>' : '<span class="up">aktiv</span>',
      R.risiko?.status==='gestoppt' ? esc(R.risiko.grund) : `Drawdown ${pct(a.drawdown_pct,2)} von max. ${L.max_drawdown_pct} %`],
    ['Validierung', `${best.length} / ${v.length}`, 'bestanden, nach Gebühren und Slippage'],
    ['Kontowert', k ? money(k.equity) : '–', k ? `Bargeld ${money(k.cash)}` : 'kein Broker im Lauf (Backtest)'],
  ];
  $('#ovKpis').innerHTML = kp.map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const P = R.plan||[];
  $('#planTag').textContent = P.length ? `${P.length} Auftragsentwürfe` : 'keine Aufträge';
  $('#planList').innerHTML = P.length ? P.map(p=>`
    <div class="li planZeile"><span><b>${esc(p.symbol)} · ${esc(p.aktion)}${p.menge?' · '+num(p.menge,0)+' Stück':''}</b>
    <small>${esc(p.strategie||'')}${p.kurs?' · Kurs '+num(p.kurs,5):''}</small></span>
    <span class="planStatus">
    <span class="pill ${p.genehmigt?'':'r'}">${p.genehmigt?'GENEHMIGT':'ABGELEHNT'}</span>
    <span class="r">${esc(p.status)}</span></span></div>`).join('')
    : '<div class="empty">Dieser Lauf hat keine Aufträge geplant.</div>';

  const A = R.auswahl||[];
  $('#selTag').textContent = A.length + ' ausgewählt';
  $('#selList').innerHTML = A.length ? A.map(s=>{
    const d = v.find(x=>x.schluessel===s.schluessel);
    return `<div class="li"><span><b>★ ${esc(s.symbol)}</b><small>${esc(d?d.strategie+' · '+params(d.parameter):s.schluessel)}</small></span>
      <span class="r">PF ${d?num((d.out_of_sample||{}).profit_factor,2):'–'}</span></div>`;
  }).join('') : '<div class="empty">Keine Strategie ausgewählt.</div>';

  const ev = [...(R.fehler||[]).map(t=>({stufe:'fehler',quelle:'Lauf',text:t,zeit:R.erstellt})), ...(R.ereignisse||[])].slice(0,30);
  $('#events').innerHTML = ev.length ? ev.map(e=>`<div class="li evZeile"><span><b style="font-weight:400">${esc(e.text)}</b>
    <small>${esc((e.zeit||'').replace('T',' ').slice(0,16))} · ${esc(e.quelle)}</small></span>
    <span class="pill ${e.stufe==='fehler'?'r':e.stufe==='warnung'?'w':'g'}">${esc(e.stufe).toUpperCase()}</span></div>`).join('')
    : '<div class="empty">Keine Ereignisse.</div>';
}

/* ---------- Risiko ---------- */
function renderRisk(){
  const r = R.risiko||{}, a = r.auslastung||{}, L = R.risiko_grenzen||{};
  const halt = r.status === 'gestoppt';
  $('#riskStatus').innerHTML = `<div class="card"><span><span class="pill ${halt?'r':''}">${halt?'HANDELSSTOPP':'AKTIV'}</span></span>
    <h2>${halt?esc(r.grund):'Keine Grenze überschritten'}</h2>
    <p class="sub" style="margin:0">${halt?'Neue Käufe sind blockiert. Aufheben nur nach Prüfung: <span class="code">python -m orakel stopp-aufheben --bestaetigen</span>':'Käufe werden einzeln gegen alle Grenzen geprüft. Verkäufe bleiben immer erlaubt.'}</p></div>`;
  const zeile = (name,lim,cur,unit) => {
    const p = (cur==null||!lim) ? null : Math.min(100, cur/lim*100);
    return `<tr><td>${name}</td><td class="m">${lim}${unit}</td><td class="m">${cur==null?'–':num(cur,unit?2:0)+unit}</td>
      <td>${p==null?'<span class="na">kein Konto im Lauf</span>':`<span class="bar"><i style="width:${p}%;background:${p>=100?COL.bad:p>=70?COL.amber:COL.good}"></i></span>`}</td></tr>`;
  };
  $('#riskLimits').innerHTML = `<table class="tbl"><thead><tr><th>Grenze</th><th class="m">Wert</th><th class="m">Aktuell</th><th>Auslastung</th></tr></thead><tbody>
    ${zeile('Drawdown vom Höchststand',L.max_drawdown_pct,a.drawdown_pct,' %')}
    ${zeile('Tagesverlust',L.max_daily_loss_pct,a.tagesverlust_pct,' %')}
    ${zeile('Gesamtengagement (100 % = kein Hebel)',L.max_gross_exposure_pct,a.engagement_pct,' %')}
    ${zeile('Offene Positionen',L.max_open_positions,a.positionen,'')}
    <tr><td>Risiko pro Trade bis Stop</td><td class="m">${L.risk_per_trade_pct} %</td><td class="m">–</td><td class="na">pro Auftrag geprüft</td></tr>
    <tr><td>Max. Grösse einer Position</td><td class="m">${L.max_position_pct} %</td><td class="m">–</td><td class="na">pro Auftrag geprüft</td></tr>
    <tr><td>Stop-Abstand</td><td class="m">${L.atr_stop_multiple} × ATR</td><td class="m">–</td><td class="na">durchschnittliche Schwankung</td></tr>
  </tbody></table>`;
  const dq = R.datenqualitaet||[];
  $('#dqTag').textContent = `${dq.filter(q=>q.ok).length} von ${dq.length} Symbolen in Ordnung`;
  $('#dq').innerHTML = dq.length ? `<table class="tbl"><thead><tr><th>Symbol</th><th>Status</th><th class="m">Kerzen</th><th>Zeitraum</th><th>Fehler / Warnungen</th></tr></thead><tbody>
    ${dq.map(q=>`<tr><td>${esc(q.symbol)}</td><td><span class="pill ${q.ok?'':'r'}">${q.ok?'OK':'FEHLER'}</span></td>
    <td class="m">${q.kerzen}</td><td>${esc((q.von||'–').slice(0,16))} bis ${esc((q.bis||'–').slice(0,16))}</td>
    <td style="white-space:normal">${[...(q.fehler||[]).map(e=>`<span class="dn">${esc(e)}</span>`),...(q.warnungen||[]).map(e=>`<span class="na">${esc(e)}</span>`)].slice(0,4).join('<br>')||'<span class="na">keine</span>'}</td></tr>`).join('')}
    </tbody></table>` : '<div class="empty">Keine Daten geprüft.</div>';
  const c = R.kosten||{};
  $('#costs').innerHTML = `<table class="tbl tblKey"><tbody>
    <tr><td>Kommission pro Stück</td><td class="m">USD ${c.commission_per_share}</td></tr>
    <tr><td>Mindestkommission</td><td class="m">USD ${c.min_commission}</td></tr>
    <tr><td>Slippage pro Ausführung</td><td class="m">${c.slippage_bps} bps</td></tr>
    <tr><td>Ausführung</td><td class="m">Eröffnung der Folgekerze</td></tr></tbody></table>`;
  $('#live').innerHTML = `<span><span class="pill r">GESPERRT</span></span><div class="reasons">
    ${(R.live?.gruende||[]).map(g=>`<span class="x">${esc(g)}</span>`).join('')}</div>`;
}

/* ---------- Lab ---------- */
document.querySelector('#labTabs').onclick = e => {
  const b = e.target.closest('.tab'); if(!b) return;
  labFilter = b.dataset.f; labSel = 0;
  document.querySelectorAll('#labTabs .tab').forEach(t=>t.classList.toggle('on',t===b));
  renderLab();
};
/* Aggregierte Kapitalkurve der Walk-Forward-Testfenster als SVG. */
const KURVE_B = 600, KURVE_H = 150, KURVE_RAND = 8;
let kapitalKurveDaten = null;

/* Zeigt Kapitalstand und Datum als Tooltip über der Walk-Forward-Kurve. */
function drahteKapitalKurve(){
  const box = document.querySelector('#labDetail .wfoKurveFlaeche');
  const daten = kapitalKurveDaten;
  if(!box || !daten || daten.punkte.length < 2) return;
  const svg = box.querySelector('svg');
  const zeiger = box.querySelector('.wfoKurveZeiger');
  const punkt = box.querySelector('.wfoKurvePunkt');
  const tipp = box.querySelector('.wfoKurveTipp');
  const live = box.querySelector('.wfoKurveLive');
  const { punkte, tief, hoch, spanne, start } = daten;
  let aktiv = -1, ueber = false;
  const datum = t => {
    const teile = String(t || '').slice(0, 10).split('-');
    return teile.length === 3 ? `${teile[2]}.${teile[1]}.${teile[0]}` : String(t || '–');
  };
  const verstecke = () => {
    if(ueber || document.activeElement === svg) return;
    box.classList.remove('an');
    tipp.replaceChildren();
    live.textContent = '';
    aktiv = -1;
  };
  const setze = i => {
    const r = svg.getBoundingClientRect();
    if(!r.width) return;
    i = Math.max(0, Math.min(punkte.length - 1, i));
    if(i === aktiv && box.classList.contains('an')) return;
    aktiv = i;
    const p = punkte[i];
    const xPx = (i / (punkte.length - 1)) * r.width;
    const yPx = (KURVE_RAND + (hoch - p.v) / spanne * (KURVE_H - 2 * KURVE_RAND)) / KURVE_H * r.height;
    const xSvg = (i / (punkte.length - 1) * KURVE_B).toFixed(1);
    zeiger.setAttribute('x1', xSvg); zeiger.setAttribute('x2', xSvg);
    punkt.style.left = xPx + 'px';
    punkt.style.top = yPx + 'px';
    const zeile = document.createElement('span');
    zeile.className = 'wfoKurveWert';
    const betrag = document.createElement('b');
    betrag.textContent = 'USD ' + num(p.v, 0);
    zeile.append(betrag);
    const roh = start && Math.abs(start) > 1e-9 ? (p.v - start) / start * 100 : null;
    const prozent = roh == null ? null : Math.round(roh * 10) / 10 || 0;
    if(prozent != null){
      const delta = document.createElement('i');
      delta.className = cls(prozent);
      delta.textContent = (prozent > 0 ? '+' : '') + num(prozent, 1) + ' %';
      zeile.append(delta);
    }
    const tag = document.createElement('span');
    tag.textContent = datum(p.t);
    const hochZeile = document.createElement('span');
    hochZeile.className = 'wfoKurveHoch';
    const abstandRoh = p.hoch && Math.abs(p.hoch) > 1e-9 ? (p.v - p.hoch) / p.hoch * 100 : 0;
    const abstand = Math.round(abstandRoh * 10) / 10 || 0;
    hochZeile.textContent = `Hoch bis hier USD ${num(p.hoch,0)} · ${abstand < 0 ? num(Math.abs(abstand),1) + ' % darunter' : 'am Hoch'}`;
    tipp.replaceChildren(zeile, tag, hochZeile);
    box.classList.add('an');
    const breite = tipp.offsetWidth, hoehe = tipp.offsetHeight;
    const links = Math.max(4, Math.min(r.width - breite - 4, xPx - breite / 2));
    let oben = yPx - hoehe - 10;
    if(oben < 4) oben = yPx + 10;
    tipp.style.left = links + 'px';
    tipp.style.top = Math.max(4, Math.min(r.height - hoehe - 4, oben)) + 'px';
    const richtung = prozent == null ? '' : prozent > 0 ? `, plus ${num(prozent,1)} Prozent seit Start` : prozent < 0 ? `, minus ${num(Math.abs(prozent),1)} Prozent seit Start` : ', unverändert seit Start';
    const hochText = abstand < 0
      ? `${num(Math.abs(abstand),1)} Prozent unter dem bisherigen Hoch von USD ${num(p.hoch,0)}`
      : `am bisherigen Hoch von USD ${num(p.hoch,0)}`;
    live.textContent = `Kapital USD ${num(p.v,0)}${richtung}, ${datum(p.t)}, ${hochText}`;
  };
  const zeige = ev => {
    const r = svg.getBoundingClientRect();
    if(!r.width) return;
    const anteil = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    setze(Math.round(anteil * (punkte.length - 1)));
  };
  svg.addEventListener('pointerenter', () => { ueber = true; });
  svg.addEventListener('pointermove', zeige);
  svg.addEventListener('pointerdown', zeige);
  box.addEventListener('pointerleave', () => { ueber = false; verstecke(); });
  svg.addEventListener('focus', () => { if(aktiv < 0) setze(0); });
  svg.addEventListener('blur', verstecke);
  svg.addEventListener('keydown', ev => {
    const schritt = ev.shiftKey ? 10 : 1;
    let ziel;
    if(ev.key === 'ArrowLeft') ziel = (aktiv < 0 ? 0 : aktiv) - schritt;
    else if(ev.key === 'ArrowRight') ziel = (aktiv < 0 ? 0 : aktiv) + schritt;
    else if(ev.key === 'Home') ziel = 0;
    else if(ev.key === 'End') ziel = punkte.length - 1;
    else return;
    ev.preventDefault();
    setze(ziel);
  });
}

function kapitalKurveBlock(o){
  const roh = (o && o.kapitalkurve || []).filter(p=>Array.isArray(p) && Number.isFinite(Number(p[1])));
  if(roh.length < 2) return '';
  // Auf höchstens 240 Punkte ausdünnen; der letzte Punkt bleibt erhalten.
  const schritt = Math.max(1, Math.ceil(roh.length / 240));
  const punkte = roh.filter((_,i)=>i%schritt===0);
  if(punkte[punkte.length-1] !== roh[roh.length-1]) punkte.push(roh[roh.length-1]);
  const werte = punkte.map(p=>Number(p[1]));
  const start = werte[0], ende = werte[werte.length-1];
  const tief = Math.min(...werte), hoch = Math.max(...werte);
  const spanne = Math.max(1e-9, hoch - tief);
  let spitze = -Infinity;
  kapitalKurveDaten = { punkte: punkte.map(p=>{
    const v = Number(p[1]);
    spitze = Math.max(spitze, v);
    return { t: String(p[0] || ''), v, hoch: spitze };
  }), tief, hoch, spanne, start };
  const B = KURVE_B, H = KURVE_H, RAND = KURVE_RAND;
  const x = i => (i / (punkte.length - 1)) * B;
  const y = w => RAND + (hoch - w) / spanne * (H - 2 * RAND);
  const verlauf = punkte.map((p,i)=>`${x(i).toFixed(1)},${y(Number(p[1])).toFixed(1)}`).join(' ');
  const farbe = ende >= start ? 'var(--good)' : 'var(--bad)';
  const falten = (o.walk_forward_folds||[]).map(f=>f.test_von).filter(Boolean).slice(1);
  const grenzen = falten.map(ts=>{
    const i = punkte.findIndex(p=>String(p[0]) >= ts);
    return i > 0 ? `<line x1="${x(i).toFixed(1)}" y1="0" x2="${x(i).toFixed(1)}" y2="${H}" class="wfoKurveFalte"></line>` : '';
  }).join('');
  const aria = `Kapitalkurve der Walk-Forward-Testfenster: Start USD ${num(start,0)}, Tief USD ${num(tief,0)}, Hoch USD ${num(hoch,0)}, Ende USD ${num(ende,0)}. Mit den Pfeiltasten Datenpunkte ablesen, Home und Ende für Anfang und Schluss.`;
  return `<div class="ph" style="border-top:1px solid var(--line)">Walk-Forward-Kapitalkurve<span class="tag">Testfenster verkettet</span></div>
    <div class="wfoKurve">
    <div class="wfoKurveFlaeche">
    <svg viewBox="0 0 ${B} ${H}" preserveAspectRatio="none" role="img" tabindex="0" aria-label="${esc(aria)}">
      <line x1="0" y1="${y(start).toFixed(1)}" x2="${B}" y2="${y(start).toFixed(1)}" class="wfoKurveBasis"></line>
      ${grenzen}
      <polygon points="0,${H} ${verlauf} ${B},${H}" fill="${farbe}" opacity=".1"></polygon>
      <polyline points="${verlauf}" fill="none" stroke="${farbe}" stroke-width="1.6"
        vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"></polyline>
      <line x1="0" y1="0" x2="0" y2="${H}" class="wfoKurveZeiger"></line>
    </svg>
    <div class="wfoKurvePunkt"></div>
    <div class="wfoKurveTipp"></div>
    <div class="wfoKurveLive" role="status" aria-live="polite"></div>
    </div>
    <div class="wfoKurveFuss">
      <span>Start <b>USD ${num(start,0)}</b></span><span>Tief <b>USD ${num(tief,0)}</b></span>
      <span>Hoch <b>USD ${num(hoch,0)}</b></span><span>Ende <b class="${cls(ende-start)}">USD ${num(ende,0)}</b></span>
    </div>
    <div class="wfoKurveHinweis" aria-hidden="true">Mit <kbd>←</kbd> <kbd>→</kbd> Datenpunkte ablesen</div></div>`;
}

/* Einzelne Walk-Forward-Fenster eines Kandidaten, aufklappbar. */
function wfoFoldsBlock(o){
  const folds = (o && o.walk_forward_folds)||[];
  if(!folds.length) return '';
  const datum = t => t ? esc(String(t).slice(0,10)) : '–';
  const betrag = v => v==null?'–':(v>=0?'+':'-')+'USD '+num(Math.abs(v),0);
  return `<details class="wfoFolds"><summary>Walk-Forward-Fenster
    <small>${folds.length} Fenster · ${folds.filter(f=>f.profitable).length} profitabel</small></summary>
    <div class="tw"><table class="tbl"><thead><tr><th>Fenster</th><th>Training</th><th>Test</th>
    <th>Parameter im Fenster</th><th class="m">Trades Training</th><th class="m">Trades Test</th>
    <th class="m">Profit Factor</th><th class="m">Netto</th><th>Ergebnis</th></tr></thead><tbody>
    ${folds.map(f=>{
      const F=f.test||{}, P=f.train||{}, ok=!!f.profitable;
      return `<tr><td>Fenster ${esc(f.nr)}</td><td>${datum(f.train_von)} – ${datum(f.train_bis)}</td>
      <td>${datum(f.test_von)} – ${datum(f.test_bis)}</td><td style="white-space:normal">${esc(params(f.parameter)||'–')}</td>
      <td class="m">${P.trades??'–'}</td><td class="m">${F.trades??'–'}</td>
      <td class="m">${F.profit_factor==null?'–':num(F.profit_factor,2)}</td>
      <td class="m ${cls(F.netto)}">${betrag(F.netto)}</td>
      <td><span class="pill ${ok?'':'r'}"${f.grund?` title="${esc(f.grund)}"`:''}>${f.grund?'KEIN PARAMETER':ok?'PROFITABEL':'VERLUST'}</span></td></tr>`;
    }).join('')}
    </tbody></table></div></details>`;
}

function renderLab(){
  const v = R.validierungen||[], selbst = u => `<span class="pill ${u==='bestanden'?'':u==='abgelehnt'?'r':'g'}">${esc(u).toUpperCase()}</span>`;
  $('#labKpis').innerHTML = [['Geprüft',v.length,'Kandidaten'],['Bestanden',v.filter(x=>x.urteil==='bestanden').length,'alle Regeln inkl. Holdout'],
    ['Holdout',`${v.filter(x=>x.holdout_bestanden===true).length} / ${v.filter(x=>x.holdout_bestanden!=null).length}`,'nur bester Kandidat je Symbol'],
    ['Abgelehnt',v.filter(x=>x.urteil==='abgelehnt').length,'mit Begründung']]
    .map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const items = v.filter(x=>labFilter==='all'||x.urteil===labFilter)
    .sort((a,b)=>(b.urteil==='bestanden')-(a.urteil==='bestanden')||((b.out_of_sample||{}).profit_factor||0)-((a.out_of_sample||{}).profit_factor||0));
  $('#labList').innerHTML = items.length ? items.map((o,k)=>`<button class="li ${k===labSel?'on':''}" data-k="${k}">
    <span><b>${esc(o.symbol)} · ${esc(o.strategie)}</b><small>${esc(params(o.parameter))}</small></span>
    <span style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">${selbst(o.urteil)}
    <span class="r">${num((o.out_of_sample||{}).profit_factor,2)}</span></span></button>`).join('')
    : '<div class="empty">Keine Einträge.</div>';
  document.querySelectorAll('#labList .li').forEach(b=>b.onclick=()=>{labSel=+b.dataset.k;renderLab();});
  const o = items[labSel];
  if(!o){ $('#labDetail').innerHTML = '<div class="empty">Keine Auswahl.</div>'; return; }
  const I=o.in_sample||{}, O=o.out_of_sample||{}, G=o.gesamt||{}, H=o.holdout||{}, Hk=H.kennzahlen||{};
  const mrow = (n,k,f) => `<tr><td>${n}</td><td class="m">${f(I[k])}</td><td class="m">${f(O[k])}</td><td class="m">${f(G[k])}</td></tr>`;
  const usd = v => v==null?'–':(v>=0?'+':'-')+'USD '+num(Math.abs(v),0);
  $('#labDetail').innerHTML = `<div class="card"><span>${selbst(o.urteil)}</span>
    <h2>${esc(o.symbol)} · ${esc(o.strategie)}</h2>
    <p class="sub" style="margin:0">${esc(o.beschreibung)}<br>Parameter: ${esc(params(o.parameter))}${o.oos_ab?' · ungesehen ab '+esc(o.oos_ab):''}</p>
    <div class="reasons">${(o.gruende||[]).map(r=>`<span class="x">${esc(r)}</span>`).join('')}${(o.erfuellt||[]).map(r=>`<span class="y">${esc(r)}</span>`).join('')}</div></div>
    <div class="tw"><table class="tbl"><thead><tr><th>Kennzahl (Start USD 100'000)</th><th class="m">Training</th><th class="m">Ungesehen</th><th class="m">Gesamt</th></tr></thead><tbody>
    ${mrow('Nettogewinn','netto',usd)}${mrow('Rendite','rendite_pct',v=>pct(v,1))}${mrow('Profit Factor','profit_factor',v=>v==null?'–':num(v,2))}
    ${mrow('Trefferquote','trefferquote_pct',v=>pct(v,1))}${mrow('Max. Drawdown','max_drawdown_pct',v=>pct(v,1))}${mrow('Trades','trades',v=>v??'–')}
    ${mrow('Gebühren','gebuehren',v=>v==null?'–':'USD '+num(v,0))}${mrow('Zeit im Markt','zeit_im_markt_pct',v=>pct(v,0))}${mrow('Sharpe','sharpe',v=>v==null?'–':num(v,2))}
    <tr><td>Kaufen und Halten (ungesehen)</td><td class="m">–</td><td class="m">${pct(o.kaufen_halten_oos_pct,1)}</td><td class="m">–</td></tr>
    <tr><td>Robustheit (Nachbar-Parameter profitabel)</td><td class="m">–</td><td class="m">–</td><td class="m">${o.robustheit_anteil==null?'–':Math.round(o.robustheit_anteil*100)+' %'}</td></tr>
    <tr><td>Monte-Carlo Drawdown (95 %)</td><td class="m">–</td><td class="m">–</td><td class="m">${pct(o.monte_carlo_dd_p95,1)}</td></tr>
    <tr><td>Walk-Forward-Fenster profitabel</td><td class="m">–</td><td class="m">–</td><td class="m">${o.walk_forward_bestanden==null?'–':Math.round(o.walk_forward_bestanden*100)+' %'}</td></tr>
    <tr><td>Zufallsvergleich (p-Wert, kleiner = besser)</td><td class="m">–</td><td class="m">–</td><td class="m">${o.zufall_p_wert==null?'nicht geprüft':num(o.zufall_p_wert,4)}</td></tr>
    </tbody></table></div>
    ${kapitalKurveBlock(o)}
    ${wfoFoldsBlock(o)}
    <div class="ph" style="border-top:1px solid var(--line)">Versiegelter Holdout<span class="tag">${H.von?esc(H.von)+' – '+esc(H.bis):'nur bester Kandidat'}</span></div>
    <div class="tw"><table class="tbl tblKey"><tbody>
    <tr><td>Ergebnis</td><td class="m">${o.holdout_bestanden==null?'nicht geöffnet':o.holdout_bestanden?'<span class="up">BESTANDEN</span>':'<span class="dn">ABGELEHNT</span>'}</td></tr>
    <tr><td>Profit Factor</td><td class="m">${Hk.profit_factor==null?'–':num(Hk.profit_factor,2)}</td></tr>
    <tr><td>Trades</td><td class="m">${Hk.trades??'–'}</td></tr>
    <tr><td>Nettogewinn</td><td class="m ${cls(Hk.netto)}">${Hk.netto==null?'–':usd(Hk.netto)}</td></tr>
    <tr><td>Max. Drawdown</td><td class="m">${pct(Hk.max_drawdown_pct,1)}</td></tr>
    <tr><td>Kaufen und Halten</td><td class="m">${pct(H.kaufen_halten_pct,1)}</td></tr>
    </tbody></table></div>
    <div class="ph" style="border-top:1px solid var(--line)">Letzte Trades<span class="tag">nach Gebühren, rot = Verlust</span></div>
    <div class="tw"><table class="tbl"><thead><tr><th>Einstieg</th><th>Ausstieg</th><th class="m">Stück</th><th class="m">Netto</th><th class="m">Rendite</th><th>Grund</th></tr></thead><tbody>
    ${(o.trades||[]).slice(-10).reverse().map(t=>`<tr><td>${esc(t.einstieg)}</td><td>${esc(t.ausstieg)}</td><td class="m">${num(t.stueck,0)}</td>
    <td class="m ${cls(t.netto)}">${num(t.netto)}</td><td class="m ${cls(t.rendite_pct)}">${num(t.rendite_pct,2)} %</td><td>${esc(t.grund)}</td></tr>`).join('')||'<tr><td colspan="6" class="na">keine Trades</td></tr>'}
    </tbody></table></div>`;
  drahteKapitalKurve();
}

/* ---------- Strategien ---------- */
function renderStrat(){
  const v = (R.validierungen||[]).filter(x=>x.urteil==='bestanden');
  const sel = new Set((R.auswahl||[]).map(a=>a.symbol+'|'+a.schluessel));
  if(!v.length){
    $('#stratList').innerHTML = '<div class="empty">Keine bestandene Strategie.</div>';
    $('#stratDetail').innerHTML = '<div class="empty">Der Richter hat keine Strategie freigegeben. Deshalb wird nicht gehandelt.<br><br>Die Gründe stehen im Lab bei jedem Kandidaten.</div>';
    return;
  }
  stratSel = Math.min(stratSel, v.length-1);
  $('#stratList').innerHTML = v.map((o,k)=>`<button class="li ${k===stratSel?'on':''}" data-k="${k}">
    <span><b>${sel.has(o.symbol+'|'+o.schluessel)?'★ ':''}${esc(o.symbol)} · ${esc(o.strategie)}</b><small>${esc(params(o.parameter))}</small></span>
    <span class="r">PF ${num((o.out_of_sample||{}).profit_factor,2)}</span></button>`).join('');
  document.querySelectorAll('#stratList .li').forEach(b=>b.onclick=()=>{stratSel=+b.dataset.k;renderStrat();});
  const d = v[stratSel], O = d.out_of_sample||{}, G = d.gesamt||{}, Hk=(d.holdout||{}).kennzahlen||{};
  const gewaehlt = sel.has(d.symbol+'|'+d.schluessel);
  $('#stratDetail').innerHTML = `<div class="card"><span>${gewaehlt?'<span class="pill">AUSGEWÄHLT FÜR '+esc(d.symbol)+'</span>':'<span class="pill g">BESTANDEN, NICHT AUSGEWÄHLT</span>'}</span>
    <h2>${esc(d.symbol)} · ${esc(d.strategie)}</h2><p class="sub" style="margin:0">${esc(d.beschreibung)}</p></div>
    <div class="kpis" style="padding:0 16px 14px">
    ${[['Profit Factor Walk-Forward',num(O.profit_factor,2)],['Trefferquote Walk-Forward',pct(O.trefferquote_pct)],
       ['Max. Drawdown Walk-Forward',pct(O.max_drawdown_pct)],['Trades Walk-Forward',O.trades??'–'],
       ['Profit Factor Holdout',num(Hk.profit_factor,2)]]
      .map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div></div>`).join('')}</div>
    <div class="tw"><table class="tbl tblKey"><tbody>
    <tr><td>Nettogewinn gesamt</td><td class="m ${cls(G.netto)}">${money(G.netto)}</td></tr>
    <tr><td>Rendite gesamt</td><td class="m ${cls(G.rendite_pct)}">${pct(G.rendite_pct,1)}</td></tr>
    <tr><td>Kaufen und Halten (ungesehen)</td><td class="m">${pct(d.kaufen_halten_oos_pct,1)}</td></tr>
    <tr><td>Gebühren gesamt</td><td class="m">${money(G.gebuehren)}</td></tr>
    <tr><td>Zeit im Markt</td><td class="m">${pct(G.zeit_im_markt_pct,0)}</td></tr></tbody></table></div>
    ${wfoFoldsBlock(d)}`;
}

/* ---------- Research ---------- */
function renderFlow(){
  const v = R.validierungen||[], dq = R.datenqualitaet||[], P = R.plan||[];
  const stationen = [
    ['Daten', `${dq.filter(q=>q.ok).length}/${dq.length} Symbole in Ordnung`, 'Kerzen laden, Lücken, Doppelungen und unmögliche Preise prüfen. Im Paper-Modus löst jeder Fehler einen Handelsstopp aus.'],
    ['Research', `${v.length} Kandidaten`, 'Nur das freigegebene Parameter-Raster. Keine KI erfindet Parameter.'],
    ['Validierung', `${v.filter(x=>x.urteil==='bestanden').length} bestanden · ${v.filter(x=>x.urteil==='abgelehnt').length} abgelehnt`, 'Rollierende Walk-Forward-Fenster, versiegelter Holdout, Monte-Carlo, Nachbar-Parameter, Zufallsvergleich.'],
    ['Risiko', `${P.filter(p=>p.genehmigt).length} genehmigt · ${P.filter(p=>!p.genehmigt).length} abgelehnt`, '1 % je Trade bis Stop, 10 % Not-Stop, maximal 15 Positionen, kein Hebel.'],
    ['Ausführung', `${P.filter(p=>(p.status||'').startsWith('Probelauf')).length} Probelauf`, 'Standard ist der Probelauf. Ohne Freigabe wird keine Order gesendet.'],
    ['Wissensbank', `${(R.wissen?.typen||[]).length} Typen · ${(R.entscheide||[]).length} Entscheide`, 'Alles Nachprüfbare landet in SQLite und im Obsidian-Vault.'],
  ];
  $('#flow').innerHTML = stationen.map((s,i)=>`<div class="station"><span class="nr">${String(i+1).padStart(2,'0')}</span>
    <span><b>${s[0]}</b><small style="display:block;color:var(--accent);font-family:var(--mono);font-size:12px">${esc(s[1])}</small>
    <small style="display:block;color:var(--muted);margin-top:4px">${esc(s[2])}</small></span></div>`).join('');
  $('#principles').innerHTML = ['KI schlägt vor, Code und Richter entscheiden.',
    'Fakten-Datenbank ist die einzige Wahrheit; das Dashboard ist ein Spiegel.',
    'Kein Look-Ahead: Ausführung erst zur nächsten Eröffnung.',
    'Kosten und Slippage in jedem Backtest.',
    'Keine Regeländerung ohne deine Freigabe.',
    'Paper-Trading, bis du es ausdrücklich anders entscheidest.']
    .map(t=>`<div class="reasons"><span class="i">${esc(t)}</span></div>`).join('');
}

/* ---------- Wissensbank ---------- */
let vaultOrdner = null, vaultOrdnerLaeuft = false;

function zeichneVaultOrdner(){
  const el = $('#vaultOrdner');
  if(!el) return;
  el.innerHTML = vaultOrdner
    ? (vaultOrdner.length ? vaultOrdner.map(o=>`<span class="i">${esc(o.name)} · ${o.anzahl} ${o.anzahl === 1 ? 'Notiz' : 'Notizen'}</span>`).join('')
      : '<span class="i">Keine Ordner mit Notizen.</span>')
    : '<span class="i">wird geladen …</span>';
}

async function ladeVaultOrdner(){
  zeichneVaultOrdner();
  if(vaultOrdner || vaultOrdnerLaeuft) return;
  vaultOrdnerLaeuft = true;
  try{
    const r = await fetch('/api/vault/graph', {cache:'no-store'});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Graph nicht verfügbar');
    vaultOrdner = (d.ordner || []).filter(o=>o && o.name)
      .map(o=>({name:o.name, anzahl:Number(o.anzahl) || 0}));
  }catch(e){
    const el = $('#vaultOrdner');
    if(el) el.innerHTML = `<span class="i">Ordner konnten nicht geladen werden: ${esc(e.message)}</span>`;
    return;
  }finally{
    vaultOrdnerLaeuft = false;
  }
  zeichneVaultOrdner();
}

function renderKb(){
  const T = R.wissen?.typen||[];
  $('#libTag').textContent = `${T.length} Typen`;
  $('#types').innerHTML = T.length ? `<table class="tbl"><thead><tr><th>Typ</th><th class="m">Tests</th><th class="m">Bestanden</th><th class="m">Quote</th><th class="m">Median PF ungesehen</th><th>Häufigste Ablehnung</th></tr></thead><tbody>
    ${T.map(t=>`<tr><td data-label="Typ">${esc(t.typ)}</td><td class="m" data-label="Tests">${t.tests}</td><td class="m" data-label="Bestanden">${t.bestanden}</td><td class="m" data-label="Quote">${pct(t.quote_pct,0)}</td>
    <td class="m" data-label="Median PF ungesehen">${t.median_pf_oos==null?'–':num(t.median_pf_oos,2)}</td><td data-label="Häufigste Ablehnung" style="white-space:normal">${esc((t.haeufigste_ablehnung||[]).join(', ')||'–')}</td></tr>`).join('')}
    </tbody></table>` : '<div class="empty">Noch keine Validierungen gespeichert.</div>';
  const D = R.entscheide||[];
  $('#decList').innerHTML = D.length ? D.map(d=>`<div class="li"><span><b>${esc(d.symbol)} · ${esc(d.aktion)}</b>
    <small>${esc((d.zeit||'').replace('T',' ').slice(0,16))} · ${esc(d.status)}</small></span>
    <span class="pill ${d.genehmigt?'':'r'}">${d.genehmigt?'JA':'NEIN'}</span></div>`).join('')
    : '<div class="empty">Noch keine Entscheide.</div>';
  $('#vaultInfo').innerHTML = `<p class="sub" style="margin:0">Der Vault liegt im Ordner <span class="code">vault/</span> und ist mit Obsidian direkt öffnbar:
    Frontmatter, Tags und [[Links]]. Validierungen, Ablehnungen, Datenfehler und Konferenzprotokolle werden dort abgelegt.</p>
    <div class="lbl">Ordner</div><div class="reasons" id="vaultOrdner"></div>`;
  ladeVaultOrdner();
  if(window.VaultGraph) window.VaultGraph.aktivieren();
}

/* ---------- Agenten ---------- */
function renderAgents(){
  const runs = R.agenten||[];
  $('#depTabs').innerHTML = Object.entries(DEP).map(([k,n])=>`<button class="tab ${k===depSel?'on':''}" data-d="${k}">${k} · ${n}</button>`).join('');
  document.querySelectorAll('#depTabs .tab').forEach(b=>b.onclick=()=>{depSel=b.dataset.d;renderAgents();});
  const meine = runs.filter(r=>r.abteilung===depSel);
  $('#agTag').textContent = `${meine.length} Agenten · ${meine.filter(r=>r.ok).length} ohne Befund`;
  $('#agList').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b>${esc(r.agent.split(':')[1]||r.agent)}</b>
    <small>${esc(r.aufgabe)}</small></span><span class="pill ${r.ok?'':'r'}">${r.ok?'OK':'BEFUND'}</span></div>`).join('')
    : '<div class="empty">Noch kein Lauf für diese Abteilung.</div>';
  $('#agRuns').innerHTML = runs.length ? runs.slice(0,40).map(r=>`<div class="li"><span><b style="font-weight:400">${esc(r.ergebnis)}</b>
    <small>${esc(DEP[r.abteilung]||r.abteilung)} · ${esc(r.agent.split(':')[1]||r.agent)}</small></span>
    <span class="pill ${r.ok?'g':'r'}">${esc(r.abteilung)}</span></div>`).join('')
    : '<div class="empty">Noch keine Agentenaktivität. Auf «Lauf starten» klicken.</div>';
}

/* ---------- Konferenz ---------- */
function renderKonf(){
  const k = R.konferenz;
  if(!k){ $('#konfBody').innerHTML = '<div class="panel"><div class="empty">Noch keine Konferenz abgehalten.</div></div>'; return; }
  $('#konfBody').innerHTML = `
    <div class="panel"><div class="ph">Protokoll<span class="sp"></span><span class="tag">${esc((k.zeit||'').replace('T',' ').slice(0,16))}</span></div>
      <div class="card"><h2>${esc(k.beschluss)}</h2><p class="sub" style="margin:0">Modus: ${esc(k.modus)}</p></div></div>
    <div class="grid2">
      <div class="panel"><div class="ph">Berichte der Abteilungen</div><div class="list">
        ${(k.berichte||[]).map(b=>`<div class="li"><span><b>${esc(b.name)}</b><small style="white-space:normal">${esc(b.text)}</small></span><span class="pill g">${esc(b.abteilung)}</span></div>`).join('')}
      </div></div>
      <div class="panel"><div class="ph">Diskussion</div><div class="list">
        ${(k.diskussion||[]).map(d=>`<div class="li"><span><b>${esc(d.von)} → ${esc(d.an)}</b><small style="white-space:normal">${esc(d.text)}</small></span></div>`).join('')}
      </div></div>
    </div>
    <div class="panel"><div class="ph">Massnahmen</div><div class="tw"><table class="tbl">
      <thead><tr><th>Massnahme</th><th>Begründung</th><th>Testplan</th><th>Verantwortlich</th></tr></thead><tbody>
      ${(k.massnahmen||[]).map(m=>`<tr><td>${esc(m.beschreibung)}</td><td style="white-space:normal">${esc(m.begruendung)}</td>
      <td style="white-space:normal">${esc(m.testplan)}</td><td>${esc(m.verantwortlicher)}</td></tr>`).join('')}
      </tbody></table></div></div>`;
}

/* ---------- Weltkugel: Global Intelligence ---------- */
// Dieselbe Schwelle, die der Risikomanager beim Kauf prüft.
function korrSchwelle(){
  const s = Number(R.risiko_grenzen?.max_correlation);
  return Number.isFinite(s) ? s : 0.85;
}

function renderGlobeMarkets(){
  const m = R.markt || {symbole:[], korrelation:[]};
  const sym = m.symbole || [];
  $('#globeTag').textContent = `${sym.length} Märkte · ${(m.stand||'').replace('T',' ')}`;
  $('#globeTable').innerHTML = sym.length ? `<table class="tbl"><thead><tr><th>Symbol</th><th>Platz</th><th class="m">Kurs</th><th class="m">24 h</th><th class="m">ATR</th><th>Regime</th></tr></thead><tbody>
    ${sym.map(s=>`<tr><td>${esc(s.symbol)}</td><td>${esc(s.stadt)}</td><td class="m">${num(s.kurs,5)}</td>
    <td class="m ${cls(s.aenderung_24h_pct)}">${num(s.aenderung_24h_pct,2)} %</td>
    <td class="m">${num(s.atr_pct,2)} %</td>
    <td><span class="pill ${s.regime==='Stress'?'r':String(s.regime).startsWith('Trend')?'b':'g'}">${esc(s.regime)}</span></td></tr>`).join('')}
    </tbody></table>` : '<div class="empty">Keine Marktdaten. Erst einen Lauf starten.</div>';
  const k = m.korrelation || [];
  const schwelle = korrSchwelle();
  const gesperrt = k.filter(x=>Math.abs(x.wert) > schwelle);
  $('#korrTag').textContent = `letzte 500 Kerzen · Schwelle ${num(schwelle,2)}`;
  $('#globeKorr').innerHTML = k.length ? `<table class="tbl"><thead><tr><th>Paar</th><th class="m">Korrelation</th><th>Stärke</th><th>Risiko</th></tr></thead><tbody>
    ${k.map(x=>{const ueber=Math.abs(x.wert)>schwelle; return `<tr class="${ueber?'krit':''}"><td>${esc(x.a)} / ${esc(x.b)}</td>
    <td class="m ${ueber?'dn':(x.wert>0?'up':'dn')}">${num(x.wert,2)}</td>
    <td><span class="bar"><i style="width:${Math.min(100,Math.abs(x.wert)*100)}%;background:${ueber?COL.bad:COL.accent}"></i></span></td>
    <td>${ueber?'<span class="pill r">SPERRE</span>':'<span class="pill g">frei</span>'}</td></tr>`;}).join('')}
    </tbody></table>` : '<div class="empty">Zu wenige gemeinsame Kerzen für Korrelationen.</div>';
  const korr = $('#globeKorr');
  if(korr){ korr.dataset.gesperrt = String(gesperrt.length); }
}

function showGlobeError(message){
  const empty = $('#globeEmpty');
  if(empty){ empty.hidden = false; empty.innerHTML = `<b>INTELLIGENCE-GRAPH NICHT VERFÜGBAR</b><span>${esc(message)}</span>`; }
  const activity = $('#globeActivity');
  if(activity){ activity.textContent = 'GRAPH OFFLINE'; activity.className = 'g-activity is-leer'; }
}

const GLOBE_WINDOWS = ['24h','7d','30d'];
function syncGlobeWindow(key){
  globeWindow = GLOBE_WINDOWS.includes(key) ? key : '24h';
  document.querySelectorAll('#globeWindow [data-window]').forEach(btn => {
    const on = btn.dataset.window === globeWindow;
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-pressed', String(on));
  });
}

function setGlobeWindow(key){
  if(!GLOBE_WINDOWS.includes(key) || key === globeWindow) return;
  syncGlobeWindow(key);
  if(current === 'globe') renderGlobe();
}

document.querySelectorAll('#globeWindow [data-window]').forEach(btn => {
  btn.addEventListener('click', () => setGlobeWindow(btn.dataset.window));
});
syncGlobeWindow(globeWindow);

async function ensureGlobe(){
  if(globeView) return globeView;
  if(globeFailed) return null;
  if(globeLoading) return globeLoading;
  const stage = $('#globeStage');
  if(!stage) return null;
  globeLoading = (async () => {
    try{
      const mod = await import('/static/globe2d.js?v=2');
      globeView = new mod.IntelligenceGlobe(stage);
      if(current === 'globe') globeView.setActive(true);
      return globeView;
    }catch(e){
      globeFailed = true;
      showGlobeError(e.message || 'Die Weltkugel konnte nicht initialisiert werden.');
      return null;
    }finally{
      globeLoading = null;
    }
  })();
  return globeLoading;
}

async function renderGlobe(){
  renderGlobeMarkets();
  const g = await ensureGlobe();
  if(!g || current !== 'globe') return;
  g.setActive(true);
  const request = ++globeRequest;
  const key = globeWindow;
  if(globeAbort) globeAbort.abort();
  const controller = new AbortController();
  globeAbort = controller;
  try{
    const r = await fetch(`/api/globe?zeitraum=${encodeURIComponent(key)}`, {cache:'no-store',signal:controller.signal});
    if(request !== globeRequest || current !== 'globe') return;
    if(!r.ok) throw new Error('Der Intelligence-Graph ist momentan nicht erreichbar.');
    const data = await r.json();
    if(request !== globeRequest || current !== 'globe') return;
    g.setData(data);
    syncGlobeWindow(data.window?.key || key);
  }catch(e){
    if(e.name === 'AbortError' || request !== globeRequest || current !== 'globe') return;
    showGlobeError(e.message || 'Der Intelligence-Graph konnte nicht geladen werden.');
  }finally{
    if(globeAbort === controller) globeAbort = null;
  }
}

/* ---------- Betrieb (Phase 8) ---------- */
function betriebDauer(sekunden){
  const s = Number(sekunden) || 0;
  if(!s) return 'jeder Takt';
  if(s >= 3600) return num(s/3600, 0) + ' h';
  if(s >= 60) return num(s/60, 0) + ' min';
  return num(s, 0) + ' s';
}

function betriebZeit(wert){
  return wert ? esc(String(wert).replace('T',' ').slice(0,16)) : '–';
}

function betriebPill(zustand){
  if(zustand === 'ok' || zustand === 'laeuft') return '';
  if(zustand === 'fehler' || zustand === 'ueberfaellig') return 'r';
  if(zustand === 'wartet' || zustand === 'backoff') return 'b';
  return 'g';
}

function betriebMeter(wert, limit){
  const p = limit > 0 ? Math.min(100, Math.max(0, Number(wert) / Number(limit) * 100)) : 0;
  const farbe = p >= 100 ? COL.bad : p >= 75 ? COL.amber : COL.good;
  return `<span class="bar"><i style="width:${p.toFixed(0)}%;background:${farbe}"></i></span>`;
}

async function ladeBetrieb(){
  if(!$('#betriebKpis')) return;
  try{
    const r = await fetch('/api/betrieb', {cache:'no-store'});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    if(!d || typeof d !== 'object' || !d.takt) throw new Error('Ungültige Antwort');
    betriebDaten = d;
    betriebFehler = null;
  }catch(e){
    betriebDaten = null;
    betriebFehler = String(e.message || e);
  }
  renderBetrieb();
}

function renderBetrieb(){
  if(!$('#betriebKpis')) return;
  if(betriebFehler){
    $('#betriebTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    $('#betriebKpis').innerHTML = '';
    $('#betriebJobs').innerHTML = `<div class="empty">Betriebsstatus nicht geladen: ${esc(betriebFehler)}</div>`;
    $('#betriebRes').innerHTML = '<div class="empty">Keine Ressourcenwerte.</div>';
    $('#betriebLog').innerHTML = '<div class="empty">Kein Jobprotokoll geladen.</div>';
    $('#betriebHinweise').innerHTML = '<div class="empty">Keine Hinweise geladen.</div>';
    return;
  }
  if(!betriebDaten){
    $('#betriebTag').textContent = 'wird geladen';
    $('#betriebKpis').innerHTML = '';
    $('#betriebJobs').innerHTML = '<div class="empty">Betriebsstatus wird geladen.</div>';
    return;
  }
  const d = betriebDaten, t = d.takt || {}, jobs = d.jobs || [];
  const res = d.ressourcen || {}, lim = res.limits || {}, st = d.statistik || {};
  const laufend = t.status === 'laeuft' ? '<span class="up">LÄUFT</span>'
    : t.status === 'ueberfaellig' ? '<span class="dn">ÜBERFÄLLIG</span>'
    : t.status === 'aus' ? '<span class="na">AUS</span>' : '–';
  const okJobs = jobs.filter(j=>j.letzter_status === 'ok' || j.zustand === 'ok').length;
  $('#betriebTag').textContent = `${jobs.length} Jobs · ${d.ok ? 'keine kritische Warnung' : 'Warnung'}`;
  $('#betriebKpis').innerHTML = [
    ['Takt', laufend, `zuletzt ${betriebZeit(t.letzter)} · ${num(t.dauer_ms,0)} ms`],
    ['Jobs', `${num(okJobs,0)} / ${num(jobs.length,0)}`, `${num(st.gesamt,0)} Läufe in 24 h`],
    ['Datenbank', `${num(res.db_mb,1)} MB`, `Limit ${num(lim.max_db_mb,0)} MB · ${num(res.freier_speicher_mb,0)} MB frei`],
    ['Fehler', num(st.fehler,0), `${num(st.uebersprungen,0)} wegen Grenzen übersprungen`],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  $('#betriebJobs').innerHTML = jobs.length ? `<table class="tbl"><thead><tr>
    <th>Job</th><th>Zustand</th><th class="m">Intervall</th><th class="m">Nächster Versuch</th><th class="m">Fehler</th><th>Letzter Erfolg</th></tr></thead><tbody>
    ${jobs.map(j=>`<tr><td>${esc(j.titel || j.name)}<small>${esc(j.name)}${j.ressourcen_intensiv ? ' · ressourcenintensiv' : ''}${j.fehlschluesse ? `<span class="betrieb-fehler-mobil"> · ${num(j.fehlschluesse,0)} Fehler</span>` : ''}</small></td>
      <td><span class="pill ${betriebPill(j.zustand)}">${esc(j.zustand)}</span></td>
      <td class="m">${esc(betriebDauer(j.intervall_sekunden))}</td>
      <td class="m">${betriebZeit(j.naechster_versuch)}</td>
      <td class="m">${num(j.fehlschluesse,0)}${j.backoff_sekunden ? ' · ' + esc(betriebDauer(j.backoff_sekunden)) : ''}</td>
      <td>${betriebZeit(j.letzter_erfolg)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Keine Jobs im Plan.</div>';

  $('#betriebRes').innerHTML = `<table class="tbl tblKey"><tbody>
    <tr><td>Datenbank</td><td class="m">${num(res.db_mb,2)} / ${num(lim.max_db_mb,0)} MB</td><td>${betriebMeter(res.db_mb, lim.max_db_mb)}</td></tr>
    <tr><td>Prozess-RSS</td><td class="m">${res.rss_mb == null ? 'nicht messbar' : num(res.rss_mb,1) + ' / ' + num(lim.max_rss_mb,0) + ' MB'}</td><td>${res.rss_mb == null ? '<span class="na">–</span>' : betriebMeter(res.rss_mb, lim.max_rss_mb)}</td></tr>
    <tr><td>Freier Speicher</td><td class="m">${num(res.freier_speicher_mb,0)} MB frei<span class="betrieb-mobil"> · Min. ${num(lim.min_freier_speicher_mb,0)} MB</span></td><td><span class="na">Minimum ${num(lim.min_freier_speicher_mb,0)} MB</span></td></tr>
    <tr><td>Taktbudget</td><td class="m">${num(lim.max_takt_sekunden,0)} s<span class="betrieb-mobil"> · Obergrenze</span></td><td><span class="na">danach werden weitere Jobs verschoben</span></td></tr>
    </tbody></table>`;

  const log = d.letzte_laeufe || [];
  $('#betriebLog').innerHTML = log.length ? log.map(e=>`<div class="li"><span><b>${esc(e.job)}</b>
    <small>${betriebZeit(e.zeit)} · ${num(e.dauer_ms,0)} ms${e.fehler ? ' · ' + esc(e.fehler) : ''}</small></span>
    <span class="pill ${e.status === 'ok' ? '' : e.status === 'fehler' ? 'r' : 'w'}">${esc(e.status)}</span></div>`).join('')
    : '<div class="empty">Noch kein Job-Lauf protokolliert.</div>';

  const warnungen = d.warnungen || [];
  $('#betriebHinweise').innerHTML = warnungen.length ? warnungen.map(w=>
    `<div class="betrieb-note"><span class="pill ${w.stufe === 'fehler' ? 'r' : w.stufe === 'info' ? 'g' : 'w'}">${esc(w.stufe)}</span>
      <span>${esc(w.text)}</span></div>`).join('')
    : '<div class="empty">Keine Warnungen. Der Takt hat alle fälligen Jobs ohne Grenzüberschreitung ausgeführt.</div>';
}

const betriebRefreshBtn = $('#betriebRefresh');
if(betriebRefreshBtn) betriebRefreshBtn.onclick = () => ladeBetrieb();

/* ---------- Raumschiff ---------- */
const DECK_A = ['A','B','E','C'];
const DECK_B = ['D','F','G','H'];

function companyAbteilung(k){
  return ((companyDaten && companyDaten.overview && companyDaten.overview.abteilungen) || [])
    .find(d => d.code === k) || null;
}

function companyAgentenDept(k){
  return ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [])
    .filter(a => a.dept === k);
}

function hatCompanyDaten(){
  return !!(companyDaten && companyDaten.agents && Number(companyDaten.agents.gesamt) > 0);
}

function shipRaum(k, breit, proAbteilung){
  const liste = proAbteilung[k] || [];
  const befunde = liste.filter(r=>!r.ok).length;
  const on = k === depSel;
  const company = hatCompanyDaten();
  const cdept = companyAbteilung(k);
  const cagenten = companyAgentenDept(k);
  const offen = company && cdept ? Number(cdept.offen) || 0 : 0;
  const laeuft = company && cdept ? Number(cdept.laeuft) || 0 : 0;
  const blockiert = company && cdept ? Number(cdept.blockiert) || 0 : 0;
  const zustand = company ? (blockiert ? 'befund' : 'ok')
    : (liste.length ? (befunde ? 'befund' : 'ok') : 'leer');
  const anzahl = company ? cagenten.length : liste.length;
  const meta = company
    ? `${anzahl} Agenten · ${offen} offen${laeuft ? ` · ${laeuft} läuft` : ''}${blockiert ? ` · ${blockiert} blockiert` : ''}`
    : (liste.length ? `${liste.length} Agenten` : 'KEINE DATEN') + (befunde ? ` · ${befunde} Befund` : '');
  const punkte = company
    ? cagenten.slice(0,10).map(a=>`<i class="${a.status==='blockiert'?'warn':a.status==='laeuft'?'ok':a.status==='wartet'?'wait':'free'}"></i>`).join('')
    : liste.slice(0,10).map(r=>`<i class="${r.ok?'ok':'warn'}"></i>`).join('');
  const aria = company
    ? `${anzahl} Agenten, ${offen} offen${blockiert?`, ${blockiert} blockiert`:''}`
    : `${liste.length} Agenten${befunde?`, ${befunde} Befund`:''}`;
  return `<button class="ship-room is-${zustand}${on?' on':''}${breit?' is-wide':''}" data-d="${k}" aria-pressed="${on?'true':'false'}"
    aria-label="${esc(DEP[k])}: ${aria}">
    <span class="ship-room-code">${k}</span>
    <span class="ship-room-name">${esc(DEP[k])}</span>
    <span class="ship-room-meta">${meta}</span>
    <span class="dots">${punkte}</span>
  </button>`;
}

let sekAktiv = 'S1', sekDaten = null;

async function ladeSekretariat(){
  try{
    const r = await fetch('/api/sekretariat', {cache:'no-store'});
    sekDaten = await r.json();
  }catch(e){
    sekDaten = null;
  }
  renderSekretariat();
}

function dauerText(min){
  if(min === null || min === undefined || isNaN(Number(min))) return 'unbekannt';
  const m = Number(min);
  if(m < 60) return `${m} Min.`;
  if(m < 1440) return `${Math.round(m / 60)} Std.`;
  return `${Math.round(m / 1440)} Tage`;
}

let agSuche = '', agEntscheid = '', agArt = '';

function renderAgenda(){
  const box = $('#sekAgenda');
  if(!box) return;
  const a = sekDaten && sekDaten.agenda;
  if(!a || !a.themen || !a.themen.length){
    box.innerHTML = '<div class="empty">Noch keine Agenda gesammelt.</div>';
    return;
  }
  if(!$('#agListe')){
    box.innerHTML = `<div class="sekStand" id="agZahl"></div>
      <div class="protoTools">
        <input id="agSuche" placeholder="Agenda durchsuchen …">
        <select id="agEntscheid">
          ${[['', 'alle Entscheide'], ['offen', 'offen'], ['vertagt', 'vertagt']]
            .map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
        </select>
        <select id="agArt">
          ${[['', 'alle Arten'], ['muster', 'Muster'], ['verlust', 'Verlust'], ['gewinn', 'Gewinn'], ['befund', 'Befund'], ['fehler', 'Fehler'], ['beschluss', 'Beschluss']]
            .map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
        </select>
      </div>
      <div id="agListe"></div>`;
    $('#agSuche').oninput = () => { agSuche = $('#agSuche').value; agendaListe(); };
    $('#agEntscheid').onchange = () => { agEntscheid = $('#agEntscheid').value; agendaListe(); };
    $('#agArt').onchange = () => { agArt = $('#agArt').value; agendaListe(); };
  }
  $('#agSuche').value = agSuche;
  $('#agEntscheid').value = agEntscheid;
  $('#agArt').value = agArt;
  agendaListe();
}

function agendaListe(){
  const box = $('#agListe');
  const a = sekDaten && sekDaten.agenda;
  if(!box || !a) return;
  const namen = {'S1': 'Mira', 'S2': 'Jonas', 'S3': 'Lea'};
  const text = (agSuche || '').trim().toLowerCase();
  const themen = a.themen.filter(t => {
    if(agEntscheid === 'vertagt' && !t.vertagt) return false;
    if(agEntscheid === 'offen' && t.vertagt) return false;
    if(agArt && t.art !== agArt) return false;
    if(!text) return true;
    return [t.thema, t.gemacht, t.besser, t.gelernt, t.ausstieg_grund]
      .join(' ').toLowerCase().includes(text);
  });
  const zahl = $('#agZahl');
  if(zahl){
    const namenArt = {muster: 'Muster', verlust: 'Verlust', gewinn: 'Gewinn',
      befund: 'Befund', fehler: 'Fehler', beschluss: 'Beschluss'};
    const verteilung = {};
    a.themen.forEach(t => { const k = t.art || 'sonstig'; verteilung[k] = (verteilung[k] || 0) + 1; });
    const textArt = Object.entries(verteilung)
      .map(([k, n]) => (namenArt[k] || k) + ' ' + n).join(' · ');
    const vorlauf = a.termin_tage
      ? ' · Termin-Vorlauf ' + a.termin_tage + (a.termin_tage === 1 ? ' Tag' : ' Tage') : '';
    zahl.textContent = kurzZeit(a.zeit) + ' · ' + themen.length + ' / ' + a.themen.length +
      ' Themen · ' + textArt + vorlauf;
  }
  box.innerHTML = themen.map(t => `
    <div class="sekThema">
      <small>${esc(namen[t.leiter] || t.leiter)} leitet · ${esc(t.art)}${t.termin ? ' · Termin ' + esc(t.termin) : ''}${t.vertagt ? ' · vertagt' : ''}</small>
      <b>${esc(t.thema)}</b>
      <span><i>Gemacht</i>${esc(t.gemacht)}</span>
      ${t.dauer_minuten !== undefined && t.dauer_minuten !== null ? `<span><i>Dauer</i>${esc(dauerText(t.dauer_minuten))}</span>` : ''}
      ${t.ausstieg_grund ? `<span><i>Ausstieg</i>${esc(t.ausstieg_grund)}</span>` : ''}
      ${t.trades && t.trades.length ? `<span><i>Trades</i>${t.trades.length}</span>` : ''}
      <span><i>Besser</i>${esc(t.besser)}</span>
      <span><i>Gelernt</i>${esc(t.gelernt)}</span>
    </div>`).join('') + (themen.length ? '' : '<div class="empty">Kein Thema passt zu Suche und Filter.</div>');
}

function renderSekretariat(){
  const box = $('#sekTabs');
  if(!box) return;
  const sekt = (sekDaten && sekDaten.sekretaere) || [];
  box.innerHTML = sekt.map(s=>`<button type="button" class="${s.id===sekAktiv?'on':''}" data-sek="${s.id}">${esc(s.name)} · ${esc(s.rolle)}</button>`).join('');
  box.querySelectorAll('[data-sek]').forEach(b=>b.onclick=()=>{ sekAktiv = b.dataset.sek; renderSekretariat(); });
  renderAgenda();
  const th = $('#sekThread');
  if(!th) return;
  const verlauf = ((sekDaten && sekDaten.chat) || []).filter(m=>m.sekretaer===sekAktiv);
  th.innerHTML = verlauf.length ? verlauf.map(m=>{
    const name = (sekt.find(s=>s.id===m.sekretaer)||{}).name || 'SEKRETARIAT';
    return `<div class="sekMsg ich"><small>DU · ${esc(kurzZeit(m.zeit))}</small>${esc(m.frage)}</div>
      <div class="sekMsg"><small>${esc(name)} · ${esc(kurzZeit(m.zeit))}</small>${esc(m.antwort)}</div>`;
  }).join('') : '<div class="empty">Noch kein Gespräch. Frag nach Befunden, Artikeln, Konferenz, Konto oder Status.</div>';
  th.scrollTop = th.scrollHeight;
  const inp = $('#sekInput');
  if(inp) inp.placeholder = `Frage an ${(sekt.find(s=>s.id===sekAktiv)||{}).name || 'Sekretariat'} …`;
}

$('#sekAgendaBtn') && ($('#sekAgendaBtn').onclick = async () => {
  const btn = $('#sekAgendaBtn');
  btn.disabled = true;
  try{
    const r = await fetch('/api/sekretariat/agenda', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Agenda fehlgeschlagen');
    sekDaten = {...(sekDaten || {}), agenda: {zeit: d.zeit, themen: d.themen}};
    renderAgenda();
    toast('Agenda gesammelt: ' + ((d.themen || []).length) + ' Themen.');
  }catch(err){
    const box = $('#sekAgenda');
    if(box) box.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(err.message)}</div>`);
    toast('Agenda fehlgeschlagen.');
  }finally{
    btn.disabled = false;
  }
});

$('#sekForm') && ($('#sekForm').onsubmit = async e => {
  e.preventDefault();
  const inp = $('#sekInput');
  const text = (inp.value || '').trim();
  if(!text) return;
  inp.value = '';
  try{
    const r = await fetch('/api/sekretariat/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sekretaer: sekAktiv, text})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Antwort fehlgeschlagen');
    sekDaten = {...(sekDaten || {}), chat: d.verlauf};
    renderSekretariat();
  }catch(err){
    const th = $('#sekThread');
    if(th) th.insertAdjacentHTML('beforeend', `<div class="sekMsg"><small>FEHLER</small>${esc(err.message)}</div>`);
  }
});

function renderCEO(runs){
  const box = $('#deckC');
  if(!box) return;
  const konto = (R.paper && R.paper.konto) || {};
  const konf = R.konferenz || {};
  const markt = (R.markt && R.markt.symbole) || [];
  const sp = R.spider || {};
  const befunde = runs.filter(r=>!r.ok).length;
  const cash = Number.isFinite(Number(konto.cash)) ? num(konto.cash, 0) : null;
  const meldungen = runs.slice(-3).reverse();
  box.innerHTML = `
    <div class="exec-room">
      <span class="exec-code">CEO</span>
      <b>Büro · Gianluca</b>
      <div class="exec-kpis">
        <span><small>KONTO</small>${cash !== null ? cash : '–'}</span>
        <span><small>LÄUFE</small>${runs.length || 0}</span>
        <span><small>BEFUNDE</small>${befunde}</span>
      </div>
      <small class="exec-note">Paper only · keine Broker-Orders</small>
    </div>
    <div class="exec-room">
      <span class="exec-code">SEC</span>
      <b>Empfang &amp; Sekretariat</b>
      <div class="exec-list">${meldungen.length ? meldungen.map(r=>`<span><b>${esc((r.agent||'').split(':')[1] || r.agent)}</b><small>${esc(r.ergebnis)}</small></span>`).join('') : '<span class="exec-empty">KEINE MELDUNGEN</span>'}</div>
    </div>
    <div class="exec-room">
      <span class="exec-code">BRD</span>
      <b>Privater Besprechungsraum</b>
      <div class="exec-list">
        <span><b>Letzte Konferenz</b><small>${konf.zeit ? kurzZeit(konf.zeit) : 'KEINE DATEN'}</small></span>
        <span><b>Beschluss</b><small>${esc(konf.beschluss || 'KEINE DATEN')}</small></span>
      </div>
    </div>
    <div class="exec-room exec-obs">
      <span class="exec-code">OBS</span>
      <b>Lounge &amp; Beobachtungsdeck</b>
      <div class="exec-stars" aria-hidden="true"></div>
      <div class="exec-list">
        <span><b>Märkte</b><small>${markt.length} Symbole</small></span>
        <span><b>Spinne</b><small>${sp.stand ? 'Abruf ' + kurzZeit(sp.stand) : 'KEINE DATEN'}</small></span>
      </div>
    </div>`;
}

function proAbteilungAusRuns(){
  const runs = (R && R.agenten) || [];
  const proAbteilung = {};
  runs.forEach(r => { (proAbteilung[r.abteilung] = proAbteilung[r.abteilung] || []).push(r); });
  return proAbteilung;
}

function renderDeckRooms(){
  const proAbteilung = proAbteilungAusRuns();
  $('#deckA').innerHTML = DECK_A.map(k=>shipRaum(k, false, proAbteilung)).join('');
  $('#deckB').innerHTML = DECK_B.map(k=>shipRaum(k, k==='D', proAbteilung)).join('');
  document.querySelectorAll('#v-ship .ship-room').forEach(b => b.onclick = () => { depSel = b.dataset.d; renderShip(); });
}

async function ladeCompany(){
  if(companyLaden) return;
  companyLaden = true;
  try{
    const antworten = await Promise.all([
      fetch('/api/company/overview', {cache:'no-store'}),
      fetch('/api/company/agents', {cache:'no-store'}),
      fetch('/api/company/tasks?limit=12', {cache:'no-store'}),
    ]);
    if(antworten.some(r => !r.ok)) throw new Error('HTTP ' + antworten.find(r => !r.ok).status);
    const [overview, agents, tasks] = await Promise.all(antworten.map(r=>r.json()));
    companyDaten = {overview, agents, tasks};
    companyFehler = null;
  }catch(e){
    companyDaten = null;
    companyFehler = String((e && e.message) || e);
  }finally{
    companyLaden = false;
  }
  renderCompany();
}

function renderCompany(){
  if(!$('#companyPanel')) return;
  renderShipWorld();
  const detail = $('#shipModeDetail'), tag = $('#companyTag');
  const kpis = $('#companyKpis'), liste = $('#companyTasks'), taskTag = $('#companyTaskTag');
  if(!companyDaten){
    if(detail) detail.textContent = companyFehler ? 'Company-API nicht erreichbar' : 'Company-API wird geladen …';
    if(tag) tag.textContent = companyFehler ? 'API-FEHLER' : 'lädt';
    if(taskTag) taskTag.textContent = '–';
    if(kpis) kpis.innerHTML = `<div class="kpi"><div class="l">Company-API</div><div class="v">–</div><div class="n">${companyFehler?esc(companyFehler):'wird geladen'}</div></div>`;
    if(liste) liste.innerHTML = `<div class="empty">${companyFehler?'Company-API nicht erreichbar.':'Offene Aufgaben werden geladen …'}</div>`;
    return;
  }
  const o = companyDaten.overview || {}, a = companyDaten.agents || {}, t = companyDaten.tasks || {};
  const s = o.agenten_status || {}, p = o.profile || {};
  const offen = Number((o.aufgaben && o.aufgaben.offen) || 0);
  const agenten = Number(a.gesamt || p.gesamt || 0);
  if(detail) detail.textContent = `${agenten} Agenten · ${s.aktiv||0} aktiv · ${s.blockiert||0} blockiert · ${offen} offen`;
  if(tag) tag.textContent = o.data_state === 'empty' ? 'keine Daten' : `live · ${kurzZeit(o.generated_at) || 'Stand unbekannt'}`;
  if(kpis) kpis.innerHTML = [
    ['Agenten', agenten, `${s.frei||0} frei`],
    ['aktiv', s.aktiv||0, 'laufende Aufgaben'],
    ['blockiert', s.blockiert||0, 'brauchen Aufmerksamkeit'],
    ['offene Aufgaben', offen, `${s.wartend||0} wartend`],
  ].map(([l,v,n])=>`<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="n">${n}</div></div>`).join('');
  const aufgaben = t.aufgaben || [];
  if(taskTag) taskTag.textContent = `${Number(t.gesamt)||0} offen${aufgaben.length < (Number(t.gesamt)||0) ? ` · ${aufgaben.length} gezeigt` : ''}`;
  if(liste) liste.innerHTML = aufgaben.length ? aufgaben.map(task=>{
    const pill = task.state === 'blocked' ? 'r' : task.state === 'running' ? 'b' : 'w';
    const frist = task.due_at ? ` · fällig ${kurzZeit(task.due_at)}` : '';
    return `<div class="li"><span><b>${esc(task.title)}</b><small>${esc(task.rufname||task.assigned_to)} · ${esc(task.dept_name||task.dept)} · ${esc(task.state_text)}${frist}</small></span><span class="pill ${pill}">${esc(task.state_text)}</span></div>`;
  }).join('') : '<div class="empty">Keine offenen Aufgaben.</div>';
}

function renderAbteilung(){
  const proAbteilung = proAbteilungAusRuns();
  const meine = proAbteilung[depSel] || [];
  const company = hatCompanyDaten();
  const cagenten = companyAgentenDept(depSel);
  if(company && cagenten.length){
    const offen = cagenten.reduce((n,a)=>n+(Number(a.offene_aufgaben)||0), 0);
    const laeuft = cagenten.filter(a=>a.status==='laeuft').length;
    $('#roomTag').textContent = `${cagenten.length} Agenten · ${offen} offen${laeuft?` · ${laeuft} läuft`:''}`;
    $('#roomAgents').innerHTML = cagenten.map(a=>{
      const pill = a.status==='blockiert'?'r':a.status==='laeuft'?'b':a.status==='wartet'?'w':'g';
      const letzte = a.letzte_task && a.letzte_task.title && a.letzte_task.title !== a.role ? a.letzte_task.title : '';
      const teile = [esc(a.role)];
      if(a.offene_aufgaben) teile.push(`${a.offene_aufgaben} offen`);
      if(letzte) teile.push(esc(letzte));
      return `<div class="li"><span><b>${esc(a.rufname)}</b><small>${teile.join(' · ')}</small></span><span class="pill ${pill}">${esc(a.status_text)}</span></div>`;
    }).join('');
  }else{
    $('#roomTag').textContent = `${meine.length} Agenten · ${meine.filter(r=>r.ok).length} ohne Befund`;
    $('#roomAgents').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b>${esc((r.agent||'').split(':')[1]||r.agent)}</b>
      <small>${esc(r.aufgabe)}</small></span><span class="pill ${r.ok?'':'r'}">${r.ok?'OK':'BEFUND'}</span></div>`).join('')
      : '<div class="empty">Noch kein Lauf für diese Abteilung.</div>';
  }
  $('#roomRuns').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b style="font-weight:400">${esc(r.ergebnis)}</b>
    <small>${esc((r.agent||'').split(':')[1]||r.agent)}</small></span></div>`).join('')
    : '<div class="empty">Keine Rohrpost.</div>';
}

function renderShip(){
  if(!companyDaten && !companyLaden) ladeCompany();
  renderCompany();
  ladeSekretariat();
  ladeSitzung();
  if(!shipZoomInit) requestAnimationFrame(fitShip);
}

/* ---------- Agenten-Querschnitt: 103 Räume ---------- */
const SHIP_FARBEN = ['#38e8ff','#ff3fa4','#ffb84d','#9b6cff','#55e6a5','#ff7a59','#5aa9ff','#ff5edb','#c6ff5e','#ff9f43','#74ffd0'];

const SHIP_DEPT_NAMEN = { A:'Hauptzentrale', B:'Spider Intelligence', C:'Labor', D:'Trading Floor',
  E:'Forschungsabteilung', F:'Risikomanagement', G:'Wissenszentrum', H:'Entwicklungsabteilung',
  I:'Globale Intelligence', J:'Sicherheit', S:'Executive-Sekretariat' };

function shipDeptList(){
  const o = (companyDaten && companyDaten.overview) || {};
  const agenten = (companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [];
  const depts = (o.abteilungen || []).slice();
  const seen = new Set(depts.map(d => d.code));
  agenten.forEach(a => {
    if(!seen.has(a.dept)){
      seen.add(a.dept);
      depts.push({ code:a.dept, name:a.dept_name || a.dept, agenten:0 });
    }
  });
  return depts.sort((a,b) => (a.code === 'S' ? 999 : a.code.charCodeAt(0)) - (b.code === 'S' ? 999 : b.code.charCodeAt(0)))
    .map(d => ({ ...d, name:SHIP_DEPT_NAMEN[d.code] || d.name, liste: agenten.filter(a => a.dept === d.code) }));
}

function shipStatusKey(a){
  return a.status === 'laeuft' ? 'laeuft' : a.status === 'blockiert' ? 'blockiert' : a.status === 'wartet' ? 'wartet' : 'frei';
}

const SHIP_ROOM_TYPEN = { A:'command', B:'server', C:'lab', D:'trading', E:'research', F:'risk',
  G:'archive', H:'workshop', I:'observatory', J:'security', S:'meeting' };

function shipDeptFarbe(code){
  const depts = shipDeptList();
  const i = depts.findIndex(d => d.code === code);
  return SHIP_FARBEN[(i >= 0 ? i : 0) % SHIP_FARBEN.length];
}

function shipDeptKnoepfe(depts, kompakt = false, filter = false){
  const titel = filter ? 'Abteilung im Schiff hervorheben' : 'Ersten Agenten dieser Abteilung öffnen';
  const gedrueckt = filter ? ' aria-controls="shipWorld" aria-pressed="false"' : '';
  return `<div class="sd-depts${kompakt ? ' sd-legend' : ''}">${depts.map(d => `<button type="button" class="sd-dept" data-dept="${esc(d.code)}" style="--dept:${shipDeptFarbe(d.code)}" title="${titel}"${gedrueckt}>
    <span class="sw"></span><b>${esc(d.code)} · ${esc(d.name)}</b><small>${d.liste.length}</small></button>`).join('')}</div>`;
}

function bindeShipDeptKnoepfe(side, agenten){
  side.querySelectorAll('[data-dept]').forEach(b => b.onclick = () => {
    const a = agenten.find(x => x.dept === b.dataset.dept);
    if(a) setShipSelection('agent', a.agent_id);
  });
}

function shipGewaehlteAbteilung(){
  if(shipDeptFilter) return shipDeptFilter;
  if(shipAuswahl.typ !== 'agent') return null;
  const raum = [...document.querySelectorAll('#shipWorld [data-agent]')]
    .find(b => b.dataset.agent === shipAuswahl.id);
  return raum?.closest('.px-dept')?.dataset.dept || null;
}

function syncShipDeptFilter(){
  const world = $('#shipWorld');
  const legend = $('#shipLegend');
  const depts = world ? [...world.querySelectorAll('.px-dept')] : [];
  if(shipDeptFilter && !depts.some(el => el.dataset.dept === shipDeptFilter)) shipDeptFilter = null;
  const aktiv = shipDeptFilter;
  const gewaehlt = shipGewaehlteAbteilung();
  if(world){
    world.classList.toggle('filter-aktiv', !!aktiv);
    depts.forEach(el => el.classList.toggle('is-filter-active', !!aktiv && el.dataset.dept === aktiv));
  }
  if(legend){
    legend.querySelectorAll('[data-dept]').forEach(b => {
      const on = !!aktiv && b.dataset.dept === aktiv;
      b.classList.toggle('is-active', on);
      b.classList.toggle('is-selected', !on && !!gewaehlt && b.dataset.dept === gewaehlt);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.title = on ? 'Filter lösen' : 'Abteilung im Schiff hervorheben';
    });
  }
}

function setShipDeptFilter(code){
  shipDeptFilter = shipDeptFilter === code ? null : code;
  syncShipDeptFilter();
}

function bindeShipFilterKnoepfe(box){
  box.querySelectorAll('[data-dept]').forEach(b => {
    b.onclick = () => setShipDeptFilter(b.dataset.dept);
  });
}

function syncShipLegend(){
  const box = $('#shipLegend');
  if(!box) return;
  const schmal = window.matchMedia('(max-width:760px)').matches;
  const zustand = String(schmal);
  if(box.dataset.schmal !== zustand){
    box.open = !schmal;
    box.dataset.schmal = zustand;
  }
}

function renderShipLegend(depts, agenten){
  const box = $('#shipLegend');
  if(!box) return;
  box.hidden = false;
  box.innerHTML = `<summary class="sl-head"><small>SEKTOREN · FILTER</small><b>${depts.length} ABTEILUNGEN</b><i class="sl-pfeil" aria-hidden="true"></i></summary>${shipDeptKnoepfe(depts, true, true)}`;
  syncShipLegend();
  bindeShipFilterKnoepfe(box);
  syncShipDeptFilter();
}

/* ---------- Pixel-Raumschiff: Querschnitt im Pixel-Art-Stil ---------- */
const PX = 3;                       // 1 Kunst-Pixel = 3 Bildschirm-Pixel
let pxRaeume = [], pxTakt = 0, pxTimer = null;
const PX_HAUT = ['#f4cfa6','#e2ad7f','#c88a58','#91603c','#5e3b25'];
const PX_HAAR = ['#2b1b12','#5a3a1e','#d6a94e','#141414','#a0522d','#e9e2d4','#ff5fb0','#3fd0ff','#7b4bff'];
const PX_HOSE = ['#24223a','#1d2b3c','#30263a','#262626'];
const PX_BODEN = { command:'#2f3a52', server:'#2a2e3c', lab:'#d9d9e4', trading:'#3a2f4d', research:'#4a3a30',
  risk:'#3d2a30', archive:'#5a4330', workshop:'#3a3a3a', observatory:'#232a44', security:'#2d2a2a', meeting:'#4b2f3d' };
const PX_MUSTER = [[3,2,3,2,2],[2,3,2,2,3],[2,2,3,3,2],[3,3,2,2,2],[2,3,3,2,2]];

function pxHash(s){ let h = 2166136261; for(const c of String(s)){ h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
function pxRng(seed){ let s = (seed >>> 0) || 7; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return (s % 100000) / 100000; }; }
function pxN(a, b, c){ let h = (a * 374761393 + b * 668265263 + c * 1442695041) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return (h ^ (h >>> 16)) >>> 0; }
function pxMix(a, b, f){
  const p = h => [1,3,5].map(i => parseInt(h.slice(i, i+2), 16));
  const x = p(a), y = p(b);
  return '#' + x.map((v,i) => Math.round(v + (y[i]-v) * f).toString(16).padStart(2,'0')).join('');
}
function pxPinsel(ctx){
  return {
    ctx,
    r(x, y, w, h, c){ if(w <= 0 || h <= 0) return; ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); },
    p(x, y, c){ ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), 1, 1); },
    a(alpha, fn){ ctx.globalAlpha = alpha; fn(); ctx.globalAlpha = 1; },
  };
}

/* ---- Bausteine ---- */
function pxHuelle(g, w, h, farbe, typ, rng){
  const fy = h - 7;
  const wand = pxMix('#2e2a4a', farbe, .2), dunkel = pxMix(wand, '#000000', .38), hell = pxMix(wand, '#ffffff', .09);
  g.r(0, 0, w, h, wand);
  const schritt = 9 + Math.floor(rng() * 4);
  for(let x = 3 + Math.floor(rng() * schritt); x < w; x += schritt){ g.r(x, 4, 1, fy - 7, dunkel); g.r(x + 1, 4, 1, fy - 7, hell); }
  g.r(0, fy - 3, w, 1, hell); g.r(0, fy - 2, w, 2, dunkel);
  g.r(0, 0, w, 3, '#0a0812'); g.r(0, 3, w, 1, pxMix(farbe, '#000000', .5));
  for(let x = 2; x < w; x += 7) g.p(x, 1, '#2a2638');
  const boden = PX_BODEN[typ] || '#3b3448';
  g.r(0, fy, w, h - fy, boden); g.r(0, fy, w, 1, pxMix(boden, '#ffffff', .28));
  for(let x = Math.floor(rng() * 6); x < w; x += 6) g.r(x, fy + 2 + ((x / 6) & 1) * 2, 1, 2, pxMix(boden, '#000000', .28));
  g.r(0, h - 1, w, 1, '#06050a');
  return fy;
}
function pxLampe(g, x, fy, farbe){
  g.r(x - 3, 3, 7, 1, '#fff4d6'); g.r(x - 2, 4, 5, 1, pxMix('#fff4d6', farbe, .4));
  g.a(.11, () => { const c = g.ctx; c.fillStyle = '#fff4d6'; c.beginPath(); c.moveTo(x - 3, 5); c.lineTo(x + 4, 5); c.lineTo(x + 13, fy); c.lineTo(x - 12, fy); c.fill(); });
}
function pxFenster(g, x, y, w, h, rng){
  g.r(x - 1, y - 1, w + 2, h + 2, '#59627a'); g.r(x, y, w, h, '#0b0f2c');
  g.r(x, y + h - 2, w, 2, '#2a1550');
  for(let i = 0; i < 4; i++) g.p(x + Math.floor(rng() * w), y + Math.floor(rng() * (h - 1)), i ? '#9fb4ff' : '#ffffff');
  g.p(x + Math.floor(rng() * w), y + h - 2, '#ff5fc8');
}
function pxTisch(g, x, y, w, fy, farbe){
  g.r(x, y, w, 1, '#a99cba'); g.r(x, y + 1, w, 2, '#4a4058'); g.r(x, y + 1, w, 1, pxMix(farbe, '#000000', .25));
  g.r(x + 1, y + 3, 1, fy - y - 3, '#2a2433'); g.r(x + w - 2, y + 3, 1, fy - y - 3, '#2a2433');
}
function pxStuhl(g, x, fy){
  g.r(x, fy - 9, 1, 6, '#3b3550'); g.r(x, fy - 4, 4, 1, '#4d4666'); g.r(x + 2, fy - 3, 1, 2, '#2a2433'); g.r(x + 1, fy - 1, 3, 1, '#1b1825');
}
function pxMonitor(g, x, y, w, h, farbe, t, an, art){
  g.r(x - 1, y - 1, w + 2, h + 2, '#0c0c13');
  g.r(x, y, w, h, an ? pxMix(farbe, '#000000', .62) : '#11141f');
  g.r(x + Math.floor(w / 2), y + h + 1, 1, 1, '#0c0c13');
  if(!an){ if((t >> 3) % 4 === 0) g.p(x + 1, y + 1, '#2c3348'); return; }
  const hell = pxMix(farbe, '#ffffff', .45);
  if(art === 'kerzen'){
    for(let i = 0; i < w - 1; i += 2){
      const v = pxN(i + (t >> 1), x, 3), hoch = 1 + v % (h - 1), auf = (v >> 4) & 1;
      g.r(x + 1 + i, y + h - hoch, 1, hoch, auf ? '#3dff8f' : '#ff4d6d');
    }
  }else if(art === 'kurve'){
    let yy = y + Math.floor(h / 2);
    for(let i = 0; i < w; i++){ yy += (pxN(i + t, x, 9) % 3) - 1; yy = Math.max(y, Math.min(y + h - 1, yy)); g.p(x + i, yy, '#ff5577'); }
  }else{
    for(let i = 0; i < h - 1; i += 2){ const l = 1 + pxN(x, i, t >> 1) % (w - 1); g.r(x + 1, y + 1 + i, Math.min(l, w - 2), 1, i % 4 ? hell : '#ffffff'); }
  }
}
function pxPflanze(g, x, fy){
  g.r(x, fy - 3, 4, 3, '#8a5a3c'); g.r(x, fy - 3, 4, 1, '#a8704a');
  g.r(x + 1, fy - 7, 2, 4, '#2fae5c'); g.p(x, fy - 6, '#3fd070'); g.p(x + 3, fy - 8, '#3fd070'); g.p(x + 1, fy - 9, '#56e087'); g.p(x + 3, fy - 5, '#249048');
}
function pxBuecher(g, x, y, w, h, rng){
  g.r(x, y, w, h, '#3a2a1e');
  for(let yy = y + 1; yy < y + h - 1; yy += 5){
    g.r(x, yy + 4, w, 1, '#5a4330');
    for(let xx = x + 1; xx < x + w - 1; xx++){
      const c = ['#c94f4f','#4f7fc9','#d6b04a','#4fb08a','#9a5fc9','#e8e0d0'][Math.floor(rng() * 6)];
      const hh = 2 + Math.floor(rng() * 2); if(rng() < .15) continue;
      g.r(xx, yy + 4 - hh, 1, hh, c);
    }
  }
}

/* ---- Figur ---- */
function pxFigur(g, x, fy, look, pose, t, rechts){
  const { haut, haar, hemd, hose } = look;
  const auge = '#140c1c';
  if(pose === 'sitzt'){
    const y = fy - 12, tipp = (t & 1) ? 1 : 0;
    g.r(x + 1, y, 3, 1, haar); g.r(x + 1, y + 1, 3, 2, haut); g.p(x + 1, y + 1, haar); g.p(x + 3, y + 1, auge);
    g.r(x, y + 3, 4, 4, hemd); g.p(x, y + 3, pxMix(hemd, '#000000', .3));
    g.r(x + 4, y + 4 + tipp, 2, 1, hemd); g.p(x + 6, y + 4 + tipp, haut);
    g.r(x + 1, y + 7, 5, 1, hose); g.r(x + 5, y + 8, 1, 3, hose); g.r(x + 5, y + 11, 2, 1, '#0d0b12');
    return;
  }
  const y = fy - 11, schritt = pose === 'geht' ? (t & 1) : 0;
  const bob = pose === 'wartet' && (t % 10 < 5) ? 1 : 0;
  g.r(x + 1, y + bob, 3, 1, haar); g.r(x + 1, y + 1 + bob, 3, 2, haut);
  g.p(rechts ? x + 1 : x + 3, y + 1 + bob, haar); g.p(rechts ? x + 3 : x + 1, y + 1 + bob, auge);
  g.r(x, y + 3, 5, 4, hemd); g.p(x, y + 6, haut); g.p(x + 4, y + 6, haut);
  g.r(x + 1, y + 7, 3, 1, hose);
  if(schritt){ g.r(x, y + 8, 1, 2, hose); g.r(x + 4, y + 8, 1, 2, hose); g.p(x, y + 10, '#0d0b12'); g.p(x + 4, y + 10, '#0d0b12'); }
  else{ g.r(x + 1, y + 8, 1, 2, hose); g.r(x + 3, y + 8, 1, 2, hose); g.p(x + 1, y + 10, '#0d0b12'); g.p(x + 3, y + 10, '#0d0b12'); }
}
function pxBlase(g, x, y, art, t){
  if(art === 'alarm'){
    if(t % 4 >= 2) return;
    g.r(x, y, 5, 6, '#ff3355'); g.r(x + 1, y - 1, 3, 1, '#ff3355'); g.r(x + 1, y + 6, 3, 1, '#ff3355');
    g.r(x + 2, y + 1, 1, 3, '#ffffff'); g.p(x + 2, y + 5, '#ffffff');
  }else{
    g.r(x - 1, y + 1, 7, 4, '#f3ecff'); g.p(x + 1, y + 5, '#f3ecff');
    for(let i = 0; i < 3; i++) g.p(x + i * 2, y + 3, i <= (t >> 1) % 3 ? '#e8a53a' : '#c9bfd8');
  }
}

/* ---- Raumtypen: zeichnen Deko + Arbeitsplatz, geben Stuhlposition zurück ---- */
function pxPlatz(g, dx, tw, fy, farbe, t, an, art, monitore){
  const ty = fy - 6, mw = Math.min(8, Math.floor((tw - 1) / monitore) - 1);
  for(let i = 0; i < monitore; i++) pxMonitor(g, dx + 1 + i * (mw + 2), ty - 7, mw, 5, farbe, t + i * 3, an, art);
  pxTisch(g, dx, ty, tw, fy, farbe);
  pxStuhl(g, dx - 6, fy);
  return dx - 5;
}
const PX_TYP = {
  command(g, w, fy, f, hell, rng, t, an){
    const bw = Math.max(10, Math.floor(w * .38));
    g.r(3, 6, bw, fy - 12, '#06222a'); g.r(3, 6, bw, 1, hell);
    for(let i = 0; i < 6; i++){ const x = 4 + pxN(i, w, 1) % (bw - 2), y = 8 + pxN(i, 2, w) % (fy - 16); g.p(x, y, (t + i) % 6 < 3 ? '#38e8ff' : '#0e5a66'); }
    g.r(3 + Math.floor(bw / 2), fy - 6, 1, 3, '#2a3550');
    const dx = bw + 10;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 2);
  },
  server(g, w, fy, f, hell, rng, t, an){
    const n = w > 46 ? 3 : 2;
    for(let i = 0; i < n; i++){
      const x = 2 + i * 7;
      g.r(x, 6, 6, fy - 6, '#14151e'); g.r(x, 6, 6, 1, '#3c3f56'); g.r(x + 5, 6, 1, fy - 6, '#25273a');
      for(let y = 8; y < fy - 1; y += 2){ g.r(x + 1, y, 4, 1, '#232535'); const z = pxN(i, y, t >> 1) % 3; g.p(x + 1 + pxN(y, i, 7) % 3, y, z === 0 ? '#2bff88' : z === 1 ? hell : '#10301f'); }
    }
    const dx = 2 + n * 7 + 8;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  lab(g, w, fy, f, hell, rng, t, an){
    g.r(3, 6, 6, fy - 9, '#8fb8c8'); g.r(4, 7, 4, fy - 11, pxMix(f, '#0a1a20', .35));
    for(let i = 0; i < 3; i++){ const by = fy - 5 - ((t * 2 + i * 7) % (fy - 12)); g.p(5 + (i % 2) * 2, by, '#e8ffff'); }
    g.r(2, fy - 3, 8, 3, '#545a6e');
    g.r(12, 12, Math.min(14, w - 34), 1, '#7a7f94');
    const farben = ['#3dff8f', '#ff5fc8', '#ffd84d', '#4dc8ff'];
    for(let i = 0; i < Math.floor(Math.min(14, w - 34) / 4); i++){ const x = 13 + i * 4; g.r(x, 9, 2, 3, farben[i % 4]); g.p(x, 8, '#c8d8e8'); }
    const dx = Math.max(20, Math.floor(w * .5));
    const ty = fy - 6; g.r(dx + 2, ty - 4, 2, 4, '#3dff8f'); g.p(dx + 2, ty - 5, '#c8d8e8');
    if(an) g.p(dx + 3, ty - 6 - (t % 3), '#e8ffff');
    pxMonitor(g, dx + 6, ty - 7, Math.min(7, w - dx - 9), 5, f, t, an, 'kurve');
    pxTisch(g, dx, ty, w - dx - 2, fy, f); pxStuhl(g, dx - 6, fy);
    return dx - 5;
  },
  trading(g, w, fy, f, hell, rng, t, an){
    g.r(0, 5, w, 3, '#0b0710');
    for(let x = 0; x < w; x += 2){ const v = pxN(x + t, 5, 1); g.p(x, 6, v % 3 ? '#3dff8f' : '#ff4d6d'); }
    g.r(3, 11, Math.max(8, Math.floor(w * .3)), 9, '#0d0b18'); g.r(3, 11, Math.max(8, Math.floor(w * .3)), 1, hell);
    pxMonitor(g, 4, 13, Math.max(6, Math.floor(w * .3) - 2), 6, '#3dff8f', t + 5, true, 'kerzen');
    const dx = Math.max(16, Math.floor(w * .3) + 10);
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kerzen', w - dx > 24 ? 3 : 2);
  },
  research(g, w, fy, f, hell, rng, t, an){
    pxBuecher(g, 2, 7, 10, fy - 7, rng);
    const dx = Math.max(20, Math.floor(w * .48));
    pxPflanze(g, w - 6, fy);
    return pxPlatz(g, dx, Math.min(14, w - dx - 8), fy, f, t, an, 'code', 1);
  },
  risk(g, w, fy, f, hell, rng, t, an){
    const bw = Math.max(10, Math.floor(w * .34));
    g.r(3, 6, bw, 11, '#1a0a10'); g.r(3, 6, bw, 1, '#ff5577');
    pxMonitor(g, 4, 8, bw - 2, 8, '#ff5577', t, true, 'kurve');
    for(let x = 0; x < w; x += 4){ g.r(x, fy, 2, 1, '#ffcc33'); g.r(x + 2, fy, 2, 1, '#1a1a1a'); }
    const dx = bw + 10;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kurve', 2);
  },
  archive(g, w, fy, f, hell, rng, t, an){
    const bw = Math.floor(w * .5);
    pxBuecher(g, 2, 6, bw, fy - 6, rng);
    const dx = bw + 9;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  workshop(g, w, fy, f, hell, rng, t, an){
    const bw = Math.max(12, Math.floor(w * .42));
    g.r(2, 6, bw, 10, '#3a3f4a');
    for(let x = 3; x < bw; x += 2) for(let y = 7; y < 16; y += 2) g.p(x, y, '#2a2e36');
    g.r(4, 8, 1, 5, '#c0c4cc'); g.r(3, 8, 3, 1, '#c0c4cc'); g.r(8, 9, 4, 1, '#ff9f43'); g.r(10, 8, 1, 4, '#8a8f99');
    g.r(2, fy - 5, bw, 2, '#6a4a2e'); g.r(3, fy - 3, 1, 3, '#3a2a1e'); g.r(bw - 1, fy - 3, 1, 3, '#3a2a1e');
    const ax = Math.floor(bw / 2) + 2, sw = an ? (t % 8 < 4 ? 1 : -1) : 0;
    g.r(ax, fy - 9, 2, 4, '#ffb84d'); g.r(ax + sw, fy - 12, 2, 3, '#ffb84d'); g.r(ax + sw * 2 - 1, fy - 13, 4, 1, '#d0d4dc');
    if(an && t % 3 === 0) g.p(ax + sw * 2, fy - 6, '#ffffff');
    const dx = bw + 10;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  observatory(g, w, fy, f, hell, rng, t, an){
    const cx = 9, cy = 12, r = 6;
    for(let y = -r - 1; y <= r + 1; y++) for(let x = -r - 1; x <= r + 1; x++){
      const d = x * x + y * y;
      if(d <= r * r) g.p(cx + x, cy + y, '#0a0c2a');
      else if(d <= (r + 1) * (r + 1) + 2) g.p(cx + x, cy + y, '#6a7390');
    }
    g.r(cx + 1, cy, 3, 3, '#7b4bff'); g.p(cx + 1, cy, '#b39bff'); g.p(cx - 3, cy - 3, '#ffffff'); g.p(cx - 1, cy + 4, '#9fb4ff');
    if((t >> 2) % 5 === 0) g.p(cx + 4, cy - 4, '#ffffff');
    g.r(19, fy - 10, 6, 2, '#c0c4cc'); g.p(18, fy - 11, '#38e8ff'); g.r(21, fy - 8, 1, 5, '#555b6e'); g.p(19, fy - 3, '#555b6e'); g.p(23, fy - 3, '#555b6e');
    const dx = Math.max(31, Math.floor(w * .55));
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  security(g, w, fy, f, hell, rng, t, an){
    const sp = w > 46 ? 3 : 2;
    for(let i = 0; i < sp; i++) for(let j = 0; j < 2; j++){
      const x = 3 + i * 7, y = 6 + j * 6;
      g.r(x, y, 6, 5, '#0b0b10'); g.r(x + 1, y + 1, 4, 3, (pxN(i, j, t >> 2) % 7) ? '#2a3a3a' : '#5a7a7a');
      g.p(x + 1 + pxN(i, j, t) % 4, y + 2, '#9fffe0');
    }
    g.r(3, fy - 9, 5, 9, '#3a4050'); g.r(8, fy - 9, 5, 9, '#343a48'); g.p(7, fy - 5, '#c0c4cc'); g.p(12, fy - 5, '#c0c4cc');
    const dx = 3 + sp * 7 + 8;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  meeting(g, w, fy, f, hell, rng, t, an){
    g.r(4, 7, 12, 8, '#d6a94e'); g.r(5, 8, 10, 6, '#2a1a40'); g.r(6, 11, 4, 3, '#ff5fc8'); g.r(10, 9, 4, 5, '#38e8ff');
    pxPflanze(g, 3, fy);
    const dx = Math.max(24, Math.floor(w * .45));
    const s = pxPlatz(g, dx, Math.min(22, w - dx - 3), fy, '#d6a94e', t, an, 'code', 2);
    g.r(dx, fy - 6, Math.min(22, w - dx - 3), 1, '#ffd98a');
    return s;
  },
};

/* ---- Ein Agentenraum ---- */
function pxAgentRaum(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const typ = e.typ in PX_TYP ? e.typ : 'command';
  const fy = pxHuelle(g, w, h, e.farbe, typ, rng);
  const hell = pxMix(e.farbe, '#ffffff', .45);
  const an = e.st === 'laeuft';
  const lampe = 8 + Math.floor(rng() * Math.max(1, w - 16));
  const fenster = rng() < .35 && w > 52;
  if(fenster) pxFenster(g, w - 13, 7, 9, 6, rng);
  const sx = PX_TYP[typ](g, fenster ? w - 12 : w, fy, e.farbe, hell, rng, t, an);
  pxLampe(g, lampe, fy, e.farbe);
  const look = e.look;
  if(e.st === 'laeuft'){
    pxFigur(g, sx, fy, look, 'sitzt', t, true);
  }else if(e.st === 'frei'){
    const R = Math.max(4, w - 9), p = (t + e.seed % (R * 2)) % (R * 2);
    const x = 2 + (p < R ? p : 2 * R - p);
    pxFigur(g, x, fy, look, 'geht', t, p < R);
  }else{
    const x = Math.max(2, sx - 3);
    pxFigur(g, x, fy, look, e.st === 'wartet' ? 'wartet' : 'steht', t, true);
    pxBlase(g, x, fy - 19, e.st === 'blockiert' ? 'alarm' : 'denkt', t);
  }
  if(e.st === 'blockiert') g.a(t % 8 < 4 ? .16 : .05, () => g.r(0, 0, w, h, '#ff1f4b'));
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}
/* ---- Gemeinschaftsräume, Hangar, Warpkern ---- */
function pxAgentenraum(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#38e8ff', 'command', rng);
  pxFenster(g, 8, 7, 22, 8, rng); pxFenster(g, w - 30, 7, 22, 8, rng);
  const cx = Math.floor(w / 2);
  g.r(cx - 14, fy - 5, 28, 2, '#3a4a66'); g.r(cx - 12, fy - 3, 24, 3, '#222c40');
  g.a(.35 + ((t % 6) / 30), () => { const c = g.ctx; c.fillStyle = '#38e8ff'; c.beginPath(); c.moveTo(cx - 10, fy - 5); c.lineTo(cx + 10, fy - 5); c.lineTo(cx + 6, 6); c.lineTo(cx - 6, 6); c.fill(); });
  for(let i = 0; i < 7; i++){ const a = (t / 4 + i * .9); g.p(cx + Math.round(Math.cos(a) * 5), 12 + i * 2, '#e0ffff'); }
  for(let i = 0; i < 4; i++){ const x = 36 + i * 12; if(x < cx - 18) pxMonitor(g, x, fy - 13, 8, 5, '#38e8ff', t + i, true, 'code'); }
  for(let i = 0; i < 4; i++){ const x = w - 44 - i * 12; if(x > cx + 18) pxMonitor(g, x, fy - 13, 8, 5, '#ff3fa4', t + i * 2, true, 'kerzen'); }
  pxLampe(g, Math.floor(w * .25), fy, '#38e8ff'); pxLampe(g, Math.floor(w * .75), fy, '#38e8ff');
  const n = Math.min(6, Math.max(2, e.anzahl || 4));
  for(let i = 0; i < n; i++){
    const L = { haut:PX_HAUT[i % 5], haar:PX_HAAR[(i * 3) % PX_HAAR.length], hemd:SHIP_FARBEN[i % SHIP_FARBEN.length], hose:PX_HOSE[i % 4] };
    const R = Math.max(10, w - 20), p = (t + i * 37) % (R * 2);
    if(i < 2) pxFigur(g, cx - 22 + i * 39, fy, L, 'wartet', t + i * 3, i === 0);
    else pxFigur(g, 6 + (p < R ? p : 2 * R - p), fy, L, 'geht', t, p < R);
  }
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}
function pxKonferenz(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ffb84d', 'meeting', rng);
  const cx = Math.floor(w / 2);
  g.r(cx - 22, 6, 44, 12, '#0b0812'); g.r(cx - 22, 6, 44, 1, '#ffb84d');
  pxMonitor(g, cx - 21, 8, 20, 9, '#3dff8f', t, true, 'kerzen'); pxMonitor(g, cx + 1, 8, 20, 9, '#ff5577', t, true, 'kurve');
  g.r(cx - 34, fy - 6, 68, 2, '#8a5a3c'); g.r(cx - 34, fy - 6, 68, 1, '#c8905a'); g.r(cx - 30, fy - 4, 2, 4, '#4a3020'); g.r(cx + 28, fy - 4, 2, 4, '#4a3020');
  const n = Math.min(6, Math.max(2, e.anzahl || 4));
  for(let i = 0; i < n; i++){
    const L = { haut:PX_HAUT[(i + 2) % 5], haar:PX_HAAR[(i * 2) % PX_HAAR.length], hemd:SHIP_FARBEN[(i + 3) % SHIP_FARBEN.length], hose:PX_HOSE[i % 4] };
    const x = cx - 32 + i * Math.floor(64 / n);
    const y = fy - 4;
    g.r(x + 1, y - 11 + (i === (t >> 3) % n ? 0 : 1), 3, 1, L.haar); g.r(x + 1, y - 10 + (i === (t >> 3) % n ? 0 : 1), 3, 2, L.haut);
    g.r(x, y - 8, 5, 3, L.hemd);
  }
  pxPflanze(g, 4, fy); pxPflanze(g, w - 8, fy);
  pxLampe(g, Math.floor(w * .3), fy, '#ffb84d'); pxLampe(g, Math.floor(w * .7), fy, '#ffb84d');
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}
function pxHangar(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#5aa9ff', 'server', rng);
  for(let x = 0; x < w; x += 6){ g.r(x, fy, 3, 1, '#ffcc33'); }
  const cx = Math.floor(w / 2), sy = fy - 9 - ((t >> 2) % 4 === 0 ? 1 : 0);
  g.r(cx - 12, sy + 3, 24, 3, '#c0c8d8'); g.r(cx - 8, sy + 1, 14, 2, '#d8e0ee'); g.r(cx - 2, sy, 5, 1, '#38e8ff');
  g.r(cx - 12, sy + 5, 24, 1, '#7a8298'); g.r(cx - 15, sy + 2, 4, 5, '#9aa2b8'); g.r(cx + 11, sy + 4, 4, 1, '#ff5fc8');
  g.r(cx - 17, sy + 3, 2, 3, (t & 1) ? '#38e8ff' : '#1a8aa0');
  g.r(cx - 6, fy - 2, 1, 2, '#555b6e'); g.r(cx + 5, fy - 2, 1, 2, '#555b6e');
  pxLampe(g, 10, fy, '#5aa9ff'); pxLampe(g, w - 10, fy, '#5aa9ff');
}
function pxWarp(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#38e8ff', 'server', rng);
  const cx = Math.floor(w / 2);
  g.r(cx - 7, 4, 14, 2, '#555b6e'); g.r(cx - 7, fy - 2, 14, 2, '#555b6e');
  g.r(cx - 5, 6, 10, fy - 8, '#0a3040');
  const puls = t % 8;
  for(let y = 6; y < fy - 2; y++){ const hell = ((y + puls) % 8) < 2; g.r(cx - 4, y, 8, 1, hell ? '#9ffcff' : '#1fb8d0'); }
  g.r(cx - 1, 6, 2, fy - 8, '#ffffff');
  g.a(.12 + (puls < 4 ? .06 : 0), () => g.r(cx - 14, 4, 28, fy - 4, '#38e8ff'));
  for(let i = 0; i < 3; i++){ g.r(4 + i * 4, 8, 2, fy - 10, '#3a3f56'); g.r(w - 6 - i * 4, 8, 2, fy - 10, '#3a3f56'); }
}
function pxLounge(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ff5edb', 'lounge', rng);
  pxFenster(g, 4, 9, Math.max(6, Math.min(18, w - 12)), 8, rng);
  const sofaW = Math.max(8, Math.min(24, w - 8));
  g.r(4, fy - 7, sofaW, 2, '#7b4bff'); g.r(4, fy - 5, sofaW, 3, '#5a35b8');
  g.r(4, fy - 7, 2, 7, '#a78bff'); g.r(4 + sofaW - 2, fy - 7, 2, 7, '#a78bff');
  g.r(Math.min(30, w - 12), fy - 5, 8, 1, '#a99cba');
  g.r(Math.min(33, w - 9), fy - 4, 2, 4, '#4a4058');
  pxPflanze(g, w - 7, fy);
  pxLampe(g, Math.floor(w * .3), fy, '#ff5edb'); pxLampe(g, Math.floor(w * .75), fy, '#ff5edb');
}
function pxLager(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ff9f43', 'lager', rng);
  const rw = Math.max(10, Math.floor(w * .42));
  for(let y = 9; y < fy; y += 8){
    g.r(2, y + 6, rw, 1, '#8a6a4a');
    for(let x = 3; x < rw - 2; x += 5) g.r(x, y + 2, 4, 4, ['#b8875a','#5a7aa0','#7a9a5a'][pxN(x, y, 3) % 3]);
  }
  g.r(2, 9, 1, fy - 9, '#5a5f78'); g.r(rw + 1, 9, 1, fy - 9, '#5a5f78');
  g.r(rw + 4, fy - 6, 5, 6, '#b8875a'); g.r(rw + 5, fy - 11, 4, 5, '#5a7aa0');
  g.r(w - 9, fy - 8, 5, 1, '#c0c4cc'); g.r(w - 9, fy - 8, 1, 8, '#c0c4cc');
  for(let x = 0; x < w; x += 4) g.r(x, fy, 2, 1, '#ffcc33');
  pxLampe(g, Math.floor(w * .3), fy, '#ff9f43'); pxLampe(g, Math.floor(w * .75), fy, '#ff9f43');
}
const PX_ART = { agent:pxAgentRaum, agents:pxAgentenraum, konf:pxKonferenz, hangar:pxHangar, warp:pxWarp, lounge:pxLounge, lager:pxLager };

function pxZeichne(e){
  const cv = e.cv;
  if(!cv.width || !cv.height) return;
  const ctx = cv.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  if(e.spiegel){ ctx.setTransform(-1, 0, 0, 1, cv.width, 0); }
  const maler = e.gross && window.PX_GROSS ? window.PX_GROSS[e.art] : PX_ART[e.art];
  if(!maler) return;
  maler(pxPinsel(ctx), cv.width, cv.height, e, pxTakt);
}
function pxGroessen(){
  pxRaeume.forEach(e => {
    const w = Math.max(12, Math.round(e.cv.clientWidth / PX)), h = Math.max(12, Math.round(e.cv.clientHeight / PX));
    if(e.cv.width !== w) e.cv.width = w;
    if(e.cv.height !== h) e.cv.height = h;
    pxZeichne(e);
  });
}
function pxStarteAnimation(){
  if(pxTimer) return;
  const ruhig = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(ruhig) return;
  pxTimer = setInterval(() => {
    const bereich = $('#v-ship');
    if(document.hidden || !bereich || bereich.hidden || !pxRaeume.length) return;
    pxTakt++;
    pxRaeume.forEach(pxZeichne);
  }, 170);
}
window.addEventListener('resize', () => { clearTimeout(pxGroessen.t); pxGroessen.t = setTimeout(pxGroessen, 200); });

function pxLook(a){
  const h = pxHash(a.agent_id || a.rufname);
  return { haut:PX_HAUT[h % 5], haar:PX_HAAR[(h >> 4) % PX_HAAR.length], hemd:shipDeptFarbe(a.dept), hose:PX_HOSE[(h >> 8) % 4] };
}

function renderShipWorld(){
  const box = $('#shipWorld');
  if(!box) return;
  box.classList.add('px-world');
  if(!companyDaten){
    const legend = $('#shipLegend');
    if(legend){ legend.hidden = true; legend.innerHTML = ''; }
    pxRaeume = [];
    box.innerHTML = `<div class="empty">${companyFehler ? 'Company-API nicht erreichbar: ' + esc(companyFehler) : 'Agentenräume werden geladen …'}</div>`;
    renderShipDetail();
    return;
  }
  const depts = shipDeptList();
  const agenten = (companyDaten.agents && companyDaten.agents.agenten) || [];
  if(shipAuswahl.typ === 'agent' && !agenten.some(a => a.agent_id === shipAuswahl.id)) shipAuswahl = { typ:'overview' };
  const s = (companyDaten.overview && companyDaten.overview.agenten_status) || {};
  const aufgaben = (companyDaten.overview && companyDaten.overview.aufgaben) || {};
  const konf = R && R.konferenz;
  const commonOn = typ => shipAuswahl.typ === typ;
  const liste = [];
  const gross = shipGrossAktiv();
  box.classList.toggle('px-gross', gross);
  shipGrossGerendert = gross;
  const leinwand = eintrag => { liste.push({ ...eintrag, gross }); return `<canvas class="px-cv" data-px="${liste.length - 1}" aria-hidden="true"></canvas>`; };

  const tuerHtml = (typ, farbe, seed) => `<span class="px-door" aria-hidden="true">${gross ? leinwand({ art:'tuer', typ, farbe, seed }) : ''}</span>`;
  const raumHtml = (a, gewicht, dIdx) => {
    const st = shipStatusKey(a);
    const offenA = Number(a.offene_aufgaben) || 0;
    const on = shipAuswahl.typ === 'agent' && shipAuswahl.id === a.agent_id;
    const titel = `${a.rufname} · ${a.role} · ${a.dept_name} · ${a.status_text || a.status}${offenA ? ` · ${offenA} offen` : ''}`;
    const seed = pxHash(a.agent_id || a.rufname);
    const cv = leinwand({ art:'agent', typ:SHIP_ROOM_TYPEN[a.dept] || 'command', farbe:shipDeptFarbe(a.dept), st, look:pxLook(a), seed, spiegel:(seed >> 3) % 3 === 0, on, agent:a.agent_id });
    return `<button type="button" class="px-room status-${st}${on ? ' on' : ''}" style="flex-grow:${gewicht}" data-agent="${esc(a.agent_id)}"
      aria-pressed="${on ? 'true' : 'false'}" title="${esc(titel)}" aria-label="${esc(titel)}">${cv}
      <span class="px-tag"><i></i>${esc(a.rufname)}</span>${offenA ? `<span class="px-task">+${offenA}</span>` : ''}</button>`;
  };
  const leerHtml = (art, gewicht, titel, extra = '') => `<span class="px-room px-void${extra}" style="flex-grow:${gewicht}" aria-hidden="true">${leinwand({ art, seed:pxHash(art + titel), farbe:'#38e8ff' })}<span class="px-tag px-tag-dim">${titel}</span></span>`;

  const deptHtml = (d, dIdx, pos) => {
    const farbe = shipDeptFarbe(d.code);
    const offen = d.liste.reduce((n,a) => n + (Number(a.offene_aufgaben) || 0), 0);
    const reihen = [];
    for(let i = 0; i < d.liste.length; i += 5) reihen.push(d.liste.slice(i, i + 5));
    if(!reihen.length) reihen.push([]);
    const floors = reihen.map((reihe, rIdx) => {
      const muster = PX_MUSTER[(dIdx + rIdx * 2) % PX_MUSTER.length];
      const teile = reihe.map((a, i) => raumHtml(a, muster[i % 5], dIdx));
      if(d.code === 'S' || reihe.length < 5){
        const fehlt = Math.max(0, 5 - reihe.length);
        for(let i = 0; i < fehlt; i++) teile.push(leerHtml(i % 2 ? 'lager' : 'lounge', 3, i % 2 ? 'LAGER' : 'CREW-LOUNGE'));
      }
      const typ = SHIP_ROOM_TYPEN[d.code] || 'command';
      const html = teile.map((t, i) => (i ? tuerHtml(typ, farbe, pxHash(d.code + rIdx + '-' + i)) : '') + t).join('');
      return `<div class="px-floor">${html || '<div class="empty">Keine Agenten.</div>'}</div>`;
    }).join('');
    return `<section class="px-dept${d.code === 'S' ? ' px-dept-wide' : ''}" data-dept="${esc(d.code)}" style="--dept:${farbe};${pos}">
      <header class="px-dept-head"><b>${esc(d.code)}</b><span>${esc(d.name)}</span><em>${d.liste.length} CREW · ${offen} OFFEN</em></header>
      ${floors}</section>`;
  };

  const normal = depts.filter(d => d.code !== 'S'), exec = depts.filter(d => d.code === 'S');
  const zeilen = Math.max(1, Math.ceil(normal.length / 2));
  const deckHtml = normal.map((d, i) => deptHtml(d, i, `grid-column:${i % 2 ? 3 : 1};grid-row:${Math.floor(i / 2) + 1}`)).join('');

  box.innerHTML = `
    <div class="px-ship">
      <div class="px-bridge">
        <span class="px-fin px-fin-l" aria-hidden="true"></span><span class="px-fin px-fin-r" aria-hidden="true"></span>
        <div class="px-brand"><span>ORAKEL // DECK 07</span><b>INTERSTELLAR OPERATIONS</b><small><i></i>${agenten.length} CREW · ${depts.length} DIVISIONEN</small></div>
        <div class="px-common">
          <button type="button" class="px-room px-common-room${commonOn('agents') ? ' on' : ''}" data-common="agents" aria-pressed="${commonOn('agents')}">
            ${leinwand({ art:'agents', seed:11, anzahl:Number(s.aktiv) || 4, on:commonOn('agents') })}
            <span class="px-tag px-tag-big"><i></i>AGENTENRAUM · ${agenten.length} AGENTEN</span></button>
          ${tuerHtml('meeting', '#ffb84d', 5)}
          <button type="button" class="px-room px-common-room${commonOn('konf') ? ' on' : ''}" data-common="konf" aria-pressed="${commonOn('konf')}">
            ${leinwand({ art:'konf', seed:23, anzahl:konf ? Math.max(4, (konf.berichte || []).length) : 6, on:commonOn('konf') })}
            <span class="px-tag px-tag-big px-tag-gold"><i></i>KONFERENZ · ${konf ? `${(konf.berichte || []).length} BERICHTE · ${(konf.massnahmen || []).length} MASSNAHMEN` : 'KEINE KONFERENZ'}</span></button>
        </div>
      </div>
      <div class="px-hull">
        <span class="px-pipe px-pipe-l" aria-hidden="true"></span><span class="px-pipe px-pipe-r" aria-hidden="true"></span>
        <div class="px-decks">
          ${deckHtml}
          <div class="px-shaft" style="grid-column:2;grid-row:1 / span ${zeilen}" aria-hidden="true"><span class="px-lift"></span></div>
        </div>
        ${exec.map((d) => deptHtml(d, 7, '')).join('')}
        <section class="px-engdeck" style="--dept:#5aa9ff">
          <header class="px-dept-head"><b>T</b><span>Technik · Antrieb</span><em>HANGAR 07 · WARP CORE</em></header>
          <div class="px-floor">${leerHtml('hangar', 3, 'HANGAR 07', ' px-big')}${tuerHtml('workshop', '#5aa9ff', 77)}${leerHtml('warp', 2, 'WARP CORE', ' px-big')}</div>
        </section>
      </div>
      <div class="px-engine">
        <span class="px-eng-state">● ${Number(s.aktiv) || 0} AKTIV · ${Number(s.blockiert) || 0} BLOCKIERT · ${Number(aufgaben.offen) || 0} OFFEN</span>
        <span class="px-nozzle"></span><span class="px-nozzle"></span><span class="px-nozzle"></span>
      </div>
      <span class="px-loop" aria-hidden="true"></span>
    </div>`;

  pxRaeume = liste.map((e, i) => ({ ...e, cv:box.querySelector(`canvas[data-px="${i}"]`) })).filter(e => e.cv);
  renderShipLegend(depts, agenten);
  box.querySelectorAll('[data-agent]').forEach(b => b.onclick = () => setShipSelection('agent', b.dataset.agent));
  box.querySelectorAll('[data-common]').forEach(b => b.onclick = () => setShipSelection(b.dataset.common));
  applyShipTransform();
  requestAnimationFrame(() => { pxGroessen(); if(!shipZoomInit) fitShip(); });
  pxStarteAnimation();
  renderShipDetail();
}


function shipWertText(wert){
  if(wert === null || wert === undefined) return '–';
  const roh = typeof wert === 'string' ? wert : JSON.stringify(wert);
  const text = String(roh ?? '–');
  return text.length > 220 ? text.slice(0, 217) + '…' : text;
}

function shipStandardEmpfaenger(a){
  const agenten = ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [])
    .filter(x => x.agent_id !== a.agent_id && x.active !== false);
  const berichtet = agenten.find(x => x.agent_id === a.reports_to);
  return (berichtet || agenten.find(x => x.dept === a.dept) || agenten[0] || {}).agent_id || '';
}

function shipEmpfaengerOptionen(a, gewaehlt){
  const agenten = ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [])
    .filter(x => x.agent_id !== a.agent_id && x.active !== false);
  const direkt = agenten.map(x => {
    const sel = x.agent_id === gewaehlt ? ' selected' : '';
    const deptName = SHIP_DEPT_NAMEN[x.dept] || x.dept_name || x.dept;
    return `<option value="${esc(x.agent_id)}"${sel}>${esc(x.rufname)} · ${esc(x.dept)} ${esc(deptName)}</option>`;
  }).join('');
  let html = direkt ? `<optgroup label="Direkt">${direkt}</optgroup>` : '';
  if(a.rank === 'leitung' || a.rank === 'sekretariat'){
    const depts = shipDeptList().filter(d => a.rank === 'sekretariat' || d.code === a.dept);
    const opt = depts.map(d => {
      const wert = 'dept:' + d.code;
      const sel = wert === gewaehlt ? ' selected' : '';
      return `<option value="${esc(wert)}"${sel}>Abteilung ${esc(d.code)} · ${esc(d.name)}</option>`;
    }).join('');
    if(opt) html += `<optgroup label="Abteilung">${opt}</optgroup>`;
  }
  if(['A1','S1','S2','S3'].includes(a.agent_id)){
    const sel = gewaehlt === 'all' ? ' selected' : '';
    html += `<optgroup label="Broadcast"><option value="all"${sel}>Alle aktiven Agenten</option></optgroup>`;
  }
  return html;
}

function shipDraftNeu(a){
  return { fuer:a.agent_id, an:shipStandardEmpfaenger(a), art:'status', betreff:'', text:'', belege:'', quittung:true };
}

function shipNachrichtHtml(m, a){
  const eingehend = String(m.to_agent) === String(a.agent_id);
  const partner = eingehend ? (m.from_rufname || m.from_agent) : (m.to_rufname || m.to_agent);
  const quittung = m.ack_at
    ? 'quittiert ' + esc(kurzZeit(m.ack_at) || '')
    : (eingehend ? 'offen' : 'ausgehend');
  const ack = eingehend && !m.ack_at
    ? `<button type="button" class="sd-msg-ack" data-ship-ack="${Number(m.id)}">Quittieren</button>` : '';
  const belege = Array.isArray(m.evidence) && m.evidence.length
    ? `<small class="sd-msg-evidence">Belege: ${m.evidence.map(x => esc(x)).join(' · ')}</small>` : '';
  return `<article class="sd-msg ${eingehend ? 'ist-eingang' : 'ist-ausgang'}">
    <div class="sd-msg-kopf"><b>${esc(m.subject || '(ohne Betreff)')}</b><span>${esc(m.kind || 'status')}</span></div>
    <small class="sd-msg-meta">${eingehend ? 'von' : 'an'} ${esc(partner || '–')} · ${esc(kurzZeit(m.created_at) || '–')} · ${quittung}</small>
    <p class="sd-msg-body">${esc(m.body || '')}</p>${belege}${ack}</article>`;
}

function shipKommunikationHtml(a){
  const detail = shipDetail && shipDetail.profil && shipDetail.profil.agent_id === a.agent_id ? shipDetail : null;
  const nachrichten = detail && Array.isArray(detail.nachrichten) ? detail.nachrichten : [];
  const erinnerungen = detail && Array.isArray(detail.erinnerungen) ? detail.erinnerungen : [];
  if(!shipDraft || shipDraft.fuer !== a.agent_id) shipDraft = shipDraftNeu(a);
  const draft = shipDraft;
  const arten = [['status','Status'],['handoff','Übergabe'],['question','Frage'],['answer','Antwort'],['task_request','Auftrag'],['task_result','Ergebnis'],['review_request','Review'],['review_result','Review-Ergebnis'],['alert','Alarm'],['decision','Entscheid']];
  const artOptionen = arten.map(([wert, text]) => `<option value="${wert}"${draft.art === wert ? ' selected' : ''}>${text}</option>`).join('');
  const formular = detail ? `<form class="sd-form" data-ship-form>
    <label>Empfänger<select name="an" data-ship-feld="an" required>${shipEmpfaengerOptionen(a, draft.an)}</select></label>
    <div class="sd-form-zeile">
      <label>Art<select name="art" data-ship-feld="art">${artOptionen}</select></label>
      <label class="sd-check"><input type="checkbox" name="quittung" data-ship-feld="quittung"${draft.quittung ? ' checked' : ''}> Quittung anfordern</label>
    </div>
    <label>Betreff<input name="betreff" maxlength="200" value="${esc(draft.betreff)}" data-ship-feld="betreff" required autocomplete="off"></label>
    <label>Nachricht<textarea name="text" rows="3" maxlength="8000" data-ship-feld="text" required>${esc(draft.text)}</textarea></label>
    <label>Belege <span>(kommagetrennt)</span><input name="belege" maxlength="2000" value="${esc(draft.belege)}" data-ship-feld="belege" placeholder="task:12, article:4821" autocomplete="off"></label>
    <button type="submit" class="sd-send">Nachricht senden</button>
  </form>` : '';
  const liste = nachrichten.length
    ? `<div class="sd-msg-liste">${nachrichten.map(m => shipNachrichtHtml(m, a)).join('')}</div>`
    : '<p class="sd-leer">Keine Nachrichten.</p>';
  const memory = erinnerungen.length ? `<div class="sd-memory-liste">${erinnerungen.map(e => `
    <div class="sd-memory"><div><b>${esc(e.scope)} · ${esc(e.key)}</b><small>${esc(kurzZeit(e.updated_at) || '–')}</small></div><code>${esc(shipWertText(e.value))}</code></div>`).join('')}</div>`
    : '<p class="sd-leer">Noch keine persönlichen Erinnerungen.</p>';
  const status = shipNachrichtStatus
    ? `<p class="sd-hinweis ${shipNachrichtStatus.typ}" role="status">${esc(shipNachrichtStatus.text)}</p>` : '';
  const fehler = shipDetailFehler
    ? `<p class="sd-hinweis fehler" role="status">${esc(shipDetailFehler)}</p>` : '';
  const laden = !detail
    ? (shipDetailLaden ? '<p class="sd-leer">Nachrichten und Erinnerungen werden geladen …</p>' : '')
    : '';
  return `<div class="sd-kommunikation" data-ship-kommunikation>
    <div class="sd-block">
      <div class="sd-block-kopf"><small>NACHRICHTEN${nachrichten.length ? ` · ${nachrichten.length}` : ''}</small>
        <button type="button" class="sd-mini" data-ship-detail-refresh${shipDetailLaden ? ' disabled' : ''}>${shipDetailLaden ? 'lädt …' : 'Aktualisieren'}</button></div>
      ${fehler}${status}${laden}${detail ? liste + formular : ''}
    </div>
    <div class="sd-block"><small>ERINNERUNGEN${erinnerungen.length ? ` · ${erinnerungen.length}` : ''}</small>
      ${detail ? memory : (shipDetailLaden ? '<p class="sd-leer">Wird geladen …</p>' : '')}</div>
  </div>`;
}

function ladeShipDetail(agentId, erzwingen = false){
  if(!erzwingen && shipDetailFuer === agentId && (shipDetailLaden || shipDetail)) return;
  const token = ++shipDetailAnfrage;
  shipDetailFuer = agentId;
  shipDetailLaden = true;
  shipDetailFehler = null;
  renderShipDetail(true);
  fetch(`/api/company/agents/${encodeURIComponent(agentId)}`, {cache:'no-store'})
    .then(async antwort => {
      const daten = await antwort.json().catch(() => ({}));
      if(!antwort.ok) throw new Error(daten.fehler || ('HTTP ' + antwort.status));
      return daten;
    })
    .then(daten => {
      if(token !== shipDetailAnfrage) return;
      shipDetail = daten;
    })
    .catch(e => {
      if(token !== shipDetailAnfrage) return;
      shipDetailFehler = String((e && e.message) || e);
    })
    .finally(() => {
      if(token !== shipDetailAnfrage) return;
      shipDetailLaden = false;
      renderShipDetail(true);
    });
}

function bindeShipKommunikation(side, a){
  const form = side.querySelector('[data-ship-form]');
  if(form){
    form.onsubmit = ev => { ev.preventDefault(); sendeShipNachricht(a, form); };
    form.querySelectorAll('[data-ship-feld]').forEach(el => {
      const key = el.dataset.shipFeld;
      const merken = () => {
        if(shipDraft && shipDraft.fuer === a.agent_id) shipDraft[key] = el.type === 'checkbox' ? el.checked : el.value;
      };
      el.addEventListener('input', merken);
      el.addEventListener('change', merken);
    });
  }
  side.querySelectorAll('[data-ship-ack]').forEach(btn => {
    btn.onclick = () => quittiereShipNachricht(a, Number(btn.dataset.shipAck), btn);
  });
  const refresh = side.querySelector('[data-ship-detail-refresh]');
  if(refresh) refresh.onclick = () => ladeShipDetail(a.agent_id, true);
}

async function sendeShipNachricht(a, form){
  const fuer = a.agent_id;
  const knopf = form.querySelector('button[type="submit"]');
  const wert = name => {
    const feld = form.querySelector(`[name="${name}"]`);
    return feld ? feld.value : '';
  };
  const an = wert('an');
  const belege = wert('belege').split(',').map(x => x.trim()).filter(Boolean);
  if(!an){
    shipNachrichtStatus = {typ:'fehler', text:'Bitte einen Empfänger wählen.'};
    renderShipDetail(true);
    return;
  }
  if(knopf){ knopf.disabled = true; knopf.textContent = 'Sendet …'; }
  try{
    const antwort = await fetch('/api/company/messages', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      from_agent:a.agent_id, to_agent:an, subject:wert('betreff'), body:wert('text'),
      kind:wert('art'), evidence:belege,
      requires_ack:Boolean(form.querySelector('[name="quittung"]')?.checked),
    })});
    const daten = await antwort.json().catch(() => ({}));
    if(!antwort.ok || !daten.ok) throw new Error(daten.fehler || ('HTTP ' + antwort.status));
    if(shipAuswahl.typ !== 'agent' || shipAuswahl.id !== fuer) return;
    const neue = Array.isArray(daten.messages) ? daten.messages : [];
    if(shipDetail){
      const ids = new Set(neue.map(m => Number(m.id)));
      shipDetail.nachrichten = [...neue, ...(shipDetail.nachrichten || []).filter(m => !ids.has(Number(m.id)))].slice(0, 25);
    }
    shipNachrichtStatus = {typ:'ok', text:`Nachricht an ${Number((daten.to_agents || []).length) || 1} Empfänger gesendet.`};
    shipDraft = shipDraftNeu(a);
    renderShipDetail(true);
  }catch(e){
    if(shipAuswahl.typ === 'agent' && shipAuswahl.id === fuer){
      shipNachrichtStatus = {typ:'fehler', text:String((e && e.message) || e)};
      renderShipDetail(true);
    }
  }
}

async function quittiereShipNachricht(a, id, knopf){
  const fuer = a.agent_id;
  if(knopf){ knopf.disabled = true; knopf.textContent = 'Quittiere …'; }
  try{
    const antwort = await fetch(`/api/company/messages/${id}/ack`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({agent_id:a.agent_id})});
    const daten = await antwort.json().catch(() => ({}));
    if(!antwort.ok || !daten.ok) throw new Error(daten.fehler || ('HTTP ' + antwort.status));
    if(shipAuswahl.typ !== 'agent' || shipAuswahl.id !== fuer) return;
    const m = (shipDetail && shipDetail.nachrichten || []).find(x => Number(x.id) === id);
    if(m) m.ack_at = (daten.nachricht && daten.nachricht.ack_at) || new Date().toISOString();
    shipNachrichtStatus = {typ:'ok', text:'Nachricht quittiert.'};
    renderShipDetail(true);
  }catch(e){
    if(shipAuswahl.typ === 'agent' && shipAuswahl.id === fuer){
      shipNachrichtStatus = {typ:'fehler', text:String((e && e.message) || e)};
      renderShipDetail(true);
    }
  }
}

function setShipSelection(typ, id){
  if(shipDeptFilter){
    const raum = typ === 'agent'
      ? [...document.querySelectorAll('#shipWorld [data-agent]')].find(b => b.dataset.agent === id)
      : null;
    if(!raum || raum.closest('.px-dept')?.dataset.dept !== shipDeptFilter){
      shipDeptFilter = null;
      syncShipDeptFilter();
    }
  }
  shipAuswahl = typ === 'agent' ? { typ:'agent', id } : { typ };
  if(typ === 'agent'){
    const a = ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || []).find(x => x.agent_id === id);
    if(shipDetailFuer !== id || !shipDetail){
      shipDetail = null;
      shipDetailFehler = null;
      shipNachrichtStatus = null;
      shipDraft = a ? shipDraftNeu(a) : null;
      ladeShipDetail(id);
    }
  }else{
    shipDetailAnfrage++;
    shipDetail = null;
    shipDetailFehler = null;
    shipDetailLaden = false;
    shipDetailFuer = null;
    shipNachrichtStatus = null;
    shipDraft = null;
  }
  document.querySelectorAll('#shipWorld [data-agent]').forEach(b => {
    const on = typ === 'agent' && b.dataset.agent === id;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  document.querySelectorAll('#shipWorld [data-common]').forEach(b => {
    const on = b.dataset.common === typ;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  pxRaeume.forEach(e => {
    const on = e.agent ? (typ === 'agent' && e.agent === id) : (e.art === 'agents' ? typ === 'agents' : e.art === 'konf' ? typ === 'konf' : false);
    if(e.on !== on){ e.on = on; pxZeichne(e); }
  });
  syncShipDeptFilter();
  renderShipDetail();
  const side = $('#shipSideInhalt'); if(side) side.scrollTop = 0;
}

function renderShipDetail(force = false){
  const side = $('#shipSideInhalt');
  if(!side) return;
  if(!companyDaten){
    side.innerHTML = `<span class="sd-kicker">RAUMSCHIFF</span><h2>Verbindung</h2><p>${companyFehler ? 'Company-API nicht erreichbar: ' + esc(companyFehler) : 'Agentenlage wird geladen …'}</p>`;
    return;
  }
  if(!force && shipAuswahl.typ === 'agent' && shipDetail && shipDetail.profil
     && shipDetail.profil.agent_id === shipAuswahl.id
     && side.querySelector('[data-ship-kommunikation]')) return;
  const depts = shipDeptList();
  const agenten = (companyDaten.agents && companyDaten.agents.agenten) || [];
  const s = (companyDaten.overview && companyDaten.overview.agenten_status) || {};
  const aufgaben = (companyDaten.overview && companyDaten.overview.aufgaben) || {};

  if(shipAuswahl.typ === 'agents'){
    side.innerHTML = `<span class="sd-kicker">GEMEINSCHAFTSRAUM</span><h2>Agentenraum</h2>
      <p>${agenten.length} Agenten in ${depts.length} Abteilungen. Eine Abteilung wählen, um ihren ersten Agenten zu öffnen.</p>
      <div class="sd-kpis"><div class="sd-kpi"><small>GESAMT</small><b>${agenten.length}</b></div>
        <div class="sd-kpi"><small>AKTIV</small><b>${Number(s.aktiv)||0}</b></div><div class="sd-kpi"><small>OFFEN</small><b>${Number(aufgaben.offen)||0}</b></div></div>
      <div class="sd-block"><small>ABTEILUNGEN</small>${shipDeptKnoepfe(depts)}</div>`;
    bindeShipDeptKnoepfe(side, agenten);
    return;
  }

  if(shipAuswahl.typ === 'konf'){
    const k = R && R.konferenz;
    if(!k){
      side.innerHTML = `<span class="sd-kicker">GEMEINSCHAFTSRAUM</span><h2>Konferenz</h2><p>Noch keine Konferenz abgehalten.</p>`;
      return;
    }
    side.innerHTML = `<span class="sd-kicker">GEMEINSCHAFTSRAUM</span><h2>Konferenz</h2>
      <p>${esc(k.beschluss || 'Kein Beschluss gespeichert.')}</p>
      <div class="sd-kpis"><div class="sd-kpi"><small>BERICHTE</small><b>${(k.berichte || []).length}</b></div>
        <div class="sd-kpi"><small>DISKUSSION</small><b>${(k.diskussion || []).length}</b></div><div class="sd-kpi"><small>MASSNAHMEN</small><b>${(k.massnahmen || []).length}</b></div></div>
      <div class="sd-block"><small>MODUS · ${esc(k.zeit ? kurzZeit(k.zeit) : '–')}</small><b>${esc(k.modus || '–')}</b></div>
      <div class="sd-block"><small>MASSNAHMEN</small>${(k.massnahmen || []).slice(0,4).map(m => `<div class="sd-measure"><b>${esc(m.beschreibung || '–')}</b>${esc(m.verantwortlicher || 'Nicht zugewiesen')}</div>`).join('') || '<p>Keine Massnahmen.</p>'}</div>`;
    return;
  }

  if(shipAuswahl.typ === 'agent'){
    const a = agenten.find(x => x.agent_id === shipAuswahl.id);
    if(a){
      const farbe = shipDeptFarbe(a.dept);
      const st = shipStatusKey(a);
      const letzte = a.letzte_task || null;
      if(!shipDraft || shipDraft.fuer !== a.agent_id) shipDraft = shipDraftNeu(a);
      side.innerHTML = `<span class="sd-kicker">AGENTENRAUM · ${esc(a.dept)}</span>
        <div class="sd-head"><span class="sd-avatar" style="--dept:${farbe}">${esc((a.rufname || '?').slice(0,1).toUpperCase())}</span>
          <span class="sd-head-txt"><small>${esc(a.agent_id)} · ${esc(a.station || '–')}</small><b>${esc(a.rufname)}</b></span></div>
        <p>${esc(a.role)} · ${esc(a.dept_name)}</p>
        <div class="sd-status ${st}"><span class="p"></span>${esc(a.status_text || a.status)}${a.active ? ' · an Bord' : ' · inaktiv'}</div>
        <div class="sd-kpis"><div class="sd-kpi"><small>OFFEN</small><b>${Number(a.offene_aufgaben)||0}</b></div>
          <div class="sd-kpi"><small>LÄUFT</small><b>${Number(a.davon_laufend)||0}</b></div><div class="sd-kpi"><small>BLOCKIERT</small><b>${Number(a.davon_blockiert)||0}</b></div></div>
        <div class="sd-block"><small>AUFTRAG</small><p>${esc(a.mission || 'Keine Mission hinterlegt.')}</p></div>
        <div class="sd-block"><small>LETZTE AUFGABE</small><b>${esc(letzte && letzte.title ? letzte.title : 'Keine Aufgabe')}</b><p>${esc(letzte && letzte.state_text ? letzte.state_text : '–')}</p></div>
        <div class="sd-block"><small>BERICHTET AN</small><b>${esc(a.reports_to || '–')}</b><p>Autonomie ${esc(a.autonomy ?? '–')} · Abteilung ${esc(a.dept)}</p></div>
        ${shipKommunikationHtml(a)}`;
      bindeShipKommunikation(side, a);
      return;
    }
    shipAuswahl = { typ:'overview' };
  }

  side.innerHTML = `<span class="sd-kicker">SCHIFFSLAGE</span><h2>${agenten.length} Agenten an Bord</h2>
    <p>${depts.length} Abteilungen. Ein Raum öffnet rechts Rolle, Status und Aufgabe.</p>
    <div class="sd-kpis"><div class="sd-kpi"><small>AKTIV</small><b>${Number(s.aktiv)||0}</b></div>
      <div class="sd-kpi"><small>BLOCKIERT</small><b>${Number(s.blockiert)||0}</b></div><div class="sd-kpi"><small>OFFEN</small><b>${Number(aufgaben.offen)||0}</b></div></div>
    <div class="sd-block"><small>BEDIENUNG</small><b>Raum antippen</b><p>Ziehen verschiebt das Schiff. Mit +/−, Mausrad oder zwei Fingern zoomen; «Fit» zeigt alles.</p></div>
    <div class="sd-block"><small>COMMON ROOMS</small><p>Agentenraum und Konferenz liegen als eigene Räume oben im Querschnitt.</p></div>`;
}

function applyShipTransform(){
  const w = $('#shipWorld');
  if(!w) return;
  w.style.transform = `translate(${shipX}px, ${shipY}px) scale(${shipZoom})`;
  const z = $('#shipZoomWert'); if(z) z.textContent = `${Math.round(shipZoom * 100)} %`;
}

function fitShip(){
  const vp = $('#shipViewport'), w = $('#shipWorld');
  if(!vp || !w || !vp.clientWidth || !w.offsetWidth) return;
  if(!w.querySelector('.px-room')) return;
  const faktor = Math.min((vp.clientWidth - 18) / w.offsetWidth, (vp.clientHeight - 18) / w.offsetHeight, 1);
  shipZoom = Math.max(0.16, Math.min(2.5, faktor));
  shipX = (vp.clientWidth - w.offsetWidth * shipZoom) / 2;
  shipY = (vp.clientHeight - w.offsetHeight * shipZoom) / 2;
  shipZoomInit = true;
  applyShipTransform();
}

function zoomShip(faktor){
  const vp = $('#shipViewport');
  if(!vp) return;
  const alt = shipZoom;
  const neu = Math.max(0.22, Math.min(2.5, shipZoom * faktor));
  if(neu === alt) return;
  const mx = vp.clientWidth / 2, my = vp.clientHeight / 2;
  shipX = mx - (mx - shipX) * (neu / alt);
  shipY = my - (my - shipY) * (neu / alt);
  shipZoom = neu;
  applyShipTransform();
}

function initShipControls(){
  const vp = $('#shipViewport');
  if(!vp) return;
  vp.querySelectorAll('[data-ship-zoom]').forEach(b => b.onclick = () => {
    if(b.dataset.shipZoom === 'in') zoomShip(1.18);
    else if(b.dataset.shipZoom === 'out') zoomShip(0.85);
    else fitShip();
  });
  vp.addEventListener('wheel', e => {
    if(e.target.closest('.ship-zoom')) return;
    e.preventDefault();
    zoomShip(e.deltaY < 0 ? 1.12 : 0.89);
  }, { passive:false });

  // Maus und Touch teilen sich denselben Pointerpfad. Ein zweiter Finger
  // zoomt um den Berührungsmittelpunkt; ein einzelner Finger verschiebt.
  const zeiger = new Map();
  let drag = null, pinch = null, klickGesperrt = false, sperrTimer = null;
  const abstand = (a,b) => Math.hypot(a.x-b.x, a.y-b.y);
  const sperreKlick = () => {
    klickGesperrt = true;
    clearTimeout(sperrTimer);
    sperrTimer = setTimeout(() => { klickGesperrt = false; }, 400);
  };
  const startePinch = () => {
    if(zeiger.size < 2) return;
    const [a,b] = [...zeiger.values()];
    const mx = (a.x+b.x)/2, my = (a.y+b.y)/2;
    pinch = {
      abstand: Math.max(1, abstand(a,b)),
      zoom: shipZoom,
      mx, my,
      wx: (mx - shipX) / shipZoom,
      wy: (my - shipY) / shipZoom,
    };
    drag = null;
  };
  vp.addEventListener('click', e => {
    if(!klickGesperrt) return;
    e.preventDefault();
    e.stopPropagation();
    klickGesperrt = false;
    clearTimeout(sperrTimer);
  }, true);

  vp.addEventListener('pointerdown', e => {
    klickGesperrt = false;
    clearTimeout(sperrTimer);
    if(e.target.closest('.ship-zoom')) return;
    if(e.pointerType === 'mouse' && e.button !== 0) return;
    zeiger.set(e.pointerId, { x:e.clientX, y:e.clientY });
    try { vp.setPointerCapture(e.pointerId); } catch {}
    if(zeiger.size === 1){
      drag = { x:e.clientX, y:e.clientY, sx:shipX, sy:shipY, bewegt:false };
      pinch = null;
    }else if(zeiger.size === 2){
      startePinch();
      sperreKlick();
    }
  }, { passive:true });

  vp.addEventListener('pointermove', e => {
    if(!zeiger.has(e.pointerId)) return;
    zeiger.set(e.pointerId, { x:e.clientX, y:e.clientY });
    if(pinch && zeiger.size >= 2){
      const [a,b] = [...zeiger.values()];
      const faktor = Math.max(1, abstand(a,b)) / pinch.abstand;
      const neu = Math.max(0.22, Math.min(2.5, pinch.zoom * faktor));
      const mx = (a.x+b.x)/2, my = (a.y+b.y)/2;
      shipZoom = neu;
      shipX = mx - pinch.wx * neu;
      shipY = my - pinch.wy * neu;
      applyShipTransform();
      sperreKlick();
      e.preventDefault();
      return;
    }
    if(!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if(!drag.bewegt && Math.hypot(dx,dy) > 8){
      drag.bewegt = true;
      sperreKlick();
    }
    if(!drag.bewegt) return;
    shipX = drag.sx + dx;
    shipY = drag.sy + dy;
    applyShipTransform();
    e.preventDefault();
  }, { passive:false });

  const beenden = e => {
    const warDrag = !!(drag && drag.bewegt);
    // Pointer-Capture leitet den Klick auf den Viewport um. Für einen echten
    // Mausklick ohne Ziehen wählen wir deshalb den Raum unter dem Zeiger.
    if(e.type === 'pointerup' && e.pointerType === 'mouse' && !warDrag){
      const ziel = document.elementFromPoint(e.clientX, e.clientY)
        ?.closest('#shipWorld [data-agent], #shipWorld [data-common]');
      if(ziel){
        sperreKlick();
        if(ziel.dataset.agent) setShipSelection('agent', ziel.dataset.agent);
        else setShipSelection(ziel.dataset.common);
      }
    }
    zeiger.delete(e.pointerId);
    if(zeiger.size < 2) pinch = null;
    if(zeiger.size === 1){
      const p = [...zeiger.values()][0];
      drag = { x:p.x, y:p.y, sx:shipX, sy:shipY, bewegt:false };
    }else if(zeiger.size === 0){
      drag = null;
    }
  };
  vp.addEventListener('pointerup', beenden);
  vp.addEventListener('pointercancel', beenden);
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const bereich = $('#v-ship');
      syncShipLegend();
      if(shipGrossAktiv() !== shipGrossGerendert){
        shipZoomInit = false;
        renderShipWorld();
        return;
      }
      if(bereich && !bereich.hidden) fitShip();
    }, 160);
  });
}
initShipControls();

/* ---------- Spider + Intelligence ---------- */
async function ladeNacht(){
  if(!$('#nachtKpis')) return;
  try {
    const r = await fetch('/api/nexus/status', {cache:'no-store'});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    nachtDaten = await r.json();
    nachtFehler = null;
  } catch(e) {
    nachtDaten = null;
    nachtFehler = String(e.message || e);
  }
  zeichneNacht();
  zeichneMissionen(nachtDaten);
}

const zeitKurz = s => esc(String(s || '').replace('T',' ').slice(0,16)) || '–';
const groesse = b => b == null ? '–' : (Number(b) >= 1048576
  ? num(Number(b)/1048576,2) + ' MB' : num(Number(b)/1024,0) + ' KB');

function zeichneNacht(){
  if(!$('#nachtKpis')) return;
  if(nachtFehler){
    $('#nachtTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    $('#nachtKpis').innerHTML = '';
    $('#nachtDetail').innerHTML = `<div class="nacht-status">Status nicht geladen: ${esc(nachtFehler)}.</div>`;
    return;
  }
  const n = nachtDaten?.nacht;
  if(!n){
    $('#nachtTag').textContent = 'kein Lauf';
    $('#nachtKpis').innerHTML = '';
    $('#nachtDetail').innerHTML = '<div class="nacht-status">Noch kein Nachtlauf gespeichert. Einrichtung: <span class="code">docs/spider/NACHTBETRIEB.md</span></div>';
    return;
  }
  const ok = n.ok === true;
  const b = n.backup || {};
  $('#nachtTag').innerHTML = ok ? '<span class="up">OK</span>' : '<span class="dn">WARNUNG</span>';
  const kp = [
    ['Status', ok ? '<span class="up">OK</span>' : '<span class="dn">Warnung</span>', 'Lauf ' + zeitKurz(n.zeit)],
    ['Quellen', num(n.faellig,0), `${num(n.abgerufen,0)} abgerufen · ${num(n.unveraendert,0)} unverändert`],
    ['Meldungen', num(n.meldungen,0), `${num(n.gespeichert,0)} gespeichert · ${num(n.dubletten,0)} Kopien · ${num(n.fehler,0)} Fehler`],
    ['Backup', b.erstellt ? zeitKurz(b.erstellt) : '–', b.integrity ? `Integrität ${esc(b.integrity)} · ${groesse(b.bytes)}` : 'kein Backup'],
  ];
  $('#nachtKpis').innerHTML = kp.map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const teile = [];
  if(ok){
    teile.push('<span class="pill">OK</span> Alle fälligen Quellen ohne Fehler.');
  } else {
    const w = n.warnung || {};
    teile.push('<span class="pill r">WARNUNG</span>');
    if(w.gesendet) teile.push('Warnung gesendet.');
    else if(w.grund) teile.push('Nicht gesendet: ' + esc(w.grund) + '.');
    else if(w.fehler) teile.push('Nicht gesendet: ' + esc(w.fehler) + '.');
  }
  if(n.ping) teile.push(n.ping.gesendet ? 'Ping gesendet.' : 'Ping nicht gesendet' + (n.ping.fehler ? ' (' + esc(n.ping.fehler) + ')' : '') + '.');
  if(b.pfad) teile.push(`Backup: <span class="code">${esc(String(b.pfad).split('/').pop())}</span>`);
  if(b.entfernt?.length) teile.push(`${b.entfernt.length} alte Backups entfernt.`);
  if(n.domain) teile.push(`Domain: ${n.domain.ok ? 'ok' : esc(n.domain.fehler || 'Fehler')}${n.domain.tage_rest != null ? ' · Zertifikat ' + num(n.domain.tage_rest,0) + ' Tage' : ''}.`);
  if(n.bewertung?.fehler) teile.push(`<span class="pill r">Bewertung</span> ${esc(n.bewertung.fehler)}.`);
  else if(n.bewertung) teile.push(`Kernaussagen: ${num(n.bewertung.kernaussagen,0)} · Widersprüche: ${num(n.bewertung.widersprueche,0)}.`);
  $('#nachtDetail').innerHTML = `<div class="nacht-status">${teile.join(' ')}</div>`;
  zeichneBewertung(nachtDaten);
}

function zeichneBewertung(d){
  if(!$('#bewertungKpis')) return;
  const c = d?.claims?.statistik || {};
  const top = d?.claims?.top || [];
  const wid = d?.claims?.widersprueche || [];
  const reps = d?.reputation || [];
  const ns = c.nach_status || {};
  $('#bewertungTag').textContent = `${num(c.gesamt,0)} Kernaussagen`;
  $('#bewertungKpis').innerHTML = [
    ['Kernaussagen', num(c.gesamt,0), `${num(c.belege,0)} Belege`],
    ['Bestätigt', num(ns['bestätigt'],0), '≥ 2 unabhängige Quellen'],
    ['Teilweise', num(ns['teilweise'],0), 'nur eine Quelle oder wenig Belege'],
    ['Widersprüchlich', num(c.widersprueche,0), 'erkannte Konflikte'],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const pill = s => s==='bestätigt' ? 'g' : (s==='widersprüchlich' ? 'r' : (s==='teilweise' ? 'w' : ''));
  $('#bewertungClaims').innerHTML = top.length ? top.map(k=>`
    <div class="li"><span><b style="font-weight:400">${esc(k.kernaussage)}</b>
      <small>${esc(k.thema)} · ${num(k.quellen,0)} Quellen · ${num(k.belege,0)} Belege</small></span>
      <span class="pill ${pill(k.status)}">${num(k.bestaetigungsgrad,2)}</span></div>`).join('')
    + (wid.length ? `<div class="nacht-status"><span class="pill r">Widerspruch</span> ${esc(wid[0].grund)} <span class="code">${esc(wid[0].quelle_a)} ↔ ${esc(wid[0].quelle_b)}</span></div>` : '')
    : '<div class="empty">Noch keine Kernaussage. Der Nachtlauf bewertet Titel mit prüfbaren Zahlen, Richtungen oder Verneinungen.</div>';

  $('#bewertungQuellen').innerHTML = reps.length ? `<table class="tbl"><thead><tr><th>Quelle</th><th class="m">Reputation</th><th class="m">belegt</th><th class="m">verworfen</th></tr></thead><tbody>
    ${reps.map(q=>`<tr><td>${esc(q.name)}<small>${esc(q.vertrauen)}</small></td><td class="m">${num(q.reputation,2)}</td>
    <td class="m up">${num(q.bestaetigt,0)}</td><td class="m dn">${num(q.widerlegt,0)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Noch keine Quellenreputation.</div>';
}

function zeichneMissionen(d){
  if(!$('#missionKpis')) return;
  if(!d){
    $('#missionTag').textContent = 'nicht erreichbar';
    $('#missionKpis').innerHTML = '';
    $('#missionList').innerHTML = '<div class="empty">Status nicht geladen.</div>';
    return;
  }
  const st = d?.missionen?.statistik || {};
  const liste = d?.missionen?.liste || [];
  const ns = st.nach_status || {};
  $('#missionTag').textContent = `${num(st.gesamt,0)} Missionen`;
  $('#missionKpis').innerHTML = [
    ['Missionen', num(st.gesamt,0), `${num(st.tasks?.erledigt,0)} Aufgaben erledigt`],
    ['Offen / laufend', num((ns.offen ?? 0) + (ns.laufend ?? 0),0), `${num(ns.laufend ?? 0,0)} laufend`],
    ['Abgeschlossen', num(ns.abgeschlossen,0), 'mit Bericht'],
    ['Fortschritt', `${num(st.fortschritt,0)} %`, 'Durchschnitt aller Missionen'],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const pill = s => s==='abgeschlossen' ? 'g' : (s==='fehlgeschlagen' ? 'r' : (s==='laufend' ? 'b' : 'w'));
  $('#missionList').innerHTML = liste.length ? liste.map(m=>{
    const p = Math.max(0, Math.min(100, Number(m.fortschritt)||0));
    const datum = String(m.erstellt || '').replace('T',' ').slice(0,16);
    return `<div class="li mission" data-kennung="${esc(m.kennung)}">
      <div class="wlTop"><span><b style="font-weight:400">${esc(m.titel)}</b>
        <small>${esc(m.kennung)} · ${esc(m.prioritaet)} · ${datum}</small></span>
        <span class="pill ${pill(m.status)}">${esc(m.status)}</span></div>
      <div class="mission-bar"><i style="width:${p}%"></i></div>
      <div class="mission-meta"><small>${num(m.erledigt,0)} / ${num(m.tasks,0)} Aufgaben${m.fehlgeschlagen ? ' · ' + num(m.fehlgeschlagen,0) + ' fehlgeschlagen' : ''}</small>
        <span class="mission-actions">
          ${m.status !== 'abgeschlossen' ? `<button class="toggle" data-mission-lauf="1">Weiterarbeiten</button>` : ''}
          ${m.bericht_vorhanden ? `<button class="toggle" data-mission-bericht="1" aria-expanded="false">Bericht</button>` : ''}
        </span></div>
      <pre class="mission-report" hidden></pre>
    </div>`;
  }).join('') : '<div class="empty">Noch keine Mission. Eine Mission prüft gespeicherte Kernaussagen und schreibt einen Bericht mit offenen Fragen.</div>';
}

const phase6Fehler = text => {
  $('#banner').className = 'banner b-sim';
  $('#banner').innerHTML = '<b>FEHLER</b>' + esc(text);
};

async function ladeGraph(){
  if(!$('#graphNodes')) return;
  try {
    const r = await fetch('/api/nexus/graph?zeitraum=' + encodeURIComponent(graphWindow), {cache:'no-store'});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Graph konnte nicht geladen werden');
    graphDaten = d;
    zeichneGraph();
  } catch(e) {
    graphDaten = null;
    if($('#graphTag')) $('#graphTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    if($('#graphKpis')) $('#graphKpis').innerHTML = '';
    if($('#graphNodes')) $('#graphNodes').innerHTML = `<div class="empty">Graph nicht geladen: ${esc(e.message)}</div>`;
    if($('#graphEdges')) $('#graphEdges').innerHTML = '';
  }
}

function zeichneGraph(){
  const d = graphDaten;
  if(!d || !$('#graphNodes')) return;
  const st = d.statistik || {}, typen = st.typen || {};
  const knoten = d.knoten || [], kanten = d.kanten || [];
  $('#graphTag').textContent = `${num(st.knoten,0)} Knoten · ${num(st.kanten,0)} Kanten`;
  $('#graphKpis').innerHTML = [
    ['Knoten', num(st.knoten,0), `${num(typen.claim,0)} Kernaussagen`],
    ['Kanten', num(st.kanten,0), `${num(typen.quelle,0)} Quellen · ${num(typen.thema,0)} Themen`],
    ['Zeitraum', d.zeitraum || graphWindow, 'aus gespeicherten Zeitstempeln'],
    ['Beziehungen', `${num((st.arten||{}).belegt_durch,0)} Belege`, `${num((st.arten||{}).widerspruch,0)} Widersprüche`],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const typName = {claim:'Kernaussage', quelle:'Quelle', thema:'Thema'};
  $('#graphNodes').innerHTML = knoten.length ? knoten.map(n=>`
    <div class="li"><span><b style="font-weight:400">${esc(n.label)}</b>
      <small>${esc(typName[n.typ] || n.typ)}${n.status ? ' · ' + esc(n.status) : ''}</small></span>
      <span class="pill ${n.typ==='claim'?'b':n.typ==='thema'?'w':'g'}">${esc(n.typ)}</span></div>`).join('')
    : `<div class="empty">${esc(d.hinweis || 'Noch keine Knoten.')}</div>`;
  const label = id => (knoten.find(n=>n.id===id) || {}).label || id;
  $('#graphEdges').innerHTML = kanten.length ? `<table class="tbl"><thead><tr><th>Von</th><th>Nach</th><th>Art</th><th class="m">Sicherheit</th></tr></thead><tbody>
    ${kanten.map(k=>`<tr><td style="white-space:normal">${esc(label(k.von))}</td><td style="white-space:normal">${esc(label(k.nach))}</td>
      <td>${esc(k.art)}</td><td class="m">${num(k.sicherheit,2)}</td></tr>`).join('')}</tbody></table>`
    : (knoten.length ? `<div class="empty">${esc(d.hinweis || 'Noch keine Kanten.')}</div>` : '');
}

async function ladeKalibrierung(){
  if(!$('#kalibrierungList')) return;
  try {
    const r = await fetch('/api/nexus/kalibrierung', {cache:'no-store'});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Kalibrierung konnte nicht geladen werden');
    kalibrierungDaten = d;
    zeichneKalibrierung();
  } catch(e) {
    kalibrierungDaten = null;
    if($('#kalibrierungTag')) $('#kalibrierungTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    if($('#kalibrierungKpis')) $('#kalibrierungKpis').innerHTML = '';
    if($('#kalibrierungList')) $('#kalibrierungList').innerHTML = `<div class="empty">Kalibrierung nicht geladen: ${esc(e.message)}</div>`;
    if($('#kalibrierungKlassen')) $('#kalibrierungKlassen').innerHTML = '';
    if($('#kalibrierungHinweis')) $('#kalibrierungHinweis').textContent = '';
  }
}

function zeichneKalibrierung(){
  const d = kalibrierungDaten;
  if(!d || !$('#kalibrierungList')) return;
  const quote = d.trefferquote == null ? '–' : pct(d.trefferquote*100, 1);
  const brier = d.brier == null ? '–' : num(d.brier, 4);
  $('#kalibrierungTag').textContent = `${num(d.gesamt,0)} Prognosen · ${num(d.auto,0)} automatisch`;
  $('#kalibrierungKpis').innerHTML = [
    ['Prognosen', num(d.gesamt,0), `${num(d.offen,0)} offen · ${num(d.unpruefbar,0)} unprüfbar`],
    ['Geprüft', num(d.geprueft,0), `${num(d.manuell,0)} manuell · ${num(d.auto,0)} Intel`],
    ['Trefferquote', quote, `${num(d.treffer,0)} Treffer aus geprüften`],
    ['Brier-Score', brier, '0 = sicher richtig, 1 = sicher falsch'],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const statusText = f => {
    const e = f.ergebnis;
    if(e && e.eingetreten === 1) return 'eingetreten';
    if(e && e.eingetreten === 0) return 'nicht eingetreten';
    return f.status || 'offen';
  };
  const statusPill = f => {
    const e = f.ergebnis;
    if(e && e.eingetreten === 1) return 'g';
    if(e && e.eingetreten === 0) return 'r';
    return f.status === 'unpruefbar' ? 'g' : 'w';
  };
  const liste = d.letzte || [];
  $('#kalibrierungList').innerHTML = liste.length ? liste.map(f=>`
    <div class="li"><span><b style="font-weight:400">${esc(f.aussage)}</b>
      <small>${esc(f.kennung)} · ${esc(f.symbol || 'ohne Symbol')} · ${num(f.konfidenz,2)} Konfidenz</small></span>
      <span class="pill ${statusPill(f)}">${esc(statusText(f))}</span></div>`).join('')
    : '<div class="empty">Noch keine Prognose. Neue Marktprognosen erscheinen hier.</div>';
  const klassen = d.kalibrierungsklassen || [];
  $('#kalibrierungKlassen').innerHTML = klassen.some(k=>k.n) ? `<table class="tbl"><thead><tr><th>Konfidenz</th><th class="m">n</th><th class="m">Treffer</th><th class="m">Quote</th><th class="m">Brier</th></tr></thead><tbody>
    ${klassen.map(k=>`<tr><td>${esc(k.klasse)}</td><td class="m">${num(k.n,0)}</td><td class="m">${num(k.treffer,0)}</td><td class="m">${k.quote==null?'–':pct(k.quote*100,1)}</td><td class="m">${k.brier==null?'–':num(k.brier,4)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Noch keine Kalibrierungsklassen. Sie füllen sich erst mit geprüften Prognosen.</div>';
  $('#kalibrierungHinweis').textContent = d.hinweis || '';
}

document.querySelectorAll('#graphWindow [data-w]').forEach(btn => {
  btn.addEventListener('click', () => {
    graphWindow = btn.dataset.w || '7d';
    document.querySelectorAll('#graphWindow [data-w]').forEach(b=>b.classList.toggle('on', b===btn));
    ladeGraph();
  });
});

function kurzZeit(wert){
  if(!wert) return '';
  const d = new Date(wert);
  if(Number.isNaN(d.getTime())) return String(wert).slice(0,16).replace('T',' ');
  return new Intl.DateTimeFormat('de-CH',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);
}

function renderSpider(){
  ladeNacht();
  const sp = R.spider || {};
  const stat = sp.statistik || {};
  const artikel = sp.artikel || [];
  const it = R.intel || {};
  const is = it.statistik || {};
  const nachStatus = is.nach_status || {};
  const auftraege = it.auftraege || [];
  const weiter = it.weiterleitungen || [];
  const quellen = it.quellen || [];
  const offen = nachStatus['offen'] ?? 0;

  $('#spiderKpis').innerHTML = [
    ['Quellen', sp.quellen ?? 0, 'RSS-Feeds im Lauf'],
    ['Gelesen', sp.gelesen ?? 0, 'Artikel im Lauf'],
    ['Analysiert', is.analysiert ?? sp.analysiert ?? 0, 'Volltext geprüft'],
    ['Neu', sp.neu ?? 0, 'in die Datenbank'],
    ['Aufträge', is.auftraege ?? 0, `${offen} offen`],
    ['Bestätigt', nachStatus['bestätigt'] ?? 0, 'Hypothesen belegt'],
    ['Widerlegt', nachStatus['widerlegt'] ?? 0, 'Hypothesen verworfen'],
    ['Weiterleitungen', is.weiterleitungen ?? 0, `${is.weiterleitungen_offen ?? 0} offen`],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const quelStatus = Object.fromEntries((sp.quellen_status||[]).map(q=>[q.name,q]));
  const intervall = sp.intervall_minuten;
  $('#spiderTag').textContent = intervall
    ? `${artikel.length} Einträge · Abruf alle ${intervall} min`
    : `${artikel.length} Einträge`;
  $('#spiderList').innerHTML = artikel.length ? artikel.map(a=>{
    const stufe = String(a.prioritaet||'').toLowerCase();
    const stufePill = stufe==='kritisch' ? 'r' : (stufe==='wichtig' ? 'w' : 'g');
    const zeiten = [`erkannt ${kurzZeit(a.erkannt||a.geholt) || '–'}`];
    if(a.veroeffentlicht) zeiten.push(`veröffentlicht ${kurzZeit(a.veroeffentlicht)}`);
    return `<div class="li"${a.prioritaet_grund?` title="${esc(a.prioritaet_grund)}"`:''}>
    <span><b style="font-weight:400">${esc(a.titel)}</b>
    <small>${esc(a.quelle)} · ${esc(a.typ)}${a.symbole?` · ${esc(a.symbole)}`:''} · ${zeiten.join(' · ')}</small></span>
    <span style="display:inline-flex;gap:6px"><span class="pill ${stufePill}">${esc(stufe||'unbekannt')}</span>
    <span class="pill ${a.qualitaet>=0.7?'':'w'}">${num(a.qualitaet,2)}</span></span></div>`;
  }).join('')
    : '<div class="empty">Noch keine Artikel. Auf «Recherche starten» klicken.</div>';

  const intelQuelle = Object.fromEntries(quellen.map(q=>[q.quelle,q]));
  const quellListe = (sp.quellen_status||[]).length ? sp.quellen_status.map(q=>q.name) : quellen.map(q=>q.quelle);
  const quellZeile = name => {
    const s = quelStatus[name] || {};
    const i = intelQuelle[name] || {};
    const letzte = s.letzter_abruf ? kurzZeit(s.letzter_abruf) : '–';
    let status = '<span class="pill w">noch nicht abgerufen</span>';
    if(s.status === 'fehler') status = '<span class="pill r">Fehler</span>';
    else if(s.letzter_abruf) status = `<span class="pill g">${s.gelesen ?? 0} gelesen</span>`;
    return `<tr><td>${esc(name)}</td><td class="m">${i.artikel ?? 0}</td><td class="m">${i.qualitaet != null ? num(i.qualitaet,2) : '–'}</td>
    <td class="m up">${i.bestaetigt ?? 0}</td><td class="m dn">${i.widerlegt ?? 0}</td>
    <td class="m">${letzte}</td><td class="m">${status}</td></tr>`;
  };
  $('#spiderQuellen').innerHTML = quellListe.length ? `<table class="tbl"><thead><tr><th>Quelle</th><th class="m">Artikel</th><th class="m">Ø Qualität</th><th class="m">belegt</th><th class="m">verworfen</th><th class="m">letzter Abruf</th><th class="m">Status</th></tr></thead><tbody>
    ${quellListe.map(quellZeile).join('')}</tbody></table>`
    : '<div class="empty">Keine Quelle konfiguriert.</div>';

  const pill = s => s==='bestätigt' ? 'g' : (s==='widerlegt' ? 'r' : (s==='offen' ? 'w' : 'g'));
  const auftragStatus = it.auftrag_status || [];
  $('#intelTag').textContent = `${auftraege.length} · ${offen} offen`;
  $('#intelAuftraege').innerHTML = auftraege.length ? auftraege.map(a=>{
    const st = auftragStatus.includes(a.status) ? auftragStatus : [a.status, ...auftragStatus];
    return `<div class="li ord" data-kennung="${esc(a.kennung)}">
    <div class="wlTop"><span><b style="font-weight:400">${esc(a.titel)}</b>
      <small>${esc(a.kennung)} · Abt. ${esc(a.abteilung)}</small></span>
      <span class="pill ${pill(a.status)}">${esc(a.status)}</span></div>
    ${a.ergebnis?`<div class="ordErg">${esc(a.ergebnis)}</div>`:''}
    <details class="ordEdit"><summary>Status und Ergebnis bearbeiten</summary>
      <div class="ordCtl">
        <label>Status<select data-a="status">${st.map(s=>`<option value="${esc(s)}"${s===a.status?' selected':''}>${esc(s)}</option>`).join('')}</select></label>
        <label>Ergebnis<textarea data-a="ergebnis" rows="2" placeholder="Beleg, Messung oder Begründung">${esc(a.ergebnis || '')}</textarea></label>
        <button type="button" class="toggle" data-save>Speichern</button>
      </div>
    </details></div>`;}).join('')
    : '<div class="empty">Noch keine Forschungsaufträge.</div>';

  const wlStatus = it.weiterleitung_status || [];
  const abteilungen = it.abteilungen || [];
  $('#intelWeiter').innerHTML = weiter.length ? weiter.map(w=>{
    const abt = abteilungen.includes(w.an) ? abteilungen : [w.an, ...abteilungen];
    const st = wlStatus.includes(w.status) ? wlStatus : [w.status, ...wlStatus];
    const wlPill = w.status==='neu' ? 'w' : (w.status==='erledigt' ? 'g' : 'b');
    return `<div class="li wl" data-kennung="${esc(w.kennung)}">
    <div class="wlTop"><span><b style="font-weight:400">${esc(w.betreff)}</b>
      <small>${esc(w.kennung)} · ${esc(w.von)}</small></span>
      <span class="pill ${wlPill}">${esc(w.status)}</span></div>
    <div class="wlCtl">
      <label>Abteilung<select data-wl="an">${abt.map(a=>`<option value="${esc(a)}"${a===w.an?' selected':''}>${esc(a)}</option>`).join('')}</select></label>
      <label>Status<select data-wl="status">${st.map(s=>`<option value="${esc(s)}"${s===w.status?' selected':''}>${esc(s)}</option>`).join('')}</select></label>
    </div></div>`;}).join('')
    : '<div class="empty">Noch keine Weiterleitungen.</div>';

  ladeGraph();
  ladeKalibrierung();
}

$('#spiderBtn') && ($('#spiderBtn').onclick = async () => {
  const b = $('#spiderBtn'); b.disabled = true; b.textContent = 'Recherche läuft …';
  try{
    const r = await fetch('/api/spider', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Recherche fehlgeschlagen');
    await lade();
  }catch(e){
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(e.message);
  }finally{
    b.disabled = false; b.textContent = 'Recherche starten';
  }
});

$('#intelAuftraege').addEventListener('click', async e => {
  const b = e.target.closest('button[data-save]');
  if(!b) return;
  const box = b.closest('[data-kennung]');
  const status = box.querySelector('select[data-a="status"]').value;
  const ergebnis = box.querySelector('textarea[data-a="ergebnis"]').value.trim();
  if(status !== 'offen' && !ergebnis){
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>Ein abgeschlossener Auftrag braucht ein Ergebnis.';
    return;
  }
  box.querySelectorAll('select, textarea, button').forEach(el=>el.disabled = true);
  try{
    const r = await fetch('/api/intel/auftrag', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({kennung: box.dataset.kennung, status, ergebnis})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Auftrag konnte nicht gespeichert werden');
    await lade();
  }catch(err){
    box.querySelectorAll('select, textarea, button').forEach(el=>el.disabled = false);
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(err.message);
  }
});

$('#intelWeiter').addEventListener('change', async e => {
  const sel = e.target.closest('select[data-wl]');
  if(!sel) return;
  const box = sel.closest('[data-kennung]');
  const abt = box.querySelector('select[data-wl="an"]');
  const st = box.querySelector('select[data-wl="status"]');
  // Neue Abteilung heisst: dort ist die Weiterleitung noch nicht übernommen.
  if(sel.dataset.wl === 'an') st.value = 'neu';
  box.querySelectorAll('select').forEach(s=>s.disabled = true);
  try{
    const q = new URLSearchParams({kennung: box.dataset.kennung,
      abteilung: abt.value, status: st.value});
    const r = await fetch('/api/intel/weiterleitung?' + q, {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Weiterleitung konnte nicht gespeichert werden');
    await lade();
  }catch(err){
    box.querySelectorAll('select').forEach(s=>s.disabled = false);
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(err.message);
  }
});

/* ---------- Missionen ---------- */
const missionFehler = text => {
  $('#banner').className = 'banner b-sim';
  $('#banner').innerHTML = '<b>FEHLER</b>' + esc(text);
};

const missionBtn = $('#missionBtn');
if (missionBtn) missionBtn.onclick = async () => {
  const titel = $('#missionTitel').value.trim();
  const auftrag = $('#missionAuftrag').value.trim();
  const prioritaet = $('#missionPrio').value;
  if(titel.length < 3 || auftrag.length < 10){
    missionFehler('Titel (min. 3 Zeichen) und Auftrag (min. 10 Zeichen) sind Pflicht.');
    return;
  }
  missionBtn.disabled = true;
  missionBtn.textContent = 'Mission läuft …';
  try{
    const r = await fetch('/api/nexus/mission', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({titel, auftrag, prioritaet})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Mission konnte nicht angelegt werden');
    const kennung = d.mission?.kennung;
    if(kennung){
      const r2 = await fetch('/api/nexus/mission/' + encodeURIComponent(kennung) + '/lauf?max_tasks=10', {method:'POST'});
      const d2 = await r2.json();
      if(!d2.ok) throw new Error(d2.fehler || 'Mission konnte nicht laufen');
    }
    $('#missionTitel').value = '';
    $('#missionAuftrag').value = '';
    await ladeNacht();
  }catch(e){
    missionFehler(e.message);
  }finally{
    missionBtn.disabled = false;
    missionBtn.textContent = 'Mission anlegen & starten';
  }
};

const missionList = $('#missionList');
if (missionList) missionList.addEventListener('click', async e => {
  const box = e.target.closest('[data-kennung]');
  if(!box) return;
  const kennung = box.dataset.kennung;
  if(e.target.closest('[data-mission-lauf]')){
    const b = e.target.closest('button');
    b.disabled = true;
    try{
      const r = await fetch('/api/nexus/mission/' + encodeURIComponent(kennung) + '/lauf?max_tasks=10', {method:'POST'});
      const d = await r.json();
      if(!d.ok) throw new Error(d.fehler || 'Mission konnte nicht laufen');
      await ladeNacht();
    }catch(err){
      missionFehler(err.message);
      b.disabled = false;
    }
    return;
  }
  const berichtBtn = e.target.closest('[data-mission-bericht]');
  if(!berichtBtn) return;
  const pre = box.querySelector('.mission-report');
  if(pre && !pre.hidden){
    pre.hidden = true;
    pre.textContent = '';
    berichtBtn.textContent = 'Bericht';
    berichtBtn.setAttribute('aria-expanded', 'false');
    return;
  }
  berichtBtn.disabled = true;
  try{
    const r = await fetch('/api/nexus/mission/' + encodeURIComponent(kennung), {cache:'no-store'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Bericht konnte nicht geladen werden');
    const bericht = d.mission?.bericht || {};
    if(pre){
      pre.textContent = bericht.text || bericht.fehler || 'Kein Bericht gespeichert.';
      pre.hidden = false;
      berichtBtn.textContent = 'Schließen';
      berichtBtn.setAttribute('aria-expanded', 'true');
    }
  }catch(err){
    missionFehler(err.message);
  }finally{
    berichtBtn.disabled = false;
  }
});

const forecastBtn = $('#forecastBtn');
if (forecastBtn) forecastBtn.onclick = async () => {
  const aussage = $('#forecastAussage').value.trim();
  const symbol = $('#forecastSymbol').value.trim().toUpperCase();
  const erwartung = $('#forecastErwartung').value;
  const zeithorizont = $('#forecastHorizont').value.trim() || '24h';
  const konfidenz = Number($('#forecastKonfidenz').value);
  if(aussage.length < 5 || !symbol){
    phase6Fehler('Aussage (min. 5 Zeichen) und Symbol sind Pflicht.');
    return;
  }
  if(!Number.isFinite(konfidenz) || konfidenz < 0 || konfidenz > 1){
    phase6Fehler('Konfidenz muss zwischen 0 und 1 liegen.');
    return;
  }
  forecastBtn.disabled = true;
  forecastBtn.textContent = 'Wird angelegt …';
  try {
    const r = await fetch('/api/nexus/prognose', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({aussage, erwartung, symbol, zeithorizont, konfidenz})});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Prognose konnte nicht angelegt werden');
    $('#forecastAussage').value = '';
    $('#forecastSymbol').value = '';
    await ladeKalibrierung();
    await ladeNacht();
  } catch(e) {
    phase6Fehler(e.message);
  } finally {
    forecastBtn.disabled = false;
    forecastBtn.textContent = 'Prognose anlegen';
  }
};

/* ---------- Laden ---------- */
async function lade(){
  try{
    const r = await fetch('/api/report',{cache:'no-store'});
    R = await r.json();
    renderTop();
    zeichne();
  }catch(e){
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(e.message);
  }
}
$('#runBtn').onclick = async () => {
  const b = $('#runBtn'); b.disabled = true; b.textContent = 'Lauf läuft …';
  try{
    const r = await fetch('/api/lauf?modus=backtest',{method:'POST'});
    if(!r.ok) throw new Error('Lauf konnte nicht gestartet werden');
    await r.json();
    await lade();
  }catch(e){
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(e.message);
  }finally{
    b.disabled = false; b.textContent = 'Lauf starten';
  }
};
lade();
// Kein Auto-Refresh, während ein Auftrag bearbeitet wird oder ein Feld den Fokus hat:
// sonst gehen Eingaben nach acht Sekunden verloren.
setInterval(() => {
  if (document.querySelector('details.ordEdit[open]')) return;
  // Ein geöffneter Missionsbericht darf nicht unter dem Leser verschwinden.
  if (document.querySelector('.mission-report:not([hidden])')) return;
  const a = document.activeElement;
  if (a && /^(SELECT|TEXTAREA|INPUT)$/.test(a.tagName)) return;
  lade();
}, 8000);
let sitzungDaten = null;
let protokolleDaten = [];
let altStunden = 1;
let altStundenServer = 1;
let altStundenWahl = parseInt(localStorage.getItem('mtgAltStunden') || '0', 10) || 0;
let altFilter = false;
let blockFilter = false;
let tradeNurAbw = false;
const SEKN = {S1:'Mira', S2:'Jonas', S3:'Lea'};

async function ladeSitzung(){
  try{
    const r = await fetch('/api/sitzung', {cache:'no-store'});
    sitzungDaten = await r.json();
  }catch(e){ sitzungDaten = null; }
  if(sitzungDaten && sitzungDaten.alt_stunden) altStundenServer = Number(sitzungDaten.alt_stunden) || 1;
  altStunden = altStundenWahl || altStundenServer;
  updateTaktStand();
  try{ renderSitzung(); }catch(e){ console.error('renderSitzung', e); }
  zeigeAltZahl();
  try{ renderProtokolle(); }catch(e){ console.error('renderProtokolle', e); }
}

function mdInline(t){
  return t.split(/(`[^`]+`)/).map(teil => {
    if(/^`[^`]+`$/.test(teil))
      return '<code>' + teil.slice(1, -1) + '</code>';
    return teil
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  }).join('');
}

function md(text){
  const zeilen = esc(text || '').split('\n');
  const aus = [];
  let liste = null;
  const schliesseListe = () => { if(liste){ aus.push('</' + liste + '>'); liste = null; } };
  const zellen = zeile => zeile.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
    .split('|').map(c => c.trim());
  for(let i = 0; i < zeilen.length; i++){
    const z = zeilen[i].replace(/\s+$/, '');
    if(z.trim().startsWith('```')){
      schliesseListe();
      const code = [];
      i += 1;
      while(i < zeilen.length && !zeilen[i].trim().startsWith('```')){
        code.push(zeilen[i]);
        i += 1;
      }
      aus.push('<pre><code>' + code.join('\n') + '</code></pre>');
      continue;
    }
    const istZitat = t => t.trim().startsWith('>') || t.trim().startsWith('&gt;');
    if(istZitat(z)){
      schliesseListe();
      const zitat = [];
      while(i < zeilen.length && istZitat(zeilen[i])){
        zitat.push(zeilen[i].replace(/^\s*(?:>|&gt;)\s?/, ''));
        i += 1;
      }
      i -= 1;
      aus.push('<blockquote>' + zitat.map(t => mdInline(t)).join('<br>') + '</blockquote>');
      continue;
    }
    const naechste = (zeilen[i + 1] || '').trim();
    const istTabelle = z.trim().startsWith('|') && naechste.includes('-')
      && /^[\s|:-]+$/.test(naechste);
    if(istTabelle){
      schliesseListe();
      aus.push('<table><thead><tr>' + zellen(z).map(c => '<th>' + mdInline(c) + '</th>').join('') + '</tr></thead><tbody>');
      i += 1;
      while(i + 1 < zeilen.length && (zeilen[i + 1] || '').trim().startsWith('|')){
        i += 1;
        aus.push('<tr>' + zellen(zeilen[i]).map(c => '<td>' + mdInline(c) + '</td>').join('') + '</tr>');
      }
      aus.push('</tbody></table>');
      continue;
    }
    if(/^\s*[-*]\s+/.test(z) || /^\s*\d+[.)]\s+/.test(z)){
      const typ = /^\s*\d+[.)]\s+/.test(z) ? 'ol' : 'ul';
      if(liste !== typ){ schliesseListe(); aus.push('<' + typ + '>'); liste = typ; }
      aus.push('<li>' + mdInline(z.replace(/^\s*(?:[-*]|\d+[.)])\s+/, '')) + '</li>');
      continue;
    }
    schliesseListe();
    const h = z.match(/^(#{1,4})\s+(.*)$/);
    if(h){ const n = Math.min(4, h[1].length + 2); aus.push('<h' + n + '>' + mdInline(h[2]) + '</h' + n + '>'); continue; }
    aus.push(z ? '<p>' + mdInline(z) + '</p>' : '');
  }
  schliesseListe();
  return aus.join('\n');
}

function quickZeitraum(tage){
  protoTage = (protoTage === tage) ? 0 : tage;
  if(protoTage){
    const lokal = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0')].join('-');
    const jetzt = new Date();
    protoVon = lokal(new Date(jetzt.getFullYear(), jetzt.getMonth(), jetzt.getDate() - protoTage));
    protoBis = lokal(jetzt);
  } else {
    protoVon = '';
    protoBis = '';
  }
  renderProtokolle();
}

let protoSuche = '', protoFilter = '', protoTimer = null;
let protoVon = '', protoBis = '', protoSort = 'neu', protoVault = false, protoTage = 0;

function renderProtokolle(){
  const box = $('#mtgProto');
  if(!box) return;
  box.innerHTML = `<div class="sekAgendaHead"><span>Vergangene Sitzungen</span><span id="protoZahl">…</span></div>
    <div class="protoTools">
      <input id="protoSuche" placeholder="Im ganzen Vault suchen …">
      <select id="protoFilter">
        ${[['', 'alle Entscheide'], ['angenommen', 'angenommen'], ['abgelehnt', 'abgelehnt'], ['vertagt', 'vertagt'], ['offen', 'offen']]
          .map(([v, l]) => `<option value="${v}"${protoFilter === v ? ' selected' : ''}>${l}</option>`).join('')}
      </select>
      <input type="date" id="protoVon" title="Sitzungen ab">
      <input type="date" id="protoBis" title="Sitzungen bis">
      <button type="button" class="protoQuick${protoTage === 7 ? ' on' : ''}" data-tage="7">7 Tage</button>
      <button type="button" class="protoQuick${protoTage === 30 ? ' on' : ''}" data-tage="30">30 Tage</button>
      <span id="protoZeitraum" class="protoZeit"></span>
      <select id="protoSort">
        <option value="neu"${protoSort === 'neu' ? ' selected' : ''}>neueste zuerst</option>
        <option value="alt"${protoSort === 'alt' ? ' selected' : ''}>älteste zuerst</option>
      </select>
      <label class="protoVault"><input type="checkbox" id="protoVault"${protoVault ? ' checked' : ''}> ganzer Vault</label>
    </div>
    <div id="protoListe"><div class="sekStand">Wird geladen …</div></div>`;
  const suche = $('#protoSuche'), filter = $('#protoFilter');
  if(suche){
    suche.value = protoSuche;
    suche.oninput = () => {
      protoSuche = suche.value;
      clearTimeout(protoTimer);
      protoTimer = setTimeout(ladeProtokolle, 300);
    };
  }
  if(filter){
    filter.value = protoFilter;
    filter.onchange = () => { protoFilter = filter.value; ladeProtokolle(); };
  const von = $('#protoVon'), bis = $('#protoBis'), sort = $('#protoSort');
  if(von){ von.value = protoVon; von.onchange = () => { protoVon = von.value; ladeProtokolle(); }; }
  if(bis){ bis.value = protoBis; bis.onchange = () => { protoBis = bis.value; ladeProtokolle(); }; }
  if(sort){ sort.value = protoSort; sort.onchange = () => { protoSort = sort.value; ladeProtokolle(); }; }
  const vault = $('#protoVault');
  if(vault){ vault.checked = protoVault; vault.onchange = () => { protoVault = vault.checked; ladeProtokolle(); }; }
  document.querySelectorAll('.protoQuick').forEach(b => { b.onclick = () => quickZeitraum(parseInt(b.dataset.tage, 10)); });
  }
  ladeProtokolle();
}

async function ladeProtokolle(){
  const box = $('#protoListe');
  if(!box) return;
  const zeitraum = $('#protoZeitraum');
  if(zeitraum) zeitraum.textContent = (protoVon || protoBis)
    ? 'Zeitraum: ' + (protoVon || '…') + ' – ' + (protoBis || '…') : '';
  try{
    const qs = protoVault
      ? new URLSearchParams({suche: protoSuche, entscheid: protoFilter, von: protoVon, bis: protoBis, sortierung: protoSort, limit: '50'})
      : new URLSearchParams({suche: protoSuche, entscheid: protoFilter, von: protoVon, bis: protoBis, sortierung: protoSort, limit: '50'});
    const pfad = protoVault ? '/api/vault/suche' : '/api/sitzung/protokolle';
    const r = await fetch(pfad + '?' + qs.toString(), {cache: 'no-store'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Fehler');
    const liste = protoVault ? (d.treffer || []) : (d.protokolle || []);
    const zahl = $('#protoZahl');
    if(zahl) zahl.textContent = liste.length + ' / ' + (d.gesamt != null ? d.gesamt : liste.length);
    const eintrag = p => `<details class="mtgProto">
        <summary>${esc(p.titel || 'Sitzung')} <small>${esc((p.datum || p.erstellt || '').slice(0, 10))}</small></summary>
        <div class="md">${md(p.inhalt || '')}</div></details>`;
    if(!liste.length){
      box.innerHTML = '<div class="sekStand">Kein Protokoll passt zu Suche und Filter.</div>';
    } else if(!protoVault){
      box.innerHTML = liste.map(eintrag).join('');
    } else {
      const gruppen = new Map();
      liste.forEach(p => {
        const k = p.kategorie || 'ohne Kategorie';
        if(!gruppen.has(k)) gruppen.set(k, []);
        gruppen.get(k).push(p);
      });
      box.innerHTML = [...gruppen.entries()].sort((a, b) => a[0].localeCompare(b[0], 'de')).map(([k, ps]) =>
        `<div class="vaultGruppe"><div class="sekAgendaHead"><span>${esc(k)}</span><span>${ps.length}</span></div>${ps.map(eintrag).join('')}</div>`).join('');
    }
  }catch(e){
    box.innerHTML = '<div class="sekStand">Protokolle konnten nicht geladen werden.</div>';
  }
}

function musterTrades(t){
  if(!t.trades || !t.trades.length) return '';
  const liste = t.trades.slice().sort((a, b) => Number(a.netto || 0) - Number(b.netto || 0));
  const abweichend = t.trades.filter(x => x.grund && x.grund !== t.ausstieg_grund).length;
  const zusatz = ' · ' + abweichend + ' mit anderem Grund';
  const basis = `${liste.length}, Verluste zuerst${zusatz}`;
  const zahl = basis + (tradeNurAbw && abweichend ? ` · ${liste.length - abweichend} ausgeblendet` : '');
  const filter = abweichend
    ? `<label class="trFilter"><input type="checkbox" class="trNurAbw"${tradeNurAbw ? ' checked' : ''}> nur abweichender Grund (${abweichend})</label>`
    : '';
  return `<details class="musterTrades"><summary>Einzel-Trades (<span class="trZahl" data-basis="${esc(basis)}">${esc(zahl)}</span>)</summary>${filter}<div class="trKopf" aria-hidden="true"><span>Betrag</span><span>Prozent</span><span>Dauer</span></div><ul${tradeNurAbw && abweichend ? ' class="nurAbw"' : ''}>` +
    liste.map(x => `<li${x.grund && x.grund !== t.ausstieg_grund ? ' class="abweichend"' : ''}><b class="trSym">${esc(x.symbol || '')}</b><span class="trDatum">${esc(String(x.einstieg || '').slice(0, 10))} → ${esc(String(x.ausstieg || '').slice(0, 10))}</span><span class="trNet ${Number(x.netto || 0) >= 0 ? 'plus' : 'minus'}">${Number(x.netto || 0).toFixed(2)}</span><span class="trRend ${Number(x.netto || 0) >= 0 ? 'plus' : 'minus'}">${Number(x.rendite || 0).toFixed(2)} %</span>${x.dauer != null ? '<span class="trDauer">' + esc(String(x.dauer)) + ' Min.</span>' : ''}${x.grund && x.grund !== t.ausstieg_grund ? '<span class="trGrund">' + esc(x.grund) + '</span>' : ''}</li>`).join('') +
    '</ul></details>';
}

function dauerSeit(iso){
  const t = Date.parse(iso);
  if(!t) return '';
  const min = Math.max(0, Math.round((Date.now() - t) / 60000));
  if(min < 1) return 'gerade eben';
  if(min < 60) return 'vor ' + min + ' Min.';
  const std = Math.round(min / 60);
  if(std < 48) return 'vor ' + std + ' Std.';
  return 'vor ' + Math.round(std / 24) + ' Tg.';
}

function zeigeAltZahl(){
  const el = document.querySelector('#mtgAltZahl');
  if(!el) return;
  const n = document.querySelectorAll('.mtask.alt').length;
  const bloecke = [...document.querySelectorAll('.mtasks')]
    .filter(g => g.querySelector('.mtask.alt')).length;
  if(blockFilter && !bloecke) blockFilter = false;
  if(altFilter && !n){ altFilter = false; document.body.classList.remove('nurAlt'); }
  el.textContent = n + ' veraltet';
  el.classList.toggle('on', altFilter);
  el.setAttribute('aria-pressed', altFilter ? 'true' : 'false');
  const blockZahl = document.querySelector('#mtgBlockZahl');
  if(blockZahl){
    blockZahl.hidden = !bloecke;
    blockZahl.textContent = bloecke + (bloecke === 1 ? ' Block' : ' Blöcke');
    blockZahl.classList.toggle('on', blockFilter);
    blockZahl.setAttribute('aria-pressed', blockFilter ? 'true' : 'false');
  }
  document.body.classList.toggle('nurAltBloecke', blockFilter && !!bloecke);
  const filterAktiv = altFilter || blockFilter;
  document.querySelectorAll('.mtasks').forEach(g => {
    g.classList.toggle('ohneAlt', filterAktiv && !g.querySelector('.mtask.alt'));
  });
}

function taskAlt(x){
  if(!x.geaendert || x.status === 'erledigt' || x.status === 'fehlgeschlagen') return false;
  const t = Date.parse(x.geaendert);
  return !!t && (Date.now() - t) > altStunden * 3600000;
}

function taskZeitText(x){
  const wert = x.abgeschlossen_am || x.fehlgeschlagen_am || x.geaendert;
  if(!wert) return '';
  const zeit = String(wert).slice(0, 16).replace('T', ' ');
  const dauer = dauerSeit(wert);
  const art = x.abgeschlossen_am ? 'abgeschlossen '
    : (x.fehlgeschlagen_am
        ? (x.status === 'blockiert' ? 'blockiert ' : 'fehlgeschlagen ')
        : '');
  return art + zeit + (dauer ? ' (' + dauer + ')' : '');
}

function taskZeit(x){
  const text = taskZeitText(x);
  return text ? ' · ' + text : '';
}

function renderSitzung(){
  const box = $('#mtgBody'); if(!box) return;
  const tag = $('#mtgTag');
  const s = sitzungDaten;
  const themen = (s && s.themen) || [];
  if(!s || s.status === 'offen' || !themen.length){
    if(tag) tag.textContent = 'nicht eröffnet';
    box.innerHTML = `<div class="empty">Noch keine Sitzung. Die Agenda kommt aus den echten Daten: Verlust-Trades, Befunde, Fehler, Beschlüsse.</div>
      <button type="button" class="toggle main" id="mtgStart">Sitzung eröffnen</button>`;
    if($('#mtgStart')) $('#mtgStart').onclick = sitzungStart;
    return;
  }
  const offen = themen.filter(t => t.status === 'offen');
  if(tag) tag.textContent = s.status === 'beendet' ? 'beendet' : `${themen.length - offen.length} / ${themen.length} entschieden`;
  if(s.status === 'beendet'){
    const e = s.ergebnis || {};
    box.innerHTML = `<div class="mtgResult"><b>Sitzung abgeschlossen</b>
        <span>Angenommen ${e.annehmen || 0} · Abgelehnt ${e.abgelehnt || 0} · Vertagt ${e.vertagen || 0} · Offen ${e.offen || 0}</span></div>
      <button type="button" class="toggle" id="mtgStart">Neue Sitzung</button>`;
    if($('#mtgStart')) $('#mtgStart').onclick = sitzungStart;
    return;
  }
  const t = themen.find(x => x.index === (s.aktiv ?? 0)) || offen[0];
  const sichtbar = (t.beitraege || []).slice(0, t.schritt || 0);
  const phase = t.phase || 'rede';
  const alleGeredet = sichtbar.length >= (t.beitraege || []).length;
  const zaehlText = z => z ? Object.entries(z).filter(([,v]) => v).map(([k,v]) => `${k} ${v}`).join(' · ') : '';
  box.innerHTML = `
    <div class="mtgThema">
      <small>Thema ${t.index + 1} von ${themen.length} · Leitung ${esc(SEKN[t.leiter] || t.leiter)} · ${esc(t.art)}${t.vertagt ? ' · aus letzter Sitzung vertagt' : ''}</small>
      <b>${esc(t.thema)}</b>
      <p class="mtgFakt">${esc(t.gemacht)}</p>
      ${musterTrades(t)}
      ${sichtbar.map(b => `<div class="mtgWort"><span>${esc(SEKN[b.von] || b.von)}</span>${esc(b.text)}</div>`).join('')}
      ${phase !== 'rede' ? `<div class="mtgEmpf">Massnahme: ${esc(t.massnahme || t.empfehlung || '')}</div>` : ''}
      ${phase === 'ergebnis' ? `<div class="mtgStimmen">${(t.stimmen || []).map(x => `<span><b>${esc(SEKN[x.von] || x.von)}</b> <i>${esc(x.entscheid)}</i> — ${esc(x.grund)}</span>`).join('')}</div>` : ''}
      ${t.ergebnis ? `<div class="mtgErg">Beschluss: <b>${esc({annehmen:'angenommen', ablehnen:'abgelehnt', vertagen:'vertagt'}[t.ergebnis] || t.ergebnis)}</b> <small>${esc(zaehlText(t.zaehlung))}</small></div>` : ''}
      ${t.ueberstimmung ? `<div class="mtgErg">CEO-Überstimmung: ${esc(t.ueberstimmung.vorher)} → <b>${esc(t.ueberstimmung.entscheid)}</b> <small>${esc(t.ueberstimmung.begruendung)}</small></div>` : ''}
      ${phase === 'ergebnis' ? `<details class="mtgOverride"><summary>Als CEO überstimmen</summary>
        <select id="ovEntscheid">${['annehmen','ablehnen','vertagen'].filter(v => v !== t.ergebnis).map(v => `<option value="${v}">${v}</option>`).join('')}</select>
        <input id="ovGrund" maxlength="300" placeholder="Begründung (Pflicht)">
        <button type="button" id="ovBtn">Überstimmen</button></details>` : ''}
      ${(s.entscheide || []).filter(e => e.index === t.index && e.mission).map(e => `<div class="mtgErg">Weitergeleitet: <b>${esc(e.mission)}</b> <small class="mstat" data-mission="${esc(e.mission)}">${esc(e.abteilung || '')} · ${esc(e.mission_status || 'offen')}${e.mission_fortschritt != null ? ' · ' + esc(String(e.mission_fortschritt)) + '%' : ''}${e.mission_geaendert ? ' · ' + esc(String(e.mission_geaendert).slice(0, 16).replace('T', ' ')) : ''}</small></div>`).join('')}
      ${(s.entscheide || []).filter(e => e.index === t.index && e.mission).map(e => (e.mission_tasks || []).length ? `<div class="mtasks">${e.mission_tasks.map(x => `<div class="mtask${taskAlt(x) ? ' alt' : ''}"><b>${esc(x.rolle)}</b><span class="mtaskstat" data-mission="${esc(e.mission)}" data-rolle="${esc(x.rolle)}">${esc(x.status)}</span><small class="mtaskzeit">${esc(taskZeitText(x))}</small>${x.fehler && (x.status === 'blockiert' || x.status === 'fehlgeschlagen') ? `<small class="mtaskgrund">Grund: ${esc(x.fehler)}</small>` : ''}<small class="mtaskziel">Ziel: ${esc(x.ziel || '')}</small>${x.ergebnis && Object.keys(x.ergebnis).length ? `<small class="mtaskres">Ergebnis: ${esc(Object.entries(x.ergebnis).filter(([k, v]) => v != null && v !== '').map(([k, v]) => k + ': ' + (typeof v === 'string' ? v : JSON.stringify(v))).join(' · '))}</small>` : ''}</div>`).join('')}</div>` : '').join('')}
      <div class="mtgVote">
        <button type="button" id="mtgWeiter">${phase === 'rede' ? (alleGeredet ? 'Abstimmung' : 'Nächste Wortmeldung') : phase === 'abstimmung' ? 'Abstimmung durchführen' : (offen.some(x => x.index !== t.index) ? 'Nächstes Thema' : 'Sitzung abschließen')}</button>
      </div>
    </div>
    ${s.entscheide && s.entscheide.length ? `<div class="mtgLog">${s.entscheide.map(e => `<span>${esc(e.entscheid)} · ${esc(e.thema)}${e.zaehlung ? ' (' + esc(zaehlText(e.zaehlung)) + ')' : ''}${e.mission ? ' → ' + esc(e.mission) + (e.mission_status ? ' [' + esc(e.mission_status) + ']' : '') : ''}</span>`).join('')}</div>` : ''}
    <button type="button" class="toggle" id="mtgEnd">Sitzung abschließen</button>`;
  box.querySelectorAll('.trNurAbw').forEach(cb => {
    cb.onchange = () => {
      tradeNurAbw = cb.checked;
      const ul = cb.closest('details')?.querySelector('ul');
      if(ul) ul.classList.toggle('nurAbw', tradeNurAbw);
      const zahl = cb.closest('details')?.querySelector('.trZahl');
      if(zahl){
        const alle = cb.closest('details').querySelectorAll('ul li').length;
        const abw = cb.closest('details').querySelectorAll('ul li.abweichend').length;
        zahl.textContent = (zahl.dataset.basis || '') +
          (tradeNurAbw && abw ? ` · ${alle - abw} ausgeblendet` : '');
      }
    };
  });
  if($('#mtgWeiter')) $('#mtgWeiter').onclick = sitzungWeiter;
  if($('#mtgEnd')) $('#mtgEnd').onclick = sitzungAbschluss;
  if($('#ovBtn')) $('#ovBtn').onclick = async () => {
    const grund = (($('#ovGrund') || {}).value || '').trim();
    if(!grund){ if($('#ovGrund')) $('#ovGrund').focus(); return; }
    try{
      const r = await fetch('/api/sitzung/ueberstimmen', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({index: t.index, entscheid: ($('#ovEntscheid') || {}).value, begruendung: grund})});
      const d = await r.json();
      if(!d.ok) throw new Error(d.fehler || 'Überstimmung fehlgeschlagen');
      sitzungDaten = d; renderSitzung();
    }catch(e){
      box.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    }
  };
  zeigeAltZahl();
}

async function sitzungWeiter(){
  try{
    const r = await fetch('/api/sitzung/weiter', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Nächster Schritt fehlgeschlagen');
    const vorher = sitzungDaten && sitzungDaten.status;
    sitzungDaten = d;
    renderSitzung();
    ladeSitzung();
    if(d.status === 'beendet' && vorher !== 'beendet') toast('Sitzung abgeschlossen.');
  }catch(e){
    const b = $('#mtgBody');
    if(b) b.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    toast('Sitzungsschritt fehlgeschlagen.');
  }
}

async function sitzungStart(){
  try{
    const r = await fetch('/api/sitzung/start', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Sitzung konnte nicht eröffnet werden');
    sitzungDaten = d;
    await ladeSitzung();
    toast('Sitzung eröffnet.');
  }catch(e){
    const b = $('#mtgBody');
    if(b) b.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    toast('Sitzung konnte nicht eröffnet werden.');
  }
}

async function sitzungAbschluss(){
  try{
    const r = await fetch('/api/sitzung/abschluss', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Abschluss fehlgeschlagen');
    sitzungDaten = d; renderSitzung(); await ladeSitzung();
    toast('Sitzung abgeschlossen.');
  }catch(e){
    const b = $('#mtgBody'); if(b) b.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    toast('Abschluss fehlgeschlagen.');
  }
}


let missionTimer = null;

async function aktualisiereMissionen(){
  if(document.hidden) return;
  if(!sitzungDaten || !(sitzungDaten.entscheide || []).length) return;
  try{
    const r = await fetch('/api/sitzung', {cache:'no-store'});
    const d = await r.json();
    if(!d || !d.ok) return;
    (d.entscheide || []).forEach(e => {
      if(!e.mission) return;
      const alt = (sitzungDaten.entscheide || []).find(x => x.mission === e.mission);
      if(alt && alt.mission_status !== e.mission_status)
        logMission(e.mission + ': ' + (alt.mission_status || 'offen') + ' → ' + (e.mission_status || 'offen'));
      const el = document.querySelector('.mstat[data-mission="' + e.mission + '"]');
      if(el) el.textContent = (e.abteilung || '') + ' · ' + (e.mission_status || 'offen') +
        (e.mission_fortschritt != null ? ' · ' + e.mission_fortschritt + ' %' : '') +
        (e.mission_geaendert ? ' · ' + String(e.mission_geaendert).slice(0, 16).replace('T', ' ') : '');
    });
    (d.entscheide || []).forEach(e => {
      (e.mission_tasks || []).forEach(x => {
        const el = document.querySelector('.mtaskstat[data-mission="' + e.mission + '"][data-rolle="' + x.rolle + '"]');
        if(el) el.textContent = x.status;
        const box = el && el.closest('.mtask');
        const zeitEl = box && box.querySelector('.mtaskzeit');
        if(zeitEl) zeitEl.textContent = taskZeitText(x);
        if(box) box.classList.toggle('alt', taskAlt(x));
        if(box){
          let g = box.querySelector('.mtaskgrund');
          const grund = (x.status === 'blockiert' || x.status === 'fehlgeschlagen') && x.fehler ? x.fehler : '';
          if(grund){
            if(!g){ g = document.createElement('small'); g.className = 'mtaskgrund'; }
            g.textContent = 'Grund: ' + grund;
            const anker = box.querySelector('small:not(.mtaskgrund)');
            box.insertBefore(g, anker || null);
          } else if(g){ g.remove(); }
        }
        const werte = x.ergebnis ? Object.entries(x.ergebnis).filter(([k, v]) => v != null && v !== '') : [];
        if(box && werte.length){
          let r = box.querySelector('.mtaskres');
          if(!r){ r = document.createElement('small'); r.className = 'mtaskres'; box.appendChild(r); }
          r.textContent = 'Ergebnis: ' + werte.map(([k, v]) => k + ': ' + (typeof v === 'string' ? v : JSON.stringify(v))).join(' · ');
        }
      });
    });
    sitzungDaten.entscheide = d.entscheide;
    missionZaehler += 1;
    updateTaktStand();
    zeigeAltZahl();
  }catch(err){ /* stiller Fehlschlag, nächster Takt versucht es erneut */ }
}

let missionTakt = parseInt(localStorage.getItem('mtgTakt') || '2000', 10);
let missionSichtbar = false;
let missionZaehler = 0;
let missionLog = (() => {
  try {
    const wert = JSON.parse(localStorage.getItem('mtgLog') || '[]');
    return Array.isArray(wert) ? wert.slice(0, 6) : [];
  } catch(e){ return []; }
})();

function toast(text){
  const t = document.querySelector('#toast');
  if(!t) return;
  t.textContent = text;
  t.classList.add('on');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('on'), 2500);
}

function zeigeMissionLog(){
  const box = document.querySelector('#mtgLog');
  if(box) box.innerHTML = missionLog.map(x => `<div class="mtgLogZeile">${esc(x)}</div>`).join('');
  const knopf = document.querySelector('#mtgLogLeeren');
  if(knopf) knopf.disabled = !missionLog.length;
}

function setzeMissionTakt(ms, speichern){
  missionTakt = ms;
  if(speichern) localStorage.setItem('mtgTakt', String(ms));
  if(missionTimer){ clearInterval(missionTimer); missionTimer = null; }
  if(missionTakt > 0 && missionSichtbar && !document.hidden)
    missionTimer = setInterval(aktualisiereMissionen, missionTakt);
  updateTaktStand();
}

function logMission(text){
  const jetzt = new Date();
  const zeit = [jetzt.getHours(), jetzt.getMinutes(), jetzt.getSeconds()]
    .map(n => String(n).padStart(2, '0')).join(':');
  missionLog.unshift(zeit + ' · ' + text);
  missionLog = missionLog.slice(0, 6);
  try { localStorage.setItem('mtgLog', JSON.stringify(missionLog)); } catch(e){}
  zeigeMissionLog();
}

function updateTaktStand(){
  const stand = document.querySelector('#mtgTaktStand');
  if(stand){
    if(missionTakt <= 0) stand.textContent = 'pausiert';
    else if(document.hidden) stand.textContent = 'pausiert · Tab im Hintergrund';
    else if(!missionSichtbar) stand.textContent = 'pausiert · Bereich nicht sichtbar';
    else stand.textContent = 'läuft · alle ' + (missionTakt / 1000) + ' s';
    stand.classList.toggle('on', !!missionTimer);
  }
  const zahl = document.querySelector('#mtgTaktZahl');
  if(zahl) zahl.textContent = missionZaehler + (missionZaehler === 1 ? ' Aktualisierung' : ' Aktualisierungen');
  const altWahl = document.querySelector('#mtgAltWahl');
  if(altWahl) altWahl.value = String(altStundenWahl);
}

(function starteMissionstakt(){
  const panel = document.querySelector('#mtgPanel');
  const wahl = document.querySelector('#mtgTakt');
  if(wahl){
    wahl.value = String(missionTakt);
    wahl.onchange = () => setzeMissionTakt(parseInt(wahl.value, 10) || 0, true);
  }
  if(panel && 'IntersectionObserver' in window){
    new IntersectionObserver(eintraege => {
      missionSichtbar = eintraege.some(e => e.isIntersecting);
      setzeMissionTakt(missionTakt, false);
    }, {threshold: 0.05}).observe(panel);
  } else {
    missionSichtbar = true;
    setzeMissionTakt(missionTakt, false);
  }
  document.addEventListener('visibilitychange', () => setzeMissionTakt(missionTakt, false));
  const altZahl = document.querySelector('#mtgAltZahl');
  if(altZahl) altZahl.onclick = () => {
    altFilter = !altFilter;
    document.body.classList.toggle('nurAlt', altFilter);
    zeigeAltZahl();
  };
  const blockZahl = document.querySelector('#mtgBlockZahl');
  if(blockZahl) blockZahl.onclick = () => {
    blockFilter = !blockFilter;
    zeigeAltZahl();
  };
  const altWahl = document.querySelector('#mtgAltWahl');
  if(altWahl){
    altWahl.value = String(altStundenWahl);
    altWahl.onchange = () => {
      altStundenWahl = parseInt(altWahl.value, 10) || 0;
      try { localStorage.setItem('mtgAltStunden', String(altStundenWahl)); } catch(e){}
      altStunden = altStundenWahl || altStundenServer;
      updateTaktStand();
      renderSitzung();
      zeigeAltZahl();
    };
  }
  const leer = document.querySelector('#mtgLogLeeren');
  if(leer){
    let bis = 0;

    leer.onclick = () => {
      if(!missionLog.length) return;
      if(Date.now() <= bis){
        missionLog = [];
        try { localStorage.removeItem('mtgLog'); } catch(e){}
        zeigeMissionLog();
        bis = 0;
        leer.textContent = 'Leeren';
        leer.classList.remove('warn');
        toast('Log geleert.');
        return;
      }
      bis = Date.now() + 3000;
      leer.textContent = 'Wirklich leeren?';
      leer.classList.add('warn');
      clearTimeout(leer._t);
      leer._t = setTimeout(() => {
        bis = 0;
        leer.textContent = 'Leeren';
        leer.classList.remove('warn');
        toast('Nicht gelöscht.');
      }, 3000);
    };
  }
  zeigeMissionLog();
  setzeMissionTakt(missionTakt, false);
})();

/* Schmale Brücke für die Prüfskripte: die Ansichten bleiben ohne eigene Nav-Einträge erreichbar. */
window.zeige = zeige;

})();
