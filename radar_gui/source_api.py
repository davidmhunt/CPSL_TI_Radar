"""Runtime source switching (gui-06): GET/POST /api/source, POST /api/source/stop, GET /api/source/boards."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import cfgapi
from .serial_source import PortBusy, SerialSource, SerialSourceError, load_board
from .sources import MockSource, ReplaySource

_XDS = "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.{}__Embed_with_CMSIS-DAP_{}"
# Defaults only (the bench's XDS110 interfaces); the Source card lets the user edit both ports.
DEFAULT_PORTS = {"AWR2243_CASCADE": (_XDS.format("29", "00000000") + "-if00", _XDS.format("29", "00000000") + "-if03"),
                 "IWR1843": (_XDS.format("05", "R2101050") + "-if00", _XDS.format("05", "R2101050") + "-if03")}
REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"
DUMP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def dump_dir() -> Path:
    """GUI-owned directory for serial `dump` captures (runs/ is gitignored); also replayable."""
    return Path(os.environ.get("RADAR_GUI_DUMP_DIR") or REPO / "runs" / "gui" / "dumps")


def replay_files(extra=None) -> list[dict]:
    """The replay allowlist: tests/fixtures/**/*.bin, the dumps dir's *.bin, and the file the GUI was started with."""
    out, seen = [], set()

    def add(p, group):
        p = Path(p).resolve()
        if p not in seen and p.is_file():
            seen.add(p)
            out.append({"path": str(p), "name": p.name, "group": group})
    for p in sorted(FIXTURES.rglob("*.bin")):
        add(p, "fixtures")
    dd = dump_dir()
    for p in sorted(dd.glob("*.bin")) if dd.is_dir() else []:
        add(p, "dumps")
    if extra:
        add(extra, "startup")
    return out
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
    dump: str | None = None            # serial: capture the raw data-port bytes to <dumps dir>/<this name> (a bare file name)


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

    @r.get("/api/source/files")
    def files():
        """Replay files the GUI will accept (POST /api/source rejects any other path) and where dumps are written."""
        return {"files": replay_files(hub.replay_file), "dump_dir": str(dump_dir())}

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
                resolved = str(Path(path).resolve())
            except (OSError, RuntimeError, ValueError):
                resolved = None
            if resolved not in {f["path"] for f in replay_files(hub.replay_file)}:
                raise HTTPException(422, "replay file not allowed: pick one from GET /api/source/files "
                                         "(tests/fixtures/*.bin or this GUI's dumps directory)")
            path = resolved
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
            dump = None
            if req.dump:
                if not DUMP_NAME.match(req.dump) or ".." in req.dump:
                    raise HTTPException(422, "dump must be a plain file name (letters, digits, _ . -); "
                                             "it is written under the GUI's dumps directory")
                dump_dir().mkdir(parents=True, exist_ok=True)
                dump = str(dump_dir() / req.dump)
                spec["dump"] = dump
            try:
                new = make_serial(req.board, path, cli, data, skip_configure=req.skip_configure, dump=dump)
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
