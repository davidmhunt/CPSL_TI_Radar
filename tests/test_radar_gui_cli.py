"""gui-34 Step 1: board command transcript (driver CLI echo lines in both formats)."""
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from radar_gui import ports
from radar_gui.app import create_app
from radar_gui.driver import DriverManager, clean_reply
from radar_gui.sources import MockSource

FIX = Path(__file__).parent / "fixtures"
FAKE = str(Path(__file__).parent / "fakes" / "fake_driver.py")


def feed(name):
    events = []
    m = DriverManager(emit=events.append)
    for ln in (FIX / name).read_text().split("\n"):
        m._line(ln)
    m._cli_close()
    return m, events


def test_debug_format_run_with_rejected_sensorstart():
    """Today's binary at log_level debug: Sent/Received pair + reply lines + prompt (real capture, IWR1843)."""
    m, events = feed("cli_debug_run.txt")
    cmds = [(e["cmd"], e["verdict"]) for e in m.cli]
    assert cmds[0] == ("calibData 0 0 0", "SKIP")
    assert cmds[1] == ("sensorStop", "DONE") and m.cli[1]["reply"] == "Ignored: Sensor is already stopped"
    assert ("cfarFovCfg -1 1 -1 1.00", "DONE") in cmds
    start = next(e for e in m.cli if e["cmd"] == "sensorStart")
    assert start["verdict"] == "ERROR" and not start["ok"]
    assert start["reply"].startswith("Error: Full configuration must be provided") and start["reply"].endswith("Error -1")
    assert start["ms"] is None
    assert m.cli[-1]["cmd"] == "sensorStop" and m.cli[-1]["verdict"] == "DONE"
    ff = m.status()["cli_first_fail"]
    assert m.cli[ff - 1] is start
    assert [e["seq"] for e in m.cli] == list(range(1, len(m.cli) + 1))
    # stats lines in the same log still parse; the log tail is unchanged
    assert m.stats["serial"]["frames"] == 0 and m.stats["serial"]["stalls"] == 0
    assert any(l.startswith("stats v1 serial") for l in m.status()["log"])
    cli_ev = [e for e in events if e["type"] == "driver_cli"]
    assert len(cli_ev) == len(m.cli) and cli_ev[-1]["first_fail"] == ff


def test_info_format_four_forms():
    m, events = feed("cli_info_run.txt")
    skip, stop, ok, to, err = m.cli
    assert (skip["tag"], skip["verdict"], skip["cmd"]) == ("skip", "SKIP", "calibData 0 0 0")
    assert (stop["tag"], stop["verdict"], stop["ms"], stop["i"]) == ("stop", "DONE", 9, None)
    assert (ok["i"], ok["n"], ok["verdict"], ok["ms"], ok["reply"]) == (1, 3, "DONE", 12, "")
    assert (to["verdict"], to["reply"], to["ok"], to["cmd"]) == ("TIMEOUT", "partial", False, "foo 1 2")
    assert (err["i"], err["verdict"], err["ms"]) == (3, "ERROR", 8)
    assert err["reply"].endswith("| Error -1")
    assert m.status()["cli_first_fail"] == 4          # the timeout is the first failure
    assert m.stats["serial"]["frames"] == 0           # stats line after the transcript still parsed


def test_reply_cap_and_timeout_without_prompt():
    assert len(clean_reply(["x" * 500], False)) == 200
    m = DriverManager()
    for ln in ["Sent command: foo 1", "Received response: foo 1", "stats v1 serial t=1.0 frames=0 missed=0 overwritten=0 stalls=0"]:
        m._line(ln)
    assert m.cli[0]["verdict"] == "TIMEOUT" and m.cli[0]["ok"] is False
    m._line("warning: CLIController: no 'Done' for 'foo 1' within 100 ms")
    assert m.cli[0]["ms"] == 100


def test_cli_cap_keeps_the_start_of_the_run():
    m = DriverManager()
    for i in range(520):
        m._line(f"cli [{i + 1}/520] c{i} -> Done (1 ms)")
    assert len(m.cli) == 500 and m.cli[0]["cmd"] == "c0" and m.cli[-1]["cmd"] == "c499"


def test_api_status_and_ws_events_with_fake_driver(tmp_path, monkeypatch):
    ports.radar_lock.release()
    cli = tmp_path / "ttyFAKE0"
    cli.write_text("")
    user, system = tmp_path / "user", tmp_path / "system"
    user.mkdir(), system.mkdir()
    cfg = user / "rig.json"
    cfg.write_text(json.dumps({"schema_version": 2, "board": "IWR1843", "radar_cfg": "x.cfg", "cli": {"port": str(cli)},
                               "serial_stream": {"enabled": True}}))
    monkeypatch.setenv("FAKE_DRIVER_CLI", "debug")
    monkeypatch.setenv("FAKE_DRIVER_MODE", "stall")
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=system, driver_bin=FAKE,
                              run_root=tmp_path / "runs", min_stop_grace=0.5))
    try:
        assert c.post("/api/driver/start", json={"config": str(cfg)}).status_code == 200
        end = time.time() + 10
        while time.time() < end and not c.get("/api/driver/status").json()["cli_first_fail"]:
            time.sleep(0.05)
        st = c.get("/api/driver/status").json()
        assert st["cli"][st["cli_first_fail"] - 1]["cmd"] == "sensorStart"
        c.post("/api/driver/stop")
    finally:
        end = time.time() + 10
        while time.time() < end and c.get("/api/driver/status").json()["state"] in ("running", "stopping"):
            time.sleep(0.05)
        ports.radar_lock.release()
