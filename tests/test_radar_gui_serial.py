"""gui-06 Step 1: TLV dialect parsing, SerialSource (configure / stream / reconnect / stall / exclusion) and runtime
source switching. Frames mirror CPSL_TI_Radar_cpp/tests/uart_test_frames.hpp. No hardware: fake CLI and data ports."""
import asyncio
import struct
import time
from functools import partial
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import ports, tlv
from radar_gui.app import create_app
from radar_gui.serial_source import PortBusy, SerialSource, SerialSourceError
from radar_gui.sources import MockSource

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


# ---- fake serial world ---------------------------------------------------------------------------------------
class FakeBoard:
    """A radar behind two fake ports. `cli`/`data` are the paths the opener recognises."""

    def __init__(self, prompt="", reject=None):
        self.present, self.prompt, self.reject = True, prompt, reject   # reject: 1-based CLI line number to refuse
        self.cli_log, self.cli_opens, self.data_opens, self.data_chunks = [], 0, 0, []
        self.lost = False
        self.n = 0

    def exists(self, path):
        return self.present

    def feed(self, *frames):
        self.data_chunks.extend(frames)

    def opener(self, path, baud):
        board = self
        if path in ("cli", "/dev/ttyACM0"):
            board.cli_opens += 1
            return FakeCli(board)
        board.data_opens += 1
        return FakeData(board)


class FakeCli:
    def __init__(self, board):
        self.b, self.out = board, b""

    def write(self, data):
        line = data.decode().strip()
        self.b.cli_log.append(line)
        n = len([x for x in self.b.cli_log if x != "sensorStop"])
        if self.b.reject == n and line != "sensorStop":
            self.out += b"Error: not recognized\n"
        else:
            self.out += b"Done\n" + self.b.prompt.encode()

    def read(self, n):
        out, self.out = self.out[:n], self.out[n:]
        if not out:
            time.sleep(0.005)
        return out

    def reset_input_buffer(self):
        self.out = b""

    def close(self):
        pass


class FakeData:
    def __init__(self, board):
        self.b = board

    def read(self, n):
        if self.b.lost:
            raise OSError("device disconnected")
        if self.b.data_chunks:
            return self.b.data_chunks.pop(0)
        time.sleep(0.01)
        return b""

    def reset_input_buffer(self):
        pass

    def close(self):
        pass


def cfg_file(tmp_path, name="rig.cfg", extra=()):
    p = tmp_path / name
    p.write_text("% a comment\n\n" + "\n".join(["sensorStop", "flushCfg", "calibData 0 0 0", *extra, "sensorStart"]) + "\n")
    return p


def make_src(board_name, cfg, brd, **kw):
    kw.setdefault("on_status", None)
    kw.setdefault("skip_firmware_check", True)   # gui-33: these tests pin the cfg exchange; test_radar_gui_fwident.py covers the check
    return SerialSource(board_name, cfg, "cli", "data", opener=brd.opener, exists=brd.exists,
                        check=lambda p: None, lock=kw.pop("lock", ports.RadarLock()), settle_s=0.01, poll_s=0.01, **kw)


@pytest.fixture(autouse=True)
def free_lock():
    ports.radar_lock.release()
    yield
    ports.radar_lock.release()


def run(coro, timeout=10):
    return asyncio.run(asyncio.wait_for(coro, timeout))


async def take(src, n):
    out, gen = [], src.frames()
    try:
        async for fr in gen:
            out.append(fr)
            if len(out) >= n:
                break
    finally:
        await gen.aclose()
    return out


def test_board_refusals(tmp_path):
    cfg = cfg_file(tmp_path)
    with pytest.raises(SerialSourceError, match="no data UART"):
        SerialSource("IWR1843_SAR", cfg, "cli", "data")
    with pytest.raises(SerialSourceError, match="unknown board"):
        SerialSource("NOPE", cfg, "cli", "data")


def test_configure_happy_path_streams_and_stops(tmp_path):
    brd = FakeBoard()
    brd.feed(sdk3_frame(1), sdk3_frame(2))
    states = []
    src = make_src("IWR1843", cfg_file(tmp_path, extra=["% skipped", "# skipped"]), brd)
    src.on_status = lambda s, m: states.append((s, m))
    frames = run(take(src, 2))
    assert [f["frame"] for f in frames] == [1, 2] and len(frames[0]["pts"]) == 3
    # comment lines are not sent, calibData is (IWR1843 skips nothing); the stop goes out on stop
    assert brd.cli_log == ["sensorStop", "flushCfg", "calibData 0 0 0", "sensorStart", "sensorStop"]
    assert ("configuring", "configuring 4/4 sensorStart") in states
    assert [s for s, _ in states if s in ("waiting", "streaming")][:2] == ["waiting", "streaming"]
    assert not src.claimed


