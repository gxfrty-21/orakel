/* Command Center E6 — erster begehbarer 3D-Prototyp.
 *
 * Die Szene ist eine Darstellung, keine Datenquelle. Screens und Hologramm
 * werden ausschließlich aus /api/report und /api/betrieb aktualisiert. Fehlt
 * eine Grundlage, steht «KEINE DATEN» auf dem Schirm. Die acht Stationen
 * entsprechen den acht echten Abteilungen A–H; es gibt keine erfundenen
 * Agenten oder Räume.
 */
import * as THREE from './vendor/three.module.js';

const TAU = Math.PI * 2;
const EYE = 1.68;
const ROOM_X = 11;
const ROOM_Z = 7;
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const DEP = {
  A: 'Hauptzentrale',
  B: 'Spider Intelligence',
  C: 'Labor',
  D: 'Trading Floor',
  E: 'Forschungsabteilung',
  F: 'Risikomanagement',
  G: 'Wissenszentrum',
  H: 'Entwicklungsabteilung',
};
const ORDER = Object.keys(DEP);
const ACCENT = '#5fe0c8';
const AMBER = '#e8b45a';
const BAD = '#e2616b';

function clamp(wert, min, max) {
  return Math.max(min, Math.min(max, wert));
}

function kurz(wert) {
  if (!wert) return 'KEINE DATEN';
  return String(wert).replace('T', ' ').slice(0, 16);
}

function zahl(wert) {
  return wert == null || Number.isNaN(Number(wert))
    ? 'KEINE DATEN' : Number(wert).toLocaleString('de-CH');
}

function kappe(ctx, text, maxBreite) {
  const roh = String(text ?? '');
  if (ctx.measureText(roh).width <= maxBreite) return roh;
  let out = roh;
  while (out.length > 1 && ctx.measureText(out + '…').width > maxBreite) {
    out = out.slice(0, -1);
  }
  return out + '…';
}

function panelMachen(breite = 512, hoehe = 256) {
  const canvas = document.createElement('canvas');
  canvas.width = breite;
  canvas.height = hoehe;
  const ctx = canvas.getContext('2d');
  const texture = new THREE.CanvasTexture(canvas);
  if (THREE.SRGBColorSpace) texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  return { canvas, ctx, texture };
}

function panelZeichnen(panel, titel, zeilen, akzent = ACCENT, fuss = '') {
  const { ctx, canvas, texture } = panel;
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#061014';
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = akzent;
  ctx.fillRect(0, 0, w, 4);
  ctx.fillStyle = 'rgba(95,224,200,.06)';
  ctx.fillRect(0, 4, w, 36);

  ctx.font = '600 20px "Geist Mono", ui-monospace, monospace';
  ctx.fillStyle = akzent;
  ctx.textAlign = 'left';
  ctx.fillText(kappe(ctx, titel.toUpperCase(), w - 48), 24, 30);

  let y = 78;
  const zeilenHoehe = Math.min(42, (h - 112) / Math.max(zeilen.length, 1));
  for (const [label, wert] of zeilen) {
    ctx.font = '500 12px "Geist Mono", ui-monospace, monospace';
    ctx.fillStyle = '#587b87';
    ctx.textAlign = 'left';
    ctx.fillText(String(label).toUpperCase(), 24, y);
    ctx.font = '500 19px "Geist Mono", ui-monospace, monospace';
    ctx.fillStyle = '#d6e9ee';
    ctx.textAlign = 'right';
    ctx.fillText(kappe(ctx, wert, w - 190), w - 24, y + 1);
    ctx.strokeStyle = 'rgba(95,224,200,.10)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(24, y + 13);
    ctx.lineTo(w - 24, y + 13);
    ctx.stroke();
    y += zeilenHoehe;
  }

  if (fuss) {
    ctx.font = '500 10px "Geist Mono", ui-monospace, monospace';
    ctx.fillStyle = '#456672';
    ctx.textAlign = 'left';
    ctx.fillText(kappe(ctx, fuss, w - 48), 24, h - 18);
  }
  texture.needsUpdate = true;
}

