"""gui-07 Step 1: radar_gui/adc.py against a closed-form synthetic cube (tests/fakes/synth_cube.py, independent of the
code under test). Bench shape = bench_1843_dca.cfg: 4 rx x 128 samples x 256 chirps (2 TX slots x 128 loops)."""
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent / "fakes"))
import synth_cube as sc  # noqa: E402

from radar_gui import adc  # noqa: E402
from radar_gui.cfg.parse import parse_cfg  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "adc"
CFG_TEXT = (FIX / "bench_1843_dca.cfg").read_text()


@pytest.fixture(scope="module")
def geom():
    return adc.Geometry.from_system_json(FIX / "bench_1843_dca.json")


def run(geom, x, **opts):
    head, data = sc.wire(x)
    a, _ = adc.decode(head, data, geom)
    return adc.process(a, geom, opts)


def test_geometry_from_bench_cfg(geom):
    assert geom.shape == (4, 128, 256) and geom.cpl == 2 and geom.n_loops == 128
    assert geom.az_slots == [0, 1] and geom.ra_enabled
    assert geom.doppler_bins == 128
    assert geom.range_res_m == pytest.approx(0.0868, abs=1e-3)       # c / (2 B), B = 26.981 MHz/us * 64 us


def test_exact_bins_range_doppler_angle(geom):
    x = sc.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.0}])
    r = run(geom, x)
    assert r.header["profile_peak_bin"] == 34
    assert r.header["rd"]["peak"] == [64 + 10, 34]                  # + = receding, zero at D/2
    assert r.header["ra"]["peak"] == [32, 34]                       # theta = 0
    assert r.header["range_step_m"] == pytest.approx(geom.range_res_m)


def test_negative_doppler_bin(geom):
    r = run(geom, sc.cube(targets=[{"kr": 20, "kd": -7}]))
    assert r.header["rd"]["peak"] == [64 - 7, 20]


@pytest.mark.parametrize("deg", [20.0, -20.0, 0.0])
def test_angle_bins(geom, deg):
    s = math.sin(math.radians(deg))
    r = run(geom, sc.cube(targets=[{"kr": 50, "sin": s}]))
    assert r.header["ra"]["peak"] == [round(32 + 32 * s), 50]
    # +theta is toward +x: the bin index grows with sin(theta)
    assert r.header["ra"]["sin_zero_bin"] == 32


def test_iq_swap_moves_peak_and_flips_image_ratio(geom):
    x = sc.cube(targets=[{"kr": 34}])
    good = run(geom, x)
    head, data = sc.wire(x, swap_iq=True)
    bad = adc.process(adc.decode(head, data, geom)[0], geom)
    assert good.header["profile_peak_bin"] == 34 and bad.header["profile_peak_bin"] == 128 - 34
    assert good.header["image_ratio_db"] > 40 and bad.header["image_ratio_db"] < -40


def test_diagnostics_bits_and_clipping(geom):
    a = np.zeros((4, 128, 256, 2), "<i2")
    a[..., 0] = 1000
    a[..., 1] = -300
    d = adc.diagnostics(a)
    assert all(r["bits"] == math.ceil(math.log2(1001)) + 1 == 11 for r in d["rows"])
    assert all(r["clipped"] == 0 and r["peak_i"] == 1000 and r["peak_q"] == 300 for r in d["rows"])
    assert d["rows"][0]["dc_i"] == 1000 and d["rows"][0]["dc_q"] == -300
    assert d["rows"][0]["iq_ratio_db"] == pytest.approx(20 * math.log10(1000 / 300))
    assert d["rows"][0]["rms_dbfs"] == pytest.approx(20 * math.log10(math.sqrt((1000 ** 2 + 300 ** 2) / 2) / 32768))
    a[1, :7, 0, 0] = 32767
    a[1, :3, 1, 1] = -32768
    d = adc.diagnostics(a)
    assert [r["clipped"] for r in d["rows"]] == [0, 10, 0, 0]
    assert d["rows"][1]["bits"] == 16
    assert d["bars"][0][0] == 1.0 and d["bars"][0][10] == 0.0 and d["bars"][0][9] == 0.5   # |I|=1000 in [512,1024)
    assert d["series"].shape == (4, 2, 128) and d["series"][0, 0, 0] == 1000


