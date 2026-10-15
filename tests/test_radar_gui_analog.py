"""radar-36: per-chip HPF corner / rxGain / IF-band data (config/firmware/*.json limits), its validation, the Raw ADC band
edges and the Configure UI's "no tables in JS" rule. Hardware-free; reads config/user/ with read access only."""
import json
import re
from pathlib import Path

import pytest

from radar_gui.cfg import CfgError, apply_params, params_from_cfg, parse_cfg, validate
from radar_gui.cfg import analog
from radar_gui.cfg import firmware as fwmod
from radar_gui.cfg import limits as limmod

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "CPSL_TI_Radar_cpp" / "config"
WEBJS = ROOT / "radar_gui" / "web" / "js"
CHIPS = ["IWR1443", "IWR1843", "IWR6843", "IWR6843ODS", "AWR2243_CASCADE"]

# The values of docs/research/gui_hpf_rxgain_2026-10-15.md (E1, E3, E5/E6), written out independently of the descriptors.
HPF1, HPF2 = [175, 235, 350, 700], [350, 700, 1400, 2800]
GAIN = {"IWR1443": (24, 48), "IWR1843": (24, 48), "IWR6843": (30, 48), "IWR6843ODS": (30, 48), "AWR2243_CASCADE": (32, 52)}
RF = {"IWR1443": [30, 34, "reserved", 26], "IWR1843": [30, 34, "reserved", 26],
      "IWR6843": [30, 33, 36, "reserved"], "IWR6843ODS": [30, 33, 36, "reserved"], "AWR2243_CASCADE": [30, 33, 36, "reserved"]}
RF_CONF_UNVERIFIED = {"AWR2243_CASCADE"}
IF_MAX = {"IWR1443": 15, "IWR1843": 10, "IWR6843": 10, "IWR6843ODS": 10, "AWR2243_CASCADE": 20}
KEYS = [*analog.HPF_KEYS, *analog.GAIN_KEYS, "rx_gain_rf_target_db", "if_band_max_mhz", *analog.IF_FRAC_KEYS.values()]


def descriptor_boards():
    for fid, d in fwmod.load_all().items():
        for b, entries in d["limits"].items():
            yield fid, b, entries


def test_every_chip_entry_has_every_key_with_source_and_confidence():
    seen = set()
    for fid, b, e in descriptor_boards():
        seen.add(b)
        assert b != "IWR1843_SAR"          # a driver-board mapping, not a chip
        for k in KEYS:
            assert k in e, (fid, b, k)
            assert e[k]["source"].strip() and e[k]["confidence"] in fwmod.CONFIDENCES and e[k]["level"] in fwmod.LEVELS, (fid, b, k)
            assert "gui_hpf_rxgain_2026-10-15.md" in e[k]["source"], (fid, b, k)   # cites a row of the Step 1 memo
    assert seen == set(CHIPS)


def test_table_values_equal_the_memo():
    for fid, b, e in descriptor_boards():
        assert e["hpf1_corner_khz"]["value"] == HPF1 and e["hpf2_corner_khz"]["value"] == HPF2, (fid, b)
        assert (e["rx_gain_min_db"]["value"], e["rx_gain_max_db"]["value"], e["rx_gain_step_db"]["value"]) == (*GAIN[b], 2), (fid, b)
        assert e["rx_gain_rf_target_db"]["value"] == RF[b], (fid, b)
        assert (e["rx_gain_rf_target_db"]["confidence"] == "unverified") == (b in RF_CONF_UNVERIFIED)
        assert e["if_band_max_mhz"]["value"] == IF_MAX[b], (fid, b)
        assert e["if_band_frac_complex1x"]["value"] == 0.9
        assert e["if_band_frac_complex2x"]["value"] == e["if_band_frac_real"]["value"] == 0.45


def test_summary_carries_analog_per_board_and_limits_dict_exposes_gain_range():
    for b in CHIPS:
        for f in fwmod.summary(b):
            assert set(KEYS) <= set(f["analog"]), (b, f["id"])
    ld = limmod.limits_dict()
    for b, (lo, hi) in GAIN.items():
        assert (ld[b]["rx_gain_min_db"]["value"], ld[b]["rx_gain_max_db"]["value"], ld[b]["rx_gain_step_db"]["value"]) == (lo, hi, 2)
    r = analog.gain_range(limmod.BOARD_LIMITS["IWR6843"])
    assert (r["min"], r["max"], r["step"]) == (30, 48, 2)


