"""RX-gain sweep core (radar-37): per-gain ADC metrics and the gain suggestion. Pure Python + numpy; no driver, no HTTP.

A sweep changes ONE field of a temporary copy of the profileCfg line, `rxGain` (arg 13: bits 5:0 = gain in dB, bits 7:6 = RF
gain target code, kept as they are), captures a few raw ADC frames per gain, and measures them. The capture itself is a
callable (`run_sweep(..., capture=...)`) so this module never touches a radar; `tune_api.py` supplies the real one (one fresh
driver run per gain: sensorStop flushes the board's configuration, so a profileCfg-only change cannot be re-started; see
docs/RESULTS.md and runs/radar37_gate). It SUGGESTS a gain and never applies one.

Suggestion rule (documented, deterministic, re-runnable on the stored rows with `suggest`):
  * a step is USABLE when it has no firmware-saturated chirp (sat_chirps == 0, or unknown on firmware that does not report
    it), no ADC sample at the rails (|x| >= full scale, `adc_bits`), and its strongest return (outside the DC/leakage
    exclusion zone) is at least `min_snr_db` above the median noise floor;
  * the ANCHOR is the lowest-gain usable step; a later step TRACKS when its strongest-return power rose within `tol_db` of
    the 1 dB/dB line from the anchor: P(g) - P(g0) >= (g - g0) - tol_db;
  * the highest tracking gain of the contiguous run from the anchor upward (stops at the first compressing or saturated
    step) is `max_ok_gain`; suggestion = `max_ok_gain - margin_db`, floored to the board's step grid and clipped to the
    board's minimum;
  * nothing usable -> `suggested_gain` None with an explicit reason.
When the run reaches the top of the sweep with no compression and no saturation, the text says so ("no compression observed
up to X dB; headroom Y dB"): the true limit is above the swept range and the suggestion is bounded by the sweep, not the radar.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import adc
from .cfg.parse import CfgError, parse_cfg

GAIN_MASK = 0x3F                 # rxGain bits 5:0: gain in dB (radar-36: bits 7:6 RF target code, 15:8 reserved)
RXGAIN_ARG = 13                  # profileCfg arg index of rxGain
DEFAULT_FRAMES = 8               # approved defaults (radar-37, 2026-10-15)
DEFAULT_MARGIN_DB = 3.0
DEFAULT_TOL_DB = 1.0
DEFAULT_MIN_SNR_DB = 10.0
ADC_BITS_CODE = {0: 12, 1: 14, 2: 16}   # adcCfg numADCBits (arg 0); samples are right-justified, full scale +-(2^(bits-1)-1)
DEFAULT_ADC_BITS = 16            # fallback when the cfg has no adcCfg (reported as such); docs/developer/radar_notes.md#hpf-rxgain-and-adc, "ADC full scale"
                                 # (16 for adcCfg 2 (medium confidence), 12 (medium-low), 14 (low)). The RF ADC's
                                 # effective resolution may be lower than this digital word.
EXCLUDE_BINS = 5.0               # default DC/leakage exclusion: this many un-padded range bins (Hann main lobe + HPF corner)
SETTLE_FRAMES = 1                # leading frames of every step dropped (the first frame after sensorStart is not steady)
MAX_STEPS = 64


class TuneError(ValueError):
    """A bad sweep request (range, step, cfg without profileCfg ...)."""


# ---- cfg edit ---------------------------------------------------------------------------------------------
def _profile_line(cfg_text: str) -> tuple[int, str, list[str], str]:
    """(line index, leading whitespace, tokens, trailing comment) of the first profileCfg line."""
    for i, raw in enumerate(cfg_text.split("\n")):
        body, sep, comment = raw.partition("%")
        parts = body.split()
        if parts and parts[0] == "profileCfg":
            return i, body[:len(body) - len(body.lstrip())], parts, (sep + comment if sep else "")
    raise TuneError("the cfg has no profileCfg line")


def read_rx_gain(cfg_text: str) -> int:
    """The whole rxGain word of the first profileCfg."""
    _, _, parts, _ = _profile_line(cfg_text)
    if len(parts) <= RXGAIN_ARG + 1:
        raise TuneError(f"profileCfg has {len(parts) - 1} fields; rxGain is field {RXGAIN_ARG + 1}")
    try:
        return int(float(parts[RXGAIN_ARG + 1]))
    except ValueError:
        raise TuneError(f"profileCfg rxGain {parts[RXGAIN_ARG + 1]!r} is not a number") from None


def set_rx_gain(cfg_text: str, gain_db: int) -> str:
    """`cfg_text` with the first profileCfg's rxGain gain bits (5:0) replaced; bits 7:6 and 15:8 are preserved and every other
    byte of the text (other lines, comments, line endings) is untouched."""
    g = int(gain_db)
    if not 0 <= g <= GAIN_MASK:
        raise TuneError(f"gain {g} dB does not fit the 6-bit gain field (0-{GAIN_MASK})")
    word = read_rx_gain(cfg_text)
    i, lead, parts, comment = _profile_line(cfg_text)
    parts[RXGAIN_ARG + 1] = str((word & ~GAIN_MASK) | g)
    lines = cfg_text.split("\n")
    cr = "\r" if lines[i].endswith("\r") else ""
    lines[i] = lead + " ".join(parts) + ((" " + comment.rstrip("\r")) if comment else "") + cr
    return "\n".join(lines)


def adc_bits_from_cfg(cfg_text: str) -> tuple[int, str]:
    """(digital word bits, source text) from the first adcCfg's numADCBits; 16 with an explicit note when absent/unknown."""
    for raw in cfg_text.split("\n"):
        parts = raw.split("%")[0].split()
        if parts and parts[0] == "adcCfg":
            try:
                code = int(float(parts[1]))
            except (IndexError, ValueError):
                break
            if code in ADC_BITS_CODE:
                return ADC_BITS_CODE[code], f"adcCfg numADCBits {code}"
            break
    return DEFAULT_ADC_BITS, f"no usable adcCfg in the cfg: assumed {DEFAULT_ADC_BITS}-bit"


