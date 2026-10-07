// Configure tab: targets (or a loaded cfg) -> live metrics + constraint check -> save cfg + system JSON.
import { $ } from './state.js';
import { renderProfile, TX_COLORS } from './profile.js';

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
  if ($('t_lvds').dataset.touched && !$('lvdsTargets').hidden) t.lvds = $('t_lvds').checked;   // untouched = the firmware template
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
  sample_rate_untested: ['sample_rate_ksps'], sample_rate_lowpower: ['sample_rate_ksps', 'low_power'], samples: ['num_samples'], adc_buffer: ['num_samples'], radar_cube: ['num_samples', 'n_loops'],
  chirps: ['n_loops'], loops: ['n_loops'], frame_period: ['frame_period_ms', 'n_loops'], frame_too_short: ['frame_period_ms', 'n_loops'],
  sampling_outside_ramp: ['adc_start_us', 'ramp_us', 'num_samples', 'sample_rate_ksps'], band: ['start_ghz', 'slope_mhz_us', 'ramp_us'],
  band_edge: ['start_ghz', 'slope_mhz_us', 'ramp_us'], too_many_rx: ['rx_mask'], too_many_tx: ['tx_mask'],
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
    if (g === 'Profile (chirp)') {   // gui-26: lowPower 0 <0|1>; shown only when the seed has low_power
      const lab = el('label', '', 'ADC mode <span class="unit">lowPower</span>'); lab.id = 'pl_low_power';
      const sel = el('select'); sel.id = 'p_low_power'; sel.innerHTML = '<option value="0">regular</option><option value="1">low power</option>';
      sel.addEventListener('change', () => { if (C.mode === 'direct') schedule(); });
      lab.append(sel); grid.append(lab);
      { const h = el('div', 'muted lvdshint', 'ADC mode: default regular (0); low power caps the ADC rate at 9375 ksps (IWR1443/1843) or 12500 ksps (IWR6843). Over the cap is a warning, not an error.'); h.style.gridColumn = '1 / -1'; grid.append(h); }
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
  C.seed = JSON.parse(JSON.stringify(p)); C.tbl = null; C.tblDirty = false; C.tblStale = false;
  $('pl_low_power').hidden = $('pl_low_power').nextElementSibling.hidden = p.low_power == null;
  if (p.low_power != null) $('p_low_power').value = String(p.low_power);
  const lv = p.lvds_stream;
  if (lv) { $('l_subframe').value = lv.subframe; fillDataFmt(lv.data_fmt); $('l_data_fmt').value = lv.data_fmt; $('l_header').checked = !!lv.header; $('l_sw').checked = !!lv.sw; }
  lvdsVis();
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
  Object.assign(out, tableParams(sd));
  if (sd.low_power != null && +$('p_low_power').value !== sd.low_power) out.low_power = +$('p_low_power').value;
  const slv = sd.lvds_stream;
  if (slv && !$('lvdsParams').hidden) {
    const cur = { subframe: +$('l_subframe').value, data_fmt: +$('l_data_fmt').value, header: $('l_header').checked ? 1 : 0, sw: $('l_sw').checked ? 1 : 0 };
    const ch = {}; for (const k in cur) if (cur[k] !== slv[k] && !(k === 'subframe' && $('l_subframe').value === '')) ch[k] = cur[k];
    if (Object.keys(ch).length) out.lvds_stream = ch;
  }
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
  C.tblStale = false;
  C.text = j.text; C.metrics = j.metrics; C.ok = j.ok; render(j); markFields(j.issues);
  if (j.params) showDerived(j.params.derived);
}
async function analyzeDirect(seq) {
  const { ok, j } = await api('/api/cfg/params', { board: $('cBoard').value, firmware: $('cFw').value, base_cfg_text: C.base, params: collectParams() });
  if (seq !== C.seq) return;
  if (!ok) { render({ ok: false, metrics: null, issues: [{ level: 'error', code: 'api', message: JSON.stringify(j && j.detail || j), confidence: '' }], text: C.text }); return; }
  applyDirect(j);
}
// Board or firmware changed while in direct mode: the seeded cfg belongs to the old board/template, so regenerate the
// new firmware's template from the targets and re-seed every parameter field from it (gui-28).
async function reseedDirect() {
  const seq = ++C.seq;
  const { ok, j } = await api('/api/cfg/analyze', { board: $('cBoard').value, firmware: $('cFw').value, targets: targets() });
  if (seq !== C.seq) return;
  if (!ok) { render({ ok: false, metrics: null, issues: [{ level: 'error', code: 'api', message: JSON.stringify(j && j.detail || j), confidence: '' }], text: C.text }); return; }
  C.text = j.text; C.name = j.name || C.name; setSource('targets');
  await seedDirect();
}
async function setMode(m) {
  if (m === C.mode) return;
  if (m === 'direct') {
    C.mode = m; modeUi(); await seedDirect();
  } else {
    C.mode = m; modeUi(); markFields([]);
    $('t_lvds').checked = cfgLvdsOn(C.text); $('t_lvds').dataset.touched = '1';
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
  const issues = j.issues || []; C.lastIssues = issues;
  const ne = issues.filter(i => i.level === 'error').length, nw = issues.filter(i => i.level === 'warning').length;
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
  C.profM = m; drawProfile(); renderMimo(m); flagTable(); lvdsWarn();
  $('cText').textContent = j.text || '';
  if (!$('sName').dataset.touched && j.name) $('sName').value = j.name.replace(/\.cfg$/, '');
}

// Chirp-construction diagram (gui-27): pure render of the analysed metrics, laid out for the column's current width.
function drawProfile() {
  const box = $('profDiagram'), w = Math.round(box.clientWidth) || 460;
  C.profW = w;
  const r = renderProfile(C.profM, w);
  box.innerHTML = r.svg || '<div class="muted">No metrics to draw.</div>';
  $('profNote').replaceChildren(...r.notes.map(n => el('div', 'pn ' + n.level, esc(n.text))));
  $('profBadge').textContent = r.notes.some(n => n.level === 'warn') ? 'check' : '';
}
let _ro = 0;
new ResizeObserver(() => { cancelAnimationFrame(_ro); _ro = requestAnimationFrame(() => { const box = $('profDiagram'); if (C.profM && Math.abs(Math.round(box.clientWidth) - (C.profW || 0)) > 2 && box.clientWidth > 0) drawProfile(); }); }).observe(document.getElementById('profDiagram'));

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
  C.fwMimo = f.mimo; renderMimo(C.metrics);
  const noTlv = !f.outputs.tlv;   // LVDS-only firmware (SAR, dca1000_raw): no TLV output, so the serial TLV stream cannot be enabled
  $('sSerial').disabled = noTlv; $('sSerial').title = noTlv ? 'This firmware has no TLV (serial) output.' : '';
  $('sSerial').checked = f.system_enables.serial && !noTlv; $('sDca').checked = f.system_enables.dca1000;
  dcaVis(); lvdsVis();
}
// ---------- LVDS stream (cfg) group (gui-22): shown only where the firmware has an LVDS output on this board ----------
const curFw = () => C.fw.find(x => x.id === $('cFw').value);
const DATA_FMT_NAMES = { 0: 'off', 1: 'ADC data', 2: 'ADC + metadata (SAR fw)', 4: 'CP ADC + chirp quality' };
function fillDataFmt(cur) {   // HW-stream options = the dataFmt values the selected firmware accepts (gui-24); a cfg's other value stays visible
  const f = curFw(), sel = $('l_data_fmt');
  const set = (f && f.lvds_data_fmts) || [0, 1];
  const keep = cur == null ? +sel.value : +cur;
  const opt = (v, txt) => { const o = document.createElement('option'); o.value = v; o.textContent = txt; return o; };
  sel.replaceChildren(...set.map(v => opt(v, DATA_FMT_NAMES[v] || String(v))));
  if (!set.includes(keep) && !Number.isNaN(keep)) sel.append(opt(keep, keep + ' (not supported by this firmware)'));
  if (f && f.lvds_data_fmts_confidence === 'unverified') sel.title = 'Accepted values for this firmware are unverified (no source in the repo).'; else sel.removeAttribute('title');
  sel.value = String(keep);
  const h = $('lvdsFmtHint');
  if (h && !h.dataset.dflt) h.dataset.dflt = h.textContent;
  if (h && f && f.id === 'iwr1843_sar_lvds') h.textContent = 'HW stream (SAR firmware): 0 = off, 1 = ADC data, 2 = ADC + metadata, 4 = CP ADC + chirp quality. Other values are rejected by the SAR validator.';
  else if (h) h.textContent = h.dataset.dflt;
}
function lvdsVis() {
  const f = curFw(), o = f && f.outputs;
  if (o && o.lvds && $('l_data_fmt').options.length) fillDataFmt();
  $('lvdsTargets').hidden = !(o && o.tlv && o.lvds);          // raw-ADC firmwares always stream; nothing to toggle in the targets view
  $('lvdsParams').hidden = !(o && o.lvds && C.seed && C.seed.lvds_stream);
  // raw-only firmware whose template has no lvdsStreamCfg: say why the group is absent (gui-28)
  $('lvdsNote').hidden = !(f && f.id === 'dca1000_raw' && o && o.lvds && !o.tlv && C.seed && !C.seed.lvds_stream);
  lvdsWarn();
}
function cfgLvdsOn(text) {
  const lv = /^\s*lvdsStreamCfg\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/m.exec(text || '');
  return !!lv && lv[3] !== '0';
}
function lvdsWarn() {   // cfg LVDS vs DCA1000 system setting: separate settings, so say when they disagree
  const f = curFw(), w = $('sLvdsWarn'), o = f && f.outputs;
  let msg = '';
  if (o && o.tlv && o.lvds) {
    const on = cfgLvdsOn(C.text), dca = $('sDca').checked;
    if (on && !dca) msg = 'The cfg streams ADC data over LVDS but the DCA1000 stream is off: nothing will capture it.';
    else if (!on && dca) msg = 'The DCA1000 stream is on but the cfg has LVDS streaming off: the capture card will get no data.';
  }
  w.textContent = msg; w.hidden = !msg;
}
// ---------- MIMO panel (gui-16): scheme badge, loop timing diagram, derived numbers with formula + scheme ----------
const SCHEME = { tdm: 'TDM', ddma: 'DDMA' };
function schemeName(m) { return m.scheme === 'tdm' && m.bpm_enabled ? 'TDM+BPM' : (SCHEME[m.scheme] || String(m.scheme).toUpperCase()); }
function diagram(m) {
  const seq = m.chirp_sequence || [], ddma = m.scheme === 'ddma';
  if (!seq.length) return '';
  const SHOW = 12, shown = seq.slice(0, SHOW), more = seq.length > SHOW;
  const lanes = ddma ? Math.max(1, Math.min(m.n_tx || 3, 12)) : Math.max(3, ...seq.map(c => 32 - Math.clz32(c.tx_mask)));
  const W = 300, gx = 30, lh = 14, top = 14, n = shown.length + (more ? 0.6 : 0);
  const slot = (W - gx - 4) / n, rampFrac = m.chirp_us > 0 && m.ramp_us > 0 ? Math.min(1, m.ramp_us / m.chirp_us) : 0.8;
  const H = top + lanes * lh + 16;
  let g = '';
  for (let l = 0; l < lanes; l++) {
    const y = top + l * lh;
    g += `<text x="2" y="${y + 10}" style="fill:${txColor(l)}">TX${l + 1}</text><line class="lane" x1="${gx}" x2="${W - 2}" y1="${y + lh - 1}" y2="${y + lh - 1}"/>`;
    shown.forEach((c, k) => {
      const on = ddma || (c.tx_mask >> l) & 1, x = gx + k * slot;
      g += `<rect class="${on ? 'on' : 'off'}"${on ? ` style="fill:${txColor(l)}"` : ''} x="${x.toFixed(1)}" y="${y + 2}" width="${Math.max(1, slot * rampFrac - .5).toFixed(1)}" height="${lh - 5}" rx="1"/>`;
    });
  }
  shown.forEach((c, k) => { g += `<text x="${(gx + k * slot).toFixed(1)}" y="${top - 4}">${c.index + 1}</text>`; });
  if (more) g += `<text x="${gx + shown.length * slot}" y="${top + lh}">+${seq.length - SHOW}</text>`;
  const yl = top + lanes * lh + 5;   // loop bracket: one TX-cycle (TDM) or one chirp (DDMA)
  const lx = Math.min(W - 2, gx + (ddma ? 1 : Math.min(m.n_tx || shown.length, shown.length)) * slot - 1);
  g += `<path class="loop" d="M${gx} ${yl} V${yl + 3} H${lx.toFixed(1)} V${yl}"/><text class="lp" x="${gx + 3}" y="${yl + 11}">T_loop ${fmt(m.loop_period_us, 1)} \u00b5s</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="chirp loop timing">${g}</svg>`;
}
function mrow(label, value, unit, d, cls, labelNote) {
  const r = el('div', 'mrow ' + (cls || ''));
  const unv = d && d.confidence === 'unverified' ? '<span class="unv" title="unverified: not confirmed against TI documentation or hardware">\u2020 unverified</span>' : '';
  r.innerHTML = `<div class="mv"><span>${label}</span><b>${value}${unit ? ' ' + unit : ''}</b></div>` +
    (d ? `<code>${esc(labelNote || d.formula)}</code><span class="sch">${esc(d.scheme)}</span>${unv}` : '');
  return r;
}
// The one "is MIMO editable" helper: reads the descriptor's mimo block (backend-derived `editable`/`editable_reason`);
// no descriptor mimo block (or none selected) falls back to read-only unless the analysed scheme is TDM.
function mimoEditState(m) {
  const f = curFw(), mm = (f && f.mimo) || C.fwMimo;
  if (mm && typeof mm.editable === 'boolean') return { editable: mm.editable, reason: mm.editable_reason, note: mm.editable_note || null };
  if (m && m.scheme === 'ddma') return { editable: false, reason: 'DDMA: all TX fire every chirp; phase codes are set by the firmware, not the cfg.', note: null };
  return { editable: !!(mm && mm.scheme === 'tdm'), reason: 'this firmware has no MIMO descriptor.', note: null };
}
function renderMimo(m) {
  const list = $('mDerived'); list.replaceChildren();
  const es = mimoEditState(m), ro = $('mRo');
  ro.hidden = es.editable || !(m && m.scheme); ro.textContent = es.editable ? '' : 'MIMO editing disabled \u2014 ' + (es.reason || 'not supported for this firmware.');
  const nt = $('mEditNote'); nt.hidden = !(es.editable && es.note && m && m.scheme); nt.textContent = nt.hidden ? '' : es.note;
  if (!m || !m.scheme) { $('mBadge').textContent = ''; $('mDiagram').innerHTML = ''; $('mCaption').textContent = ''; $('mNote').textContent = ''; return; }
  const ddma = m.scheme === 'ddma', D = m.derivations || {}, tc = m.chirp_us;
  C.mLast = m; C.tbl = ddma ? null : { masks: (m.chirp_sequence || []).map(c => c.tx_mask), bpm: !!m.bpm_enabled }; drawTable();
  $('mBadge').textContent = schemeName(m);
  $('mNote').textContent = ddma ? `${m.n_bands} Doppler bands, ${m.n_tx} TX` : `${m.n_tx} TX, ${m.chirps_per_loop} chirp${m.chirps_per_loop > 1 ? 's' : ''}/loop` + (m.bpm_enabled ? ', BPM on' : '');
  $('mDiagram').innerHTML = diagram(m);
  $('mCaption').textContent = ddma ? 'DDMA: every TX fires on every chirp \u2014 phase-coded, set by firmware \u2014 view only.'
    : `Tc = ${fmt(tc, 1)} \u00b5s` + (m.idle_us != null && m.ramp_us != null ? ` (idle ${fmt(m.idle_us, 1)} + ramp ${fmt(m.ramp_us, 1)})` : '') + '; bars = TX active.';
  const sub = m.subframes && m.subframes.length;
  const vmaxNote = ddma ? `${D.vmax_full_ms.formula}` : `${D.vmax_full_ms.formula}${m.n_tx > 1 ? ` = \u03bb/(4\u00b7${m.n_tx}\u00b7Tc)` : ''}`;
  const rows = [
    ['Max velocity (full span, \u00b1)', fmt(m.vmax_full_ms, 2), 'm/s', D.vmax_full_ms, 'head', vmaxNote],
    ddma && ['\u2514 per-TX band, \u00b1', fmt(m.vmax_per_tx_ms, 2), 'm/s', D.vmax_per_tx_ms, 'sec',
      `${D.vmax_per_tx_ms.formula} \u2014 limit if empty-band disambiguation fails`],
    ['Velocity resolution', fmt(m.velocity_res_ms, 3), 'm/s', D.velocity_res_ms],
    ['Loop period T_loop', fmt(m.loop_period_us, 1), '\u00b5s', D.loop_period_us],
    m.pattern_period_us !== m.loop_period_us && ['Pattern period', fmt(m.pattern_period_us, 1), '\u00b5s', D.pattern_period_us],
    ['Doppler bins', m.doppler_bins, '', D.doppler_bins],
    ['Doppler step', fmt(m.doppler_step_ms, 3), 'm/s/bin', D.doppler_step_ms],
    ['TX used', m.n_tx, '', D.n_tx],
    ['Virtual channels', m.n_virtual, '', D.n_virtual],
  ].filter(Boolean);
  for (const r of rows) list.append(mrow(...r));
  if (sub) list.append(el('div', 'muted', `advFrameCfg: ${m.subframes.length} subframes (display only).`));
}

