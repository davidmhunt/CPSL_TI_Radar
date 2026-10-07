// Run tab (gui-05): pick a system JSON, validate, start/stop the C++ driver, watch stats + log.
// Backend: /api/driver/* (see radar_gui/README.md); live updates arrive as driver_state / driver_stats / driver_log
// messages on the shared /stream WebSocket (routed here by main.js).
import { $ } from './state.js';
import { mountCliPanel } from './cli_panel.js';

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const LOG_MAX = 500;
let cliPanel = null;   // mounted on first showRun (needs the DOM)
const R = { ready: false, configs: [], state: 'idle', st: null, log: [], stats: {}, validated: null, wantPath: null, expectHz: null };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
  let j = null; try { j = await r.json(); } catch (e) { /* non-JSON error body */ }
  return { ok: r.ok, status: r.status, j };
}
function detailText(res) {
  const d = res.j && res.j.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(x => (x.loc ? x.loc.join('.') + ': ' : '') + x.msg).join('; ');
  return `request failed (HTTP ${res.status})`;
}
// Refusal wording by HTTP code: 409 busy / wrong state, 422 bad config or input, 503 no driver binary.
function refusal(res) {
  const t = detailText(res);
  if (res.status === 409) return /ports busy|in use|already/i.test(t) ? t : 'Refused: ' + t;
  if (res.status === 422) return 'Config rejected: ' + t;
  if (res.status === 503) return 'Driver unavailable: ' + t;
  return t;
}
function msg(text, cls) {
  const m = $('rMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad');
}

// ---------- config picker ----------
const cfgPath = () => $('rCfg').value;
function curCfg() { return R.configs.find(c => c.path === cfgPath()); }
async function loadConfigs() {
  const { j } = await api('/api/driver/configs');
  R.configs = (j && j.configs) || [];
  const sel = $('rCfg'); sel.innerHTML = '';
  for (const [group, label] of [['user', 'Saved from Configure (config/user)'], ['system', 'Shipped (config/system)']]) {
    const items = R.configs.filter(c => c.group === group); if (!items.length) continue;
    const og = document.createElement('optgroup'); og.label = label;
    for (const c of items) og.append(new Option(c.name + (c.board ? `  [${c.board}]` : ''), c.path));
    sel.append(og);
  }
  if (!R.configs.length) sel.append(new Option('(no system JSONs found)', ''));
  selectWanted();
  cfgChanged();
}
function selectWanted() {
  if (!R.wantPath) return;
  const base = R.wantPath.split('/').pop();
  const c = R.configs.find(c => c.path === R.wantPath || c.path.split('/').pop() === base);
  if (c) $('rCfg').value = c.path;
  R.wantPath = null;
}
function cfgChanged() {
  R.validated = null; R.expectHz = null; $('rValCard').hidden = true; msg('');
  const c = curCfg();
  $('rCfgInfo').textContent = c ? c.path : '';
  buttons();
}
export async function openInRun(path) {
  R.wantPath = path;
  if (R.ready) { await loadConfigs(); }
}

// ---------- validate / start / stop ----------
async function validate() {
  if (!cfgPath()) return;
  msg(''); $('rValidate').disabled = true; $('rValidate').textContent = 'Validating...';
  const res = await api('/api/driver/validate', { config: cfgPath() });
  $('rValidate').textContent = 'Validate'; buttons();
  if (!res.ok) { msg(refusal(res)); return; }
  showValidate(res.j);
}
function showValidate(v) {
  R.validated = v;
  R.expectHz = v.frame && v.frame.period_ms ? 1000 / v.frame.period_ms : null;
  $('rValCard').hidden = false;
  const b = $('rValBadge'); b.textContent = v.ok ? 'OK' : 'INVALID'; b.className = 'badge ' + (v.ok ? 'ok' : 'bad');
  const parts = [];
  if (v.frame) { parts.push(`${v.frame.rx} RX x ${v.frame.samples} samples x ${v.frame.chirps} chirps, ${v.frame.period_ms} ms period (${(1000 / v.frame.period_ms).toFixed(1)} Hz)`); }
  if (v.bytes_per_frame) parts.push(`${v.bytes_per_frame.toLocaleString()} bytes/frame`);
  $('rValSummary').innerHTML = parts.map(esc).join('<br>') + (v.notes || []).map(n => `<br><span class="warnline">note: ${esc(n)}</span>`).join('');
  $('rValText').textContent = (v.text || '').trim(); $('rValDet').open = !v.ok;
}
async function start() {
  msg(''); $('rStart').disabled = true;
  const body = { config: cfgPath() };
  const f = $('rFrames').value, d = $('rDur').value;
  if (f) body.frames = +f; if (d) body.duration = +d;
  const res = await api('/api/driver/start', body);
  if (!res.ok) { msg(refusal(res)); buttons(); return; }
  R.log = []; R.stats = {}; renderLog(); renderStreams();
  applyStatus(res.j);
  if (!R.validated) { const v = await api('/api/driver/validate', { config: cfgPath() }); if (v.ok) { showValidate(v.j); renderStreams(); } }
}
async function stop() {
  msg(''); $('rStop').disabled = true;
  const res = await api('/api/driver/stop', {});
  if (!res.ok) { msg(refusal(res)); buttons(); return; }
  applyStatus(res.j);
}

