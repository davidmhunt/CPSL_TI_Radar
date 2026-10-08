// Radar tab (gui-05, gui-37): the backend session. Pick a saved system JSON (plus overrides) or a quick setup, validate,
// start/stop the C++ driver, watch stats + log. The setup is the one shared with the Point cloud tab and the header bar
// (session.js `spec`). Backend: /api/driver/* (see radar_gui/README.md); live updates arrive as driver_state / driver_stats /
// driver_log messages on the shared /stream WebSocket (routed here by main.js).
import { $ } from './state.js';
import { mountCliPanel } from './cli_panel.js';
import { api, fwVerdictView, refusal, detailText, D, caps, hasSetup, boardInfo, cfgsFor, spec, specChanged, specReady, onceBoard, skipEffective, skipSupported,
  cfgSentHere, specBoard, savedCfg, loadData, fill, splitBy, FLAGS, flagGate, flagEff, ownFlag, recDiff, startSession, stopSession, registerExtras, onSession, boardLive, SS } from './session.js';

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const LOG_MAX = 500;
let cliPanel = null;   // mounted on first showRun (needs the DOM)
const R = { ready: false, state: 'idle', st: null, log: [], stats: {}, validated: null, wantPath: null, expectHz: null, cfgKey: null };

function msg(text, cls) {
  const m = $('rMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad');
}

