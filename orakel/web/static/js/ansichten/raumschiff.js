/* Raumschiff: 2.5D-Querschnitt, Räume, Agentenpanel und Pixelbühne. */
import { ladeSitzung } from './sitzung.js';
import { R } from '../kern/daten.js';
import { $, DEP, auswahl, dauerText, esc, kurzZeit, num, toast } from '../kern/helfer.js';

let companyDaten = null, companyFehler = null, companyTimer = null, companyLaden = false;
const SHIP_GROSS_MQ = window.matchMedia('(min-width: 1100px)');
let shipGrossGerendert = null;
function shipGrossAktiv(){ return SHIP_GROSS_MQ.matches; }
let shipAuswahl = { typ: 'overview' }, shipDeptFilter = null, shipZoom = 1, shipX = 0, shipY = 0, shipZoomInit = false;
let shipDetail = null, shipDetailFehler = null, shipDetailLaden = false;
let shipDetailFuer = null, shipDetailAnfrage = 0, shipNachrichtStatus = null, shipDraft = null;

const DECK_A = ['A','B','E','C'];

const DECK_B = ['D','F','G','H'];

function companyAbteilung(k){
  return ((companyDaten && companyDaten.overview && companyDaten.overview.abteilungen) || [])
    .find(d => d.code === k) || null;
}

function companyAgentenDept(k){
  return ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [])
    .filter(a => a.dept === k);
}

function hatCompanyDaten(){
  return !!(companyDaten && companyDaten.agents && Number(companyDaten.agents.gesamt) > 0);
}

function shipRaum(k, breit, proAbteilung){
  const liste = proAbteilung[k] || [];
  const befunde = liste.filter(r=>!r.ok).length;
  const on = k === auswahl.depSel;
  const company = hatCompanyDaten();
  const cdept = companyAbteilung(k);
  const cagenten = companyAgentenDept(k);
  const offen = company && cdept ? Number(cdept.offen) || 0 : 0;
  const laeuft = company && cdept ? Number(cdept.laeuft) || 0 : 0;
  const blockiert = company && cdept ? Number(cdept.blockiert) || 0 : 0;
  const zustand = company ? (blockiert ? 'befund' : 'ok')
    : (liste.length ? (befunde ? 'befund' : 'ok') : 'leer');
  const anzahl = company ? cagenten.length : liste.length;
  const meta = company
    ? `${anzahl} Agenten · ${offen} offen${laeuft ? ` · ${laeuft} läuft` : ''}${blockiert ? ` · ${blockiert} blockiert` : ''}`
    : (liste.length ? `${liste.length} Agenten` : 'KEINE DATEN') + (befunde ? ` · ${befunde} Befund` : '');
  const punkte = company
    ? cagenten.slice(0,10).map(a=>`<i class="${a.status==='blockiert'?'warn':a.status==='laeuft'?'ok':a.status==='wartet'?'wait':'free'}"></i>`).join('')
    : liste.slice(0,10).map(r=>`<i class="${r.ok?'ok':'warn'}"></i>`).join('');
  const aria = company
    ? `${anzahl} Agenten, ${offen} offen${blockiert?`, ${blockiert} blockiert`:''}`
    : `${liste.length} Agenten${befunde?`, ${befunde} Befund`:''}`;
  return `<button class="ship-room is-${zustand}${on?' on':''}${breit?' is-wide':''}" data-d="${k}" aria-pressed="${on?'true':'false'}"
    aria-label="${esc(DEP[k])}: ${aria}">
    <span class="ship-room-code">${k}</span>
    <span class="ship-room-name">${esc(DEP[k])}</span>
    <span class="ship-room-meta">${meta}</span>
    <span class="dots">${punkte}</span>
  </button>`;
}

let sekAktiv = 'S1', sekDaten = null;

async function ladeSekretariat(){
  try{
    const r = await fetch('/api/sekretariat', {cache:'no-store'});
    sekDaten = await r.json();
  }catch(e){
    sekDaten = null;
  }
  renderSekretariat();
}

let agSuche = '', agEntscheid = '', agArt = '';

function renderAgenda(){
  const box = $('#sekAgenda');
  if(!box) return;
  const a = sekDaten && sekDaten.agenda;
  if(!a || !a.themen || !a.themen.length){
    box.innerHTML = '<div class="empty">Noch keine Agenda gesammelt.</div>';
    return;
  }
  if(!$('#agListe')){
    box.innerHTML = `<div class="sekStand" id="agZahl"></div>
      <div class="protoTools">
        <input id="agSuche" placeholder="Agenda durchsuchen …">
        <select id="agEntscheid">
          ${[['', 'alle Entscheide'], ['offen', 'offen'], ['vertagt', 'vertagt']]
            .map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
        </select>
        <select id="agArt">
          ${[['', 'alle Arten'], ['muster', 'Muster'], ['verlust', 'Verlust'], ['gewinn', 'Gewinn'], ['befund', 'Befund'], ['fehler', 'Fehler'], ['beschluss', 'Beschluss']]
            .map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
        </select>
      </div>
      <div id="agListe"></div>`;
    $('#agSuche').oninput = () => { agSuche = $('#agSuche').value; agendaListe(); };
    $('#agEntscheid').onchange = () => { agEntscheid = $('#agEntscheid').value; agendaListe(); };
    $('#agArt').onchange = () => { agArt = $('#agArt').value; agendaListe(); };
  }
  $('#agSuche').value = agSuche;
  $('#agEntscheid').value = agEntscheid;
  $('#agArt').value = agArt;
  agendaListe();
}

function agendaListe(){
  const box = $('#agListe');
  const a = sekDaten && sekDaten.agenda;
  if(!box || !a) return;
  const namen = {'S1': 'Mira', 'S2': 'Jonas', 'S3': 'Lea'};
  const text = (agSuche || '').trim().toLowerCase();
  const themen = a.themen.filter(t => {
    if(agEntscheid === 'vertagt' && !t.vertagt) return false;
    if(agEntscheid === 'offen' && t.vertagt) return false;
    if(agArt && t.art !== agArt) return false;
    if(!text) return true;
    return [t.thema, t.gemacht, t.besser, t.gelernt, t.ausstieg_grund]
      .join(' ').toLowerCase().includes(text);
  });
  const zahl = $('#agZahl');
  if(zahl){
    const namenArt = {muster: 'Muster', verlust: 'Verlust', gewinn: 'Gewinn',
      befund: 'Befund', fehler: 'Fehler', beschluss: 'Beschluss'};
    const verteilung = {};
    a.themen.forEach(t => { const k = t.art || 'sonstig'; verteilung[k] = (verteilung[k] || 0) + 1; });
    const textArt = Object.entries(verteilung)
      .map(([k, n]) => (namenArt[k] || k) + ' ' + n).join(' · ');
    const vorlauf = a.termin_tage
      ? ' · Termin-Vorlauf ' + a.termin_tage + (a.termin_tage === 1 ? ' Tag' : ' Tage') : '';
    zahl.textContent = kurzZeit(a.zeit) + ' · ' + themen.length + ' / ' + a.themen.length +
      ' Themen · ' + textArt + vorlauf;
  }
  box.innerHTML = themen.map(t => `
    <div class="sekThema">
      <small>${esc(namen[t.leiter] || t.leiter)} leitet · ${esc(t.art)}${t.termin ? ' · Termin ' + esc(t.termin) : ''}${t.vertagt ? ' · vertagt' : ''}</small>
      <b>${esc(t.thema)}</b>
      <span><i>Gemacht</i>${esc(t.gemacht)}</span>
      ${t.dauer_minuten !== undefined && t.dauer_minuten !== null ? `<span><i>Dauer</i>${esc(dauerText(t.dauer_minuten))}</span>` : ''}
      ${t.ausstieg_grund ? `<span><i>Ausstieg</i>${esc(t.ausstieg_grund)}</span>` : ''}
      ${t.trades && t.trades.length ? `<span><i>Trades</i>${t.trades.length}</span>` : ''}
      <span><i>Besser</i>${esc(t.besser)}</span>
      <span><i>Gelernt</i>${esc(t.gelernt)}</span>
    </div>`).join('') + (themen.length ? '' : '<div class="empty">Kein Thema passt zu Suche und Filter.</div>');
}

function renderSekretariat(){
  const box = $('#sekTabs');
  if(!box) return;
  const sekt = (sekDaten && sekDaten.sekretaere) || [];
  box.innerHTML = sekt.map(s=>`<button type="button" class="${s.id===sekAktiv?'on':''}" data-sek="${s.id}">${esc(s.name)} · ${esc(s.rolle)}</button>`).join('');
  box.querySelectorAll('[data-sek]').forEach(b=>b.onclick=()=>{ sekAktiv = b.dataset.sek; renderSekretariat(); });
  renderAgenda();
  const th = $('#sekThread');
  if(!th) return;
  const verlauf = ((sekDaten && sekDaten.chat) || []).filter(m=>m.sekretaer===sekAktiv);
  th.innerHTML = verlauf.length ? verlauf.map(m=>{
    const name = (sekt.find(s=>s.id===m.sekretaer)||{}).name || 'SEKRETARIAT';
    return `<div class="sekMsg ich"><small>DU · ${esc(kurzZeit(m.zeit))}</small>${esc(m.frage)}</div>
      <div class="sekMsg"><small>${esc(name)} · ${esc(kurzZeit(m.zeit))}</small>${esc(m.antwort)}</div>`;
  }).join('') : '<div class="empty">Noch kein Gespräch. Frag nach Befunden, Artikeln, Konferenz, Konto oder Status.</div>';
  th.scrollTop = th.scrollHeight;
  const inp = $('#sekInput');
  if(inp) inp.placeholder = `Frage an ${(sekt.find(s=>s.id===sekAktiv)||{}).name || 'Sekretariat'} …`;
}

