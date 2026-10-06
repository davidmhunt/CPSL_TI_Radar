// Configure tab: targets (or a loaded cfg) -> live metrics + constraint check -> save cfg + system JSON.
import { $ } from './state.js';

const C = { mode: 'targets', base: '', seed: null, fw: [], source: 'targets', text: '', name: '', loadedName: '', metrics: null, ok: true, seq: 0, timer: null, ready: false };
const TARGETS = ['max_range_m', 'max_velocity_ms', 'range_res_m', 'velocity_res_ms', 'frame_rate_hz',
  'num_samples', 'num_loops', 'tx_mask', 'rx_mask', 'cfar_range_db', 'cfar_doppler_db'];

async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  let j = null; try { j = await r.json(); } catch { /* not json */ }
  return { ok: r.ok, status: r.status, j };
}
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (v, d = 2) => v == null || !isFinite(v) ? '–' : (+v).toFixed(d);

function targets() {
  const t = {};
  for (const k of TARGETS) { const v = $('t_' + k).value; if (v !== '') t[k] = +v; }
  return t;
}

function setSource(kind, name) {
  C.source = kind; C.loadedName = name || '';
  $('cSource').textContent = kind === 'cfg' ? `Analysing loaded cfg: ${name}. Editing a target switches back to generating.` : '';
  $('cToTargets').disabled = kind !== 'cfg';
}


// ---------- direct chirp-parameter mode (gui-11) ----------
// [key, label, unit, group, kind]; kind: p = profiles[0].<key>, t = top-level number, m = chirp_tx_masks list.
const PF = [
  ['start_ghz', 'Start frequency', 'GHz', 'Profile (chirp)', 'p'], ['slope_mhz_us', 'Chirp slope', 'MHz/us', 'Profile (chirp)', 'p'],
  ['idle_us', 'Idle time', 'us', 'Profile (chirp)', 'p'], ['adc_start_us', 'ADC start time', 'us', 'Profile (chirp)', 'p'],
  ['ramp_us', 'Ramp end time', 'us', 'Profile (chirp)', 'p'], ['tx_start_us', 'TX start time', 'us', 'Profile (chirp)', 'p'],
  ['num_samples', 'ADC samples', '', 'Profile (chirp)', 'p'], ['sample_rate_ksps', 'Sample rate', 'ksps', 'Profile (chirp)', 'p'],
  ['rx_gain_db', 'RX gain', 'dB', 'Profile (chirp)', 'p'], ['hpf1', 'HPF1 corner (code)', '', 'Profile (chirp)', 'p'],
  ['hpf2', 'HPF2 corner (code)', '', 'Profile (chirp)', 'p'],
  ['rx_mask', 'RX mask', 'bitmask', 'Antennas', 't'], ['tx_mask', 'TX mask', 'bitmask', 'Antennas', 't'],
  ['rx_mask2', 'RX mask (chip 2)', 'bitmask', 'Antennas', 't'], ['tx_mask2', 'TX mask (chip 2)', 'bitmask', 'Antennas', 't'],
  ['chirp_tx_masks', 'TX mask per chirp', 'comma list', 'Antennas', 'm'],
  ['n_loops', 'Loops (chirp sets/frame)', '', 'Frame', 't'], ['frame_period_ms', 'Frame period', 'ms', 'Frame', 't'],
  ['frames', 'Frames (0 = forever)', '', 'Frame', 't'],
];
// derived: [key, label, unit, group it is shown under, decimals]
const DV = [
  ['center_ghz', 'Centre frequency', 'GHz', 'Profile (chirp)', 3], ['bandwidth_mhz', 'Bandwidth (sampled)', 'MHz', 'Profile (chirp)', 1],
  ['sweep_mhz', 'Sweep (full ramp)', 'MHz', 'Profile (chirp)', 1], ['sampling_us', 'Sampling window', 'us', 'Profile (chirp)', 2],
  ['adc_end_us', 'ADC end', 'us', 'Profile (chirp)', 2], ['chirp_us', 'Chirp time (idle + ramp)', 'us', 'Profile (chirp)', 2],
  ['frame_rate_hz', 'Frame rate', 'Hz', 'Frame', 2],
];
// Which input an issue code points at.
const ISSUE_FIELDS = {
  slope: ['slope_mhz_us'], idle: ['idle_us'], sample_rate: ['sample_rate_ksps'], sample_rate_low: ['sample_rate_ksps'],
  sample_rate_untested: ['sample_rate_ksps'], samples: ['num_samples'], adc_buffer: ['num_samples'], radar_cube: ['num_samples', 'n_loops'],
  chirps: ['n_loops', 'chirp_tx_masks'], loops: ['n_loops'], frame_period: ['frame_period_ms', 'n_loops'], frame_too_short: ['frame_period_ms', 'n_loops'],
  sampling_outside_ramp: ['adc_start_us', 'ramp_us', 'num_samples', 'sample_rate_ksps'], band: ['start_ghz', 'slope_mhz_us', 'ramp_us'],
  band_edge: ['start_ghz', 'slope_mhz_us', 'ramp_us'], too_many_rx: ['rx_mask'], too_many_tx: ['tx_mask', 'chirp_tx_masks'],
  lvds_rate: ['sample_rate_ksps', 'rx_mask'], dca_rate: ['sample_rate_ksps', 'rx_mask'], dca_rate_high: ['sample_rate_ksps', 'rx_mask'],
  duty: ['frame_period_ms'], channel_cfg_layout: ['rx_mask', 'tx_mask'], frame_cfg_layout: ['n_loops'],
};
const pid = k => 'p_' + k;

