// Entry point: WebSocket stream + controls. Views live in views.js.
import { $, S } from './state.js';
import { drawLegend } from './colors.js';
import { redraw, visiblePoints, topXf } from './views.js';
import { showConfigure } from './cfg.js';
import { initSource, srcStatus, resetStats } from './source.js';
import { initSession, feedMessage, boardLive, view as sessView } from './session.js';
import { showSettings } from './settings.js';
import { showRun, onDriverMessage, openInRun, driverHeader } from './run.js';
import { showAdc, hideAdc, initAdc } from './adc.js';

// ---------- stream ----------
// The stream state (starting / streaming / ended / ...) feeds the session store, which renders the header session bar.
function setStatus(state, msg) {
  feedMessage({ type: 'status', state, msg });
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
  else if (m.type && m.type.startsWith('driver_')) { onDriverMessage(m); feedMessage(m); header(); }
  else if (m.type === 'cfg') {
    S.cfg = m; S.frames.length = 0; S.last = null; resetStats();
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
// Internal ids (data-tab values) are unchanged by the gui-37 renames; the labels are Configure, Radar (run), Point cloud (live),
// Raw ADC (adc), Devices (settings) and Logs. Old hashes (#run, #settings, ...) keep working next to the new names.
const HASH = { cfg: '#configure', run: '#run', adc: '#adc', settings: '#settings', logs: '#logs' };
const ALIAS = { '#configure': 'cfg', '#cfg': 'cfg', '#run': 'run', '#radar': 'run', '#live': 'live', '#pointcloud': 'live', '#adc': 'adc',
  '#settings': 'settings', '#devices': 'settings', '#logs': 'logs', '#3d': 'live' };
const PANEL = { cfg: 'cfgMain', run: 'runMain', live: 'liveMain', adc: 'adcMain', settings: 'setMain', logs: 'logsMain' };
let navigated = false;
const tabButtons = () => [...$('tabs').querySelectorAll('[role=tab]')];
function tab(name, auto) {
  if (!PANEL[name] || !$(PANEL[name])) return;
  if (!auto) navigated = true;
  for (const b of tabButtons()) {
    const on = b.dataset.tab === name;
    b.classList.toggle('on', on); b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1;
  }
  for (const [k, id] of Object.entries(PANEL)) if ($(id)) $(id).hidden = k !== name;
  if (name === 'adc') showAdc(); else hideAdc();
  if (name === 'cfg') showConfigure(); else if (name === 'run') showRun(); else if (name === 'settings') showSettings(); else redraw();
  if (!auto) history.replaceState(null, '', HASH[name] || location.pathname);
}
// Configure -> Save result "Open in Run" link
addEventListener('open-in-run', e => { tab('run'); openInRun(e.detail); });
addEventListener('goto-tab', e => tab(e.detail));   // Point cloud "More options in Radar" / Radar "Watch in Point cloud" / header "Set up..."
$('tabs').addEventListener('click', e => { const b = e.target.closest('[role=tab]'); if (b) tab(b.dataset.tab); });
// WAI-ARIA tabs: arrow keys move between tabs (and select them), Home/End jump to the ends; digits 1-N select a tab when
// focus is not in a field. There is deliberately no global Start/Stop hotkey: a stray Start spends the cascade's once-per-boot cfg.
$('tabs').addEventListener('keydown', e => {
  const bs = tabButtons(), i = bs.indexOf(document.activeElement);
  const to = e.key === 'ArrowRight' ? (i + 1) % bs.length : e.key === 'ArrowLeft' ? (i - 1 + bs.length) % bs.length : e.key === 'Home' ? 0 : e.key === 'End' ? bs.length - 1 : -1;
  if (to < 0 || i < 0) return;
  e.preventDefault(); bs[to].focus(); tab(bs[to].dataset.tab);
});
addEventListener('keydown', e => {
  if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey || !/^[1-9]$/.test(e.key)) return;
  const t = e.target, tag = t && t.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
  const b = tabButtons()[+e.key - 1]; if (b) { e.preventDefault(); tab(b.dataset.tab); }
});
const explicit = ALIAS[location.hash];
if (explicit) tab(explicit);
else tab('run', true);   // landing: Radar, unless a session turns out to be live (below)

if (location.hash === '#3d') $('viewSeg').children[1].click();  // link straight to the 3D view
initSource();
initAdc();
initSession().then(() => {   // landing rule: Point cloud when a session is live, else Radar (never overrides a tab the user chose)
  if (!explicit && !navigated) { const k = sessView().kind; if (k === 'board' && boardLive() || k === 'replay') tab('live', true); }
});
connect();
redraw();
