// One session store (gui-37): the board has one engine (the C++ driver) and one session. This module merges the driver's
// status / driver_* WebSocket messages, the Live source (/api/source) and the stream status into one view, owns the shared
// "setup" (saved config + overrides, or a quick setup) that the Radar tab and the Point cloud tab both edit, builds the
// start request, and renders the header session bar. Every field is optional: a backend without an endpoint or capability
// hides the feature (D.caps / D.boards stay empty) and nothing here throws.
import { $ } from './state.js';

// ---------- http ----------
export async function api(path, body) {
  let r;
  try { r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) }); }
  catch (e) { return { ok: false, status: 0, j: null }; }
  let j = null; try { j = await r.json(); } catch (e) { /* non-JSON error body */ }
  return { ok: r.ok, status: r.status, j };
}
export function detailText(res) {
  const d = res.j && res.j.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(x => (x.loc ? x.loc.join('.') + ': ' : '') + x.msg).join('; ');
  return res.status === 0 ? 'cannot reach the GUI server' : `request failed (HTTP ${res.status})`;
}
// Refusal wording by HTTP code: 409 busy / wrong state, 422 bad config or input, 503 no driver binary.
export function refusal(res) {
  const t = detailText(res);
  if (res.status === 409) return /ports busy|in use|already/i.test(t) ? t : 'Refused: ' + t;
  if (res.status === 422) return 'Config rejected: ' + t;
  if (res.status === 503) return 'Driver unavailable: ' + t;
  if (res.status === 404 || res.status === 405) return 'This GUI server is older than this page: restart the GUI (' + t + ')';
  return t;
}
export const baseName = p => String(p || '').split('/').pop();
export const stem = p => baseName(p).replace(/\.[^.]*$/, '');

// ---------- data the pickers share ----------
export const D = { configs: [], caps: null, boards: [], cfgs: [], files: [], loaded: false };
export async function loadData() {
  const [c, b, g, f] = await Promise.all([api('/api/driver/configs'), api('/api/driver/boards'), api('/api/cfgs'), api('/api/source/files')]);
  D.configs = (c.j && c.j.configs) || [];
  D.caps = (c.j && c.j.caps) || null;           // absent on an older backend
  let boards = b.ok && b.j && b.j.boards;
  if (!boards) boards = ((await api('/api/source/boards')).j || {}).boards || [];   // backend older than gui-37: board list only
  D.boards = boards;
  D.cfgs = (g.j && g.j.cfgs) || []; D.files = (f.j && f.j.files) || [];
  D.loaded = true;
  fixSpec(); dispatchEvent(new CustomEvent('spec-changed')); changed();
}
export const caps = () => D.caps || {};
export const hasSetup = () => !!caps().setup;
export const boardInfo = name => D.boards.find(b => b.board === name);

// <select> helpers shared by the Radar and Point cloud pickers. groups: [[label|null, [[value, text, disabled?], ...]], ...];
// a select is rebuilt only when its content changed, so an open dropdown survives the 5 Hz session ticks.
export function fill(sel, groups, value) {   // groups: [[label|null, [[value, text, disabled?], ...]], ...]
  const sig = JSON.stringify(groups) + '|' + value;
  if (sel.dataset.sig === sig) return;
  sel.dataset.sig = sig; sel.innerHTML = '';
  for (const [label, items] of groups) {
    const host = label ? Object.assign(document.createElement('optgroup'), { label }) : sel;
    for (const [v, t, dis] of items) { const o = new Option(t, v); o.disabled = !!dis; host.append(o); }
    if (label) sel.append(host);
  }
  sel.value = value;
}
export const splitBy = (items, key, labels) => labels.map(([g, label]) => [label, items.filter(x => x[key] === g)]).filter(([, xs]) => xs.length);

// ---------- the shared setup (what Start starts) ----------
const KEY = 'radar_gui.session_spec';
const DEF = { mode: 'saved', config: '', board: '', firmware: '', cfg_id: '', cli_port: '', data_port: '', dca1000: null,
  save_adc: null, save_lvds: null, save_serial: null, fw_check: 'auto', skip: false, skipSet: false, started: false };