def test_rejected_line_once_per_boot_names_power_cycle(tmp_path):
    brd = FakeBoard(prompt="mmwDemo:/>", reject=1)
    states = []
    src = make_src("AWR2243_CASCADE", cfg_file(tmp_path), brd)
    src.on_status = lambda s, m: states.append((s, m))

    async def go():
        t = asyncio.create_task(take(src, 1))
        await asyncio.sleep(0.3)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(go())
    failed = [m for s, m in states if s == "cfg_failed"]
    assert failed and "flushCfg" in failed[0] and "power-cycle the board" in failed[0] and "not recognized" in failed[0]
    assert brd.data_opens == 0                         # no streaming after a rejected cfg
    assert "sensorStop" not in brd.cli_log[2:]         # and a once-per-boot board never gets a stop command


def test_rejected_line_other_board_has_no_power_cycle_hint(tmp_path):
    brd = FakeBoard(reject=1)
    states = []
    src = make_src("IWR1843", cfg_file(tmp_path), brd)
    src.on_status = lambda s, m: states.append((s, m))

    async def go():
        t = asyncio.create_task(take(src, 1))
        await asyncio.sleep(0.3)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(go())
    failed = [m for s, m in states if s == "cfg_failed"]
    assert failed and "power-cycle" not in failed[0]


def test_cfg_failed_on_repeatable_board_frees_ports_for_retry(tmp_path):
    """D5: no waiting for port loss; the lock is released so a new Start can claim it."""
    brd = FakeBoard(reject=1)
    lock = ports.RadarLock()
    src = make_src("IWR1843", cfg_file(tmp_path), brd, lock=lock)
    states = []
    src.on_status = lambda s, m: states.append((s, m))

    async def go():
        t = asyncio.create_task(take(src, 1))
        await asyncio.sleep(0.3)
        assert lock.owner is None and not src.claimed          # released while the failure is shown
        assert states[-1][0] == "cfg_failed" and "press Start" in states[-1][1]
        assert lock.acquire("serial")                          # a retry can claim it
        lock.release("serial")
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(go())


def test_skip_configure_sends_nothing_and_cascade_stop_just_closes(tmp_path):
    brd = FakeBoard(prompt="mmwDemo:/>")
    brd.feed(make_frame(1, [points_tlv(2, 0.0), side_info_tlv(2)]))
    src = make_src("AWR2243_CASCADE", cfg_file(tmp_path), brd, skip_configure=True)
    assert len(run(take(src, 1))) == 1
    assert brd.cli_opens == 0 and brd.cli_log == []    # no cfg, and no sensorStop on the once-per-boot cascade


def test_compact_points_hint(tmp_path):
    brd = FakeBoard(prompt="mmwDemo:/>")
    brd.feed(make_frame(1, [(12, b"\0" * 24)], num_obj=0))
    states = []
    src = make_src("AWR2243_CASCADE", cfg_file(tmp_path), brd, skip_configure=True)
    src.on_status = lambda s, m: states.append((s, m))
    fr = run(take(src, 1))[0]
    assert fr["compact_points_skipped"] and fr["pts"] == []
    assert ("streaming", "cfg sends compact points; use guiMonitor detectedObjects 1") in states


def test_port_lost_waits_then_reconfigures(tmp_path):
    brd = FakeBoard()
    brd.feed(sdk3_frame(1))
    states = []
    src = make_src("IWR1843", cfg_file(tmp_path), brd)
    src.on_status = lambda s, m: states.append(s)

    async def go():
        out, gen = [], src.frames()
        async for fr in gen:
            out.append(fr["frame"])
            if len(out) == 1:
                brd.lost, brd.present = True, False          # power cycle: reads fail, ports vanish
                asyncio.get_running_loop().call_later(0.3, restore)
            if len(out) == 2:
                break
        await gen.aclose()
        return out

    def restore():
        brd.lost, brd.present = False, True
        brd.feed(sdk3_frame(2))

    assert run(go()) == [1, 2]
    assert "no_board" in states
    assert brd.cli_opens >= 2 and brd.cli_log.count("flushCfg") == 2     # configured again after the reappearance


