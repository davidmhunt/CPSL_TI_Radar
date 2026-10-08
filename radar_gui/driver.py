"""Run control for the C++ driver (gui-05): validate, start/stop as a subprocess, live stats and log.

The driver binary is `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` unless `--driver-bin` / `RADAR_GUI_DRIVER`
says otherwise. `stats v1` lines are parsed with `tools/bench/bench_lib.Parser` (not re-implemented here).
"""
from __future__ import annotations

import collections
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import session_cfg
from .ports import check_ports, radar_lock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "bench"))
import bench_lib  # noqa: E402

DEFAULT_BIN = REPO / "CPSL_TI_Radar_cpp" / "build" / "CPSL_TI_Radar_CPP"
DEFAULT_RUN_ROOT = REPO / "runs" / "gui"
LOG_LINES = 500
LOG_FLUSH_S = 0.15   # driver_log lines are sent to the page as one driver_log_batch per this interval (gui-09 D8)
_FRAME_RE = re.compile(r"^frame:\s+(\d+) rx x (\d+) samples x (\d+) chirps, ([\d.]+) ms period")
_BPF_RE = re.compile(r"^bytes/frame:\s*(\d+)")
CLI_MAX = 500          # transcript entries kept (the beginning of the run: that is where a rejected cfg shows)
CLI_REPLY_MAX = 200
# Board CLI transcript (gui-34). Two driver formats: the info-level echo (one line per command, written after the reply)
#   cli [3/27] channelCfg 15 7 0 -> Done (12 ms)
#   cli [27/27] sensorStart -> ERROR (8 ms) "Error: Full configuration ... | Error -1"
#   cli [5/27] foo -> TIMEOUT no 'Done' in 100 ms "<partial reply>"       cli [skip] calibData 0 0 0 (skip_commands)
# and, as a fallback for older binaries run at log_level debug, the "Sent command:" / "Received response:" pair
# followed by the raw reply lines up to the board prompt.
_CLI_ECHO_RE = re.compile(r"^\s*cli \[(?P<tag>[^\]]+)\] (?P<cmd>.+?) -> (?P<verdict>DONE|ERROR|TIMEOUT)\b(?P<rest>.*)$", re.I)
_MS_RE = re.compile(r"\((\d+(?:\.\d+)?) ?ms\)")
_CLI_SKIP_RE = re.compile(r"^\s*cli \[skip\] (?P<cmd>.+?)(?: \([^)]*\))?\s*$")
_DBG_SKIP_RE = re.compile(r"^Skipped command \([^)]*\): (?P<cmd>.+?)\s*$")
_DBG_SENT_RE = re.compile(r"^Sent command: (?P<cmd>.+?)\s*$")
_DBG_WARN_RE = re.compile(r"^warning: CLIController: no '[^']*' for '(?P<cmd>.+?)' within (?P<ms>\d+) ms")
_PROMPT_END = ":/>"
_ERR_TOKENS = ("Error", "not recognized")
_STOP_PENDING = ("stats v1", "warning:", "error:", "SerialStreamer", "Received ", "no frame")


# gui-33: the driver's firmware identity check (Radar.cpp check_firmware_identity). One verdict line per run:
#   [warning: ]firmware: <match|mismatch|skipped|unknown> expected=<fw> found=<fields | not queried | no reply>
# and detail lines: the fatal/warn mismatch message (carries the flash hint), the skipped reason, the unknown reason.
_FW_RE = re.compile(r"^(?:warning: |error: )?firmware: (?P<verdict>match|mismatch|skipped|unknown) expected=(?P<exp>\S+) found=(?P<found>.*)$")
_FW_HINT_RE = re.compile(r"firmware mismatch on \S+: system JSON expects .*?Flash it: (?P<hint>.+?), or set runtime\.firmware_check")
_FW_SKIP_RE = re.compile(r"Radar: firmware check skipped: (?P<d>.+)$")
_FW_UNK_RE = re.compile(r"Radar: could not confirm the firmware on \S+ \((?P<d>.*)\); sending the cfg anyway")


def parse_firmware_line(line: str) -> dict | None:
    """The `firmware:` verdict line -> {verdict, expected, found} (None for any other line)."""
    m = _FW_RE.match(line.replace("\r", "").strip())
    return {"verdict": m["verdict"], "expected": m["exp"], "found": m["found"].strip()} if m else None


