/**
 * Weltkugel in 2D — Canvas, ohne WebGL.
 *
 * Alle Knoten, Kanten, Quellen und Zahlen kommen aus /api/globe. Gezeichnet
 * wird nur, was dort steht: keine erfundenen Signale. Lichtpunkte laufen nur
 * auf Verbindungen, die laut Daten aktiv sind (aktive Kante oder Zähler > 0).
 *
 * Aufbau:
 *  - Quellen (links) und Abteilungen (rechts) sind die Listen neben der Kugel.
 *    Ihre Linien starten genau auf Höhe des jeweiligen Listeneintrags.
 *  - Der Hub ist die Kugel selbst.
 *  - Alle übrigen Knoten liegen auf der Kugeloberfläche und drehen mit.
 */
const TILT_START = -0.38;      // leichte Neigung nach vorne (3D-Eindruck)
const SPIN = 0.0019;           // Rotation pro Bild
const PUNKTE = 1500;           // Punkte der Kugeloberfläche

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
      tooltip: document.getElementById('globeTooltip'),
      empty: document.getElementById('globeEmpty'),
      legend: document.getElementById('globeLegend'),
      mode: document.getElementById('globeMode'),
      modeDetail: document.getElementById('globeModeDetail'),
      hint: document.getElementById('globeHint'),
      reset: document.getElementById('globeReset'),
      spin: document.getElementById('globeToggleSpin'),
    };
    this.data = null;
    this.nodes = [];          // Knoten auf der Kugel
    this.byId = new Map();
    this.edgeListe = [];
    this.anker = new Map();   // Quellen/Abteilungen: Position am Rand
    this.pos = new Map();     // projizierte Positionen der Kugelknoten
    this.yaw = 0;
    this.tilt = TILT_START;
    this.zoom = 1;
    this.spinning = true;
    this.vYaw = 0;
    this.vTilt = 0;
    this.active = false;
    this.selected = null;
    this.hover = null;
    this.frame = null;
    this.zeit = 0;
    this.ruhig = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.kugel = fibonacci(PUNKTE);
    this.gitter = gitterLinien();

    this._resize = this._resize.bind(this);
    this._tick = this._tick.bind(this);
    window.addEventListener('resize', this._resize);
    if (window.ResizeObserver) new ResizeObserver(() => this._resize()).observe(stage);
    this._bedienung();
    this._resize();
  }

  /* ---------- Öffentliche Schnittstelle (unverändert) ---------- */
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
  }

  showError(message) {
    if (this.dom.empty) {
      this.dom.empty.hidden = false;
      this.dom.empty.innerHTML = `<b>INTELLIGENCE-GRAPH NICHT VERFÜGBAR</b><span>${esc(message)}</span>`;
    }
  }

  /* ---------- Bedienung: Ziehen, Zoomen, Knöpfe ---------- */
  _bedienung() {
    const c = this.canvas;
    let drag = null;
    c.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY, yaw: this.yaw, tilt: this.tilt, bewegt: false, t: performance.now() };
      this.vYaw = 0; this.vTilt = 0;
    });
    c.addEventListener('pointermove', (e) => {
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (!drag.bewegt && Math.hypot(dx, dy) > 4) {
          drag.bewegt = true;
          c.classList.add('is-grabbing');
          try { c.setPointerCapture(e.pointerId); } catch (_) {}
          this._tooltip(null);
        }
        if (drag.bewegt) {
          const r = this._radius();
          const neuYaw = drag.yaw + dx / r;
          const neuTilt = clamp(drag.tilt - dy / r, -1.3, 1.3);
          this.vYaw = neuYaw - this.yaw;
          this.vTilt = neuTilt - this.tilt;
          this.yaw = neuYaw;
          this.tilt = neuTilt;
          this._weiter();
          return;
        }
      }
      this._hover(e);
    });
    const ende = (e) => {
      if (!drag) return;
      const war = drag.bewegt;
      drag = null;
      c.classList.remove('is-grabbing');
      try { c.releasePointerCapture(e.pointerId); } catch (_) {}
      if (!war && e.type === 'pointerup') this._click(e);
    };
    c.addEventListener('pointerup', ende);
    c.addEventListener('pointercancel', ende);
    c.addEventListener('pointerleave', () => { if (!drag) this._hover(null); });
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      this.zoom = clamp(this.zoom * Math.exp(-e.deltaY * 0.0012), 0.6, 2.4);
      this._weiter();
    }, { passive: false });
    c.addEventListener('dblclick', () => this._zuruecksetzen());
    if (this.dom.reset) this.dom.reset.addEventListener('click', () => this._zuruecksetzen());
    if (this.dom.spin) this.dom.spin.addEventListener('click', () => {
      this.spinning = !this.spinning;
      this.dom.spin.textContent = this.spinning ? 'Rotation pausieren' : 'Rotation fortsetzen';
      this.dom.spin.setAttribute('aria-pressed', String(!this.spinning));
      this._weiter();
    });
    this.stage.addEventListener('keydown', (e) => {
      const schritt = { ArrowLeft: [-0.12, 0], ArrowRight: [0.12, 0], ArrowUp: [0, 0.1], ArrowDown: [0, -0.1] }[e.key];
      if (schritt) { e.preventDefault(); this.yaw += schritt[0]; this.tilt = clamp(this.tilt + schritt[1], -1.3, 1.3); this._weiter(); }
      else if (e.key === '+' || e.key === '=') { this.zoom = clamp(this.zoom * 1.15, 0.6, 2.4); this._weiter(); }
      else if (e.key === '-') { this.zoom = clamp(this.zoom / 1.15, 0.6, 2.4); this._weiter(); }
      else if (e.key === 'Escape') { this.selected = null; this._detail(null); this._weiter(); }
    });
    if (this.dom.detail) this.dom.detail.addEventListener('click', (e) => {
      if (e.target.closest('.gd-close')) { this.selected = null; this._detail(null); this._weiter(); }
    });
  }

  _zuruecksetzen() {
    this.yaw = 0; this.tilt = TILT_START; this.zoom = 1; this.vYaw = 0; this.vTilt = 0;
    this._weiter();
  }

  _weiter() {
    // Neu zeichnen, auch wenn die Animation gerade nicht läuft.
    if (!this.frame) this._zeichnen();
  }

  /* ---------- Daten aufbereiten ---------- */
  _aufbau() {
    const liste = (this.data && this.data.nodes) || [];
    this.nodes = [];
    this.byId = new Map();
    liste.forEach((n, i) => {
      const k = { ...n, idx: i };
      this.byId.set(n.id, k);
      if (n.type === 'hub' || n.type === 'source' || n.type === 'department') return;
      const h = hash(String(n.id || i));
      // gleichmässig verteilt, aber stabil pro Knoten
      const u = (h % 10000) / 10000, v = ((h >>> 9) % 10000) / 10000;
      k.lat = Math.asin(clamp(2 * u - 1, -0.94, 0.94));
      k.lon = v * Math.PI * 2;
      this.nodes.push(k);
    });
    this.edgeListe = ((this.data && this.data.edges) || []).map((e, i) => ({ ...e, phase: (hash(e.from + '>' + e.to + i) % 1000) / 1000 }));
  }

  /* ---------- Geometrie ---------- */
  _radius() {
    return Math.min(this.w * 0.5, this.h) * 0.33 * this.zoom;
  }

  _projekt(lat, lon, cx, cy, r, hoehe = 1) {
    // Kugel -> Drehung um Y (yaw) -> Neigung um X (tilt) -> Bildschirm
    let x = Math.cos(lat) * Math.sin(lon), y = Math.sin(lat), z = Math.cos(lat) * Math.cos(lon);
    const cy1 = Math.cos(this.yaw), sy1 = Math.sin(this.yaw);
    [x, z] = [x * cy1 + z * sy1, -x * sy1 + z * cy1];
    const ct = Math.cos(this.tilt), st = Math.sin(this.tilt);
    [y, z] = [y * ct - z * st, y * st + z * ct];
    return { x: cx + r * hoehe * x, y: cy - r * hoehe * y, z };
  }

  _vektorProjekt(v, cx, cy, r, hoehe = 1) {
    const lat = Math.asin(clamp(v[1], -1, 1)), lon = Math.atan2(v[0], v[2]);
    return this._projekt(lat, lon, cx, cy, r, hoehe);
  }

  _anker() {
    // Position der Listeneinträge links/rechts relativ zur Kugelfläche
    this.anker = new Map();
    const s = this.stage.getBoundingClientRect();
    const neben = (liste, links) => {
      if (!liste) return false;
      const r = liste.getBoundingClientRect();
      return links ? r.right <= s.left + 4 && r.bottom > s.top : r.left >= s.right - 4 && r.bottom > s.top;
    };
    const lesen = (liste, links) => {
      if (!neben(liste, links)) return;
      const lr = liste.getBoundingClientRect();
      liste.querySelectorAll('[data-node]').forEach((el) => {
        const r = el.getBoundingClientRect();
        let y = r.top + r.height / 2 - s.top;
        // abgeschnittene Einträge an den sichtbaren Rand der Liste setzen
        y = clamp(y, lr.top - s.top + 6, lr.bottom - s.top - 6);
        this.anker.set(el.dataset.node, { x: links ? 0 : this.w, y, links });
      });
    };
    lesen(this.dom.sources, true);
    lesen(this.dom.departments, false);
  }

  _resize() {
    const rect = this.stage.getBoundingClientRect();
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    this.w = Math.max(320, Math.round(rect.width));
    this.h = Math.max(320, Math.round(rect.height));
    this.dpr = dpr;
    this.canvas.width = Math.round(this.w * dpr);
    this.canvas.height = Math.round(this.h * dpr);
    this._anker();
    this._zeichnen();
  }

  _tick() {
    if (!this.active) { this.frame = null; return; }
    this.zeit += 1;
    if (!this.ruhig) {
      if (this.spinning) this.yaw += SPIN;
      // Schwung nach dem Loslassen
      if (Math.abs(this.vYaw) > 0.0002 || Math.abs(this.vTilt) > 0.0002) {
        this.yaw += this.vYaw; this.tilt = clamp(this.tilt + this.vTilt, -1.3, 1.3);
        this.vYaw *= 0.93; this.vTilt *= 0.93;
      }
    }
    this._zeichnen();
    this.frame = requestAnimationFrame(this._tick);
  }

  /* ---------- Zeichnen ---------- */
  _zeichnen() {
    const ctx = this.ctx;
    if (!ctx || !this.w) return;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    const cx = this.w / 2, cy = this.h / 2 + 14;
    const r = this._radius();
    ctx.clearRect(0, 0, this.w, this.h);

    this._sterne(ctx);

    // Atmosphäre hinter der Kugel
    let g = ctx.createRadialGradient(cx, cy, r * 0.2, cx, cy, r * 1.45);
    g.addColorStop(0, 'rgba(56,232,255,.10)');
    g.addColorStop(0.62, 'rgba(56,232,255,.05)');
    g.addColorStop(0.72, 'rgba(56,232,255,.08)');
    g.addColorStop(1, 'rgba(56,232,255,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, r * 1.45, 0, Math.PI * 2); ctx.fill();

    // Rückseite (schwach), dann Kanäle, dann Vorderseite
    this._oberflaeche(ctx, cx, cy, r, false);
    this._kanaele(ctx, cx, cy, r);
    // Kugelkörper leicht abdunkeln, damit die Vorderseite klar wirkt
    g = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.35, r * 0.1, cx, cy, r);
    g.addColorStop(0, 'rgba(20,60,78,.35)');
    g.addColorStop(1, 'rgba(4,12,16,.55)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();
    this._oberflaeche(ctx, cx, cy, r, true);

    // Rand-Leuchten
    ctx.save();
    ctx.strokeStyle = 'rgba(120,235,255,.45)';
    ctx.lineWidth = 1.2;
    ctx.shadowColor = '#38e8ff';
    ctx.shadowBlur = 16;
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
    ctx.restore();

    this._kugelKanten(ctx, cx, cy, r);
    this._knoten(ctx, cx, cy, r);

    // Ring aussen (Umlaufbahn)
    ctx.save();
    ctx.strokeStyle = 'rgba(56,232,255,.16)';
    ctx.setLineDash([2, 7]);
    ctx.lineDashOffset = -this.zeit * 0.15;
    ctx.beginPath();
    ctx.ellipse(cx, cy, r * 1.32, r * 1.32 * Math.max(0.18, Math.abs(Math.sin(this.tilt)) + 0.12), 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  _sterne(ctx) {
    ctx.save();
    for (let i = 0; i < 110; i++) {
      const x = (hash('s' + i) % 1000) / 1000 * this.w;
      const y = (hash('t' + i) % 1000) / 1000 * this.h;
      const blink = this.ruhig ? 0 : Math.sin(this.zeit * 0.03 + i) * 0.08;
      ctx.globalAlpha = Math.max(0.05, 0.12 + ((hash('a' + i) % 100) / 100) * 0.22 + blink);
      ctx.fillStyle = i % 7 === 0 ? '#38e8ff' : (i % 5 === 0 ? '#ff9ad4' : '#cfe6ee');
      ctx.fillRect(x, y, 1.2, 1.2);
    }
    ctx.restore();
  }

  _oberflaeche(ctx, cx, cy, r, vorne) {
    // Längen- und Breitengrade
    ctx.save();
    ctx.lineWidth = vorne ? 0.7 : 0.5;
    for (const linie of this.gitter) {
      ctx.beginPath();
      let offen = false;
      for (const [lat, lon] of linie) {
        const p = this._projekt(lat, lon, cx, cy, r);
        const sichtbar = vorne ? p.z >= 0 : p.z < 0;
        if (sichtbar) {
          if (!offen) { ctx.moveTo(p.x, p.y); offen = true; } else ctx.lineTo(p.x, p.y);
        } else offen = false;
      }
      ctx.strokeStyle = vorne ? 'rgba(120,220,240,.20)' : 'rgba(120,220,240,.06)';
      ctx.stroke();
    }
    // Punktwolke der Oberfläche
    for (const v of this.kugel) {
      const p = this._vektorProjekt(v, cx, cy, r);
      if (vorne ? p.z < 0 : p.z >= 0) continue;
      const tiefe = vorne ? p.z : -p.z;
      ctx.globalAlpha = vorne ? 0.18 + tiefe * 0.6 : 0.05 + (1 - tiefe) * 0.06;
      ctx.fillStyle = vorne ? '#bff4ff' : '#4fb6cc';
      const s = vorne ? 0.8 + tiefe * 0.9 : 0.8;
      ctx.fillRect(p.x - s / 2, p.y - s / 2, s, s);
    }
    ctx.restore();
  }

  /* Linien von den Quellen in die Kugel und von der Kugel zu den Abteilungen */
  _kanaele(ctx, cx, cy, r) {
    if (!this.anker.size) return;
    const linien = [];
    const randPunkt = (a) => {
      const dx = a.x - cx, dy = a.y - cy, d = Math.hypot(dx, dy) || 1;
      return { x: cx + dx / d * r, y: cy + dy / d * r };
    };
    // 1) Grundkanal pro Listeneintrag (schwach; aktiv, wenn Zähler > 0)
    const d = this.data || {};
    for (const q of d.sources || []) {
      const a = this.anker.get('source:' + q.id);
      if (a) linien.push({ a, b: randPunkt(a), farbe: q.color || '#38e8ff', aktiv: Number(q.count) > 0, stark: false, phase: (hash(q.id) % 100) / 100 });
    }
    for (const t of d.departments || []) {
      const a = this.anker.get('dept:' + t.id);
      if (a) linien.push({ a: randPunkt(a), b: a, farbe: t.color || '#e8c46a', aktiv: Number(t.agent_runs) > 0 || Boolean(t.active), stark: false, phase: (hash(t.id) % 100) / 100 });
    }
    // 2) Konkrete Kanten aus den Daten: Quelle -> Knoten, Knoten -> Abteilung, Hub -> Abteilung
    for (const e of this.edgeListe) {
      const von = this.anker.get(e.from), nach = this.anker.get(e.to);
      if (von && !nach) {
        const p = this.pos.get(e.to);
        if (!p) continue;
        const n = this.byId.get(e.to);
        // gebündelt: über den Kanal der Quelle zum Rand, dann gerade zum Knoten
        if (p.z >= 0) linien.push({ a: randPunkt(von), b: p, farbe: (n && n.color) || '#6fd9ff', aktiv: !!e.active || !!(n && n.active), stark: true, gerade: true, phase: e.phase, id: e.to, kanal: von });
      } else if (nach && !von) {
        if (e.from === 'hub') continue; // Grundkanal deckt das ab
        const p = this.pos.get(e.from);
        if (!p) continue;
        const n = this.byId.get(e.from);
        if (p.z >= 0) linien.push({ a: p, b: randPunkt(nach), farbe: (n && n.color) || '#e8c46a', aktiv: !!e.active || !!(n && n.active), stark: true, gerade: true, phase: e.phase, id: e.from, kanal: nach });
      }
    }
    const fokus = this.hover || this.selected;
    ctx.save();
    // Kanäle des Fokus-Knotens hervorheben
    const fokusKanaele = new Set(linien.filter(l => fokus && l.id === fokus && l.kanal).map(l => l.kanal));
    for (const l of linien) {
      const hervor = fokus && (l.id === fokus || (!l.stark && (fokusKanaele.has(l.a) || fokusKanaele.has(l.b))));
      const kurve = l.gerade
        ? { c1: { x: l.a.x + (l.b.x - l.a.x) / 3, y: l.a.y + (l.b.y - l.a.y) / 3 }, c2: { x: l.a.x + (l.b.x - l.a.x) * 2 / 3, y: l.a.y + (l.b.y - l.a.y) * 2 / 3 } }
        : bezier(l.a, l.b);
      ctx.beginPath();
      ctx.moveTo(l.a.x, l.a.y);
      ctx.bezierCurveTo(kurve.c1.x, kurve.c1.y, kurve.c2.x, kurve.c2.y, l.b.x, l.b.y);
      ctx.strokeStyle = hexA(l.farbe, hervor ? 0.95 : l.stark ? (l.aktiv ? 0.32 : 0.14) : (l.aktiv ? 0.5 : 0.14));
      ctx.lineWidth = hervor ? 1.8 : l.stark ? 1.1 : 0.9;
      ctx.stroke();
      // Lichtpunkte nur auf aktiven Verbindungen
      if (l.aktiv && !this.ruhig) {
        for (let k = 0; k < (l.stark ? 2 : 1); k++) {
          const t = ((this.zeit * 0.0045) + l.phase + k * 0.5) % 1;
          const p = bezierPunkt(l.a, kurve.c1, kurve.c2, l.b, t);
          ctx.globalAlpha = Math.sin(t * Math.PI);
          ctx.fillStyle = l.farbe;
          ctx.shadowColor = l.farbe;
          ctx.shadowBlur = 8;
          ctx.beginPath(); ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2); ctx.fill();
          ctx.shadowBlur = 0;
          ctx.globalAlpha = 1;
        }
      }
    }
    // Andockpunkte an der Liste
    for (const a of this.anker.values()) {
      ctx.fillStyle = 'rgba(120,235,255,.55)';
      ctx.fillRect(a.links ? 0 : a.x - 3, a.y - 1, 3, 2);
    }
    ctx.restore();
  }

  /* Kanten zwischen Knoten auf der Kugel als Bögen über die Oberfläche */
  _kugelKanten(ctx, cx, cy, r) {
    // Positionen aktualisieren
    for (const n of this.nodes) this.pos.set(n.id, this._projekt(n.lat, n.lon, cx, cy, r));
    const fokus = this.hover || this.selected;
    ctx.save();
    for (const e of this.edgeListe) {
      const a = this.byId.get(e.from), b = this.byId.get(e.to);
      if (!a || !b || a.lat === undefined || b.lat === undefined) continue;
      const va = einheit(a.lat, a.lon), vb = einheit(b.lat, b.lon);
      const hervor = fokus && (e.from === fokus || e.to === fokus);
      const schritte = 24;
      let vorher = null;
      for (let i = 0; i <= schritte; i++) {
        const t = i / schritte;
        const v = slerp(va, vb, t);
        const p = this._vektorProjekt(v, cx, cy, r, 1 + Math.sin(t * Math.PI) * 0.12);
        if (vorher && (p.z >= -0.05 || vorher.z >= -0.05)) {
          const vorne = p.z >= 0 && vorher.z >= 0;
          ctx.strokeStyle = e.active ? `rgba(255,63,164,${hervor ? .95 : vorne ? .6 : .15})` : `rgba(56,232,255,${hervor ? .9 : vorne ? .35 : .08})`;
          ctx.lineWidth = hervor ? 1.6 : 1;
          ctx.beginPath(); ctx.moveTo(vorher.x, vorher.y); ctx.lineTo(p.x, p.y); ctx.stroke();
        }
        vorher = p;
      }
      if (e.active && !this.ruhig) {
        const t = ((this.zeit * 0.006) + e.phase) % 1;
        const p = this._vektorProjekt(slerp(va, vb, t), cx, cy, r, 1 + Math.sin(t * Math.PI) * 0.12);
        if (p.z >= 0) { ctx.fillStyle = '#ff7ac4'; ctx.beginPath(); ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2); ctx.fill(); }
      }
    }
    ctx.restore();
  }

  _knoten(ctx, cx, cy, r) {
    const fokus = this.hover || this.selected;
    const sortiert = this.nodes.map(n => [n, this.pos.get(n.id)]).sort((a, b) => a[1].z - b[1].z);
    for (const [n, p] of sortiert) {
      const vorne = p.z >= 0;
      const farbe = n.color || '#38e8ff';
      const groesse = (3.2 + Math.min(4, Number(n.relevance || 0.4) * 6)) * (0.75 + Math.max(0, p.z) * 0.35) * Math.sqrt(this.zoom);
      ctx.save();
      ctx.globalAlpha = vorne ? 0.6 + p.z * 0.4 : 0.14;
      if (vorne) {
        const R = groesse * (n.id === fokus ? 6 : 3.6);
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, R);
        g.addColorStop(0, hexA(farbe, .5)); g.addColorStop(1, hexA(farbe, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(p.x, p.y, R, 0, Math.PI * 2); ctx.fill();
        if (n.active && !this.ruhig) {
          const puls = (this.zeit * 0.02 + (n.idx % 10) / 10) % 1;
          ctx.globalAlpha = (1 - puls) * 0.6;
          ctx.strokeStyle = farbe;
          ctx.beginPath(); ctx.arc(p.x, p.y, groesse + puls * 14, 0, Math.PI * 2); ctx.stroke();
          ctx.globalAlpha = 0.6 + p.z * 0.4;
        }
      }
      ctx.translate(p.x, p.y);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = farbe;
      ctx.fillRect(-groesse / 2, -groesse / 2, groesse, groesse);
      if (vorne) {
        ctx.fillStyle = 'rgba(255,255,255,.75)';
        ctx.fillRect(-groesse / 6, -groesse / 6, groesse / 3, groesse / 3);
      }
      if (n.id === this.selected || n.id === this.hover) {
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.2;
        ctx.strokeRect(-groesse, -groesse, groesse * 2, groesse * 2);
      }
      ctx.restore();
    }
  }

  /* ---------- Treffer, Tooltip, Detail ---------- */
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
    return best ? { n: best, x, y } : null;
  }

  _hover(e) {
    const t = e ? this._treffer(e) : null;
    const id = t ? t.n.id : null;
    this.canvas.style.cursor = t ? 'pointer' : 'grab';
    if (id !== this.hover) { this.hover = id; this._weiter(); }
    this._tooltip(t);
  }

  _tooltip(t) {
    const tip = this.dom.tooltip;
    if (!tip) return;
    if (!t) { tip.hidden = true; return; }
    const n = t.n;
    tip.hidden = false;
    tip.innerHTML = `<b>${esc(n.title || n.id)}</b><span>${esc(n.category || n.type || '')}${n.source ? ' · ' + esc(n.source) : ''}</span>`;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(this.w - w - 8, t.x + 14) + 'px';
    tip.style.top = Math.max(8, Math.min(this.h - h - 8, t.y + 14)) + 'px';
  }

  _click(e) {
    const t = this._treffer(e);
    if (!t) { this.selected = null; this._detail(null); this._weiter(); return; }
    this.selected = t.n.id;
    this._detail(t.n);
    this._weiter();
  }

  _detail(n) {
    const box = this.dom.detail;
    if (!box) return;
    if (!n) { box.hidden = true; return; }
    const zeit = n.time ? String(n.time).replace('T', ' ').slice(0, 16) : '—';
    const feld = (l, w) => `<span><small>${esc(l)}</small><b>${esc(w ?? '—')}</b></span>`;
    box.hidden = false;
    box.innerHTML = `<div class="gd-top"><span class="gd-type${n.demo ? ' is-demo' : ''}">${esc(n.category || n.type || 'Knoten')}${n.demo ? ' · Demo' : ''}</span>
        <button type="button" class="gd-close" aria-label="Schliessen">×</button></div>
      <h3>${esc(n.title || n.id)}</h3>
      ${n.summary ? `<p class="gd-summary">${esc(n.summary)}</p>` : ''}
      <div class="gd-grid">${feld('Quelle', n.source || '—')}${feld('Abteilung', n.department || '—')}${feld('Zeit', zeit)}${feld('Status', n.status || '—')}</div>
      ${n.detail ? `<p class="gd-detail">${esc(n.detail)}</p>` : ''}
      ${n.url ? `<a class="gd-link" href="${esc(n.url)}" target="_blank" rel="noopener">Quelle öffnen ↗</a>` : ''}`;
  }

  /* ---------- Listen links/rechts (wie bisher, plus data-node für die Linien) ---------- */
  _rails() {
    const d = this.data || {};
    const quellen = d.sources || [];
    const abteilungen = d.departments || [];
    const counts = d.counts || {};
    const activity = d.activity || {};
    if (this.dom.sources) {
      this.dom.sources.innerHTML = quellen.map(q => `<div class="globe-rail-item${Number(q.count) > 0 ? ' is-live' : ''}" data-node="source:${esc(q.id)}">
        <span class="globe-rail-dot" style="background:${esc(q.color || '#38e8ff')}"></span>
        <span class="globe-rail-name">${esc(q.name)}</span>
        <span class="globe-rail-count">${q.count ?? 0}</span>
      </div>`).join('') || '<div class="globe-rail-empty">Keine Quelle verbunden.</div>';
      this.dom.sources.onscroll = () => { this._anker(); this._weiter(); };
    }
    if (this.dom.departments) {
      this.dom.departments.innerHTML = abteilungen.map(a => `<div class="globe-rail-item${Number(a.agent_runs) > 0 || a.active ? ' is-live' : ''}" data-node="dept:${esc(a.id)}">
        <span class="globe-rail-dot" style="background:${esc(a.color || '#38e8ff')}"></span>
        <span class="globe-rail-name">${esc(a.name)}</span>
        <span class="globe-rail-count">${a.agent_runs ?? 0}</span>
      </div>`).join('') || '<div class="globe-rail-empty">Keine Abteilung aktiv.</div>';
      this.dom.departments.onscroll = () => { this._anker(); this._weiter(); };
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
    if (this.selected && !this.byId.has(this.selected)) { this.selected = null; this._detail(null); }
  }
}

/* ---------- Hilfsfunktionen ---------- */
function fibonacci(n) {
  const punkte = [], gold = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2, rr = Math.sqrt(1 - y * y), t = gold * i;
    punkte.push([Math.cos(t) * rr, y, Math.sin(t) * rr]);
  }
  return punkte;
}

