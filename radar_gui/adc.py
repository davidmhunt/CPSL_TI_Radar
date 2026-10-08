"""ADC views from the driver tap (gui-07): range profile, range-Doppler, range-azimuth, raw ADC diagnostics.

Hand-written numpy; no dependency on mmwave_radar_processing. The input is a tap `adc` message (radar_gui/tap.py):
header {"index","shape":[rx,samples,chirps],"missing_bytes","layout":"rx,sample,chirp","iq_order":"IQ"} + int16 (I,Q)
pairs flattened [rx][sample][chirp], chirp fastest. Chirp c of a frame = loop c // cpl, TX slot c % cpl.

Conventions (all pinned by tests/test_radar_gui_adc.py against hand-computed bins):
  * Range FFT of a complex sample stream: positive IF only, all N bins shown. A reflector at bin k with I and Q
    swapped appears at N-k.
  * Doppler: FFT over loops, fftshifted, bin D/2 = 0. A signal exp(+j w l) (range increasing, "receding") peaks at a
    positive bin, matching the Live cloud's "+ = receding".
  * Angle: the azimuth virtual array is the azimuth-TX slots x RX in TX order, position m = slot_index * n_rx + rx,
    element spacing lambda/2. A target at +theta (toward +x) gives element phase +pi*m*sin(theta) on the hardware (element index
    grows toward -x), so the angle FFT is mirrored (`az_sign_for(board)` = -1) to put +theta = right = +x, like the Live cloud.
    BENCH-CONFIRMED for the IWR1843 only (2026-10-07, bench_1843_dca); see AZ_SIGN_BY_BOARD.
"""
from __future__ import annotations

import json
import math
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

import importlib

from .cfg import firmware as fwmod
mt = importlib.import_module("radar_gui.cfg.metrics")   # `radar_gui.cfg.metrics` the module (the package re-exports the function)
from .cfg.parse import Cfg, CfgError, parse_cfg_file

# Azimuth sign: +1 = element index grows toward +x, -1 = toward -x (the angle axis is mirrored so right = +angle = +x).
# BENCH RESULT (user, 2026-10-07, IWR1843 + DCA1000, bench_1843_dca, Raw ADC tab): the firmware point cloud puts left at
# -x (right = +x) but the unflipped range-azimuth showed right as a negative angle, i.e. the IWR1843 element index grows
# toward -x -> -1. Only the IWR1843 is bench-confirmed; the other boards are ASSUMED to share the TI single-chip
# EVM antenna layout (same RX/TX ordering) and are not verified. There is no per-board sign in config/boards/*.json,
# so it lives here keyed by board name; confirm each other board on the bench and add it.
AZ_SIGN_BY_BOARD = {"IWR1843": -1}      # bench-confirmed
AZ_SIGN_DEFAULT = -1                    # ASSUMPTION for IWR1443 / IWR6843 / unknown boards (not bench-verified)
ANGLE_BINS = 64             # zero-padded angle FFT size
FULL_SCALE = 32768.0
DB_FLOOR = 1e-3             # added to power before 10*log10
DYN_DB = 60.0               # heatmap window below the peak
MAX_POOL = 256              # heatmap axes above this are max-pooled down
MAX_PROFILE = 1024
MAX_SERIES = 512
LAYOUT = "rx,sample,chirp"

MSG_NO_RUN = "ADC views need a driver run with the DCA1000 (Radar tab)"
MSG_NO_TAP = "driver has no live tap / no ADC tap (rebuild the driver)"
MSG_NO_DCA = "this run has no DCA1000 stream"
MSG_OFF = "ADC views off for this run"
MSG_WAIT = "waiting for ADC frames…"


def az_sign_for(board: str | None) -> int:
    return AZ_SIGN_BY_BOARD.get(board or "", AZ_SIGN_DEFAULT)


def pow2(x: int) -> int:
    return 1 if x <= 1 else 1 << (x - 1).bit_length()


class AdcError(ValueError):
    """A frame the processor rejects (counted, never raised past the processor)."""


