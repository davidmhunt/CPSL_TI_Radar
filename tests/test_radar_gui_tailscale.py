import json
import subprocess
from types import SimpleNamespace as R

from radar_gui.__main__ import parse_args
import socket

import pytest

from radar_gui.tailscale import TailscaleServe, bind_addresses, bind_sockets

ST = json.dumps({"BackendState": "Running", "Self": {"DNSName": "box.tn.ts.net.", "TailscaleIPs": ["100.1.2.3", "fd7a::1"]}, "CertDomains": ["box.tn.ts.net"]})


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
    assert parse_args(["--tailscale"]).tailscale == "bind"
    assert parse_args(["--tailscale=serve"]).tailscale == "serve"
    assert parse_args(["--tailscale-serve"]).tailscale == "serve"


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


def test_stop_falls_back_to_reset_when_off_fails():
    calls = []
    base = fake(calls)

    def run(args, timeout=15):
        if args[-1] == "off":
            calls.append(args)
            return R(returncode=1, stdout="", stderr="unknown")
        return base(args, timeout)
    t = TailscaleServe(8000, run=run)
    assert t.start()
    t.stop()
    assert calls[-2] == ["serve", "--https=443", "off"] and calls[-1] == ["serve", "reset"]


def test_stop_no_reset_when_not_ours():
    calls = []
    t = TailscaleServe(8000, run=fake(calls, serve_status='{"TCP":{"443":{}}}'))
    t.start()
    t.stop()
    assert ["serve", "reset"] not in calls


def test_bind_addresses_picks_ipv4_and_short_name():
    assert bind_addresses(run=fake([])) == ("100.1.2.3", "box", None)


def test_bind_addresses_falls_back_to_ip_cmd():
    calls = []
    st = json.dumps({"BackendState": "Running", "Self": {"DNSName": "", "TailscaleIPs": []}})
    base = fake(calls, status=st)

    def run(args, timeout=15):
        if args == ["ip", "-4"]:
            return R(returncode=0, stdout="100.9.9.9\n", stderr="")
        return base(args, timeout)
    assert bind_addresses(run=run) == ("100.9.9.9", None, None)


@pytest.mark.parametrize("status,rc,word", [
    (json.dumps({"BackendState": "NeedsLogin"}), 0, "tailscale up"),
    ("", 1, "not reachable"),
    (json.dumps({"BackendState": "Running", "Self": {"TailscaleIPs": []}}), 0, "no Tailscale IPv4"),
])
def test_bind_addresses_reasons(status, rc, word):
    def run(args, timeout=15):
        return R(returncode=rc if args[0] == "status" else 1, stdout=status if args[0] == "status" else "", stderr="")
    ip, _, why = bind_addresses(run=run)
    assert ip is None and word in why


def test_bind_addresses_missing_binary():
    def run(args, timeout=15):
        raise FileNotFoundError
    assert "not found" in bind_addresses(run=run)[2]


def test_bind_sockets_same_port_loopback_only_and_no_wildcard():
    socks = bind_sockets("127.0.0.1", 0, "127.0.0.1")
    try:
        assert all(s.getsockname()[0] == "127.0.0.1" for s in socks) and len(socks) == 2
    finally:
        for s in socks:
            s.close()
    for bad in ("0.0.0.0", ""):
        with pytest.raises(ValueError):
            bind_sockets("127.0.0.1", 0, bad)


def test_bind_sockets_closes_on_failure():
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    try:
        with pytest.raises(OSError):
            bind_sockets("127.0.0.1", blocker.getsockname()[1], "127.0.0.1")
    finally:
        blocker.close()


def test_serve_requires_cert_domains(capsys):
    calls = []
    st = json.dumps({"BackendState": "Running", "CertDomains": None,
                     "Self": {"DNSName": "box.tn.ts.net."}})
    assert TailscaleServe(8000, run=fake(calls, status=st)).start() is None
    out = capsys.readouterr().out
    assert "HTTPS certificates are not enabled" in out and "plain --tailscale" in out
    assert not any(c[:2] == ["serve", "--bg"] for c in calls)


def test_serve_failure_surfaces_stderr(capsys):
    t = TailscaleServe(8000, run=fake([], serve_rc=1, serve_err="line one\nAccess denied: x"))
    assert t.start() is None
    out = capsys.readouterr().out
    assert "line one | Access denied: x" in out and "Serving locally only" in out
