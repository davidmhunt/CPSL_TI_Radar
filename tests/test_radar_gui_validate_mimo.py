"""gui-15 Step 1: per-scheme chirp-pattern / BPM / subframe / profile validation rules, each with a violating cfg
and a passing counterpart (docs/design/mimo_modes.md section 4). Hardware-free."""
import re
from pathlib import Path

import pytest

from radar_gui.cfg import firmware as fwmod
from radar_gui.cfg import parse_cfg, parse_cfg_file, validate

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar"
FIX = ROOT / "tests" / "fixtures" / "mimo"
REPEAT = (FIX / "s3_repeat.cfg").read_text()      # TDM [1,4,1,4], 4 chirps x 32 loops, channelCfg 15 5 0, no bpm
BPM = (FIX / "s2_bpm.cfg").read_text()            # masks 5,5 + bpmCfg on
ADV = (FIX / "adv_subframe_4.cfg").read_text()    # advFrameCfg 4 subframes
CASCADE = (RADAR / "cascade" / "cascade_shortrange.cfg").read_text()


def edit(text, old, new):
    assert old in text
    return text.replace(old, new)


def tdm(masks, loops=32, tx=None, base=REPEAT):
    """`base` with the chirp table replaced by `masks` (one chirpCfg per chirp) and frameCfg to match."""
    lines = [l for l in base.splitlines() if not l.startswith(("chirpCfg", "frameCfg"))]
    out = []
    for l in lines:
        out.append(l)
        if l.startswith("profileCfg"):
            out += [f"chirpCfg {i} {i} 0 0 0 0 0 {m}" for i, m in enumerate(masks)]
            out.append(f"frameCfg 0 {len(masks) - 1} {loops} 0 25 1 0")
    t = "\n".join(out)
    if tx is not None:
        t = re.sub(r"channelCfg 15 \d+ 0", f"channelCfg 15 {tx} 0", t)
    return t


def rep(text, board="IWR6843", fw="demo"):
    return validate(parse_cfg(text), board, fw)


def lv(r, code):
    return [i.level for i in r.issues if i.code == code]


MIX = {"tx_pattern_invalid", "tx_not_in_channelcfg", "tx_pattern_not_periodic", "tx_missing_from_loop",
       "tx_loops_odd", "tx_order_convention", "simo_multi_tx", "bpm_unsupported", "subframes_unsupported",
       "extra_profiles_ignored", "chirps_span_profiles", "cascade_chirp_mask_ignored", "ddma_cpl_not_band_multiple"}


def mimo_codes(r):
    return {i.code for i in r.issues} & MIX


# --- passing counterparts -----------------------------------------------------------------------------

@pytest.mark.parametrize("text", [REPEAT, tdm([1, 4]), tdm([1, 4, 2], tx=7, loops=32), tdm([1], tx=1), BPM],
                         ids=["repeat", "az2", "az2+elev", "single", "bpm"])
def test_valid_patterns_raise_nothing(text):
    r = rep(text)
    assert r.ok and not mimo_codes(r), [(i.code, i.message) for i in r.issues]


# --- TDM pattern rules ---------------------------------------------------------------------------------

def test_mixed_one_tx_and_multi_tx_is_an_error():
    r = rep(tdm([1, 5]))
    assert lv(r, "tx_pattern_invalid") == ["error"] and not r.ok


def test_chirps_per_loop_over_max_is_error_and_at_max_is_fine():
    assert lv(rep(tdm([1, 4] * 17, loops=4)), "tx_pattern_invalid") == ["error"]       # 34 > 32
    assert not lv(rep(tdm([1, 4] * 16, loops=4)), "tx_pattern_invalid")                # 32 ok


def test_chirp_with_no_tx_is_error():
    assert lv(rep(tdm([1, 0])), "tx_pattern_invalid") == ["error"]


def test_not_periodic_pattern_is_warning_not_error():
    r = rep(tdm([1, 4, 1, 2], tx=7))
    assert lv(r, "tx_pattern_not_periodic") == ["warning"] and r.ok
    assert not lv(rep(tdm([1, 4, 1, 4])), "tx_pattern_not_periodic")


