"""radar-41: stable /dev/radar port names (whitelist, defaults, Save, Devices API) and no-cache on web/ files."""
import json

import pytest
from fastapi.testclient import TestClient

from radar_gui import session_cfg
from radar_gui.app import create_app
from radar_gui.sources import MockSource


def links(d, *names):
    d.mkdir(exist_ok=True)
    for n in names:
        (d / n).symlink_to("/dev/null")
    return str(d)


@pytest.mark.parametrize("p", ["/dev/radar/R2101050-cli", "/dev/radar/R2101050-data", "/dev/ttyACM0", "/dev/serial/by-id/usb-x-if00"])
def test_port_whitelist_accepts(p):
    assert session_cfg.check_port(p, "cli_port") == p


@pytest.mark.parametrize("p", ["/dev/radar/R2101050", "/dev/radar/../sda-cli", "/dev/radar/a/b-cli", "/dev/radar/R1-cli2", "/dev/tty", "/dev/radar/-"])
def test_port_whitelist_rejects(p):
    with pytest.raises(session_cfg.SessionError, match="/dev/radar/<id>-cli"):
        session_cfg.check_port(p, "cli_port")


def test_radar_links_and_defaults(tmp_path):
    d = links(tmp_path / "radar", "R1-cli", "R1-data", "R2-cli")   # R2 has no data link: not a pair
    assert session_cfg.radar_links(d) == {"R1": (f"{d}/R1-cli", f"{d}/R1-data")}
    assert session_cfg.default_ports("IWR1843", d) == (f"{d}/R1-cli", f"{d}/R1-data")
    assert session_cfg.default_ports("AWR2243_CASCADE", d) == session_cfg.DEFAULT_PORTS["AWR2243_CASCADE"]
    d2 = links(tmp_path / "two", "A-cli", "A-data", "B-cli", "B-data")   # ambiguous: current behaviour
    assert session_cfg.default_ports("IWR1843", d2) == session_cfg.DEFAULT_PORTS["IWR1843"]
    assert session_cfg.default_ports("IWR1443", str(tmp_path / "none")) == session_cfg.FALLBACK_PORTS


def test_boards_and_save_default_to_radar_links(tmp_path, monkeypatch):
    d = links(tmp_path / "radar", "R9-cli", "R9-data")
    monkeypatch.setattr(session_cfg, "RADAR_DIR", d)
    user = tmp_path / "user"
    user.mkdir()
    with TestClient(create_app(MockSource(rate_hz=5), user_cfg_dir=user, system_cfg_dir=tmp_path / "sys",
                               run_root=tmp_path / "runs")) as c:
        b = {x["board"]: x for x in c.get("/api/driver/boards").json()["boards"]}["IWR1843"]
        assert (b["cli_port"], b["data_port"]) == (f"{d}/R9-cli", f"{d}/R9-data")
        assert c.get("/api/settings/ports").json()["radar_links"] == [{"id": "R9", "cli": f"{d}/R9-cli", "data": f"{d}/R9-data"}]
        from radar_gui import cfgapi
        doc = cfgapi.system_json(cfgapi.SaveReq(board="IWR1843", name="x", cfg_text=""), "x.cfg")
        assert doc["cli"]["port"] == f"{d}/R9-cli" and doc["serial_stream"]["port"] == f"{d}/R9-data"
        doc = cfgapi.system_json(cfgapi.SaveReq(board="IWR1843", name="x", cfg_text="", cli_port="/dev/ttyACM3"), "x.cfg")
        assert doc["cli"]["port"] == "/dev/ttyACM3"


def test_web_files_revalidate():
    with TestClient(create_app(MockSource(rate_hz=5))) as c:
        for path in ("/", "/index.html", "/js/main.js"):
            r = c.get(path)
            assert r.status_code == 200, path
            assert r.headers["cache-control"] in ("no-cache", "no-store"), path
        for path in ("/index.html", "/js/main.js"):
            r = c.get(path)
            assert r.headers["cache-control"] == "no-cache" and r.headers.get("etag")
            r2 = c.get(path, headers={"If-None-Match": r.headers["etag"]})
            assert r2.status_code == 304
