/**
 * Weltkugel in 2D — Canvas, ohne WebGL.
 *
 * Alle Knoten, Kanten, Quellen und Zahlen kommen aus /api/globe. Gezeichnet
 * wird nur, was dort steht: keine erfundenen Signale, keine Daueraktivität.
 * Die Kugel dreht sich langsam; Knoten leuchten in ihrer Kategorie-Farbe.
 */
export class IntelligenceGlobe {
  constructor(stage) {
    this.stage = stage;
    this.canvas = stage.querySelector('#globeCanvas');
    this.ctx = this.canvas.getContext('2d');
    this.dom = {
      sources: document.getElementById('globeSources'),
      sourceTotal: document.getElementById('globeSourceTotal'),
      sourceCount: document.getElementById('globeSourceCount'),
      departments: document.getElementById('globeDepartments'),
      deptTotal: document.getElementById('globeDeptTotal'),
      activity: document.getElementById('globeActivity'),
      activityDetail: document.getElementById('globeActivityDetail'),
      nodeCount: document.getElementById('globeNodeCount'),
      edgeCount: document.getElementById('globeEdgeCount'),
      sourceCountTop: document.getElementById('globeSourceCountTop'),
      meta: document.getElementById('globeMeta'),
      detail: document.getElementById('globeDetail'),
      empty: document.getElementById('globeEmpty'),
      legend: document.getElementById('globeLegend'),
      mode: document.getElementById('globeMode'),
      modeDetail: document.getElementById('globeModeDetail'),
      hint: document.getElementById('globeHint'),
    };
    this.data = null;
    this.nodes = [];
    this.rotation = 0;
    this.active = false;
    this.selected = null;
    this.frame = null;
    this._resize = this._resize.bind(this);
    this._tick = this._tick.bind(this);
    window.addEventListener('resize', this._resize);
    this.canvas.addEventListener('pointermove', (e) => this._hover(e));
    this.canvas.addEventListener('pointerleave', () => this._hover(null));
    this.canvas.addEventListener('click', (e) => this._click(e));
    this._resize();
  }

  setActive(aktiv) {
    this.active = Boolean(aktiv);
    if (this.active && !this.frame) this.frame = requestAnimationFrame(this._tick);
    if (!this.active && this.frame) {
      cancelAnimationFrame(this.frame);
      this.frame = null;
    }
  }

  setData(data) {
    this.data = data || null;
    this._aufbau();
    this._rails();
    this._resize();
    this._zeichnen();
  }

  showError(message) {
    if (this.dom.empty) {
      this.dom.empty.hidden = false;
      this.dom.empty.innerHTML = `<b>INTELLIGENCE-GRAPH NICHT VERFÜGBAR</b><span>${esc(message)}</span>`;
    }
  }

  _resize() {
    const rect = this.stage.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.w = Math.max(320, Math.round(rect.width));
    this.h = Math.max(320, Math.round(rect.height));
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._zeichnen();
  }

  _aufbau() {
    const liste = (this.data && this.data.nodes) || [];
    this.nodes = liste.map((n, i) => {
      const h = hash(String(n.id || i));
      const lat = -1.15 + (h % 2000) / 2000 * 2.3;
      const lon = ((h >>> 7) % 3600) / 10;
      return { ...n, lat, lon, idx: i };
    });
    this.pos = new Map();
    this.edgeListe = (this.data && this.data.edges) || [];
  }

  _projekt(lat, lon, cx, cy, r) {
    const l = lon + this.rotation;
    const z = Math.cos(lat) * Math.cos(l);
    return {
      x: cx + r * Math.cos(lat) * Math.sin(l),
      y: cy - r * Math.sin(lat),
      z,
    };
  }

  _tick() {
    if (!this.active) { this.frame = null; return; }
    this.rotation += 0.0016;
    this._zeichnen();
    this.frame = requestAnimationFrame(this._tick);
  }

