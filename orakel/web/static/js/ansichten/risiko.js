/* Risiko: Handelsstopp, Auslastung der Grenzen und Prüfprotokoll. */
import { R } from '../kern/daten.js';
import { $, COL, esc, num } from '../kern/helfer.js';

function renderRisk(){
  const r = R.risiko||{}, a = r.auslastung||{}, L = R.risiko_grenzen||{};
  const halt = r.status === 'gestoppt';
  $('#riskStatus').innerHTML = `<div class="card"><span><span class="pill ${halt?'r':''}">${halt?'HANDELSSTOPP':'AKTIV'}</span></span>
    <h2>${halt?esc(r.grund):'Keine Grenze überschritten'}</h2>
    <p class="sub" style="margin:0">${halt?'Neue Käufe sind blockiert. Aufheben nur nach Prüfung: <span class="code">python -m orakel stopp-aufheben --bestaetigen</span>':'Käufe werden einzeln gegen alle Grenzen geprüft. Verkäufe bleiben immer erlaubt.'}</p></div>`;
  const zeile = (name,lim,cur,unit) => {
    const p = (cur==null||!lim) ? null : Math.min(100, cur/lim*100);
    return `<tr><td>${name}</td><td class="m">${lim}${unit}</td><td class="m">${cur==null?'–':num(cur,unit?2:0)+unit}</td>
      <td>${p==null?'<span class="na">kein Konto im Lauf</span>':`<span class="bar"><i style="width:${p}%;background:${p>=100?COL.bad:p>=70?COL.amber:COL.good}"></i></span>`}</td></tr>`;
  };
  $('#riskLimits').innerHTML = `<table class="tbl"><thead><tr><th>Grenze</th><th class="m">Wert</th><th class="m">Aktuell</th><th>Auslastung</th></tr></thead><tbody>
    ${zeile('Drawdown vom Höchststand',L.max_drawdown_pct,a.drawdown_pct,' %')}
    ${zeile('Tagesverlust',L.max_daily_loss_pct,a.tagesverlust_pct,' %')}
    ${zeile('Gesamtengagement (Nominal)',L.max_gross_exposure_pct,a.engagement_pct,' %')}
    ${zeile('Offene Positionen',L.max_open_positions,a.positionen,'')}
    <tr><td>Risiko pro Trade bis Stop</td><td class="m">${L.risk_per_trade_pct} %</td><td class="m">–</td><td class="na">pro Auftrag geprüft</td></tr>
    <tr><td>Hebelgrenze</td><td class="m">${L.max_hebel}×</td><td class="m">–</td><td class="na">Nominal je Eigenkapital</td></tr>
    <tr><td>Max. Nominal je Position</td><td class="m">${L.max_position_pct} %</td><td class="m">–</td><td class="na">pro Auftrag geprüft</td></tr>
    <tr><td>Stop-Abstand</td><td class="m">${L.atr_stop_multiple} × ATR</td><td class="m">–</td><td class="na">durchschnittliche Schwankung</td></tr>
  </tbody></table>`;
  const dq = R.datenqualitaet||[];
  $('#dqTag').textContent = `${dq.filter(q=>q.ok).length} von ${dq.length} Symbolen in Ordnung`;
  $('#dq').innerHTML = dq.length ? `<table class="tbl"><thead><tr><th>Symbol</th><th>Status</th><th class="m">Kerzen</th><th>Zeitraum</th><th>Fehler / Warnungen</th></tr></thead><tbody>
    ${dq.map(q=>`<tr><td>${esc(q.symbol)}</td><td><span class="pill ${q.ok?'':'r'}">${q.ok?'OK':'FEHLER'}</span></td>
    <td class="m">${q.kerzen}</td><td>${esc((q.von||'–').slice(0,16))} bis ${esc((q.bis||'–').slice(0,16))}</td>
    <td style="white-space:normal">${[...(q.fehler||[]).map(e=>`<span class="dn">${esc(e)}</span>`),...(q.warnungen||[]).map(e=>`<span class="na">${esc(e)}</span>`)].slice(0,4).join('<br>')||'<span class="na">keine</span>'}</td></tr>`).join('')}
    </tbody></table>` : '<div class="empty">Keine Daten geprüft.</div>';
  const c = R.kosten||{};
  $('#costs').innerHTML = `<table class="tbl tblKey"><tbody>
    <tr><td>Kommission pro Stück</td><td class="m">USD ${c.commission_per_share}</td></tr>
    <tr><td>Mindestkommission</td><td class="m">USD ${c.min_commission}</td></tr>
    <tr><td>Slippage pro Ausführung</td><td class="m">${c.slippage_bps} bps</td></tr>
    <tr><td>Ausführung</td><td class="m">Eröffnung der Folgekerze</td></tr></tbody></table>`;
  $('#live').innerHTML = `<span><span class="pill r">GESPERRT</span></span><div class="reasons">
    ${(R.live?.gruende||[]).map(g=>`<span class="x">${esc(g)}</span>`).join('')}</div>`;
}

export { renderRisk };