// ---------- state ----------
const DOT = { idle: '', running: 'ok', stopping: 'warn', exited: 'ok', failed: 'bad' };
function buttons() {
  const s = R.state, live = s === 'running' || s === 'stopping';
  $('rStart').disabled = live || !cfgPath();
  $('rStop').disabled = s !== 'running';
  $('rValidate').disabled = live || !cfgPath();
  $('rCfg').disabled = live; $('rFrames').disabled = live; $('rDur').disabled = live;
}
// A new run id means a new driver run: drop the previous run's transcript. (Merging, not replacing, because the
// start response can arrive after the first WebSocket cli events of the same run.)
let cliRun = null;
function sawRun(r) { if (r != null && r !== cliRun) { cliRun = r; if (cliPanel) cliPanel.clear(); } }
function applyStatus(st) {
  R.st = { ...(R.st || {}), ...st };
  R.state = st.state;
  if (st.stats && Object.keys(st.stats).length) R.stats = st.stats;
  if (st.log && st.log.length) { R.log = st.log.slice(-LOG_MAX); renderLog(); }
  sawRun(st.run);
  if (cliPanel && Array.isArray(st.cli)) cliPanel.merge(st.cli);   // absent on a backend older than gui-34
  render();
}
function render() {
  const st = R.st || {}, s = R.state;
  $('rDot').className = 'dot ' + (DOT[s] || ''); $('rState').textContent = s + (st.pid && (s === 'running' || s === 'stopping') ? ` · pid ${st.pid}` : '');
  const dp = $('drvPill'); dp.style.display = s === 'idle' ? 'none' : '';
  $('drvDot').className = 'dot ' + (DOT[s] || ''); $('drvText').textContent = 'driver ' + s;
  buttons(); renderStreams();
  $('rWatchRow').hidden = !(st.tap === 'on' && (s === 'running' || s === 'stopping'));
  if (st.config && s !== 'idle') { const c = R.configs.find(c => c.path === st.config || (REPO_TAIL(st.config) === c.path)); if (c && (s === 'running' || s === 'stopping')) $('rCfg').value = c.path; }
  if (s === 'failed' || (s === 'exited' && st.exit_code)) msg((st.error || `driver exited with code ${st.exit_code}`) + (noFrames() ? ' ' + ZERO_HINT : ''));
  else if (s === 'exited' && noFrames()) msg(ZERO_HINT, 'warn');
  else if (s === 'running' || s === 'stopping' || s === 'idle') { if ($('rMsg').classList.contains('bad') && s !== 'idle') msg(''); }
  const out = $('rOutCard'), done = s === 'exited' || s === 'failed';
  out.hidden = !done;
  if (done) renderOutput(st);
}
// D2: a run that ended without a single frame says so plainly (the default log level hides the cause).
const ZERO_HINT = '0 frames received. Check the log for a command the board did not answer Done to (or re-run with log_level debug in the system JSON), and power-cycle the board.';
function noFrames() {
  const v = Object.values(R.stats || {}).map(s => +s.frames || 0);
  return !v.length || v.every(n => n === 0);
}
// D1: while a driver run is live the page header shows that run's frame count and rate, not the Live source's.
// Returns null when no run is live; tolerant of old backends (missing fields -> null).
export function driverHeader() {
  if (R.state !== 'running' && R.state !== 'stopping') return null;
  if ((R.st || {}).tap === 'on') return null;   // gui-36: the run is tapped, so the header shows the Live numbers (the run's own cloud)
  const s = (R.stats || {}).serial || (R.stats || {}).dca || Object.values(R.stats || {})[0] || {};
  return { frame: s.frames == null ? null : s.frames, rate: s.rate_hz == null ? null : s.rate_hz };
}
const REPO_TAIL = p => { const i = p.indexOf('CPSL_TI_Radar_cpp/'); return i >= 0 ? p.slice(i) : p; };

