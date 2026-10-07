"""Run control for the C++ driver (gui-05): validate, start/stop as a subprocess, live stats and log.

The driver binary is `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` unless `--driver-bin` / `RADAR_GUI_DRIVER`
says otherwise. `stats v1` lines are parsed with `tools/bench/bench_lib.Parser` (not re-implemented here).
"""
from __future__ import annotations

import collections
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .ports import check_ports, radar_lock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "bench"))
import bench_lib  # noqa: E402

DEFAULT_BIN = REPO / "CPSL_TI_Radar_cpp" / "build" / "CPSL_TI_Radar_CPP"
DEFAULT_RUN_ROOT = REPO / "runs" / "gui"
LOG_LINES = 500
_FRAME_RE = re.compile(r"^frame:\s+(\d+) rx x (\d+) samples x (\d+) chirps, ([\d.]+) ms period")
_BPF_RE = re.compile(r"^bytes/frame:\s*(\d+)")


class DriverError(Exception):
    """A refusal; `status` is the HTTP code the API uses (409 busy/state, 422 bad input, 503 no binary)."""

    def __init__(self, msg: str, status: int = 409):
        super().__init__(msg)
        self.status = status


def driver_bin(override: str | None = None) -> Path:
    return Path(override or os.environ.get("RADAR_GUI_DRIVER") or DEFAULT_BIN)


def run_root(override: str | os.PathLike | None = None) -> Path:
    return Path(override or os.environ.get("RADAR_GUI_RUN_DIR") or DEFAULT_RUN_ROOT)


def parse_validate(text: str, exit_code: int) -> dict:
    """ok/exit/text plus bytes/frame, the frame line and `note:` lines, from `--validate` output."""
    out = {"ok": exit_code == 0 and any(ln.startswith("OK:") for ln in text.splitlines()),
           "exit": exit_code, "text": text, "bytes_per_frame": None, "frame": None, "notes": []}
    for ln in text.splitlines():
        if m := _BPF_RE.match(ln):
            out["bytes_per_frame"] = int(m.group(1))
        elif m := _FRAME_RE.match(ln):
            out["frame"] = {"rx": int(m.group(1)), "samples": int(m.group(2)), "chirps": int(m.group(3)),
                            "period_ms": float(m.group(4)), "line": ln.strip()}
        elif ln.startswith("note:"):
            out["notes"].append(ln[5:].strip())
    return out


def load_system_json(path: Path) -> dict:
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise DriverError(f"cannot read system config {path}: {e}", 422)
    if not isinstance(d, dict):
        raise DriverError(f"system config {path} is not a JSON object", 422)
    return d


