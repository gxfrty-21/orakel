/* Einstieg: Ansichten registrieren, Kopfzeile, Bericht laden, Prüfbrücken. */
import { R, lade, registriereNachLaden, registriereFehler } from './kern/daten.js';
import { $, COL, MODE, esc } from './kern/helfer.js';
import { registriereAnsicht, zeige, zeichne } from './kern/navigation.js';
import { renderOverview } from './ansichten/uebersicht.js';
import { renderRisk } from './ansichten/risiko.js';
import { renderLab } from './ansichten/lab.js';
import { renderStrat } from './ansichten/strategien.js';
import { renderFlow } from './ansichten/research.js';
import { renderKb } from './ansichten/wissen.js';
import { renderAgents } from './ansichten/agenten.js';
import { renderKonf } from './ansichten/konferenz.js';
import { renderGlobe, globeAktiviere, globeDeaktiviere } from './ansichten/globe.js';
import { renderBetrieb, betriebAktiviere, betriebDeaktiviere } from './ansichten/betrieb.js';
import { renderShip, shipAktiviere, shipDeaktiviere } from './ansichten/raumschiff.js';
import { renderSpider, zeichneBewertung } from './ansichten/spider.js';

registriereAnsicht('overview', {render: renderOverview});
registriereAnsicht('risk', {render: renderRisk});
registriereAnsicht('lab', {render: renderLab});
registriereAnsicht('strat', {render: renderStrat});
registriereAnsicht('research', {render: renderFlow});
registriereAnsicht('kb', {render: renderKb});
registriereAnsicht('agents', {render: renderAgents});
registriereAnsicht('konf', {render: renderKonf});
registriereAnsicht('globe', {render: renderGlobe, aktiviere: globeAktiviere, deaktiviere: globeDeaktiviere});
registriereAnsicht('betrieb', {render: renderBetrieb, aktiviere: betriebAktiviere, deaktiviere: betriebDeaktiviere});
registriereAnsicht('ship', {render: renderShip, aktiviere: shipAktiviere, deaktiviere: shipDeaktiviere});
registriereAnsicht('spider', {render: renderSpider});

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

registriereNachLaden(neu => {
  // Nichtvisueller Datenstand für den Auto-Refresh-Test: Bei fokussiertem
  // Lab-Detail wird nur der Ansichts-Render pausiert, R aber ersetzt. Das
  // Attribut macht die übernommenen Berichtsdaten prüfbar, ohne die stabile
  // Lab-Ansicht neu zu zeichnen.
  const laborDaten = document.querySelector('#labList');
  if (laborDaten) laborDaten.dataset.berichtKandidat = neu.validierungen?.[0]?.symbol || '';
  renderTop();
  if (!document.activeElement?.closest('#v-lab:not([hidden]) #labDetail')) zeichne();
});

registriereFehler(e => {
  $('#banner').className = 'banner b-sim';
  $('#banner').innerHTML = '<b>FEHLER</b>' + esc(e.message);
});

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

/* Schmale Brücke für die Prüfskripte: Ansichten und Claim-Renderer bleiben ohne eigene Nav-Einträge erreichbar. */
window.zeige = zeige;
window.zeichneBewertung = zeichneBewertung;
