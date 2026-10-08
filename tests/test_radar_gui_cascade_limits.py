"""Cascade DDM chirp / L3 limits (gui-09 D11; docs/research/gui_cascade_chirp_limit_2026-10-07.md)."""
import re
from pathlib import Path

import pytest

import importlib

from radar_gui.cfg import parse_cfg, validate

generate = importlib.import_module("radar_gui.cfg.generate")

RADAR = Path(__file__).resolve().parents[1] / "CPSL_TI_Radar_cpp" / "config" / "radar" / "AWR2243_CASCADE" / "cascade_ddm"
BASE = (RADAR / "shortrange.cfg").read_text()


def with_frame(loops, samples=None, text=BASE):
    t = re.sub(r"^frameCfg 0 7 \d+", f"frameCfg 0 7 {loops}", text, flags=re.M)
    if samples:
        def prof(m):
            tok = m.group(0).split()
            tok[10] = str(samples)
            return " ".join(tok)
        t = re.sub(r"^profileCfg .*$", prof, t, flags=re.M)
    return validate(parse_cfg(t), "AWR2243_CASCADE", "cascade_ddm")


def codes(r, level):
    return [i.code for i in r.issues if i.level == level]


def test_256_chirps_pass():
    r = with_frame(32)
    assert r.metrics.n_chirps == 256 and "chirps" not in codes(r, "error") + codes(r, "warning")


@pytest.mark.parametrize("loops,chirps", [(48, 384), (128, 1024)])
def test_over_256_errors_with_fix(loops, chirps):
    r = with_frame(loops)
    assert r.metrics.n_chirps == chirps and "chirps" in codes(r, "error") and not r.ok
    msg = next(i.message for i in r.issues if i.code == "chirps")
    assert "256" in msg and "reduce loops to <= 32 with 8 chirp cfgs" in msg


def test_l3_cube_error_only_when_exceeded():
    assert "radar_cube_l3" not in codes(with_frame(32, samples=192), "error")
    r = with_frame(32, samples=1024)       # 1024 range bins x 256 chirps x 8 RX x 4 B x 0.5 ~ 4 MB > 2.54 MiB
    assert "radar_cube_l3" in codes(r, "error")


def test_shipped_cascade_cfgs_clean():
    for f in RADAR.glob("*.cfg"):
        r = validate(parse_cfg(f.read_text()), "AWR2243_CASCADE", "cascade_ddm")
        assert r.ok and not codes(r, "error"), f.name


def test_generator_caps_cascade_chirps():
    for vres in (0.05, 0.2):
        loops = generate._loop_options(None, vres, {"fc_hz": 77e9, "tc": 40.0}, 8, True)[0][0]
        assert loops * 8 <= 256
