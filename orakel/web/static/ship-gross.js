/* Grossmodus-Kunst (2400-px-Variante aus dem Anhang). Wird nur fuer den Grossmodus geladen. */
(function(){
  'use strict';
  const SHIP_FARBEN = ['#38e8ff','#ff3fa4','#ffb84d','#9b6cff','#55e6a5','#ff7a59','#5aa9ff','#ff5edb','#c6ff5e','#ff9f43','#74ffd0'];
  const PX_HAUT = ['#f4cfa6','#e2ad7f','#c88a58','#91603c','#5e3b25'];
  const PX_HAAR = ['#2b1b12','#5a3a1e','#d6a94e','#141414','#a0522d','#e9e2d4','#ff5fb0','#3fd0ff','#7b4bff'];
  const PX_HOSE = ['#24223a','#1d2b3c','#30263a','#262626'];
  const PX_BODEN = { command:'#2f3a52', server:'#2a2e3c', lab:'#d9d9e4', trading:'#3a2f4d', research:'#4a3a30',
    risk:'#3d2a30', archive:'#5a4330', workshop:'#3a3a3a', observatory:'#232a44', security:'#2d2a2a', meeting:'#4b2f3d',
    hangar:'#2c3040', warp:'#262a3a', lounge:'#4a3a46', lager:'#3a3630' };
  const PX_BUNT = ['#c94f4f','#4f7fc9','#d6b04a','#4fb08a','#9a5fc9','#e8e0d0'];
  const PX_ZIFFERN = { '0':['111','101','101','101','111'], '1':['010','110','010','010','111'], '2':['111','001','111','100','111'],
    '3':['111','001','011','001','111'], '4':['101','101','111','001','001'], '5':['111','100','111','001','111'],
    '6':['111','100','111','101','111'], '7':['111','001','010','010','010'], '8':['111','101','111','101','111'], '9':['111','101','111','001','111'] };
  function pxHash(s){ let h = 2166136261; for(const c of String(s)){ h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; }
  function pxRng(seed){ let s = (seed >>> 0) || 7; return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return (s % 100000) / 100000; }; }
  function pxN(a, b, c){ let h = (a * 374761393 + b * 668265263 + c * 1442695041) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return (h ^ (h >>> 16)) >>> 0; }
  function pxMix(a, b, f){
    const p = h => [1,3,5].map(i => parseInt(h.slice(i, i+2), 16));
    const x = p(a), y = p(b);
    return '#' + x.map((v,i) => Math.round(v + (y[i]-v) * f).toString(16).padStart(2,'0')).join('');
  }
  function pxPinsel(ctx){
    return {
      ctx,
      r(x, y, w, h, c){ if(w <= 0 || h <= 0) return; ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h)); },
      p(x, y, c){ ctx.fillStyle = c; ctx.fillRect(Math.round(x), Math.round(y), 1, 1); },
      a(alpha, fn){ ctx.globalAlpha = alpha; fn(); ctx.globalAlpha = 1; },
    };
  }
  function pxText(g, x, y, s, c, sc = 1){
    [...String(s)].forEach((ch, i) => {
      const m = PX_ZIFFERN[ch]; if(!m) return;
      m.forEach((row, ry) => [...row].forEach((v, rx) => { if(v === '1') g.r(x + i * 4 * sc + rx * sc, y + ry * sc, sc, sc, c); }));
    });
  }
  function pxKegel(g, alpha, farbe, x1, x2, y1, x3, x4, y2){
    g.a(alpha, () => { const c = g.ctx; c.fillStyle = farbe; c.beginPath(); c.moveTo(x1, y1); c.lineTo(x2, y1); c.lineTo(x4, y2); c.lineTo(x3, y2); c.fill(); });
  }

