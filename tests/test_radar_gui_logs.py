"""gui-37 Step 2b: Logs tab backend. Every test uses a temp run root (create_app(run_root=...)): the real runs/gui/ is never listed or deleted."""
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import ports
from radar_gui.app import create_app
from radar_gui.sources import MockSource

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")


@pytest.fixture
def env(tmp_path, monkeypatch):
    ports.radar_lock.release()
    monkeypatch.setenv("FAKE_DRIVER_RATE", "50")
    monkeypatch.setattr("radar_gui.ports.check_ports", lambda p: None)
    monkeypatch.setattr("radar_gui.driver.check_ports", lambda p: None)
    runs, user = tmp_path / "runs", tmp_path / "user"
    runs.mkdir(); user.mkdir()
    (user / "keep.json").write_text("{}")
    for n, body in (("20260101T000000Z_old_a", "line1\nline2\n<script>alert(1)</script>\n"), ("20260102T000000Z_new_b", "x\n" * 800)):
        d = runs / n
        d.mkdir()
        (d / "driver.log").write_text(body)
        (d / "session.json").write_text(json.dumps({"board": "/x/boards/IWR1843.json", "firmware": "demo", "output": {"save_adc_frames": True}}))
        (d / "radar.cfg").write_text("% c\n")
    (runs / "20260102T000000Z_new_b" / "serial_data.bin").write_bytes(b"1234")
    (runs / "dumps").mkdir()
    (runs / "dumps" / "d.bin").write_bytes(b"dump")
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=tmp_path / "sys", driver_bin=FAKE, run_root=runs,
                              min_stop_grace=0.5))
    with c:
        yield c, runs, user, tmp_path
    ports.radar_lock.release()


def test_listing_newest_first_with_details(env):
    c, runs, *_ = env
    j = c.get("/api/logs").json()
    assert [s["name"] for s in j["sessions"]] == ["20260102T000000Z_new_b", "20260101T000000Z_old_a"]   # dumps/ is not a session
    new = j["sessions"][0]
    assert new["board"] == "IWR1843" and new["firmware"] == "demo" and new["replayable"] and new["saving"]["save_adc_frames"]
    assert new["started"].startswith("2026-01-02T00:00:00") and {f["name"] for f in new["files"]} >= {"driver.log", "session.json", "serial_data.bin"}
    assert new["size"] == sum(f["size"] for f in new["files"]) and j["total_size"] == sum(s["size"] for s in j["sessions"])
    assert not j["sessions"][1]["replayable"] and j["root"] == str(runs.resolve())


def test_view_log_tail_is_plain_text(env):
    c, *_ = env
    r = c.get("/api/logs/20260101T000000Z_old_a/file").json()
    assert "<script>alert(1)</script>" in r["text"] and not r["truncated"]            # returned verbatim as JSON text (the page uses textContent)
    r = c.get("/api/logs/20260102T000000Z_new_b/file", params={"tail": 10}).json()
    assert r["text"].count("\n") <= 10 and r["truncated"]
    assert c.get("/api/logs/20260101T000000Z_old_a/file", params={"file": "session.json"}).json()["text"].lstrip().startswith("{")
    assert c.get("/api/logs/20260101T000000Z_old_a/file", params={"file": "serial_data.bin"}).status_code == 422
    assert c.get("/api/logs/20260101T000000Z_old_a/file", params={"file": "../../x"}).status_code == 422
    assert c.get("/api/logs/20260109T000000Z_none/file").status_code == 404


@pytest.mark.parametrize("name", ["..", "../user", "20260101T000000Z_old_a/../..", "%2e%2e", "dumps", "20260101T000000Z_..", "/etc", "a/b", ""])
def test_path_escape_names_are_422_and_nothing_is_deleted(env, name):
    c, runs, user, _ = env
    r = c.post("/api/logs/delete", json={"names": [name]})
    assert r.status_code in (422, 404), (name, r.text)
    assert (user / "keep.json").exists() and (runs / "dumps" / "d.bin").exists() and (runs / "20260101T000000Z_old_a").exists()
    if name not in ("", "a/b", "/etc"):
        assert c.get(f"/api/logs/{name}/file").status_code in (404, 422)


