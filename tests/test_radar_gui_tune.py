"""The RX-gain sweep core (radar_gui/tune.py) on synthetic data; no driver, no hardware."""
import copy
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fakes"))
import synth_cube  # noqa: E402

from radar_gui import adc, tune  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "adc"
RNG = {"min": 24, "max": 48, "step": 2}
BASE = (FIX / "bench_1843_dca.cfg").read_text()


@pytest.fixture(scope="module")
def geom():
    return adc.Geometry.from_system_json(FIX / "bench_1843_dca.json")


def row(g, peak_db, noise_db=26.0, sat=0, clipped=0, headroom=30.0):
    return {"gain_db": g, "peak_db": peak_db, "noise_db": noise_db, "snr_db": peak_db - noise_db, "sat_chirps": sat,
            "chirps": 100, "clipped": clipped, "headroom_db": headroom, "adc_peak": 100, "peak_dbfs": -40.0, "bits": 8,
            "frames": 8, "peak_range_m": 3.0, "dc_db": 20.0}


def linear(gains, comp_above=None, slope_after=0.3, p0=50.0, sat_from=None):
    out = []
    for g in gains:
        eff = g if comp_above is None or g <= comp_above else comp_above + (g - comp_above) * slope_after
        out.append(row(g, p0 + (eff - gains[0]), sat=12 if sat_from is not None and g >= sat_from else 0))
    return out


# ---- cfg edit ------------------------------------------------------------------------------------------------
def test_set_rx_gain_changes_only_the_gain_bits():
    text = "sensorStop\r\nprofileCfg 0 77 87.04 7 73 0 0 26.981 1 128 2000 0 0 94 % rf target 1\r\nchirpCfg 0 0 0 0 0 0 0 1\r\n"
    out = tune.set_rx_gain(text, 40)
    assert out.split("\r\n")[1] == "profileCfg 0 77 87.04 7 73 0 0 26.981 1 128 2000 0 0 104 % rf target 1"   # 94 = 30 + 64 -> 40 + 64
    assert out.split("\r\n")[0] == "sensorStop" and out.split("\r\n")[2] == text.split("\r\n")[2]
    assert tune.read_rx_gain(text) == 94 and tune.read_rx_gain(out) == 104
    assert tune.set_rx_gain(BASE, 30) == BASE            # an unchanged gain is byte-identical


def test_set_rx_gain_rejects_bad_input():
    with pytest.raises(tune.TuneError):
        tune.set_rx_gain("sensorStop\n", 30)
    with pytest.raises(tune.TuneError):
        tune.set_rx_gain(BASE, 64)
    with pytest.raises(tune.TuneError):
        tune.read_rx_gain("profileCfg 0 77 87.04 7 73 0 0 26.981 1 128 2000 0 0\n")


def test_gain_grid_validation():
    assert tune.gain_grid(24, 32, 2, RNG) == [24, 26, 28, 30, 32]
    for bad in [(25, 32, 2), (24, 33, 2), (22, 32, 2), (24, 50, 2), (30, 24, 2), (24, 32, 3), (24, 32, 0), (24.5, 32, 2)]:
        with pytest.raises(tune.TuneError):
            tune.gain_grid(*bad, RNG)
    assert len(tune.gain_grid(0, 63, 1, None)) == 64      # 64 steps is the cap
    with pytest.raises(tune.TuneError, match="at most 64"):
        tune.gain_grid(0, 70, 1, {"min": 0, "max": 200, "step": 1})


# ---- suggestion rule on synthetic rows ----------------------------------------------------------------------
def test_linear_then_compressing():
    rows = linear(list(range(24, 50, 2)), comp_above=40)
    s = tune.suggest(rows, RNG, margin_db=3)
    assert s["max_ok_gain"] == 40 and s["limited_by"] == "compression" and s["compression_observed"]
    assert s["suggested_gain"] == 36                      # 40 - 3 = 37 -> floored to the 2 dB grid
    assert [r["status"] for r in rows if r["gain_db"] == 42] == ["compressed"]
    assert all(r["status"] == "after_limit" for r in rows if r["gain_db"] > 42)


def test_saturation_onset_stops_the_run_even_if_power_still_tracks():
    rows = linear(list(range(24, 50, 2)), sat_from=44)
    s = tune.suggest(rows, RNG, margin_db=3)
    assert s["limited_by"] == "saturation" and s["saturation_observed"] and not s["compression_observed"]
    assert s["max_ok_gain"] == 42 and s["suggested_gain"] == 38


