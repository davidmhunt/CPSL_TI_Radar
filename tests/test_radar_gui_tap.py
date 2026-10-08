"""gui-36 Steps 2-3: Live follows a GUI-started driver run over the tap pipe. Fake driver `tap` / `no-tap` modes
(tests/fakes/fake_driver.py); no hardware. Wire format: radar_gui/tap.py."""
import json
import os
import struct
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import ports, tap
from radar_gui.app import create_app
from radar_gui.sources import MockSource

# Slow loop: subprocess / driver / live-server tests; skip with `uv run pytest -m "not slow"`.
pytestmark = pytest.mark.slow

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    ports.radar_lock.release()
    cli = tmp_path / "ttyFAKE0"
    cli.write_text("")
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir()
    system.mkdir()
    for name in ("rig", "rig_die"):
        (user / f"{name}.json").write_text(json.dumps({"schema_version": 2, "board": "IWR1843", "radar_cfg": "x.cfg",
                                                       "cli": {"port": str(cli)}, "dca1000": {"enabled": True}}))
    monkeypatch.setenv("FAKE_DRIVER_RATE", "50")
    monkeypatch.setenv("FAKE_DRIVER_MODE", "tap")

    def make(**kw):
        return TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE,
                                     run_root=tmp_path / "runs", min_stop_grace=0.5, **kw))
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


def src(c):
    return c.get("/api/source").json()


def cfgp(user, name="rig"):
    return str(user / f"{name}.json")


def test_wire_roundtrip_and_bad_length():
    r, w = os.pipe()
    body = json.dumps({"type": "frame", "frame": 3}).encode()
    os.write(w, struct.pack("<IB", len(body) + 1, tap.POINTS) + body)
    assert tap.read_message(r) == (tap.POINTS, body)
    os.write(w, struct.pack("<I", 0))
    with pytest.raises(tap.TapClosed):
        tap.read_message(r)
    os.close(w)
    with pytest.raises(tap.TapClosed):
        tap.read_message(r)
    os.close(r)
    head, data = tap.decode_adc(b'{"index":3}\n\x01\x00\x02\x00')
    assert head == {"index": 3} and data == b"\x01\x00\x02\x00"


def test_follow_on_start_frames_reach_stream_and_clean_end(env):
    make, user = env
    with make() as c, c.websocket_connect("/stream") as ws:
        assert src(c)["kind"] == "mock"
        assert c.post("/api/driver/start", json={"config": cfgp(user), "frames": 40}).status_code == 200
        wait(lambda: src(c)["kind"] == "driver", what="Live follows the run")
        s = src(c)
        assert s["spec"]["tap"] is True and s["spec"]["name"] == "rig" and s["spec"]["pid"] and ports.radar_lock.owner == "driver"
        got = []
        while len(got) < 3:
            m = ws.receive_json()
            if m["type"] == "frame" and len(m["pts"]) == 4:
                got.append(m)
        assert got[0]["frame"] < got[-1]["frame"] and got[0]["n"] == 4
        end = wait(lambda: src(c)["source_state"] != "running" and src(c), what="run end")
        assert end["source_state"] == "ended" and end["status"]["state"] == "ended"
        assert "driver run ended (exit 0, 40 frames)" == end["status"]["msg"]
        assert end["hello"]["board"] == "IWR1843" and end["frames_in"] == 40
        assert c.get("/api/driver/status").json()["tap"] == "on"
        # the picker is usable again, but nothing fell back to a serial source by itself
        assert src(c)["kind"] == "driver"
        assert c.post("/api/source", json={"kind": "mock"}).json()["kind"] == "mock"


def test_source_card_read_only_while_following(env):
    make, user = env
    with make() as c:
        c.post("/api/driver/start", json={"config": cfgp(user)})
        wait(lambda: src(c)["kind"] == "driver")
        # the fake installs its SIGINT handler before its first tap frame; an earlier SIGINT kills it (died, not ended)
        wait(lambda: src(c).get("frames_in", 0) > 0, what="driver is streaming (handler installed)")
        r = c.post("/api/source", json={"kind": "mock"})
        assert r.status_code == 409 and "Run tab" in r.json()["detail"]
        assert c.post("/api/source/stop").status_code == 409
        c.post("/api/driver/stop")
        wait(lambda: src(c)["source_state"] == "ended", what="ended after stop")


def test_sigkill_is_died(env):
    make, user = env
    with make() as c:
        c.post("/api/driver/start", json={"config": cfgp(user)})
        s = wait(lambda: src(c)["kind"] == "driver" and src(c))
        os.kill(s["spec"]["pid"], 9)
        t0 = time.time()
        d = wait(lambda: src(c)["source_state"] == "died" and src(c), what="died")
        assert time.time() - t0 < 2.5
        assert d["status"] == {"type": "status", "state": "error", "msg": "driver died (exit -9)"}


def test_adc_messages_are_counted():
    """The page does not ask for adc yet (gui-07 is not approved); the reader still parses and counts them."""
    r, w = os.pipe()
    from radar_gui.sources import DriverSource

    class M:
        def status(self, log=True):
            return {"run": 1, "state": "running"}
    ds = DriverSource(M(), 1, "x.json", 1, r)
    head = json.dumps({"index": 6, "shape": [1, 1, 1]}).encode() + b"\n" + b"\0\0\0\0"
    os.write(w, struct.pack("<IB", len(head) + 1, tap.ADC) + head)
    os.close(w)
    ds._read()
    assert ds.adc_in == 1 and ds.last_adc["index"] == 6 and ds.frames_in == 0
    ds.release()


