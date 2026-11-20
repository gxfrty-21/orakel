/* Betrieb: Takt, Backoff, Grenzen und Betriebsprotokoll. */
import { $, COL, esc, num } from '../kern/helfer.js';

let betriebDaten = null, betriebFehler = null, betriebTimer = null;

function betriebDauer(sekunden){
  const s = Number(sekunden) || 0;
  if(!s) return 'jeder Takt';
  if(s >= 3600) return num(s/3600, 0) + ' h';
  if(s >= 60) return num(s/60, 0) + ' min';
  return num(s, 0) + ' s';
}

function betriebZeit(wert){
  return wert ? esc(String(wert).replace('T',' ').slice(0,16)) : '–';
}

function betriebPill(zustand){
  if(zustand === 'ok' || zustand === 'laeuft') return '';
  if(zustand === 'fehler' || zustand === 'ueberfaellig') return 'r';
  if(zustand === 'wartet' || zustand === 'backoff') return 'b';
  return 'g';
}

function betriebMeter(wert, limit){
  const p = limit > 0 ? Math.min(100, Math.max(0, Number(wert) / Number(limit) * 100)) : 0;
  const farbe = p >= 100 ? COL.bad : p >= 75 ? COL.amber : COL.good;
  return `<span class="bar"><i style="width:${p.toFixed(0)}%;background:${farbe}"></i></span>`;
}

async function ladeBetrieb(){
  if(!$('#betriebKpis')) return;
  try{
    const r = await fetch('/api/betrieb', {cache:'no-store'});
    if(!r.ok) throw new Error('HTTP ' + r.status);
    const d = await r.json();
    if(!d || typeof d !== 'object' || !d.takt) throw new Error('Ungültige Antwort');
    betriebDaten = d;
    betriebFehler = null;
  }catch(e){
    betriebDaten = null;
    betriebFehler = String(e.message || e);
  }
  renderBetrieb();
}