# ---- request validation -----------------------------------------------------------------------------------
def gain_grid(lo, hi, step, rng: dict | None) -> list[int]:
    """The gains of a sweep lo..hi (inclusive) every `step` dB, validated against the board's {min, max, step} (radar-36
    `analog.gain_range`; None = no limits known, only 0-63). Whole dB only; off-step or out-of-range values raise TuneError."""
    vals = []
    for name, v in (("min", lo), ("max", hi), ("step", step)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v):
            raise TuneError(f"gain {name} must be a whole number of dB, got {v!r}")
        vals.append(int(v))
    lo, hi, step = vals
    if step < 1:
        raise TuneError("gain step must be at least 1 dB")
    if lo > hi:
        raise TuneError(f"gain min {lo} is above gain max {hi}")
    bmin, bmax, bstep = (rng["min"], rng["max"], rng["step"]) if rng else (0, GAIN_MASK, 1)
    for name, v in (("min", lo), ("max", hi)):
        if not bmin <= v <= bmax:
            raise TuneError(f"gain {name} {v} dB is outside this board's valid {bmin:g}-{bmax:g} dB")
        if (v - bmin) % bstep:
            raise TuneError(f"gain {name} {v} dB is not on this board's {bstep:g} dB step (valid: {bmin:g}, {bmin + bstep:g}, ...)")
    if step % bstep:
        raise TuneError(f"gain step {step} dB is not a multiple of this board's {bstep:g} dB step")
    out = list(range(lo, hi + 1, step))
    if len(out) > MAX_STEPS:
        raise TuneError(f"{len(out)} gains requested; at most {MAX_STEPS} per sweep")
    return out


