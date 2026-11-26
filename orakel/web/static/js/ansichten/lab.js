/* Lab: Kandidatenliste, Filter, Fall-Details und Walk-Forward-Faltblöcke. */
import { R } from '../kern/daten.js';
import { $, cls, esc, num, params, pct } from '../kern/helfer.js';
import { zeichne } from '../kern/navigation.js';

let labFilter = 'all', labSel = 0, labWahl = '';

document.querySelector('#labTabs').onclick = e => {
  const b = e.target.closest('.tab'); if(!b) return;
  labFilter = b.dataset.f; labSel = 0; labWahl = '';
  document.querySelectorAll('#labTabs .tab').forEach(t=>t.classList.toggle('on',t===b));
  renderLab();
};

const KURVE_B = 600, KURVE_H = 150, KURVE_RAND = 8;

let kapitalKurveDaten = null;

function drahteKapitalKurve(){
  const box = document.querySelector('#labDetail .wfoKurveFlaeche');
  const daten = kapitalKurveDaten;
  if(!box || !daten || daten.punkte.length < 2) return;
  const svg = box.querySelector('svg');
  const zeiger = box.querySelector('.wfoKurveZeiger');
  const punkt = box.querySelector('.wfoKurvePunkt');
  const tipp = box.querySelector('.wfoKurveTipp');
  const live = box.querySelector('.wfoKurveLive');
  const { punkte, tief, hoch, spanne, start } = daten;
  let aktiv = -1, ueber = false;
  const datum = t => {
    const teile = String(t || '').slice(0, 10).split('-');
    return teile.length === 3 ? `${teile[2]}.${teile[1]}.${teile[0]}` : String(t || '–');
  };
  const verstecke = () => {
    if(ueber || document.activeElement === svg) return;
    box.classList.remove('an');
    tipp.replaceChildren();
    live.textContent = '';
    aktiv = -1;
  };
  const setze = i => {
    const r = svg.getBoundingClientRect();
    if(!r.width) return;
    i = Math.max(0, Math.min(punkte.length - 1, i));
    if(i === aktiv && box.classList.contains('an')) return;
    aktiv = i;
    const p = punkte[i];
    const xPx = (i / (punkte.length - 1)) * r.width;
    const yPx = (KURVE_RAND + (hoch - p.v) / spanne * (KURVE_H - 2 * KURVE_RAND)) / KURVE_H * r.height;
    const xSvg = (i / (punkte.length - 1) * KURVE_B).toFixed(1);
    zeiger.setAttribute('x1', xSvg); zeiger.setAttribute('x2', xSvg);
    punkt.style.left = xPx + 'px';
    punkt.style.top = yPx + 'px';
    const zeile = document.createElement('span');
    zeile.className = 'wfoKurveWert';
    const betrag = document.createElement('b');
    betrag.textContent = 'USD ' + num(p.v, 0);
    zeile.append(betrag);
    const roh = start && Math.abs(start) > 1e-9 ? (p.v - start) / start * 100 : null;
    const prozent = roh == null ? null : Math.round(roh * 10) / 10 || 0;
    if(prozent != null){
      const delta = document.createElement('i');
      delta.className = cls(prozent);
      delta.textContent = (prozent > 0 ? '+' : '') + num(prozent, 1) + ' %';
      zeile.append(delta);
    }
    const tag = document.createElement('span');
    tag.textContent = datum(p.t);
    const hochZeile = document.createElement('span');
    hochZeile.className = 'wfoKurveHoch';
    const abstandRoh = p.hoch && Math.abs(p.hoch) > 1e-9 ? (p.v - p.hoch) / p.hoch * 100 : 0;
    const abstand = Math.round(abstandRoh * 10) / 10 || 0;
    hochZeile.textContent = `Hoch bis hier USD ${num(p.hoch,0)} · ${abstand < 0 ? num(Math.abs(abstand),1) + ' % darunter' : 'am Hoch'}`;
    tipp.replaceChildren(zeile, tag, hochZeile);
    box.classList.add('an');
    const breite = tipp.offsetWidth, hoehe = tipp.offsetHeight;
    const links = Math.max(4, Math.min(r.width - breite - 4, xPx - breite / 2));
    let oben = yPx - hoehe - 10;
    if(oben < 4) oben = yPx + 10;
    tipp.style.left = links + 'px';
    tipp.style.top = Math.max(4, Math.min(r.height - hoehe - 4, oben)) + 'px';
    const richtung = prozent == null ? '' : prozent > 0 ? `, plus ${num(prozent,1)} Prozent seit Start` : prozent < 0 ? `, minus ${num(Math.abs(prozent),1)} Prozent seit Start` : ', unverändert seit Start';
    const hochText = abstand < 0
      ? `${num(Math.abs(abstand),1)} Prozent unter dem bisherigen Hoch von USD ${num(p.hoch,0)}`
      : `am bisherigen Hoch von USD ${num(p.hoch,0)}`;
    live.textContent = `Kapital USD ${num(p.v,0)}${richtung}, ${datum(p.t)}, ${hochText}`;
  };
  const zeige = ev => {
    const r = svg.getBoundingClientRect();
    if(!r.width) return;
    const anteil = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    setze(Math.round(anteil * (punkte.length - 1)));
  };
  svg.addEventListener('pointerenter', () => { ueber = true; });
  svg.addEventListener('pointermove', zeige);
  svg.addEventListener('pointerdown', zeige);
  box.addEventListener('pointerleave', () => { ueber = false; verstecke(); });
  svg.addEventListener('focus', () => { if(aktiv < 0) setze(0); });
  svg.addEventListener('blur', verstecke);
  svg.addEventListener('keydown', ev => {
    const schritt = ev.shiftKey ? 10 : 1;
    let ziel;
    if(ev.key === 'ArrowLeft') ziel = (aktiv < 0 ? 0 : aktiv) - schritt;
    else if(ev.key === 'ArrowRight') ziel = (aktiv < 0 ? 0 : aktiv) + schritt;
    else if(ev.key === 'Home') ziel = 0;
    else if(ev.key === 'End') ziel = punkte.length - 1;
    else return;
    ev.preventDefault();
    setze(ziel);
  });
}

