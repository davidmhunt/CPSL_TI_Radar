"""gui-37 Step 1: the effective session.json of a driver start (saved config + overrides, or a quick setup), the caps
that gate its optional keys, /api/driver/boards and driver.log in the run folder. Fake driver, no hardware."""
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import ports, session_cfg
from radar_gui.app import create_app
from radar_gui.sources import MockSource

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")
CLI0, CLI1 = "/dev/ttyACM7", "/dev/ttyACM8"


def wait_for(c, states, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get("/api/driver/status").json()
        if st["state"] in states:
            return st
        time.sleep(0.05)
    raise AssertionError(f"state never reached {states}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    ports.radar_lock.release()
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir()
    system.mkdir()
    (user / "rig.cfg").write_text("% test cfg\nsensorStart\n")
    (user / "cascade_rig.cfg").write_text("% test cfg\n")
    (tmp_path / "data").mkdir()
    cfg = user / "rig.json"
    cfg.write_text(json.dumps({"schema_version": 2, "board": "IWR1843", "radar_cfg": "rig.cfg",
                               "cli": {"port": "/dev/ttyACM0"}, "serial_stream": {"enabled": True, "port": "/dev/ttyACM1"},
                               "dca1000": {"enabled": True}, "output": {"dir": "../data", "save_adc_frames": False},
                               "firmware": "demo", "runtime": {"log_level": "info"}}))
    monkeypatch.setenv("FAKE_DRIVER_RATE", "50")
    monkeypatch.setattr("radar_gui.ports.check_ports", lambda p: None)   # the fake ports do not exist
    monkeypatch.setattr("radar_gui.driver.check_ports", lambda p: None)

    def make(**kw):
        return TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE,
                                     run_root=tmp_path / "runs", min_stop_grace=0.5, **kw))
    yield make, cfg, tmp_path
    ports.radar_lock.release()


def session_of(c, st=None):
    st = st or c.get("/api/driver/status").json()
    return json.loads(Path(st["session_json"]).read_text()), Path(st["run_dir"])


def stop(c):
    end = time.time() + 20   # the fake installs its SIGINT handler before it prints "Using config" (see test_radar_gui_driver)
    while time.time() < end and not any("Using config" in ln for ln in c.get("/api/driver/status").json()["log"]):
        time.sleep(0.05)
    c.post("/api/driver/stop")
    wait_for(c, ("exited", "failed"))


# ---- saved config + overrides -------------------------------------------------------------------------------
def test_saved_config_session_json_and_run_folder(env):
    make, cfg, tmp = env
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"save_adc_frames": True, "skip_configure": False}})
        assert r.status_code == 200, r.text
        st = r.json()
        eff, run = session_of(c, st)
        assert run.parent == tmp / "runs" and run.name.endswith("_rig")
        assert (run / "radar.cfg").read_text() == (tmp / "user" / "rig.cfg").read_text()
        assert eff["radar_cfg"] == "radar.cfg"
        assert Path(eff["board"]).is_absolute() and Path(eff["board"]).name == "IWR1843.json"
        assert eff["output"] == {"dir": str((tmp / "data").resolve()), "save_adc_frames": True}
        assert eff["firmware"] == "demo" and eff["cli"]["port"] == "/dev/ttyACM0"
        assert st["saving"] == {"save_adc_frames": True, "save_raw_lvds": False, "save_serial_bytes": False}
        assert st["label"] == "rig" and st["firmware"] == "demo" and st["config"] == str(cfg.resolve())
        stop(c)
        log = (run / "driver.log").read_text()
        assert f"Using config: {run / 'session.json'}" in log and "Stopped." in log


def test_plain_start_still_writes_session(env):
    make, cfg, tmp = env
    with make() as c:
        assert c.post("/api/driver/start", json={"config": str(cfg)}).status_code == 200
        eff, run = session_of(c)
        assert eff["output"]["save_adc_frames"] is False and "skip_configure" not in eff.get("runtime", {})
        stop(c)
        assert {p.name for p in run.iterdir()} >= {"session.json", "radar.cfg", "driver.log"}


def test_overrides_firmware_check_skip_and_validation(env):
    make, cfg, _ = env
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"firmware_check": "off", "skip_configure": True}})
        assert r.status_code == 200, r.text
        eff, _run = session_of(c, r.json())
        assert eff["runtime"] == {"log_level": "info", "firmware_check": "off", "skip_configure": True}
        stop(c)
        assert c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"firmware_check": "maybe"}}).status_code == 422
        assert c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"nonsense": 1}}).status_code == 422


def test_save_without_dca_refused(env):
    make, cfg, tmp = env
    doc = json.loads(cfg.read_text())
    doc["dca1000"]["enabled"] = False
    cfg.write_text(json.dumps(doc))
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"save_adc_frames": True}})
        assert r.status_code == 422 and "DCA1000" in r.json()["detail"]
        assert not (tmp / "runs").exists() or not list((tmp / "runs").iterdir())