function buildParams() {
  const box = $('pFields'); box.replaceChildren();
  let grp = null, grid = null;
  const group = g => { box.append(el('div', 'pgroup', esc(g))); grid = el('div', 'grid2'); box.append(grid); };
  for (const g of ['Profile (chirp)', 'Antennas', 'Frame']) {
    group(g);
    for (const [k, label, unit, gr, kind] of PF.filter(f => f[3] === g)) {
      const lab = el('label', '', `${esc(label)} <span class="unit">${esc(unit)}</span>`); lab.id = 'pl_' + k;
      const inp = el('input'); inp.id = pid(k); inp.type = kind === 'm' ? 'text' : 'number'; if (kind !== 'm') inp.step = 'any';
      inp.addEventListener('input', () => { if (C.mode === 'direct') schedule(); });
      lab.append(inp); grid.append(lab);
    }
    const dg = el('div', 'dgrid');
    for (const [k, label, unit, gr] of DV.filter(d => d[3] === g)) dg.append(el('div', 'dv', `<span>${esc(label)}</span><b id="d_${k}">–</b> <small>${esc(unit)}</small>`));
    box.append(dg);
  }
}
const lval = k => $(pid(k)).value.trim();
function fillParams(p) {   // p: a params dict from the endpoint -> inputs + derived
  const pr = (p.profiles && p.profiles[0]) || {};
  for (const [k, , , , kind] of PF) {
    const v = kind === 'p' ? pr[k] : p[k], lab = $('pl_' + k);
    lab.hidden = v == null;
    $(pid(k)).value = v == null ? '' : kind === 'm' ? v.join(', ') : +(+v).toPrecision(8);
  }
  C.seed = JSON.parse(JSON.stringify(p));
  showDerived(p.derived);
}
function showDerived(d) {
  for (const [k, , , , dec] of DV) $('d_' + k).textContent = d && d[k] != null ? fmt(d[k], dec) : '–';
}
// Only the fields the user changed from the seed are sent, so untouched cfg lines stay byte-identical.
function collectParams() {
  const prof = {}, out = {}, sd = C.seed || {}, sp = (sd.profiles && sd.profiles[0]) || {};
  for (const [k, , , , kind] of PF) {
    const raw = lval(k); if (raw === '' || $('pl_' + k).hidden) continue;
    if (kind === 'm') { const arr = raw.split(/[ ,]+/).filter(Boolean).map(Number); if (JSON.stringify(arr) !== JSON.stringify(sd[k])) out[k] = arr; continue; }
    const v = +raw, old = kind === 'p' ? sp[k] : sd[k];
    if (old != null && Math.abs(+(+old).toPrecision(8) - v) < 1e-12) continue;
    if (kind === 'p') prof[k] = v; else out[k] = v;
  }
  if (Object.keys(prof).length) out.profiles = [prof];
  return out;
}
function markFields(issues) {
  for (const l of document.querySelectorAll('#pFields label')) l.classList.remove('err', 'warn');
  for (const i of issues || []) for (const k of ISSUE_FIELDS[i.code] || []) {
    const l = $('pl_' + k); if (!l || l.classList.contains('err')) continue;
    if (i.level === 'error') { l.classList.remove('warn'); l.classList.add('err'); } else if (i.level === 'warning') l.classList.add('warn');
  }
}
async function seedDirect() {   // last generated/loaded cfg -> inputs (endpoint with params {})
  C.base = C.text;
  const { ok, j } = await api('/api/cfg/params', { board: $('cBoard').value, firmware: $('cFw').value, base_cfg_text: C.base, params: {} });
  if (!ok || !j.params) { render(ok ? j : { ok: false, issues: [{ level: 'error', code: 'api', message: 'seeding failed' }], text: C.text }); return; }
  fillParams(j.params); applyDirect(j);
}
function applyDirect(j) {
  C.text = j.text; C.metrics = j.metrics; C.ok = j.ok; render(j); markFields(j.issues);
  if (j.params) showDerived(j.params.derived);
}
async function analyzeDirect(seq) {
  const { ok, j } = await api('/api/cfg/params', { board: $('cBoard').value, firmware: $('cFw').value, base_cfg_text: C.base, params: collectParams() });
  if (seq !== C.seq) return;
  if (!ok) { render({ ok: false, metrics: null, issues: [{ level: 'error', code: 'api', message: JSON.stringify(j && j.detail || j), confidence: '' }], text: C.text }); return; }
  applyDirect(j);
}
async function setMode(m) {
  if (m === C.mode) return;
  if (m === 'direct') {
    C.mode = m; modeUi(); await seedDirect();
  } else {
    C.mode = m; modeUi(); markFields([]);
    const mt = C.metrics;   // direct -> targets: seed the target fields from the achieved numbers
    if (mt) {
      const set = (k, v) => { $('t_' + k).value = v == null ? '' : +(+v).toPrecision(4); };
      set('max_range_m', mt.max_range_m); set('max_velocity_ms', mt.max_velocity_ms); set('frame_rate_hz', mt.frame_rate_hz);
      set('range_res_m', ''); set('velocity_res_ms', ''); set('num_samples', mt.num_samples); set('num_loops', mt.n_loops);
    }
    setSource('cfg', C.loadedName || 'chirp parameters'); schedule();   // analyse the current text until a target is edited
  }
}
function modeUi() {
  for (const b of document.querySelectorAll('#cInMode button')) b.classList.toggle('on', b.dataset.m === C.mode);
  $('targetsCard').hidden = C.mode !== 'targets'; $('paramsCard').hidden = C.mode !== 'direct';
  $('pNote').textContent = C.mode === 'direct' ? 'edits apply to the seeded cfg' : '';
}