def test_tx_missing_from_loop_is_info():
    r = rep(tdm([1, 1], tx=5))        # channelCfg enables TX3, no chirp uses it
    assert lv(r, "tx_missing_from_loop") == ["info"] and r.ok


def test_three_tx_odd_loops_warns():
    assert lv(rep(tdm([1, 4, 2], tx=7, loops=31)), "tx_loops_odd") == ["warning"]
    assert not lv(rep(tdm([1, 4, 2], tx=7, loops=32)), "tx_loops_odd")


def test_tx_order_convention_is_warning_elevation_last_is_clean():
    r = rep(tdm([1, 2, 4], tx=7))
    assert lv(r, "tx_order_convention") == ["warning"] and r.ok
    assert not lv(rep(tdm([1, 4, 2], tx=7)), "tx_order_convention")


def test_chirp_tx_outside_channelcfg_is_error():
    r = rep(tdm([1, 2], tx=1))        # TX2 not enabled in channelCfg
    assert lv(r, "tx_not_in_channelcfg") == ["error"] and not r.ok
    assert not lv(rep(tdm([1, 4], tx=5)), "tx_not_in_channelcfg")


def test_simo_multi_tx_without_bpm_is_info_only():
    r = rep(tdm([5]))
    assert lv(r, "simo_multi_tx") == ["info"] and r.ok and not lv(r, "tx_pattern_invalid")


# --- BPM -----------------------------------------------------------------------------------------------

def test_bpm_on_a_bpm_false_firmware_is_error():
    real = fwmod.mimo
    with pytest.MonkeyPatch.context() as mp:                     # SAR-like descriptor: bpm false, medium confidence
        mp.setattr(fwmod, "mimo", lambda b, f: {**real(b, f), "bpm": False, "confidence": "medium"})
        r = rep(BPM, "IWR1843", "demo")
    assert lv(r, "bpm_unsupported") == ["error"] and not r.ok
    assert not lv(rep(BPM, "IWR1843", "demo"), "bpm_unsupported")        # the real demo allows it


def test_bpm_on_unverified_firmware_is_only_a_warning():
    r = rep(BPM, "IWR1443", "demo")                              # 1443 demo override: bpm false, unverified
    assert lv(r, "bpm_unsupported") == ["warning"]
    assert lv(rep(BPM, "IWR6843", "dca1000_raw"), "bpm_unsupported") == ["warning"]


def test_bpm_needs_mask_5_on_every_chirp():
    assert lv(rep(edit(BPM, "chirpCfg 1 1 0 0 0 0 0 5", "chirpCfg 1 1 0 0 0 0 0 4")), "tx_pattern_invalid") == ["error"]


# --- subframes -----------------------------------------------------------------------------------------

def test_advanced_frame_cfg_is_accepted_on_demo():
    r = rep(ADV, "IWR1843", "demo")
    assert not {i.code for i in r.errors} & MIX and "missing_frameCfg" not in codes_of(r) and "subframes_unsupported" not in codes_of(r)


def codes_of(r):
    return {i.code for i in r.issues}


def test_advanced_frame_cfg_rejected_where_subframes_is_zero():
    real = fwmod.mimo
    with pytest.MonkeyPatch.context() as mp:                     # SAR-like descriptor: subframes 0
        mp.setattr(fwmod, "mimo", lambda b, f: {**real(b, f), "subframes": 0})
        r = rep(ADV, "IWR1843", "demo")
    assert lv(r, "subframes_unsupported") == ["error"] and not r.ok


def test_advanced_frame_unknown_support_is_a_warning():
    assert lv(rep(ADV, "IWR6843", "dca1000_raw"), "subframes_unsupported") == ["warning"]


def test_advanced_frame_over_max_subframes_is_error(monkeypatch):
    from radar_gui.cfg import firmware as fwmod
    real = fwmod.mimo
    monkeypatch.setattr(fwmod, "mimo", lambda b, f: {**real(b, f), "subframes": 2})
    assert lv(rep(ADV, "IWR1843", "demo"), "subframes_unsupported") == ["error"]


def test_plain_frame_without_framecfg_still_missing():
    r = rep("\n".join(l for l in REPEAT.splitlines() if not l.startswith("frameCfg")))
    assert "missing_frameCfg" in codes_of(r) and not r.ok