def test_stall_status(tmp_path):
    brd = FakeBoard()
    brd.feed(sdk3_frame(1))
    states = []
    src = make_src("IWR1843", cfg_file(tmp_path), brd, stall_s=0.15)
    src.on_status = lambda s, m: states.append(s)

    async def go():
        t = asyncio.create_task(take(src, 2))
        await asyncio.sleep(0.6)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    run(go())
    assert "stalled" in states and states.index("streaming") < states.index("stalled")


def test_dump_writes_raw_bytes(tmp_path):
    brd = FakeBoard()
    f1, f2 = sdk3_frame(1), sdk3_frame(2)
    brd.feed(f1, f2)
    src = make_src("IWR1843", cfg_file(tmp_path), brd, dump=str(tmp_path / "cap.bin"))
    run(take(src, 2))
    assert (tmp_path / "cap.bin").read_bytes() == f1 + f2


def test_lock_exclusion_with_driver_run(tmp_path):
    lock = ports.RadarLock()
    brd = FakeBoard()
    src = make_src("IWR1843", cfg_file(tmp_path), brd, lock=lock)
    assert lock.acquire("driver")
    with pytest.raises(PortBusy, match="radar in use by driver"):
        src.claim()
    assert lock.owner == "driver"                      # a refused claim does not disturb the holder
    lock.release("driver")
    src.claim()
    assert lock.owner == "serial" and not lock.acquire("driver")
    src.release()
    assert lock.owner is None


def test_ports_busy_refuses_and_releases_lock(tmp_path):
    lock = ports.RadarLock()
    src = SerialSource("IWR1843", cfg_file(tmp_path), "cli", "data", lock=lock,
                       check=lambda p: "ports busy: cli held by 1 other")
    with pytest.raises(PortBusy, match="ports busy"):
        src.claim()
    assert lock.owner is None


# ---- API end to end -------------------------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path):
    user = tmp_path / "user"
    user.mkdir()
    cfg_file(user, "rig1843.cfg")
    cfg_file(user, "cascade_rig.cfg")
    brd = FakeBoard()
    factory = partial(SerialSource, opener=brd.opener, exists=brd.exists, check=lambda p: None,
                      settle_s=0.01, poll_s=0.01, skip_firmware_check=True)   # FakeBoard answers Done to everything
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, serial_factory=factory))
    yield c, brd, tmp_path
    ports.radar_lock.release()


def frames_from(ws, n, timeout=8):
    got, end = [], time.time() + timeout
    while len(got) < n and time.time() < end:
        m = ws.receive_json()
        if m["type"] == "frame":
            got.append(m)
    return got


def test_api_serial_end_to_end_through_stream(api):
    c, brd, _ = api
    brd.feed(sdk3_frame(1), sdk3_frame(2), sdk3_frame(3))
    with c:
        with c.websocket_connect("/stream") as ws:
            r = c.post("/api/source", json={"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg",
                                            "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1"})
            assert r.status_code == 200 and r.json()["kind"] == "serial"
            fr = None
            for _ in range(200):   # mock frames may still arrive before the swap; the serial ones carry x == 1.0
                m = ws.receive_json()
                if m["type"] == "frame" and m["n"] == 3 and m["pts"][0][0] == 1.0:
                    fr = m
                    break
            assert fr and fr["pts"][0] == [1.0, 2.0, 3.0, 4.0, 10.0, 0.0] and fr["frame"] == 1
        assert ports.radar_lock.owner == "serial"
        assert c.get("/api/state").json()["source"] == "serial"
        assert c.get("/api/source").json()["spec"]["board"] == "IWR1843"
        # (a driver run is refused while the source holds the lock: DriverManager.start uses the same RadarLock,
        # see test_lock_exclusion_with_driver_run)
        # a new serial source replaces the old one (it releases the lock first)
        r2 = c.post("/api/source", json={"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg",
                                         "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1"})
        assert r2.status_code == 200
        assert c.post("/api/source/stop").status_code == 200
        assert ports.radar_lock.owner is None
        assert "sensorStop" in brd.cli_log


def test_api_serial_refused_while_driver_holds_lock_and_old_source_keeps_running(api):
    c, brd, _ = api
    with c:
        assert ports.radar_lock.acquire("driver")
        r = c.post("/api/source", json={"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg",
                                        "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1"})
        assert r.status_code == 409 and "driver" in r.json()["detail"]
        assert c.get("/api/source").json()["kind"] == "mock"          # untouched
        with c.websocket_connect("/stream") as ws:
            assert frames_from(ws, 1)