function pxHuelle(g, w, h, farbe, typ, rng, t = 0){
  const fy = h - 7;
  const wand = pxMix('#2e2a4a', farbe, .2), dunkel = pxMix(wand, '#000000', .38), hell = pxMix(wand, '#ffffff', .09);
  g.r(0, 0, w, h, wand);
  const schritt = 9 + Math.floor(rng() * 4);
  for(let x = 3 + Math.floor(rng() * schritt); x < w; x += schritt){ g.r(x, 6, 1, fy - 9, dunkel); g.r(x + 1, 6, 1, fy - 9, hell); }
  g.r(0, fy - 3, w, 1, hell); g.r(0, fy - 2, w, 2, dunkel);
  g.r(0, 0, w, 3, '#0a0812'); g.r(0, 3, w, 1, pxMix(farbe, '#000000', .5));
  for(let x = 2; x < w; x += 7) g.p(x, 1, '#2a2638');
  // Deckenrohr mit Muffen und Fluss-Licht
  g.r(0, 4, w, 2, '#3a3f56'); g.r(0, 4, w, 1, '#565c78');
  for(let x = 5 + Math.floor(rng() * 9); x < w; x += 15){ g.r(x, 3, 2, 4, '#262a3c'); g.p(x, 3, '#4a5068'); }
  const fx = (t * 2) % (w + 20) - 10;
  g.p(fx, 5, pxMix(farbe, '#ffffff', .55)); g.p(fx - 1, 5, farbe); g.p(fx - 2, 5, pxMix(farbe, '#3a3f56', .5));
  const boden = PX_BODEN[typ] || '#3b3448';
  g.r(0, fy, w, h - fy, boden); g.r(0, fy, w, 1, pxMix(boden, '#ffffff', .28));
  for(let x = Math.floor(rng() * 6); x < w; x += 6) g.r(x, fy + 2 + ((x / 6) & 1) * 2, 1, 2, pxMix(boden, '#000000', .28));
  g.r(0, h - 1, w, 1, '#06050a');
  return fy;
}
function pxLampe(g, x, fy, farbe){
  g.r(x - 3, 3, 7, 1, '#fff4d6'); g.r(x - 2, 4, 5, 1, pxMix('#fff4d6', farbe, .4));
  pxKegel(g, .1, '#fff4d6', x - 3, x + 4, 5, x - 12, x + 13, fy);
}
function pxFenster(g, x, y, w, h, rng){
  g.r(x - 1, y - 1, w + 2, h + 2, '#59627a'); g.r(x, y, w, h, '#0b0f2c');
  g.r(x, y + h - 2, w, 2, '#2a1550');
  const n = Math.max(4, Math.floor(w * h / 10));
  for(let i = 0; i < n; i++) g.p(x + Math.floor(rng() * w), y + Math.floor(rng() * (h - 1)), i % 4 ? '#9fb4ff' : '#ffffff');
  g.p(x + Math.floor(rng() * w), y + h - 2, '#ff5fc8');
  if(w > 14) g.r(x + Math.floor(w / 2), y, 1, h, '#59627a');
}
function pxTisch(g, x, y, w, fy, farbe){
  g.r(x, y, w, 1, '#a99cba'); g.r(x, y + 1, w, 2, '#4a4058'); g.r(x, y + 1, w, 1, pxMix(farbe, '#000000', .25));
  g.r(x + 1, y + 3, 1, fy - y - 3, '#2a2433'); g.r(x + w - 2, y + 3, 1, fy - y - 3, '#2a2433');
}
function pxStuhl(g, x, fy, c = '#3b3550'){
  g.r(x, fy - 10, 2, 7, c); g.r(x, fy - 10, 2, 1, pxMix(c, '#ffffff', .25));
  g.r(x, fy - 4, 5, 1, pxMix(c, '#ffffff', .12)); g.r(x + 2, fy - 3, 1, 2, '#2a2433');
  g.r(x, fy - 1, 5, 1, '#1b1825'); g.p(x, fy - 1, '#000000'); g.p(x + 4, fy - 1, '#000000');
}
function pxMonitor(g, x, y, w, h, farbe, t, an, art){
  g.r(x - 1, y - 1, w + 2, h + 2, '#0c0c13');
  g.r(x, y, w, h, an ? pxMix(farbe, '#000000', .62) : '#11141f');
  g.r(x + Math.floor(w / 2), y + h + 1, 1, 1, '#0c0c13');
  if(!an){ if((t >> 3) % 4 === 0) g.p(x + 1, y + 1, '#2c3348'); return; }
  const hell = pxMix(farbe, '#ffffff', .45);
  if(art === 'kerzen'){
    for(let i = 0; i < w - 1; i += 2){
      const v = pxN(i + (t >> 1), x, 3), hoch = 1 + v % (h - 1), auf = (v >> 4) & 1;
      g.r(x + 1 + i, y + h - hoch, 1, hoch, auf ? '#3dff8f' : '#ff4d6d');
    }
  }else if(art === 'kurve'){
    let yy = y + Math.floor(h / 2);
    for(let i = 0; i < w; i++){ yy += (pxN(i + t, x, 9) % 3) - 1; yy = Math.max(y, Math.min(y + h - 1, yy)); g.p(x + i, yy, '#ff5577'); }
  }else if(art === 'karte'){
    for(let i = 0; i < w * h / 6; i++){ const px = pxN(i, x, 5) % w, py = pxN(i, y, 6) % h; g.p(x + px, y + py, '#1f5a4a'); }
    for(let i = 0; i < 4; i++){ const px = pxN(i, x, 7) % w, py = pxN(i, y, 8) % h; g.p(x + px, y + py, (t + i * 3) % 8 < 4 ? '#ffd84d' : '#ff5fc8'); }
  }else{
    for(let i = 0; i < h - 1; i += 2){ const l = 1 + pxN(x, i, t >> 1) % (w - 1); g.r(x + 1, y + 1 + i, Math.min(l, w - 2), 1, i % 4 ? hell : '#ffffff'); }
  }
}
function pxPflanze(g, x, fy){
  g.r(x, fy - 3, 4, 3, '#8a5a3c'); g.r(x, fy - 3, 4, 1, '#a8704a');
  g.r(x + 1, fy - 7, 2, 4, '#2fae5c'); g.p(x, fy - 6, '#3fd070'); g.p(x + 3, fy - 8, '#3fd070'); g.p(x + 1, fy - 9, '#56e087'); g.p(x + 3, fy - 5, '#249048');
}
function pxPflanzeGross(g, x, fy){
  g.r(x, fy - 4, 5, 4, '#6a4a3a'); g.r(x, fy - 4, 5, 1, '#8a6a4a');
  g.r(x + 2, fy - 12, 1, 8, '#2a7a40');
  [[0,-11],[3,-13],[1,-14],[4,-10],[-1,-8],[4,-7],[2,-16],[0,-15],[-1,-12],[4,-15]].forEach(([dx, dy], i) => g.r(x + dx, fy + dy, 2, 1, i % 3 ? '#3fd070' : '#2fae5c'));
}
function pxBuecher(g, x, y, w, h, rng){
  g.r(x, y, w, h, '#3a2a1e');
  for(let yy = y + 1; yy < y + h - 1; yy += 5){
    g.r(x, yy + 4, w, 1, '#5a4330');
    for(let xx = x + 1; xx < x + w - 1; xx++){
      const c = PX_BUNT[Math.floor(rng() * 6)];
      const hh = 2 + Math.floor(rng() * 2); if(rng() < .15) continue;
      g.r(xx, yy + 4 - hh, 1, hh, c);
    }
  }
}
function pxPoster(g, x, y, farbe, art){
  g.r(x - 1, y - 1, 8, 10, '#1a1626'); g.r(x, y, 6, 8, '#0e1030');
  if(art === 0){ g.r(x + 2, y + 2, 3, 3, farbe); g.p(x + 2, y + 2, pxMix(farbe, '#ffffff', .5)); g.r(x + 1, y + 4, 5, 1, pxMix(farbe, '#ffffff', .3)); g.p(x + 1, y + 1, '#ffffff'); g.p(x + 5, y + 6, '#9fb4ff'); }
  else if(art === 1){ for(let i = 0; i < 5; i++){ const hh = 1 + ((i * 7 + 3) % 5); g.r(x + 1 + i, y + 7 - hh, 1, hh, i % 2 ? farbe : '#3dff8f'); } }
  else { g.r(x + 2, y + 2, 2, 4, '#e8e0f0'); g.r(x + 2, y + 1, 2, 1, '#ff5577'); g.p(x + 1, y + 5, farbe); g.p(x + 4, y + 5, farbe); g.p(x + 2, y + 6, '#ffb84d'); g.p(x + 3, y + 7, '#ff7a59'); }
}
function pxUhr(g, x, y, t){
  g.r(x + 1, y, 3, 1, '#c8c0d8'); g.r(x, y + 1, 5, 3, '#c8c0d8'); g.r(x + 1, y + 4, 3, 1, '#c8c0d8');
  g.r(x + 1, y + 1, 3, 3, '#f4f0fa'); g.p(x + 2, y + 2, '#140c1c');
  const d = [[0,-1],[1,0],[0,1],[-1,0]][(t >> 3) % 4]; g.p(x + 2 + d[0], y + 2 + d[1], '#ff3355');
}
function pxLueftung(g, x, y, w){
  g.r(x, y, w, 4, '#1c1e2c'); g.r(x, y, w, 1, '#4a4f68');
  for(let i = 1; i < 4; i++) g.r(x + 1, y + i, w - 2, 1, i % 2 ? '#2e3246' : '#141622');
}
function pxWandRegal(g, x, y, w, rng, farbe){
  g.r(x, y, w, 1, '#8a6a4a'); g.r(x, y + 1, w, 1, '#4a3424'); g.p(x + 1, y + 2, '#3a2a1e'); g.p(x + w - 2, y + 2, '#3a2a1e');
  let xx = x + 1, i = 0;
  while(xx < x + w - 3){
    const k = Math.floor(rng() * 6); i++;
    if(k === 0){ const n = 2 + (i % 3); for(let j = 0; j < n && xx < x + w - 1; j++, xx++) g.r(xx, y - 3 - (j % 2), 1, 3 + (j % 2), PX_BUNT[(j + i) % 5]); xx++; }
    else if(k === 1){ g.r(xx, y - 2, 2, 2, '#8a5a3c'); g.p(xx, y - 3, '#3fd070'); g.p(xx + 1, y - 4, '#56e087'); xx += 3; }
    else if(k === 2){ g.r(xx, y - 2, 2, 2, '#e8e0f0'); g.p(xx + 2, y - 2, '#e8e0f0'); xx += 4; }
    else if(k === 3){ g.r(xx, y - 3, 3, 3, pxMix(farbe, '#000000', .3)); g.r(xx, y - 3, 3, 1, farbe); xx += 4; }
    else if(k === 4){ g.r(xx, y - 3, 3, 2, '#ffd84d'); g.p(xx + 1, y - 1, '#b8902a'); xx += 4; }
    else xx += 2;
  }
}
function pxKaffee(g, x, fy, t){
  g.r(x, fy - 7, 7, 7, '#3a3346'); g.r(x, fy - 7, 7, 1, '#6a6080'); g.p(x + 3, fy - 4, '#8a80a0'); g.r(x + 1, fy - 2, 5, 1, '#2a2436');
  g.r(x + 1, fy - 14, 5, 7, '#222030'); g.r(x + 1, fy - 14, 5, 1, '#4a4660'); g.p(x + 4, fy - 13, (t >> 2) % 2 ? '#ff3355' : '#7a1a2a');
  g.r(x + 2, fy - 11, 2, 1, '#111111'); g.r(x + 2, fy - 9, 2, 2, '#e8e0f0');
  if(t % 6 < 3) g.p(x + 3, fy - 15 - (t % 3), '#c8c0d8');
}
function pxMuell(g, x, fy){ g.r(x, fy - 4, 3, 4, '#4a4f68'); g.r(x, fy - 4, 3, 1, '#6a7090'); g.p(x + 1, fy - 5, '#e8e0f0'); }
function pxTower(g, x, fy, t, farbe){ g.r(x, fy - 6, 3, 6, '#1a1826'); g.r(x, fy - 6, 3, 1, '#3a3650'); g.p(x + 1, fy - 4, (t >> 1) % 3 ? farbe : '#203040'); g.p(x + 1, fy - 2, '#2bff88'); }
function pxLoescher(g, x, fy){ g.r(x - 1, fy - 9, 4, 1, '#5a5f78'); g.r(x, fy - 8, 2, 6, '#d42a3a'); g.r(x, fy - 8, 2, 1, '#ff6070'); g.p(x + 2, fy - 8, '#222222'); g.p(x + 2, fy - 7, '#222222'); }
function pxKiste(g, x, yb, w, h, c){
  const d = pxMix(c, '#000000', .35), l = pxMix(c, '#ffffff', .2);
  g.r(x, yb - h, w, h, c); g.r(x, yb - h, w, 1, l); g.r(x, yb - h, 1, h, d); g.r(x + w - 1, yb - h, 1, h, d); g.r(x, yb - 1, w, 1, d);
  for(let i = 1; i < h - 1; i++) g.p(x + Math.round(i * (w - 1) / (h - 1)), yb - h + i, d);
}
function pxFass(g, x, yb, c){ g.r(x, yb - 7, 5, 7, c); g.r(x, yb - 7, 5, 1, pxMix(c, '#ffffff', .3)); g.r(x, yb - 5, 5, 1, pxMix(c, '#000000', .3)); g.r(x, yb - 2, 5, 1, pxMix(c, '#000000', .3)); g.p(x + 2, yb - 4, '#ffd84d'); }
function pxSchrank(g, x, fy, w, h, c){
  const d = pxMix(c, '#000000', .35);
  g.r(x, fy - h, w, h, c); g.r(x, fy - h, w, 1, pxMix(c, '#ffffff', .25));
  for(let xx = x; xx < x + w; xx += 4){ g.r(xx, fy - h, 1, h, d); g.r(xx + 1, fy - h + 2, 2, 1, d); g.r(xx + 1, fy - h + 4, 2, 1, d); g.p(xx + 2, fy - Math.floor(h / 2), '#c0c4cc'); }
}
function pxAkten(g, x, fy, h, c){
  g.r(x, fy - h, 6, h, c); g.r(x, fy - h, 6, 1, pxMix(c, '#ffffff', .25));
  for(let y = fy - h + 2; y < fy - 1; y += 4){ g.r(x, y + 2, 6, 1, pxMix(c, '#000000', .35)); g.r(x + 2, y, 2, 1, '#c0c4cc'); }
}
function pxWhiteboard(g, x, y, w, h, rng, farbe){
  g.r(x - 1, y - 1, w + 2, h + 2, '#8a90a8'); g.r(x, y, w, h, '#eef0f6');
  for(let yy = y + 1; yy < y + h - 1; yy += 2){ const l = 2 + Math.floor(rng() * (w - 3)); g.r(x + 1 + Math.floor(rng() * 2), yy, Math.min(l, w - 3), 1, ['#3a6ad0','#d03a4a','#2a2a3a',farbe][Math.floor(rng() * 4)]); }
  g.r(x + 1, y + h + 1, w - 2, 1, '#5a5f78'); g.p(x + 2, y + h, '#d03a4a'); g.p(x + 4, y + h, '#3a6ad0');
}
function pxPinnwand(g, x, y, w, h, rng){
  g.r(x - 1, y - 1, w + 2, h + 2, '#6a4a2e'); g.r(x, y, w, h, '#b8875a');
  for(let i = 0; i < Math.floor(w * h / 9); i++){ const nx = x + Math.floor(rng() * (w - 2)), ny = y + Math.floor(rng() * (h - 2)); g.r(nx, ny, 2, 2, ['#ffd84d','#ff8fc8','#8fe8ff','#f4f0fa','#9fff9f'][i % 5]); g.p(nx, ny, '#d42a3a'); }
}
function pxSofa(g, x, fy, w, c){
  const d = pxMix(c, '#000000', .35), l = pxMix(c, '#ffffff', .2);
  g.r(x, fy - 8, w, 4, d); g.r(x, fy - 8, w, 1, l); g.r(x, fy - 4, w, 3, c); g.r(x, fy - 4, w, 1, l);
  for(let xx = x + Math.floor(w / 3); xx < x + w - 2; xx += Math.floor(w / 3)) g.r(xx, fy - 7, 1, 3, pxMix(c, '#000000', .5));
  g.r(x - 2, fy - 6, 2, 5, d); g.r(x + w, fy - 6, 2, 5, d); g.p(x - 1, fy - 1, '#111111'); g.p(x + w, fy - 1, '#111111');
}
function pxWasser(g, x, fy, t){
  g.r(x, fy - 8, 4, 8, '#d8dce8'); g.r(x, fy - 8, 4, 1, '#ffffff'); g.p(x + 1, fy - 5, '#3a6ad0'); g.p(x + 2, fy - 5, '#d03a4a');
  g.r(x, fy - 14, 4, 6, '#7fc8ff'); g.r(x + 1, fy - 15, 2, 1, '#5aa0e0'); g.a(.6, () => g.r(x + 1, fy - 13, 1, 4, '#e8f8ff'));
  if(t % 14 < 4) g.p(x + 2, fy - 9 - (t % 14), '#ffffff');
}
function pxAutomat(g, x, fy, t, farbe){
  g.r(x, fy - 18, 9, 18, '#2a2440'); g.r(x, fy - 18, 9, 1, '#5a5080');
  g.r(x + 1, fy - 16, 5, 12, '#0b0f2c');
  for(let r = 0; r < 4; r++) for(let c = 0; c < 2; c++) g.r(x + 2 + c * 2, fy - 15 + r * 3, 1, 2, ['#ff5577','#ffd84d','#3dff8f','#38e8ff'][(r + c) % 4]);
  g.r(x + 7, fy - 15, 1, 3, farbe); g.p(x + 7, fy - 11, (t >> 2) % 2 ? '#3dff8f' : '#1a4a2a'); g.r(x + 1, fy - 3, 5, 2, '#111111');
}
function pxWarnschild(g, x, y, c = '#ffcc33'){
  g.p(x + 2, y, c); g.r(x + 1, y + 1, 3, 1, c); g.r(x + 1, y + 2, 3, 1, c); g.r(x, y + 3, 5, 1, c);
  g.p(x + 2, y + 1, '#1a1a1a'); g.p(x + 2, y + 3, '#1a1a1a');
}
function pxBake(g, x, y, t, c = '#ff3355'){
  g.r(x, y + 2, 4, 1, '#3a3f56'); g.r(x + 1, y, 2, 2, (t >> 1) % 2 ? c : pxMix(c, '#000000', .5));
  if((t >> 1) % 2) g.a(.18, () => g.r(x - 3, y - 1, 10, 4, c));
}
function pxAnzeige(g, x, y, t, c){
  g.r(x, y, 7, 7, '#c0c4cc'); g.r(x + 1, y + 1, 5, 5, '#f4f0fa'); g.r(x + 1, y + 4, 5, 1, '#e8a0a8');
  const a = Math.PI * (1 + ((Math.sin(t / 7) + 1) / 2));
  g.p(x + 3, y + 4, '#140c1c'); g.p(x + 3 + Math.round(Math.cos(a) * 2), y + 4 + Math.round(Math.sin(a) * 2), c);
}
function pxTank(g, x, y, w, h, c, t){
  g.r(x, y, w, h, '#3a3f56'); g.r(x, y, w, 2, '#565c78'); g.r(x, y + h - 2, w, 2, '#262a3c');
  g.r(x + 1, y + 3, 2, h - 6, '#0a1020'); const lv = Math.floor((h - 6) * (.5 + Math.sin(t / 9 + x) * .2));
  g.r(x + 1, y + h - 3 - lv, 2, lv, c);
  g.r(x + w - 2, y + 2, 1, h - 4, '#6a7090');
}
function pxNetz(g, x, y, r, c){
  for(let i = -r; i <= r; i++){ g.p(x + i, y, c); g.p(x, y + i, c); g.p(x + i, y + i, c); g.p(x + i, y - i, c); }
  for(let a = 0; a < 16; a++){ const rr = r * .65; g.p(x + Math.round(Math.cos(a / 16 * Math.PI * 2) * rr), y + Math.round(Math.sin(a / 16 * Math.PI * 2) * rr), c); }
}

