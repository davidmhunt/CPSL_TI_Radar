"""HTTP API for driver run control (gui-05): /api/driver/{configs,validate,start,stop,status}."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .cfgapi import DEFAULT_USER_DIR
from .driver import REPO, DriverError, DriverManager

DEFAULT_SYSTEM_DIR = REPO / "CPSL_TI_Radar_cpp" / "config" / "system"


class ConfigReq(BaseModel):
    config: str                                  # a path listed by GET /api/driver/configs


class StartReq(ConfigReq):
    frames: int | None = Field(None, ge=1)
    duration: float | None = Field(None, gt=0)


def list_configs(user_dir: Path, system_dir: Path) -> list[dict]:
    out = []
    for group, d in (("user", user_dir), ("system", system_dir)):
        for p in sorted(Path(d).glob("*.json")) if Path(d).is_dir() else []:
            try:
                j = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(j, dict) and "radar_cfg" in j:
                try:
                    rel = str(p.resolve().relative_to(REPO))
                except ValueError:
                    rel = str(p.resolve())
                out.append({"name": p.stem, "group": group, "path": rel, "board": j.get("board")})
    return out


def make_router(mgr: DriverManager, user_dir=None, system_dir=None) -> APIRouter:
    user_dir = Path(user_dir) if user_dir else DEFAULT_USER_DIR
    system_dir = Path(system_dir) if system_dir else DEFAULT_SYSTEM_DIR
    r = APIRouter(prefix="/api/driver")

    def resolve(config: str) -> Path:
        """Only files that GET /api/driver/configs lists may be run: the API is reachable over a tailnet."""
        p = (REPO / config).resolve()
        listed = {(REPO / c["path"]).resolve() for c in list_configs(user_dir, system_dir)}
        if p not in listed:
            raise HTTPException(422, f"{config!r} is not a system config in config/user or config/system")
        return p

    def call(fn, *a):
        try:
            return fn(*a)
        except DriverError as e:
            raise HTTPException(e.status, str(e))

    @r.get("/configs")
    def configs():
        return {"configs": list_configs(user_dir, system_dir)}

    @r.post("/validate")
    def validate(req: ConfigReq):
        return call(mgr.validate, resolve(req.config))

    @r.post("/start")
    def start(req: StartReq):
        return call(mgr.start, resolve(req.config), req.frames, req.duration)

    @r.post("/stop")
    def stop():
        return call(mgr.stop)

    @r.get("/status")
    def status():
        return mgr.status()

    return r
