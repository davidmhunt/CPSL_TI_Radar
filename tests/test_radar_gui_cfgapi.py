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
    assert j["limits"]["IWR1843"]["max_slope_mhz_us"]["confidence"] in ("repo", "high", "medium", "low", "unverified")
    html = client.get("/").text
    assert 'id="cfgMain"' in html and client.get("/js/cfg.js").status_code == 200


def test_firmware_list_per_board_and_generate_with_firmware(client):
    allfw = client.get("/api/cfg/firmware").json()["firmware"]
    assert {f["id"] for f in allfw} >= {"demo", "dca1000_raw", "cascade_ddm", "iwr1843_sar_lvds"}
    assert not {"demo_stock", "demo_lvds"} & {f["id"] for f in allfw}
    f1843 = client.get("/api/cfg/firmware", params={"board": "IWR1843"}).json()["firmware"]
    assert [f["id"] for f in f1843] == ["demo", "dca1000_raw"]
    assert all("outputs" in f and f["template"] and f["mimo"]["scheme"] == "tdm" for f in f1843)
    f1443 = client.get("/api/cfg/firmware", params={"board": "IWR1443"}).json()["firmware"]
    assert f1443[0]["outputs"] == {"tlv": True, "lvds": False} and f1443[0]["mimo"]["bpm"] is False
    assert not any(f["outputs"]["lvds"] and f["outputs"]["tlv"] for f in f1443)
    f6843 = client.get("/api/cfg/firmware", params={"board": "IWR6843"}).json()["firmware"]
    assert [f["id"] for f in f6843] == ["demo", "dca1000_raw"] and f6843[0]["outputs"] == {"tlv": True, "lvds": True}
    assert client.get("/api/cfg/firmware", params={"board": "AWR2243_CASCADE"}).json()["firmware"][0]["mimo"]["scheme"] == "ddma"
    assert {f["id"] for f in client.get("/api/cfg/firmware", params={"board": "AWR2243_CASCADE"}).json()["firmware"]} \
        == {"cascade_ddm"}
    assert client.get("/api/cfg/firmware", params={"board": "NOPE"}).status_code == 422
    g = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": {**T, "lvds": True}, "firmware": "demo"}).json()
    assert g["ok"] and g["targets"]["firmware"] == "demo" and "lvdsStreamCfg -1 0 1 0" in g["text"]
    bad = client.post("/api/cfg/generate", json={"board": "IWR1443", "targets": T, "firmware": "cascade_ddm"}).json()
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
        assert fws[0]["id"] == "demo" and fws[0]["default"]
        assert all(f["outputs"] and not f["pending"] for f in fws) and "iwr1843_sar_lvds" not in [f["id"] for f in fws]
    assert "IWR1843_SAR" not in client.get("/api/cfg/boards").json()["boards"]


def test_analyze_cfg_reports_firmware_issues(client):
    text = generate("IWR1843", T).text
    bad = client.post("/api/cfg/analyze", json={"board": "IWR1443", "cfg_text": text, "firmware": "cascade_ddm"}).json()
    assert not bad["ok"] and bad["issues"][0]["code"] == "firmware_board_mismatch"
    pend = client.post("/api/cfg/analyze", json={"board": "IWR1843_SAR", "cfg_text": text, "firmware": "iwr1843_sar_lvds"})
    assert pend.status_code == 422                                         # not a GUI board
    ok = client.post("/api/cfg/analyze", json={"board": "IWR1843", "cfg_text": text, "firmware": "demo"}).json()
    assert not any(i["code"].startswith("firmware_") for i in ok["issues"])