const fmtN = n => n == null ? '–' : (+n).toLocaleString();
const fmtRate = r => r == null ? '–' : r.toFixed(r >= 100 ? 0 : 1) + ' Hz';
const STREAM_FIELDS = {
  dca: [['dropped', 'dropped', true], ['kernel_drops', 'kernel drops', true], ['incomplete', 'incomplete', true]],
  serial: [['missed', 'missed', true]],
};
function renderStreams() {
  PERF.renderStreams++;
  const box = $('rStreams'), keys = Object.keys(R.stats);
  $('rStreamsNote').textContent = R.expectHz ? `expected ${R.expectHz.toFixed(1)} Hz from the config` : '';
  if (!keys.length) { box.innerHTML = '<div class="muted pad">No stats yet. Start a run to see frames, drops and rates.</div>'; return; }
  const ended = R.state === 'exited' || R.state === 'failed';   // D9: after exit the last-interval rate is ~0; show frames / run time
  box.innerHTML = keys.map(k => {
    const s = R.stats[k], fields = STREAM_FIELDS[k] || [];
    const shown = new Set(['frames', 'rate_hz', ...fields.map(f => f[0]), 'packets']);
    const bad = fields.some(f => s[f[0]] > 0);
    const avg = ended && s.t_driver > 0 && s.frames != null ? s.frames / s.t_driver : null;
    const rate = avg != null ? avg : s.rate_hz;
    const rateBad = R.expectHz && rate != null && rate < 0.9 * R.expectHz;
    const other = Object.entries(s).filter(([n, v]) => !shown.has(n) && typeof v === 'number' && v > 0 && !/^(rcvbuf|t_driver)$/.test(n))
      .map(([n, v]) => `${n}=${fmtN(v)}`).join(' · ');
    return `<div class="stream${bad ? ' bad' : ''}"><div class="sname">${esc(k === 'dca' ? 'DCA1000' : k)} <span class="badge ${bad ? 'bad' : 'ok'}">${bad ? 'drops' : 'clean'}</span></div>
      <div class="tiles2">
        <div class="tile"><span>frames</span><b>${fmtN(s.frames)}</b></div>
        <div class="tile${rateBad ? ' badt' : ''}"><span>${avg != null ? 'avg rate' : 'rate'}</span><b>${fmtRate(rate)}</b></div>
        ${fields.map(([n, label]) => `<div class="tile${s[n] > 0 ? ' badt' : ''}"><span>${esc(label)}</span><b>${fmtN(s[n])}</b></div>`).join('')}
      </div>${other ? `<div class="muted other">other counters: ${esc(other)}</div>` : ''}</div>`;
  }).join('');
}
const fmtSize = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KiB` : `${(n / 1048576).toFixed(2)} MiB`;
function renderOutput(st) {
  $('rRunDir').textContent = 'Run directory: ' + (st.run_dir || '–');
  const v = st.bin_verdict, b = $('rVerdictBadge');
  if (v) {
    const good = v.verdict === 'exact', warn = v.verdict === 'short_sigint_tail';
    b.textContent = 'adc_data.bin ' + v.verdict; b.className = 'badge ' + (good ? 'ok' : warn ? 'warn' : 'bad');
    $('rVerdict').innerHTML = `adc_data.bin: ${fmtN(v.actual_bytes)} B on disk, ${fmtN(v.expected_bytes)} B expected (bytes/frame x DCA frames)` +
      (v.short_by_bytes ? `; short by ${fmtN(v.short_by_bytes)} B (${v.short_by_frames} frames)` : '');
  } else { b.textContent = ''; b.className = 'badge'; $('rVerdict').textContent = 'No adc_data.bin verdict (no adc_data.bin written, or no DCA stats).'; }
  const files = st.files || [];
  $('rFiles').innerHTML = files.length ? '<tr><th>file</th><th>size</th></tr>' + files.map(f => `<tr><td>${esc(f.name)}</td><td>${fmtSize(f.size)} <span class="muted">(${fmtN(f.size)} B)</span></td></tr>`).join('')
    : '<tr><td class="muted">No output files from this run.</td></tr>';
}

// ---------- log ----------
// gui-09 D8: WebSocket messages only mark state dirty; the DOM is updated at most once per animation frame. The log is
// appended to (with a line cap), not rebuilt: a full rebuild happens only when the whole log is replaced or the filter flips.
export const PERF = window.__perf = { renderLog: 0, appendLog: 0, renderStreams: 0, logMs: 0, msgs: 0 };
const pend = { rebuild: false, lines: [], streams: false, raf: 0 };
function schedule() { if (!pend.raf) pend.raf = requestAnimationFrame(flush); }
function flush() {
  pend.raf = 0;
  if (pend.rebuild) renderLog(); else if (pend.lines.length) appendLog(pend.lines);
  if (pend.streams) renderStreams();
  pend.rebuild = pend.streams = false; pend.lines = [];
}
const shown = l => !($('rHideStats').checked && l.startsWith('stats v1'));
function renderLog() {
  const t0 = performance.now(), el = $('rLog');
  PERF.renderLog++; pend.rebuild = false; pend.lines = [];
  const near = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  el.textContent = R.log.filter(shown).map(l => l + '\n').join('');
  if (near) el.scrollTop = el.scrollHeight;
  PERF.logMs += performance.now() - t0;
}
function appendLog(lines) {
  const t0 = performance.now(), el = $('rLog');
  PERF.appendLog++;
  const vis = lines.filter(shown);
  if (vis.length) {
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    const frag = document.createDocumentFragment();
    for (const l of vis) frag.appendChild(document.createTextNode(l + '\n'));
    el.appendChild(frag);
    while (el.childNodes.length > LOG_MAX) el.removeChild(el.firstChild);
    if (near) el.scrollTop = el.scrollHeight;
  }
  PERF.logMs += performance.now() - t0;
}
function addLines(lines) {
  for (const l of lines) R.log.push(l);
  if (R.log.length > LOG_MAX) R.log.splice(0, R.log.length - LOG_MAX);
  if (!R.ready) return;
  if (pend.rebuild) { schedule(); return; }
  pend.lines.push(...lines); schedule();
}

// ---------- websocket ----------
let seenState = false, cliSync = null;
export function onDriverMessage(m) {
  PERF.msgs++;
  if (m.type === 'driver_log') {            // one line (backend older than gui-09 Step 4c)
    addLines([m.line]);
  } else if (m.type === 'driver_log_batch') {
    addLines(m.lines);
  } else if (m.type === 'driver_cli') {
    sawRun(m.run); if (cliPanel) cliPanel.upsert(m.entry);
    // The WebSocket queue is 8 deep and drops the oldest on a burst (a configure sends dozens of lines at once), so
    // re-read the full transcript from the status once the burst is over.
    clearTimeout(cliSync); cliSync = setTimeout(() => { if (R.ready) refresh(); }, 500);
  } else if (m.type === 'driver_stats') {
    R.stats[m.stream] = m.stats; if (R.ready) { pend.streams = true; schedule(); }
  } else if (m.type === 'driver_state') {
    const first = !seenState; seenState = true;
    const { type, ...st } = m; sawRun(st.run);
    R.state = st.state; R.st = { ...(R.st || {}), ...st };
    if (R.ready) { render(); if (first) refresh(); }
  }
}
async function refresh() { const { ok, j } = await api('/api/driver/status'); if (ok) applyStatus(j); }

export function showRun() {
  if (R.ready) { refresh(); return; }
  R.ready = true; cliPanel = mountCliPanel($('rCli'));
  $('rCfg').addEventListener('change', cfgChanged);
  $('rWatch').onclick = () => dispatchEvent(new CustomEvent('goto-tab', { detail: 'live' }));
  $('rValidate').onclick = validate; $('rStart').onclick = start; $('rStop').onclick = stop;
  $('rHideStats').addEventListener('change', () => { pend.rebuild = true; schedule(); });
  loadConfigs().then(refresh);
}