$('#sekAgendaBtn') && ($('#sekAgendaBtn').onclick = async () => {
  const btn = $('#sekAgendaBtn');
  btn.disabled = true;
  try{
    const r = await fetch('/api/sekretariat/agenda', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Agenda fehlgeschlagen');
    sekDaten = {...(sekDaten || {}), agenda: {zeit: d.zeit, themen: d.themen}};
    renderAgenda();
    toast('Agenda gesammelt: ' + ((d.themen || []).length) + ' Themen.');
  }catch(err){
    const box = $('#sekAgenda');
    if(box) box.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(err.message)}</div>`);
    toast('Agenda fehlgeschlagen.');
  }finally{
    btn.disabled = false;
  }
});

$('#sekForm') && ($('#sekForm').onsubmit = async e => {
  e.preventDefault();
  const inp = $('#sekInput');
  const text = (inp.value || '').trim();
  if(!text) return;
  inp.value = '';
  try{
    const r = await fetch('/api/sekretariat/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sekretaer: sekAktiv, text})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Antwort fehlgeschlagen');
    sekDaten = {...(sekDaten || {}), chat: d.verlauf};
    renderSekretariat();
  }catch(err){
    const th = $('#sekThread');
    if(th) th.insertAdjacentHTML('beforeend', `<div class="sekMsg"><small>FEHLER</small>${esc(err.message)}</div>`);
  }
});

function renderCEO(runs){
  const box = $('#deckC');
  if(!box) return;
  const konto = (R.paper && R.paper.konto) || {};
  const konf = R.konferenz || {};
  const markt = (R.markt && R.markt.symbole) || [];
  const sp = R.spider || {};
  const befunde = runs.filter(r=>!r.ok).length;
  const cash = Number.isFinite(Number(konto.cash)) ? num(konto.cash, 0) : null;
  const meldungen = runs.slice(-3).reverse();
  box.innerHTML = `
    <div class="exec-room">
      <span class="exec-code">CEO</span>
      <b>Büro · Gianluca</b>
      <div class="exec-kpis">
        <span><small>KONTO</small>${cash !== null ? cash : '–'}</span>
        <span><small>LÄUFE</small>${runs.length || 0}</span>
        <span><small>BEFUNDE</small>${befunde}</span>
      </div>
      <small class="exec-note">Paper only · keine Broker-Orders</small>
    </div>
    <div class="exec-room">
      <span class="exec-code">SEC</span>
      <b>Empfang &amp; Sekretariat</b>
      <div class="exec-list">${meldungen.length ? meldungen.map(r=>`<span><b>${esc((r.agent||'').split(':')[1] || r.agent)}</b><small>${esc(r.ergebnis)}</small></span>`).join('') : '<span class="exec-empty">KEINE MELDUNGEN</span>'}</div>
    </div>
    <div class="exec-room">
      <span class="exec-code">BRD</span>
      <b>Privater Besprechungsraum</b>
      <div class="exec-list">
        <span><b>Letzte Konferenz</b><small>${konf.zeit ? kurzZeit(konf.zeit) : 'KEINE DATEN'}</small></span>
        <span><b>Beschluss</b><small>${esc(konf.beschluss || 'KEINE DATEN')}</small></span>
      </div>
    </div>
    <div class="exec-room exec-obs">
      <span class="exec-code">OBS</span>
      <b>Lounge &amp; Beobachtungsdeck</b>
      <div class="exec-stars" aria-hidden="true"></div>
      <div class="exec-list">
        <span><b>Märkte</b><small>${markt.length} Symbole</small></span>
        <span><b>Spinne</b><small>${sp.stand ? 'Abruf ' + kurzZeit(sp.stand) : 'KEINE DATEN'}</small></span>
      </div>
    </div>`;
}

function proAbteilungAusRuns(){
  const runs = (R && R.agenten) || [];
  const proAbteilung = {};
  runs.forEach(r => { (proAbteilung[r.abteilung] = proAbteilung[r.abteilung] || []).push(r); });
  return proAbteilung;
}

function renderDeckRooms(){
  const proAbteilung = proAbteilungAusRuns();
  $('#deckA').innerHTML = DECK_A.map(k=>shipRaum(k, false, proAbteilung)).join('');
  $('#deckB').innerHTML = DECK_B.map(k=>shipRaum(k, k==='D', proAbteilung)).join('');
  document.querySelectorAll('#v-ship .ship-room').forEach(b => b.onclick = () => { auswahl.depSel = b.dataset.d; renderShip(); });
}

async function ladeCompany(){
  if(companyLaden) return;
  companyLaden = true;
  try{
    const antworten = await Promise.all([
      fetch('/api/company/overview', {cache:'no-store'}),
      fetch('/api/company/agents', {cache:'no-store'}),
      fetch('/api/company/tasks?limit=12', {cache:'no-store'}),
    ]);
    if(antworten.some(r => !r.ok)) throw new Error('HTTP ' + antworten.find(r => !r.ok).status);
    const [overview, agents, tasks] = await Promise.all(antworten.map(r=>r.json()));
    companyDaten = {overview, agents, tasks};
    companyFehler = null;
  }catch(e){
    companyDaten = null;
    companyFehler = String((e && e.message) || e);
  }finally{
    companyLaden = false;
  }
  renderCompany();
}

function renderCompany(){
  if(!$('#companyPanel')) return;
  renderShipWorld();
  const detail = $('#shipModeDetail'), tag = $('#companyTag');
  const kpis = $('#companyKpis'), liste = $('#companyTasks'), taskTag = $('#companyTaskTag');
  if(!companyDaten){
    if(detail) detail.textContent = companyFehler ? 'Company-API nicht erreichbar' : 'Company-API wird geladen …';
    if(tag) tag.textContent = companyFehler ? 'API-FEHLER' : 'lädt';
    if(taskTag) taskTag.textContent = '–';
    if(kpis) kpis.innerHTML = `<div class="kpi"><div class="l">Company-API</div><div class="v">–</div><div class="n">${companyFehler?esc(companyFehler):'wird geladen'}</div></div>`;
    if(liste) liste.innerHTML = `<div class="empty">${companyFehler?'Company-API nicht erreichbar.':'Offene Aufgaben werden geladen …'}</div>`;
    return;
  }
  const o = companyDaten.overview || {}, a = companyDaten.agents || {}, t = companyDaten.tasks || {};
  const s = o.agenten_status || {}, p = o.profile || {};
  const offen = Number((o.aufgaben && o.aufgaben.offen) || 0);
  const agenten = Number(a.gesamt || p.gesamt || 0);
  if(detail) detail.textContent = `${agenten} Agenten · ${s.aktiv||0} aktiv · ${s.blockiert||0} blockiert · ${offen} offen`;
  if(tag) tag.textContent = o.data_state === 'empty' ? 'keine Daten' : `live · ${kurzZeit(o.generated_at) || 'Stand unbekannt'}`;
  if(kpis) kpis.innerHTML = [
    ['Agenten', agenten, `${s.frei||0} frei`],
    ['aktiv', s.aktiv||0, 'laufende Aufgaben'],
    ['blockiert', s.blockiert||0, 'brauchen Aufmerksamkeit'],
    ['offene Aufgaben', offen, `${s.wartend||0} wartend`],
  ].map(([l,v,n])=>`<div class="kpi"><div class="l">${l}</div><div class="v">${v}</div><div class="n">${n}</div></div>`).join('');
  const aufgaben = t.aufgaben || [];
  if(taskTag) taskTag.textContent = `${Number(t.gesamt)||0} offen${aufgaben.length < (Number(t.gesamt)||0) ? ` · ${aufgaben.length} gezeigt` : ''}`;
  if(liste) liste.innerHTML = aufgaben.length ? aufgaben.map(task=>{
    const pill = task.state === 'blocked' ? 'r' : task.state === 'running' ? 'b' : 'w';
    const frist = task.due_at ? ` · fällig ${kurzZeit(task.due_at)}` : '';
    return `<div class="li"><span><b>${esc(task.title)}</b><small>${esc(task.rufname||task.assigned_to)} · ${esc(task.dept_name||task.dept)} · ${esc(task.state_text)}${frist}</small></span><span class="pill ${pill}">${esc(task.state_text)}</span></div>`;
  }).join('') : '<div class="empty">Keine offenen Aufgaben.</div>';
}

function renderAbteilung(){
  const proAbteilung = proAbteilungAusRuns();
  const meine = proAbteilung[auswahl.depSel] || [];
  const company = hatCompanyDaten();
  const cagenten = companyAgentenDept(auswahl.depSel);
  if(company && cagenten.length){
    const offen = cagenten.reduce((n,a)=>n+(Number(a.offene_aufgaben)||0), 0);
    const laeuft = cagenten.filter(a=>a.status==='laeuft').length;
    $('#roomTag').textContent = `${cagenten.length} Agenten · ${offen} offen${laeuft?` · ${laeuft} läuft`:''}`;
    $('#roomAgents').innerHTML = cagenten.map(a=>{
      const pill = a.status==='blockiert'?'r':a.status==='laeuft'?'b':a.status==='wartet'?'w':'g';
      const letzte = a.letzte_task && a.letzte_task.title && a.letzte_task.title !== a.role ? a.letzte_task.title : '';
      const teile = [esc(a.role)];
      if(a.offene_aufgaben) teile.push(`${a.offene_aufgaben} offen`);
      if(letzte) teile.push(esc(letzte));
      return `<div class="li"><span><b>${esc(a.rufname)}</b><small>${teile.join(' · ')}</small></span><span class="pill ${pill}">${esc(a.status_text)}</span></div>`;
    }).join('');
  }else{
    $('#roomTag').textContent = `${meine.length} Agenten · ${meine.filter(r=>r.ok).length} ohne Befund`;
    $('#roomAgents').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b>${esc((r.agent||'').split(':')[1]||r.agent)}</b>
      <small>${esc(r.aufgabe)}</small></span><span class="pill ${r.ok?'':'r'}">${r.ok?'OK':'BEFUND'}</span></div>`).join('')
      : '<div class="empty">Noch kein Lauf für diese Abteilung.</div>';
  }
  $('#roomRuns').innerHTML = meine.length ? meine.map(r=>`<div class="li"><span><b style="font-weight:400">${esc(r.ergebnis)}</b>
    <small>${esc((r.agent||'').split(':')[1]||r.agent)}</small></span></div>`).join('')
    : '<div class="empty">Keine Rohrpost.</div>';
}

function renderShip(){
  if(!companyDaten && !companyLaden) ladeCompany();
  renderCompany();
  ladeSekretariat();
  ladeSitzung();
  if(!shipZoomInit) requestAnimationFrame(fitShip);
}

const SHIP_FARBEN = ['#38e8ff','#ff3fa4','#ffb84d','#9b6cff','#55e6a5','#ff7a59','#5aa9ff','#ff5edb','#c6ff5e','#ff9f43','#74ffd0'];

const SHIP_DEPT_NAMEN = { A:'Hauptzentrale', B:'Spider Intelligence', C:'Labor', D:'Trading Floor',
  E:'Forschungsabteilung', F:'Risikomanagement', G:'Wissenszentrum', H:'Entwicklungsabteilung',
  I:'Globale Intelligence', J:'Sicherheit', S:'Executive-Sekretariat' };

