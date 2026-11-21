/* Sitzung: Laden, Sitzungsstand, Agenda, Protokoll und Missionstakt. */
import { $, esc, toast } from '../kern/helfer.js';

let sitzungDaten = null;

let protokolleDaten = [];

let altStunden = 1;

let altStundenServer = 1;

let altStundenWahl = parseInt(localStorage.getItem('mtgAltStunden') || '0', 10) || 0;

let altFilter = false;

let blockFilter = false;

let tradeNurAbw = false;

const SEKN = {S1:'Mira', S2:'Jonas', S3:'Lea'};

async function ladeSitzung(){
  try{
    const r = await fetch('/api/sitzung', {cache:'no-store'});
    sitzungDaten = await r.json();
  }catch(e){ sitzungDaten = null; }
  if(sitzungDaten && sitzungDaten.alt_stunden) altStundenServer = Number(sitzungDaten.alt_stunden) || 1;
  altStunden = altStundenWahl || altStundenServer;
  updateTaktStand();
  try{ renderSitzung(); }catch(e){ console.error('renderSitzung', e); }
  zeigeAltZahl();
  try{ renderProtokolle(); }catch(e){ console.error('renderProtokolle', e); }
}

function mdInline(t){
  return t.split(/(`[^`]+`)/).map(teil => {
    if(/^`[^`]+`$/.test(teil))
      return '<code>' + teil.slice(1, -1) + '</code>';
    return teil
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  }).join('');
}

function md(text){
  const zeilen = esc(text || '').split('\n');
  const aus = [];
  let liste = null;
  const schliesseListe = () => { if(liste){ aus.push('</' + liste + '>'); liste = null; } };
  const zellen = zeile => zeile.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
    .split('|').map(c => c.trim());
  for(let i = 0; i < zeilen.length; i++){
    const z = zeilen[i].replace(/\s+$/, '');
    if(z.trim().startsWith('```')){
      schliesseListe();
      const code = [];
      i += 1;
      while(i < zeilen.length && !zeilen[i].trim().startsWith('```')){
        code.push(zeilen[i]);
        i += 1;
      }
      aus.push('<pre><code>' + code.join('\n') + '</code></pre>');
      continue;
    }
    const istZitat = t => t.trim().startsWith('>') || t.trim().startsWith('&gt;');
    if(istZitat(z)){
      schliesseListe();
      const zitat = [];
      while(i < zeilen.length && istZitat(zeilen[i])){
        zitat.push(zeilen[i].replace(/^\s*(?:>|&gt;)\s?/, ''));
        i += 1;
      }
      i -= 1;
      aus.push('<blockquote>' + zitat.map(t => mdInline(t)).join('<br>') + '</blockquote>');
      continue;
    }
    const naechste = (zeilen[i + 1] || '').trim();
    const istTabelle = z.trim().startsWith('|') && naechste.includes('-')
      && /^[\s|:-]+$/.test(naechste);
    if(istTabelle){
      schliesseListe();
      aus.push('<table><thead><tr>' + zellen(z).map(c => '<th>' + mdInline(c) + '</th>').join('') + '</tr></thead><tbody>');
      i += 1;
      while(i + 1 < zeilen.length && (zeilen[i + 1] || '').trim().startsWith('|')){
        i += 1;
        aus.push('<tr>' + zellen(zeilen[i]).map(c => '<td>' + mdInline(c) + '</td>').join('') + '</tr>');
      }
      aus.push('</tbody></table>');
      continue;
    }
    if(/^\s*[-*]\s+/.test(z) || /^\s*\d+[.)]\s+/.test(z)){
      const typ = /^\s*\d+[.)]\s+/.test(z) ? 'ol' : 'ul';
      if(liste !== typ){ schliesseListe(); aus.push('<' + typ + '>'); liste = typ; }
      aus.push('<li>' + mdInline(z.replace(/^\s*(?:[-*]|\d+[.)])\s+/, '')) + '</li>');
      continue;
    }
    schliesseListe();
    const h = z.match(/^(#{1,4})\s+(.*)$/);
    if(h){ const n = Math.min(4, h[1].length + 2); aus.push('<h' + n + '>' + mdInline(h[2]) + '</h' + n + '>'); continue; }
    aus.push(z ? '<p>' + mdInline(z) + '</p>' : '');
  }
  schliesseListe();
  return aus.join('\n');
}

