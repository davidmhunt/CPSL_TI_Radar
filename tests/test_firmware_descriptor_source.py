"""Descriptor `source` back-references (fwstd-03) resolve to firmware_dev projects.

Skipped when the firmware_dev submodule is not checked out.
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DESCRIPTORS = sorted((ROOT / "CPSL_TI_Radar_cpp" / "config" / "firmware").glob("*.json"))
PROJECTS = ROOT / "firmware_dev" / "projects"

needs_fw = pytest.mark.skipif(not PROJECTS.is_dir(), reason="firmware_dev submodule not checked out")


def _artifacts(project: Path) -> set[str]:
    toml = project / "project.toml"
    if toml.is_file():
        import tomllib
        data = tomllib.loads(toml.read_text())
        return {a["file"] for a in data.get("artifact", [])}
    env = project / "project.env"
    m = re.search(r'^ARTIFACTS="([^"]*)"', env.read_text(), re.M)
    return set(m.group(1).split()) if m else set()


def _entries():
    for p in DESCRIPTORS:
        for board, e in json.loads(p.read_text()).get("identify", {}).items():
            yield pytest.param(p.name, board, e, id=f"{p.stem}-{board}")


@needs_fw
@pytest.mark.parametrize("fname,board,entry", list(_entries()))
def test_source_resolves(fname, board, entry):
    assert "source" in entry, "identify entry needs `source` (null for prebuilt-only)"
    src = entry["source"]
    if src is None:
        assert "shipped_firmware" in entry["flash_hint"], "null source must point to shipped_firmware/README.md"
        return
    proj = PROJECTS / src["fw_project"]
    assert proj.is_dir(), f"{fname}/{board}: no project {src['fw_project']}"
    assert src["artifact"] in _artifacts(proj), f"{fname}/{board}: artifact {src['artifact']} not declared"
    assert f"flash {src['fw_project']} " in entry["flash_hint"], "flash_hint must name the same project"


def _check(projects: Path, src: dict) -> bool:
    proj = projects / src["fw_project"]
    return proj.is_dir() and src["artifact"] in _artifacts(proj)


def test_toml_project_backlink(tmp_path):
    proj = tmp_path / "demo"
    proj.mkdir()
    (proj / "project.toml").write_text(
        '[[artifact]]\nfile = "demo.bin"\nboard = "X"\ndescriptor = "d"\nflashable = true\n')
    assert _artifacts(proj) == {"demo.bin"}
    assert _check(tmp_path, {"fw_project": "demo", "artifact": "demo.bin"})
    assert not _check(tmp_path, {"fw_project": "demo", "artifact": "other.bin"})
    assert not _check(tmp_path, {"fw_project": "missing", "artifact": "demo.bin"})


def test_env_project_artifacts(tmp_path):
    (tmp_path / "project.env").write_text('ARTIFACTS="a.bin b.bin"\n')
    assert _artifacts(tmp_path) == {"a.bin", "b.bin"}