def test_clipped_adc_samples_count_as_saturation_without_firmware_counter():
    rows = linear(list(range(24, 40, 2)))
    rows[-1]["sat_chirps"], rows[-1]["clipped"] = None, 5          # firmware without the per-chirp counter
    assert tune.suggest(rows, RNG)["max_ok_gain"] == 36


def test_all_saturated_is_none_with_reason():
    rows = linear(list(range(24, 40, 2)), sat_from=24)
    s = tune.suggest(rows, RNG)
    assert s["suggested_gain"] is None and "saturated at every swept gain" in s["none_reason"] and s["text"].startswith("No suggestion")


def test_noise_only_scene_is_none_not_a_gain():
    rows = [row(g, 26.0 + 3 + (g - 24), noise_db=26.0 + (g - 24)) for g in range(24, 40, 2)]   # peak 3 dB over the median at every gain
    s = tune.suggest(rows, RNG, min_snr_db=10)
    assert s["suggested_gain"] is None and "no return above the noise floor" in s["none_reason"]


def test_flat_response_that_never_tracks_gives_the_lowest_gain_minus_nothing_usable():
    rows = [row(g, 60.0) for g in range(24, 40, 2)]       # power flat in gain: only the anchor is ok, the next step compresses
    s = tune.suggest(rows, RNG, margin_db=3)
    assert s["limited_by"] == "compression" and s["max_ok_gain"] == 24 and s["suggested_gain"] == 24   # clipped to the board minimum


def test_no_compression_to_the_top_says_so_with_headroom():
    rows = linear(list(range(24, 50, 2)))
    for r in rows:
        r["headroom_db"] = 40.0 - (r["gain_db"] - 24) * 0.5
    s = tune.suggest(rows, RNG, margin_db=3)
    assert s["limited_by"] == "sweep_top" and s["max_ok_gain"] == 48 and s["suggested_gain"] == 44
    assert "no compression observed up to 48 dB; headroom 28.0 dB" in s["text"]
    assert s["headroom_db"] == 28.0


def test_margin_is_clipped_to_the_board_minimum_and_step_grid():
    rows = linear([24, 26, 28], comp_above=24)
    assert tune.suggest(rows, RNG, margin_db=10)["suggested_gain"] == 24
    rows = linear(list(range(24, 36, 2)))
    assert tune.suggest(rows, RNG, margin_db=0.5)["suggested_gain"] == 32     # 34 - 0.5 = 33.5 floors to the 2 dB grid
    assert tune.suggest(rows, None, margin_db=0.5)["suggested_gain"] == 33    # no limits known: whole dB


def test_rule_is_deterministic_on_stored_rows():
    rows = linear(list(range(24, 50, 2)), comp_above=38)
    a = tune.suggest(rows, RNG, margin_db=3)
    again = tune.suggest(copy.deepcopy(rows), RNG, margin_db=3)
    assert a["suggested_gain"] == again["suggested_gain"] == 34


# ---- metrics on synthetic cubes ----------------------------------------------------------------------------
def cap_of(x, n=2, **kw):
    return tune.Capture([synth_cube.to_int16(x)] * n, **kw)


def test_dc_dominated_profile_is_excluded_from_the_return(geom):
    x = synth_cube.cube(targets=[{"kr": 0, "kd": 0, "sin": 0.0, "amp": 900.0}, {"kr": 34, "kd": 10, "sin": 0.3, "amp": 60.0}],
                        noise=2.0)
    m = tune.step_metrics(30, cap_of(x), geom, tune.exclusion_m(geom))
    assert m["dc_db"] > m["peak_db"] + 15                 # the leakage bin is far stronger ...
    assert m["peak_range_m"] == pytest.approx(34 * geom.range_res_m, abs=0.2)    # ... and the return is the target
    assert m["snr_db"] > 20
    whole = tune.step_metrics(30, cap_of(x), geom, 0.0)   # exclusion 0: the DC bin wins (what the console follow-up saw)
    assert whole["peak_range_m"] < 0.2


