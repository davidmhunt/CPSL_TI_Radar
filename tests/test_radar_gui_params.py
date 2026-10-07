"""radar_gui.cfg.params + POST /api/cfg/params (gui-11 Step 1). Hardware-free."""
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radar_gui import cfgapi
from radar_gui.cfg import CfgError, apply_params, metrics, params_from_cfg, parse_cfg

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar"
CASES = [  # (path, board): single-chip 2-TX, 6843 3-TX, cascade DDMA
    (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg", "IWR1843"),
    (RADAR / "nav_configs" / "6843_RadVel_ods_10Hz.cfg", "IWR6843"),
    (ROOT / "tools" / "radar_viewer" / "configs" / "cascade_R15m_V5ms_20Hz.cfg", "AWR2243_CASCADE"),
]
IDS = [p.name for p, _ in CASES]


def md(text, board):
    return metrics(parse_cfg(text), board).to_dict()


@pytest.mark.parametrize("path,board", CASES, ids=IDS)
def test_round_trip_is_identity(path, board):
    text = path.read_text()
    params = params_from_cfg(parse_cfg(text), board)
    out = apply_params(text, params)
    assert md(out, board) == md(text, board)
    assert params_from_cfg(parse_cfg(out), board) == params
    # unedited tokens keep their original text: only line-ending normalisation may differ
    assert out.rstrip("\n").splitlines() == text.rstrip("\n").splitlines()


def test_params_schema_single_profile_list():
    p = params_from_cfg(parse_cfg((RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()), "IWR1843")
    assert len(p["profiles"]) == 1
    assert {"start_ghz", "slope_mhz_us", "idle_us", "adc_start_us", "ramp_us", "tx_start_us", "num_samples",
            "sample_rate_ksps", "hpf1", "hpf2", "rx_gain_db"} <= set(p["profiles"][0])
    assert p["chirp_tx_masks"] == [1, 4] and p["tx_mask"] == 5
    assert {"bandwidth_mhz", "ramp_us", "sampling_us", "adc_end_us"} <= set(p["derived"])


def test_slope_edit_changes_exactly_the_slope_dependent_metrics():
    path, board = CASES[0]
    text = path.read_text()
    params = params_from_cfg(parse_cfg(text), board)
    params["profiles"][0]["slope_mhz_us"] = 40.0
    new = md(apply_params(text, params), board)
    old = md(text, board)
    changed = {k for k in old if old[k] != new[k]}
    # slope enters bandwidth, range resolution, max range, centre frequency (-> wavelength -> velocities),
    # and the sweep; nothing about timing, samples, array or frame.
    assert changed == {"slope_mhz_us", "bandwidth_mhz", "sweep_mhz", "center_ghz", "range_res_m", "max_range_m",
                       "max_range_ideal_m", "velocity_res_ms", "max_velocity_ms",
                       "lambda_mm", "doppler_step_ms", "vmax_full_ms", "vmax_per_tx_ms"}
    assert new["bandwidth_mhz"] == pytest.approx(old["bandwidth_mhz"] * 40.0 / 80.0)


def test_loops_and_period_edit_touch_frame_metrics_only():
    path, board = CASES[0]
    text = path.read_text()
    old = md(text, board)
    new = md(apply_params(text, {"n_loops": 50, "frame_period_ms": 200}), board)
    changed = {k for k in old if old[k] != new[k]}
    assert changed == {"n_loops", "n_chirps", "velocity_res_ms", "frame_period_ms", "frame_rate_hz", "active_ms",
                       "duty_cycle", "bytes_per_frame", "avg_data_rate_mbps", "doppler_bins", "doppler_step_ms"}


def test_tx_mask_edit_regenerates_chirps_on_single_chip():
    path, board = CASES[1]
    text = path.read_text()
    out = apply_params(text, {"tx_mask": 3})
    m = metrics(parse_cfg(out), board)
    assert m.chirps_per_loop == 2 and m.n_tx == 2
    assert [c.args[7] for c in parse_cfg(out).all("chirpCfg")] == ["1", "2"]


def test_only_the_four_commands_change():
    path, board = CASES[0]
    text = path.read_text()
    params = params_from_cfg(parse_cfg(text), board)
    params["profiles"][0]["idle_us"] = 100
    params["rx_mask"] = 7
    params["chirp_tx_masks"] = [1, 2, 4]
    out = apply_params(text, params)
    a, b = parse_cfg(text), parse_cfg(out)
    names = lambda c: [x.name for x in c.commands]
    assert names(b).count("chirpCfg") == 3
    other = lambda c: [(x.name, x.args) for x in c.commands
                       if x.name not in ("profileCfg", "chirpCfg", "frameCfg", "channelCfg")]
    assert other(a) == other(b)


@pytest.mark.parametrize("bad", [{"profiles": [{"slope_mhz_us": "fast"}]}, {"n_loops": 2.5}, {"profiles": []},
                                 {"frame_period_ms": None}, {"chirp_tx_masks": []}])
def test_bad_values_raise_cfgerror(bad):
    with pytest.raises(CfgError):
        apply_params((RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text(), bad)


# --- endpoint ---------------------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path):
    app = FastAPI()
    app.include_router(cfgapi.make_router(tmp_path))
    return TestClient(app)


def test_endpoint_applies_params_and_validates(client):
    path, board = CASES[0]
    text = path.read_text()
    params = params_from_cfg(parse_cfg(text), board)
    params["profiles"][0]["slope_mhz_us"] = 40.0
    r = client.post("/api/cfg/params", json={"board": board, "base_cfg_text": text, "params": params}).json()
    assert r["metrics"]["slope_mhz_us"] == 40.0 and r["metrics"]["bandwidth_mhz"] == pytest.approx(
        params["derived"]["bandwidth_mhz"] / 2)
    assert r["report"]["issues"] == r["issues"] and r["params"]["profiles"][0]["slope_mhz_us"] == 40.0
    assert "profileCfg" in r["text"]


def test_endpoint_invalid_edits_are_issues_not_exceptions(client):
    path, board = CASES[0]
    text = path.read_text()
    for bad in ({"profiles": [{"slope_mhz_us": -5}]}, {"profiles": [{"slope_mhz_us": "x"}]},
                {"rx_mask": 0}, {"n_loops": 0}, {"frame_period_ms": 1}):
        r = client.post("/api/cfg/params", json={"board": board, "base_cfg_text": text, "params": bad})
        assert r.status_code == 200, bad
        assert r.json()["ok"] is False and r.json()["issues"], bad
    # garbage base cfg
    r = client.post("/api/cfg/params", json={"board": board, "base_cfg_text": "hello", "params": {}})
    assert r.status_code == 200 and not r.json()["ok"]


def test_endpoint_honours_firmware_and_board(client):
    path, board = CASES[0]
    r = client.post("/api/cfg/params", json={"board": board, "base_cfg_text": path.read_text(),
                                             "firmware": "no_such_fw", "params": {}}).json()
    assert any(i["code"] == "unknown_firmware" for i in r["issues"])
    assert client.post("/api/cfg/params", json={"board": "nope", "base_cfg_text": "x"}).status_code == 422


# ---- lvdsStreamCfg (gui-22) ----
def _lvds_cfgs():
    out = []
    for p in sorted((ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar").rglob("*.cfg")) + \
            sorted((ROOT / "firmware_dev" / "projects").rglob("*.cfg")):
        t = p.read_text(errors="replace")
        if "lvdsStreamCfg" in t:
            try:
                parse_cfg(t).first("profileCfg") and params_from_cfg(parse_cfg(t))
            except (CfgError, AttributeError):    # advanced-subframe / partial cfgs the editor does not take
                continue
            out.append(p)
    return out


@pytest.mark.parametrize("path", _lvds_cfgs(), ids=lambda p: p.name)
def test_lvds_stream_round_trip_exact(path):
    t = path.read_text(errors="replace")
    p = params_from_cfg(parse_cfg(t))
    assert set(p["lvds_stream"]) == {"subframe", "header", "data_fmt", "sw"}
    assert apply_params(t, p) == apply_params(t, {})        # whole-dict round trip changes nothing more than the baseline


def test_apply_lvds_hw_stream_changes_only_that_line():
    t = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()
    assert "lvdsStreamCfg -1 0 1 0" in t
    out = apply_params(t, {"lvds_stream": {"data_fmt": 0}})
    a, b = t.splitlines(), out.splitlines()
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(a) == len(b) and len(diff) == 1 and diff[0][1].split("%")[0].split() == "lvdsStreamCfg -1 0 0 0".split()
    assert params_from_cfg(parse_cfg(out))["lvds_stream"]["data_fmt"] == 0


def test_lvds_stream_missing_line_or_bad_value():
    t = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()
    no = "\n".join(l for l in t.splitlines() if "lvdsStreamCfg" not in l) + "\n"
    assert "lvds_stream" not in params_from_cfg(parse_cfg(no))
    with pytest.raises(CfgError):
        apply_params(no, {"lvds_stream": {"data_fmt": 1}})
    with pytest.raises(CfgError):
        apply_params(t, {"lvds_stream": {"data_fmt": 0.5}})


def test_iwr1443_demo_with_lvds_on_flags_not_in_firmware():
    from radar_gui.cfg import generate, validate
    cfg = parse_cfg(generate("IWR1443", max_range_m=10, max_velocity_ms=5).text + "\nlvdsStreamCfg -1 0 1 0\n")
    assert "lvds_not_in_firmware" in {i.code for i in validate(cfg, "IWR1443", "demo").errors}


# ---- lowPower 0 <adcMode> (gui-26) ----
def _lowpower_cfgs():
    out = []
    for p in sorted((RADAR).rglob("*.cfg")) + sorted((ROOT / "firmware_dev" / "projects").rglob("*.cfg")):
        t = p.read_text(errors="replace")
        if "lowPower" in t:
            try:
                params_from_cfg(parse_cfg(t))
            except (CfgError, AttributeError):
                continue
            out.append(p)
    return out


@pytest.mark.parametrize("path", _lowpower_cfgs(), ids=lambda p: p.name)
def test_low_power_round_trip_exact(path):
    t = path.read_text(errors="replace")
    p = params_from_cfg(parse_cfg(t))
    if "cascade" in path.name:
        assert "low_power" not in p                 # cascade: not offered
        return
    assert p["low_power"] in (0, 1)
    assert apply_params(t, p).rstrip("\n").splitlines() == t.rstrip("\n").splitlines()


def test_low_power_toggle_changes_one_line_and_warning_follows():
    from radar_gui.cfg import validate
    t = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()
    t = t.replace("profileCfg 0 77 293 7 44 0 0 80.0 1 63 2100", "profileCfg 0 77 293 7 44 0 0 60.0 1 63 10000")
    assert params_from_cfg(parse_cfg(t), "IWR1843")["low_power"] == 0
    on = apply_params(t, {"low_power": 1}, board="IWR1843")
    a, b = t.splitlines(), on.splitlines()
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert len(a) == len(b) and len(diff) == 1 and diff[0][1].split("%")[0].split() == "lowPower 0 1".split()
    codes = lambda s: {i.code for i in validate(parse_cfg(s), "IWR1843").issues}
    assert "sample_rate_lowpower" in codes(on) and "sample_rate_lowpower" not in codes(t)
    off = apply_params(on, {"low_power": 0}, board="IWR1843")
    assert off.splitlines() == a and "sample_rate_lowpower" not in codes(off)
    assert apply_params(t, {"low_power": 0}) == apply_params(t, {})        # unchanged = untouched


def test_low_power_bad_values():
    t = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()
    with pytest.raises(CfgError):
        apply_params(t, {"low_power": 2})
    cas = (ROOT / "tools" / "radar_viewer" / "configs" / "cascade_R15m_V5ms_20Hz.cfg").read_text()
    with pytest.raises(CfgError):
        apply_params(cas, {"low_power": 1}, board="AWR2243_CASCADE")
