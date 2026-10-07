"""gui-07 Step 2: ADC views plumbing: --tap-adc-every pass-through (gate), the /adc binary WebSocket, panel states.
Fake driver (tests/fakes/fake_driver.py) in `tap` mode with FAKE_DRIVER_ADC=bench; no hardware."""
import json
import shutil
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import adc, ports
from radar_gui.app import create_app
from radar_gui.sources import MockSource

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")
FIX = Path(__file__).parent / "fixtures" / "adc"


@pytest.fixture
def env(tmp_path, monkeypatch):
    ports.radar_lock.release()
    cli = tmp_path / "ttyFAKE0"
    cli.write_text("")
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir()
    system.mkdir()
    shutil.copy(FIX / "bench_1843_dca.cfg", user / "bench_1843_dca.cfg")
    base = json.loads((FIX / "bench_1843_dca.json").read_text())
    base.update(cli={"port": str(cli)}, serial_stream={"enabled": False})
    (user / "dca.json").write_text(json.dumps(base))
    (user / "nodca.json").write_text(json.dumps({**base, "dca1000": {"enabled": False}}))
    monkeypatch.setenv("FAKE_DRIVER_RATE", "40")
    monkeypatch.setenv("FAKE_DRIVER_MODE", "tap")
    monkeypatch.setenv("FAKE_DRIVER_ADC", "bench")

    def make():
        return TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE,
                                     run_root=tmp_path / "runs", min_stop_grace=0.5))
    yield make, user
    ports.radar_lock.release()


def wait(pred, timeout=15, what="condition"):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError(f"never: {what}")


def parse(b: bytes):
    n = struct.unpack_from("<I", b)[0]
    return json.loads(b[4:4 + n]), b[4 + n:]


def next_frame(ws, n=40):
    for _ in range(n):
        h, body = parse(ws.receive_bytes())
        if h["kind"] == "frame":
            return h, body
    raise AssertionError("no ADC frame")


def start(c, user, name="dca", **kw):
    r = c.post("/api/driver/start", json={"config": str(user / f"{name}.json"), **kw})
    assert r.status_code == 200, r.text
    return r.json()


def log_has(c, text):
    return any(text in ln for ln in c.get("/api/driver/status").json()["log"])


def test_idle_state_is_none(env):
    make, _ = env
    with make() as c, c.websocket_connect("/adc") as ws:
        h, _ = parse(ws.receive_bytes())
        assert h["kind"] == "status" and h["state"] == "none" and h["msg"] == adc.MSG_NO_RUN


def test_k_default_is_every_frame_and_is_parameterizable(env):
    make, user = env
    with make() as c:
        st = start(c, user, frames=3)
        assert st["adc_every"] == 1 and st["adc_reason"] is None
        wait(lambda: log_has(c, "tap: adc_every=1"), what="driver got K=1")
        wait(lambda: c.get("/api/driver/status").json()["state"] != "running")
        st = start(c, user, frames=3, adc_every=3)
        assert st["adc_every"] == 3
        wait(lambda: log_has(c, "tap: adc_every=3"), what="driver got K=3")
        wait(lambda: c.get("/api/driver/status").json()["state"] != "running")


def test_off_and_no_dca_omit_the_flag(env):
    make, user = env
    with make() as c:
        st = start(c, user, frames=3, adc_every=0)
        assert st["adc_every"] == 0 and st["adc_reason"] == "off"
        wait(lambda: log_has(c, "tap: adc_every=0"))
        with c.websocket_connect("/adc") as ws:
            h, _ = parse(ws.receive_bytes())
            assert h["state"] == "off" and h["msg"] == adc.MSG_OFF
        wait(lambda: c.get("/api/driver/status").json()["state"] != "running")
        st = start(c, user, "nodca", frames=3)
        assert st["adc_every"] == 0 and st["adc_reason"] == "no_dca"
        wait(lambda: log_has(c, "tap: adc_every=0"))
        with c.websocket_connect("/adc") as ws:
            h, _ = parse(ws.receive_bytes())
            assert h["state"] == "no_dca" and h["msg"] == adc.MSG_NO_DCA


def test_binary_without_adc_tap_or_tap_shows_rebuild(env, monkeypatch):
    make, user = env
    monkeypatch.setenv("FAKE_DRIVER_NO_ADC_TAP", "1")
    with make() as c:
        assert c.get("/api/driver/configs").json()["caps"]["adc_tap"] is False
        st = start(c, user, frames=3)
        assert st["adc_every"] == 0 and st["adc_reason"] == "no_adc_tap"
        with c.websocket_connect("/adc") as ws:
            h, _ = parse(ws.receive_bytes())
            assert h["state"] == "no_tap" and "rebuild" in h["msg"]
        wait(lambda: c.get("/api/driver/status").json()["state"] != "running")
    monkeypatch.setenv("FAKE_DRIVER_MODE", "no-tap")
    with make() as c:
        start(c, user, frames=3)
        with c.websocket_connect("/adc") as ws:
            h, _ = parse(ws.receive_bytes())
            assert h["state"] == "no_tap"


def test_frames_reach_adc_with_exact_bins_then_ended(env):
    make, user = env
    with make() as c:
        start(c, user, frames=30)
        with c.websocket_connect("/adc") as ws:
            h, body = next_frame(ws)
            assert h["profile_peak_bin"] == 34 and h["rd"]["peak"] == [64 + 10, 34] and h["ra"]["peak"] == [43, 34]
            assert h["shape"] == [4, 128, 256] and h["adc_in"] >= 1 and h["partial"] is False
            assert sum(a["bytes"] for a in h["arrays"]) == len(body)
            wait(lambda: c.get("/api/driver/status").json()["state"] != "running")
            seen = None
            for _ in range(60):
                m, _b = parse(ws.receive_bytes())
                if m["kind"] == "status" and m["state"] == "ended":
                    seen = m
                    break
            assert seen is not None and seen["adc_in"] >= 1


def test_slow_adc_client_does_not_stall_stream(env):
    make, user = env
    with make() as c, c.websocket_connect("/adc"), c.websocket_connect("/stream") as st:   # /adc is never read
        start(c, user, frames=60)
        frames = 0
        end = time.time() + 10
        while time.time() < end and frames < 30:
            m = st.receive_json()
            frames += m.get("type") == "frame"
        assert frames >= 30


def test_clutter_option_changes_the_view(env):
    make, user = env
    with make() as c:
        start(c, user)
        with c.websocket_connect("/adc") as ws:
            h, _ = next_frame(ws)
            assert h["profile_peak_bin"] == 34
            ws.send_text(json.dumps({"clutter": True, "chirp": 3}))
            for _ in range(80):
                h, _b = next_frame(ws)
                if h["diag"]["chirp"] == 3:
                    break
            assert h["diag"]["chirp"] == 3
        c.post("/api/driver/stop")
        wait(lambda: c.get("/api/driver/status").json()["state"] != "running")
