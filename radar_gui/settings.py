"""Settings tab backend (gui-32): read-only host facts for bench setup.

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


def scan_ports(by_id_dir: str = BY_ID, proc: str = "/proc", host: hs.Host | None = None) -> dict:
    host = host or hs.Host()
    names = host.listdir(by_id_dir)
    groups: dict = {}
    for n in names:
        path = f"{by_id_dir}/{n}"
        m = NAME.match(n)
        serial, ifn = (m["serial"], m["ifn"]) if m else (n, "")
        dev = m["dev"] if m else n
        xds = "XDS110" in dev
        g = groups.setdefault(serial, {"serial": serial, "device": dev, "xds110": xds, "ports": []})
        role = hs.XDS110_IFACES.get(ifn, "") if xds else ""
        g["ports"].append({"by_id": path, "tty": host.realpath(path), "interface": ifn, "role": role,
                           "holders": [{"pid": p, "comm": c} for p, c in portmod.holders(path, proc)]})
    out = []
    for g in groups.values():
        g["ports"].sort(key=lambda p: p["interface"])
        g["cascade"] = g["serial"] == CASCADE_SERIAL
        g["label"] = ("cascade (per AWR2243_CASCADE_cascade_ddm_shortrange.json)" if g["cascade"]
                      else "XDS110 board" if g["xds110"] else "USB serial device")
        out.append(g)
    out.sort(key=lambda g: g["serial"])
    return {"by_id_dir": by_id_dir, "present": bool(host.exists(by_id_dir)), "boards": out}


def dca_checks(host: hs.Host, nic: str | None = None, ping: bool = False) -> dict:
    cands = hs.ethernet_candidates(host)
    if nic is not None and nic not in cands:
        raise ValueError(f"{nic!r} is not a wired ethernet interface on this host (candidates: {', '.join(cands) or 'none'})")
    return {"candidates": cands, "nic": nic, "ping": ping,
            "checks": [hs.check_dca_nic(host, nic, confirm=None, ping=ping).to_dict(),
                       hs.check_sysctl(host).to_dict()]}


def make_router(host_factory=hs.Host, by_id_dir: str = BY_ID, proc: str = "/proc") -> APIRouter:
    r = APIRouter()

    @r.get("/api/settings/ports")
    def ports():
        return scan_ports(by_id_dir, proc, host_factory())

    @r.get("/api/settings/dca")
    def dca(nic: str | None = None, ping: int = 0):
        try:
            return dca_checks(host_factory(), nic or None, bool(ping))
        except ValueError as e:
            raise HTTPException(422, str(e))

    return r
