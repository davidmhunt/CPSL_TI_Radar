#!/usr/bin/env python3
"""Stand-in for CPSL_TI_Radar_CPP in radar_gui tests (no hardware).

argv: <system.json> [--validate] [--stats] [--frames N] [--duration S]
Mode comes from FAKE_DRIVER_MODE (default "run"): run | crash | ignore-sigint | validate-invalid |
write-bin | stall.  FAKE_DRIVER_RATE (frames/s, default 20), FAKE_DRIVER_BPF (bytes/frame, default 1000),
FAKE_DRIVER_PERIOD_MS (default 100). FAKE_DRIVER_CLI=debug|info|ok (or by-config: ok when the config name contains "_ok", else debug) replays the board command transcript of
tests/fixtures/cli_<kind>_run.txt (stats lines dropped) right after "Using config", ending in a rejected sensorStart.
"""
import os
import signal
import sys
import time

mode = os.environ.get("FAKE_DRIVER_MODE", "run")
rate = float(os.environ.get("FAKE_DRIVER_RATE", "20"))
bpf = int(os.environ.get("FAKE_DRIVER_BPF", "1000"))
period = int(os.environ.get("FAKE_DRIVER_PERIOD_MS", "100"))
args = sys.argv[1:]
cfg = next((a for a in args if not a.startswith("-")), "")


def opt(name, cast):
    return cast(args[args.index(name) + 1]) if name in args else None


if "--validate" in args:
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

print(f"Using config: {cfg}", flush=True)
if os.environ.get("FAKE_DRIVER_CLI"):
    kind = os.environ["FAKE_DRIVER_CLI"]
    if kind == "by-config":
        kind = "ok" if "_ok" in os.path.basename(cfg) else "debug"
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "fixtures", f"cli_{kind}_run.txt")
    with open(fx, newline="") as f:
        for ln in f.read().split("\n"):
            if ln and not ln.startswith(("stats v1", "Using config")):
                print(ln.replace("\r", "\r"), flush=True)
binf = open("adc_data.bin", "wb") if mode == "write-bin" else None
frames, t0, last_print, limit_f, limit_s = 0, time.monotonic(), -1.0, opt("--frames", int), opt("--duration", float)


def stats():
    t = time.monotonic() - t0
    print(f"stats v1 dca t={t:.3f} frames={frames} packets={frames * 10} dropped=0 drop_events=0 late=0 duplicate=0 "
          f"incomplete=0 skipped=0 overrun=0 overwritten=0 stalls=0 rcvbuf=1048576 kernel_drops=0 ring_full=0 "
          f"implausible=0 resyncs=0", flush=True)
    print(f"stats v1 serial t={t:.3f} frames={frames} missed=0 overwritten=0 stalls=0", flush=True)


while not stop["flag"]:
    time.sleep(1.0 / rate)
    t = time.monotonic() - t0
    if mode != "stall":
        frames += 1
        if binf:
            binf.write(b"\0" * bpf)
    if mode == "crash" and t > 0.3:
        print("error: lost the DCA1000 stream", file=sys.stderr, flush=True)
        sys.exit(3)
    if t - last_print >= 0.2:  # fast stats cadence so tests finish quickly
        stats()
        last_print = t
    if (limit_f and frames >= limit_f) or (limit_s and t >= limit_s):
        break
if binf:
    binf.close()
stats()
print("Stopped.", flush=True)
sys.exit(0)
