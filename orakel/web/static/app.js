/* Orakel Dashboard — liest /api/report (Schema 2) und /api/lauf. */
(() => {
const $ = s => document.querySelector(s);
const COL = { accent:'#5fe0c8', amber:'#e8b45a', good:'#62d68a', bad:'#e2616b', blue:'#8fb8ff', dim:'#55606d' };
let R = null, current = 'overview', labFilter = 'all', labSel = 0, stratSel = 0, depSel = 'A';
let globe3d = null, globeFailed = false, globeWindow = '24h', globeRequest = 0, globeAbort = null, globeLoading = null;
let nexus3d = null, nexusFailed = false, nexusWindow = '7d', nexusRequest = 0, nexusAbort = null, nexusLoading = null, nexusDaten = null, nexusSelected = null;
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
  if(v !== 'globe' && globe3d) globe3d.setActive(false);
  if(v !== 'nexus' && nexus3d) nexus3d.setActive(false);
  if(v !== 'nexus' && nexusAbort){ nexusAbort.abort(); nexusAbort = null; }
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
    globe:renderGlobe,nexus:renderNexus,betrieb:renderBetrieb,ship:renderShip,spider:renderSpider})[current]?.();
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
function renderKb(){
  const T = R.wissen?.typen||[];
  $('#libTag').textContent = `${T.length} Typen`;
  $('#types').innerHTML = T.length ? `<table class="tbl"><thead><tr><th>Typ</th><th class="m">Tests</th><th class="m">Bestanden</th><th class="m">Quote</th><th class="m">Median PF ungesehen</th><th>Häufigste Ablehnung</th></tr></thead><tbody>
    ${T.map(t=>`<tr><td>${esc(t.typ)}</td><td class="m">${t.tests}</td><td class="m">${t.bestanden}</td><td class="m">${pct(t.quote_pct,0)}</td>
    <td class="m">${t.median_pf_oos==null?'–':num(t.median_pf_oos,2)}</td><td style="white-space:normal">${esc((t.haeufigste_ablehnung||[]).join(', ')||'–')}</td></tr>`).join('')}
    </tbody></table>` : '<div class="empty">Noch keine Validierungen gespeichert.</div>';
  const D = R.entscheide||[];
  $('#decList').innerHTML = D.length ? D.map(d=>`<div class="li"><span><b>${esc(d.symbol)} · ${esc(d.aktion)}</b>
    <small>${esc((d.zeit||'').replace('T',' ').slice(0,16))} · ${esc(d.status)}</small></span>
    <span class="pill ${d.genehmigt?'':'r'}">${d.genehmigt?'JA':'NEIN'}</span></div>`).join('')
    : '<div class="empty">Noch keine Entscheide.</div>';
  $('#vaultInfo').innerHTML = `<p class="sub" style="margin:0">Der Vault liegt im Ordner <span class="code">vault/</span> und ist mit Obsidian direkt öffnbar:
    Frontmatter, Tags und [[Links]]. Validierungen, Ablehnungen, Datenfehler und Konferenzprotokolle werden dort abgelegt.</p>
    <div class="lbl">Ordner</div><div class="reasons">${['00-Index','10-Daten','20-Strategien','30-Validierungen','40-Entscheide','50-Konferenz','60-Fehler','70-Wissen']
      .map(o=>`<span class="i">${o}</span>`).join('')}</div>`;
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

async function ensureGlobe3d(){
  if(globe3d) return globe3d;
  if(globeFailed) return null;
  if(globeLoading) return globeLoading;
  const stage = $('#globeStage');
  if(!stage) return null;
  globeLoading = (async () => {
    try{
      const mod = await import('/static/globe3d.js');
      globe3d = new mod.IntelligenceGlobe(stage);
      if(current === 'globe') globe3d.setActive(true);
      return globe3d;
    }catch(e){
      globeFailed = true;
      showGlobeError(e.message || 'Die 3D-Ansicht konnte nicht initialisiert werden.');
      return null;
    }finally{
      globeLoading = null;
    }
  })();
  return globeLoading;
}

async function renderGlobe(){
  renderGlobeMarkets();
  const g = await ensureGlobe3d();
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

/* ---------- Nexus-Raum (Phase 7) ---------- */
const NEXUS_WINDOWS = ['24h','7d','30d','alle'];
function syncNexusWindow(key){
  nexusWindow = NEXUS_WINDOWS.includes(key) ? key : '7d';
  document.querySelectorAll('#nexusWindow [data-window]').forEach(btn => {
    const on = btn.dataset.window === nexusWindow;
    btn.classList.toggle('is-active', on);
    btn.setAttribute('aria-pressed', String(on));
  });
}

function setNexusWindow(key){
  if(!NEXUS_WINDOWS.includes(key) || key === nexusWindow) return;
  syncNexusWindow(key);
  if(current === 'nexus') renderNexus();
}

document.querySelectorAll('#nexusWindow [data-window]').forEach(btn => {
  btn.addEventListener('click', () => setNexusWindow(btn.dataset.window));
});
syncNexusWindow(nexusWindow);

async function ensureNexus3d(){
  if(nexus3d) return nexus3d;
  if(nexusFailed) return null;
  if(nexusLoading) return nexusLoading;
  const stage = $('#nexusStage');
  if(!stage) return null;
  nexusLoading = (async () => {
    try{
      const mod = await import('/static/nexus3d.js?v=9');
      nexus3d = new mod.NexusRoom(stage);
      if(current === 'nexus') nexus3d.setActive(true);
      return nexus3d;
    }catch(e){
      nexusFailed = true;
      showNexusError(e.message || 'Die 3D-Ansicht konnte nicht initialisiert werden.');
      return null;
    }finally{
      nexusLoading = null;
    }
  })();
  return nexusLoading;
}

function showNexusError(message){
  const mode = $('#nexusMode');
  if(mode){
    mode.className = 'nexus-mode is-error';
    const label = $('#nexusModeLabel');
    const detail = $('#nexusModeDetail');
    if(label) label.textContent = 'RAUM OFFLINE';
    if(detail) detail.textContent = message || '3D-Ansicht nicht verfügbar';
  }
  const activity = $('#nexusActivity');
  if(activity){ activity.textContent = 'KEINE VERBINDUNG'; activity.className = 'nexus-activity is-error'; }
  const detail = $('#nexusActivityDetail');
  if(detail) detail.textContent = message || 'Der Nexus-Raum konnte nicht geladen werden.';
  const empty = $('#nexusEmpty');
  if(empty){
    empty.hidden = false;
    empty.innerHTML = `<b>RAUM NICHT VERFÜGBAR</b><span>${esc(message || 'Die 3D-Ansicht konnte nicht geladen werden.')}</span>`;
  }
  ['nexusStatNodes','nexusStatEdges','nexusStatRunning'].forEach(id => {
    const el = document.getElementById(id);
    if(el) el.textContent = '–';
  });
  if(nexus3d) nexus3d.showError(message);
}

async function renderNexus(){
  const g = await ensureNexus3d();
  if(current !== 'nexus') return;
  if(g) g.setActive(true);
  await ladeNexus(g);
}

async function ladeNexus(g){
  const request = ++nexusRequest;
  const key = nexusWindow;
  if(nexusAbort) nexusAbort.abort();
  const controller = new AbortController();
  nexusAbort = controller;
  try{
    const r = await fetch(`/api/nexus/raum?zeitraum=${encodeURIComponent(key)}`, {
      cache:'no-store', signal:controller.signal,
    });
    if(request !== nexusRequest || current !== 'nexus') return;
    if(!r.ok) throw new Error(`Der Nexus-Raum ist momentan nicht erreichbar (HTTP ${r.status}).`);
    const d = await r.json();
    if(request !== nexusRequest || current !== 'nexus') return;
    if(!d.ok) throw new Error(d.fehler || 'Der Nexus-Raum konnte nicht geladen werden.');
    nexusDaten = d;
    zeichneNexus(d);
    if(g) g.setData(d);
    syncNexusWindow(d.zeitraum || key);
  }catch(e){
    if(e.name === 'AbortError' || request !== nexusRequest || current !== 'nexus') return;
    nexusDaten = null;
    showNexusError(e.message || 'Der Nexus-Raum konnte nicht geladen werden.');
  }finally{
    if(nexusAbort === controller) nexusAbort = null;
  }
}

function zeichneNexus(d){
  const graph = d.graph || {};
  const st = graph.statistik || {};
  const zahlen = d.zahlen || {};
  const a = d.aktivitaet || {};
  const knoten = graph.knoten || [];
  const kanten = graph.kanten || [];
  const events = a.events || [];
  const typName = {claim:'Kernaussage', quelle:'Quelle', thema:'Thema'};
  const mode = $('#nexusMode');
  if(mode){
    mode.className = 'nexus-mode' + (nexusFailed ? ' is-error' : (a.status ? ' is-'+a.status : ''));
    const label = $('#nexusModeLabel');
    const detail = $('#nexusModeDetail');
    if(label) label.textContent = nexusFailed ? 'RAUM OFFLINE' : (a.label || 'RUHIG');
    if(detail) detail.textContent = nexusFailed
      ? '3D-Modul nicht verfügbar; Datenleiste bleibt sichtbar'
      : `${num(zahlen.knoten,0)} Knoten · ${num(a.laufend,0)} laufend · ${esc(d.zeitraum || nexusWindow)}`;
  }
  const total = $('#nexusNodeTotal');
  if(total) total.textContent = `${num(knoten.length,0)} Knoten`;
  const eventTotal = $('#nexusEventTotal');
  if(eventTotal) eventTotal.textContent = `${num(events.length,0)} Ereignisse`;
  const statNodes = $('#nexusStatNodes');
  const statEdges = $('#nexusStatEdges');
  const statRunning = $('#nexusStatRunning');
  if(statNodes) statNodes.textContent = num(st.knoten,0);
  if(statEdges) statEdges.textContent = num(st.kanten,0);
  if(statRunning) statRunning.textContent = num(a.laufend,0);
  const activity = $('#nexusActivity');
  if(activity){ activity.textContent = a.label || '–'; activity.className = 'nexus-activity' + (a.status ? ' is-'+a.status : ''); }
  const activityDetail = $('#nexusActivityDetail');
  if(activityDetail) activityDetail.textContent = a.detail || '';
  const hint = $('#nexusGraphHint');
  if(hint) hint.textContent = kanten.length ? `${num(kanten.length,0)} Kanten im Zeitraum` : (graph.hinweis || 'Noch keine Graphkanten.');

  if(nexusSelected && !knoten.some(n => n.id === nexusSelected)) nexusSelected = null;
  const nodesBox = $('#nexusNodes');
  if(nodesBox){
    nodesBox.innerHTML = knoten.length ? knoten.slice(0,40).map(n => `
      <button type="button" class="nexus-node${nexusSelected === n.id ? ' is-selected' : ''}" data-node="${esc(n.id)}">
        <span class="nexus-node-top"><span class="nexus-node-type is-${esc(n.typ)}">${esc(typName[n.typ] || n.typ)}</span></span>
        <span class="nexus-node-label">${esc(n.label)}</span>
        <small>${esc(n.status || n.id)}${n.meta?.thema ? ' · ' + esc(n.meta.thema) : ''}</small>
      </button>`).join('')
      : `<div class="nexus-rail-empty">${esc(graph.hinweis || 'Noch keine Graphknoten. Der Raum bleibt ohne erfundene Knoten leer.')}</div>`;
  }

  const eventsBox = $('#nexusEvents');
  if(eventsBox){
    const artName = {mission:'Mission', claim:'Claim', quelle:'Quelle', prognose:'Prognose'};
    eventsBox.innerHTML = events.length ? events.slice(0,30).map(e => {
      const t = String(e.zeit || '');
      const time = t.includes('T') ? t.slice(11,16) : '–';
      return `<div class="nexus-event">
        <span class="nexus-event-time">${esc(time)}</span>
        <span class="nexus-event-main"><span class="nexus-event-art is-${esc(e.art)}">${esc(artName[e.art] || e.art)}</span>
          <span class="nexus-event-text">${esc(e.text)}</span>
          <span class="nexus-event-title">${esc(e.titel)}${e.status ? ' · ' + esc(e.status) : ''}</span></span>
      </div>`;
    }).join('') : '<div class="nexus-rail-empty">Keine Aktivität im gewählten Zeitraum. Es wird kein Ereignis erfunden.</div>';
  }

  const empty = $('#nexusEmpty');
  if(empty){
    if(nexusFailed){
      empty.hidden = false;
      empty.innerHTML = '<b>3D-ANSICHT NICHT VERFÜGBAR</b><span>Die Datenleiste bleibt nutzbar; für den Raum fehlt WebGL oder das Modul.</span>';
    }else if(!knoten.length){
      empty.hidden = false;
      empty.innerHTML = `<b>RAUM OHNE GRAPH</b><span>${esc(graph.hinweis || 'Noch keine Graphknoten im gewählten Zeitraum.')}${events.length ? ' Die Aktivität rechts bleibt sichtbar.' : ''}</span>`;
    }else{
      empty.hidden = true;
    }
  }

  const legend = $('#nexusLegend');
  if(legend){
    legend.innerHTML = `<span class="n-legend-item"><i style="background:#5fe0c8"></i>Kernaussage</span>
      <span class="n-legend-item"><i style="background:#8fb8ff"></i>Quelle</span>
      <span class="n-legend-item"><i style="background:#e8b45a"></i>Thema</span>
      <span class="n-legend-item"><i class="is-line"></i>Kante</span>
      <span class="n-legend-item">${a.laufend ? 'Beine aktiv' : 'Beine ruhig'}</span>`;
  }
  const meta = $('#nexusMeta');
  if(meta) meta.textContent = `${num(zahlen.knoten,0)} Knoten · ${num(zahlen.kanten,0)} Kanten · ${esc(d.zeitraum || nexusWindow)} · ${esc(String(d.generiert || '').replace('T',' ').slice(0,16))}`;

  const typesBox = $('#nexusTypes');
  if(typesBox){
    const typen = st.typen || {};
    const rows = [['claim','Kernaussagen'],['quelle','Quellen'],['thema','Themen']];
    typesBox.innerHTML = knoten.length ? `<table class="tbl"><thead><tr><th>Typ</th><th class="m">Knoten</th></tr></thead><tbody>
      ${rows.map(([key,label]) => `<tr><td>${label}</td><td class="m">${num(typen[key],0)}</td></tr>`).join('')}</tbody></table>`
      : '<div class="empty">Keine Knoten im gewählten Zeitraum.</div>';
    const typeTag = $('#nexusTypeTag');
    if(typeTag) typeTag.textContent = knoten.length ? `${num(Object.keys(typen).length,0)} Typen` : 'leer';
  }

  const contract = $('#nexusContract');
  if(contract){
    const aktivText = a.laufend > 0
      ? `${num(a.laufend,0)} Mission${a.laufend === 1 ? '' : 'en'} laufen; die Beine bewegen sich.`
      : 'Keine laufende Mission; die Beine bleiben ruhig.';
    contract.innerHTML = `<p><b>Graph:</b> ${num(zahlen.knoten,0)} Knoten und ${num(zahlen.kanten,0)} Kanten aus dem persistierten Wissensgraph.</p>
      <p><b>Aktivität:</b> ${esc(a.detail || 'Keine Aktivität gespeichert.')}</p>
      <p><b>Bewegung:</b> ${esc(aktivText)}</p>
      <p class="nexus-limit">Die Szene liest <code>/api/nexus/raum</code>. Sie erfindet weder Knoten noch Ereignisse; neue Knoten leuchten nur nach einem echten Refresh auf.</p>`;
  }
}

const nexusNodes = $('#nexusNodes');
if(nexusNodes) nexusNodes.addEventListener('click', e => {
  const b = e.target.closest('[data-node]');
  if(!b || !nexus3d) return;
  nexusSelected = b.dataset.node;
  nexus3d.selectNode(b.dataset.node);
  nexusNodes.querySelectorAll('[data-node]').forEach(el => el.classList.toggle('is-selected', el === b));
});
const nexusStage = $('#nexusStage');
if(nexusStage) nexusStage.addEventListener('nexusselection', e => {
  nexusSelected = e.detail || null;
  document.querySelectorAll('#nexusNodes [data-node]').forEach(el => {
    el.classList.toggle('is-selected', el.dataset.node === e.detail);
  });
});

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
function renderShip(){
  const runs = R.agenten || [];
  const proAbteilung = {};
  runs.forEach(r => { (proAbteilung[r.abteilung] = proAbteilung[r.abteilung] || []).push(r); });

  $('#deck').innerHTML = Object.entries(DEP).map(([k,n])=>{
    const liste = proAbteilung[k] || [];
    const befunde = liste.filter(r=>!r.ok).length;
    return `<button class="room ${k===depSel?'on':''}" data-d="${k}">
      <span class="room-d">${k}</span>
      <b>${esc(n)}</b>
      <small>${liste.length} Agenten${befunde?` · ${befunde} Befund` : ''}</small>
      <span class="dots">${liste.slice(0,10).map(r=>`<i class="${r.ok?'ok':'warn'}"></i>`).join('')}</span>
    </button>`;
  }).join('');
  document.querySelectorAll('.room').forEach(b => b.onclick = () => { depSel = b.dataset.d; renderShip(); });

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

  $('#spiderTag').textContent = `${artikel.length} Einträge`;
  $('#spiderList').innerHTML = artikel.length ? artikel.map(a=>`<div class="li"><span><b style="font-weight:400">${esc(a.titel)}</b>
    <small>${esc(a.quelle)} · ${esc(a.typ)}${a.symbole?` · ${esc(a.symbole)}`:''}</small></span>
    <span class="pill ${a.qualitaet>=0.7?'':'w'}">${num(a.qualitaet,2)}</span></div>`).join('')
    : '<div class="empty">Noch keine Artikel. Auf «Recherche starten» klicken.</div>';

  $('#spiderQuellen').innerHTML = quellen.length ? `<table class="tbl"><thead><tr><th>Quelle</th><th class="m">Artikel</th><th class="m">Ø Qualität</th><th class="m">belegt</th><th class="m">verworfen</th></tr></thead><tbody>
    ${quellen.map(q=>`<tr><td>${esc(q.quelle)}</td><td class="m">${q.artikel}</td><td class="m">${num(q.qualitaet,2)}</td>
    <td class="m up">${q.bestaetigt}</td><td class="m dn">${q.widerlegt}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Keine Quelle hat bisher geliefert.</div>';

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
})();
