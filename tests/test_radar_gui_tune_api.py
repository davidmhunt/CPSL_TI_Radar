"""The Tune API (radar_gui/tune_api.py) against the fake driver in `gain` mode; no hardware.
Validation (off-step, out-of-range, busy), a full sweep end to end, the saved run folder, cancel, a failing step, and that the
user's config directory is never opened for write."""
import builtins
import io
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from radar_gui import ports
from radar_gui.app import create_app
from radar_gui.sources import MockSource

pytestmark = pytest.mark.slow

FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")
FIX = Path(__file__).parent / "fixtures" / "adc"


@pytest.fixture
def env(tmp_path, monkeypatch):
    ports.radar_lock.release()
    cli = tmp_path / "ttyFAKE0"
    cli.write_text("")
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir()
    system.mkdir()
    shutil.copy(FIX / "bench_1843_dca.cfg", user / "bench_1843_dca.cfg")
    base = json.loads((FIX / "bench_1843_dca.json").read_text())
    base.update(cli={"port": str(cli)}, serial_stream={"enabled": False}, firmware="iwr1843_sar_lvds")
    (user / "dca.json").write_text(json.dumps(base))
    (user / "nodca.json").write_text(json.dumps({**base, "dca1000": {"enabled": False}}))
    monkeypatch.setenv("FAKE_DRIVER_MODE", "tap")
    monkeypatch.setenv("FAKE_DRIVER_ADC", "gain")
    monkeypatch.setenv("FAKE_DRIVER_RATE", "40")
    monkeypatch.setenv("FAKE_DRIVER_KNEE", "40")
    monkeypatch.setenv("FAKE_DRIVER_SAT_GAIN", "46")
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE,
                              run_root=tmp_path / "runs", min_stop_grace=0.5))
    paths = {x["name"]: x["path"] for x in c.get("/api/driver/configs").json()["configs"]}
    yield c, paths, user, tmp_path
    ports.radar_lock.release()


def wait_done(c, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        s = c.get("/api/tune/status").json()
        if s["state"] != "running":
            return s
        time.sleep(0.1)
    raise AssertionError("sweep never finished")


def body(path, **kw):
    return {"config": path, "gain_min": 30, "gain_max": 48, "gain_step": 2, "frames": 2, **kw}


def test_info_carries_the_board_limits(env):
    c, paths, *_ = env
    j = c.get("/api/tune/info", params={"config": paths["dca"]}).json()
    assert j["board"] == "IWR1843" and j["gain_range"]["min"] == 24 and j["gain_range"]["max"] == 48 and j["gain_range"]["step"] == 2
    assert j["current_gain_db"] == 30 and j["dca1000"] and j["defaults"]["frames"] == 8 and j["defaults"]["margin_db"] == 3.0


@pytest.mark.parametrize("kw", [{"gain_min": 31}, {"gain_max": 49}, {"gain_min": 22}, {"gain_max": 50}, {"gain_step": 3},
                                {"gain_min": 40, "gain_max": 30}, {"frames": 0}, {"margin_db": -1}])
def test_start_refuses_bad_ranges(env, kw):
    c, paths, *_ = env
    r = c.post("/api/tune/start", json=body(paths["dca"], **kw))
    assert r.status_code == 422, r.text
    assert c.get("/api/tune/status").json()["state"] == "idle"        # nothing started, nothing created
    assert not list((env[3] / "runs").glob("*")) if (env[3] / "runs").exists() else True


def test_start_refuses_unlisted_config_and_no_dca(env):
    c, paths, *_ = env
    assert c.post("/api/tune/start", json=body("/etc/passwd")).status_code == 422
    r = c.post("/api/tune/start", json=body(paths["nodca"]))
    assert r.status_code == 422 and "DCA1000" in r.text


def test_start_is_busy_while_a_driver_run_holds_the_radar(env):
    c, paths, *_ = env
    assert c.post("/api/driver/start", json={"config": paths["dca"]}).status_code == 200
    r = c.post("/api/tune/start", json=body(paths["dca"]))
    assert r.status_code == 409 and "driver run is active" in r.text
    c.post("/api/driver/stop")


def test_full_sweep_end_to_end(env):
    c, paths, user, tmp = env
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in user.iterdir()}
    r = c.post("/api/tune/start", json=body(paths["dca"], margin_db=3))
    assert r.status_code == 200, r.text
    s = wait_done(c)
    assert s["state"] == "done", s["error"]
    assert [x["gain_db"] for x in s["rows"]] == list(range(30, 50, 2))
    sug = s["suggestion"]
    assert sug["limited_by"] == "compression" and sug["max_ok_gain"] == 40 and sug["suggested_gain"] == 36
    row46 = next(x for x in s["rows"] if x["gain_db"] == 46)
    assert row46["sat_chirps"] > 0 and row46["status"] == "after_limit" and row46["headroom_db"] is not None
    # saved run: params, table, plot data, cfg copy; one folder per step, each with the step's cfg at its gain
    d = Path(s["run_dir"])
    assert d.parent == tmp / "runs" and d.name.endswith("_tune_dca")
    saved = json.loads((d / "tune.json").read_text())
    assert saved["state"] == "done" and saved["rows"] == s["rows"] and saved["params"]["frames"] == 2
    assert saved["params"]["adc_bits"] == 16 and saved["params"]["adc_bits_source"] == "adcCfg numADCBits 2"
    assert (d / "tune.csv").read_text().splitlines()[0].startswith("gain_db,status") and (d / "plot.json").is_file()
    assert (d / "radar.cfg").read_text() == (user / "bench_1843_dca.cfg").read_text()
    assert "profileCfg 0 77 87.04 7 73 0 0 26.981 1 128 2000 0 0 44" in (d / "step_g44" / "step.cfg").read_text()
    assert not list(d.rglob("adc_data.bin"))
    # the user's setups are untouched, and the suggestion was not applied anywhere
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in user.iterdir()}
    assert after == before
    assert (user / "bench_1843_dca.cfg").read_text().count(" 2000 0 0 30\n") == 1
    # re-running the stored rule on the stored table reproduces the suggestion
    from radar_gui import tune
    again = tune.suggest(copy_rows(saved["rows"]), saved["params"]["gain_range"], saved["params"]["margin_db"],
                         saved["params"]["tol_db"], saved["params"]["min_snr_db"], saved["params"]["adc_bits"])
    assert again["suggested_gain"] == sug["suggested_gain"]


