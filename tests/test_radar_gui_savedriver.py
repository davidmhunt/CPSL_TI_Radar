"""gui-04 Step 4: Configure Save returns the real driver's `--validate --json` verdict (`driver`), and
radar_gui.driver.validate_config falls back to the plain text on a driver without --json."""
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui.app import create_app
from radar_gui.cfg import generate
from radar_gui.driver import parse_validate_json, validate_config
from radar_gui.sources import MockSource
from tests.test_validate_parity import DRIVER  # noqa: F401  (a driver with --json, or None)

CPP = Path(__file__).resolve().parent.parent / "CPSL_TI_Radar_cpp"


def _client(tmp_path, binary):
    return TestClient(create_app(MockSource(rate_hz=200), user_cfg_dir=tmp_path / "user", driver_bin=str(binary)))


def _save(c, **kw):
    txt = generate("IWR1843", {"max_range_m": 10, "max_velocity_ms": 3}).text
    return c.post("/api/cfg/save", json={"board": "IWR1843", "name": "t1", "cfg_text": txt, "firmware": "demo", **kw})


@pytest.mark.skipif(DRIVER is None, reason="no driver binary with --json")
def test_save_returns_the_driver_verdict(tmp_path):
    with _client(tmp_path, DRIVER) as c:
        j = _save(c).json()
    assert j["driver"]["available"] and j["driver"]["json"] and j["driver"]["ok"], j["driver"]
    assert '"firmware": "demo"' in Path(j["json_path"]).read_text()


def test_save_without_a_driver_binary_still_saves(tmp_path):
    with _client(tmp_path, tmp_path / "nope") as c:
        j = _save(c).json()
    assert j["ok"] and j["driver"]["available"] is False


def test_fallback_to_text_on_a_driver_without_json(tmp_path):
    fake = tmp_path / "olddriver"
    fake.write_text('#!/bin/sh\ncase "$*" in *--json*) echo "unknown option: --json"; exit 2;; esac\n'
                    'echo "frame:      4 rx x 8 samples x 2 chirps, 50 ms period"; echo "OK: x"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    v = validate_config(fake, "x.json")
    assert v["ok"] and v["frame"]["rx"] == 4 and "json" not in v


def test_parse_validate_json_rejects_non_json():
    assert parse_validate_json("usage: ...", 2) is None
    v = parse_validate_json('{"ok": false, "errors": [{"code": "slope", "message": "m"}], "warnings": []}', 1)
    assert not v["ok"] and "error [slope]: m" in v["text"]
