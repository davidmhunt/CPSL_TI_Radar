"""Runtime source switching (gui-06): GET/POST /api/source, POST /api/source/stop, GET /api/source/boards."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import cfgapi
from .serial_source import PortBusy, SerialSource, SerialSourceError, load_board
from .sources import MockSource, ReplaySource

BY_ID = "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000"
DEFAULT_PORTS = {"AWR2243_CASCADE": (BY_ID + "-if00", BY_ID + "-if03")}   # the cascade's XDS110 interfaces
SERIAL_BOARDS = ("IWR1443", "IWR1843", "IWR6843", "IWR6843ODS", "AWR2243_CASCADE")


class SourceReq(BaseModel):
    kind: Literal["mock", "replay", "serial"]
    board: str | None = None
    cfg_id: str | None = None          # an id from GET /api/cfgs (shipped or config/user/)
    cli_port: str | None = None
    data_port: str | None = None
    skip_configure: bool = False
    file: str | None = None            # replay: TLV dump (default: the one the GUI was started with)
    rate_hz: float = 10.0
    dump: str | None = None            # serial: also write the raw data-port bytes here (fixture capture)


def make_router(hub, user_dir=None, serial_factory=None) -> APIRouter:
    udir = Path(user_dir or os.environ.get("RADAR_GUI_USER_CFG_DIR") or cfgapi.DEFAULT_USER_DIR)
    make_serial = serial_factory or SerialSource
    r = APIRouter()

    def cfg_path(cfg_id: str) -> Path:
        group, _, rel = cfg_id.partition(":")
        root = {**cfgapi.SHIPPED, "user": udir}.get(group)
        if root is None or not rel:
            raise HTTPException(422, f"unknown cfg id {cfg_id!r}")
        p = (root / rel).resolve()
        if root.resolve() not in p.parents or p.suffix != ".cfg" or not p.is_file():
            raise HTTPException(422, f"no such cfg {cfg_id!r}")
        return p

    def describe():
        s = hub.source
        out = {"kind": s.name, "spec": hub.spec, "status": hub.status, "info": s.info}
        for k in ("state", "msg"):
            if hasattr(s, k):
                out["source_" + k] = getattr(s, k)
        return out

    @r.get("/api/source")
    def get_source():
        return describe()

    @r.get("/api/source/boards")
    def boards():
        out = []
        for b in SERIAL_BOARDS:
            try:
                d = load_board(b)
            except SerialSourceError:
                continue
            cli, data = DEFAULT_PORTS.get(b, ("/dev/ttyACM0", "/dev/ttyACM1"))
            out.append({"board": b, "once_per_boot": bool(d.get("lifecycle", {}).get("config_once_per_boot")),
                        "cli_baud": d["cli"]["baud"], "data_baud": d["data_uart"]["baud"],
                        "tlv_dialect": d["data_uart"]["tlv_dialect"], "cli_port": cli, "data_port": data})
        return {"boards": out}

    @r.post("/api/source")
    async def set_source(req: SourceReq):
        spec = req.model_dump(exclude_none=True)
        if req.kind == "mock":
            new = MockSource(rate_hz=req.rate_hz)
        elif req.kind == "replay":
            path = req.file or hub.replay_file
            if not path:
                raise HTTPException(422, "replay needs a file (the GUI was not started with one)")
            try:
                new = ReplaySource(path, rate_hz=req.rate_hz)
            except (OSError, ValueError) as e:
                raise HTTPException(422, f"replay: {e}") from e
            spec["file"] = str(path)
        else:
            missing = [k for k in ("board", "cfg_id") if not getattr(req, k)]
            if missing:
                raise HTTPException(422, f"serial source needs {missing}")
            dcli, ddata = DEFAULT_PORTS.get(req.board, ("/dev/ttyACM0", "/dev/ttyACM1"))
            cli, data = req.cli_port or dcli, req.data_port or ddata
            path = cfg_path(req.cfg_id)
            if (cfgapi.guess_board(req.cfg_id.partition(":")[2]) == "AWR2243_CASCADE") != (req.board == "AWR2243_CASCADE"):
                raise HTTPException(422, f"cfg {req.cfg_id!r} is not for board {req.board}")
            spec.update(cli_port=cli, data_port=data)
            try:
                new = make_serial(req.board, path, cli, data, skip_configure=req.skip_configure, dump=req.dump)
            except SerialSourceError as e:
                raise HTTPException(422, str(e)) from e
        try:
            await hub.set_source(new, spec)
        except PortBusy as e:
            raise HTTPException(409, str(e)) from e
        return describe()

    @r.post("/api/source/stop")
    async def stop():
        """Stop the running source (a serial one releases the ports and the radar lock). The page then shows `ended`."""
        await hub.stop_source()
        hub.set_status("ended", "Source stopped")
        return describe()

    return r
