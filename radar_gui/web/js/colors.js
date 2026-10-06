import { $, S } from './state.js';

// Diverging (velocity): blue = approaching, grey = static, red = receding. Sequential (SNR/height): viridis-like.
const DIV = [[59,130,246],[148,163,184],[239,68,68]];
const SEQ = [[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];
export const SCALES = {
  v:   { lo: -3, hi: 3, unit: 'm/s', stops: DIV, idx: 3 },
  snr: { lo: 5, hi: 35, unit: 'dB', stops: SEQ, idx: 4 },
  z:   { lo: -1, hi: 2, unit: 'm', stops: SEQ, idx: 2 },
};
function lerpStops(stops, t) {
  t = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(t)), f = t - i, a = stops[i], b = stops[i + 1];
  return `rgb(${a.map((c, k) => Math.round(c + (b[k] - c) * f)).join(',')})`;
}
export function colorOf(p) {
  const s = SCALES[S.color];
  return lerpStops(s.stops, (p[s.idx] - s.lo) / (s.hi - s.lo));
}
export function drawLegend() {
  const s = SCALES[S.color];
  $('legLo').textContent = `${s.lo} ${s.unit}`; $('legHi').textContent = `${s.hi}`;
  $('legBar').style.background = `linear-gradient(90deg, ${s.stops.map((c, i) =>
    `rgb(${c}) ${i / (s.stops.length - 1) * 100}%`).join(',')})`;
}
