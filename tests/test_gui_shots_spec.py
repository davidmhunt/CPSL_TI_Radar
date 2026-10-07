"""Hardware/browser-free check of tools/gui_shots.py spec parsing (no Firefox is launched)."""
import importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gui_shots", ROOT / "tools" / "gui_shots.py")
gs = importlib.util.module_from_spec(spec); spec.loader.exec_module(gs)


def test_builtin_and_smoke_spec_parse():
    sc, user = gs.load_spec("builtin")
    assert sc and user == {}
    sc, user = gs.load_spec(str(ROOT / "tools" / "gui_shots_specs" / "smoke.json"))
    assert len({s["name"] for s in sc}) == len(sc) and user
    known = {"mode", "board", "firmware", "load", "set", "click", "click_text", "js", "wait"}
    for s in sc:
        assert s.get("shots") or s.get("dumps")
        for a in s.get("actions", []):
            assert known & set(a), a


def test_spec_requires_name(tmp_path):
    p = tmp_path / "s.json"; p.write_text(json.dumps([{"actions": []}]))
    try:
        gs.load_spec(str(p))
    except ValueError:
        return
    raise AssertionError("expected ValueError")
