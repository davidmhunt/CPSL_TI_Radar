"""Replay fixtures cut from the 2026-10-07 bench captures (tests/fixtures/replay/README.md)."""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import tlv
from radar_gui.app import create_app
from radar_gui.sources import ReplaySource

DIR = Path(__file__).parent / "fixtures" / "replay"
CASES = {
    "sdk3": (DIR / "iwr1843_sdk3_20frames.bin", 2, [7] * 20),
    "mcuplus_cascade": (DIR / "awr2243_cascade_20frames.bin", 2414,
                        [56, 56, 56, 57, 56, 60, 55, 54, 57, 61, 60, 62, 57, 56, 62, 68, 51, 56, 62, 59]),
}


@pytest.mark.parametrize("dialect", CASES)
def test_fixture_parses_whole_frames(dialect):
    path, first, counts = CASES[dialect]
    data = path.read_bytes()
    assert len(data) < 100_000
    pkts = list(tlv.split_packets(data, dialect))
    assert len(pkts) == 20 and sum(map(len, pkts)) == len(data)      # no partial bytes at either end
    frames = [tlv.parse_frame(p, dialect) for p in pkts]
    nums = [f["frame"] for f in frames]
    assert nums == list(range(first, first + 20))                    # monotonic, no gaps
    assert [f["n"] for f in frames] == counts == [len(f["pts"]) for f in frames]
    assert all(len(pt) == 6 for f in frames for pt in f["pts"])
    assert not any(f.get("compact_points_skipped") for f in frames)


def test_cascade_cloud_is_nonempty_with_sane_ranges():
    path, _, _ = CASES["mcuplus_cascade"]
    frames = [tlv.parse_frame(p, "mcuplus_cascade") for p in tlv.split_packets(path.read_bytes(), "mcuplus_cascade")]
    assert all(f["n"] > 0 for f in frames)
    assert all(abs(pt[0]) < 100 and 0 <= pt[1] < 100 for f in frames for pt in f["pts"])


@pytest.mark.parametrize("dialect", CASES)
def test_replay_source_plays_fixture(dialect):
    path, first, counts = CASES[dialect]
    src = ReplaySource(str(path), rate_hz=1000, loop=False, dialect=dialect)

    async def collect():
        return [f async for f in src.frames()]

    frames = asyncio.run(collect())
    assert [f["frame"] for f in frames] == list(range(first, first + 20))
    assert [len(f["pts"]) for f in frames] == counts


@pytest.mark.parametrize("dialect", CASES)
def test_gui_replays_fixture_via_api(dialect, tmp_path):
    """POST /api/source replay: fixtures are on the allowlist; the default (sdk3-header) parse reads both dialects."""
    path, first, counts = CASES[dialect]
    other = next(p for d, (p, _, _) in CASES.items() if d != dialect)
    app = create_app(ReplaySource(str(other), rate_hz=200), user_cfg_dir=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/stream") as ws:
        r = c.post("/api/source", json={"kind": "replay", "file": str(path), "rate_hz": 200})
        assert r.status_code == 200 and r.json()["kind"] == "replay"
        assert str(path.resolve()) in {f["path"] for f in c.get("/api/source/files").json()["files"]}
        seen = {}
        for _ in range(400):
            m = ws.receive_json()
            i = m.get("frame", -1) - first if m.get("type") == "frame" else -1
            if 0 <= i < 20 and m["n"] == counts[i]:   # a frame of this fixture (not a leftover of the previous source)
                seen[m["frame"]] = m["n"]
            if len(seen) == 20:
                break
        assert sorted(seen) == list(range(first, first + 20))
