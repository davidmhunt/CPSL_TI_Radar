"""radar_gui.cfg: parse, metrics and per-board validation (gui-02 Step 1). Hardware-free."""
import importlib.util
import json
from pathlib import Path

import pytest

from radar_gui.cfg import BOARD_LIMITS, BOARDS, limits_dict, metrics, parse_cfg, parse_cfg_file, validate

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar"
VIEWER = ROOT / "tools" / "radar_viewer" / "configs"
SHIPPED = sorted(RADAR.rglob("*.cfg")) + sorted(VIEWER.glob("*.cfg"))


def board_for(p: Path) -> str:
    s = str(p)
    if "cascade" in s or "calibration_run" in s:
        return "AWR2243_CASCADE"
    if "1443" in s or "14xx" in s:
        return "IWR1443"
    if "6843" in s:
        return "IWR6843"
    return "IWR1843"


# --- parse -------------------------------------------------------------------------------------

def test_parse_drops_comments_and_keeps_line_numbers():
    cfg = parse_cfg("% header\n\nsensorStop % trailing\nprofileCfg 0 77 5\n# x\nfoo\n")
    assert [c.name for c in cfg.commands] == ["sensorStop", "profileCfg", "foo"]
    assert cfg.first("profileCfg").args == ["0", "77", "5"] and cfg.first("profileCfg").line == 4
    assert cfg.all("nope") == [] and not cfg.has("nope")


# --- metrics: hand-computed ----------------------------------------------------------------------