/* ---- Figur ---- */
function pxFigur(g, x, fy, look, pose, t, rechts){
  const { haut, haar, hemd, hose } = look;
  const auge = '#140c1c';
  if(pose === 'sitzt'){
    const y = fy - 12, tipp = (t & 1) ? 1 : 0;
    g.r(x + 1, y, 3, 1, haar); g.r(x + 1, y + 1, 3, 2, haut); g.p(x + 1, y + 1, haar); g.p(x + 3, y + 1, auge);
    g.r(x, y + 3, 4, 4, hemd); g.p(x, y + 3, pxMix(hemd, '#000000', .3));
    g.r(x + 4, y + 4 + tipp, 2, 1, hemd); g.p(x + 6, y + 4 + tipp, haut);
    g.r(x + 1, y + 7, 5, 1, hose); g.r(x + 5, y + 8, 1, 3, hose); g.r(x + 5, y + 11, 2, 1, '#0d0b12');
    return;
  }
  const y = fy - 11, schritt = pose === 'geht' ? (t & 1) : 0;
  const bob = pose === 'wartet' && (t % 10 < 5) ? 1 : 0;
  g.r(x + 1, y + bob, 3, 1, haar); g.r(x + 1, y + 1 + bob, 3, 2, haut);
  g.p(rechts ? x + 1 : x + 3, y + 1 + bob, haar); g.p(rechts ? x + 3 : x + 1, y + 1 + bob, auge);
  g.r(x, y + 3, 5, 4, hemd); g.p(x, y + 6, haut); g.p(x + 4, y + 6, haut);
  g.r(x + 1, y + 7, 3, 1, hose);
  if(schritt){ g.r(x, y + 8, 1, 2, hose); g.r(x + 4, y + 8, 1, 2, hose); g.p(x, y + 10, '#0d0b12'); g.p(x + 4, y + 10, '#0d0b12'); }
  else{ g.r(x + 1, y + 8, 1, 2, hose); g.r(x + 3, y + 8, 1, 2, hose); g.p(x + 1, y + 10, '#0d0b12'); g.p(x + 3, y + 10, '#0d0b12'); }
}
function pxBlase(g, x, y, art, t){
  if(art === 'alarm'){
    if(t % 4 >= 2) return;
    g.r(x, y, 5, 6, '#ff3355'); g.r(x + 1, y - 1, 3, 1, '#ff3355'); g.r(x + 1, y + 6, 3, 1, '#ff3355');
    g.r(x + 2, y + 1, 1, 3, '#ffffff'); g.p(x + 2, y + 5, '#ffffff');
  }else{
    g.r(x - 1, y + 1, 7, 4, '#f3ecff'); g.p(x + 1, y + 5, '#f3ecff');
    for(let i = 0; i < 3; i++) g.p(x + i * 2, y + 3, i <= (t >> 1) % 3 ? '#e8a53a' : '#c9bfd8');
  }
}
function pxLookNr(i){ return { haut:PX_HAUT[i % 5], haar:PX_HAAR[(i * 3) % PX_HAAR.length], hemd:SHIP_FARBEN[i % SHIP_FARBEN.length], hose:PX_HOSE[i % 4] }; }
/* Person hinter einem Tisch (Oberkörper sichtbar, Gesicht zum Betrachter) */
function pxSitztVorne(g, x, ty, look, redet){
  const y = ty - 9 - (redet ? 1 : 0);
  g.r(x + 1, y, 3, 1, look.haar); g.r(x + 1, y + 1, 3, 2, look.haut); g.p(x + 1, y + 1, look.haar);
  g.p(x + 1, y + 2, '#140c1c'); g.p(x + 3, y + 2, '#140c1c');
  g.r(x, y + 3, 5, ty - y - 3, look.hemd); g.p(x + 2, y + 3, pxMix(look.hemd, '#ffffff', .4));
  g.p(x, ty - 1, look.haut); g.p(x + 4, ty - 1, look.haut);
}

/* ---- Arbeitsplatz: Monitore, Tisch, Kleinkram, Stuhl. Gibt Sitzposition zurück ---- */
function pxPlatz(g, dx, tw, fy, farbe, t, an, art, monitore, rng){
  const ty = fy - 6;
  const mw = Math.max(4, Math.min(9, Math.floor((tw - 5) / monitore) - 2));
  if(rng() < .8) pxWandRegal(g, dx + 1, ty - 14, Math.min(tw - 2, 18), rng, farbe);
  for(let i = 0; i < monitore; i++) pxMonitor(g, dx + 2 + i * (mw + 2), ty - 7, mw, 5, farbe, t + i * 3, an, art);
  if(rng() < .5) g.p(dx + 1 + mw, ty - 8, '#ffd84d');
  pxTisch(g, dx, ty, tw, fy, farbe);
  g.r(dx + 2, ty - 1, 5, 1, '#2a2638'); if(an && t % 2) g.p(dx + 3 + (t % 3), ty - 1, '#5a5670');
  g.p(dx + 8, ty - 1, '#2a2638');
  const ende = dx + tw - 3, deko = rng();
  if(deko < .45){ g.r(ende, ty - 2, 2, 2, '#e8e0f0'); g.p(ende + 2, ty - 2, '#e8e0f0'); if(t % 10 < 3) g.p(ende + 1, ty - 4 - (t % 2), '#c8c0d8'); }
  else if(deko < .75){ g.r(ende + 1, ty - 6, 1, 6, '#5a5f78'); g.r(ende - 1, ty - 7, 3, 1, '#ffd84d'); g.a(.15, () => g.r(ende - 3, ty - 6, 6, 6, '#ffd84d')); }
  else { g.r(ende - 1, ty - 1, 4, 1, '#f4f0fa'); g.r(ende, ty - 2, 3, 1, '#e0dcea'); }
  pxTower(g, dx + tw - 6, fy, t, farbe);
  if(rng() < .6) pxMuell(g, dx + 3, fy);
  pxStuhl(g, dx - 6, fy);
  return dx - 5;
}

