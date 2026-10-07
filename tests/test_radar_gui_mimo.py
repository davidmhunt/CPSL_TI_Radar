"""gui-14 Step 2: chirp-sequence parse + MIMO-scheme-aware metrics against the hand-derived oracle
(gui-14 directive Log, from docs/design/mimo_modes.md). Hardware-free."""
import json
from pathlib import Path

import pytest

from radar_gui.cfg import CfgError, metrics, parse_cfg, parse_cfg_file, validate
from radar_gui.cfg import firmware as fwmod

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar"
FIX = ROOT / "tests" / "fixtures" / "mimo"
REL = 5e-4   # oracle is given to 4 significant figures

# case: (cfg path, board, scheme, n_tx, T_loop us, N, bins, step, dv, vmax, n_virtual)
CASES = {
    "A_simo": (FIX / "s1_simo.cfg", "IWR6843", "tdm", 1, 108, 64, 64, 0.3481, 0.3481, 11.14, 4),
    "B_tdm2": (RADAR / "IWR_Demos" / "6843.cfg", "IWR6843", "tdm", 2, 216, 64, 32, 0.3481, 0.3481, 5.570, 8),
    "C1_tdm3": (RADAR / "IWR_Demos" / "short_range_3D.cfg", "IWR6843", "tdm", 3, 192.4, 48, 16, 0.6147, 0.6147, 4.917, 12),
    "D_bpm": (FIX / "s2_bpm.cfg", "IWR6843", "tdm", 2, 216, 128, 64, 0.1741, 0.1741, 5.570, 8),
    "E_repeat": (FIX / "s3_repeat.cfg", "IWR6843", "tdm", 2, 216, 128, 64, 0.1741, 0.1741, 5.570, 8),
    "F_ddma": (RADAR / "cascade" / "cascade_shortrange.cfg", "AWR2243_CASCADE", "ddma", 6, 50, 256, 256,
               0.1499, 0.1499, 19.19, 48),
}


@pytest.mark.parametrize("name", CASES)
def test_oracle_case(name):
    path, board, scheme, n_tx, t_loop, n, bins, step, dv, vmax, n_virt = CASES[name]
    m = metrics(parse_cfg_file(path), board, scheme)
    assert m.scheme == m.mode == scheme
    assert m.n_tx == n_tx and m.n_virtual == n_virt and m.n_chirps == n and m.doppler_bins == bins
    assert m.loop_period_us == pytest.approx(t_loop, rel=REL)
    assert m.doppler_step_ms == pytest.approx(step, rel=REL)
    assert m.velocity_res_ms == pytest.approx(dv, rel=REL)
    assert m.max_velocity_ms == pytest.approx(vmax, rel=REL) and m.vmax_full_ms == m.max_velocity_ms


def test_oracle_c2_non_pow2_step_differs_from_resolution():
    txt = (RADAR / "IWR_Demos" / "short_range_3D.cfg").read_text().replace(
        "frameCfg 0 2 16 0 33.333 1 0", "frameCfg 0 2 50 0 33.333 1 0")
    m = metrics(parse_cfg(txt), "IWR6843", "tdm")
    assert (m.n_tx, m.n_chirps, m.doppler_bins) == (3, 150, 64)
    assert m.doppler_step_ms == pytest.approx(0.1537, rel=REL) and m.velocity_res_ms == pytest.approx(0.1967, rel=REL)
    assert m.max_velocity_ms == pytest.approx(4.917, rel=REL)


def test_oracle_lambda_is_sampled_band_centre():
    assert metrics(parse_cfg_file(FIX / "s1_simo.cfg"), "IWR6843", "tdm").lambda_mm == pytest.approx(4.812, rel=REL)
    assert metrics(parse_cfg_file(RADAR / "IWR_Demos" / "short_range_3D.cfg"), "IWR6843", "tdm").lambda_mm == \
        pytest.approx(3.785, rel=REL)
    assert metrics(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg"), "AWR2243_CASCADE", "ddma"
                   ).lambda_mm == pytest.approx(3.838, rel=REL)


def test_repeated_pattern_uses_n_tx_not_chirps_per_loop():
    m = metrics(parse_cfg_file(FIX / "s3_repeat.cfg"), "IWR6843", "tdm")
    assert m.chirps_per_loop == 4 and m.n_tx == 2
    assert m.loop_period_us == pytest.approx(216) and m.pattern_period_us == pytest.approx(432)
    assert m.max_velocity_ms == pytest.approx(5.570, rel=REL)   # not 2.785 (cpl*Tc)


def test_simo_is_not_popcount():
    m = metrics(parse_cfg_file(FIX / "s1_simo.cfg"), "IWR6843", "tdm")
    assert m.n_tx == 1 and m.n_az_virtual == 4 and not m.bpm_enabled
    assert any("SIMO" in n for n in m.notes)


