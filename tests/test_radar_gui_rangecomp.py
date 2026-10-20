"""Raw ADC range compensation is a display-only frontend transform.

No JS engine in the test environment, so the pure function in web/js/rangecomp.js is mirrored in Python with its constants
parsed out of the JS (a drift in the exponent table or the formula fails the static checks below), and the display-only
promise is checked statically: the backend never sees the mode, the JS never writes to the received arrays or header."""
import math
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "radar_gui" / "web"
SRC = (WEB / "js" / "rangecomp.js").read_text()
CODE = re.sub(r"//.*", "", SRC)

MODES = {k: float(v) for k, v in re.findall(r"\b(\w+):\s*(\d+)", re.search(r"COMP_MODES = \{([^}]*)\}", CODE).group(1))}


def range_comp(mode, r, rref, edge=None):
    """Python mirror of rangeComp()."""
    k = MODES.get(mode, 0.0)
    if not k or not (r > rref) or not (rref > 0):
        return 0.0
    if edge is not None and r > edge:
        return 0.0
    return k * math.log10(r / rref)


def range_ref(bands):
    h = bands["hpf_m"] if bands and (bands.get("hpf_m") or 0) > 0 else 0
    return max(1.0, h)


def test_js_constants_and_formula_match_the_mirror():
    assert MODES == {"off": 0.0, "r2": 20.0, "r4": 40.0}
    assert "k * Math.log10(r_m / rref_m)" in CODE
    assert "Math.max(1, h)" in CODE
    assert re.search(r"edge_m != null && r_m > edge_m\) return 0", CODE)
    assert re.search(r"!\(r_m > rref_m\)", CODE)


def test_off_is_identity_and_inside_rref_is_clamped():
    for r in (0.1, 0.5, 1.0, 5.0, 100.0):
        assert range_comp("off", r, 1.0) == 0.0
    for mode in ("r2", "r4"):
        assert range_comp(mode, 0.0, 1.0) == 0.0          # bin 0 / r = 0: clamped, not -inf
        assert range_comp(mode, 0.5, 1.0) == 0.0
        assert range_comp(mode, 1.0, 1.0) == 0.0
        assert range_comp(mode, 2.0, 13.45) == 0.0        # inside the HPF corner reference


def test_r4_flattens_a_one_over_r4_power_profile_and_r2_a_one_over_r2():
    rref = 1.0
    for mode, p in (("r4", 4), ("r2", 2)):
        rs = [1.0 + 0.5 * i for i in range(1, 60)]
        db = [-10.0 * p * math.log10(r / rref) + 3.0 for r in rs]
        comp = [d + range_comp(mode, r, rref) for d, r in zip(db, rs)]
        assert max(comp) - min(comp) < 1e-9 and comp[0] == pytest.approx(3.0)


def test_out_of_band_bins_are_untouched_and_ref_follows_hpf():
    assert range_comp("r4", 150.0, 1.0, edge=138.4) == 0.0
    assert range_comp("r4", 138.0, 1.0, edge=138.4) == pytest.approx(40 * math.log10(138.0))
    assert range_ref(None) == 1.0 and range_ref({"hpf_m": None}) == 1.0 and range_ref({"hpf_m": 0.4}) == 1.0
    assert range_ref({"hpf_m": 13.45}) == 13.45
    assert range_comp("r4", 26.9, range_ref({"hpf_m": 13.45})) == pytest.approx(40 * math.log10(2.0))


def test_display_only_backend_and_arrays_untouched():
    for f in ("adc.py", "app.py"):
        src = (ROOT / "radar_gui" / f).read_text().lower()
        assert not re.search(r"range_?comp|\bcomp\b|r\^4|compens", src), f      # the backend never receives the mode
    adc = re.sub(r"//.*", "", (WEB / "js" / "adc.js").read_text())
    assert "sendOpts" in adc and not re.search(r"JSON\.stringify\(\{[^}]*comp", adc)   # not a websocket opt
    assert not re.search(r"\b(raw|p|m\.arr\.profile|m\.arr\.rd)\[[^\]]+\]\s*[+\-*]?=[^=]", adc)   # no in-place writes
    assert "Float32Array.from(raw" in adc                                  # compensated profile is a copy
    assert re.search(r"profile_peak_db\.toFixed", adc)                    # the peak text still prints the raw backend value
    assert 'id="adcComp"' in (WEB / "index.html").read_text()