function shipDeptList(){
  const o = (companyDaten && companyDaten.overview) || {};
  const agenten = (companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [];
  const depts = (o.abteilungen || []).slice();
  const seen = new Set(depts.map(d => d.code));
  agenten.forEach(a => {
    if(!seen.has(a.dept)){
      seen.add(a.dept);
      depts.push({ code:a.dept, name:a.dept_name || a.dept, agenten:0 });
    }
  });
  return depts.sort((a,b) => (a.code === 'S' ? 999 : a.code.charCodeAt(0)) - (b.code === 'S' ? 999 : b.code.charCodeAt(0)))
    .map(d => ({ ...d, name:SHIP_DEPT_NAMEN[d.code] || d.name, liste: agenten.filter(a => a.dept === d.code) }));
}

function shipStatusKey(a){
  return a.status === 'laeuft' ? 'laeuft' : a.status === 'blockiert' ? 'blockiert' : a.status === 'wartet' ? 'wartet' : 'frei';
}

const SHIP_ROOM_TYPEN = { A:'command', B:'server', C:'lab', D:'trading', E:'research', F:'risk',
  G:'archive', H:'workshop', I:'observatory', J:'security', S:'meeting' };

function shipDeptFarbe(code){
  const depts = shipDeptList();
  const i = depts.findIndex(d => d.code === code);
  return SHIP_FARBEN[(i >= 0 ? i : 0) % SHIP_FARBEN.length];
}

function shipDeptKnoepfe(depts, kompakt = false, filter = false){
  const titel = filter ? 'Abteilung im Schiff hervorheben' : 'Ersten Agenten dieser Abteilung öffnen';
  const gedrueckt = filter ? ' aria-controls="shipWorld" aria-pressed="false"' : '';
  return `<div class="sd-depts${kompakt ? ' sd-legend' : ''}">${depts.map(d => `<button type="button" class="sd-dept" data-dept="${esc(d.code)}" style="--dept:${shipDeptFarbe(d.code)}" title="${titel}"${gedrueckt}>
    <span class="sw"></span><b>${esc(d.code)} · ${esc(d.name)}</b><small>${d.liste.length}</small></button>`).join('')}</div>`;
}

function bindeShipDeptKnoepfe(side, agenten){
  side.querySelectorAll('[data-dept]').forEach(b => b.onclick = () => {
    const a = agenten.find(x => x.dept === b.dataset.dept);
    if(a) setShipSelection('agent', a.agent_id);
  });
}

function shipGewaehlteAbteilung(){
  if(shipDeptFilter) return shipDeptFilter;
  if(shipAuswahl.typ !== 'agent') return null;
  const raum = [...document.querySelectorAll('#shipWorld [data-agent]')]
    .find(b => b.dataset.agent === shipAuswahl.id);
  return raum?.closest('.px-dept')?.dataset.dept || null;
}

function syncShipDeptFilter(){
  const world = $('#shipWorld');
  const legend = $('#shipLegend');
  const depts = world ? [...world.querySelectorAll('.px-dept')] : [];
  if(shipDeptFilter && !depts.some(el => el.dataset.dept === shipDeptFilter)) shipDeptFilter = null;
  const aktiv = shipDeptFilter;
  const gewaehlt = shipGewaehlteAbteilung();
  if(world){
    world.classList.toggle('filter-aktiv', !!aktiv);
    depts.forEach(el => el.classList.toggle('is-filter-active', !!aktiv && el.dataset.dept === aktiv));
  }
  if(legend){
    legend.querySelectorAll('[data-dept]').forEach(b => {
      const on = !!aktiv && b.dataset.dept === aktiv;
      b.classList.toggle('is-active', on);
      b.classList.toggle('is-selected', !on && !!gewaehlt && b.dataset.dept === gewaehlt);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      b.title = on ? 'Filter lösen' : 'Abteilung im Schiff hervorheben';
    });
  }
}

function setShipDeptFilter(code){
  shipDeptFilter = shipDeptFilter === code ? null : code;
  syncShipDeptFilter();
}

function bindeShipFilterKnoepfe(box){
  box.querySelectorAll('[data-dept]').forEach(b => {
    b.onclick = () => setShipDeptFilter(b.dataset.dept);
  });
}

function syncShipLegend(){
  const box = $('#shipLegend');
  if(!box) return;
  const schmal = window.matchMedia('(max-width:760px)').matches;
  const zustand = String(schmal);
  if(box.dataset.schmal !== zustand){
    box.open = !schmal;
    box.dataset.schmal = zustand;
  }
}

function renderShipLegend(depts, agenten){
  const box = $('#shipLegend');
  if(!box) return;
  box.hidden = false;
  box.innerHTML = `<summary class="sl-head"><small>SEKTOREN · FILTER</small><b>${depts.length} ABTEILUNGEN</b><i class="sl-pfeil" aria-hidden="true"></i></summary>${shipDeptKnoepfe(depts, true, true)}`;
  syncShipLegend();
  bindeShipFilterKnoepfe(box);
  syncShipDeptFilter();
}

const PX = 3;                       // 1 Kunst-Pixel = 3 Bildschirm-Pixel

let pxRaeume = [], pxTakt = 0, pxTimer = null;

const PX_HAUT = ['#f4cfa6','#e2ad7f','#c88a58','#91603c','#5e3b25'];

const PX_HAAR = ['#2b1b12','#5a3a1e','#d6a94e','#141414','#a0522d','#e9e2d4','#ff5fb0','#3fd0ff','#7b4bff'];

const PX_HOSE = ['#24223a','#1d2b3c','#30263a','#262626'];

const PX_BODEN = { command:'#2f3a52', server:'#2a2e3c', lab:'#d9d9e4', trading:'#3a2f4d', research:'#4a3a30',
  risk:'#3d2a30', archive:'#5a4330', workshop:'#3a3a3a', observatory:'#232a44', security:'#2d2a2a', meeting:'#4b2f3d' };

const PX_MUSTER = [[3,2,3,2,2],[2,3,2,2,3],[2,2,3,3,2],[3,3,2,2,2],[2,3,3,2,2]];

function pxHash(s){ let h = 2166136261; for(const c of String(s)){ h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }

function pxRng(seed){ let s = (seed >>> 0) || 7; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return (s % 100000) / 100000; }; }

function pxN(a, b, c){ let h = (a * 374761393 + b * 668265263 + c * 1442695041) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return (h ^ (h >>> 16)) >>> 0; }

function pxMix(a, b, f){
  const p = h => [1,3,5].map(i => parseInt(h.slice(i, i+2), 16));
  const x = p(a), y = p(b);
  return '#' + x.map((v,i) => Math.round(v + (y[i]-v) * f).toString(16).padStart(2,'0')).join('');
}

function pxPinsel(ctx){
  return {
    ctx,
    r(x, y, w, h, c){ if(w <= 0 || h <= 0) return; ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); },
    p(x, y, c){ ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), 1, 1); },
    a(alpha, fn){ ctx.globalAlpha = alpha; fn(); ctx.globalAlpha = 1; },
  };
}

function pxHuelle(g, w, h, farbe, typ, rng){
  const fy = h - 7;
  const wand = pxMix('#2e2a4a', farbe, .2), dunkel = pxMix(wand, '#000000', .38), hell = pxMix(wand, '#ffffff', .09);
  g.r(0, 0, w, h, wand);
  const schritt = 9 + Math.floor(rng() * 4);
  for(let x = 3 + Math.floor(rng() * schritt); x < w; x += schritt){ g.r(x, 4, 1, fy - 7, dunkel); g.r(x + 1, 4, 1, fy - 7, hell); }
  g.r(0, fy - 3, w, 1, hell); g.r(0, fy - 2, w, 2, dunkel);
  g.r(0, 0, w, 3, '#0a0812'); g.r(0, 3, w, 1, pxMix(farbe, '#000000', .5));
  for(let x = 2; x < w; x += 7) g.p(x, 1, '#2a2638');
  const boden = PX_BODEN[typ] || '#3b3448';
  g.r(0, fy, w, h - fy, boden); g.r(0, fy, w, 1, pxMix(boden, '#ffffff', .28));
  for(let x = Math.floor(rng() * 6); x < w; x += 6) g.r(x, fy + 2 + ((x / 6) & 1) * 2, 1, 2, pxMix(boden, '#000000', .28));
  g.r(0, h - 1, w, 1, '#06050a');
  return fy;
}

function pxLampe(g, x, fy, farbe){
  g.r(x - 3, 3, 7, 1, '#fff4d6'); g.r(x - 2, 4, 5, 1, pxMix('#fff4d6', farbe, .4));
  g.a(.11, () => { const c = g.ctx; c.fillStyle = '#fff4d6'; c.beginPath(); c.moveTo(x - 3, 5); c.lineTo(x + 4, 5); c.lineTo(x + 13, fy); c.lineTo(x - 12, fy); c.fill(); });
}

function pxFenster(g, x, y, w, h, rng){
  g.r(x - 1, y - 1, w + 2, h + 2, '#59627a'); g.r(x, y, w, h, '#0b0f2c');
  g.r(x, y + h - 2, w, 2, '#2a1550');
  for(let i = 0; i < 4; i++) g.p(x + Math.floor(rng() * w), y + Math.floor(rng() * (h - 1)), i ? '#9fb4ff' : '#ffffff');
  g.p(x + Math.floor(rng() * w), y + h - 2, '#ff5fc8');
}

function pxTisch(g, x, y, w, fy, farbe){
  g.r(x, y, w, 1, '#a99cba'); g.r(x, y + 1, w, 2, '#4a4058'); g.r(x, y + 1, w, 1, pxMix(farbe, '#000000', .25));
  g.r(x + 1, y + 3, 1, fy - y - 3, '#2a2433'); g.r(x + w - 2, y + 3, 1, fy - y - 3, '#2a2433');
}

function pxStuhl(g, x, fy){
  g.r(x, fy - 9, 1, 6, '#3b3550'); g.r(x, fy - 4, 4, 1, '#4d4666'); g.r(x + 2, fy - 3, 1, 2, '#2a2433'); g.r(x + 1, fy - 1, 3, 1, '#1b1825');
}

function pxMonitor(g, x, y, w, h, farbe, t, an, art){
  g.r(x - 1, y - 1, w + 2, h + 2, '#0c0c13');
  g.r(x, y, w, h, an ? pxMix(farbe, '#000000', .62) : '#11141f');
  g.r(x + Math.floor(w / 2), y + h + 1, 1, 1, '#0c0c13');
  if(!an){ if((t >> 3) % 4 === 0) g.p(x + 1, y + 1, '#2c3348'); return; }
  const hell = pxMix(farbe, '#ffffff', .45);
  if(art === 'kerzen'){
    for(let i = 0; i < w - 1; i += 2){
      const v = pxN(i + (t >> 1), x, 3), hoch = 1 + v % (h - 1), auf = (v >> 4) & 1;
      g.r(x + 1 + i, y + h - hoch, 1, hoch, auf ? '#3dff8f' : '#ff4d6d');
    }
  }else if(art === 'kurve'){
    let yy = y + Math.floor(h / 2);
    for(let i = 0; i < w; i++){ yy += (pxN(i + t, x, 9) % 3) - 1; yy = Math.max(y, Math.min(y + h - 1, yy)); g.p(x + i, yy, '#ff5577'); }
  }else{
    for(let i = 0; i < h - 1; i += 2){ const l = 1 + pxN(x, i, t >> 1) % (w - 1); g.r(x + 1, y + 1 + i, Math.min(l, w - 2), 1, i % 4 ? hell : '#ffffff'); }
  }
}

function pxPflanze(g, x, fy){
  g.r(x, fy - 3, 4, 3, '#8a5a3c'); g.r(x, fy - 3, 4, 1, '#a8704a');
  g.r(x + 1, fy - 7, 2, 4, '#2fae5c'); g.p(x, fy - 6, '#3fd070'); g.p(x + 3, fy - 8, '#3fd070'); g.p(x + 1, fy - 9, '#56e087'); g.p(x + 3, fy - 5, '#249048');
}

function pxBuecher(g, x, y, w, h, rng){
  g.r(x, y, w, h, '#3a2a1e');
  for(let yy = y + 1; yy < y + h - 1; yy += 5){
    g.r(x, yy + 4, w, 1, '#5a4330');
    for(let xx = x + 1; xx < x + w - 1; xx++){
      const c = ['#c94f4f','#4f7fc9','#d6b04a','#4fb08a','#9a5fc9','#e8e0d0'][Math.floor(rng() * 6)];
      const hh = 2 + Math.floor(rng() * 2); if(rng() < .15) continue;
      g.r(xx, yy + 4 - hh, 1, hh, c);
    }
  }
}

function pxFigur(g, x, fy, look, pose, t, rechts){
  const { haut, haar, hemd, hose } = look;
  const auge = '#140c1c';
  if(pose === 'sitzt'){
    const y = fy - 12, tipp = (t & 1) ? 1 : 0;
    g.r(x + 1, y, 3, 1, haar); g.r(x + 1, y + 1, 3, 2, haut); g.p(x + 1, y + 1, haar); g.p(x + 3, y + 1, auge);
    g.r(x, y + 3, 4, 4, hemd); g.p(x, y + 3, pxMix(hemd, '#000000', .3));
    g.r(x + 4, y + 4 + tipp, 2, 1, hemd); g.p(x + 6, y + 4 + tipp, haut);
    g.r(x + 1, y + 7, 5, 1, hose); g.r(x + 5, y + 8, 1, 3, hose); g.r(x + 5, y + 11, 2, 1, '#0d0b12');
    return;
  }
  const y = fy - 11, schritt = pose === 'geht' ? (t & 1) : 0;
  const bob = pose === 'wartet' && (t % 10 < 5) ? 1 : 0;
  g.r(x + 1, y + bob, 3, 1, haar); g.r(x + 1, y + 1 + bob, 3, 2, haut);
  g.p(rechts ? x + 1 : x + 3, y + 1 + bob, haar); g.p(rechts ? x + 3 : x + 1, y + 1 + bob, auge);
  g.r(x, y + 3, 5, 4, hemd); g.p(x, y + 6, haut); g.p(x + 4, y + 6, haut);
  g.r(x + 1, y + 7, 3, 1, hose);
  if(schritt){ g.r(x, y + 8, 1, 2, hose); g.r(x + 4, y + 8, 1, 2, hose); g.p(x, y + 10, '#0d0b12'); g.p(x + 4, y + 10, '#0d0b12'); }
  else{ g.r(x + 1, y + 8, 1, 2, hose); g.r(x + 3, y + 8, 1, 2, hose); g.p(x + 1, y + 10, '#0d0b12'); g.p(x + 3, y + 10, '#0d0b12'); }
}

