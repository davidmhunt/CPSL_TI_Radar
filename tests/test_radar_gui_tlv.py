"""TLV dialect parsing and runtime source switching. The Python serial source was deleted: a board
session is always the C++ driver. Frames mirror CPSL_TI_Radar_cpp/tests/uart_test_frames.hpp."""
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import tlv
from radar_gui.app import create_app
from radar_gui.sources import MockSource, ReplaySource

SAMPLE = Path(__file__).parent / "fixtures" / "sample_frames.bin"


# ---- fixture builders (byte-for-byte mirrors of uart_test_frames.hpp) --------------------------------------------
def points_tlv(n, base):                       # sdk3 TLV 1: float {x,y,z,v} = base + 4*i + {0..3}
    return 1, b"".join(struct.pack("<f", base + i) for i in range(n * 4))


def side_info_tlv(n):                          # TLV 7: snr = (100+i)*0.1 dB, noise = -20*i*0.1 dB
    return 7, b"".join(struct.pack("<hh", 100 + i, -20 * i) for i in range(n))


def sdk2_points_tlv(objs, q):                  # {u16 n, u16 q} + 12 B/obj {u16 rng, i16 dop, u16 peak, i16 x, y, z}
    return 1, struct.pack("<HH", len(objs), q) + b"".join(struct.pack("<HhHhhh", *o) for o in objs)


def make_frame(num, tlvs, sdk2=False, pad=32, num_obj=None):
    body = b"".join(struct.pack("<II", t, len(p)) + p for t, p in tlvs)
    hdr = 36 if sdk2 else 40
    total = (hdr + len(body) + pad - 1) // pad * pad
    if num_obj is None:
        pts = next((p for t, p in tlvs if t == 1), b"")
        num_obj = (struct.unpack_from("<H", pts)[0] if pts else 0) if sdk2 else len(pts) // 16
    f = tlv.MAGIC + struct.pack("<IIIIII", 0x03060000, total, 0x000A1843, num, 123456, num_obj)
    f += struct.pack("<I", len(tlvs)) + (b"" if sdk2 else struct.pack("<I", 0))
    return (f + body).ljust(total, b"\0")


def sdk3_frame(num, n=3):
    return make_frame(num, [points_tlv(n, 1.0), side_info_tlv(n)])


# ---- parsing ---------------------------------------------------------------------------------------------------
def test_parse_sdk3():
    fr = tlv.parse_frame(sdk3_frame(7), "sdk3")
    assert fr["frame"] == 7 and fr["n"] == 3 and len(fr["pts"]) == 3
    assert fr["pts"][0] == [1.0, 2.0, 3.0, 4.0, 10.0, 0.0]          # snr (100+0)*0.1
    assert fr["pts"][2] == [9.0, 10.0, 11.0, 12.0, 10.2, -4.0]      # snr 10.2, noise -40*0.1
    assert "compact_points_skipped" not in fr


def test_parse_sdk2_36_byte_header_q_format_no_velocity():
    objs = [(10, -3, 500, 256, -128, 64), (11, 0, 400, 512, 1024, -256)]
    fr = tlv.parse_frame(make_frame(5, [sdk2_points_tlv(objs, 8)], sdk2=True), "sdk2")
    assert fr["frame"] == 5 and fr["n"] == 2
    assert fr["pts"] == [[1.0, -0.5, 0.25, 0.0, 0.0, 0.0], [2.0, 4.0, -1.0, 0.0, 0.0, 0.0]]
    with pytest.raises(tlv.TlvError):      # an sdk2 frame is not a valid sdk3 one (header length differs)
        tlv.parse_frame(make_frame(5, [sdk2_points_tlv(objs, 8)], sdk2=True), "sdk3")


def test_parse_cascade_points_and_compact_flag():
    fr = tlv.parse_frame(make_frame(1, [points_tlv(2, 0.5), side_info_tlv(2)]), "mcuplus_cascade")
    assert len(fr["pts"]) == 2 and "compact_points_skipped" not in fr
    compact = make_frame(2, [(12, b"\0" * 24)], num_obj=0)           # guiMonitor detectedObjects 3: TLV 12 only
    fr = tlv.parse_frame(compact, "mcuplus_cascade")
    assert fr["pts"] == [] and fr["compact_points_skipped"] is True
    # TLV 12 is only special on the cascade
    assert "compact_points_skipped" not in tlv.parse_frame(compact, "sdk3")