# --- profiles ------------------------------------------------------------------------------------------

def test_profile_not_used_by_the_frame_is_ignored_warning():
    extra = "profileCfg 1 60 7 7 40 0 0 100 1 256 8000 0 0 158\n"
    r = rep(edit(REPEAT, "chirpCfg 0 0", extra + "chirpCfg 0 0"))
    assert lv(r, "extra_profiles_ignored") == ["warning"] and r.ok
    assert not lv(rep(REPEAT), "extra_profiles_ignored")
    assert not lv(rep(ADV, "IWR1843", "demo"), "extra_profiles_ignored")   # every profile used by a subframe


def test_chirps_spanning_two_profiles_is_error():
    extra = "profileCfg 1 60 7 7 40 0 0 100 1 256 8000 0 0 158\n"
    t = edit(REPEAT, "chirpCfg 0 0", extra + "chirpCfg 0 0")
    bad = re.sub(r"chirpCfg 1 1 0", "chirpCfg 1 1 1", t)
    r = rep(bad)
    assert lv(r, "chirps_span_profiles") == ["error"] and not r.ok
    i = next(i for i in r.issues if i.code == "chirps_span_profiles")
    assert "multiprofile" in i.message and i.confidence == "high"
    assert not lv(rep(t), "chirps_span_profiles")      # extra profile declared but unused: warning only
    assert not lv(rep(REPEAT), "chirps_span_profiles")


# --- cascade / DDMA ------------------------------------------------------------------------------------

def test_cascade_chirp_mask_differing_from_channelcfg_is_info():
    r = rep(edit(CASCADE, "chirpCfg 0 7 0 0 0 0 0 7", "chirpCfg 0 7 0 0 0 0 0 1"), "AWR2243_CASCADE", "cascade_ddm")
    assert lv(r, "cascade_chirp_mask_ignored") == ["info"] and r.ok
    assert not mimo_codes(rep(CASCADE, "AWR2243_CASCADE", "cascade_ddm"))


def test_cascade_cpl_not_multiple_of_bands_warns():
    t = edit(edit(CASCADE, "chirpCfg 0 7 ", "chirpCfg 0 5 "), "frameCfg 0 7 32", "frameCfg 0 5 32")
    r = rep(t, "AWR2243_CASCADE", "cascade_ddm")
    assert lv(r, "ddma_cpl_not_band_multiple") == ["warning"] and r.ok


def test_cascade_advanced_frame_is_an_error():
    adv = (edit(CASCADE, "frameCfg 0 7 32 0 192 50 1 0 2", "") + "\nadvFrameCfg 1 0 1 0 1\n"
           "subFrameCfg 0 0 0 8 32 0 0 1 1 100\n")
    r = rep(adv, "AWR2243_CASCADE", "cascade_ddm")
    assert lv(r, "subframes_unsupported") == ["error"]


def test_tdm_rules_do_not_apply_to_ddma():
    # eight identical chirps with mask 7 would be 'multi-TX' on TDM; on DDMA it is the shipped layout
    r = rep(CASCADE, "AWR2243_CASCADE", "cascade_ddm")
    assert not (codes_of(r) & {"simo_multi_tx", "tx_pattern_invalid"})


# --- issue shape + sweep -------------------------------------------------------------------------------

def test_issues_carry_source_and_confidence():
    r = rep(tdm([1, 5]))
    i = next(i for i in r.issues if i.code == "tx_pattern_invalid")
    assert "gui_multichirp_tdm.md" in i.source and i.confidence == "high"


def test_shipped_cfgs_have_no_pattern_errors_and_only_known_warnings():
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    from test_radar_gui_cfg import SHIPPED, board_for
    seen = set()
    for p in SHIPPED:
        r = validate(parse_cfg_file(p), board_for(p))
        assert r.ok, (str(p), [i.message for i in r.errors])
        seen |= {(i.level, i.code) for i in r.issues} & {(l, c) for l in ("warning", "info", "error") for c in MIX}
    # raw-ADC cfgs enable TX channels no chirp uses; 6843 ODS cfgs use the 1,2,4 order: both reported, neither an error
    assert seen == {("info", "tx_missing_from_loop"), ("warning", "tx_order_convention")}, seen
