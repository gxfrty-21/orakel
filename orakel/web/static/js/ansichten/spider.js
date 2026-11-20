/* Spider: Quellen, Claims, Nachtbetrieb, Graph und Kalibrierung. */
import { R, lade } from '../kern/daten.js';
import { $, esc, kurzZeit, num, pct } from '../kern/helfer.js';

let nachtDaten = null, nachtFehler = null;
let graphWindow = '7d', graphDaten = null, kalibrierungDaten = null;

async function ladeNacht(){
  if(!$('#nachtKpis')) return;
  try {
    const r = await fetch('/api/nexus/status', {cache:'no-store'});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    nachtDaten = await r.json();
    nachtFehler = null;
  } catch(e) {
    nachtDaten = null;
    nachtFehler = String(e.message || e);
  }
  zeichneNacht();
  zeichneBewertung(nachtDaten);
  zeichneMissionen(nachtDaten);
}

const zeitKurz = s => esc(String(s || '').replace('T',' ').slice(0,16)) || '–';

const groesse = b => b == null ? '–' : (Number(b) >= 1048576
  ? num(Number(b)/1048576,2) + ' MB' : num(Number(b)/1024,0) + ' KB');

function zeichneNacht(){
  if(!$('#nachtKpis')) return;
  if(nachtFehler){
    $('#nachtTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    $('#nachtKpis').innerHTML = '';
    $('#nachtDetail').innerHTML = `<div class="nacht-status">Status nicht geladen: ${esc(nachtFehler)}.</div>`;
    return;
  }
  const n = nachtDaten?.nacht;
  if(!n){
    $('#nachtTag').textContent = 'kein Lauf';
    $('#nachtKpis').innerHTML = '';
    $('#nachtDetail').innerHTML = '<div class="nacht-status">Noch kein Nachtlauf gespeichert. Einrichtung: <span class="code">docs/spider/NACHTBETRIEB.md</span></div>';
    return;
  }
  const ok = n.ok === true;
  const b = n.backup || {};
  $('#nachtTag').innerHTML = ok ? '<span class="up">OK</span>' : '<span class="dn">WARNUNG</span>';
  const kp = [
    ['Status', ok ? '<span class="up">OK</span>' : '<span class="dn">Warnung</span>', 'Lauf ' + zeitKurz(n.zeit)],
    ['Quellen', num(n.faellig,0), `${num(n.abgerufen,0)} abgerufen · ${num(n.unveraendert,0)} unverändert`],
    ['Meldungen', num(n.meldungen,0), `${num(n.gespeichert,0)} gespeichert · ${num(n.dubletten,0)} Kopien · ${num(n.fehler,0)} Fehler`],
    ['Backup', b.erstellt ? zeitKurz(b.erstellt) : '–', b.integrity ? `Integrität ${esc(b.integrity)} · ${groesse(b.bytes)}` : 'kein Backup'],
  ];
  $('#nachtKpis').innerHTML = kp.map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const teile = [];
  if(ok){
    teile.push('<span class="pill">OK</span> Alle fälligen Quellen ohne Fehler.');
  } else {
    const w = n.warnung || {};
    teile.push('<span class="pill r">WARNUNG</span>');
    if(w.gesendet) teile.push('Warnung gesendet.');
    else if(w.grund) teile.push('Nicht gesendet: ' + esc(w.grund) + '.');
    else if(w.fehler) teile.push('Nicht gesendet: ' + esc(w.fehler) + '.');
  }
  if(n.ping) teile.push(n.ping.gesendet ? 'Ping gesendet.' : 'Ping nicht gesendet' + (n.ping.fehler ? ' (' + esc(n.ping.fehler) + ')' : '') + '.');
  if(b.pfad) teile.push(`Backup: <span class="code">${esc(String(b.pfad).split('/').pop())}</span>`);
  if(b.entfernt?.length) teile.push(`${b.entfernt.length} alte Backups entfernt.`);
  if(n.domain) teile.push(`Domain: ${n.domain.ok ? 'ok' : esc(n.domain.fehler || 'Fehler')}${n.domain.tage_rest != null ? ' · Zertifikat ' + num(n.domain.tage_rest,0) + ' Tage' : ''}.`);
  if(n.bewertung?.fehler) teile.push(`<span class="pill r">Bewertung</span> ${esc(n.bewertung.fehler)}.`);
  else if(n.bewertung) teile.push(`Kernaussagen: ${num(n.bewertung.kernaussagen,0)} · Widersprüche: ${num(n.bewertung.widersprueche,0)}.`);
  $('#nachtDetail').innerHTML = `<div class="nacht-status">${teile.join(' ')}</div>`;
}

function widerspruchsVergleich(w){
  if(w?.wert_a_bp == null || w?.wert_b_bp == null) return '';
  return `<span class="claimWiderspruchWerte">Vergleich: ${num(w.wert_a_bp,2)} bp <span aria-hidden="true">↔</span> ${num(w.wert_b_bp,2)} bp</span>`;
}

function zeichneBewertung(d){
  if(!$('#bewertungKpis')) return;
  const c = d?.claims?.statistik || {};
  const top = d?.claims?.top || [];
  const wid = d?.claims?.widersprueche || [];
  const widJeClaim = new Map();
  for(const w of wid){
    const id = Number(w.claim_id);
    if(!widJeClaim.has(id)) widJeClaim.set(id, []);
    widJeClaim.get(id).push(w);
  }
  const reps = d?.reputation || [];
  const ns = c.nach_status || {};
  $('#bewertungTag').textContent = `${num(c.gesamt,0)} Kernaussagen`;
  $('#bewertungKpis').innerHTML = [
    ['Kernaussagen', num(c.gesamt,0), `${num(c.belege,0)} Belege`],
    ['Bestätigt', num(ns['bestätigt'],0), '≥ 2 unabhängige Quellen'],
    ['Teilweise', num(ns['teilweise'],0), 'nur eine Quelle oder wenig Belege'],
    ['Widersprüchlich', num(c.widersprueche,0), 'erkannte Konflikte'],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const pill = s => s==='bestätigt' ? 'g' : (s==='widersprüchlich' ? 'r' : (s==='teilweise' ? 'w' : ''));
  $('#bewertungClaims').innerHTML = top.length ? top.map(k=>`
    <div class="li"><span><b style="font-weight:400">${esc(k.kernaussage)}</b>
      <small>${esc(k.thema)} · ${num(k.quellen,0)} Quellen · ${num(k.belege,0)} Belege</small>
      <small class="claimMeta"><span>Zeitraum: ${esc(k.zeitraum || '–')}</span><span>Bedingung: ${esc(k.bedingung || '–')}</span><span>Extraktionssicherheit: ${num(k.sicherheit,2)}</span></small>${(widJeClaim.get(Number(k.id)) || []).map(w=>`<small class="claimWiderspruch"><span class="pill r">Widerspruch</span><span class="claimWiderspruchGrund">${esc(w.grund)}</span><span class="claimWiderspruchSicherheit">Widerspruchssicherheit: ${num(w.sicherheit,2)}</span>${widerspruchsVergleich(w)}<span class="claimWiderspruchQuellen">Quellen: <span class="claimWiderspruchQuelle">${esc(w.quelle_a || '–')}</span><span class="claimWiderspruchPfeil" aria-hidden="true">↔</span><span class="claimWiderspruchQuelle">${esc(w.quelle_b || '–')}</span></span></small>`).join('')}</span>
      <span class="pill ${pill(k.status)}">${num(k.bestaetigungsgrad,2)}</span></div>`).join('')
    + (wid.length ? `<div class="nacht-status"><span class="pill r">Widerspruch</span> ${esc(wid[0].grund)} <span>Widerspruchssicherheit: ${num(wid[0].sicherheit,2)}</span> <span class="code">${esc(wid[0].quelle_a)} ↔ ${esc(wid[0].quelle_b)}</span></div>` : '')
    : '<div class="empty">Noch keine Kernaussage. Der Nachtlauf bewertet Titel mit prüfbaren Zahlen, Richtungen oder Verneinungen.</div>';

  $('#bewertungQuellen').innerHTML = reps.length ? `<table class="tbl"><thead><tr><th>Quelle</th><th class="m">Reputation</th><th class="m">belegt</th><th class="m">verworfen</th></tr></thead><tbody>
    ${reps.map(q=>`<tr><td>${esc(q.name)}<small>${esc(q.vertrauen)}</small></td><td class="m">${num(q.reputation,2)}</td>
    <td class="m up">${num(q.bestaetigt,0)}</td><td class="m dn">${num(q.widerlegt,0)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Noch keine Quellenreputation.</div>';
}

function zeichneMissionen(d){
  if(!$('#missionKpis')) return;
  if(!d){
    $('#missionTag').textContent = 'nicht erreichbar';
    $('#missionKpis').innerHTML = '';
    $('#missionList').innerHTML = '<div class="empty">Status nicht geladen.</div>';
    return;
  }
  const st = d?.missionen?.statistik || {};
  const liste = d?.missionen?.liste || [];
  const ns = st.nach_status || {};
  $('#missionTag').textContent = `${num(st.gesamt,0)} Missionen`;
  $('#missionKpis').innerHTML = [
    ['Missionen', num(st.gesamt,0), `${num(st.tasks?.erledigt,0)} Aufgaben erledigt`],
    ['Offen / laufend', num((ns.offen ?? 0) + (ns.laufend ?? 0),0), `${num(ns.laufend ?? 0,0)} laufend`],
    ['Abgeschlossen', num(ns.abgeschlossen,0), 'mit Bericht'],
    ['Fortschritt', `${num(st.fortschritt,0)} %`, 'Durchschnitt aller Missionen'],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const pill = s => s==='abgeschlossen' ? 'g' : (s==='fehlgeschlagen' ? 'r' : (s==='laufend' ? 'b' : 'w'));
  $('#missionList').innerHTML = liste.length ? liste.map(m=>{
    const p = Math.max(0, Math.min(100, Number(m.fortschritt)||0));
    const datum = String(m.erstellt || '').replace('T',' ').slice(0,16);
    return `<div class="li mission" data-kennung="${esc(m.kennung)}">
      <div class="wlTop"><span><b style="font-weight:400">${esc(m.titel)}</b>
        <small>${esc(m.kennung)} · ${esc(m.prioritaet)} · ${datum}</small></span>
        <span class="pill ${pill(m.status)}">${esc(m.status)}</span></div>
      <div class="mission-bar"><i style="width:${p}%"></i></div>
      <div class="mission-meta"><small>${num(m.erledigt,0)} / ${num(m.tasks,0)} Aufgaben${m.fehlgeschlagen ? ' · ' + num(m.fehlgeschlagen,0) + ' fehlgeschlagen' : ''}</small>
        <span class="mission-actions">
          ${m.status !== 'abgeschlossen' ? `<button class="toggle" data-mission-lauf="1">Weiterarbeiten</button>` : ''}
          ${m.bericht_vorhanden ? `<button class="toggle" data-mission-bericht="1" aria-expanded="false">Bericht</button>` : ''}
        </span></div>
      <pre class="mission-report" hidden></pre>
    </div>`;
  }).join('') : '<div class="empty">Noch keine Mission. Eine Mission prüft gespeicherte Kernaussagen und schreibt einen Bericht mit offenen Fragen.</div>';
}

const phase6Fehler = text => {
  $('#banner').className = 'banner b-sim';
  $('#banner').innerHTML = '<b>FEHLER</b>' + esc(text);
};

async function ladeGraph(){
  if(!$('#graphNodes')) return;
  try {
    const r = await fetch('/api/nexus/graph?zeitraum=' + encodeURIComponent(graphWindow), {cache:'no-store'});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Graph konnte nicht geladen werden');
    graphDaten = d;
    zeichneGraph();
  } catch(e) {
    graphDaten = null;
    if($('#graphTag')) $('#graphTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    if($('#graphKpis')) $('#graphKpis').innerHTML = '';
    if($('#graphNodes')) $('#graphNodes').innerHTML = `<div class="empty">Graph nicht geladen: ${esc(e.message)}</div>`;
    if($('#graphEdges')) $('#graphEdges').innerHTML = '';
  }
}

function zeichneGraph(){
  const d = graphDaten;
  if(!d || !$('#graphNodes')) return;
  const st = d.statistik || {}, typen = st.typen || {};
  const knoten = d.knoten || [], kanten = d.kanten || [];
  $('#graphTag').textContent = `${num(st.knoten,0)} Knoten · ${num(st.kanten,0)} Kanten`;
  $('#graphKpis').innerHTML = [
    ['Knoten', num(st.knoten,0), `${num(typen.claim,0)} Kernaussagen`],
    ['Kanten', num(st.kanten,0), `${num(typen.quelle,0)} Quellen · ${num(typen.thema,0)} Themen`],
    ['Zeitraum', d.zeitraum || graphWindow, 'aus gespeicherten Zeitstempeln'],
    ['Beziehungen', `${num((st.arten||{}).belegt_durch,0)} Belege`, `${num((st.arten||{}).widerspruch,0)} Widersprüche`],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const typName = {claim:'Kernaussage', quelle:'Quelle', thema:'Thema'};
  $('#graphNodes').innerHTML = knoten.length ? knoten.map(n=>`
    <div class="li"><span><b style="font-weight:400">${esc(n.label)}</b>
      <small>${esc(typName[n.typ] || n.typ)}${n.status ? ' · ' + esc(n.status) : ''}</small></span>
      <span class="pill ${n.typ==='claim'?'b':n.typ==='thema'?'w':'g'}">${esc(n.typ)}</span></div>`).join('')
    : `<div class="empty">${esc(d.hinweis || 'Noch keine Knoten.')}</div>`;
  const label = id => (knoten.find(n=>n.id===id) || {}).label || id;
  $('#graphEdges').innerHTML = kanten.length ? `<table class="tbl"><thead><tr><th>Von</th><th>Nach</th><th>Art</th><th class="m">Sicherheit</th></tr></thead><tbody>
    ${kanten.map(k=>`<tr><td style="white-space:normal">${esc(label(k.von))}</td><td style="white-space:normal">${esc(label(k.nach))}</td>
      <td>${esc(k.art)}</td><td class="m">${num(k.sicherheit,2)}</td></tr>`).join('')}</tbody></table>`
    : (knoten.length ? `<div class="empty">${esc(d.hinweis || 'Noch keine Kanten.')}</div>` : '');
}

async function ladeKalibrierung(){
  if(!$('#kalibrierungList')) return;
  try {
    const r = await fetch('/api/nexus/kalibrierung', {cache:'no-store'});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Kalibrierung konnte nicht geladen werden');
    kalibrierungDaten = d;
    zeichneKalibrierung();
  } catch(e) {
    kalibrierungDaten = null;
    if($('#kalibrierungTag')) $('#kalibrierungTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    if($('#kalibrierungKpis')) $('#kalibrierungKpis').innerHTML = '';
    if($('#kalibrierungList')) $('#kalibrierungList').innerHTML = `<div class="empty">Kalibrierung nicht geladen: ${esc(e.message)}</div>`;
    if($('#kalibrierungKlassen')) $('#kalibrierungKlassen').innerHTML = '';
    if($('#kalibrierungHinweis')) $('#kalibrierungHinweis').textContent = '';
  }
}

function zeichneKalibrierung(){
  const d = kalibrierungDaten;
  if(!d || !$('#kalibrierungList')) return;
  const quote = d.trefferquote == null ? '–' : pct(d.trefferquote*100, 1);
  const brier = d.brier == null ? '–' : num(d.brier, 4);
  $('#kalibrierungTag').textContent = `${num(d.gesamt,0)} Prognosen · ${num(d.auto,0)} automatisch`;
  $('#kalibrierungKpis').innerHTML = [
    ['Prognosen', num(d.gesamt,0), `${num(d.offen,0)} offen · ${num(d.unpruefbar,0)} unprüfbar`],
    ['Geprüft', num(d.geprueft,0), `${num(d.manuell,0)} manuell · ${num(d.auto,0)} Intel`],
    ['Trefferquote', quote, `${num(d.treffer,0)} Treffer aus geprüften`],
    ['Brier-Score', brier, '0 = sicher richtig, 1 = sicher falsch'],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');
  const statusText = f => {
    const e = f.ergebnis;
    if(e && e.eingetreten === 1) return 'eingetreten';
    if(e && e.eingetreten === 0) return 'nicht eingetreten';
    return f.status || 'offen';
  };
  const statusPill = f => {
    const e = f.ergebnis;
    if(e && e.eingetreten === 1) return 'g';
    if(e && e.eingetreten === 0) return 'r';
    return f.status === 'unpruefbar' ? 'g' : 'w';
  };
  const liste = d.letzte || [];
  $('#kalibrierungList').innerHTML = liste.length ? liste.map(f=>`
    <div class="li"><span><b style="font-weight:400">${esc(f.aussage)}</b>
      <small>${esc(f.kennung)} · ${esc(f.symbol || 'ohne Symbol')} · ${num(f.konfidenz,2)} Konfidenz</small></span>
      <span class="pill ${statusPill(f)}">${esc(statusText(f))}</span></div>`).join('')
    : '<div class="empty">Noch keine Prognose. Neue Marktprognosen erscheinen hier.</div>';
  const klassen = d.kalibrierungsklassen || [];
  $('#kalibrierungKlassen').innerHTML = klassen.some(k=>k.n) ? `<table class="tbl"><thead><tr><th>Konfidenz</th><th class="m">n</th><th class="m">Treffer</th><th class="m">Quote</th><th class="m">Brier</th></tr></thead><tbody>
    ${klassen.map(k=>`<tr><td>${esc(k.klasse)}</td><td class="m">${num(k.n,0)}</td><td class="m">${num(k.treffer,0)}</td><td class="m">${k.quote==null?'–':pct(k.quote*100,1)}</td><td class="m">${k.brier==null?'–':num(k.brier,4)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Noch keine Kalibrierungsklassen. Sie füllen sich erst mit geprüften Prognosen.</div>';
  $('#kalibrierungHinweis').textContent = d.hinweis || '';
}

document.querySelectorAll('#graphWindow [data-w]').forEach(btn => {
  btn.addEventListener('click', () => {
    graphWindow = btn.dataset.w || '7d';
    document.querySelectorAll('#graphWindow [data-w]').forEach(b=>b.classList.toggle('on', b===btn));
    ladeGraph();
  });
});

function renderSpider(){
  ladeNacht();
  const sp = R.spider || {};
  const stat = sp.statistik || {};
  const artikel = sp.artikel || [];
  const it = R.intel || {};
  const is = it.statistik || {};
  const nachStatus = is.nach_status || {};
  const auftraege = it.auftraege || [];
  const weiter = it.weiterleitungen || [];
  const quellen = it.quellen || [];
  const offen = nachStatus['offen'] ?? 0;

  $('#spiderKpis').innerHTML = [
    ['Quellen', sp.quellen ?? 0, 'RSS-Feeds im Lauf'],
    ['Gelesen', sp.gelesen ?? 0, 'Artikel im Lauf'],
    ['Analysiert', is.analysiert ?? sp.analysiert ?? 0, 'Volltext geprüft'],
    ['Neu', sp.neu ?? 0, 'in die Datenbank'],
    ['Aufträge', is.auftraege ?? 0, `${offen} offen`],
    ['Bestätigt', nachStatus['bestätigt'] ?? 0, 'Hypothesen belegt'],
    ['Widerlegt', nachStatus['widerlegt'] ?? 0, 'Hypothesen verworfen'],
    ['Weiterleitungen', is.weiterleitungen ?? 0, `${is.weiterleitungen_offen ?? 0} offen`],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  const quelStatus = Object.fromEntries((sp.quellen_status||[]).map(q=>[q.name,q]));
  const intervall = sp.intervall_minuten;
  $('#spiderTag').textContent = intervall
    ? `${artikel.length} Einträge · Abruf alle ${intervall} min`
    : `${artikel.length} Einträge`;
  $('#spiderList').innerHTML = artikel.length ? artikel.map(a=>{
    const stufe = String(a.prioritaet||'').toLowerCase();
    const stufePill = stufe==='kritisch' ? 'r' : (stufe==='wichtig' ? 'w' : 'g');
    const zeiten = [`erkannt ${kurzZeit(a.erkannt||a.geholt) || '–'}`];
    if(a.veroeffentlicht) zeiten.push(`veröffentlicht ${kurzZeit(a.veroeffentlicht)}`);
    return `<div class="li"${a.prioritaet_grund?` title="${esc(a.prioritaet_grund)}"`:''}>
    <span><b style="font-weight:400">${esc(a.titel)}</b>
    <small>${esc(a.quelle)} · ${esc(a.typ)}${a.symbole?` · ${esc(a.symbole)}`:''} · ${zeiten.join(' · ')}</small></span>
    <span style="display:inline-flex;gap:6px"><span class="pill ${stufePill}">${esc(stufe||'unbekannt')}</span>
    <span class="pill ${a.qualitaet>=0.7?'':'w'}">${num(a.qualitaet,2)}</span></span></div>`;
  }).join('')
    : '<div class="empty">Noch keine Artikel. Auf «Recherche starten» klicken.</div>';

  const intelQuelle = Object.fromEntries(quellen.map(q=>[q.quelle,q]));
  const quellListe = (sp.quellen_status||[]).length ? sp.quellen_status.map(q=>q.name) : quellen.map(q=>q.quelle);
  const quellZeile = name => {
    const s = quelStatus[name] || {};
    const i = intelQuelle[name] || {};
    const letzte = s.letzter_abruf ? kurzZeit(s.letzter_abruf) : '–';
    let status = '<span class="pill w">noch nicht abgerufen</span>';
    if(s.status === 'fehler') status = '<span class="pill r">Fehler</span>';
    else if(s.letzter_abruf) status = `<span class="pill g">${s.gelesen ?? 0} gelesen</span>`;
    return `<tr><td>${esc(name)}</td><td class="m">${i.artikel ?? 0}</td><td class="m">${i.qualitaet != null ? num(i.qualitaet,2) : '–'}</td>
    <td class="m up">${i.bestaetigt ?? 0}</td><td class="m dn">${i.widerlegt ?? 0}</td>
    <td class="m">${letzte}</td><td class="m">${status}</td></tr>`;
  };
  $('#spiderQuellen').innerHTML = quellListe.length ? `<table class="tbl"><thead><tr><th>Quelle</th><th class="m">Artikel</th><th class="m">Ø Qualität</th><th class="m">belegt</th><th class="m">verworfen</th><th class="m">letzter Abruf</th><th class="m">Status</th></tr></thead><tbody>
    ${quellListe.map(quellZeile).join('')}</tbody></table>`
    : '<div class="empty">Keine Quelle konfiguriert.</div>';

  const pill = s => s==='bestätigt' ? 'g' : (s==='widerlegt' ? 'r' : (s==='offen' ? 'w' : 'g'));
  const auftragStatus = it.auftrag_status || [];
  $('#intelTag').textContent = `${auftraege.length} · ${offen} offen`;
  $('#intelAuftraege').innerHTML = auftraege.length ? auftraege.map(a=>{
    const st = auftragStatus.includes(a.status) ? auftragStatus : [a.status, ...auftragStatus];
    return `<div class="li ord" data-kennung="${esc(a.kennung)}">
    <div class="wlTop"><span><b style="font-weight:400">${esc(a.titel)}</b>
      <small>${esc(a.kennung)} · Abt. ${esc(a.abteilung)}</small></span>
      <span class="pill ${pill(a.status)}">${esc(a.status)}</span></div>
    ${a.ergebnis?`<div class="ordErg">${esc(a.ergebnis)}</div>`:''}
    <details class="ordEdit"><summary>Status und Ergebnis bearbeiten</summary>
      <div class="ordCtl">
        <label>Status<select data-a="status">${st.map(s=>`<option value="${esc(s)}"${s===a.status?' selected':''}>${esc(s)}</option>`).join('')}</select></label>
        <label>Ergebnis<textarea data-a="ergebnis" rows="2" placeholder="Beleg, Messung oder Begründung">${esc(a.ergebnis || '')}</textarea></label>
        <button type="button" class="toggle" data-save>Speichern</button>
      </div>
    </details></div>`;}).join('')
    : '<div class="empty">Noch keine Forschungsaufträge.</div>';

  const wlStatus = it.weiterleitung_status || [];
  const abteilungen = it.abteilungen || [];
  $('#intelWeiter').innerHTML = weiter.length ? weiter.map(w=>{
    const abt = abteilungen.includes(w.an) ? abteilungen : [w.an, ...abteilungen];
    const st = wlStatus.includes(w.status) ? wlStatus : [w.status, ...wlStatus];
    const wlPill = w.status==='neu' ? 'w' : (w.status==='erledigt' ? 'g' : 'b');
    return `<div class="li wl" data-kennung="${esc(w.kennung)}">
    <div class="wlTop"><span><b style="font-weight:400">${esc(w.betreff)}</b>
      <small>${esc(w.kennung)} · ${esc(w.von)}</small></span>
      <span class="pill ${wlPill}">${esc(w.status)}</span></div>
    <div class="wlCtl">
      <label>Abteilung<select data-wl="an">${abt.map(a=>`<option value="${esc(a)}"${a===w.an?' selected':''}>${esc(a)}</option>`).join('')}</select></label>
      <label>Status<select data-wl="status">${st.map(s=>`<option value="${esc(s)}"${s===w.status?' selected':''}>${esc(s)}</option>`).join('')}</select></label>
    </div></div>`;}).join('')
    : '<div class="empty">Noch keine Weiterleitungen.</div>';

  ladeGraph();
  ladeKalibrierung();
}

$('#spiderBtn') && ($('#spiderBtn').onclick = async () => {
  const b = $('#spiderBtn'); b.disabled = true; b.textContent = 'Recherche läuft …';
  try{
    const r = await fetch('/api/spider', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Recherche fehlgeschlagen');
    await lade();
  }catch(e){
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(e.message);
  }finally{
    b.disabled = false; b.textContent = 'Recherche starten';
  }
});

$('#intelAuftraege').addEventListener('click', async e => {
  const b = e.target.closest('button[data-save]');
  if(!b) return;
  const box = b.closest('[data-kennung]');
  const status = box.querySelector('select[data-a="status"]').value;
  const ergebnis = box.querySelector('textarea[data-a="ergebnis"]').value.trim();
  if(status !== 'offen' && !ergebnis){
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>Ein abgeschlossener Auftrag braucht ein Ergebnis.';
    return;
  }
  box.querySelectorAll('select, textarea, button').forEach(el=>el.disabled = true);
  try{
    const r = await fetch('/api/intel/auftrag', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({kennung: box.dataset.kennung, status, ergebnis})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Auftrag konnte nicht gespeichert werden');
    await lade();
  }catch(err){
    box.querySelectorAll('select, textarea, button').forEach(el=>el.disabled = false);
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(err.message);
  }
});

$('#intelWeiter').addEventListener('change', async e => {
  const sel = e.target.closest('select[data-wl]');
  if(!sel) return;
  const box = sel.closest('[data-kennung]');
  const abt = box.querySelector('select[data-wl="an"]');
  const st = box.querySelector('select[data-wl="status"]');
  // Neue Abteilung heisst: dort ist die Weiterleitung noch nicht übernommen.
  if(sel.dataset.wl === 'an') st.value = 'neu';
  box.querySelectorAll('select').forEach(s=>s.disabled = true);
  try{
    const q = new URLSearchParams({kennung: box.dataset.kennung,
      abteilung: abt.value, status: st.value});
    const r = await fetch('/api/intel/weiterleitung?' + q, {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Weiterleitung konnte nicht gespeichert werden');
    await lade();
  }catch(err){
    box.querySelectorAll('select').forEach(s=>s.disabled = false);
    $('#banner').className = 'banner b-sim';
    $('#banner').innerHTML = '<b>FEHLER</b>' + esc(err.message);
  }
});

const missionFehler = text => {
  $('#banner').className = 'banner b-sim';
  $('#banner').innerHTML = '<b>FEHLER</b>' + esc(text);
};

const missionBtn = $('#missionBtn');

if (missionBtn) missionBtn.onclick = async () => {
  const titel = $('#missionTitel').value.trim();
  const auftrag = $('#missionAuftrag').value.trim();
  const prioritaet = $('#missionPrio').value;
  if(titel.length < 3 || auftrag.length < 10){
    missionFehler('Titel (min. 3 Zeichen) und Auftrag (min. 10 Zeichen) sind Pflicht.');
    return;
  }
  missionBtn.disabled = true;
  missionBtn.textContent = 'Mission läuft …';
  try{
    const r = await fetch('/api/nexus/mission', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({titel, auftrag, prioritaet})});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Mission konnte nicht angelegt werden');
    const kennung = d.mission?.kennung;
    if(kennung){
      const r2 = await fetch('/api/nexus/mission/' + encodeURIComponent(kennung) + '/lauf?max_tasks=10', {method:'POST'});
      const d2 = await r2.json();
      if(!d2.ok) throw new Error(d2.fehler || 'Mission konnte nicht laufen');
    }
    $('#missionTitel').value = '';
    $('#missionAuftrag').value = '';
    await ladeNacht();
  }catch(e){
    missionFehler(e.message);
  }finally{
    missionBtn.disabled = false;
    missionBtn.textContent = 'Mission anlegen & starten';
  }
};

const missionList = $('#missionList');

if (missionList) missionList.addEventListener('click', async e => {
  const box = e.target.closest('[data-kennung]');
  if(!box) return;
  const kennung = box.dataset.kennung;
  if(e.target.closest('[data-mission-lauf]')){
    const b = e.target.closest('button');
    b.disabled = true;
    try{
      const r = await fetch('/api/nexus/mission/' + encodeURIComponent(kennung) + '/lauf?max_tasks=10', {method:'POST'});
      const d = await r.json();
      if(!d.ok) throw new Error(d.fehler || 'Mission konnte nicht laufen');
      await ladeNacht();
    }catch(err){
      missionFehler(err.message);
      b.disabled = false;
    }
    return;
  }
  const berichtBtn = e.target.closest('[data-mission-bericht]');
  if(!berichtBtn) return;
  const pre = box.querySelector('.mission-report');
  if(pre && !pre.hidden){
    pre.hidden = true;
    pre.textContent = '';
    berichtBtn.textContent = 'Bericht';
    berichtBtn.setAttribute('aria-expanded', 'false');
    return;
  }
  berichtBtn.disabled = true;
  try{
    const r = await fetch('/api/nexus/mission/' + encodeURIComponent(kennung), {cache:'no-store'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Bericht konnte nicht geladen werden');
    const bericht = d.mission?.bericht || {};
    if(pre){
      pre.textContent = bericht.text || bericht.fehler || 'Kein Bericht gespeichert.';
      pre.hidden = false;
      berichtBtn.textContent = 'Schließen';
      berichtBtn.setAttribute('aria-expanded', 'true');
    }
  }catch(err){
    missionFehler(err.message);
  }finally{
    berichtBtn.disabled = false;
  }
});

const forecastBtn = $('#forecastBtn');

if (forecastBtn) forecastBtn.onclick = async () => {
  const aussage = $('#forecastAussage').value.trim();
  const symbol = $('#forecastSymbol').value.trim().toUpperCase();
  const erwartung = $('#forecastErwartung').value;
  const zeithorizont = $('#forecastHorizont').value.trim() || '24h';
  const konfidenz = Number($('#forecastKonfidenz').value);
  if(aussage.length < 5 || !symbol){
    phase6Fehler('Aussage (min. 5 Zeichen) und Symbol sind Pflicht.');
    return;
  }
  if(!Number.isFinite(konfidenz) || konfidenz < 0 || konfidenz > 1){
    phase6Fehler('Konfidenz muss zwischen 0 und 1 liegen.');
    return;
  }
  forecastBtn.disabled = true;
  forecastBtn.textContent = 'Wird angelegt …';
  try {
    const r = await fetch('/api/nexus/prognose', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({aussage, erwartung, symbol, zeithorizont, konfidenz})});
    const d = await r.json();
    if(!r.ok || !d.ok) throw new Error(d.fehler || 'Prognose konnte nicht angelegt werden');
    $('#forecastAussage').value = '';
    $('#forecastSymbol').value = '';
    await ladeKalibrierung();
    await ladeNacht();
  } catch(e) {
    phase6Fehler(e.message);
  } finally {
    forecastBtn.disabled = false;
    forecastBtn.textContent = 'Prognose anlegen';
  }
};

export { renderSpider, zeichneBewertung };