class DriverManager:
    """At most one driver run at a time; thread-safe. `emit(msg_dict)` receives driver_* messages (any thread)."""

    def __init__(self, bin_override=None, run_root_override=None, lock=radar_lock, emit=None,
                 min_stop_grace: float = 5.0):
        self.bin_override, self.root_override, self.lock = bin_override, run_root_override, lock
        self.emit, self.min_grace = emit or (lambda m: None), min_stop_grace
        self._mu = threading.RLock()
        self._reset()
        self.state = "idle"

    def _reset(self):
        self.proc = None
        self.config = self.run_dir = self.exit_code = self.error = None
        self.stats, self.files, self.bin_verdict, self.forced = {}, [], None, False
        self.log = collections.deque(maxlen=LOG_LINES)
        self.parser = bench_lib.Parser()
        self._prev = {}
        self.expect = {}
        self.sigint_sent = False
        self.t_start = 0.0

    # ---- validate -------------------------------------------------------------------------------
    def _bin(self) -> Path:
        b = driver_bin(self.bin_override)
        if not (b.is_file() and os.access(b, os.X_OK)):
            raise DriverError(f"driver binary not found or not executable: {b} "
                              "(build CPSL_TI_Radar_cpp, or pass --driver-bin / set RADAR_GUI_DRIVER)", 503)
        return b

    def validate(self, config: str | os.PathLike) -> dict:
        b = self._bin()
        try:
            p = subprocess.run([str(b), str(config), "--validate"], capture_output=True, text=True, timeout=30,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            raise DriverError("--validate timed out after 30 s", 503)
        return parse_validate(p.stdout + p.stderr, p.returncode)

    # ---- start / stop ---------------------------------------------------------------------------
    def start(self, config: str | os.PathLike, frames: int | None = None, duration: float | None = None) -> dict:
        config = Path(config).resolve()
        with self._mu:
            if self.state in ("running", "stopping"):
                raise DriverError(f"driver already {self.state}")
            b = self._bin()
            sysjson = load_system_json(config)
            val = self.validate(config)
            if not val["ok"]:
                raise DriverError("config is INVALID:\n" + val["text"].strip(), 422)
            ports = [sysjson.get("cli", {}).get("port")]
            if sysjson.get("serial_stream", {}).get("enabled"):
                ports.append(sysjson["serial_stream"].get("port"))
            ports = [p for p in ports if p]
            if not self.lock.acquire("driver"):
                raise DriverError(f"radar in use by {self.lock.owner}")
            spawned = False
            try:
                if (why := check_ports(ports)):
                    raise DriverError(why)
                out_dir = (sysjson.get("output") or {}).get("dir")
                if out_dir:
                    files_dir = config.parent / out_dir
                    cwd = run_root(self.root_override)
                    cwd.mkdir(parents=True, exist_ok=True)
                else:
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    cwd = run_root(self.root_override) / f"{stamp}_{config.stem}"
                    cwd.mkdir(parents=True, exist_ok=True)
                    files_dir = cwd
                cmd = [str(b), str(config), "--stats"]
                if frames:
                    cmd += ["--frames", str(int(frames))]
                if duration:
                    cmd += ["--duration", str(float(duration))]
                self._reset()
                self.config, self.run_dir, self.files_dir = str(config), str(cwd), files_dir
                self.expect = {"bytes_per_frame": val["bytes_per_frame"],
                               "period_ms": (val["frame"] or {}).get("period_ms")}
                self.t_start = time.time()
                try:
                    self.proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                                 start_new_session=True)
                except OSError as e:
                    self.error = f"cannot start driver: {e}"
                    self._set_state("failed")
                    raise DriverError(self.error, 503)
                spawned = True
            except BaseException:
                if not spawned:
                    self.lock.release("driver")
                raise
            self._set_state("running")
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True, name="driver-pump").start()
            return self.status()

    def stop(self) -> dict:
        with self._mu:
            if self.state != "running":
                raise DriverError(f"driver is {self.state}, not running")
            proc = self.proc
            self.sigint_sent = True
            self._set_state("stopping")
            self._signal(proc, signal.SIGINT)
            period = (self.expect.get("period_ms") or 0) / 1000.0
            grace = max(self.min_grace, 2 * period)
            threading.Thread(target=self._escalate, args=(proc, grace), daemon=True, name="driver-kill").start()
            return self.status()

    @staticmethod
    def _signal(proc, sig):
        try:
            os.killpg(proc.pid, sig)  # own process group (start_new_session)
        except (ProcessLookupError, PermissionError):
            pass

    def _escalate(self, proc, grace):
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.forced = True
            self._signal(proc, signal.SIGKILL)

    def shutdown(self):
        """Server exit: stop a live run, hard-kill it if it ignores that."""
        p = self.proc
        if p is not None and p.poll() is None:
            self._signal(p, signal.SIGINT)
            try:
                p.wait(timeout=max(self.min_grace, 2))
            except subprocess.TimeoutExpired:
                self._signal(p, signal.SIGKILL)

    # ---- reader ---------------------------------------------------------------------------------
    def _pump(self, proc):
        for line in proc.stdout:
            self._line(line.rstrip("\r\n"))
        code = proc.wait()
        with self._mu:
            self._finish(code)

    def _line(self, line):
        t = time.monotonic()
        with self._mu:
            self.log.append(line)
            n = len(self.parser.events)
            self.parser.feed(t, line)
            msg = None
            if len(self.parser.events) > n:
                ev = self.parser.events[-1]
                kind = ev["kind"].split("_")[0]
                prev = self._prev.get(kind)
                rate = None
                if prev:
                    dt = (ev.get("t_driver", t) - prev.get("t_driver", prev["t"])) if "t_driver" in ev else ev["t"] - prev["t"]
                    if dt > 0:
                        rate = (ev.get("frames", 0) - prev.get("frames", 0)) / dt
                self._prev[kind] = ev
                self.stats[kind] = {**{k: v for k, v in ev.items() if k not in ("kind", "t")}, "rate_hz": rate}
                msg = {"type": "driver_stats", "stream": kind, "stats": self.stats[kind]}
        self.emit(msg or {"type": "driver_log", "line": line})
        if msg:
            self.emit({"type": "driver_log", "line": line})

    def _finish(self, code):
        self.exit_code = code
        clean = code == 0 or (self.sigint_sent and code in (-signal.SIGINT, 130))
        if self.forced:
            self.error = "driver did not stop after SIGINT; killed (SIGKILL)"
        elif not clean:
            self.error = f"driver exited with code {code}"
        self.files = self._list_files()
        dca = self.stats.get("dca")
        adc = next((f for f in self.files if f["name"] == "adc_data.bin"), None)
        bpf = self.expect.get("bytes_per_frame")
        if adc and dca and bpf:
            self.bin_verdict = bench_lib.check_bin_size(adc["size"], bpf, dca["frames"], self.sigint_sent)
        self.lock.release("driver")
        self._set_state("exited" if clean and not self.forced else "failed")

    def _list_files(self):
        out = []
        d = Path(self.files_dir)
        if d.is_dir():
            for p in sorted(d.iterdir()):
                try:
                    st = p.stat()
                except OSError:
                    continue
                if p.is_file() and st.st_mtime >= self.t_start - 1:
                    out.append({"name": p.name, "size": st.st_size})
        return out

    def _set_state(self, state):
        self.state = state
        self.emit({"type": "driver_state", **self.status(log=False)})

    # ---- status ---------------------------------------------------------------------------------
    def status(self, log: bool = True) -> dict:
        with self._mu:
            return {"state": self.state, "pid": self.proc.pid if self.proc and self.state in ("running", "stopping") else None,
                    "config": self.config, "run_dir": self.run_dir, "exit_code": self.exit_code,
                    "error": self.error, "stats": dict(self.stats), "log": list(self.log)[-100:] if log else [],
                    "files": list(self.files), "bin_verdict": self.bin_verdict,
                    "radar_owner": self.lock.owner}