# ---- caps gate the optional keys ----------------------------------------------------------------------------
def test_caps_new_build_vs_rebuild_1(env, monkeypatch):
    make, cfg, _ = env
    with make() as c:
        caps = c.get("/api/driver/configs").json()["caps"]
        assert caps["setup"] is True and caps["firmware_key"] and caps["firmware_check"] and caps["save_serial_bytes"]
    monkeypatch.setenv("FAKE_DRIVER_KEYS", "")
    with make() as c:
        caps = c.get("/api/driver/configs").json()["caps"]
        assert caps["setup"] is True and not (caps["firmware_key"] or caps["firmware_check"] or caps["save_serial_bytes"])
    monkeypatch.setenv("FAKE_DRIVER_KEYS", "firmware")
    with make() as c:
        caps = c.get("/api/driver/configs").json()["caps"]
        assert (caps["firmware_key"], caps["firmware_check"], caps["save_serial_bytes"]) == (True, False, False)


def test_rebuild_1_binary_gets_no_new_keys(env, monkeypatch):
    make, cfg, _ = env
    monkeypatch.setenv("FAKE_DRIVER_KEYS", "")
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"firmware_check": "warn"}})
        assert r.status_code == 200, r.text   # the fake would reject the keys at --validate
        eff, _run = session_of(c, r.json())
        assert "firmware" not in eff and "firmware_check" not in eff["runtime"]
        assert any("firmware" in n for n in r.json()["notes"]) and r.json()["firmware"] is None
        stop(c)
        r = c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"save_serial_bytes": True}})
        assert r.status_code == 422 and "save_serial_bytes" in r.json()["detail"]


def test_new_binary_gets_keys_and_serial_bytes(env):
    make, cfg, _ = env
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg), "overrides": {"save_serial_bytes": True, "firmware_check": "warn"}})
        assert r.status_code == 200, r.text
        eff, _run = session_of(c, r.json())
        assert eff["output"]["save_serial_bytes"] is True and eff["runtime"]["firmware_check"] == "warn" and eff["firmware"] == "demo"
        assert r.json()["saving"]["save_serial_bytes"] is True


# ---- quick setup --------------------------------------------------------------------------------------------
def quick(**kw):
    return {"setup": {"board": "IWR1843", "cfg_id": "user:rig.cfg", "cli_port": CLI0, "data_port": CLI1, **kw}}


def test_quick_setup_defaults_serial_only(env):
    make, _cfg, tmp = env
    with make() as c:
        r = c.post("/api/driver/start", json=quick())
        assert r.status_code == 200, r.text
        eff, run = session_of(c, r.json())
        assert eff["board"].endswith("config/boards/IWR1843.json") and eff["radar_cfg"] == "radar.cfg"
        assert eff["firmware"] == "demo" and eff["cli"] == {"port": CLI0}
        assert eff["serial_stream"] == {"enabled": True, "port": CLI1}
        assert eff["dca1000"]["enabled"] is False and eff["dca1000"]["fpga_ip"] == "192.168.33.180"
        assert "output" not in eff and eff["runtime"] == {"log_level": "info"}
        assert (run / "radar.cfg").is_file() and run.name.endswith("_quick_IWR1843_rig")
        st = r.json()
        assert st["label"] == "IWR1843 · rig" and st["config"] == str(run / "session.json") and st["adc_reason"] == "no_dca"
        stop(c)


def test_quick_setup_is_followed_by_live(env, monkeypatch):
    monkeypatch.setenv("FAKE_DRIVER_MODE", "tap")
    make, _cfg, _ = env
    with make() as c:
        assert c.post("/api/driver/start", json=quick(dca1000=True, save_adc_frames=True)).status_code == 200
        end = time.time() + 10
        while time.time() < end and c.get("/api/source").json()["kind"] != "driver":
            time.sleep(0.05)
        src = c.get("/api/source").json()
        assert src["kind"] == "driver" and src["config"].endswith("session.json")
        eff, _ = session_of(c)
        assert eff["dca1000"]["enabled"] and eff["output"] == {"save_adc_frames": True}
        stop(c)


