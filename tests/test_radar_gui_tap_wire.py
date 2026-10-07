"""Cross-check of the C++ live-tap encoder (gui-36 Step 1) against the Python reader.

`CPSL_TI_Radar_cpp/tests/data/live_tap_golden.bin` is the byte stream test_live_tap.cpp asserts the C++
encoder produces (hello, points with NaN -> null, adc); here `radar_gui/tap.py` parses the same file.
"""
import os
from pathlib import Path

import pytest

from radar_gui import tap

GOLDEN = Path(__file__).resolve().parents[1] / "CPSL_TI_Radar_cpp" / "tests" / "data" / "live_tap_golden.bin"


def _messages():
    r, w = os.pipe()
    os.write(w, GOLDEN.read_bytes())
    os.close(w)
    out = []
    try:
        while True:
            try:
                out.append(tap.read_message(r))
            except tap.TapClosed:
                break
    finally:
        os.close(r)
    return out


def test_golden_stream_parses_with_the_python_reader():
    msgs = _messages()
    assert [t for t, _ in msgs] == [tap.HELLO, tap.POINTS, tap.ADC]
    hello = tap.decode_json(msgs[0][1])
    assert hello == {"version": 1, "board": "IWR1843", "streams": ["points", "adc"], "adc_every": 3}

    pts = tap.decode_json(msgs[1][1])
    assert pts["type"] == "frame" and pts["frame"] == 7 and pts["n"] == 2 and pts["t"] == 1700000000.25
    assert pts["pts"] == [[1.5, 2.25, 0, -0.5, 20, 5], [None, 1, -1.25, 0.1, None, 0]]

    head, data = tap.decode_adc(msgs[2][1])
    assert head == {"index": 6, "shape": [2, 3, 2], "missing_bytes": 16, "layout": "rx,sample,chirp",
                    "iq_order": "IQ"}
    assert len(data) == 2 * 3 * 2 * 4
    np = pytest.importorskip("numpy")
    iq = np.frombuffer(data, dtype="<i2").reshape(2, 3, 2, 2)   # [rx][sample][chirp][I,Q]
    assert iq[1, 2, 1].tolist() == [121, -122]
    assert iq[0, 1, 0].tolist() == [10, -11]