/* ---- Raumtypen je Abteilung: Deko links, Arbeitsplatz rechts ---- */
const PX_TYP = {
  command(g, w, fy, f, hell, rng, t, an){        // A Hauptzentrale
    const bw = Math.max(12, Math.floor(w * .36));
    g.r(2, 8, bw, 16, '#04161c'); g.r(2, 8, bw, 1, hell); g.r(2, 23, bw, 1, '#0e3a44');
    for(let x = 5; x < bw; x += 4) g.r(x, 9, 1, 14, '#082a32');
    for(let y = 12; y < 23; y += 4) g.r(3, y, bw - 2, 1, '#082a32');
    for(let i = 0; i < 8; i++){ const x = 3 + pxN(i, w, 1) % (bw - 2), y = 10 + pxN(i, 2, w) % 12; g.p(x, y, (t + i) % 6 < 3 ? '#38e8ff' : '#0e5a66'); }
    g.a(.3, () => g.r(3 + (t % (bw - 2)), 9, 1, 14, '#38e8ff'));
    for(let x = 2; x < bw + 2; x += 3) g.p(x, 26, (x + t) % 9 < 2 ? '#ff3fa4' : '#3a2040');
    const hx = 2 + Math.floor(bw / 2) - 3;
    g.r(hx, fy - 5, 7, 5, '#2a3550'); g.r(hx, fy - 5, 7, 1, '#4a5a80'); g.r(hx + 1, fy - 6, 5, 1, '#38e8ff');
    pxKegel(g, .22, '#38e8ff', hx + 1, hx + 6, fy - 6, hx - 1, hx + 8, fy - 14);
    g.r(hx + 2, fy - 13, 3, 3, '#7fe8ff'); const a = t / 3; g.p(hx + 3 + Math.round(Math.cos(a) * 3), fy - 12 + Math.round(Math.sin(a)), '#ffffff');
    if(bw > 16) pxPflanze(g, 1, fy);
    const dx = bw + 11;
    pxUhr(g, dx + 2, 9, t);
    if(w - dx > 24) pxPoster(g, dx + 10, 9, f, 0);
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', w - dx > 30 ? 3 : 2, rng);
  },
  server(g, w, fy, f, hell, rng, t, an){         // B Spider Intelligence
    const n = Math.max(2, Math.min(4, Math.floor((w - 32) / 7)));
    for(let i = 0; i < n; i++){
      const x = 2 + i * 7;
      g.r(x, 9, 6, fy - 9, '#14151e'); g.r(x, 9, 6, 1, '#3c3f56'); g.r(x + 5, 9, 1, fy - 9, '#25273a');
      for(let y = 11; y < fy - 1; y += 2){ g.r(x + 1, y, 4, 1, '#232535'); const z = pxN(i, y, t >> 1) % 3; g.p(x + 1 + pxN(y, i, 7) % 3, y, z === 0 ? '#2bff88' : z === 1 ? hell : '#10301f'); }
      g.r(x + 2, 6, 1, 3, ['#ff3fa4','#38e8ff','#ffd84d','#3dff8f'][i % 4]);
    }
    for(let x = 2; x < 2 + n * 7; x++) g.p(x, 7 + (Math.sin(x / 2.2) > 0 ? 1 : 0), '#ff5fc8');
    const lx = 3 + n * 7;
    g.r(lx, 9, 7, 7, '#1c1e2c'); g.r(lx, 9, 7, 1, '#4a4f68');
    const s = (t >> 1) % 2; g.p(lx + 3, 12, '#8a90a8');
    if(s){ g.p(lx + 1, 12, '#5a6080'); g.p(lx + 5, 12, '#5a6080'); g.p(lx + 3, 10, '#5a6080'); g.p(lx + 3, 14, '#5a6080'); }
    else { g.p(lx + 1, 10, '#5a6080'); g.p(lx + 5, 14, '#5a6080'); g.p(lx + 5, 10, '#5a6080'); g.p(lx + 1, 14, '#5a6080'); }
    g.r(lx, 18, 7, 4, '#05040a'); g.r(lx + 1, 19, 1 + (t >> 2) % 5, 2, (t >> 2) % 5 > 3 ? '#ffb84d' : '#3dff8f');
    pxNetz(g, lx + 3, 28, 3, pxMix(f, '#ffffff', .3));
    for(let x = 2; x < lx + 6; x++) if(x % 6 < 4) g.p(x, fy - 1, ['#1a1a28','#ff3fa4','#38e8ff'][x % 3]);
    const dx = lx + 15;
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', w - dx > 26 ? 2 : 1, rng);
  },
  lab(g, w, fy, f, hell, rng, t, an){            // C Labor
    g.r(2, 7, 8, fy - 7, '#545a6e'); g.r(3, 9, 6, fy - 13, '#8fb8c8'); g.r(4, 10, 4, fy - 15, pxMix(f, '#0a1a20', .35));
    g.r(5, 18, 2, 6, pxMix(f, '#000000', .55)); g.p(4, 20, pxMix(f, '#000000', .55)); g.p(7, 21, pxMix(f, '#000000', .55));
    for(let i = 0; i < 4; i++){ const by = fy - 6 - ((t * 2 + i * 7) % (fy - 16)); g.p(4 + (i % 3) * 1.5, by, '#e8ffff'); }
    g.r(2, fy - 4, 8, 4, '#3a4050'); g.p(4, fy - 2, (t >> 1) % 2 ? '#3dff8f' : '#1a5a3a');
    const zone = Math.max(10, Math.floor(w * .5) - 14);
    g.r(12, 12, zone, 1, '#7a7f94');
    const farben = ['#3dff8f', '#ff5fc8', '#ffd84d', '#4dc8ff'];
    for(let i = 0; i < Math.floor(zone / 3); i++){ const x = 13 + i * 3; g.r(x, 9, 2, 3, farben[i % 4]); g.p(x, 8, '#c8d8e8'); }
    pxWarnschild(g, 12, 15, '#ffcc33');
    if(zone > 12) pxWhiteboard(g, 19, 16, Math.min(12, zone - 7), 6, rng, f);
    g.r(12, fy - 7, zone, 1, '#c0c8d8'); g.r(12, fy - 6, zone, 6, '#8a90a8'); g.r(12, fy - 6, zone, 1, '#5a6070');
    g.r(13, fy - 10, 4, 3, '#d8dce8'); g.p(14, fy - 9, (t % 4 < 2) ? '#38e8ff' : '#1a5a6a');
    g.r(19, fy - 10, 2, 3, '#3dff8f'); g.p(19, fy - 11, '#c8d8e8'); if(t % 3 === 0) g.p(20, fy - 12 - (t % 2), '#e8ffff');
    if(zone > 12) { g.r(23, fy - 9, 3, 2, '#ff5fc8'); g.r(24, fy - 11, 1, 2, '#c8d8e8'); }
    const dx = 12 + zone + 9;
    const s = pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kurve', 1, rng);
    const mx = dx + w - dx - 9;
    g.r(mx, fy - 13, 1, 6, '#2a2a3a'); g.r(mx - 1, fy - 14, 3, 1, '#2a2a3a'); g.r(mx - 1, fy - 8, 4, 1, '#3a3a4a'); g.p(mx, fy - 15, '#4dc8ff');
    return s;
  },
  trading(g, w, fy, f, hell, rng, t, an){        // D Trading Floor
    g.r(0, 7, w, 3, '#0b0710');
    for(let x = 0; x < w; x += 2){ const v = pxN(x + t, 5, 1); g.p(x, 8, v % 3 ? '#3dff8f' : '#ff4d6d'); }
    const bw = Math.max(10, Math.floor(w * .32));
    g.r(2, 13, bw, 10, '#0d0b18'); g.r(2, 13, bw, 1, hell);
    pxMonitor(g, 3, 15, bw - 2, 7, '#3dff8f', t + 5, true, 'kerzen');
    for(let i = 0; i < 3 && 3 + i * 6 < bw; i++){ g.r(3 + i * 6, 25, 5, 4, '#1a1626'); g.p(5 + i * 6, 26, '#ffd84d'); g.p(5 + i * 6 + (((t >> 3) + i) % 2), 27, '#ffd84d'); }
    g.r(3, fy - 4, 4, 4, '#3a2f4d'); g.r(3, fy - 7, 3, 2, '#ffd84d'); g.p(2, fy - 8, '#ffd84d'); g.p(6, fy - 8, '#ffd84d'); g.p(3, fy - 5, '#ffd84d'); g.p(5, fy - 5, '#ffd84d');
    if(bw > 13) { g.r(9, fy - 2, 4, 2, '#f4f0fa'); g.r(9, fy - 3, 3, 1, '#e0dcea'); }
    const dx = bw + 10;
    const s = pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kerzen', w - dx > 26 ? 3 : 2, rng);
    g.r(dx + 1, fy - 7, 3, 1, '#2a2638'); g.p(dx + 1, fy - 8, '#2a2638');
    return s;
  },
  research(g, w, fy, f, hell, rng, t, an){       // E Forschung
    pxBuecher(g, 2, 8, 10, fy - 8, rng);
    const zx = 14, zw = Math.max(6, Math.floor(w * .48) - 16);
    pxPinnwand(g, zx, 10, Math.min(12, zw), 7, rng);
    if(zw > 6){ g.r(zx + 1, fy - 1, 1, 1, '#5a4330'); g.r(zx + 1, fy - 9, 1, 8, '#7a5a3a'); g.r(zx - 1, fy - 13, 5, 4, '#3a6ad0'); g.p(zx, fy - 12, '#4fb08a'); g.p(zx + 2, fy - 11, '#4fb08a'); g.r(zx - 1, fy - 1, 5, 1, '#5a4330'); }
    g.r(zx + 5, fy - 3, 4, 3, '#f4f0fa'); g.r(zx + 5, fy - 3, 4, 1, '#e0dcea'); g.r(zx + 6, fy - 5, 3, 2, '#e8e0d0');
    const dx = Math.max(24, Math.floor(w * .48)) + 2;
    const s = pxPlatz(g, dx, Math.min(22, w - dx - 8), fy, f, t, an, 'code', 1, rng);
    pxPflanze(g, w - 6, fy);
    return s;
  },
  risk(g, w, fy, f, hell, rng, t, an){           // F Risikomanagement
    const bw = Math.max(10, Math.floor(w * .34));
    g.r(2, 8, bw, 11, '#1a0a10'); g.r(2, 8, bw, 1, '#ff5577');
    pxMonitor(g, 3, 10, bw - 2, 8, '#ff5577', t, true, 'kurve');
    pxAnzeige(g, 3, 22, t, '#ff3355'); if(bw > 13) pxAnzeige(g, 11, 22, t + 20, '#ffb84d');
    g.r(2, fy - 11, 10, 11, '#4a4f60'); g.r(3, fy - 10, 8, 9, '#3a3f50');
    for(let i = 0; i < 12; i++){ const a = i / 12 * Math.PI * 2; g.p(7 + Math.round(Math.cos(a) * 3), fy - 6 + Math.round(Math.sin(a) * 3), '#6a7090'); }
    const ra = t / 5; g.p(7 + Math.round(Math.cos(ra) * 2), fy - 6 + Math.round(Math.sin(ra) * 2), '#c0c4cc'); g.p(7, fy - 6, '#c0c4cc');
    for(let x = 0; x < w; x += 4){ g.r(x, fy, 2, 1, '#ffcc33'); g.r(x + 2, fy, 2, 1, '#1a1a1a'); }
    const dx = bw + 10;
    pxBake(g, dx + 4, 8, t);
    const s = pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'kurve', 2, rng);
    g.r(dx + w - dx - 8, fy - 8, 3, 2, '#d42a3a'); g.p(dx + w - dx - 9, fy - 8, '#d42a3a');
    return s;
  },
  archive(g, w, fy, f, hell, rng, t, an){        // G Wissenszentrum
    const bw = Math.floor(w * .44);
    pxBuecher(g, 2, 7, bw, fy - 7, rng);
    for(let y = 8; y < fy - 1; y += 3){ g.p(bw - 2, y, '#8a6a4a'); }
    g.r(bw - 3, 8, 1, fy - 8, '#8a6a4a'); g.r(bw - 1, 8, 1, fy - 8, '#8a6a4a');
    pxAkten(g, bw + 3, fy, 14, '#5a6070');
    pxKiste(g, bw + 3, fy - 14, 6, 4, '#b8875a');
    const dx = bw + 17;
    if(dx + 14 > w){ return pxPlatz(g, bw + 12, w - bw - 14, fy, f, t, an, 'code', 1, rng); }
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 1, rng);
  },
  workshop(g, w, fy, f, hell, rng, t, an){       // H Entwicklung
    const bw = Math.max(14, Math.floor(w * .42));
    g.r(2, 8, bw, 12, '#3a3f4a');
    for(let x = 3; x < bw; x += 2) for(let y = 9; y < 20; y += 2) g.p(x, y, '#2a2e36');
    g.r(4, 10, 1, 6, '#c0c4cc'); g.r(3, 10, 3, 1, '#c0c4cc');
    g.r(8, 11, 4, 1, '#ff9f43'); g.r(10, 10, 1, 5, '#8a8f99');
    if(bw > 16){ g.r(14, 10, 1, 7, '#d42a3a'); g.r(13, 10, 3, 2, '#8a8f99'); g.r(17, 12, 3, 3, '#ffd84d'); g.p(18, 13, '#3a3f4a'); }
    g.r(2, fy - 6, bw, 2, '#6a4a2e'); g.r(3, fy - 4, 1, 4, '#3a2a1e'); g.r(bw, fy - 4, 1, 4, '#3a2a1e');
    const ax = 5, sw = an ? (t % 8 < 4 ? 1 : -1) : 0;
    g.r(ax, fy - 8, 3, 2, '#5a5f78'); g.r(ax + 1, fy - 12, 2, 4, '#ffb84d'); g.r(ax + 1 + sw, fy - 15, 2, 3, '#ffb84d'); g.r(ax + sw * 2, fy - 16, 4, 1, '#d0d4dc');
    if(an && t % 3 === 0){ g.p(ax + 2 + sw * 2, fy - 7, '#ffffff'); g.p(ax + 3 + sw * 2, fy - 8, '#ffd84d'); }
    const dr = Math.floor(bw / 2) + 3;
    g.r(dr, fy - 8, 6, 2, '#2a2e3a'); g.p(dr - 1, fy - 9, '#c0c4cc'); g.p(dr + 6, fy - 9, '#c0c4cc'); g.p(dr + 2, fy - 8, (t >> 1) % 2 ? '#38e8ff' : '#1a4a5a');
    g.r(bw - 4, fy - 9, 4, 3, '#8a8f99');
    pxFass(g, bw + 1, fy, '#d46a2a');
    const dx = bw + 13;
    pxWarnschild(g, dx + 2, 9);
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 2, rng);
  },
  observatory(g, w, fy, f, hell, rng, t, an){    // I Globale Intelligence
    const cx = 10, cy = 15, r = 7;
    for(let y = -r - 1; y <= r + 1; y++) for(let x = -r - 1; x <= r + 1; x++){
      const d = x * x + y * y;
      if(d <= r * r) g.p(cx + x, cy + y, '#0a0c2a');
      else if(d <= (r + 1) * (r + 1) + 2) g.p(cx + x, cy + y, '#6a7390');
    }
    for(let y = -3; y <= 3; y++) for(let x = -3; x <= 3; x++) if(x * x + y * y <= 9) g.p(cx + 1 + x, cy + 1 + y, (x + y + (t >> 3)) % 3 ? '#2a5ac8' : '#3fae6a');
    g.p(cx - 1, cy - 1, '#c8e0ff'); g.p(cx - 5, cy - 4, '#ffffff'); g.p(cx + 4, cy - 5, '#9fb4ff');
    const sa = t / 6; g.p(cx + 1 + Math.round(Math.cos(sa) * 5), cy + 1 + Math.round(Math.sin(sa) * 2), '#ffd84d');
    g.r(21, fy - 12, 7, 2, '#c0c4cc'); g.p(20, fy - 13, '#38e8ff'); g.r(24, fy - 10, 1, 7, '#555b6e'); g.p(22, fy - 3, '#555b6e'); g.p(26, fy - 3, '#555b6e'); g.r(22, fy - 2, 5, 1, '#555b6e');
    const mw = Math.max(8, Math.floor(w * .5) - 22);
    if(mw > 8) pxWandschirm(g, 21, 9, Math.min(14, mw), 7, f, t, 'karte');
    g.r(3, fy - 5, 5, 5, '#3a4050'); g.r(4, fy - 9, 1, 4, '#8a90a8'); g.r(2, fy - 10, 5, 1, '#c0c4cc'); g.p(4, fy - 11, (t >> 2) % 2 ? '#ff3355' : '#5a1a2a');
    const dx = Math.max(34, Math.floor(w * .55));
    return pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'karte', 1, rng);
  },
  security(g, w, fy, f, hell, rng, t, an){       // J Sicherheit
    const sp = w > 52 ? 3 : 2;
    for(let i = 0; i < sp; i++) for(let j = 0; j < 2; j++){
      const x = 2 + i * 7, y = 8 + j * 6;
      g.r(x, y, 6, 5, '#0b0b10'); g.r(x + 1, y + 1, 4, 3, (pxN(i, j, t >> 2) % 7) ? '#2a3a3a' : '#5a7a7a');
      g.p(x + 1 + pxN(i, j, t) % 4, y + 2, '#9fffe0'); if(pxN(i, j, 3) % 3 === 0) g.p(x + 4, y + 1, (t >> 1) % 2 ? '#ff3355' : '#3a1a1a');
    }
    pxSchrank(g, 2, fy, 12, 13, '#3a4050');
    const ex = 2 + sp * 7 + 1;
    g.r(ex, 9, 5, 5, f); g.r(ex + 1, 14, 3, 1, f); g.p(ex + 2, 15, f); g.r(ex + 1, 10, 3, 3, pxMix(f, '#000000', .45)); g.p(ex + 2, 11, '#ffffff');
    g.r(16, fy - 14, 1, 14, '#5a5f78'); g.r(16, fy - 14, 7, 1, '#5a5f78'); g.r(22, fy - 14, 1, 14, '#5a5f78');
    g.a(.25, () => g.r(17, fy - 13 + (t % 12), 5, 1, '#3dff8f'));
    const dx = Math.max(ex + 13, 31);
    pxBake(g, dx + 6, 8, t, '#ffb84d');
    const s = pxPlatz(g, dx, w - dx - 2, fy, f, t, an, 'code', 2, rng);
    g.r(dx - 2, fy - 18, 2, 3, '#1a1a24'); g.p(dx - 2, fy - 17, (t >> 2) % 2 ? '#3dff8f' : '#ff3355');
    return s;
  },
  meeting(g, w, fy, f, hell, rng, t, an){        // S Executive-Sekretariat
    g.r(3, 8, 13, 9, '#d6a94e'); g.r(4, 9, 11, 7, '#2a1a40'); g.r(5, 12, 4, 4, '#ff5fc8'); g.r(9, 10, 5, 6, '#38e8ff'); g.p(12, 10, '#ffffff');
    pxPflanzeGross(g, 2, fy);
    pxAkten(g, 9, fy, 12, '#4a3a50');
    g.r(9, fy - 15, 6, 3, '#d8dce8'); g.r(10, fy - 16, 4, 1, '#a8acb8'); g.p(13, fy - 14, (t >> 2) % 2 ? '#3dff8f' : '#1a5a3a');
    if(t % 20 < 6) g.r(10, fy - 13 + ((t % 20) >> 1), 4, 1, '#ffffff');
    g.r(18, 9, 7, 8, '#f4f0fa'); g.r(18, 9, 7, 2, '#d42a3a'); for(let i = 0; i < 6; i++) g.p(19 + (i % 3) * 2, 12 + Math.floor(i / 3) * 2, '#8a90a8');
    const dx = Math.max(28, Math.floor(w * .45));
    const s = pxPlatz(g, dx, Math.min(24, w - dx - 3), fy, '#d6a94e', t, an, 'code', 2, rng);
    g.r(dx, fy - 6, Math.min(24, w - dx - 3), 1, '#ffd98a');
    const rx = dx + 30;
    if(w - rx > 34){
      pxSofa(g, rx + 4, fy, 22, '#7b4bff');
      g.r(rx + 30, fy - 5, 10, 1, '#c8905a'); g.r(rx + 34, fy - 4, 2, 4, '#6a4a30'); g.r(rx + 32, fy - 7, 2, 2, '#e8e0f0'); g.r(rx + 36, fy - 6, 3, 1, '#f4f0fa');
      pxWandschirm(g, rx + 6, 12, 18, 9, '#ffb84d', t, 'kerzen');
      if(w - rx > 56){ pxWandRegal(g, rx + 30, 22, 16, rng, '#ffb84d'); pxWasser(g, rx + 46, fy, t); }
      if(w - rx > 70){ pxBuecher(g, rx + 54, 9, 12, fy - 9, rng); pxPflanzeGross(g, rx + 68, fy); }
      if(w - rx > 90){ pxPinnwand(g, rx + 78, 11, 14, 8, rng); pxKaffee(g, rx + 80, fy, t); pxAkten(g, rx + 90, fy, 14, '#4a3a50'); }
    }
    return s;
  },
};

