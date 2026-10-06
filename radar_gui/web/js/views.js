// Canvas views: top, 3D, front, sparkline. Ported from tools/radar_viewer/index.html.
import { $, css, S } from './state.js';
import { colorOf } from './colors.js';

function fit(cv) {
  const r = cv.getBoundingClientRect(), d = devicePixelRatio || 1;
  if (cv.width !== Math.round(r.width * d) || cv.height !== Math.round(r.height * d)) {
    cv.width = Math.round(r.width * d); cv.height = Math.round(r.height * d);
  }
  const ctx = cv.getContext('2d'); ctx.setTransform(d, 0, 0, d, 0, 0);
  return [ctx, r.width, r.height];
}
export function visiblePoints() {
  const out = [], n = S.frames.length;
  S.frames.forEach((f, i) => { for (const p of f.pts) if (p[4] >= S.minSnr) out.push([p, n - 1 - i]); });
  return out;
}
const alphaOf = age => S.trail > 1 ? Math.max(0.12, 1 - age / S.trail) : 1;

export let topXf = null;
function drawTop() {
  const [ctx, W, H] = fit($('main'));
  ctx.clearRect(0, 0, W, H);
  const R = S.range, pad = 24;
  const scale = Math.min((W - 2 * pad) / (2 * R), (H - 2 * pad) / R);
  const ox = W / 2, oy = H - pad;
  topXf = { scale, ox, oy };
  const X = x => ox + x * scale, Y = y => oy - y * scale;

  const fov = (S.cfg.fov || [-85, 85]).slice(0, 2).map(d => d * Math.PI / 180);
  ctx.fillStyle = 'rgba(88,166,255,0.05)';
  ctx.beginPath(); ctx.moveTo(ox, oy);
  ctx.arc(ox, oy, R * scale, -Math.PI / 2 + fov[0], -Math.PI / 2 + fov[1]); ctx.closePath(); ctx.fill();
  ctx.fillStyle = css('--muted'); ctx.font = '11px system-ui';
  const step = R <= 6 ? 1 : R <= 15 ? 2 : 5;
  for (let r = step; r <= R; r += step) {
    ctx.strokeStyle = r % (step * 5) === 0 ? css('--grid-strong') : css('--grid');
    ctx.beginPath(); ctx.arc(ox, oy, r * scale, Math.PI, 2 * Math.PI); ctx.stroke();
    ctx.fillText(`${r} m`, ox + 4, oy - r * scale - 3);
  }
  for (const a of [-60, -30, 0, 30, 60]) {
    const t = a * Math.PI / 180;
    ctx.strokeStyle = css('--grid');
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(X(R * Math.sin(t)), Y(R * Math.cos(t))); ctx.stroke();
  }
  ctx.fillStyle = css('--accent'); ctx.fillRect(ox - 10, oy - 3, 20, 6);
  for (const [p, age] of visiblePoints()) {
    ctx.globalAlpha = alphaOf(age); ctx.fillStyle = colorOf(p);
    ctx.beginPath(); ctx.arc(X(p[0]), Y(p[1]), S.size, 0, 2 * Math.PI); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function project(x, y, z, W, H) {
  // world: x right, y forward, z up. Orbit around a point in front of the sensor.
  const px = x, py = y - S.range / 2, pz = z;
  const cyw = Math.cos(S.yaw), syw = Math.sin(S.yaw), cp = Math.cos(S.pitch), sp = Math.sin(S.pitch);
  const x1 = px * cyw - py * syw, y1 = px * syw + py * cyw;
  const y2 = y1 * cp - pz * sp, z2 = y1 * sp + pz * cp;
  const depth = S.range * 2.2 / S.zoom + y2;
  if (depth <= 0.1) return null;
  const f = Math.min(W, H) * 0.9;
  return [W / 2 + x1 * f / depth, H / 2 - z2 * f / depth, depth];
}
function draw3D() {
  const [ctx, W, H] = fit($('main'));
  ctx.clearRect(0, 0, W, H);
  const R = S.range, line = (a, b) => {
    const p = project(...a, W, H), q = project(...b, W, H);
    if (p && q) { ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke(); }
  };
  ctx.lineWidth = 1;
  const step = R <= 6 ? 1 : R <= 15 ? 2 : 5;
  for (let v = -R; v <= R + 1e-9; v += step) { ctx.strokeStyle = v === 0 ? css('--grid-strong') : css('--grid'); line([v, 0, 0], [v, R, 0]); }
  for (let v = 0; v <= R + 1e-9; v += step) { ctx.strokeStyle = css('--grid'); line([-R, v, 0], [R, v, 0]); }
  ctx.lineWidth = 2;
  ctx.strokeStyle = '#ef4444'; line([0, 0, 0], [1, 0, 0]);
  ctx.strokeStyle = '#22c55e'; line([0, 0, 0], [0, 1, 0]);
  ctx.strokeStyle = '#3b82f6'; line([0, 0, 0], [0, 0, 1]);
  const pts = visiblePoints().map(([p, age]) => [p, age, project(p[0], p[1], p[2], W, H)]).filter(e => e[2]);
  pts.sort((a, b) => b[2][2] - a[2][2]); // far first
  for (const [p, age, s] of pts) {
    ctx.globalAlpha = alphaOf(age); ctx.fillStyle = colorOf(p);
    const r = Math.max(1, S.size * (S.range * 2.2 / S.zoom) / s[2]);
    ctx.beginPath(); ctx.arc(s[0], s[1], r, 0, 2 * Math.PI); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawFront() {
  const [ctx, W, H] = fit($('front'));
  ctx.clearRect(0, 0, W, H);
  const R = S.range, zMin = -2, zMax = 3, pad = 18;
  const sx = (W - 2 * pad) / (2 * R), sz = (H - 2 * pad) / (zMax - zMin);
  const X = x => W / 2 + x * sx, Z = z => H - pad - (z - zMin) * sz;
  ctx.strokeStyle = css('--grid'); ctx.fillStyle = css('--muted'); ctx.font = '10px system-ui';
  for (let z = zMin; z <= zMax; z++) { ctx.beginPath(); ctx.moveTo(pad, Z(z)); ctx.lineTo(W - pad, Z(z)); ctx.stroke(); ctx.fillText(`${z}`, 2, Z(z) + 3); }
  ctx.strokeStyle = css('--grid-strong'); ctx.beginPath(); ctx.moveTo(W / 2, pad); ctx.lineTo(W / 2, H - pad); ctx.stroke();
  for (const [p, age] of visiblePoints()) {
    ctx.globalAlpha = alphaOf(age); ctx.fillStyle = colorOf(p);
    ctx.beginPath(); ctx.arc(X(p[0]), Z(p[2]), Math.max(1.5, S.size * 0.7), 0, 2 * Math.PI); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function drawSpark() {
  const [ctx, W, H] = fit($('spark'));
  ctx.clearRect(0, 0, W, H);
  const c = S.counts; if (c.length < 2) return;
  const max = Math.max(10, ...c), pad = 6;
  ctx.strokeStyle = css('--accent'); ctx.lineWidth = 1.5; ctx.beginPath();
  c.forEach((v, i) => {
    const x = pad + i / 199 * (W - 2 * pad), y = H - pad - v / max * (H - 2 * pad);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = css('--muted'); ctx.font = '10px system-ui'; ctx.fillText(`max ${max}`, W - 48, 11);
}

// Coalesced timeout rather than requestAnimationFrame, so it keeps drawing in background tabs.
let pending = false;
export function redraw() {
  if (pending) return;
  pending = true;
  setTimeout(() => {
    pending = false;
    try { S.view === 'top' ? drawTop() : draw3D(); drawFront(); drawSpark(); }
    catch (err) { $('statusMsg').textContent = 'Drawing error: ' + err.message; console.error(err); }
  }, 0);
}
