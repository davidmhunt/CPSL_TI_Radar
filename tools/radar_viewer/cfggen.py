"""Chirp-design generator for the AWR2243 2-chip cascade demo (DDMA, 6 TX x 8 RX).

Turns a few targets (max range, max velocity, sample / chirp counts, frame rate, detection
thresholds) into a full cfg, starting from TI's short-range cfg and changing only the lines that
depend on them. The maths matches the firmware's mmwdemo_rfparserDDMA.c:

    range resolution = c * fs / (2 * S * N_samples)       (sampled bandwidth B = S * N / fs)
    max range        = 0.9 * c * fs / (2 * S)             (complex 1x, ~90% of the IF band usable)
    max velocity     = c / (4 * fc * Tc)                  (DDMA demod recovers the full Doppler span)
    vel. resolution  = c / (2 * N_chirps * fc * Tc)       (N_chirps = 8 chirp cfgs x numLoops)

So with the sample count fixed, max range and range resolution move together
(max range = 0.9 * N_samples * resolution), and the same for velocity with the chirp count
(max velocity = N_chirps / 2 * resolution). The counts are the extra knob.
"""
import math
import os
import re
import time

C = 3e8
# TI only tested 192 samples x 256 chirps ("Chirp design is limited to 192 adc samples, 256 chirps").
# Smaller counts shrink the radar cube, so they should fit, but they are untested.
SAMPLE_OPTIONS = (192, 128)
CHIRP_OPTIONS = (256, 128, 64)
TESTED_SAMPLES, TESTED_CHIRPS = 192, 256
CHIRPS_PER_LOOP = 8                 # chirpCfg 0..7 (DDMA phase per chirp)
FS_TESTED_KSPS = (5000, 10000)      # TI's short- and long-range cfgs
FS_MIN_KSPS, FS_MAX_KSPS = 2000, 10000
MAX_SLOPE = 100.0                   # MHz/us
MIN_IDLE_US = 4.0
RAMP_MARGIN_US = 0.6                # ramp keeps going this long after the last sample
BAND_TOP_GHZ = 81.0
USABLE_IF = 0.9

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.normpath(os.path.join(HERE, "..", "..", "CPSL_TI_Radar_cpp", "config", "radar",
                                         "cascade", "cascade_shortrange.cfg"))
CALIB_TEMPLATE = os.path.normpath(os.path.join(HERE, "..", "..", "firmware_dev", "firmware", "cascade",
                                               "src", "demo", "chirp_configs", "cascade_shortrange_calib.cfg"))
OUT_DIR = os.path.join(HERE, "configs")
CALIB_FILE = os.path.join(OUT_DIR, "antenna_calib.txt")
# The viewer and the C++ driver parse type 1 (points) + type 7 (side info); TI's cfgs ask for compact type 12.
GUI_MONITOR = "guiMonitor -1 1 0 0 0 0 0 1 1"

DEFAULTS = {
    "max_range": 15.0, "samples": 192, "max_velocity": 19.4, "chirps": 256, "frame_rate": 20.0,
    "cfar_doppler_db": 12.0, "cfar_range_db": 10.0, "localmax_azim": 15, "localmax_doppler": 40,
    "fov_azim": 85, "fov_elev": 30, "use_calibration": True, "name": "",
}


class CfgError(ValueError):
    pass


def read_lines(path):
    with open(path) as f:
        return [l.rstrip("\r\n") for l in f]


