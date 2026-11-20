/* Konferenz: Beschluss, Abteilungsberichte und Protokoll. */
import { R } from '../kern/daten.js';
import { $, esc } from '../kern/helfer.js';

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

export { renderKonf };