function pxBlase(g, x, y, art, t){
  if(art === 'alarm'){
    if(t % 4 >= 2) return;
    g.r(x, y, 5, 6, '#ff3355'); g.r(x + 1, y - 1, 3, 1, '#ff3355'); g.r(x + 1, y + 6, 3, 1, '#ff3355');
    g.r(x + 2, y + 1, 1, 3, '#ffffff'); g.p(x + 2, y + 5, '#ffffff');
  }else{
    g.r(x - 1, y + 1, 7, 4, '#f3ecff'); g.p(x + 1, y + 5, '#f3ecff');
    for(let i = 0; i < 3; i++) g.p(x + i * 2, y + 3, i <= (t >> 1) % 3 ? '#e8a53a' : '#c9bfd8');
  }
}

function pxPlatz(g, dx, tw, fy, farbe, t, an, art, monitore){
  const ty = fy - 6, mw = Math.min(8, Math.floor((tw - 1) / monitore) - 1);
  for(let i = 0; i < monitore; i++) pxMonitor(g, dx + 1 + i * (mw + 2), ty - 7, mw, 5, farbe, t + i * 3, an, art);
  pxTisch(g, dx, ty, tw, fy, farbe);
  pxStuhl(g, dx - 6, fy);
  return dx - 5;
}