def test_one_bad_name_deletes_nothing(env):
    c, runs, *_ = env
    r = c.post("/api/logs/delete", json={"names": ["20260101T000000Z_old_a", "../user"]})
    assert r.status_code == 422 and (runs / "20260101T000000Z_old_a").is_dir()


def test_delete_happy_path_only_named_folders(env):
    c, runs, user, _ = env
    r = c.post("/api/logs/delete", json={"names": ["20260101T000000Z_old_a"]})
    assert r.status_code == 200 and r.json()["deleted"] == ["20260101T000000Z_old_a"] and r.json()["freed"] > 0
    assert not (runs / "20260101T000000Z_old_a").exists() and (runs / "20260102T000000Z_new_b").is_dir()
    assert (runs / "dumps" / "d.bin").exists() and (user / "keep.json").exists()
    assert [s["name"] for s in c.get("/api/logs").json()["sessions"]] == ["20260102T000000Z_new_b"]


def test_symlink_escape_is_rejected_and_target_untouched(env):
    c, runs, user, tmp = env
    victim = tmp / "victim"
    victim.mkdir()
    (victim / "precious.txt").write_text("keep")
    (runs / "20260103T000000Z_link").symlink_to(victim, target_is_directory=True)
    assert "20260103T000000Z_link" not in [s["name"] for s in c.get("/api/logs").json()["sessions"]]
    assert c.post("/api/logs/delete", json={"names": ["20260103T000000Z_link"]}).status_code == 422
    assert c.get("/api/logs/20260103T000000Z_link/file").status_code == 422
    assert (victim / "precious.txt").read_text() == "keep"
    # a symlink INSIDE a session folder is removed as a link, its target survives
    d = runs / "20260101T000000Z_old_a"
    (d / "sneaky").symlink_to(victim, target_is_directory=True)
    assert c.post("/api/logs/delete", json={"names": [d.name]}).status_code == 200
    assert (victim / "precious.txt").read_text() == "keep"


def test_running_session_cannot_be_deleted(env, tmp_path):
    c, runs, user, _ = env
    cfg = tmp_path / "rig.json"
    (tmp_path / "rig.cfg").write_text("% c\n")
    cfg.write_text(json.dumps({"schema_version": 2, "board": "IWR1843", "radar_cfg": "rig.cfg", "cli": {"port": "/dev/ttyACM0"}, "serial_stream": {"enabled": True, "port": "/dev/ttyACM1"}}))
    # the config must be listed: put it in the user dir
    (user / "rig.json").write_text(cfg.read_text()); (user / "rig.cfg").write_text("% c\n")
    r = c.post("/api/driver/start", json={"config": str(user / "rig.json")})
    assert r.status_code == 200, r.text
    run = Path(r.json()["run_dir"]).name
    j = c.get("/api/logs").json()
    assert j["running"] == run and next(s for s in j["sessions"] if s["name"] == run)["running"]
    d = c.post("/api/logs/delete", json={"names": ["20260101T000000Z_old_a", run]})
    assert d.status_code == 409 and (runs / run).is_dir() and (runs / "20260101T000000Z_old_a").is_dir()   # nothing deleted at all
    end = time.time() + 20
    while time.time() < end and not any("Using config" in ln for ln in c.get("/api/driver/status").json()["log"]):
        time.sleep(0.05)
    c.post("/api/driver/stop")
    end = time.time() + 15
    while time.time() < end and c.get("/api/driver/status").json()["state"] not in ("exited", "failed"):
        time.sleep(0.05)
    assert c.post("/api/logs/delete", json={"names": [run]}).status_code == 200