# ---- geometry ---------------------------------------------------------------------------------------------
@dataclass
class Geometry:
    n_rx: int
    n_samples: int
    n_loops: int
    cpl: int                         # chirps (TX slots) per loop
    slot_masks: list[int]
    az_slots: list[int]              # slot indices of the azimuth TX, in TX order
    range_res_m: float               # one bin of an n_samples-point range FFT
    loop_period_s: float             # revisit period of one TX (TDM n_TX * Tc)
    lambda_m: float
    doppler_bins: int
    frame_rate_hz: float
    board: str = ""
    az_sign: int = AZ_SIGN_DEFAULT   # see AZ_SIGN_BY_BOARD
    ra_reason: str = ""              # non-empty = the range-azimuth view is disabled, with the reason
    notes: list[str] = field(default_factory=list)

    @property
    def n_chirps(self) -> int:
        return self.n_loops * self.cpl

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.n_rx, self.n_samples, self.n_chirps)

    @property
    def ra_enabled(self) -> bool:
        return not self.ra_reason

    @property
    def velocity_step_ms(self) -> float:
        return self.lambda_m / (2 * self.doppler_bins * self.loop_period_s)

    @classmethod
    def from_cfg(cls, cfg: Cfg, board: str | None = None) -> "Geometry":
        m = mt.metrics(cfg, board or None)
        if board == mt.CASCADE:
            raise CfgError("cascade raw ADC is not supported by the ADC views")
        masks = [e["tx_mask"] for e in m.chirp_sequence]
        ebit = fwmod.elevation_tx_bit(board) if board else 0b010
        azm = mt.az_tx_mask(ebit)
        az_slots = [i for i, k in enumerate(masks) if k & azm and not (k & ebit)]
        reason = ""
        if m.scheme == "ddma":
            reason = "range-azimuth is not available for DDMA"
        elif m.bpm_enabled:
            reason = "range-azimuth is not available for BPM"
        elif board == "IWR6843ODS":
            reason = "range-azimuth is not available for the IWR6843ODS (not a half-wavelength line)"
        elif len(az_slots) * m.n_rx < 2:
            reason = "range-azimuth needs at least 2 azimuth virtual channels"
        return cls(n_rx=m.n_rx, n_samples=m.num_samples, n_loops=m.n_loops, cpl=m.chirps_per_loop, slot_masks=masks,
                   az_slots=az_slots, range_res_m=m.range_res_m, loop_period_s=m.loop_period_us * 1e-6,
                   lambda_m=m.lambda_mm * 1e-3, doppler_bins=pow2(m.n_loops), frame_rate_hz=m.frame_rate_hz,
                   board=board or "", az_sign=az_sign_for(board), ra_reason=reason, notes=list(m.notes))

    @classmethod
    def from_system_json(cls, path) -> "Geometry":
        p = Path(path)
        d = json.loads(p.read_text())
        cfg = parse_cfg_file((p.parent / d["radar_cfg"]).resolve())
        return cls.from_cfg(cfg, d.get("board"))


# ---- decode -----------------------------------------------------------------------------------------------
def decode(head: dict, data: bytes, geom: Geometry | None = None) -> tuple[np.ndarray, bool]:
    """(int16 array [rx, samples, chirps, 2], partial) from a tap adc message; AdcError for anything malformed.
    `partial` = missing_bytes > 0 (the frame is still processed)."""
    try:
        rx, ns, nc = (int(v) for v in head["shape"])
    except (KeyError, TypeError, ValueError):
        raise AdcError("bad shape in the adc header") from None
    if head.get("layout") != LAYOUT:
        raise AdcError(f"unsupported layout {head.get('layout')!r} (expected {LAYOUT!r})")
    if head.get("iq_order") != "IQ":
        raise AdcError(f"unsupported iq_order {head.get('iq_order')!r} (expected 'IQ')")
    if min(rx, ns, nc) < 1 or len(data) != 4 * rx * ns * nc:
        raise AdcError(f"payload is {len(data)} bytes, shape {[rx, ns, nc]} needs {4 * rx * ns * nc}")
    if geom is not None and (rx, ns, nc) != geom.shape:
        raise AdcError(f"frame shape {[rx, ns, nc]} (rx, samples, chirps) differs from the cfg's {list(geom.shape)}")
    a = np.frombuffer(data, dtype="<i2").reshape(rx, ns, nc, 2)
    return a, int(head.get("missing_bytes", 0) or 0) > 0