// ---------- analysis ----------
function schedule() { clearTimeout(C.timer); C.timer = setTimeout(analyze, 200); }
async function analyze() {
  const seq = ++C.seq, board = $('cBoard').value;
  if (C.mode === 'direct') return analyzeDirect(seq);
  const body = C.source === 'cfg' ? { board, firmware: $('cFw').value, cfg_text: C.text } : { board, firmware: $('cFw').value, targets: targets() };
  const { ok, j } = await api('/api/cfg/analyze', body);
  if (seq !== C.seq) return;   // a newer request is in flight
  if (!ok) { render({ ok: false, metrics: null, issues: [{ level: 'error', code: 'api', message: JSON.stringify(j && j.detail || j), confidence: '' }], text: C.text }); return; }
  C.text = j.text; C.name = j.name || C.name; C.metrics = j.metrics; C.ok = j.ok;
  render(j);
}

function tile(label, value, unit, sub, big) {
  const t = el('div', 'tile' + (big ? ' big' : ''));
  t.innerHTML = `<span>${label}</span><b>${value}</b> <small style="display:inline">${unit || ''}</small>` + (sub ? `<small>${sub}</small>` : '');
  return t;
}
function render(j) {
  const m = j.metrics, tiles = $('tiles'); tiles.replaceChildren();
  if (m) {
    const want = j.targets || {}, a = j.achieved || {};
    tiles.append(
      tile('Range resolution', fmt(m.range_res_m * 100, 1), 'cm', want.range_res_m ? `asked ${fmt(want.range_res_m * 100, 1)} cm` : '', true),
      tile('Velocity resolution', fmt(m.velocity_res_ms, 3), 'm/s', want.velocity_res_ms ? `asked ${fmt(want.velocity_res_ms, 3)}` : '', true),
      tile('Angular resolution', fmt(m.azimuth_res_deg, 1), 'deg', `${m.n_az_virtual} az virtual ch.`, true),
      tile('Max range', fmt(m.max_range_m, 1), 'm', want.max_range_m ? `asked ${fmt(want.max_range_m, 1)} m` : ''),
      tile('Max velocity', fmt(m.max_velocity_ms, 2), 'm/s', want.max_velocity_ms ? `asked ${fmt(want.max_velocity_ms, 2)}` : ''),
      tile('Frame rate', fmt(m.frame_rate_hz, 1), 'Hz', `${fmt(m.frame_period_ms, 1)} ms period`),
      tile('Bandwidth', fmt(m.bandwidth_mhz, 0), 'MHz', `slope ${fmt(m.slope_mhz_us, 2)} MHz/us`),
      tile('Samples x chirps', `${m.num_samples} x ${m.n_chirps}`, '', `${m.n_tx} TX, ${m.n_rx} RX (${m.mode})`),
      tile('Duty cycle', fmt(m.duty_cycle * 100, 0), '%', `${fmt(m.avg_data_rate_mbps, 0)} Mbps avg ADC`),
    );
  } else tiles.append(el('div', 'muted', 'No metrics (see the issues).'));
  const issues = j.issues || [], ne = issues.filter(i => i.level === 'error').length, nw = issues.filter(i => i.level === 'warning').length;
  const v = $('cVerdict');
  v.className = 'badge ' + (ne ? 'bad' : nw ? 'warn' : 'ok');
  v.textContent = ne ? `${ne} error${ne > 1 ? 's' : ''}` : nw ? `fits, ${nw} warning${nw > 1 ? 's' : ''}` : 'fits the board';
  $('cCounts').textContent = `${ne} error, ${nw} warning, ${issues.length - ne - nw} info`;
  const ul = $('issues'); ul.replaceChildren();
  if (!issues.length) ul.append(el('li', 'info', '<span class="lv">ok</span>No constraint violations found.'));
  const order = { error: 0, warning: 1, info: 2 };
  for (const i of [...issues].sort((x, y) => order[x.level] - order[y.level])) {
    const li = el('li', i.level);
    if (i.source) li.title = 'source: ' + i.source;
    li.innerHTML = `<span class="lv">${esc(i.level)}</span>${esc(i.message)}` +
      (i.confidence ? `<span class="conf ${esc(i.confidence)}">${i.confidence === 'unverified' ? 'unverified limit' : esc(i.confidence)}</span>` : '') +
      `<span class="code">${esc(i.code)}</span>`;
    ul.append(li);
  }
  $('cText').textContent = j.text || '';
  if (!$('sName').dataset.touched && j.name) $('sName').value = j.name.replace(/\.cfg$/, '');
}

