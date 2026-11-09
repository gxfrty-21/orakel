/* Orakel Dashboard — liest /api/report (Schema 2) und /api/lauf. */
(() => {
const $ = s => document.querySelector(s);
const COL = { accent:'#5fe0c8', amber:'#e8b45a', good:'#62d68a', bad:'#e2616b', blue:'#8fb8ff', dim:'#55606d' };
let R = null, current = 'overview', labFilter = 'all', labSel = 0, stratSel = 0, depSel = 'A';
let globe3d = null, globeFailed = false, globeWindow = '24h', globeRequest = 0, globeAbort = null, globeLoading = null;
let nachtDaten = null, nachtFehler = null;
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
  document.querySelectorAll('.nav').forEach(b=>b.classList.toggle('on',b.dataset.v===v));
  document.querySelectorAll('.view').forEach(s=>s.hidden = s.id !== 'v-'+v);
  zeichne();
}
function zeichne(){
  if(!R) return;
  ({overview:renderOverview,risk:renderRisk,lab:renderLab,strat:renderStrat,
    research:renderFlow,kb:renderKb,agents:renderAgents,konf:renderKonf,
    globe:renderGlobe,ship:renderShip,spider:renderSpider})[current]?.();
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
    ['Meldungen', num(n.meldungen,0), `${num(n.fehler,0)} Fehler`],
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
  $('#nachtDetail').innerHTML = `<div class="nacht-status">${teile.join(' ')}</div>`;
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
  const a = document.activeElement;
  if (a && /^(SELECT|TEXTAREA|INPUT)$/.test(a.tagName)) return;
  lade();
}, 8000);
})();