const PX_TYP = {
  command(g, w, fy, f, hell, rng, t, an){
    const bw = Math.max(10, Math.floor(w * .38));
    g.r(3, 6, bw, fy - 12, '#06222a'); g.r(3, 6, bw, 1, hell);
    for(let i = 0; i < 6; i++){ const x = 4 + pxN(i, w, 1) % (bw - 2), y = 8 + pxN(i, 2, w) % (fy - 16); g.p(x, y, (t + i) % 6 < 3 ? '#38e8ff' : '#0e5a66'); }
    g.r(3 + Math.floor(bw / 2), fy - 6, 1, 3, '#2a3550');
    const dx = bw + 10;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 2);
  },
  server(g, w, fy, f, hell, rng, t, an){
    const n = w > 46 ? 3 : 2;
    for(let i = 0; i < n; i++){
      const x = 2 + i * 7;
      g.r(x, 6, 6, fy - 6, '#14151e'); g.r(x, 6, 6, 1, '#3c3f56'); g.r(x + 5, 6, 1, fy - 6, '#25273a');
      for(let y = 8; y < fy - 1; y += 2){ g.r(x + 1, y, 4, 1, '#232535'); const z = pxN(i, y, t >> 1) % 3; g.p(x + 1 + pxN(y, i, 7) % 3, y, z === 0 ? '#2bff88' : z === 1 ? hell : '#10301f'); }
    }
    const dx = 2 + n * 7 + 8;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  lab(g, w, fy, f, hell, rng, t, an){
    g.r(3, 6, 6, fy - 9, '#8fb8c8'); g.r(4, 7, 4, fy - 11, pxMix(f, '#0a1a20', .35));
    for(let i = 0; i < 3; i++){ const by = fy - 5 - ((t * 2 + i * 7) % (fy - 12)); g.p(5 + (i % 2) * 2, by, '#e8ffff'); }
    g.r(2, fy - 3, 8, 3, '#545a6e');
    g.r(12, 12, Math.min(14, w - 34), 1, '#7a7f94');
    const farben = ['#3dff8f', '#ff5fc8', '#ffd84d', '#4dc8ff'];
    for(let i = 0; i < Math.floor(Math.min(14, w - 34) / 4); i++){ const x = 13 + i * 4; g.r(x, 9, 2, 3, farben[i % 4]); g.p(x, 8, '#c8d8e8'); }
    const dx = Math.max(20, Math.floor(w * .5));
    const ty = fy - 6; g.r(dx + 2, ty - 4, 2, 4, '#3dff8f'); g.p(dx + 2, ty - 5, '#c8d8e8');
    if(an) g.p(dx + 3, ty - 6 - (t % 3), '#e8ffff');
    pxMonitor(g, dx + 6, ty - 7, Math.min(7, w - dx - 9), 5, f, t, an, 'kurve');
    pxTisch(g, dx, ty, w - dx - 2, fy, f); pxStuhl(g, dx - 6, fy);
    return dx - 5;
  },
  trading(g, w, fy, f, hell, rng, t, an){
    g.r(0, 5, w, 3, '#0b0710');
    for(let x = 0; x < w; x += 2){ const v = pxN(x + t, 5, 1); g.p(x, 6, v % 3 ? '#3dff8f' : '#ff4d6d'); }
    g.r(3, 11, Math.max(8, Math.floor(w * .3)), 9, '#0d0b18'); g.r(3, 11, Math.max(8, Math.floor(w * .3)), 1, hell);
    pxMonitor(g, 4, 13, Math.max(6, Math.floor(w * .3) - 2), 6, '#3dff8f', t + 5, true, 'kerzen');
    const dx = Math.max(16, Math.floor(w * .3) + 10);
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kerzen', w - dx > 24 ? 3 : 2);
  },
  research(g, w, fy, f, hell, rng, t, an){
    pxBuecher(g, 2, 7, 10, fy - 7, rng);
    const dx = Math.max(20, Math.floor(w * .48));
    pxPflanze(g, w - 6, fy);
    return pxPlatz(g, dx, Math.min(14, w - dx - 8), fy, f, t, an, 'code', 1);
  },
  risk(g, w, fy, f, hell, rng, t, an){
    const bw = Math.max(10, Math.floor(w * .34));
    g.r(3, 6, bw, 11, '#1a0a10'); g.r(3, 6, bw, 1, '#ff5577');
    pxMonitor(g, 4, 8, bw - 2, 8, '#ff5577', t, true, 'kurve');
    for(let x = 0; x < w; x += 4){ g.r(x, fy, 2, 1, '#ffcc33'); g.r(x + 2, fy, 2, 1, '#1a1a1a'); }
    const dx = bw + 10;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kurve', 2);
  },
  archive(g, w, fy, f, hell, rng, t, an){
    const bw = Math.floor(w * .5);
    pxBuecher(g, 2, 6, bw, fy - 6, rng);
    const dx = bw + 9;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  workshop(g, w, fy, f, hell, rng, t, an){
    const bw = Math.max(12, Math.floor(w * .42));
    g.r(2, 6, bw, 10, '#3a3f4a');
    for(let x = 3; x < bw; x += 2) for(let y = 7; y < 16; y += 2) g.p(x, y, '#2a2e36');
    g.r(4, 8, 1, 5, '#c0c4cc'); g.r(3, 8, 3, 1, '#c0c4cc'); g.r(8, 9, 4, 1, '#ff9f43'); g.r(10, 8, 1, 4, '#8a8f99');
    g.r(2, fy - 5, bw, 2, '#6a4a2e'); g.r(3, fy - 3, 1, 3, '#3a2a1e'); g.r(bw - 1, fy - 3, 1, 3, '#3a2a1e');
    const ax = Math.floor(bw / 2) + 2, sw = an ? (t % 8 < 4 ? 1 : -1) : 0;
    g.r(ax, fy - 9, 2, 4, '#ffb84d'); g.r(ax + sw, fy - 12, 2, 3, '#ffb84d'); g.r(ax + sw * 2 - 1, fy - 13, 4, 1, '#d0d4dc');
    if(an && t % 3 === 0) g.p(ax + sw * 2, fy - 6, '#ffffff');
    const dx = bw + 10;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  observatory(g, w, fy, f, hell, rng, t, an){
    const cx = 9, cy = 12, r = 6;
    for(let y = -r - 1; y <= r + 1; y++) for(let x = -r - 1; x <= r + 1; x++){
      const d = x * x + y * y;
      if(d <= r * r) g.p(cx + x, cy + y, '#0a0c2a');
      else if(d <= (r + 1) * (r + 1) + 2) g.p(cx + x, cy + y, '#6a7390');
    }
    g.r(cx + 1, cy, 3, 3, '#7b4bff'); g.p(cx + 1, cy, '#b39bff'); g.p(cx - 3, cy - 3, '#ffffff'); g.p(cx - 1, cy + 4, '#9fb4ff');
    if((t >> 2) % 5 === 0) g.p(cx + 4, cy - 4, '#ffffff');
    g.r(19, fy - 10, 6, 2, '#c0c4cc'); g.p(18, fy - 11, '#38e8ff'); g.r(21, fy - 8, 1, 5, '#555b6e'); g.p(19, fy - 3, '#555b6e'); g.p(23, fy - 3, '#555b6e');
    const dx = Math.max(31, Math.floor(w * .55));
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  security(g, w, fy, f, hell, rng, t, an){
    const sp = w > 46 ? 3 : 2;
    for(let i = 0; i < sp; i++) for(let j = 0; j < 2; j++){
      const x = 3 + i * 7, y = 6 + j * 6;
      g.r(x, y, 6, 5, '#0b0b10'); g.r(x + 1, y + 1, 4, 3, (pxN(i, j, t >> 2) % 7) ? '#2a3a3a' : '#5a7a7a');
      g.p(x + 1 + pxN(i, j, t) % 4, y + 2, '#9fffe0');
    }
    g.r(3, fy - 9, 5, 9, '#3a4050'); g.r(8, fy - 9, 5, 9, '#343a48'); g.p(7, fy - 5, '#c0c4cc'); g.p(12, fy - 5, '#c0c4cc');
    const dx = 3 + sp * 7 + 8;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1);
  },
  meeting(g, w, fy, f, hell, rng, t, an){
    g.r(4, 7, 12, 8, '#d6a94e'); g.r(5, 8, 10, 6, '#2a1a40'); g.r(6, 11, 4, 3, '#ff5fc8'); g.r(10, 9, 4, 5, '#38e8ff');
    pxPflanze(g, 3, fy);
    const dx = Math.max(24, Math.floor(w * .45));
    const s = pxPlatz(g, dx, Math.min(22, w - dx - 3), fy, '#d6a94e', t, an, 'code', 2);
    g.r(dx, fy - 6, Math.min(22, w - dx - 3), 1, '#ffd98a');
    return s;
  },
};

function pxAgentRaum(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const typ = e.typ in PX_TYP ? e.typ : 'command';
  const fy = pxHuelle(g, w, h, e.farbe, typ, rng);
  const hell = pxMix(e.farbe, '#ffffff', .45);
  const an = e.st === 'laeuft';
  const lampe = 8 + Math.floor(rng() * Math.max(1, w - 16));
  const fenster = rng() < .35 && w > 52;
  if(fenster) pxFenster(g, w - 13, 7, 9, 6, rng);
  const sx = PX_TYP[typ](g, fenster ? w - 12 : w, fy, e.farbe, hell, rng, t, an);
  pxLampe(g, lampe, fy, e.farbe);
  const look = e.look;
  if(e.st === 'laeuft'){
    pxFigur(g, sx, fy, look, 'sitzt', t, true);
  }else if(e.st === 'frei'){
    const R = Math.max(4, w - 9), p = (t + e.seed % (R * 2)) % (R * 2);
    const x = 2 + (p < R ? p : 2 * R - p);
    pxFigur(g, x, fy, look, 'geht', t, p < R);
  }else{
    const x = Math.max(2, sx - 3);
    pxFigur(g, x, fy, look, e.st === 'wartet' ? 'wartet' : 'steht', t, true);
    pxBlase(g, x, fy - 19, e.st === 'blockiert' ? 'alarm' : 'denkt', t);
  }
  if(e.st === 'blockiert') g.a(t % 8 < 4 ? .16 : .05, () => g.r(0, 0, w, h, '#ff1f4b'));
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}

function pxAgentenraum(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#38e8ff', 'command', rng);
  pxFenster(g, 8, 7, 22, 8, rng); pxFenster(g, w - 30, 7, 22, 8, rng);
  const cx = Math.floor(w / 2);
  g.r(cx - 14, fy - 5, 28, 2, '#3a4a66'); g.r(cx - 12, fy - 3, 24, 3, '#222c40');
  g.a(.35 + ((t % 6) / 30), () => { const c = g.ctx; c.fillStyle = '#38e8ff'; c.beginPath(); c.moveTo(cx - 10, fy - 5); c.lineTo(cx + 10, fy - 5); c.lineTo(cx + 6, 6); c.lineTo(cx - 6, 6); c.fill(); });
  for(let i = 0; i < 7; i++){ const a = (t / 4 + i * .9); g.p(cx + Math.round(Math.cos(a) * 5), 12 + i * 2, '#e0ffff'); }
  for(let i = 0; i < 4; i++){ const x = 36 + i * 12; if(x < cx - 18) pxMonitor(g, x, fy - 13, 8, 5, '#38e8ff', t + i, true, 'code'); }
  for(let i = 0; i < 4; i++){ const x = w - 44 - i * 12; if(x > cx + 18) pxMonitor(g, x, fy - 13, 8, 5, '#ff3fa4', t + i * 2, true, 'kerzen'); }
  pxLampe(g, Math.floor(w * .25), fy, '#38e8ff'); pxLampe(g, Math.floor(w * .75), fy, '#38e8ff');
  const n = Math.min(6, Math.max(2, e.anzahl || 4));
  for(let i = 0; i < n; i++){
    const L = { haut:PX_HAUT[i % 5], haar:PX_HAAR[(i * 3) % PX_HAAR.length], hemd:SHIP_FARBEN[i % SHIP_FARBEN.length], hose:PX_HOSE[i % 4] };
    const R = Math.max(10, w - 20), p = (t + i * 37) % (R * 2);
    if(i < 2) pxFigur(g, cx - 22 + i * 39, fy, L, 'wartet', t + i * 3, i === 0);
    else pxFigur(g, 6 + (p < R ? p : 2 * R - p), fy, L, 'geht', t, p < R);
  }
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}

function pxKonferenz(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ffb84d', 'meeting', rng);
  const cx = Math.floor(w / 2);
  g.r(cx - 22, 6, 44, 12, '#0b0812'); g.r(cx - 22, 6, 44, 1, '#ffb84d');
  pxMonitor(g, cx - 21, 8, 20, 9, '#3dff8f', t, true, 'kerzen'); pxMonitor(g, cx + 1, 8, 20, 9, '#ff5577', t, true, 'kurve');
  g.r(cx - 34, fy - 6, 68, 2, '#8a5a3c'); g.r(cx - 34, fy - 6, 68, 1, '#c8905a'); g.r(cx - 30, fy - 4, 2, 4, '#4a3020'); g.r(cx + 28, fy - 4, 2, 4, '#4a3020');
  const n = Math.min(6, Math.max(2, e.anzahl || 4));
  for(let i = 0; i < n; i++){
    const L = { haut:PX_HAUT[(i + 2) % 5], haar:PX_HAAR[(i * 2) % PX_HAAR.length], hemd:SHIP_FARBEN[(i + 3) % SHIP_FARBEN.length], hose:PX_HOSE[i % 4] };
    const x = cx - 32 + i * Math.floor(64 / n);
    const y = fy - 4;
    g.r(x + 1, y - 11 + (i === (t >> 3) % n ? 0 : 1), 3, 1, L.haar); g.r(x + 1, y - 10 + (i === (t >> 3) % n ? 0 : 1), 3, 2, L.haut);
    g.r(x, y - 8, 5, 3, L.hemd);
  }
  pxPflanze(g, 4, fy); pxPflanze(g, w - 8, fy);
  pxLampe(g, Math.floor(w * .3), fy, '#ffb84d'); pxLampe(g, Math.floor(w * .7), fy, '#ffb84d');
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}

function pxHangar(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#5aa9ff', 'server', rng);
  for(let x = 0; x < w; x += 6){ g.r(x, fy, 3, 1, '#ffcc33'); }
  const cx = Math.floor(w / 2), sy = fy - 9 - ((t >> 2) % 4 === 0 ? 1 : 0);
  g.r(cx - 12, sy + 3, 24, 3, '#c0c8d8'); g.r(cx - 8, sy + 1, 14, 2, '#d8e0ee'); g.r(cx - 2, sy, 5, 1, '#38e8ff');
  g.r(cx - 12, sy + 5, 24, 1, '#7a8298'); g.r(cx - 15, sy + 2, 4, 5, '#9aa2b8'); g.r(cx + 11, sy + 4, 4, 1, '#ff5fc8');
  g.r(cx - 17, sy + 3, 2, 3, (t & 1) ? '#38e8ff' : '#1a8aa0');
  g.r(cx - 6, fy - 2, 1, 2, '#555b6e'); g.r(cx + 5, fy - 2, 1, 2, '#555b6e');
  pxLampe(g, 10, fy, '#5aa9ff'); pxLampe(g, w - 10, fy, '#5aa9ff');
}

function pxWarp(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#38e8ff', 'server', rng);
  const cx = Math.floor(w / 2);
  g.r(cx - 7, 4, 14, 2, '#555b6e'); g.r(cx - 7, fy - 2, 14, 2, '#555b6e');
  g.r(cx - 5, 6, 10, fy - 8, '#0a3040');
  const puls = t % 8;
  for(let y = 6; y < fy - 2; y++){ const hell = ((y + puls) % 8) < 2; g.r(cx - 4, y, 8, 1, hell ? '#9ffcff' : '#1fb8d0'); }
  g.r(cx - 1, 6, 2, fy - 8, '#ffffff');
  g.a(.12 + (puls < 4 ? .06 : 0), () => g.r(cx - 14, 4, 28, fy - 4, '#38e8ff'));
  for(let i = 0; i < 3; i++){ g.r(4 + i * 4, 8, 2, fy - 10, '#3a3f56'); g.r(w - 6 - i * 4, 8, 2, fy - 10, '#3a3f56'); }
}

function pxLounge(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ff5edb', 'lounge', rng);
  pxFenster(g, 4, 9, Math.max(6, Math.min(18, w - 12)), 8, rng);
  const sofaW = Math.max(8, Math.min(24, w - 8));
  g.r(4, fy - 7, sofaW, 2, '#7b4bff'); g.r(4, fy - 5, sofaW, 3, '#5a35b8');
  g.r(4, fy - 7, 2, 7, '#a78bff'); g.r(4 + sofaW - 2, fy - 7, 2, 7, '#a78bff');
  g.r(Math.min(30, w - 12), fy - 5, 8, 1, '#a99cba');
  g.r(Math.min(33, w - 9), fy - 4, 2, 4, '#4a4058');
  pxPflanze(g, w - 7, fy);
  pxLampe(g, Math.floor(w * .3), fy, '#ff5edb'); pxLampe(g, Math.floor(w * .75), fy, '#ff5edb');
}

function pxLager(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ff9f43', 'lager', rng);
  const rw = Math.max(10, Math.floor(w * .42));
  for(let y = 9; y < fy; y += 8){
    g.r(2, y + 6, rw, 1, '#8a6a4a');
    for(let x = 3; x < rw - 2; x += 5) g.r(x, y + 2, 4, 4, ['#b8875a','#5a7aa0','#7a9a5a'][pxN(x, y, 3) % 3]);
  }
  g.r(2, 9, 1, fy - 9, '#5a5f78'); g.r(rw + 1, 9, 1, fy - 9, '#5a5f78');
  g.r(rw + 4, fy - 6, 5, 6, '#b8875a'); g.r(rw + 5, fy - 11, 4, 5, '#5a7aa0');
  g.r(w - 9, fy - 8, 5, 1, '#c0c4cc'); g.r(w - 9, fy - 8, 1, 8, '#c0c4cc');
  for(let x = 0; x < w; x += 4) g.r(x, fy, 2, 1, '#ffcc33');
  pxLampe(g, Math.floor(w * .3), fy, '#ff9f43'); pxLampe(g, Math.floor(w * .75), fy, '#ff9f43');
}

const PX_ART = { agent:pxAgentRaum, agents:pxAgentenraum, konf:pxKonferenz, hangar:pxHangar, warp:pxWarp, lounge:pxLounge, lager:pxLager };

function pxZeichne(e){
  const cv = e.cv;
  if(!cv.width || !cv.height) return;
  const ctx = cv.getContext('2d');
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  if(e.spiegel){ ctx.setTransform(-1, 0, 0, 1, cv.width, 0); }
  const maler = e.gross && window.PX_GROSS ? window.PX_GROSS[e.art] : PX_ART[e.art];
  if(!maler) return;
  maler(pxPinsel(ctx), cv.width, cv.height, e, pxTakt);
}

function pxGroessen(){
  pxRaeume.forEach(e => {
    const w = Math.max(12, Math.round(e.cv.clientWidth / PX)), h = Math.max(12, Math.round(e.cv.clientHeight / PX));
    if(e.cv.width !== w) e.cv.width = w;
    if(e.cv.height !== h) e.cv.height = h;
    pxZeichne(e);
  });
}

function pxStarteAnimation(){
  if(pxTimer) return;
  const ruhig = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if(ruhig) return;
  pxTimer = setInterval(() => {
    const bereich = $('#v-ship');
    if(document.hidden || !bereich || bereich.hidden || !pxRaeume.length) return;
    pxTakt++;
    pxRaeume.forEach(pxZeichne);
  }, 170);
}

window.addEventListener('resize', () => { clearTimeout(pxGroessen.t); pxGroessen.t = setTimeout(pxGroessen, 200); });

function pxLook(a){
  const h = pxHash(a.agent_id || a.rufname);
  return { haut:PX_HAUT[h % 5], haar:PX_HAAR[(h >> 4) % PX_HAAR.length], hemd:shipDeptFarbe(a.dept), hose:PX_HOSE[(h >> 8) % 4] };
}

function renderShipWorld(){
  const box = $('#shipWorld');
  if(!box) return;
  box.classList.add('px-world');
  if(!companyDaten){
    const legend = $('#shipLegend');
    if(legend){ legend.hidden = true; legend.innerHTML = ''; }
    pxRaeume = [];
    box.innerHTML = `<div class="empty">${companyFehler ? 'Company-API nicht erreichbar: ' + esc(companyFehler) : 'Agentenräume werden geladen …'}</div>`;
    renderShipDetail();
    return;
  }
  const depts = shipDeptList();
  const agenten = (companyDaten.agents && companyDaten.agents.agenten) || [];
  if(shipAuswahl.typ === 'agent' && !agenten.some(a => a.agent_id === shipAuswahl.id)) shipAuswahl = { typ:'overview' };
  const s = (companyDaten.overview && companyDaten.overview.agenten_status) || {};
  const aufgaben = (companyDaten.overview && companyDaten.overview.aufgaben) || {};
  const konf = R && R.konferenz;
  const commonOn = typ => shipAuswahl.typ === typ;
  const liste = [];
  const gross = shipGrossAktiv();
  box.classList.toggle('px-gross', gross);
  shipGrossGerendert = gross;
  const leinwand = eintrag => { liste.push({ ...eintrag, gross }); return `<canvas class="px-cv" data-px="${liste.length - 1}" aria-hidden="true"></canvas>`; };

  const tuerHtml = (typ, farbe, seed) => `<span class="px-door" aria-hidden="true">${gross ? leinwand({ art:'tuer', typ, farbe, seed }) : ''}</span>`;
  const raumHtml = (a, gewicht, dIdx) => {
    const st = shipStatusKey(a);
    const offenA = Number(a.offene_aufgaben) || 0;
    const on = shipAuswahl.typ === 'agent' && shipAuswahl.id === a.agent_id;
    const titel = `${a.rufname} · ${a.role} · ${a.dept_name} · ${a.status_text || a.status}${offenA ? ` · ${offenA} offen` : ''}`;
    const seed = pxHash(a.agent_id || a.rufname);
    const cv = leinwand({ art:'agent', typ:SHIP_ROOM_TYPEN[a.dept] || 'command', farbe:shipDeptFarbe(a.dept), st, look:pxLook(a), seed, spiegel:(seed >> 3) % 3 === 0, on, agent:a.agent_id });
    return `<button type="button" class="px-room status-${st}${on ? ' on' : ''}" style="flex-grow:${gewicht}" data-agent="${esc(a.agent_id)}"
      aria-pressed="${on ? 'true' : 'false'}" title="${esc(titel)}" aria-label="${esc(titel)}">${cv}
      <span class="px-tag"><i></i>${esc(a.rufname)}</span>${offenA ? `<span class="px-task">+${offenA}</span>` : ''}</button>`;
  };
  const leerHtml = (art, gewicht, titel, extra = '') => `<span class="px-room px-void${extra}" style="flex-grow:${gewicht}" aria-hidden="true">${leinwand({ art, seed:pxHash(art + titel), farbe:'#38e8ff' })}<span class="px-tag px-tag-dim">${titel}</span></span>`;

  const deptHtml = (d, dIdx, pos) => {
    const farbe = shipDeptFarbe(d.code);
    const offen = d.liste.reduce((n,a) => n + (Number(a.offene_aufgaben) || 0), 0);
    const reihen = [];
    for(let i = 0; i < d.liste.length; i += 5) reihen.push(d.liste.slice(i, i + 5));
    if(!reihen.length) reihen.push([]);
    const floors = reihen.map((reihe, rIdx) => {
      const muster = PX_MUSTER[(dIdx + rIdx * 2) % PX_MUSTER.length];
      const teile = reihe.map((a, i) => raumHtml(a, muster[i % 5], dIdx));
      if(d.code === 'S' || reihe.length < 5){
        const fehlt = Math.max(0, 5 - reihe.length);
        for(let i = 0; i < fehlt; i++) teile.push(leerHtml(i % 2 ? 'lager' : 'lounge', 3, i % 2 ? 'LAGER' : 'CREW-LOUNGE'));
      }
      const typ = SHIP_ROOM_TYPEN[d.code] || 'command';
      const html = teile.map((t, i) => (i ? tuerHtml(typ, farbe, pxHash(d.code + rIdx + '-' + i)) : '') + t).join('');
      return `<div class="px-floor">${html || '<div class="empty">Keine Agenten.</div>'}</div>`;
    }).join('');
    return `<section class="px-dept${d.code === 'S' ? ' px-dept-wide' : ''}" data-dept="${esc(d.code)}" style="--dept:${farbe};${pos}">
      <header class="px-dept-head"><b>${esc(d.code)}</b><span>${esc(d.name)}</span><em>${d.liste.length} CREW · ${offen} OFFEN</em></header>
      ${floors}</section>`;
  };

  const normal = depts.filter(d => d.code !== 'S'), exec = depts.filter(d => d.code === 'S');
  const zeilen = Math.max(1, Math.ceil(normal.length / 2));
  const deckHtml = normal.map((d, i) => deptHtml(d, i, `grid-column:${i % 2 ? 3 : 1};grid-row:${Math.floor(i / 2) + 1}`)).join('');

  box.innerHTML = `
    <div class="px-ship">
      <div class="px-bridge">
        <span class="px-fin px-fin-l" aria-hidden="true"></span><span class="px-fin px-fin-r" aria-hidden="true"></span>
        <div class="px-brand"><span>ORAKEL // DECK 07</span><b>INTERSTELLAR OPERATIONS</b><small><i></i>${agenten.length} CREW · ${depts.length} DIVISIONEN</small></div>
        <div class="px-common">
          <button type="button" class="px-room px-common-room${commonOn('agents') ? ' on' : ''}" data-common="agents" aria-pressed="${commonOn('agents')}">
            ${leinwand({ art:'agents', seed:11, anzahl:Number(s.aktiv) || 4, on:commonOn('agents') })}
            <span class="px-tag px-tag-big"><i></i>AGENTENRAUM · ${agenten.length} AGENTEN</span></button>
          ${tuerHtml('meeting', '#ffb84d', 5)}
          <button type="button" class="px-room px-common-room${commonOn('konf') ? ' on' : ''}" data-common="konf" aria-pressed="${commonOn('konf')}">
            ${leinwand({ art:'konf', seed:23, anzahl:konf ? Math.max(4, (konf.berichte || []).length) : 6, on:commonOn('konf') })}
            <span class="px-tag px-tag-big px-tag-gold"><i></i>KONFERENZ · ${konf ? `${(konf.berichte || []).length} BERICHTE · ${(konf.massnahmen || []).length} MASSNAHMEN` : 'KEINE KONFERENZ'}</span></button>
        </div>
      </div>
      <div class="px-hull">
        <span class="px-pipe px-pipe-l" aria-hidden="true"></span><span class="px-pipe px-pipe-r" aria-hidden="true"></span>
        <div class="px-decks">
          ${deckHtml}
          <div class="px-shaft" style="grid-column:2;grid-row:1 / span ${zeilen}" aria-hidden="true"><span class="px-lift"></span></div>
        </div>
        ${exec.map((d) => deptHtml(d, 7, '')).join('')}
        <section class="px-engdeck" style="--dept:#5aa9ff">
          <header class="px-dept-head"><b>T</b><span>Technik · Antrieb</span><em>HANGAR 07 · WARP CORE</em></header>
          <div class="px-floor">${leerHtml('hangar', 3, 'HANGAR 07', ' px-big')}${tuerHtml('workshop', '#5aa9ff', 77)}${leerHtml('warp', 2, 'WARP CORE', ' px-big')}</div>
        </section>
      </div>
      <div class="px-engine">
        <span class="px-eng-state">● ${Number(s.aktiv) || 0} AKTIV · ${Number(s.blockiert) || 0} BLOCKIERT · ${Number(aufgaben.offen) || 0} OFFEN</span>
        <span class="px-nozzle"></span><span class="px-nozzle"></span><span class="px-nozzle"></span>
      </div>
      <span class="px-loop" aria-hidden="true"></span>
    </div>`;

  pxRaeume = liste.map((e, i) => ({ ...e, cv:box.querySelector(`canvas[data-px="${i}"]`) })).filter(e => e.cv);
  renderShipLegend(depts, agenten);
  box.querySelectorAll('[data-agent]').forEach(b => b.onclick = () => setShipSelection('agent', b.dataset.agent));
  box.querySelectorAll('[data-common]').forEach(b => b.onclick = () => setShipSelection(b.dataset.common));
  applyShipTransform();
  requestAnimationFrame(() => { pxGroessen(); if(!shipZoomInit) fitShip(); });
  pxStarteAnimation();
  renderShipDetail();
}

function shipWertText(wert){
  if(wert === null || wert === undefined) return '–';
  const roh = typeof wert === 'string' ? wert : JSON.stringify(wert);
  const text = String(roh ?? '–');
  return text.length > 220 ? text.slice(0, 217) + '…' : text;
}

function shipStandardEmpfaenger(a){
  const agenten = ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [])
    .filter(x => x.agent_id !== a.agent_id && x.active !== false);
  const berichtet = agenten.find(x => x.agent_id === a.reports_to);
  return (berichtet || agenten.find(x => x.dept === a.dept) || agenten[0] || {}).agent_id || '';
}

function shipEmpfaengerOptionen(a, gewaehlt){
  const agenten = ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || [])
    .filter(x => x.agent_id !== a.agent_id && x.active !== false);
  const direkt = agenten.map(x => {
    const sel = x.agent_id === gewaehlt ? ' selected' : '';
    const deptName = SHIP_DEPT_NAMEN[x.dept] || x.dept_name || x.dept;
    return `<option value="${esc(x.agent_id)}"${sel}>${esc(x.rufname)} · ${esc(x.dept)} ${esc(deptName)}</option>`;
  }).join('');
  let html = direkt ? `<optgroup label="Direkt">${direkt}</optgroup>` : '';
  if(a.rank === 'leitung' || a.rank === 'sekretariat'){
    const depts = shipDeptList().filter(d => a.rank === 'sekretariat' || d.code === a.dept);
    const opt = depts.map(d => {
      const wert = 'dept:' + d.code;
      const sel = wert === gewaehlt ? ' selected' : '';
      return `<option value="${esc(wert)}"${sel}>Abteilung ${esc(d.code)} · ${esc(d.name)}</option>`;
    }).join('');
    if(opt) html += `<optgroup label="Abteilung">${opt}</optgroup>`;
  }
  if(['A1','S1','S2','S3'].includes(a.agent_id)){
    const sel = gewaehlt === 'all' ? ' selected' : '';
    html += `<optgroup label="Broadcast"><option value="all"${sel}>Alle aktiven Agenten</option></optgroup>`;
  }
  return html;
}