def test_descriptor_schema_rejects_bad_analog_values():
    d = json.loads((CONFIG / "firmware" / "demo.json").read_text())
    d["limits"]["IWR1843"]["hpf1_corner_khz"]["value"] = [700, 175]
    d["limits"]["IWR1843"]["rx_gain_min_db"]["value"] = 60
    d["limits"]["IWR1843"]["rx_gain_rf_target_db"]["value"] = [30, 34]
    bad = fwmod.check_descriptor(d, "demo")
    assert any("hpf1_corner_khz" in m for m in bad) and any("rx_gain_min_db > rx_gain_max_db" in m for m in bad)
    assert any("rx_gain_rf_target_db" in m for m in bad)


# ---- the rxGain word ---------------------------------------------------------------------------------------------------
def test_gain_word_split_and_range_check_looks_at_bits_5_0_only():
    assert analog.split_gain_word(158) == (30, 2, 0)       # 0x9E: shipped IWR6843 cfgs
    assert analog.split_gain_word(0x5E) == (30, 1, 0)      # Studio json
    lim = limmod.BOARD_LIMITS["IWR6843"]
    assert analog.gain_issues(158, lim) == []              # a naive 30..48 check on 158 would fail; bits 5:0 = 30 do not
    assert [c for c, *_ in analog.gain_issues(28, lim)] == ["rx_gain"]          # below the 6843 minimum
    assert [c for c, *_ in analog.gain_issues(31, lim)] == ["rx_gain"]          # odd
    assert [c for c, *_ in analog.gain_issues(50, limmod.BOARD_LIMITS["IWR1843"])] == ["rx_gain"]
    assert [c for c, *_ in analog.gain_issues(2 << 6 | 30, limmod.BOARD_LIMITS["IWR1843"])] == ["rx_gain_target"]   # reserved on xWR1xxx


def test_awr2243_rf_target_is_unverified_and_never_flagged():
    lim = limmod.BOARD_LIMITS["AWR2243_CASCADE"]
    assert lim["rx_gain_rf_target_db"].confidence == "unverified"
    assert not analog.trusted(lim, "rx_gain_rf_target_db")
    assert analog.gain_issues(3 << 6 | 40, lim) == []


def _cfg_with(text_cfg: str, hpf1=None, hpf2=None, gain=None) -> str:
    out = []
    for ln in text_cfg.splitlines():
        t = ln.split()
        if t and t[0] == "profileCfg":
            if hpf1 is not None:
                t[12] = str(hpf1)
            if hpf2 is not None:
                t[13] = str(hpf2)
            if gain is not None:
                t[14] = str(gain)
            ln = " ".join(t)
        out.append(ln)
    return "\n".join(out) + "\n"


def test_validate_reports_but_never_rewrites_out_of_range_codes():
    base = (CONFIG / "radar" / "IWR1843" / "demo" / "RadVel_10Hz.cfg").read_text()
    codes = lambda txt, fw=None: {i.code for i in validate(parse_cfg(txt), "IWR1843", fw).warnings}
    assert not codes(base) & {"rx_gain", "hpf_code", "rx_gain_target"}
    assert "hpf_code" in codes(_cfg_with(base, hpf1=5))
    assert "rx_gain" in codes(_cfg_with(base, gain=60))
    odd = _cfg_with(base, hpf2=9, gain=60)
    assert apply_params(odd, params_from_cfg(parse_cfg(odd), "IWR1843")) == odd      # preserved byte for byte
    # editing HPF1 only: the full rxGain word (158 here, bits 7:6 set) is untouched
    w = _cfg_with(base, gain=158)
    out = apply_params(w, {"profiles": [{"hpf1": 2}]})
    pc = next(ln.split() for ln in out.splitlines() if ln.startswith("profileCfg"))
    assert pc[12] == "2" and pc[14] == "158"


# ---- params round trip over every cfg in config/ and config/user/ (read-only) ---------------------------------------------
def _round_trip_files():
    shipped = sorted((CONFIG / "radar").rglob("*.cfg"))
    user_dir = CONFIG / "user"
    user = sorted(user_dir.glob("*.cfg")) if user_dir.is_dir() else []
    return shipped, user