def analyze(lines):
    """Derived numbers for a cfg (as the firmware computes them). Missing pieces are left out."""
    out = {}
    cmds = {}
    for l in lines:
        p = l.split()
        if p and not p[0].startswith("%"):
            cmds.setdefault(p[0], []).append(p)
    try:
        p = cmds["profileCfg"][0]
        start, idle, adc, ramp, slope = float(p[2]), float(p[3]), float(p[4]), float(p[5]), float(p[8])
        n, fs = int(p[10]), float(p[11])
        bw = slope * n / (fs * 1e-3)                                   # MHz sampled
        fc = start * 1e3 + slope * adc + bw / 2                        # MHz
        tc = idle + ramp                                               # us
        out.update(range_res_m=C / (2 * bw * 1e6), max_range_m=USABLE_IF * C * fs * 1e3 / (2 * slope * 1e12),
                   samples=n, fs_ksps=fs, slope=slope, bandwidth_mhz=bw, sweep_mhz=slope * ramp,
                   chirp_us=tc, idle_us=idle, ramp_us=ramp, adc_start_us=adc, start_ghz=start,
                   max_velocity=C / (4 * fc * 1e6 * tc * 1e-6))
        f = cmds["frameCfg"][0]
        chirps = (int(f[2]) - int(f[1]) + 1) * int(f[3])
        out.update(chirps=chirps, vel_res=C / (2 * chirps * fc * 1e6 * tc * 1e-6),
                   frame_period_ms=float(f[6] if len(f) >= 9 else f[5]), active_ms=chirps * tc * 1e-3)
    except (KeyError, IndexError, ValueError, ZeroDivisionError):
        pass
    if "aoaFovCfg" in cmds:
        try:
            out["fov"] = [float(x) for x in cmds["aoaFovCfg"][0][2:6]]
        except ValueError:
            pass
    return out


def _solve_chirp(max_range, n, max_velocity):
    """Pick sample rate, slope and timings that hit max_range and max_velocity with n samples."""
    if max_range <= 0 or max_velocity <= 0:
        raise CfgError("Max range and max velocity must be positive.")
    fs_list = list(FS_TESTED_KSPS) + [f for f in range(FS_MIN_KSPS, FS_MAX_KSPS + 1, 250) if f not in FS_TESTED_KSPS]
    reasons = []
    for fs in fs_list:
        slope = USABLE_IF * fs * 1e3 * C / (2 * max_range) / 1e12          # MHz/us
        if slope > MAX_SLOPE:
            reasons.append(("slope", slope))
            continue
        adc = 6.0 if slope >= 20 else 3.0
        ramp = math.ceil((adc + n / (fs * 1e-3) + RAMP_MARGIN_US) * 100) / 100
        sweep = slope * ramp                                               # MHz
        start = 77.0 if 77.0 + sweep / 1e3 <= BAND_TOP_GHZ else 76.0
        if start + sweep / 1e3 > BAND_TOP_GHZ:
            reasons.append(("band", sweep))
            continue
        bw = slope * n / (fs * 1e-3)
        fc = start * 1e9 + slope * 1e12 * adc * 1e-6 + bw * 1e6 / 2
        tc = C / (4 * fc * max_velocity) * 1e6                             # us
        idle = round(tc - ramp, 2)
        if idle < MIN_IDLE_US:
            reasons.append(("time", ramp + MIN_IDLE_US, C / (4 * fc * (ramp + MIN_IDLE_US) * 1e-6)))
            continue
        if idle > 5000:
            reasons.append(("idle", idle))
            continue
        return dict(fs=fs, slope=round(slope, 3), adc=adc, ramp=ramp, idle=idle, start=start)

    kinds = {r[0] for r in reasons}
    if kinds == {"time"} or ("time" in kinds and kinds <= {"time", "slope", "band"}):
        best = max((r for r in reasons if r[0] == "time"), key=lambda r: r[2])
        raise CfgError(f"Max velocity {max_velocity:g} m/s needs chirps shorter than the {n} samples allow "
                       f"(best here is about {best[2]:.1f} m/s). Lower the max velocity, use fewer samples, "
                       f"or a longer max range.")
    if "band" in kinds or "slope" in kinds:
        res = max_range / (USABLE_IF * n)
        raise CfgError(f"{max_range:g} m with {n} samples means {res * 100:.1f} cm resolution, which needs more "
                       f"than the 76-81 GHz band (or a slope over {MAX_SLOPE:g} MHz/us). Use a longer max range "
                       f"or fewer samples.")
    if "idle" in kinds:
        raise CfgError(f"Max velocity {max_velocity:g} m/s is too low (chirp idle time would exceed 5 ms).")
    raise CfgError("No chirp design fits these targets.")


def load_calibration():
    """Saved antennaCalibParams1..3 lines from a calibration run, or None."""
    if not os.path.exists(CALIB_FILE):
        return None
    lines = [l.strip() for l in read_lines(CALIB_FILE)]
    params = [l for l in lines if l.startswith("antennaCalibParams")]
    if len(params) != 3:
        return None
    return {"lines": params, "comment": " ".join(l.lstrip("% ") for l in lines if l.startswith("%"))}


