/* Research: Ablauf von Daten bis Ausführung mit Grenzen je Station. */
import { R } from '../kern/daten.js';
import { $, esc } from '../kern/helfer.js';

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

export { renderFlow };
