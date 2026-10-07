"""gui-04 Step 2b: list_configs returns each file's `firmware`, and POST /api/driver/configs/firmware adds the mandatory key to a
config/user system JSON (never overwrites, keeps a .bak, byte-identical to the migration tool). Temp dirs only."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.sources import MockSource

REPO = Path(__file__).resolve().parents[1]
FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")
DOC = {"schema_version": 2, "board": "IWR1843", "radar_cfg": "rig.cfg", "cli": {"port": "/dev/ttyACM0"},
       "serial_stream": {"enabled": True, "port": "/dev/ttyACM1"}, "dca1000": {"enabled": False}}


def dumps(d):
    return json.dumps(d, indent=4) + "\n"


@pytest.fixture
def env(tmp_path):
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir(); system.mkdir()
    for d in (user, system):
        (d / "rig.cfg").write_text("% cfg\n")
    (user / "old.json").write_text(dumps(DOC))
    (user / "has.json").write_text(dumps({**DOC, "firmware": "demo"}))
    (user / "sar.json").write_text(dumps({**DOC, "board": "IWR1843_SAR"}))
    (user / "ghost.json.bak").write_text("x")
    (user / "bak.json").write_text(dumps(DOC)); (user / "bak.json.bak").write_text("keep me")
    (system / "ship.json").write_text(dumps(DOC))
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE, run_root=tmp_path / "runs"))
    with c:
        yield c, user, system


def path_of(c, name):
    return next(x["path"] for x in c.get("/api/driver/configs").json()["configs"] if x["name"] == name)


def add(c, name, fw):
    return c.post("/api/driver/configs/firmware", json={"config": path_of(c, name), "firmware": fw})


def test_listing_has_firmware_or_null_with_hint(env):
    c, *_ = env
    cfgs = {x["name"]: x for x in c.get("/api/driver/configs").json()["configs"]}
    assert cfgs["has"]["firmware"] == "demo" and cfgs["has"]["firmware_hint"] is None
    assert cfgs["old"]["firmware"] is None and cfgs["old"]["firmware_hint"] == "demo"
    assert cfgs["sar"]["firmware_hint"] == "iwr1843_sar_lvds" and cfgs["ship"]["firmware"] is None


def test_happy_path_bytes_equal_tool_output_and_bak_is_original(env, tmp_path):
    c, user, _ = env
    orig = (user / "old.json").read_bytes()
    r = add(c, "old", "demo")
    assert r.status_code == 200, r.text
    assert r.json()["validate"]["ok"] is True and r.json()["backup"].endswith("old.json.bak")
    assert (user / "old.json.bak").read_bytes() == orig
    ref = tmp_path / "ref.json"; ref.write_bytes(orig)
    subprocess.run([sys.executable, str(REPO / "tools/migrate_config_v1_to_v2.py"), "--add-firmware", "--in-place", "-q", str(ref)], check=True)
    assert (user / "old.json").read_bytes() == ref.read_bytes()
    assert list(json.loads((user / "old.json").read_text()))[:3] == ["schema_version", "board", "firmware"]
    assert not list(user.glob("*.tmp"))
    assert next(x for x in c.get("/api/driver/configs").json()["configs"] if x["name"] == "old")["firmware"] == "demo"


def test_already_has_key_409(env):
    c, user, _ = env
    before = (user / "has.json").read_bytes()
    assert add(c, "has", "demo").status_code == 409
    assert (user / "has.json").read_bytes() == before and not (user / "has.json.bak").exists()


def test_bak_exists_409_and_untouched(env):
    c, user, _ = env
    before = (user / "bak.json").read_bytes()
    assert add(c, "bak", "demo").status_code == 409
    assert (user / "bak.json").read_bytes() == before and (user / "bak.json.bak").read_text() == "keep me"


def test_shipped_file_and_unlisted_path_422(env, tmp_path):
    c, user, system = env
    before = (system / "ship.json").read_bytes()
    assert add(c, "ship", "demo").status_code == 422
    assert (system / "ship.json").read_bytes() == before and not (system / "ship.json.bak").exists()
    (tmp_path / "evil.json").write_text(dumps(DOC))
    r = c.post("/api/driver/configs/firmware", json={"config": str(tmp_path / "evil.json"), "firmware": "demo"})
    assert r.status_code == 422


def test_unknown_or_unlisted_firmware_422(env):
    c, user, _ = env
    r = add(c, "old", "nope")
    assert r.status_code == 422 and "demo" in r.text and "iwr1843_sar_lvds" in r.text
    assert add(c, "old", "cascade_ddm").status_code == 422
    assert "firmware" not in json.loads((user / "old.json").read_text()) and not (user / "old.json.bak").exists()


def test_sar_alias_422_and_sar_board_ok(env):
    c, user, _ = env
    r = add(c, "old", "iwr1843_sar_lvds")      # board IWR1843 lists it, but it runs as board IWR1843_SAR
    assert r.status_code == 422 and 'set "board": "IWR1843_SAR"' in r.json()['detail']
    assert "firmware" not in json.loads((user / "old.json").read_text())
    assert add(c, "sar", "demo").status_code == 422        # IWR1843_SAR lists only iwr1843_sar_lvds
    assert add(c, "sar", "iwr1843_sar_lvds").status_code == 200
