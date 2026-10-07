"""Frame sources. A Source is an async iterator of frame dicts in the viewer's wire format:
{"type":"frame","frame":int,"n":int,"t":float,"pts":[[x,y,z,v,snr,noise],...]}."""
import asyncio
import math
import os
import random
import threading
import time

from . import adc, tap, tlv


class Source:
    name = "base"
    rate_hz = 10.0
    info = {"max_range_m": 10, "fov": [-60, 60]}  # hints for the page

    holds_lock = False   # True for a source that owns the radar (SerialSource)

    def claim(self):
        """Take whatever exclusive resource the source needs; raise PortBusy if it is taken. Default: none."""

    def release(self):
        pass

    async def frames(self):
        raise NotImplementedError
        yield  # pragma: no cover


class NoSource(Source):
    """No source yet (the default since gui-36 Step 3b): the Live tab waits for Serial, Replay or a driver run."""
    name = "none"
    drives_status = True
    MSG = "pick Serial or Replay, or start a driver run in the Run tab"

    def __init__(self):
        self.on_status = lambda s, m: None

    async def frames(self):
        self.on_status("idle", self.MSG)
        await asyncio.Event().wait()
        yield  # pragma: no cover


def detect_dialect(name: str) -> str:
    """TLV dialect of a replay dump from its file name (gui-09 D16): AWR2243_CASCADE_* -> mcuplus_cascade, IWR1443* -> sdk2."""
    n = os.path.basename(name).lower()
    return "mcuplus_cascade" if n.startswith("awr2243_cascade") else "sdk2" if n.startswith("iwr1443") else "sdk3"


class MockSource(Source):
    """Synthetic scene: three targets moving on loops plus a few static wall points."""
    name = "mock"

    def __init__(self, rate_hz=10.0, max_frames=None, seed=1):
        self.rate_hz, self.max_frames, self.rng = rate_hz, max_frames, random.Random(seed)
        self.walls = [(x / 2, 8.5, 0.6 + 0.4 * self.rng.random()) for x in range(-8, 9)]

    def scene(self, t):
        """(x, y, z, vx, vy) per target at time t."""
        out = []
        for k, (cx, cy, rx, ry, w, z) in enumerate([(0, 5, 3, 1.5, 0.5, 0.9), (-2, 3.5, 1, 2, -0.8, 1.2),
                                                    (2.5, 6.5, 1.5, 1.0, 1.1, 0.3)]):
            a = w * t + k
            out.append((cx + rx * math.cos(a), cy + ry * math.sin(a), z,
                        -rx * w * math.sin(a), ry * w * math.cos(a)))
        return out

    def make_frame(self, n, t):
        r, pts = self.rng, []
        for x, y, z, vx, vy in self.scene(t):
            rng_ = math.hypot(x, y) or 1
            vr = (x * vx + y * vy) / rng_  # radial velocity, + = receding
            for _ in range(r.randint(6, 12)):
                pts.append([x + r.gauss(0, .12), y + r.gauss(0, .12), z + r.gauss(0, .15), vr + r.gauss(0, .1),
                            r.uniform(14, 34), 5.0])
        for x, y, z in r.sample(self.walls, 6):
            pts.append([x + r.gauss(0, .05), y + r.gauss(0, .05), z, r.gauss(0, .03), r.uniform(8, 20), 5.0])
        pts = [[round(v, 3) for v in p] for p in pts]
        return {"type": "frame", "frame": n, "n": len(pts), "t": time.time(), "pts": pts}

    async def frames(self):
        n, t0 = 0, time.monotonic()
        while self.max_frames is None or n < self.max_frames:
            yield self.make_frame(n, time.monotonic() - t0)
            n += 1
            await asyncio.sleep(1 / self.rate_hz)