def save_calibration(result):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(CALIB_FILE, "w") as f:
        f.write(f"% Antenna calibration measured {time.strftime('%Y-%m-%d %H:%M')} with the viewer: "
                f"reflector at {result['range']:.3f} m, peakVal {result['peak']}\n")
        for line in result["lines"]:
            f.write(line + "\n")


def safe_name(name, fallback):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", (name or "").strip()).strip("._")
    name = name or fallback
    return name if name.endswith(".cfg") else name + ".cfg"


def generate(params):
    """Returns {text, derived, warnings, name}. Raises CfgError for impossible targets."""
    p = dict(DEFAULTS)
    p.update({k: v for k, v in params.items() if k in DEFAULTS and v is not None and v != ""})
    try:
        max_range, max_vel, rate = float(p["max_range"]), float(p["max_velocity"]), float(p["frame_rate"])
        n, chirps = int(p["samples"]), int(p["chirps"])
        cfar_d, cfar_r = float(p["cfar_doppler_db"]), float(p["cfar_range_db"])
        lm_az, lm_dop = int(p["localmax_azim"]), int(p["localmax_doppler"])
        fov_az, fov_el = float(p["fov_azim"]), float(p["fov_elev"])
    except (TypeError, ValueError) as e:
        raise CfgError(f"Bad number: {e}")
    if n not in SAMPLE_OPTIONS:
        raise CfgError(f"ADC samples must be one of {SAMPLE_OPTIONS}.")
    if chirps not in CHIRP_OPTIONS:
        raise CfgError(f"Chirps per frame must be one of {CHIRP_OPTIONS}.")
    if not 1 <= rate <= 30:
        raise CfgError("Frame rate must be 1-30 Hz.")
    if not (0 < fov_az <= 90 and 0 < fov_el <= 90):
        raise CfgError("Field of view half-angles must be 1-90 degrees.")

    ch = _solve_chirp(max_range, n, max_vel)
    period = round(1000.0 / rate, 3)
    loops = chirps // CHIRPS_PER_LOOP
    long_range = max_range > 30
    hpf1, hpf2, gain = (2, 2, 42) if long_range else (0, 0, 30)    # TI's long-/short-range front-end settings

    profile = (f"profileCfg 0 {ch['start']:g} {ch['idle']:g} {ch['adc']:g} {ch['ramp']:g} 0 0 {ch['slope']:g} 0 "
               f"{n} {ch['fs']} {hpf1} {hpf2} {gain}")
    frame = f"frameCfg 0 7 {loops} 0 {n} {period:g} 1 0 2"
    derived_lines = [profile, frame]
    derived = analyze(derived_lines)
    x_lim = min(max_range, 30.0)

    calib = load_calibration() if p["use_calibration"] else None
    replace = {
        "profileCfg": profile,
        "frameCfg": frame,
        "guiMonitor": GUI_MONITOR,
        "cfarCfg/1": f"cfarCfg -1 1 3 16 0 0 1 {cfar_d:.1f} {1 if long_range else 0} 7 0 1",
        "cfarCfg/0": f"cfarCfg -1 0 3 16 0 0 1 {cfar_r:.1f} 0 7 0 1",
        "localMaxCfg": f"localMaxCfg -1 {lm_az} {lm_dop}",
        "aoaFovCfg": f"aoaFovCfg -1 {-fov_az:g} {fov_az:g} {-fov_el:g} {fov_el:g}",
        "appSceneryParams": f"appSceneryParams 0.0 0.0 1.0 0.0 0.0 {-x_lim:.1f} {x_lim:.1f} 0.1 {max_range:.1f} -5.0 5.0",
        "gtrack": f"gtrack 1 800 30 0.0 {derived['max_velocity']:.2f} {derived['vel_res']:.4f} "
                  f"{2.0 if long_range else 0.5} {10.0 if long_range else 0.5} 0.0 {period / 1000:.3f}",
    }
    if calib:
        for i, line in enumerate(calib["lines"], 1):
            replace[f"antennaCalibParams{i}"] = line

    out = []
    for line in read_lines(TEMPLATE):
        s = line.strip()
        if not s or s.startswith("%"):
            continue                                          # drop TI's header; we write our own
        cmd = s.split()[0]
        key = f"cfarCfg/{s.split()[2]}" if cmd == "cfarCfg" else cmd
        out.append(replace.get(key, s))

    warnings = []
    if n != TESTED_SAMPLES or chirps != TESTED_CHIRPS:
        warnings.append(f"TI only tested {TESTED_SAMPLES} samples x {TESTED_CHIRPS} chirps; "
                        f"{n} x {chirps} should fit in memory but is untested.")
    if ch["fs"] not in FS_TESTED_KSPS:
        warnings.append(f"Sample rate {ch['fs']} ksps is between TI's tested 5000/10000 ksps.")
    if derived["active_ms"] > period - 5:
        raise CfgError(f"The chirps take {derived['active_ms']:.1f} ms, leaving no time to process a "
                       f"{period:g} ms frame. Lower the frame rate or the chirp count, or raise max velocity.")
    if derived["active_ms"] > period * 0.5:
        warnings.append(f"Chirps take {derived['active_ms']:.1f} of {period:g} ms; TI's cfgs leave more than half "
                        f"the frame for processing. If frames drop, lower the frame rate.")
    if rate > 20:
        warnings.append("Above 20 Hz is untested; with many points the 3.125 Mbaud data port can saturate.")
    if cfar_d < 10 or cfar_r < 8:
        warnings.append("CFAR thresholds this low mostly add noise points; the firmware caps a frame at 800.")
    if p["use_calibration"] and not calib:
        warnings.append("No saved calibration yet, so TI's default antenna calibration is used.")

    header = [
        f"% Generated by radar_viewer/cfggen.py on {time.strftime('%Y-%m-%d %H:%M')} from {os.path.basename(TEMPLATE)}",
        f"% Max Range: {derived['max_range_m']:.2f} m",
        f"% Range resolution : {derived['range_res_m']:.4f} m",
        f"% Max Velocity : {derived['max_velocity']:.2f} m/s",
        f"% Velocity Resolution : {derived['vel_res']:.4f} m/s",
        f"% Frame: {chirps} chirps x {derived['chirp_us']:.2f} us = {derived['active_ms']:.2f} ms active, "
        f"period {period:g} ms ({rate:g} Hz)",
        f"% Antenna calibration: {'saved (' + calib['comment'] + ')' if calib else 'TI default'}",
    ]
    fallback = f"cascade_R{max_range:g}m_V{max_vel:g}ms_{rate:g}Hz".replace(".", "p")
    name = safe_name(p["name"], fallback)
    return {"text": "\n".join(header + out) + "\n", "derived": derived, "warnings": warnings, "name": name,
            "calibrated": bool(calib)}


