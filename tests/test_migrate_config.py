"""Migration golden test for tools/migrate_config_v1_to_v2.py (directive core-10).

tests/fixtures/v1_configs/ holds every tracked v1 system config exactly as it
was before the migration (``git show 177e61b:CPSL_TI_Radar_cpp/config/system/<f>``).
Converting each one must give the tracked v2 file byte for byte; the ctest
``test_validate_all_configs`` then checks those v2 files load in the driver
(``CPSL_TI_Radar_CPP --validate``).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/v1_configs"
SYSTEM = REPO / "CPSL_TI_Radar_cpp/config/system"
BOARDS = REPO / "CPSL_TI_Radar_cpp/config/boards"
SCRIPT = REPO / "tools/migrate_config_v1_to_v2.py"

sys.path.insert(0, str(SCRIPT.parent))
import migrate_config_v1_to_v2 as mig  # noqa: E402

V1_FILES = sorted(FIXTURES.glob("*.json"))

# Deliberate edits made to a tracked v2 file after the scripted migration
# (merged over the script's output before comparing):
# - the bench baseline keeps writing LVDS_Raw_0.bin, as the pre-rework
#   baseline runs did, so later runs do the same disk I/O (core-10 step 7)
HAND_EDITS = {
    "front_radar_IWR1843_stress_test_baseline.json": {"output": {"save_raw_lvds": True}},
}


def merge(doc: dict, patch: dict) -> dict:
    for k, v in patch.items():
        doc[k] = merge(doc.get(k, {}), v) if isinstance(v, dict) else v
    return doc


@pytest.fixture(autouse=True)
def boards_dir(monkeypatch):
    # fixtures do not sit next to config/boards, so name the descriptors explicitly
    monkeypatch.setenv(mig.BOARDS_ENV, str(BOARDS))


def run(*args, cwd=REPO):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], cwd=cwd,
                          capture_output=True, text=True)


def test_fixtures_cover_every_tracked_config():
    assert len(V1_FILES) == 39
    assert sorted(p.name for p in V1_FILES) == sorted(p.name for p in SYSTEM.glob("*.json"))
    for p in V1_FILES:
        assert not mig.is_v2(json.loads(p.read_text())), p.name


@pytest.mark.parametrize("v1", V1_FILES, ids=lambda p: p.stem)
def test_golden_conversion_matches_tracked_v2(v1, tmp_path):
    work = tmp_path / v1.name
    work.write_text(v1.read_text())
    r = run(work, "--in-place")
    assert r.returncode == 0, r.stderr
    assert "UNMAPPED" not in r.stderr
    got = work.read_text()
    if v1.name in HAND_EDITS:
        got = mig.dumps(merge(json.loads(got), HAND_EDITS[v1.name]))
    assert got == (SYSTEM / v1.name).read_text()


def test_whole_directory_in_place_then_idempotent(tmp_path):
    for p in V1_FILES:
        (tmp_path / p.name).write_text(p.read_text())
    assert run(tmp_path, "--check", "-q").returncode == 1
    assert run(tmp_path, "--in-place", "-q").returncode == 0
    first = {p.name: p.read_text() for p in tmp_path.glob("*.json")}
    assert run(tmp_path, "--check", "-q").returncode == 0
    assert run(tmp_path, "--in-place", "-q").returncode == 0  # second run: nothing to do
    assert {p.name: p.read_text() for p in tmp_path.glob("*.json")} == first


def test_tracked_configs_are_all_v2():
    r = run(SYSTEM, "--check", "-q")
    assert r.returncode == 0, r.stderr


def test_never_writes_without_in_place(tmp_path):
    src = FIXTURES / "radar_1.json"
    work = tmp_path / "radar_1.json"
    work.write_text(src.read_text())
    r = run(work)
    assert r.returncode == 0
    assert work.read_text() == src.read_text()  # untouched
    assert json.loads(r.stdout) == json.loads((SYSTEM / "radar_1.json").read_text())


def test_key_mapping_details():
    v1 = json.loads((FIXTURES / "front_radar_IWR1843_stress_test_baseline.json").read_text())
    v2, notes, unmapped = mig.convert(v1, FIXTURES / "x.json")
    assert unmapped == []
    assert v2["schema_version"] == 2 and v2["board"] == "IWR1843"
    assert v2["radar_cfg"] == v1["TI_Radar_Config_Management"]["TI_Radar_config_path"]
    assert v2["cli"] == {"port": "/dev/ttyACM0"}
    assert v2["dca1000"] == {"enabled": True, "fpga_ip": "192.168.33.180", "host_ip": "192.168.33.30",
                             "cmd_port": 4096, "data_port": 4098}
    assert v2["output"] == {"save_adc_frames": True, "save_raw_lvds": False}
    assert v2["runtime"] == {"log_level": "debug"}
    assert "SDK_version" not in json.dumps(v2)
    assert any("SDK_version" in n for n in notes)


def test_overrides_kept_when_they_differ_and_dropped_when_equal():
    v1 = json.loads((FIXTURES / "radar_0_AWR2243_cascade_serial.json").read_text())
    v2, _, _ = mig.convert(v1, FIXTURES / "x.json")
    assert "board_overrides" not in v2  # all four equal AWR2243_CASCADE.json
    v1["Streamer"]["serial_streaming"]["timeout_ms"] = 7000
    v1["CLI_Controller"]["cmd_timeout_ms"] = 6000
    v2, _, _ = mig.convert(v1, FIXTURES / "x.json")
    assert v2["board_overrides"] == {"cli": {"cmd_timeout_ms": 6000}, "data_uart": {"timeout_ms": 7000}}


def test_board_from_sdk_version_when_board_type_missing():
    v1 = json.loads((FIXTURES / "radar_1.json").read_text())
    del v1["Streamer"]["board_type"]
    v2, notes, _ = mig.convert(v1, FIXTURES / "x.json")
    assert v2["board"] == "IWR1443"
    assert any("derived from SDK_version" in n for n in notes)


def test_unmapped_key_is_reported_and_blocks_conversion(tmp_path):
    v1 = json.loads((FIXTURES / "radar_1.json").read_text())
    v1["Streamer"]["mystery"] = 1
    v1["Processor"] = {"x": 1}  # known, removed: a note, not unmapped
    work = tmp_path / "radar_1.json"
    work.write_text(json.dumps(v1))
    r = run(work, "--in-place")
    assert r.returncode == 2
    assert "UNMAPPED" in r.stderr and "Streamer.mystery" in r.stderr
    assert json.loads(work.read_text()) == v1  # not converted
    r = run(work, "--in-place", "--drop-unmapped")
    assert r.returncode == 0
    assert json.loads(work.read_text())["schema_version"] == 2