def test_no_tap_binary_runs_untapped(env, monkeypatch):
    make, user = env
    monkeypatch.setenv("FAKE_DRIVER_MODE", "run")
    with make() as c:
        c.post("/api/driver/start", json={"config": cfgp(user), "frames": 10})
        wait(lambda: src(c)["kind"] == "driver")
        assert c.get("/api/driver/status").json()["tap"] in ("off", "on")
        end = wait(lambda: src(c)["source_state"] != "running" and src(c), what="end")
        assert end["spec"]["tap"] is False and end["status"]["state"] == "ended"
        assert end["frames_in"] == 0 and "10 frames" in end["status"]["msg"]
        assert end["source_msg"].startswith("driver run ended")


def test_no_tap_status_says_rebuild(env, monkeypatch):
    make, user = env
    monkeypatch.setenv("FAKE_DRIVER_MODE", "no-tap")
    monkeypatch.setenv("FAKE_DRIVER_RATE", "5")
    with make() as c, c.websocket_connect("/stream") as ws:
        c.post("/api/driver/start", json={"config": cfgp(user)})
        seen = []
        end = time.time() + 10
        while time.time() < end and "no_tap" not in [m.get("state") for m in seen]:
            seen.append(ws.receive_json())
        msg = next(m for m in seen if m.get("state") == "no_tap")["msg"]
        assert "rebuild the driver" in msg
        assert c.get("/api/driver/status").json()["tap"] == "off"
        c.post("/api/driver/stop")


def test_slow_ws_client_does_not_stall_the_pipe_reader(env, monkeypatch):
    make, user = env
    monkeypatch.setenv("FAKE_DRIVER_RATE", "200")
    with make() as c, c.websocket_connect("/stream"):   # connected, never read
        c.post("/api/driver/start", json={"config": cfgp(user), "frames": 400})
        wait(lambda: src(c)["kind"] == "driver")
        end = wait(lambda: src(c)["source_state"] != "running" and src(c), timeout=20, what="end")
        assert end["frames_in"] == 400 and end["source_state"] == "ended"


def test_run_refused_while_serial_source_holds_the_board(env):
    make, user = env
    assert ports.radar_lock.acquire("serial source")
    with make() as c:
        r = c.post("/api/driver/start", json={"config": cfgp(user)})
        assert r.status_code == 409 and "Live serial source holds the radar" in r.json()["detail"]
        assert "stop it in the Live tab" in r.json()["detail"]
        assert src(c)["kind"] == "mock"


def test_default_source_is_none_and_idle():
    from radar_gui.__main__ import parse_args
    from radar_gui.sources import NoSource, make_source
    assert parse_args([]).source == "none"
    with TestClient(create_app(make_source("none"))) as c, c.websocket_connect("/stream") as ws:
        assert c.get("/api/source").json()["kind"] == "none"
        seen = [ws.receive_json() for _ in range(3)]
        assert any(m.get("state") == "idle" and "Serial or Replay" in m["msg"] for m in seen)
        assert next(m for m in seen if m["type"] == "cfg")["name"] == ""
        assert isinstance(create_app(NoSource()).state.hub.source, NoSource)


def test_replay_dialect_detected_from_name_and_overridable(tmp_path):
    from radar_gui.sources import detect_dialect
    assert [detect_dialect(n) for n in ("AWR2243_CASCADE_x.bin", "awr2243_cascade_20frames.bin", "IWR1443_a.bin",
                                        "IWR1843_a.bin", "x.bin")] == ["mcuplus_cascade"] * 2 + ["sdk2", "sdk3", "sdk3"]
    fx = Path(__file__).parent / "fixtures" / "replay"
    with TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=tmp_path)) as c:
        files = {f["name"]: f for f in c.get("/api/source/files").json()["files"]}
        casc = files["awr2243_cascade_20frames.bin"]
        assert casc["dialect"] == "mcuplus_cascade" and files["iwr1843_sdk3_20frames.bin"]["dialect"] == "sdk3"
        assert c.post("/api/source", json={"kind": "replay", "file": casc["path"]}).json()["spec"]["dialect"] == "mcuplus_cascade"
        r = c.post("/api/source", json={"kind": "replay", "file": casc["path"], "dialect": "sdk3"})
        assert r.json()["spec"]["dialect"] == "sdk3"
        assert c.post("/api/source", json={"kind": "replay", "file": casc["path"], "dialect": "bogus"}).status_code == 422


def test_skip_configure_gated_on_usage_text(env, monkeypatch):
    make, user = env
    (user / "casc.json").write_text(json.dumps({"schema_version": 2, "board": "AWR2243_CASCADE", "radar_cfg": "x.cfg",
                                                "cli": {"port": json.loads((user / "rig.json").read_text())["cli"]["port"]}}))
    with make() as c:
        j = c.get("/api/driver/configs").json()
        assert {k: j["caps"][k] for k in ("tap", "skip_configure", "adc_tap")} == {"tap": True, "skip_configure": False, "adc_tap": True}
        assert {x["name"]: x["once_per_boot"] for x in j["configs"]}["casc"] is True
        assert {x["name"]: x["once_per_boot"] for x in j["configs"]}["rig"] is False
        r = c.post("/api/driver/start", json={"config": cfgp(user, "casc"), "skip_configure": True})
        assert r.status_code == 422 and "rebuild the driver" in r.json()["detail"]
    monkeypatch.setenv("FAKE_DRIVER_SKIP", "1")
    with make() as c:
        assert c.get("/api/driver/configs").json()["caps"]["skip_configure"] is True
        assert c.post("/api/driver/start", json={"config": cfgp(user, "casc"), "skip_configure": True, "frames": 5}).status_code == 200
        wait(lambda: any("skip-configure" in ln for ln in c.get("/api/driver/status").json()["log"]), what="flag passed")