function gitterLinien() {
  const linien = [], rad = Math.PI / 180;
  for (let lat = -60; lat <= 60; lat += 20) {
    const l = [];
    for (let lon = 0; lon <= 360; lon += 4) l.push([lat * rad, lon * rad]);
    linien.push(l);
  }
  for (let lon = 0; lon < 360; lon += 20) {
    const l = [];
    for (let lat = -88; lat <= 88; lat += 4) l.push([lat * rad, lon * rad]);
    linien.push(l);
  }
  return linien;
}

function einheit(lat, lon) {
  return [Math.cos(lat) * Math.sin(lon), Math.sin(lat), Math.cos(lat) * Math.cos(lon)];
}

function slerp(a, b, t) {
  const dot = clamp(a[0] * b[0] + a[1] * b[1] + a[2] * b[2], -1, 1);
  const w = Math.acos(dot);
  if (w < 1e-4) return a;
  const s = Math.sin(w), fa = Math.sin((1 - t) * w) / s, fb = Math.sin(t * w) / s;
  return [a[0] * fa + b[0] * fb, a[1] * fa + b[1] * fb, a[2] * fa + b[2] * fb];
}

function bezier(a, b) {
  const dx = b.x - a.x;
  return { c1: { x: a.x + dx * 0.5, y: a.y }, c2: { x: a.x + dx * 0.62, y: b.y } };
}

function bezierPunkt(a, c1, c2, b, t) {
  const u = 1 - t;
  return {
    x: u * u * u * a.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * b.x,
    y: u * u * u * a.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * b.y,
  };
}

function hexA(hex, a) {
  const h = String(hex || '#38e8ff').replace('#', '');
  const v = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h.slice(0, 6), 16);
  return `rgba(${(v >> 16) & 255},${(v >> 8) & 255},${v & 255},${a})`;
}

function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

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