function standardMaterial(farbe, optionen = {}) {
  return new THREE.MeshStandardMaterial({
    color: farbe,
    roughness: 0.72,
    metalness: 0.36,
    ...optionen,
  });
}

function boxMachen(parent, w, h, d, x, y, z, material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  mesh.position.set(x, y, z);
  parent.add(mesh);
  return mesh;
}

function screenMachen(panel, breite, hoehe, farbe = ACCENT) {
  const mat = new THREE.MeshBasicMaterial({
    map: panel.texture,
    toneMapped: false,
  });
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(breite, hoehe), mat);
  screen.userData.panel = panel;
  screen.userData.farbe = farbe;
  return screen;
}

export class CommandDeck {
  constructor(stage) {
    this.stage = stage;
    this.canvas = stage.querySelector('#commandCanvas');
    if (!this.canvas) throw new Error('Command-Canvas fehlt.');
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    if (THREE.SRGBColorSpace) this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x03080b, 1);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x03080b);
    this.scene.fog = new THREE.FogExp2(0x03080b, 0.028);
    this.camera = new THREE.PerspectiveCamera(68, 1, 0.05, 80);
    this.camera.rotation.order = 'YXZ';
    this.camera.position.set(0, EYE, 6.15);
    this.yaw = 0;
    this.pitch = 0;
    this.velocity = new THREE.Vector3();
    this.keys = new Set();
    this.obstacles = [];
    this.active = false;
    this.locked = false;
    this._raf = null;
    this._last = 0;
    this._resizeObserver = null;
    this.report = null;
    this.betrieb = null;

    this.central = panelMachen(1024, 512);
    this.screens = {};
    this.stationScreens = {};
    this.stationen = {};
    this.standort = null;
    this._bauen();
    this._zeichneLeer();
    this._binden();
    this._beobachteGroesse();
  }

  _bauen() {
    const root = new THREE.Group();
    this.root = root;
    this.scene.add(root);

    const boden = new THREE.Mesh(
      new THREE.PlaneGeometry(22, 14),
      standardMaterial(0x0b1b21, { roughness: 0.84, metalness: 0.25 }),
    );
    boden.rotation.x = -Math.PI / 2;
    root.add(boden);

    const raster = new THREE.GridHelper(22, 44, 0x1b5a63, 0x10262d);
    raster.position.y = 0.012;
    raster.material.transparent = true;
    raster.material.opacity = 0.3;
    root.add(raster);

    const wandMat = standardMaterial(0x0c1b22, { roughness: 0.82, metalness: 0.3 });
    const deckeMat = standardMaterial(0x081218, { roughness: 0.95, metalness: 0.1 });
    const hinten = new THREE.Mesh(new THREE.PlaneGeometry(22, 5.6), wandMat);
    hinten.position.set(0, 2.8, -7);
    root.add(hinten);
    for (const seite of [-1, 1]) {
      const wand = new THREE.Mesh(new THREE.PlaneGeometry(14, 5.6), wandMat);
      wand.position.set(seite * 11, 2.8, 0);
      wand.rotation.y = seite * Math.PI / 2;
      root.add(wand);
    }
    const vorne = new THREE.Mesh(new THREE.PlaneGeometry(22, 5.6), wandMat);
    vorne.position.set(0, 2.8, 7);
    vorne.rotation.y = Math.PI;
    root.add(vorne);
    const decke = new THREE.Mesh(new THREE.PlaneGeometry(22, 14), deckeMat);
    decke.position.set(0, 5.6, 0);
    decke.rotation.x = Math.PI / 2;
    root.add(decke);

    const balkenMat = standardMaterial(0x111f26, { roughness: 0.55, metalness: 0.55 });
    for (let x = -8; x <= 8; x += 4) {
      boxMachen(root, 0.16, 0.22, 14, x, 5.38, 0, balkenMat);
    }
    const streifenMat = new THREE.MeshBasicMaterial({ color: 0x2b8f92 });
    for (const seite of [-1, 1]) {
      boxMachen(root, 0.05, 0.025, 12.8, seite * 10.88, 0.04, 0, streifenMat);
      boxMachen(root, 0.05, 0.025, 12.8, seite * 10.88, 5.32, 0, streifenMat);
      for (const z of [-5.2, -2.6, 0, 2.6, 5.2]) {
        boxMachen(root, 0.035, 2.5, 0.035, seite * 10.9, 2.6, z, streifenMat);
      }
    }
    for (let x = -8; x <= 8; x += 4) {
      boxMachen(root, 0.035, 0.035, 12.8, x, 5.33, 0, streifenMat);
    }
    const deckenlichtMat = new THREE.MeshBasicMaterial({ color: 0x9df7ea });
    for (const x of [-7, 0, 7]) {
      boxMachen(root, 0.08, 0.035, 5.2, x, 5.48, 0, deckenlichtMat);
    }

    const rahmenMat = standardMaterial(0x14242c, { roughness: 0.4, metalness: 0.7 });
    for (const seite of [-1, 1]) {
      const tuer = new THREE.Group();
      tuer.position.set(seite * 10.94, 0, 0);
      tuer.rotation.y = seite * Math.PI / 2;
      boxMachen(tuer, 2.4, 0.14, 0.18, 0, 2.7, 0, rahmenMat);
      boxMachen(tuer, 2.4, 0.14, 0.18, 0, 0.12, 0, rahmenMat);
      boxMachen(tuer, 0.14, 2.7, 0.18, -1.13, 1.4, 0, rahmenMat);
      boxMachen(tuer, 0.14, 2.7, 0.18, 1.13, 1.4, 0, rahmenMat);
      const licht = boxMachen(tuer, 1.8, 0.035, 0.03, 0, 2.6, 0.1,
        new THREE.MeshBasicMaterial({ color: 0x5fe0c8 }));
      licht.userData.licht = true;
      root.add(tuer);
    }

    const tischMat = standardMaterial(0x101c22, { roughness: 0.45, metalness: 0.7 });
    const kanteMat = new THREE.MeshBasicMaterial({ color: 0x5fe0c8 });
    boxMachen(root, 5.2, 0.12, 5.2, 0, 0.92, 0, tischMat);
    boxMachen(root, 4.7, 0.72, 4.7, 0, 0.5, 0, standardMaterial(0x0b151a));
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.62, 0.035, 8, 96), kanteMat);
    ring.position.y = 1.0;
    ring.rotation.x = Math.PI / 2;
    root.add(ring);

    const hologram = new THREE.Group();
    const kern = new THREE.Mesh(
      new THREE.IcosahedronGeometry(1.12, 2),
      new THREE.MeshBasicMaterial({ color: 0x5fe0c8, wireframe: true, transparent: true, opacity: 0.55 }),
    );
    kern.position.y = 2.0;
    hologram.add(kern);
    for (let i = 0; i < 3; i++) {
      const orbit = new THREE.Mesh(
        new THREE.TorusGeometry(1.35 + i * 0.18, 0.012, 5, 72),
        new THREE.MeshBasicMaterial({ color: i === 1 ? 0xe8b45a : 0x5fe0c8, transparent: true, opacity: 0.45 }),
      );
      orbit.position.y = 2.0;
      orbit.rotation.x = Math.PI / 2 + i * 0.3;
      orbit.rotation.z = i * 0.55;
      orbit.userData.orbit = i;
      hologram.add(orbit);
    }
    this.hologram = hologram;
    root.add(hologram);

    const zentral = screenMachen(this.central, 4.1, 2.05);
    zentral.position.set(0, 3.45, 0);
    root.add(zentral);
    this.zentralScreen = zentral;

    const grosse = [
      { key: 'takt', x: -7.0, titel: 'DAUERBETRIEB / TAKT' },
      { key: 'risiko', x: 0, titel: 'RISIKO / PAPER' },
      { key: 'agenten', x: 7.0, titel: 'AGENTEN / ABTEILUNGEN' },
    ];
    for (const def of grosse) {
      const panel = panelMachen(1024, 512);
      const gruppe = new THREE.Group();
      gruppe.position.set(def.x, 3.18, -6.86);
      boxMachen(gruppe, 6.15, 3.05, 0.12, 0, 0, -0.05, rahmenMat);
      const screen = screenMachen(panel, 5.85, 2.8);
      screen.position.z = 0.03;
      gruppe.add(screen);
      root.add(gruppe);
      this.screens[def.key] = { panel, titel: def.titel };
    }

    ORDER.forEach((key, index) => {
      const winkel = ((index + 0.5) / ORDER.length) * TAU;
      const x = Math.sin(winkel) * 7.05;
      const z = Math.cos(winkel) * 4.45;
      const gruppe = new THREE.Group();
      gruppe.position.set(x, 0, z);
      gruppe.lookAt(0, 0, 0);
      const pultMat = standardMaterial(0x0f1b21, { roughness: 0.55, metalness: 0.5 });
      boxMachen(gruppe, 2.05, 0.12, 0.9, 0, 0.78, 0, pultMat);
      boxMachen(gruppe, 1.7, 0.7, 0.72, 0, 0.39, 0, pultMat);
      boxMachen(gruppe, 0.08, 0.05, 0.3, 0, 0.82, 0.28,
        new THREE.MeshBasicMaterial({ color: 0x5fe0c8 }));
      boxMachen(gruppe, 1.82, 1.02, 0.08, 0, 1.35, 0.17, rahmenMat);
      const panel = panelMachen(512, 256);
      const screen = screenMachen(panel, 1.62, 0.82);
      screen.position.set(0, 1.35, 0.23);
      gruppe.add(screen);
      const stuhl = new THREE.Mesh(
        new THREE.CylinderGeometry(0.28, 0.32, 0.12, 16),
        standardMaterial(0x111e24),
      );
      stuhl.position.set(0, 0.52, -0.78);
      gruppe.add(stuhl);
      root.add(gruppe);
      this.stationScreens[key] = panel;
      this.stationen[key] = { x, z };
      this.obstacles.push({ x, z, r: 1.12 });
    });

    this.scene.add(new THREE.HemisphereLight(0xb4f0e8, 0x0d1a20, 1.0));
    this.scene.add(new THREE.AmbientLight(0x7fb4c0, 0.42));
    const lichter = [
      [0, 4.7, 0, 0x5fe0c8, 28],
      [-6.2, 4.2, -1.5, 0xe8b45a, 14],
      [6.2, 4.2, -1.5, 0x8fb8ff, 14],
      [0, 1.5, 5.2, 0x5fe0c8, 10],
    ];
    for (const [x, y, z, farbe, stärke] of lichter) {
      const licht = new THREE.PointLight(farbe, stärke, 16, 2);
      licht.position.set(x, y, z);
      root.add(licht);
    }

    this.obstacles.push({ x: 0, z: 0, r: 2.65 });
  }

  _zeichneLeer() {
    for (const panel of Object.values(this.stationScreens)) {
      panelZeichnen(panel, 'WIRD GELADEN', [['DATEN', 'KEINE DATEN']], ACCENT,
        'WARTE AUF /api/report');
    }
    panelZeichnen(this.central, 'COMMAND CENTER / E6', [
      ['TAKT', 'KEINE DATEN'],
      ['AGENTEN', 'KEINE DATEN'],
      ['DATENQUELLE', 'WIRD GELADEN'],
    ], ACCENT, 'DIE BRÜCKE ZEIGT NUR ECHTE API-DATEN');
    for (const def of Object.values(this.screens)) {
      panelZeichnen(def.panel, def.titel, [['STATUS', 'KEINE DATEN']], ACCENT,
        'WARTE AUF API');
    }
  }

  _binden() {
    this._onKeyDown = (event) => {
      if (!this.active || !this.locked) return;
      if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ShiftLeft', 'ShiftRight'].includes(event.code)) {
        event.preventDefault();
        this.keys.add(event.code);
      }
    };
    this._onKeyUp = (event) => {
      this.keys.delete(event.code);
    };
    this._onMouseMove = (event) => {
      if (!this.locked) return;
      this.yaw -= event.movementX * 0.0023;
      this.pitch -= event.movementY * 0.0023;
      this.pitch = clamp(this.pitch, -1.15, 1.15);
    };
    this._onPointerLock = () => {
      this.locked = document.pointerLockElement === this.canvas;
      if (!this.locked) this.keys.clear();
      this._modusMelden();
    };
    this._onBlur = () => this.keys.clear();
    this._onCanvasClick = () => {
      if (this.active && !this.locked) this.enter();
    };

    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
    window.addEventListener('blur', this._onBlur);
    document.addEventListener('mousemove', this._onMouseMove);
    document.addEventListener('pointerlockchange', this._onPointerLock);
    this.canvas.addEventListener('click', this._onCanvasClick);
  }

  _beobachteGroesse() {
    this._onResize = () => this.resize();
    window.addEventListener('resize', this._onResize);
    if (typeof ResizeObserver !== 'undefined') {
      this._resizeObserver = new ResizeObserver(() => this.resize());
      this._resizeObserver.observe(this.stage);
    }
  }

  _modusMelden() {
    this.stage.dispatchEvent(new CustomEvent('commandmode', {
      detail: { active: this.active, locked: this.locked },
    }));
  }

  resize() {
    const breite = Math.max(1, this.stage.clientWidth);
    const hoehe = Math.max(1, this.stage.clientHeight);
    if (breite < 2 || hoehe < 2) return;
    this.renderer.setSize(breite, hoehe, false);
    this.camera.aspect = breite / hoehe;
    this.camera.updateProjectionMatrix();
  }

  setActive(active) {
    const neu = Boolean(active);
    if (this.active === neu) {
      if (neu) this.resize();
      return;
    }
    this.active = neu;
    if (!neu) {
      if (document.pointerLockElement === this.canvas) document.exitPointerLock();
      this.keys.clear();
      this.velocity.set(0, 0, 0);
      if (this._raf) {
        cancelAnimationFrame(this._raf);
        this._raf = null;
      }
    } else {
      this.resize();
      this._last = performance.now();
      this._modusMelden();
      this._raf = requestAnimationFrame(this.animate);
    }
    this._modusMelden();
  }

  enter() {
    if (!this.active) return;
    if (this.locked) return;
    this.canvas.focus();
    const anfrage = this.canvas.requestPointerLock();
    if (anfrage && typeof anfrage.catch === 'function') {
      anfrage.catch(() => {
        this.stage.dispatchEvent(new CustomEvent('commandmode', {
          detail: { active: this.active, locked: false, fehler: 'Mauszeiger konnte nicht gesperrt werden.' },
        }));
      });
    }
  }

  reset() {
    this.camera.position.set(0, EYE, 6.15);
    this.yaw = 0;
    this.pitch = 0;
    this.camera.rotation.x = 0;
    this.camera.rotation.y = 0;
    this.velocity.set(0, 0, 0);
    this.standort = null;
    this._modusMelden();
  }

  reiseZu(key) {
    const station = this.stationen[key];
    if (!station) return false;
    const radius = Math.hypot(station.x, station.z) || 1;
    const rueck = 1.7;
    const px = station.x * (1 - rueck / radius);
    const pz = station.z * (1 - rueck / radius);
    this.camera.position.set(px, EYE, pz);
    this.yaw = Math.atan2(-(station.x - px), -(station.z - pz));
    this.pitch = -0.17;
    this.camera.rotation.x = this.pitch;
    this.camera.rotation.y = this.yaw;
    this.velocity.set(0, 0, 0);
    this.keys.clear();
    this.standort = key;
    this._modusMelden();
    return true;
  }

  _bewegen(dt) {
    const vorne = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    const rechts = new THREE.Vector3(Math.cos(this.yaw), 0, -Math.sin(this.yaw));
    const richtung = new THREE.Vector3();
    if (this.keys.has('KeyW')) richtung.add(vorne);
    if (this.keys.has('KeyS')) richtung.sub(vorne);
    if (this.keys.has('KeyD')) richtung.add(rechts);
    if (this.keys.has('KeyA')) richtung.sub(rechts);
    if (richtung.lengthSq() > 0) richtung.normalize();
    const tempo = this.keys.has('ShiftLeft') || this.keys.has('ShiftRight') ? 5.2 : 2.9;
    richtung.multiplyScalar(tempo);
    this.velocity.lerp(richtung, 1 - Math.exp(-9 * dt));
    const naechste = this.camera.position.clone().addScaledVector(this.velocity, dt);
    naechste.x = clamp(naechste.x, -ROOM_X + 0.42, ROOM_X - 0.42);
    naechste.z = clamp(naechste.z, -ROOM_Z + 0.42, ROOM_Z - 0.42);
    for (const o of this.obstacles) {
      const dx = naechste.x - o.x;
      const dz = naechste.z - o.z;
      const abstand = Math.hypot(dx, dz);
      const mindest = o.r + 0.36;
      if (abstand < mindest && abstand > 0.0001) {
        naechste.x = o.x + dx / abstand * mindest;
        naechste.z = o.z + dz / abstand * mindest;
      }
    }
    this.camera.position.copy(naechste);
    this.camera.position.y = EYE;
    this.camera.rotation.x = this.pitch;
    this.camera.rotation.y = this.yaw;
  }

  animate = (now) => {
    if (!this.active) {
      this._raf = null;
      return;
    }
    const dt = Math.min(0.05, Math.max(0, (now - this._last) / 1000));
    this._last = now;
    this._raf = requestAnimationFrame(this.animate);
    this._bewegen(dt);
    if (this.hologram) {
      this.hologram.rotation.y += dt * (REDUCED ? 0.02 : 0.12);
      this.hologram.children.forEach((kind, i) => {
        if (kind.userData.orbit != null) kind.rotation.z += dt * (0.04 + i * 0.015);
      });
    }
    this.renderer.render(this.scene, this.camera);
  };

  update(report, betrieb) {
    this.report = report;
    this.betrieb = betrieb;
    const agenten = Array.isArray(report?.agenten) ? report.agenten : [];
    const proAbteilung = Object.fromEntries(ORDER.map(key => [key, []]));
    for (const lauf of agenten) {
      if (lauf && proAbteilung[lauf.abteilung]) proAbteilung[lauf.abteilung].push(lauf);
    }
    for (const key of ORDER) {
      const liste = proAbteilung[key];
      const fehler = liste.filter(lauf => lauf.ok === false).length;
      const ok = liste.length - fehler;
      const letzter = liste[0];
      panelZeichnen(
        this.stationScreens[key],
        `${key} / ${DEP[key]}`,
        [
          ['AGENTEN', liste.length ? zahl(liste.length) : 'KEINE DATEN'],
          ['OHNE BEFUND', liste.length ? zahl(ok) : '–'],
          ['BEFUNDE', liste.length ? zahl(fehler) : '–'],
          ['LETZTE AUFGABE', letzter?.aufgabe || 'KEINE DATEN'],
        ],
        fehler ? AMBER : ACCENT,
        liste.length ? `LETZTER LAUF ${kurz(letzter?.zeit)}` : 'NOCH KEIN LAUF',
      );
    }

    const takt = betrieb?.takt || {};
    const ressourcen = betrieb?.ressourcen || {};
    const jobs = Array.isArray(betrieb?.jobs) ? betrieb.jobs : [];
    const taktRoh = takt.status || '';
    const taktStatus = taktRoh ? taktRoh.toUpperCase() : 'KEINE DATEN';
    panelZeichnen(
      this.central,
      'COMMAND CENTER / E6',
      [
        ['TAKT', taktStatus],
        ['LETZTER TAKT', kurz(takt.letzter)],
        ['JOBS', jobs.length ? zahl(jobs.length) : '–'],
        ['DB / RSS', `${zahl(ressourcen.db_mb)} / ${zahl(ressourcen.rss_mb)} MB`],
        ['AGENTEN', agenten.length ? zahl(agenten.length) : 'KEINE DATEN'],
      ],
      taktRoh === 'laeuft' ? ACCENT : AMBER,
      'LIVE: /api/health · /api/betrieb · /api/report',
    );

    const risiko = report?.risiko || {};
    const auslastung = risiko.auslastung || {};
    panelZeichnen(
      this.screens.takt.panel,
      this.screens.takt.titel,
      [
        ['STATUS', taktStatus],
        ['LETZTER TAKT', kurz(takt.letzter)],
        ['JOBS IM PLAN', jobs.length ? zahl(jobs.length) : '–'],
        ['LETZTER TAKT-STATUS', takt.letzter_status || '–'],
      ],
      taktRoh === 'laeuft' ? ACCENT : AMBER,
      `DB ${zahl(ressourcen.db_mb)} MB · RSS ${zahl(ressourcen.rss_mb)} MB`,
    );
    panelZeichnen(
      this.screens.risiko.panel,
      this.screens.risiko.titel,
      [
        ['RISIKOSTATUS', risiko.status ? risiko.status.toUpperCase() : 'KEINE DATEN'],
        ['DRAWDOWN', auslastung.drawdown_pct == null ? 'KEINE DATEN' : `${zahl(auslastung.drawdown_pct)} %`],
        ['OFFENE POSITIONEN', auslastung.positionen == null ? 'KEINE DATEN' : zahl(auslastung.positionen)],
        ['MODUS', report?.modus ? report.modus.toUpperCase() : 'KEINE DATEN'],
      ],
      risiko.status === 'gestoppt' ? BAD : ACCENT,
      `REPORT ${kurz(report?.erstellt)} · NUR PAPER`,
    );
    const fehler = agenten.filter(lauf => lauf.ok === false).length;
    const neueste = agenten[0];
    panelZeichnen(
      this.screens.agenten.panel,
      this.screens.agenten.titel,
      [
        ['AGENTENLÄUFE', agenten.length ? zahl(agenten.length) : 'KEINE DATEN'],
        ['BEFUNDE', agenten.length ? zahl(fehler) : 'KEINE DATEN'],
        ['ABTEILUNGEN', zahl(Object.keys(proAbteilung).length)],
        ['LETZTE AKTIVITÄT', neueste?.aufgabe || 'KEINE DATEN'],
      ],
      fehler ? AMBER : ACCENT,
      neueste ? `ZULETZT ${kurz(neueste.zeit)}` : 'NOCH KEIN LAUF',
    );
  }

  dispose() {
    this.setActive(false);
    window.removeEventListener('keydown', this._onKeyDown);
    window.removeEventListener('keyup', this._onKeyUp);
    window.removeEventListener('blur', this._onBlur);
    window.removeEventListener('resize', this._onResize);
    document.removeEventListener('mousemove', this._onMouseMove);
    document.removeEventListener('pointerlockchange', this._onPointerLock);
    this.canvas.removeEventListener('click', this._onCanvasClick);
    if (this._resizeObserver) this._resizeObserver.disconnect();
    this.renderer.dispose();
  }
}