/* ---- Ein Agentenraum ---- */
function pxAgentRaum(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const typ = e.typ in PX_TYP ? e.typ : 'command';
  const fy = pxHuelle(g, w, h, e.farbe, typ, rng, t + (e.seed & 31));
  const hell = pxMix(e.farbe, '#ffffff', .45);
  const lampe = 8 + Math.floor(rng() * Math.max(1, w - 16));
  const fenster = rng() < .4 && w > 60;
  // Verhalten: Wer einen Auftrag hat, sitzt am PC. Freie Bots wechseln zwischen Sitzen, Gehen und Stehen.
  const offen = (Number(e.offen) || 0) > 0;
  const modus = e.st === 'blockiert' ? 'alarm' : e.st === 'wartet' ? 'denkt' : (e.st === 'laeuft' || offen) ? 'arbeitet' : 'pause';
  const C = 140, p = (t + e.seed % C) % C;
  const sitzt = modus === 'arbeitet' || modus === 'denkt' || (modus === 'pause' && p < 50);
  if(fenster) pxFenster(g, w - 13, 9, 10, 7, rng);
  const sx = PX_TYP[typ](g, fenster ? w - 13 : w, fy, e.farbe, hell, rng, t, sitzt);
  pxLampe(g, lampe, fy, e.farbe);
  const look = e.look;
  if(sitzt){
    pxFigur(g, sx, fy, look, 'sitzt', t, true);
    if(modus === 'denkt') pxBlase(g, sx + 1, fy - 20, 'denkt', t);
  }else if(modus === 'alarm'){
    const x = Math.max(2, sx - 3);
    pxFigur(g, x, fy, look, 'steht', t, true);
    pxBlase(g, x, fy - 19, 'alarm', t);
  }else{
    const ziel = 3 + (e.seed >> 5) % Math.max(1, sx - 12), weg = sx - ziel;
    let x, pose = 'geht', rechts = false;
    if(p < 82){ x = sx - Math.round(weg * (p - 50) / 32); }
    else if(p < 108){ x = ziel; pose = 'steht'; }
    else { x = ziel + Math.round(weg * (p - 108) / 32); rechts = true; }
    pxFigur(g, x, fy, look, pose, t, rechts);
    if(pose === 'steht'){ g.p(rechts ? x + 5 : x - 1, fy - 5, '#e8e0f0'); if(t % 6 < 3) g.p(rechts ? x + 5 : x - 1, fy - 7, '#c8c0d8'); }
  }
  if(e.st === 'blockiert') g.a(t % 8 < 4 ? .16 : .05, () => g.r(0, 0, w, h, '#ff1f4b'));
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}

/* ---- Durchgang zwischen zwei Räumen derselben Abteilung ---- */
function pxTuer(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const typ = e.typ || 'command', f = e.farbe;
  const fy = pxHuelle(g, w, h, f, typ, rng, t);
  const hoch = Math.min(26, fy - 14), x0 = 3, bw = w - 6, top = fy - hoch;
  const rahmen = pxMix('#59619a', f, .25);
  g.r(x0, top, bw, hoch, '#0e1020');
  g.r(x0 + 2, top + 2, bw - 4, hoch - 2, '#161a2e');
  g.a(.25, () => g.r(x0 + 2, top + 2, bw - 4, 3, f));
  g.r(x0 + 2, fy - 2, bw - 4, 2, pxMix(PX_BODEN[typ] || '#3b3448', '#000000', .3));
  g.r(x0, top, 2, hoch, rahmen); g.r(x0 + bw - 2, top, 2, hoch, rahmen); g.r(x0, top - 2, bw, 2, rahmen);
  g.r(x0 + 2, top, 1, hoch, f); g.r(x0 + bw - 3, top, 1, hoch, f);
  g.r(x0 + 2, top - 4, bw - 4, 1, (t >> 2) % 6 ? '#3dff8f' : '#1a5a3a');
  const oben = 7, platz = top - 6 - oben;
  if(typ === 'command'){
    g.r(3, oben, w - 6, Math.min(6, platz), '#04161c'); g.r(3, oben, w - 6, 1, '#38e8ff');
    for(let i = 0; i < 5; i++) g.p(4 + pxN(i, 1, 2) % (w - 8), oben + 2 + pxN(i, 3, 4) % 3, (t + i) % 5 < 2 ? '#38e8ff' : '#0e5a66');
    g.r(1, top + 8, 2, 4, '#2a3550'); g.p(1, top + 9, '#38e8ff'); g.p(1, top + 11, (t >> 2) % 2 ? '#ff3fa4' : '#3a2040');
  }else if(typ === 'server'){
    g.r(0, oben, w, 2, '#3a3f56');
    for(let i = 0; i < 4; i++){ const c = ['#ff3fa4','#38e8ff','#ffd84d','#3dff8f'][i]; for(let x = 0; x < w; x++) g.p(x, oben + 2 + i + (Math.sin(x / 2 + i) > .6 ? 1 : 0), c); }
    g.r(w - 3, oben + 7, 2, top - oben - 7, '#ff3fa4');
    pxNetz(g, Math.floor(w / 2), oben + 10, 2, pxMix(f, '#ffffff', .3));
  }else if(typ === 'lab'){
    pxWarnschild(g, Math.floor(w / 2) - 2, oben + 1, '#ffcc33');
    g.r(Math.floor(w / 2) - 3, oben + 7, 6, 3, '#3dff8f'); g.p(Math.floor(w / 2) - 1, oben + 8, '#ffffff'); g.p(Math.floor(w / 2), oben + 8, '#ffffff');
    pxLoescher(g, 1, fy - 2);
  }else if(typ === 'trading'){
    g.r(1, oben + 1, w - 2, 4, '#0b0710');
    for(let x = 1; x < w - 1; x++){ const v = pxN(x + t, 9, 2); g.p(x, oben + 2 + (v % 2), v % 3 ? '#3dff8f' : '#ff4d6d'); }
    pxUhr(g, Math.floor(w / 2) - 2, oben + 6, t);
  }else if(typ === 'research'){
    pxPinnwand(g, 3, oben + 1, w - 6, Math.min(6, platz - 1), rng);
    pxPflanze(g, 0, fy);
  }else if(typ === 'risk'){
    pxBake(g, Math.floor(w / 2) - 2, oben + 3, t);
    for(let y = top; y < fy; y += 4){ g.r(x0, y, 2, 2, '#ffcc33'); g.r(x0 + bw - 2, y + 2, 2, 2, '#ffcc33'); }
    pxWarnschild(g, Math.floor(w / 2) - 2, oben + 8, '#ff5577');
  }else if(typ === 'archive'){
    pxWandRegal(g, 2, oben + 5, w - 4, rng, f);
    pxBuecher(g, 2, oben + 6, w - 4, Math.max(5, platz - 6), rng);
  }else if(typ === 'workshop'){
    g.r(2, oben, w - 4, 7, '#3a3f4a'); g.r(4, oben + 1, 1, 5, '#c0c4cc'); g.r(3, oben + 1, 3, 1, '#c0c4cc'); g.r(8, oben + 2, 4, 1, '#ff9f43'); g.r(10, oben + 1, 1, 4, '#8a8f99');
    for(let x = x0; x < x0 + bw; x += 4) g.r(x, top - 2, 2, 2, '#ffcc33');
    pxFass(g, w - 5, fy, '#d46a2a');
  }else if(typ === 'observatory'){
    const cx = Math.floor(w / 2), cy = oben + 5;
    for(let y = -4; y <= 4; y++) for(let x = -4; x <= 4; x++){ const d = x * x + y * y; if(d <= 12) g.p(cx + x, cy + y, '#0a0c2a'); else if(d <= 20) g.p(cx + x, cy + y, '#6a7390'); }
    g.r(cx, cy, 2, 2, '#ff7a59'); g.p(cx - 2, cy - 2, '#ffffff'); if((t >> 2) % 6 === 0) g.p(cx + 2, cy - 2, '#ffffff');
  }else if(typ === 'security'){
    g.r(Math.floor(w / 2) - 1, oben, 2, 3, '#5a5f78');
    const k = (t >> 3) % 2; g.r(Math.floor(w / 2) - 3 + k * 2, oben + 3, 4, 3, '#2a2e3a'); g.p(Math.floor(w / 2) - 3 + k * 5, oben + 4, '#ff3355');
    g.r(0, top + 8, 3, 5, '#1a1a24'); g.p(1, top + 9, (t >> 2) % 3 ? '#ff3355' : '#3dff8f'); g.r(1, top + 11, 1, 1, '#8a90a8');
  }else{
    g.r(3, oben + 1, w - 6, Math.min(7, platz - 1), '#d6a94e'); g.r(4, oben + 2, w - 8, Math.min(5, platz - 3), '#2a1a40'); g.p(6, oben + 4, '#ff5fc8'); g.p(w - 6, oben + 3, '#38e8ff');
    pxPflanze(g, 0, fy);
  }
}

