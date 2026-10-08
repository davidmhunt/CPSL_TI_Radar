"""core-24: the committed dataFmt 2 fixtures (CPSL_TI_Radar_cpp/tests/data/sar_fmt2/) are exactly what the firmware
project's sar_synth.py / sar_parse.py produce today. test_sar_meta.cpp compares the driver against those goldens; if
the firmware tools change, this fails until make_fixtures.py is re-run and the C++ test passes against the result."""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "CPSL_TI_Radar_cpp" / "tests" / "data" / "sar_fmt2"
TOOLS = REPO / "firmware_dev" / "projects" / "iwr1843_sar_lvds" / "tools"

pytestmark = pytest.mark.skipif(not (TOOLS / "sar_synth.py").is_file() or not (TOOLS / "sar_parse.py").is_file(),
                                reason="firmware_dev (iwr1843_sar_lvds tools) not checked out")


def test_fixtures_match_the_firmware_tools(tmp_path):
    p = subprocess.run([sys.executable, "-I", str(FIX / "make_fixtures.py"), str(tmp_path)], capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    made = sorted(f.name for f in tmp_path.iterdir())
    committed = sorted(f.name for f in FIX.iterdir() if f.name != "make_fixtures.py" and f.is_file())
    assert made == committed
    for name in made:
        assert (tmp_path / name).read_bytes() == (FIX / name).read_bytes(), "%s differs: re-run make_fixtures.py" % name