def test_quick_setup_refusals(env):
    make, cfg, tmp = env
    with make() as c:
        def code(body):
            return c.post("/api/driver/start", json=body)
        # DCA1000 only where the firmware streams LVDS
        r = code({"setup": {"board": "AWR2243_CASCADE", "cfg_id": "user:cascade_rig.cfg", "dca1000": True}})
        assert r.status_code == 422 and "no LVDS output" in r.json()["detail"]
        assert code(quick(save_adc_frames=True)).status_code == 422                 # saving needs the DCA1000
        assert code(quick(serial=False)).status_code == 422                          # nothing to stream
        assert code(quick(cli_port="/etc/passwd")).status_code == 422
        assert code(quick(data_port="/dev/sda")).status_code == 422
        assert code(quick(firmware="nope")).status_code == 422
        assert code(quick(fpga_ip="not-an-ip")).status_code == 422
        assert code({"setup": {"board": "IWR1843", "cfg_id": "user:../x.cfg"}}).status_code == 422
        assert code({"setup": {"board": "IWR1843", "cfg_id": "user:cascade_rig.cfg"}}).status_code == 422   # cascade cfg, 1843 board
        assert code({"setup": {"board": "IWR9999", "cfg_id": "user:rig.cfg"}}).status_code == 422
        assert code({**quick(), "config": str(cfg)}).status_code == 422
        assert code({}).status_code == 422
        assert code({**quick(), "overrides": {"skip_configure": True}}).status_code == 422
        assert not (tmp / "runs").exists() or not list((tmp / "runs").iterdir())


def test_quick_setup_sar_firmware_writes_driver_board(env):
    make, _cfg, _ = env
    with make() as c:
        r = c.post("/api/driver/start", json=quick(firmware="iwr1843_sar_lvds"))
        assert r.status_code == 200, r.text
        eff, _ = session_of(c, r.json())
        assert eff["board"].endswith("IWR1843_SAR.json") and eff["firmware"] == "iwr1843_sar_lvds"
        assert eff["serial_stream"]["enabled"] is False and eff["dca1000"]["enabled"] is True
        stop(c)


def test_validate_refusal_reaches_the_page_and_leaves_no_folder(env, monkeypatch):
    monkeypatch.setenv("FAKE_DRIVER_MODE", "validate-invalid")
    make, cfg, tmp = env
    with make() as c:
        for body in ({"config": str(cfg)}, quick()):
            r = c.post("/api/driver/start", json=body)
            assert r.status_code == 422 and "INVALID" in r.json()["detail"], r.text
        assert c.get("/api/driver/status").json()["state"] == "idle"
        assert not (tmp / "runs").exists() or not list((tmp / "runs").iterdir())
        assert ports.radar_lock.owner is None


# ---- boards ---------------------------------------------------------------------------------------------------
def test_boards_endpoint(env):
    make, _cfg, _ = env
    with make() as c:
        bs = {b["board"]: b for b in c.get("/api/driver/boards").json()["boards"]}
        assert list(bs) == list(session_cfg.SERIAL_BOARDS)
        b = bs["IWR1843"]
        old = {x["board"]: x for x in c.get("/api/source/boards").json()["boards"]}["IWR1843"]
        assert all(b[k] == old[k] for k in old)                       # the same data as /api/source/boards ...
        assert b["default_firmware"] == "demo"                        # ... plus the firmwares
        fw = {f["id"]: f for f in b["firmwares"]}
        assert fw["demo"]["tlv"] and fw["demo"]["lvds"] and not fw["demo"]["dca1000"]
        assert not fw["iwr1843_sar_lvds"]["tlv"] and fw["iwr1843_sar_lvds"]["dca1000"]
        assert bs["AWR2243_CASCADE"]["once_per_boot"] is True
        assert [f["lvds"] for f in bs["AWR2243_CASCADE"]["firmwares"]] == [False]


def test_run_folders_do_not_collide(env):
    make, cfg, _ = env
    with make() as c:
        runs = []
        for _ in range(2):
            r = c.post("/api/driver/start", json={"config": str(cfg), "frames": 1})
            assert r.status_code == 200, r.text
            runs.append(r.json()["run_dir"])
            wait_for(c, ("exited", "failed"))
        assert runs[0] != runs[1]


def test_probe_caps_relative_binary_path(env, monkeypatch):
    """A relative driver path gives the same caps as the absolute one (the probe runs in a temp cwd)."""
    from radar_gui import driver
    rel = Path(os.path.relpath(FAKE, Path.cwd()))
    assert not rel.is_absolute()
    want = session_cfg.probe_caps(Path(FAKE).absolute())
    assert want["firmware_key"] and want["firmware_check"] and want["save_serial_bytes"]
    assert session_cfg.probe_caps(rel) == want
    monkeypatch.setenv("FAKE_DRIVER_KEYS", "firmware")
    assert session_cfg.probe_caps(rel) == session_cfg.probe_caps(Path(FAKE).absolute())
    assert driver.driver_bin(str(rel)).is_absolute()
    real = Path(driver.DEFAULT_BIN)
    if real.exists():
        monkeypatch.undo()
        r = Path(os.path.relpath(real, Path.cwd()))
        assert session_cfg.probe_caps(r) == session_cfg.probe_caps(real)