class ReplaySource(Source):
    """Replays a recorded TLV byte dump (back-to-back frame packets) in a loop."""
    name = "replay"

    def __init__(self, path, rate_hz=10.0, loop=True, max_frames=None, dialect="sdk3"):
        self.dialect = dialect
        with open(path, "rb") as f:
            self.packets = list(tlv.split_packets(f.read(), dialect))
        if not self.packets:
            raise ValueError(f"no TLV frames found in {path}")
        self.path, self.rate_hz, self.loop, self.max_frames = path, rate_hz, loop, max_frames

    async def frames(self):
        sent = 0
        while True:
            for pkt in self.packets:
                if self.max_frames is not None and sent >= self.max_frames:
                    return
                yield tlv.parse_frame(pkt, self.dialect)
                sent += 1
                await asyncio.sleep(1 / self.rate_hz)
            if not self.loop:
                return


class DriverSource(Source):
    """Follows a GUI-started driver run (gui-36): the point cloud comes off the run's tap pipe (radar_gui/tap.py), so the
    Live tab shows the board the driver owns without a second connection. Holds no radar lock (the run does). `state`:
    running -> ended | died, decided from the DriverManager status once the pipe hits EOF. Never falls back to a serial
    source by itself. `tapped` False = the binary has no `--tap-fd` (nothing to read; status says to rebuild)."""
    name = "driver"
    drives_status = True
    finished_status = False   # the Hub must not overwrite the final status with "Source finished"
    NO_TAP_MSG = "driver run has no live tap (rebuild the driver)"

    def __init__(self, mgr, run: int, config: str, pid: int | None, fd: int | None, adc_every: int = 0,
                 adc_reason: str | None = None):
        self.mgr, self.run, self.config, self.pid, self.fd = mgr, run, config, pid, fd
        self.adc_every, self.adc_reason = adc_every, adc_reason
        self.adc_sink = None          # callable(bytes) set by the app: encoded ADC view messages (called from the processor thread)
        self.geom, self.geom_err, self.processor = None, "", None
        if fd is not None and adc_every > 0:
            try:
                self.geom = adc.Geometry.from_system_json(config)
                self.processor = adc.AdcProcessor(self.geom, self._adc_out)
            except Exception as e:   # a cfg the maths cannot read: the ADC panels say so, Live is unaffected
                self.geom_err = f"cannot build the ADC geometry from the run's cfg: {e}"
        self.tapped = fd is not None
        self.state, self.msg = "running", "" if self.tapped else self.NO_TAP_MSG
        self.hello = None
        self.frames_in = self.adc_in = self.adc_bad = self.skipped = 0
        self.last_adc = None          # header of the newest adc message (plumbing for gui-07; the data is not kept)
        self.on_status = lambda s, m: None
        self._slot, self._mu, self._eof, self._stop = None, threading.Lock(), False, False
        self._loop = self._wake = self._thread = None
        self.spec = {"kind": "driver", "config": config, "pid": pid, "run": run, "tap": self.tapped,
                     "name": os.path.splitext(os.path.basename(config))[0]}

    @property
    def running(self) -> bool:
        return self.state == "running"

    def _adc_out(self, msg: bytes):
        sink = self.adc_sink
        if sink is not None:
            sink(msg)

    def adc_status(self) -> dict:
        """State of the ADC views for this run (the /adc panels show `msg`): none/no_tap/no_dca/off/error/waiting/running/ended/died."""
        p = self.processor
        out = {"run": self.run, "config": self.spec["name"], "adc_every": self.adc_every, "adc_in": self.adc_in,
               **(p.counters() if p else {})}
        if not self.tapped:
            return {**out, "state": "no_tap", "msg": adc.MSG_NO_TAP}
        r = self.adc_reason
        if r == "off":
            return {**out, "state": "off", "msg": adc.MSG_OFF}
        if r == "no_dca":
            return {**out, "state": "no_dca", "msg": adc.MSG_NO_DCA}
        if r in ("no_adc_tap", "no_tap"):
            return {**out, "state": "no_tap", "msg": adc.MSG_NO_TAP}
        if self.hello is not None and "adc" not in (self.hello.get("streams") or []):
            return {**out, "state": "no_dca", "msg": adc.MSG_NO_DCA}
        if self.geom_err:
            return {**out, "state": "error", "msg": self.geom_err}
        if self.state in ("ended", "died"):
            return {**out, "state": self.state, "msg": self.msg}
        if p is not None and p.rejected and not p.adc_shown:
            return {**out, "state": "error", "msg": p.last_error}
        if not self.adc_in:
            return {**out, "state": "waiting", "msg": adc.MSG_WAIT}
        return {**out, "state": "running", "msg": ""}

    def release(self):
        self._stop = True
        if self.processor is not None:
            self.processor.stop()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._close_fd()

    def _close_fd(self):
        fd, self.fd = self.fd, None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    # ---- reader thread: pipe -> newest-wins slot (never blocks on the page or the loop) ----
    def _read(self):
        try:
            while True:
                kind, payload = tap.read_message(self.fd, lambda: self._stop)
                if kind == tap.HELLO:
                    self.hello = tap.decode_json(payload)
                elif kind == tap.POINTS:
                    fr = tap.decode_json(payload)
                    fr.setdefault("type", "frame")
                    with self._mu:
                        if self._slot is not None:
                            self.skipped += 1
                        self._slot = fr
                        self.frames_in += 1
                    self._poke()
                elif kind == tap.ADC:
                    try:
                        self.last_adc, raw = tap.decode_adc(payload)
                    except ValueError:   # a bad adc header must not end the point-cloud stream
                        self.adc_bad += 1
                        continue
                    self.adc_in += 1
                    if self.processor is not None:
                        self.processor.submit(self.last_adc, raw)
                # unknown types are skipped (forward compatible)
        except (tap.TapClosed, ValueError):
            pass
        finally:
            self._eof = True
            self._poke()

    def _poke(self):
        loop, ev = self._loop, self._wake
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(ev.set)

    def _finished(self):
        """The manager status of this run if it is over, else None."""
        st = self.mgr.status(log=False)
        if st["run"] != self.run:
            return {"state": "exited", "exit_code": None, "stats": {}}
        return st if st["state"] in ("exited", "failed") else None

    async def frames(self):
        self._loop, self._wake = asyncio.get_running_loop(), asyncio.Event()
        if self.tapped:
            self.on_status("waiting", "driver run starting: waiting for the first frame")
            if self.processor is not None:
                self.processor.start()
            self._thread = threading.Thread(target=self._read, daemon=True, name="driver-tap")
            self._thread.start()
        else:
            self.on_status("no_tap", self.NO_TAP_MSG)
        first, st = True, None
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), 0.25)
            except asyncio.TimeoutError:
                pass
            self._wake.clear()
            with self._mu:
                fr, self._slot = self._slot, None
            if fr is not None:
                if first:
                    first = False
                    self.on_status("streaming", "")
                yield fr
            if self._eof or not self.tapped:
                st = self._finished()
                if st is not None:
                    break
        code = st.get("exit_code")
        n = self.frames_in if self.tapped else max([int(s.get("frames", 0)) for s in st.get("stats", {}).values()] or [0])
        self.state = "ended" if st["state"] == "exited" else "died"
        if self.state == "ended":
            self.msg = f"driver run ended (exit {code}, {n} frames)"
            self.finished_status = True
            self.on_status("ended", self.msg)
        else:
            self.msg = f"driver died (exit {code})"
            self.finished_status = True
            self.on_status("error", self.msg)
        self._close_fd()


def make_source(kind, rate_hz=10.0, path=None):
    if kind == "none":
        return NoSource()
    if kind == "mock":
        return MockSource(rate_hz=rate_hz)
    if kind == "replay":
        if not path:
            raise SystemExit("--source replay needs --file <tlv dump>")
        return ReplaySource(path, rate_hz=rate_hz, dialect=detect_dialect(path))
    raise SystemExit(f"unknown source {kind!r}")