def exclusion_m(geom: adc.Geometry, bins: float = EXCLUDE_BINS) -> float:
    """Default DC/leakage exclusion radius: `bins` un-padded range bins (from the range resolution)."""
    return float(bins) * float(geom.range_res_m)


# ---- per-step metrics -------------------------------------------------------------------------------------
@dataclass
class Capture:
    """What one gain step captured. `frames`: int16 cubes [rx, samples, chirps, 2] (settle frames already dropped);
    `sat_chirps`/`chirps`: firmware-reported saturated chirps over those frames and the chirps examined (None = the firmware
    reports no per-chirp saturation)."""
    frames: list
    sat_chirps: int | None = None
    chirps: int = 0
    info: dict = field(default_factory=dict)


def _db10(x) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(x, 1e-9))


def step_metrics(gain_db: int, cap: Capture, geom: adc.Geometry, exclude_m: float, adc_bits: int = DEFAULT_ADC_BITS) -> dict:
    """One result row. Power numbers are dB of the range-FFT power (same scale as the Raw ADC tab's profile), averaged over
    RX, chirps and the step's frames; `noise_db` is the median of the profile outside the exclusion zone, `peak_db` its
    maximum there (the strongest return), `dc_db` the maximum inside it (DC / leakage, reported but never used)."""
    if not cap.frames:
        raise TuneError(f"gain {gain_db} dB: no ADC frames were captured")
    fs_adc = float((1 << (int(adc_bits) - 1)) - 1)     # digital full scale 2^(bits-1)-1
    prof_lin, peak, bits, clipped_rail, step_m = None, 0, 0, 0, None
    for a in cap.frames:
        res = adc.process(a, geom, {"clutter": False})
        arrs = dict(res.arrays)
        p = np.power(10.0, arrs["profile"].astype(np.float64) / 10.0)
        prof_lin = p if prof_lin is None else prof_lin + p
        step_m = res.header["profile_step_m"]
        for r in res.header["diag"]["rows"]:
            peak = max(peak, r["peak_i"], r["peak_q"])
            bits = max(bits, r["bits"])
        clipped_rail += int((np.abs(a.astype(np.int32)) >= fs_adc).sum())
    prof_db = _db10(prof_lin / len(cap.frames))
    half = max(len(prof_db) // 2, 1)               # positive ranges only (the upper half mirrors the negative IF)
    r_m = np.arange(half) * step_m
    keep = r_m >= exclude_m
    if not keep.any():
        raise TuneError(f"exclusion zone {exclude_m:.2f} m covers the whole {r_m[-1]:.2f} m profile")
    body = prof_db[:half][keep]
    k = int(np.argmax(body))
    peak_db, noise_db = float(body[k]), float(np.median(body))
    dc_db = float(prof_db[:half][~keep].max()) if (~keep).any() else None
    return {"gain_db": int(gain_db), "frames": len(cap.frames), "sat_chirps": cap.sat_chirps, "chirps": int(cap.chirps),
            "adc_peak": int(peak), "peak_dbfs": 20 * math.log10(max(peak, 1) / adc.FULL_SCALE),
            "headroom_db": 20 * math.log10(fs_adc / max(peak, 1)), "bits": int(bits), "clipped": int(clipped_rail),
            "peak_db": peak_db, "peak_range_m": float(r_m[keep][k]), "noise_db": noise_db, "snr_db": peak_db - noise_db,
            "dc_db": dc_db}


# ---- suggestion ---------------------------------------------------------------------------------------------
def snap_down(g: float, rng: dict | None) -> int:
    """Largest whole-dB gain <= g on the board's step grid, never below its minimum."""
    if not rng:
        return int(math.floor(g))
    bmin, bstep = rng["min"], rng["step"]
    v = bmin + math.floor((g - bmin) / bstep) * bstep
    return int(max(v, bmin))


def _saturated(r: dict) -> bool:
    return bool(r.get("sat_chirps")) or bool(r.get("clipped"))


def suggest(rows: list[dict], rng: dict | None = None, margin_db: float = DEFAULT_MARGIN_DB, tol_db: float = DEFAULT_TOL_DB,
            min_snr_db: float = DEFAULT_MIN_SNR_DB, adc_bits: int = DEFAULT_ADC_BITS) -> dict:
    """The suggestion from stored `rows` (step_metrics output). Deterministic: re-running it on a saved table reproduces
    the saved suggestion. Annotates each row with `usable`, `dev_db` (tracking deviation from the 1 dB/dB line, None before
    the anchor) and `status` (ok | weak | saturated | compressed | after_limit)."""
    rows.sort(key=lambda r: r["gain_db"])
    for r in rows:
        r["usable"] = (not _saturated(r)) and r["snr_db"] >= min_snr_db
        r["dev_db"], r["status"] = None, "ok"
        r["status"] = "saturated" if _saturated(r) else ("weak" if r["snr_db"] < min_snr_db else "ok")
    out = {"suggested_gain": None, "none_reason": None, "anchor_gain": None, "max_ok_gain": None, "limited_by": None,
           "compression_observed": False, "saturation_observed": any(_saturated(r) for r in rows),
           "headroom_db": None, "margin_db": float(margin_db), "tol_db": float(tol_db), "min_snr_db": float(min_snr_db),
           "top_gain": rows[-1]["gain_db"] if rows else None, "text": ""}
    if not rows:
        out["none_reason"] = "no steps"
        out["text"] = "No suggestion: the sweep has no steps."
        return out
    anchor = next((r for r in rows if r["usable"]), None)
    if anchor is None:
        sat = [r for r in rows if r["status"] == "saturated"]
        if sat and len(sat) == len(rows):
            out["none_reason"] = (f"saturated at every swept gain, down to the lowest ({rows[0]['gain_db']} dB): "
                                  f"sweep lower gains or reduce the scene's return")
        elif sat:
            out["none_reason"] = (f"no usable step: {len(sat)} saturated, the rest have the strongest return under "
                                  f"{min_snr_db:g} dB above the noise floor")
        else:
            best = max(r["snr_db"] for r in rows)
            out["none_reason"] = (f"no return above the noise floor: the strongest peak is {best:.1f} dB above the median noise "
                                  f"(needs {min_snr_db:g} dB); point the radar at a target")
        out["text"] = "No suggestion: " + out["none_reason"] + "."
        return out
    out["anchor_gain"] = anchor["gain_db"]
    good, ended = anchor, False
    for r in rows:
        if r["gain_db"] < anchor["gain_db"]:
            if r["status"] == "ok":
                r["status"] = "weak"
            continue
        r["dev_db"] = (r["peak_db"] - anchor["peak_db"]) - (r["gain_db"] - anchor["gain_db"])
        if ended:
            r["status"] = "after_limit"
            continue
        if _saturated(r):
            ended, out["limited_by"] = True, "saturation"
        elif r["dev_db"] < -tol_db:
            ended, out["limited_by"], r["status"] = True, "compression", "compressed"
            out["compression_observed"] = True
        else:
            good = r
    out["max_ok_gain"], out["headroom_db"] = good["gain_db"], good["headroom_db"]
    if out["limited_by"] is None:
        out["limited_by"] = "sweep_top"
    g = snap_down(good["gain_db"] - margin_db, rng)
    out["suggested_gain"] = g
    below = g < rows[0]["gain_db"]
    lim = out["limited_by"]
    if lim == "sweep_top":
        why = (f"no compression observed up to {good['gain_db']} dB; headroom {good['headroom_db']:.1f} dB below the {adc_bits}-bit digital full scale (from adcCfg) "
               f"at that gain: the radar's limit is above the swept range")
    elif lim == "compression":
        why = f"returns stop tracking gain above {good['gain_db']} dB (compression > {tol_db:g} dB)"
    else:
        why = f"saturated chirps / ADC samples at the rails above {good['gain_db']} dB"
    out["text"] = (f"Suggested RX gain {g} dB ({good['gain_db']} dB - {margin_db:g} dB margin"
                   f"{', on the board step grid' if rng else ''}): {why}."
                   + (f" Below the swept range (lowest {rows[0]['gain_db']} dB): check it with a sweep that includes it." if below else ""))
    return out


# ---- the sweep ------------------------------------------------------------------------------------------------
def run_sweep(base_cfg_text: str, gains: list[int], n_frames: int, capture: Callable[[int, str, int], Capture],
              geom: adc.Geometry, *, rng: dict | None = None, margin_db: float = DEFAULT_MARGIN_DB,
              tol_db: float = DEFAULT_TOL_DB, min_snr_db: float = DEFAULT_MIN_SNR_DB, exclude_m: float | None = None,
              adc_bits: int | None = None, progress: Callable[[dict], None] | None = None,
              cancelled: Callable[[], bool] = lambda: False) -> dict:
    """Sweep `gains` over `base_cfg_text` (never modified: each step gets `set_rx_gain(base, g)` text) and return
    {"rows", "suggestion", "params"}. `capture(gain, cfg_text, n_frames) -> Capture`. Raises TuneError on a bad
    request; whatever `capture` raises propagates (the caller records the failed step). A cancel between steps returns the
    rows so far with `cancelled` True and no suggestion."""
    if n_frames < 1:
        raise TuneError("frames per step must be at least 1")
    if not gains:
        raise TuneError("no gains to sweep")
    adc_src = "override"
    if adc_bits is None:
        adc_bits, adc_src = adc_bits_from_cfg(base_cfg_text)
    read_rx_gain(base_cfg_text)                       # a cfg without a usable profileCfg fails before any step runs
    ex = float(exclusion_m(geom) if exclude_m is None else exclude_m)
    rows, did_cancel = [], False
    for i, g in enumerate(gains):
        if cancelled():
            did_cancel = True
            break
        if progress:
            progress({"step": i, "steps": len(gains), "gain_db": g, "phase": "capture"})
        cap = capture(g, set_rx_gain(base_cfg_text, g), n_frames)
        if progress:
            progress({"step": i, "steps": len(gains), "gain_db": g, "phase": "measure"})
        rows.append(step_metrics(g, cap, geom, ex, adc_bits))
        if progress:
            progress({"step": i + 1, "steps": len(gains), "gain_db": g, "phase": "done", "row": rows[-1]})
    params = {"gains": list(gains), "frames": int(n_frames), "margin_db": float(margin_db), "tol_db": float(tol_db),
              "min_snr_db": float(min_snr_db), "exclude_m": ex, "adc_bits": int(adc_bits), "adc_bits_source": adc_src, "gain_range": rng,
              "settle_frames": SETTLE_FRAMES}
    sug = None if did_cancel else suggest(rows, rng, margin_db, tol_db, min_snr_db, adc_bits)
    return {"rows": rows, "suggestion": sug, "params": params, "cancelled": did_cancel}


def rows_csv(rows: list[dict]) -> str:
    cols = ["gain_db", "status", "sat_chirps", "chirps", "adc_peak", "peak_dbfs", "headroom_db", "bits", "clipped",
            "peak_db", "peak_range_m", "noise_db", "snr_db", "dev_db", "dc_db", "frames"]
    def f(v):
        return "" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))
    return "\n".join([",".join(cols)] + [",".join(f(r.get(c)) for c in cols) for r in rows]) + "\n"


__all__ = ["Capture", "TuneError", "gain_grid", "run_sweep", "set_rx_gain", "read_rx_gain", "step_metrics", "suggest",
           "exclusion_m", "adc_bits_from_cfg", "snap_down", "rows_csv", "CfgError", "parse_cfg"]
