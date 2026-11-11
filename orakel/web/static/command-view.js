/* Command Center — eigenständige Dashboard-Ansicht (#v-command).
 *
 * Die Ansicht liegt bewusst neben app.js: app.js bleibt unverändert, dieses
 * Modul verdrahtet Navigation, Daten und die 3D-Brücke. Alle Werte stammen aus
 * /api/report und /api/betrieb; fehlt eine Grundlage, steht «KEINE DATEN» im
 * Panel. Die Szene ist Darstellung, keine Datenquelle und keine Automation.
 */
(() => {
  const $ = s => document.querySelector(s);
  const DEP = {
    A: 'Hauptzentrale',
    B: 'Spider Intelligence',
    C: 'Labor',
    D: 'Trading Floor',
    E: 'Forschungsabteilung',
    F: 'Risikomanagement',
    G: 'Wissenszentrum',
    H: 'Entwicklungsabteilung',
  };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num = (v, d = 2) => (v == null || isNaN(v)) ? '–'
    : Number(v).toLocaleString('de-CH', {minimumFractionDigits: d, maximumFractionDigits: d});

  let report = null, betrieb = null, betriebFehler = null;
  let deck = null, deckFehler = null, deckLaden = null;
  let aktiv = false, gesperrtWar = false;
  let timerReport = null, timerBetrieb = null;

  const zeit = wert => wert ? esc(String(wert).replace('T', ' ').slice(0, 16)) : 'KEINE DATEN';

  function statusKlasse(status){
    if(status === 'laeuft') return 'up';
    if(status === 'ueberfaellig' || status === 'fehler') return 'dn';
    if(status === 'aus') return 'na';
    return '';
  }

  async function ladeReport(){
    if(!$('#commandKpis')) return;
    try{
      const r = await fetch('/api/report', {cache: 'no-store'});
      if(!r.ok) throw new Error('HTTP ' + r.status);
      report = await r.json();
    }catch(e){
      report = null;
    }
    zeichne();
  }

  async function ladeBetrieb(){
    if(!$('#commandKpis')) return;
    try{
      const r = await fetch('/api/betrieb', {cache: 'no-store'});
      if(!r.ok) throw new Error('HTTP ' + r.status);
      const d = await r.json();
      if(!d || typeof d !== 'object' || !d.takt) throw new Error('Ungültige Antwort');
      betrieb = d;
      betriebFehler = null;
    }catch(e){
      betrieb = null;
      betriebFehler = String(e.message || e);
    }
    zeichne();
  }

  function zeichne(){
    if(!$('#commandKpis')) return;
    const runs = Array.isArray(report?.agenten) ? report.agenten : [];
    const proAbteilung = {};
    runs.forEach(r => { (proAbteilung[r.abteilung] = proAbteilung[r.abteilung] || []).push(r); });
    const d = betrieb;
    const takt = d?.takt || {};
    const jobs = Array.isArray(d?.jobs) ? d.jobs : [];
    const res = d?.ressourcen || {};
    const stat = d?.statistik || {};
    const okJobs = jobs.filter(j => j.letzter_status === 'ok' || j.zustand === 'ok').length;
    const befund = runs.filter(r => r.ok === false).length;
    const status = betriebFehler ? 'NICHT ERREICHBAR' : (takt.status ? takt.status.toUpperCase() : 'KEINE DATEN');
    const klasse = betriebFehler ? 'dn' : statusKlasse(takt.status);
    const taktLaeuft = !betriebFehler && takt.status === 'laeuft';

    const mode = $('#commandMode');
    if(mode) mode.innerHTML = `<span class="g-live-dot ${taktLaeuft ? '' : 'is-off'}"></span><span><b>${esc(status)}</b><small>${betriebFehler ? 'API /api/betrieb nicht erreichbar' : takt.letzter ? 'zuletzt ' + zeit(takt.letzter) : 'keine Taktzeit'}</small></span>`;
    const tag = $('#commandTag');
    if(tag) tag.textContent = `${runs.length ? num(runs.length, 0) + ' Läufe' : 'KEINE DATEN'} · ${Object.keys(proAbteilung).filter(k => proAbteilung[k].length).length || '–'} Abteilungen`;

    const hudStatus = $('#commandHudStatus');
    if(hudStatus){ hudStatus.textContent = status; hudStatus.className = 'command-hud-status ' + klasse; }
    const hudDetail = $('#commandHudDetail');
    if(hudDetail) hudDetail.textContent = betriebFehler ? betriebFehler : takt.letzter ? 'LETZTER TAKT ' + zeit(takt.letzter) : 'LETZTER TAKT KEINE DATEN';
    const hudTakt = $('#commandHudTakt');
    if(hudTakt) hudTakt.textContent = takt.status ? takt.status.toUpperCase() : '–';
    const hudAgenten = $('#commandHudAgenten');
    if(hudAgenten) hudAgenten.textContent = runs.length ? num(runs.length, 0) : 'KEINE DATEN';
    const hudDb = $('#commandHudDb');
    if(hudDb) hudDb.textContent = res.db_mb == null ? '–' : num(res.db_mb, 1) + ' MB';

    const kpis = [
      ['Takt', `<span class="${klasse}">${esc(status)}</span>`, betriebFehler ? 'API /api/betrieb nicht erreichbar' : takt.letzter ? 'zuletzt ' + zeit(takt.letzter) : 'keine Taktzeit'],
      ['Jobs', jobs.length ? `${num(okJobs, 0)} / ${num(jobs.length, 0)}` : 'KEINE DATEN', d ? `${num(stat.gesamt, 0)} Läufe in 24 h` : 'API nicht geladen'],
      ['Datenbank', res.db_mb == null ? 'KEINE DATEN' : `${num(res.db_mb, 1)} MB`, res.rss_mb == null ? 'RSS nicht messbar' : `RSS ${num(res.rss_mb, 1)} MB`],
      ['Agentenläufe', runs.length ? num(runs.length, 0) : 'KEINE DATEN', `${num(befund, 0)} Befunde`],
    ];
    $('#commandKpis').innerHTML = kpis.map(q => `<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('')
      + (betriebFehler ? `<div class="command-load-error">Betriebsdaten fehlen: ${esc(betriebFehler)}</div>` : '');

    $('#commandDepts').innerHTML = Object.entries(DEP).map(([k, n]) => {
      const liste = proAbteilung[k] || [];
      const f = liste.filter(r => r.ok === false).length;
      return `<div class="command-dept">
        <span class="command-dept-key">${k}</span>
        <span class="command-dept-name"><b>${esc(n)}</b><small>${liste.length ? `${num(liste.length, 0)} Läufe` : 'KEINE DATEN'}</small></span>
        <span class="command-dept-state ${f ? 'warn' : liste.length ? 'ok' : 'off'}">${f ? `${num(f, 0)} BEFUND` : liste.length ? 'OK' : '–'}</span>
      </div>`;
    }).join('');

    const letzte = runs.slice().sort((a, b) => String(b.zeit || '').localeCompare(String(a.zeit || ''))).slice(0, 6);
    $('#commandActivity').innerHTML = letzte.length ? letzte.map(r => `<div class="command-activity-row">
      <span class="command-activity-dot ${r.ok ? 'ok' : 'warn'}"></span>
      <span><b>${esc(r.aufgabe || '–')}</b><small>${esc((r.agent || '').split(':')[1] || r.agent || '–')} · ${zeit(r.zeit)}</small></span>
    </div>`).join('') : '<div class="command-empty">Keine Agentenläufe im Report.</div>';

    const quellen = [
      {ok: Boolean(report), text: 'GET /api/report' + (report?.erstellt ? ' · ' + zeit(report.erstellt) : ' · keine Antwort')},
      {ok: Boolean(d) && !betriebFehler, text: 'GET /api/betrieb' + (d && !betriebFehler ? ' · verbunden' : ' · keine Antwort')},
      {ok: Boolean(deck), text: 'THREE.JS / WEBGL' + (deckFehler ? ' · nicht verfügbar' : deck ? ' · aktiv' : ' · wird geladen')},
    ];
    $('#commandSources').innerHTML = quellen.map(q => `<div class="command-source"><span class="command-source-dot ${q.ok ? 'ok' : 'off'}"></span><span>${q.text}</span></div>`).join('');

    if(deck) deck.update(report, betrieb);
  }

  function deckHolen(){
    if(deck) return Promise.resolve(deck);
    if(deckFehler) return Promise.resolve(null);
    if(deckLaden) return deckLaden;
    const stage = $('#commandStage');
    if(!stage) return Promise.resolve(null);
    deckLaden = import('/static/command3d.js?v=3')
      .then(mod => {
        deck = new mod.CommandDeck(stage);
        deck.update(report, betrieb);
        deck.setActive(aktiv);
        if(!$('#commandMap')?.hidden) karteZeichnen();
        return deck;
      })
      .catch(e => {
        deckFehler = '3D-Ansicht nicht verfügbar: ' + (e.message || e);
        deck = null;
        const overlay = $('#commandOverlay');
        if(overlay){
          overlay.hidden = false;
          const text = $('#commandOverlayText');
          if(text) text.textContent = deckFehler + ' Die Daten bleiben in der Seitenleiste sichtbar.';
        }
        const btn = $('#commandEnter');
        if(btn) btn.disabled = true;
        const btn2 = $('#commandEnterOverlay');
        if(btn2) btn2.disabled = true;
        zeichne();
        return null;
      })
      .finally(() => { deckLaden = null; });
    return deckLaden;
  }

  function betreten(){
    deckHolen().then(d => { if(d) d.enter(); });
  }

  function karteOeffnen(){
    const map = $('#commandMap');
    if(!map || !map.hidden) return;
    if(document.pointerLockElement === $('#commandCanvas')) document.exitPointerLock();
    map.hidden = false;
    const btn = $('#commandMapBtn');
    if(btn){ btn.textContent = 'Karte schliessen'; btn.setAttribute('aria-expanded', 'true'); }
    const plan = $('#commandMapPlan');
    if(deckFehler){
      if(plan) plan.innerHTML = '<div class="command-map-loading">3D-Ansicht nicht verfügbar.</div>';
    }else{
      if(plan) plan.innerHTML = '<div class="command-map-loading">Deckskarte wird geladen.</div>';
      deckHolen().then(d => { if(d && !$('#commandMap')?.hidden) karteZeichnen(); });
    }
    requestAnimationFrame(() => $('#commandMapClose')?.focus());
  }

  function karteSchliessen(){
    const map = $('#commandMap');
    if(!map || map.hidden) return;
    map.hidden = true;
    const btn = $('#commandMapBtn');
    if(btn){ btn.textContent = 'Deckskarte'; btn.setAttribute('aria-expanded', 'false'); }
  }

  function karteToggle(){
    const map = $('#commandMap');
    if(map && !map.hidden) karteSchliessen();
    else karteOeffnen();
  }

  function karteZeichnen(){
    const plan = $('#commandMapPlan');
    if(!plan || !deck) return;
    const stationen = deck.stationen || {};
    if(!Object.keys(stationen).length){
      plan.innerHTML = '<div class="command-map-loading">Noch keine Stationsdaten.</div>';
      return;
    }
    const knoten = Object.entries(DEP).map(([k, n]) => {
      const p = stationen[k];
      if(!p) return '';
      const links = 50 + (p.x / 11) * 40;
      const oben = 50 + (p.z / 7) * 40;
      const hier = deck.standort === k;
      return `<button type="button" class="command-map-node${hier ? ' is-current' : ''}" data-map-station="${k}" style="--map-x:${links.toFixed(2)}%;--map-y:${oben.toFixed(2)}%" aria-label="${esc(n)} anwählen"${hier ? ' aria-current="true"' : ''}>
        <b>${k}</b><span>${esc(n)}</span>
      </button>`;
    }).join('');
    plan.innerHTML = `<div class="command-map-deck"><span>E6</span><small>MAIN COMMAND CENTER</small></div>
      <div class="command-map-core" aria-hidden="true"><b>CORE</b><small>Hologramm</small></div>${knoten}`;
    plan.querySelectorAll('[data-map-station]').forEach(btn => {
      btn.onclick = () => reise(btn.dataset.mapStation);
    });
  }

  function reise(key){
    if(!DEP[key]) return;
    const fahren = (d, direkt) => {
      if(!d || !d.reiseZu(key)) return;
      karteSchliessen();
      if(direkt) d.enter();
    };
    if(deck) fahren(deck, true);
    else deckHolen().then(d => fahren(d, false));
  }

  function aktiviere(){
    if(aktiv) return;
    aktiv = true;
    ladeReport();
    ladeBetrieb();
    if(!timerReport) timerReport = setInterval(ladeReport, 8000);
    if(!timerBetrieb) timerBetrieb = setInterval(ladeBetrieb, 30000);
    deckHolen().then(d => { if(d) d.setActive(true); });
  }

  function deaktiviere(){
    if(!aktiv) return;
    aktiv = false;
    karteSchliessen();
    if(timerReport){ clearInterval(timerReport); timerReport = null; }
    if(timerBetrieb){ clearInterval(timerBetrieb); timerBetrieb = null; }
    if(deck) deck.setActive(false);
  }

  const sichtbar = () => { const v = $('#v-command'); return v ? !v.hidden : false; };

  document.querySelectorAll('.nav').forEach(btn => {
    btn.addEventListener('click', () => {
      if(btn.dataset.v === 'command') aktiviere();
      else deaktiviere();
    });
  });

  const eintreten = $('#commandEnter');
  if(eintreten) eintreten.onclick = () => {
    if(document.pointerLockElement === $('#commandCanvas')) document.exitPointerLock();
    else betreten();
  };
  const eintretenOverlay = $('#commandEnterOverlay');
  if(eintretenOverlay) eintretenOverlay.onclick = () => {
    if(document.pointerLockElement === $('#commandCanvas')) document.exitPointerLock();
    else betreten();
  };
  const zuruecksetzen = $('#commandReset');
  if(zuruecksetzen) zuruecksetzen.onclick = () => deckHolen().then(d => { if(d) d.reset(); });
  const karteBtn = $('#commandMapBtn');
  if(karteBtn) karteBtn.onclick = karteToggle;
  const karteZu = $('#commandMapClose');
  if(karteZu) karteZu.onclick = karteSchliessen;

  document.addEventListener('keydown', event => {
    if(!sichtbar() || event.repeat) return;
    if(event.code === 'KeyM'){
      event.preventDefault();
      karteToggle();
    }else if(event.code === 'Escape' && !$('#commandMap')?.hidden){
      event.preventDefault();
      karteSchliessen();
    }
  });

  const stage = $('#commandStage');
  if(stage) stage.addEventListener('commandmode', event => {
    const detail = event.detail || {};
    const overlay = $('#commandOverlay');
    if(!overlay) return;
    if(deckFehler){ overlay.hidden = false; return; }
    const warGesperrt = gesperrtWar;
    gesperrtWar = Boolean(detail.locked);
    overlay.hidden = Boolean(detail.locked);
    const text = $('#commandOverlayText');
    if(text){
      if(detail.fehler){
        text.textContent = detail.fehler + ' Klicken, um es erneut zu versuchen.';
      }else if(warGesperrt && !detail.locked){
        text.textContent = 'Mauszeiger frei. Klicken, um die Brücke weiter zu begehen; ESC gibt ihn wieder frei.';
      }else if(detail.active && !detail.locked){
        text.textContent = 'Klicken, um den Raum zu betreten. WASD zum Gehen, Maus zum Umsehen, ESC zum Verlassen.';
      }
    }
    const btn = $('#commandEnter');
    if(btn) btn.textContent = detail.locked ? 'Mauszeiger freigeben' : 'Betreten';
  });

  if(sichtbar()) aktiviere();
})();