export const spec = { ...DEF };
try { Object.assign(spec, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) { /* private mode / bad JSON */ }
for (const k of ['save_adc', 'save_lvds', 'save_serial']) spec[k] = spec[k] === true || spec[k] === 'on' ? true : spec[k] === false || spec[k] === 'off' ? false : null;   // null = as the config has it
export function saveSpec() { try { localStorage.setItem(KEY, JSON.stringify(spec)); } catch (e) { /* ignore */ } }
// Pickers call this after editing `spec`; every view re-renders from it.
export function specChanged() { saveSpec(); dispatchEvent(new CustomEvent('spec-changed')); changed(); }
function fixSpec() {
  if (!hasSetup()) spec.mode = 'saved';
  if (spec.config && D.configs.length && !D.configs.some(c => c.path === spec.config)) spec.config = '';
  if (!spec.config && D.configs.length) spec.config = (D.configs.find(c => c.group === 'user') || D.configs[0]).path;
  if (D.boards.length) {
    if (!boardInfo(spec.board)) spec.board = D.boards[0].board;
    const b = boardInfo(spec.board), fws = (b && b.firmwares) || [];
    if (fws.length && !fws.some(f => f.id === spec.firmware)) spec.firmware = b.default_firmware || fws[0].id;
    if (!cfgsFor(spec.board).some(c => c.id === spec.cfg_id)) spec.cfg_id = (cfgsFor(spec.board)[0] || {}).id || '';
  }
}
// Recording flags: a checkbox shows the config's own value until the user touches it (spec value null). A flag the hardware or
// the driver cannot honour reads as off and its box is disabled.
export const FLAGS = [['save_adc', 'save_adc_frames', 'ADC frames'], ['save_lvds', 'save_raw_lvds', 'raw LVDS'], ['save_serial', 'save_serial_bytes', 'serial bytes']];
export function ownFlag(ov) { return spec.mode === 'quick' ? false : !!(((savedCfg() || {}).saves) || {})[ov]; }
export function flagGate(k) {
  const c = savedCfg() || {}, quick = spec.mode === 'quick' && hasSetup();
  if (k === 'save_serial') return !caps().save_serial_bytes ? 'needs a newer driver build' : !quick && c.serial === false ? 'this config has no serial stream' : '';
  if (quick) { const fw = ((boardInfo(spec.board) || {}).firmwares || []).find(f => f.id === spec.firmware) || {}; const on = spec.dca1000 != null ? spec.dca1000 : fw.dca1000; return on ? '' : 'turn on the DCA1000 stream'; }
  return c.dca === false ? 'this config does not stream over the DCA1000' : '';
}
export function flagEff(k, ov) { return !flagGate(k) && (spec[k] != null ? spec[k] : ownFlag(ov)); }
export const recDiff = () => FLAGS.filter(([k, ov]) => flagEff(k, ov) !== ownFlag(ov) && flagEff(k, ov)).map(f => f[2]);
export const cfgsFor = board => D.cfgs.filter(c => c.board === board);
export function savedCfg() { return D.configs.find(c => c.path === spec.config); }
export function specBoard() { return spec.mode === 'quick' ? spec.board : (savedCfg() || {}).board || ''; }
export function specLabel() {
  if (spec.mode === 'quick') { const c = D.cfgs.find(c => c.id === spec.cfg_id); return `${spec.board} · ${c ? stem(c.name) : '?'}`; }
  const c = savedCfg(); return c ? c.name : '';
}
export const specReady = () => spec.mode === 'quick' ? !!(spec.board && spec.cfg_id) : !!spec.config;
export function onceBoard() {
  if (spec.mode === 'quick') return !!(boardInfo(spec.board) || {}).once_per_boot;
  return !!(savedCfg() || {}).once_per_boot;
}

// "This GUI process already sent the cfg to that board" (once-per-boot boards): keyed on the backend's boot id, so a
// restarted GUI or an older backend (no boot id) never claims it. A power-cycle cannot be seen: "Send cfg" is one click away.
const EVK = 'radar_gui.cfg_sent';
function sentMap() { try { return JSON.parse(localStorage.getItem(EVK) || '{}'); } catch (e) { return {}; } }
export function cfgSentHere(board) { const m = sentMap(); return !!(board && SS.boot && m[board] === SS.boot); }
function markSent(board, on) {
  if (!board || !SS.boot) return;
  const m = sentMap(); if (on) m[board] = SS.boot; else delete m[board];
  try { localStorage.setItem(EVK, JSON.stringify(m)); } catch (e) { /* ignore */ }
}
export function skipDefault() { return onceBoard() && cfgSentHere(specBoard()); }
export function skipEffective() { return onceBoard() && (spec.skipSet ? spec.skip : skipDefault()); }
export const skipSupported = () => caps().skip_configure !== false;   // absent caps (old backend): leave it available

// ---------- live session state ----------
export const SS = { drv: { state: 'idle' }, cli: [], stream: { state: '', msg: '' }, src: null, boot: null, run: null, startErr: '', busy: false, runId: null };
const listeners = new Set();
export const onSession = fn => { listeners.add(fn); return fn; };
export function changed() { renderHeader(); for (const f of listeners) { try { f(); } catch (e) { console.error(e); } } }

function mergeDrv(st) {
  const { type, cli, log, ...rest } = st;   // driver_state messages carry empty log/cli (status(log=False)); only a full status fills them
  if (rest.run != null && rest.run !== SS.runId) { SS.runId = rest.run; SS.cli = []; SS.drv = { log: [], ...rest }; }
  else SS.drv = { ...SS.drv, ...rest };
  if (Array.isArray(log) && log.length) SS.drv.log = log.slice(-60);
  if (rest.boot) SS.boot = rest.boot;
  if (Array.isArray(cli) && cli.length) { SS.cli = cli.slice(); evidence(); }
}
function evidence() {
  const b = SS.run && SS.run.board; if (!b) return;
  const bad = SS.cli.some(e => e.verdict === 'ERROR' || e.verdict === 'TIMEOUT');
  if (bad) markSent(b, false); else if (SS.cli.some(e => e.verdict === 'DONE')) markSent(b, true);
}
export function feedMessage(m) {
  if (m.type === 'driver_state') { const was = live(); mergeDrv(m); if (was && !live()) loadData(); }   // a run ended: new captures may be replayable
  else if (m.type === 'driver_cli') {
    if (m.run != null && m.run !== SS.runId) { SS.runId = m.run; SS.cli = []; }
    const k = SS.cli.findIndex(e => e.seq === m.entry.seq); if (k >= 0) SS.cli[k] = m.entry; else SS.cli.push(m.entry);
    evidence();
  } else if (m.type === 'driver_stats') SS.drv.stats = { ...(SS.drv.stats || {}), [m.stream]: m.stats };
  else if (m.type === 'status') SS.stream = { state: m.state, msg: m.msg || '' };
  else if (m.type === 'driver_log_batch') { if (m.run === SS.runId) SS.drv.log = [...(SS.drv.log || []), ...m.lines].slice(-60); return; }
  else return;
  changed();
}
export async function refreshAll() {
  const [d, s] = await Promise.all([api('/api/driver/status'), api('/api/source')]);
  if (d.ok && d.j) { mergeDrv(d.j); if (Array.isArray(d.j.cli)) SS.cli = d.j.cli.slice(); }
  if (s.ok && s.j) SS.src = s.j;
  changed();
}
export async function refreshSrc() { const s = await api('/api/source'); if (s.ok && s.j) { SS.src = s.j; changed(); } return s.j; }

const live = () => ['running', 'stopping'].includes(SS.drv.state);
export const boardLive = live;
const replayLive = () => !live() && SS.src && SS.src.kind === 'replay' && SS.stream.state === 'streaming';
const hasFrames = () => Object.values(SS.drv.stats || {}).some(s => +s.frames > 0) || SS.stream.state === 'streaming';
const badCli = () => SS.cli.find(e => e.verdict === 'ERROR' || e.verdict === 'TIMEOUT');
function sessName() {
  const d = SS.drv, label = d.label || stem(d.config) || '', b = (SS.run && SS.run.board) || '';
  return !b || label.startsWith(b) ? label : `${b} · ${label}`;
}
// {kind: none|board|replay, state, cls (dot colour), pill, desc, name, saving[], pid, canStop}
export function view() {
  const d = SS.drv, s = d.state || 'idle', name = sessName();
  const saving = Object.entries(d.saving || {}).filter(([, v]) => v).map(([k]) => k.replace(/^save_/, '').replace(/_/g, ' '));
  const v = { kind: 'none', state: 'none', cls: '', pill: 'No session', desc: '', name, saving, pid: d.pid, canStop: false, file: '' };
  if (live()) {
    v.kind = 'board'; v.canStop = s === 'running';
    const prog = SS.cli.filter(e => e.i && e.n && e.verdict !== 'SKIP').pop();
    if (s === 'stopping') { v.state = 'stopping'; v.cls = 'warn'; v.pill = `Stopping · ${name}`; }
    else if (hasFrames()) { v.state = 'running'; v.cls = 'ok'; v.pill = `${name} · pid ${d.pid}`; }
    else if (prog) { v.state = 'configuring'; v.cls = 'warn'; v.pill = `Configuring ${prog.i}/${prog.n} · ${name}`; }
    else { v.state = 'starting'; v.cls = 'warn'; v.pill = `Starting · ${name}`; }
    if (v.state === 'running' && d.tap === 'off') v.desc = 'The driver has no live tap: the point cloud is not shown.';
    if (v.state === 'configuring') v.desc = 'Sending the cfg to the board; this takes a few seconds.';
  } else if (replayLive()) {
    const f = baseName(((SS.src || {}).spec || {}).file);
    Object.assign(v, { kind: 'replay', state: 'replay', cls: 'ok', pill: `Replay · ${f}`, canStop: true, file: f });
  } else if (s === 'failed' || (s === 'exited' && d.exit_code)) {
    const ff = badCli(), fw = /wrong firmware|firmware mismatch/i.test(((d.log || []).slice(-30).join('\n')) + (d.error || ''));
    v.kind = 'board'; v.cls = 'bad';
    if (fw) { v.state = 'wrong_firmware'; v.pill = `Wrong firmware · ${name}`; v.desc = 'The board is running different firmware than this config expects: see the log.'; }
    else if (ff) { v.state = 'cfg_failed'; v.pill = `Config failed · ${name}`; v.desc = `${ff.cmd} was not answered Done.` + (d.config && /cascade/i.test(name) ? ' The cascade accepts a cfg once per power-up: power-cycle it.' : ' Power-cycle the board and Send cfg again.'); }
    else { v.state = 'died'; v.pill = `Died · ${name}`; v.desc = d.error || `driver exited with code ${d.exit_code}`; }
  } else if (s === 'exited') {
    const n = Math.max(0, ...Object.values(d.stats || {}).map(x => +x.frames || 0));
    Object.assign(v, { kind: 'board', state: 'ended', pill: `Ended · ${name}`, desc: `driver run ended (${n} frames)` });
  }
  if (SS.stream.state === 'disconnected') { v.cls = 'bad'; v.desc = SS.stream.msg || 'Lost connection to the server. Retrying\u2026'; }
  return v;
}

// ---------- start / stop ----------
export function blockedReason() {
  const v = view();
  return v.kind === 'board' && live() ? `Stop ${v.name} first` : '';
}
let extrasFn = () => ({});
export const registerExtras = fn => { extrasFn = fn; };    // run.js: frames, duration, adc_every from the Radar form
function buildBody(opts) {
  const c = caps(), body = {}, ov = {}, x = extrasFn() || {};
  if (spec.mode === 'quick' && hasSetup()) {
    const q = { board: spec.board, cfg_id: spec.cfg_id };
    if (spec.firmware) q.firmware = spec.firmware;
    if (spec.cli_port.trim()) q.cli_port = spec.cli_port.trim();
    if (spec.data_port.trim()) q.data_port = spec.data_port.trim();
    if (spec.dca1000 != null) q.dca1000 = spec.dca1000;
    for (const [k, ovk] of FLAGS) if (flagEff(k, ovk)) q[ovk] = true;
    if (c.firmware_check && spec.fw_check !== 'auto') q.firmware_check = spec.fw_check;
    body.setup = q;
  } else {
    if (!spec.config) return 'Choose a system config first';
    body.config = spec.config;
    if (hasSetup()) {
      for (const [k, ovk] of FLAGS) if (spec[k] != null && !flagGate(k) && spec[k] !== ownFlag(ovk)) ov[ovk] = spec[k];
      if (c.firmware_check && spec.fw_check !== 'auto') ov.firmware_check = spec.fw_check;
      if (Object.keys(ov).length) body.overrides = ov;
    }
  }
  const skip = opts.skip != null ? opts.skip : skipEffective();
  if (skip && onceBoard() && skipSupported()) body.skip_configure = true;
  if (x.frames) body.frames = x.frames;
  if (x.duration) body.duration = x.duration;
  if (x.adc_every != null) body.adc_every = x.adc_every;
  return body;
}
// opts.skip: true = Restart (skip cfg), false = Send cfg, undefined = the shared default. Returns {ok, text}.
export async function startSession(opts = {}) {
  const why = blockedReason(); if (why) return { ok: false, text: why };
  const body = buildBody(opts); if (typeof body === 'string') return { ok: false, text: body };
  SS.startErr = ''; SS.busy = true; changed();
  const run = { board: specBoard(), label: specLabel() };
  const res = await api('/api/driver/start', body);
  SS.busy = false;
  if (!res.ok) { SS.startErr = refusal(res); changed(); return { ok: false, text: SS.startErr }; }
  SS.run = run; SS.cli = []; SS.runId = null;
  spec.started = true; spec.skipSet = false; saveSpec();
  mergeDrv(res.j); SS.cli = (res.j.cli || []).slice();
  dispatchEvent(new CustomEvent('session-started', { detail: res.j }));
  refreshSrc(); changed();
  return { ok: true, text: '' };
}
export async function stopSession() {
  const v = view();
  const res = v.kind === 'replay' ? await api('/api/source/stop', {}) : await api('/api/driver/stop', {});
  if (!res.ok) { SS.startErr = refusal(res); changed(); return { ok: false, text: SS.startErr }; }
  SS.startErr = '';
  if (v.kind === 'replay') { SS.src = res.j; SS.stream = { state: 'ended', msg: 'Source stopped' }; }
  else mergeDrv(res.j);
  dispatchEvent(new CustomEvent('session-stopped', { detail: res.j }));
  changed(); return { ok: true, text: '' };
}

// ---------- header session bar ----------
const setText = (id, t) => { const e = $(id); if (e && e.textContent !== t) e.textContent = t; };
function renderHeader() {
  if (!$('sessPill')) return;
  const v = view(), busy = SS.busy;
  $('sessDot').className = 'dot ' + v.cls;
  setText('sessText', v.pill);
  const sv = $('sessSave');
  if (v.kind === 'board' && (v.state === 'running' || v.state === 'configuring' || v.state === 'starting')) {
    sv.hidden = false; const on = v.saving.length > 0;
    setText('sessSave', on ? '● saving' : 'not saving'); sv.className = 'badge ' + (on ? 'bad' : '');
    sv.title = on ? 'Saving: ' + v.saving.join(', ') : 'No capture files are written';
  } else if (!live() && specReady() && recDiff().length) {
    sv.hidden = false; setText('sessSave', 'will save: ' + recDiff().join(', ')); sv.className = 'badge warn'; sv.title = 'The next start records this (differs from the config\'s own settings)';
  } else sv.hidden = true;
  const desc = SS.startErr || v.desc;
  setText('sessDesc', desc); $('sessDesc').className = SS.startErr ? 'bad' : 'muted';
  const btn = $('sessBtn'), alt = $('sessAlt');
  if (v.canStop || v.state === 'configuring' || v.state === 'starting') {
    btn.textContent = 'Stop'; btn.dataset.act = 'stop'; btn.disabled = busy;
    btn.classList.remove('primary'); alt.hidden = true;
  } else if (v.state === 'stopping') {
    btn.textContent = 'Stopping…'; btn.dataset.act = 'none'; btn.disabled = true; alt.hidden = true;
  } else {
    const ready = spec.started && specReady(), once = ready && onceBoard(), skip = once && skipEffective() && skipSupported();
    btn.dataset.act = ready ? 'start' : 'setup';
    btn.textContent = !ready ? 'Set up…' : skip ? 'Restart (skip cfg)' : `Start ${specLabel()}`;
    btn.title = !ready ? 'Choose a board and cfg in the Radar tab' : skip ? `Stream ${specLabel()} without sending the cfg again (this GUI configured the board earlier)` : `Start ${specLabel()} with the Radar tab setup`;
    btn.disabled = busy; btn.classList.add('primary');
    alt.hidden = !(skip && !busy);
    alt.textContent = 'Send cfg (after a power-cycle)';
  }
}
export function initSession() {
  $('sessBtn').onclick = async () => {
    const a = $('sessBtn').dataset.act;
    if (a === 'stop') await stopSession();
    else if (a === 'setup') dispatchEvent(new CustomEvent('goto-tab', { detail: 'run' }));
    else if (a === 'start') await startSession();
  };
  $('sessAlt').onclick = () => startSession({ skip: false });
  window.__session = { D, SS, spec, changed, view };   // debugging / gui_shots (an old-backend shot patches D.caps and calls changed())
  changed();
  return loadData().then(refreshAll);
}