def test_parse_rejects_malformed():
    with pytest.raises(tlv.TlvError, match="numDetectedObj"):
        tlv.parse_frame(make_frame(1, [points_tlv(2, 0.0)], num_obj=5), "sdk3")
    with pytest.raises(tlv.TlvError, match="side info"):
        tlv.parse_frame(make_frame(1, [points_tlv(2, 0.0), side_info_tlv(1)]), "sdk3")
    with pytest.raises(tlv.TlvError, match="magic"):
        tlv.parse_frame(b"\0" * 64, "sdk3")


def test_frame_reader_resync_gaps_and_errors():
    r = tlv.FrameReader("sdk3")
    stream = b"junk" + sdk3_frame(1) + sdk3_frame(2) + b"\x01\x02" + sdk3_frame(4)
    got = []
    for i in range(0, len(stream), 7):                 # 7-byte chunks: frames split across reads
        got += r.feed(stream[i:i + 7])
    assert [f["frame"] for f in got] == [1, 2, 4]
    assert r.gaps == 1 and r.errors == 1               # 4 after 2; two junk bytes after a frame (leading junk is free)
    bad = bytearray(sdk3_frame(5))
    struct.pack_into("<I", bad, 28, 9)                 # numDetectedObj != points
    assert r.feed(bytes(bad) + sdk3_frame(6)) and r.errors == 2


def test_replay_fixture_still_parses():
    pk = list(tlv.split_packets(SAMPLE.read_bytes()))
    assert pk and tlv.parse_frame(pk[0])["pts"]



@pytest.fixture
def api(tmp_path):
    return TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=tmp_path))


def frames_from(ws, n, timeout=8):
    got, end = [], time.time() + timeout
    while len(got) < n and time.time() < end:
        m = ws.receive_json()
        if m["type"] == "frame":
            got.append(m)
    return got


@pytest.mark.parametrize("body", [{"kind": "serial"}, {"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg"}])
def test_serial_source_removed_410(api, body):
    """The Python serial source is gone; a board session is POST /api/driver/start."""
    with api as c:
        r = c.post("/api/source", json=body)
        assert r.status_code == 410 and "driver" in r.json()["detail"]
        assert c.get("/api/source").json()["kind"] == "mock"


def test_api_boards_listing(api):
    with api as c:
        bs = {b["board"]: b for b in c.get("/api/source/boards").json()["boards"]}
        assert "IWR1843_SAR" not in bs
        assert bs["AWR2243_CASCADE"]["once_per_boot"] and bs["AWR2243_CASCADE"]["tlv_dialect"] == "mcuplus_cascade"
        assert bs["IWR1443"]["tlv_dialect"] == "sdk2" and not bs["IWR1843"]["once_per_boot"]


def test_switch_replay_mock_replay_keeps_streaming(tmp_path):
    app = create_app(ReplaySource(str(SAMPLE), rate_hz=200),
                     user_cfg_dir=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/stream") as ws:
        assert frames_from(ws, 2)
        for kind in ("mock", "replay", "mock", "replay"):
            r = c.post("/api/source", json={"kind": kind, "rate_hz": 200})
            assert r.status_code == 200 and r.json()["kind"] == kind
            fr = frames_from(ws, 3)
            assert len(fr) == 3
            assert c.get("/api/state").json()["source"] == kind



# ---- security: replay allowlist ---------------------------------------------------------
def test_replay_file_allowlist(api, tmp_path, monkeypatch):
    c = api
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    (dumps / "cap.bin").write_bytes(SAMPLE.read_bytes())
    monkeypatch.setenv("RADAR_GUI_DUMP_DIR", str(dumps))
    secret = tmp_path / "secret.bin"                       # a readable file outside the allowlist
    secret.write_bytes(SAMPLE.read_bytes())
    with c:
        listed = c.get("/api/source/files").json()
        assert listed["dump_dir"] == str(dumps)
        paths = {f["path"] for f in listed["files"]}
        assert str(SAMPLE.resolve()) in paths and str(dumps / "cap.bin") in paths and str(secret) not in paths
        assert c.post("/api/source", json={"kind": "replay", "file": str(secret)}).status_code == 422
        assert c.post("/api/source", json={"kind": "replay", "file": "/etc/passwd"}).status_code == 422
        assert c.post("/api/source", json={"kind": "replay", "file": str(dumps / ".." / "secret.bin")}).status_code == 422
        assert c.post("/api/source", json={"kind": "replay", "file": str(SAMPLE)}).status_code == 200
        assert c.post("/api/source", json={"kind": "replay", "file": str(dumps / "cap.bin")}).status_code == 200

