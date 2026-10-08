"""gui-04 Step 4: the real driver's `--validate --json` against the GUI's Python validate(): the same `ok` and the same
error-code set for every shipped system config and for the seeded-bad corpus (tests/fixtures/parity/).
Skipped when no driver binary (build/, or $RADAR_GUI_DRIVER) supports `--json`."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from radar_gui.cfg.parse import parse_cfg_file
from radar_gui.cfg.validate import validate

REPO = Path(__file__).resolve().parent.parent
CPP = REPO / "CPSL_TI_Radar_cpp"
CORPUS = Path(__file__).parent / "fixtures" / "parity"
GUI_BOARD = {"IWR1843_SAR": "IWR1843"}   # the driver board that runs the SAR firmware is the GUI's IWR1843

# Error codes only the Python validator emits; the driver does not port them, so they are dropped from the comparison:
#  - the MIMO / chirp-pattern rules (need the GUI-only `mimo` block of the firmware descriptor),
#  - lvds_fmt_unsupported (GUI-only `lvds_data_fmts`),
#  - every cfar_* code (gui-35: on-chip CFAR editing is GUI-only by user ruling).
GUI_ONLY_CODES = frozenset({"subframes_unsupported", "chirps_span_profiles", "bpm_unsupported", "tx_pattern_invalid",
                            "tx_not_in_channelcfg", "lvds_fmt_unsupported"})


def gui_only(code: str) -> bool:
    return code in GUI_ONLY_CODES or code.startswith("cfar_")


def _driver():
    for b in (Path(os.environ.get("RADAR_GUI_DRIVER") or CPP / "build" / "CPSL_TI_Radar_CPP"),):
        if b.is_file():
            try:
                p = subprocess.run([str(b), "--help"], capture_output=True, text=True, timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if "--json" in p.stdout + p.stderr:
                return b
    return None


DRIVER = _driver()
pytestmark = pytest.mark.skipif(DRIVER is None, reason="no driver binary with --validate --json (build CPSL_TI_Radar_cpp)")
SHIPPED = sorted((CPP / "config" / "system").glob("*.json"))
CASES = json.loads((CORPUS / "manifest.json").read_text())


def driver_verdict(system_json: Path) -> tuple[bool, set]:
    p = subprocess.run([str(DRIVER), str(system_json), "--validate", "--json"], capture_output=True, text=True, timeout=30)
    d = json.loads(p.stdout)
    assert (p.returncode == 0) == d["ok"]
    return d["ok"], {e["code"] for e in d["errors"]}


def python_verdict(cfg: Path, board: str, firmware: str) -> tuple[bool, set]:
    rep = validate(parse_cfg_file(cfg), GUI_BOARD.get(board, board), firmware)
    codes = {i.code for i in rep.errors if not gui_only(i.code)}
    return not codes, codes


def test_corpus_relies_on_no_gui_only_code():
    seen = {i.code for c in CASES for i in validate(parse_cfg_file(CORPUS / c["cfg"]), GUI_BOARD.get(c["board"], c["board"]), c["firmware"]).errors}
    assert not any(gui_only(c) for c in seen), "a corpus case relies on a GUI-only code"


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_shipped_system_config(path):
    sj = json.loads(path.read_text())
    cfg = (path.parent / sj["radar_cfg"]).resolve()
    ok_d, codes_d = driver_verdict(path)
    ok_p, codes_p = python_verdict(cfg, sj["board"], sj["firmware"])
    assert (ok_d, codes_d) == (ok_p, codes_p)
    assert ok_d, codes_d


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_corpus_case(case, tmp_path):
    serial = {"enabled": True, "port": "/dev/ttyACM1"} if case["serial"] else {"enabled": False}
    dca = ({"enabled": True, "fpga_ip": "192.168.33.180", "host_ip": "192.168.33.30", "cmd_port": 4096, "data_port": 4098}
           if case["dca"] else {"enabled": False})
    sj = tmp_path / "case.json"
    sj.write_text(json.dumps({"schema_version": 2, "board": str(CPP / "config" / "boards" / f"{case['board']}.json"),
                              "firmware": case["firmware"], "radar_cfg": str(CORPUS / case["cfg"]),
                              "cli": {"port": "/dev/ttyACM0"}, "serial_stream": serial, "dca1000": dca}))
    ok_d, codes_d = driver_verdict(sj)
    ok_p, codes_p = python_verdict(CORPUS / case["cfg"], case["board"], case["firmware"])
    assert (ok_d, codes_d) == (ok_p, codes_p) == (False, set(case["codes"]))
