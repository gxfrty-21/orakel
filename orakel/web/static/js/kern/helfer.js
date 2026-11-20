/* Gemeinsame Helfer: DOM-Zugriff, Zahlenformat, Farben, Abteilungen, Toast. */
export const auswahl = { depSel: 'A' };

const $ = s => document.querySelector(s);

const COL = { accent:'#5fe0c8', amber:'#e8b45a', good:'#62d68a', bad:'#e2616b', blue:'#8fb8ff', dim:'#55606d' };

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

function dauerText(min){
  if(min === null || min === undefined || isNaN(Number(min))) return 'unbekannt';
  const m = Number(min);
  if(m < 60) return `${m} Min.`;
  if(m < 1440) return `${Math.round(m / 60)} Std.`;
  return `${Math.round(m / 1440)} Tage`;
}

function kurzZeit(wert){
  if(!wert) return '';
  const d = new Date(wert);
  if(Number.isNaN(d.getTime())) return String(wert).slice(0,16).replace('T',' ');
  return new Intl.DateTimeFormat('de-CH',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);
}

function toast(text){
  const t = document.querySelector('#toast');
  if(!t) return;
  t.textContent = text;
  t.classList.add('on');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('on'), 2500);
}

export { $, COL, DEP, MODE, cls, dauerText, esc, kurzZeit, money, num, params, pct, toast };
