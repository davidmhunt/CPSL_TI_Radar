"""Runtime source switching: GET/POST /api/source, POST /api/source/stop, GET /api/source/boards."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import driver as driver_mod
from . import session_cfg
from .sources import MockSource, ReplaySource, detect_dialect

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def dump_dir() -> Path:
    """GUI-owned directory of extra replayable captures (runs/ is gitignored)."""
    return Path(os.environ.get("RADAR_GUI_DUMP_DIR") or REPO / "runs" / "gui" / "dumps")


RUN_CAPTURE = "serial_data.bin"   # the driver's raw data-port bytes (output.save_serial_bytes), one per run folder
_BOARD_DIALECT = {"IWR1443": "sdk2", "AWR2243_CASCADE": "mcuplus_cascade"}


def run_dialect(run_dir: Path) -> str:
    """TLV dialect of a run folder's capture, from the board named in its session.json (default sdk3)."""
    try:
        b = json.loads((run_dir / "session.json").read_text()).get("board")
    except (OSError, ValueError, AttributeError):
        return "sdk3"
    return _BOARD_DIALECT.get(Path(str(b)).stem, "sdk3") if isinstance(b, str) else "sdk3"


def run_captures(root: Path) -> list[dict]:
    """<root>/<run>/serial_data.bin for every run folder (newest first); dumps/ is not a run folder."""
    out = []
    if root.is_dir():
        for d in sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and p.name != "dumps"), reverse=True):
            f = d / RUN_CAPTURE
            if f.is_file() and not f.is_symlink():
                out.append({"path": str(f.resolve()), "name": f"{d.name}/{RUN_CAPTURE}", "group": "runs", "dialect": run_dialect(d)})
    return out


def replay_files(extra=None, runs_root=None) -> list[dict]:
    """The replay allowlist: tests/fixtures/**/*.bin, the dumps dir's *.bin, the run folders' serial_data.bin and the file the
    GUI was started with."""
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
    for c in run_captures(Path(runs_root or driver_mod.run_root())):
        if Path(c["path"]) not in seen:
            seen.add(Path(c["path"]))
            out.append(c)
    if extra:
        add(extra, "startup")
    return out


class SourceReq(BaseModel):
    kind: Literal["mock", "replay", "serial"]   # "serial" only to answer 410
    file: str | None = None            # replay: TLV dump (default: the one the GUI was started with)
    dialect: Literal["sdk2", "sdk3", "mcuplus_cascade"] | None = None   # replay: TLV dialect (default: from the file name)
    rate_hz: float = 10.0


def make_router(hub, user_dir=None, run_root=None) -> APIRouter:
    r = APIRouter()

    def describe():
        s = hub.source
        out = {"kind": s.name, "spec": hub.spec, "status": hub.status, "info": s.info}
        for k in ("state", "msg"):
            if hasattr(s, k):
                out["source_" + k] = getattr(s, k)
        if s.name == "driver":   # Live follows a driver run
            out.update(config=s.config, pid=s.pid, tap=s.tapped, frames_in=s.frames_in, skipped=s.skipped, hello=s.hello)
        return out

    @r.get("/api/source")
    def get_source():
        return describe()

    @r.get("/api/source/files")
    def files():
        """Replay files the GUI will accept (POST /api/source rejects any other path) and where dumps are written."""
        return {"files": [{"dialect": detect_dialect(f["name"]), **f} for f in replay_files(hub.replay_file, run_root)], "dump_dir": str(dump_dir())}

    @r.get("/api/source/boards")
    def boards():
        """Kept for old pages; the same rows as GET /api/driver/boards (without its firmware lists)."""
        keep = ("board", "once_per_boot", "cli_baud", "data_baud", "tlv_dialect", "cli_port", "data_port")
        return {"boards": [{k: b[k] for k in keep} for b in session_cfg.boards_info()]}

    def refuse_while_following():
        if hub.following_run:
            raise HTTPException(409, "Point cloud is following a driver run: stop it in the Radar tab first")

    @r.post("/api/source")
    async def set_source(req: SourceReq):
        refuse_while_following()
        spec = req.model_dump(exclude_none=True)
        if req.kind == "serial":
            raise HTTPException(410, "the Python serial source was removed: start a driver session "
                                     "(POST /api/driver/start, or Start in the Radar tab)")
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
            allowed = {f["path"]: f for f in replay_files(hub.replay_file, run_root)}
            if resolved not in allowed:
                raise HTTPException(422, "replay file not allowed: pick one from GET /api/source/files "
                                         "(tests/fixtures/*.bin or this GUI's dumps directory)")
            path = resolved
            try:
                spec["dialect"] = req.dialect or allowed[resolved].get("dialect") or detect_dialect(path)
                new = ReplaySource(path, rate_hz=req.rate_hz, dialect=spec["dialect"])
            except (OSError, ValueError) as e:
                raise HTTPException(422, f"replay: {e}") from e
            spec["file"] = str(path)
        await hub.set_source(new, spec)
        return describe()

    @r.post("/api/source/stop")
    async def stop():
        """Stop the running source. The page then shows `ended`."""
        refuse_while_following()
        await hub.stop_source()
        hub.set_status("ended", "Source stopped")
        return describe()

    return r
