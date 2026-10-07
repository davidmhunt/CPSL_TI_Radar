"""HTTP API for driver run control (gui-05): /api/driver/{configs,validate,start,stop,status}."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import cfgapi, session_cfg, sysjson
from .cfgapi import DEFAULT_USER_DIR
from .driver import REPO, DriverError, DriverManager

DEFAULT_SYSTEM_DIR = REPO / "CPSL_TI_Radar_cpp" / "config" / "system"


class ConfigReq(BaseModel):
    config: str                                  # a path listed by GET /api/driver/configs


class Overrides(BaseModel):
    """What a start may change in a saved config (gui-37). null = leave the saved value."""
    model_config = ConfigDict(extra="forbid")
    save_adc_frames: bool | None = None
    save_raw_lvds: bool | None = None
    save_serial_bytes: bool | None = None        # needs caps.save_serial_bytes
    skip_configure: bool | None = None
    firmware_check: Literal["auto", "warn", "off"] | None = None
    log_level: Literal["debug", "info", "warn", "error"] | None = None


class Setup(Overrides):
    """A quick setup: no saved system JSON, the page picks board, firmware, cfg and ports."""
    board: str
    cfg_id: str                                  # an id from GET /api/cfgs (shipped or config/user/)
    firmware: str | None = None                  # default: the board's first
    cli_port: str | None = None
    data_port: str | None = None
    serial: bool | None = None                   # null = the firmware's default
    dca1000: bool | None = None                  # null = the firmware's default; true only where it streams LVDS
    fpga_ip: str | None = None
    host_ip: str | None = None
    cmd_port: int | None = Field(None, ge=1, le=65535)
    data_udp_port: int | None = Field(None, ge=1, le=65535)


class SaveConfigReq(BaseModel):
    config: str                                  # a path listed by GET /api/driver/configs
    overrides: Overrides
    mode: Literal["inplace", "copy"] = "inplace"
    name: str | None = None                      # copy: the new file's name in config/user/


class StartReq(BaseModel):
    config: str | None = None                    # a saved system JSON listed by GET /api/driver/configs ...
    overrides: Overrides | None = None
    setup: Setup | None = None                   # ... or a quick setup (exactly one of the two)
    frames: int | None = Field(None, ge=1)
    duration: float | None = Field(None, gt=0)
    skip_configure: bool = False   # the board was already configured this power-up (once-per-boot boards): just stream
    adc_every: int | None = Field(None, ge=0)   # gui-07 ADC views: null = every frame (K=1), 0 = off, K = every K-th frame


def once_per_boot(board) -> bool:
    """Board accepts a cfg once per power-up (config/boards/<board>.json lifecycle.config_once_per_boot)."""
    try:
        p = REPO / "CPSL_TI_Radar_cpp" / "config" / "boards" / f"{board}.json"
        return bool(board and "/" not in board and json.loads(p.read_text()).get("lifecycle", {}).get("config_once_per_boot"))
    except (OSError, ValueError, AttributeError):
        return False


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
                o = j.get("output") if isinstance(j.get("output"), dict) else {}
                out.append({"name": p.stem, "group": group, "path": rel, "board": j.get("board"),
                            "once_per_boot": once_per_boot(j.get("board")),
                            # what the file records on its own (gui-37: the Radar tab's recording boxes start from these)
                            "saves": {k: bool(o.get(k)) for k in session_cfg.SAVE_KEYS},
                            "dca": bool((j.get("dca1000") or {}).get("enabled")),
                            "serial": bool((j.get("serial_stream") or {}).get("enabled"))})
    return out


def make_router(mgr: DriverManager, user_dir=None, system_dir=None) -> APIRouter:
    user_dir = Path(user_dir or os.environ.get("RADAR_GUI_USER_CFG_DIR") or DEFAULT_USER_DIR)
    system_dir = Path(system_dir) if system_dir else DEFAULT_SYSTEM_DIR
    r = APIRouter(prefix="/api/driver")

    def resolve(config: str) -> Path:
        """Only files that GET /api/driver/configs lists may be run: the API is reachable over a tailnet."""
        p = (REPO / config).resolve()
        listed = {(REPO / c["path"]).resolve() for c in list_configs(user_dir, system_dir)}
        if p not in listed:
            raise HTTPException(422, f"{config!r} is not a system config in config/user or config/system")
        return p

    def cfg_path(cfg_id: str) -> Path:
        """A cfg id of GET /api/cfgs ("driver:...", "viewer:...", "user:...") -> its .cfg file, inside that tree only."""
        group, _, rel = cfg_id.partition(":")
        root = {**cfgapi.SHIPPED, "user": Path(user_dir)}.get(group)
        if root is None or not rel:
            raise HTTPException(422, f"unknown cfg id {cfg_id!r}")
        p = (root / rel).resolve()
        if root.resolve() not in p.parents or p.suffix != ".cfg" or not p.is_file():
            raise HTTPException(422, f"no such cfg {cfg_id!r}")
        return p

    def call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except DriverError as e:
            raise HTTPException(e.status, str(e))

    @r.get("/configs")
    def configs():
        return {"configs": list_configs(user_dir, system_dir), "caps": mgr.caps()}

    @r.get("/boards")
    def boards():
        """Quick-setup data: per board its serial defaults and firmwares (what each outputs). The same board fields as
        GET /api/source/boards, plus `default_firmware` and `firmwares`."""
        return {"boards": session_cfg.boards_info()}

    @r.post("/validate")
    def validate(req: ConfigReq):
        return call(mgr.validate, resolve(req.config))

    @r.post("/start")
    def start(req: StartReq):
        if (req.config is None) == (req.setup is None):
            raise HTTPException(422, "give exactly one of config (a saved system JSON) or setup (a quick setup)")
        if req.setup is not None:
            if req.overrides is not None:
                raise HTTPException(422, "overrides apply to a saved config; a setup carries its own options")
            setup = req.setup.model_dump(exclude_none=True)
            setup["cfg_path"] = str(cfg_path(setup.pop("cfg_id")))
            return call(mgr.start, None, req.frames, req.duration, req.skip_configure, req.adc_every, setup=setup)
        ov = req.overrides.model_dump(exclude_none=True) if req.overrides else None
        return call(mgr.start, resolve(req.config), req.frames, req.duration, req.skip_configure, req.adc_every, overrides=ov)

    @r.post("/config/save")
    def save_config(req: SaveConfigReq):
        """Write the recording flags (and other overrides) back into a system JSON: in place for a config/user file (the old
        bytes stay as <name>.json.bak), as a new config/user file for a shipped one or on request. Re-validates the result."""
        src = resolve(req.config)
        ov, kc = req.overrides.model_dump(exclude_none=True), mgr.caps()
        ov.pop("skip_configure", None)    # a per-start choice, not a stored setting
        try:
            if req.mode == "inplace":
                if user_dir.resolve() not in src.parents:
                    raise HTTPException(422, "shipped configs are never overwritten: use mode=copy (Save as copy in config/user/)")
                dst = sysjson.update_user_json(src, user_dir, ov, kc)
            else:
                dst = sysjson.copy_to_user(src, user_dir, req.name or "", ov, kc)
        except sysjson.SysJsonError as e:
            raise HTTPException(e.status, str(e))
        try:
            rel = str(dst.relative_to(REPO))
        except ValueError:
            rel = str(dst)
        try:
            val = mgr.validate(dst)
        except DriverError as e:
            val = {"ok": False, "text": str(e)}
        return {"path": rel, "mode": req.mode, "backup": rel + ".bak" if req.mode == "inplace" else None, "validate": val}

    @r.post("/stop")
    def stop():
        return call(mgr.stop)

    @r.get("/status")
    def status():
        return mgr.status()

    return r
