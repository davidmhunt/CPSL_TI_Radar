#!/usr/bin/env python3
"""Stand-in for CPSL_TI_Radar_CPP in radar_gui tests (no hardware).

argv: <system.json> [--validate] [--stats] [--frames N] [--duration S]
Mode comes from FAKE_DRIVER_MODE (default "run"): run | crash | ignore-sigint | validate-invalid |
write-bin | stall | tap | no-tap.  FAKE_DRIVER_RATE (frames/s, default 20), FAKE_DRIVER_BPF (bytes/frame, default 1000),
FAKE_DRIVER_PERIOD_MS (default 100). FAKE_DRIVER_CLI=debug|info|ok (or by-config: ok when the config name contains "_ok", else debug) replays the board command transcript of
tests/fixtures/cli_<kind>_run.txt (stats lines dropped) right after "Using config", ending in a rejected sensorStart.
Mode "tap" writes the gui-36 live-tap protocol (hello + one points message per frame, adc with --tap-adc-every K) to the
inherited `--tap-fd N`, and its usage text lists --tap-fd; every other mode's usage text does not (an old binary). A config whose
name contains "_die" SIGKILLs itself after FAKE_DRIVER_DIE_S (default 4) seconds (a crashed driver for the page).
Tap ADC messages (--tap-adc-every K): FAKE_DRIVER_ADC=tiny (default, a 2x4x2 ramp) or bench (a synthetic 4x128x256 cube
matching tests/fixtures/adc/bench_1843_dca.*: a mover at range bin 34, Doppler +10, ~20 deg, and a static reflector at bin 60,
0 deg; FAKE_DRIVER_ADC_AMP scales both, e.g. 30000 for clipping). FAKE_DRIVER_STATS_MS (stats cadence, default 200) and FAKE_DRIVER_LOG_LPS (extra debug-style log lines per second,
default 0) imitate a log_level debug run for the GUI lag measurement (gui-09 D8).
"""
import json
import math
import os
import signal
import struct
import sys
import time

mode = os.environ.get("FAKE_DRIVER_MODE", "run")
rate = float(os.environ.get("FAKE_DRIVER_RATE", "20"))
bpf = int(os.environ.get("FAKE_DRIVER_BPF", "1000"))
period = int(os.environ.get("FAKE_DRIVER_PERIOD_MS", "100"))
stats_s = float(os.environ.get("FAKE_DRIVER_STATS_MS", "200")) / 1000.0
log_lps = float(os.environ.get("FAKE_DRIVER_LOG_LPS", "0"))
args = sys.argv[1:]
cfg = next((a for a in args if not a.startswith("-")), "")


def opt(name, cast):
    return cast(args[args.index(name) + 1]) if name in args else None


if "--help" in args or "-h" in args:
    print(f"usage: {sys.argv[0]} <system.json> [--validate] [--stats] [--frames N] [--duration S]" +
          (" [--tap-fd N]" + ("" if os.environ.get("FAKE_DRIVER_NO_ADC_TAP") else " [--tap-adc-every K]") if mode == "tap" else "") +
          (" [--skip-configure]" if os.environ.get("FAKE_DRIVER_SKIP") else ""))
    sys.exit(0)

if "--validate" in args:
    # gui-37: FAKE_DRIVER_KEYS = comma list of the optional system-JSON keys this "build" accepts (default: all; "" = Rebuild 1).
    # A key outside it is "unknown", like the real reader's `<path>: /firmware: unknown key (allowed: ...)`.
    accepted = os.environ.get("FAKE_DRIVER_KEYS", "firmware,firmware_check,save_serial_bytes").split(",")
    try:
        _doc = json.load(open(cfg))
    except (OSError, ValueError):
        _doc = {}
    _used = {"firmware": "firmware" in _doc, "firmware_check": "firmware_check" in (_doc.get("runtime") or {}),
             "save_serial_bytes": "save_serial_bytes" in (_doc.get("output") or {})}
    _path = {"firmware": "/firmware", "firmware_check": "/runtime/firmware_check", "save_serial_bytes": "/output/save_serial_bytes"}
    for _k, _u in _used.items():
        if _u and _k not in accepted:
            print(f"{cfg}: {_path[_k]}: unknown key (allowed: board, cli, ...)", file=sys.stderr)
            print(f"INVALID: {cfg}")
            sys.exit(1)
    if mode == "validate-invalid":
        print(f"config {cfg}: radar_cfg missing", file=sys.stderr)
        print(f"INVALID: {cfg}")
        sys.exit(1)
    print(f"config:     {cfg} (schema v2)")
    print(f"frame:      4 rx x 256 samples x 128 chirps, {period} ms period (cfg fields: rx masks 1, period 5)")
    print(f"bytes/frame: {bpf}")
    print("note:       IWR1843 accepts a cfg once per power-up")
    print(f"OK: {cfg}")
    sys.exit(0)