  _zeichnen() {
    const ctx = this.ctx;
    if (!ctx || !this.w) return;
    const cx = this.w / 2, cy = this.h / 2;
    const r = Math.min(this.w, this.h) * 0.34;
    ctx.clearRect(0, 0, this.w, this.h);

    // Sterne / Tiefe
    ctx.save();
    for (let i = 0; i < 90; i++) {
      const x = (hash('s' + i) % 1000) / 1000 * this.w;
      const y = (hash('t' + i) % 1000) / 1000 * this.h;
      ctx.globalAlpha = 0.12 + ((hash('a' + i) % 100) / 100) * 0.2;
      ctx.fillStyle = i % 7 === 0 ? '#38e8ff' : '#ff9ad4';
      ctx.fillRect(x, y, 1.2, 1.2);
    }
    ctx.restore();

    // Kugel aus Punkten
    ctx.save();
    for (let lat = -80; lat <= 80; lat += 8) {
      for (let lon = 0; lon < 360; lon += 8) {
        const p = this._projekt(lat * Math.PI / 180, lon * Math.PI / 180, cx, cy, r);
        if (p.z < 0.05) continue;
        ctx.globalAlpha = 0.10 + p.z * 0.35;
        ctx.fillStyle = '#38e8ff';
        ctx.fillRect(p.x, p.y, 1.1, 1.1);
      }
    }
    ctx.restore();

    // Kanten
    if (this.data && this.edgeListe.length) {
      const pos = new Map();
      for (const n of this.nodes) {
        const p = this._projekt(n.lat, n.lon, cx, cy, r);
        pos.set(n.id, p);
        this.pos.set(n.id, p);
      }
      ctx.save();
      ctx.lineWidth = 1;
      for (const e of this.edgeListe) {
        const a = pos.get(e.from), b = pos.get(e.to);
        if (!a || !b || a.z < 0 || b.z < 0) continue;
        ctx.strokeStyle = e.active ? 'rgba(255,63,164,.55)' : 'rgba(56,232,255,.22)';
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        const nx = mx + (cx - mx) * 0.18, ny = my + (cy - my) * 0.18;
        ctx.quadraticCurveTo(nx, ny, b.x, b.y);
        ctx.stroke();
      }
      ctx.restore();
    }

    // Knoten als Rauten
    for (const n of this.nodes) {
      const p = this._projekt(n.lat, n.lon, cx, cy, r);
      this.pos.set(n.id, p);
      if (p.z < 0) continue;
      const groesse = 3.4 + Math.min(4, Number(n.relevance || 0.4) * 6);
      ctx.save();
      ctx.globalAlpha = 0.55 + p.z * 0.45;
      ctx.translate(p.x, p.y);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = n.color || '#38e8ff';
      ctx.shadowColor = n.color || '#38e8ff';
      ctx.shadowBlur = 10;
      ctx.fillRect(-groesse / 2, -groesse / 2, groesse, groesse);
      if (this.selected === n.id) {
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.2;
        ctx.strokeRect(-groesse, -groesse, groesse * 2, groesse * 2);
      }
      ctx.restore();
    }

    // Ring aussen
    ctx.save();
    ctx.strokeStyle = 'rgba(56,232,255,.18)';
    ctx.setLineDash([2, 6]);
    ctx.beginPath();
    ctx.arc(cx, cy, r * 1.28, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  _treffer(e) {
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left, y = e.clientY - rect.top;
    let best = null, dist = 14;
    for (const n of this.nodes) {
      const p = this.pos.get(n.id);
      if (!p || p.z < 0) continue;
      const d = Math.hypot(p.x - x, p.y - y);
      if (d < dist) { dist = d; best = n; }
    }
    return best;
  }

  _hover(e) {
    const n = e ? this._treffer(e) : null;
    this.canvas.style.cursor = n ? 'pointer' : 'grab';
    if (n && this.dom.detail) {
      this.dom.detail.hidden = false;
      this.dom.detail.innerHTML = `<b>${esc(n.title || n.id)}</b>
        <span>${esc(n.summary || n.detail || '')}</span>
        <small>${esc(n.source || '')}${n.time ? ' · ' + esc(String(n.time).replace('T', ' ').slice(0, 16)) : ''}</small>`;
    }
  }

  _click(e) {
    const n = this._treffer(e);
    if (!n) return;
    this.selected = n.id;
    if (this.dom.detail) {
      this.dom.detail.hidden = false;
      this.dom.detail.innerHTML = `<b>${esc(n.title || n.id)}</b>
        <span>${esc(n.detail || n.summary || '')}</span>
        <small>${esc(n.source || '')}${n.status ? ' · ' + esc(n.status) : ''}</small>`;
    }
    this._zeichnen();
  }

  _rails() {
    const d = this.data || {};
    const quellen = d.sources || [];
    const abteilungen = d.departments || [];
    const counts = d.counts || {};
    const activity = d.activity || {};
    if (this.dom.sources) {
      this.dom.sources.innerHTML = quellen.map(q => `<div class="globe-rail-item">
        <span class="globe-rail-dot" style="background:${esc(q.color || '#38e8ff')}"></span>
        <span class="globe-rail-name">${esc(q.name)}</span>
        <span class="globe-rail-count">${q.count ?? 0}</span>
      </div>`).join('') || '<div class="globe-rail-empty">Keine Quelle verbunden.</div>';
    }
    if (this.dom.departments) {
      this.dom.departments.innerHTML = abteilungen.map(a => `<div class="globe-rail-item">
        <span class="globe-rail-dot" style="background:${esc(a.color || '#38e8ff')}"></span>
        <span class="globe-rail-name">${esc(a.name)}</span>
        <span class="globe-rail-count">${a.agent_runs ?? 0}</span>
      </div>`).join('') || '<div class="globe-rail-empty">Keine Abteilung aktiv.</div>';
    }
    const setz = (el, wert) => { if (el) el.textContent = wert; };
    setz(this.dom.sourceTotal, quellen.length);
    setz(this.dom.sourceCount, quellen.length);
    setz(this.dom.sourceCountTop, quellen.length);
    setz(this.dom.deptTotal, abteilungen.length);
    setz(this.dom.nodeCount, counts.nodes ?? (d.nodes || []).length);
    setz(this.dom.edgeCount, counts.edges ?? (d.edges || []).length);
    setz(this.dom.activity, activity.label || '—');
    setz(this.dom.activityDetail, activity.detail || '');
    setz(this.dom.meta, `Stand ${String(d.generated_at || '').replace('T', ' ').slice(0, 16)} · Zeitraum ${(d.window && d.window.label) || '—'}`);
    if (this.dom.mode) {
      this.dom.mode.classList.toggle('is-demo', Boolean(d.demo));
      const b = this.dom.mode.querySelector('b');
      if (b) b.textContent = d.demo ? 'DEMO' : 'LIVE';
    }
    if (this.dom.modeDetail) this.dom.modeDetail.textContent = d.demo ? (d.demo_hinweis || 'Demodaten') : 'Daten aus SQLite';
    if (this.dom.legend) {
      this.dom.legend.innerHTML = (d.legend || []).map(l => `<span><i class="globe-swatch" style="background:${esc(l.color)}"></i>${esc(l.label)}</span>`).join('');
    }
    if (this.dom.empty) this.dom.empty.hidden = true;
  }
}

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
