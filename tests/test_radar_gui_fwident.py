"""Firmware identity matcher over the shared fw_replies manifest and descriptor schema (the Python
serial-source pre-cfg check was removed; the driver checks now)."""
import json
from pathlib import Path

import pytest

from radar_gui import fwident
from radar_gui.cfg import firmware as fwmod

DATA = Path(__file__).resolve().parents[1] / "CPSL_TI_Radar_cpp" / "tests" / "data" / "fw_replies"
MANIFEST = json.loads((DATA / "manifest.json").read_text())


def load_replies(case):
    return {cmd: (fwident.strip_fixture((DATA / f).read_text()) if f else None) for cmd, f in case["replies"].items()}


@pytest.mark.parametrize("case", MANIFEST["cases"], ids=lambda c: c["id"])
def test_manifest_verdicts(case):
    res = fwident.identify(case["fw"], case["board"], load_replies(case))
    assert res["verdict"] == case["verdict"], res


def test_manifest_covers_every_verdict_and_every_identify_entry():
    assert {c["verdict"] for c in MANIFEST["cases"]} == {"match", "mismatch", "unknown", "skipped"}
    have = {(c["fw"], c["board"]) for c in MANIFEST["cases"]}
    want = {(fw, b) for fw, d in fwmod.load_all().items() for b in (d.get("identify") or {})}
    assert want <= have
    for c in MANIFEST["cases"]:
        for f in c["replies"].values():
            assert f is None or (DATA / f).is_file()


def test_bench_recorded_fields():
    case = next(c for c in MANIFEST["cases"] if c["id"] == "demo_1843_on_demo")
    res = fwident.identify("demo", "IWR1843", load_replies(case))
    assert res["fields"]["sdk"] == "03.06.02.00" and res["fields"]["platform"] == "xWR18xx" and res["level"] == "bench"
    assert "IWR18xx" in res["fields"]["device"]


def test_mismatch_message_names_expected_found_and_flash():
    case = next(c for c in MANIFEST["cases"] if c["id"] == "sar_expected_on_demo_board")
    res = fwident.identify(case["fw"], case["board"], load_replies(case))
    m = fwident.mismatch_message(case["fw"], case["board"], res, "/dev/ttyACM0")
    assert "iwr1843_sar_lvds (IWR1843)" in m and "platform=xWR18xx" in m and "./fw flash iwr1843_sar_lvds" in m and "/dev/ttyACM0" in m


def test_descriptors_valid_and_regexes_portable():
    for fw, d in fwmod.load_all().items():
        assert fwmod.check_descriptor(d, fw) == [], fw
        for b, e in (d.get("identify") or {}).items():
            for p in e["probes"]:
                for rx in [*p["require"], *p["reject"], *p["show"].values()]:
                    assert "(?" not in rx, (fw, b, rx)     # no lookbehind / named groups / inline flags (C++ ECMAScript)


def test_check_identify_rejects_bad_entries():
    ok = {"level": "bench", "flash_hint": "x", "probes": [{"cmd": "version", "require": ["a"], "reject": [], "show": {}}]}
    assert fwident.check_identify({"B": ok}) == []
    assert fwident.check_identify({"B": {**ok, "extra": 1}})
    assert fwident.check_identify({"B": {**ok, "level": "guess"}})
    assert fwident.check_identify({"B": {**ok, "probes": [{"cmd": "v", "require": ["("], "reject": [], "show": {}}]}})
    assert fwident.check_identify({"B": {**ok, "probes": [{"cmd": "v", "require": [], "reject": [], "show": {}}]}})

