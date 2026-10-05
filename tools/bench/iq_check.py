#!/usr/bin/env python3
"""I/Q order confirmation check for an IWR1843 DCA1000 capture (core-03 D9).

Input: adc_data.bin from a short ``save_to_file`` capture, the radar cfg used,
and the measured distance (m) of a lone reflector.

Layout (DCA1000Handler::write_adc_data_cube_to_file): per frame, for chirp,
for rx, for sample: int16 real then int16 imag, little-endian, i.e.
bytes_per_frame = 4 * rx * samples * chirps.  "real"/"imag" are therefore the
current converter's output (ADCCubeConverter::interleave_data: first lane pair
-> imag, second -> real).  The "swapped" ordering is the same data with real
and imag exchanged, x' = j*conj(x), which mirrors the range spectrum
(bin k <-> N-k).

Method: per chirp, remove the mean, N-point DFT (N = adc samples, no padding),
average |X| over chirps of the chosen frame/rx, find the strongest bin outside
the DC region.  Expected bin = R / range_resolution,
range_resolution = c*fs / (2*slope*N).

Usage: uv run tools/bench/iq_check.py adc_data.bin <radar.cfg> <distance_m>
       [--rx 0] [--frame 0] [--tol 2]
"""
from __future__ import annotations

import argparse
import cmath
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_lib as lib  # noqa: E402

C = 299_792_458.0
DC_GUARD = 3  # ignore bins within this many of 0 (and N)


def cfg_params(cfg_text: str) -> dict:
    e = lib.expected_from_radar_cfg(cfg_text)
    prof = [l.split() for l in cfg_text.splitlines()
            if l.split() and l.split()[0] == "profileCfg"][-1]
    e["slope_mhz_us"] = float(prof[8])
    e["sample_rate_ksps"] = float(prof[11])
    e["range_resolution_m"] = (C * e["sample_rate_ksps"] * 1e3) / (
        2 * e["slope_mhz_us"] * 1e12 * e["adc_samples"])
    return e


def read_frame(path: Path, p: dict, frame: int):
    """cube[chirp][rx][sample] -> list of (re, im) via a flat int16 read."""
    bpf = p["bytes_per_frame"]
    with open(path, "rb") as fh:
        fh.seek(bpf * frame)
        raw = fh.read(bpf)
    if len(raw) < bpf:
        raise SystemExit(f"iq_check: {path} has no complete frame {frame} "
                         f"(need {bpf} B at offset {bpf * frame})")
    return struct.unpack(f"<{bpf // 2}h", raw)


def chirp_samples(words, p: dict, chirp: int, rx: int, swap: bool):
    n = p["adc_samples"]
    base = ((chirp * p["rx_antennas"]) + rx) * n * 2
    out = []
    for s in range(n):
        re, im = words[base + 2 * s], words[base + 2 * s + 1]
        out.append(complex(im, re) if swap else complex(re, im))
    return out


def dft_mag(x):
    try:
        import numpy as np
        return list(np.abs(np.fft.fft(np.asarray(x))))
    except ImportError:
        n = len(x)
        tw = [cmath.exp(-2j * math.pi * k / n) for k in range(n)]
        return [abs(sum(x[i] * tw[(k * i) % n] for i in range(n))) for k in range(n)]


def avg_spectrum(words, p: dict, rx: int, swap: bool):
    n, chirps = p["adc_samples"], p["chirps_per_frame"]
    acc = [0.0] * n
    for c in range(chirps):
        x = chirp_samples(words, p, c, rx, swap)
        m = sum(x) / n
        for k, v in enumerate(dft_mag([v - m for v in x])):
            acc[k] += v
    return [a / chirps for a in acc]


def peak_bin(spec) -> int:
    n = len(spec)
    cand = range(DC_GUARD, n - DC_GUARD + 1)
    return max(cand, key=lambda k: spec[k])


def verdict(peak_cur: int, peak_swp: int, expected_bin: float, n: int, tol: int) -> str:
    mirror = n - expected_bin
    near = lambda a, b: abs(a - b) <= tol  # noqa: E731
    if near(peak_cur, expected_bin) and near(peak_swp, mirror):
        return "current order OK"
    if near(peak_cur, mirror) and near(peak_swp, expected_bin):
        return "SWAPPED (current order puts the peak at the mirror bin N-k)"
    return "inconclusive"


def run(path: Path, cfg_text: str, dist_m: float, rx=0, frame=0, tol=2) -> dict:
    p = cfg_params(cfg_text)
    words = read_frame(path, p, frame)
    n = p["adc_samples"]
    exp_bin = dist_m / p["range_resolution_m"]
    sc, ss = avg_spectrum(words, p, rx, False), avg_spectrum(words, p, rx, True)
    pc, ps = peak_bin(sc), peak_bin(ss)
    return {"n": n, "range_resolution_m": p["range_resolution_m"], "expected_bin": exp_bin,
            "mirror_bin": n - exp_bin, "peak_current": pc, "peak_swapped": ps,
            "peak_to_median_current": sc[pc] / (sorted(sc)[n // 2] or 1.0),
            "verdict": verdict(pc, ps, exp_bin, n, tol)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("bin", type=Path)
    ap.add_argument("radar_cfg", type=Path)
    ap.add_argument("distance_m", type=float)
    ap.add_argument("--rx", type=int, default=0)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--tol", type=int, default=2, help="bins of tolerance")
    a = ap.parse_args(argv)
    r = run(a.bin, a.radar_cfg.read_text(), a.distance_m, a.rx, a.frame, a.tol)
    print(f"N = {r['n']}, range resolution = {r['range_resolution_m']:.4f} m")
    print(f"expected bin for {a.distance_m} m: {r['expected_bin']:.1f}  (mirror N-k: {r['mirror_bin']:.1f})")
    print(f"peak bin, current converter order: {r['peak_current']}  "
          f"(peak/median {r['peak_to_median_current']:.1f})")
    print(f"peak bin, swapped I/Q order:       {r['peak_swapped']}")
    print(f"VERDICT: {r['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
