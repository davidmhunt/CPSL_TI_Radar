#!/usr/bin/env python3
"""Run a system config on a radar for N seconds and record a streaming baseline.

Runs the unmodified driver binary (``CPSL_TI_Radar_CPP``) as a subprocess,
parses its verbose stdout, samples its CPU from /proc once per second, sends
SIGINT after N seconds and writes, under ``docs/results/baseline/`` by default:

    <tag>__<config>__rep<k>__<N>s__<UTC stamp>.csv    per-second rows
    <same basename>.json                              provenance sidecar

Existing files are never overwritten.  The raw stdout log and the driver's
output files (adc_data.bin, LVDS_Raw_0.bin, written to its cwd) go to a
per-run directory under ``tools/bench/runs/`` (git-ignored).

Usage (from the repo root):
    uv run tools/bench/bench_run.py <system.json> --seconds 60 --rep 1 \
        --tag baseline_pre_rework
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_lib as lib  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DRIVER = REPO / "CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP"
DEFAULT_OUT = REPO / "docs/results/baseline"
RUNS = Path(__file__).resolve().parent / "runs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sh(cmd: list, cwd=REPO) -> str:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception as exc:  # best effort only
        return f"unavailable ({exc.__class__.__name__})"


def read_text(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return "unavailable"


def nic_info(system_ip: str | None) -> dict:
    """Passive reads only: which interface holds system_ip and its settings."""
    info = {"system_ip": system_ip, "interface": None}
    if not system_ip:
        return info
    for line in sh(["ip", "-o", "-4", "addr", "show"]).splitlines():
        parts = line.split()
        if len(parts) > 3 and parts[3].split("/")[0] == system_ip:
            info["interface"] = parts[1]
    ifc = info["interface"]
    if ifc:
        base = f"/sys/class/net/{ifc}"
        info.update(
            mtu=read_text(f"{base}/mtu"), speed_mbps=read_text(f"{base}/speed"),
            operstate=read_text(f"{base}/operstate"),
            driver=os.path.basename(os.path.realpath(f"{base}/device/driver"))
            if os.path.exists(f"{base}/device/driver") else "unavailable",
            ethtool_ring=sh(["ethtool", "-g", ifc]),
        )
    return info


def provenance(args, cfg_path: Path, cfg: dict, radar_cfg: Path, expected: dict,
               driver: Path, basename: str) -> dict:
    stream = cfg.get("Streamer", {})
    dca = stream.get("DCA1000_streaming", {})
    return {
        "basename": basename,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "tag": args.tag, "rep": args.rep, "seconds_requested": args.seconds,
        "command_line": sys.argv,
        "commit": sh(["git", "rev-parse", "HEAD"]),
        "branch": sh(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "dirty_driver_or_bench_paths": sh(
            ["git", "status", "--porcelain", "--", "CPSL_TI_Radar_cpp/src",
             "CPSL_TI_Radar_cpp/main.cpp", "tools/bench"]).splitlines(),
        "driver_binary": str(driver),
        "driver_binary_sha256": sha256(driver) if driver.exists() else None,
        "driver_binary_mtime_utc": dt.datetime.fromtimestamp(
            driver.stat().st_mtime, dt.timezone.utc).isoformat(timespec="seconds")
        if driver.exists() else None,
        "system_config": str(cfg_path.relative_to(REPO)) if cfg_path.is_relative_to(REPO) else str(cfg_path),
        "system_config_sha256": sha256(cfg_path),
        "radar_config": str(radar_cfg.relative_to(REPO)) if radar_cfg.is_relative_to(REPO) else str(radar_cfg),
        "radar_config_sha256": sha256(radar_cfg),
        "board": stream.get("board_type"),
        "sdk_version": stream.get("SDK_version"),
        "dca1000_enabled": bool(dca.get("enabled")),
        "serial_enabled": bool(stream.get("serial_streaming", {}).get("enabled")),
        "save_to_file": bool(stream.get("save_to_file")),
        "expected": expected,
        "host": {
            "kernel": platform.release(), "machine": platform.machine(),
            "hostname": platform.node(), "uname": " ".join(platform.uname()),
            "rmem_max": read_text("/proc/sys/net/core/rmem_max"),
            "rmem_default": read_text("/proc/sys/net/core/rmem_default"),
            "netdev_max_backlog": read_text("/proc/sys/net/core/netdev_max_backlog"),
            "cpu_count": os.cpu_count(),
        },
        "nic": nic_info(dca.get("system_IP")) if dca.get("enabled") else {"note": "DCA1000 path not enabled"},
    }


def sample_proc(pid: int):
    try:
        ticks, pages = lib.parse_proc_stat(Path(f"/proc/{pid}/stat").read_text())
    except (OSError, ValueError, IndexError):
        return None
    return ticks, pages * os.sysconf("SC_PAGE_SIZE") // 1024


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("config", type=Path, help="system config .json (verbose must be true)")
    ap.add_argument("--seconds", "-n", type=int, default=60)
    ap.add_argument("--rep", type=int, default=1)
    ap.add_argument("--tag", default="baseline_pre_rework",
                    help="experiment label, first part of the filenames")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--driver", type=Path, default=DEFAULT_DRIVER)
    ap.add_argument("--start-timeout", type=float, default=90.0,
                    help="seconds to wait for the first frame before giving up")
    ap.add_argument("--stop-mode", choices=["sigint", "natural"], default="sigint",
                    help="sigint: signal the driver after N s. natural: do not signal; wait "
                         "for the driver to exit on its own (it quits 2 s after frames stop)")
    ap.add_argument("--allow-non-release", action="store_true",
                    help="run even if the driver build is not CMAKE_BUILD_TYPE=Release "
                         "(sidecar records it; such a run is not a baseline)")
    ap.add_argument("--natural-timeout", type=float, default=120.0)
    args = ap.parse_args(argv)

    cfg_path = args.config.resolve()
    cfg = json.loads(cfg_path.read_text())
    if not cfg.get("verbose"):
        sys.exit("bench: the system config must set \"verbose\": true (stats come from the driver's stdout)")
    stream = cfg.get("Streamer", {})
    dca_on = bool(stream.get("DCA1000_streaming", {}).get("enabled"))
    ser_on = bool(stream.get("serial_streaming", {}).get("enabled"))
    if not (dca_on or ser_on):
        sys.exit("bench: config enables neither DCA1000 nor serial streaming")
    radar_cfg = Path(cfg["TI_Radar_Config_Management"]["TI_Radar_config_path"])
    if not radar_cfg.is_absolute():
        radar_cfg = (cfg_path.parent / radar_cfg).resolve()
    expected = lib.expected_from_radar_cfg(radar_cfg.read_text())
    if not args.driver.exists():
        sys.exit(f"bench: driver binary not found: {args.driver} (build it, see docs/ARCHITECTURE.md)")

    build = lib.parse_cmake_cache(
        (args.driver.resolve().parent / "CMakeCache.txt").read_text()
        if (args.driver.resolve().parent / "CMakeCache.txt").exists() else "")
    if build.get("CMAKE_BUILD_TYPE") != "Release":
        msg = (f"driver build type is {build.get('CMAKE_BUILD_TYPE')!r} "
               f"(from {args.driver.resolve().parent}/CMakeCache.txt), not 'Release'. Rebuild with: "
               "cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build -DCMAKE_BUILD_TYPE=Release "
               "&& cmake --build CPSL_TI_Radar_cpp/build -j")
        if not args.allow_non_release:
            sys.exit("bench: refusing to run: " + msg + " (override: --allow-non-release)")
        print("bench: WARNING: " + msg, file=sys.stderr)
    nframes = lib.frame_cfg_num_frames(radar_cfg.read_text())
    if nframes != 0:
        print(f"bench: WARNING: radar cfg frameCfg numFrames={nframes} (not 0): the radar "
              f"stops after that many frames, a {args.seconds} s run will end early",
              file=sys.stderr)

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    basename = lib.result_basename(args.tag, cfg_path.stem, args.rep, args.seconds, stamp)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, side_path = args.out_dir / f"{basename}.csv", args.out_dir / f"{basename}.json"
    run_dir = RUNS / basename
    run_dir.mkdir(parents=True)
    prov = provenance(args, cfg_path, cfg, radar_cfg, expected, args.driver.resolve(), basename)
    prov["build"] = build
    prov["radar_cfg_numFrames"] = nframes
    prov["non_release_override"] = bool(args.allow_non_release)

    parser, lines = lib.Parser(), queue.Queue()
    launched = time.monotonic()
    log = open(run_dir / "driver_stdout.log", "w")
    proc = subprocess.Popen([str(args.driver.resolve()), str(cfg_path)], cwd=run_dir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            bufsize=1, env={**os.environ, "PYTHONUNBUFFERED": "1"})

    def reader():
        for ln in proc.stdout:
            lines.put((time.monotonic(), ln))
            log.write(ln); log.flush()
        lines.put(None)
    threading.Thread(target=reader, daemon=True).start()

    state = {"done": False}

    def drain(until: float | None = None):
        """Feed queued lines to the parser; True once the stream ended."""
        while not state["done"]:
            try:
                item = lines.get(timeout=0.05 if until is not None else 0.2)
            except queue.Empty:
                if until is None or time.monotonic() >= until:
                    return False
                continue
            if item is None:
                state["done"] = True
                break
            parser.feed(*item)
        return state["done"]

    # wait for the first frame
    t_wait_end = time.monotonic() + args.start_timeout
    t0 = None
    while t0 is None and time.monotonic() < t_wait_end and not state["done"]:
        drain(time.monotonic() + 0.1)
        t0 = lib.first_frame_time(parser.events)
    result_note, sigint_sent = "ok", False
    cpu_samples = []
    if t0 is None:
        result_note = "no frame received before start timeout / driver exit"
    else:
        tck = os.sysconf("SC_CLK_TCK")
        for k in range(0, args.seconds + 1):
            wait_until = t0 + k
            while time.monotonic() < wait_until and not state["done"]:
                drain(wait_until)
            s = sample_proc(proc.pid)
            if s is None:
                result_note = f"driver exited at second {k}"
                break
            cpu_samples.append((time.monotonic(), s[0], tck, s[1]))

    # stop
    if proc.poll() is None:
        if args.stop_mode == "sigint" or t0 is None:
            proc.send_signal(signal.SIGINT)
            sigint_sent = True
            wait_s = 15
        else:
            wait_s = args.natural_timeout
        try:
            proc.wait(timeout=wait_s)
        except subprocess.TimeoutExpired:
            proc.kill(); proc.wait()
            result_note += "; driver killed (did not exit after stop)"
    while not drain(time.monotonic() + 1.0) and proc.poll() is None:
        pass
    drain(time.monotonic() + 0.5)
    parser.finish()
    log.close()

    if t0 is None:
        prov["result"] = {"status": "FAILED", "note": result_note}
        lib.write_sidecar(side_path, prov)
        print(f"bench FAILED: {result_note}; log: {run_dir/'driver_stdout.log'}; sidecar: {side_path}")
        return 2

    nsec = min(args.seconds, max(0, len(cpu_samples) - 1))
    rows = lib.aggregate(parser.events, cpu_samples, t0, nsec)
    summary = lib.summarize(rows)
    dca_events = [e for e in parser.events if e["kind"] == "dca_frame"]
    received = dca_events[-1]["frames_cum"] if dca_events else 0
    result = {"status": "ok" if nsec == args.seconds and result_note == "ok" else "INCOMPLETE",
              "note": result_note, "startup_s": round(t0 - launched, 3),
              "stop": {"mode": args.stop_mode, "sigint_sent": sigint_sent,
                       "exit_code": proc.returncode},
              "granted_so_rcvbuf_bytes": parser.granted_rcvbuf,
              "dca_received_frames_cum_at_exit": received,
              "summary": summary, "driver_warnings_first": parser.warnings[:20]}
    if dca_on and prov["save_to_file"]:
        chk = {}
        for name in ("adc_data.bin", "LVDS_Raw_0.bin"):
            p = run_dir / name
            chk[name] = p.stat().st_size if p.exists() else None
        if chk["adc_data.bin"] is not None:
            result["bin_size_check"] = lib.check_bin_size(
                chk["adc_data.bin"], expected["bytes_per_frame"], received, sigint_sent)
            result["bin_size_check"]["file"] = str(run_dir / "adc_data.bin")
        result["lvds_raw_bytes"] = chk["LVDS_Raw_0.bin"]
    prov["result"] = result
    lib.write_csv(csv_path, rows)
    lib.write_sidecar(side_path, prov)
    print(json.dumps({"csv": str(csv_path), "sidecar": str(side_path),
                      "run_dir": str(run_dir), "result": result}, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
