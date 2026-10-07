"""Frame sources. A Source is an async iterator of frame dicts in the viewer's wire format:
{"type":"frame","frame":int,"n":int,"t":float,"pts":[[x,y,z,v,snr,noise],...]}."""
import asyncio
import math
import random
import time

from . import tlv


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


def make_source(kind, rate_hz=10.0, path=None):
    if kind == "mock":
        return MockSource(rate_hz=rate_hz)
    if kind == "replay":
        if not path:
            raise SystemExit("--source replay needs --file <tlv dump>")
        return ReplaySource(path, rate_hz=rate_hz)
    raise SystemExit(f"unknown source {kind!r}")
