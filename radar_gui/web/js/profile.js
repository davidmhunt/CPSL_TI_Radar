// Chirp-construction diagram (gui-27): a pure render of the analysed metrics -> SVG string.
// Top: frequency-vs-time of one chirp (idle, TX start, ADC window, ramp end, sampled/full bandwidth, Tc).
// Bottom: the frame strip (active vs idle, zoomed into ONE loop of chirps (gui-31)), TX-coloured like the MIMO card.
// Profile 0 / subframe 0 only (the metrics' flat fields). Text is laid out in CSS pixels (viewBox width = container width).

// Every Metrics field this file reads; tests/test_radar_gui_profile.py checks the backend supplies each one.
export const PROFILE_FIELDS = ['start_ghz', 'slope_mhz_us', 'idle_us', 'tx_start_us', 'adc_start_us', 'ramp_us', 'adc_end_us',
  'sampling_us', 'num_samples', 'sample_rate_ksps', 'bandwidth_mhz', 'sweep_mhz', 'chirp_us', 'chirps_per_loop', 'n_loops',
  'n_chirps', 'n_tx', 'loop_period_us', 'scheme', 'chirp_sequence', 'frame_period_ms', 'frame_rate_hz', 'active_ms', 'duty_cycle', 'subframes'];

export const TX_COLORS = ['#4aa3ff', '#ff8a3d', '#4ccf7a', '#e05cc8', '#e6c84a', '#35d0d0', '#b08cff', '#ff6b6b', '#9ccc65', '#ffb74d', '#7986cb', '#a1887f'];
const txColor = l => TX_COLORS[l % TX_COLORS.length];

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (v, d = 2) => { const s = (+v).toFixed(d); return s.includes('.') ? s.replace(/\.?0+$/, '') : s; };   // 6.00 -> 6
const FONT = '11px system-ui, -apple-system, "Segoe UI", sans-serif';
let _ctx = null;
function textW(s) {
  try { _ctx = _ctx || document.createElement('canvas').getContext('2d'); _ctx.font = FONT; return _ctx.measureText(s).width; }
  catch { return s.length * 6.2; }
}

// Place labels above a baseline in stacked tiers so none overlap; each gets a leader line down to its anchor x.
// items: [{x, text, ...}] -> adds .tier .x0 .w; returns tier count. A label may not cover another label's leader.
// Backtracking search: smallest tier count for which every label fits without covering another label or leader.
function placeTiers(items, W, gap = 6) {
  const base = [...items].sort((a, b) => a.x - b.x);
  for (const it of base) it.w = textW(it.text);
  const cands = (it, T) => {
    const out = [];
    for (let tier = 0; tier <= T; tier++) for (const anchor of ['middle', 'start', 'end']) {
      let x0 = anchor === 'middle' ? it.x - it.w / 2 : anchor === 'start' ? it.x - 2 : it.x - it.w + 2;
      x0 = Math.max(2, Math.min(W - it.w - 2, x0));
      if (it.x >= x0 - 1 && it.x <= x0 + it.w + 1 && !out.some(c => c.tier === tier && c.x0 === x0)) out.push({ tier, x0 });
    }
    return out;
  };
  const clash = (it, c, o) => (o.tier === c.tier && c.x0 < o.x0 + o.w + gap && o.x0 < c.x0 + it.w + gap) ||
    (o.tier > c.tier && o.x > c.x0 - 3 && o.x < c.x0 + it.w + 3) || (c.tier > o.tier && it.x > o.x0 - 3 && it.x < o.x0 + o.w + 3);
  const dfs = (i, T, done) => {
    if (i === base.length) return true;
    const it = base[i];
    for (const c of cands(it, T)) {
      if (done.some(o => clash(it, c, o))) continue;
      it.tier = c.tier; it.x0 = c.x0; done.push(it);
      if (dfs(i + 1, T, done)) return true;
      done.pop();
    }
    return false;
  };
  for (let T = 0; T < 8; T++) if (dfs(0, T, [])) return base.reduce((m, i) => Math.max(m, i.tier + 1), 0);
  base.forEach((it, i) => { it.tier = i; it.x0 = Math.max(2, Math.min(W - it.w - 2, it.x - it.w / 2)); });   // give up: one tier each
  return base.length;
}