function renderBetrieb(){
  if(!$('#betriebKpis')) return;
  if(betriebFehler){
    $('#betriebTag').innerHTML = '<span class="dn">nicht erreichbar</span>';
    $('#betriebKpis').innerHTML = '';
    $('#betriebJobs').innerHTML = `<div class="empty">Betriebsstatus nicht geladen: ${esc(betriebFehler)}</div>`;
    $('#betriebRes').innerHTML = '<div class="empty">Keine Ressourcenwerte.</div>';
    $('#betriebLog').innerHTML = '<div class="empty">Kein Jobprotokoll geladen.</div>';
    $('#betriebHinweise').innerHTML = '<div class="empty">Keine Hinweise geladen.</div>';
    return;
  }
  if(!betriebDaten){
    $('#betriebTag').textContent = 'wird geladen';
    $('#betriebKpis').innerHTML = '';
    $('#betriebJobs').innerHTML = '<div class="empty">Betriebsstatus wird geladen.</div>';
    return;
  }
  const d = betriebDaten, t = d.takt || {}, jobs = d.jobs || [];
  const res = d.ressourcen || {}, lim = res.limits || {}, st = d.statistik || {};
  const laufend = t.status === 'laeuft' ? '<span class="up">LÄUFT</span>'
    : t.status === 'ueberfaellig' ? '<span class="dn">ÜBERFÄLLIG</span>'
    : t.status === 'aus' ? '<span class="na">AUS</span>' : '–';
  const okJobs = jobs.filter(j=>j.letzter_status === 'ok' || j.zustand === 'ok').length;
  $('#betriebTag').textContent = `${jobs.length} Jobs · ${d.ok ? 'keine kritische Warnung' : 'Warnung'}`;
  $('#betriebKpis').innerHTML = [
    ['Takt', laufend, `zuletzt ${betriebZeit(t.letzter)} · ${num(t.dauer_ms,0)} ms`],
    ['Jobs', `${num(okJobs,0)} / ${num(jobs.length,0)}`, `${num(st.gesamt,0)} Läufe in 24 h`],
    ['Datenbank', `${num(res.db_mb,1)} MB`, `Limit ${num(lim.max_db_mb,0)} MB · ${num(res.freier_speicher_mb,0)} MB frei`],
    ['Fehler', num(st.fehler,0), `${num(st.uebersprungen,0)} wegen Grenzen übersprungen`],
  ].map(q=>`<div class="kpi"><div class="l">${q[0]}</div><div class="v">${q[1]}</div><div class="n">${q[2]}</div></div>`).join('');

  $('#betriebJobs').innerHTML = jobs.length ? `<table class="tbl"><thead><tr>
    <th>Job</th><th>Zustand</th><th class="m">Intervall</th><th class="m">Nächster Versuch</th><th class="m">Fehler</th><th>Letzter Erfolg</th></tr></thead><tbody>
    ${jobs.map(j=>`<tr><td>${esc(j.titel || j.name)}<small>${esc(j.name)}${j.ressourcen_intensiv ? ' · ressourcenintensiv' : ''}${j.fehlschluesse ? `<span class="betrieb-fehler-mobil"> · ${num(j.fehlschluesse,0)} Fehler</span>` : ''}</small></td>
      <td><span class="pill ${betriebPill(j.zustand)}">${esc(j.zustand)}</span></td>
      <td class="m">${esc(betriebDauer(j.intervall_sekunden))}</td>
      <td class="m">${betriebZeit(j.naechster_versuch)}</td>
      <td class="m">${num(j.fehlschluesse,0)}${j.backoff_sekunden ? ' · ' + esc(betriebDauer(j.backoff_sekunden)) : ''}</td>
      <td>${betriebZeit(j.letzter_erfolg)}</td></tr>`).join('')}</tbody></table>`
    : '<div class="empty">Keine Jobs im Plan.</div>';

  $('#betriebRes').innerHTML = `<table class="tbl tblKey"><tbody>
    <tr><td>Datenbank</td><td class="m">${num(res.db_mb,2)} / ${num(lim.max_db_mb,0)} MB</td><td>${betriebMeter(res.db_mb, lim.max_db_mb)}</td></tr>
    <tr><td>Prozess-RSS</td><td class="m">${res.rss_mb == null ? 'nicht messbar' : num(res.rss_mb,1) + ' / ' + num(lim.max_rss_mb,0) + ' MB'}</td><td>${res.rss_mb == null ? '<span class="na">–</span>' : betriebMeter(res.rss_mb, lim.max_rss_mb)}</td></tr>
    <tr><td>Freier Speicher</td><td class="m">${num(res.freier_speicher_mb,0)} MB frei<span class="betrieb-mobil"> · Min. ${num(lim.min_freier_speicher_mb,0)} MB</span></td><td><span class="na">Minimum ${num(lim.min_freier_speicher_mb,0)} MB</span></td></tr>
    <tr><td>Taktbudget</td><td class="m">${num(lim.max_takt_sekunden,0)} s<span class="betrieb-mobil"> · Obergrenze</span></td><td><span class="na">danach werden weitere Jobs verschoben</span></td></tr>
    </tbody></table>`;

  const log = d.letzte_laeufe || [];
  $('#betriebLog').innerHTML = log.length ? log.map(e=>`<div class="li"><span><b>${esc(e.job)}</b>
    <small>${betriebZeit(e.zeit)} · ${num(e.dauer_ms,0)} ms${e.fehler ? ' · ' + esc(e.fehler) : ''}</small></span>
    <span class="pill ${e.status === 'ok' ? '' : e.status === 'fehler' ? 'r' : 'w'}">${esc(e.status)}</span></div>`).join('')
    : '<div class="empty">Noch kein Job-Lauf protokolliert.</div>';

  const warnungen = d.warnungen || [];
  $('#betriebHinweise').innerHTML = warnungen.length ? warnungen.map(w=>
    `<div class="betrieb-note"><span class="pill ${w.stufe === 'fehler' ? 'r' : w.stufe === 'info' ? 'g' : 'w'}">${esc(w.stufe)}</span>
      <span>${esc(w.text)}</span></div>`).join('')
    : '<div class="empty">Keine Warnungen. Der Takt hat alle fälligen Jobs ohne Grenzüberschreitung ausgeführt.</div>';
}

const betriebRefreshBtn = $('#betriebRefresh');

if(betriebRefreshBtn) betriebRefreshBtn.onclick = () => ladeBetrieb();

export function betriebAktiviere(){
  if(!betriebTimer){ ladeBetrieb(); betriebTimer = setInterval(ladeBetrieb, 30000); }
}

export function betriebDeaktiviere(){
  if(betriebTimer){ clearInterval(betriebTimer); betriebTimer = null; }
}

export { ladeBetrieb, renderBetrieb };