function quickZeitraum(tage){
  protoTage = (protoTage === tage) ? 0 : tage;
  if(protoTage){
    const lokal = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'),
      String(d.getDate()).padStart(2, '0')].join('-');
    const jetzt = new Date();
    protoVon = lokal(new Date(jetzt.getFullYear(), jetzt.getMonth(), jetzt.getDate() - protoTage));
    protoBis = lokal(jetzt);
  } else {
    protoVon = '';
    protoBis = '';
  }
  renderProtokolle();
}

let protoSuche = '', protoFilter = '', protoTimer = null;

let protoVon = '', protoBis = '', protoSort = 'neu', protoVault = false, protoTage = 0;

function renderProtokolle(){
  const box = $('#mtgProto');
  if(!box) return;
  box.innerHTML = `<div class="sekAgendaHead"><span>Vergangene Sitzungen</span><span id="protoZahl">…</span></div>
    <div class="protoTools">
      <input id="protoSuche" placeholder="Im ganzen Vault suchen …">
      <select id="protoFilter">
        ${[['', 'alle Entscheide'], ['angenommen', 'angenommen'], ['abgelehnt', 'abgelehnt'], ['vertagt', 'vertagt'], ['offen', 'offen']]
          .map(([v, l]) => `<option value="${v}"${protoFilter === v ? ' selected' : ''}>${l}</option>`).join('')}
      </select>
      <input type="date" id="protoVon" title="Sitzungen ab">
      <input type="date" id="protoBis" title="Sitzungen bis">
      <button type="button" class="protoQuick${protoTage === 7 ? ' on' : ''}" data-tage="7">7 Tage</button>
      <button type="button" class="protoQuick${protoTage === 30 ? ' on' : ''}" data-tage="30">30 Tage</button>
      <span id="protoZeitraum" class="protoZeit"></span>
      <select id="protoSort">
        <option value="neu"${protoSort === 'neu' ? ' selected' : ''}>neueste zuerst</option>
        <option value="alt"${protoSort === 'alt' ? ' selected' : ''}>älteste zuerst</option>
      </select>
      <label class="protoVault"><input type="checkbox" id="protoVault"${protoVault ? ' checked' : ''}> ganzer Vault</label>
    </div>
    <div id="protoListe"><div class="sekStand">Wird geladen …</div></div>`;
  const suche = $('#protoSuche'), filter = $('#protoFilter');
  if(suche){
    suche.value = protoSuche;
    suche.oninput = () => {
      protoSuche = suche.value;
      clearTimeout(protoTimer);
      protoTimer = setTimeout(ladeProtokolle, 300);
    };
  }
  if(filter){
    filter.value = protoFilter;
    filter.onchange = () => { protoFilter = filter.value; ladeProtokolle(); };
  const von = $('#protoVon'), bis = $('#protoBis'), sort = $('#protoSort');
  if(von){ von.value = protoVon; von.onchange = () => { protoVon = von.value; ladeProtokolle(); }; }
  if(bis){ bis.value = protoBis; bis.onchange = () => { protoBis = bis.value; ladeProtokolle(); }; }
  if(sort){ sort.value = protoSort; sort.onchange = () => { protoSort = sort.value; ladeProtokolle(); }; }
  const vault = $('#protoVault');
  if(vault){ vault.checked = protoVault; vault.onchange = () => { protoVault = vault.checked; ladeProtokolle(); }; }
  document.querySelectorAll('.protoQuick').forEach(b => { b.onclick = () => quickZeitraum(parseInt(b.dataset.tage, 10)); });
  }
  ladeProtokolle();
}

