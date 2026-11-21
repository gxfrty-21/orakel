/* Agenten: Läufe je Abteilung mit Status und Befund. */
import { R } from '../kern/daten.js';
import { $, DEP, auswahl, esc } from '../kern/helfer.js';

function renderAgents(){
  const runs = R.agenten||[];
  $('#depTabs').innerHTML = Object.entries(DEP).map(([k,n])=>`<button class="tab ${k===auswahl.depSel?'on':''}" data-d="${k}">${k} · ${n}</button>`).join('');
  document.querySelectorAll('#depTabs .tab').forEach(b=>b.onclick=()=>{auswahl.depSel=b.dataset.d;renderAgents();});
  const meine = runs.filter(r=>r.abteilung===auswahl.depSel);
  $('#agTag').textContent = `${meine.length} Agenten · ${meine.filter(r=>r.ok).length} ohne Befund`;
  $('#agList').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b>${esc(r.agent.split(':')[1]||r.agent)}</b>
    <small>${esc(r.aufgabe)}</small></span><span class="pill ${r.ok?'':'r'}">${r.ok?'OK':'BEFUND'}</span></div>`).join('')
    : '<div class="empty">Noch kein Lauf für diese Abteilung.</div>';
  $('#agRuns').innerHTML = runs.length ? runs.slice(0,40).map(r=>`<div class="li"><span><b style="font-weight:400">${esc(r.ergebnis)}</b>
    <small>${esc(DEP[r.abteilung]||r.abteilung)} · ${esc(r.agent.split(':')[1]||r.agent)}</small></span>
    <span class="pill ${r.ok?'g':'r'}">${esc(r.abteilung)}</span></div>`).join('')
    : '<div class="empty">Noch keine Agentenaktivität. Auf «Lauf starten» klicken.</div>';
}

export { renderAgents };
