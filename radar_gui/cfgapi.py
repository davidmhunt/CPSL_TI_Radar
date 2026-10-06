"""HTTP API for the Configure tab (gui-03): analyse / generate / save TI cfgs plus the driver's system JSON.

Everything here is a thin layer over `radar_gui.cfg`; no cfg maths lives in this file.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .cfg import BOARDS, CfgError, generate, limits_dict, metrics, parse_cfg, validate

REPO = Path(__file__).resolve().parent.parent
# Shipped cfg trees (read-only here) listed by GET /api/cfgs
SHIPPED = {"driver": REPO / "CPSL_TI_Radar_cpp" / "config" / "radar",
           "viewer": REPO / "tools" / "radar_viewer" / "configs"}
# Saved files go here. It is a sibling of config/boards, so a system JSON saved in it finds the board
# descriptors through the driver's default "<JSON dir>/../boards" lookup.
DEFAULT_USER_DIR = REPO / "CPSL_TI_Radar_cpp" / "config" / "user"
OUTPUT_MODES = ["tlv", "lvds", "raw"]
LOG_LEVELS = ["debug", "info", "warn", "error"]
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")


def guess_board(rel: str) -> str:
    p = rel.lower()
    if "cascade" in p or "2243" in p:
        return "AWR2243_CASCADE"
    if "1443" in p or "14xx" in p:
        return "IWR1443"
    if "6843" in p or "_ods" in p:
        return "IWR6843"
    return "IWR1843"


class AnalyzeReq(BaseModel):
    board: str
    cfg_text: str | None = None            # analyse this cfg ...
    targets: dict | None = None            # ... or generate one from these targets


class SaveReq(BaseModel):
    board: str
    name: str                              # base name, no extension; used for both files
    cfg_text: str
    force: bool = False                    # save even when validate() reports an error
    cli_port: str = "/dev/ttyACM0"
    serial_enabled: bool = True
    data_port: str = "/dev/ttyACM1"
    dca1000_enabled: bool = False
    fpga_ip: str = "192.168.33.180"
    host_ip: str = "192.168.33.30"
    cmd_port: int = Field(4096, ge=1, le=65535)
    data_udp_port: int = Field(4098, ge=1, le=65535)
    save_adc_frames: bool = False
    save_raw_lvds: bool = False
    log_level: str = "info"


def _bad_board(board):
    if board not in BOARDS:
        raise HTTPException(422, f"unknown board {board!r}; one of {list(BOARDS)}")


def _analyze_text(board: str, text: str) -> dict:
    try:
        cfg = parse_cfg(text)
        rep = validate(cfg, board)
    except CfgError as e:
        return {"board": board, "ok": False, "source": "cfg", "text": text, "metrics": None,
                "issues": [{"level": "error", "code": "parse", "message": str(e), "source": "", "confidence": ""}]}
    d = rep.to_dict()
    return {"board": board, "ok": d["ok"], "source": "cfg", "text": text, "metrics": d["metrics"],
            "issues": d["issues"]}


def system_json(req: SaveReq, cfg_name: str) -> dict:
    """The driver's schema v2 (docs/ARCHITECTURE.md "Configuration"); paths resolve against the JSON's dir."""
    return {
        "schema_version": 2,
        "board": req.board,
        "radar_cfg": cfg_name,
        "cli": {"port": req.cli_port},
        "serial_stream": {"enabled": req.serial_enabled, "port": req.data_port},
        "dca1000": {"enabled": req.dca1000_enabled, "fpga_ip": req.fpga_ip, "host_ip": req.host_ip,
                    "cmd_port": req.cmd_port, "data_port": req.data_udp_port},
        "output": {"save_adc_frames": req.save_adc_frames, "save_raw_lvds": req.save_raw_lvds},
        "runtime": {"log_level": req.log_level},
    }


def make_router(user_dir: Path | None = None) -> APIRouter:
    udir = Path(user_dir) if user_dir else Path(os.environ.get("RADAR_GUI_USER_CFG_DIR") or DEFAULT_USER_DIR)
    r = APIRouter()

    def roots():
        return {**SHIPPED, "user": udir}

    @r.get("/api/cfg/boards")
    def boards():
        return {"boards": list(BOARDS), "output_modes": OUTPUT_MODES, "log_levels": LOG_LEVELS,
                "limits": limits_dict(), "user_dir": str(udir)}

    @r.post("/api/cfg/analyze")
    def analyze(req: AnalyzeReq):
        _bad_board(req.board)
        if req.cfg_text is not None:
            return _analyze_text(req.board, req.cfg_text)
        if req.targets is not None:
            return _generated(req.board, req.targets)
        raise HTTPException(422, "give cfg_text or targets")

    def _generated(board, targets):
        g = generate(board, targets).to_dict()
        return {"board": board, "ok": g["ok"], "source": "targets", "text": g["text"], "name": g["name"],
                "metrics": g["metrics"], "issues": g["report"]["issues"], "achieved": g["achieved"],
                "targets": g["targets"]}

    @r.post("/api/cfg/generate")
    def gen(req: AnalyzeReq):
        _bad_board(req.board)
        return _generated(req.board, req.targets or {})

    @r.get("/api/cfgs")
    def cfgs():
        out = []
        for group, root in roots().items():
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*.cfg")):
                rel = p.relative_to(root).as_posix()
                out.append({"id": f"{group}:{rel}", "group": "user" if group == "user" else "shipped",
                            "name": rel, "board": guess_board(rel)})
        return {"cfgs": out, "user_dir": str(udir)}

    @r.get("/api/cfg/file")
    def cfg_file(id: str):
        group, _, rel = id.partition(":")
        root = roots().get(group)
        if root is None or not rel:
            raise HTTPException(404, "unknown cfg id")
        p = (root / rel).resolve()
        if root.resolve() not in p.parents or p.suffix != ".cfg" or not p.is_file():
            raise HTTPException(404, "no such cfg")
        return {"id": id, "name": rel, "board": guess_board(rel), "text": p.read_text(errors="replace")}

    @r.post("/api/cfg/save")
    def save(req: SaveReq):
        _bad_board(req.board)
        if not _NAME.match(req.name) or req.name.endswith("."):
            raise HTTPException(422, "name: letters, digits, '_', '-', '.', must start with a letter or digit")
        if req.log_level not in LOG_LEVELS:
            raise HTTPException(422, f"log_level must be one of {LOG_LEVELS}")
        res = _analyze_text(req.board, req.cfg_text)
        if not res["ok"] and not req.force:
            raise HTTPException(422, {"message": "cfg has error-level issues (set force to save anyway)",
                                      "issues": res["issues"]})
        cfg_path, json_path = udir / f"{req.name}.cfg", udir / f"{req.name}.json"
        udir.mkdir(parents=True, exist_ok=True)
        text = req.cfg_text if req.cfg_text.endswith("\n") else req.cfg_text + "\n"
        try:   # "x" = fail if present: a new name is the only way to write, shipped or user file alike
            with open(cfg_path, "x") as f:
                try:
                    with open(json_path, "x") as j:
                        json.dump(system_json(req, cfg_path.name), j, indent=4)
                        j.write("\n")
                except FileExistsError:
                    f.close()
                    cfg_path.unlink()
                    raise
                f.write(text)
        except FileExistsError:
            raise HTTPException(409, f"{req.name}.cfg / {req.name}.json already exists in {udir}; pick a new name") from None
        return {"ok": True, "cfg_path": str(cfg_path), "json_path": str(json_path), "issues": res["issues"],
                "validate_cmd": f"CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP {json_path} --validate"}

    return r