function kapitalKurveBlock(o){
  const roh = (o && o.kapitalkurve || []).filter(p=>Array.isArray(p) && Number.isFinite(Number(p[1])));
  if(roh.length < 2) return '';
  // Auf höchstens 240 Punkte ausdünnen; der letzte Punkt bleibt erhalten.
  const schritt = Math.max(1, Math.ceil(roh.length / 240));
  const punkte = roh.filter((_,i)=>i%schritt===0);
  if(punkte[punkte.length-1] !== roh[roh.length-1]) punkte.push(roh[roh.length-1]);
  const werte = punkte.map(p=>Number(p[1]));
  const start = werte[0], ende = werte[werte.length-1];
  const tief = Math.min(...werte), hoch = Math.max(...werte);
  const spanne = Math.max(1e-9, hoch - tief);
  let spitze = -Infinity;
  kapitalKurveDaten = { punkte: punkte.map(p=>{
    const v = Number(p[1]);
    spitze = Math.max(spitze, v);
    return { t: String(p[0] || ''), v, hoch: spitze };
  }), tief, hoch, spanne, start };
  const B = KURVE_B, H = KURVE_H, RAND = KURVE_RAND;
  const x = i => (i / (punkte.length - 1)) * B;
  const y = w => RAND + (hoch - w) / spanne * (H - 2 * RAND);
  const verlauf = punkte.map((p,i)=>`${x(i).toFixed(1)},${y(Number(p[1])).toFixed(1)}`).join(' ');
  const farbe = ende >= start ? 'var(--good)' : 'var(--bad)';
  const falten = (o.walk_forward_folds||[]).map(f=>f.test_von).filter(Boolean).slice(1);
  const grenzen = falten.map(ts=>{
    const i = punkte.findIndex(p=>String(p[0]) >= ts);
    return i > 0 ? `<line x1="${x(i).toFixed(1)}" y1="0" x2="${x(i).toFixed(1)}" y2="${H}" class="wfoKurveFalte"></line>` : '';
  }).join('');
  const aria = `Kapitalkurve der Walk-Forward-Testfenster: Start USD ${num(start,0)}, Tief USD ${num(tief,0)}, Hoch USD ${num(hoch,0)}, Ende USD ${num(ende,0)}. Mit den Pfeiltasten Datenpunkte ablesen, Home und Ende für Anfang und Schluss.`;
  return `<div class="ph" style="border-top:1px solid var(--line)">Walk-Forward-Kapitalkurve<span class="tag">Testfenster verkettet</span></div>
    <div class="wfoKurve">
    <div class="wfoKurveFlaeche">
    <svg viewBox="0 0 ${B} ${H}" preserveAspectRatio="none" role="img" tabindex="0" aria-label="${esc(aria)}">
      <line x1="0" y1="${y(start).toFixed(1)}" x2="${B}" y2="${y(start).toFixed(1)}" class="wfoKurveBasis"></line>
      ${grenzen}
      <polygon points="0,${H} ${verlauf} ${B},${H}" fill="${farbe}" opacity=".1"></polygon>
      <polyline points="${verlauf}" fill="none" stroke="${farbe}" stroke-width="1.6"
        vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round"></polyline>
      <line x1="0" y1="0" x2="0" y2="${H}" class="wfoKurveZeiger"></line>
    </svg>
    <div class="wfoKurvePunkt"></div>
    <div class="wfoKurveTipp"></div>
    <div class="wfoKurveLive" role="status" aria-live="polite"></div>
    </div>
    <div class="wfoKurveFuss">
      <span>Start <b>USD ${num(start,0)}</b></span><span>Tief <b>USD ${num(tief,0)}</b></span>
      <span>Hoch <b>USD ${num(hoch,0)}</b></span><span>Ende <b class="${cls(ende-start)}">USD ${num(ende,0)}</b></span>
    </div>
    <div class="wfoKurveHinweis" aria-hidden="true">Mit <kbd>←</kbd> <kbd>→</kbd> Datenpunkte ablesen</div></div>`;
}