def test_metrics_1843_radvel_10hz_tdm():
    m = metrics(parse_cfg_file(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg"), "IWR1843")
    # slope 80, 63 samples @ 2100 ksps -> 30 us, B = 2400 MHz; fc = 77 + (80*7 + 1200)/1e3 = 78.76 GHz
    assert m.mode == "tdm" and (m.n_rx, m.n_tx, m.n_virtual, m.n_az_virtual) == (4, 2, 8, 8)
    assert m.range_res_m == pytest.approx(0.0625, rel=1e-3)
    assert m.max_range_ideal_m == pytest.approx(3.935, rel=1e-3) and m.max_range_m == pytest.approx(3.5414, rel=1e-3)
    # Tc = 337 us, 2 chirps per loop (TDM) -> loop 674 us; 115 loops -> 230 chirps
    assert m.chirp_us == 337 and m.n_chirps == 230
    assert m.max_velocity_ms == pytest.approx(1.4118, rel=2e-3)
    assert m.velocity_res_ms == pytest.approx(0.02455, rel=2e-3)
    assert m.azimuth_res_deg == pytest.approx(14.32, rel=1e-3)
    assert m.frame_period_ms == 100 and m.frame_rate_hz == 10
    assert m.active_ms == pytest.approx(77.51, rel=1e-3) and m.duty_cycle == pytest.approx(0.7751, rel=1e-3)
    assert m.bytes_per_chirp == 63 * 4 * 4 and m.bytes_per_frame == 63 * 4 * 4 * 230
    assert m.avg_data_rate_mbps == pytest.approx(63 * 16 * 230 * 8 / 1e5, rel=1e-6)


def test_metrics_6843_ods_tdm_three_tx():
    m = metrics(parse_cfg_file(RADAR / "nav_configs" / "6843_RadVel_ods_10Hz.cfg"), "IWR6843")
    # fc = 60 + (80*7 + 1200)/1e3 = 61.76 GHz; Tc = 244 us; 3 chirps per loop -> 732 us; 100 loops -> 300 chirps
    assert (m.n_tx, m.n_virtual, m.chirps_per_loop, m.n_chirps) == (3, 12, 3, 300)
    assert m.max_velocity_ms == pytest.approx(1.658, rel=2e-3)
    assert m.velocity_res_ms == pytest.approx(0.03316, rel=2e-3)
    assert m.range_res_m == pytest.approx(0.0625, rel=1e-3)


def test_metrics_cascade_ddma_matches_hand_and_cfggen():
    p = RADAR / "cascade" / "cascade_shortrange.cfg"
    m = metrics(parse_cfg_file(p), "AWR2243_CASCADE")
    # 192 samples @ 5000 ksps = 38.4 us, slope 44.41 -> B = 1705.3 MHz; Tc = 5 + 45 = 50 us; 8 x 32 = 256 chirps
    assert m.mode == "ddma" and (m.n_rx, m.n_tx, m.n_virtual) == (8, 6, 48)
    assert m.range_res_m == pytest.approx(0.08791, rel=1e-3)
    assert m.max_range_m == pytest.approx(15.2, rel=5e-3)
    assert m.max_velocity_ms == pytest.approx(19.19, rel=2e-3)      # DDMA: lambda / (4 Tc), not / (4 * 8 Tc)
    assert m.velocity_res_ms == pytest.approx(0.1500, rel=2e-3)
    assert m.n_chirps == 256 and m.frame_period_ms == 50 and m.duty_cycle == pytest.approx(0.256, rel=1e-3)
    assert m.bytes_per_chirp == 192 * 8 * 4 and m.bytes_per_frame == 192 * 8 * 4 * 256
    # cross-check against the existing generator's analyzer
    spec = importlib.util.spec_from_file_location("cfggen", ROOT / "tools" / "radar_viewer" / "cfggen.py")
    cfggen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfggen)
    a = cfggen.analyze(cfggen.read_lines(p))
    # cfggen uses c = 3e8 and we use 299792458 m/s: ~0.07 % apart
    assert m.range_res_m == pytest.approx(a["range_res_m"], rel=2e-3)
    assert m.max_range_m == pytest.approx(a["max_range_m"], rel=2e-3)
    assert m.max_velocity_ms == pytest.approx(a["max_velocity"], rel=2e-3)
    assert m.velocity_res_ms == pytest.approx(a["vel_res"], rel=2e-3)
    assert m.active_ms == pytest.approx(a["active_ms"], rel=1e-6)


def test_board_none_infers_layout_and_cascade_is_ddma():
    assert metrics(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg")).mode == "ddma"
    assert metrics(parse_cfg_file(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg")).mode == "tdm"


def test_real_adc_halves_bytes_and_range():
    base = parse_cfg_file(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg")
    m_c = metrics(base, "IWR1843")
    txt = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text().replace("adcCfg 2 1", "adcCfg 2 0")
    m_r = metrics(parse_cfg(txt), "IWR1843")
    assert m_r.bytes_per_chirp * 2 == m_c.bytes_per_chirp
    assert m_r.max_range_ideal_m == pytest.approx(m_c.max_range_ideal_m / 2)


def test_lvds_dataformat2_adds_per_chirp_metadata():
    txt = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text().replace("lvdsStreamCfg -1 0 1 0", "lvdsStreamCfg -1 0 2 0")
    m = metrics(parse_cfg(txt), "IWR1843")
    assert m.lvds_data_fmt == 2 and m.bytes_per_chirp == 63 * 16 + 64


# --- validate: deliberate violations -------------------------------------------------------------

def _mod(path, old, new):
    t = path.read_text()
    assert old in t
    return parse_cfg(t.replace(old, new))


def codes(rep, level=None):
    return {i.code for i in rep.issues if level is None or i.level == level}


def test_clean_cfg_validates():
    rep = validate(parse_cfg_file(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg"), "IWR1843")
    assert rep.ok and not rep.errors and rep.metrics is not None


def test_cascade_slope_over_limit_is_error():
    cfg = _mod(RADAR / "cascade" / "cascade_shortrange.cfg", "0 0 44.41 0 192", "0 0 150 0 192")
    rep = validate(cfg, "AWR2243_CASCADE")
    assert not rep.ok and "slope" in codes(rep, "error")


def test_single_chip_slope_over_limit_is_warning_only():
    cfg = _mod(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg", "0 0 80.0 1 63", "0 0 300.0 1 63")
    rep = validate(cfg, "IWR1843")
    slope = [i for i in rep.issues if i.code == "slope"]
    assert slope and slope[0].level == "warning" and slope[0].confidence == "unverified"


def test_samples_beyond_adc_buffer_reported():
    cfg = _mod(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg", "1 63 2100", "1 2000 2100")
    rep = validate(cfg, "IWR1843")
    assert "adc_buffer" in codes(rep) and "sampling_outside_ramp" in codes(rep, "error")


def test_cascade_untested_sample_count_warns():
    cfg = _mod(RADAR / "cascade" / "cascade_shortrange.cfg", "0 192 5000", "0 256 5000")
    rep = validate(cfg, "AWR2243_CASCADE")
    assert "samples" in codes(rep, "warning")


def test_idle_below_min_on_cascade_is_error():
    cfg = _mod(RADAR / "cascade" / "cascade_shortrange.cfg", "profileCfg 0 77 5 6 45", "profileCfg 0 77 2 6 45")
    assert "idle" in codes(validate(cfg, "AWR2243_CASCADE"), "error")


def test_band_overshoot_beyond_tolerance_is_error():
    cfg = _mod(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg", "profileCfg 0 77 293 7 44", "profileCfg 0 79 293 7 44")
    assert "band" in codes(validate(cfg, "IWR1843"), "error")   # 79 + 80*44 MHz = 82.52 GHz


def test_frame_shorter_than_chirps_is_error():
    cfg = _mod(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg", "frameCfg 0 1 115 0 100 1 0", "frameCfg 0 1 115 0 50 1 0")
    assert "frame_too_short" in codes(validate(cfg, "IWR1843"), "error")


def test_wrong_dialect_for_board_is_error():
    rep = validate(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg"), "IWR1843")
    assert not rep.ok and "frame_cfg_layout" in codes(rep)
    rep = validate(parse_cfg_file(RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg"), "AWR2243_CASCADE")
    assert not rep.ok


def test_missing_command_and_unknown_board():
    rep = validate(parse_cfg("sensorStart\n"), "IWR1843")
    assert not rep.ok and "missing_profileCfg" in codes(rep)
    assert "unknown_board" in codes(validate(parse_cfg("x"), "IWR9999"))


def test_cascade_cfg_notes_once_per_boot_and_lvds():
    rep = validate(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg"), "AWR2243_CASCADE")
    assert rep.ok and "once_per_boot" in codes(rep, "info")
    cfg = parse_cfg((RADAR / "cascade" / "cascade_shortrange.cfg").read_text() + "\nlvdsStreamCfg -1 0 1 0\n")
    assert "lvds_unsupported" in codes(validate(cfg, "AWR2243_CASCADE"), "warning")


def test_dca_link_rate_error():
    # 600 samples x 4 RX x 4 B per 60 us chirp = 1280 Mbps > 2 lanes x 600 Mbps
    txt = (RADAR / "nav_configs" / "1843_RadVel_10Hz.cfg").read_text()
    txt = txt.replace("profileCfg 0 77 293 7 44 0 0 80.0 1 63 2100", "profileCfg 0 77 5 7 55 0 0 20.0 1 600 12000")
    rep = validate(parse_cfg(txt), "IWR1843")
    assert "lvds_rate" in codes(rep, "warning") and rep.metrics.chirp_avg_rate_mbps == pytest.approx(1280, rel=1e-6)


# --- API shape -------------------------------------------------------------------------------------

def test_report_and_limits_are_json_serialisable():
    rep = validate(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg"), "AWR2243_CASCADE")
    d = json.loads(json.dumps(rep.to_dict()))
    assert d["board"] == "AWR2243_CASCADE" and d["metrics"]["mode"] == "ddma" and d["ok"] is True
    json.dumps(limits_dict())
    json.dumps(parse_cfg_file(SHIPPED[0]).to_dict())


def test_every_board_has_limits_with_source_and_confidence():
    assert set(BOARD_LIMITS) == set(BOARDS)
    for board, lim in BOARD_LIMITS.items():
        for key, v in lim.items():
            if key == "kind":
                continue
            assert v.source and v.confidence in ("repo", "recalled", "unverified"), (board, key)
            assert v.level in ("error", "warning")


# --- sweep over every shipped cfg --------------------------------------------------------------------

def test_sweep_found_the_shipped_cfgs():
    assert len(SHIPPED) >= 70


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: str(p.relative_to(ROOT)))
def test_shipped_cfg_parses_and_validates(path):
    board = board_for(path)
    rep = validate(parse_cfg_file(path), board)
    json.dumps(rep.to_dict())
    assert rep.metrics is not None, [i.message for i in rep.issues]
    # shipped cfgs run on hardware: any error here is either a real cfg problem or a wrong rule
    assert rep.ok, [i.message for i in rep.errors]


# ---------------------------------------------------------------------------------------------
# generate() (gui-02 Step 2)

import time

from radar_gui.cfg import generate

GEN_CASES = [("IWR1443", "demo_stock"), ("IWR1443", "dca1000_raw"), ("IWR1843", "demo_stock"),
             ("IWR1843", "demo_lvds"), ("IWR1843", "dca1000_raw"), ("IWR6843", "demo_stock"),
             ("IWR6843", "demo_lvds"), ("AWR2243_CASCADE", "cascade_ddm")]
TYPICAL = [dict(max_range_m=10, max_velocity_ms=5, range_res_m=0.1, frame_rate_hz=10),
           dict(max_range_m=20, max_velocity_ms=8, range_res_m=0.15, frame_rate_hz=20),
           dict(max_range_m=5, max_velocity_ms=3, frame_rate_hz=5)]


@pytest.mark.parametrize("board,fw", GEN_CASES)
@pytest.mark.parametrize("targets", TYPICAL)
def test_generate_round_trips_targets_and_validates_clean(board, fw, targets):
    r = generate(board, targets, firmware=fw)
    assert r.ok, [i.message for i in r.report.errors]
    assert not r.report.errors
    assert r.text.strip().startswith("%")
    # parse the returned text again, independently of the generator's own report
    m = metrics(parse_cfg(r.text), board)
    assert m.max_range_m == pytest.approx(targets["max_range_m"], rel=0.02)
    assert m.max_velocity_ms == pytest.approx(targets["max_velocity_ms"], rel=0.02)
    assert m.frame_rate_hz == pytest.approx(targets["frame_rate_hz"], rel=0.01)
    if "range_res_m" in targets:
        assert m.range_res_m == pytest.approx(targets["range_res_m"], rel=0.06)
    assert m.duty_cycle <= 0.9
    # no warnings for the typical targets either, apart from the cascade's standing notes
    # (cascade at 5 m needs a sample rate between TI's tested 5000/10000 ksps, which is a legitimate warning)
    assert not [i for i in r.report.warnings if i.code != "sample_rate_untested"], \
        [i.message for i in r.report.warnings]
    assert m.mode == ("ddma" if board == "AWR2243_CASCADE" else "tdm")
    assert validate(parse_cfg(r.text), board).ok


def test_generate_velocity_resolution_and_explicit_overrides():
    r = generate("IWR1843", max_range_m=10, max_velocity_ms=5, velocity_res_ms=0.1)
    assert r.metrics.velocity_res_ms == pytest.approx(0.1, rel=0.1)
    r = generate("IWR1843", max_range_m=10, max_velocity_ms=5, range_res_m=0.1, num_samples=64, num_loops=48)
    assert (r.metrics.num_samples, r.metrics.n_loops) == (64, 48)
    assert any(i.code == "range_res_ignored" for i in r.report.issues)


def test_generate_tx_rx_selection():
    r = generate("IWR6843", max_range_m=10, max_velocity_ms=4, tx_mask=7, rx_mask=0b0111)
    assert (r.metrics.n_tx, r.metrics.n_rx, r.metrics.chirps_per_loop) == (3, 3, 3)
    assert r.metrics.max_velocity_ms == pytest.approx(4, rel=0.02)   # 3 TX -> longer loop -> shorter chirps
    one = generate("IWR1843", max_range_m=10, max_velocity_ms=4, tx_mask=1)
    assert one.metrics.n_tx == 1
    assert generate("IWR1843", max_range_m=10, max_velocity_ms=4, tx_mask=9).report.errors[0].code == "bad_mask"
    cas = generate("AWR2243_CASCADE", max_range_m=10, max_velocity_ms=4, tx_mask=1)
    assert cas.metrics.n_tx == 6 and any(i.code == "mask_fixed" for i in cas.report.issues)


def test_generate_firmware_selects_cfg_flavour():
    assert "lvdsStreamCfg -1 0 0 0" in generate("IWR1843", max_range_m=10, max_velocity_ms=5).text   # default
    lv = generate("IWR1843", max_range_m=10, max_velocity_ms=5, firmware="demo_lvds")
    assert "lvdsStreamCfg -1 0 1 0" in lv.text and lv.metrics.lvds_data_fmt == 1
    assert lv.targets["firmware"] == "demo_lvds" and lv.targets["template"].startswith("radar/")
    raw = generate("IWR1843", max_range_m=10, max_velocity_ms=5, firmware="dca1000_raw")
    assert "guiMonitor" not in raw.text and "testFmkCfg" in raw.text
    assert generate("AWR2243_CASCADE", max_range_m=10, max_velocity_ms=5).targets["firmware"] == "cascade_ddm"


def test_generate_every_board_firmware_pair_generates_or_mismatches():
    from radar_gui.cfg import firmware as fwmod
    for fw in fwmod.load_all().values():
        for board in BOARDS:
            r = generate(board, max_range_m=10, max_velocity_ms=5, firmware=fw["id"])
            if board not in fw["boards"]:
                assert not r.ok and r.text == "" and r.report.errors[0].code == "firmware_board_mismatch", (board, fw["id"])
            elif fw.get("pending"):
                assert r.report.errors[0].code == "firmware_pending"
            else:
                assert r.ok, (board, fw["id"], [i.message for i in r.report.errors])
    r = generate("IWR1443", max_range_m=10, max_velocity_ms=5, firmware="demo_lvds")
    assert "supports:" in r.report.errors[0].message
    assert generate("IWR1843", max_range_m=10, max_velocity_ms=5, firmware="nope").report.errors[0].code \
        == "unknown_firmware"


def test_generate_output_mode_is_a_deprecated_alias():
    lv = generate("IWR1843", max_range_m=10, max_velocity_ms=5, output_mode="lvds")
    assert lv.ok and lv.targets["firmware"] == "demo_lvds"
    assert any(i.code == "output_mode_deprecated" for i in lv.report.issues)
    assert generate("AWR2243_CASCADE", max_range_m=10, max_velocity_ms=5, output_mode="tlv").ok
    assert generate("IWR1443", max_range_m=10, max_velocity_ms=5, output_mode="lvds").report.errors[0].code \
        == "firmware_board_mismatch"
    assert generate("IWR1843", max_range_m=10, max_velocity_ms=5, output_mode="x").report.errors[0].code \
        == "bad_output_mode"


# --- firmware descriptors (gui-10) --------------------------------------------------------------------

def _descriptor_files():
    from radar_gui.cfg import firmware as fwmod
    return sorted(fwmod.FIRMWARE_DIR.glob("*.json"))


def test_firmware_descriptors_exist_and_validate():
    from radar_gui.cfg import firmware as fwmod
    files = _descriptor_files()
    assert {p.stem for p in files} >= {"demo_stock", "demo_lvds", "dca1000_raw", "iwr1843_sar_lvds", "cascade_ddm"}
    for p in files:
        d = json.loads(p.read_text())
        assert fwmod.check_descriptor(d, p.stem) == [], p.name
        for b in d["boards"]:   # every board has a template that exists
            assert (fwmod.CONFIG_DIR / d["templates"][b]).is_file(), (p.name, b)
    assert set(fwmod.load_all()) == {p.stem for p in files}


def test_firmware_descriptor_schema_rejects_bad_files():
    from radar_gui.cfg import firmware as fwmod
    good = json.loads((fwmod.FIRMWARE_DIR / "demo_lvds.json").read_text())
    def bad(**ch):
        return fwmod.check_descriptor({**good, **ch}, "demo_lvds")
    assert bad(boards=["NOPE"]) and bad(outputs={"tlv": False, "lvds": False}) and bad(templates={})
    assert bad(system_enables={"serial": True}) and bad(id="other")
    assert bad(limits={"IWR1843": {"x": {"value": 1}}})


def test_every_board_has_a_default_firmware_with_matching_limits():
    from radar_gui.cfg import firmware as fwmod
    for board in BOARDS:
        d = fwmod.default_for(board)
        assert d is not None and d["limits"][board], board
        assert fwmod.for_board(board)[0]["id"] == d["id"]
        assert set(BOARD_LIMITS[board]) == set(d["limits"][board])


def test_validate_with_firmware_uses_its_limits_and_rejects_unsupported():
    cfg = parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg")
    assert validate(cfg, "AWR2243_CASCADE", "cascade_ddm").ok
    assert validate(cfg, "AWR2243_CASCADE", "demo_stock").errors[0].code == "firmware_board_mismatch"


def test_generate_infeasible_range_resolution_is_reported_not_raised():
    for board in ("IWR1843", "AWR2243_CASCADE"):
        r = generate(board, max_range_m=100, max_velocity_ms=5, range_res_m=0.02)
        codes = {i.code for i in r.report.errors}
        assert not r.ok and "range_unreachable" in codes and codes & {"band", "slope"}, codes
        assert r.text   # best-effort cfg is still returned


def test_generate_infeasible_velocity_is_reported():
    r = generate("IWR1843", max_range_m=10, max_velocity_ms=80, range_res_m=0.05)
    assert not r.ok and any(i.code == "velocity_unreachable" for i in r.report.errors)
    r = generate("AWR2243_CASCADE", max_range_m=15, max_velocity_ms=60)
    assert not r.ok and any(i.code == "velocity_unreachable" for i in r.report.errors)


def test_generate_too_long_chirps_for_frame_rate_is_reported():
    r = generate("IWR1843", max_range_m=10, max_velocity_ms=5, frame_rate_hz=500, num_loops=200)
    assert not r.ok and any(i.code == "frame_too_short" for i in r.report.errors)


def test_generate_bad_input_is_structured():
    for board, t, code in [("IWR9999", dict(max_range_m=1, max_velocity_ms=1), "unknown_board"),
                           ("IWR1843", dict(max_velocity_ms=1), "bad_target"),
                           ("IWR1843", dict(max_range_m="far", max_velocity_ms=1), "bad_target"),
                           ("IWR1843", dict(max_range_m=-3, max_velocity_ms=1), "bad_target"),
                           ("IWR1843", dict(max_range_m=3, max_velocity_ms=1, frame_rate_hz=0), "bad_target")]:
        r = generate(board, t)
        assert not r.ok and r.text == "" and r.report.errors[0].code == code
    r = generate("IWR1843", dict(max_range_m=10, max_velocity_ms=5, bogus=1))
    assert r.ok and any(i.code == "unknown_target" for i in r.report.warnings)


def test_generate_result_is_json_safe_and_fast():
    t0 = time.perf_counter()
    for board, fw in GEN_CASES:
        r = generate(board, TYPICAL[0], firmware=fw)
        json.dumps(r.to_dict(), allow_nan=False)
    bad = generate("IWR1843", max_range_m=100, max_velocity_ms=5, range_res_m=0.02)
    json.dumps(bad.to_dict(), allow_nan=False)
    assert (time.perf_counter() - t0) / (len(GEN_CASES) + 1) < 0.05   # keystroke-rate budget, per call


def test_generated_text_only_changes_what_depends_on_targets():
    """Boilerplate comes from the shipped template: same command set, only timing lines differ."""
    r = generate("AWR2243_CASCADE", max_range_m=15.2, max_velocity_ms=19.4, frame_rate_hz=20)
    ship = parse_cfg_file(Path(__file__).resolve().parents[1] / "CPSL_TI_Radar_cpp/config/radar/cascade"
                          / "cascade_shortrange.cfg")
    assert [c.name for c in parse_cfg(r.text).commands] == [c.name for c in ship.commands]
    # reproduces TI's short-range design: 192 samples, ~5 Msps, ~44 MHz/us
    assert r.metrics.num_samples == 192 and r.metrics.sample_rate_ksps == 5000
    assert r.metrics.slope_mhz_us == pytest.approx(44.4, rel=0.03)
