"""Derived numbers for a cfg: resolutions, maxima, timing, ADC data volume.

Maths (per the mmWave SDK demos; `tools/radar_viewer/cfggen.py` documents the cascade/DDMA case
as implemented in the firmware's mmwdemo_rfparserDDMA.c):

    B (sampled)      = slope * N / fs
    range resolution = c / (2 B)
    max range        = 0.9 * c * fs / (2 slope)   complex 1x ADC (half of that for real-only ADC)
    fc               = start + slope * adcStart + B / 2
    TDM MIMO         max velocity = lambda / (4 * T_loop),  T_loop = chirps_per_loop * Tc
    cascade DDMA     max velocity = lambda / (4 * Tc)       (demodulation recovers the full span)
    velocity res.    = lambda / (2 * N_chirps * Tc)         (both modes)
    azimuth res.     ~ 2 / N_az_virtual rad at boresight (uniform half-wavelength virtual array)
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .parse import Cfg, CfgError

C = 299_792_458.0
USABLE_IF = 0.9           # cfggen.py USABLE_IF: ~90 % of the IF band is usable
CASCADE = "AWR2243_CASCADE"
BOARDS = ("IWR1443", "IWR1843", "IWR6843", CASCADE)
# TX1 and TX3 are the azimuth pair on the single-chip EVMs (TX2 is the elevation-offset one).
# Assumption from the EVM antenna layout; ODS/AOP 6843 modules differ (see Metrics.notes).
SINGLE_CHIP_AZ_TX_MASK = 0b101
LVDS_DATAFMT2_META_BYTES = 64   # docs/firmware.md: dataFmt 2 = ADC + two 32-byte per-chirp metadata slots


def popcount(x: int) -> int:
    return bin(x & 0xFFFFFFFF).count("1")


@dataclass
class Metrics:
    mode: str                     # "tdm" or "ddma"
    board: str                    # as given, or "" when it could not be inferred
    # chirp / profile
    start_ghz: float
    slope_mhz_us: float
    idle_us: float
    adc_start_us: float
    ramp_us: float
    num_samples: int
    sample_rate_ksps: float
    bandwidth_mhz: float          # sampled bandwidth
    sweep_mhz: float              # slope * ramp
    center_ghz: float
    chirp_us: float               # idle + ramp
    sampling_us: float            # N / fs
    # array
    n_rx: int
    n_tx: int
    n_virtual: int
    n_az_virtual: int
    chirps_per_loop: int
    n_loops: int
    n_chirps: int                 # per frame
    # headline numbers
    range_res_m: float
    max_range_m: float
    max_range_ideal_m: float
    velocity_res_ms: float
    max_velocity_ms: float
    azimuth_res_deg: float
    # frame
    frame_period_ms: float
    frame_rate_hz: float
    active_ms: float
    duty_cycle: float
    # ADC data
    bytes_per_sample: int
    bytes_per_chirp: int
    bytes_per_frame: int
    avg_data_rate_mbps: float     # bytes_per_frame / frame period, megabit/s
    burst_rate_mbps: float        # rate while sampling: fs * n_rx * bytes_per_sample
    chirp_avg_rate_mbps: float    # bytes_per_chirp / chirp time (ADC buffer drains between chirps)
    lvds_data_fmt: int | None     # lvdsStreamCfg dataFmt, None when no lvdsStreamCfg
    num_frames: int | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def infer_board_kind(cfg: Cfg) -> str:
    """'cascade' (10-token frameCfg, 5-field channelCfg) or 'single' (single-chip layout)."""
    f = cfg.first("frameCfg")
    if f is not None and len(f.args) >= 9:
        return "cascade"
    return "single"


def _need(cfg: Cfg, name: str):
    c = cfg.first(name)
    if c is None:
        raise CfgError(f"missing {name}")
    return c


def frame_layout(cfg: Cfg, cascade: bool) -> dict:
    """frameCfg fields. Single chip: start end loops frames period trig delay.
    Cascade: start end loops frames numAdc period trig delay ?  (period at args[5])."""
    f = _need(cfg, "frameCfg")
    a = f.floats()
    need = 9 if cascade else 7
    if len(a) < need:
        raise CfgError(f"line {f.line}: frameCfg needs {need} fields, got {len(a)}")
    out = dict(start=int(a[0]), end=int(a[1]), loops=int(a[2]), frames=int(a[3]),
               period_ms=a[5] if cascade else a[4])
    return out


def chirp_tx_masks(cfg: Cfg, start: int, end: int) -> dict[int, int]:
    """chirp index -> TX enable mask, for chirps start..end that have a chirpCfg."""
    masks: dict[int, int] = {}
    for c in cfg.all("chirpCfg"):
        a = c.floats()
        if len(a) < 8:
            raise CfgError(f"line {c.line}: chirpCfg needs 8 fields, got {len(a)}")
        for i in range(int(a[0]), int(a[1]) + 1):
            if start <= i <= end:
                masks[i] = masks.get(i, 0) | int(a[7])
    return masks


def metrics(cfg: Cfg, board: str | None = None) -> Metrics:
    """Compute metrics. `board` picks TDM (single chip) vs DDMA (cascade); None infers from the
    frameCfg layout. Raises CfgError when a needed command is missing or malformed."""
    if board is not None and board not in BOARDS:
        raise CfgError(f"unknown board {board!r}; expected one of {BOARDS}")
    cascade = (board == CASCADE) if board else infer_board_kind(cfg) == "cascade"
    notes: list[str] = []

    p = _need(cfg, "profileCfg")
    pa = p.floats()
    if len(pa) < 12:
        raise CfgError(f"line {p.line}: profileCfg needs 14 fields, got {len(pa)}")
    start_ghz, idle, adc_start, ramp, slope = pa[1], pa[2], pa[3], pa[4], pa[7]
    n, fs = int(pa[9]), pa[10]
    if fs <= 0 or slope <= 0 or n <= 0:
        raise CfgError("profileCfg: slope, numAdcSamples and sample rate must be positive")
    sampling_us = n * 1000.0 / fs
    bw = slope * sampling_us
    fc_ghz = start_ghz + (slope * adc_start + bw / 2) / 1e3
    lam = C / (fc_ghz * 1e9)
    tc = idle + ramp

    adc = cfg.first("adcCfg")
    adc_fmt = int(adc.floats()[1]) if adc and len(adc.args) >= 2 else 1
    bps = 2 if adc_fmt == 0 else 4    # real = 16 bit; complex = 16 bit I + 16 bit Q
    if adc is None:
        notes.append("no adcCfg: assuming complex 16-bit samples")

    ch = _need(cfg, "channelCfg").floats()
    if cascade:
        if len(ch) < 5:
            raise CfgError("cascade channelCfg needs 5 fields")
        n_rx = popcount(int(ch[0])) + popcount(int(ch[3]))
    else:
        n_rx = popcount(int(ch[0]))
    if n_rx == 0:
        raise CfgError("channelCfg enables no RX channel")

    fr = frame_layout(cfg, cascade)
    chirps_per_loop = fr["end"] - fr["start"] + 1
    if chirps_per_loop < 1 or fr["loops"] < 1:
        raise CfgError("frameCfg: need at least one chirp and one loop")
    masks = chirp_tx_masks(cfg, fr["start"], fr["end"])
    missing = [i for i in range(fr["start"], fr["end"] + 1) if i not in masks]
    if missing:
        raise CfgError(f"frameCfg uses chirp(s) {missing} with no chirpCfg")
    used = 0
    for m in masks.values():
        used |= m
    if cascade:
        n_tx = popcount(int(ch[1])) + popcount(int(ch[4]))
        n_az = n_tx * n_rx
        notes.append("cascade azimuth aperture assumes a uniform half-wavelength virtual array (unverified)")
    else:
        n_tx = popcount(used)
        n_az = max(1, popcount(used & SINGLE_CHIP_AZ_TX_MASK)) * n_rx
        notes.append("azimuth resolution assumes TX1/TX3 azimuth pair at the EVM layout; "
                     "6843 ODS/AOP antenna layouts differ (unverified)")
    n_virtual = n_tx * n_rx

    n_chirps = chirps_per_loop * fr["loops"]
    loop_us = chirps_per_loop * tc
    # DDMA recovers the full +-lambda/(4 Tc) span; TDM is limited by the per-TX loop period.
    max_v = lam / (4 * tc * 1e-6) if cascade else lam / (4 * loop_us * 1e-6)
    vel_res = lam / (2 * n_chirps * tc * 1e-6)
    ideal = C * fs * 1e3 / (2 * slope * 1e12)
    if adc_fmt == 0:
        ideal /= 2                    # real-only sampling: only fs/2 of IF band
    range_res = C / (2 * bw * 1e6)
    # FUTURE(gui-12): real per-board antenna geometry (6843 ODS/AOP, 2-chip cascade) instead of the uniform half-wavelength virtual array
    az_res = math.degrees(2.0 / n_az)

    active_ms = n_chirps * tc * 1e-3
    period = fr["period_ms"]
    lv = cfg.first("lvdsStreamCfg")
    lv_fmt = int(lv.floats()[2]) if lv and len(lv.args) >= 3 else None
    meta = LVDS_DATAFMT2_META_BYTES if lv_fmt == 2 else 0
    per_chirp = n * n_rx * bps + meta
    per_frame = per_chirp * n_chirps

    return Metrics(
        mode="ddma" if cascade else "tdm", board=board or "",
        start_ghz=start_ghz, slope_mhz_us=slope, idle_us=idle, adc_start_us=adc_start, ramp_us=ramp,
        num_samples=n, sample_rate_ksps=fs, bandwidth_mhz=bw, sweep_mhz=slope * ramp,
        center_ghz=fc_ghz, chirp_us=tc, sampling_us=sampling_us,
        n_rx=n_rx, n_tx=n_tx, n_virtual=n_virtual, n_az_virtual=n_az,
        chirps_per_loop=chirps_per_loop, n_loops=fr["loops"], n_chirps=n_chirps,
        range_res_m=range_res, max_range_m=USABLE_IF * ideal, max_range_ideal_m=ideal,
        velocity_res_ms=vel_res, max_velocity_ms=max_v, azimuth_res_deg=az_res,
        frame_period_ms=period, frame_rate_hz=1000.0 / period if period > 0 else 0.0,
        active_ms=active_ms, duty_cycle=active_ms / period if period > 0 else float("inf"),
        bytes_per_sample=bps, bytes_per_chirp=per_chirp, bytes_per_frame=per_frame,
        avg_data_rate_mbps=per_frame * 8 / (period * 1e3) if period > 0 else 0.0,
        burst_rate_mbps=fs * 1e3 * n_rx * bps * 8 / 1e6,
        chirp_avg_rate_mbps=per_chirp * 8 / tc, lvds_data_fmt=lv_fmt,
        num_frames=fr["frames"], notes=notes)