// ---------- the setup form (reads and writes the shared `spec`) ----------
const cfgPath = () => spec.mode === 'quick' && hasSetup() ? 'quick:' + spec.board + ':' + spec.cfg_id : spec.config;
function renderSetup() {
  const quick = spec.mode === 'quick' && hasSetup();
  $('rMode').hidden = !hasSetup();
  [...$('rMode').children].forEach(b => b.classList.toggle('on', b.dataset.m === (quick ? 'quick' : 'saved')));
  $('rSavedBox').hidden = quick; $('rQuickBox').hidden = !quick;
  fill($('rCfg'), D.configs.length ? splitBy(D.configs, 'group', [['user', 'Saved from Configure (config/user)'], ['system', 'Shipped (config/system)']])
    .map(([l, xs]) => [l, xs.map(c => [c.path, c.name + (c.board ? `  [${c.board}]` : '')])]) : [[null, [['', '(no system JSONs found)']]]], spec.config);
  if (quick || (D.boards.length && hasSetup())) {
    const b = boardInfo(spec.board) || {}, fws = b.firmwares || [], fw = fws.find(f => f.id === spec.firmware) || {};
    fill($('rBoard'), [[null, D.boards.map(x => [x.board, x.board])]], spec.board);
    fill($('rFw'), [[null, fws.map(f => [f.id, f.id + (f.pending ? ' (pending)' : ''), !!f.pending])]], spec.firmware);
    $('rFwInfo').textContent = fw.id ? `${fw.description || ''}${fw.description ? ' ' : ''}Outputs: ${[fw.tlv && 'TLV point cloud', fw.lvds && 'LVDS raw ADC'].filter(Boolean).join(' + ') || 'none'}.` : '';
    const cf = cfgsFor(spec.board), grp = splitBy(cf, 'group', [['user', 'Saved from Configure'], ['shipped', 'Shipped']]);
    fill($('rQCfg'), cf.length ? grp.map(([l, xs]) => [l, xs.map(c => [c.id, c.name])]) : [[null, [['', '(no cfgs for this board)']]]], spec.cfg_id);
    for (const [id, k, ph] of [['rQCli', 'cli_port', b.cli_port], ['rQData', 'data_port', b.data_port]]) {
      const e = $(id); if (e.value !== spec[k]) e.value = spec[k]; e.placeholder = ph || '';
    }
    $('rQDcaRow').hidden = !fw.lvds; $('rQDca').checked = spec.dca1000 != null ? !!spec.dca1000 : !!fw.dca1000;
  }
  // recording: each box starts from the selected config's own value; a flag the config/hardware/driver cannot honour is disabled
  $('rRecBox').hidden = !hasSetup();
  for (const [id, [k, ovk]] of [['rSaveAdc', FLAGS[0]], ['rSaveLvds', FLAGS[1]], ['rSaveSer', FLAGS[2]]]) {
    const why = flagGate(k), e = $(id);
    e.checked = flagEff(k, ovk); e.disabled = !!why || boardLive(); e.title = why; e.parentElement.classList.toggle('dis', !!why);
  }
  const hint = FLAGS.map(([k]) => flagGate(k)).filter(Boolean);
  $('rRecNote').textContent = (!caps().save_serial_bytes ? 'Save serial bytes needs a newer driver build (it is greyed out until the driver has it). ' : '') +
    (!quick && savedCfg() && savedCfg().dca === false ? 'This config has no DCA1000 stream, so ADC/LVDS saving is unavailable. ' : '') +
    (recDiff().length ? 'This start will record: ' + recDiff().join(', ') + '.' : '');
  $('rSaveCfg').hidden = quick; $('rSaveCfg').disabled = boardLive() || !spec.config;
  $('rSaveCfg').textContent = savedCfg() && savedCfg().group === 'user' ? 'Save to config' : 'Save as copy in config/user/';
  // skip cfg: only once-per-boot boards; defaulted on only after this GUI configured the board
  const once = onceBoard(), can = skipSupported(), sent = cfgSentHere(specBoard());
  $('rSkipRow').hidden = !once; $('rSkip').checked = skipEffective() && can; $('rSkip').disabled = !can;
  $('rSkipRow').lastElementChild.textContent = !can ? 'Skip cfg unavailable: rebuild the driver (it has no --skip-configure)'
    : sent ? 'Restart without sending the cfg: this GUI already configured the board. Untick after a power-cycle.' : 'Already configured this power-up (skip cfg)';
  $('rFwChkRow').hidden = !caps().firmware_check; $('rFwChk').value = spec.fw_check;
  $('rValidate').hidden = quick;
  const key = cfgPath();
  if (key !== R.cfgKey) { R.cfgKey = key; cfgChanged(); }
  const c = savedCfg();
  $('rCfgInfo').textContent = !quick && c ? c.path : '';
  renderFwMark(!quick && c);
  renderState();
}
// gui-04: a system JSON without the mandatory "firmware" key is marked (firmware === null; undefined = an older backend, no mark).
// A config/user file gets an Add firmware button: pick from the board's list (the migration tool's inference preselected).
let fwPickFor = null;
async function renderFwMark(c) {
  const miss = !!c && c.firmware === null, user = miss && c.group === 'user';
  $('rFwMark').hidden = !miss;
  if (!miss) { fwPickFor = null; return; }
  $('rFwMarkText').textContent = user ? 'This config needs a firmware: the driver will require one. Choose it and add it (the old file is kept as .bak). '
    : 'needs firmware \u2014 re-save in Configure or run the migration tool (uv run tools/migrate_config_v1_to_v2.py --add-firmware --in-place <file>). ';
  $('rFwAdd').hidden = !user;
  if (!user || fwPickFor === c.path) return;
  fwPickFor = c.path;
  const { ok, j } = await api('/api/cfg/firmware?board=' + encodeURIComponent(c.board || ''));
  if (fwPickFor !== c.path) return;
  // SAR on a plain IWR1843 is refused by the server, so it is not offered
  const ids = ok && j && j.firmware ? j.firmware.filter(f => !f.driver_board || f.driver_board === c.board).map(f => f.id) : [];
  fill($('rFwPick'), [[null, ids.map(i => [i, i])]], c.firmware_hint && ids.includes(c.firmware_hint) ? c.firmware_hint : ids[0] || '');
  $('rFwAddBtn').disabled = !ids.length || boardLive();
}
async function addFirmware() {
  const c = savedCfg(); if (!c || c.firmware !== null || c.group !== 'user') return;
  const fw = $('rFwPick').value; if (!fw) return;
  if (!confirm(`Add "firmware": "${fw}" to config/user/${c.name}.json?\nThe previous version is kept as ${c.name}.json.bak.`)) return;
  const m = $('rSaveMsg'); m.hidden = false; m.className = 'runmsg warn'; m.textContent = 'Adding firmware...';
  const res = await api('/api/driver/configs/firmware', { config: c.path, firmware: fw });
  if (!res.ok) { m.className = 'runmsg bad'; m.textContent = res.status === 404 || res.status === 405 ? 'This GUI server is older than this page: restart the GUI to add firmware.' : detailText(res); return; }
  const v = res.j.validate || {};
  m.className = 'runmsg ' + (v.ok ? 'ok' : 'bad');
  m.textContent = `Added firmware ${res.j.firmware} to ${res.j.path} (previous version: ${res.j.backup.split('/').pop()}). Validation: ${v.ok ? 'OK' : 'INVALID'}` + (v.ok ? '' : '\n' + (v.text || '').trim());
  fwPickFor = null;
  await loadData();
  specChanged();
}
function cfgChanged() {
  R.validated = null; R.expectHz = null; $('rValCard').hidden = true; msg('');
  adcRestore();
}
export async function openInRun(path) {
  const base = path.split('/').pop();
  await loadData();
  const c = D.configs.find(c => c.path === path || c.path.split('/').pop() === base);
  if (c) { spec.mode = 'saved'; spec.config = c.path; spec.skipSet = false; specChanged(); }
}