def test_step_metrics_power_and_headroom_follow_amplitude(geom):
    def at(amp):
        x = synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3, "amp": amp}], noise=2.0)
        return tune.step_metrics(30, cap_of(x), geom, tune.exclusion_m(geom))
    a, b = at(50.0), at(100.0)
    assert b["peak_db"] - a["peak_db"] == pytest.approx(6.02, abs=0.2)
    assert a["headroom_db"] - b["headroom_db"] == pytest.approx(6.02, abs=1.0)    # a peak SAMPLE: noise makes it only roughly linear
    assert a["clipped"] == 0 and a["bits"] < b["bits"] + 1


def test_rail_samples_are_clipped_at_the_adc_full_scale(geom):
    x = synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3, "amp": 3000.0}], noise=2.0)     # beyond a 12-bit rail (2047)
    m12 = tune.step_metrics(30, cap_of(x), geom, 0.4, adc_bits=12)
    m16 = tune.step_metrics(30, cap_of(x), geom, 0.4, adc_bits=16)
    assert m12["clipped"] > 0 and m16["clipped"] == 0
    assert m12["headroom_db"] < 0 < m16["headroom_db"]


# ---- the sweep driver loop -----------------------------------------------------------------------------------
def test_run_sweep_uses_copies_and_reports_progress(geom):
    seen, prog = [], []

    def capture(g, text, n):
        seen.append((g, tune.read_rx_gain(text), n))
        amp = 20.0 * 10 ** ((g - 30) / 20)
        return cap_of(synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3, "amp": amp}], noise=2.0), n, sat_chirps=0, chirps=10)
    base_before = BASE
    res = tune.run_sweep(BASE, [24, 26, 28], 2, capture, geom, rng=RNG, progress=prog.append)
    assert seen == [(24, 24, 2), (26, 26, 2), (28, 28, 2)] and BASE == base_before
    assert [r["gain_db"] for r in res["rows"]] == [24, 26, 28] and res["suggestion"]["suggested_gain"] == 24
    assert res["params"]["frames"] == 2 and prog[-1]["phase"] == "done"


def test_run_sweep_cancel_returns_rows_so_far_and_no_suggestion(geom):
    flag = {"n": 0}

    def capture(g, text, n):
        flag["n"] += 1
        return cap_of(synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3, "amp": 40.0}], noise=2.0), n)
    res = tune.run_sweep(BASE, [24, 26, 28], 1, capture, geom, rng=RNG, cancelled=lambda: flag["n"] >= 2)
    assert res["cancelled"] and len(res["rows"]) == 2 and res["suggestion"] is None


# ---- ADC full scale from adcCfg ----------------------------------------------------------
def test_adc_bits_derived_from_adccfg():
    assert tune.adc_bits_from_cfg("adcCfg 2 1\n") == (16, "adcCfg numADCBits 2")
    assert tune.adc_bits_from_cfg("adcCfg 0 1 % x\n")[0] == 12 and tune.adc_bits_from_cfg("adcCfg 1 1\n")[0] == 14
    b, why = tune.adc_bits_from_cfg("sensorStop\n")
    assert b == 16 and "no usable adcCfg" in why


def test_16bit_cfg_does_not_flag_1481_or_2500_counts(geom):
    for amp in (1481.0, 2500.0):
        x = synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3, "amp": amp}], noise=2.0)
        m = tune.step_metrics(30, cap_of(x), geom, 0.4, adc_bits=tune.adc_bits_from_cfg(BASE)[0])
        assert m["clipped"] == 0 and m["headroom_db"] > 15, (amp, m)


def test_12bit_rail_is_2047(geom):
    a = np.zeros((4, 128, 256, 2), np.int16)
    a[0, 0, 0, 0] = 2046
    m = tune.step_metrics(30, tune.Capture([a]), geom, 0.4, adc_bits=12)
    assert m["clipped"] == 0
    a[0, 0, 0, 0] = 2047
    assert tune.step_metrics(30, tune.Capture([a]), geom, 0.4, adc_bits=12)["clipped"] == 1


def test_run_sweep_derives_bits_unless_overridden(geom):
    def capture(g, text, n):
        return cap_of(synth_cube.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3, "amp": 40.0}], noise=2.0), n)
    r = tune.run_sweep(BASE, [24], 1, capture, geom, rng=RNG)
    assert r["params"]["adc_bits"] == 16 and r["params"]["adc_bits_source"] == "adcCfg numADCBits 2"
    r = tune.run_sweep(BASE, [24], 1, capture, geom, rng=RNG, adc_bits=12)
    assert r["params"]["adc_bits"] == 12 and r["params"]["adc_bits_source"] == "override"