// ---------- boards, firmware, loading ----------
// Firmware offered for a board come from the descriptors (GET /api/cfg/firmware); the default is listed first.
async function loadFirmware(board, want) {
  const { j } = await api('/api/cfg/firmware?board=' + encodeURIComponent(board));
  C.fw = (j && j.firmware || []).filter(f => !f.pending);   // pending stubs are not offered
  $('cFw').replaceChildren(...C.fw.map(f => new Option(f.id + (f.default ? ' (default)' : ''), f.id)));
  const pick = C.fw.find(f => f.id === want) || C.fw[0];
  if (pick) $('cFw').value = pick.id;
  showFirmware();
}
function showFirmware() {
  const f = C.fw.find(x => x.id === $('cFw').value);
  if (!f) { $('cOutputs').textContent = ''; return; }
  const o = [f.outputs.tlv && 'TLV point cloud (serial)', f.outputs.lvds && 'raw ADC (LVDS \u2192 DCA1000)'].filter(Boolean);
  $('cOutputs').textContent = 'Outputs: ' + o.join(' / ') + ' \u2014 ' + f.description;
  $('sSerial').checked = f.system_enables.serial; $('sDca').checked = f.system_enables.dca1000;
  dcaVis();
}
// Best firmware for a loaded cfg's flavour among the board's list (falls back to the default).
function inferFirmware(text) {
  const demo = /^\s*(guiMonitor|cfarCfg)\b/m.test(text);
  const lv = /^\s*lvdsStreamCfg\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/m.exec(text);
  const lvds = demo && lv && (lv[3] !== '0' || lv[4] === '1');
  const f = C.fw.find(f => demo ? (f.outputs.tlv && f.outputs.lvds === !!lvds) : !f.outputs.tlv);
  return f ? f.id : null;
}
function dcaVis() { $('dcaFields').style.opacity = $('sDca').checked ? 1 : .4; }