def test_save_uses_firmware_system_enables(client):
    def saved(fw, **kw):
        body = _save_body(client, f"fw_{fw}_{len(kw)}_{len(saved.n)}", **kw)
        saved.n.append(1)
        body.pop("serial_enabled", None); body.pop("dca1000_enabled", None)
        body.update(kw, firmware=fw)
        r = client.post("/api/cfg/save", json=body)
        assert r.status_code == 200, r.text
        return json.loads(Path(r.json()["json_path"]).read_text())
    saved.n = []
    s = saved("demo")
    assert s["serial_stream"]["enabled"] and not s["dca1000"]["enabled"]
    s = saved("dca1000_raw")
    assert not s["serial_stream"]["enabled"] and s["dca1000"]["enabled"]
    lvds_text = generate("IWR1843", {**T, "lvds": True}).text     # cfg LVDS on; system settings stay separate (gui-22)
    s = saved("demo", cfg_text=lvds_text)
    assert s["serial_stream"]["enabled"] and not s["dca1000"]["enabled"]
    # explicit request values still win (the UI checkboxes)
    s = saved("demo", dca1000_enabled=True)
    assert s["dca1000"]["enabled"]


def test_save_refuses_firmware_mismatch_unless_forced(client):
    r = client.post("/api/cfg/save", json=_save_body(client, "mm", board="IWR1443", firmware="cascade_ddm"))
    assert r.status_code == 422


def test_direct_mode_ui_served_and_flow(client):
    """gui-11 step 2: the page has the mode toggle, cfg.js serves, and the seed/edit flow the UI drives works."""
    html = client.get("/").text
    assert 'id="cInMode"' in html and "Chirp parameters" in html and 'id="pFields"' in html
    js = client.get("/js/cfg.js")
    assert js.status_code == 200 and "/api/cfg/params" in js.text
    base = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": T}).json()["text"]
    seed = client.post("/api/cfg/params", json={"board": "IWR1843", "base_cfg_text": base, "params": {}}).json()
    assert seed["params"]["profiles"][0]["slope_mhz_us"] > 0 and "bandwidth_mhz" in seed["params"]["derived"]
    slope = seed["params"]["profiles"][0]["slope_mhz_us"]
    r = client.post("/api/cfg/params", json={"board": "IWR1843", "base_cfg_text": base,
                                             "params": {"profiles": [{"slope_mhz_us": slope / 2}]}}).json()
    assert r["params"]["derived"]["bandwidth_mhz"] < seed["params"]["derived"]["bandwidth_mhz"] * 0.6
    assert r["metrics"]["max_range_m"] > 0 and r["text"] != base


def test_mimo_panel_payload_fields(client):
    """gui-16: the Configure-tab MIMO panel reads these metrics fields (cfg.js renderMimo); no browser harness."""
    need = ("scheme", "bpm_enabled", "chirp_sequence", "n_bands", "loop_period_us", "pattern_period_us", "doppler_bins",
            "doppler_step_ms", "vmax_full_ms", "vmax_per_tx_ms", "lambda_mm", "derivations", "subframes", "n_tx",
            "n_virtual", "chirps_per_loop", "chirp_us", "idle_us", "ramp_us", "velocity_res_ms")
    for board, fw, scheme in (("IWR1843", "demo", "tdm"), ("AWR2243_CASCADE", "cascade_ddm", "ddma")):
        g = client.post("/api/cfg/generate", json={"board": board, "targets": T, "firmware": fw}).json()
        m = g["metrics"]
        assert all(k in m for k in need), [k for k in need if k not in m]
        assert m["scheme"] == scheme and m["chirp_sequence"] and "tx_mask" in m["chirp_sequence"][0]
        for k in ("vmax_full_ms", "vmax_per_tx_ms", "velocity_res_ms", "loop_period_us", "doppler_bins", "doppler_step_ms",
                  "n_tx", "n_virtual"):
            assert set(m["derivations"][k]) >= {"formula", "scheme", "confidence"} and m["derivations"][k]["scheme"] == scheme
        # analyze (cfg text) carries the same fields
        a = client.post("/api/cfg/analyze", json={"board": board, "cfg_text": g["text"], "firmware": fw}).json()
        assert a["metrics"]["scheme"] == scheme and a["metrics"]["derivations"]
    assert m["n_bands"] == 8 and m["vmax_per_tx_ms"] < m["vmax_full_ms"]
    html = client.get("/").text
    assert all(i in html for i in ('id="mBadge"', 'id="mDiagram"', 'id="mDerived"', 'id="mChirpTable"'))


