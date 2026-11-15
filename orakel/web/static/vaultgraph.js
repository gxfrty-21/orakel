/* Wissensbank: interaktiver Graph aus /api/vault/graph. */
(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const FARBEN = {
    '10-Daten':'#7fd4ff', '20-Strategien':'#ff3fa4',
    '30-Validierungen':'#38e8ff', '40-Entscheide':'#5ef2c0', '50-Konferenz':'#c08bff',
    '60-Fehler':'#ff5470', '70-Wissen':'#ffb84d', 'Unaufgelöst':'#8f7ba8', 'Tags':'#c9a7ff',
  };

  const state = {
    daten: null, knoten: [], kanten: [], byId: new Map(),
    basisKnoten: [], basisKanten: [], tagAnzahl: 0, tags: false, tagFilter: null,
    selected: null, hover: null, search: '', folder: '', orphans: true,
    t: { x: 0, y: 0, k: 1 }, width: 0, height: 0, dpr: 1,
    drag: null, pan: null, geladen: false, laedt: false, userMoved: false,
  };
  let el = {};
  let tagAktivIndex = -1;

  function aktivieren() {
    if (!el.initialisiert) init();
    if (!state.geladen && !state.laedt) laden();
    else { resize(); wecke(0.02); }
    starteNachladen();
  }

  function init() {
    const canvas = $('#vaultCanvas');
    if (!canvas || el.initialisiert) return;
    el = {
      canvas, stage: $('#vaultStage'), empty: $('#vaultGraphEmpty'), tip: $('#vaultTip'),
      detail: $('#vaultDetail'), tag: $('#vaultGraphTag'), count: $('#vaultGraphCount'),
      search: $('#vaultSearch'), searchClear: $('#vaultSearchClear'),
      folder: $('#vaultFolder'), orphans: $('#vaultOrphans'),
      tags: $('#vaultTags'), reset: $('#vaultReset'), legend: $('#vaultLegend'),
      fokus: $('#vaultTagFokus'), fokusLabel: $('#vaultTagFokusLabel'),
      tagSuche: $('#vaultTagSuche'), tagSucheClear: $('#vaultTagSucheClear'),
      tagOptionen: $('#vaultTagOptionen'),
      tagAktiv: $('#vaultTagAktiv'), fokusClear: $('#vaultTagFokusClear'),
      ctx: canvas.getContext('2d'),
      initialisiert: true,
    };
    if (!el.stage || !el.ctx) return;

    el.search.addEventListener('input', () => {
      state.search = el.search.value.trim().toLowerCase();
      updateCount();
      draw();
    });
    el.search.addEventListener('keydown', ev => {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      el.search.value = '';
      state.search = '';
      updateCount();
      draw();
      el.search.blur();
    });
    if (el.searchClear) el.searchClear.addEventListener('click', () => {
      el.search.value = '';
      state.search = '';
      updateCount();
      draw();
      el.search.focus();
    });
    el.folder.addEventListener('change', filterGeaendert);
    el.orphans.addEventListener('change', filterGeaendert);
    if (el.tags) el.tags.addEventListener('change', tagsGeaendert);
    if (el.fokusClear) el.fokusClear.addEventListener('click', () => entferneTagFokus());
    if (el.tagSuche) {
      el.tagSuche.addEventListener('focus', () => oeffneTagOptionen());
      el.tagSuche.addEventListener('input', () => { tagAktivIndex = -1; oeffneTagOptionen(); });
      el.tagSuche.addEventListener('keydown', tagSucheTaste);
    }
    if (el.tagSucheClear) el.tagSucheClear.addEventListener('click', () => {
      el.tagSuche.value = '';
      tagAktivIndex = -1;
      oeffneTagOptionen();
      el.tagSuche.focus();
    });
    if (el.tagOptionen) {
      el.tagOptionen.addEventListener('mousedown', ev => ev.preventDefault());
      el.tagOptionen.addEventListener('click', ev => {
        const b = ev.target.closest('button[data-tag-id]');
        if (b) sprungZuTag(b.dataset.tagId);
      });
    }
    document.addEventListener('pointerdown', ev => {
      if (el.fokus && !el.fokus.contains(ev.target)) schliesseTagOptionen();
    });
    document.addEventListener('keydown', ev => {
      if (ev.key !== '/' || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const t = ev.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      const kb = document.getElementById('v-kb');
      if (!kb || kb.hidden || !state.geladen || !el.tagSuche || !el.fokus || el.fokus.hidden) return;
      ev.preventDefault();
      el.tagSuche.focus();
      el.tagSuche.select();
    });
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
        if (state.tagFilter) { entferneTagFokus(); return; }
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
      state.basisKnoten = (d.knoten || []).map(n => ({
        ...n,
        _such: [n.titel, n.ordner, n.kategorie, ...(n.tags || []), n.auszug]
          .filter(Boolean).join(' ').toLowerCase(),
      }));
      state.basisKanten = (d.kanten || []).map(e => ({ ...e }));
      state.tags = true;
      state.tagAnzahl = 0;
      state.tagFilter = null;
      if (el.fokus) el.fokus.hidden = true;
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
      if (el.tags) el.tags.checked = true;
      if (el.tagSuche) el.tagSuche.value = '';
      schliesseTagOptionen();
      state.knoten = [];
      rebuildGraph();
      baueFilter();
      layout(true);
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
        .map(o => `<option value="${esc(o.name)}">${esc(o.name)} · ${o.anzahl} ${o.anzahl === 1 ? 'Notiz' : 'Notizen'}</option>`).join('');
    }
    updateLegende();
    aktualisiereTagSprung();
  }

  function tagListe() {
    const tags = new Map();
    for (const n of state.basisKnoten || []) {
      for (const roh of n.tags || []) {
        const tag = String(roh).trim();
        if (!tag) continue;
        const key = tag.toLowerCase();
        const t = tags.get(key) || { id: 'tag:' + key, titel: '#' + tag, anzahl: 0 };
        t.anzahl += 1;
        tags.set(key, t);
      }
    }
    return [...tags.values()].sort((a, b) => b.anzahl - a.anzahl || a.titel.localeCompare(b.titel, 'de'));
  }

  function aktualisiereTagSprung() {
    if (!el.fokus) return;
    const tags = tagListe();
    el.fokus.hidden = tags.length === 0;
    if (el.fokusLabel) el.fokusLabel.textContent = state.tagFilter ? 'Tag-Fokus' : 'Tag-Sprung';
    if (el.tagAktiv) {
      const aktiv = state.tagFilter ? tags.find(t => t.id === state.tagFilter) : null;
      el.tagAktiv.hidden = !aktiv;
      el.tagAktiv.textContent = aktiv ? `${aktiv.titel} · ${aktiv.anzahl} ${aktiv.anzahl === 1 ? 'Notiz' : 'Notizen'}` : '';
    }
    if (el.fokusClear) el.fokusClear.hidden = !state.tagFilter;
    if (el.tagSuche) el.tagSuche.placeholder = state.tagFilter ? 'Anderen Tag suchen … (/)' : 'Tag suchen … (/)';
  }

  function tagSucheFilter() {
    const q = (el.tagSuche?.value || '').trim().toLowerCase();
    return tagListe().filter(t => !q || t.titel.toLowerCase().includes(q));
  }

  function aktualisiereTagSuchKnopf() {
    if (el.tagSucheClear && el.tagSuche) el.tagSucheClear.hidden = !el.tagSuche.value;
  }

  function rendereTagOptionen() {
    aktualisiereTagSuchKnopf();
    if (!el.tagOptionen) return;
    tagAktivIndex = -1;
    const tags = tagSucheFilter();
    el.tagOptionen.innerHTML = tags.length
      ? tags.map((t, i) => `<button type="button" role="option" aria-selected="false" id="vaultTagOption${i}" data-tag-id="${esc(t.id)}">
          <span>${esc(t.titel)}</span><small>${t.anzahl} ${t.anzahl === 1 ? 'Notiz' : 'Notizen'}</small></button>`).join('')
      : '<div class="leer">Kein Tag gefunden.</div>';
  }

  function oeffneTagOptionen() {
    if (!el.fokus || el.fokus.hidden || !el.tagOptionen) return;
    rendereTagOptionen();
    el.tagOptionen.hidden = false;
    if (el.tagSuche) el.tagSuche.setAttribute('aria-expanded', 'true');
  }

  function schliesseTagOptionen() {
    if (el.tagOptionen) el.tagOptionen.hidden = true;
    if (el.tagSuche) {
      el.tagSuche.setAttribute('aria-expanded', 'false');
      el.tagSuche.removeAttribute('aria-activedescendant');
    }
    aktualisiereTagSuchKnopf();
    tagAktivIndex = -1;
  }

  function markiereTagOption(index) {
    if (!el.tagOptionen || !el.tagSuche) return;
    const buttons = [...el.tagOptionen.querySelectorAll('button[data-tag-id]')];
    if (!buttons.length) return;
    tagAktivIndex = (index + buttons.length) % buttons.length;
    buttons.forEach((b, i) => {
      b.classList.toggle('aktiv', i === tagAktivIndex);
      b.setAttribute('aria-selected', i === tagAktivIndex ? 'true' : 'false');
    });
    const aktiv = buttons[tagAktivIndex];
    el.tagSuche.setAttribute('aria-activedescendant', aktiv.id);
    aktiv.scrollIntoView({ block: 'nearest' });
  }

  function tagSucheTaste(ev) {
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      if (el.tagOptionen.hidden) oeffneTagOptionen();
      const buttons = [...el.tagOptionen.querySelectorAll('button[data-tag-id]')];
      if (!buttons.length) return;
      const next = tagAktivIndex < 0
        ? (ev.key === 'ArrowDown' ? 0 : buttons.length - 1)
        : tagAktivIndex + (ev.key === 'ArrowDown' ? 1 : -1);
      markiereTagOption(next);
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      if (!el.tagOptionen || el.tagOptionen.hidden) return;
      const buttons = [...el.tagOptionen.querySelectorAll('button[data-tag-id]')];
      const ziel = buttons[tagAktivIndex >= 0 ? tagAktivIndex : 0];
      if (ziel) sprungZuTag(ziel.dataset.tagId);
    } else if (ev.key === 'Escape') {
      ev.preventDefault();
      el.tagSuche.value = '';
      schliesseTagOptionen();
      el.tagSuche.blur();
    } else if (ev.key === 'Tab') {
      schliesseTagOptionen();
    }
  }

  function sprungZuTag(id) {
    if (!id) return;
    if (el.tagSuche) el.tagSuche.value = '';
    schliesseTagOptionen();
    let n = state.byId.get(id);
    if (!n) {
      state.tags = true;
      if (el.tags) el.tags.checked = true;
      rebuildGraph();
      layout(false);
      updateLegende();
      updateMeta();
      n = state.byId.get(id);
    }
    if (n) tagFokusSetzen(n);
    else aktualisiereTagSprung();
  }

  function updateLegende() {
    if (!el.legend) return;
    const ordner = state.daten?.ordner || [];
    const st = state.daten?.statistik || {};
    el.legend.innerHTML = ordner
      .map(o => `<span><i style="background:${FARBEN[o.name] || '#ab9cc9'}"></i>${esc(o.name)} ${o.anzahl}</span>`)
      .join('') + (st.unaufgeloest
        ? `<span><i style="background:${FARBEN['Unaufgelöst']}"></i>unaufgelöst ${st.unaufgeloest}</span>` : '') +
      (state.tags && state.tagAnzahl
        ? `<span><i style="background:${FARBEN.Tags}"></i>Tags ${state.tagAnzahl}</span>` : '');
  }

  function updateMeta() {
    if (!state.daten || !el.tag) return;
    const st = state.daten.statistik || {};
    el.tag.textContent = `${st.notizen || 0} Notizen · ${st.links || 0} Links` +
      (st.unaufgeloest ? ` · ${st.unaufgeloest} unaufgelöst` : '') +
      (state.tags ? ` · ${state.tagAnzahl} Tags` : '');
    updateCount();
  }

  function rebuildGraph() {
    const alt = new Map(state.knoten.map(n => [n.id, n]));
    const notizen = (state.basisKnoten || []).map(n => {
      const old = alt.get(n.id);
      return { ...n, x: old?.x, y: old?.y, vx: old?.vx || 0, vy: old?.vy || 0 };
    });
    let kanten = (state.basisKanten || []).map(e => ({ ...e }));
    const tagKnoten = new Map();
    if (state.tags) {
      for (const n of notizen) {
        for (const roh of n.tags || []) {
          const tag = String(roh).trim();
          if (!tag) continue;
          const key = tag.toLowerCase();
          let t = tagKnoten.get(key);
          if (!t) {
            const old = alt.get('tag:' + key);
            t = {
              id: 'tag:' + key, titel: '#' + tag, ordner: 'Tags', kategorie: 'tag',
              tags: [tag], erstellt: null, pfad: null, auszug: '', unaufgeloest: false,
              typ: 'tag', _such: ('#' + tag + ' tag ' + tag).toLowerCase(),
              x: old?.x, y: old?.y, vx: 0, vy: 0, anzahl: 0,
            };
            tagKnoten.set(key, t);
          }
          t.anzahl += 1;
          kanten.push({ von: n.id, nach: t.id, art: 'tag' });
        }
      }
    }
    const gesehen = new Set();
    kanten = kanten.filter(e => {
      const key = e.von + '\u0000' + e.nach;
      if (gesehen.has(key)) return false;
      gesehen.add(key);
      return true;
    });
    const knoten = notizen.concat([...tagKnoten.values()]);
    for (const n of knoten) { n.ausgehend = 0; n.eingehend = 0; n.grad = 0; n.wgrad = 0; }
    const byId = new Map(knoten.map(n => [n.id, n]));
    for (const e of kanten) {
      const a = byId.get(e.von), b = byId.get(e.nach);
      if (!a || !b) continue;
      a.ausgehend += 1;
      b.eingehend += 1;
      a.grad += 1;
      b.grad += 1;
      if (e.art !== 'tag') { a.wgrad += 1; b.wgrad += 1; }
    }
    for (const t of tagKnoten.values()) {
      t.auszug = `${t.anzahl} ${t.anzahl === 1 ? 'Notiz teilt' : 'Notizen teilen'} #${t.tags[0]}.`;
    }
    state.knoten = knoten;
    state.kanten = kanten;
    state.byId = byId;
    state.tagAnzahl = tagKnoten.size;
    if (state.selected) {
      const neu = byId.get(state.selected.id);
      state.selected = neu || null;
      if (!neu) renderDetail(null);
    }
  }

  function tagsGeaendert() {
    if (!state.daten) return;
    state.tags = !!(el.tags && el.tags.checked);
    if (!state.tags && state.tagFilter) {
      state.tagFilter = null;
      if (el.tagSuche) el.tagSuche.value = '';
      schliesseTagOptionen();
    }
    rebuildGraph();
    layout(false);
    fitToVisible();
    updateLegende();
    updateMeta();
    aktualisiereTagSprung();
    draw();
  }

  function updateCount() {
    if (el.searchClear && el.search) el.searchClear.hidden = !el.search.value;
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
    if (state.tagFilter) {
      if (n.id === state.tagFilter) return true;
      if (n.typ === 'tag') return false;
      return state.kanten.some(e => e.von === n.id && e.nach === state.tagFilter);
    }
    if (!state.orphans && (n.grad || 0) === 0) return false;
    if (state.folder && n.typ === 'tag') {
      return state.kanten.some(e => e.nach === n.id && state.byId.get(e.von)?.ordner === state.folder);
    }
    if (state.folder && n.ordner !== state.folder) return false;
    return true;
  }

  function istTreffer(n) {
    return !state.search || (n._such || '').includes(state.search);
  }

  function filterGeaendert() {
    const ordner = el.folder ? el.folder.value : '';
    if (state.tagFilter && ordner !== state.folder) {
      state.tagFilter = null;
      if (el.tagSuche) el.tagSuche.value = '';
      schliesseTagOptionen();
    }
    state.folder = ordner;
    state.orphans = el.orphans ? el.orphans.checked : true;
    state.hover = null;
    hideTip();
    if (state.selected && !sichtbar(state.selected)) {
      state.selected = null;
      renderDetail(null);
    }
    fitToVisible();
    updateCount();
    aktualisiereTagSprung();
    draw();
  }

  function tagFokusSetzen(n) {
    if (!n || n.typ !== 'tag') return;
    if (state.tagFilter === n.id) { entferneTagFokus(); return; }
    state.tagFilter = n.id;
    state.selected = n;
    if (el.search) el.search.value = '';
    state.search = '';
    if (el.folder) el.folder.value = '';
    state.folder = '';
    state.hover = null;
    hideTip();
    if (el.tagSuche) el.tagSuche.value = '';
    schliesseTagOptionen();
    aktualisiereTagSprung();
    renderDetail(n);
    fitToVisible();
    updateCount();
    draw();
  }

  function entferneTagFokus() {
    if (!state.tagFilter) return;
    state.tagFilter = null;
    if (el.tagSuche) el.tagSuche.value = '';
    schliesseTagOptionen();
    if (state.selected && state.selected.typ === 'tag') {
      state.selected = null;
      renderDetail(null);
    }
    aktualisiereTagSprung();
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
    state.tags = true;
    state.tagFilter = null;
    if (el.tags) el.tags.checked = true;
    if (el.tagSuche) el.tagSuche.value = '';
    schliesseTagOptionen();
    state.selected = null;
    state.hover = null;
    hideTip();
    rebuildGraph();
    layout(true);
    renderDetail(null);
    fitToVisible();
    updateLegende();
    updateMeta();
    aktualisiereTagSprung();
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

  /* ---------- Obsidian-Look: Hilfen ---------- */
  const glowCache = new Map();
  function hexA(hex, a) {
    const v = parseInt(String(hex).slice(1, 7), 16);
    return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${a})`;
  }
  function mix(a, b, f) {
    const p = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
    const x = p(a), y = p(b);
    return '#' + x.map((v, i) => Math.round(v + (y[i] - v) * f).toString(16).padStart(2, '0')).join('');
  }
  function glow(color) {
    let c = glowCache.get(color);
    if (c) return c;
    c = document.createElement('canvas');
    c.width = c.height = 64;
    const g = c.getContext('2d');
    const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, hexA(color, .6));
    gr.addColorStop(.3, hexA(color, .22));
    gr.addColorStop(1, hexA(color, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, 64, 64);
    glowCache.set(color, c);
    return c;
  }
  const ruhig = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- Live-Physik ---------- */
  const sim = { alpha: 0, raf: 0 };
  state.zentren = new Map();

  function clusterZentren() {
    const anzahl = new Map();
    for (const k of state.knoten) if (k.typ !== 'tag') anzahl.set(k.ordner, (anzahl.get(k.ordner) || 0) + 1);
    const namen = [...anzahl.keys()].sort();
    const R = namen.length > 1 ? 70 + Math.sqrt(state.knoten.length) * 24 : 0;
    state.zentren = new Map(namen.map((o, i) => {
      const a = 2 * Math.PI * i / namen.length - Math.PI / 2;
      return [o, { x: Math.cos(a) * R, y: Math.sin(a) * R, n: anzahl.get(o) }];
    }));
  }

  function nachbarn() {
    const m = new Map();
    for (const e of state.kanten) {
      if (!m.has(e.von)) m.set(e.von, []);
      if (!m.has(e.nach)) m.set(e.nach, []);
      m.get(e.von).push(e.nach);
      m.get(e.nach).push(e.von);
    }
    return m;
  }

  function platziere(k, nb) {
    const h = hash(k.id), a = (h % 6283) / 1000, j = ((h >>> 12) % 1000) / 1000;
    const gesetzt = (nb.get(k.id) || []).map(id => state.byId.get(id)).filter(z => z && Number.isFinite(z.x));
    if (gesetzt.length) {
      const mx = gesetzt.reduce((s, z) => s + z.x, 0) / gesetzt.length;
      const my = gesetzt.reduce((s, z) => s + z.y, 0) / gesetzt.length;
      k.x = mx + Math.cos(a) * (12 + j * 18);
      k.y = my + Math.sin(a) * (12 + j * 18);
    } else {
      const z = state.zentren.get(k.ordner) || { x: 0, y: 0, n: 1 };
      const r = (8 + Math.sqrt(z.n || 1) * 9) * Math.sqrt(j);
      k.x = z.x + Math.cos(a) * r;
      k.y = z.y + Math.sin(a) * r;
    }
    k.vx = 0; k.vy = 0;
  }

  function layout(voll) {
    if (!state.knoten.length) return;
    clusterZentren();
    if (voll) state.knoten.forEach(k => { k.x = undefined; k.y = undefined; });
    const nb = nachbarn();
    const offen = state.knoten.filter(k => !Number.isFinite(k.x) || !Number.isFinite(k.y));
    offen.filter(k => k.typ !== 'tag').forEach(k => platziere(k, nb));
    offen.filter(k => k.typ === 'tag').forEach(k => platziere(k, nb));
    if (voll || ruhig()) {
      let a = 1;
      for (let i = 0; i < 260; i++) { schritt(a); a *= 0.982; }
      wecke(0.05);
    } else {
      wecke(offen.length ? 0.35 : 0.12);
    }
  }

  function schritt(alpha) {
    const ks = state.knoten, n = ks.length;
    if (!n) return;
    const ZELLE = 90, grid = new Map();
    for (const k of ks) {
      const key = Math.floor(k.x / ZELLE) + ',' + Math.floor(k.y / ZELLE);
      let l = grid.get(key);
      if (!l) grid.set(key, l = []);
      l.push(k);
    }
    // Abstossung (nur Nachbarzellen, darum auch bei Tausenden Notizen schnell)
    for (const k of ks) {
      const cx = Math.floor(k.x / ZELLE), cy = Math.floor(k.y / ZELLE);
      for (let gx = cx - 1; gx <= cx + 1; gx++) for (let gy = cy - 1; gy <= cy + 1; gy++) {
        const l = grid.get(gx + ',' + gy);
        if (!l) continue;
        for (const o of l) {
          if (o === k) continue;
          let dx = k.x - o.x, dy = k.y - o.y;
          let d2 = dx * dx + dy * dy;
          if (d2 > ZELLE * ZELLE) continue;
          if (d2 < 0.01) { dx = (hash(k.id) % 7) - 3 || 1; dy = 1; d2 = dx * dx + dy * dy; }
          const d = Math.sqrt(d2);
          let f = 900 / Math.max(d2, 16) * alpha;
          const min = radius(k) + radius(o) + 3;
          if (d < min) f += (min - d) * 0.25;
          k.vx += dx / d * f; k.vy += dy / d * f;
        }
      }
    }
    // Links ziehen zusammen
    for (const e of state.kanten) {
      const a = state.byId.get(e.von), b = state.byId.get(e.nach);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const L = e.art === 'tag' ? 36 : 44;
      const ga = Math.max(1, a.grad || 1), gb = Math.max(1, b.grad || 1);
      // Wie in Obsidian: stark verlinkte Knoten (Hubs) bewegen sich weniger,
      // damit nicht alles zu einem einzigen Klumpen zusammengezogen wird.
      const f = (d - L) / d * 0.09 * alpha * clamp(1 / Math.min(ga, gb), 0.2, 1);
      const anteilA = gb / (ga + gb), anteilB = ga / (ga + gb);
      a.vx += dx * f * anteilA * 2; a.vy += dy * f * anteilA * 2;
      b.vx -= dx * f * anteilB * 2; b.vy -= dy * f * anteilB * 2;
    }
    // Gruppen: jede Notiz zieht zu ihrem Ordner, alles leicht zur Mitte
    for (const k of ks) {
      const z = k.typ !== 'tag' ? state.zentren.get(k.ordner) : null;
      if (z) { k.vx += (z.x - k.x) * 0.02 * alpha; k.vy += (z.y - k.y) * 0.02 * alpha; }
      k.vx += -k.x * 0.0025 * alpha; k.vy += -k.y * 0.0025 * alpha;
    }
    for (const k of ks) {
      if (k.fx != null) { k.x = k.fx; k.y = k.fy; k.vx = 0; k.vy = 0; continue; }
      k.vx = clamp(k.vx * 0.62, -8, 8);
      k.vy = clamp(k.vy * 0.62, -8, 8);
      k.x += k.vx; k.y += k.vy;
    }
  }

  function wecke(a) {
    sim.alpha = Math.max(sim.alpha, a);
    if (!sim.raf) sim.raf = requestAnimationFrame(schleife);
  }

  function schleife() {
    sim.raf = 0;
    const kb = document.getElementById('v-kb');
    if (!kb || kb.hidden || !state.geladen) return;
    let weiter = false;
    if (sim.alpha > 0.004 || state.drag) {
      if (!ruhig() || state.drag) schritt(Math.max(sim.alpha, state.drag ? 0.12 : 0));
      sim.alpha *= 0.985;
      if (!ruhig()) weiter = true;
    }
    const jetzt = performance.now();
    if (state.knoten.some(n => n._neu && jetzt - n._neu < 4000)) weiter = true;
    draw();
    if (weiter || state.drag) sim.raf = requestAnimationFrame(schleife);
  }

  /* ---------- Neue Notizen automatisch holen ---------- */
  let nachladeTimer = null;
  function starteNachladen() {
    if (nachladeTimer) return;
    nachladeTimer = setInterval(() => {
      const kb = document.getElementById('v-kb');
      if (document.hidden || !kb || kb.hidden || state.laedt || state.drag || !state.daten) return;
      nachladen();
    }, 30000);
  }
  function signatur(d) {
    return (d.knoten || []).map(n => n.id + ':' + (n.tags || []).join(',')).sort().join('|') + '#' +
      (d.kanten || []).map(e => e.von + '>' + e.nach).sort().join('|');
  }
  async function nachladen() {
    try {
      const r = await fetch('/api/vault/graph', { cache: 'no-store' });
      const d = await r.json();
      if (!r.ok || !d.ok) return;
      if (state.daten && signatur(d) === signatur(state.daten)) return;
      const alteIds = new Set(state.basisKnoten.map(n => n.id));
      state.daten = d;
      state.basisKnoten = (d.knoten || []).map(n => ({
        ...n,
        _such: [n.titel, n.ordner, n.kategorie, ...(n.tags || []), n.auszug].filter(Boolean).join(' ').toLowerCase(),
      }));
      state.basisKanten = (d.kanten || []).map(e => ({ ...e }));
      rebuildGraph();
      const jetzt = performance.now();
      state.knoten.forEach(n => { if (n.typ !== 'tag' && !alteIds.has(n.id)) n._neu = jetzt; });
      layout(false);
      const ordner = state.folder;
      baueFilter();
      if (el.folder) el.folder.value = ordner;
      if (el.folder && el.folder.value !== ordner) state.folder = '';
      updateMeta();
      if (state.selected) renderDetail(state.selected);
      if (el.empty) el.empty.hidden = state.knoten.length > 0;
      if (el.canvas) el.canvas.hidden = state.knoten.length === 0;
      if (!state.userMoved) fitToVisible();
      draw();
    } catch (_) { /* nächster Versuch in 30 Sekunden */ }
  }

  /* ---------- Minimap ---------- */
  function miniSprung(p) {
    const m = state.mini;
    if (!m) return;
    const wx = (p.x - m.x - m.ox) / m.s + m.minX;
    const wy = (p.y - m.y - m.oy) / m.s + m.minY;
    state.t.x = state.width / 2 - wx * state.t.k;
    state.t.y = state.height / 2 - wy * state.t.k;
    state.userMoved = true;
    draw();
  }
  function inMini(p) {
    const m = state.mini;
    return m && p.x >= m.x && p.x <= m.x + m.w && p.y >= m.y && p.y <= m.y + m.h;
  }
  function zeichneMini(ctx, vis) {
    state.mini = null;
    if (state.width < 520 || state.height < 320 || !vis.length) return;
    const w = 150, h = 108, x = state.width - w - 14, y = state.height - h - 58;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of vis) { minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x); minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y); }
    minX -= 20; minY -= 20; maxX += 20; maxY += 20;
    const s = Math.min((w - 10) / (maxX - minX), (h - 10) / (maxY - minY));
    const ox = (w - (maxX - minX) * s) / 2, oy = (h - (maxY - minY) * s) / 2;
    state.mini = { x, y, w, h, s, ox, oy, minX, minY };
    ctx.fillStyle = 'rgba(16,14,24,.88)';
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = 'rgba(255,255,255,.14)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x + .5, y + .5, w - 1, h - 1);
    for (const n of vis) {
      ctx.fillStyle = n.typ === 'tag' || (n.wgrad || 0) >= 3 ? (FARBEN[n.ordner] || '#ab9cc9') : 'rgba(220,214,235,.75)';
      ctx.fillRect(x + ox + (n.x - minX) * s - .75, y + oy + (n.y - minY) * s - .75, 1.5, 1.5);
    }
    const a = world({ x: 0, y: 0 }), b = world({ x: state.width, y: state.height });
    const rx = clamp(x + ox + (a.x - minX) * s, x, x + w), ry = clamp(y + oy + (a.y - minY) * s, y, y + h);
    const rx2 = clamp(x + ox + (b.x - minX) * s, x, x + w), ry2 = clamp(y + oy + (b.y - minY) * s, y, y + h);
    ctx.strokeStyle = '#38e8ff';
    ctx.strokeRect(rx + .5, ry + .5, Math.max(2, rx2 - rx - 1), Math.max(2, ry2 - ry - 1));
  }

  function radius(n) {
    // Bei vielen Notizen kleinere Punkte, damit Wolken wie in Obsidian entstehen
    const f = state.knoten.length > 300 ? .6 : state.knoten.length > 120 ? .8 : 1;
    if (n.typ === 'tag') return f * (2.6 + Math.min(3.4, Math.sqrt(n.grad || 0) * .8));
    return f * (n.unaufgeloest ? 2.2 : 2.6 + Math.min(5, Math.sqrt(n.wgrad || 0) * 1.6));
  }

  function draw() {
    if (!el.ctx) return;
    const ctx = el.ctx, W = state.width, H = state.height, k = state.t.k;
    ctx.setTransform(state.dpr, 0, 0, state.dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#100f17';
    ctx.fillRect(0, 0, W, H);
    // Raster wie in Obsidian
    let s = 40 * k;
    while (s < 18) s *= 2;
    while (s > 90) s /= 2;
    ctx.strokeStyle = 'rgba(255,255,255,.04)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = ((state.t.x % s) + s) % s; x < W; x += s) { ctx.moveTo(Math.round(x) + .5, 0); ctx.lineTo(Math.round(x) + .5, H); }
    for (let y = ((state.t.y % s) + s) % s; y < H; y += s) { ctx.moveTo(0, Math.round(y) + .5); ctx.lineTo(W, Math.round(y) + .5); }
    ctx.stroke();
    if (!state.geladen || !state.knoten.length) return;

    const visListe = state.knoten.filter(sichtbar);
    const vis = new Set(visListe.map(n => n.id));
    const fokus = state.drag ? state.drag.n : (state.hover || state.selected);
    const nb = new Set();
    if (fokus) for (const e of state.kanten) {
      if (e.von === fokus.id) nb.add(e.nach);
      if (e.nach === fokus.id) nb.add(e.von);
    }
    const jetzt = performance.now();
    ctx.save();
    ctx.translate(state.t.x, state.t.y);
    ctx.scale(k, k);

    // Kanten: normal, gedimmt, hervorgehoben
    const pfade = { normal: new Path2D(), dim: new Path2D(), hi: new Path2D() };
    for (const e of state.kanten) {
      const a = state.byId.get(e.von), b = state.byId.get(e.nach);
      if (!a || !b || !vis.has(a.id) || !vis.has(b.id)) continue;
      let p = pfade.normal;
      if (fokus) p = (e.von === fokus.id || e.nach === fokus.id) ? pfade.hi : pfade.dim;
      else if (state.search && (!istTreffer(a) || !istTreffer(b))) p = pfade.dim;
      p.moveTo(a.x, a.y);
      p.lineTo(b.x, b.y);
    }
    ctx.lineWidth = 1 / k;
    ctx.strokeStyle = 'rgba(170,160,200,.05)'; ctx.stroke(pfade.dim);
    ctx.strokeStyle = 'rgba(170,160,200,.22)'; ctx.stroke(pfade.normal);
    ctx.lineWidth = 1.4 / k;
    ctx.strokeStyle = 'rgba(94,242,255,.85)'; ctx.stroke(pfade.hi);

    // Knoten
    for (const n of visListe) {
      let alpha = 1;
      if (state.search && !istTreffer(n)) alpha = 0.12;
      if (fokus && n !== fokus && !nb.has(n.id)) alpha = Math.min(alpha, 0.16);
      const istFokus = fokus && n.id === fokus.id;
      const r = radius(n) * (istFokus ? 1.3 : 1);
      const basis = FARBEN[n.ordner] || '#ab9cc9';
      const wichtig = n.typ === 'tag' || (n.wgrad || 0) >= 3;
      const farbe = n.unaufgeloest ? '#5d5470' : wichtig ? basis : mix(basis, '#dcd8e6', .78);
      ctx.globalAlpha = alpha;
      if (istFokus || (fokus && nb.has(n.id)) || (wichtig && !n.unaufgeloest)) {
        const R = r * (istFokus ? 8 : 4.6);
        ctx.drawImage(glow(istFokus ? '#5ef2ff' : basis), n.x - R, n.y - R, R * 2, R * 2);
      }
      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = istFokus ? '#e9fbff' : farbe;
      ctx.fill();
      if (n.unaufgeloest) {
        ctx.strokeStyle = '#8f7ba8';
        ctx.lineWidth = 1 / k;
        ctx.stroke();
      }
      if (istFokus) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 3 / k, 0, Math.PI * 2);
        ctx.strokeStyle = '#5ef2ff';
        ctx.lineWidth = 1.6 / k;
        ctx.stroke();
      }
      if (n._neu) {
        const p = (jetzt - n._neu) / 4000;
        if (p < 1) {
          ctx.globalAlpha = (1 - p) * 0.9;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r + 4 + p * 26, 0, Math.PI * 2);
          ctx.strokeStyle = '#5ef2c0';
          ctx.lineWidth = 2 / k;
          ctx.stroke();
          const R = r * 7 * (1 - p * .5);
          ctx.drawImage(glow('#5ef2c0'), n.x - R, n.y - R, R * 2, R * 2);
        } else n._neu = 0;
      }
    }

    // Beschriftung unter den Punkten (wie in Obsidian)
    const ab = 2;
    const hubs = new Set(visListe.filter(n => (n.wgrad || 0) >= 4 || n.typ === 'tag').sort((a, b) => (b.grad || 0) - (a.grad || 0)).slice(0, 6).map(n => n.id));
    const fs = 11 / k;
    ctx.font = `${fs}px "Geist Mono", ui-monospace, monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (const n of visListe) {
      if (state.search && !istTreffer(n)) continue;
      const istFokus = fokus && n.id === fokus.id;
      let a = 0;
      if (istFokus) a = 1;
      else if (fokus && nb.has(n.id)) a = .9;
      else if (fokus) a = 0;
      else a = Math.max(clamp((k - ab) / .5, 0, 1), hubs.has(n.id) && k > .7 ? .8 : 0);
      if (a <= 0.02) continue;
      const label = n.titel.length > 34 ? n.titel.slice(0, 32) + '…' : n.titel;
      ctx.globalAlpha = a;
      ctx.fillStyle = 'rgba(10,9,16,.85)';
      ctx.fillText(label, n.x + .8 / k, n.y + radius(n) + 5 / k + .8 / k);
      ctx.fillStyle = istFokus ? '#ffffff' : (n.unaufgeloest ? '#a99bbd' : '#d9d3e8');
      ctx.fillText(label, n.x, n.y + radius(n) + 5 / k);
    }
    ctx.restore();
    ctx.globalAlpha = 1;
    ctx.textAlign = 'start';
    ctx.textBaseline = 'alphabetic';
    zeichneMini(ctx, visListe);
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
    if (inMini(p)) {
      state.miniDrag = true;
      miniSprung(p);
      try { el.canvas.setPointerCapture(ev.pointerId); } catch (_) {}
      return;
    }
    const n = pick(p.x, p.y);
    if (n) {
      state.selected = n;
      state.drag = { n, ox: p.x, oy: p.y, nx: n.x, ny: n.y, moved: false };
      n.fx = n.x; n.fy = n.y;
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
    if (state.miniDrag) { miniSprung(p); return; }
    if (state.drag) {
      state.userMoved = true;
      if (Math.abs(p.x - state.drag.ox) + Math.abs(p.y - state.drag.oy) > 3) state.drag.moved = true;
      const n = state.drag.n;
      n.fx = n.x = state.drag.nx + (p.x - state.drag.ox) / state.t.k;
      n.fy = n.y = state.drag.ny + (p.y - state.drag.oy) / state.t.k;
      if (state.drag.moved) wecke(0.3);
      draw();
      return;
    }
    if (inMini(p)) {
      if (state.hover) { state.hover = null; draw(); }
      hideTip();
      el.canvas.style.cursor = 'crosshair';
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
    if (state.miniDrag) {
      state.miniDrag = false;
      try { el.canvas.releasePointerCapture(ev.pointerId); } catch (_) {}
      return;
    }
    if (state.drag) { state.drag.n.fx = null; state.drag.n.fy = null; wecke(0.1); }
    if (state.drag && !state.drag.moved && state.drag.n.typ === 'tag') {
      tagFokusSetzen(state.drag.n);
    }
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
    const tags = n.typ === 'tag' ? '' : (n.tags || []).map(t => `<span class="vd-tag">#${esc(t)}</span>`).join('');
    const datum = n.erstellt ? n.erstellt.replace('T', ' ').slice(0, 16) : 'ohne Datum';
    const art = n.typ === 'tag' ? `Tag-Knoten · ${n.anzahl || ein.length} Notizen` :
      n.unaufgeloest ? 'unaufgelöster Link' : 'Notiz';
    el.detail.innerHTML = `
      <div class="vd-kicker">${esc(n.ordner)}</div>
      <h3>${esc(n.titel)}</h3>
      <div class="vd-meta">${n.typ === 'tag' ? esc(art) : esc(datum) + ' · ' + esc(art)}</div>
      ${tags ? `<div class="vd-tags">${tags}</div>` : ''}
      <p class="vd-text">${esc(n.auszug || (n.unaufgeloest ? 'Dieses Linkziel existiert noch nicht im Vault.' : 'Keine Textvorschau.'))}</p>
      ${n.pfad ? `<div class="vd-path">vault/${esc(n.pfad)}</div>` : ''}
      <div class="vd-group"><div class="lbl">Ausgehend (${aus.length})</div>
        ${aus.length ? aus.map(e => link(e.nach)).join('') : `<div class="vd-leer">${n.typ === 'tag' ? 'Keine ausgehenden Verbindungen.' : 'Keine ausgehenden Wikilinks.'}</div>`}
      </div>
      <div class="vd-group"><div class="lbl">Eingehend (${ein.length})</div>
        ${ein.length ? ein.map(e => link(e.von)).join('') : '<div class="vd-leer">Keine Backlinks.</div>'}
      </div>`;
  }

  window.VaultGraph = { aktivieren };
})();