async function ladeProtokolle(){
  const box = $('#protoListe');
  if(!box) return;
  const zeitraum = $('#protoZeitraum');
  if(zeitraum) zeitraum.textContent = (protoVon || protoBis)
    ? 'Zeitraum: ' + (protoVon || '…') + ' – ' + (protoBis || '…') : '';
  try{
    const qs = protoVault
      ? new URLSearchParams({suche: protoSuche, entscheid: protoFilter, von: protoVon, bis: protoBis, sortierung: protoSort, limit: '50'})
      : new URLSearchParams({suche: protoSuche, entscheid: protoFilter, von: protoVon, bis: protoBis, sortierung: protoSort, limit: '50'});
    const pfad = protoVault ? '/api/vault/suche' : '/api/sitzung/protokolle';
    const r = await fetch(pfad + '?' + qs.toString(), {cache: 'no-store'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Fehler');
    const liste = protoVault ? (d.treffer || []) : (d.protokolle || []);
    const zahl = $('#protoZahl');
    if(zahl) zahl.textContent = liste.length + ' / ' + (d.gesamt != null ? d.gesamt : liste.length);
    const eintrag = p => `<details class="mtgProto">
        <summary>${esc(p.titel || 'Sitzung')} <small>${esc((p.datum || p.erstellt || '').slice(0, 10))}</small></summary>
        <div class="md">${md(p.inhalt || '')}</div></details>`;
    if(!liste.length){
      box.innerHTML = '<div class="sekStand">Kein Protokoll passt zu Suche und Filter.</div>';
    } else if(!protoVault){
      box.innerHTML = liste.map(eintrag).join('');
    } else {
      const gruppen = new Map();
      liste.forEach(p => {
        const k = p.kategorie || 'ohne Kategorie';
        if(!gruppen.has(k)) gruppen.set(k, []);
        gruppen.get(k).push(p);
      });
      box.innerHTML = [...gruppen.entries()].sort((a, b) => a[0].localeCompare(b[0], 'de')).map(([k, ps]) =>
        `<div class="vaultGruppe"><div class="sekAgendaHead"><span>${esc(k)}</span><span>${ps.length}</span></div>${ps.map(eintrag).join('')}</div>`).join('');
    }
  }catch(e){
    box.innerHTML = '<div class="sekStand">Protokolle konnten nicht geladen werden.</div>';
  }
}

function musterTrades(t){
  if(!t.trades || !t.trades.length) return '';
  const liste = t.trades.slice().sort((a, b) => Number(a.netto || 0) - Number(b.netto || 0));
  const abweichend = t.trades.filter(x => x.grund && x.grund !== t.ausstieg_grund).length;
  const zusatz = ' · ' + abweichend + ' mit anderem Grund';
  const basis = `${liste.length}, Verluste zuerst${zusatz}`;
  const zahl = basis + (tradeNurAbw && abweichend ? ` · ${liste.length - abweichend} ausgeblendet` : '');
  const filter = abweichend
    ? `<label class="trFilter"><input type="checkbox" class="trNurAbw"${tradeNurAbw ? ' checked' : ''}> nur abweichender Grund (${abweichend})</label>`
    : '';
  return `<details class="musterTrades"><summary>Einzel-Trades (<span class="trZahl" data-basis="${esc(basis)}">${esc(zahl)}</span>)</summary>${filter}<div class="trKopf" aria-hidden="true"><span>Betrag</span><span>Prozent</span><span>Dauer</span></div><ul${tradeNurAbw && abweichend ? ' class="nurAbw"' : ''}>` +
    liste.map(x => `<li${x.grund && x.grund !== t.ausstieg_grund ? ' class="abweichend"' : ''}><b class="trSym">${esc(x.symbol || '')}</b><span class="trDatum">${esc(String(x.einstieg || '').slice(0, 10))} → ${esc(String(x.ausstieg || '').slice(0, 10))}</span><span class="trNet ${Number(x.netto || 0) >= 0 ? 'plus' : 'minus'}">${Number(x.netto || 0).toFixed(2)}</span><span class="trRend ${Number(x.netto || 0) >= 0 ? 'plus' : 'minus'}">${Number(x.rendite || 0).toFixed(2)} %</span>${x.dauer != null ? '<span class="trDauer">' + esc(String(x.dauer)) + ' Min.</span>' : ''}${x.grund && x.grund !== t.ausstieg_grund ? '<span class="trGrund">' + esc(x.grund) + '</span>' : ''}</li>`).join('') +
    '</ul></details>';
}

function dauerSeit(iso){
  const t = Date.parse(iso);
  if(!t) return '';
  const min = Math.max(0, Math.round((Date.now() - t) / 60000));
  if(min < 1) return 'gerade eben';
  if(min < 60) return 'vor ' + min + ' Min.';
  const std = Math.round(min / 60);
  if(std < 48) return 'vor ' + std + ' Std.';
  return 'vor ' + Math.round(std / 24) + ' Tg.';
}

function zeigeAltZahl(){
  const el = document.querySelector('#mtgAltZahl');
  if(!el) return;
  const n = document.querySelectorAll('.mtask.alt').length;
  const bloecke = [...document.querySelectorAll('.mtasks')]
    .filter(g => g.querySelector('.mtask.alt')).length;
  if(blockFilter && !bloecke) blockFilter = false;
  if(altFilter && !n){ altFilter = false; document.body.classList.remove('nurAlt'); }
  el.textContent = n + ' veraltet';
  el.classList.toggle('on', altFilter);
  el.setAttribute('aria-pressed', altFilter ? 'true' : 'false');
  const blockZahl = document.querySelector('#mtgBlockZahl');
  if(blockZahl){
    blockZahl.hidden = !bloecke;
    blockZahl.textContent = bloecke + (bloecke === 1 ? ' Block' : ' Blöcke');
    blockZahl.classList.toggle('on', blockFilter);
    blockZahl.setAttribute('aria-pressed', blockFilter ? 'true' : 'false');
  }
  document.body.classList.toggle('nurAltBloecke', blockFilter && !!bloecke);
  const filterAktiv = altFilter || blockFilter;
  document.querySelectorAll('.mtasks').forEach(g => {
    g.classList.toggle('ohneAlt', filterAktiv && !g.querySelector('.mtask.alt'));
  });
}

function taskAlt(x){
  if(!x.geaendert || x.status === 'erledigt' || x.status === 'fehlgeschlagen') return false;
  const t = Date.parse(x.geaendert);
  return !!t && (Date.now() - t) > altStunden * 3600000;
}

function taskZeitText(x){
  const wert = x.abgeschlossen_am || x.fehlgeschlagen_am || x.geaendert;
  if(!wert) return '';
  const zeit = String(wert).slice(0, 16).replace('T', ' ');
  const dauer = dauerSeit(wert);
  const art = x.abgeschlossen_am ? 'abgeschlossen '
    : (x.fehlgeschlagen_am
        ? (x.status === 'blockiert' ? 'blockiert ' : 'fehlgeschlagen ')
        : '');
  return art + zeit + (dauer ? ' (' + dauer + ')' : '');
}

function taskZeit(x){
  const text = taskZeitText(x);
  return text ? ' · ' + text : '';
}

function renderSitzung(){
  const box = $('#mtgBody'); if(!box) return;
  const tag = $('#mtgTag');
  const s = sitzungDaten;
  const themen = (s && s.themen) || [];
  if(!s || s.status === 'offen' || !themen.length){
    if(tag) tag.textContent = 'nicht eröffnet';
    box.innerHTML = `<div class="empty">Noch keine Sitzung. Die Agenda kommt aus den echten Daten: Verlust-Trades, Befunde, Fehler, Beschlüsse.</div>
      <button type="button" class="toggle main" id="mtgStart">Sitzung eröffnen</button>`;
    if($('#mtgStart')) $('#mtgStart').onclick = sitzungStart;
    return;
  }
  const offen = themen.filter(t => t.status === 'offen');
  if(tag) tag.textContent = s.status === 'beendet' ? 'beendet' : `${themen.length - offen.length} / ${themen.length} entschieden`;
  if(s.status === 'beendet'){
    const e = s.ergebnis || {};
    box.innerHTML = `<div class="mtgResult"><b>Sitzung abgeschlossen</b>
        <span>Angenommen ${e.annehmen || 0} · Abgelehnt ${e.abgelehnt || 0} · Vertagt ${e.vertagen || 0} · Offen ${e.offen || 0}</span></div>
      <button type="button" class="toggle" id="mtgStart">Neue Sitzung</button>`;
    if($('#mtgStart')) $('#mtgStart').onclick = sitzungStart;
    return;
  }
  const t = themen.find(x => x.index === (s.aktiv ?? 0)) || offen[0];
  const sichtbar = (t.beitraege || []).slice(0, t.schritt || 0);
  const phase = t.phase || 'rede';
  const alleGeredet = sichtbar.length >= (t.beitraege || []).length;
  const zaehlText = z => z ? Object.entries(z).filter(([,v]) => v).map(([k,v]) => `${k} ${v}`).join(' · ') : '';
  box.innerHTML = `
    <div class="mtgThema">
      <small>Thema ${t.index + 1} von ${themen.length} · Leitung ${esc(SEKN[t.leiter] || t.leiter)} · ${esc(t.art)}${t.vertagt ? ' · aus letzter Sitzung vertagt' : ''}</small>
      <b>${esc(t.thema)}</b>
      <p class="mtgFakt">${esc(t.gemacht)}</p>
      ${musterTrades(t)}
      ${sichtbar.map(b => `<div class="mtgWort"><span>${esc(SEKN[b.von] || b.von)}</span>${esc(b.text)}</div>`).join('')}
      ${phase !== 'rede' ? `<div class="mtgEmpf">Massnahme: ${esc(t.massnahme || t.empfehlung || '')}</div>` : ''}
      ${phase === 'ergebnis' ? `<div class="mtgStimmen">${(t.stimmen || []).map(x => `<span><b>${esc(SEKN[x.von] || x.von)}</b> <i>${esc(x.entscheid)}</i> — ${esc(x.grund)}</span>`).join('')}</div>` : ''}
      ${t.ergebnis ? `<div class="mtgErg">Beschluss: <b>${esc({annehmen:'angenommen', ablehnen:'abgelehnt', vertagen:'vertagt'}[t.ergebnis] || t.ergebnis)}</b> <small>${esc(zaehlText(t.zaehlung))}</small></div>` : ''}
      ${t.ueberstimmung ? `<div class="mtgErg">CEO-Überstimmung: ${esc(t.ueberstimmung.vorher)} → <b>${esc(t.ueberstimmung.entscheid)}</b> <small>${esc(t.ueberstimmung.begruendung)}</small></div>` : ''}
      ${phase === 'ergebnis' ? `<details class="mtgOverride"><summary>Als CEO überstimmen</summary>
        <select id="ovEntscheid">${['annehmen','ablehnen','vertagen'].filter(v => v !== t.ergebnis).map(v => `<option value="${v}">${v}</option>`).join('')}</select>
        <input id="ovGrund" maxlength="300" placeholder="Begründung (Pflicht)">
        <button type="button" id="ovBtn">Überstimmen</button></details>` : ''}
      ${(s.entscheide || []).filter(e => e.index === t.index && e.mission).map(e => `<div class="mtgErg">Weitergeleitet: <b>${esc(e.mission)}</b> <small class="mstat" data-mission="${esc(e.mission)}">${esc(e.abteilung || '')} · ${esc(e.mission_status || 'offen')}${e.mission_fortschritt != null ? ' · ' + esc(String(e.mission_fortschritt)) + '%' : ''}${e.mission_geaendert ? ' · ' + esc(String(e.mission_geaendert).slice(0, 16).replace('T', ' ')) : ''}</small></div>`).join('')}
      ${(s.entscheide || []).filter(e => e.index === t.index && e.mission).map(e => (e.mission_tasks || []).length ? `<div class="mtasks">${e.mission_tasks.map(x => `<div class="mtask${taskAlt(x) ? ' alt' : ''}"><b>${esc(x.rolle)}</b><span class="mtaskstat" data-mission="${esc(e.mission)}" data-rolle="${esc(x.rolle)}">${esc(x.status)}</span><small class="mtaskzeit">${esc(taskZeitText(x))}</small>${x.fehler && (x.status === 'blockiert' || x.status === 'fehlgeschlagen') ? `<small class="mtaskgrund">Grund: ${esc(x.fehler)}</small>` : ''}<small class="mtaskziel">Ziel: ${esc(x.ziel || '')}</small>${x.ergebnis && Object.keys(x.ergebnis).length ? `<small class="mtaskres">Ergebnis: ${esc(Object.entries(x.ergebnis).filter(([k, v]) => v != null && v !== '').map(([k, v]) => k + ': ' + (typeof v === 'string' ? v : JSON.stringify(v))).join(' · '))}</small>` : ''}</div>`).join('')}</div>` : '').join('')}
      <div class="mtgVote">
        <button type="button" id="mtgWeiter">${phase === 'rede' ? (alleGeredet ? 'Abstimmung' : 'Nächste Wortmeldung') : phase === 'abstimmung' ? 'Abstimmung durchführen' : (offen.some(x => x.index !== t.index) ? 'Nächstes Thema' : 'Sitzung abschließen')}</button>
      </div>
    </div>
    ${s.entscheide && s.entscheide.length ? `<div class="mtgLog">${s.entscheide.map(e => `<span>${esc(e.entscheid)} · ${esc(e.thema)}${e.zaehlung ? ' (' + esc(zaehlText(e.zaehlung)) + ')' : ''}${e.mission ? ' → ' + esc(e.mission) + (e.mission_status ? ' [' + esc(e.mission_status) + ']' : '') : ''}</span>`).join('')}</div>` : ''}
    <button type="button" class="toggle" id="mtgEnd">Sitzung abschließen</button>`;
  box.querySelectorAll('.trNurAbw').forEach(cb => {
    cb.onchange = () => {
      tradeNurAbw = cb.checked;
      const ul = cb.closest('details')?.querySelector('ul');
      if(ul) ul.classList.toggle('nurAbw', tradeNurAbw);
      const zahl = cb.closest('details')?.querySelector('.trZahl');
      if(zahl){
        const alle = cb.closest('details').querySelectorAll('ul li').length;
        const abw = cb.closest('details').querySelectorAll('ul li.abweichend').length;
        zahl.textContent = (zahl.dataset.basis || '') +
          (tradeNurAbw && abw ? ` · ${alle - abw} ausgeblendet` : '');
      }
    };
  });
  if($('#mtgWeiter')) $('#mtgWeiter').onclick = sitzungWeiter;
  if($('#mtgEnd')) $('#mtgEnd').onclick = sitzungAbschluss;
  if($('#ovBtn')) $('#ovBtn').onclick = async () => {
    const grund = (($('#ovGrund') || {}).value || '').trim();
    if(!grund){ if($('#ovGrund')) $('#ovGrund').focus(); return; }
    try{
      const r = await fetch('/api/sitzung/ueberstimmen', {method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({index: t.index, entscheid: ($('#ovEntscheid') || {}).value, begruendung: grund})});
      const d = await r.json();
      if(!d.ok) throw new Error(d.fehler || 'Überstimmung fehlgeschlagen');
      sitzungDaten = d; renderSitzung();
    }catch(e){
      box.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    }
  };
  zeigeAltZahl();
}

async function sitzungWeiter(){
  try{
    const r = await fetch('/api/sitzung/weiter', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Nächster Schritt fehlgeschlagen');
    const vorher = sitzungDaten && sitzungDaten.status;
    sitzungDaten = d;
    renderSitzung();
    ladeSitzung();
    if(d.status === 'beendet' && vorher !== 'beendet') toast('Sitzung abgeschlossen.');
  }catch(e){
    const b = $('#mtgBody');
    if(b) b.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    toast('Sitzungsschritt fehlgeschlagen.');
  }
}

async function sitzungStart(){
  try{
    const r = await fetch('/api/sitzung/start', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Sitzung konnte nicht eröffnet werden');
    sitzungDaten = d;
    await ladeSitzung();
    toast('Sitzung eröffnet.');
  }catch(e){
    const b = $('#mtgBody');
    if(b) b.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    toast('Sitzung konnte nicht eröffnet werden.');
  }
}

async function sitzungAbschluss(){
  try{
    const r = await fetch('/api/sitzung/abschluss', {method:'POST'});
    const d = await r.json();
    if(!d.ok) throw new Error(d.fehler || 'Abschluss fehlgeschlagen');
    sitzungDaten = d; renderSitzung(); await ladeSitzung();
    toast('Sitzung abgeschlossen.');
  }catch(e){
    const b = $('#mtgBody'); if(b) b.insertAdjacentHTML('afterbegin', `<div class="sekMsg"><small>FEHLER</small>${esc(e.message)}</div>`);
    toast('Abschluss fehlgeschlagen.');
  }
}

let missionTimer = null;

async function aktualisiereMissionen(){
  if(document.hidden) return;
  if(!sitzungDaten || !(sitzungDaten.entscheide || []).length) return;
  try{
    const r = await fetch('/api/sitzung', {cache:'no-store'});
    const d = await r.json();
    if(!d || !d.ok) return;
    (d.entscheide || []).forEach(e => {
      if(!e.mission) return;
      const alt = (sitzungDaten.entscheide || []).find(x => x.mission === e.mission);
      if(alt && alt.mission_status !== e.mission_status)
        logMission(e.mission + ': ' + (alt.mission_status || 'offen') + ' → ' + (e.mission_status || 'offen'));
      const el = document.querySelector('.mstat[data-mission="' + e.mission + '"]');
      if(el) el.textContent = (e.abteilung || '') + ' · ' + (e.mission_status || 'offen') +
        (e.mission_fortschritt != null ? ' · ' + e.mission_fortschritt + ' %' : '') +
        (e.mission_geaendert ? ' · ' + String(e.mission_geaendert).slice(0, 16).replace('T', ' ') : '');
    });
    (d.entscheide || []).forEach(e => {
      (e.mission_tasks || []).forEach(x => {
        const el = document.querySelector('.mtaskstat[data-mission="' + e.mission + '"][data-rolle="' + x.rolle + '"]');
        if(el) el.textContent = x.status;
        const box = el && el.closest('.mtask');
        const zeitEl = box && box.querySelector('.mtaskzeit');
        if(zeitEl) zeitEl.textContent = taskZeitText(x);
        if(box) box.classList.toggle('alt', taskAlt(x));
        if(box){
          let g = box.querySelector('.mtaskgrund');
          const grund = (x.status === 'blockiert' || x.status === 'fehlgeschlagen') && x.fehler ? x.fehler : '';
          if(grund){
            if(!g){ g = document.createElement('small'); g.className = 'mtaskgrund'; }
            g.textContent = 'Grund: ' + grund;
            const anker = box.querySelector('small:not(.mtaskgrund)');
            box.insertBefore(g, anker || null);
          } else if(g){ g.remove(); }
        }
        const werte = x.ergebnis ? Object.entries(x.ergebnis).filter(([k, v]) => v != null && v !== '') : [];
        if(box && werte.length){
          let r = box.querySelector('.mtaskres');
          if(!r){ r = document.createElement('small'); r.className = 'mtaskres'; box.appendChild(r); }
          r.textContent = 'Ergebnis: ' + werte.map(([k, v]) => k + ': ' + (typeof v === 'string' ? v : JSON.stringify(v))).join(' · ');
        }
      });
    });
    sitzungDaten.entscheide = d.entscheide;
    missionZaehler += 1;
    updateTaktStand();
    zeigeAltZahl();
  }catch(err){ /* stiller Fehlschlag, nächster Takt versucht es erneut */ }
}

let missionTakt = parseInt(localStorage.getItem('mtgTakt') || '2000', 10);

let missionSichtbar = false;

let missionZaehler = 0;

let missionLog = (() => {
  try {
    const wert = JSON.parse(localStorage.getItem('mtgLog') || '[]');
    return Array.isArray(wert) ? wert.slice(0, 6) : [];
  } catch(e){ return []; }
})();

function zeigeMissionLog(){
  const box = document.querySelector('#mtgLog');
  if(box) box.innerHTML = missionLog.map(x => `<div class="mtgLogZeile">${esc(x)}</div>`).join('');
  const knopf = document.querySelector('#mtgLogLeeren');
  if(knopf) knopf.disabled = !missionLog.length;
}

function setzeMissionTakt(ms, speichern){
  missionTakt = ms;
  if(speichern) localStorage.setItem('mtgTakt', String(ms));
  if(missionTimer){ clearInterval(missionTimer); missionTimer = null; }
  if(missionTakt > 0 && missionSichtbar && !document.hidden)
    missionTimer = setInterval(aktualisiereMissionen, missionTakt);
  updateTaktStand();
}

function logMission(text){
  const jetzt = new Date();
  const zeit = [jetzt.getHours(), jetzt.getMinutes(), jetzt.getSeconds()]
    .map(n => String(n).padStart(2, '0')).join(':');
  missionLog.unshift(zeit + ' · ' + text);
  missionLog = missionLog.slice(0, 6);
  try { localStorage.setItem('mtgLog', JSON.stringify(missionLog)); } catch(e){}
  zeigeMissionLog();
}

function updateTaktStand(){
  const stand = document.querySelector('#mtgTaktStand');
  if(stand){
    if(missionTakt <= 0) stand.textContent = 'pausiert';
    else if(document.hidden) stand.textContent = 'pausiert · Tab im Hintergrund';
    else if(!missionSichtbar) stand.textContent = 'pausiert · Bereich nicht sichtbar';
    else stand.textContent = 'läuft · alle ' + (missionTakt / 1000) + ' s';
    stand.classList.toggle('on', !!missionTimer);
  }
  const zahl = document.querySelector('#mtgTaktZahl');
  if(zahl) zahl.textContent = missionZaehler + (missionZaehler === 1 ? ' Aktualisierung' : ' Aktualisierungen');
  const altWahl = document.querySelector('#mtgAltWahl');
  if(altWahl) altWahl.value = String(altStundenWahl);
}

(function starteMissionstakt(){
  const panel = document.querySelector('#mtgPanel');
  const wahl = document.querySelector('#mtgTakt');
  if(wahl){
    wahl.value = String(missionTakt);
    wahl.onchange = () => setzeMissionTakt(parseInt(wahl.value, 10) || 0, true);
  }
  if(panel && 'IntersectionObserver' in window){
    new IntersectionObserver(eintraege => {
      missionSichtbar = eintraege.some(e => e.isIntersecting);
      setzeMissionTakt(missionTakt, false);
    }, {threshold: 0.05}).observe(panel);
  } else {
    missionSichtbar = true;
    setzeMissionTakt(missionTakt, false);
  }
  document.addEventListener('visibilitychange', () => setzeMissionTakt(missionTakt, false));
  const altZahl = document.querySelector('#mtgAltZahl');
  if(altZahl) altZahl.onclick = () => {
    altFilter = !altFilter;
    document.body.classList.toggle('nurAlt', altFilter);
    zeigeAltZahl();
  };
  const blockZahl = document.querySelector('#mtgBlockZahl');
  if(blockZahl) blockZahl.onclick = () => {
    blockFilter = !blockFilter;
    zeigeAltZahl();
  };
  const altWahl = document.querySelector('#mtgAltWahl');
  if(altWahl){
    altWahl.value = String(altStundenWahl);
    altWahl.onchange = () => {
      altStundenWahl = parseInt(altWahl.value, 10) || 0;
      try { localStorage.setItem('mtgAltStunden', String(altStundenWahl)); } catch(e){}
      altStunden = altStundenWahl || altStundenServer;
      updateTaktStand();
      renderSitzung();
      zeigeAltZahl();
    };
  }
  const leer = document.querySelector('#mtgLogLeeren');
  if(leer){
    let bis = 0;

    leer.onclick = () => {
      if(!missionLog.length) return;
      if(Date.now() <= bis){
        missionLog = [];
        try { localStorage.removeItem('mtgLog'); } catch(e){}
        zeigeMissionLog();
        bis = 0;
        leer.textContent = 'Leeren';
        leer.classList.remove('warn');
        toast('Log geleert.');
        return;
      }
      bis = Date.now() + 3000;
      leer.textContent = 'Wirklich leeren?';
      leer.classList.add('warn');
      clearTimeout(leer._t);
      leer._t = setTimeout(() => {
        bis = 0;
        leer.textContent = 'Leeren';
        leer.classList.remove('warn');
        toast('Nicht gelöscht.');
      }, 3000);
    };
  }
  zeigeMissionLog();
  setzeMissionTakt(missionTakt, false);
})();

export { ladeSitzung };
