// ADC tab (gui-07): range profile, range-Doppler, range-azimuth (cartesian/polar) and raw-ADC diagnostics from the
// driver tap, over the binary /adc WebSocket. Message = u32 LE header length + JSON header + arrays (radar_gui/adc.py `encode`).
// The socket is only open while the tab is shown. An older backend without /adc degrades to a message in each panel.
import { $ } from './state.js';

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const A = { ws: null, open: false, retry: 0, last: null, status: null, ra: 'cart', rx: 0, lut: null, drawn: 0, noBackend: false,
  clutter: false, chirp: 0, rmax: 0, cache: {} };
const RXCOL = ['#58a6ff', '#3fb950', '#d29922', '#f778ba', '#a371f7', '#79c0ff', '#ffa657', '#56d4dd'];
const PANELS = ['adcProf', 'adcRd', 'adcRa', 'adcSeries', 'adcBits'];

// ---------- colormap ----------
const STOPS = [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]];
const LUT = new Uint32Array(256);
for (let i = 0; i < 256; i++) {
  const t = i / 255 * (STOPS.length - 1), k = Math.min(STOPS.length - 2, Math.floor(t)), f = t - k;
  const c = STOPS[k].map((v, j) => Math.round(v + (STOPS[k + 1][j] - v) * f));
  LUT[i] = (255 << 24) | (c[2] << 16) | (c[1] << 8) | c[0];   // little-endian RGBA
}

