// Tune tab (radar-37): RX-gain sweep. GET /api/tune/info?config=, POST /api/tune/start | cancel, GET /api/tune/status (polled).
// The board's valid gain min/max/step come from the server (radar-36 limits) and prefill the inputs; off-step / out-of-range
// values are refused here and again by the server. The result is a SUGGESTION shown as text: there is deliberately no control
// that applies a gain. All server text goes in through textContent. A server without these endpoints shows a "restart" hint.
import { $, css } from './state.js';
import { api, detailText, D, loadData } from './session.js';

const T = { ready: false, info: null, timer: null, last: null };
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
const missing = res => res.status === 404 || res.status === 405 || res.status === 0;
const f1 = v => (v == null ? '–' : (+v).toFixed(1));

function msg(text, cls) { const m = $('tnMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'runmsg ' + (cls || 'bad'); }

function gainRange() { return T.info && T.info.gain_range; }
// '' when the three inputs form a valid sweep, else why not (mirrors tune.gain_grid on the server)
export function gainProblem(lo, hi, step, rng) {
  const vals = { min: lo, max: hi, step };
  for (const [k, v] of Object.entries(vals)) if (!Number.isInteger(v)) return `gain ${k} must be a whole number of dB`;
  if (step < 1) return 'gain step must be at least 1 dB';
  if (lo > hi) return `gain min ${lo} is above gain max ${hi}`;
  const [bmin, bmax, bstep] = rng ? [rng.min, rng.max, rng.step] : [0, 63, 1];
  for (const [k, v] of [['min', lo], ['max', hi]]) {
    if (v < bmin || v > bmax) return `gain ${k} ${v} dB is outside this board's valid ${bmin}-${bmax} dB`;
    if ((v - bmin) % bstep) return `gain ${k} ${v} dB is not on this board's ${bstep} dB step`;
  }
  if (step % bstep) return `gain step ${step} dB is not a multiple of this board's ${bstep} dB step`;
  const n = Math.floor((hi - lo) / step) + 1;
  if (n > 64) return `${n} gains requested; at most 64 per sweep`;
  return '';
}
const nums = () => [+$('tnMin').value, +$('tnMax').value, +$('tnStep').value];

function validate() {
  const running = T.last && T.last.state === 'running';
  const [lo, hi, st] = nums();
  const why = T.info && !T.info.error ? gainProblem(lo, hi, st, gainRange()) : (T.info ? T.info.error : 'Pick a config.');
  const w = $('tnWarn'); w.hidden = !why; w.textContent = why || '';
  $('tnStart').disabled = !!why || running || !T.info;
  $('tnCancel').disabled = !running;
  for (const id of ['tnConfig', 'tnMin', 'tnMax', 'tnStep', 'tnFrames', 'tnMargin']) $(id).disabled = !!running;
}

async function loadInfo() {
  const cfg = $('tnConfig').value;
  T.info = null;
  if (!cfg) { $('tnLimits').textContent = 'No saved config with a DCA1000 stream: set one up in the Radar tab.'; validate(); return; }
  const res = await api('/api/tune/info?config=' + encodeURIComponent(cfg));
  if (!res.ok) { msg(missing(res) ? 'This GUI server is older than the Tune tab: restart the GUI to enable it.' : detailText(res)); validate(); return; }
  msg('');
  T.info = res.j;
  const r = res.j.gain_range;
  $('tnLimits').textContent = r
    ? `${res.j.board || 'board'} valid RX gain: ${r.min}-${r.max} dB in ${r.step} dB steps (${r.confidence} confidence). This config uses ${res.j.current_gain_db} dB.`
    : `No gain limits known for ${res.j.board || 'this board'}; the field takes 0-63 dB. This config uses ${res.j.current_gain_db} dB.`;
  if (r) { $('tnMin').value = r.min; $('tnMax').value = r.max; $('tnStep').value = r.step; $('tnMin').step = r.step; $('tnMax').step = r.step; $('tnStep').step = r.step; $('tnStep').min = r.step; }
  $('tnFrames').value = (res.j.defaults || {}).frames || 8;
  $('tnMargin').value = (res.j.defaults || {}).margin_db ?? 3;
  validate();
}

async function fillConfigs() {
  if (!D.loaded) await loadData();
  const sel = $('tnConfig'), keep = sel.value;
  const items = D.configs.filter(c => c.dca);
  const sig = JSON.stringify(items.map(c => c.path));
  if (T.sig === sig && T.info) return;      // keep what the user typed when they come back to the tab
  T.sig = sig;
  sel.textContent = '';
  for (const c of items) { const o = new Option(`${c.name}${c.group === 'system' ? ' (shipped)' : ''}`, c.path); sel.append(o); }
  if (items.some(c => c.path === keep)) sel.value = keep;
  await loadInfo();
}

async function start() {
  const [lo, hi, st] = nums();
  const res = await api('/api/tune/start', { config: $('tnConfig').value, gain_min: lo, gain_max: hi, gain_step: st,
    frames: +$('tnFrames').value, margin_db: +$('tnMargin').value });
  if (!res.ok) { msg(detailText(res)); return; }
  msg('');
  T.last = res.j; render(); poll();
}
async function cancel() {
  const res = await api('/api/tune/cancel', {});
  if (!res.ok) msg(detailText(res));
}
async function poll() {
  clearTimeout(T.timer);
  const res = await api('/api/tune/status');
  if (res.ok) { T.last = res.j; render(); }
  if (T.last && T.last.state === 'running') T.timer = setTimeout(poll, 800);
}

function render() {
  const s = T.last;
  validate();
  if (!s || s.state === 'idle') { $('tnResult').hidden = true; return; }
  $('tnResult').hidden = false;
  $('tnRun').textContent = s.run_dir || '';
  const sug = $('tnSug'), x = s.suggestion;
  if (s.state === 'running') {
    sug.className = 'runmsg'; sug.textContent = `Sweeping: step ${Math.min(s.step + (s.phase === 'done' ? 0 : 1), s.steps)} of ${s.steps}, ${s.gain_db} dB (${s.phase === 'capture' ? 'reconfiguring and capturing' : s.phase === 'measure' ? 'measuring' : s.phase})…`;
  } else if (s.state === 'failed') {
    sug.className = 'runmsg bad'; sug.textContent = 'Sweep failed: ' + (s.error || 'unknown error');
  } else if (s.state === 'cancelled') {
    sug.className = 'runmsg warn'; sug.textContent = `Cancelled after ${s.rows.length} of ${s.steps} steps; no suggestion.`;
  } else if (x) {
    sug.className = 'runmsg ' + (x.suggested_gain == null ? 'warn' : 'ok');
    sug.textContent = x.text + ' This is a suggestion only; nothing was applied.';
  }
  table(s); plot(s);
  $('tnNote').textContent = s.params ? `${s.params.frames} frames per step (first ${s.params.settle_frames} dropped), DC/leakage exclusion ${f1(s.params.exclude_m)} m, headroom is dB below the ${s.params.adc_bits}-bit digital full scale (${s.params.adc_bits_source || 'adcCfg'}; the RF ADC's effective resolution may be lower: docs/research memo "ADC full scale (radar-37)"); compression = strongest return more than ${s.params.tol_db} dB under the 1 dB/dB line; margin ${s.params.margin_db} dB.` : '';
}

function table(s) {
  const t = $('tnTable'); t.textContent = '';
  const heads = ['Gain (dB)', 'Status', 'Sat. chirps', 'ADC peak', 'Peak (dBFS)', 'Headroom (dB)', 'Bits', 'Clipped', 'Return (dB)', 'Noise (dB)', 'SNR (dB)', 'vs 1 dB/dB'];
  const h = el('tr'); for (const x of heads) h.append(el('th', '', x)); t.append(h);
  const sg = s.suggestion && s.suggestion.suggested_gain;
  for (const r of s.rows) {
    const tr = el('tr', 'st-' + (r.status || 'ok') + (r.gain_db === (s.suggestion && s.suggestion.max_ok_gain) ? ' sug' : ''));
    const sat = r.sat_chirps == null ? 'n/a' : `${r.sat_chirps}/${r.chirps}`;
    const cells = [r.gain_db, r.status || '', sat, r.adc_peak, f1(r.peak_dbfs), f1(r.headroom_db), r.bits, r.clipped, f1(r.peak_db), f1(r.noise_db), f1(r.snr_db), r.dev_db == null ? '–' : f1(r.dev_db)];
    cells.forEach((v, i) => tr.append(el('td', i > 1 ? 'num' : '', String(v))));
    t.append(tr);
  }
  if (sg != null) { const tr = el('tr', 'sug'); const td = el('td', '', `Suggested gain: ${sg} dB`); td.colSpan = heads.length; tr.append(td); t.append(tr); }
}

function plot(s) {
  const cv = $('tnPlot'), dpr = window.devicePixelRatio || 1, r = cv.getBoundingClientRect();
  cv.width = Math.max(10, r.width * dpr); cv.height = Math.max(10, r.height * dpr);
  const g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const W = r.width, H = r.height, L = 46, B = 38, Tp = 10, R = 12;
  g.clearRect(0, 0, W, H);
  const rows = s.rows; if (!rows.length) return;
  const xs = rows.map(q => q.gain_db), lo = Math.min(...xs), hi = Math.max(...xs, lo + 1);
  const ys = rows.flatMap(q => [q.peak_db, q.noise_db]);
  let y0 = Math.floor(Math.min(...ys) / 10) * 10, y1 = Math.ceil(Math.max(...ys) / 10) * 10; if (y1 <= y0) y1 = y0 + 10;
  const X = v => L + (v - lo) / (hi - lo) * (W - L - R), Y = v => Tp + (1 - (v - y0) / (y1 - y0)) * (H - Tp - B);
  const line = css('--line') || '#30363d', muted = css('--muted') || '#8b949e', accent = css('--accent') || '#58a6ff', bad = css('--bad') || '#f85149', ok = css('--ok') || '#3fb950';
  g.font = '11px system-ui, sans-serif'; g.fillStyle = muted; g.strokeStyle = line; g.lineWidth = 1;
  for (let v = y0; v <= y1; v += 10) { g.beginPath(); g.moveTo(L, Y(v)); g.lineTo(W - R, Y(v)); g.stroke(); g.textAlign = 'right'; g.fillText(String(v), L - 4, Y(v) + 4); }
  g.textAlign = 'center';
  for (const v of xs) g.fillText(String(v), X(v), H - B + 14);
  g.fillText('RX gain (dB)', (L + W - R) / 2, H - 4); g.save(); g.translate(10, (Tp + H - B) / 2); g.rotate(-Math.PI / 2); g.fillText('range-profile power (dB)', 0, 0); g.restore();
  const series = (key, col) => {
    g.strokeStyle = col; g.lineWidth = 2; g.beginPath();
    rows.forEach((q, i) => { const x = X(q.gain_db), y = Y(q[key]); if (i) g.lineTo(x, y); else g.moveTo(x, y); }); g.stroke();
  };
  // the ideal 1 dB/dB line from the first usable step
  const a = rows.find(q => q.dev_db != null);
  if (a) { g.setLineDash([4, 4]); g.strokeStyle = muted; g.beginPath(); g.moveTo(X(a.gain_db), Y(a.peak_db)); g.lineTo(X(hi), Y(a.peak_db + hi - a.gain_db)); g.stroke(); g.setLineDash([]); }
  series('noise_db', muted); series('peak_db', accent);
  for (const q of rows) {
    const bads = q.sat_chirps > 0 || q.clipped > 0 || q.status === 'compressed';
    g.fillStyle = bads ? bad : accent; g.beginPath(); g.arc(X(q.gain_db), Y(q.peak_db), bads ? 5 : 3, 0, 7); g.fill();
  }
  const x = s.suggestion && s.suggestion.suggested_gain;
  if (x != null && x >= lo && x <= hi) { g.strokeStyle = ok; g.lineWidth = 2; g.setLineDash([6, 4]); g.beginPath(); g.moveTo(X(x), Tp); g.lineTo(X(x), H - B); g.stroke(); g.setLineDash([]); g.fillStyle = ok; g.textAlign = 'left'; g.fillText(`suggested ${x} dB`, X(x) + 4, Tp + 12); }
  g.textAlign = 'left'; g.fillStyle = accent; g.fillText('strongest return', L + 6, Tp + 12); g.fillStyle = muted; g.fillText('noise floor (median)   - - 1 dB/dB', L + 100, Tp + 12);
  g.fillStyle = bad; g.fillText('red = saturated or compressed', L + 6, Tp + 26);
}

export function showTune() {
  if (!T.ready) {
    T.ready = true;
    $('tnConfig').onchange = loadInfo;
    for (const id of ['tnMin', 'tnMax', 'tnStep']) $(id).addEventListener('input', validate);
    $('tnStart').onclick = start; $('tnCancel').onclick = cancel;
    addEventListener('resize', () => { if (T.last && !$('tuneMain').hidden) plot(T.last); });
  }
  fillConfigs();
  poll();   // a sweep started earlier (or in another tab) is picked up again
}