// ---------- ADC views setting (gui-07): every frame (default) | every K | off, remembered per config ----------
const adcKey = () => 'radar_gui.adc_every:' + cfgPath();
function adcValue() { const v = $('rAdc').value; return v === 'k' ? Math.max(2, parseInt($('rAdcK').value, 10) || 2) : +v; }
function adcSave() { try { localStorage.setItem(adcKey(), String(adcValue())); } catch (e) { /* private mode */ } }
function adcShow() { $('rAdcKRow').hidden = $('rAdc').value !== 'k'; }
function adcRestore() {
  let v = 1; try { const s = localStorage.getItem(adcKey()); if (s != null) v = +s; } catch (e) { /* ignore */ }
  if (v >= 2) { $('rAdc').value = 'k'; $('rAdcK').value = v; } else $('rAdc').value = v === 0 ? '0' : '1';
  adcShow();
  const can = caps().adc_tap !== false;   // absent on an older backend: leave it enabled
  $('rAdcNote').textContent = can ? 'Raw ADC tab: live views of the DCA1000 data (needs a DCA1000 config and a driver with the ADC tap).'
    : 'ADC views unavailable: rebuild the driver (it has no --tap-adc-every).';
}
registerExtras(() => ({ frames: +$('rFrames').value || 0, duration: +$('rDur').value || 0, adc_every: adcValue() }));

