"""Settings tab backend: read-only host facts for bench setup.

GET /api/settings/ports  radar serial ports grouped by board (from /dev/serial/by-id names; nothing is opened)
GET /api/settings/dca    DCA1000 host checks (NIC address, rmem_max, optional FPGA ping) reusing tools/setup/host_setup.py

Nothing here writes to a port, runs sudo or changes host settings: the fix commands the checks report are returned as text.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

from . import ports as portmod

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "setup"))
import host_setup as hs  # noqa: E402

BY_ID = "/dev/serial/by-id"
CASCADE_SERIAL = "00000000"  # the cascade's XDS110 reports serial 00000000 (config/system/AWR2243_CASCADE_cascade_ddm_shortrange.json)
# usb-<vendor>_<product...>_<SERIAL>-if<NN>[-port0]: the serial is the last "_" field
NAME = re.compile(r"^usb-(?P<dev>.+)_(?P<serial>[^_]+)-if(?P<ifn>[0-9a-fA-F]{2})(?:-port\d+)?$")


def scan_ports(by_id_dir: str = BY_ID, proc: str = "/proc", host: hs.Host | None = None, radar_dir: str | None = None) -> dict:
    host = host or hs.Host()
    names = host.listdir(by_id_dir)
    groups: dict = {}
    for n in names:
        path = f"{by_id_dir}/{n}"
        m = NAME.match(n)
        serial, ifn = (m["serial"], m["ifn"]) if m else (n, "")
        dev = m["dev"] if m else n
        model = next((k for k in hs.RADAR_MODELS if k in dev.lower()), None)   # "xds110" / "cp2105" in the by-id name
        g = groups.setdefault((serial, model), {"serial": serial, "device": dev, "model": model,
                                                "xds110": model == "xds110", "ports": []})
        role = hs.RADAR_MODELS[model][2].get(ifn, "") if model else ""
        g["ports"].append({"by_id": path, "tty": host.realpath(path), "interface": ifn, "role": role,
                           "holders": [{"pid": p, "comm": c} for p, c in portmod.holders(path, proc)]})
    out = []
    for g in groups.values():
        g["ports"].sort(key=lambda p: p["interface"])
        g["cascade"] = g["serial"] == CASCADE_SERIAL
        g["label"] = ("cascade (per AWR2243_CASCADE_cascade_ddm_shortrange.json)" if g["cascade"]
                      else f"{g['model'].upper()} board" if g["model"] else "USB serial device")
        out.append(g)
    out.sort(key=lambda g: g["serial"])
    from .session_cfg import radar_links
    return {"by_id_dir": by_id_dir, "present": bool(host.exists(by_id_dir)), "boards": out,
            "radar_links": [{"id": k, "cli": c, "data": d} for k, (c, d) in radar_links(radar_dir).items()]}


HOST_ONLY = ("sysctl", "dca-nic", "firewall", "udev")   # state lives on the host, not in a container's filesystem


def _host_only(c: dict) -> dict:
    """In a container a failing host-only check is not evidence the host is misconfigured (e.g. /etc/sysctl.d/99-radar.conf
    exists only on the host): show INFO + the fix command(s) verbatim; the runtime-value detail is kept."""
    if c["name"] not in HOST_ONLY or c["status"] in (hs.OK, hs.NA):
        return c
    cmds = [*c.get("fix_cmds", []), *c.get("manual", [])]
    if not cmds:
        return c
    return {**c, "status": "INFO", "fix_cmds": [], "manual": ["run on the host:", *cmds]}


def dca_checks(host: hs.Host, nic: str | None = None, ping: bool = False, container: bool | None = None) -> dict:
    cands = hs.ethernet_candidates(host)
    if nic is not None and nic not in cands:
        raise ValueError(f"{nic!r} is not a wired ethernet interface on this host (candidates: {', '.join(cands) or 'none'})")
    checks = [hs.check_dca_nic(host, nic, confirm=None, ping=ping).to_dict(),
              hs.check_sysctl(host).to_dict(),
              hs.check_firewall(host, nic).to_dict()]
    from .configs_api import in_container
    if in_container() if container is None else container:
        checks = [_host_only(c) for c in checks]
    return {"candidates": cands, "nic": nic, "ping": ping, "in_container": bool(in_container() if container is None else container),
            "checks": checks}


def make_router(host_factory=hs.Host, by_id_dir: str = BY_ID, proc: str = "/proc", radar_dir: str | None = None) -> APIRouter:
    r = APIRouter()

    @r.get("/api/settings/ports")
    def ports():
        return scan_ports(by_id_dir, proc, host_factory(), radar_dir)

    @r.get("/api/settings/dca")
    def dca(nic: str | None = None, ping: int = 0):
        try:
            return dca_checks(host_factory(), nic or None, bool(ping))
        except ValueError as e:
            raise HTTPException(422, str(e))

    return r
