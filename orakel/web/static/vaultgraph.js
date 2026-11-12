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
    else { resize(); draw(); }
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
      state.tags = false;
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
      if (el.tags) el.tags.checked = false;
      if (el.tagSuche) el.tagSuche.value = '';
      schliesseTagOptionen();
      rebuildGraph();
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
      layout();
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
    for (const n of knoten) { n.ausgehend = 0; n.eingehend = 0; n.grad = 0; }
    const byId = new Map(knoten.map(n => [n.id, n]));
    for (const e of kanten) {
      const a = byId.get(e.von), b = byId.get(e.nach);
      if (!a || !b) continue;
      a.ausgehend += 1;
      b.eingehend += 1;
      a.grad += 1;
      b.grad += 1;
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
    layout();
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
    state.tags = false;
    state.tagFilter = null;
    if (el.tags) el.tags.checked = false;
    if (el.tagSuche) el.tagSuche.value = '';
    schliesseTagOptionen();
    state.selected = null;
    state.hover = null;
    hideTip();
    rebuildGraph();
    layout();
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
    if (n.typ === 'tag') return 3.8 + Math.min(4.2, Math.sqrt(n.grad || 0) * 1.8);
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
      ctx.strokeStyle = sel && (e.von === sel.id || e.nach === sel.id) ? '#38e8ff' :
        (e.art === 'tag' ? '#c9a7ff' : '#9b7fc2');
      ctx.lineWidth = 1.35 / state.t.k;
      if (e.art === 'tag') ctx.setLineDash([4 / state.t.k, 4 / state.t.k]);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (const n of state.knoten) {
      if (!vis.has(n.id)) continue;
      let alpha = 1;
      if (state.search && !istTreffer(n)) alpha = 0.16;
      if (sel && n.id !== sel.id && !nb.has(n.id)) alpha = Math.min(alpha, 0.22);
      const r = radius(n) + (state.hover && state.hover.id === n.id ? 1.2 : 0);
      const color = FARBEN[n.ordner] || '#ab9cc9';
      ctx.globalAlpha = alpha;
      if (n.typ === 'tag') {
        ctx.save();
        ctx.translate(n.x, n.y);
        ctx.rotate(Math.PI / 4);
        ctx.fillStyle = color;
        ctx.fillRect(-r * 0.72, -r * 0.72, r * 1.44, r * 1.44);
        ctx.strokeStyle = 'rgba(255,255,255,.45)';
        ctx.lineWidth = 0.8 / state.t.k;
        ctx.strokeRect(-r * 0.72, -r * 0.72, r * 1.44, r * 1.44);
        ctx.restore();
      } else {
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
      state.drag = { n, ox: p.x, oy: p.y, nx: n.x, ny: n.y, moved: false };
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
      if (Math.abs(p.x - state.drag.ox) + Math.abs(p.y - state.drag.oy) > 3) state.drag.moved = true;
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
