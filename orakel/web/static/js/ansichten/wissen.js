/* Wissensbank: Ordner, Graph-Einbindung und Detailspalte. */
import { R } from '../kern/daten.js';
import { aktivieren as vaultAktivieren } from '../vaultgraph.js';
import { $, esc, num, pct } from '../kern/helfer.js';

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
  vaultAktivieren();
}

export { renderKb };