// ---------- socket ----------
function parse(buf) {
  const dv = new DataView(buf), n = dv.getUint32(0, true);
  const h = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n)));
  const base = 4 + n, arr = {};
  for (const a of h.arrays || []) {
    const raw = buf.slice(base + a.offset, base + a.offset + a.bytes);   // slice: typed arrays need an aligned offset
    arr[a.name] = a.dtype === 'u8' ? new Uint8Array(raw) : a.dtype === 'f32' ? new Float32Array(raw) : new Int16Array(raw);
  }
  return { h, arr };
}
function connect() {
  if (A.ws) return;
  const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/adc`);
  ws.binaryType = 'arraybuffer';
  A.ws = ws; let got = false;
  ws.onopen = () => { A.open = true; A.noBackend = false; sendOpts(); };
  ws.onmessage = ev => {
    got = true; A.retry = 0;
    let m; try { m = parse(ev.data); } catch (e) { return; }
    if (m.h.kind === 'status') {
      // a new run, or a state with nothing to show, drops the previous run's picture; ended/died keep the last frame
      if (A.runSeen !== m.h.run || ['none', 'off', 'no_dca', 'no_tap', 'waiting', 'error'].includes(m.h.state)) A.last = null;
      A.runSeen = m.h.run; A.status = m.h;
    } else if (m.h.kind === 'frame') {
      A.last = m;
      const st = A.status && /^(ended|died)$/.test(A.status.state) ? A.status : { state: 'running', msg: '' };
      A.status = { ...(A.status || {}), ...m.h, state: st.state, msg: st.msg, run: A.runSeen };
    }
    schedule();
  };
  ws.onclose = () => {
    A.ws = null; A.open = false;
    if (!A.visible) return;
    if (!got && A.retry++ >= 2) A.noBackend = true;   // /adc missing: the backend predates gui-07 (restart the GUI)
    schedule();
    setTimeout(connect, A.noBackend ? 5000 : 1500);
  };
}
function sendOpts() { if (A.ws && A.open) A.ws.send(JSON.stringify({ clutter: A.clutter, chirp: A.chirp })); }
export function showAdc() { A.visible = true; connect(); schedule(); }
export function hideAdc() { A.visible = false; if (A.ws) { A.ws.close(); } }

let raf = 0;
function schedule() { if (!raf && A.visible) raf = requestAnimationFrame(() => { raf = 0; draw(); }); }

// ---------- canvas helpers ----------
function fit(cv) {
  const r = cv.getBoundingClientRect(), d = window.devicePixelRatio || 1;
  const w = Math.max(40, Math.round(r.width * d)), h = Math.max(40, Math.round(r.height * d));
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; A.lut = null; }
  const g = cv.getContext('2d'); g.setTransform(d, 0, 0, d, 0, 0);
  return { g, w: r.width, h: r.height };
}
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const font = g => { g.font = '11px system-ui, sans-serif'; g.fillStyle = css('--muted'); g.strokeStyle = css('--grid-strong'); };
function niceStep(span, n) {
  const raw = span / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10) * p;
}
function ticks(lo, hi, n) { const s = niceStep(hi - lo, n), out = []; for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(Math.abs(v) < 1e-9 ? 0 : v); return out; }
// An offscreen image of an array region: u8 values -> colormap. `get(col,row)` returns the value; the result is w x h pixels.
function heat(u8, rows, cols, c0, c1, flipRows, transpose) {
  const w = transpose ? rows : c1 - c0, h = transpose ? c1 - c0 : rows;
  const cv = A.cache.cv || (A.cache.cv = document.createElement('canvas'));
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const g = cv.getContext('2d'), im = g.createImageData(w, h), px = new Uint32Array(im.data.buffer);
  for (let r = 0; r < rows; r++) for (let c = c0; c < c1; c++) {
    const v = LUT[u8[r * cols + c]];
    if (transpose) px[(c1 - 1 - c) * w + r] = v;                           // x = row (angle), y = range upward
    else px[(flipRows ? rows - 1 - r : r) * w + (c - c0)] = v;             // x = range, y = row upward when flipRows
  }
  g.putImageData(im, 0, 0);
  return cv;
}
const frame = (g, x, y, w, h) => { g.strokeStyle = css('--line'); g.strokeRect(x + .5, y + .5, w, h); };

// ---------- the four panels ----------
const PAD = { l: 44, r: 10, t: 8, b: 24 };
function nR(step, bins) { return A.rmax > 0 ? Math.max(2, Math.min(bins, Math.ceil(A.rmax / step))) : bins; }

function drawProfile(m) {
  const { g, w, h } = fit($('adcProf')); g.clearRect(0, 0, w, h);
  if (!m) return;
  const p = m.arr.profile, step = m.h.range_step_m, n = nR(step, p.length);
  const x0 = PAD.l, y0 = PAD.t, pw = w - PAD.l - PAD.r, ph = h - PAD.t - PAD.b;
  let hi = -1e9; for (let i = 0; i < n; i++) hi = Math.max(hi, p[i]);
  const lo = hi - 70, X = i => x0 + (i + .5) / n * pw, Y = v => y0 + (1 - Math.max(0, Math.min(1, (v - lo) / (hi - lo)))) * ph;
  font(g);
  for (const v of ticks(lo, hi, 5)) { g.beginPath(); g.moveTo(x0, Y(v)); g.lineTo(x0 + pw, Y(v)); g.stroke(); g.fillText(v.toFixed(0), 6, Y(v) + 4); }
  for (const r of ticks(0, n * step, 8)) { const x = x0 + r / (n * step) * pw; g.fillText(r.toFixed(r % 1 ? 1 : 0) + ' m', x - 8, h - 8); }
  g.strokeStyle = css('--accent'); g.lineWidth = 1.4; g.beginPath();
  for (let i = 0; i < n; i++) { const x = X(i), y = Y(p[i]); i ? g.lineTo(x, y) : g.moveTo(x, y); }
  g.stroke(); g.lineWidth = 1; frame(g, x0, y0, pw, ph);
  const k = m.h.profile_peak_bin;
  if (k < n) { g.fillStyle = css('--warn'); g.fillRect(X(k) - 1.5, Y(p[k]) - 1.5, 4, 4); }
  g.fillStyle = css('--text'); g.textAlign = 'right';
  g.fillText(`peak bin ${k} · ${(k * step).toFixed(2)} m · ${m.h.profile_peak_db.toFixed(1)} dB · image ratio ${m.h.image_ratio_db.toFixed(1)} dB`, x0 + pw - 6, y0 + 14);
  g.textAlign = 'left';
}

function drawRd(m) {
  const { g, w, h } = fit($('adcRd')); g.clearRect(0, 0, w, h);
  if (!m) return;
  const d = m.h.rd, [rows, cols] = d.shape, n = nR(d.range_step_m, cols);
  const x0 = PAD.l, y0 = PAD.t, pw = w - PAD.l - PAD.r, ph = h - PAD.t - PAD.b;
  g.imageSmoothingEnabled = false;
  g.drawImage(heat(m.arr.rd, rows, cols, 0, n, true, false), x0, y0, pw, ph);
  font(g);
  const vlo = (0 - d.vel_zero_bin - .5) * d.vel_step_ms, vhi = (rows - 1 - d.vel_zero_bin + .5) * d.vel_step_ms;
  for (const v of ticks(vlo, vhi, 6)) { const y = y0 + (1 - (v - vlo) / (vhi - vlo)) * ph; g.fillText(v.toFixed(1), 6, y + 4); g.beginPath(); g.moveTo(x0 - 4, y); g.lineTo(x0, y); g.stroke(); }
  for (const r of ticks(0, n * d.range_step_m, 8)) g.fillText(r.toFixed(r % 1 ? 1 : 0) + ' m', x0 + r / (n * d.range_step_m) * pw - 8, h - 8);
  g.fillText('m/s', 6, y0 + 10);
  frame(g, x0, y0, pw, ph);
  const [pr, pc] = d.peak;
  if (pc < n) {
    const x = x0 + (pc + .5) / n * pw, y = y0 + (1 - (pr + .5) / rows) * ph;
    g.strokeStyle = '#fff'; g.beginPath(); g.arc(x, y, 6, 0, 7); g.stroke();
    g.fillStyle = css('--text'); g.textAlign = 'right';
    g.fillText(`peak ${(pc * d.range_step_m).toFixed(2)} m · ${((pr - d.vel_zero_bin) * d.vel_step_ms).toFixed(2)} m/s (+ = receding)`, x0 + pw - 6, y0 + 14); g.textAlign = 'left';
  }
}

function raLut(w, h, d, rows, cols, n, x0, y0, pw, ph) {
  const key = [w, h, rows, n, d.range_step_m, d.sin_step, d.sin_zero_bin].join('|');
  if (A.lut && A.lut.key === key) return A.lut;
  const rmax = n * d.range_step_m, sc = Math.min(pw / (2 * rmax), ph / rmax);
  const cx = x0 + pw / 2, cy = y0 + ph, W = Math.ceil(pw), H = Math.ceil(ph), idx = new Int32Array(W * H).fill(-1);
  for (let j = 0; j < H; j++) for (let i = 0; i < W; i++) {
    const x = (i + x0 - cx + .5) / sc, y = (cy - (j + y0) - .5) / sc, r = Math.hypot(x, y);
    if (y <= 0 || r >= rmax) continue;
    const a = Math.round(x / r / d.sin_step + d.sin_zero_bin), c = Math.floor(r / d.range_step_m);
    if (a >= 0 && a < rows && c < n) idx[j * W + i] = a * cols + c;
  }
  return (A.lut = { key, idx, W, H, sc, cx, cy, rmax });
}
function drawRa(m) {
  const { g, w, h } = fit($('adcRa')); g.clearRect(0, 0, w, h);
  if (!m || !m.h.ra) return;
  const d = m.h.ra, [rows, cols] = d.shape, n = nR(d.range_step_m, cols);
  const x0 = PAD.l, y0 = PAD.t, pw = w - PAD.l - PAD.r, ph = h - PAD.t - PAD.b;
  font(g);
  if (A.ra === 'polar') {
    g.imageSmoothingEnabled = false;
    g.drawImage(heat(m.arr.ra, rows, cols, 0, n, false, true), x0, y0, pw, ph);
    frame(g, x0, y0, pw, ph);
    const slo = (-d.sin_zero_bin - .5) * d.sin_step, shi = (rows - 1 - d.sin_zero_bin + .5) * d.sin_step;
    for (const deg of [-60, -40, -20, 0, 20, 40, 60]) { const s = Math.sin(deg * Math.PI / 180); if (s < slo || s > shi) continue; g.fillText(deg + '°', x0 + (s - slo) / (shi - slo) * pw - 8, h - 8); }
    for (const r of ticks(0, n * d.range_step_m, 6)) g.fillText(r.toFixed(r % 1 ? 1 : 0) + ' m', 4, y0 + (1 - r / (n * d.range_step_m)) * ph + 4);
    const [pa, pc] = d.peak;
    if (pc < n) {
      const x = x0 + (pa + .5) / rows * pw, y = y0 + (1 - (pc + .5) / n) * ph;
      g.strokeStyle = '#fff'; g.beginPath(); g.arc(x, y, 6, 0, 7); g.stroke();
    }
  } else {
    const L = raLut(w, h, d, rows, cols, n, x0, y0, pw, ph), u8 = m.arr.ra;
    const cv = A.cache.rc || (A.cache.rc = document.createElement('canvas'));
    if (cv.width !== L.W || cv.height !== L.H) { cv.width = L.W; cv.height = L.H; }
    const cg = cv.getContext('2d'), im = cg.createImageData(L.W, L.H), px = new Uint32Array(im.data.buffer);
    for (let i = 0; i < L.idx.length; i++) px[i] = L.idx[i] < 0 ? 0 : LUT[u8[L.idx[i]]];
    cg.putImageData(im, 0, 0);
    g.drawImage(cv, x0, y0, L.W, L.H);
    g.strokeStyle = css('--grid-strong');
    for (const r of ticks(0, L.rmax, 5)) { if (!r) continue; g.beginPath(); g.arc(L.cx, L.cy, r * L.sc, Math.PI, 2 * Math.PI); g.stroke(); g.fillText(r.toFixed(r % 1 ? 1 : 0) + ' m', L.cx + 3, L.cy - r * L.sc - 2); }
    for (const deg of [-60, -30, 0, 30, 60]) {
      const t = deg * Math.PI / 180; g.beginPath(); g.moveTo(L.cx, L.cy); g.lineTo(L.cx + Math.sin(t) * L.rmax * L.sc, L.cy - Math.cos(t) * L.rmax * L.sc); g.stroke();
      g.fillText(deg + '°', L.cx + Math.sin(t) * (L.rmax * L.sc - 14) - 8, L.cy - Math.cos(t) * (L.rmax * L.sc - 14));
    }
    const [pa, pc] = d.peak;
    if (pc < n) {
      const s = (pa - d.sin_zero_bin) * d.sin_step, r = (pc + .5) * d.range_step_m, x = L.cx + r * s * L.sc, y = L.cy - r * Math.sqrt(Math.max(0, 1 - s * s)) * L.sc;
      g.strokeStyle = '#fff'; g.beginPath(); g.arc(x, y, 6, 0, 7); g.stroke();
    }
  }
  const [pa, pc] = d.peak, s = (pa - d.sin_zero_bin) * d.sin_step;
  g.fillStyle = css('--text'); g.textAlign = 'right';
  g.fillText(`peak ${((pc + .5) * d.range_step_m).toFixed(2)} m · ${(Math.asin(Math.max(-1, Math.min(1, s))) * 180 / Math.PI).toFixed(1)}° (+ = right, +x)`, x0 + pw - 6, y0 + 14);
  g.textAlign = 'left';
}

function drawSeries(m) {
  const { g, w, h } = fit($('adcSeries')); g.clearRect(0, 0, w, h);
  if (!m) return;
  const d = m.h.diag, ts = m.arr.series, n = d.series_n, rx = m.h.diag.rows.length, r = Math.min(A.rx, rx - 1);
  const x0 = 38, y0 = 6, pw = w - x0 - 8, ph = h - y0 - 20;
  let pk = 1; for (let i = 0; i < 2 * n; i++) pk = Math.max(pk, Math.abs(ts[(r * 2) * n + i]));
  pk = Math.max(pk, 64); font(g);
  g.beginPath(); g.moveTo(x0, y0 + ph / 2); g.lineTo(x0 + pw, y0 + ph / 2); g.stroke();
  g.fillText(String(pk), 2, y0 + 10); g.fillText(String(-pk), 2, y0 + ph); g.fillText('sample' + (d.series_step > 1 ? ` (every ${d.series_step})` : '') + ` · chirp ${d.chirp}`, x0, h - 6);
  for (const [q, col] of [[0, css('--accent')], [1, css('--warn')]]) {
    g.strokeStyle = col; g.beginPath();
    for (let i = 0; i < n; i++) { const x = x0 + i / Math.max(1, n - 1) * pw, y = y0 + (1 - (ts[(r * 2 + q) * n + i] / pk + 1) / 2) * ph; i ? g.lineTo(x, y) : g.moveTo(x, y); }
    g.stroke();
  }
  g.fillStyle = css('--accent'); g.fillText('I', x0 + pw - 30, y0 + 12); g.fillStyle = css('--warn'); g.fillText('Q', x0 + pw - 14, y0 + 12);
}

function drawBits(m) {
  const { g, w, h } = fit($('adcBits')); g.clearRect(0, 0, w, h);
  if (!m) return;
  const bars = m.h.diag.bars, x0 = 30, y0 = 6, pw = w - x0 - 8, ph = h - y0 - 20, bw = pw / 16;
  font(g);
  g.fillText('1', 8, y0 + 10); g.fillText('0', 8, y0 + ph);
  bars.forEach((row, r) => { g.fillStyle = RXCOL[r % RXCOL.length]; row.forEach((v, b) => g.fillRect(x0 + b * bw + r * (bw - 2) / bars.length + 1, y0 + (1 - v) * ph, Math.max(1.5, (bw - 3) / bars.length), v * ph)); });
  g.fillStyle = css('--muted');
  for (let b = 0; b < 16; b += 3) g.fillText(String(b), x0 + b * bw + 2, h - 6);
  g.textAlign = 'right'; g.fillText('bit b: share of |x| >= 2^b', x0 + pw, y0 + 10); g.textAlign = 'left';
}

function table(m) {
  const el = $('adcTable');
  if (!m) { el.innerHTML = ''; return; }
  const rows = m.h.diag.rows;
  el.innerHTML = '<tr><th>RX</th><th>peak I</th><th>peak Q</th><th>bits</th><th>RMS dBFS</th><th>DC I</th><th>DC Q</th><th>I/Q dB</th><th>clipped</th></tr>' +
    rows.map(r => `<tr class="${r.clipped ? 'badrow' : ''}"><td><span class="rxdot" style="background:${RXCOL[r.rx % RXCOL.length]}"></span>${r.rx}</td><td>${r.peak_i}</td><td>${r.peak_q}</td><td>${r.bits}</td>` +
      `<td>${r.rms_dbfs.toFixed(1)}</td><td>${r.dc_i.toFixed(1)}</td><td>${r.dc_q.toFixed(1)}</td><td>${r.iq_ratio_db.toFixed(2)}</td><td>${r.clipped}</td></tr>`).join('');
}

// ---------- states / counters ----------
const STATE_CLS = { running: 'ok', waiting: 'warn', ended: 'warn', died: 'bad', error: 'bad', none: '', off: '', no_tap: 'warn', no_dca: '' };
function status() {
  const s = A.status, el = $('adcState');
  let state, msg;
  if (A.noBackend) { state = 'none'; msg = 'ADC views need the newer backend: restart the GUI (python -m radar_gui)'; }
  else if (!s) { state = 'waiting'; msg = A.open ? 'connected…' : 'connecting…'; }
  else { state = s.state; msg = s.msg; }
  const have = !!A.last;
  // a state that has nothing to show hides the plots under a message; ended/died keep the last frame on screen
  const blank = !have && !(state === 'running');
  for (const id of ['adcMsgProf', 'adcMsgRd', 'adcMsgRa', 'adcMsgDiag']) { const e = $(id); e.hidden = !blank; e.textContent = blank ? msg : ''; }
  el.className = 'badge ' + (STATE_CLS[state] || ''); el.textContent = state === 'running' ? 'live' : state.replace('_', ' ');
  $('adcStatMsg').textContent = have && msg ? msg : '';
  const c = s || {};
  $('adcCounters').textContent = c.adc_in == null ? '' : `in ${c.adc_in} · shown ${c.adc_shown ?? 0} · dropped(gui) ${c.adc_dropped_gui ?? 0} · rejected ${c.adc_rejected ?? 0} · gaps ${c.index_gaps ?? 0} · proc ${c.proc_ms == null ? '–' : c.proc_ms.toFixed(1) + ' ms'}`;
  const part = $('adcPartial'); part.hidden = !(have && A.last.h.partial);
  const er = $('adcErr'); er.hidden = !(c.error && state !== 'error'); er.textContent = c.error ? 'last rejected frame: ' + c.error : '';
  const raOff = have && A.last.h.ra === null;
  $('adcRaMsg').hidden = !raOff; $('adcRaMsg').textContent = raOff ? 'range-azimuth disabled: ' + (A.last.h.ra_reason || '') : '';
  return blank;
}

function draw() {
  const m = A.last; status();
  drawProfile(m); drawRd(m); drawRa(m); drawSeries(m); drawBits(m); table(m);
  const sr = $('adcRx'), nrx = m ? m.h.diag.rows.length : 0;
  if (sr.options.length !== nrx) { sr.innerHTML = Array.from({ length: nrx }, (_, i) => `<option value="${i}">RX ${i}</option>`).join(''); sr.value = String(Math.min(A.rx, Math.max(0, nrx - 1))); }
}

// ---------- controls ----------
export function initAdc() {
  $('adcRaSeg').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    [...$('adcRaSeg').children].forEach(c => c.classList.toggle('on', c === b)); A.ra = b.dataset.m; A.lut = null; schedule();
  });
  $('adcClutter').addEventListener('change', () => { A.clutter = $('adcClutter').checked; sendOpts(); });
  $('adcChirp').addEventListener('change', () => { A.chirp = Math.max(0, parseInt($('adcChirp').value, 10) || 0); sendOpts(); });
  $('adcRx').addEventListener('change', () => { A.rx = +$('adcRx').value; schedule(); });
  $('adcRmax').addEventListener('input', () => { A.rmax = +$('adcRmax').value; A.lut = null; $('adcRmaxVal').textContent = A.rmax > 0 ? A.rmax + ' m' : 'full'; schedule(); });
  addEventListener('resize', () => { if (A.visible) { A.lut = null; schedule(); } });
}