// TX indices (0-based) used by the loop: bit positions of the chirp masks (TDM/BPM) or all TXs (DDMA).
export function usedTx(m) {
  if (m.scheme === 'ddma') return Array.from({ length: Math.max(1, Math.min(m.n_tx || 1, 12)) }, (_, i) => i);
  const s = new Set();
  for (const c of m.chirp_sequence || []) for (let l = 0; l < 12; l++) if ((c.tx_mask >> l) & 1) s.add(l);
  if (!s.size) for (let l = 0; l < Math.max(1, m.n_tx || 1); l++) s.add(l);
  return [...s].sort((a, b) => a - b);
}
const maskTx = (m, mask) => m.scheme === 'ddma' ? usedTx(m) : [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].filter(l => (mask >> l) & 1);

// width: container width in CSS px. Returns { svg, notes: [{level, text}] }.
export function renderProfile(m, width) {
  const notes = [];
  if (!m) return { svg: '', notes };
  const W = Math.max(300, Math.round(width || 460));
  const idle = Math.max(0, m.idle_us), ramp = m.ramp_us, txs = m.tx_start_us || 0;
  const a0 = m.adc_start_us, a1 = m.adc_end_us, over = a1 - ramp;
  const adcBad = over > 1e-9 || a0 < -1e-9, tmax = Math.max(ramp, a1, txs, 1e-9);
  const L = 66, R = 58, P = W - L - R, x0 = L, x1 = L + P, Hp = W < 520 ? 130 : 150;
  const TIER = 14;
  let g = '';
  const t = (x, y, s, o = {}) => `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}"${o.a ? ` text-anchor="${o.a}"` : ''}${o.c ? ` class="${o.c}"` : ''}${o.f ? ` style="fill:${o.f}"` : ''}>${esc(s)}</text>`;
  const ttl = s => `<title>${esc(s)}</title>`;

  // ---- time axis: idle (drawn up to 38% / at least 4% of the width) then the ramp domain ----
  const idleTrue = idle > 0 ? idle / (idle + tmax) * P : 0;
  const wI = idle > 0 ? Math.max(0.04 * P, Math.min(0.38 * P, idleTrue)) : 0;
  const scaled = idle > 0 && Math.abs(wI - idleTrue) > 1;
  if (scaled) notes.push({ level: 'info', text: `Idle (${num(idle)} µs) is drawn ${wI > idleTrue ? 'wider' : 'narrower'} than its true share of the time axis (axis break marked).` });
  const xT = tt => tt < 0 ? x0 + Math.max(0, (tt + idle) / (idle || 1)) * wI : x0 + wI + tt / tmax * (P - wI);
  const xr0 = xT(0), xr1 = xT(ramp), xa0 = xT(a0), xa1 = xT(a1);
  const feat = [
    { k: 'tx', tt: txs, text: `TX start ${num(txs)} µs`, title: `TX start time ${num(txs, 4)} µs after the ramp starts (profileCfg txStartTime)` },
    { k: 'a0', tt: a0, text: `ADC start ${num(a0)} µs`, title: `ADC start time ${num(a0, 4)} µs after the ramp starts` },
    { k: 'a1', tt: a1, text: `ADC end ${num(a1)} µs`, title: `ADC end = ADC start + ${num(m.sampling_us, 4)} µs sampling window = ${num(a1, 4)} µs` + (over > 1e-9 ? ` — ${num(over, 4)} µs after the ramp ends!` : ''), bad: over > 1e-9 },
    { k: 'r1', tt: ramp, text: `ramp end ${num(ramp)} µs`, title: `Ramp end time ${num(ramp, 4)} µs (sweep ${num(m.sweep_mhz, 3)} MHz = slope x ramp)` },
  ].map(f => ({ ...f, x: xT(f.tt) }));
  // events at (almost) the same time share one label: ADC end == ramp end is a normal, intended setup
  const lab = [];
  for (const f of feat) {
    const o = lab.find(l => Math.abs(l.x - f.x) < 1.5);
    if (o) { o.text = o.text.replace(/ [-\d.]+ µs$/, '') + ' = ' + f.text; o.title += '\n' + f.title; o.bad = o.bad || f.bad; o.fs.push(f); } else lab.push({ ...f, fs: [f] });
  }
  const nT = placeTiers(lab, W);
  const yTop = nT * TIER + 8, yBot = yTop + Hp;
  const yF = tt => yBot - Math.max(0, Math.min(ramp, tt)) / ramp * Hp;   // frequency (via slope) at ramp time tt

  // ---- plot ----
  g += `<line class="ax" x1="${x0}" y1="${yTop}" x2="${x0}" y2="${yBot}"/><line class="ax" x1="${x0}" y1="${yBot}" x2="${x1}" y2="${yBot}"/>`;
  const fEnd = m.start_ghz + m.sweep_mhz / 1e3;
  g += `<g>${ttl(`Start frequency ${num(m.start_ghz, 6)} GHz`)}${t(x0 - 6, yBot + 3, `${num(m.start_ghz, 3)} GHz`, { a: 'end' })}</g>`;
  g += `<g>${ttl(`Ramp-end frequency ${num(fEnd, 6)} GHz = start + sweep ${num(m.sweep_mhz, 3)} MHz`)}${t(x0 - 6, yTop + 3, `${num(fEnd, 3)} GHz`, { a: 'end' })}</g>`;
  g += `<text class="ax-t" x="${x0 - 6}" y="${(yTop + yBot) / 2}" text-anchor="end">f</text>`;
  // ADC window shading (red beyond the ramp end)
  const shadeX1 = Math.min(xa1, xr1);
  if (shadeX1 > xa0) g += `<rect class="adcwin" x="${xa0.toFixed(1)}" y="${yTop}" width="${(shadeX1 - xa0).toFixed(1)}" height="${Hp}">${ttl(`ADC sampling window ${num(m.sampling_us, 4)} µs = ${m.num_samples} samples / ${num(m.sample_rate_ksps, 3)} ksps`)}</rect>`;
  if (over > 1e-9) g += `<rect class="adcbad" x="${xr1.toFixed(1)}" y="${yTop}" width="${(xa1 - xr1).toFixed(1)}" height="${Hp}">${ttl(`ADC window runs ${num(over, 4)} µs past the ramp end: samples outside the ramp are not on the chirp`)}</rect>`;
  // idle (flat) with axis break, previous-chirp drop, ramp, drop to next chirp
  g += `<g>${ttl(`Idle time ${num(idle, 4)} µs: the synthesizer waits at the start frequency`)}<line class="idle" x1="${x0}" y1="${yBot}" x2="${xr0.toFixed(1)}" y2="${yBot}"/><line class="drop" x1="${x0}" y1="${yTop}" x2="${x0}" y2="${yBot}"/>`;
  if (scaled && wI > 10) { const bx = x0 + wI * 0.5; g += `<path class="brk" d="M${bx - 5} ${yBot + 5} l4 -10 M${bx + 1} ${yBot + 5} l4 -10"/>`; }
  g += `</g>`;
  g += `<g>${ttl(`Chirp ramp: ${num(m.slope_mhz_us, 4)} MHz/µs for ${num(ramp, 4)} µs = ${num(m.sweep_mhz, 3)} MHz sweep`)}<line class="ramp" x1="${xr0.toFixed(1)}" y1="${yBot}" x2="${xr1.toFixed(1)}" y2="${yTop}"/><line class="drop" x1="${xr1.toFixed(1)}" y1="${yTop}" x2="${xr1.toFixed(1)}" y2="${yBot}"/></g>`;
  const sa = Math.max(a0, 0), sb = Math.min(a1, ramp);
  if (sb > sa) g += `<g>${ttl(`Sampled part of the ramp: ${num(m.bandwidth_mhz, 3)} MHz (slope x ${num(m.sampling_us, 4)} µs)`)}<line class="samp${adcBad ? ' bad' : ''}" x1="${xT(sa).toFixed(1)}" y1="${yF(sa).toFixed(1)}" x2="${xT(sb).toFixed(1)}" y2="${yF(sb).toFixed(1)}"/></g>`;
  // slope label under the ramp
  const xm = (xr0 + xr1) / 2, ym = yBot - Hp / 2;
  g += `<g>${ttl(`Chirp slope ${num(m.slope_mhz_us, 6)} MHz/µs`)}${t(xm - 8, ym - 8, `slope ${num(m.slope_mhz_us, 2)} MHz/µs`, { a: 'end', c: 'slope' })}</g>`;
  // TX-on bar (stripes of the TX colours used by the loop), tx start -> ramp end
  const tx = usedTx(m), bx0 = Math.max(x0 + 1, xT(Math.max(txs, -idle))), bh = Math.max(2, Math.min(5, 14 / tx.length));
  if (xr1 > bx0) g += `<g>${ttl(`TX on from ${num(txs, 3)} µs: ${tx.map(l => 'TX' + (l + 1)).join(', ')}` + (m.scheme === 'ddma' ? ' (all fire every chirp)' : ' (each chirp uses its own TX subset)'))}` +
    tx.map((l, i) => `<rect x="${bx0.toFixed(1)}" y="${(yBot - tx.length * bh - 2 + i * bh).toFixed(1)}" width="${(xr1 - bx0).toFixed(1)}" height="${bh.toFixed(1)}" style="fill:${txColor(l)}"/>`).join('') + `</g>`;
  // event lines + staggered labels with leaders
  for (const f of feat) g += `<g>${ttl(f.title)}<line class="ev${f.bad ? ' bad' : ''}" x1="${f.x.toFixed(1)}" y1="${yTop}" x2="${f.x.toFixed(1)}" y2="${yBot}"/><line class="hit" x1="${f.x.toFixed(1)}" y1="${yTop}" x2="${f.x.toFixed(1)}" y2="${yBot}"/></g>`;
  for (const l of lab) {
    const y = yTop - 6 - l.tier * TIER;
    g += `<g>${ttl(l.title)}<line class="lead" x1="${l.x.toFixed(1)}" y1="${y + 2}" x2="${l.x.toFixed(1)}" y2="${yTop}"/>${t(l.x0, y, l.text, { c: 'evl' + (l.bad ? ' bad' : '') })}</g>`;
  }
  // bandwidth brackets on the right: sampled (inner) and full sweep (outer), with rotated labels
  const bracket = (xb, ya, yb, text, title, cls) => {
    const len = textW(text), c = Math.max(yTop + len / 2, Math.min(yBot - len / 2, (ya + yb) / 2));
    return `<g>${ttl(title)}<path class="bk ${cls || ''}" d="M${x1 + 3} ${ya.toFixed(1)} H${xb} V${yb.toFixed(1)} H${x1 + 3}"/>` +
      `<text class="bkt ${cls || ''}" transform="translate(${xb + 12} ${c.toFixed(1)}) rotate(-90)" text-anchor="middle">${esc(text)}</text></g>`;
  };
  if (sb > sa) g += `<line class="guide" x1="${xT(sa).toFixed(1)}" y1="${yF(sa).toFixed(1)}" x2="${x1 + 3}" y2="${yF(sa).toFixed(1)}"/><line class="guide" x1="${xT(sb).toFixed(1)}" y1="${yF(sb).toFixed(1)}" x2="${x1 + 3}" y2="${yF(sb).toFixed(1)}"/>`;
  if (sb > sa) g += bracket(x1 + 9, yF(sa), yF(sb), `sampled ${num(m.bandwidth_mhz, 1)} MHz`, `Sampled bandwidth ${num(m.bandwidth_mhz, 4)} MHz = slope x sampling window`, adcBad ? 'bad' : 'hl');
  g += bracket(x1 + 31, yBot, yTop, `sweep ${num(m.sweep_mhz, 1)} MHz`, `Full sweep ${num(m.sweep_mhz, 4)} MHz = slope x ramp time`);

  // ---- timing brackets under the plot: idle, ramp, ADC window, Tc (one row each) ----
  let y = yBot + 12;
  const row = (xa, xb, text, title, cls, tickOnly) => {
    const xs = Math.min(xa, xb), xe = Math.max(xa, xb), w = textW(text), c = Math.max(w / 2 + 2, Math.min(W - w / 2 - 2, (xs + xe) / 2));
    const r = `<g>${ttl(title)}<path class="bk ${cls || ''}" d="M${xs.toFixed(1)} ${y} v4 H${xe.toFixed(1)} v-4"/>${t(c, y + 15, text, { a: 'middle', c: 'bkl ' + (cls || '') })}</g>`;
    y += 20; return r;
  };
  if (idle > 0) g += row(x0, xr0, `idle ${num(idle)} µs`, `Idle time ${num(idle, 4)} µs` + (scaled ? ' (not to scale)' : ''), '');
  g += row(xr0, xr1, `ramp ${num(ramp)} µs`, `Ramp end time ${num(ramp, 4)} µs`, '');
  g += row(xa0, xa1, `ADC window ${num(m.sampling_us)} µs = ${m.num_samples} × ${num(m.sample_rate_ksps, 0)} ksps`,
    `ADC sampling window ${num(m.sampling_us, 4)} µs = ${m.num_samples} samples at ${num(m.sample_rate_ksps, 3)} ksps` + (over > 1e-9 ? ` — ${num(over, 4)} µs beyond the ramp end` : ''), adcBad ? 'bad' : 'hl');
  g += row(x0, xr1, `Tc = idle + ramp = ${num(m.chirp_us)} µs`, `Chirp time Tc = idle ${num(idle, 4)} + ramp ${num(ramp, 4)} = ${num(m.chirp_us, 4)} µs`, 'tc');
  if (over > 1e-9) notes.push({ level: 'warn', text: `ADC window ends ${num(over, 2)} µs after the ramp end (ADC start ${num(a0)} + ${num(m.sampling_us)} µs sampling > ramp ${num(ramp)} µs): the last samples fall outside the ramp. Nominal sampled bandwidth ${num(m.bandwidth_mhz, 1)} MHz; only ${num(Math.max(0, ramp - a0) * m.slope_mhz_us, 1)} MHz of it is swept inside the ramp.` });
  if (a0 < -1e-9) notes.push({ level: 'warn', text: `ADC start is negative (${num(a0)} µs).` });

  // ---- frame strip ----
  y += 6;
  g += `<line class="sep" x1="2" y1="${y}" x2="${W - 2}" y2="${y}"/>`;
  y += 8;
  const per = m.frame_period_ms, act = Math.min(m.active_ms, per), fr = per > 0 ? act / per : 1;
  const bw = W - 4, fx0 = 2, barH = 16, M = Math.max(1, m.chirps_per_loop || (m.chirp_sequence || []).length || 1), NL = Math.max(1, m.n_loops || 1);
  const aw = Math.max(4, Math.min(bw, fr * bw)), idleMs = Math.max(0, per - m.active_ms);
  const actTitle = `Active time ${num(m.active_ms, 5)} ms = ${NL} loop${NL > 1 ? 's' : ''} x ${M} chirp${M > 1 ? 's' : ''} = ${m.n_chirps} chirps x Tc ${num(m.chirp_us, 4)} µs = ${num(fr * 100, 3)}% of the frame period` + (m.duty_cycle > 1 ? ' - EXCEEDS the frame period' : '');
  const actVars = [`active ${num(m.active_ms, 3)} ms (${num(fr * 100, 1)}%) · ${NL} loop${NL > 1 ? 's' : ''} × ${M} chirp${M > 1 ? 's' : ''} = ${m.n_chirps} chirps`,
    `active ${num(m.active_ms, 3)} ms (${num(fr * 100, 1)}%) · ${NL} × ${M} chirps`, `active ${num(m.active_ms, 3)} ms (${num(fr * 100, 1)}%)`, `active ${num(m.active_ms, 3)} ms`];
  const actText = actVars.find(v => textW(v) <= bw) || actVars[actVars.length - 1];
  const items = [{ x: fx0 + aw / 2, text: actText, bad: m.duty_cycle > 1, title: actTitle }];
  if (bw - aw > 8) items.push({ x: fx0 + aw + (bw - aw) / 2, text: `idle ${num(idleMs, 2)} ms`, title: `Idle time per frame ${num(idleMs, 5)} ms (frame period minus active time)` });
  // frame axis above the bar: the whole bar = one frame period
  const fpText = `frame period ${num(per, 2)} ms · ${num(m.frame_rate_hz, 2)} Hz`;
  g += `<g>${ttl(`Frame period ${num(per, 5)} ms; frame rate ${num(m.frame_rate_hz, 4)} Hz (the bar below spans one frame)`)}<path class="bk" d="M${fx0} ${y + 16} v-4 H${fx0 + bw} v4"/>${t(W / 2, y + 9, fpText, { a: 'middle', c: 'bkl' })}</g>`;
  y += 22;
  const nF = placeTiers(items, W);
  const fyTop = y + nF * TIER + 2;
  for (const it of items) {
    const ly = fyTop - 6 - it.tier * TIER;
    g += `<g>${ttl(it.title)}<line class="lead" x1="${it.x.toFixed(1)}" y1="${ly + 2}" x2="${it.x.toFixed(1)}" y2="${fyTop}"/>${t(it.x0, ly, it.text, { c: 'frl' + (it.bad ? ' bad' : '') })}</g>`;
  }
  g += `<g>${ttl(`Frame period ${num(per, 5)} ms (${num(m.frame_rate_hz, 4)} Hz)`)}<rect class="fidle" x="${fx0}" y="${fyTop}" width="${bw}" height="${barH}"/></g>`;
  g += `<g>${ttl(`Active ${num(m.active_ms, 5)} ms`)}<rect class="fact" x="${fx0}" y="${fyTop}" width="${aw.toFixed(1)}" height="${barH}"/></g>`;
  y = fyTop + barH + 2;
  // zoom: ONE loop (gui-31). A loop-sized slice of the active segment (1/NL of it) is blown up to the full width below,
  // showing its chirps in order (TX-coloured ramp, blank idle gap = the Tc slot), instead of every chirp of the frame.
  const zy = y + 16, zh = 22, sw = Math.max(3, Math.min(aw, aw / NL)), tLoop = M * m.chirp_us, tRev = m.loop_period_us || tLoop;   // loop duration (every chirp), vs the per-TX revisit period
  g += `<path class="zoom" d="M${fx0} ${fyTop + barH} L${fx0 + sw} ${fyTop + barH} L${fx0 + bw} ${zy} L${fx0} ${zy} Z"/>`;
  g += `<g>${ttl(`One loop = 1/${NL} of the active time (${num(tLoop, 4)} µs of ${num(m.active_ms, 5)} ms), zoomed below`)}<rect class="slice" x="${fx0}" y="${fyTop}" width="${sw.toFixed(1)}" height="${barH}"/></g>`;
  const seq = m.chirp_sequence && m.chirp_sequence.length ? m.chirp_sequence : Array.from({ length: M }, (_, i) => ({ index: i, tx_mask: 1 }));
  const cwid = bw / M, rf = m.chirp_us > 0 ? Math.min(1, ramp / m.chirp_us) : 1, gapOk = cwid >= 7;
  g += `<g>${ttl(`One loop: ${M} chirp${M > 1 ? 's' : ''} x Tc ${num(m.chirp_us, 4)} µs = ${num(tLoop, 4)} µs`)}`;
  for (let c = 0; c < M; c++) {
    const cs = seq[c % seq.length], txl = maskTx(m, cs.tx_mask), sx = fx0 + c * cwid, h = zh / Math.max(1, txl.length);
    const rx = gapOk ? sx + cwid * (1 - rf) : sx, rw = gapOk ? cwid * rf : cwid;
    g += `<g>${ttl(`Chirp ${c + 1} of ${M}: ${txl.map(l => 'TX' + (l + 1)).join('+') || 'no TX'}; Tc ${num(m.chirp_us, 4)} µs (idle ${num(idle, 4)} + ramp ${num(ramp, 4)})`)}` +
      txl.map((l, i) => `<rect x="${rx.toFixed(2)}" y="${(zy + i * h).toFixed(2)}" width="${Math.max(0.6, rw - (cwid > 3 ? 0.6 : 0)).toFixed(2)}" height="${h.toFixed(2)}" style="fill:${txColor(l)}"/>`).join('') +
      (cwid >= 4 ? `<line class="tick" x1="${sx.toFixed(2)}" y1="${zy}" x2="${sx.toFixed(2)}" y2="${zy + zh}"/>` : '') + `</g>`;
  }
  g += `<rect class="loopbox" x="${fx0}" y="${zy}" width="${bw}" height="${zh}"/></g>`;
  y = zy + zh + 12;
  const frow = (xa, xb, text, title, cls) => {
    const xs = Math.min(xa, xb), xe = Math.max(xa, xb), w = textW(text), c = Math.max(w / 2 + 2, Math.min(W - w / 2 - 2, (xs + xe) / 2));
    const r = `<g>${ttl(title)}<path class="bk ${cls || ''}" d="M${xs.toFixed(1)} ${y} v4 H${xe.toFixed(1)} v-4"/>${t(c, y + 15, text, { a: 'middle', c: 'bkl ' + (cls || '') })}</g>`;
    y += 20; return r;
  };
  if (M > 1 && cwid >= 40) g += frow(fx0, fx0 + cwid, `Tc ${num(m.chirp_us, 2)} µs`, `One chirp slot: Tc = idle ${num(idle, 4)} + ramp ${num(ramp, 4)} = ${num(m.chirp_us, 4)} µs`, 'tc');
  g += frow(fx0, fx0 + bw, `1 loop = ${M} chirp${M > 1 ? 's' : ''} · ${num(tLoop, 2)} µs`, `One loop: ${M} chirp${M > 1 ? 's' : ''} x Tc ${num(m.chirp_us, 4)} µs = ${num(tLoop, 4)} µs` + (m.scheme === 'ddma' ? '' : ` (each TX revisited every ${num(tRev, 4)} µs)`), 'tc');
  // legend: TX colours
  y += 2;
  let lx = 2, ly = y;
  g += t(lx, ly + 9, 'TX:', { c: 'frl' }); lx += textW('TX:') + 8;
  for (const l of tx) {
    const w = textW('TX' + (l + 1)) + 20;
    if (lx + w > W) { lx = 2; ly += 16; }
    g += `<g>${ttl(`TX${l + 1}`)}<rect x="${lx}" y="${ly}" width="10" height="10" rx="2" style="fill:${txColor(l)}"/>${t(lx + 14, ly + 9, 'TX' + (l + 1), { c: 'frl' })}</g>`;
    lx += w;
  }
  const H = ly + 16;
  if (m.subframes && m.subframes.length > 1) notes.push({ level: 'info', text: `advFrameCfg: ${m.subframes.length} subframes - the diagram shows subframe 0 (its profile and loop) only.` });
  if (m.duty_cycle > 1) notes.push({ level: 'warn', text: `Active time (${num(m.active_ms, 2)} ms) exceeds the frame period (${num(per, 2)} ms).` });
  return { svg: `<svg viewBox="0 0 ${W} ${H.toFixed(0)}" width="${W}" height="${H.toFixed(0)}" role="img" aria-label="chirp construction diagram">${g}</svg>`, notes };
}
