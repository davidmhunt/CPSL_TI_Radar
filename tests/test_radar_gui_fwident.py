"""gui-33 Step 1: firmware identity matcher over the shared fw_replies manifest, descriptor schema, and SerialSource's
pre-cfg check (match, mismatch, no reply, cascade skipped, skip box)."""
import json
from pathlib import Path

import pytest

from radar_gui import fwident, ports
from radar_gui.cfg import firmware as fwmod
from radar_gui.serial_source import SerialSource, expected_firmware

from test_radar_gui_serial import FakeBoard, FakeCli, cfg_file, run

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


def test_expected_firmware():
    assert expected_firmware("IWR1843") == "demo" and expected_firmware("AWR2243_CASCADE") == "cascade_ddm"


# ---- SerialSource -----------------------------------------------------------------------------------------------
class AnswerBoard(FakeBoard):
    """Answers version / sarStats with fixture text (None = silent); everything else Done."""

    def __init__(self, answers, **kw):
        super().__init__(**kw)
        self.answers = answers

    def opener(self, path, baud):
        if path == "cli":
            self.cli_opens += 1
            return AnswerCli(self)
        return super().opener(path, baud)


class AnswerCli(FakeCli):
    def write(self, data):
        line = data.decode().strip()
        if line in self.b.answers:
            self.b.cli_log.append(line)
            a = self.b.answers[line]
            self.out += (a or "").encode()
        else:
            super().write(data)


def fx(name):
    return fwident.strip_fixture((DATA / name).read_text())


def src_for(board, brd, tmp_path, **kw):
    states = []
    s = SerialSource(board, cfg_file(tmp_path), "cli", "data", opener=brd.opener, exists=brd.exists, check=lambda p: None,
                     lock=ports.RadarLock(), settle_s=0.01, poll_s=0.01, on_status=lambda a, b: states.append((a, b)), **kw)
    return s, states


def configure(src):
    return run(src._configure(), 15)


def test_match_then_cfg_sent(tmp_path):
    brd = AnswerBoard({"version": fx("demo_IWR1843_version.txt"), "sarStats": fx("demo_IWR1843_sarStats.txt")})
    src, states = src_for("IWR1843", brd, tmp_path)
    assert configure(src) is True
    assert brd.cli_log == ["version", "sarStats", "sensorStop", "flushCfg", "calibData 0 0 0", "sensorStart"]
    assert src.firmware["verdict"] == "match" and src.firmware["expected"] == "demo"
    assert [e["cmd"] for e in src.cli[:2]] == ["version", "sarStats"] and src.cli[0]["tag"] == "id"
    assert src.cli_first_fail is None            # sarStats 'not recognized' is the expected answer, not a cfg failure


def test_mismatch_sends_no_cfg(tmp_path):
    # a SAR image on the board while the demo is expected
    brd = AnswerBoard({"version": fx("iwr1843_sar_lvds_IWR1843_version.txt"), "sarStats": fx("iwr1843_sar_lvds_IWR1843_sarStats.txt")})
    src, states = src_for("IWR1843", brd, tmp_path)
    assert configure(src) is False
    assert brd.cli_log == ["version", "sarStats"]
    st, msg = states[-1]
    assert st == "wrong_firmware" and "expects demo (IWR1843)" in msg and "./fw flash demo" in msg and "Skip firmware check" in msg
    assert src.firmware["verdict"] == "mismatch"


def test_no_reply_warns_and_continues(tmp_path):
    brd = AnswerBoard({"version": None, "sarStats": None})
    src, states = src_for("IWR1843", brd, tmp_path)
    import radar_gui.fwident as fi
    orig = fi.timeout_ms
    fi.timeout_ms = lambda fw, b: 60       # keep the test fast; the real timeout is 3000 ms
    try:
        assert configure(src) is True
    finally:
        fi.timeout_ms = orig
    assert brd.cli_log == ["version", "sarStats", "sensorStop", "flushCfg", "calibData 0 0 0", "sensorStart"]
    assert src.firmware["verdict"] == "unknown"
    assert any(s == "configuring" and "firmware not verified" in m for s, m in states)


def test_cascade_not_queried(tmp_path):
    brd = AnswerBoard({"version": "Platform : wrong\nDone\n"})
    src, _ = src_for("AWR2243_CASCADE", brd, tmp_path)
    assert configure(src) is True
    assert "version" not in brd.cli_log and src.firmware["verdict"] == "skipped"


def test_skip_box_writes_no_version(tmp_path):
    brd = AnswerBoard({"version": "Platform : wrong\nDone\n", "sarStats": "Done\n"})
    src, _ = src_for("IWR1843", brd, tmp_path, skip_firmware_check=True)
    assert configure(src) is True
    assert "version" not in brd.cli_log and "sarStats" not in brd.cli_log and src.firmware is None


def test_api_wrong_firmware_status_and_firmware_in_describe(tmp_path):
    from functools import partial

    from fastapi.testclient import TestClient

    from radar_gui.app import create_app
    from radar_gui.sources import MockSource

    user = tmp_path / "user"
    user.mkdir()
    cfg_file(user, "rig1843.cfg")
    brd = FakeBoard()     # answers Done to version: not the demo
    factory = partial(SerialSource, opener=brd.opener, exists=brd.exists, check=lambda p: None, settle_s=0.01, poll_s=0.01)
    c = TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, serial_factory=factory))
    body = {"kind": "serial", "board": "IWR1843", "cfg_id": "user:rig1843.cfg", "cli_port": "/dev/ttyACM0", "data_port": "/dev/ttyACM1"}
    try:
        with c:
            assert c.post("/api/source", json=body).status_code == 200
            import time
            for _ in range(100):
                j = c.get("/api/source").json()
                if j.get("source_state") == "wrong_firmware":
                    break
                time.sleep(0.05)
            assert j["source_state"] == "wrong_firmware" and j["firmware"]["verdict"] == "mismatch"
            assert "sensorStart" not in brd.cli_log
            assert c.post("/api/source", json={**body, "skip_firmware_check": True}).status_code == 200
    finally:
        ports.radar_lock.release()