/* ---- Gemeinschaftsräume ---- */
function pxAgentenraum(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#38e8ff', 'command', rng, t);
  const cx = Math.floor(w / 2);
  pxFenster(g, 8, 9, 34, 12, rng); pxFenster(g, w - 44, 9, 34, 12, rng);
  pxLueftung(g, 48, 9, 10); pxUhr(g, cx - 40, 10, t); pxPoster(g, cx + 34, 10, '#ff3fa4', 2);
  // Holo-Projektor mit Weltkugel
  g.r(cx - 16, fy - 6, 32, 2, '#3a4a66'); g.r(cx - 14, fy - 4, 28, 4, '#222c40'); g.r(cx - 10, fy - 7, 20, 1, '#38e8ff');
  for(let x = cx - 12; x < cx + 12; x += 4) g.p(x, fy - 2, (x + t) % 8 < 4 ? '#38e8ff' : '#1a4a5a');
  pxKegel(g, .25 + (t % 6) / 40, '#38e8ff', cx - 10, cx + 10, fy - 7, cx - 18, cx + 18, 8);
  const r = 9, gy = 24;
  for(let y = -r; y <= r; y++) for(let x = -r; x <= r; x++) if(x * x + y * y <= r * r){
    const lon = Math.floor((Math.atan2(y, x * 1.6) * 3 + t / 3)) % 3;
    if(x * x + y * y > (r - 1) * (r - 1) || lon === 0 || y % 4 === 0) g.p(cx + x, gy + y, '#9ffcff');
  }
  for(let i = 0; i < 10; i++){ const a = t / 5 + i * .63; g.p(cx + Math.round(Math.cos(a) * 14), gy + Math.round(Math.sin(a) * 4), i % 3 ? '#e0ffff' : '#ff5fc8'); }
  // Arbeitsreihe links
  const plaetze = Math.max(2, Math.floor((cx - 36) / 30));
  const n = Math.min(10, Math.max(2, e.anzahl || 4));
  let fig = 0;
  for(let i = 0; i < plaetze; i++){
    const dx = 14 + i * 30;
    const an = i < n;
    const s = pxPlatz(g, dx, 20, fy, '#38e8ff', t + i * 4, an, i % 2 ? 'kerzen' : 'code', 2, rng);
    if(an){ pxFigur(g, s, fy, pxLookNr(fig++), 'sitzt', t + i, true); }
  }
  // Lounge rechts
  const lx = cx + 26;
  pxSofa(g, lx + 4, fy, 26, '#7b4bff');
  if(n > plaetze){ pxFigur(g, lx + 8, fy - 2, pxLookNr(fig++), 'sitzt', 0, true); }
  if(n > plaetze + 1){ pxFigur(g, lx + 18, fy - 2, pxLookNr(fig++), 'sitzt', 0, true); }
  g.r(lx + 36, fy - 5, 12, 1, '#a99cba'); g.r(lx + 41, fy - 4, 2, 4, '#4a4058'); g.r(lx + 38, fy - 7, 2, 2, '#e8e0f0'); g.r(lx + 44, fy - 7, 2, 2, '#ff5fc8');
  pxWandschirm(g, lx + 6, 26, 22, 10, '#ff3fa4', t, 'kerzen');
  const bar = w - 70;
  g.r(bar, fy - 9, 28, 9, '#3a3346'); g.r(bar, fy - 10, 28, 1, '#8a80a0'); g.r(bar, fy - 9, 28, 1, '#38e8ff');
  pxKaffee(g, bar + 2, fy - 10, t); g.r(bar + 12, fy - 12, 2, 2, '#e8e0f0'); g.r(bar + 16, fy - 12, 2, 2, '#e8e0f0'); g.r(bar + 20, fy - 14, 4, 4, '#ff7a59'); g.p(bar + 21, fy - 15, '#3fd070');
  pxWandRegal(g, bar, 30, 28, rng, '#38e8ff');
  pxAutomat(g, w - 36, fy, t, '#38e8ff');
  pxWasser(g, w - 24, fy, t);
  pxPflanzeGross(g, w - 14, fy); pxPflanzeGross(g, 4, fy);
  // Laufende Agenten
  for(let i = fig; i < n; i++){
    const R = Math.max(10, w - 30), pp = (t + i * 53) % (R * 2);
    pxFigur(g, 10 + (pp < R ? pp : 2 * R - pp), fy, pxLookNr(i), 'geht', t, pp < R);
  }
  [.15, .38, .62, .85].forEach(k => pxLampe(g, Math.floor(w * k), fy, '#38e8ff'));
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}
function pxKonferenz(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ffb84d', 'meeting', rng, t);
  const cx = Math.floor(w / 2);
  // Wandbildschirm mit Rahmen
  g.r(cx - 50, 8, 100, 24, '#0b0812'); g.r(cx - 50, 8, 100, 1, '#ffb84d'); g.r(cx - 50, 31, 100, 1, '#6a4a20');
  pxMonitor(g, cx - 48, 10, 46, 20, '#3dff8f', t, true, 'kerzen');
  pxMonitor(g, cx + 2, 10, 22, 9, '#ff5577', t, true, 'kurve');
  pxMonitor(g, cx + 26, 10, 22, 9, '#38e8ff', t, true, 'code');
  pxMonitor(g, cx + 2, 21, 46, 9, '#ffb84d', t, true, 'karte');
  // Seiten: Fenster, Regal, Wasser, Pflanzen, Sideboard
  pxFenster(g, 8, 9, 26, 14, rng);
  pxBuecher(g, 40, 10, 22, fy - 10, rng);
  pxWasser(g, 66, fy, t); pxPflanzeGross(g, 3, fy); pxPflanzeGross(g, 74, fy - 0);
  pxFenster(g, w - 34, 9, 26, 14, rng);
  pxUhr(g, w - 66, 10, t); pxPoster(g, w - 56, 10, '#ffb84d', 1);
  const sb = w - 76;
  g.r(sb, fy - 8, 30, 8, '#6a4a30'); g.r(sb, fy - 8, 30, 1, '#c8905a'); g.r(sb + 14, fy - 7, 1, 7, '#4a3020'); g.p(sb + 7, fy - 4, '#c8905a'); g.p(sb + 21, fy - 4, '#c8905a');
  g.r(sb + 2, fy - 13, 3, 5, '#2a2a3a'); g.r(sb + 2, fy - 13, 3, 1, '#5a5a6a'); g.r(sb + 7, fy - 11, 2, 3, '#7fc8ff'); g.r(sb + 10, fy - 11, 2, 3, '#7fc8ff');
  g.r(sb + 15, fy - 10, 2, 2, '#e8e0f0'); g.r(sb + 19, fy - 10, 2, 2, '#e8e0f0'); g.r(sb + 24, fy - 12, 4, 4, '#ff7a59'); g.p(sb + 25, fy - 13, '#3fd070');
  pxPflanzeGross(g, w - 12, fy);
  // Kleiderständer
  g.r(w - 42, fy - 18, 1, 18, '#5a4330'); g.r(w - 44, fy - 18, 5, 1, '#5a4330'); g.r(w - 44, fy - 17, 2, 5, '#4f7fc9'); g.r(w - 44, fy - 1, 5, 1, '#5a4330');
  // Langer Tisch mit Stühlen
  const tw = Math.min(160, w - 190), tx = cx - Math.floor(tw / 2), ty = fy - 9;
  const plaetze = Math.floor((tw - 8) / 14);
  const n = Math.min(plaetze, Math.max(2, e.anzahl || 4));
  const redner = (t >> 4) % (n + 1);
  for(let i = 0; i < plaetze; i++){
    const x = tx + 6 + i * 14;
    g.r(x - 1, ty - 11, 7, 11, '#2a1a24'); g.r(x - 1, ty - 11, 7, 1, '#7a4a5a'); g.r(x, ty - 10, 5, 9, '#4a2a3a');
    if(i < n) pxSitztVorne(g, x, ty, pxLookNr(i + 3), i === redner);
  }
  g.r(tx, ty, tw, 2, '#c8905a'); g.r(tx, ty, tw, 1, '#e8b07a'); g.r(tx + 2, ty + 2, tw - 4, 5, '#8a5a3c'); g.r(tx + 2, ty + 6, tw - 4, 1, '#6a4028');
  for(let x = tx + 10; x < tx + tw - 10; x += 22) g.r(x, ty + 3, 12, 2, '#a06a44');
  g.r(tx + 4, ty + 7, 3, fy - ty - 7, '#4a3020'); g.r(tx + tw - 7, ty + 7, 3, fy - ty - 7, '#4a3020');
  for(let i = 0; i < plaetze; i++){
    const x = tx + 6 + i * 14;
    if(i < n && i % 2 === 0){ g.r(x, ty - 3, 5, 3, '#8a90a8'); g.p(x + 2, ty - 2, '#e8e8f0'); }
    else if(i < n){ g.r(x + 1, ty - 1, 4, 1, '#f4f0fa'); }
    g.r(x + 6, ty - 2, 1, 2, '#bfe8ff');
  }
  g.r(cx - 1, ty - 4, 3, 4, '#7fc8ff'); g.r(cx, ty - 5, 1, 1, '#5aa0e0');
  // Stühle an den Tischenden (seitlich)
  g.r(tx + tw + 5, fy - 10, 2, 7, '#4a2a3a'); g.r(tx + tw + 2, fy - 4, 5, 1, '#5a3a4a'); g.r(tx + tw + 4, fy - 3, 1, 2, '#2a2433'); g.r(tx + tw + 2, fy - 1, 5, 1, '#1b1825');
  if(n > 1){ const L = pxLookNr(1), y = fy - 12, sx2 = tx + tw + 2;
    g.r(sx2 + 1, y, 3, 1, L.haar); g.r(sx2 + 1, y + 1, 3, 2, L.haut); g.p(sx2 + 3, y + 1, L.haar); g.p(sx2 + 1, y + 1, '#140c1c');
    g.r(sx2 + 1, y + 3, 4, 4, L.hemd); g.r(sx2 - 1, y + 4, 2, 1, L.hemd); g.r(sx2, y + 7, 5, 1, L.hose); g.r(sx2, y + 8, 1, 3, L.hose); g.r(sx2 - 1, y + 11, 2, 1, '#0d0b12'); }
  // Redner vor dem Bildschirm
  const rx = tx - 9;
  pxFigur(g, rx, fy, pxLookNr(8), redner === n ? 'wartet' : 'steht', t, true);
  if(redner === n){ for(let i = 0; i < 6; i++) g.p(rx + 5 + i, fy - 7 - i * 2, '#c0c4cc'); }
  [.18, .4, .6, .82].forEach(k => pxLampe(g, Math.floor(w * k), fy, '#ffb84d'));
  if(e.on) g.a(.10, () => g.r(0, 0, w, h, '#ff3fa4'));
}