def test_save_warns_on_cfg_lvds_vs_dca1000_mismatch(client):
    on = generate("IWR1843", {**T, "lvds": True}).text
    off = generate("IWR1843", T).text

    def warns(text, dca, name, board="IWR1843", fw="demo"):
        body = _save_body(client, name, cfg_text=text, firmware=fw, board=board, dca1000_enabled=dca)
        r = client.post("/api/cfg/save", json=body)
        assert r.status_code == 200, r.text
        return r.json()["warnings"]
    w = warns(on, False, "w1")
    assert len(w) == 1 and "LVDS streaming on" in w[0]
    assert len(warns(off, True, "w3")) == 1
    assert warns(on, True, "w4") == [] and warns(off, False, "w5") == []
    assert warns(off, True, "w6", fw="dca1000_raw") == []     # raw firmware: LVDS is not a cfg choice


def test_chirp_table_payloads(client):
    """gui-16 step 2: the payloads the chirp table / presets post (cfg.js tableParams) and the fields it redraws from."""
    js = client.get("/js/cfg.js").text
    assert 'id="mChirpTable"' in client.get("/").text and "chirp_tx_masks" in js and "bpm" in js

    def post(board, fw, base, params):
        return client.post("/api/cfg/params", json={"board": board, "firmware": fw, "base_cfg_text": base, "params": params}).json()

    for board, bpm_ok in (("IWR1443", False), ("IWR1843", True)):
        fw = client.get("/api/cfg/firmware", params={"board": board}).json()["firmware"][0]
        assert fw["mimo"]["bpm"] is bpm_ok and fw["mimo"]["max_chirps_per_loop"] != 0   # table shows the BPM preset only when true
    base = client.post("/api/cfg/generate", json={"board": "IWR1843", "targets": T, "firmware": "demo"}).json()["text"]
    seed = post("IWR1843", "demo", base, {})
    assert seed["params"]["bpm"] is False and all(isinstance(x, int) for x in seed["params"]["chirp_tx_masks"])
    for masks in ([1], [1, 4], [1, 4, 2], [1, 4, 2, 2]):            # SIMO / 2-TX / 3-TX presets / an added row
        r = post("IWR1843", "demo", base, {"chirp_tx_masks": masks})
        assert r["metrics"] and [c["tx_mask"] for c in r["metrics"]["chirp_sequence"]] == masks
        assert r["params"]["chirp_tx_masks"] == masks and r["metrics"]["scheme"] == "tdm" and not r["metrics"]["bpm_enabled"]
    r = post("IWR1843", "demo", base, {"bpm": True})                  # BPM preset: only the flag is sent
    assert r["metrics"]["bpm_enabled"] and r["params"]["bpm"] is True and r["params"]["chirp_tx_masks"] == [5, 5]
    assert not any(i["level"] == "error" for i in r["issues"] if i["code"] == "params")
    back = post("IWR1843", "demo", r["text"], {"bpm": False, "chirp_tx_masks": [1, 4]})
    assert back["params"]["bpm"] is False and back["params"]["chirp_tx_masks"] == [1, 4]
    b14 = client.post("/api/cfg/generate", json={"board": "IWR1443", "targets": T}).json()["text"]
    rej = post("IWR1443", "demo", b14, {"bpm": True})
    assert any(i["code"] == "params" and i["level"] == "error" for i in rej["issues"])
    cas = client.post("/api/cfg/generate", json={"board": "AWR2243_CASCADE", "targets": T, "firmware": "cascade_ddm"}).json()
    r = post("AWR2243_CASCADE", "cascade_ddm", cas["text"], {"chirp_tx_masks": [1, 2, 4]})
    assert "cascade_chirp_mask_ignored" in [i["code"] for i in r["issues"]] and r["metrics"]["scheme"] == "ddma"
