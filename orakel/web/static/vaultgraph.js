/* Wissensbank: interaktiver Graph aus /api/vault/graph. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const FARBEN = {
    '00-Index':'#9b8bb4', '10-Daten':'#7fd4ff', '20-Strategien':'#ff3fa4',
    '30-Validierungen':'#38e8ff', '40-Entscheide':'#5ef2c0', '50-Konferenz':'#c08bff',
    '60-Fehler':'#ff5470', '70-Wissen':'#ffb84d', 'Unaufgelöst':'#8f7ba8',
  };

  const state = {
    daten: null, knoten: [], kanten: [], byId: new Map(),
    selected: null, hover: null, search: '', folder: '', orphans: true,
    t: { x: 0, y: 0, k: 1 }, width: 0, height: 0, dpr: 1,
    drag: null, pan: null, geladen: false, laedt: false, userMoved: false,
  };
  let el = {};

  function aktivieren() {
    if (!el.initialisiert) init();
    if (!state.geladen && !state.laedt) laden();
    else { resize(); draw(); }
  }

  function init() {
    const canvas = $('#vaultCanvas');
    if (!canvas || el.initialisiert) return;
    el = {
      canvas, stage: $('#vaultStage'), empty: $('#vaultGraphEmpty'), tip: $('#vaultTip'),
      detail: $('#vaultDetail'), tag: $('#vaultGraphTag'), count: $('#vaultGraphCount'),
      search: $('#vaultSearch'), folder: $('#vaultFolder'), orphans: $('#vaultOrphans'),
      reset: $('#vaultReset'), legend: $('#vaultLegend'), ctx: canvas.getContext('2d'),
      initialisiert: true,
    };
    if (!el.stage || !el.ctx) return;

    el.search.addEventListener('input', () => {
      state.search = el.search.value.trim().toLowerCase();
      updateCount();
      draw();
    });
    el.folder.addEventListener('change', filterGeaendert);
    el.orphans.addEventListener('change', filterGeaendert);
    el.reset.addEventListener('click', reset);
    el.empty.addEventListener('click', ev => {
      if (ev.target && ev.target.id === 'vaultReload') laden();
    });
    el.detail.addEventListener('click', ev => {
      const b = ev.target.closest('[data-vault-target]');
      if (!b) return;
      const n = state.byId.get(b.getAttribute('data-vault-target'));
      if (!n) return;
      state.selected = n;
      renderDetail(n);
      draw();
    });
    document.querySelectorAll('[data-vault-zoom]').forEach(b => {
      b.addEventListener('click', () => {
        if (!state.geladen) return;
        if (b.dataset.vaultZoom === 'fit') { fitToVisible(); draw(); return; }
        zoomAt(state.width / 2, state.height / 2, b.dataset.vaultZoom === 'in' ? 1.2 : 1 / 1.2);
      });
    });

    canvas.addEventListener('pointerdown', onDown);
    canvas.addEventListener('pointermove', onMove);
    canvas.addEventListener('pointerup', onUp);
    canvas.addEventListener('pointercancel', onUp);
    canvas.addEventListener('pointerleave', () => {
      if (state.drag || state.pan) return;
      state.hover = null;
      hideTip();
      draw();
    });
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('dblclick', () => { fitToVisible(); draw(); });
    canvas.addEventListener('keydown', ev => {
      if (ev.key === 'Escape') {
        state.selected = null;
        renderDetail(null);
        draw();
      }
    });
    if (window.ResizeObserver) new ResizeObserver(() => resize()).observe(el.stage);
    else window.addEventListener('resize', resize);
    resize();
  }

  async function laden() {
    if (state.laedt) return;
    init();
    if (!el.canvas) return;
    state.laedt = true;
    if (el.tag) el.tag.textContent = 'lädt …';
    if (el.empty) {
      el.empty.hidden = false;
      el.empty.innerHTML = '<b>VAULT-GRAPH</b><span>Lade Notizen und Wikilinks …</span>';
    }
    try {
      const r = await fetch('/api/vault/graph', { cache: 'no-store' });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.fehler || 'Graph konnte nicht geladen werden');
      state.daten = d;
      state.knoten = (d.knoten || []).map(n => ({
        ...n,
        _such: [n.titel, n.ordner, n.kategorie, ...(n.tags || []), n.auszug]
          .filter(Boolean).join(' ').toLowerCase(),
      }));
      state.kanten = d.kanten || [];
      state.byId = new Map(state.knoten.map(n => [n.id, n]));
      state.selected = null;
      state.hover = null;
      state.search = '';
      state.folder = '';
      state.orphans = true;
      state.geladen = true;
      state.userMoved = false;
      if (el.search) el.search.value = '';
      if (el.folder) el.folder.value = '';
      if (el.orphans) el.orphans.checked = true;
      baueFilter();
      layout();
      resize();
      fitToVisible();
      updateMeta();
      renderDetail(null);
      el.empty.hidden = state.knoten.length > 0;
      el.canvas.hidden = state.knoten.length === 0;
      if (!state.knoten.length && el.empty) {
        el.empty.innerHTML = `<b>VAULT-GRAPH</b><span>${esc(d.hinweis || 'Der Vault enthält noch keine Notizen.')}</span><button type="button" id="vaultReload">Erneut laden</button>`;
      }
      draw();
    } catch (e) {
      state.geladen = false;
      state.knoten = [];
      state.kanten = [];
      if (el.tag) el.tag.textContent = 'nicht geladen';
      if (el.empty) {
        el.empty.hidden = false;
        el.empty.innerHTML = `<b>VAULT-GRAPH</b><span>Graph nicht geladen: ${esc(e.message)}</span><button type="button" id="vaultReload">Erneut laden</button>`;
      }
      if (el.canvas) el.canvas.hidden = true;
      if (el.count) el.count.textContent = '';
      renderDetail(null);
    } finally {
      state.laedt = false;
    }
  }

  function baueFilter() {
    const ordner = state.daten?.ordner || [];
    if (el.folder) {
      el.folder.innerHTML = '<option value="">Alle Ordner</option>' + ordner
        .map(o => `<option value="${esc(o.name)}">${esc(o.name)} (${o.anzahl})</option>`).join('');
    }
    if (el.legend) {
      const st = state.daten?.statistik || {};
      el.legend.innerHTML = ordner
        .map(o => `<span><i style="background:${FARBEN[o.name] || '#ab9cc9'}"></i>${esc(o.name)} ${o.anzahl}</span>`)
        .join('') + (st.unaufgeloest
          ? `<span><i style="background:${FARBEN['Unaufgelöst']}"></i>unaufgelöst ${st.unaufgeloest}</span>` : '');
    }
  }

  function updateMeta() {
    if (!state.daten || !el.tag) return;
    const st = state.daten.statistik || {};
    el.tag.textContent = `${st.notizen || 0} Notizen · ${st.links || 0} Links` +
      (st.unaufgeloest ? ` · ${st.unaufgeloest} unaufgelöst` : '');
    updateCount();
  }

  function updateCount() {
    if (!el.count) return;
    const sichtbar_ = state.knoten.filter(sichtbar);
    if (state.search) {
      const treffer = sichtbar_.filter(istTreffer).length;
      el.count.textContent = `${treffer} Treffer · ${sichtbar_.length} sichtbar`;
    } else {
      el.count.textContent = `${sichtbar_.length} Knoten sichtbar`;
    }
  }

  function sichtbar(n) {
    if (!state.orphans && (n.grad || 0) === 0) return false;
    if (state.folder && n.ordner !== state.folder) return false;
    return true;
  }

  function istTreffer(n) {
    return !state.search || (n._such || '').includes(state.search);
  }

  function filterGeaendert() {
    state.folder = el.folder ? el.folder.value : '';
    state.orphans = el.orphans ? el.orphans.checked : true;
    state.hover = null;
    hideTip();
    if (state.selected && !sichtbar(state.selected)) {
      state.selected = null;
      renderDetail(null);
    }
    fitToVisible();
    updateCount();
    draw();
  }

  function reset() {
    if (el.search) el.search.value = '';
    if (el.folder) el.folder.value = '';
    if (el.orphans) el.orphans.checked = true;
    state.search = '';
    state.folder = '';
    state.orphans = true;
    state.selected = null;
    state.hover = null;
    hideTip();
    renderDetail(null);
    fitToVisible();
    updateCount();
    draw();
  }

  function hash(s) {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  function layout() {
    const n = state.knoten.length;
    if (!n) return;
    const w = state.width || 760, h = state.height || 480;
    state.knoten.forEach((k, i) => {
      const a = (2 * Math.PI * i / n) + ((hash(k.id) % 1000) / 1000 - 0.5) * 0.42;
      const r = Math.min(w, h) * (0.22 + ((hash(k.id + ':r') % 1000) / 1000) * 0.16);
      k.x = w / 2 + Math.cos(a) * r;
      k.y = h / 2 + Math.sin(a) * r;
      k.vx = 0;
      k.vy = 0;
    });
    for (let tick = 0; tick < 190; tick++) {
      for (let i = 0; i < n; i++) {
        const a = state.knoten[i];
        for (let j = i + 1; j < n; j++) {
          const b = state.knoten[j];
          let dx = b.x - a.x, dy = b.y - a.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 0.01) { dx = (i + 1) * 0.01; dy = (j + 1) * 0.01; d2 = dx * dx + dy * dy; }
          const d = Math.sqrt(d2);
          if (d < 28) {
            const f = (28 - d) * 0.09;
            a.vx -= dx / d * f; a.vy -= dy / d * f;
            b.vx += dx / d * f; b.vy += dy / d * f;
          }
          const f = 500 / Math.max(d2, 900) * 0.14;
          a.vx -= dx / d * f; a.vy -= dy / d * f;
          b.vx += dx / d * f; b.vy += dy / d * f;
        }
        a.vx += (w / 2 - a.x) * 0.0008;
        a.vy += (h / 2 - a.y) * 0.0008;
      }
      for (const e of state.kanten) {
        const a = state.byId.get(e.von), b = state.byId.get(e.nach);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y;
        const d = Math.max(1, Math.hypot(dx, dy));
        const f = (d - 78) * 0.003;
        a.vx += dx / d * f; a.vy += dy / d * f;
        b.vx -= dx / d * f; b.vy -= dy / d * f;
      }
      for (const k of state.knoten) {
        k.vx = clamp(k.vx * 0.86, -2.2, 2.2);
        k.vy = clamp(k.vy * 0.86, -2.2, 2.2);
        k.x += k.vx;
        k.y += k.vy;
      }
    }
  }

  function fitToVisible() {
    const vis = state.knoten.filter(sichtbar);
    if (!vis.length || !state.width || !state.height) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of vis) {
      minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y);
    }
    const dx = Math.max(1, maxX - minX), dy = Math.max(1, maxY - minY);
    const k = clamp(Math.min((state.width - 70) / dx, (state.height - 64) / dy), 0.3, 1.6);
    state.t.k = k;
    state.t.x = state.width / 2 - (minX + maxX) / 2 * k;
    state.t.y = state.height / 2 - (minY + maxY) / 2 * k;
    state.userMoved = false;
  }

  function resize() {
    if (!el.stage || !el.canvas) return;
    const r = el.stage.getBoundingClientRect();
    state.width = Math.max(240, Math.round(r.width));
    state.height = Math.max(280, Math.round(r.height));
    state.dpr = Math.min(2, window.devicePixelRatio || 1);
    el.canvas.width = Math.round(state.width * state.dpr);
    el.canvas.height = Math.round(state.height * state.dpr);
    if (state.geladen && !state.userMoved) fitToVisible();
    draw();
  }

  function radius(n) {
    return n.unaufgeloest ? 3.6 : 4.2 + Math.min(4.5, Math.sqrt(n.grad || 0) * 2.4);
  }

  function draw() {
    if (!el.ctx) return;
    const ctx = el.ctx;
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    ctx.clearRect(0, 0, state.width, state.height);
    if (!state.geladen || !state.knoten.length) return;

    const vis = new Set(state.knoten.filter(sichtbar).map(n => n.id));
    const sel = state.selected;
    const nb = new Set();
    if (sel) {
      for (const e of state.kanten) {
        if (e.von === sel.id) nb.add(e.nach);
        if (e.nach === sel.id) nb.add(e.von);
      }
    }
    ctx.save();
    ctx.translate(state.t.x, state.t.y);
    ctx.scale(state.t.k, state.t.k);

    for (const e of state.kanten) {
      const a = state.byId.get(e.von), b = state.byId.get(e.nach);
      if (!a || !b || !vis.has(a.id) || !vis.has(b.id)) continue;
      let alpha = 0.58;
      if (state.search && (!istTreffer(a) || !istTreffer(b))) alpha = 0.07;
      if (sel) alpha = e.von === sel.id || e.nach === sel.id ? 0.85 : 0.08;
      ctx.globalAlpha = alpha;
      ctx.strokeStyle = sel && (e.von === sel.id || e.nach === sel.id) ? '#38e8ff' : '#9b7fc2';
      ctx.lineWidth = 1.35 / state.t.k;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }

    for (const n of state.knoten) {
      if (!vis.has(n.id)) continue;
      let alpha = 1;
      if (state.search && !istTreffer(n)) alpha = 0.16;
      if (sel && n.id !== sel.id && !nb.has(n.id)) alpha = Math.min(alpha, 0.22);
      const r = radius(n) + (state.hover && state.hover.id === n.id ? 1.2 : 0);
      const color = FARBEN[n.ordner] || '#ab9cc9';
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      if (n.unaufgeloest) {
        ctx.fillStyle = 'rgba(143,123,168,.15)';
        ctx.fill();
        ctx.setLineDash([3 / state.t.k, 3 / state.t.k]);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.3 / state.t.k;
        ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.fillStyle = color;
        ctx.fill();
        if (n.grad > 0) {
          ctx.strokeStyle = 'rgba(255,255,255,.38)';
          ctx.lineWidth = 0.8 / state.t.k;
          ctx.stroke();
        }
      }
      if (sel && sel.id === n.id) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 4 / state.t.k, 0, Math.PI * 2);
        ctx.strokeStyle = '#38e8ff';
        ctx.lineWidth = 1.5 / state.t.k;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    for (const n of state.knoten) {
      if (!vis.has(n.id)) continue;
      if (!(sel && sel.id === n.id) && !(state.hover && state.hover.id === n.id) &&
          state.t.k < 1.8) continue;
      if (state.search && !istTreffer(n)) continue;
      const r = radius(n);
      const fs = 10.5 / state.t.k;
      const label = n.titel.length > 38 ? n.titel.slice(0, 36) + '…' : n.titel;
      ctx.font = `${fs}px "Geist Mono", ui-monospace, monospace`;
      const tx = n.x + r + 6 / state.t.k;
      const ty = n.y + fs * 0.36;
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = 'rgba(8,4,15,.82)';
      ctx.fillRect(tx - 2 / state.t.k, ty - fs * 0.9, tw + 4 / state.t.k, fs * 1.25);
      ctx.fillStyle = n.unaufgeloest ? '#b9a8cc' : '#e9defa';
      ctx.fillText(label, tx, ty);
    }
    ctx.restore();
    ctx.globalAlpha = 1;
  }

  function punkt(ev) {
    const r = el.canvas.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  }

  function world(p) {
    return { x: (p.x - state.t.x) / state.t.k, y: (p.y - state.t.y) / state.t.k };
  }

  function pick(sx, sy) {
    const p = world({ x: sx, y: sy });
    let best = null, bestD = Infinity;
    for (const n of state.knoten) {
      if (!sichtbar(n)) continue;
      const d = Math.hypot(n.x - p.x, n.y - p.y);
      if (d <= radius(n) + 7 / state.t.k && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  function onDown(ev) {
    if (ev.button !== 0) return;
    const p = punkt(ev);
    const n = pick(p.x, p.y);
    if (n) {
      state.selected = n;
      state.drag = { n, ox: p.x, oy: p.y, nx: n.x, ny: n.y };
      renderDetail(n);
      hideTip();
      draw();
    } else {
      state.pan = { sx: p.x, sy: p.y, tx: state.t.x, ty: state.t.y, moved: false };
      el.canvas.style.cursor = 'grabbing';
    }
    try { el.canvas.setPointerCapture(ev.pointerId); } catch (_) {}
  }

  function onMove(ev) {
    const p = punkt(ev);
    if (state.drag) {
      state.userMoved = true;
      state.drag.n.x = state.drag.nx + (p.x - state.drag.ox) / state.t.k;
      state.drag.n.y = state.drag.ny + (p.y - state.drag.oy) / state.t.k;
      draw();
      return;
    }
    if (state.pan) {
      state.pan.moved = state.pan.moved || Math.abs(p.x - state.pan.sx) + Math.abs(p.y - state.pan.sy) > 3;
      state.t.x = state.pan.tx + (p.x - state.pan.sx);
      state.t.y = state.pan.ty + (p.y - state.pan.sy);
      draw();
      return;
    }
    const n = pick(p.x, p.y);
    if (n) {
      showTip(n, p);
      if (!state.hover || state.hover.id !== n.id) { state.hover = n; draw(); }
      el.canvas.style.cursor = 'pointer';
    } else {
      if (state.hover) { state.hover = null; draw(); }
      hideTip();
      el.canvas.style.cursor = 'grab';
    }
  }

  function onUp(ev) {
    if (state.pan && !state.pan.moved) {
      state.selected = null;
      renderDetail(null);
      draw();
    }
    state.drag = null;
    state.pan = null;
    el.canvas.style.cursor = 'grab';
    try { el.canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
  }

  function onWheel(ev) {
    ev.preventDefault();
    const p = punkt(ev);
    zoomAt(p.x, p.y, Math.exp(-ev.deltaY * 0.0015));
  }

  function zoomAt(px, py, factor) {
    const old = state.t.k;
    const k = clamp(old * factor, 0.3, 4);
    if (Math.abs(k - old) < 0.0001) return;
    state.t.x = px - (px - state.t.x) * (k / old);
    state.t.y = py - (py - state.t.y) * (k / old);
    state.t.k = k;
    state.userMoved = true;
    draw();
  }

  function showTip(n, p) {
    if (!el.tip) return;
    el.tip.hidden = false;
    el.tip.innerHTML = `<b>${esc(n.titel)}</b><span>${esc(n.ordner)}${n.tags?.length ? ' · #' + n.tags.slice(0, 3).map(esc).join(' #') : ''}${n.unaufgeloest ? ' · Linkziel fehlt' : ''}</span>`;
    const w = el.tip.offsetWidth;
    const left = p.x + 12 + w > state.width - 8 ? p.x - w - 12 : p.x + 12;
    const top = Math.min(p.y + 12, state.height - el.tip.offsetHeight - 8);
    el.tip.style.left = Math.max(8, left) + 'px';
    el.tip.style.top = Math.max(8, top) + 'px';
  }

  function hideTip() {
    if (el.tip) el.tip.hidden = true;
  }

  function renderDetail(n) {
    if (!el.detail) return;
    if (!n) {
      const hinweis = state.daten?.hinweis || 'Knoten anklicken, um Notiz, Tags und Links zu sehen.';
      el.detail.innerHTML = `<div class="empty">${esc(hinweis)}</div>`;
      return;
    }
    const aus = state.kanten.filter(e => e.von === n.id);
    const ein = state.kanten.filter(e => e.nach === n.id);
    const link = id => {
      const z = state.byId.get(id);
      return `<button type="button" class="vd-link" data-vault-target="${esc(id)}">${esc(z?.titel || id)}<small>${esc(z?.unaufgeloest ? 'unaufgelöst' : z?.ordner || '')}</small></button>`;
    };
    const tags = (n.tags || []).map(t => `<span class="vd-tag">#${esc(t)}</span>`).join('');
    const datum = n.erstellt ? n.erstellt.replace('T', ' ').slice(0, 16) : 'ohne Datum';
    el.detail.innerHTML = `
      <div class="vd-kicker">${esc(n.ordner)}</div>
      <h3>${esc(n.titel)}</h3>
      <div class="vd-meta">${esc(datum)} · ${n.unaufgeloest ? 'unaufgelöster Link' : 'Notiz'}</div>
      ${tags ? `<div class="vd-tags">${tags}</div>` : ''}
      <p class="vd-text">${esc(n.auszug || (n.unaufgeloest ? 'Dieses Linkziel existiert noch nicht im Vault.' : 'Keine Textvorschau.'))}</p>
      ${n.pfad ? `<div class="vd-path">vault/${esc(n.pfad)}</div>` : ''}
      <div class="vd-group"><div class="lbl">Ausgehend (${aus.length})</div>
        ${aus.length ? aus.map(e => link(e.nach)).join('') : '<div class="vd-leer">Keine ausgehenden Wikilinks.</div>'}
      </div>
      <div class="vd-group"><div class="lbl">Eingehend (${ein.length})</div>
        ${ein.length ? ein.map(e => link(e.von)).join('') : '<div class="vd-leer">Keine Backlinks.</div>'}
      </div>`;
  }

  window.VaultGraph = { aktivieren };
})();
