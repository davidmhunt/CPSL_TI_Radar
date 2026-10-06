// Shared UI state and tiny DOM helpers.
export const $ = id => document.getElementById(id);
export const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

export const S = {
  view: 'top', color: 'v', range: 10, trail: 1, size: 3, minSnr: 0, paused: false,
  frames: [], counts: [], cfg: {}, last: null, rangeTouched: false,
  yaw: -0.35, pitch: 0.4, zoom: 1,
};
