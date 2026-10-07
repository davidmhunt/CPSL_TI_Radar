"""Driver run control (gui-05 Step 1) against tests/fakes/fake_driver.py. No hardware, no real ports."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import ports
from radar_gui.app import create_app
from radar_gui.driver import parse_validate
from radar_gui.sources import MockSource

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")


def wait_for(c, states, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        st = c.get("/api/driver/status").json()
        if st["state"] in states:
            return st
        time.sleep(0.05)
    raise AssertionError(f"state never reached {states}: {c.get('/api/driver/status').json()['state']}")


@pytest.fixture
def env(tmp_path, monkeypatch):
    ports.radar_lock.release()
    cli = tmp_path / "ttyFAKE0"
    cli.write_text("")
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir()
    system.mkdir()
    cfg = user / "rig.json"
    cfg.write_text(json.dumps({"schema_version": 2, "board": "IWR1843", "radar_cfg": "x.cfg",
                               "cli": {"port": str(cli)}, "dca1000": {"enabled": True}}))
    monkeypatch.setenv("FAKE_DRIVER_RATE", "50")

    def make(**kw):
        return TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE,
                                     run_root=tmp_path / "runs", min_stop_grace=0.5, **kw))
    yield make, cfg, cli, tmp_path
    ports.radar_lock.release()


def test_configs_and_unlisted_config_refused(env):
    make, cfg, _, tmp = env
    with make() as c:
        cs = c.get("/api/driver/configs").json()["configs"]
        assert [(x["name"], x["group"]) for x in cs] == [("rig", "user")]
        bad = tmp / "other.json"
        bad.write_text("{}")
        assert c.post("/api/driver/start", json={"config": str(bad)}).status_code == 422


def test_validate_parse(env):
    make, cfg, _, _ = env
    with make() as c:
        v = c.post("/api/driver/validate", json={"config": str(cfg)}).json()
        assert v["ok"] and v["exit"] == 0 and v["bytes_per_frame"] == 1000
        assert v["frame"]["period_ms"] == 100 and v["frame"]["samples"] == 256
        assert v["notes"] == ["IWR1843 accepts a cfg once per power-up"]


def test_validate_invalid(env, monkeypatch):
    make, cfg, _, _ = env
    monkeypatch.setenv("FAKE_DRIVER_MODE", "validate-invalid")
    with make() as c:
        v = c.post("/api/driver/validate", json={"config": str(cfg)}).json()
        assert not v["ok"] and v["exit"] == 1 and "INVALID" in v["text"]
        r = c.post("/api/driver/start", json={"config": str(cfg)})
        assert r.status_code == 422 and wait_for(c, {"idle"})["state"] == "idle"


def test_parse_validate_unit():
    v = parse_validate("frame:      4 rx x 8 samples x 2 chirps, 50 ms period\nbytes/frame: 256\nOK: x\n", 0)
    assert v["ok"] and v["bytes_per_frame"] == 256 and v["frame"]["period_ms"] == 50


def test_start_stats_ws_and_stop(env):
    make, cfg, _, tmp = env
    with make() as c, c.websocket_connect("/stream") as ws:
        r = c.post("/api/driver/start", json={"config": str(cfg)})
        assert r.status_code == 200 and r.json()["state"] == "running"
        assert (tmp / "runs").is_dir() and "rig" in r.json()["run_dir"]
        seen = set()
        end = time.time() + 10
        while time.time() < end and not {"driver_stats", "driver_log_batch", "driver_state"} <= seen:
            seen.add(ws.receive_json()["type"])
        assert {"driver_stats", "driver_log_batch", "driver_state"} <= seen
        time.sleep(0.6)
        st = c.get("/api/driver/status").json()
        assert st["pid"] and st["stats"]["dca"]["frames"] > 0 and st["stats"]["serial"]["frames"] > 0
        assert 20 < st["stats"]["dca"]["rate_hz"] < 80  # fake runs at 50 Hz
        assert any(ln.startswith("stats v1 dca") for ln in st["log"])
        assert c.post("/api/driver/stop").json()["state"] == "stopping"
        st = wait_for(c, {"exited", "failed"})
        assert st["state"] == "exited" and st["exit_code"] == 0 and st["error"] is None
        assert st["stats"]["dca"]["frames"] > 0 and any(ln == "Stopped." for ln in st["log"])
        assert ports.radar_lock.owner is None


def test_frames_limit_ends_run(env):
    make, cfg, _, _ = env
    with make() as c:
        c.post("/api/driver/start", json={"config": str(cfg), "frames": 10})
        st = wait_for(c, {"exited", "failed"})
        assert st["state"] == "exited" and st["stats"]["dca"]["frames"] == 10


def test_sigkill_fallback(env, monkeypatch):
    make, cfg, _, _ = env
    monkeypatch.setenv("FAKE_DRIVER_MODE", "ignore-sigint")
    with make() as c:
        c.post("/api/driver/start", json={"config": str(cfg)})
        time.sleep(0.4)
        t0 = time.time()
        c.post("/api/driver/stop")
        st = wait_for(c, {"exited", "failed"})
        assert st["state"] == "failed" and "SIGKILL" in st["error"] and st["exit_code"] < 0
        assert 0.4 < time.time() - t0 < 5
        assert ports.radar_lock.owner is None


def test_crash(env, monkeypatch):
    make, cfg, _, _ = env
    monkeypatch.setenv("FAKE_DRIVER_MODE", "crash")
    with make() as c:
        c.post("/api/driver/start", json={"config": str(cfg)})
        st = wait_for(c, {"exited", "failed"})
        assert st["state"] == "failed" and st["exit_code"] == 3 and "code 3" in st["error"]
        assert any("lost the DCA1000" in ln for ln in st["log"])
        # a crashed run does not block the next one
        monkeypatch.setenv("FAKE_DRIVER_MODE", "run")
        assert c.post("/api/driver/start", json={"config": str(cfg), "frames": 3}).status_code == 200
        wait_for(c, {"exited"})


def test_double_start_refused(env):
    make, cfg, _, _ = env
    with make() as c:
        assert c.post("/api/driver/start", json={"config": str(cfg)}).status_code == 200
        r = c.post("/api/driver/start", json={"config": str(cfg)})
        assert r.status_code == 409 and "already running" in r.json()["detail"]
        c.post("/api/driver/stop")
        wait_for(c, {"exited"})
        assert c.post("/api/driver/stop").status_code == 409  # nothing to stop


def test_radar_lock_held_elsewhere_refused(env):
    make, cfg, _, _ = env
    assert ports.radar_lock.acquire("serial source")
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg)})
        assert r.status_code == 409 and "serial source" in r.json()["detail"]


def test_ports_busy_refused_and_missing_port(env):
    make, cfg, cli, tmp = env
    holder = subprocess.Popen([sys.executable, "-c", f"import time; f=open({str(cli)!r}); time.sleep(30)"])
    try:
        time.sleep(0.5)
        with make() as c:
            r = c.post("/api/driver/start", json={"config": str(cfg)})
            assert r.status_code == 409
            assert f"ports busy: {cli} held by {holder.pid} " in r.json()["detail"]
            assert ports.radar_lock.owner is None  # refusal released the lock
    finally:
        holder.kill()
        holder.wait()
    cli.rename(tmp / "gone")
    with make() as c:
        r = c.post("/api/driver/start", json={"config": str(cfg)})
        assert r.status_code == 409 and "not found" in r.json()["detail"]


def test_ports_resolve_symlink(tmp_path):
    real = tmp_path / "ttyX"
    real.write_text("")
    link = tmp_path / "by-id-link"
    link.symlink_to(real)
    h = subprocess.Popen([sys.executable, "-c", f"import time; f=open({str(real)!r}); time.sleep(30)"])
    try:
        time.sleep(0.5)
        assert [p for p, _ in ports.holders(str(link))] == [h.pid]
    finally:
        h.kill()
        h.wait()


def test_run_dir_files_and_bin_verdict(env, monkeypatch):
    make, cfg, _, tmp = env
    monkeypatch.setenv("FAKE_DRIVER_MODE", "write-bin")
    with make() as c:
        c.post("/api/driver/start", json={"config": str(cfg), "frames": 12})
        st = wait_for(c, {"exited", "failed"})
        assert st["state"] == "exited"
        run = Path(st["run_dir"])
        assert run.parent == tmp / "runs" and run.name.endswith("_rig")
        assert [f for f in st["files"] if f["name"] == "adc_data.bin"] == [{"name": "adc_data.bin", "size": 12000}]
        assert st["bin_verdict"]["verdict"] == "exact" and st["bin_verdict"]["expected_bytes"] == 12000


def test_output_dir_in_json_is_used(env, monkeypatch):
    make, cfg, _, tmp = env
    j = json.loads(cfg.read_text())
    j["output"] = {"dir": str(tmp / "elsewhere")}
    cfg.write_text(json.dumps(j))
    (tmp / "elsewhere").mkdir()
    # the fake writes into its cwd; check that files are listed from the configured dir (empty here)
    monkeypatch.setenv("FAKE_DRIVER_MODE", "write-bin")
    with make() as c:
        c.post("/api/driver/start", json={"config": str(cfg), "frames": 3})
        st = wait_for(c, {"exited"})
        assert st["files"] == [] and "elsewhere" not in st["run_dir"]


def test_missing_binary_is_503(env):
    make, cfg, _, tmp = env
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=cfg.parent, system_cfg_dir=tmp / "system",
                              driver_bin=str(tmp / "nope")))
    with c:
        r = c.post("/api/driver/validate", json={"config": str(cfg)})
        assert r.status_code == 503 and "not found" in r.json()["detail"]


def test_user_dir_env_override_lists_configs(env, monkeypatch):
    """The Run tab's picker must see the same saved-config dir the Configure tab saves to (RADAR_GUI_USER_CFG_DIR)."""
    _, cfg, _, tmp = env
    monkeypatch.setenv("RADAR_GUI_USER_CFG_DIR", str(cfg.parent))
    with TestClient(create_app(MockSource(rate_hz=5), driver_bin=FAKE, system_cfg_dir=tmp / "system",
                               run_root=tmp / "runs")) as c:
        assert [x["name"] for x in c.get("/api/driver/configs").json()["configs"]] == ["rig"]


