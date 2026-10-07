// Entry point: WebSocket stream + controls. Views live in views.js.
import { $, S } from './state.js';
import { drawLegend } from './colors.js';
import { redraw, visiblePoints, topXf } from './views.js';
import { showConfigure } from './cfg.js';
import { initSource, srcStatus, resetStats } from './source.js';
import { showSettings } from './settings.js';
import { showRun, onDriverMessage, openInRun, driverHeader } from './run.js';

// ---------- stream ----------
const STATE_DOT = { streaming: 'ok', starting: 'warn', configuring: 'warn', waiting: 'warn', ended: 'warn', error: 'bad', disconnected: 'bad',
  idle: '', cfg_failed: 'bad', no_tap: 'warn', wrong_firmware: 'bad', no_board: 'bad', stalled: 'bad' };
function setStatus(state, msg) {
  $('state').textContent = state.replace('_', ' ');
  $('dot').className = 'dot ' + (STATE_DOT[state] || '');
  $('statusMsg').textContent = msg || '';
  srcStatus(state, msg);
}
// D1: during a driver run the header Frame/Points/Rate show that run (Points has no meaning there), not the Live source.
let lastFrame = null;
function header(m) {
  const d = driverHeader();
  if (d) {
    $('sFrame').textContent = d.frame == null ? '–' : d.frame; $('sPts').textContent = '–';
    $('sRate').textContent = d.rate == null ? '–' : d.rate.toFixed(1) + ' Hz';
  } else if (m || lastFrame) {
    m = m || lastFrame; lastFrame = m;
    $('sFrame').textContent = m.frame; $('sPts').textContent = m.pts.length; $('sRate').textContent = m.rate.toFixed(1) + ' Hz';
  }
  $('sFrame').previousElementSibling.textContent = d ? 'Driver run' : 'Frame';
  $('sFrame').parentElement.title = d ? 'Driver run in progress: frames and rate are from the Run tab, not the Live source' : '';
}
function onMessage(m) {
  if (m.type === 'status') setStatus(m.state, m.msg);
  else if (m.type && m.type.startsWith('driver_')) { onDriverMessage(m); header(); }
  else if (m.type === 'cfg') {
    S.cfg = m; S.frames.length = 0; S.last = null; resetStats();
    $('cfgName').textContent = m.name || ''; $('cfgName').style.display = m.name ? '' : 'none';
    if (m.max_range_m && !S.rangeTouched) { $('range').value = Math.round(m.max_range_m); $('range').dispatchEvent(new Event('input')); }
    redraw();
  } else if (m.type === 'frame') {
    // gui-09 D8: while a driver run is live the Live view is not drawn (the mock/serial stream would only compete for the main thread)
    if (driverHeader()) { S.last = m; lastFrame = m; return; }
    S.last = m;
    S.counts.push(m.pts.length); if (S.counts.length > 200) S.counts.shift();
    lastFrame = m; header(m);
    $('sGaps').textContent = m.gaps; $('sErr').textContent = m.errors;
    $('gapStat').classList.toggle('bad', m.gaps > 0); $('errStat').classList.toggle('bad', m.errors > 0);
    if (!S.paused) { S.frames.push(m); while (S.frames.length > S.trail) S.frames.shift(); }
    redraw();
  }
}
function connect() {
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/stream`);
  ws.onmessage = ev => onMessage(JSON.parse(ev.data));
  ws.onclose = () => { setStatus('disconnected', 'Lost connection to the server. Retrying…'); setTimeout(connect, 1500); };
}

// ---------- controls ----------
function bindRange(id, key, fmt) {
  const el = $(id), out = $(id === 'minSnr' ? 'snrVal' : id + 'Val');
  const upd = () => {
    S[key] = +el.value; out.textContent = fmt(S[key]); redraw();
    if (key === 'trail') while (S.frames.length > S.trail) S.frames.shift();
  };
  el.addEventListener('input', upd); upd();
}
bindRange('range', 'range', v => `${v} m`);
$('range').addEventListener('pointerdown', () => { S.rangeTouched = true; });
bindRange('trail', 'trail', v => v === 1 ? 'live only' : `${v}`);
bindRange('size', 'size', v => `${v}`);
bindRange('minSnr', 'minSnr', v => `${v}`);

function seg(id, attr, key, after) {
  $(id).addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    [...$(id).children].forEach(c => c.classList.toggle('on', c === b));
    S[key] = b.dataset[attr]; redraw(); after && after();
  });
}
seg('viewSeg', 'v', 'view', () => {
  $('mainCard').classList.toggle('is3d', S.view === '3d');
  $('hint').textContent = S.view === '3d' ? 'drag to rotate · scroll to zoom' : 'x = right, y = forward (m)';
  $('tip').style.display = 'none';
});
seg('colorSeg', 'c', 'color', drawLegend);
drawLegend();

$('pause').onclick = () => { S.paused = !S.paused; $('pause').textContent = S.paused ? 'Resume' : 'Pause'; };
$('resetView').onclick = () => { S.yaw = -0.35; S.pitch = 0.4; S.zoom = 1; redraw(); };

const cv = $('main');
let drag = null;
cv.addEventListener('pointerdown', e => { if (S.view === '3d') { drag = [e.clientX, e.clientY]; cv.setPointerCapture(e.pointerId); cv.style.cursor = 'grabbing'; } });
cv.addEventListener('pointerup', () => { drag = null; cv.style.cursor = ''; });
cv.addEventListener('pointermove', e => {
  if (drag) {
    S.yaw += (e.clientX - drag[0]) * 0.008;
    S.pitch = Math.max(-0.1, Math.min(1.5, S.pitch + (e.clientY - drag[1]) * 0.008));
    drag = [e.clientX, e.clientY]; redraw(); return;
  }
  if (S.view !== 'top' || !topXf) return;
  const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = null, bd = 100;
  for (const [p, age] of visiblePoints()) {
    if (age) continue;
    const dx = topXf.ox + p[0] * topXf.scale - mx, dy = topXf.oy - p[1] * topXf.scale - my, d = dx * dx + dy * dy;
    if (d < bd) { bd = d; best = p; }
  }
  const tip = $('tip');
  if (!best) { tip.style.display = 'none'; return; }
  tip.innerHTML = `range ${Math.hypot(best[0], best[1], best[2]).toFixed(2)} m<br>` +
    `x ${best[0].toFixed(2)} · y ${best[1].toFixed(2)} · z ${best[2].toFixed(2)} m<br>` +
    `v ${best[3].toFixed(2)} m/s · SNR ${best[4].toFixed(1)} dB`;
  tip.style.display = 'block'; tip.style.left = (mx + 14) + 'px'; tip.style.top = (my + 40) + 'px';
});
cv.addEventListener('pointerleave', () => { $('tip').style.display = 'none'; });
cv.addEventListener('wheel', e => {
  if (S.view !== '3d') return;
  e.preventDefault(); S.zoom = Math.max(0.3, Math.min(6, S.zoom * Math.exp(-e.deltaY * 0.001))); redraw();
}, { passive: false });
addEventListener('resize', redraw);

// ---------- tabs ----------
const HASH = { cfg: '#configure', run: '#run', settings: '#settings' };
function tab(name) {
  [...$('tabs').children].forEach(b => b.classList.toggle('on', b.dataset.tab === name));
  $('liveMain').hidden = name !== 'live'; $('cfgMain').hidden = name !== 'cfg'; $('runMain').hidden = name !== 'run'; $('setMain').hidden = name !== 'settings';
  if (name === 'cfg') showConfigure(); else if (name === 'run') showRun(); else if (name === 'settings') showSettings(); else redraw();
  history.replaceState(null, '', HASH[name] || location.pathname);
}
// Configure -> Save result "Open in Run" link
addEventListener('open-in-run', e => { tab('run'); openInRun(e.detail); });
addEventListener('goto-tab', e => tab(e.detail));   // gui-36: Live card "Manage in Run tab" / Run "Watching in Live"
$('tabs').addEventListener('click', e => { const b = e.target.closest('button'); if (b) tab(b.dataset.tab); });
if (location.hash === '#configure') tab('cfg'); else if (location.hash === '#run') tab('run'); else if (location.hash === '#settings') tab('settings');

if (location.hash === '#3d') $('viewSeg').children[1].click();  // link straight to the 3D view
initSource();
connect();
redraw();
