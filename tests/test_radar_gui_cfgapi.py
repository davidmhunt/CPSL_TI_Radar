"""Configure-tab API (gui-03): analyze / generate / save / list, and the saved system JSON against the driver."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.cfg import generate, parse_cfg
from radar_gui.sources import MockSource

REPO = Path(__file__).resolve().parent.parent
DRIVER = REPO / "CPSL_TI_Radar_cpp" / "build" / "CPSL_TI_Radar_CPP"
T = {"max_range_m": 10, "max_velocity_ms": 3}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(MockSource(rate_hz=200), user_cfg_dir=tmp_path / "user")) as c:
        c.udir = tmp_path / "user"
        yield c


def test_boards_and_page(client):
    j = client.get("/api/cfg/boards").json()
    assert set(j["boards"]) == {"IWR1443", "IWR1843", "IWR6843", "AWR2243_CASCADE"}
    assert j["limits"]["IWR1843"]["max_slope_mhz_us"]["confidence"] in ("repo", "recalled", "unverified")
    html = client.get("/").text
    assert 'id="cfgMain"' in html and client.get("/js/cfg.js").status_code == 200


def test_generate_then_analyze_round_trip(client):
    g = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": T}).json()
    assert g["ok"] and g["text"] and g["source"] == "targets"
    a = client.post("/api/cfg/analyze", json={"board": "IWR1843", "cfg_text": g["text"]}).json()
    assert a["source"] == "cfg" and a["ok"]
    assert a["metrics"] == g["metrics"]
    assert a["issues"] == g["issues"]
    assert g["metrics"]["max_range_m"] == pytest.approx(10, rel=0.02)
    # analyze with targets is the same as generate
    assert client.post("/api/cfg/analyze", json={"board": "IWR1843", "targets": T}).json() == g


def test_issues_carry_level_and_confidence(client):
    cfg = generate("IWR1843", T).text
    bad = "\n".join(("profileCfg 0 77 7 7 73 0 0 400 1 128 2000 0 0 30" if l.startswith("profileCfg") else l)
                    for l in cfg.splitlines())
    a = client.post("/api/cfg/analyze", json={"board": "IWR1843", "cfg_text": bad}).json()
    assert not a["ok"]
    errs = [i for i in a["issues"] if i["level"] == "error"]
    assert errs and all(set(i) >= {"level", "code", "message", "confidence"} for i in a["issues"])


def test_bad_inputs(client):
    assert client.post("/api/cfg/analyze", json={"board": "NOPE", "targets": T}).status_code == 422
    assert client.post("/api/cfg/analyze", json={"board": "IWR1843"}).status_code == 422
    r = client.post("/api/cfg/analyze", json={"board": "IWR1843", "cfg_text": "garbage"}).json()
    assert not r["ok"] and r["issues"]
    g = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": {"max_range_m": -1}}).json()
    assert not g["ok"] and g["issues"]


def _save_body(client, name="t1", **kw):
    g = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": T}).json()
    return {"board": "IWR1843", "name": name, "cfg_text": g["text"], **kw}


def test_save_writes_parseable_cfg_and_schema_v2_json(client):
    r = client.post("/api/cfg/save", json=_save_body(client, dca1000_enabled=True, cmd_port=4092, data_udp_port=4094))
    assert r.status_code == 200, r.text
    j = r.json()
    cfg = parse_cfg(Path(j["cfg_path"]).read_text())
    assert cfg.has("profileCfg")
    s = json.loads(Path(j["json_path"]).read_text())
    assert s["schema_version"] == 2 and s["board"] == "IWR1843" and s["radar_cfg"] == "t1.cfg"
    assert s["dca1000"]["enabled"] and s["dca1000"]["cmd_port"] == 4092 and s["dca1000"]["data_port"] == 4094
    assert s["cli"]["port"] == "/dev/ttyACM0" and s["serial_stream"]["enabled"]
    # the saved cfg shows up in the listing
    ids = [c["id"] for c in client.get("/api/cfgs").json()["cfgs"] if c["group"] == "user"]
    assert "user:t1.cfg" in ids


def test_save_never_overwrites(client):
    assert client.post("/api/cfg/save", json=_save_body(client)).status_code == 200
    before = (client.udir / "t1.cfg").read_text()
    assert client.post("/api/cfg/save", json=_save_body(client)).status_code == 409
    assert (client.udir / "t1.cfg").read_text() == before
    # a stray .json alone also blocks the name, and leaves no half-written cfg behind
    (client.udir / "t2.json").write_text("{}")
    assert client.post("/api/cfg/save", json=_save_body(client, "t2")).status_code == 409
    assert not (client.udir / "t2.cfg").exists() and (client.udir / "t2.json").read_text() == "{}"


@pytest.mark.parametrize("name", ["../evil", "a/b", "", ".hidden", "x y", "a.cfg/.."])
def test_save_rejects_bad_names(client, name):
    assert client.post("/api/cfg/save", json=_save_body(client, name)).status_code == 422
    assert not client.udir.exists() or not list(client.udir.iterdir())


def test_save_refuses_errors_unless_forced(client):
    body = _save_body(client, "bad")
    body["cfg_text"] = "garbage"
    assert client.post("/api/cfg/save", json=body).status_code == 422
    assert client.post("/api/cfg/save", json={**body, "force": True}).status_code == 200


def test_list_and_load_shipped_cfg_cannot_escape(client):
    lst = client.get("/api/cfgs").json()["cfgs"]
    shipped = [c for c in lst if c["group"] == "shipped"]
    assert len(shipped) > 50
    c = next(c for c in shipped if c["board"] == "AWR2243_CASCADE")
    f = client.get("/api/cfg/file", params={"id": c["id"]}).json()
    assert "frameCfg" in f["text"]
    a = client.post("/api/cfg/analyze", json={"board": f["board"], "cfg_text": f["text"]}).json()
    assert a["metrics"] and a["metrics"]["mode"] != "tdm"
    for bad in ("driver:../../../../etc/passwd", "driver:../radar_gui/app.py", "user:../x.cfg", "nope:x.cfg", "driver:"):
        assert client.get("/api/cfg/file", params={"id": bad}).status_code == 404


@pytest.mark.skipif(not DRIVER.exists(), reason="driver not built (CPSL_TI_Radar_cpp/build)")
def test_saved_system_json_passes_driver_validate(client):
    j = client.post("/api/cfg/save", json=_save_body(client, "drv")).json()
    env = dict(os.environ, CPSL_TI_RADAR_BOARDS_DIR=str(REPO / "CPSL_TI_Radar_cpp" / "config" / "boards"))
    p = subprocess.run([str(DRIVER), j["json_path"], "--validate"], capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "OK:" in p.stdout and "board:      IWR1843" in p.stdout