/* ---- Füllräume ---- */
function pxLounge(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ff5edb', 'lounge', rng, t);
  pxFenster(g, 4, 9, Math.min(22, w - 30), 9, rng);
  pxSofa(g, 6, fy, Math.min(20, w - 34), '#ff5edb');
  g.r(8, fy - 12, 6, 1, '#d6a94e');
  pxWandschirm(g, Math.min(30, w - 22), 9, 12, 7, '#38e8ff', t, 'kerzen');
  pxKaffee(g, w - 18, fy - 6, t); g.r(w - 20, fy - 6, 11, 6, '#3a3346'); g.r(w - 20, fy - 6, 11, 1, '#8a80a0');
  pxPflanzeGross(g, w - 7, fy);
  g.r(Math.min(30, w - 22), fy - 4, 8, 1, '#a99cba'); g.r(Math.min(33, w - 19), fy - 3, 2, 3, '#4a4058'); g.r(Math.min(31, w - 21), fy - 6, 2, 2, '#e8e0f0');
  pxLampe(g, Math.floor(w * .3), fy, '#ff5edb'); pxLampe(g, Math.floor(w * .75), fy, '#ff5edb');
  const R = Math.max(6, w - 20), p = (t * .5 + 31) % (R * 2);
  pxFigur(g, 6 + Math.round(p < R ? p : 2 * R - p), fy, pxLookNr(5), 'geht', t, p < R);
}
function pxLager(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#ff9f43', 'lager', rng, t);
  const rw = Math.max(16, Math.floor(w * .45));
  for(let y = 10; y < fy; y += 11){
    g.r(2, y + 9, rw, 1, '#8a6a4a');
    for(let x = 3; x < rw - 3; x += 6) if(pxN(x, y, 3) % 4) pxKiste(g, x, y + 9, 5, 4 + pxN(x, y, 5) % 3, ['#b8875a','#5a7aa0','#7a9a5a'][pxN(x, y, 1) % 3]);
  }
  g.r(2, 10, 1, fy - 10, '#5a5f78'); g.r(rw + 1, 10, 1, fy - 10, '#5a5f78');
  pxKiste(g, rw + 6, fy, 8, 7, '#b8875a'); pxKiste(g, rw + 7, fy - 7, 6, 5, '#5a7aa0');
  pxFass(g, rw + 16, fy, '#3a8a5a'); pxFass(g, rw + 22, fy, '#d46a2a');
  g.r(w - 10, fy - 9, 1, 9, '#c0c4cc'); g.r(w - 10, fy - 1, 5, 1, '#c0c4cc'); g.p(w - 6, fy, '#2a2a2a'); g.p(w - 9, fy, '#2a2a2a'); pxKiste(g, w - 9, fy - 1, 4, 4, '#b8875a');
  for(let x = 0; x < w; x += 4){ g.r(x, fy, 2, 1, '#ffcc33'); }
  pxWarnschild(g, rw + 8, 10);
  pxLampe(g, Math.floor(w * .3), fy, '#ff9f43'); pxLampe(g, Math.floor(w * .75), fy, '#ff9f43');
}

/* ---- Hangar 07 ---- */
function pxHangar(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#5aa9ff', 'hangar', rng, t);
  // Hangartor rechts mit Kraftfeld und Weltraum
  const tx = w - 48, ty = 12;
  g.r(tx, ty, 44, fy - ty, '#03040e');
  for(let i = 0; i < 40; i++){ const sx = tx + ((pxN(i, 1, 1) % 44) - (t * (1 + i % 3)) % 44 + 44) % 44, sy = ty + 1 + pxN(i, 2, 2) % (fy - ty - 2); g.p(sx, sy, i % 5 ? '#9fb4ff' : '#ffffff'); }
  for(let y = -6; y <= 6; y++) for(let x = -6; x <= 6; x++) if(x * x + y * y <= 36) g.p(tx + 30 + x, ty + 22 + y, (x + y) % 3 ? '#c86a3a' : '#e8904a');
  g.a(.14 + ((t % 10) < 5 ? .05 : 0), () => g.r(tx, ty, 44, fy - ty, '#38e8ff'));
  for(let x = tx + ((t >> 1) % 6); x < tx + 44; x += 6) g.a(.2, () => g.r(x, ty, 1, fy - ty, '#9ffcff'));
  g.r(tx - 4, ty - 4, 4, fy - ty + 4, '#3b4268'); g.r(tx + 44, ty - 4, 4, fy - ty + 4, '#3b4268'); g.r(tx - 4, ty - 4, 52, 4, '#3b4268');
  for(let y = ty; y < fy; y += 6){ g.r(tx - 4, y, 4, 3, '#ffcc33'); g.r(tx + 44, y + 3, 4, 3, '#ffcc33'); }
  for(let i = 0; i < 3; i++) g.r(tx, ty + i * 2, 44, 1, '#59619a');
  // Kontrollkabine oben links mit Treppe
  g.r(4, 9, 58, 24, '#2a2f48'); g.r(4, 9, 58, 1, '#59619a'); g.r(6, 12, 54, 11, '#0b1530'); g.a(.3, () => g.r(6, 12, 54, 3, '#7fd4ff'));
  pxSitztVorne(g, 16, 23, pxLookNr(2), false); pxSitztVorne(g, 40, 23, pxLookNr(6), (t >> 4) % 2 === 0);
  g.r(6, 23, 54, 3, '#3a3f5a'); for(let x = 8; x < 58; x += 3) g.p(x, 24, (x + t) % 7 < 2 ? '#3dff8f' : (x % 2 ? '#38e8ff' : '#ff5fc8'));
  g.r(4, 33, 58, 2, '#59619a');
  for(let i = 0; i < 12; i++){ g.r(62 + i * 2, 35 + i * 4, 3, 1, '#59619a'); }
  g.r(62, 31, 1, 4, '#8a90a8'); for(let i = 0; i < 12; i++) g.p(64 + i * 2, 30 + i * 4, '#8a90a8');
  // Kisten, Fässer, Tank unter der Kabine
  pxKiste(g, 4, fy, 10, 8, '#b8875a'); pxKiste(g, 15, fy, 8, 6, '#5a7aa0'); pxKiste(g, 6, fy - 8, 7, 6, '#7a9a5a');
  pxFass(g, 25, fy, '#d46a2a'); pxFass(g, 31, fy, '#3a8a5a');
  pxTank(g, 40, fy - 20, 9, 20, '#38e8ff', t); pxTank(g, 51, fy - 16, 7, 16, '#ff5fc8', t + 30);
  // Grosse Hangarnummer
  pxText(g, 94, 12, '07', '#5aa9ff', 3); pxText(g, 93, 11, '07', '#cfe8ff', 3);
  pxWarnschild(g, 98, 32); pxWarnschild(g, 106, 32); pxLueftung(g, 114, 30, 12);
  for(let x = 150; x < tx - 30; x += 46){ pxFenster(g, x, 32, 20, 7, rng); g.r(x + 24, 31, 3, 9, '#262a3c'); g.p(x + 25, 33, (x + t) % 10 < 5 ? '#ff3fa4' : '#3a2040'); g.p(x + 25, 36, '#38e8ff'); }
  // Laufkran
  const kl = 132, kr = tx - 12;
  g.r(kl, 9, kr - kl, 2, '#59619a'); for(let x = kl; x < kr; x += 8) g.p(x, 10, '#262a3c');
  const KR = kr - kl - 14, kp = (t >> 1) % (KR * 2), kx = kl + 2 + (kp < KR ? kp : 2 * KR - kp);
  g.r(kx, 11, 12, 4, '#ffb84d'); g.r(kx, 11, 12, 1, '#ffd98a'); g.p(kx + 2, 13, '#1a1a1a'); g.p(kx + 9, 13, '#1a1a1a');
  const sl = 14 + Math.round((Math.sin(t / 8) + 1) * 4);
  g.r(kx + 6, 15, 1, sl, '#8a90a8'); g.r(kx + 4, 15 + sl, 5, 1, '#c0c4cc');
  pxKiste(g, kx + 2, 15 + sl + 8, 9, 7, '#5a7aa0');
  // Landeplattform
  const cx = Math.floor((96 + tx) / 2);
  g.r(cx - 70, fy, 140, 1, '#ffcc33'); g.r(cx - 60, fy + 2, 120, 1, '#a08a2a');
  for(let x = cx - 70; x < cx + 70; x += 10) g.p(x, fy + 1, (x + t * 2) % 40 < 10 ? '#38e8ff' : '#1a3a4a');
  // Shuttle
  const sy = fy - 34 - ((t >> 3) % 6 === 0 ? 1 : 0), sx = cx - 58;
  g.r(sx + 6, sy + 10, 92, 16, '#c8d0e0'); g.r(sx + 6, sy + 10, 92, 2, '#e8f0ff'); g.r(sx + 6, sy + 24, 92, 2, '#8a92a8');
  g.r(sx + 98, sy + 12, 8, 12, '#c8d0e0'); g.r(sx + 106, sy + 15, 6, 8, '#b8c0d4'); g.r(sx + 112, sy + 18, 4, 4, '#a8b0c4');
  g.r(sx + 96, sy + 11, 12, 5, '#38e8ff'); g.r(sx + 97, sy + 12, 4, 1, '#c8ffff'); g.r(sx + 104, sy + 12, 1, 4, '#1a8aa0');
  g.r(sx + 20, sy + 4, 50, 6, '#b8c0d4'); g.r(sx + 20, sy + 4, 50, 1, '#e8f0ff'); g.r(sx + 30, sy + 1, 20, 3, '#9aa2b8');
  g.r(sx + 6, sy + 16, 92, 2, '#ff3fa4'); g.r(sx + 6, sy + 18, 92, 1, '#38e8ff');
  for(let x = sx + 14; x < sx + 96; x += 12){ g.r(x, sy + 12, 1, 12, '#a0a8bc'); }
  for(let i = 0; i < 6; i++){ g.r(sx + 22 + i * 10, sy + 13, 5, 3, '#0b1530'); g.p(sx + 23 + i * 10, sy + 13, '#7fd4ff'); }
  g.r(sx - 4, sy + 11, 10, 14, '#7a8298'); g.r(sx - 4, sy + 11, 10, 1, '#9aa2b8');
  const glut = (t & 1) ? '#38e8ff' : '#1a8aa0';
  g.r(sx - 8, sy + 13, 4, 4, glut); g.r(sx - 8, sy + 19, 4, 4, glut); g.a(.3, () => g.r(sx - 18, sy + 12, 10, 12, '#38e8ff'));
  g.r(sx + 30, sy + 26, 50, 3, '#9aa2b8'); g.r(sx + 26, sy + 29, 58, 2, '#7a8298');
  g.r(sx + 20, sy + 26, 2, fy - sy - 26, '#555b6e'); g.r(sx + 88, sy + 26, 2, fy - sy - 26, '#555b6e'); g.r(sx + 18, fy - 1, 6, 1, '#3a3f56'); g.r(sx + 86, fy - 1, 6, 1, '#3a3f56');
  g.p(sx + 60, sy + 3, (t >> 2) % 2 ? '#ff3355' : '#5a1a2a'); g.p(sx + 112, sy + 20, (t >> 2) % 2 ? '#3dff8f' : '#1a5a3a');
  for(let i = 0; i < 9; i++) g.p(sx + 34 + i * 4 - Math.round(i * 0), sy + 26 + Math.round(i * (fy - sy - 26) / 9), '#a0a8bc');
  g.r(sx + 34, sy + 25, 2, 2, '#a0a8bc');
  // Mechaniker auf Leiter mit Funken
  const lx = sx + 70;
  g.r(lx, sy + 12, 1, fy - sy - 12, '#ffb84d'); g.r(lx + 5, sy + 12, 1, fy - sy - 12, '#ffb84d'); for(let y = sy + 14; y < fy; y += 4) g.r(lx, y, 6, 1, '#ffb84d');
  pxFigur(g, lx, sy + 26, pxLookNr(4), 'steht', t, false);
  if(t % 3 !== 2){ g.p(lx - 1, sy + 20, '#ffffff'); g.p(lx - 2 - (t % 3), sy + 21 + (t % 2), '#ffd84d'); g.p(lx - 1 - (t % 4), sy + 23, '#ff9f43'); }
  // Werkzeugwagen, Gabelstapler, Mechaniker mit Kiste, Drohne
  const ww = sx + 118; g.r(ww, fy - 8, 12, 6, '#d42a3a'); g.r(ww, fy - 8, 12, 1, '#ff6070'); g.r(ww + 1, fy - 6, 10, 1, '#8a1a2a'); g.r(ww + 1, fy - 4, 10, 1, '#8a1a2a'); g.p(ww + 1, fy - 1, '#1a1a1a'); g.p(ww + 10, fy - 1, '#1a1a1a'); g.r(ww + 3, fy - 10, 5, 2, '#8a8f99');
  const fx = 70 + Math.round((Math.sin(t / 25) + 1) * 30);
  g.r(fx, fy - 9, 12, 7, '#ffb84d'); g.r(fx + 2, fy - 14, 6, 5, '#2a2e3a'); g.r(fx + 3, fy - 13, 4, 3, '#7fd4ff'); g.r(fx + 12, fy - 13, 1, 12, '#5a5f78'); g.r(fx + 12, fy - 2, 6, 1, '#5a5f78');
  pxKiste(g, fx + 13, fy - 2, 5, 5, '#b8875a'); g.r(fx + 1, fy - 2, 3, 2, '#1a1a1a'); g.r(fx + 8, fy - 2, 3, 2, '#1a1a1a');
  pxFigur(g, fx + 4, fy - 6, pxLookNr(7), 'sitzt', 0, true);
  const mR = 60, mp = (t + 17) % (mR * 2), mx = sx + 90 + (mp < mR ? mp : 2 * mR - mp);
  pxFigur(g, mx, fy, pxLookNr(9), 'geht', t, mp >= mR);
  g.r(mx, fy - 10, 5, 3, '#b8875a');
  const dX = cx + Math.round(Math.cos(t / 11) * 50), dY = 30 + Math.round(Math.sin(t / 7) * 6);
  g.r(dX, dY, 6, 2, '#5a5f78'); g.r(dX - 1, dY - 1, 2, 1, '#c0c4cc'); g.r(dX + 5, dY - 1, 2, 1, '#c0c4cc'); g.p(dX + 2, dY + 2, (t & 1) ? '#ff3355' : '#3dff8f');
  [.1, .28, .46, .64, .8].forEach(k => pxLampe(g, Math.floor(w * k), fy, '#5aa9ff'));
}