# ---- pooling / quantising ---------------------------------------------------------------------------------
def maxpool(a: np.ndarray, axis: int, limit: int) -> tuple[np.ndarray, int]:
    """Max-pool `axis` down to <= limit cells (max, not mean, so peaks survive). Returns (array, factor)."""
    n = a.shape[axis]
    if n <= limit:
        return a, 1
    f = -(-n // limit)
    pad = (-n) % f
    if pad:
        w = [(0, 0)] * a.ndim
        w[axis] = (0, pad)
        a = np.pad(a, w, mode="constant", constant_values=a.min())
    s = list(a.shape)
    s[axis:axis + 1] = [a.shape[axis] // f, f]
    return a.reshape(s).max(axis=axis + 1), f


def to_u8(db: np.ndarray, dyn: float = DYN_DB) -> tuple[np.ndarray, float, float]:
    hi = float(db.max())
    lo = hi - dyn
    q = np.clip((db - lo) / dyn, 0.0, 1.0) * 255.0
    return (q + 0.5).astype(np.uint8), lo, hi


def _db(p: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(p + DB_FLOOR)


# ---- processing -------------------------------------------------------------------------------------------
def hann(n: int) -> np.ndarray:
    return np.hanning(n + 2)[1:-1].astype(np.float32) if n > 1 else np.ones(1, np.float32)


def diagnostics(a: np.ndarray, clip_level: int = 32767, chirp: int = 0) -> dict:
    """Per-RX raw-ADC numbers from the int16 cube [rx, samples, chirps, 2]."""
    x = a.astype(np.int32)
    rx = x.shape[0]
    rows, bars = [], []
    chirp = min(max(int(chirp), 0), x.shape[2] - 1)
    for r in range(rx):
        i, q = x[r, :, :, 0], x[r, :, :, 1]
        pk_i, pk_q = int(np.abs(i).max()), int(np.abs(q).max())
        peak = max(pk_i, pk_q)
        bits = min(16, math.ceil(math.log2(peak + 1)) + 1)
        pi, pq = float((i.astype(np.float64) ** 2).mean()), float((q.astype(np.float64) ** 2).mean())
        rms = math.sqrt((pi + pq) / 2.0)
        mag = np.abs(x[r])
        clipped = int((mag >= clip_level).sum())
        rows.append({"rx": r, "peak_i": pk_i, "peak_q": pk_q, "bits": bits,
                     "rms_dbfs": 20 * math.log10(max(rms, 1e-9) / FULL_SCALE),
                     "dc_i": float(i.mean()), "dc_q": float(q.mean()),
                     "iq_ratio_db": 10 * math.log10(max(pi, 1e-9) / max(pq, 1e-9)), "clipped": clipped})
        flat = mag.ravel()
        bars.append([float((flat >= (1 << b)).mean()) for b in range(16)])
    ts = a[:, :, chirp, :]                      # [rx, samples, 2]
    step = -(-ts.shape[1] // MAX_SERIES)
    ts = np.ascontiguousarray(ts[:, ::step, :].transpose(0, 2, 1))   # [rx, 2 (I,Q), n]
    return {"rows": rows, "bars": bars, "series": ts.astype("<i2"), "series_step": step, "chirp": chirp}


@dataclass
class Result:
    header: dict
    arrays: list[tuple[str, np.ndarray]]


def process(a: np.ndarray, geom: Geometry, opts: dict | None = None) -> Result:
    """All views of one int16 cube [rx, samples, chirps, 2]. Raises AdcError on a shape the geometry does not match."""
    opts = opts or {}
    rx, ns, nc, _ = a.shape
    if (rx, ns, nc) != geom.shape:
        raise AdcError(f"frame shape {[rx, ns, nc]} (rx, samples, chirps) differs from the cfg's {list(geom.shape)}")
    nl, cpl = geom.n_loops, geom.cpl
    x = (a[..., 0].astype(np.float32) + 1j * a[..., 1].astype(np.float32)).astype(np.complex64)
    nf = pow2(ns)
    r = np.fft.fft(x * hann(ns)[None, :, None], n=nf, axis=1)            # [rx, nf, chirps]
    r = r.reshape(rx, nf, nl, cpl)
    if opts.get("clutter"):
        r = r - r.mean(axis=2, keepdims=True)
    p = (r.real ** 2 + r.imag ** 2)
    prof_db = _db(p.mean(axis=(0, 2, 3)))                                 # [nf]
    k = int(np.argmax(prof_db))
    # image ratio: the peak bin (folded into the lower half, positive IF = real ranges) against its mirror N-k. Large positive =
    # healthy; negative = I and Q swapped (the energy sits at N-k) or a target beyond half the range.
    kl = min(k, nf - k) if k else 0
    image_ratio = float(prof_db[kl] - prof_db[(nf - kl) % nf])
    bin_m = geom.range_res_m * ns / nf

    # range-Doppler: FFT over loops per virtual channel (TX slot x RX), power summed over the channels
    dn = geom.doppler_bins
    d = np.fft.fftshift(np.fft.fft(r * hann(nl)[None, None, :, None], n=dn, axis=2), axes=2)
    rd = (d.real ** 2 + d.imag ** 2).sum(axis=(0, 3)).T                  # [dn, nf]
    rd_db = _db(rd)
    rdp, rd_f = maxpool(rd_db, 1, MAX_POOL)
    rd_u8, rd_lo, rd_hi = to_u8(rdp)
    ki, kj = np.unravel_index(int(np.argmax(rd_db)), rd_db.shape)

    arrays = [("profile", prof_db.astype("<f4")[:MAX_PROFILE]), ("rd", rd_u8)]
    head = {
        "kind": "frame",
        "range_step_m": bin_m, "range_bins": int(nf), "profile_peak_bin": k, "profile_peak_db": float(prof_db[k]),
        "image_ratio_db": image_ratio,
        "rd": {"shape": list(rd_u8.shape), "min": rd_lo, "max": rd_hi, "range_step_m": bin_m * rd_f,
               "vel_step_ms": geom.velocity_step_ms, "vel_zero_bin": dn // 2, "peak": [int(ki), int(kj)]},
    }
    if geom.ra_enabled:
        az = geom.az_slots
        v = r[:, :, :, az]                                                # [rx, nf, nl, na]
        v = v.transpose(2, 1, 3, 0).reshape(nl, nf, len(az) * rx)         # position m = slot_index * rx + rx
        ang = np.fft.fftshift(np.fft.ifft(v, n=ANGLE_BINS, axis=2) * v.shape[2], axes=2)
        ra = (ang.real ** 2 + ang.imag ** 2).sum(axis=0).T                # [ANGLE_BINS, nf]
        if geom.az_sign < 0:
            ra = np.roll(ra[::-1], 1, axis=0)         # mirror about the zero bin: j -> (A - j) % A (a bare [::-1] would shift by one)
        ra_db = _db(ra)
        rap, ra_f = maxpool(ra_db, 1, MAX_POOL)
        ra_u8, ra_lo, ra_hi = to_u8(rap)
        ai, aj = np.unravel_index(int(np.argmax(ra_db)), ra_db.shape)
        arrays.append(("ra", ra_u8))
        head["ra"] = {"shape": list(ra_u8.shape), "min": ra_lo, "max": ra_hi, "range_step_m": bin_m * ra_f,
                      "sin_zero_bin": ANGLE_BINS // 2, "sin_step": 2.0 / ANGLE_BINS, "peak": [int(ai), int(aj)]}
    else:
        head["ra"] = None
        head["ra_reason"] = geom.ra_reason
    dg = diagnostics(a, int(opts.get("clip_level", 32767)), int(opts.get("chirp", 0)))
    head["diag"] = {"rows": dg["rows"], "bars": dg["bars"], "series_step": dg["series_step"], "chirp": dg["chirp"],
                    "n_chirps": nc, "series_n": int(dg["series"].shape[2])}
    arrays.append(("series", dg["series"]))
    return Result(head, arrays)


def encode(res: Result, extra: dict | None = None) -> bytes:
    """u32 LE header length, JSON header, then the arrays back to back (offsets/dtypes/shapes listed in the header)."""
    head = dict(res.header)
    if extra:
        head.update(extra)
    meta, blobs, off = [], [], 0
    for name, arr in res.arrays:
        b = np.ascontiguousarray(arr).tobytes()
        meta.append({"name": name, "dtype": {"uint8": "u8", "float32": "f32", "int16": "i16"}[arr.dtype.name],
                     "shape": list(arr.shape), "offset": off, "bytes": len(b)})
        blobs.append(b)
        off += len(b)
    head["arrays"] = meta
    hb = json.dumps(head, separators=(",", ":")).encode()
    return struct.pack("<I", len(hb)) + hb + b"".join(blobs)


def encode_status(state: str, msg: str, extra: dict | None = None) -> bytes:
    hb = json.dumps({"kind": "status", "state": state, "msg": msg, **(extra or {})}, separators=(",", ":")).encode()
    return struct.pack("<I", len(hb)) + hb


# ---- the processor thread ---------------------------------------------------------------------------------
class AdcProcessor:
    """Own thread, 1-slot newest-wins input: a slow FFT drops frames (counted), never stalls the tap reader.
    `on_result(bytes)` receives each encoded message (any thread). Counters feed the ADC tab."""

    def __init__(self, geom: Geometry, on_result=None):
        self.geom, self.on_result = geom, on_result or (lambda b: None)
        self.opts = {"clutter": False, "chirp": 0, "clip_level": 32767}
        self.adc_in = self.adc_shown = self.dropped_gui = self.rejected = 0
        self.partial = False
        self.last_error = ""
        self.last_index = None
        self.index_gaps = 0
        self.proc_ms = deque(maxlen=64)
        self.last_msg: bytes | None = None
        self._slot = None
        self._last_raw = None
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._run, daemon=True, name="adc-proc")

    def start(self):
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self):
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def median_ms(self) -> float | None:
        return float(np.median(self.proc_ms)) if self.proc_ms else None

    def counters(self) -> dict:
        return {"adc_in": self.adc_in, "adc_shown": self.adc_shown, "adc_dropped_gui": self.dropped_gui,
                "adc_rejected": self.rejected, "proc_ms": self.median_ms(), "index_gaps": self.index_gaps,
                "partial": self.partial, "error": self.last_error}

    def submit(self, head: dict, data: bytes):
        """Called by the tap reader thread; never blocks on processing."""
        with self._cv:
            self.adc_in += 1
            idx = head.get("index")
            if isinstance(idx, int):
                if self.last_index is not None and idx > self.last_index + 1:
                    self.index_gaps += idx - self.last_index - 1
                self.last_index = idx
            if self._slot is not None:
                self.dropped_gui += 1
            self._slot = (head, data)
            self._cv.notify()

    def set_options(self, **kw):
        with self._cv:
            for k in ("clutter", "chirp", "clip_level"):
                if k in kw:
                    self.opts[k] = kw[k]
            if self._slot is None and self._last_raw is not None:
                self._slot = self._last_raw          # re-render the newest frame with the new options (not an input)
                self._cv.notify()

    def process_one(self, head: dict, data: bytes, rerender: bool = False) -> bytes | None:
        t0 = time.perf_counter()
        try:
            a, partial = decode(head, data, self.geom)
            res = process(a, self.geom, self.opts)
        except AdcError as e:
            self.rejected += 1
            self.last_error = str(e)
            return None
        self.partial = partial
        self.last_error = ""
        self.proc_ms.append((time.perf_counter() - t0) * 1000.0)
        if not rerender:
            self.adc_shown += 1
        return encode(res, {"index": head.get("index"), "missing_bytes": head.get("missing_bytes", 0),
                            "partial": partial, "shape": list(a.shape[:3]), **self.counters()})

    def _run(self):
        while True:
            with self._cv:
                while self._slot is None and not self._stop:
                    self._cv.wait(0.5)
                if self._stop:
                    return
                item, self._slot = self._slot, None
                rerender = item is self._last_raw     # set_options re-queued the frame already shown
                self._last_raw = item
            msg = self.process_one(*item, rerender=rerender)
            if msg is not None:
                self.last_msg = msg
                try:
                    self.on_result(msg)
                except Exception:
                    pass