def test_api_validation_errors(api):
    c, _, _ = api
    with c:
        def post(**kw):
            return c.post("/api/source", json={"kind": "serial", "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1", **kw})
        assert post(board="IWR1843").status_code == 422                                   # no cfg
        assert post(board="IWR1843_SAR", cfg_id="user:rig1843.cfg").status_code == 422   # no data UART
        assert post(board="IWR1843", cfg_id="user:nope.cfg").status_code == 422
        assert post(board="IWR1843", cfg_id="user:cascade_rig.cfg").status_code == 422   # cascade cfg on a single chip
        assert post(board="AWR2243_CASCADE", cfg_id="user:rig1843.cfg").status_code == 422
        assert c.post("/api/source", json={"kind": "replay", "file": "/nonexistent.bin"}).status_code == 422
        assert c.get("/api/source").json()["kind"] == "mock"


def test_api_boards_listing(api):
    c, _, _ = api
    with c:
        bs = {b["board"]: b for b in c.get("/api/source/boards").json()["boards"]}
        assert "IWR1843_SAR" not in bs
        assert bs["AWR2243_CASCADE"]["once_per_boot"] and bs["AWR2243_CASCADE"]["tlv_dialect"] == "mcuplus_cascade"
        assert bs["IWR1443"]["tlv_dialect"] == "sdk2" and not bs["IWR1843"]["once_per_boot"]


def test_cfg_hint_max_range_from_cfg_metrics(tmp_path):
    brd = FakeBoard()
    shipped = Path(__file__).parent.parent / "CPSL_TI_Radar_cpp/config/radar/IWR6843/demo/default.cfg"
    src = make_src("IWR6843", shipped, brd)
    assert src.info["max_range_m"] != 10 and src.info["max_range_m"] > 0 and src.info["fov"]
    assert make_src("IWR1843", cfg_file(tmp_path), brd).info["max_range_m"] == 10     # unanalysable cfg: default hint


def test_switch_replay_mock_replay_keeps_streaming(tmp_path):
    app = create_app(__import__("radar_gui.sources", fromlist=["x"]).ReplaySource(str(SAMPLE), rate_hz=200),
                     user_cfg_dir=tmp_path)
    with TestClient(app) as c, c.websocket_connect("/stream") as ws:
        assert frames_from(ws, 2)
        for kind in ("mock", "replay", "mock", "replay"):
            r = c.post("/api/source", json={"kind": kind, "rate_hz": 200})
            assert r.status_code == 200 and r.json()["kind"] == kind
            fr = frames_from(ws, 3)
            assert len(fr) == 3
            assert c.get("/api/state").json()["source"] == kind


# ---- security: replay allowlist and confined dump target ---------------------------------------------------------
def test_replay_file_allowlist(api, tmp_path, monkeypatch):
    c, _, _ = api
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


def test_api_serial_ports_restricted_to_usb_serial(api):
    """D4: only /dev/serial/by-id/*, /dev/ttyACM<N>, /dev/ttyUSB<N>."""
    c, _, _ = api
    base = {"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg"}
    with c:
        for bad in ("/dev/tty", "/dev/ttyS0", "/dev/null", "/dev/serial/by-id/../../tty", "/dev/ttyACM", "cli", "/etc/passwd"):
            for key in ("cli_port", "data_port"):
                body = {**base, "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1", key: bad}
                r = c.post("/api/source", json=body)
                assert r.status_code == 422 and "not allowed" in r.json()["detail"], (key, bad)
        assert c.get("/api/source").json()["kind"] == "mock"
        for ok in ("/dev/ttyUSB3", "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.05__Embed_with_CMSIS-DAP_R2101050-if00"):
            r = c.post("/api/source", json={**base, "cli_port": "/dev/ttyACM0", "data_port": ok})
            assert r.status_code == 200, ok


def test_dump_target_confined_to_dump_dir(api, tmp_path, monkeypatch):
    c, _, _ = api
    dumps = tmp_path / "dumps"
    monkeypatch.setenv("RADAR_GUI_DUMP_DIR", str(dumps))
    body = {"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg", "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1"}
    with c:
        for bad in ("/tmp/evil.bin", "../evil.bin", "a/b.bin", "..", ".hidden"):
            assert c.post("/api/source", json={**body, "dump": bad}).status_code == 422, bad
        r = c.post("/api/source", json={**body, "dump": "cap1.bin"})
        assert r.status_code == 200 and r.json()["spec"]["dump"] == str(dumps / "cap1.bin")
        assert c.post("/api/source/stop").status_code == 200
