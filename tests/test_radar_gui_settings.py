"""gui-32: Settings tab API. Hardware-free: a fake /dev/serial/by-id mirroring the bench (symlinks to plain files in
tmp_path, never a real port) and host_setup's FakeHost fixtures for the DCA checks."""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from radar_gui import settings
from test_host_setup import bench_host

X05 = "usb-Texas_Instruments_XDS110__03.00.00.05__Embed_with_CMSIS-DAP_R2101050"
X29 = "usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000"


def make_by_id(tmp_path, names_to_tty):
    d, dev = tmp_path / "by-id", tmp_path / "dev"
    d.mkdir(); dev.mkdir()
    for name, tty in names_to_tty.items():
        (dev / tty).write_text("")
        os.symlink(dev / tty, d / name)
    return d, dev


def client(by_id, host=None, proc=None, tmp=None):
    app = FastAPI()
    app.include_router(settings.make_router((lambda: host) if host else settings.hs.Host, str(by_id), str(proc or tmp / "proc")))
    return TestClient(app)


@pytest.fixture
def bench(tmp_path):
    d, dev = make_by_id(tmp_path, {X05 + "-if00": "ttyACM0", X05 + "-if03": "ttyACM1",
                                   X29 + "-if00": "ttyACM2", X29 + "-if03": "ttyACM3"})
    return d, dev, tmp_path


def test_ports_grouped_by_board(bench):
    d, dev, tmp = bench
    j = client(d, tmp=tmp).get("/api/settings/ports").json()
    b = {x["serial"]: x for x in j["boards"]}
    assert set(b) == {"R2101050", "00000000"} and j["present"]
    one = b["R2101050"]
    assert not one["cascade"] and one["label"] == "XDS110 board"
    assert [(p["interface"], p["role"], os.path.basename(p["tty"])) for p in one["ports"]] == [("00", "cli", "ttyACM0"), ("03", "data", "ttyACM1")]
    assert one["ports"][0]["by_id"] == f"{d}/{X05}-if00" and one["ports"][0]["holders"] == []
    c = b["00000000"]
    assert c["cascade"] and "AWR2243_CASCADE_cascade_ddm_shortrange.json" in c["label"]
    assert [(p["role"], os.path.basename(p["tty"])) for p in c["ports"]] == [("cli", "ttyACM2"), ("data", "ttyACM3")]


def test_port0_suffix_and_non_xds(tmp_path):
    d, _ = make_by_id(tmp_path, {X05 + "-if00-port0": "ttyACM0", "usb-FTDI_FT232R_USB_UART_A1234-if00-port0": "ttyUSB0"})
    j = client(d, tmp=tmp_path).get("/api/settings/ports").json()
    b = {x["serial"]: x for x in j["boards"]}
    assert b["R2101050"]["ports"][0]["role"] == "cli"
    assert b["A1234"]["xds110"] is False and b["A1234"]["ports"][0]["role"] == "" and b["A1234"]["label"] == "USB serial device"


def test_holder_reported(bench):
    d, dev, tmp = bench
    proc = tmp / "proc" / "4242"; (proc / "fd").mkdir(parents=True)
    os.symlink(dev / "ttyACM1", proc / "fd" / "7")
    (proc / "comm").write_text("CPSL_TI_Radar\n")
    j = client(d, tmp=tmp).get("/api/settings/ports").json()
    data = [p for b in j["boards"] if b["serial"] == "R2101050" for p in b["ports"] if p["role"] == "data"][0]
    assert data["holders"] == [{"pid": 4242, "comm": "CPSL_TI_Radar"}]


def test_no_boards(tmp_path):
    d = tmp_path / "by-id"; d.mkdir()
    j = client(d, tmp=tmp_path).get("/api/settings/ports").json()
    assert j["boards"] == [] and j["present"]
    j = client(tmp_path / "missing", tmp=tmp_path).get("/api/settings/ports").json()
    assert j["boards"] == [] and not j["present"]


def test_dca_ok_and_candidates():
    h = bench_host()
    j = client("/x", host=h, proc="/x").get("/api/settings/dca?nic=enp3s0").json()
    assert j["candidates"] == ["enp3s0"] and not j["ping"]
    nic, sysctl = j["checks"]
    assert nic["name"] == "dca-nic" and "192.168.33.30/24" in nic["detail"]
    assert sysctl["name"] == "sysctl" and "134217728" in sysctl["detail"]
    assert ("ping", "-c", "1", "-W", "1", "192.168.33.180") not in h.calls and h.executed == []


def test_dca_ping_only_on_request_and_text_fixes():
    h = bench_host()
    j = client("/x", host=h, proc="/x").get("/api/settings/dca?nic=enp3s0&ping=1").json()
    assert ("ping", "-c", "1", "-W", "1", "192.168.33.180") in h.calls
    assert any("does not answer ping" in n for n in j["checks"][0]["notes"])
    sysctl = j["checks"][1]
    assert sysctl["status"] == "MISSING" and sysctl["fix_cmds"] and all(isinstance(s, str) for s in sysctl["fix_cmds"])
    assert h.executed == []  # fixes are text only


def test_dca_unconfirmed_candidate_and_bad_nic():
    h = bench_host()
    j = client("/x", host=h, proc="/x").get("/api/settings/dca").json()
    assert "NOT confirmed" in j["checks"][0]["detail"]
    r = client("/x", host=h, proc="/x").get("/api/settings/dca?nic=wlp1s0;rm")
    assert r.status_code == 422


def test_routes_mounted_in_app():
    from radar_gui.app import create_app
    from radar_gui.sources import MockSource
    paths = set(create_app(MockSource()).openapi()["paths"])
    assert {"/api/settings/ports", "/api/settings/dca"} <= paths
