// Range compensation (radar-38): a DISPLAY-ONLY dB gain that lifts far returns so they can be compared with near ones.
// Pure functions, no DOM: adc.js applies them at draw time to the profile (dB floats) and the range-Doppler u8 map. Backend stats,
// the peak markers, recordings and the tune sweep never see it. r2 = +20 log10(R/Rref) (amplitude-like / distributed scaling),
// r4 = +40 log10(R/Rref) (point-target radar equation: power falls as 1/R^4).
export const COMP_MODES = { off: 0, r2: 20, r4: 40 };
export const COMP_LABEL = { off: 'off', r2: 'R^2', r4: 'R^4' };

// Reference range: past the HPF1 corner when the frame header says where it is (radar-36 `bands.hpf_m`), never under 1 m.
export function rangeRef(bands) {
  const h = bands && bands.hpf_m > 0 ? bands.hpf_m : 0;
  return Math.max(1, h);
}

// dB to add at range r_m. Zero (not -inf, not negative) at or inside rref, and zero beyond the usable IF band edge
// (edge_m, null = unknown): noise out there is shaded as unreliable and would only blow up.
export function rangeComp(mode, r_m, rref_m, edge_m) {
  const k = COMP_MODES[mode] || 0;
  if (!k || !(r_m > rref_m) || !(rref_m > 0)) return 0;
  if (edge_m != null && r_m > edge_m) return 0;
  return k * Math.log10(r_m / rref_m);
}