stop = {"flag": False}
if mode == "ignore-sigint":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
else:
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

print(f"Using config: {cfg}" + (" (skip-configure)" if "--skip-configure" in args else ""), flush=True)
if os.environ.get("FAKE_DRIVER_CLI"):
    kind = os.environ["FAKE_DRIVER_CLI"]
    if kind == "by-config":
        kind = "ok" if "_ok" in os.path.basename(cfg) else "debug"
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "fixtures", f"cli_{kind}_run.txt")
    with open(fx, newline="") as f:
        for ln in f.read().split("\n"):
            if ln and not ln.startswith(("stats v1", "Using config")):
                print(ln.replace("\r", "\r"), flush=True)
tapf = os.fdopen(opt("--tap-fd", int), "wb", buffering=0) if mode == "tap" and "--tap-fd" in args else None
adc_every = opt("--tap-adc-every", int) or 0
if mode == "tap":
    print(f"tap: adc_every={adc_every}", flush=True)
adc_cube = None
if mode == "tap" and adc_every and os.environ.get("FAKE_DRIVER_ADC") == "bench":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import synth_cube
    amp = float(os.environ.get("FAKE_DRIVER_ADC_AMP", "4000"))
    adc_cube = synth_cube.wire(synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.342, "amp": amp},
                                                         {"kr": 60, "kd": 0, "sin": 0.0, "amp": amp * 0.4}], noise=25.0))
tap_ok = {"on": tapf is not None}


def tap_send(kind, payload):
    if not tap_ok["on"]:
        return
    try:
        tapf.write(struct.pack("<IB", len(payload) + 1, kind) + payload)
    except OSError:   # EPIPE: the reader went away; the run continues untapped
        tap_ok["on"] = False


def tap_points(n):
    pts = [[round(math.cos(0.3 * n + k) * (1 + k * .5), 3), round(3 + k * .8 + math.sin(0.3 * n), 3), 0.5, 0.1 * k,
            20.0 + k, 5.0] for k in range(4)]
    tap_send(2, json.dumps({"type": "frame", "frame": n, "n": len(pts), "t": time.time(), "pts": pts}).encode())


if tapf is not None:
    tap_send(1, json.dumps({"version": 1, "board": "IWR1843", "streams": ["points"] + (["adc"] if adc_every else []),
                            "adc_every": adc_every}).encode())
binf = open("adc_data.bin", "wb") if mode == "write-bin" else None
frames, t0, last_print, limit_f, limit_s = 0, time.monotonic(), -1.0, opt("--frames", int), opt("--duration", float)


def stats():
    t = time.monotonic() - t0
    print(f"stats v1 dca t={t:.3f} frames={frames} packets={frames * 10} dropped=0 drop_events=0 late=0 duplicate=0 "
          f"incomplete=0 skipped=0 overrun=0 overwritten=0 stalls=0 rcvbuf=1048576 kernel_drops=0 ring_full=0 "
          f"implausible=0 resyncs=0", flush=True)
    print(f"stats v1 serial t={t:.3f} frames={frames} missed=0 overwritten=0 stalls=0", flush=True)


extra = 0.0
while not stop["flag"]:
    time.sleep(1.0 / rate)
    t = time.monotonic() - t0
    extra += log_lps / rate
    while extra >= 1.0:
        extra -= 1.0
        print(f"[debug] dca packet seq={frames * 10} bytes=1456 ring=3/64 t={t:.4f}", flush=True)
    if mode != "stall":
        frames += 1
        if tapf is not None:
            tap_points(frames - 1)
            if adc_every and (frames - 1) % adc_every == 0:
                if adc_cube is not None:
                    head, body = dict(adc_cube[0], index=frames - 1), adc_cube[1]
                else:
                    head = {"index": frames - 1, "shape": [2, 4, 2], "missing_bytes": 0, "layout": "rx,sample,chirp",
                            "iq_order": "IQ"}
                    body = struct.pack("<32h", *range(32))
                tap_send(3, json.dumps(head).encode() + b"\n" + body)
        if binf:
            binf.write(b"\0" * bpf)
    if mode == "tap" and "_die" in os.path.basename(cfg) and t > float(os.environ.get("FAKE_DRIVER_DIE_S", "4")):
        os.kill(os.getpid(), signal.SIGKILL)
    if mode == "crash" and t > 0.3:
        print("error: lost the DCA1000 stream", file=sys.stderr, flush=True)
        sys.exit(3)
    if t - last_print >= stats_s:  # fast stats cadence so tests finish quickly
        stats()
        last_print = t
    if (limit_f and frames >= limit_f) or (limit_s and t >= limit_s):
        break
if binf:
    binf.close()
stats()
print("Stopped.", flush=True)
sys.exit(0)
