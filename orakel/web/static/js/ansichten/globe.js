/* Weltkugel: Marktdaten, Korrelationen und der Intelligence-Graph. */
import { R } from '../kern/daten.js';
import { $, COL, cls, esc, num } from '../kern/helfer.js';

let globeView = null, globeFailed = false, globeWindow = '24h', globeRequest = 0, globeAbort = null, globeLoading = null;
let aktiv = false;

export function globeAktiviere(){ aktiv = true; }

export function globeDeaktiviere(){ aktiv = false; if(globeView) globeView.setActive(false); }

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
  if(aktiv) renderGlobe();
}

document.querySelectorAll('#globeWindow [data-window]').forEach(btn => {
  btn.addEventListener('click', () => setGlobeWindow(btn.dataset.window));
});

syncGlobeWindow(globeWindow);

async function ensureGlobe(){
  if(globeView) return globeView;
  if(globeFailed) return null;
  if(globeLoading) return globeLoading;
  const stage = $('#globeStage');
  if(!stage) return null;
  globeLoading = (async () => {
    try{
      const mod = await import('/static/globe2d.js?v=2');
      globeView = new mod.IntelligenceGlobe(stage);
      if(aktiv) globeView.setActive(true);
      return globeView;
    }catch(e){
      globeFailed = true;
      showGlobeError(e.message || 'Die Weltkugel konnte nicht initialisiert werden.');
      return null;
    }finally{
      globeLoading = null;
    }
  })();
  return globeLoading;
}

async function renderGlobe(){
  renderGlobeMarkets();
  const g = await ensureGlobe();
  if(!g || !aktiv) return;
  g.setActive(true);
  const request = ++globeRequest;
  const key = globeWindow;
  if(globeAbort) globeAbort.abort();
  const controller = new AbortController();
  globeAbort = controller;
  try{
    const r = await fetch(`/api/globe?zeitraum=${encodeURIComponent(key)}`, {cache:'no-store',signal:controller.signal});
    if(request !== globeRequest || !aktiv) return;
    if(!r.ok) throw new Error('Der Intelligence-Graph ist momentan nicht erreichbar.');
    const data = await r.json();
    if(request !== globeRequest || !aktiv) return;
    g.setData(data);
    syncGlobeWindow(data.window?.key || key);
  }catch(e){
    if(e.name === 'AbortError' || request !== globeRequest || !aktiv) return;
    showGlobeError(e.message || 'Der Intelligence-Graph konnte nicht geladen werden.');
  }finally{
    if(globeAbort === controller) globeAbort = null;
  }
}

export { renderGlobe };
