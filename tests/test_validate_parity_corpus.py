"""The seeded-bad parity corpus (tests/fixtures/parity/, gui-04 Step 3b): manifest.json lists the error codes the
Python validator gives each cfg; the driver's ctest `test_validate_parity_corpus` checks the same lists against
`--validate --json`. Step 4's tests/test_validate_parity.py compares the two live."""
import json
from pathlib import Path

from radar_gui.cfg.parse import parse_cfg_file
from radar_gui.cfg.validate import validate

CORPUS = Path(__file__).parent / "fixtures" / "parity"
CASES = json.loads((CORPUS / "manifest.json").read_text())
GUI_BOARD = {"IWR1843_SAR": "IWR1843"}   # the driver board that runs the SAR firmware is the GUI's IWR1843


def test_corpus_covers_every_ported_rule_code():
    codes = {c for case in CASES for c in case["codes"]}
    assert len(CASES) >= 30 and len(codes) >= 30


def test_manifest_matches_the_python_validator():
    for case in CASES:
        rep = validate(parse_cfg_file(CORPUS / case["cfg"]), GUI_BOARD.get(case["board"], case["board"]), case["firmware"])
        assert sorted({i.code for i in rep.errors}) == case["codes"], case["name"]
        assert not rep.ok
