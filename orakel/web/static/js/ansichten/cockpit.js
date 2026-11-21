/* Cockpit: Bot-Zustand, Kontostand, Gewinn/Verlust und offene Positionen.
   Alle Zahlen kommen aus dem Bericht (SQLite). Fehlt eine Grundlage, steht «–». */
import { R } from '../kern/daten.js';
import { $, COL, cls, esc, money, num } from '../kern/helfer.js';

const CP_ZEITRAUM = { heute:'Heute', '7t':'7 Tage', '1m':'1 Monat' };
let cpZeitraum = 'heute';
try { const g = localStorage.getItem('orakel.cpZeitraum'); if (g && CP_ZEITRAUM[g]) cpZeitraum = g; } catch(e) {}

const cpVz = v => v==null ? '–' : (v>0?'+':'') + num(v);

function cpSeitText(sek){
  if(sek==null) return 'noch kein Takt';
  if(sek < 90) return 'vor ' + Math.max(0,Math.round(sek)) + ' Sek.';
  if(sek < 5400) return 'vor ' + Math.round(sek/60) + ' Min.';
  if(sek < 172800) return 'vor ' + Math.round(sek/3600) + ' Std.';
  return 'vor ' + Math.round(sek/86400) + ' Tagen';
}

function cpZeit(iso){
  if(!iso) return '–';
  const d = new Date(iso);
  return isNaN(d) ? '–' : d.toLocaleString('de-CH',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
}

function cpSparkline(verlauf, farbe){
  const w = (verlauf||[]).map(p=>Number(p[1])).filter(v=>!isNaN(v));
  if(w.length < 2) return '<div class="cpSpark leer">Noch kein Verlauf</div>';
  const min = Math.min(...w), max = Math.max(...w), span = (max-min) || 1;
  const pkt = w.map((v,i)=>`${(i/(w.length-1)*100).toFixed(2)},${(34-(v-min)/span*30).toFixed(2)}`).join(' ');
  return `<svg class="cpSpark" viewBox="0 0 100 36" preserveAspectRatio="none" role="img" aria-label="Verlauf Kontostand">
    <polyline points="${pkt}" fill="none" stroke="${farbe}" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>`;
}

export function renderCockpit(){
  const el = $('#cockpit');
  if(!el) return;
  const C = R.cockpit;
  if(!C){ el.innerHTML = '<div class="empty">Cockpit-Daten fehlen (Server aktualisieren).</div>'; $('#cpPosPanel').hidden = true; return; }
  const bot = C.bot||{}, konto = C.konto||{}, g = (C.gewinn||{})[cpZeitraum]||{};
  const BOT = { laeuft:['Läuft','g',COL.good], steht:['Steht','w',COL.amber], gestoppt:['Gestoppt','r',COL.bad], nie:['Noch nie gelaufen','n',COL.dim] };
  const b = BOT[bot.zustand] || ['Unbekannt','n',COL.dim];
  const gFarbe = g.betrag>0 ? COL.good : g.betrag<0 ? COL.bad : COL.dim;
  const seit = g.betrag==null ? 'keine Kontodaten im Zeitraum'
    : g.seit_start ? 'seit Start am ' + cpZeit(g.seit)
    : cpZeitraum==='heute' ? 'seit 00:00 Uhr (Zürich)' : 'seit ' + cpZeit(g.seit);
  const P = C.positionen||[];
  el.innerHTML = `
    <div class="cpKachel cpBot cp-${b[1]}">
      <div class="l">Bot</div>
      <div class="v"><span class="cpDot" style="background:${b[2]}"></span>${b[0]}</div>
      <div class="n">${esc(bot.text||'')} · letzter Takt ${cpSeitText(bot.alter_sekunden)}</div>
    </div>
    <div class="cpKachel">
      <div class="l">Kontostand</div>
      <div class="v">${money(konto.equity)}</div>
      <div class="n">${konto.equity==null ? 'noch kein Paper-Konto' : 'Bargeld ' + money(konto.cash) + ' · Start ' + money(konto.start_kapital)}</div>
    </div>
    <div class="cpKachel cpGewinn">
      <div class="cpKopf"><span class="l">Gewinn / Verlust</span>
        <span class="tabs" role="group" aria-label="Zeitraum">${Object.entries(CP_ZEITRAUM).map(([k,t])=>
          `<button type="button" class="tab ${k===cpZeitraum?'on':''}" data-cpz="${k}" aria-pressed="${k===cpZeitraum}">${t}</button>`).join('')}</span></div>
      <div class="v ${cls(g.betrag)}">${g.betrag==null ? '–' : cpVz(g.betrag) + ' USD'}<small>${g.pct==null ? '' : ' ' + (g.pct>0?'+':'') + num(g.pct,2) + ' %'}</small></div>
      ${cpSparkline(g.verlauf, gFarbe)}
      <div class="n">${seit}</div>
    </div>
    <div class="cpKachel">
      <div class="l">Offene Positionen</div>
      <div class="v">${P.length}</div>
      <div class="n">${P.length ? 'nicht realisiert <span class="' + cls(C.positionen_ergebnis) + '">' + cpVz(C.positionen_ergebnis) + ' USD</span>' : 'keine offene Position'}</div>
    </div>`;
  el.querySelectorAll('[data-cpz]').forEach(t => t.onclick = () => {
    cpZeitraum = t.dataset.cpz;
    try { localStorage.setItem('orakel.cpZeitraum', cpZeitraum); } catch(e) {}
    renderCockpit();
    const neu = el.querySelector(`[data-cpz="${cpZeitraum}"]`);
    if (neu) neu.focus();
  });

  $('#cpPosPanel').hidden = !P.length;
  $('#cpPosTag').textContent = P.length ? P.length + ' offen' : '';
  $('#cpPos').innerHTML = P.length ? `<table class="tbl"><thead><tr><th>Symbol</th><th class="m">Menge</th><th class="m">Einstieg</th><th class="m">Kurs</th><th class="m">Stop</th><th class="m">Ergebnis</th><th>Seit</th></tr></thead><tbody>
    ${P.map(p=>`<tr><td><b>${esc(p.symbol)}</b><br><small class="na">${esc(p.strategie)}</small></td>
      <td class="m">${num(p.menge,0)}</td><td class="m">${num(p.einstieg,5)}</td><td class="m">${num(p.kurs,5)}</td>
      <td class="m">${num(p.stop,5)}</td>
      <td class="m ${cls(p.ergebnis)}">${cpVz(p.ergebnis)}${p.ergebnis_pct==null?'':'<br><small>'+(p.ergebnis_pct>0?'+':'')+num(p.ergebnis_pct,2)+' %</small>'}</td>
      <td>${esc(cpZeit(p.eroeffnet))}</td></tr>`).join('')}</tbody></table>` : '';
}