def parse_firmware_extra(line: str) -> dict:
    """A detail line of the firmware check -> {hint} (mismatch message) or {detail} (skipped / unknown reason); {} otherwise."""
    t = line.replace("\r", "").strip()
    if (m := _FW_HINT_RE.search(t)):
        return {"hint": m["hint"]}
    if (m := _FW_SKIP_RE.search(t)) or (m := _FW_UNK_RE.search(t)):
        return {"detail": m["d"]}
    return {}


def clean_reply(lines, drop_done: bool) -> str:
    """Reply lines -> one line: newlines as ' | ', optional lone 'Done' dropped, capped at CLI_REPLY_MAX chars."""
    keep = [ln for ln in lines if not (drop_done and ln == "Done")]
    text = " | ".join(keep)
    return text if len(text) <= CLI_REPLY_MAX else text[:CLI_REPLY_MAX - 1] + "\u2026"


def first_fail(cli) -> int | None:
    """1-based position (seq) of the first ERROR/TIMEOUT entry, else None."""
    return next((e["seq"] for e in cli if e["verdict"] in ("ERROR", "TIMEOUT")), None)


class DriverError(Exception):
    """A refusal; `status` is the HTTP code the API uses (409 busy/state, 422 bad input, 503 no binary)."""

    def __init__(self, msg: str, status: int = 409):
        super().__init__(msg)
        self.status = status


def driver_bin(override: str | None = None) -> Path:
    # absolute: the probes and the run launch use another cwd, where a relative path would not resolve
    return Path(override or os.environ.get("RADAR_GUI_DRIVER") or DEFAULT_BIN).absolute()


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


def parse_validate_json(text: str, exit_code: int) -> dict | None:
    """The driver's `--validate --json` object as the validate() dict (None when `text` is not that object, i.e. a
    driver without --json). Keeps every key parse_validate gives (`text` is rebuilt from the errors/warnings/notes)
    and adds `json`, `errors`, `warnings`, `board`, `firmware`, `metrics`."""
    try:
        d = json.loads(text)
    except ValueError:
        return None
    if not isinstance(d, dict) or "ok" not in d or "errors" not in d:
        return None
    errs, warns = d.get("errors") or [], d.get("warnings") or []
    lines = [f"error [{e.get('code', '')}]: {e.get('message', '')}" for e in errs]
    lines += [f"warning [{w.get('code', '')}]: {w.get('message', '')}" for w in warns]
    lines += [f"note: {n}" for n in d.get("notes") or []]
    fr = d.get("frame")
    if fr:
        fr = dict(fr, line=f"frame: {fr['rx']} rx x {fr['samples']} samples x {fr['chirps']} chirps, {fr['period_ms']} ms period")
        lines.append(fr["line"])
    if d.get("bytes_per_frame") is not None:
        lines.append(f"bytes/frame: {d['bytes_per_frame']}")
    ok = bool(d["ok"]) and exit_code == 0
    if ok:
        lines.append(f"OK: {d.get('config', '')}")
    return {"ok": ok, "exit": exit_code, "text": "\n".join(lines) + "\n", "bytes_per_frame": d.get("bytes_per_frame"),
            "frame": fr, "notes": list(d.get("notes") or []), "json": True, "errors": errs, "warnings": warns,
            "board": d.get("board"), "firmware": d.get("firmware"), "metrics": d.get("metrics") or {}}


def validate_config(binary: Path, config: str | os.PathLike, env: dict | None = None) -> dict:
    """Run `<binary> <config> --validate --json` (gui-04) and return the validate() dict; a driver without --json
    (exit 2 / non-JSON output) falls back to the plain-text `--validate` and parse_validate."""
    def run(*flags):
        try:
            return subprocess.run([str(binary), str(config), "--validate", *flags], capture_output=True, text=True,
                                  timeout=30, stdin=subprocess.DEVNULL, env=env)
        except subprocess.TimeoutExpired:
            raise DriverError("--validate timed out after 30 s", 503)
    p = run("--json")
    v = parse_validate_json(p.stdout, p.returncode)
    if v is not None:
        return v
    p = run()
    return parse_validate(p.stdout + p.stderr, p.returncode)


