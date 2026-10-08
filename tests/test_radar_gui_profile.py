"""gui-27: the chirp-construction diagram (web/js/profile.js) draws only fields the backend metrics supply. JS-free:
the field list is parsed out of profile.js (PROFILE_FIELDS) and checked against Metrics for several cfg flavours."""
import re
from pathlib import Path

import pytest

from radar_gui.cfg import metrics, parse_cfg_file

ROOT = Path(__file__).resolve().parents[1]
RADAR = ROOT / "CPSL_TI_Radar_cpp" / "config" / "radar"
FIX = ROOT / "tests" / "fixtures" / "mimo"
SRC = (ROOT / "radar_gui" / "web" / "js" / "profile.js").read_text()
CASES = [(FIX / "s1_simo.cfg", "IWR6843"), (FIX / "s2_bpm.cfg", "IWR6843"), (RADAR / "IWR1443" / "demo" / "short_range_3D.cfg", "IWR6843"),
         (RADAR / "AWR2243_CASCADE" / "cascade_ddm" / "shortrange.cfg", "AWR2243_CASCADE"), (FIX / "adv_subframe_4.cfg", "IWR1843")]


def fields():
    block = re.search(r"PROFILE_FIELDS = \[(.*?)\];", SRC, re.S).group(1)
    return re.findall(r"'([a-z_0-9]+)'", block)


def test_field_list_is_complete():
    f = fields()
    assert len(f) >= 20 and len(set(f)) == len(f)
    # every m.<field> the JS reads is declared
    used = set(re.findall(r"\bm\.([a-z_0-9]+)", SRC))
    assert used <= set(f), used - set(f)


@pytest.mark.parametrize("path,board", CASES, ids=lambda p: getattr(p, "name", p))
def test_backend_supplies_every_field(path, board):
    d = metrics(parse_cfg_file(path), board).to_dict()
    missing = [k for k in fields() if k not in d]
    assert not missing, missing
    assert d["tx_start_us"] == pytest.approx(float(next(c for c in parse_cfg_file(path).all("profileCfg")).floats()[8]))
    assert d["adc_end_us"] == pytest.approx(d["adc_start_us"] + d["sampling_us"])
