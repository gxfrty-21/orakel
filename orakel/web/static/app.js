/* Orakel Dashboard — liest /api/report (Schema 2) und /api/lauf. */
(() => {
const $ = s => document.querySelector(s);
const COL = { accent:'#5fe0c8', amber:'#e8b45a', good:'#62d68a', bad:'#e2616b', blue:'#8fb8ff', dim:'#55606d' };
let R = null, current = 'overview', labFilter = 'all', labSel = 0, stratSel = 0, depSel = 'A';
let globeView = null, globeFailed = false, globeWindow = '24h', globeRequest = 0, globeAbort = null, globeLoading = null;
let nachtDaten = null, nachtFehler = null;
let graphWindow = '7d', graphDaten = null, kalibrierungDaten = null;
let betriebDaten = null, betriebFehler = null, betriebTimer = null;
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
document.querySelectorAll('.nav').forEach(b => b.onclick = () => zeige(b.dataset.v));
function zeige(v){ current=v;
  if(v !== 'globe' && globeView) globeView.setActive(false);
  if(v !== 'betrieb' && betriebTimer){ clearInterval(betriebTimer); betriebTimer = null; }
  if(v === 'betrieb' && !betriebTimer){
    ladeBetrieb();
    betriebTimer = setInterval(ladeBetrieb, 30000);
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
    <div class="li"><span><b>${esc(p.symbol)} · ${esc(p.aktion)}${p.menge?' · '+num(p.menge,0)+' Stück':''}</b>
    <small>${esc(p.strategie||'')}${p.kurs?' · Kurs '+num(p.kurs,5):''}</small></span>
    <span style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
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
  $('#events').innerHTML = ev.length ? ev.map(e=>`<div class="li"><span><b style="font-weight:400">${esc(e.text)}</b>
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
  $('#costs').innerHTML = `<table class="tbl"><tbody>
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
function renderLab(){
  const v = R.validierungen||[], selbst = u => `<span class="pill ${u==='bestanden'?'':u==='abgelehnt'?'r':'g'}">${esc(u).toUpperCase()}</span>`;
  $('#labKpis').innerHTML = [['Geprüft',v.length,'Kandidaten'],['Bestanden',v.filter(x=>x.urteil==='bestanden').length,'alle Regeln erfüllt'],
    ['Abgelehnt',v.filter(x=>x.urteil==='abgelehnt').length,'mit Begründung'],['Zu wenig Daten',v.filter(x=>x.urteil==='zu wenig Daten').length,'nicht bewertbar']]
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
  const I=o.in_sample||{}, O=o.out_of_sample||{}, G=o.gesamt||{};
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
    <tr><td>Walk-Forward bestanden</td><td class="m">–</td><td class="m">–</td><td class="m">${o.walk_forward_bestanden==null?'–':Math.round(o.walk_forward_bestanden*100)+' %'}</td></tr>
    <tr><td>Zufallsvergleich (p-Wert, kleiner = besser)</td><td class="m">–</td><td class="m">–</td><td class="m">${o.zufall_p_wert==null?'nicht geprüft':num(o.zufall_p_wert,4)}</td></tr>
    </tbody></table></div>
    <div class="ph" style="border-top:1px solid var(--line)">Letzte Trades<span class="tag">nach Gebühren, rot = Verlust</span></div>
    <div class="tw"><table class="tbl"><thead><tr><th>Einstieg</th><th>Ausstieg</th><th class="m">Stück</th><th class="m">Netto</th><th class="m">Rendite</th><th>Grund</th></tr></thead><tbody>
    ${(o.trades||[]).slice(-10).reverse().map(t=>`<tr><td>${esc(t.einstieg)}</td><td>${esc(t.ausstieg)}</td><td class="m">${num(t.stueck,0)}</td>
    <td class="m ${cls(t.netto)}">${num(t.netto)}</td><td class="m ${cls(t.rendite_pct)}">${num(t.rendite_pct,2)} %</td><td>${esc(t.grund)}</td></tr>`).join('')||'<tr><td colspan="6" class="na">keine Trades</td></tr>'}
    </tbody></table></div>`;
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
  const d = v[stratSel], O = d.out_of_sample||{}, G = d.gesamt||{};
  const gewaehlt = sel.has(d.symbol+'|'+d.schluessel);
  $('#stratDetail').innerHTML = `<div class="card"><span>${gewaehlt?'<span class="pill">AUSGEWÄHLT FÜR '+esc(d.symbol)+'</span>':'<span class="pill g">BESTANDEN, NICHT AUSGEWÄHLT</span>'}</span>
    <h2>${esc(d.symbol)} · ${esc(d.strategie)}</h2><p class="sub" style="margin:0">${esc(d.beschreibung)}</p></div>
    <div class="kpis" style="padding:0 16px 14px">
    ${[['Profit Factor ungesehen',num(O.profit_factor,2)],['Trefferquote ungesehen',pct(O.trefferquote_pct)],
       ['Max. Drawdown ungesehen',pct(O.max_drawdown_pct)],['Trades ungesehen',O.trades??'–']]
      .map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div></div>`).join('')}</div>
    <div class="tw"><table class="tbl"><tbody>
    <tr><td>Nettogewinn gesamt</td><td class="m ${cls(G.netto)}">${money(G.netto)}</td></tr>
    <tr><td>Rendite gesamt</td><td class="m ${cls(G.rendite_pct)}">${pct(G.rendite_pct,1)}</td></tr>
    <tr><td>Kaufen und Halten (ungesehen)</td><td class="m">${pct(d.kaufen_halten_oos_pct,1)}</td></tr>
    <tr><td>Gebühren gesamt</td><td class="m">${money(G.gebuehren)}</td></tr>
    <tr><td>Zeit im Markt</td><td class="m">${pct(G.zeit_im_markt_pct,0)}</td></tr></tbody></table></div>`;
}

/* ---------- Research ---------- */
function renderFlow(){
  const v = R.validierungen||[], dq = R.datenqualitaet||[], P = R.plan||[];
  const stationen = [
    ['Daten', `${dq.filter(q=>q.ok).length}/${dq.length} Symbole in Ordnung`, 'Kerzen laden, Lücken, Doppelungen und unmögliche Preise prüfen. Im Paper-Modus löst jeder Fehler einen Handelsstopp aus.'],
    ['Research', `${v.length} Kandidaten`, 'Nur das freigegebene Parameter-Raster. Keine KI erfindet Parameter.'],
    ['Validierung', `${v.filter(x=>x.urteil==='bestanden').length} bestanden · ${v.filter(x=>x.urteil==='abgelehnt').length} abgelehnt`, 'Training und ungesehener Teil, Walk-Forward, Monte-Carlo, Nachbar-Parameter, Zufallsvergleich.'],
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
      const mod = await import('/static/globe2d.js?v=1');
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

  $('#betriebRes').innerHTML = `<table class="tbl"><tbody>
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

function shipRaum(k, breit, proAbteilung){
  const liste = proAbteilung[k] || [];
  const befunde = liste.filter(r=>!r.ok).length;
  const on = k === depSel;
  const zustand = liste.length ? (befunde ? 'befund' : 'ok') : 'leer';
  return `<button class="ship-room is-${zustand}${on?' on':''}${breit?' is-wide':''}" data-d="${k}" aria-pressed="${on?'true':'false'}"
    aria-label="${esc(DEP[k])}: ${liste.length} Agenten${befunde?`, ${befunde} Befund`:''}">
    <span class="ship-room-code">${k}</span>
    <span class="ship-room-name">${esc(DEP[k])}</span>
    <span class="ship-room-meta">${liste.length ? `${liste.length} Agenten` : 'KEINE DATEN'}${befunde?` · ${befunde} Befund` : ''}</span>
    <span class="dots">${liste.slice(0,10).map(r=>`<i class="${r.ok?'ok':'warn'}"></i>`).join('')}</span>
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
    <div class="exec-room exec-meet" title="Zur Agenda">
      <span class="exec-code">MTG</span>
      <b>Meetingraum</b>
      <div class="exec-list">
        <span><b>Nächste Sitzung</b><small>00:00 · Mitternacht</small></span>
        <span><b>Agenda</b><small>${(sekDaten && sekDaten.agenda && sekDaten.agenda.themen ? sekDaten.agenda.themen.length : 0)} Themen · Leitung Mira, Jonas, Lea</small></span>
        <span><b>Protokoll</b><small>${(R.konferenz && R.konferenz.sekretariat && R.konferenz.sekretariat.agenda) ? R.konferenz.sekretariat.agenda.length + ' Themen übernommen' : 'noch nicht übernommen'}</small></span>
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

function renderShip(){
  const runs = R.agenten || [];
  const proAbteilung = {};
  runs.forEach(r => { (proAbteilung[r.abteilung] = proAbteilung[r.abteilung] || []).push(r); });

  $('#deckA').innerHTML = DECK_A.map(k=>shipRaum(k, false, proAbteilung)).join('');
  $('#deckB').innerHTML = DECK_B.map(k=>shipRaum(k, k==='D', proAbteilung)).join('');
  document.querySelectorAll('#v-ship .ship-room').forEach(b => b.onclick = () => { depSel = b.dataset.d; renderShip(); });
  const detail = $('#shipModeDetail');
  if(detail) detail.textContent = `${runs.length} Agentenläufe · ${Object.keys(proAbteilung).length} von 8 Abteilungen aktiv`;
  renderCEO(runs);
  ladeSekretariat();
  ladeSitzung();

  const meine = proAbteilung[depSel] || [];
  $('#roomTag').textContent = `${meine.length} Agenten · ${meine.filter(r=>r.ok).length} ohne Befund`;
  $('#roomAgents').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b>${esc((r.agent||'').split(':')[1]||r.agent)}</b>
    <small>${esc(r.aufgabe)}</small></span><span class="pill ${r.ok?'':'r'}">${r.ok?'OK':'BEFUND'}</span></div>`).join('')
    : '<div class="empty">Noch kein Lauf für diese Abteilung.</div>';
  $('#roomRuns').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b style="font-weight:400">${esc(r.ergebnis)}</b>
    <small>${esc((r.agent||'').split(':')[1]||r.agent)}</small></span></div>`).join('')
    : '<div class="empty">Keine Rohrpost.</div>';
}

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

})();

document.addEventListener('click', e => {
  if(e.target.closest && e.target.closest('.exec-meet')){
    const ziel = document.querySelector('#sekAgenda');
    if(ziel) ziel.scrollIntoView({behavior:'smooth', block:'center'});
  }
});