/* ---- Warp Core ---- */
function pxWarp(g, w, h, e, t){
  const rng = pxRng(e.seed);
  const fy = pxHuelle(g, w, h, '#38e8ff', 'warp', rng, t);
  const cx = Math.floor(w / 2), puls = t % 12;
  // Halo
  g.a(.10 + (puls < 6 ? .05 : 0), () => g.r(cx - 30, 6, 60, fy - 6, '#38e8ff'));
  g.a(.08, () => g.r(cx - 46, 6, 92, fy - 6, '#38e8ff'));
  // Kühltanks an den Wänden
  pxTank(g, 4, fy - 30, 10, 30, '#38e8ff', t); pxTank(g, 16, fy - 24, 8, 24, '#3dff8f', t + 13);
  pxTank(g, w - 14, fy - 30, 10, 30, '#38e8ff', t + 7); pxTank(g, w - 24, fy - 24, 8, 24, '#ff5fc8', t + 21);
  // Plasmaleitungen zu den Wänden
  [18, 40].forEach((y, j) => {
    g.r(4, y, cx - 14, 4, '#3a3f56'); g.r(cx + 10, y, w - cx - 14, 4, '#3a3f56');
    g.r(4, y, cx - 14, 1, '#565c78'); g.r(cx + 10, y, w - cx - 14, 1, '#565c78');
    for(let x = 0; x < cx - 14; x += 9){ const xx = cx - 12 - ((x + t * 2 + j * 4) % (cx - 16)); g.r(xx, y + 1, 3, 2, '#9ffcff'); g.r(w - xx - 3, y + 1, 3, 2, '#9ffcff'); }
    for(let x = 10; x < cx - 14; x += 16){ g.r(x, y - 1, 3, 6, '#262a3c'); g.r(w - x - 3, y - 1, 3, 6, '#262a3c'); }
  });
  // Deckenanschluss
  g.r(cx - 16, 4, 32, 3, '#555b6e'); g.r(cx - 12, 7, 24, 3, '#3a3f56'); g.r(cx - 12, 7, 24, 1, '#6a7090');
  // Reaktorbasis
  const by = fy - 12;
  g.r(cx - 26, by, 52, 12, '#3a3f56'); g.r(cx - 26, by, 52, 2, '#6a7090'); g.r(cx - 22, by + 3, 44, 7, '#1a1d2e');
  for(let x = cx - 20; x < cx + 20; x += 4){ g.r(x, by + 4, 2, 5, ((x + t) % 12) < 6 ? '#1fb8d0' : '#0a4050'); }
  for(let x = cx - 34; x < cx + 34; x += 4){ g.r(x, fy, 2, 1, '#ffcc33'); g.r(x + 2, fy, 2, 1, '#1a1a1a'); }
  // Kernsäule
  const top = 10, bot = by;
  g.r(cx - 10, top, 20, bot - top, '#2a2e40'); g.r(cx - 10, top, 2, bot - top, '#4a5068'); g.r(cx + 8, top, 2, bot - top, '#1a1d2e');
  for(let y = top; y < bot; y++){ const hell = ((y + puls * 2) % 12) < 3; g.r(cx - 6, y, 12, 1, hell ? '#c8ffff' : (y % 2 ? '#1fb8d0' : '#3fd8f0')); }
  g.r(cx - 1, top, 2, bot - top, '#ffffff');
  for(let y = top + 4; y < bot - 2; y += 9){
    g.r(cx - 14, y, 28, 3, '#555b6e'); g.r(cx - 14, y, 28, 1, '#8a90a8');
    g.p(cx - 12, y + 1, (y + t) % 6 < 3 ? '#ff3fa4' : '#5a1a3a'); g.p(cx + 11, y + 1, (y + t) % 6 < 3 ? '#ff3fa4' : '#5a1a3a');
  }
  if(t % 17 < 2){ for(let i = 0; i < 6; i++) g.p(cx + 14 + i * 2, 20 + ((i * 3 + t) % 4) - 1, '#e0ffff'); }
  if(t % 23 < 2){ for(let i = 0; i < 6; i++) g.p(cx - 15 - i * 2, 42 - ((i * 3 + t) % 4) + 1, '#e0ffff'); }
  // Laufsteg mit Geländer und Leiter
  const cw = 54;
  g.r(30, cw, cx - 44, 2, '#59619a'); g.r(cx + 14, cw, w - cx - 44, 2, '#59619a');
  g.r(30, cw - 6, cx - 44, 1, '#8a90a8'); g.r(cx + 14, cw - 6, w - cx - 44, 1, '#8a90a8');
  for(let x = 30; x < cx - 14; x += 6) g.r(x, cw - 6, 1, 6, '#8a90a8');
  for(let x = cx + 14; x < w - 30; x += 6) g.r(x, cw - 6, 1, 6, '#8a90a8');
  g.r(34, cw, 1, fy - cw, '#ffb84d'); g.r(39, cw, 1, fy - cw, '#ffb84d'); for(let y = cw + 3; y < fy; y += 4) g.r(34, y, 6, 1, '#ffb84d');
  g.r(w - 40, cw, 1, fy - cw, '#ffb84d'); g.r(w - 35, cw, 1, fy - cw, '#ffb84d'); for(let y = cw + 3; y < fy; y += 4) g.r(w - 40, y, 6, 1, '#ffb84d');
  const LR = w - cx - 52, lp = (t + 9) % (LR * 2);
  pxFigur(g, cx + 16 + (lp < LR ? lp : 2 * LR - lp), cw, pxLookNr(3), 'geht', t, lp < LR);
  pxFigur(g, 46 + Math.round(Math.sin(t / 20) * 6), cw, pxLookNr(10), 'steht', t, true);
  // Konsolen mit Technikern
  [[44, false], [w - 72, true]].forEach(([kx, sp], i) => {
    g.r(kx, fy - 9, 22, 9, '#2a2e40'); g.r(kx, fy - 10, 22, 2, '#4a5068');
    pxMonitor(g, kx + 2, fy - 18, 8, 6, '#38e8ff', t + i * 5, true, i ? 'kurve' : 'code'); pxMonitor(g, kx + 12, fy - 18, 8, 6, '#ff3fa4', t + i * 3, true, 'kerzen');
    for(let x = kx + 2; x < kx + 20; x += 3) g.p(x, fy - 7, (x + t) % 5 < 2 ? '#3dff8f' : '#ffb84d');
    const sx = sp ? kx + 24 : kx - 7;
    if(!sp){ pxStuhl(g, sx - 1, fy); pxFigur(g, sx, fy, pxLookNr(i + 5), 'sitzt', t, true); }
    else { g.r(sx + 3, fy - 10, 2, 7, '#3b3550'); g.r(sx, fy - 4, 5, 1, '#4d4666'); g.r(sx + 2, fy - 3, 1, 2, '#2a2433'); g.r(sx, fy - 1, 5, 1, '#1b1825');
      const L = pxLookNr(i + 5), y = fy - 12, tp = t & 1;
      g.r(sx + 1, y, 3, 1, L.haar); g.r(sx + 1, y + 1, 3, 2, L.haut); g.p(sx + 3, y + 1, L.haar); g.p(sx + 1, y + 1, '#140c1c');
      g.r(sx + 1, y + 3, 4, 4, L.hemd); g.r(sx - 1, y + 4 + tp, 2, 1, L.hemd); g.p(sx - 2, y + 4 + tp, L.haut);
      g.r(sx, y + 7, 5, 1, L.hose); g.r(sx, y + 8, 1, 3, L.hose); g.r(sx - 1, y + 11, 2, 1, '#0d0b12'); }
  });
  // Anzeigen, Warnschilder, Dampf
  pxAnzeige(g, 28, 26, t, '#ff3355'); pxAnzeige(g, 37, 26, t + 11, '#38e8ff'); pxAnzeige(g, w - 44, 26, t + 5, '#ffb84d'); pxAnzeige(g, w - 35, 26, t + 17, '#3dff8f');
  pxWarnschild(g, cx - 34, 26); pxWarnschild(g, cx + 29, 26);
    for(const vx of [cx - 32, cx + 28]){
    g.r(vx, fy - 1, 5, 1, '#1a1d2e');
    if((t + vx) % 20 < 8){ const k = (t + vx) % 20; g.a(.5 - k / 20, () => g.r(vx - Math.floor(k / 3), fy - 2 - k, 5 + Math.floor(k / 2), 2, '#c8d0e0')); }
  }
  [.2, .8].forEach(k => pxLampe(g, Math.floor(w * k), fy, '#38e8ff'));
}
const PX_ART = { agent:pxAgentRaum, agents:pxAgentenraum, konf:pxKonferenz, hangar:pxHangar, warp:pxWarp, tuer:pxTuer, lounge:pxLounge, lager:pxLager };
function pxWandschirm(g, x, y, w, h, farbe, t, art){ g.r(x - 2, y - 2, w + 4, h + 4, '#05040a'); g.r(x - 2, y - 2, w + 4, 1, pxMix(farbe, '#000000', .3)); pxMonitor(g, x, y, w, h, farbe, t, true, art); }
  window.PX_GROSS = PX_ART;
})();
