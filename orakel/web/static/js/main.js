/* Einstieg: Ansichten registrieren, Kopfzeile, Bericht laden, Prüfbrücken. */
import { R, lade, registriereNachLaden, registriereFehler } from './kern/daten.js';
import { $, COL, MODE, esc } from './kern/helfer.js';
import { registriereAnsicht, zeige, zeichne, initialisiereNavigation } from './kern/navigation.js';
import { renderOverview } from './ansichten/uebersicht.js';
import { renderRisk } from './ansichten/risiko.js';
import { renderLab, pausiertRenderWegenLabDetail, setzeLabNeuStatus } from './ansichten/lab.js';
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
initialisiereNavigation();

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
  if (pausiertRenderWegenLabDetail()) setzeLabNeuStatus(true);
  else { zeichne(); setzeLabNeuStatus(false); }
});

registriereFehler(e => {
  $('#banner').className = 'banner b-sim';
  $('#banner').innerHTML = '<b>FEHLER</b>' + esc(e.message);
});

// Der Lauf läuft im Hintergrund. Der Knopf wartet auf den Status und lädt
// erst danach den Bericht; die Anfrage selbst ist sofort beantwortet.
async function warteAufLauf(id){
  const grenze = Date.now() + 15 * 60 * 1000;
  while(Date.now() < grenze){
    const r = await fetch('/api/lauf/' + encodeURIComponent(id),{cache:'no-store'});
    if(r.ok){
      const s = await r.json();
      if(s.status === 'fertig' || s.status === 'fehler') return s;
    }
    await new Promise(f => setTimeout(f, 2000));
  }
  throw new Error('Lauf-Status nicht rechtzeitig erhalten');
}

$('#runBtn').onclick = async () => {
  const b = $('#runBtn'); b.disabled = true; b.textContent = 'Lauf läuft …';
  try{
    const r = await fetch('/api/lauf?modus=backtest',{method:'POST'});
    const antwort = await r.json();
    // 409 heisst: Es läuft schon einer. Der Knopf hängt sich an dessen ID,
    // statt einen zweiten Backtest einzureihen.
    if(!r.ok && r.status !== 409) throw new Error(antwort.fehler || 'Lauf konnte nicht gestartet werden');
    if(!antwort.id) throw new Error('Lauf konnte nicht gestartet werden');
    const stand = await warteAufLauf(antwort.id);
    if(stand.status === 'fehler') throw new Error(stand.fehler || 'Lauf fehlgeschlagen');
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
// Single-flight: Läuft noch eine Antwort, wird der Takt übersprungen statt einen
// zweiten Aufruf zu starten; langsame Antworten können sich so nicht überlappen.
// Im Hintergrundtab pausiert der Takt; beim Zurückkehren wird sofort nachgeladen.
let ladeLaeuft = false;
async function autoRefresh(){
  if (document.hidden || ladeLaeuft) return;
  if (document.querySelector('details.ordEdit[open]')) return;
  // Ein geöffneter Missionsbericht darf nicht unter dem Leser verschwinden.
  if (document.querySelector('.mission-report:not([hidden])')) return;
  const a = document.activeElement;
  if (a && /^(SELECT|TEXTAREA|INPUT)$/.test(a.tagName)) return;
  ladeLaeuft = true;
  try{ await lade(); }finally{ ladeLaeuft = false; }
}
setInterval(autoRefresh, 8000);
document.addEventListener('visibilitychange', () => { if(!document.hidden) autoRefresh(); });

/* Schmale Brücke für die Prüfskripte: Ansichten und Claim-Renderer bleiben ohne eigene Nav-Einträge erreichbar. */
window.zeige = zeige;
window.zeichneBewertung = zeichneBewertung;
window.pausiertRenderWegenLabDetail = pausiertRenderWegenLabDetail;