function wfoFoldsBlock(o){
  const folds = (o && o.walk_forward_folds)||[];
  if(!folds.length) return '';
  const datum = t => t ? esc(String(t).slice(0,10)) : '–';
  const betrag = v => v==null?'–':(v>=0?'+':'-')+'USD '+num(Math.abs(v),0);
  return `<details class="wfoFolds"><summary>Walk-Forward-Fenster
    <small>${folds.length} Fenster · ${folds.filter(f=>f.profitable).length} profitabel</small></summary>
    <div class="tw"><table class="tbl"><thead><tr><th>Fenster</th><th>Training</th><th>Test</th>
    <th>Parameter im Fenster</th><th class="m">Trades Training</th><th class="m">Trades Test</th>
    <th class="m">Profit Factor</th><th class="m">Netto</th><th>Ergebnis</th></tr></thead><tbody>
    ${folds.map(f=>{
      const F=f.test||{}, P=f.train||{}, ok=!!f.profitable;
      return `<tr><td>Fenster ${esc(f.nr)}</td><td>${datum(f.train_von)} – ${datum(f.train_bis)}</td>
      <td>${datum(f.test_von)} – ${datum(f.test_bis)}</td><td style="white-space:normal">${esc(params(f.parameter)||'–')}</td>
      <td class="m">${P.trades??'–'}</td><td class="m">${F.trades??'–'}</td>
      <td class="m">${F.profit_factor==null?'–':num(F.profit_factor,2)}</td>
      <td class="m ${cls(F.netto)}">${betrag(F.netto)}</td>
      <td><span class="pill ${ok?'':'r'}"${f.grund?` title="${esc(f.grund)}"`:''}>${f.grund?'KEIN PARAMETER':ok?'PROFITABEL':'VERLUST'}</span></td></tr>`;
    }).join('')}
    </tbody></table></div></details>`;
}

/* Stabile Kennung eines Kandidaten. Auswahl und Fokus sollen einen Neuaufbau
   der Liste überstehen, auch wenn sich deren Reihenfolge ändert. */
function labKennung(o){
  return o ? `${o.symbol ?? ''}|${o.strategie ?? ''}|${params(o.parameter)}` : '';
}