// ---------- TDM chirp table (gui-16 step 2): one row per chirp, TX1..TX3 checkboxes, presets ----------
// C.tbl = {masks, bpm} mirrors the loop as last analysed (renderMimo) or as just edited; collectParams sends only its difference from the seed.
const TX_PRESETS = [['SIMO (1 TX)', [1], 'simo'], ['2-TX TDM', [1, 4], 'tdm2'], ['3-TX with elevation (1,4,2)', [1, 4, 2], 'tdm3'], ['BPM (2 TX)', null, 'bpm']];
const TBL_CODES = new Set(['tx_pattern_invalid', 'tx_not_in_channelcfg', 'bpm_unsupported', 'tx_order_convention', 'tx_pattern_not_periodic',
  'simo_multi_tx', 'too_many_tx', 'chirps', 'channel_cfg_layout', 'frame_cfg_layout', 'params', 'tx_mask_from_chirps', 'cascade_chirp_mask_ignored']);
const viewOnly = () => !mimoEditState(C.metrics || C.mLast).editable;
const isDdma = () => { const f = curFw(); return !!(f && f.mimo && f.mimo.scheme === 'ddma') || !!(C.metrics && C.metrics.scheme === 'ddma'); };
function tableParams(sd) {
  const t = C.tbl, out = {};
  if (!t || !C.tblDirty || isDdma() || viewOnly() || !Array.isArray(sd.chirp_tx_masks) || sd.chirp_tx_masks.some(x => typeof x !== 'number')) return out;
  const sameMasks = JSON.stringify(t.masks) === JSON.stringify(sd.chirp_tx_masks);
  if (t.bpm !== !!sd.bpm) { out.bpm = t.bpm; if (!t.bpm && !sameMasks) out.chirp_tx_masks = t.masks; }   // BPM on: the backend sets masks [5,5]
  else if (!t.bpm && !sameMasks) out.chirp_tx_masks = t.masks;
  return out;
}
async function tableEdit(masks, bpm) {
  if (isDdma() || viewOnly()) return;
  if (C.mode !== 'direct') await setMode('direct');   // editing the table = direct mode (seeds from the current cfg)
  C.tbl = { masks, bpm }; C.tblDirty = true; C.tblStale = true; drawTable(); schedule();   // tblDirty: differs from the seed (sent on); tblStale: not analysed yet (phase readout hidden)
}
// Per-TX phase readout (gui-23): one row per chirp of the loop (backend `chirp_phases`), TX columns coloured like the MIMO diagram.
const ROWS_SCROLL = 12;
const txColor = l => TX_COLORS[l % TX_COLORS.length];
function phaseTable(m) {
  const box = el('div', 'ptbl'), cp = m.chirp_phases || [], tx = m.phase_tx || [];
  const unv = m.phase_confidence === 'unverified';
  const cap = el('div', 'muted chint' + (unv ? ' unverified' : ''));
  cap.textContent = (unv ? '\u2020 UNVERIFIED (hypothesis): ' : '') + 'Phase per TX, degrees' + (m.phase_source ? ` \u2014 ${m.phase_source}` : '') + (m.phase_note ? `. ${m.phase_note}` : '');
  if (!cp.length) { box.append(el('div', 'muted chint', m.phase_note || 'No phase data for this configuration.')); return box; }
  const sc = el('div', 'pscroll' + (cp.length > ROWS_SCROLL ? ' scroll' : '')), tb = document.createElement('table');
  const hr = tb.createTHead().insertRow(); { const th0 = document.createElement('th'); th0.textContent = '#'; hr.append(th0); }
  tx.forEach(name => { const th = document.createElement('th'), l = (parseInt(String(name).replace(/\D/g, ''), 10) || 1) - 1; th.textContent = name; th.style.color = txColor(l); th.style.borderBottomColor = txColor(l); hr.append(th); });
  const body = tb.createTBody();
  for (const c of cp) {
    const r = body.insertRow(); r.insertCell().textContent = String(c.index + 1);
    (c.phase_deg || []).forEach(v => { const td = r.insertCell(); td.textContent = v == null ? '\u2014' : (Math.round(v * 1000) / 1000) + '\u00b0'; if (v == null) td.title = 'not BPM-coded'; });
  }
  sc.append(tb); box.append(sc, cap); return box;
}
function drawTable() {
  const box = $('mChirpTable'); box.replaceChildren();
  const f = curFw(), mm = (f && f.mimo) || C.fwMimo || {}, m = C.metrics || C.mLast;
  if (!m || !m.scheme) return;
  const ddma = m.scheme === 'ddma' || mm.scheme === 'ddma';
  const t = C.tbl || { masks: (m.chirp_sequence || []).map(c => c.tx_mask), bpm: !!m.bpm_enabled };
  const max = mm.max_chirps_per_loop || 16, wrap = el('div', 'ctbl' + (ddma || !mimoEditState(m).editable ? ' ro' : ''));
  wrap.append(el('div', 'pgroup', `Chirp table <span class="muted">${t.masks.length}${ddma ? '' : '/' + max} chirp${t.masks.length === 1 ? '' : 's'}/loop</span>`));
  const ro = !mimoEditState(m).editable, lock = ddma || ro || t.bpm;
  if (ddma) {
    const n = Math.max(1, Math.min(m.n_tx || 3, 12));
    wrap.append(phaseTable(m));
    wrap.append(el('div', 'muted chint', `DDMA: all ${n} TX fire on every chirp, ${m.n_bands || 8} Doppler bands. Phase shifts are set by firmware, not cfg.`));
    box.append(wrap); flagTable(); return;
  }
  const rows = el('div', 'crows' + (t.masks.length > ROWS_SCROLL ? ' scroll' : '')); wrap.append(rows);
  t.masks.forEach((mask, i) => {
    const r = el('div', 'crow' + (mask === 0 ? ' err' : '')); r.append(el('span', 'ci', String(i + 1)));
    for (let l = 0; l < 3; l++) {
      const lab = el('label', 'tx'), cb = el('input'); cb.type = 'checkbox'; cb.checked = !!((mask >> l) & 1); cb.disabled = lock;
      cb.addEventListener('change', () => { const ms = t.masks.slice(); ms[i] = (ms[i] & ~(1 << l)) | (cb.checked ? 1 << l : 0); tableEdit(ms, false); });
      lab.append(cb, document.createTextNode('TX' + (l + 1))); r.append(lab);
    }
    const btn = (txt, title, fn, dis) => { const b = el('button', 'btn mini', txt); b.title = title; b.disabled = !!dis; b.onclick = fn; return b; };
    const mv = d => () => { const ms = t.masks.slice(); [ms[i], ms[i + d]] = [ms[i + d], ms[i]]; tableEdit(ms, false); };
    r.append(btn('▲', 'move up', mv(-1), lock || i === 0), btn('▼', 'move down', mv(1), lock || i === t.masks.length - 1),
      btn('✕', 'remove chirp', () => tableEdit(t.masks.filter((_, j) => j !== i), false), lock || t.masks.length <= 1));
    rows.append(r);
  });
  if (m.chirp_phases && m.chirp_phases.length && !C.tblStale) wrap.append(phaseTable(m));   // stale only until the edit has been re-analysed
  const act = el('div', 'cacts');
  const add = el('button', 'btn mini', '+ Add chirp'); add.disabled = lock || t.masks.length >= max;
  add.title = t.masks.length >= max ? `the firmware accepts at most ${max} chirps per loop` : '';
  add.onclick = () => tableEdit([...t.masks, 2], false); act.append(add);
  if (!ro) wrap.append(act);
  const pre = el('div', 'cacts');
  for (const [label, masks, id] of TX_PRESETS) {
    if (ro || (id === 'bpm' && !mm.bpm)) continue;   // BPM only where the firmware descriptor allows it
    const b = el('button', 'btn mini', label); b.onclick = () => tableEdit(masks || [5, 5], id === 'bpm'); pre.append(b);
  }
  wrap.append(pre);
  if (t.bpm) wrap.append(el('div', 'muted chint', 'BPM: TX1+TX3 on both chirps, phase-coded +/-. Choose another preset to leave BPM.'));
  box.append(wrap); flagTable();
}
function flagTable() {   // issue codes that concern the chirp pattern flag the whole table (the issues carry no row index)
  const w = document.querySelector('#mChirpTable .ctbl'); if (!w) return;
  const bad = (C.lastIssues || []).filter(i => TBL_CODES.has(i.code));
  w.classList.toggle('err', bad.some(i => i.level === 'error')); w.classList.toggle('warn', !bad.some(i => i.level === 'error') && bad.length > 0);
  w.title = bad.map(i => i.code).join(', ');
}