def copy_rows(rows):
    return [dict(r) for r in rows]


def test_user_config_dir_is_never_opened_for_write(env, monkeypatch):
    c, paths, user, tmp = env
    opened = []
    real_open, real_io_open = builtins.open, io.open

    def spy(file, mode="r", *a, **kw):
        try:
            p = Path(file) if isinstance(file, (str, bytes, Path)) else None
        except TypeError:
            p = None
        if p is not None and any(ch in str(mode) for ch in "wax+") and str(user) in str(p.absolute()):
            opened.append((str(p), mode))
        return real_open(file, mode, *a, **kw)
    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(io, "open", spy)
    (user / "canary.txt").write_text("x")                    # the spy sees a write into the user dir (so silence below means something)
    assert len(opened) == 1
    opened.clear()
    assert c.post("/api/tune/start", json=body(paths["dca"], gain_max=36)).status_code == 200
    assert wait_done(c)["state"] == "done"
    assert opened == []


def test_a_driver_start_is_refused_during_a_sweep_and_cancel_stops_it(env, monkeypatch):
    c, paths, *_ = env
    monkeypatch.setenv("FAKE_DRIVER_RATE", "2")             # slow frames: the sweep lasts long enough to poke at it
    assert c.post("/api/tune/start", json=body(paths["dca"], frames=4)).status_code == 200
    r = c.post("/api/driver/start", json={"config": paths["dca"]})
    assert r.status_code == 409 and "gain sweep" in r.text
    assert c.post("/api/tune/start", json=body(paths["dca"])).status_code == 409      # one sweep at a time
    assert c.post("/api/tune/cancel").status_code == 200
    s = wait_done(c)
    assert s["state"] == "cancelled" and s["suggestion"] is None
    assert json.loads((Path(s["run_dir"]) / "tune.json").read_text())["state"] == "cancelled"
    assert c.post("/api/tune/cancel").status_code == 409                               # nothing running now
    assert c.get("/api/driver/status").json()["state"] != "running"


def test_a_failing_step_is_reported_with_its_gain(env, monkeypatch):
    c, paths, *_ = env
    monkeypatch.setenv("FAKE_DRIVER_ADC", "tiny")           # a cube that does not match the cfg's geometry
    assert c.post("/api/tune/start", json=body(paths["dca"])).status_code == 200
    s = wait_done(c)
    assert s["state"] == "failed" and "gain 30 dB" in s["error"] and "0 of 2 ADC frames" in s["error"]
    assert s["suggestion"] is None