// Guard für den Ansichts-Render: Nur ein Fokus im sichtbaren Lab-Detail
// pausiert den Neuaufbau. Ein Fokus auf Liste oder Tabs und ein ausgeblendetes
// Lab blockieren ihn nicht. Der Parameter macht die Regel direkt prüfbar.
function pausiertRenderWegenLabDetail(aktiv = document.activeElement){
  return Boolean(aktiv && aktiv.closest && aktiv.closest('#v-lab:not([hidden]) #labDetail'));
}
// Während der pausierte Render neue Daten nur übernimmt, zeigt #labNeu das
// sichtbar und als höfliche Live-Region an. Beim Verlassen des Details wird
// sofort gezeichnet, statt den nächsten Acht-Sekunden-Takt abzuwarten.
let labNeuAusstehend = false;
function setzeLabNeuStatus(ausstehend){
  labNeuAusstehend = ausstehend;
  const el = document.querySelector('#labNeu');
  if(!el) return;
  el.textContent = ausstehend ? 'Neue Daten verfügbar' : '';
  el.hidden = !ausstehend;
}
function zeichneLabNeu(){
  if(!labNeuAusstehend || pausiertRenderWegenLabDetail()) return;
  // Vor dem Zeichnen löschen: renderLab stellt den Fokus wieder her, dessen
  // focusin sonst erneut hier landet (Rekursion).
  setzeLabNeuStatus(false);
  zeichne();
}
document.addEventListener('focusin', zeichneLabNeu);
// focusout: Der Fokus kann auf body fallen (Klick auf ein nicht fokussierbares
// Element). Erst nach dem Fokuswechsel zeichnen, damit er nicht ins Leere geht.
document.addEventListener('focusout', () => setTimeout(zeichneLabNeu, 0));