function shipDraftNeu(a){
  return { fuer:a.agent_id, an:shipStandardEmpfaenger(a), art:'status', betreff:'', text:'', belege:'', quittung:true };
}

function shipNachrichtHtml(m, a){
  const eingehend = String(m.to_agent) === String(a.agent_id);
  const partner = eingehend ? (m.from_rufname || m.from_agent) : (m.to_rufname || m.to_agent);
  const quittung = m.ack_at
    ? 'quittiert ' + esc(kurzZeit(m.ack_at) || '')
    : (eingehend ? 'offen' : 'ausgehend');
  const ack = eingehend && !m.ack_at
    ? `<button type="button" class="sd-msg-ack" data-ship-ack="${Number(m.id)}">Quittieren</button>` : '';
  const belege = Array.isArray(m.evidence) && m.evidence.length
    ? `<small class="sd-msg-evidence">Belege: ${m.evidence.map(x => esc(x)).join(' · ')}</small>` : '';
  return `<article class="sd-msg ${eingehend ? 'ist-eingang' : 'ist-ausgang'}">
    <div class="sd-msg-kopf"><b>${esc(m.subject || '(ohne Betreff)')}</b><span>${esc(m.kind || 'status')}</span></div>
    <small class="sd-msg-meta">${eingehend ? 'von' : 'an'} ${esc(partner || '–')} · ${esc(kurzZeit(m.created_at) || '–')} · ${quittung}</small>
    <p class="sd-msg-body">${esc(m.body || '')}</p>${belege}${ack}</article>`;
}