// Best firmware for a loaded cfg's flavour among the board's list (falls back to the default).
function inferFirmware(text) {
  const demo = /^\s*(guiMonitor|cfarCfg)\b/m.test(text);
  const lv = /^\s*lvdsStreamCfg\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)/m.exec(text);
  const lvds = demo && lv && (lv[3] !== '0' || lv[4] === '1');
  // demo cfgs: prefer a TLV firmware whose LVDS output matches the cfg, else any TLV one
  const f = demo ? (C.fw.find(f => f.outputs.tlv && f.outputs.lvds === !!lvds) || C.fw.find(f => f.outputs.tlv))
                 : C.fw.find(f => !f.outputs.tlv);
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
  $('t_lvds').checked = cfgLvdsOn(j.text); $('t_lvds').dataset.touched = '1';   // a loaded cfg's LVDS choice survives regenerating
  await loadFirmware(j.board); const fw = inferFirmware(j.text); if (fw) { $('cFw').value = fw; showFirmware(); }
  $('sName').dataset.touched = ''; $('sName').value = j.name.split('/').pop().replace(/\.cfg$/, '') + '_copy';
  if (C.mode === 'direct') seedDirect(); else analyze();
}
function toTargets() {
  const m = C.metrics; if (!m) return;
  const set = (k, v) => { $('t_' + k).value = v == null ? '' : +(+v).toPrecision(4); };
  set('max_range_m', m.max_range_m); set('max_velocity_ms', m.max_velocity_ms); set('frame_rate_hz', m.frame_rate_hz);
  set('range_res_m', ''); set('velocity_res_ms', ''); set('num_samples', m.num_samples); set('num_loops', m.n_loops);
  $('t_lvds').checked = cfgLvdsOn(C.text); $('t_lvds').dataset.touched = '1';
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
  msg.innerHTML = `Saved<br>${esc(j.cfg_path)}<br>${esc(j.json_path)}<br>` +
    (j.warnings || []).map(w => `<span class="warnline">${esc(w)}</span><br>`).join('') + `<span class="muted">check: ${esc(j.validate_cmd)}</span><br><a href="#run" id="sOpenRun">Open in Run</a>`;
  $('sOpenRun').onclick = e => { e.preventDefault(); dispatchEvent(new CustomEvent('open-in-run', { detail: j.json_path })); };
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
  $('cFw').addEventListener('change', () => { showFirmware(); if (C.mode === 'direct') reseedDirect(); else if (C.source === 'targets') schedule(); else analyze(); });
  $('cBoard').addEventListener('change', async () => { await loadFirmware($('cBoard').value, $('cFw').value); if (C.mode === 'direct') reseedDirect(); else if (C.source === 'targets') schedule(); else analyze(); });
  $('cLoad').addEventListener('change', onLoad);
  $('cToTargets').onclick = toTargets;
  buildParams();
  for (const b of document.querySelectorAll('#cInMode button')) b.onclick = () => setMode(b.dataset.m);
  $('sSave').onclick = save;
  $('sName').addEventListener('input', () => { $('sName').dataset.touched = '1'; });
  $('sDca').addEventListener('change', () => { dcaVis(); lvdsWarn(); });
  $('t_lvds').addEventListener('change', () => { $('t_lvds').dataset.touched = '1'; setSource('targets'); schedule(); });
  for (const k of ['subframe', 'data_fmt', 'header', 'sw']) $('l_' + k).addEventListener('input', () => { if (C.mode === 'direct') schedule(); });
  dcaVis(); analyze();
}
export function showConfigure() { if (!C.ready) { C.ready = true; init(); } }