class DriverManager:
    """At most one driver run at a time; thread-safe. `emit(msg_dict)` receives driver_* messages (any thread)."""

    def __init__(self, bin_override=None, run_root_override=None, lock=radar_lock, emit=None,
                 min_stop_grace: float = 5.0, on_run=None, owner_detail=None):
        self.bin_override, self.root_override, self.lock = bin_override, run_root_override, lock
        self.on_run = on_run                      # gui-36: called with the run info after the spawn; True = tap fd taken over
        self.owner_detail = owner_detail or (lambda: "")
        self._tap_cache = {}                      # (binary path, mtime) -> supports --tap-fd
        self._caps_cache = {}                     # (binary path, mtime) -> session_cfg.probe_caps()
        self.emit, self.min_grace = emit or (lambda m: None), min_stop_grace
        self._mu = threading.RLock()
        self._reset()
        self.state = "idle"
        self.run_id = 0     # counts runs; the page clears its transcript when it changes (gui-34)
        self.boot = uuid.uuid4().hex[:12]   # this GUI process: the page keys "this GUI configured the board" evidence on it (gui-37)

    def _reset(self):
        self.proc = None
        self.config = self.run_dir = self.exit_code = self.error = None
        self.stats, self.files, self.bin_verdict, self.forced = {}, [], None, False
        self.log = collections.deque(maxlen=LOG_LINES)
        self.parser = bench_lib.Parser()
        self._prev = {}
        self.cli, self._cli_pend, self._cli_seq = [], None, 0
        self._logbuf, self._flush_timer = [], None
        self.expect = {}
        self.sigint_sent = False
        self.t_start = 0.0
        self.label = self.session_json = self._logf = None   # gui-37: display label, the run's session.json, driver.log handle
        self.saving, self.fw_id, self.notes = {}, None, []
        self.fw_check = None      # gui-33: the driver's `firmware:` verdict line, parsed (parse_firmware_line); None = no line seen
        self.tap = None   # "on" = run started with --tap-fd, "off" = the binary has no tap, None = no run yet
        self.adc_every = 0        # gui-07: K passed as --tap-adc-every (0 = not passed)
        self.adc_reason = None    # why not: "off" | "no_dca" | "no_adc_tap" | "no_tap"; None = ADC tap on

    # ---- validate -------------------------------------------------------------------------------
    def _bin(self) -> Path:
        b = driver_bin(self.bin_override)
        if not (b.is_file() and os.access(b, os.X_OK)):
            raise DriverError(f"driver binary not found or not executable: {b} "
                              "(build CPSL_TI_Radar_cpp, or pass --driver-bin / set RADAR_GUI_DRIVER)", 503)
        return b

    def validate(self, config: str | os.PathLike) -> dict:
        return validate_config(self._bin(), config)

    def _usage(self, b: Path) -> str:
        """The binary's usage text, once per binary (path + mtime): feature flags are detected from it, so an older
        build keeps working without them."""
        try:
            key = (str(b), b.stat().st_mtime_ns)
        except OSError:
            return ""
        if key not in self._tap_cache:
            try:
                p = subprocess.run([str(b), "--help"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
                self._tap_cache[key] = p.stdout + p.stderr
            except (OSError, subprocess.TimeoutExpired):
                self._tap_cache[key] = ""
        return self._tap_cache[key]

    def tap_supported(self, b: Path) -> bool:
        return "--tap-fd" in self._usage(b)

    def _key_caps(self, b: Path) -> dict:
        """Which optional system-JSON keys the binary accepts (a `--validate` probe, once per binary path + mtime)."""
        try:
            key = (str(b), b.stat().st_mtime_ns)
        except OSError:
            return {"firmware_key": False, "firmware_check": False, "save_serial_bytes": False}
        if key not in self._caps_cache:
            self._caps_cache[key] = session_cfg.probe_caps(b)
        return self._caps_cache[key]

    def caps(self) -> dict:
        """What the configured binary can do (False for a missing binary): the Run tab greys options out with it.
        `setup` is this backend's own capability (start accepts a quick setup / overrides), not the binary's."""
        try:
            b = driver_bin(self.bin_override)
            ok = b.is_file() and os.access(b, os.X_OK)
        except OSError:
            ok = False
        u = self._usage(b) if ok else ""
        return {"tap": "--tap-fd" in u, "skip_configure": "--skip-configure" in u, "adc_tap": "--tap-adc-every" in u,
                "setup": True, **(self._key_caps(b) if ok else {"firmware_key": False, "firmware_check": False,
                                                                 "save_serial_bytes": False})}

    # ---- start / stop ---------------------------------------------------------------------------
    def start(self, config: str | os.PathLike | None = None, frames: int | None = None, duration: float | None = None,
              skip_configure: bool = False, adc_every: int | None = None, setup: dict | None = None,
              overrides: dict | None = None) -> dict:
        """Start a run from a saved system JSON (`config`, plus `overrides`) or a quick `setup` (gui-37). Either way the
        driver runs `<run folder>/session.json`, written here with the cfg copy; a refused start leaves no folder."""
        if (config is None) == (setup is None):
            raise DriverError("give exactly one of config (a saved system JSON) or setup (a quick setup)", 422)
        with self._mu:
            if self.state in ("running", "stopping"):
                raise DriverError(f"driver already {self.state}")
            b = self._bin()
            try:
                caps = self._key_caps(b)
                plan = (session_cfg.from_setup(setup, caps) if setup is not None
                        else session_cfg.from_saved(Path(config).resolve(), overrides, caps))
            except session_cfg.SessionError as e:
                raise DriverError(str(e), 422)
            eff = plan["eff"]
            skip = bool(skip_configure or plan["skip_configure"])
            if skip and "--skip-configure" not in self._usage(b):
                if skip_configure:
                    raise DriverError("this driver binary has no --skip-configure (rebuild the driver)", 422)
                skip = False   # only the JSON key (runtime.skip_configure) asked for it, which any build reads
            cwd = self._make_run_dir(plan["name"])
            spawned = False
            try:
                session = session_cfg.write_session(cwd, plan)
                val = self.validate(session)
                if not val["ok"]:
                    raise DriverError("config is INVALID:\n" + val["text"].strip(), 422)
                ports = [eff.get("cli", {}).get("port")]
                if eff.get("serial_stream", {}).get("enabled"):
                    ports.append(eff["serial_stream"].get("port"))
                ports = [p for p in ports if p]
                if not self.lock.acquire("driver"):
                    raise DriverError(f"Live serial source holds the radar{self.owner_detail()}; stop it in the Live tab"
                                      if self.lock.owner == "serial source" else f"radar in use by {self.lock.owner}")
                try:
                    if (why := check_ports(ports)):
                        raise DriverError(why)
                    out_dir = (eff.get("output") or {}).get("dir")
                    files_dir = Path(out_dir) if out_dir else cwd
                    cmd = [str(b), str(session), "--stats"]
                    if skip:
                        cmd += ["--skip-configure"]
                    if frames:
                        cmd += ["--frames", str(int(frames))]
                    if duration:
                        cmd += ["--duration", str(float(duration))]
                    self._reset()
                    self.run_id += 1
                    shown = str(Path(config).resolve()) if config is not None else str(session)
                    self.config, self.run_dir, self.files_dir = shown, str(cwd), files_dir
                    self.label, self.session_json = plan["label"], str(session)
                    self.saving, self.fw_id, self.notes = session_cfg.saving_of(eff), eff.get("firmware"), list(plan["notes"])
                    self.expect = {"bytes_per_frame": val["bytes_per_frame"],
                                   "period_ms": (val["frame"] or {}).get("period_ms")}
                    self.t_start = time.time()
                    rfd = wfd = None
                    tap_ok = self.tap_supported(b)
                    # gui-07 ADC views: K = None -> every frame (1), 0 = off. Passed only when the run has a DCA1000 stream and
                    # the binary's usage text lists --tap-adc-every (an older build keeps working without it).
                    k = 1 if adc_every is None else max(0, int(adc_every))
                    reason = None
                    if k == 0:
                        reason = "off"
                    elif not (eff.get("dca1000") or {}).get("enabled"):
                        reason = "no_dca"
                    elif not tap_ok:
                        reason = "no_tap"
                    elif "--tap-adc-every" not in self._usage(b):
                        reason = "no_adc_tap"
                    self.adc_every, self.adc_reason = (0, reason) if reason else (k, None)
                    if tap_ok:
                        rfd, wfd = os.pipe()
                        cmd += ["--tap-fd", str(wfd)]
                        if self.adc_every:
                            cmd += ["--tap-adc-every", str(self.adc_every)]
                    try:
                        self._logf = open(cwd / session_cfg.DRIVER_LOG, "w", buffering=1, errors="replace")
                    except OSError:
                        self._logf = None
                    try:
                        self.proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                     stdin=subprocess.DEVNULL, text=True, bufsize=1,
                                                     start_new_session=True, pass_fds=(wfd,) if wfd is not None else ())
                    except OSError as e:
                        for fd in (rfd, wfd):
                            if fd is not None:
                                os.close(fd)
                        self._close_log()
                        self.error = f"cannot start driver: {e}"
                        self._set_state("failed")
                        raise DriverError(self.error, 503)
                    if wfd is not None:
                        os.close(wfd)      # only the driver holds the write end: its exit is EOF for the reader
                    self.tap = "on" if rfd is not None else "off"
                    spawned = True
                finally:
                    if not spawned:
                        self.lock.release("driver")
            except BaseException:
                if not spawned and self.state != "failed":
                    shutil.rmtree(cwd, ignore_errors=True)   # a refused start leaves nothing behind
                raise
            self._set_state("running")
            taken = False
            if self.on_run is not None:
                try:
                    taken = bool(self.on_run({"run": self.run_id, "config": self.config, "pid": self.proc.pid,
                                              "tap_fd": rfd, "tap": self.tap,
                                              "adc_every": self.adc_every, "adc_reason": self.adc_reason,
                    "label": self.label, "session_json": self.session_json, "saving": dict(self.saving),
                    "firmware": self.fw_id, "firmware_check": None, "notes": list(self.notes)}))
                except Exception:
                    taken = False
            if rfd is not None and not taken:
                os.close(rfd)
            threading.Thread(target=self._pump, args=(self.proc,), daemon=True, name="driver-pump").start()
            return self.status()

    def _make_run_dir(self, name: str) -> Path:
        """`<run root>/<UTC>_<name>`, unique (a second start in the same second gets `-2`, ...)."""
        root = run_root(self.root_override)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"{stamp}_{session_cfg.safe_name(name)}"
        root.mkdir(parents=True, exist_ok=True)
        for i in range(1, 100):
            d = root / (base if i == 1 else f"{base}-{i}")
            try:
                d.mkdir()
                return d
            except FileExistsError:
                continue
        raise DriverError(f"cannot create a run folder under {root}", 503)

    def _close_log(self):
        f, self._logf = self._logf, None
        if f is not None:
            try:
                f.close()
            except OSError:
                pass

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
            self._logbuf.append(line)
            if self._logf is not None:
                try:
                    self._logf.write(line + "\n")
                except (OSError, ValueError):   # disk full / closed: the page still has the log
                    self._close_log()
            if self._flush_timer is None:
                self._flush_timer = threading.Timer(LOG_FLUSH_S, self._flush_log)
                self._flush_timer.daemon = True
                self._flush_timer.start()
            cli_events = self._cli_line(line)
            fw_msg = self._firmware_line(line)
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
        if msg:
            self.emit(msg)
        for ev in cli_events:
            self.emit(ev)
        if fw_msg:
            self.emit(fw_msg)

    def _firmware_line(self, line):
        """gui-33: fold the driver's firmware-check output into `fw_check`; returns the driver_firmware event on a change.
        Caller holds the lock."""
        new = parse_firmware_line(line)
        if new is not None:
            self.fw_check = new
        elif self.fw_check is not None and (extra := parse_firmware_extra(line)):
            if all(self.fw_check.get(k) == v for k, v in extra.items()):
                return None
            self.fw_check = {**self.fw_check, **extra}
        else:
            return None
        return {"type": "driver_firmware", "run": self.run_id, "firmware_check": dict(self.fw_check)}

    def _flush_log(self):
        """Send the buffered output lines as one driver_log_batch (order kept). A page that drops the oldest message on
        a burst then loses at most one batch, and the status re-read after a driver_cli burst restores it."""
        with self._mu:
            lines, self._logbuf, self._flush_timer = self._logbuf, [], None
            if lines:
                self.emit({"type": "driver_log_batch", "run": self.run_id, "lines": lines})

    # ---- board command transcript (gui-34) -------------------------------------------------------
    def _cli_add(self, **e) -> dict:
        self._cli_seq += 1
        entry = {"seq": self._cli_seq, "i": None, "n": None, "tag": None, "cmd": "", "ok": False, "verdict": "ERROR",
                 "reply": "", "ms": None, **e}
        if len(self.cli) < CLI_MAX:
            self.cli.append(entry)
        return {"type": "driver_cli", "run": self.run_id, "entry": entry, "first_fail": first_fail(self.cli)}

    def _cli_close(self) -> list:
        """Finish the pending debug-format command: ERROR if the reply has an error token, DONE if it has Done, else TIMEOUT."""
        p, self._cli_pend = self._cli_pend, None
        if p is None:
            return []
        lines = [ln for ln in p["lines"] if ln and ln != p["cmd"] and not ln.endswith(_PROMPT_END)]
        if any(ln.startswith(_ERR_TOKENS) or "not recognized" in ln for ln in lines):
            verdict = "ERROR"
        elif any(ln.startswith("Done") for ln in lines):
            verdict = "DONE"
        else:
            verdict = "TIMEOUT"
        return [self._cli_add(cmd=p["cmd"], ok=verdict == "DONE", verdict=verdict,
                              reply=clean_reply(lines, verdict == "DONE"))]

    def _cli_line(self, line) -> list:
        """Feed one driver output line; returns the driver_cli events it completed. Caller holds the lock."""
        text = line.replace("\r", "").strip()
        if (m := _CLI_ECHO_RE.match(text)):
            tag = m.group("tag").strip()
            ij = re.fullmatch(r"(\d+)/(\d+)", tag)
            verdict, rest = m.group("verdict").upper(), m.group("rest")
            q = rest.find(' "')
            head, reply = (rest, "") if q < 0 else (rest[:q], rest[q + 2:].rstrip().removesuffix('"'))
            ms = _MS_RE.search(head)
            ms = None if ms is None else (int(float(ms.group(1))) if float(ms.group(1)).is_integer() else float(ms.group(1)))
            return self._cli_close() + [self._cli_add(
                i=int(ij.group(1)) if ij else None, n=int(ij.group(2)) if ij else None, tag=None if ij else tag,
                cmd=m.group("cmd"), ok=verdict == "DONE", verdict=verdict, reply=clean_reply([reply], False) if reply else "", ms=ms)]
        if (m := _CLI_SKIP_RE.match(text)) or (m := _DBG_SKIP_RE.match(text)):
            return self._cli_close() + [self._cli_add(tag="skip", cmd=m.group("cmd"), ok=True, verdict="SKIP")]
        if (m := _DBG_SENT_RE.match(text)):
            out = self._cli_close()
            self._cli_pend = {"cmd": m.group("cmd"), "lines": []}
            return out
        if (m := _DBG_WARN_RE.match(text)):
            if self._cli_pend is not None and self._cli_pend["cmd"] == m.group("cmd"):
                out = self._cli_close()
            else:
                out = []
            last = self.cli[-1] if self.cli else None
            if last and last["cmd"] == m.group("cmd") and last["verdict"] == "TIMEOUT" and last["ms"] is None:
                last["ms"] = int(m.group("ms"))
                out = out or [{"type": "driver_cli", "run": self.run_id, "entry": last, "first_fail": first_fail(self.cli)}]
            return out
        if self._cli_pend is None:
            return []
        if text.startswith("Received response:"):
            return []
        if text.endswith(_PROMPT_END) or text.startswith(_STOP_PENDING):
            return self._cli_close()
        if len(self._cli_pend["lines"]) < 20:
            self._cli_pend["lines"].append(text)
        return []

    def _finish(self, code):
        t, self._flush_timer = self._flush_timer, None
        if t is not None:
            t.cancel()
        self._flush_log()   # the tail of the output must reach the page before the exit state
        for ev in self._cli_close():
            self.emit(ev)
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
        self._close_log()
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
                    "run": self.run_id, "cli": [dict(e) for e in self.cli] if log else [], "cli_first_fail": first_fail(self.cli),
                    "files": list(self.files), "bin_verdict": self.bin_verdict,
                    "radar_owner": self.lock.owner, "tap": self.tap,
                    "adc_every": self.adc_every, "adc_reason": self.adc_reason,
                    "label": self.label, "session_json": self.session_json, "saving": dict(self.saving),
                    "firmware": self.fw_id, "firmware_check": dict(self.fw_check) if self.fw_check else None,
                    "notes": list(self.notes), "boot": self.boot}