function shipKommunikationHtml(a){
  const detail = shipDetail && shipDetail.profil && shipDetail.profil.agent_id === a.agent_id ? shipDetail : null;
  const nachrichten = detail && Array.isArray(detail.nachrichten) ? detail.nachrichten : [];
  const erinnerungen = detail && Array.isArray(detail.erinnerungen) ? detail.erinnerungen : [];
  if(!shipDraft || shipDraft.fuer !== a.agent_id) shipDraft = shipDraftNeu(a);
  const draft = shipDraft;
  const arten = [['status','Status'],['handoff','Übergabe'],['question','Frage'],['answer','Antwort'],['task_request','Auftrag'],['task_result','Ergebnis'],['review_request','Review'],['review_result','Review-Ergebnis'],['alert','Alarm'],['decision','Entscheid']];
  const artOptionen = arten.map(([wert, text]) => `<option value="${wert}"${draft.art === wert ? ' selected' : ''}>${text}</option>`).join('');
  const formular = detail ? `<form class="sd-form" data-ship-form>
    <label>Empfänger<select name="an" data-ship-feld="an" required>${shipEmpfaengerOptionen(a, draft.an)}</select></label>
    <div class="sd-form-zeile">
      <label>Art<select name="art" data-ship-feld="art">${artOptionen}</select></label>
      <label class="sd-check"><input type="checkbox" name="quittung" data-ship-feld="quittung"${draft.quittung ? ' checked' : ''}> Quittung anfordern</label>
    </div>
    <label>Betreff<input name="betreff" maxlength="200" value="${esc(draft.betreff)}" data-ship-feld="betreff" required autocomplete="off"></label>
    <label>Nachricht<textarea name="text" rows="3" maxlength="8000" data-ship-feld="text" required>${esc(draft.text)}</textarea></label>
    <label>Belege <span>(kommagetrennt)</span><input name="belege" maxlength="2000" value="${esc(draft.belege)}" data-ship-feld="belege" placeholder="task:12, article:4821" autocomplete="off"></label>
    <button type="submit" class="sd-send">Nachricht senden</button>
  </form>` : '';
  const liste = nachrichten.length
    ? `<div class="sd-msg-liste">${nachrichten.map(m => shipNachrichtHtml(m, a)).join('')}</div>`
    : '<p class="sd-leer">Keine Nachrichten.</p>';
  const memory = erinnerungen.length ? `<div class="sd-memory-liste">${erinnerungen.map(e => `
    <div class="sd-memory"><div><b>${esc(e.scope)} · ${esc(e.key)}</b><small>${esc(kurzZeit(e.updated_at) || '–')}</small></div><code>${esc(shipWertText(e.value))}</code></div>`).join('')}</div>`
    : '<p class="sd-leer">Noch keine persönlichen Erinnerungen.</p>';
  const status = shipNachrichtStatus
    ? `<p class="sd-hinweis ${shipNachrichtStatus.typ}" role="status">${esc(shipNachrichtStatus.text)}</p>` : '';
  const fehler = shipDetailFehler
    ? `<p class="sd-hinweis fehler" role="status">${esc(shipDetailFehler)}</p>` : '';
  const laden = !detail
    ? (shipDetailLaden ? '<p class="sd-leer">Nachrichten und Erinnerungen werden geladen …</p>' : '')
    : '';
  return `<div class="sd-kommunikation" data-ship-kommunikation>
    <div class="sd-block">
      <div class="sd-block-kopf"><small>NACHRICHTEN${nachrichten.length ? ` · ${nachrichten.length}` : ''}</small>
        <button type="button" class="sd-mini" data-ship-detail-refresh${shipDetailLaden ? ' disabled' : ''}>${shipDetailLaden ? 'lädt …' : 'Aktualisieren'}</button></div>
      ${fehler}${status}${laden}${detail ? liste + formular : ''}
    </div>
    <div class="sd-block"><small>ERINNERUNGEN${erinnerungen.length ? ` · ${erinnerungen.length}` : ''}</small>
      ${detail ? memory : (shipDetailLaden ? '<p class="sd-leer">Wird geladen …</p>' : '')}</div>
  </div>`;
}

function ladeShipDetail(agentId, erzwingen = false){
  if(!erzwingen && shipDetailFuer === agentId && (shipDetailLaden || shipDetail)) return;
  const token = ++shipDetailAnfrage;
  shipDetailFuer = agentId;
  shipDetailLaden = true;
  shipDetailFehler = null;
  renderShipDetail(true);
  fetch(`/api/company/agents/${encodeURIComponent(agentId)}`, {cache:'no-store'})
    .then(async antwort => {
      const daten = await antwort.json().catch(() => ({}));
      if(!antwort.ok) throw new Error(daten.fehler || ('HTTP ' + antwort.status));
      return daten;
    })
    .then(daten => {
      if(token !== shipDetailAnfrage) return;
      shipDetail = daten;
    })
    .catch(e => {
      if(token !== shipDetailAnfrage) return;
      shipDetailFehler = String((e && e.message) || e);
    })
    .finally(() => {
      if(token !== shipDetailAnfrage) return;
      shipDetailLaden = false;
      renderShipDetail(true);
    });
}

function bindeShipKommunikation(side, a){
  const form = side.querySelector('[data-ship-form]');
  if(form){
    form.onsubmit = ev => { ev.preventDefault(); sendeShipNachricht(a, form); };
    form.querySelectorAll('[data-ship-feld]').forEach(el => {
      const key = el.dataset.shipFeld;
      const merken = () => {
        if(shipDraft && shipDraft.fuer === a.agent_id) shipDraft[key] = el.type === 'checkbox' ? el.checked : el.value;
      };
      el.addEventListener('input', merken);
      el.addEventListener('change', merken);
    });
  }
  side.querySelectorAll('[data-ship-ack]').forEach(btn => {
    btn.onclick = () => quittiereShipNachricht(a, Number(btn.dataset.shipAck), btn);
  });
  const refresh = side.querySelector('[data-ship-detail-refresh]');
  if(refresh) refresh.onclick = () => ladeShipDetail(a.agent_id, true);
}

async function sendeShipNachricht(a, form){
  const fuer = a.agent_id;
  const knopf = form.querySelector('button[type="submit"]');
  const wert = name => {
    const feld = form.querySelector(`[name="${name}"]`);
    return feld ? feld.value : '';
  };
  const an = wert('an');
  const belege = wert('belege').split(',').map(x => x.trim()).filter(Boolean);
  if(!an){
    shipNachrichtStatus = {typ:'fehler', text:'Bitte einen Empfänger wählen.'};
    renderShipDetail(true);
    return;
  }
  if(knopf){ knopf.disabled = true; knopf.textContent = 'Sendet …'; }
  try{
    const antwort = await fetch('/api/company/messages', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({
      from_agent:a.agent_id, to_agent:an, subject:wert('betreff'), body:wert('text'),
      kind:wert('art'), evidence:belege,
      requires_ack:Boolean(form.querySelector('[name="quittung"]')?.checked),
    })});
    const daten = await antwort.json().catch(() => ({}));
    if(!antwort.ok || !daten.ok) throw new Error(daten.fehler || ('HTTP ' + antwort.status));
    if(shipAuswahl.typ !== 'agent' || shipAuswahl.id !== fuer) return;
    const neue = Array.isArray(daten.messages) ? daten.messages : [];
    if(shipDetail){
      const ids = new Set(neue.map(m => Number(m.id)));
      shipDetail.nachrichten = [...neue, ...(shipDetail.nachrichten || []).filter(m => !ids.has(Number(m.id)))].slice(0, 25);
    }
    shipNachrichtStatus = {typ:'ok', text:`Nachricht an ${Number((daten.to_agents || []).length) || 1} Empfänger gesendet.`};
    shipDraft = shipDraftNeu(a);
    renderShipDetail(true);
  }catch(e){
    if(shipAuswahl.typ === 'agent' && shipAuswahl.id === fuer){
      shipNachrichtStatus = {typ:'fehler', text:String((e && e.message) || e)};
      renderShipDetail(true);
    }
  }
}

async function quittiereShipNachricht(a, id, knopf){
  const fuer = a.agent_id;
  if(knopf){ knopf.disabled = true; knopf.textContent = 'Quittiere …'; }
  try{
    const antwort = await fetch(`/api/company/messages/${id}/ack`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({agent_id:a.agent_id})});
    const daten = await antwort.json().catch(() => ({}));
    if(!antwort.ok || !daten.ok) throw new Error(daten.fehler || ('HTTP ' + antwort.status));
    if(shipAuswahl.typ !== 'agent' || shipAuswahl.id !== fuer) return;
    const m = (shipDetail && shipDetail.nachrichten || []).find(x => Number(x.id) === id);
    if(m) m.ack_at = (daten.nachricht && daten.nachricht.ack_at) || new Date().toISOString();
    shipNachrichtStatus = {typ:'ok', text:'Nachricht quittiert.'};
    renderShipDetail(true);
  }catch(e){
    if(shipAuswahl.typ === 'agent' && shipAuswahl.id === fuer){
      shipNachrichtStatus = {typ:'fehler', text:String((e && e.message) || e)};
      renderShipDetail(true);
    }
  }
}