def test_run_tab_is_served(env):
    make, *_ = env
    with make() as c:
        html = c.get("/").text
        assert 'data-tab="run"' in html and 'id="runMain"' in html
        assert c.get("/js/run.js").status_code == 200


def test_log_batches_keep_order_and_lose_nothing(env, monkeypatch):
    """gui-09 D8: output lines reach the page as driver_log_batch, in order, and the tail is flushed before the exit state."""
    make, cfg, _, _ = env
    monkeypatch.setenv("FAKE_DRIVER_LOG_LPS", "200")
    monkeypatch.setenv("FAKE_DRIVER_RATE", "50")
    with make() as c, c.websocket_connect("/stream") as ws:
        assert c.post("/api/driver/start", json={"config": str(cfg), "frames": 100}).status_code == 200
        lines, batches, end, state = [], 0, time.time() + 15, None
        while time.time() < end and state not in ("exited", "failed"):
            m = ws.receive_json()
            if m["type"] == "driver_log_batch":
                batches += 1
                lines += m["lines"]
            elif m["type"] == "driver_state":
                state = m["state"]
        assert state == "exited"
        full = c.get("/api/driver/status").json()["log"]
        assert lines[-len(full):] == full and lines[0].startswith("Using config")
        seqs = [int(l.split("seq=")[1].split()[0]) for l in lines if l.startswith("[debug]")]
        assert seqs == sorted(seqs) and len(seqs) >= 150
        assert batches < len(lines) / 3   # batched, not one message per line
        assert lines[-1] == "Stopped."