def test_params_round_trip_leaves_every_shipped_and_user_cfg_identical():
    shipped, user = _round_trip_files()
    covered, skipped = [], []
    for p in shipped + user:
        text = p.read_text()                       # read only
        try:
            params = params_from_cfg(parse_cfg(text))
        except CfgError:
            skipped.append(p.name)                 # not a complete profile cfg (e.g. fragments); counted, not hidden
            continue
        out = apply_params(text, params)
        assert out.rstrip("\n").splitlines() == text.rstrip("\n").splitlines(), p
        covered.append(p.relative_to(CONFIG).as_posix())
    assert len(covered) >= 20, (len(covered), skipped)
    assert len(skipped) < len(covered)
    print(f"round-trip covered {len(covered)} cfgs, skipped {len(skipped)}")
    sar = CONFIG / "user" / "SAR_ugv_fmt2.cfg"
    if sar.is_file():
        assert "user/SAR_ugv_fmt2.cfg" in covered


# ---- Raw ADC band edges --------------------------------------------------------------------------------------------------
def test_band_edges_derive_from_limits_data_sar_example():
    lim = limmod.firmware_limits("IWR1843", "iwr1843_sar_lvds")
    b = analog.band_edges(lim, 0, 1, 2000.0, 1.95)             # SAR_ugv_fmt2: complex 1x, 2 Msps, slope 1.95 MHz/us
    assert b["hpf_khz"] == 175 and b["hpf_m"] == pytest.approx(13.45, abs=0.02)
    assert b["if_mhz"] == pytest.approx(1.8) and b["if_m"] == pytest.approx(138.4, abs=0.1)
    # the edge follows the data: a different max IF below 0.9 fs, a different fraction, a different HPF code
    from dataclasses import replace
    lim2 = dict(lim, if_band_max_mhz=replace(lim["if_band_max_mhz"], value=1.0))
    assert analog.band_edges(lim2, 0, 1, 2000.0, 1.95)["if_mhz"] == pytest.approx(1.0)
    assert analog.band_edges(lim, 1, 1, 2000.0, 1.95)["hpf_khz"] == 235
    assert analog.band_edges(lim, 0, 2, 2000.0, 1.95)["if_mhz"] == pytest.approx(0.9)    # complex 2x: 0.45 fs
    assert analog.band_edges(lim, 0, 0, 2000.0, 1.95)["if_mhz"] == pytest.approx(0.9)    # real: 0.45 fs


def test_unverified_or_unknown_data_gives_no_edges():
    lim = limmod.firmware_limits("IWR1843", "iwr1843_sar_lvds")
    from dataclasses import replace
    weak = {k: replace(v, confidence="unverified") if k in ("hpf1_corner_khz", "if_band_frac_complex1x") else v for k, v in lim.items()}
    b = analog.band_edges(weak, 0, 1, 2000.0, 1.95)
    assert b["hpf_m"] is None and b["if_m"] is None
    assert analog.band_edges(None, 0, 1, 2000.0, 1.95)["if_m"] is None
    assert analog.band_edges(lim, 7, 1, 2000.0, 1.95)["hpf_m"] is None     # out-of-table code: not shaded


def test_geometry_puts_bands_in_the_frame_header():
    from radar_gui import adc
    sar = CONFIG / "user" / "SAR_ugv_fmt2.cfg"
    cfg_path = sar if sar.is_file() else None
    if cfg_path is None:
        pytest.skip("config/user/SAR_ugv_fmt2.cfg not present")
    g = adc.Geometry.from_cfg(parse_cfg(cfg_path.read_text()), "IWR1843", "iwr1843_sar_lvds")
    assert g.bands["hpf_m"] == pytest.approx(13.45, abs=0.02) and g.bands["if_m"] == pytest.approx(138.4, abs=0.1)


# ---- static checks on the JS ---------------------------------------------------------------------------------------------
def test_no_corner_tables_or_if_fractions_in_js():
    pat = re.compile(r"(?<![\w.])(175|235|1400|2800)(?![\w.])")
    for f in ("cfg.js", "adc.js"):
        src = re.sub(r"//.*", "", (WEBJS / f).read_text())
        assert not pat.findall(src), (f, pat.findall(src))
    adc_src = re.sub(r"//.*", "", (WEBJS / "adc.js").read_text())
    assert not re.search(r"(?<![\w.])0\.9(?![\w])", adc_src)           # the IF band fraction comes from the data
    assert "bands" in adc_src and "if_m" in adc_src and "hpf_m" in adc_src   # ...via the frame header edges