def write(result):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, result["name"])
    with open(path, "w") as f:
        f.write(result["text"])
    return path


def calibration_cfg(distance, window):
    """TI's calibration cfg, with our reflector distance and point TLVs the viewer can draw."""
    if not 1.0 <= distance <= 12.0 or not 0.1 <= window <= 2.0:
        raise CfgError("Reflector distance must be 1-12 m and the search window 0.1-2 m.")
    out = [f"% Calibration run generated by radar_viewer on {time.strftime('%Y-%m-%d %H:%M')} from "
           f"{os.path.basename(CALIB_TEMPLATE)}: corner reflector at {distance:g} m boresight"]
    for line in read_lines(CALIB_TEMPLATE):
        s = line.strip()
        if not s or s.startswith("%"):
            continue
        cmd = s.split()[0]
        if cmd == "guiMonitor":
            s = GUI_MONITOR
        elif cmd == "measureRangeBiasAndRxChanPhase":
            s = f"measureRangeBiasAndRxChanPhase 1 {distance:g} {window:g}"
        out.append(s)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "calibration_run.cfg")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    return path


if __name__ == "__main__":
    # Sanity check: TI's own short-range numbers should come back out.
    r = generate({"max_range": 15.2, "max_velocity": 19.4})
    d = r["derived"]
    print(r["text"].splitlines()[1:6], r["warnings"])
    print({k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()})
    print(analyze(read_lines(TEMPLATE)))
