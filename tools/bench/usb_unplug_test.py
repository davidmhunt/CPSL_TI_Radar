#!/usr/bin/env python3
"""USB-unplug test (core-11 Step 8b): pull the board's USB cable mid-run and
check the driver exits cleanly (exit 1 + 'sensorStop could not be sent'),
not crashing (134/139/negative) or hanging.

Run:  uv run tools/bench/usb_unplug_test.py      (stdlib only, no args needed)
Hardware is single-user: run it only with the bench free.
"""
import argparse, json, os, signal, subprocess, sys, tempfile, threading, time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MSG = "sensorStop could not be sent"
CRASH_CODES = (134, 139)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(REPO / "CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json"))
    ap.add_argument("--driver", default=str(REPO / "CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP"))
    ap.add_argument("--no-stats", action="store_true", help="do not pass --stats (then no frame detection)")
    ap.add_argument("--start-timeout", type=float, default=60, help="s to wait for frames to flow")
    ap.add_argument("--exit-wait", type=float, default=20, help="s to wait for exit after unplug")
    ap.add_argument("--sigint-wait", type=float, default=15)
    a = ap.parse_args()

    driver, config = Path(a.driver).resolve(), Path(a.config).resolve()
    if not driver.is_file() or not os.access(driver, os.X_OK):
        sys.exit(f"REFUSING: driver binary missing/not executable: {driver}")
    if not config.is_file():
        sys.exit(f"REFUSING: config missing: {config}")

    runs = REPO / "tools/bench/runs"
    runs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    wd = Path(tempfile.mkdtemp(prefix=f"usb_unplug_{stamp}_", dir=runs))
    log_path, json_path = wd / "driver.log", wd / "summary.json"
    cmd = [str(driver), str(config)] + ([] if a.no_stats else ["--stats"])
    print(f"workdir: {wd}\nlog:     {log_path}\ncmd:     {' '.join(cmd)}", flush=True)

    lines, lock = [], threading.Lock()
    flowing = threading.Event()
    logf = open(log_path, "w")
    proc = subprocess.Popen(cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", bufsize=1)

    def frames_ok(line):
        if "stats v1" not in line:
            return False
        for tok in line.split():
            if tok.startswith("frames="):
                try:
                    return int(tok[7:]) > 0
                except ValueError:
                    pass
        return False

    def reader():
        for line in proc.stdout:
            logf.write(line); logf.flush()
            with lock:
                lines.append(line.rstrip("\n"))
            if frames_ok(line):
                flowing.set()
        logf.flush()

    t = threading.Thread(target=reader, daemon=True); t.start()

    hang = sigint_sent = False
    unplug_prompted = False
    rc = None
    try:
        t0 = time.time()
        while not flowing.is_set():
            if proc.poll() is not None:
                break
            if time.time() - t0 > a.start_timeout:
                print(f"No frames within {a.start_timeout}s; aborting (SIGINT).", flush=True)
                proc.send_signal(signal.SIGINT); sigint_sent = True
                break
            time.sleep(0.2)
        if flowing.is_set() and proc.poll() is None:
            unplug_prompted = True
            bar = "#" * 60
            print(f"\a\n{bar}\n##   UNPLUG THE BOARD USB CABLE NOW   ##\n{bar}\n", flush=True)
            t1 = time.time(); last_bell = 0
            while proc.poll() is None:
                el = time.time() - t1
                if el > a.exit_wait:
                    print(f"\nDriver still alive {a.exit_wait:.0f}s after prompt: sending SIGINT once.", flush=True)
                    proc.send_signal(signal.SIGINT); sigint_sent = True
                    break
                print(f"  driver running... {el:4.0f}s since prompt (SIGINT at {a.exit_wait:.0f}s) - UNPLUG NOW", flush=True)
                if el - last_bell >= 5:
                    print("\a", end="", flush=True); last_bell = el
                time.sleep(1)
        if sigint_sent:
            try:
                proc.wait(a.sigint_wait)
            except subprocess.TimeoutExpired:
                print("Still alive after SIGINT: SIGKILL -> HANG", flush=True)
                proc.kill(); hang = True; proc.wait()
        else:
            proc.wait()
        rc = proc.returncode
    except KeyboardInterrupt:
        print("\nCtrl-C: killing driver.", flush=True)
        proc.kill(); proc.wait(); rc = proc.returncode
    finally:
        t.join(3); logf.close()
        for f in ("adc_data.bin", "LVDS_Raw_0.bin"):
            try:
                (wd / f).unlink()
            except FileNotFoundError:
                pass

    with lock:
        text = "\n".join(lines)
        tail = lines[-10:]
    msg_found = MSG in text
    crashed = rc is not None and (rc < 0 or rc in CRASH_CODES)
    sig = signal.Signals(-rc).name if rc is not None and rc < 0 else None
    reasons = []
    if not flowing.is_set(): reasons.append("frames never started flowing (nothing to unplug from)")
    if hang: reasons.append("HANG (needed SIGKILL)")
    if sigint_sent and not hang and flowing.is_set(): reasons.append("driver did not exit on its own; needed SIGINT")
    if crashed: reasons.append(f"CRASH (rc={rc}{' ' + sig if sig else ''})")
    if rc != 1 and not crashed and not hang: reasons.append(f"exit code {rc} != 1")
    if not msg_found: reasons.append(f"'{MSG}' not in log")
    verdict = "PASS" if not reasons else "FAIL"

    summary = dict(verdict=verdict, exit_code=rc, signal=sig, crashed=crashed, hang=hang,
                   sigint_sent=sigint_sent, frames_flowed=flowing.is_set(), unplug_prompted=unplug_prompted,
                   clean_error_message=msg_found, reasons=reasons, cmd=cmd, log=str(log_path), time=stamp)
    json_path.write_text(json.dumps(summary, indent=2) + "\n")

    print("\n" + "=" * 60)
    print(f"VERDICT: {verdict}")
    print(f"  exit code:            {rc}   (want 1)")
    print(f"  clean-error message:  {'yes' if msg_found else 'NO'}  ('{MSG}')")
    print(f"  crash/signal:         {'YES ' + str(sig or rc) if crashed else 'no'}  (negative rc, 134, 139)")
    print(f"  hang:                 {'YES' if hang else 'no'}   SIGINT needed: {'yes' if sigint_sent else 'no'}")
    for r in reasons: print(f"  - {r}")
    print("  last log lines:")
    for l in tail: print("    | " + l)
    print(f"log:     {log_path}\nsummary: {json_path}")
    print("=" * 60)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