async function loadList(select) {
  const { j } = await api('/api/cfgs');
  const keep = $('cLoad').value;
  $('cLoad').replaceChildren(new Option('(choose a shipped or saved cfg)', ''));
  for (const grp of ['shipped', 'user']) {
    const og = document.createElement('optgroup'); og.label = grp === 'user' ? 'Saved (user)' : 'Shipped (read-only)';
    for (const c of j.cfgs.filter(c => c.group === grp)) { const o = new Option(c.name, c.id); o.dataset.board = c.board; og.append(o); }
    $('cLoad').append(og);
  }
  if (select) $('cLoad').value = select; else $('cLoad').value = keep;
}

async function onLoad() {
  const id = $('cLoad').value; if (!id) return;
  const { ok, j } = await api('/api/cfg/file?id=' + encodeURIComponent(id));
  if (!ok) return;
  $('cBoard').value = j.board; C.text = j.text; setSource('cfg', j.name);
  await loadFirmware(j.board); const fw = inferFirmware(j.text); if (fw) { $('cFw').value = fw; showFirmware(); }
  $('sName').dataset.touched = ''; $('sName').value = j.name.split('/').pop().replace(/\.cfg$/, '') + '_copy';
  if (C.mode === 'direct') seedDirect(); else analyze();
}
function toTargets() {
  const m = C.metrics; if (!m) return;
  const set = (k, v) => { $('t_' + k).value = v == null ? '' : +(+v).toPrecision(4); };
  set('max_range_m', m.max_range_m); set('max_velocity_ms', m.max_velocity_ms); set('frame_rate_hz', m.frame_rate_hz);
  set('range_res_m', ''); set('velocity_res_ms', ''); set('num_samples', m.num_samples); set('num_loops', m.n_loops);
  setSource('targets'); schedule();
}

// ---------- save ----------
async function save() {
  const msg = $('sMsg'); msg.className = 'muted'; msg.textContent = 'Saving...';
  const body = {
    board: $('cBoard').value, firmware: $('cFw').value, name: $('sName').value.trim(), cfg_text: C.text, force: $('sForce').checked,
    cli_port: $('sCli').value, data_port: $('sData').value, serial_enabled: $('sSerial').checked,
    dca1000_enabled: $('sDca').checked, fpga_ip: $('sFpga').value, host_ip: $('sHost').value,
    cmd_port: +$('sCmd').value, data_udp_port: +$('sUdp').value,
    save_adc_frames: $('sAdc').checked, save_raw_lvds: $('sLvds').checked, log_level: 'info',
  };
  const { ok, j } = await api('/api/cfg/save', body);
  if (!ok) {
    const d = j && j.detail; msg.className = 'bad';
    msg.textContent = typeof d === 'string' ? d : d && d.message ? d.message : Array.isArray(d) ? d.map(x => x.msg).join('; ') : 'save failed';
    return;
  }
  msg.className = 'ok';
  msg.innerHTML = `Saved<br>${esc(j.cfg_path)}<br>${esc(j.json_path)}<br><span class="muted">check: ${esc(j.validate_cmd)}</span>`;
  loadList();
}

// ---------- init ----------
async function init() {
  const { j } = await api('/api/cfg/boards');
  for (const b of j.boards) $('cBoard').append(new Option(b, b));
  $('cBoard').value = 'IWR1843';
  await loadFirmware('IWR1843');
  await loadList();
  for (const k of TARGETS) $('t_' + k).addEventListener('input', () => { setSource('targets'); schedule(); });
  $('cFw').addEventListener('change', () => { showFirmware(); if (C.source === 'targets' || C.mode === 'direct') schedule(); else analyze(); });
  $('cBoard').addEventListener('change', async () => { await loadFirmware($('cBoard').value, $('cFw').value); if (C.source === 'targets' || C.mode === 'direct') schedule(); else analyze(); });
  $('cLoad').addEventListener('change', onLoad);
  $('cToTargets').onclick = toTargets;
  buildParams();
  for (const b of document.querySelectorAll('#cInMode button')) b.onclick = () => setMode(b.dataset.m);
  $('sSave').onclick = save;
  $('sName').addEventListener('input', () => { $('sName').dataset.touched = '1'; });
  $('sDca').addEventListener('change', dcaVis);
  dcaVis(); analyze();
}
export function showConfigure() { if (!C.ready) { C.ready = true; init(); } }