// ---------- validate / start / stop ----------
async function validate() {
  if (!spec.config) return;
  msg(''); $('rValidate').disabled = true; $('rValidate').textContent = 'Validating...';
  const res = await api('/api/driver/validate', { config: spec.config });
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
  msg(''); buttons();
  const res = await startSession();
  if (!res.ok) { msg(res.text); buttons(); }
}
// Any start (this tab, the Point cloud tab or the header) lands here: a new run drops the previous run's log and stats.
async function started(st) {
  adcSave();
  R.log = []; R.stats = {}; renderLog(); renderStreams();
  applyStatus(st);
  if (!R.validated && spec.mode !== 'quick' && spec.config) { const v = await api('/api/driver/validate', { config: spec.config }); if (v.ok) { showValidate(v.j); renderStreams(); } }
}
// "Save to config": write the recording flags (and the firmware check) back into the selected system JSON. A config/user file is
// overwritten after a confirm (the old one stays as <name>.json.bak); a shipped one is only ever copied into config/user/.
async function saveToConfig() {
  const c = savedCfg(); if (!c) return;
  const ov = {}; for (const [k, ovk] of FLAGS) if (!flagGate(k)) ov[ovk] = flagEff(k, ovk);
  if (caps().firmware_check && spec.fw_check !== 'auto') ov.firmware_check = spec.fw_check;
  const body = { config: c.path, overrides: ov, mode: 'inplace' };
  const set = Object.entries(ov).map(([k, v]) => `${k.replace('save_', '').replace(/_/g, ' ')}=${v ? 'on' : 'off'}`).join(', ');
  if (c.group === 'user') {
    if (!confirm(`Overwrite config/user/${c.name}.json with: ${set}?\nThe previous version is kept as ${c.name}.json.bak.`)) return;
  } else {
    const name = prompt(`${c.name}.json is a shipped config and is never overwritten.\nSave a copy with ${set} in config/user/ as (name, no .json):`, c.name + '_rec');
    if (!name) return;
    body.mode = 'copy'; body.name = name.trim();
  }
  const m = $('rSaveMsg'); m.hidden = false; m.className = 'runmsg warn'; m.textContent = 'Saving...';
  const res = await api('/api/driver/config/save', body);
  if (!res.ok) { m.className = 'runmsg bad'; m.textContent = res.status === 404 || res.status === 405 ? 'This GUI server is older than this page: restart the GUI to save configs.' : detailText(res); return; }
  const v = res.j.validate || {};
  m.className = 'runmsg ' + (v.ok ? 'ok' : 'bad');
  m.textContent = `Saved ${res.j.path}` + (res.j.backup ? ` (previous version: ${res.j.backup.split('/').pop()})` : '') + `. Validation: ${v.ok ? 'OK' : 'INVALID'}` + (v.ok ? '' : '\n' + (v.text || '').trim());
  await loadData();
  const n = D.configs.find(x => x.path === res.j.path);
  if (n) { spec.config = n.path; spec.mode = 'saved'; for (const [k] of FLAGS) spec[k] = null; specChanged(); }
}
async function stop() {
  msg(''); $('rStop').disabled = true;
  const res = await stopSession();
  if (!res.ok) { msg(res.text); buttons(); }
}

// ---------- state ----------
const DOT = { idle: '', running: 'ok', stopping: 'warn', exited: 'ok', failed: 'bad' };
function buttons() {
  const s = R.state, live = s === 'running' || s === 'stopping', quick = spec.mode === 'quick' && hasSetup();
  $('rStart').disabled = live || !specReady() || SS.busy;
  $('rStart').textContent = live ? `Stop ${SS.run ? SS.run.label : 'the session'} first` : (specReady() && onceBoard() && skipEffective() && skipSupported() ? 'Restart (skip cfg)' : 'Start');
  $('rStop').disabled = s !== 'running';
  $('rValidate').disabled = live || !spec.config || quick;
  for (const id of ['rCfg', 'rMode', 'rBoard', 'rFw', 'rQCfg', 'rQCli', 'rQData', 'rQDca', 'rSaveAdc', 'rSaveLvds', 'rSaveSer', 'rFwChk', 'rFrames', 'rDur', 'rAdc', 'rAdcK']) {
    const e = $(id); if (!e) continue;
    if (id === 'rMode') [...e.children].forEach(b => { b.disabled = live; }); else e.disabled = live;
  }
  $('rSkip').disabled = live || !skipSupported();
}
// Cheap per-tick refresh (session ticks arrive with every stats message): never rebuilds a <select>.
function renderState() {
  if (!R.ready) return;
  buttons();
  const st = R.st || {}, fw = st.firmware, c = caps();
  const notes = (st.notes || []).map(n => 'note: ' + n).join('\n');
  const vv = fwVerdictView(st.state && st.state !== 'idle' ? st.firmware_check : null), v = $('rFwVerdict');
  v.hidden = !vv; if (vv) { v.className = 'runmsg ' + vv.cls; v.textContent = vv.text; }
  // without a verdict (older driver / backend, or a start still in progress) the id line is what there is
  $('rFwLine').textContent = ((st.state && st.state !== 'idle' && fw && !vv) ? `Firmware: ${fw} \u00b7 ` + (c.firmware_check ? 'checked by the driver at start (verdict in the log)' : 'not checked (this driver build has no firmware check)') : '') +
    (notes ? '\n' + notes : '');
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
  buttons(); renderStreams(); renderState();
  $('rWatchRow').hidden = !(st.tap === 'on' && (s === 'running' || s === 'stopping'));
  if (st.config && (s === 'running' || s === 'stopping')) { const c = D.configs.find(c => c.path === st.config || (REPO_TAIL(st.config) === c.path)); if (c) $('rCfg').value = c.path; }
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
  } else if (m.type === 'driver_firmware') {
    sawRun(m.run); R.st = { ...(R.st || {}), firmware_check: m.firmware_check }; if (R.ready) renderState();
  } else if (m.type === 'driver_state') {
    const first = !seenState; seenState = true;
    const { type, ...st } = m; sawRun(st.run);
    R.state = st.state; R.st = { ...(R.st || {}), ...st };
    if (R.ready) { render(); if (first) refresh(); }
  }
}
async function refresh() { const { ok, j } = await api('/api/driver/status'); if (ok) applyStatus(j); }

