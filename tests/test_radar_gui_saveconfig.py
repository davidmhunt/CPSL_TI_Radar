"""gui-37 Step 2: the configs listing carries what each file records, "Save to config" (POST /api/driver/config/save) writes the
recording flags back into config/user/ (in place with a .bak, or as a copy; a shipped config is never overwritten), and run-folder
serial captures are replayable. Temp dirs only."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.sources import MockSource

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")
DOC = {"schema_version": 2, "board": "IWR1843", "radar_cfg": "rig.cfg", "cli": {"port": "/dev/ttyACM0"},
       "serial_stream": {"enabled": True, "port": "/dev/ttyACM1"}, "dca1000": {"enabled": True}, "output": {"save_raw_lvds": True}}


@pytest.fixture
def env(tmp_path):
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir(); system.mkdir()
    for d in (user, system):
        (d / "rig.cfg").write_text("% cfg\n")
    (user / "rig.json").write_text(json.dumps(DOC, indent=2))
    (system / "ship.json").write_text(json.dumps({**DOC, "radar_cfg": "rig.cfg"}))
    (system / "nodca.json").write_text(json.dumps({k: v for k, v in DOC.items() if k != "dca1000"}))
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE, run_root=tmp_path / "runs"))
    with c:
        yield c, user, system


def path_of(c, name):
    return next(x["path"] for x in c.get("/api/driver/configs").json()["configs"] if x["name"] == name)


def test_listing_has_own_flags(env):
    c, *_ = env
    cfgs = {x["name"]: x for x in c.get("/api/driver/configs").json()["configs"]}
    assert cfgs["rig"]["saves"] == {"save_adc_frames": False, "save_raw_lvds": True, "save_serial_bytes": False}
    assert cfgs["rig"]["dca"] is True and cfgs["rig"]["serial"] is True and cfgs["nodca"]["dca"] is False


def test_save_in_place_keeps_backup_and_format(env):
    c, user, _ = env
    orig = (user / "rig.json").read_bytes()
    r = c.post("/api/driver/config/save", json={"config": path_of(c, "rig"), "overrides": {"save_adc_frames": True, "save_raw_lvds": False}})
    assert r.status_code == 200, r.text
    assert r.json()["validate"]["ok"] is True and r.json()["backup"].endswith("rig.json.bak")
    assert (user / "rig.json.bak").read_bytes() == orig
    text = (user / "rig.json").read_text()
    assert text.endswith("}\n") and '\n    "schema_version": 2' in text            # indent 4, trailing newline
    doc = json.loads(text)
    assert list(doc)[:3] == ["schema_version", "board", "radar_cfg"]                 # key order kept
    assert doc["output"] == {"save_raw_lvds": False, "save_adc_frames": True}
    assert not list(user.glob("*.tmp"))


def test_shipped_config_is_never_overwritten_only_copied(env):
    c, user, system = env
    before = (system / "ship.json").read_bytes()
    p = path_of(c, "ship")
    assert c.post("/api/driver/config/save", json={"config": p, "overrides": {"save_adc_frames": True}}).status_code == 422
    assert (system / "ship.json").read_bytes() == before
    r = c.post("/api/driver/config/save", json={"config": p, "overrides": {"save_adc_frames": True}, "mode": "copy", "name": "ship_rec"})
    assert r.status_code == 200, r.text
    doc = json.loads((user / "ship_rec.json").read_text())
    assert doc["output"]["save_adc_frames"] is True and Path(doc["radar_cfg"]).is_absolute()   # relative paths made absolute
    assert (system / "ship.json").read_bytes() == before
    assert c.post("/api/driver/config/save", json={"config": p, "overrides": {}, "mode": "copy", "name": "ship_rec"}).status_code == 409


def test_save_path_escapes_and_bad_input_are_422(env, tmp_path):
    c, user, _ = env
    p = path_of(c, "rig")
    evil = tmp_path / "evil.json"
    evil.write_text(json.dumps(DOC))
    assert c.post("/api/driver/config/save", json={"config": str(evil), "overrides": {}}).status_code == 422
    assert c.post("/api/driver/config/save", json={"config": "../../etc/passwd", "overrides": {}}).status_code == 422
    for name in ("../x", "a/b", "", ".hidden", "x" * 80):
        r = c.post("/api/driver/config/save", json={"config": p, "overrides": {}, "mode": "copy", "name": name})
        assert r.status_code == 422, name
    assert not (tmp_path / "x.json").exists() and not list(tmp_path.glob("*.json.bak"))
    # a flag the config cannot honour
    assert c.post("/api/driver/config/save", json={"config": path_of(c, "nodca"), "overrides": {"save_adc_frames": True}, "mode": "copy", "name": "n"}).status_code == 422


def test_symlink_in_user_dir_cannot_escape(env, tmp_path):
    c, user, _ = env
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(DOC))
    (user / "link.json").symlink_to(outside)
    before = outside.read_bytes()
    r = c.post("/api/driver/config/save", json={"config": str((user / "link.json")), "overrides": {"save_adc_frames": True}})
    assert r.status_code == 422 and outside.read_bytes() == before


def test_run_folder_serial_capture_is_replayable(env, tmp_path):
    c, *_ = env
    run = tmp_path / "runs" / "20260101T000000Z_x"
    run.mkdir(parents=True)
    (run / "serial_data.bin").write_bytes((Path(__file__).parent / "fixtures/replay/awr2243_cascade_20frames.bin").read_bytes())
    (run / "session.json").write_text(json.dumps({"board": "/x/config/boards/AWR2243_CASCADE.json"}))
    files = c.get("/api/source/files").json()["files"]
    f = next(x for x in files if x["group"] == "runs")
    assert f["name"].endswith("/serial_data.bin") and f["dialect"] == "mcuplus_cascade"
    r = c.post("/api/source", json={"kind": "replay", "file": f["path"]})
    assert r.status_code == 200, r.text
    assert r.json()["spec"]["dialect"] == "mcuplus_cascade"
