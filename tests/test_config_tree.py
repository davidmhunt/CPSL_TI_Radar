"""gui-38: the shape of CPSL_TI_Radar_cpp/config/ (hardware-free).

radar cfgs sit at radar/<BOARD>/<firmware>/<name>.cfg; system JSONs are named <BOARD>_<fw>_<purpose>[_<mount>].json;
config/archive/ is never referenced; config/moved_paths.json maps every pre-reorganisation name to its new one.
config/user/ is the user's own and exempt.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[1] / "CPSL_TI_Radar_cpp" / "config"
SYSTEM = CONFIG / "system"
RADAR = CONFIG / "radar"
BOARDS = {p.stem: json.loads(p.read_text()) for p in sorted((CONFIG / "boards").glob("*.json"))}
FIRMWARE = {p.stem: json.loads(p.read_text()) for p in sorted((CONFIG / "firmware").glob("*.json"))}
SYSTEMS = sorted(SYSTEM.glob("*.json"))
CFGS = sorted(RADAR.rglob("*.cfg"))
MOVED = json.loads((CONFIG / "moved_paths.json").read_text())

# driver boards that are not a radar folder: IWR1843_SAR is the driver name of the GUI board IWR1843 + iwr1843_sar_lvds
GUI_BOARD = {drv: gui for fw in FIRMWARE.values() for gui, drv in (fw.get("driver_board") or {}).items()}


def gui_board(driver_board: str) -> str:
    return GUI_BOARD.get(driver_board, driver_board)


def cfg_of(system_json: Path) -> Path:
    doc = json.loads(system_json.read_text())
    return (system_json.parent / doc["radar_cfg"]).resolve()


def test_counts():
    assert len(SYSTEMS) >= 39 and len(CFGS) == 75       # 77 moved cfgs minus the 2 archived ones
    assert len(MOVED["radar"]) == 77 and len(MOVED["system"]) == 41


@pytest.mark.parametrize("path", SYSTEMS, ids=lambda p: p.name)
def test_a_system_json_resolves_board_and_cfg_in_matching_folder(path):
    doc = json.loads(path.read_text())
    assert doc["board"] in BOARDS, doc["board"]
    cfg = cfg_of(path)
    assert cfg.is_file(), cfg
    rel = cfg.relative_to(RADAR.resolve()).parts
    assert len(rel) == 3, rel
    assert rel[0] == gui_board(doc["board"]) and rel[1] == doc["firmware"], (rel, doc["board"], doc["firmware"])
    assert doc["firmware"] in BOARDS[doc["board"]]["firmwares"]


@pytest.mark.parametrize("cfg", CFGS, ids=lambda p: str(p.relative_to(RADAR)))
def test_b_cfg_sits_at_board_firmware_name(cfg):
    rel = cfg.relative_to(RADAR).parts
    assert len(rel) == 3, rel
    board, fw, _ = rel
    assert board in BOARDS, f"no board descriptor for {board}"
    assert fw in FIRMWARE and fw in BOARDS[board]["firmwares"], (board, fw)


def test_c_every_template_resolves_under_its_board_and_firmware():
    for fw_id, fw in FIRMWARE.items():
        for board, tpl in fw["templates"].items():
            p = CONFIG / tpl
            assert p.is_file(), (fw_id, board, tpl)
            rel = p.relative_to(RADAR).parts
            assert rel[:2] == (board, fw_id), (fw_id, board, tpl)


def test_d_nothing_points_into_archive_and_moved_targets_exist():
    for path in SYSTEMS:
        assert "archive" not in cfg_of(path).relative_to(CONFIG.resolve()).parts, path.name
    for fw in FIRMWARE.values():
        assert all("archive" not in t for t in fw["templates"].values())
    for kind, base in (("radar", CONFIG), ("system", SYSTEM)):
        for old, new in MOVED[kind].items():
            assert (base / new).is_file(), (kind, old, new)
            assert not (base / old).exists(), f"{old} still exists"
    # the archive holds exactly the 2 archived cfgs
    assert sorted(p.name for p in (CONFIG / "archive").rglob("*.cfg")) == ["standard.cfg", "vel_detection.cfg"]


def _name_pattern() -> re.Pattern:
    boards = sorted({gui_board(b) for b in BOARDS}, key=len, reverse=True)
    fws = sorted(FIRMWARE, key=len, reverse=True)
    return re.compile(rf"^({'|'.join(boards)})_({'|'.join(fws)})_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)*?(?:_(?:front|back|down|r1))?\.json$")


@pytest.mark.parametrize("path", SYSTEMS, ids=lambda p: p.name)
def test_e_system_name_matches_board_and_firmware(path):
    m = _name_pattern().match(path.name)
    assert m, path.name
    doc = json.loads(path.read_text())
    assert m.group(1) == gui_board(doc["board"]) and m.group(2) == doc["firmware"], path.name


# --- config/README.md index (gui-38 Step 2) ---------------------------------------------------------------

README = (CONFIG / "README.md").read_text()
_ROW = re.compile(r"^\| \[`([^`]+\.json)`\]\(system/([^)]+)\) \| ([^|]+?) \| ([^|]+?) \|", re.M)


def test_readme_indexes_every_system_json_with_matching_board_and_firmware():
    rows = {m.group(1): (m.group(3), m.group(4)) for m in _ROW.finditer(README)}
    assert sorted(rows) == [p.name for p in SYSTEMS], "config/README.md index != config/system/*.json"
    for path in SYSTEMS:
        doc = json.loads(path.read_text())
        assert rows[path.name] == (doc["board"], doc["firmware"]), path.name


def test_readme_old_to_new_tables_cover_moved_paths():
    for old, new in MOVED["system"].items():
        assert f"| `{old}` | `{new}` |" in README, old
    assert all(f"`{old}`" in README for old in MOVED["radar"])