export function showRun() {
  if (R.ready) { refresh(); renderSetup(); return; }
  R.ready = true; cliPanel = mountCliPanel($('rCli'));
  $('rMode').addEventListener('click', e => { const b = e.target.closest('button'); if (!b || b.disabled) return; spec.mode = b.dataset.m; spec.skipSet = false; specChanged(); });
  const on = (id, fn, resetSkip = false) => $(id).addEventListener('change', () => { fn($(id)); if (resetSkip) spec.skipSet = false; specChanged(); });
  on('rCfg', e => { spec.config = e.value; for (const [k] of FLAGS) spec[k] = null; }, true);
  on('rBoard', e => { spec.board = e.value; const b = boardInfo(e.value) || {}; spec.firmware = b.default_firmware || ''; spec.cfg_id = (cfgsFor(e.value)[0] || {}).id || ''; spec.cli_port = spec.data_port = ''; spec.dca1000 = null; for (const [k] of FLAGS) spec[k] = null; }, true);
  on('rFw', e => { spec.firmware = e.value; spec.dca1000 = null; });
  on('rQCfg', e => { spec.cfg_id = e.value; });
  on('rQCli', e => { spec.cli_port = e.value.trim(); }); on('rQData', e => { spec.data_port = e.value.trim(); });
  on('rQDca', e => { spec.dca1000 = e.checked; });
  for (const [id, [k]] of [['rSaveAdc', FLAGS[0]], ['rSaveLvds', FLAGS[1]], ['rSaveSer', FLAGS[2]]]) on(id, e => { spec[k] = e.checked; });
  $('rSaveCfg').onclick = saveToConfig;
  $('rFwAddBtn').onclick = addFirmware;
  on('rFwChk', e => { spec.fw_check = e.value; });
  $('rSkip').addEventListener('change', () => { spec.skip = $('rSkip').checked; spec.skipSet = true; specChanged(); });
  addEventListener('spec-changed', () => { if (R.ready) renderSetup(); });
  addEventListener('session-started', e => started(e.detail));
  onSession(renderState);
  $('rWatch').onclick = () => dispatchEvent(new CustomEvent('goto-tab', { detail: 'live' }));
  $('rAdc').addEventListener('change', () => { adcShow(); adcSave(); }); $('rAdcK').addEventListener('change', adcSave);
  $('rValidate').onclick = validate; $('rStart').onclick = start; $('rStop').onclick = stop;
  $('rHideStats').addEventListener('change', () => { pend.rebuild = true; schedule(); });
  renderSetup(); refresh();
}
