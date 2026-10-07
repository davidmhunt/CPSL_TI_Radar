"""generate(board, targets): build a firmware-ready `.cfg` from high-level targets (gui-02 Step 2).

Generalises the solver in `tools/radar_viewer/cfggen.py` (cascade DDMA only) to the single-chip TDM
boards. The boilerplate (everything that is not chirp/frame timing) comes from a shipped cfg of that
board under `CPSL_TI_Radar_cpp/config/radar/`, so the firmware accepts it; only the lines that depend
on the targets are rewritten. Maths (same as `metrics.py`):

    max range     = 0.9 * c * fs / (2 slope)               -> slope from fs and max range
    sampled B     = slope * N / fs ;  range res = c / (2 B) -> N from max range and range res
    TDM velocity  = lambda / (4 * n_tx * Tc)   (n_tx = TX time slots per loop from `metrics.tdm_slots`: distinct
                    azimuth TX + 1 for elevation, 2 for BPM; not the mask popcount)   -> Tc, hence idle time
    DDMA velocity = lambda / (4 * Tc)          (cascade)
    vel. res      = lambda / (2 * chirps * Tc)               -> loops (optional target)

`generate` never raises for an unreachable target: it returns the best-effort cfg (when one can be
built) with `ok=False` and structured issues. Pure Python, a few ms per call.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from . import firmware as fwmod
from .limits import CAS, firmware_limits
from .metrics import BOARDS, C, USABLE_IF, Metrics, az_tx_mask, tdm_slots
from .parse import CfgError, parse_cfg
from .validate import Issue, Report, validate

# Deprecated `output_mode` target -> firmware id (kept so older callers keep working; use `firmware`).
_LEGACY_MODE_FIRMWARE = {"tlv": None, "lvds": "demo", "raw": "dca1000_raw"}   # tlv = the board's default; lvds = demo + lvds target
TARGET_KEYS = ("max_range_m", "max_velocity_ms", "range_res_m", "frame_rate_hz", "velocity_res_ms",
               "num_samples", "num_loops", "tx_mask", "rx_mask", "bpm", "firmware", "output_mode", "lvds", "cfar_range_db",
               "cfar_doppler_db", "name")

# Generator design constants (conservative; the validator holds the real per-board limits).
GEN_MAX_SLOPE = 100.0           # MHz/us: highest slope any shipped cfg reaches (cfggen MAX_SLOPE)
SINGLE_MIN_IDLE_US = 5.0        # shipped single-chip cfgs use >= 5 us (TI documents a min chirp cycle, not an idle minimum)
SINGLE_ADC_START_US = 7.0       # shipped single-chip cfgs
SINGLE_RAMP_MARGIN_US = 2.0     # ramp continues this long after the last sample (shipped: 1.5-8)
CASCADE_RAMP_MARGIN_US = 0.6    # cfggen RAMP_MARGIN_US
SINGLE_MAX_B_MHZ = 3200.0       # default N keeps the sampled bandwidth under this (band is 4 GHz)
DEFAULT_SAMPLES = 128
DEFAULT_CASCADE_SAMPLES = 192
DUTY_PREFERRED = 0.5            # default loop count keeps chirps under half the frame
GUI_MONITOR = "guiMonitor -1 1 0 0 0 0 0 1 1"   # cascade: points + side info (cfggen.GUI_MONITOR)


@dataclass
class GenResult:
    board: str
    ok: bool                         # a cfg was built and the report has no error-level issue
    text: str                        # "" when the targets were unusable (bad input)
    name: str
    targets: dict                    # resolved targets, defaults filled in
    report: Report                   # validate() of `text` + the solver's own issues
    metrics: Metrics | None = None
    achieved: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"board": self.board, "ok": self.ok, "text": self.text, "name": self.name,
                "targets": self.targets, "achieved": self.achieved, "report": self.report.to_dict(),
                "metrics": self.metrics.to_dict() if self.metrics else None}


@lru_cache(maxsize=None)
def _template(rel: str) -> tuple[str, ...]:
    out = []
    for raw in (fwmod.CONFIG_DIR / rel).read_text(errors="replace").splitlines():
        s = raw.split("%", 1)[0].strip()
        if s:
            out.append(s)
    return tuple(out)


def _fail(board: str, targets: dict, issues: list[Issue], name: str = "") -> GenResult:
    return GenResult(board, False, "", name, targets, Report(board, False, issues))


def _num(t: Mapping[str, Any], key: str, default=None, *, positive=True):
    v = t.get(key)
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise CfgError(f"{key}: {v!r} is not a number") from None
    if not math.isfinite(f) or (positive and f <= 0):
        raise CfgError(f"{key}: must be a positive number, got {v!r}")
    return f


def _safe_name(name: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("._") or fallback
    return name if name.endswith(".cfg") else name + ".cfg"


# ---------------------------------------------------------------------------------------------
# chirp solver (generalised from cfggen._solve_chirp)

@dataclass(frozen=True)
class _Prof:
    fs_list: tuple
    min_idle: float
    margin: float
    starts: tuple                    # candidate start frequencies, GHz
    band_hi: float
    adc_start: Any                   # slope -> us
    idle_max: float = 5000.0


def _profile(board: str, lim: dict) -> _Prof:
    lo, hi = lim["band_ghz"].value
    if board == CAS:
        # TI-tested rates first (cfggen), then the rest ascending; lower fs = lower data rate
        tested = tuple(lim["tested_sample_rates_ksps"].value)
        rest = tuple(f for f in range(int(lim["min_sample_rate_ksps"].value),
                                      int(max(tested)) + 1, 250) if f not in tested)   # beyond TI-tested rates: never auto-picked
        return _Prof(tested + rest, lim["min_idle_us"].value, CASCADE_RAMP_MARGIN_US, (77.0, 76.0), hi,
                     lambda s: 6.0 if s >= 20 else 3.0)
    # the template may select low-power ADC mode (lowPower 0 1), so stay under its cap too
    fs_max = int(min(lim["max_sample_rate_ksps"].value, lim.get("lowpower_max_ksps", lim["max_sample_rate_ksps"]).value))
    starts = (lo,) if lo >= 60.0 and hi <= 64.0 else (77.0, lo)
    return _Prof(tuple(range(2000, fs_max + 1, 250)), SINGLE_MIN_IDLE_US,
                 SINGLE_RAMP_MARGIN_US, starts, hi, lambda s: SINGLE_ADC_START_US)


def _design(prof: _Prof, rng: float, n: int, vmax: float, factor: int, max_slope: float) -> list[dict]:
    """One candidate per sample rate with feasibility flags (slope, band, idle)."""
    out = []
    for fs in prof.fs_list:
        slope = round(USABLE_IF * fs * 1e3 * C / (2 * rng) / 1e12, 3)         # MHz/us
        adc = prof.adc_start(slope)
        sampling = n * 1e3 / fs
        ramp = math.ceil((adc + sampling + prof.margin) * 100) / 100
        sweep = slope * ramp
        start = next((s for s in prof.starts if s + sweep / 1e3 <= prof.band_hi), prof.starts[0])
        bw = slope * sampling
        fc_hz = (start * 1e3 + slope * adc + bw / 2) * 1e6
        tc = C / (4 * factor * fc_hz * vmax) * 1e6                             # us
        idle = round(tc - ramp, 2)
        out.append(dict(fs=fs, slope=slope, adc=adc, ramp=ramp, start=start, idle=idle, fc_hz=fc_hz, tc=tc,
                        slope_ok=0 < slope <= max_slope,
                        band_ok=start + sweep / 1e3 <= prof.band_hi,
                        idle_ok=prof.min_idle <= idle <= prof.idle_max))
    return out


# ---------------------------------------------------------------------------------------------

def generate(board: str, targets: Mapping[str, Any] | None = None, *, firmware: str | None = None,
             **kw) -> GenResult:
    """Build a cfg for `board` running `firmware` from `targets` (a dict, or keyword arguments).

    `firmware` is a descriptor id (CPSL_TI_Radar_cpp/config/firmware/); default is the board's default
    firmware. A firmware that does not support the board fails with `firmware_board_mismatch`.

    Targets (SI units; the first two are required):
      max_range_m, max_velocity_ms   what the radar must cover
      range_res_m                    optional; sets the ADC sample count (N = max_range / (0.9 res))
      frame_rate_hz                  default 10
      velocity_res_ms                optional; sets the loop count (chirps per frame)
      num_samples, num_loops         optional explicit overrides (win over range_res_m / velocity_res_ms)
      tx_mask, rx_mask               single chip: TX1..3 / RX1..4 bit masks (default = the board's azimuth pair: TX1+TX3 = 5, ODS TX1+TX2 = 3; RX all = 15). The chirps
                                     are one TX each in TI's azimuth-first order (TX1, TX3, TX2 = masks 1,4,2)
      bpm                            bool, default false (plain TDM, bpmCfg disabled). true: BPM = mask 5 on 2 chirps with
                                     bpmCfg enabled; only where the firmware descriptor says mimo.bpm (else bpm_unsupported)
      lvds                           bool, default false: a TLV firmware (`demo` on 1843/6843) also streams raw ADC over
                                     LVDS (lvdsStreamCfg on). Not available where the firmware has no LVDS output (1443).
      output_mode                    DEPRECATED alias for `firmware` (tlv=board default, lvds=demo + lvds=true, raw=dca1000_raw)
      cfar_range_db, cfar_doppler_db detection thresholds (demo cfgs; not 1443)
      name                           output file name (default derived from the targets)

    Returns a GenResult; unreachable targets give ok=False and issues (level/code/message), not an
    exception. `result.to_dict()` is JSON-safe.
    """
    t_in = dict(targets or {})
    t_in.update(kw)
    issues: list[Issue] = []
    if board not in BOARDS:
        return _fail(str(board), t_in, [Issue("error", "unknown_board", f"unknown board {board!r}; expected one of "
                                              f"{list(BOARDS)}")])
    for k in t_in:
        if k not in TARGET_KEYS:
            issues.append(Issue("warning", "unknown_target", f"unknown target {k!r} ignored"))
    cascade = board == CAS
    fw_in = firmware or t_in.get("firmware")
    mode_in = t_in.get("output_mode")
    if fw_in in (None, "") and mode_in not in (None, ""):
        if str(mode_in).lower() not in _LEGACY_MODE_FIRMWARE:
            return _fail(board, t_in, issues + [Issue("error", "bad_output_mode",
                                                      f"output_mode is deprecated (use firmware); got {mode_in!r}")])
        fw_in = _LEGACY_MODE_FIRMWARE[str(mode_in).lower()]
        if str(mode_in).lower() == "lvds":
            t_in["lvds"] = True
        if fw_in is None and fwmod.default_for(board):
            fw_in = fwmod.default_for(board)["id"]
        issues.append(Issue("info", "output_mode_deprecated", f"output_mode is deprecated; using firmware {fw_in!r}"))
    if fw_in in (None, ""):
        fw = fwmod.default_for(board)
    else:
        fw = fwmod.get(str(fw_in))
        if fw is None:
            return _fail(board, t_in, issues + [Issue("error", "unknown_firmware",
                         f"unknown firmware {fw_in!r}; expected one of {list(fwmod.load_all())}")])
    if fw is None:
        return _fail(board, t_in, issues + [Issue("error", "firmware_board_mismatch", f"no firmware for {board}")])
    if not fwmod.supports(fw, board):
        ok_fw = [d["id"] for d in fwmod.for_board(board)]
        return _fail(board, t_in, issues + [Issue("error", "firmware_board_mismatch",
                     f"{board} does not list firmware {fw['id']!r}; {board} supports: {ok_fw}",
                     f"config/boards/{board}.json", "repo")])
    if fw.get("pending"):
        return _fail(board, t_in, issues + [Issue("error", "firmware_pending",
                     f"firmware {fw['id']!r}: {fw['pending']}", f"config/firmware/{fw['id']}.json", "repo")])
    t_in["firmware"] = fw["id"]
    want_lvds = t_in.get("lvds")
    if isinstance(want_lvds, str):
        want_lvds = want_lvds.strip().lower() in ("1", "true", "yes", "on")
    want_lvds = bool(want_lvds)
    if want_lvds and fwmod.outputs(fw, board)["tlv"] and not fwmod.outputs(fw, board)["lvds"]:
        return _fail(board, t_in, issues + [Issue("error", "lvds_unsupported_by_firmware",
                     f"firmware {fw['id']!r} has no LVDS output on {board}", f"config/firmware/{fw['id']}.json", "repo")])
    mode = fwmod.flavour(fw, board, want_lvds)
    lim = firmware_limits(board, fw["id"])
    try:
        rng = _num(t_in, "max_range_m")
        vmax = _num(t_in, "max_velocity_ms")
        res = _num(t_in, "range_res_m")
        rate = _num(t_in, "frame_rate_hz", 10.0)
        vres = _num(t_in, "velocity_res_ms")
        n_given = _num(t_in, "num_samples")
        loops_given = _num(t_in, "num_loops")
        cfar_r, cfar_d = _num(t_in, "cfar_range_db"), _num(t_in, "cfar_doppler_db")
        tx_mask = int(t_in["tx_mask"]) if t_in.get("tx_mask") not in (None, "") else az_tx_mask(fwmod.elevation_tx_bit(board))
        rx_mask = int(t_in["rx_mask"]) if t_in.get("rx_mask") not in (None, "") else 0b1111
        if rng is None or vmax is None:
            raise CfgError("max_range_m and max_velocity_ms are required")
        if rate > 1000:
            raise CfgError("frame_rate_hz must be at most 1000")
    except (CfgError, TypeError, ValueError) as e:
        return _fail(board, t_in, issues + [Issue("error", "bad_target", str(e))])

    tpl_rel = fw["templates"][board]
    try:
        template = _template(tpl_rel)
    except OSError as e:
        return _fail(board, t_in, issues + [Issue("error", "template_missing", f"cannot read {tpl_rel}: {e}")])

    if cascade:
        if t_in.get("tx_mask") not in (None, "") or t_in.get("rx_mask") not in (None, ""):
            issues.append(Issue("info", "mask_fixed", "cascade DDMA uses all 6 TX x 8 RX; tx_mask/rx_mask ignored"))
        tx_mask, rx_mask = 0b111, 0b1111
    elif not (0 < tx_mask <= 0b111) or not (0 < rx_mask <= 0b1111):
        return _fail(board, t_in, issues + [Issue("error", "bad_mask", "tx_mask must be 1..7 and rx_mask 1..15")])
    want_bpm = t_in.get("bpm")
    if isinstance(want_bpm, str):
        want_bpm = want_bpm.strip().lower() in ("1", "true", "yes", "on")
    want_bpm = bool(want_bpm)
    mm = fwmod.mimo(board, fw)
    if want_bpm and (cascade or mm["scheme"] != "tdm" or not mm.get("bpm")):
        return _fail(board, t_in, issues + [Issue("error", "bpm_unsupported",
                     f"firmware {fw['id']!r} on {board} does not support BPM (descriptor mimo.bpm is false)",
                     f"config/firmware/{fw['id']}.json", mm.get("confidence", "repo"))])
    if cascade:
        chirp_masks, cpl, factor = [], 8, 1             # DDMA: 8 identical chirps, all TX each
    elif want_bpm:
        tx_mask = 0b101
        chirp_masks = [0b101, 0b101]
        cpl = 2
        factor = tdm_slots(chirp_masks, True)[0]
    else:
        ebit = fwmod.elevation_tx_bit(board)                       # ISK 2 -> 1,4,2; ODS 4 -> 1,2,4
        chirp_masks = [b for b in (1, 2, 4) if b != ebit and tx_mask & b] + ([ebit] if tx_mask & ebit else [])  # azimuth first
        cpl = len(chirp_masks)                                     # chirps per loop
        factor = tdm_slots(chirp_masks, False, ebit)[0]                  # n_TX slots: velocity ambiguity multiplier

    # sample count
    note_res = None
    if n_given is not None:
        n = int(n_given)
        if res is not None:
            note_res = "num_samples given: range_res_m is not used to size the ADC window"
    elif res is not None:
        n = int(round(rng / (USABLE_IF * res) / 2)) * 2
    else:   # keep the sampled bandwidth inside the band for short ranges
        n = min(DEFAULT_CASCADE_SAMPLES if cascade else DEFAULT_SAMPLES,
                int(SINGLE_MAX_B_MHZ * 1e6 * 2 * rng / (USABLE_IF * C) // 2) * 2)
    n = max(n, 16)
    if note_res:
        issues.append(Issue("info", "range_res_ignored", note_res))

    prof = _profile(board, lim)
    cands = _design(prof, rng, n, vmax, factor, GEN_MAX_SLOPE)
    feasible = [c for c in cands if c["slope_ok"] and c["band_ok"] and c["idle_ok"]]
    fallback = None
    if not feasible:
        sb = [c for c in cands if c["slope_ok"] and c["band_ok"]]
        if sb:
            c = dict(max(sb, key=lambda c: c["fs"]))
            c["idle"] = prof.min_idle
            c["tc"] = c["ramp"] + c["idle"]
            v_best = C / (4 * factor * c["fc_hz"] * c["tc"] * 1e-6)
            if c["idle_ok"] is False and c["tc"] and v_best < vmax:
                issues.append(Issue("error", "velocity_unreachable",
                                    f"max velocity {vmax:g} m/s needs chirps shorter than {n} samples allow "
                                    f"(best here is about {v_best:.1f} m/s). Lower the max velocity, use fewer "
                                    f"samples (coarser range resolution), or a longer max range."))
            else:   # idle too long (velocity too low)
                issues.append(Issue("warning", "velocity_too_low",
                                    f"max velocity {vmax:g} m/s is below what the idle-time limit can give"))
            fallback = c
        else:
            c = dict(min(cands, key=lambda c: c["fs"]))
            c["idle"] = max(prof.min_idle, c["idle"])
            c["tc"] = c["ramp"] + c["idle"]
            issues.append(Issue("error", "range_unreachable",
                                f"{rng:g} m with {n} samples means {rng / (USABLE_IF * n) * 100:.1f} cm range "
                                f"resolution, which needs more bandwidth than the {prof.starts[-1]:g}-"
                                f"{prof.band_hi:g} GHz band or a slope above {GEN_MAX_SLOPE:g} MHz/us. Use a "
                                f"longer max range or fewer samples."))
            fallback = c
        feasible = [fallback]

    # Try each feasible sample rate (lowest first) and a few loop counts; keep the first clean design.
    best = None
    for cand in feasible[:12]:
        design = _assemble_candidate(board, fw["id"], mode, tpl_rel, template, cand, n, rng, vmax, rate, cpl, tx_mask, rx_mask,
                                     loops_given, vres, cfar_r, cfar_d, cascade, lim, chirp_masks, factor, want_bpm)
        if best is None:
            best = design
        if design["clean"]:
            best = design
            break
    text, report, cand, loops = best["text"], best["report"], best["cand"], best["loops"]

    report.issues = issues + report.issues
    m = report.metrics
    achieved = {}
    if m is not None:
        achieved = dict(max_range_m=m.max_range_m, range_res_m=m.range_res_m, max_velocity_ms=m.max_velocity_ms,
                        velocity_res_ms=m.velocity_res_ms, frame_rate_hz=m.frame_rate_hz,
                        num_samples=m.num_samples, num_loops=m.n_loops, sample_rate_ksps=m.sample_rate_ksps,
                        slope_mhz_us=m.slope_mhz_us)

        def missed(name, got, want, tol):
            if want and abs(got - want) / want > tol and not any(i.code in ("velocity_unreachable",
                                                                          "range_unreachable") for i in issues):
                report.issues.append(Issue("warning", "target_missed",
                                           f"{name}: asked {want:g}, the cfg gives {got:.4g}"))
        missed("max_range_m", m.max_range_m, rng, 0.05)
        missed("max_velocity_ms", m.max_velocity_ms, vmax, 0.05)
        if res is not None and n_given is None:
            missed("range_res_m", m.range_res_m, res, 0.10)
        if vres is not None and loops_given is None:
            missed("velocity_res_ms", m.velocity_res_ms, vres, 0.20)
    report.ok = not any(i.level == "error" for i in report.issues)
    resolved = dict(board=board, bpm=want_bpm, max_range_m=rng, max_velocity_ms=vmax, frame_rate_hz=rate, range_res_m=res,
                    velocity_res_ms=vres, num_samples=n, num_loops=loops, tx_mask=tx_mask, rx_mask=rx_mask,
                    firmware=fw["id"], template=tpl_rel, cfar_range_db=cfar_r, cfar_doppler_db=cfar_d)
    name = _safe_name(str(t_in.get("name") or ""), f"{board.lower().replace('awr2243_', '')}_R{rng:g}m_V{vmax:g}ms_"
                                                   f"{rate:g}Hz".replace(".", "p"))
    return GenResult(board, report.ok, text, name, resolved, report, m, achieved)


def _loop_options(loops_given, vres, cand, cpl, cascade):
    if loops_given is not None:
        return [max(1, int(loops_given))], False
    if vres is not None:
        lam = C / cand["fc_hz"]
        chirps = lam / (2 * vres * cand["tc"] * 1e-6)
        return [max(1, math.ceil(chirps / cpl))], False
    return ([32, 16, 8] if cascade else [128, 64, 32, 16, 8]), True


def _assemble_candidate(board, fw_id, mode, tpl_rel, template, cand, n, rng, vmax, rate, cpl, tx_mask, rx_mask, loops_given,
                        vres, cfar_r, cfar_d, cascade, lim, chirp_masks=(), factor=1, bpm=False) -> dict:
    options, auto = _loop_options(loops_given, vres, cand, cpl, cascade)
    last = None
    for loops in options:
        if cascade:
            text = _cascade_text(template, cand, n, rng, vmax, rate, loops, cfar_r, cfar_d, lim)
        else:
            text = _single_text(board, mode, tpl_rel, template, cand, n, rng, vmax, rate, loops, cpl, tx_mask, rx_mask,
                                cfar_r, cfar_d, chirp_masks, factor, bpm)
        check = text
        if mode == "raw":     # the raw firmware always streams ADC data over LVDS; validate its data rate
            check = text + "\nlvdsStreamCfg -1 0 1 0\n"
        report = validate(parse_cfg(check), board, fw_id)
        m = report.metrics
        codes = {i.code for i in report.issues}
        clean = report.ok and m is not None and m.duty_cycle <= (DUTY_PREFERRED if auto else 0.9) \
            and not codes & {"radar_cube", "adc_buffer", "lvds_rate", "dca_rate", "dca_rate_high"}
        last = dict(text=text, report=report, cand=cand, loops=loops, clean=clean)
        if clean:
            break
    return last


def _frame_period(rate: float, digits: int) -> float:
    return round(1000.0 / rate, digits)


def _profile_line(template, cand, n) -> str:
    tok = next(s for s in template if s.startswith("profileCfg")).split()
    tok[2], tok[3], tok[4], tok[5] = (f"{cand['start']:g}", f"{cand['idle']:g}", f"{cand['adc']:g}",
                                      f"{cand['ramp']:g}")
    tok[8], tok[10], tok[11] = f"{cand['slope']:g}", str(n), str(int(cand["fs"]))
    return " ".join(tok)


def _set_threshold(line: str, db: float | None) -> str:
    if db is None:
        return line
    tok = line.split()
    if len(tok) > 8:
        tok[8] = f"{db:.1f}"          # tok[0] is the command, so args[7] is tok[8]
    return " ".join(tok)


def _single_text(board, mode, tpl_rel, template, cand, n, rng, vmax, rate, loops, cpl, tx_mask, rx_mask, cfar_r, cfar_d,
                 chirp_masks, n_tx, bpm=False):
    period = _frame_period(rate, 2)
    tx_bits = list(chirp_masks)
    chirps = [f"chirpCfg {i} {i} 0 0 0 0 0 {b}" for i, b in enumerate(tx_bits)]
    fc = cand["fc_hz"] / 1e9
    lam = C / cand["fc_hz"]
    tc = cand["idle"] + cand["ramp"]
    rr = C / (2 * cand["slope"] * (n * 1e3 / cand["fs"]) * 1e6)
    max_v = lam / (4 * n_tx * tc * 1e-6)
    out = [f"% Generated by radar_gui.cfg.generate from {tpl_rel} for {board}, {mode} flavour",
           f"% Targets: max range {rng:g} m, max velocity {vmax:g} m/s, {rate:g} Hz",
           f"% Range resolution {rr:.4f} m, max velocity {max_v:.2f} m/s, {n} samples, {loops} loops x {cpl} chirps ({'BPM' if bpm else 'TDM'}, n_TX {n_tx}), "
           f"fs {cand['fs']:g} ksps, slope {cand['slope']:g} MHz/us, centre {fc:.3f} GHz"]
    done = False
    saw_bpm = False
    for s in template:
        cmd = s.split()[0]
        if cmd == "profileCfg":
            out.append(_profile_line(template, cand, n))
        elif cmd == "channelCfg":
            out.append(f"channelCfg {rx_mask} {tx_mask} 0")
        elif cmd == "bpmCfg":
            saw_bpm = True
            out.append("bpmCfg -1 1 0 1" if bpm else "bpmCfg -1 0 0 1")
        elif cmd == "chirpCfg":
            if not done:
                out += chirps
                done = True
        elif cmd == "frameCfg":
            tok = s.split()
            tok[2], tok[3], tok[5] = str(len(tx_bits) - 1), str(loops), f"{period:g}"
            tok[1] = "0"
            out.append(" ".join(tok))
        elif cmd == "lvdsStreamCfg":
            tok = s.split()
            tok[3] = "1" if mode == "lvds" else "0"
            out.append(" ".join(tok))
        elif cmd == "cfarCfg" and board != "IWR1443":
            tok = s.split()
            out.append(_set_threshold(s, cfar_d if tok[2] == "1" else cfar_r))
        elif cmd == "cfarFovCfg" and board != "IWR1443":
            tok = s.split()
            if tok[2] == "0":
                out.append(f"cfarFovCfg {tok[1]} 0 0 {rng:.2f}")
            else:
                out.append(f"cfarFovCfg {tok[1]} 1 {-max_v:.2f} {max_v:.2f}")
        else:
            out.append(s)
    if bpm and not saw_bpm:        # the template has no bpmCfg line: add one after channelCfg
        out.insert(next(i for i, l in enumerate(out) if l.startswith("channelCfg")) + 1, "bpmCfg -1 1 0 1")
    return "\n".join(out) + "\n"


def _cascade_text(template, cand, n, rng, vmax, rate, loops, cfar_r, cfar_d, lim) -> str:
    period = _frame_period(rate, 3)
    chirps = loops * 8
    lam = C / cand["fc_hz"]
    tc = cand["idle"] + cand["ramp"]
    max_v = lam / (4 * tc * 1e-6)
    vel_res = lam / (2 * chirps * tc * 1e-6)
    long_range = rng > 30
    hpf, gain = (2, 42) if long_range else (0, 30)
    slope, fs = cand["slope"], int(cand["fs"])
    profile = (f"profileCfg 0 {cand['start']:g} {cand['idle']:g} {cand['adc']:g} {cand['ramp']:g} 0 0 {slope:g} 0 "
               f"{n} {fs} {hpf} {hpf} {gain}")
    cd = 12.0 if cfar_d is None else cfar_d
    cr = 10.0 if cfar_r is None else cfar_r
    x_lim = min(rng, 30.0)
    replace = {
        "profileCfg": profile,
        "frameCfg": f"frameCfg 0 7 {loops} 0 {n} {period:g} 1 0 2",
        "guiMonitor": GUI_MONITOR,
        "cfarCfg/1": f"cfarCfg -1 1 3 16 0 0 1 {cd:.1f} {1 if long_range else 0} 7 0 1",
        "cfarCfg/0": f"cfarCfg -1 0 3 16 0 0 1 {cr:.1f} 0 7 0 1",
        "localMaxCfg": "localMaxCfg -1 15 40",
        "aoaFovCfg": "aoaFovCfg -1 -85 85 -30 30",
        "appSceneryParams": f"appSceneryParams 0.0 0.0 1.0 0.0 0.0 {-x_lim:.1f} {x_lim:.1f} 0.1 {rng:.1f} -5.0 5.0",
        "gtrack": f"gtrack 1 800 30 0.0 {max_v:.2f} {vel_res:.4f} {2.0 if long_range else 0.5} "
                  f"{10.0 if long_range else 0.5} 0.0 {period / 1000:.3f}",
    }
    out = [f"% Generated by radar_gui.cfg.generate from cascade/cascade_shortrange.cfg (DDMA, 6 TX x 8 RX)",
           f"% Targets: max range {rng:g} m, max velocity {vmax:g} m/s, {rate:g} Hz",
           f"% {n} samples, {chirps} chirps x {tc:.2f} us, fs {fs} ksps, slope {slope:g} MHz/us, "
           f"velocity resolution {vel_res:.4f} m/s"]
    for s in template:
        cmd = s.split()[0]
        key = f"cfarCfg/{s.split()[2]}" if cmd == "cfarCfg" else cmd
        out.append(replace.get(key, s))
    return "\n".join(out) + "\n"