function renderLab(){
  const v = R.validierungen||[], selbst = u => `<span class="pill ${u==='bestanden'?'':u==='abgelehnt'?'r':'g'}">${esc(u).toUpperCase()}</span>`;
  $('#labKpis').innerHTML = [['Geprüft',v.length,'Kandidaten'],['Bestanden',v.filter(x=>x.urteil==='bestanden').length,'alle Regeln inkl. Holdout'],
    ['Holdout',`${v.filter(x=>x.holdout_bestanden===true).length} / ${v.filter(x=>x.holdout_bestanden!=null).length}`,'nur bester Kandidat je Symbol'],
    ['Abgelehnt',v.filter(x=>x.urteil==='abgelehnt').length,'mit Begründung']]
    .map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const items = v.filter(x=>labFilter==='all'||x.urteil===labFilter)
    .sort((a,b)=>(b.urteil==='bestanden')-(a.urteil==='bestanden')||((b.out_of_sample||{}).profit_factor||0)-((a.out_of_sample||{}).profit_factor||0));
  const liste = $('#labList');
  // Der Refresh baut die Liste nicht unter dem Nutzer neu auf: Einträge werden
  // über ihre Kennung wiederverwendet und nur in die neue Reihenfolge gebracht.
  // Fokus, Scrollposition und Auswahl bleiben damit erhalten, auch wenn sich
  // die Sortierung ändert (Auswahl über labKennung, nicht über den Index).
  const fokusEl = document.activeElement?.closest?.('#labList .li') ?? null;
  const fokusK = fokusEl?.dataset.id ?? null;
  // Rückfall über die Position, wenn der Refresh alle Kennungen austauscht
  // (etwa bei neuen Symbolen) und der alte Knoten nicht wiederverwendet wird.
  const fokusIndex = fokusEl?.dataset.k ?? null;
  const scroll = liste.scrollTop;
  if(labWahl){
    const idx = items.findIndex(o=>labKennung(o)===labWahl);
    if(idx>=0) labSel = idx;
  }
  if(labSel>=items.length) labSel = 0;
  if(!items.length){
    liste.innerHTML = `<div class="empty">${!v.length ? 'Noch keine Kandidaten geprüft.'
      : labFilter==='bestanden' ? 'Keine bestandene Strategie.' : 'Keine Einträge in diesem Filter.'}</div>`;
  }else{
    liste.querySelector('.empty')?.remove();
    const frei = new Map();
    liste.querySelectorAll('.li').forEach(el=>{
      const id = el.dataset.id || '';
      if(!frei.has(id)) frei.set(id, []);
      frei.get(id).push(el);
    });
    items.forEach((o,k)=>{
      const id = labKennung(o);
      let el = frei.get(id)?.shift();
      if(!el){
        el = document.createElement('button');
        el.className = 'li';
        el.dataset.id = id;
      }
      el.dataset.k = k;
      el.classList.toggle('on', k===labSel);
      const signatur = `${esc(o.symbol)}|${esc(o.strategie)}|${esc(params(o.parameter))}|${o.urteil}|${num((o.out_of_sample||{}).profit_factor,2)}`;
      if(el.dataset.signatur !== signatur){
        el.dataset.signatur = signatur;
        el.innerHTML = `<span><b>${esc(o.symbol)} · ${esc(o.strategie)}</b><small>${esc(params(o.parameter))}</small></span>
          <span style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">${selbst(o.urteil)}
          <span class="r">${num((o.out_of_sample||{}).profit_factor,2)}</span></span>`;
      }
      el.onclick = () => { labSel = +el.dataset.k; labWahl = labKennung(items[labSel]); renderLab(); };
      liste.appendChild(el);
    });
    frei.forEach(rest => rest.forEach(el => el.remove()));
  }
  liste.scrollTop = scroll;
  if(fokusK || fokusIndex != null){
    // Beim Verschieben bleibt der Fokus normalerweise auf demselben Knoten;
    // nur wenn der Browser ihn verliert, wird er gezielt wiederhergestellt.
    const aktiv = document.activeElement?.closest?.('#labList .li');
    const passt = aktiv && (fokusK ? aktiv.dataset.id === fokusK : aktiv.dataset.k === fokusIndex);
    if(!passt){
      const ziel = (fokusK && [...liste.querySelectorAll('.li')].find(el => el.dataset.id === fokusK))
        || (fokusIndex != null ? [...liste.querySelectorAll('.li')].find(el => el.dataset.k === fokusIndex) : null);
      if(ziel) ziel.focus({preventScroll:true});
    }
    liste.scrollTop = scroll;
  }
  const o = items[labSel];
  if(!o){
    // Ein leerer Filter ist ein Ergebnis, kein fehlender Klick: Das Detail
    // nennt den Grund, statt nur «Keine Auswahl.» zu zeigen.
    $('#labDetail').innerHTML = `<div class="empty">${!v.length ? 'Noch keine Kandidaten geprüft. Ein Lauf füllt das Lab.'
      : labFilter==='bestanden' ? 'Der Richter hat keinen Kandidaten freigegeben. Die Begründungen stehen bei den abgelehnten Kandidaten.'
      : 'Dieser Filter enthält keine Kandidaten. Unter «Alle» stehen alle geprüften.'}</div>`;
    return;
  }
  const I=o.in_sample||{}, O=o.out_of_sample||{}, G=o.gesamt||{}, H=o.holdout||{}, Hk=H.kennzahlen||{};
  const mrow = (n,k,f) => `<tr><td>${n}</td><td class="m">${f(I[k])}</td><td class="m">${f(O[k])}</td><td class="m">${f(G[k])}</td></tr>`;
  const usd = v => v==null?'–':(v>=0?'+':'-')+'USD '+num(Math.abs(v),0);
  $('#labDetail').innerHTML = `<div class="card"><span>${selbst(o.urteil)}</span>
    <h2>${esc(o.symbol)} · ${esc(o.strategie)}</h2>
    <p class="sub" style="margin:0">${esc(o.beschreibung)}<br>Parameter: ${esc(params(o.parameter))}${o.oos_ab?' · ungesehen ab '+esc(o.oos_ab):''}</p>
    <div class="reasons">${(o.gruende||[]).map(r=>`<span class="x">${esc(r)}</span>`).join('')}${(o.erfuellt||[]).map(r=>`<span class="y">${esc(r)}</span>`).join('')}</div></div>
    <div class="tw"><table class="tbl"><thead><tr><th>Kennzahl (Start USD 100'000)</th><th class="m">Training</th><th class="m">Ungesehen</th><th class="m">Gesamt</th></tr></thead><tbody>
    ${mrow('Nettogewinn','netto',usd)}${mrow('Rendite','rendite_pct',v=>pct(v,1))}${mrow('Profit Factor','profit_factor',v=>v==null?'–':num(v,2))}
    ${mrow('Trefferquote','trefferquote_pct',v=>pct(v,1))}${mrow('Max. Drawdown','max_drawdown_pct',v=>pct(v,1))}${mrow('Trades','trades',v=>v??'–')}
    ${mrow('Gebühren','gebuehren',v=>v==null?'–':'USD '+num(v,0))}
    ${mrow('Finanzierung','finanzierung',v=>v==null?'–':'USD '+num(v,2))}
    ${mrow('Zeit im Markt','zeit_im_markt_pct',v=>pct(v,0))}${mrow('Sharpe','sharpe',v=>v==null?'–':num(v,2))}
    <tr><td>Kaufen und Halten (ungesehen)</td><td class="m">–</td><td class="m">${pct(o.kaufen_halten_oos_pct,1)}</td><td class="m">–</td></tr>
    <tr><td>Robustheit (Nachbar-Parameter profitabel)</td><td class="m">–</td><td class="m">–</td><td class="m">${o.robustheit_anteil==null?'–':Math.round(o.robustheit_anteil*100)+' %'}</td></tr>
    <tr><td>Monte-Carlo Drawdown (95 %)</td><td class="m">–</td><td class="m">–</td><td class="m">${pct(o.monte_carlo_dd_p95,1)}</td></tr>
    <tr><td>Walk-Forward-Fenster profitabel</td><td class="m">–</td><td class="m">–</td><td class="m">${o.walk_forward_bestanden==null?'–':Math.round(o.walk_forward_bestanden*100)+' %'}</td></tr>
    <tr><td>Zufallsvergleich (p-Wert, kleiner = besser)</td><td class="m">–</td><td class="m">–</td><td class="m">${o.zufall_p_wert==null?'nicht geprüft':num(o.zufall_p_wert,4)}</td></tr>
    </tbody></table></div>
    ${kapitalKurveBlock(o)}
    ${wfoFoldsBlock(o)}
    <div class="ph" style="border-top:1px solid var(--line)">Versiegelter Holdout<span class="tag">${H.von?esc(H.von)+' – '+esc(H.bis):'nur bester Kandidat'}</span></div>
    <div class="tw"><table class="tbl tblKey"><tbody>
    <tr><td>Ergebnis</td><td class="m">${o.holdout_bestanden==null?'nicht geöffnet':o.holdout_bestanden?'<span class="up">BESTANDEN</span>':'<span class="dn">ABGELEHNT</span>'}</td></tr>
    <tr><td>Profit Factor</td><td class="m">${Hk.profit_factor==null?'–':num(Hk.profit_factor,2)}</td></tr>
    <tr><td>Trades</td><td class="m">${Hk.trades??'–'}</td></tr>
    <tr><td>Nettogewinn</td><td class="m ${cls(Hk.netto)}">${Hk.netto==null?'–':usd(Hk.netto)}</td></tr>
    <tr><td>Max. Drawdown</td><td class="m">${pct(Hk.max_drawdown_pct,1)}</td></tr>
    <tr><td>Kaufen und Halten</td><td class="m">${pct(H.kaufen_halten_pct,1)}</td></tr>
    </tbody></table></div>
    <div class="ph" style="border-top:1px solid var(--line)">Letzte Trades<span class="tag">nach Gebühren, rot = Verlust</span></div>
    <div class="tw"><table class="tbl"><thead><tr><th>Einstieg</th><th>Ausstieg</th><th class="m">Stück</th><th class="m">Netto</th><th class="m">Rendite</th><th>Grund</th></tr></thead><tbody>
    ${(o.trades||[]).slice(-10).reverse().map(t=>`<tr><td>${esc(t.einstieg)}</td><td>${esc(t.ausstieg)}</td><td class="m">${num(t.stueck,0)}</td>
    <td class="m ${cls(t.netto)}">${num(t.netto)}</td><td class="m ${cls(t.rendite_pct)}">${num(t.rendite_pct,2)} %</td><td>${esc(t.grund)}</td></tr>`).join('')||'<tr><td colspan="6" class="na">keine Trades</td></tr>'}
    </tbody></table></div>`;
  drahteKapitalKurve();
}

export { renderLab, wfoFoldsBlock, pausiertRenderWegenLabDetail, setzeLabNeuStatus };
