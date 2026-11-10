/* Phase 7: fester 3D-Nexus mit Spinne, echtem Graph und echter Aktivität.
 *
 * Die Szene liest ausschließlich /api/nexus/raum. Es gibt keine Demo-Knoten
 * und keine künstliche Aktivität: Beine bewegen sich nur bei laufenden
 * Missionen/Aufgaben, Graphknoten leuchten nur auf, wenn ein Refresh wirklich
 * neue IDs liefert. Die Kamera bleibt fest; Auswahl und Tooltip sind optional.
 */
import * as THREE from './vendor/three.module.js';

const TAU = Math.PI * 2;
const UP = new THREE.Vector3(0, 1, 0);
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const TYP_FARBE = { claim: 0x5fe0c8, quelle: 0x8fb8ff, thema: 0xe8b45a };
const ART_FARBE = { gehoert_zu: 0xe8b45a, belegt_durch: 0x5fe0c8, widerspruch: 0xe2616b };
const TYP_NAME = { claim: 'Kernaussage', quelle: 'Quelle', thema: 'Thema' };

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

function fmt(value) {
  return value == null || Number.isNaN(Number(value))
    ? '–' : Number(value).toLocaleString('de-CH');
}

function glowTexture(size = 128) {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const x = c.getContext('2d');
  const g = x.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.16, 'rgba(255,255,255,.9)');
  g.addColorStop(0.42, 'rgba(255,255,255,.3)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g;
  x.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function circlePoints(radius, count = 96, y = 0) {
  const points = [];
  for (let i = 0; i <= count; i++) {
    const a = (i / count) * TAU;
    points.push(new THREE.Vector3(Math.cos(a) * radius, y, Math.sin(a) * radius));
  }
  return points;
}

export class NexusRoom {
  constructor(stage) {
    this.stage = stage;
    this.canvas = document.getElementById('nexusCanvas');
    if (!this.canvas) throw new Error('Nexus-Canvas fehlt.');
    this.dom = {
      tooltip: document.getElementById('nexusTooltip'),
      pause: document.getElementById('nexusPause'),
      reset: document.getElementById('nexusReset'),
    };
    this.active = false;
    this.paused = REDUCED;
    this.running = false;
    this.hasLoaded = false;
    this.selectedId = null;
    this.hoveredId = null;
    this.data = null;
    this.seen = new Set();
    this.nodeById = new Map();
    this.nodeMeshes = new Map();
    this.pickMeshes = [];
    this.legs = [];
    this.edgeCurves = [];
    this.pulses = [];
    this.screens = [];
    this.lastFrame = 0;
    this.raf = 0;
    this.loop = this.loop.bind(this);
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.scratch = new THREE.Vector3();
    this.glow = glowTexture();
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
        canvas: this.canvas, alpha: true, antialias: true,
        powerPreference: 'high-performance',
      });
    } catch (error) {
      throw new Error('WebGL ist in diesem Browser nicht verfügbar.');
    }
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    this.camera.position.set(6.9, 4.8, 8.9);
    this.camera.lookAt(0, 1.35, 0);
    this.root = new THREE.Group();
    this.scene.add(this.root);
    this.scene.add(new THREE.HemisphereLight(0x8fe8ff, 0x061015, 0.7));
    const key = new THREE.PointLight(0x5fe0c8, 2.6, 22, 2);
    key.position.set(-3, 6, 5);
    this.scene.add(key);
    const warm = new THREE.PointLight(0xe8b45a, 1.1, 14, 2);
    warm.position.set(4, 3, 3);
    this.scene.add(warm);
    const rim = new THREE.PointLight(0x9df7ea, 1.5, 9, 2);
    rim.position.set(0, 4.2, 2.5);
    this.scene.add(rim);
    this.buildStars();
    this.buildRoom();
    this.buildScreens();
    this.buildSpider();
    this.graphGroup = new THREE.Group();
    this.root.add(this.graphGroup);
    this.selectionRing = this.makeRing(0x5fe0c8, 0.52);
    this.root.add(this.selectionRing);
    this.selectionRing.visible = false;
    this.updateLegs(0, false);
    this.canvas.addEventListener('webglcontextlost', event => {
      event.preventDefault();
      this.showError('Der WebGL-Kontext wurde unterbrochen. Bitte die Ansicht neu laden.');
    });
  }

  setCamera() {
    const rect = this.stage.getBoundingClientRect();
    const narrow = rect.width < 720;
    const f = narrow ? 1.2 : 1;
    this.camera.position.set(6.9 * f, 4.8 * f, 8.9 * f);
    this.camera.lookAt(0, 1.35, 0);
    this.camera.fov = narrow ? 44 : 40;
    this.camera.updateProjectionMatrix();
  }

  buildStars() {
    const count = 260;
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 12 + Math.random() * 15;
      const theta = Math.random() * TAU;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = Math.sin(phi) * Math.cos(theta) * r;
      positions[i * 3 + 1] = Math.cos(phi) * r + 2;
      positions[i * 3 + 2] = Math.sin(phi) * Math.sin(theta) * r;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    this.stars = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0x4b7893, size: 0.045, transparent: true, opacity: 0.4,
      depthWrite: false, sizeAttenuation: true,
    }));
    this.root.add(this.stars);
  }

  buildRoom() {
    const room = new THREE.Group();
    this.root.add(room);
    this.room = room;

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(5.7, 96),
      new THREE.MeshBasicMaterial({
        color: 0x061a1e, transparent: true, opacity: 0.88, side: THREE.DoubleSide,
      }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0.005;
    room.add(floor);

    const outer = new THREE.Mesh(
      new THREE.RingGeometry(5.52, 5.66, 96),
      new THREE.MeshBasicMaterial({
        color: 0x1d6368, transparent: true, opacity: 0.55, side: THREE.DoubleSide,
      }),
    );
    outer.rotation.x = -Math.PI / 2;
    outer.position.y = 0.012;
    room.add(outer);

    [1.1, 1.75, 2.45, 3.2, 4.0, 4.8, 5.35].forEach((radius, i) => {
      const geo = new THREE.BufferGeometry().setFromPoints(circlePoints(radius, 112, 0.02));
      const line = new THREE.LineLoop(geo, new THREE.LineBasicMaterial({
        color: i % 2 ? 0x16434a : 0x246c70, transparent: true,
        opacity: i % 2 ? 0.18 : 0.25, depthWrite: false,
      }));
      room.add(line);
    });

    for (let i = 0; i < 18; i++) {
      const angle = (i / 18) * TAU;
      const geo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(Math.cos(angle) * 1.15, 0.02, Math.sin(angle) * 1.15),
        new THREE.Vector3(Math.cos(angle) * 5.35, 0.02, Math.sin(angle) * 5.35),
      ]);
      room.add(new THREE.Line(geo, new THREE.LineBasicMaterial({
        color: 0x123b43, transparent: true, opacity: 0.18, depthWrite: false,
      })));
    }

    const dais = new THREE.Mesh(
      new THREE.CylinderGeometry(1.02, 1.18, 0.2, 48),
      new THREE.MeshStandardMaterial({
        color: 0x0a1c20, metalness: 0.55, roughness: 0.35,
        emissive: 0x082b2c, emissiveIntensity: 0.7,
      }),
    );
    dais.position.y = 0.11;
    room.add(dais);

    this.coreRing = new THREE.Mesh(
      new THREE.TorusGeometry(1.28, 0.018, 8, 96),
      new THREE.MeshBasicMaterial({
        color: 0x5fe0c8, transparent: true, opacity: 0.42,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }),
    );
    this.coreRing.rotation.x = Math.PI / 2;
    this.coreRing.position.y = 0.24;
    room.add(this.coreRing);

    this.coreHalo = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glow, color: 0x5fe0c8, transparent: true, opacity: 0.18,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    this.coreHalo.scale.set(2.8, 2.8, 1);
    this.coreHalo.position.set(0, 0.32, 0);
    room.add(this.coreHalo);

    for (let i = 0; i < 12; i++) {
      const angle = (i / 12) * TAU;
      const marker = new THREE.Mesh(
        new THREE.OctahedronGeometry(0.045, 0),
        new THREE.MeshBasicMaterial({
          color: i % 3 === 0 ? 0xe8b45a : 0x4fcbd1, transparent: true, opacity: 0.65,
        }),
      );
      marker.position.set(Math.cos(angle) * 5.25, 0.14, Math.sin(angle) * 5.25);
      room.add(marker);
    }
  }

  buildScreens() {
    const positions = [
      { x: -3.35, y: 3.25, z: -2.55, title: 'GRAPH' },
      { x: 3.35, y: 3.25, z: -2.55, title: 'AKTIVITÄT' },
    ];
    positions.forEach((pos, index) => {
      const canvas = document.createElement('canvas');
      canvas.width = 512;
      canvas.height = 256;
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(2.15, 1.08),
        new THREE.MeshBasicMaterial({
          map: texture, transparent: true, opacity: 0.92, side: THREE.DoubleSide,
        }),
      );
      const group = new THREE.Group();
      group.position.set(pos.x, pos.y, pos.z);
      group.add(mesh);
      const frame = new THREE.LineSegments(
        new THREE.EdgesGeometry(mesh.geometry),
        new THREE.LineBasicMaterial({
          color: index ? 0xe8b45a : 0x5fe0c8, transparent: true, opacity: 0.5,
        }),
      );
      group.add(frame);
      group.lookAt(this.camera.position);
      this.root.add(group);
      this.screens.push({ canvas, ctx: canvas.getContext('2d'), texture, mesh, group });
      this.drawScreen(index, pos.title, '–', 'wird geladen');
    });
  }

  drawScreen(index, title, value, detail) {
    const screen = this.screens[index];
    if (!screen) return;
    const { ctx, canvas } = screen;
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(4,16,20,.94)';
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = index ? 'rgba(232,180,90,.5)' : 'rgba(95,224,200,.5)';
    ctx.lineWidth = 3;
    ctx.strokeRect(1.5, 1.5, w - 3, h - 3);
    ctx.fillStyle = index ? '#e8b45a' : '#5fe0c8';
    ctx.font = '600 21px "Geist Mono", ui-monospace, monospace';
    ctx.fillText(title, 26, 44);
    ctx.fillStyle = '#d7e9ee';
    ctx.font = '700 68px "Geist Mono", ui-monospace, monospace';
    ctx.fillText(String(value), 24, 132);
    ctx.fillStyle = '#6f909b';
    ctx.font = '400 18px "Geist Mono", ui-monospace, monospace';
    ctx.fillText(String(detail).slice(0, 54), 26, 181);
    ctx.fillStyle = 'rgba(95,224,200,.22)';
    ctx.fillRect(26, 210, 460, 2);
    ctx.fillStyle = '#496d77';
    ctx.font = '400 14px "Geist Mono", ui-monospace, monospace';
    ctx.fillText('ORAKEL / PERSISTIERTE DATEN', 26, 235);
    screen.texture.needsUpdate = true;
  }

  buildSpider() {
    this.spider = new THREE.Group();
    this.spiderScale = 1.45;
    this.spiderBaseY = 0.94 * this.spiderScale;
    this.spider.scale.setScalar(this.spiderScale);
    this.spider.position.set(0, this.spiderBaseY, 0);
    this.root.add(this.spider);

    const shell = new THREE.MeshStandardMaterial({
      color: 0x243941, metalness: 0.48, roughness: 0.32,
      emissive: 0x0b3935, emissiveIntensity: 1.15,
    });
    const jointMat = new THREE.MeshStandardMaterial({
      color: 0x3d737a, metalness: 0.5, roughness: 0.26,
      emissive: 0x0f4a49, emissiveIntensity: 1.1,
    });
    const limbMat = new THREE.MeshStandardMaterial({
      color: 0x417b81, metalness: 0.42, roughness: 0.3,
      emissive: 0x0d3d3d, emissiveIntensity: 1.05,
    });

    const abdomen = new THREE.Mesh(new THREE.SphereGeometry(0.55, 28, 20), shell);
    abdomen.scale.set(0.9, 0.74, 1.2);
    abdomen.position.set(0, 0.14, -0.42);
    this.spider.add(abdomen);
    const abdomenGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glow, color: 0x5fe0c8, transparent: true, opacity: 0.2,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }));
    abdomenGlow.scale.set(1.42, 1.1, 1);
    abdomenGlow.position.set(0, 0.14, -0.42);
    this.spider.add(abdomenGlow);
    this.abdomenGlow = abdomenGlow;

    const head = new THREE.Mesh(new THREE.SphereGeometry(0.34, 24, 18), shell);
    head.position.set(0, 0.08, 0.48);
    this.spider.add(head);
    const eyeMat = new THREE.MeshBasicMaterial({ color: 0x9df7ea });
    [[-0.16, 0.14, 0.72], [0, 0.17, 0.77], [0.16, 0.14, 0.72],
      [-0.26, 0.06, 0.64], [0.26, 0.06, 0.64]].forEach(([x, y, z], i) => {
      const eye = new THREE.Mesh(new THREE.SphereGeometry(i === 1 ? 0.042 : 0.027, 10, 8), eyeMat);
      eye.position.set(x, y, z);
      this.spider.add(eye);
    });

    const fangMat = new THREE.MeshStandardMaterial({
      color: 0x8ec6c6, metalness: 0.4, roughness: 0.3,
    });
    [-0.13, 0.13].forEach(x => {
      const fang = new THREE.Mesh(new THREE.ConeGeometry(0.035, 0.3, 8), fangMat);
      fang.position.set(x, -0.15, 0.64);
      fang.rotation.x = Math.PI;
      this.spider.add(fang);
    });

    const segGeo = new THREE.CylinderGeometry(0.03, 0.043, 1, 7);
    for (const side of [-1, 1]) {
      for (let i = 0; i < 4; i++) {
        const hip = new THREE.Vector3(side * 0.27, 0.02, 0.36 - i * 0.25);
        const foot = new THREE.Vector3(
          side * (1.08 + i * 0.14), -0.93, 0.92 - i * 0.58,
        );
        const a = new THREE.Mesh(segGeo, limbMat);
        const b = new THREE.Mesh(segGeo, limbMat);
        const joint = new THREE.Mesh(new THREE.SphereGeometry(0.052, 9, 7), jointMat);
        this.spider.add(a, b, joint);
        this.legs.push({
          side, i, hip, foot, a, b, joint,
          phase: i * 1.35 + (side > 0 ? 0.7 : 0),
        });
      }
    }
  }

  updateLegs(time, running) {
    const active = running && !this.paused;
    this.legs.forEach(leg => {
      const foot = leg.foot.clone();
      if (active) {
        const lift = Math.max(0, Math.sin(time * 4.3 + leg.phase));
        foot.y += lift * 0.17;
        foot.z += Math.cos(time * 4.3 + leg.phase) * 0.12;
        foot.x += Math.sin(time * 3.1 + leg.phase) * 0.055;
      }
      const knee = new THREE.Vector3(
        leg.hip.x + (foot.x - leg.hip.x) * 0.46,
        0.34 + (active ? Math.sin(time * 4.3 + leg.phase) * 0.025 : 0),
        leg.hip.z + (foot.z - leg.hip.z) * 0.46,
      );
      this.placeSegment(leg.a, leg.hip, knee);
      this.placeSegment(leg.b, knee, foot);
      leg.joint.position.copy(knee);
    });
  }

  placeSegment(mesh, start, end) {
    const dir = end.clone().sub(start);
    const len = dir.length();
    mesh.position.copy(start).add(end).multiplyScalar(0.5);
    mesh.scale.set(1, Math.max(0.001, len), 1);
    mesh.quaternion.setFromUnitVectors(UP, dir.normalize());
  }

  makeRing(color, scale) {
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: this.glow, color, transparent: true, opacity: 0.92,
      blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
    }));
    sprite.scale.set(scale, scale, 1);
    return sprite;
  }

  setData(data) {
    this.data = data || {};
    const graph = this.data.graph || {};
    const nodes = (graph.knoten || []).slice(0, 120);
    const edges = (graph.kanten || []).slice(0, 220);
    const activity = this.data.aktivitaet || {};
    this.running = Number(activity.laufend || 0) > 0
      || Number(activity.tasks_aktiv || 0) > 0;
    const first = !this.hasLoaded;
    const newIds = nodes.filter(node => !this.seen.has(node.id)).map(node => node.id);
    this.hasLoaded = true;
    this.seen = new Set(nodes.map(node => node.id));
    this.nodeById = new Map(nodes.map(node => [node.id, node]));
    this.buildGraph(nodes, edges, first ? [] : newIds);
    if (this.selectedId && !this.nodeById.has(this.selectedId)) this.clearSelection();
    const zahlen = this.data.zahlen || {};
    this.drawScreen(0, 'GRAPH', fmt(zahlen.knoten), `${fmt(zahlen.kanten)} Kanten · ${fmt(zahlen.claims)} Claims`);
    this.drawScreen(1, 'AKTIVITÄT', fmt((activity.events || []).length),
      `${fmt(activity.laufend)} laufend · ${fmt(activity.offen)} offen`);
    if (this.dom.pause) {
      this.dom.pause.textContent = this.paused ? 'Bewegung fortsetzen' : 'Bewegung pausieren';
      this.dom.pause.setAttribute('aria-pressed', String(this.paused));
    }
  }

  buildGraph(nodes, edges, newIds) {
    while (this.graphGroup.children.length) {
      const child = this.graphGroup.children.pop();
      this.graphGroup.remove(child);
      this.disposeObject(child);
    }
    this.nodeMeshes.clear();
    this.pickMeshes = [];
    this.edgeCurves = [];
    this.pulses = [];
    if (!nodes.length) {
      this.selectionRing.visible = false;
      return;
    }

    const positionen = new Map();
    const counts = { claim: 0, quelle: 0, thema: 0 };
    const radius = { claim: 2.55, quelle: 4.18, thema: 3.42 };
    const baseY = { claim: 1.62, quelle: 0.56, thema: 2.92 };
    for (const node of nodes) {
      const typ = TYP_FARBE[node.typ] ? node.typ : 'thema';
      const index = counts[typ]++;
      const angle = index * 2.3999632297 + hash(node.id) * 0.8
        + (typ === 'quelle' ? 0.65 : typ === 'thema' ? 1.25 : 0);
      const r = radius[typ] + (index % 3) * 0.17;
      const y = baseY[typ] + (index % 4) * 0.17;
      const pos = new THREE.Vector3(Math.cos(angle) * r, y, Math.sin(angle) * r);
      positionen.set(node.id, pos);
    }

    const edgeGroups = new Map();
    for (const edge of edges) {
      const a = positionen.get(edge.von);
      const b = positionen.get(edge.nach);
      if (!a || !b) continue;
      const mid = a.clone().add(b).multiplyScalar(0.5);
      mid.y += 0.42;
      const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
      if (!edgeGroups.has(edge.art)) edgeGroups.set(edge.art, []);
      edgeGroups.get(edge.art).push(curve);
      this.edgeCurves.push(curve);
    }
    for (const [art, curves] of edgeGroups) {
      const positions = [];
      for (const curve of curves) {
        const pts = curve.getPoints(9);
        for (let i = 0; i < pts.length - 1; i++) {
          positions.push(pts[i].x, pts[i].y, pts[i].z, pts[i + 1].x, pts[i + 1].y, pts[i + 1].z);
        }
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      const line = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({
        color: ART_FARBE[art] || 0x4b7d88, transparent: true,
        opacity: art === 'widerspruch' ? 0.52 : 0.3,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      this.graphGroup.add(line);
    }

    const newSet = new Set(newIds);
    for (const node of nodes) {
      const typ = TYP_FARBE[node.typ] ? node.typ : 'thema';
      const pos = positionen.get(node.id);
      if (!pos) continue;
      const color = new THREE.Color(TYP_FARBE[typ]);
      const size = typ === 'claim' ? 0.12 : typ === 'quelle' ? 0.1 : 0.085;
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(size, 12, 10),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.98 }),
      );
      mesh.position.copy(pos);
      mesh.userData.nodeId = node.id;
      mesh.userData.node = node;
      mesh.userData.baseScale = 1;
      mesh.userData.flashUntil = newSet.has(node.id) ? performance.now() + 1900 : 0;
      this.graphGroup.add(mesh);
      const halo = new THREE.Sprite(new THREE.SpriteMaterial({
        map: this.glow, color, transparent: true, opacity: 0.5,
        blending: THREE.AdditiveBlending, depthWrite: false,
      }));
      halo.scale.setScalar(typ === 'claim' ? 0.46 : 0.34);
      halo.position.copy(pos);
      this.graphGroup.add(halo);
      mesh.userData.halo = halo;
      this.nodeMeshes.set(node.id, mesh);
      this.pickMeshes.push(mesh);
    }

    if (this.running) {
      const step = Math.max(1, Math.floor(this.edgeCurves.length / 8));
      for (let i = 0; i < this.edgeCurves.length && this.pulses.length < 8; i += step) {
        const curve = this.edgeCurves[i];
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
          map: this.glow, color: 0x9df7ea, transparent: true, opacity: 0.82,
          blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false,
        }));
        sprite.scale.setScalar(0.16);
        this.graphGroup.add(sprite);
        this.pulses.push({ sprite, curve, t: hash(`${i}:${this.edgeCurves.length}`) });
      }
    }
    if (this.selectedId && this.nodeMeshes.has(this.selectedId)) {
      this.positionSelection();
    } else {
      this.selectionRing.visible = false;
    }
  }

  positionSelection() {
    if (!this.selectedId) return;
    const mesh = this.nodeMeshes.get(this.selectedId);
    if (!mesh) {
      this.selectionRing.visible = false;
      return;
    }
    mesh.getWorldPosition(this.scratch);
    this.selectionRing.position.copy(this.scratch);
    this.selectionRing.visible = true;
  }

  selectNode(id) {
    if (!this.nodeMeshes.has(id)) return;
    this.selectedId = id;
    this.positionSelection();
    const node = this.nodeById.get(id);
    if (node) this.showTooltip(node, null);
    this.stage.dispatchEvent(new CustomEvent('nexusselection', {
      detail: id, bubbles: true,
    }));
  }

  clearSelection() {
    this.selectedId = null;
    this.selectionRing.visible = false;
    if (this.dom.tooltip) this.dom.tooltip.hidden = true;
    this.stage.dispatchEvent(new CustomEvent('nexusselection', {
      detail: null, bubbles: true,
    }));
  }

  showTooltip(node, event) {
    if (!this.dom.tooltip || !node) return;
    const rect = this.stage.getBoundingClientRect();
    const x = event ? event.clientX - rect.left + 14 : rect.width * 0.52;
    const y = event ? event.clientY - rect.top + 14 : rect.height * 0.42;
    this.dom.tooltip.innerHTML = `<b>${esc(node.label)}</b><span>${esc(
      TYP_NAME[node.typ] || node.typ,
    )}${node.status ? ' · ' + esc(node.status) : ''}</span>`;
    this.dom.tooltip.style.left = `${Math.min(rect.width - 210, Math.max(10, x))}px`;
    this.dom.tooltip.style.top = `${Math.min(rect.height - 70, Math.max(10, y))}px`;
    this.dom.tooltip.hidden = false;
  }

  hideTooltip() {
    if (this.dom.tooltip) this.dom.tooltip.hidden = true;
    this.hoveredId = null;
  }

  pick(event) {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster.intersectObjects(this.pickMeshes, false)[0] || null;
  }

  hoverAt(event) {
    const hit = this.pick(event);
    if (!hit) {
      this.hideTooltip();
      this.canvas.style.cursor = 'default';
      return;
    }
    const id = hit.object.userData.nodeId;
    const node = this.nodeById.get(id);
    if (!node) return;
    this.hoveredId = id;
    this.canvas.style.cursor = 'pointer';
    this.showTooltip(node, event);
  }

  bindEvents() {
    this.canvas.addEventListener('pointermove', event => this.hoverAt(event));
    this.canvas.addEventListener('pointerleave', () => this.hideTooltip());
    this.canvas.addEventListener('click', event => {
      const hit = this.pick(event);
      if (hit) this.selectNode(hit.object.userData.nodeId);
      else this.clearSelection();
    });
    this.dom.reset?.addEventListener('click', () => this.resetView());
    this.dom.pause?.addEventListener('click', () => this.togglePause());
    this.stage.addEventListener('keydown', event => {
      if (event.key === 'Escape') this.clearSelection();
    });
  }

  togglePause() {
    this.paused = !this.paused;
    if (this.dom.pause) {
      this.dom.pause.textContent = this.paused ? 'Bewegung fortsetzen' : 'Bewegung pausieren';
      this.dom.pause.setAttribute('aria-pressed', String(this.paused));
    }
  }

  resetView() {
    this.setCamera();
    this.clearSelection();
    this.hideTooltip();
    this.resize();
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

  resize() {
    const rect = this.stage.getBoundingClientRect();
    const w = Math.max(1, rect.width || 800);
    const h = Math.max(1, rect.height || 620);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.setCamera();
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.8));
    this.layoutScreens(w < 720);
    if (this.renderer) this.renderer.render(this.scene, this.camera);
  }

  layoutScreens(narrow) {
    const x = narrow ? 2.28 : 3.35;
    const y = narrow ? 2.92 : 3.25;
    const scale = narrow ? 0.76 : 1;
    this.screens.forEach((screen, index) => {
      screen.group.position.set(index ? x : -x, y, -2.55);
      screen.group.scale.setScalar(scale);
      screen.group.lookAt(this.camera.position);
    });
  }

  loop(now) {
    if (!this.active) {
      this.raf = 0;
      return;
    }
    const dt = Math.min(0.05, (now - this.lastFrame) / 1000 || 0.016);
    this.lastFrame = now;
    const t = now / 1000;
    this.spider.position.y = this.spiderBaseY + (this.paused ? 0 : Math.sin(t * 0.9) * 0.012);
    this.abdomenGlow.material.opacity = this.running ? 0.34 : 0.2;
    this.coreRing.rotation.z += this.running && !this.paused ? dt * 0.55 : 0;
    this.coreRing.material.opacity = this.running
      ? 0.48 + Math.sin(t * 3.1) * 0.13 : 0.26;
    this.coreHalo.material.opacity = this.running
      ? 0.26 + Math.sin(t * 2.4) * 0.07 : 0.14;
    this.updateLegs(t, this.running && !this.paused);
    this.nodeMeshes.forEach(mesh => {
      const flash = mesh.userData.flashUntil || 0;
      if (flash > now) {
        const p = 1 - (flash - now) / 1900;
        const scale = 1 + Math.sin(Math.min(1, p) * Math.PI) * 0.9;
        mesh.scale.setScalar(scale);
        mesh.userData.halo.material.opacity = 0.5 + Math.sin(Math.min(1, p) * Math.PI) * 0.45;
      } else {
        mesh.scale.setScalar(1);
        mesh.userData.halo.material.opacity = 0.5;
      }
    });
    if (this.selectedId) {
      this.positionSelection();
      this.selectionRing.scale.setScalar(0.52 + Math.sin(t * 3) * 0.03);
    }
    this.pulses.forEach(pulse => {
      pulse.t = (pulse.t + (this.running && !this.paused ? 0.0045 : 0)) % 1;
      pulse.sprite.position.copy(pulse.curve.getPoint(pulse.t));
      pulse.sprite.visible = this.running;
    });
    this.renderer.render(this.scene, this.camera);
    this.raf = requestAnimationFrame(this.loop);
  }

  showError(message) {
    this.running = false;
    this.paused = true;
    if (this.dom.pause) {
      this.dom.pause.textContent = 'Bewegung pausiert';
      this.dom.pause.setAttribute('aria-pressed', 'true');
    }
    if (this.dom.tooltip) this.dom.tooltip.hidden = true;
    this.stage.dataset.error = String(message || '3D-Ansicht nicht verfügbar');
  }

  disposeObject(object) {
    object.traverse?.(child => {
      if (child.geometry) child.geometry.dispose();
      if (child.material) {
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.forEach(material => {
          if (material.map && material.map !== this.glow) material.map.dispose();
          material.dispose();
        });
      }
    });
  }
}
