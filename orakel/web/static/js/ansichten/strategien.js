/* Strategien: bestandene Kandidaten und die Auswahl je Symbol. */
import { wfoFoldsBlock } from './lab.js';
import { R } from '../kern/daten.js';
import { $, cls, esc, money, num, params, pct } from '../kern/helfer.js';

let stratSel = 0;

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
    <tr><td>Finanzierung gesamt</td><td class="m">${money(G.finanzierung)}</td></tr>
    <tr><td>Zeit im Markt</td><td class="m">${pct(G.zeit_im_markt_pct,0)}</td></tr></tbody></table></div>
    ${wfoFoldsBlock(d)}`;
}

export { renderStrat };