def test_bad_frames_are_rejected(geom):
    x = sc.cube(targets=[{"kr": 34}])
    head, data = sc.wire(x)
    with pytest.raises(adc.AdcError, match="payload"):
        adc.decode(head, data[:-4], geom)
    with pytest.raises(adc.AdcError, match="layout"):
        adc.decode({**head, "layout": "chirp,rx,sample"}, data, geom)
    with pytest.raises(adc.AdcError, match="iq_order"):
        adc.decode({**head, "iq_order": "QI"}, data, geom)
    h2, d2 = sc.wire(sc.cube(n_samples=64, n_loops=128))
    with pytest.raises(adc.AdcError, match=r"\[4, 64, 256\].*\[4, 128, 256\]"):
        adc.decode(h2, d2, geom)
    got = []
    p = adc.AdcProcessor(geom, got.append)
    assert p.process_one(h2, d2) is None and p.rejected == 1 and "differs" in p.last_error
    assert p.process_one(head, data) is not None and p.adc_shown == 1 and p.last_error == ""


def test_missing_bytes_is_partial_but_processed(geom):
    head, data = sc.wire(sc.cube(targets=[{"kr": 34}]), missing=64)
    p = adc.AdcProcessor(geom)
    msg = p.process_one(head, data)
    hl = struct.unpack_from("<I", msg)[0]
    h = json.loads(msg[4:4 + hl])
    assert h["partial"] is True and h["missing_bytes"] == 64 and h["profile_peak_bin"] == 34


def test_ra_disabled_cases():
    def g(text, board="IWR1843"):
        return adc.Geometry.from_cfg(parse_cfg(text), board)
    assert g(CFG_TEXT + "bpmCfg -1 1 0 1\n").ra_enabled is False
    assert "BPM" in g(CFG_TEXT + "bpmCfg -1 1 0 1\n").ra_reason
    ods = g(CFG_TEXT, "IWR6843ODS")
    assert not ods.ra_enabled and "ODS" in ods.ra_reason
    one = g(CFG_TEXT.replace("channelCfg 15 5 0", "channelCfg 1 1 0").replace("chirpCfg 1 1 0 0 0 0 0 4", "chirpCfg 1 1 0 0 0 0 0 1"))
    assert one.az_slots == [0, 1] and one.n_rx == 1 and one.ra_enabled          # 2 slots x 1 RX = 2 channels
    one.az_slots = [0]
    assert (len(one.az_slots) * one.n_rx) == 1
    # a single TX with one RX has 1 azimuth channel: disabled
    solo = g(CFG_TEXT.replace("channelCfg 15 5 0", "channelCfg 1 1 0").replace("chirpCfg 1 1 0 0 0 0 0 4", "chirpCfg 1 1 0 0 0 0 0 1")
             .replace("chirpCfg 0 0 0 0 0 0 0 1", "chirpCfg 0 0 0 0 0 0 0 1").replace("frameCfg 0 1 128", "frameCfg 0 0 128"))
    assert not solo.ra_enabled and "2 azimuth" in solo.ra_reason
    r = adc.process(np.zeros((1, 128, 128, 2), "<i2"), solo)
    assert r.header["ra"] is None and r.header["ra_reason"] == solo.ra_reason and "rd" in r.header


def test_maxpool_keeps_the_peak():
    a = np.zeros((3, 1000), np.float32)
    a[1, 777] = 5.0
    p, f = adc.maxpool(a, 1, 256)
    assert p.shape[1] <= 256 and f == 4 and p.max() == 5.0 and p[1].argmax() == 777 // 4
    q, f1 = adc.maxpool(a, 1, 1000)
    assert f1 == 1 and q is a


def test_clutter_removal_drops_static_target(geom):
    x = sc.cube(targets=[{"kr": 34, "kd": 0, "amp": 4000}, {"kr": 60, "kd": 12, "amp": 1000}])
    assert run(geom, x).header["profile_peak_bin"] == 34
    r = run(geom, x, clutter=True)
    assert r.header["profile_peak_bin"] == 60


def test_message_roundtrip_and_size(geom):
    p = adc.AdcProcessor(geom)
    head, data = sc.wire(sc.cube(targets=[{"kr": 34, "kd": 3, "sin": 0.3}], noise=20))
    msg = p.process_one(head, data)
    hl = struct.unpack_from("<I", msg)[0]
    h = json.loads(msg[4:4 + hl])
    body = msg[4 + hl:]
    arrs = {a["name"]: a for a in h["arrays"]}
    assert set(arrs) == {"profile", "rd", "ra", "series"}
    assert arrs["rd"]["shape"] == [128, 128] and arrs["ra"]["shape"] == [64, 128] and arrs["series"]["shape"] == [4, 2, 128]
    assert sum(a["bytes"] for a in h["arrays"]) == len(body)
    assert len(msg) < 200_000
    prof = np.frombuffer(body, "<f4", count=128, offset=arrs["profile"]["offset"])
    assert int(prof.argmax()) == 34
    rd = np.frombuffer(body, np.uint8, count=128 * 128, offset=arrs["rd"]["offset"]).reshape(128, 128)
    assert rd.max() == 255 and np.unravel_index(rd.argmax(), rd.shape) == (67, 34)
    assert h["index"] == 0 and h["adc_shown"] == 1 and h["diag"]["rows"][0]["rx"] == 0