function setShipSelection(typ, id){
  if(shipDeptFilter){
    const raum = typ === 'agent'
      ? [...document.querySelectorAll('#shipWorld [data-agent]')].find(b => b.dataset.agent === id)
      : null;
    if(!raum || raum.closest('.px-dept')?.dataset.dept !== shipDeptFilter){
      shipDeptFilter = null;
      syncShipDeptFilter();
    }
  }
  shipAuswahl = typ === 'agent' ? { typ:'agent', id } : { typ };
  if(typ === 'agent'){
    const a = ((companyDaten && companyDaten.agents && companyDaten.agents.agenten) || []).find(x => x.agent_id === id);
    if(shipDetailFuer !== id || !shipDetail){
      shipDetail = null;
      shipDetailFehler = null;
      shipNachrichtStatus = null;
      shipDraft = a ? shipDraftNeu(a) : null;
      ladeShipDetail(id);
    }
  }else{
    shipDetailAnfrage++;
    shipDetail = null;
    shipDetailFehler = null;
    shipDetailLaden = false;
    shipDetailFuer = null;
    shipNachrichtStatus = null;
    shipDraft = null;
  }
  document.querySelectorAll('#shipWorld [data-agent]').forEach(b => {
    const on = typ === 'agent' && b.dataset.agent === id;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  document.querySelectorAll('#shipWorld [data-common]').forEach(b => {
    const on = b.dataset.common === typ;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  pxRaeume.forEach(e => {
    const on = e.agent ? (typ === 'agent' && e.agent === id) : (e.art === 'agents' ? typ === 'agents' : e.art === 'konf' ? typ === 'konf' : false);
    if(e.on !== on){ e.on = on; pxZeichne(e); }
  });
  syncShipDeptFilter();
  renderShipDetail();
  const side = $('#shipSideInhalt'); if(side) side.scrollTop = 0;
}

function renderShipDetail(force = false){
  const side = $('#shipSideInhalt');
  if(!side) return;
  if(!companyDaten){
    side.innerHTML = `<span class="sd-kicker">RAUMSCHIFF</span><h2>Verbindung</h2><p>${companyFehler ? 'Company-API nicht erreichbar: ' + esc(companyFehler) : 'Agentenlage wird geladen …'}</p>`;
    return;
  }
  if(!force && shipAuswahl.typ === 'agent' && shipDetail && shipDetail.profil
     && shipDetail.profil.agent_id === shipAuswahl.id
     && side.querySelector('[data-ship-kommunikation]')) return;
  const depts = shipDeptList();
  const agenten = (companyDaten.agents && companyDaten.agents.agenten) || [];
  const s = (companyDaten.overview && companyDaten.overview.agenten_status) || {};
  const aufgaben = (companyDaten.overview && companyDaten.overview.aufgaben) || {};

  if(shipAuswahl.typ === 'agents'){
    side.innerHTML = `<span class="sd-kicker">GEMEINSCHAFTSRAUM</span><h2>Agentenraum</h2>
      <p>${agenten.length} Agenten in ${depts.length} Abteilungen. Eine Abteilung wählen, um ihren ersten Agenten zu öffnen.</p>
      <div class="sd-kpis"><div class="sd-kpi"><small>GESAMT</small><b>${agenten.length}</b></div>
        <div class="sd-kpi"><small>AKTIV</small><b>${Number(s.aktiv)||0}</b></div><div class="sd-kpi"><small>OFFEN</small><b>${Number(aufgaben.offen)||0}</b></div></div>
      <div class="sd-block"><small>ABTEILUNGEN</small>${shipDeptKnoepfe(depts)}</div>`;
    bindeShipDeptKnoepfe(side, agenten);
    return;
  }

  if(shipAuswahl.typ === 'konf'){
    const k = R && R.konferenz;
    if(!k){
      side.innerHTML = `<span class="sd-kicker">GEMEINSCHAFTSRAUM</span><h2>Konferenz</h2><p>Noch keine Konferenz abgehalten.</p>`;
      return;
    }
    side.innerHTML = `<span class="sd-kicker">GEMEINSCHAFTSRAUM</span><h2>Konferenz</h2>
      <p>${esc(k.beschluss || 'Kein Beschluss gespeichert.')}</p>
      <div class="sd-kpis"><div class="sd-kpi"><small>BERICHTE</small><b>${(k.berichte || []).length}</b></div>
        <div class="sd-kpi"><small>DISKUSSION</small><b>${(k.diskussion || []).length}</b></div><div class="sd-kpi"><small>MASSNAHMEN</small><b>${(k.massnahmen || []).length}</b></div></div>
      <div class="sd-block"><small>MODUS · ${esc(k.zeit ? kurzZeit(k.zeit) : '–')}</small><b>${esc(k.modus || '–')}</b></div>
      <div class="sd-block"><small>MASSNAHMEN</small>${(k.massnahmen || []).slice(0,4).map(m => `<div class="sd-measure"><b>${esc(m.beschreibung || '–')}</b>${esc(m.verantwortlicher || 'Nicht zugewiesen')}</div>`).join('') || '<p>Keine Massnahmen.</p>'}</div>`;
    return;
  }

  if(shipAuswahl.typ === 'agent'){
    const a = agenten.find(x => x.agent_id === shipAuswahl.id);
    if(a){
      const farbe = shipDeptFarbe(a.dept);
      const st = shipStatusKey(a);
      const letzte = a.letzte_task || null;
      if(!shipDraft || shipDraft.fuer !== a.agent_id) shipDraft = shipDraftNeu(a);
      side.innerHTML = `<span class="sd-kicker">AGENTENRAUM · ${esc(a.dept)}</span>
        <div class="sd-head"><span class="sd-avatar" style="--dept:${farbe}">${esc((a.rufname || '?').slice(0,1).toUpperCase())}</span>
          <span class="sd-head-txt"><small>${esc(a.agent_id)} · ${esc(a.station || '–')}</small><b>${esc(a.rufname)}</b></span></div>
        <p>${esc(a.role)} · ${esc(a.dept_name)}</p>
        <div class="sd-status ${st}"><span class="p"></span>${esc(a.status_text || a.status)}${a.active ? ' · an Bord' : ' · inaktiv'}</div>
        <div class="sd-kpis"><div class="sd-kpi"><small>OFFEN</small><b>${Number(a.offene_aufgaben)||0}</b></div>
          <div class="sd-kpi"><small>LÄUFT</small><b>${Number(a.davon_laufend)||0}</b></div><div class="sd-kpi"><small>BLOCKIERT</small><b>${Number(a.davon_blockiert)||0}</b></div></div>
        <div class="sd-block"><small>AUFTRAG</small><p>${esc(a.mission || 'Keine Mission hinterlegt.')}</p></div>
        <div class="sd-block"><small>LETZTE AUFGABE</small><b>${esc(letzte && letzte.title ? letzte.title : 'Keine Aufgabe')}</b><p>${esc(letzte && letzte.state_text ? letzte.state_text : '–')}</p></div>
        <div class="sd-block"><small>BERICHTET AN</small><b>${esc(a.reports_to || '–')}</b><p>Autonomie ${esc(a.autonomy ?? '–')} · Abteilung ${esc(a.dept)}</p></div>
        ${shipKommunikationHtml(a)}`;
      bindeShipKommunikation(side, a);
      return;
    }
    shipAuswahl = { typ:'overview' };
  }

  side.innerHTML = `<span class="sd-kicker">SCHIFFSLAGE</span><h2>${agenten.length} Agenten an Bord</h2>
    <p>${depts.length} Abteilungen. Ein Raum öffnet rechts Rolle, Status und Aufgabe.</p>
    <div class="sd-kpis"><div class="sd-kpi"><small>AKTIV</small><b>${Number(s.aktiv)||0}</b></div>
      <div class="sd-kpi"><small>BLOCKIERT</small><b>${Number(s.blockiert)||0}</b></div><div class="sd-kpi"><small>OFFEN</small><b>${Number(aufgaben.offen)||0}</b></div></div>
    <div class="sd-block"><small>BEDIENUNG</small><b>Raum antippen</b><p>Ziehen verschiebt das Schiff. Mit +/−, Mausrad oder zwei Fingern zoomen; «Fit» zeigt alles.</p></div>
    <div class="sd-block"><small>COMMON ROOMS</small><p>Agentenraum und Konferenz liegen als eigene Räume oben im Querschnitt.</p></div>`;
}

function applyShipTransform(){
  const vp = $('#shipViewport'), w = $('#shipWorld');
  if(!w) return;
  /* Mindestens 72 px des Schiffs bleiben an jedem Rand sichtbar; gilt für
     Ziehen, Pinch, Mausrad, +/− und Fit, weil alle über diese Funktion laufen. */
  if(vp && vp.clientWidth && w.offsetWidth){
    const breite = w.offsetWidth * shipZoom, hoehe = w.offsetHeight * shipZoom;
    shipX = Math.max(72 - breite, Math.min(vp.clientWidth - 72, shipX));
    shipY = Math.max(72 - hoehe, Math.min(vp.clientHeight - 72, shipY));
  }
  w.style.transform = `translate(${shipX}px, ${shipY}px) scale(${shipZoom})`;
  const z = $('#shipZoomWert'); if(z) z.textContent = `${Math.round(shipZoom * 100)} %`;
}

function fitShip(){
  const vp = $('#shipViewport'), w = $('#shipWorld');
  if(!vp || !w || !vp.clientWidth || !w.offsetWidth) return;
  if(!w.querySelector('.px-room')) return;
  const faktor = Math.min((vp.clientWidth - 18) / w.offsetWidth, (vp.clientHeight - 18) / w.offsetHeight, 1);
  /* Bei 240 px ist der feste Mindestzoom 0,16 breiter als der Viewport.
     Dort darf der Fit-Zoom bis auf den tatsächlichen Faktor sinken. */
  const mindestZoom = vp.clientWidth <= 260 ? 0.1 : 0.16;
  shipZoom = Math.max(mindestZoom, Math.min(2.5, faktor));
  shipX = (vp.clientWidth - w.offsetWidth * shipZoom) / 2;
  shipY = (vp.clientHeight - w.offsetHeight * shipZoom) / 2;
  shipZoomInit = true;
  applyShipTransform();
}

function zoomShip(faktor){
  const vp = $('#shipViewport');
  if(!vp) return;
  const alt = shipZoom;
  const neu = Math.max(0.22, Math.min(2.5, shipZoom * faktor));
  if(neu === alt) return;
  const mx = vp.clientWidth / 2, my = vp.clientHeight / 2;
  shipX = mx - (mx - shipX) * (neu / alt);
  shipY = my - (my - shipY) * (neu / alt);
  shipZoom = neu;
  applyShipTransform();
}

function initShipControls(){
  const vp = $('#shipViewport');
  if(!vp) return;
  vp.querySelectorAll('[data-ship-zoom]').forEach(b => b.onclick = () => {
    if(b.dataset.shipZoom === 'in') zoomShip(1.18);
    else if(b.dataset.shipZoom === 'out') zoomShip(0.85);
    else fitShip();
  });
  vp.addEventListener('wheel', e => {
    if(e.target.closest('.ship-zoom')) return;
    e.preventDefault();
    zoomShip(e.deltaY < 0 ? 1.12 : 0.89);
  }, { passive:false });

  // Maus und Touch teilen sich denselben Pointerpfad. Ein zweiter Finger
  // zoomt um den Berührungsmittelpunkt; ein einzelner Finger verschiebt.
  const zeiger = new Map();
  let drag = null, pinch = null, klickGesperrt = false, sperrTimer = null;
  const abstand = (a,b) => Math.hypot(a.x-b.x, a.y-b.y);
  const sperreKlick = () => {
    klickGesperrt = true;
    clearTimeout(sperrTimer);
    sperrTimer = setTimeout(() => { klickGesperrt = false; }, 400);
  };
  const startePinch = () => {
    if(zeiger.size < 2) return;
    const [a,b] = [...zeiger.values()];
    const mx = (a.x+b.x)/2, my = (a.y+b.y)/2;
    pinch = {
      abstand: Math.max(1, abstand(a,b)),
      zoom: shipZoom,
      mx, my,
      wx: (mx - shipX) / shipZoom,
      wy: (my - shipY) / shipZoom,
    };
    drag = null;
  };
  vp.addEventListener('click', e => {
    if(!klickGesperrt) return;
    e.preventDefault();
    e.stopPropagation();
    klickGesperrt = false;
    clearTimeout(sperrTimer);
  }, true);

  vp.addEventListener('pointerdown', e => {
    klickGesperrt = false;
    clearTimeout(sperrTimer);
    if(e.target.closest('.ship-zoom')) return;
    if(e.pointerType === 'mouse' && e.button !== 0) return;
    zeiger.set(e.pointerId, { x:e.clientX, y:e.clientY });
    try { vp.setPointerCapture(e.pointerId); } catch {}
    if(zeiger.size === 1){
      drag = { x:e.clientX, y:e.clientY, sx:shipX, sy:shipY, bewegt:false };
      pinch = null;
    }else if(zeiger.size === 2){
      startePinch();
      sperreKlick();
    }
  }, { passive:true });

  vp.addEventListener('pointermove', e => {
    if(!zeiger.has(e.pointerId)) return;
    zeiger.set(e.pointerId, { x:e.clientX, y:e.clientY });
    if(pinch && zeiger.size >= 2){
      const [a,b] = [...zeiger.values()];
      const faktor = Math.max(1, abstand(a,b)) / pinch.abstand;
      const neu = Math.max(0.22, Math.min(2.5, pinch.zoom * faktor));
      const mx = (a.x+b.x)/2, my = (a.y+b.y)/2;
      shipZoom = neu;
      shipX = mx - pinch.wx * neu;
      shipY = my - pinch.wy * neu;
      applyShipTransform();
      sperreKlick();
      e.preventDefault();
      return;
    }
    if(!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if(!drag.bewegt && Math.hypot(dx,dy) > 8){
      drag.bewegt = true;
      sperreKlick();
    }
    if(!drag.bewegt) return;
    shipX = drag.sx + dx;
    shipY = drag.sy + dy;
    applyShipTransform();
    e.preventDefault();
  }, { passive:false });

  const beenden = e => {
    const warDrag = !!(drag && drag.bewegt);
    // Pointer-Capture leitet den Klick auf den Viewport um. Für einen echten
    // Mausklick ohne Ziehen wählen wir deshalb den Raum unter dem Zeiger.
    if(e.type === 'pointerup' && e.pointerType === 'mouse' && !warDrag){
      const ziel = document.elementFromPoint(e.clientX, e.clientY)
        ?.closest('#shipWorld [data-agent], #shipWorld [data-common]');
      if(ziel){
        sperreKlick();
        if(ziel.dataset.agent) setShipSelection('agent', ziel.dataset.agent);
        else setShipSelection(ziel.dataset.common);
      }
    }
    zeiger.delete(e.pointerId);
    if(zeiger.size < 2) pinch = null;
    if(zeiger.size === 1){
      const p = [...zeiger.values()][0];
      drag = { x:p.x, y:p.y, sx:shipX, sy:shipY, bewegt:false };
    }else if(zeiger.size === 0){
      drag = null;
    }
  };
  vp.addEventListener('pointerup', beenden);
  vp.addEventListener('pointercancel', beenden);
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      const bereich = $('#v-ship');
      syncShipLegend();
      if(shipGrossAktiv() !== shipGrossGerendert){
        shipZoomInit = false;
        renderShipWorld();
        return;
      }
      if(bereich && !bereich.hidden) fitShip();
    }, 160);
  });
}

initShipControls();

export function shipAktiviere(){
  if(!companyTimer){ ladeCompany(); companyTimer = setInterval(ladeCompany, 30000); }
}

export function shipDeaktiviere(){
  if(companyTimer){ clearInterval(companyTimer); companyTimer = null; }
}

export { ladeCompany, renderShip };
