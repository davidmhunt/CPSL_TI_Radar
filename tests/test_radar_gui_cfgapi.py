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


def test_firmware_list_per_board_and_generate_with_firmware(client):
    allfw = client.get("/api/cfg/firmware").json()["firmware"]
    assert {f["id"] for f in allfw} >= {"demo_stock", "demo_lvds", "dca1000_raw", "cascade_ddm", "iwr1843_sar_lvds"}
    f1843 = client.get("/api/cfg/firmware", params={"board": "IWR1843"}).json()["firmware"]
    assert [f["id"] for f in f1843][0] == "demo_stock" and {f["id"] for f in f1843} == {"demo_stock", "demo_lvds", "dca1000_raw"}
    assert all("outputs" in f and f["template"] for f in f1843)
    assert {f["id"] for f in client.get("/api/cfg/firmware", params={"board": "AWR2243_CASCADE"}).json()["firmware"]} \
        == {"cascade_ddm"}
    assert client.get("/api/cfg/firmware", params={"board": "NOPE"}).status_code == 422
    g = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": T, "firmware": "demo_lvds"}).json()
    assert g["ok"] and g["targets"]["firmware"] == "demo_lvds"
    bad = client.post("/api/cfg/generate", json={"board": "IWR1443", "targets": T, "firmware": "demo_lvds"}).json()
    assert not bad["ok"] and bad["issues"][0]["code"] == "firmware_board_mismatch"


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


# ---- gui-10 Step 2: firmware selector in the UI / save ----
def test_ui_has_firmware_selector_and_no_output_mode():
    js = (REPO / "radar_gui" / "web" / "js" / "cfg.js").read_text()
    html = (REPO / "radar_gui" / "web" / "index.html").read_text()
    assert 'id="cFw"' in html and 'id="cOutputs"' in html and 'id="cMode"' not in html
    assert "output_mode" not in js and "cMode" not in js and "/api/cfg/firmware?board=" in js


def test_firmware_list_per_board_default_first_and_sar_not_offered(client):
    for b in ("IWR1443", "IWR1843", "IWR6843"):
        fws = client.get("/api/cfg/firmware", params={"board": b}).json()["firmware"]
        assert fws[0]["id"] == "demo_stock" and fws[0]["default"]
        assert all(f["outputs"] and not f["pending"] for f in fws) and "iwr1843_sar_lvds" not in [f["id"] for f in fws]
    assert "IWR1843_SAR" not in client.get("/api/cfg/boards").json()["boards"]


def test_analyze_cfg_reports_firmware_issues(client):
    text = generate("IWR1843", T).text
    bad = client.post("/api/cfg/analyze", json={"board": "IWR1443", "cfg_text": text, "firmware": "cascade_ddm"}).json()
    assert not bad["ok"] and bad["issues"][0]["code"] == "firmware_board_mismatch"
    pend = client.post("/api/cfg/analyze", json={"board": "IWR1843_SAR", "cfg_text": text, "firmware": "iwr1843_sar_lvds"})
    assert pend.status_code == 422                                         # not a GUI board
    ok = client.post("/api/cfg/analyze", json={"board": "IWR1843", "cfg_text": text, "firmware": "demo_stock"}).json()
    assert not any(i["code"].startswith("firmware_") for i in ok["issues"])


def test_save_uses_firmware_system_enables(client):
    def saved(fw, **kw):
        body = _save_body(client, f"fw_{fw}_{len(kw)}", **kw)
        body.pop("serial_enabled", None); body.pop("dca1000_enabled", None)
        body.update(kw, firmware=fw)
        r = client.post("/api/cfg/save", json=body)
        assert r.status_code == 200, r.text
        return json.loads(Path(r.json()["json_path"]).read_text())
    s = saved("demo_stock")
    assert s["serial_stream"]["enabled"] and not s["dca1000"]["enabled"]
    s = saved("dca1000_raw")
    assert not s["serial_stream"]["enabled"] and s["dca1000"]["enabled"]
    s = saved("demo_lvds")
    assert s["serial_stream"]["enabled"] and s["dca1000"]["enabled"]
    # explicit request values still win (the UI checkboxes)
    s = saved("demo_stock", dca1000_enabled=True)
    assert s["dca1000"]["enabled"]


def test_save_refuses_firmware_mismatch_unless_forced(client):
    r = client.post("/api/cfg/save", json=_save_body(client, "mm", board="IWR1443", firmware="cascade_ddm"))
    assert r.status_code == 422
