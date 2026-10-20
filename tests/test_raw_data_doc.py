"""docs/raw_data/decode_example.py decodes the tracked IWR1843 frame as the docs describe.

Doc-only decoder (no repo converter code). The golden frame's expectations (range peak in bins 9..12,
mirror >= 15 dB down, I/Q flip moves the peak) come from CPSL_TI_Radar_cpp/tests/data/iq/README.md.
The SAR case (bit-exact against adc_data.bin) needs a gitignored local capture and skips if absent.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "docs" / "raw_data"))
import decode_example as d  # noqa: E402

FRAME = ROOT / "CPSL_TI_Radar_cpp/tests/data/iq/iwr1843_R0.9m_frame99.bin"
SAR_RUN = ROOT / "runs/gui/20261016T191733Z_SAR_ugv_fmt2"
R, NS, NC = 4, 128, 256


def _frame_bytes():
    if not FRAME.exists() or FRAME.stat().st_size != 4 * R * NS * NC:
        pytest.skip("golden frame absent or an LFS pointer (git lfs pull)")
    return FRAME.read_bytes()


def _peak_and_mirror_db(cube):
    mag = np.abs(np.fft.fft(cube[0], axis=0)).mean(axis=1)  # rx0, chirp-averaged, over samples
    k = int(np.argmax(mag[1:NS // 2])) + 1
    return k, 20 * np.log10(mag[k] / mag[NS - k])


def test_demo_frame_shape_and_range():
    arr = d.decode_demo_frame(_frame_bytes(), R, NS, NC)
    assert arr.shape == (NC, R, NS, 2)
    assert d.to_cube(arr).shape == (R, NS, NC)
    assert abs(int(arr.min())) < 2048 and abs(int(arr.max())) < 2048  # 12-bit values (README section 3)


def test_demo_frame_range_peak_matches_golden_expectation():
    cube = d.to_cube(d.decode_demo_frame(_frame_bytes(), R, NS, NC))
    k, db = _peak_and_mirror_db(cube)
    assert 9 <= k <= 12
    assert db >= 15


def test_demo_frame_iq_swap_loses_the_peak():
    arr = d.decode_payload(_frame_bytes(), R, NS, NC, q_first=False)
    k, db = _peak_and_mirror_db(d.to_cube(arr))
    assert db < 15 or not 9 <= k <= 12


def test_sar_capture_bit_exact_against_adc_data():
    raw, ref = SAR_RUN / "LVDS_Raw_0.bin", SAR_RUN / "adc_data.bin"
    if not (raw.exists() and ref.exists()):
        pytest.skip("local SAR capture absent")
    arr, _ = d.decode_sar(raw.read_bytes(), 1, 3980, 0)
    expect = np.fromfile(ref, dtype="<i2")
    assert np.array_equal(arr.reshape(-1)[:expect.size], expect)


def test_decoder_equals_cube_golden_used_by_cpp_test():
    """The golden the C++ ctest test_iq_cube_bitexact compares ADCCubeConverter against is this decoder's output."""
    gold = ROOT / "CPSL_TI_Radar_cpp/tests/data/iq/iwr1843_R0.9m_frame99.cube_int16.bin"
    arr = d.decode_demo_frame(_frame_bytes(), R, NS, NC)  # [chirp][rx][sample][re, im]
    mine = np.ascontiguousarray(arr.transpose(1, 2, 0, 3)).astype("<i2").tobytes()  # [rx][sample][chirp][re, im]
    assert mine == gold.read_bytes()
