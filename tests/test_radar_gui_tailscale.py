import json
import subprocess
from types import SimpleNamespace as R

from radar_gui.__main__ import parse_args
from radar_gui.tailscale import TailscaleServe

ST = json.dumps({"BackendState": "Running", "Self": {"DNSName": "box.tn.ts.net."}})


def fake(calls, serve_status="{}", serve_rc=0, status=ST, status_rc=0, serve_err=""):
    def run(args, timeout=15):
        calls.append(args)
        if args[0] == "status":
            return R(returncode=status_rc, stdout=status, stderr="")
        if args[:2] == ["serve", "status"]:
            return R(returncode=0, stdout=serve_status, stderr="")
        return R(returncode=serve_rc, stdout="", stderr=serve_err)
    return run


def test_args():
    a = parse_args(["--source", "mock", "--port", "9000", "--tailscale"])
    assert a.tailscale and a.port == 9000 and a.host == "127.0.0.1"
    assert not parse_args([]).tailscale


def test_start_stop(capsys):
    calls = []
    t = TailscaleServe(8000, run=fake(calls))
    assert t.start() == "https://box.tn.ts.net/"
    assert ["serve", "--bg", "--yes", "--https=443", "8000"] in calls
    assert "GUI on tailnet: https://box.tn.ts.net/" in capsys.readouterr().out
    t.stop()
    assert calls[-1] == ["serve", "--https=443", "off"]
    assert not any("funnel" in c or "reset" in c for c in calls)


def test_existing_config_not_clobbered(capsys):
    calls = []
    t = TailscaleServe(8000, run=fake(calls, serve_status='{"TCP":{"443":{}}}'))
    assert t.start() is None
    t.stop()
    assert not any(c[:2] == ["serve", "--bg"] or c[-1] == "off" for c in calls)
    assert "already exists" in capsys.readouterr().out


def test_missing_binary(capsys):
    def run(args, timeout=15):
        raise FileNotFoundError
    t = TailscaleServe(8000, run=run)
    assert t.start() is None
    t.stop()
    assert "not found" in capsys.readouterr().out


def test_logged_out(capsys):
    t = TailscaleServe(8000, run=fake([], status=json.dumps({"BackendState": "NeedsLogin"})))
    assert t.start() is None
    assert "tailscale up" in capsys.readouterr().out


def test_operator_hint(capsys):
    calls = []
    t = TailscaleServe(8000, run=fake(calls, serve_rc=1, serve_err="Access denied: serve config denied"))
    assert t.start() is None
    assert "set --operator" in capsys.readouterr().out
    t.stop()
    assert calls[-1][0] == "serve" and calls[-1][-1] != "off"


def test_timeout(capsys):
    def run(args, timeout=15):
        raise subprocess.TimeoutExpired("tailscale", 15)
    assert TailscaleServe(8000, run=run).start() is None
