/* Übersicht: Cockpit, Modus, Risiko, Validierung und Entscheide auf einen Blick. */
import { R } from '../kern/daten.js';
import { $, MODE, esc, num, params, pct } from '../kern/helfer.js';
import { renderCockpit } from './cockpit.js';

function renderOverview(){
  renderCockpit();
  const v = R.validierungen||[], best = v.filter(x=>x.urteil==='bestanden');
  const a = R.risiko?.auslastung||{}, L = R.risiko_grenzen||{};
  const kp = [
    ['Modus', MODE[R.modus]?.[0]||'–', `${v.length} Kandidaten geprüft`],
    ['Risiko', R.risiko?.status==='gestoppt' ? '<span class="dn">GESTOPPT</span>' : '<span class="up">aktiv</span>',
      R.risiko?.status==='gestoppt' ? esc(R.risiko.grund) : `Drawdown ${pct(a.drawdown_pct,2)} von max. ${L.max_drawdown_pct} %`],
    ['Validierung', `${best.length} / ${v.length}`, 'bestanden, nach Gebühren und Slippage'],
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

export { renderOverview };