def test_processor_newest_wins_never_blocks(geom):
    got = []
    p = adc.AdcProcessor(geom, got.append)
    head, data = sc.wire(sc.cube(targets=[{"kr": 34}]))
    t0 = time.perf_counter()
    for i in range(40):
        p.submit({**head, "index": i}, data)
    assert time.perf_counter() - t0 < 0.05        # submit never waits for processing
    p.start()
    end = time.time() + 10
    while p.adc_shown + p.dropped_gui < 40 and time.time() < end:
        time.sleep(0.02)
    p.stop()
    assert p.adc_in == 40 and p.adc_shown + p.dropped_gui == 40 and p.dropped_gui >= 30
    assert json.loads(got[-1][4:4 + struct.unpack_from("<I", got[-1])[0]])["index"] == 39


def test_options_rerender_last_frame(geom):
    got = []
    p = adc.AdcProcessor(geom, got.append)
    head, data = sc.wire(sc.cube(targets=[{"kr": 34}, {"kr": 60, "kd": 12, "amp": 1000}]))
    p.start()
    p.submit(head, data)
    end = time.time() + 10
    while len(got) < 1 and time.time() < end:
        time.sleep(0.02)
    p.set_options(clutter=True, chirp=5)
    while len(got) < 2 and time.time() < end:
        time.sleep(0.02)
    p.stop()
    h = json.loads(got[1][4:4 + struct.unpack_from("<I", got[1])[0]])
    assert h["profile_peak_bin"] == 60 and h["diag"]["chirp"] == 5


def test_timing_bench_shape(geom, record_property):
    """Median processing time for the bench 4x128x256 cube. Default: gross-regression guard (< 250 ms), tolerant of host
    load (idle ~35-39 ms, loaded 54-145 ms). The gui-07 Verify bar (< 50 ms) is opt-in on an idle host:
    `RADAR_GUI_PERF=1 uv run pytest tests/test_radar_gui_adc.py -k timing_bench -q`. Median is always recorded."""
    x = sc.cube(targets=[{"kr": 34, "kd": 10, "sin": 0.3}], noise=30)
    head, data = sc.wire(x)
    p = adc.AdcProcessor(geom)
    for _ in range(3):
        p.process_one(head, data)              # warm-up (FFT plans, allocations)
    p.proc_ms.clear()
    for _ in range(30):
        assert p.process_one(head, data) is not None
    med = p.median_ms()
    print(f"\nadc proc_ms median {med:.2f} ms (4x128x256, bench_1843_dca)")
    record_property("proc_ms_median", med)
    strict = os.environ.get("RADAR_GUI_PERF") == "1"
    assert med < (50 if strict else 250)


def _real_frames():
    raw = np.fromfile(FIX / "iwr1843_bench_dca_2frames.bin", "<i2")
    per = 256 * 4 * 128 * 2
    assert raw.size == 2 * per
    for f in range(2):   # file order: chirp, rx, sample, (I, Q) -> tap layout [rx][sample][chirp]
        a = raw[f * per:(f + 1) * per].reshape(256, 4, 128, 2).transpose(1, 2, 0, 3)
        yield f, np.ascontiguousarray(a).astype("<i2")


def test_real_bench_frames_run_end_to_end(geom, capsys):
    for f, a in _real_frames():
        head = {"index": f, "shape": [4, 128, 256], "missing_bytes": 0, "layout": "rx,sample,chirp", "iq_order": "IQ"}
        p = adc.AdcProcessor(geom)
        msg = p.process_one(head, a.tobytes())
        assert msg is not None and p.rejected == 0
        hl = struct.unpack_from("<I", msg)[0]
        h = json.loads(msg[4:4 + hl])
        body = msg[4 + hl:]
        arrs = {x["name"]: x for x in h["arrays"]}
        assert arrs["rd"]["shape"] == [128, 128] and arrs["ra"]["shape"] == [64, 128] and arrs["series"]["shape"] == [4, 2, 128]
        assert np.isfinite(np.frombuffer(body, "<f4", count=128, offset=arrs["profile"]["offset"])).all()
        assert h["ra"] is not None and np.isfinite(h["image_ratio_db"])
        rows = h["diag"]["rows"]
        assert len(rows) == 4 and all(r["clipped"] == 0 and r["bits"] < 16 for r in rows)
        print(f"real frame {f}: peak bin {h['profile_peak_bin']} image {h['image_ratio_db']:.1f} dB; "
              f"bits {[r['bits'] for r in rows]} clipped {[r['clipped'] for r in rows]} "
              f"rms_dbfs {[round(r['rms_dbfs'], 1) for r in rows]}")
