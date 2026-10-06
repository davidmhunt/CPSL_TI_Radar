import asyncio
import os

from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.sources import MockSource, ReplaySource

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_frames.bin")
FIXTURE_COUNTS = [3, 5, 0, 8, 4]  # points per frame in the fixture (see radar_gui/tlv.build_packet)


def test_health_state_and_index():
    with TestClient(create_app(MockSource(rate_hz=200))) as c:
        assert c.get("/api/health").json() == {"ok": True}
        st = c.get("/api/state").json()
        assert st["source"] == "mock" and "status" in st
        r = c.get("/")
        assert r.status_code == 200 and "CPSL Radar" in r.text
        assert c.get("/js/main.js").status_code == 200


def test_mock_stream_yields_changing_frames():
    with TestClient(create_app(MockSource(rate_hz=200))) as c, c.websocket_connect("/stream") as ws:
        frames = []
        while len(frames) < 5:
            m = ws.receive_json()
            if m["type"] == "frame":
                frames.append(m)
        assert [f["frame"] for f in frames] == sorted({f["frame"] for f in frames})
        assert all(len(f["pts"]) > 10 and len(f["pts"][0]) == 6 for f in frames)
        assert frames[0]["pts"] != frames[-1]["pts"]


def test_replay_fixture_point_counts():
    src = ReplaySource(FIXTURE, rate_hz=1000, loop=False)

    async def collect():
        return [f async for f in src.frames()]

    frames = asyncio.run(collect())
    assert [len(f["pts"]) for f in frames] == FIXTURE_COUNTS
    assert [f["frame"] for f in frames] == list(range(5))
    assert frames[0]["pts"][0][4] == 12.0  # SNR from the type-7 TLV