def test_bpm_flag_parsed():
    assert metrics(parse_cfg_file(FIX / "s2_bpm.cfg"), "IWR6843", "tdm").bpm_enabled
    assert not metrics(parse_cfg_file(RADAR / "IWR_Demos" / "6843.cfg"), "IWR6843", "tdm").bpm_enabled


def test_ddma_two_vmax_pattern_period_and_unverified_bins():
    m = metrics(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg"), "AWR2243_CASCADE", "ddma")
    assert m.vmax_full_ms == pytest.approx(19.19, rel=REL) and m.vmax_per_tx_ms == pytest.approx(2.399, rel=REL)
    assert m.n_bands == 8 and m.loop_period_us == pytest.approx(50) and m.pattern_period_us == pytest.approx(400)
    assert m.doppler_bins // m.n_bands == 32
    d = m.derivations
    assert d["doppler_bins"]["confidence"] == "unverified" and d["vmax_per_tx_ms"]["confidence"] == "derived"
    for k in ("n_tx", "loop_period_us", "doppler_bins", "doppler_step_ms", "velocity_res_ms", "vmax_full_ms",
              "vmax_per_tx_ms", "n_virtual"):
        assert d[k]["formula"] and d[k]["scheme"] == "ddma"


def test_tdm_derivations_and_vmax_per_tx_equals_full():
    m = metrics(parse_cfg_file(RADAR / "IWR_Demos" / "6843.cfg"), "IWR6843", "tdm")
    assert m.vmax_per_tx_ms == m.vmax_full_ms and m.n_bands == 1
    assert all(v["scheme"] == "tdm" and v["formula"] for v in m.derivations.values())
    assert m.derivations["doppler_bins"]["confidence"] == "derived"


def test_chirp_sequence_and_default_scheme():
    cfg = parse_cfg_file(RADAR / "IWR_Demos" / "short_range_3D.cfg")
    assert cfg.chirp_sequence == [(0, 1), (1, 4), (2, 2)]
    assert [c["tx_mask"] for c in metrics(cfg, "IWR6843").chirp_sequence] == [1, 4, 2]
    # no scheme passed: the board's default firmware decides, else the cfg layout
    assert metrics(cfg, "IWR6843").scheme == fwmod.mimo("IWR6843", fwmod.default_for("IWR6843"))["scheme"] == "tdm"
    casc = parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg")
    assert metrics(casc, "AWR2243_CASCADE").scheme == "ddma" and metrics(casc).scheme == "ddma"
    assert metrics(cfg).scheme == "tdm"
    with pytest.raises(CfgError):
        metrics(cfg, "IWR6843", "bogus")


def test_validate_passes_the_firmware_scheme():
    cfg = parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg")
    assert validate(cfg, "AWR2243_CASCADE", "cascade_ddm").metrics.scheme == "ddma"
    assert validate(parse_cfg_file(FIX / "s3_repeat.cfg"), "IWR6843", "demo").metrics.scheme == "tdm"


# --- advFrameCfg ----------------------------------------------------------------------------

# NOTE: the Step 1 oracle rows for subframes 2 and 3 used slope 100 for every profile; the cfg's profiles 2 and 3
# have slope 55 and 15, so those rows are re-derived by hand here (fc = 77 + (slope*3 + B/2)/1000 GHz, B = slope*ts).
ADV = [  # sub: chirps_per_loop, n_loops, Tc, lambda_mm, step, vmax, bins
    (0, 2, 32, 12, 3.869, 2.519, 40.30, 32),
    (1, 2, 32, 46, 3.791, 0.6439, 10.30, 32),
    (2, 2, 32, 31, 3.857, 0.9720, 15.55, 32),
    (3, 2, 16, 51, 3.876, 1.187, 9.499, 16),
]


def test_adv_frame_four_subframes_oracle_case_g():
    cfg = parse_cfg_file(FIX / "adv_subframe_4.cfg")
    assert [s["num_loops"] for s in cfg.subframes] == [32, 32, 32, 16]
    m = metrics(cfg, "IWR1843", "tdm")      # no frameCfg: must not raise
    assert len(m.subframes) == 4
    for sf, (i, cpl, loops, tc, lam, step, vmax, bins) in zip(m.subframes, ADV):
        assert sf["index"] == i and sf["chirps_per_loop"] == cpl and sf["n_loops"] == loops
        assert sf["chirp_us"] == pytest.approx(tc) and sf["n_tx"] == 2 and sf["n_virtual"] == 8
        assert sf["profile_id"] == i
        assert sf["doppler_bins"] == bins and sf["loop_period_us"] == pytest.approx(2 * tc)
        assert sf["doppler_step_ms"] == pytest.approx(step, rel=REL) and sf["velocity_res_ms"] == pytest.approx(step, rel=REL)
        assert sf["max_velocity_ms"] == pytest.approx(vmax, rel=REL)
    assert m.lambda_mm == pytest.approx(3.869, rel=REL) and m.max_velocity_ms == pytest.approx(40.30, rel=REL)


def test_adv_frame_two_subframe_variant():
    txt = "\n".join(l for l in (FIX / "adv_subframe_4.cfg").read_text().splitlines()
               if not l.startswith(("subFrameCfg 2", "subFrameCfg 3"))).replace("advFrameCfg 4", "advFrameCfg 2")
    m = metrics(parse_cfg(txt), "IWR1843", "tdm")
    assert [s["index"] for s in m.subframes] == [0, 1]
    assert m.subframes[1]["max_velocity_ms"] == pytest.approx(10.30, rel=REL)


def test_adv_frame_count_mismatch_is_an_error():
    txt = (FIX / "adv_subframe_4.cfg").read_text().replace("advFrameCfg 4", "advFrameCfg 3")
    with pytest.raises(CfgError):
        metrics(parse_cfg(txt), "IWR1843", "tdm")


def test_plain_cfg_has_no_subframes():
    assert metrics(parse_cfg_file(FIX / "s1_simo.cfg"), "IWR6843", "tdm").subframes == []


# --- golden compare: every shipped cfg vs the pre-gui-14 output ----------------------------------

def test_golden_every_shipped_cfg_unchanged():
    """The fixture is metrics() output from before gui-14 (key numeric fields). The directive Log lists
    every diff: none in these fields (only the cascade azimuth note wording, not compared here)."""
    from test_radar_gui_cfg import SHIPPED, board_for
    gold = json.loads((FIX / "golden_metrics_pre_gui14.json").read_text())
    got = {}
    for p in SHIPPED:
        got[str(p.relative_to(ROOT))] = metrics(parse_cfg_file(p), board_for(p)).to_dict()
    # the untracked/extra cfgs are only compared when the fixture knows them
    assert set(gold) <= set(got) and len(gold) == 77
    for k, old in gold.items():
        for f, v in old.items():
            want = v if isinstance(v, str) else pytest.approx(v, rel=1e-12)
            assert got[k][f] == want, (k, f)


# --- gui-23: per-TX phase readout --------------------------------------------------------------

def test_ddma_phase_table_6tx_cpl8():
    m = metrics(parse_cfg_file(RADAR / "cascade" / "cascade_shortrange.cfg"), "AWR2243_CASCADE", "ddma")
    assert m.phase_tx == ["TX1", "TX2", "TX3", "TX4", "TX5", "TX6"]
    assert len(m.chirp_phases) == 8 and m.phase_confidence == "unverified" and "HYPOTHESIS" in m.phase_note
    assert "firmware-derived" in m.phase_source
    ph = [r["phase_deg"] for r in m.chirp_phases]
    by_rank = {r: [row[tx] for row in ph] for r, tx in enumerate((2, 0, 5, 4, 3, 1))}   # TX index per rank
    assert by_rank[0] == [0] * 8
    assert by_rank[1] == [0, 45, 90, 135, 180, 225, 270, 315]
    assert by_rank[2] == [0, 90, 180, 270, 0, 90, 180, 270]
    assert by_rank[3] == [0, 135, 270, 45, 180, 315, 90, 225]
    assert by_rank[4] == [0, 180, 0, 180, 0, 180, 0, 180]
    assert by_rank[5] == [0, 225, 90, 315, 180, 45, 270, 135]
    assert ph[1] == [45, 225, 0, 180, 135, 90]    # chirp 1 per TX1..TX6 (rank of TX1 = 1, TX2 = 5, TX3 = 0, ...)


def test_ddma_phase_quantised_to_5p625():
    from radar_gui.cfg.metrics import ddma_chirp_phase_deg
    assert all(ddma_chirp_phase_deg(k, r) % 5.625 == 0 for k in range(32) for r in range(6))
    with pytest.raises(ValueError):
        ddma_chirp_phase_deg(1, 1, n_tx=4)


def test_bpm_phase_table_0_180_on_chirp1():
    m = metrics(parse_cfg_file(FIX / "s2_bpm.cfg"), "IWR6843", "tdm")
    assert m.phase_tx == ["TX1", "TX3"] and m.phase_source == "bpmCfg chirp0/chirp1"
    assert [r["phase_deg"] for r in m.chirp_phases] == [[0, 0], [0, 180]]


def test_tdm_phase_table_zeros():
    m = metrics(parse_cfg_file(RADAR / "IWR_Demos" / "short_range_3D.cfg"), "IWR6843", "tdm")
    assert m.phase_source == "none (TDM)" and m.phase_tx == ["TX1", "TX2", "TX3"]
    assert [r["phase_deg"] for r in m.chirp_phases] == [[0, 0, 0]] * 3
    assert [r["index"] for r in m.chirp_phases] == [0, 1, 2]
