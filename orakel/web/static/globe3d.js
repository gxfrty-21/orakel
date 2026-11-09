/* Orakel Global Intelligence Sphere — echte 3D-Szene, keine Canvas-Kulisse.
 * Die Daten kommen aus /api/globe; hier wird nur dargestellt, nicht erfunden.
 */
import * as THREE from './vendor/three.module.js';

const TAU = Math.PI * 2;
const GOLDEN = Math.PI * (3 - Math.sqrt(5));
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const PALETTE = ['#63d7ff', '#8be7ff', '#5fe0c8', '#b8d7ff', '#65a8ff'];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < String(text).length; i++) {
    h ^= String(text).charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

function fmtDate(value) {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return new Intl.DateTimeFormat('de-CH', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(d);
}

function fmtNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toLocaleString('de-CH', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });
}

function safeUrl(value) {
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function glowTexture(size = 128) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const x = c.getContext('2d');
  const g = x.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.16, 'rgba(255,255,255,.95)');
  g.addColorStop(0.42, 'rgba(255,255,255,.38)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g;
  x.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function ringTexture(size = 256) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const x = c.getContext('2d');
  const g = x.createRadialGradient(size / 2, size / 2, size * 0.28, size / 2, size / 2, size * 0.50);
  g.addColorStop(0, 'rgba(255,255,255,0)');
  g.addColorStop(0.68, 'rgba(255,255,255,.15)');
  g.addColorStop(0.84, 'rgba(255,255,255,.95)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g;
  x.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function fibonacciSphere(count, radius = 2.0) {
  const points = [];
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const theta = GOLDEN * i;
    points.push(new THREE.Vector3(Math.cos(theta) * r * radius, y * radius, Math.sin(theta) * r * radius));
  }
  return points;
}

export class IntelligenceGlobe {
  constructor(stage) {
    this.stage = stage;
    this.canvas = document.getElementById('globeCanvas');
    this.dom = {
      sources: document.getElementById('globeSources'),
      departments: document.getElementById('globeDepartments'),
      mode: document.getElementById('globeMode'),
      modeDetail: document.getElementById('globeModeDetail'),
      activity: document.getElementById('globeActivity'),
      activityDetail: document.getElementById('globeActivityDetail'),
      nodeCount: document.getElementById('globeNodeCount'),
      edgeCount: document.getElementById('globeEdgeCount'),
      sourceCount: document.getElementById('globeSourceCount'),
      sourceCountTop: document.getElementById('globeSourceCountTop'),
      meta: document.getElementById('globeMeta'),
      sourceTotal: document.getElementById('globeSourceTotal'),
      deptTotal: document.getElementById('globeDeptTotal'),
      detail: document.getElementById('globeDetail'),
      tooltip: document.getElementById('globeTooltip'),
      empty: document.getElementById('globeEmpty'),
      legend: document.getElementById('globeLegend'),
      reset: document.getElementById('globeReset'),
      spin: document.getElementById('globeToggleSpin'),
      panel: document.getElementById('globePanel'),
      hint: document.getElementById('globeHint'),
    };
    this.data = null;
    this.nodeById = new Map();
    this.nodeMeshes = new Map();
    this.channelMeshes = new Map();
    this.channelCurves = new Map();
    this.channelColors = new Map();
    this.pickMeshes = [];
    this.flowPulses = [];
    this.nodeBirths = new Map();
    this.seenIds = new Set();
    this.firstData = true;
    this.active = false;
    this.spinOn = true;
    this.dragging = false;
    this.moved = 0;
    this.lastInteraction = 0;
    this.rotY = 0.28;
    this.rotX = -0.10;
    this.zoom = 8.8;
    this.narrow = window.innerWidth < 900;
    this.selectedId = null;
    this.hoveredId = null;
    this.lastFrame = 0;
    this.raf = 0;
    this.loop = this.loop.bind(this);
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.glow = glowTexture();
    this.ringTex = ringTexture();
    this.scratch = new THREE.Vector3();
    this.initScene();
    this.bindEvents();
    this.resize();
    if ('ResizeObserver' in window) {
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.stage);
    }
  }

  initScene() {
    try {
      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas, alpha: true, antialias: true, powerPreference: 'high-performance',
      });
    } catch (error) {
      throw new Error('WebGL ist in diesem Browser nicht verfügbar.');
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
    this.camera.position.set(0, 0, this.zoom);
    this.root = new THREE.Group();
    this.scene.add(this.root);

    this.buildStars();
    this.buildAtmosphere();
    this.sphereGroup = new THREE.Group();
    this.sphereGroup.rotation.set(this.rotX, this.rotY, 0);
    this.root.add(this.sphereGroup);
    // Dunkler Kern gibt der Partikelhülle Tiefe: die Rückseite verschwindet
    // hinter dem Globus, statt die Vorderseite mit Additivlicht zu überstrahlen.
    this.globeShell = new THREE.Mesh(
      new THREE.SphereGeometry(1.965, 56, 36),
      new THREE.MeshBasicMaterial({ color: 0x06131b }),
    );
    this.sphereGroup.add(this.globeShell);
    this.buildParticles();
    this.buildNetwork();
    this.buildOrbits();
    this.dataGroup = new THREE.Group();
    this.sphereGroup.add(this.dataGroup);
    this.channelGroup = new THREE.Group();
    this.root.add(this.channelGroup);
    this.pulseGroup = new THREE.Group();
    this.root.add(this.pulseGroup);
    this.selectionRing = this.makeRing(0x5fe0c8, 0.42);
    this.hoverRing = this.makeRing(0xa9efff, 0.30);
    this.root.add(this.selectionRing, this.hoverRing);
    this.selectionRing.visible = false;
    this.hoverRing.visible = false;
    this.canvas.addEventListener('webglcontextlost', e => {
      e.preventDefault();
      this.showError('Der WebGL-Kontext wurde unterbrochen. Bitte die Ansicht neu laden.');
    });
  }

  buildStars() {
    const count = this.narrow ? 180 : 340;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 10 + Math.random() * 12;
      const theta = Math.random() * TAU;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = Math.sin(phi) * Math.cos(theta) * r;
      positions[i * 3 + 1] = Math.cos(phi) * r;
      positions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this.stars = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0x4b7893, size: 0.035, transparent: true, opacity: 0.38,
      depthWrite: false, sizeAttenuation: true,
    }));
    this.root.add(this.stars);
  }

  buildAtmosphere() {
    const mat = new THREE.SpriteMaterial({
      map: this.glow, color: 0x1b8ba8, transparent: true, opacity: 0.085,
      blending: THREE.AdditiveBlending, depthWrite: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(6.0, 6.0, 1);
    sprite.position.z = -0.8;
    this.root.add(sprite);
    this.atmosphere = sprite;
  }

  buildParticles() {
    const count = this.narrow ? 1500 : 3000;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const sizes = new Float32Array(count);
    const alphas = new Float32Array(count);
    const color = new THREE.Color();
    for (let i = 0; i < count; i++) {
      const y = 1 - (i / Math.max(1, count - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = GOLDEN * i;
      const inner = i % 19 === 0 ? 0.68 + Math.random() * 0.22 : 1.0 + (Math.random() - 0.5) * 0.018;
      const radius = 2.03 * inner;
      positions[i * 3] = Math.cos(theta) * r * radius;
      positions[i * 3 + 1] = y * radius;
      positions[i * 3 + 2] = Math.sin(theta) * r * radius;
      color.set(PALETTE[i % PALETTE.length]);
      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;
      sizes[i] = (i % 17 === 0 ? 1.9 : 0.55) + Math.random() * 0.9;
      alphas[i] = (i % 11 === 0 ? 0.55 : 0.16) + Math.random() * 0.22;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geo.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(sizes, 1));
    geo.setAttribute('aAlpha', new THREE.BufferAttribute(alphas, 1));
    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uTex: { value: this.glow },
        uPixelRatio: { value: this.renderer.getPixelRatio() },
      },
      vertexShader: `
        uniform float uPixelRatio;
        attribute vec3 aColor;
        attribute float aSize;
        attribute float aAlpha;
        varying vec3 vColor;
        varying float vAlpha;
        void main() {
          vColor = aColor;
          vAlpha = aAlpha;
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = aSize * (14.0 / max(0.1, -mv.z)) * uPixelRatio;
          gl_Position = projectionMatrix * mv;
        }
      `,
      fragmentShader: `
        uniform sampler2D uTex;
        varying vec3 vColor;
        varying float vAlpha;
        void main() {
          vec4 tex = texture2D(uTex, gl_PointCoord);
          if (tex.a < 0.015) discard;
          gl_FragColor = vec4(vColor, tex.a * vAlpha);
        }
      `,
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    this.particles = new THREE.Points(geo, mat);
    this.sphereGroup.add(this.particles);
  }

  buildNetwork() {
    const count = this.narrow ? 180 : 290;
    const points = fibonacciSphere(count, 2.02);
    const colors = new THREE.Color();
    const edgePositions = [];
    const edgeColors = [];
    const seen = new Set();
    const nearest = (index, k) => {
      const result = [];
      const p = points[index];
      for (let j = 0; j < points.length; j++) {
        if (j === index) continue;
        const d = p.distanceToSquared(points[j]);
        result.push([d, j]);
      }
      result.sort((a, b) => a[0] - b[0]);
      return result.slice(0, k).map(v => v[1]);
    };
    const addEdge = (a, b) => {
      const key = a < b ? `${a}:${b}` : `${b}:${a}`;
      if (seen.has(key)) return;
      seen.add(key);
      const start = points[a];
      const end = points[b];
      const mid = start.clone().add(end).multiplyScalar(0.5).normalize().multiplyScalar(2.10);
      const curve = new THREE.QuadraticBezierCurve3(start, mid, end);
      colors.set(PALETTE[(a + b) % PALETTE.length]);
      const segments = 7;
      for (let s = 0; s < segments; s++) {
        const p1 = curve.getPoint(s / segments);
        const p2 = curve.getPoint((s + 1) / segments);
        edgePositions.push(p1.x, p1.y, p1.z, p2.x, p2.y, p2.z);
        edgeColors.push(colors.r, colors.g, colors.b, colors.r, colors.g, colors.b);
      }
    };
    for (let i = 0; i < points.length; i++) {
      nearest(i, 2).forEach(j => addEdge(i, j));
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(edgePositions, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(edgeColors, 3));
    this.network = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
      transparent: true, opacity: 0.18, vertexColors: true,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    this.sphereGroup.add(this.network);

    const nodeGeo = new THREE.BufferGeometry();
    const nodePositions = new Float32Array(points.length * 3);
    points.forEach((p, i) => {
      nodePositions[i * 3] = p.x;
      nodePositions[i * 3 + 1] = p.y;
      nodePositions[i * 3 + 2] = p.z;
    });
    nodeGeo.setAttribute('position', new THREE.BufferAttribute(nodePositions, 3));
    this.networkNodes = new THREE.Points(nodeGeo, new THREE.PointsMaterial({
      color: 0x9aeaff, size: 0.028, transparent: true, opacity: 0.55,
      blending: THREE.AdditiveBlending, depthWrite: false, sizeAttenuation: true,
    }));
    this.sphereGroup.add(this.networkNodes);
  }

  buildOrbits() {
    const makeOrbit = (radius, tilt, color, opacity) => {
      const pts = [];
      for (let i = 0; i <= 160; i++) {
        const a = (i / 160) * TAU;
        pts.push(new THREE.Vector3(Math.cos(a) * radius, 0, Math.sin(a) * radius));
      }
      const geo = new THREE.BufferGeometry().setFromPoints(pts);
      const line = new THREE.LineLoop(geo, new THREE.LineBasicMaterial({
        color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      line.rotation.x = tilt;
      this.sphereGroup.add(line);
    };
    makeOrbit(2.42, 0.98, 0x5fe0c8, 0.075);
    makeOrbit(2.55, -0.72, 0x6cb5ff, 0.055);
  }

  makeRing(color, scale) {
    const mat = new THREE.SpriteMaterial({
      map: this.ringTex, color, transparent: true, opacity: 0.92,
      blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(scale, scale, 1);
    return sprite;
  }

  resize() {
    const rect = this.stage.getBoundingClientRect();
    const w = Math.max(1, rect.width || 800);
    const h = Math.max(1, rect.height || 620);
    this.narrow = w < 760;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
    // Auf hohen, schmalen Stages würde die Kugel seitlich aus dem Bild laufen.
    const fit = Math.min(1, (w / h) / 0.78);
    this.sphereGroup.scale.setScalar((this.narrow ? 0.84 : 1) * fit);
    if (this.particles?.material?.uniforms?.uPixelRatio) {
      this.particles.material.uniforms.uPixelRatio.value = this.renderer.getPixelRatio();
    }
    if (this.data) {
      this.buildChannels(this.data);
      this.buildFlowPulses(this.data);
    }
  }

  buildChannels(data) {
    while (this.channelGroup.children.length) {
      const child = this.channelGroup.children.pop();
      this.channelGroup.remove(child);
      this.disposeObject(child);
    }
    this.channelMeshes.clear();
    this.channelCurves.clear();
    this.channelColors.clear();
    this.pickMeshes = [...this.nodeMeshes.values()];
    const sources = data.sources || [];
    const departments = data.departments || [];
    const top = this.narrow ? 1.75 : 2.18;
    const bottom = -top;
    const x = this.narrow ? 1.92 : 2.72;
    const sourceGeo = new THREE.OctahedronGeometry(0.065, 0);
    const deptGeo = new THREE.OctahedronGeometry(0.075, 0);
    const makeChannel = (item, side, index, total) => {
      const y = total <= 1 ? 0 : top - (index / (total - 1)) * (top - bottom);
      const pos = new THREE.Vector3(side === 'source' ? -x : x, y, 0.18);
      const color = new THREE.Color(item.color || (side === 'source' ? '#6fd9ff' : '#5fe0c8'));
      const mesh = new THREE.Mesh(side === 'source' ? sourceGeo : deptGeo,
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95 }));
      mesh.position.copy(pos);
      mesh.userData.nodeId = `${side === 'source' ? 'source' : 'dept'}:${item.id}`;
      this.channelGroup.add(mesh);
      this.channelMeshes.set(mesh.userData.nodeId, mesh);
      this.pickMeshes.push(mesh);
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glow, color, transparent: true, opacity: item.active ? 0.8 : 0.34,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      halo.scale.set(item.active ? 0.46 : 0.3, item.active ? 0.46 : 0.3, 1);
      halo.position.copy(pos);
      this.channelGroup.add(halo);
      const end = new THREE.Vector3(side === 'source' ? -1.72 : 1.72, y * 0.25, 0.12);
      const control = new THREE.Vector3(side === 'source' ? -2.32 : 2.32, y * 0.66, 0.55);
      const curve = new THREE.QuadraticBezierCurve3(
        side === 'source' ? pos.clone() : end.clone(),
        control,
        side === 'source' ? end.clone() : pos.clone(),
      );
      const lineGeo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(34));
      const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({
        color, transparent: true, opacity: item.active ? 0.34 : 0.12,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      this.channelGroup.add(line);
      this.channelCurves.set(`${side}:${item.id}`, curve);
      this.channelColors.set(`${side}:${item.id}`, color);
    };
    sources.forEach((s, i) => makeChannel(s, 'source', i, sources.length));
    departments.forEach((d, i) => makeChannel(d, 'dept', i, departments.length));
    this.updateRings();
  }

  setData(data) {
    this.data = data;
    this.nodeById = new Map((data.nodes || []).map(n => [n.id, n]));
    const nodes = (data.nodes || []).filter(n => !['hub', 'source', 'department'].includes(n.type));
    const ids = new Set(nodes.map(n => n.id));
    const first = this.firstData;
    const now = performance.now();
    const newIds = [];
    nodes.forEach((node, index) => {
      if (!this.seenIds.has(node.id)) {
        newIds.push(node.id);
        this.nodeBirths.set(node.id, now + (this.firstData ? index * 16 : 0));
      }
    });
    this.seenIds = ids;
    this.firstData = false;

    while (this.dataGroup.children.length) {
      const child = this.dataGroup.children.pop();
      this.dataGroup.remove(child);
      this.disposeObject(child);
    }
    this.nodeMeshes.clear();
    const count = Math.max(1, nodes.length);
    const nodeGeo = new THREE.SphereGeometry(0.05, 8, 8);
    nodes.forEach((node, index) => {
      const y = 1 - (index / Math.max(1, count - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = GOLDEN * index + hash(node.id) * 0.7;
      const radius = 2.055;
      const pos = new THREE.Vector3(Math.cos(theta) * r * radius, y * radius, Math.sin(theta) * r * radius);
      const color = new THREE.Color(node.color || '#8be7ff');
      const size = node.type === 'research' ? 1.35 : node.type === 'market' ? 1.2 : 1;
      const mesh = new THREE.Mesh(nodeGeo, new THREE.MeshBasicMaterial({
        color, transparent: true, opacity: node.demo ? 0.65 : 0.98,
      }));
      mesh.position.copy(pos);
      mesh.scale.setScalar(size);
      mesh.userData.nodeId = node.id;
      mesh.userData.node = node;
      this.dataGroup.add(mesh);
      this.nodeMeshes.set(node.id, mesh);
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glow, color, transparent: true, opacity: node.demo ? 0.28 : 0.55,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      const haloBase = node.type === 'research' ? 0.46 : 0.30;
      halo.scale.setScalar(haloBase);
      halo.userData.base = haloBase;
      halo.position.copy(pos);
      this.dataGroup.add(halo);
      mesh.userData.halo = halo;
      if (node.type === 'research' && node.status === 'offen') {
        const ring = this.makeRing(0xe8c46a, 0.48);
        ring.position.copy(pos);
        this.dataGroup.add(ring);
        mesh.userData.orderRing = ring;
      }
      if (this.nodeBirths.has(node.id)) {
        mesh.scale.setScalar(0.01);
        halo.scale.setScalar(0.001);
      }
    });
    this.pickMeshes = [...this.nodeMeshes.values()];
    this.buildChannels(data);
    this.buildFlowPulses(data);
    this.renderAll(data);
    if (this.selectedId && !this.nodeById.has(this.selectedId)) this.clearSelection();
    else if (this.selectedId) this.selectNode(this.selectedId, false);
    this.updateRings();
    if (newIds.length && !first) {
      // Ein kurzer Lichtimpuls markiert ausschließlich wirklich neue Knoten.
      this.pulseGroup.position.set(0, 0, 0);
    }
  }

  buildFlowPulses(data) {
    while (this.pulseGroup.children.length) {
      const child = this.pulseGroup.children.pop();
      this.pulseGroup.remove(child);
      this.disposeObject(child);
    }
    this.flowPulses = [];
    const seen = new Set();
    const flows = (data.flows || []).filter(f => f.active);
    for (const flow of flows) {
      let curveKey = null;
      if (flow.from?.startsWith('source:') && (flow.to === 'hub' || flow.to?.startsWith('article:'))) {
        curveKey = flow.from;
      } else if (flow.from === 'hub' && flow.to?.startsWith('dept:')) {
        curveKey = flow.to;
      } else if (flow.to?.startsWith('dept:')) {
        curveKey = flow.to;
      }
      if (!curveKey || !this.channelCurves.has(curveKey) || seen.has(curveKey)) continue;
      seen.add(curveKey);
      const color = this.channelColors.get(curveKey) || new THREE.Color(0x5fe0c8);
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glow, color, transparent: true, opacity: 0.95,
        blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
      }));
      sprite.scale.setScalar(0.16);
      this.pulseGroup.add(sprite);
      this.flowPulses.push({
        sprite, curve: this.channelCurves.get(curveKey),
        t: hash(flow.id || curveKey), speed: REDUCED ? 0.05 : 0.13 + hash(curveKey) * 0.14,
      });
    }
  }

  renderAll(data) {
    this.renderHud(data);
    this.renderRails(data);
    this.renderLegend(data);
    this.ensureDetailClose();
    if (this.selectedId) this.renderDetail(this.nodeById.get(this.selectedId));
  }

  renderHud(data) {
    const activity = data.activity || {};
    const counts = data.counts || {};
    const demo = !!data.demo;
    const windowLabel = data.window?.label || '24 Stunden';
    if (this.dom.mode) {
      this.dom.mode.classList.toggle('is-demo', demo);
      const modeDetail = demo
        ? (data.demo_hinweis || 'Beispieldaten sind klar markiert.')
        : `${data.sources.filter(s => s.active).length} Quellen aktiv · ${windowLabel} · ${fmtDate(data.generated_at)}`;
      this.dom.mode.innerHTML = `<span class="g-live-dot"></span><span><b>${demo ? 'DEMO' : 'LIVE'}</b><small>${esc(modeDetail)}</small></span>`;
      this.dom.modeDetail = this.dom.mode.querySelector('small');
    }
    if (this.dom.activity) {
      this.dom.activity.textContent = activity.label || '—';
      this.dom.activity.className = `g-activity is-${activity.state || 'leer'}`;
    }
    if (this.dom.activityDetail) this.dom.activityDetail.textContent = activity.detail || '';
    if (this.dom.nodeCount) this.dom.nodeCount.textContent = fmtNumber(counts.nodes);
    if (this.dom.edgeCount) this.dom.edgeCount.textContent = fmtNumber(counts.edges);
    if (this.dom.sourceCount) this.dom.sourceCount.textContent = `${fmtNumber(counts.sources)} / ${data.sources.length}`;
    if (this.dom.sourceCountTop) this.dom.sourceCountTop.textContent = fmtNumber(counts.sources);
    if (this.dom.sourceTotal) this.dom.sourceTotal.textContent = `${data.sources.filter(s => s.active).length} aktiv`;
    if (this.dom.deptTotal) this.dom.deptTotal.textContent = `${fmtNumber(counts.open_orders)} offen`;
    if (this.dom.meta) {
      this.dom.meta.textContent = `${fmtNumber(counts.nodes)} Knoten · ${fmtNumber(counts.edges)} Verbindungen · ${windowLabel} · ${fmtDate(data.generated_at)}`;
    }
    if (this.dom.empty) {
      this.dom.empty.hidden = !demo;
      if (demo) {
        this.dom.empty.innerHTML = `<b>DEMO-MODUS</b><span>${esc(data.demo_hinweis || 'Noch keine echte Datenquelle verbunden.')}</span>`;
      }
    }
    if (this.dom.spin) {
      this.dom.spin.textContent = this.spinOn ? 'Rotation pausieren' : 'Rotation fortsetzen';
      this.dom.spin.setAttribute('aria-pressed', String(!this.spinOn));
    }
  }

  renderRails(data) {
    const sources = data.sources || [];
    const departments = data.departments || [];
    if (this.dom.sources) {
      this.dom.sources.innerHTML = sources.map((s, i) => `
        <button type="button" class="g-rail-item ${s.active ? 'is-live' : 'is-idle'} ${this.selectedId === 'source:' + s.id ? 'is-selected' : ''}"
          data-node="source:${esc(s.id)}" aria-label="${esc(s.name)}" title="${esc(s.name)} — ${esc(s.hint)}">
          <span class="g-rail-index">${String(i + 1).padStart(2, '0')}</span>
          <span class="g-rail-main"><b>${esc(s.name)}</b><small>${esc(s.hint)}</small></span>
          <span class="g-rail-count">${fmtNumber(s.count)}<small>${esc(s.status)}</small></span>
        </button>`).join('');
    }
    if (this.dom.departments) {
      this.dom.departments.innerHTML = departments.map((d, i) => `
        <button type="button" class="g-rail-item is-dept ${d.active ? 'is-live' : 'is-idle'} ${this.selectedId === 'dept:' + d.id ? 'is-selected' : ''}"
          data-node="dept:${esc(d.id)}" aria-label="${esc(d.name)}" title="${esc(d.name)} — ${esc(d.hint)}">
          <span class="g-rail-index">${esc(d.id)}</span>
          <span class="g-rail-main"><b>${esc(d.name)}</b><small>${esc(d.hint)}</small></span>
          <span class="g-rail-count">${fmtNumber(d.agent_runs)}<small>${esc(d.status)}</small></span>
        </button>`).join('');
    }
    const selected = this.selectedId;
    [this.dom.sources, this.dom.departments].forEach(box => {
      if (!box) return;
      box.querySelectorAll('[data-node]').forEach(el => {
        el.classList.toggle('is-selected', el.dataset.node === selected);
      });
    });
  }

  renderLegend(data) {
    if (!this.dom.legend) return;
    const legend = data.legend || [];
    this.dom.legend.innerHTML = legend.map(l => `<span class="g-legend-item"><i style="background:${esc(l.color)}"></i>${esc(l.label)}</span>`).join('')
      + '<span class="g-legend-item is-muted"><i class="is-line"></i>Datenleitung</span>';
  }

  ensureDetailClose() {
    if (!this.dom.detail || this.dom.detail.dataset.bound) return;
    this.dom.detail.dataset.bound = '1';
    this.dom.detail.addEventListener('click', e => {
      if (e.target.closest('[data-close]')) this.clearSelection();
    });
  }

  selectNode(id, reveal = true) {
    const node = this.nodeById.get(id);
    if (!node) return;
    this.selectedId = id;
    this.renderRails(this.data || {});
    this.renderDetail(node);
    this.updateRings();
    if (reveal) this.selectHalo(id);
  }

  selectHalo(id) {
    this.selectionRing.visible = true;
    this.selectionId = id;
    this.updateRings();
  }

  clearSelection() {
    this.selectedId = null;
    this.selectionId = null;
    this.selectionRing.visible = false;
    this.hoveredId = null;
    this.hoverRing.visible = false;
    if (this.dom.detail) this.dom.detail.hidden = true;
    if (this.dom.tooltip) this.dom.tooltip.hidden = true;
    this.renderRails(this.data || {});
  }

  renderDetail(node) {
    const box = this.dom.detail;
    if (!box || !node) return;
    const relevance = node.relevance == null ? '—' : `${Math.round(node.relevance * 100)} %`;
    const related = node.related?.length ? node.related.slice(0, 5).join(' · ')
      : node.symbols?.length ? node.symbols.join(' · ')
        : node.tags?.length ? node.tags.slice(0, 5).join(' · ') : '—';
    const url = safeUrl(node.url);
    const extra = [];
    if (node.count != null) extra.push(`<span><small>Eingänge</small><b>${fmtNumber(node.count)}</b></span>`);
    if (node.agent_runs != null) extra.push(`<span><small>Agentenläufe</small><b>${fmtNumber(node.agent_runs)}</b></span>`);
    if (node.open_orders != null) extra.push(`<span><small>Offene Aufträge</small><b>${fmtNumber(node.open_orders)}</b></span>`);
    if (node.quality != null) extra.push(`<span><small>Quellenqualität</small><b>${fmtNumber(node.quality * 100)} %</b></span>`);
    box.innerHTML = `
      <div class="gd-top"><span class="gd-type ${node.demo ? 'is-demo' : ''}">${esc(node.demo ? 'DEMO · ' + node.category : node.category || 'Knoten')}</span>
        <button type="button" class="gd-close" data-close aria-label="Detailfenster schließen">×</button></div>
      <h3>${esc(node.title)}</h3>
      <p class="gd-summary">${esc(node.summary || node.detail || '')}</p>
      <div class="gd-grid">
        <span><small>Quelle</small><b>${esc(node.source || '—')}</b></span>
        <span><small>Zeitpunkt</small><b>${esc(fmtDate(node.time))}</b></span>
        <span><small>Relevanz</small><b>${esc(relevance)}</b></span>
        <span><small>Abteilung</small><b>${esc(node.department || '—')}</b></span>
        <span><small>Status</small><b>${esc(node.status || '—')}</b></span>
        <span><small>Verknüpft</small><b>${esc(related)}</b></span>
      </div>
      ${extra.length ? `<div class="gd-extra">${extra.join('')}</div>` : ''}
      ${node.detail && node.detail !== node.summary ? `<p class="gd-detail">${esc(node.detail)}</p>` : ''}
      ${url ? `<a class="gd-link" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Quelle öffnen <span>↗</span></a>` : ''}
    `;
    box.hidden = false;
  }

  showTooltip(node, event) {
    if (!this.dom.tooltip || !node) return;
    const rect = this.stage.getBoundingClientRect();
    const left = Math.min(rect.width - 230, Math.max(10, event.clientX - rect.left + 14));
    const top = Math.min(rect.height - 80, Math.max(10, event.clientY - rect.top + 14));
    this.dom.tooltip.innerHTML = `<b>${esc(node.title)}</b><span>${esc(node.category || '')} · ${esc(node.source || '')}</span>`;
    this.dom.tooltip.style.left = `${left}px`;
    this.dom.tooltip.style.top = `${top}px`;
    this.dom.tooltip.hidden = false;
  }

  hideTooltip() {
    if (this.dom.tooltip) this.dom.tooltip.hidden = true;
  }

  updateRings() {
    if (!this.selectionRing) return;
    const selected = this.selectedId;
    const mesh = selected ? this.nodeMeshes.get(selected) : null;
    const channel = selected ? this.channelMeshes.get(selected) : null;
    if (selected && (mesh || channel)) {
      this.selectionRing.visible = true;
      this.selectionId = selected;
    } else if (!selected) {
      this.selectionRing.visible = false;
    }
    if (this.hoveredId) {
      const hm = this.nodeMeshes.get(this.hoveredId);
      const hc = this.channelMeshes.get(this.hoveredId);
      this.hoverRing.visible = !!(hm || hc);
    } else {
      this.hoverRing.visible = false;
    }
  }

  setActive(active) {
    this.active = active;
    if (active) {
      this.resize();
      if (!this.raf) {
        this.lastFrame = performance.now();
        this.raf = requestAnimationFrame(this.loop);
      }
    } else if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
  }

  resetView() {
    this.rotY = 0.28;
    this.rotX = -0.10;
    this.zoom = 8.8;
    this.camera.position.z = this.zoom;
    this.spinOn = true;
    this.clearSelection();
    this.renderHud(this.data || {});
  }

  toggleSpin() {
    this.spinOn = !this.spinOn;
    this.renderHud(this.data || {});
  }

  bindEvents() {
    const canvas = this.canvas;
    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      this.dragging = true;
      this.moved = 0;
      this.startX = e.clientX;
      this.startY = e.clientY;
      this.lastX = e.clientX;
      this.lastY = e.clientY;
      this.lastInteraction = performance.now();
      canvas.setPointerCapture?.(e.pointerId);
      canvas.classList.add('is-grabbing');
      e.preventDefault();
    });
    canvas.addEventListener('pointermove', e => {
      if (!this.dragging) {
        this.hoverAt(e);
        return;
      }
      const dx = e.clientX - this.lastX;
      const dy = e.clientY - this.lastY;
      this.lastX = e.clientX;
      this.lastY = e.clientY;
      this.moved += Math.abs(dx) + Math.abs(dy);
      this.rotY += dx * 0.0055;
      this.rotX = Math.max(-1.05, Math.min(1.05, this.rotX + dy * 0.0035));
      this.lastInteraction = performance.now();
      this.sphereGroup.rotation.set(this.rotX, this.rotY, 0);
      this.hideTooltip();
    });
    canvas.addEventListener('pointerup', e => {
      if (!this.dragging) return;
      const wasClick = this.moved < 5;
      this.dragging = false;
      canvas.classList.remove('is-grabbing');
      canvas.releasePointerCapture?.(e.pointerId);
      if (wasClick) this.pickAt(e);
      this.lastInteraction = performance.now();
    });
    canvas.addEventListener('pointerleave', () => {
      if (!this.dragging) {
        this.hoveredId = null;
        this.hideTooltip();
      }
    });
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      this.zoom = Math.max(7.2, Math.min(12, this.zoom + e.deltaY * 0.0016));
      this.camera.position.z = this.zoom;
    }, { passive: false });
    this.dom.sources?.addEventListener('click', e => {
      const button = e.target.closest('[data-node]');
      if (button) this.selectNode(button.dataset.node);
    });
    this.dom.departments?.addEventListener('click', e => {
      const button = e.target.closest('[data-node]');
      if (button) this.selectNode(button.dataset.node);
    });
    this.dom.reset?.addEventListener('click', () => this.resetView());
    this.dom.spin?.addEventListener('click', () => this.toggleSpin());
    document.addEventListener('keydown', e => {
      if (!this.active) return;
      if (e.key === 'Escape') this.clearSelection();
      if (e.key === 'ArrowLeft') this.rotY -= 0.08;
      if (e.key === 'ArrowRight') this.rotY += 0.08;
      if (e.key === 'ArrowUp') this.rotX = Math.max(-1.05, this.rotX - 0.06);
      if (e.key === 'ArrowDown') this.rotX = Math.min(1.05, this.rotX + 0.06);
      if (e.key === '+' || e.key === '=') this.camera.position.z = Math.max(7.2, this.camera.position.z - 0.3);
      if (e.key === '-') this.camera.position.z = Math.min(12, this.camera.position.z + 0.3);
      if (e.key === 'r' || e.key === 'R') this.resetView();
    });
  }

  hoverAt(event) {
    const hit = this.pick(event);
    if (!hit) {
      this.hoveredId = null;
      this.hideTooltip();
      this.canvas.style.cursor = 'grab';
      return;
    }
    const id = hit.object.userData.nodeId;
    if (!this.nodeById.has(id)) {
      this.hoveredId = null;
      this.hideTooltip();
      return;
    }
    this.hoveredId = id;
    this.canvas.style.cursor = 'pointer';
    this.showTooltip(this.nodeById.get(id), event);
  }

  pick(event) {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.pickMeshes, false);
    return hits[0] || null;
  }

  pickAt(event) {
    const hit = this.pick(event);
    if (!hit) {
      this.clearSelection();
      return;
    }
    this.selectNode(hit.object.userData.nodeId);
  }

  loop(now) {
    if (!this.active) {
      this.raf = 0;
      return;
    }
    const dt = Math.min(0.05, (now - this.lastFrame) / 1000 || 0.016);
    this.lastFrame = now;
    if (this.spinOn && !this.dragging && now - this.lastInteraction > 1600 && !document.hidden) {
      this.rotY += (REDUCED ? 0.018 : 0.055) * dt;
    }
    this.sphereGroup.rotation.set(this.rotX, this.rotY, 0);
    if (this.atmosphere) {
      const breathe = 1 + Math.sin(now / 5200) * 0.025;
      this.atmosphere.scale.set(6.4 * breathe, 6.4 * breathe, 1);
    }
    this.nodeMeshes.forEach((mesh, id) => {
      const birth = this.nodeBirths.get(id);
      if (birth != null) {
        const progress = Math.max(0, Math.min(1, (now - birth) / 650));
        const ease = 1 - Math.pow(1 - progress, 3);
        const base = mesh.userData.node?.type === 'research' ? 1.35 : 1;
        mesh.scale.setScalar(base * ease);
        const halo = mesh.userData.halo;
        if (halo) halo.scale.setScalar((halo.userData.base || 0.3) * ease);
        if (progress >= 1) this.nodeBirths.delete(id);
      }
      if (mesh.userData.orderRing) {
        mesh.userData.orderRing.scale.setScalar(0.44 + Math.sin(now / 520) * 0.06);
      }
    });
    this.flowPulses.forEach(p => {
      p.t += p.speed * dt;
      if (p.t > 1) p.t -= 1;
      p.sprite.position.copy(p.curve.getPoint(p.t));
      const scale = 0.10 + Math.sin(p.t * Math.PI) * 0.05;
      p.sprite.scale.setScalar(scale);
    });
    this.positionRings();
    this.renderer.render(this.scene, this.camera);
    this.raf = requestAnimationFrame(this.loop);
  }

  positionRings() {
    if (this.selectionRing?.visible && this.selectionId) {
      const mesh = this.nodeMeshes.get(this.selectionId);
      const channel = this.channelMeshes.get(this.selectionId);
      if (mesh) {
        mesh.getWorldPosition(this.scratch);
        this.selectionRing.position.copy(this.scratch);
      } else if (channel) {
        this.selectionRing.position.copy(channel.position);
      } else {
        this.selectionRing.visible = false;
      }
      this.selectionRing.scale.setScalar(0.40 + Math.sin(performance.now() / 700) * 0.025);
    }
    if (this.hoverRing?.visible && this.hoveredId) {
      const mesh = this.nodeMeshes.get(this.hoveredId);
      const channel = this.channelMeshes.get(this.hoveredId);
      if (mesh) {
        mesh.getWorldPosition(this.scratch);
        this.hoverRing.position.copy(this.scratch);
      } else if (channel) {
        this.hoverRing.position.copy(channel.position);
      }
    }
  }

  showError(message) {
    if (this.dom.empty) {
      this.dom.empty.hidden = false;
      this.dom.empty.innerHTML = `<b>3D-ANSICHT NICHT VERFÜGBAR</b><span>${esc(message)}</span>`;
    }
    if (this.dom.activity) this.dom.activity.textContent = '3D-FEHLER';
  }

  disposeObject(object) {
    object.traverse?.(child => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach(m => {
          if (m.map && ![this.glow, this.ringTex].includes(m.map)) m.map.dispose();
          m.dispose();
        });
      }
    });
  }
}
