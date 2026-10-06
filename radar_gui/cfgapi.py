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

from .cfg import firmware as fwmod
from .cfg import BOARDS, CfgError, apply_params, generate, params_from_cfg, limits_dict, metrics, parse_cfg, validate

REPO = Path(__file__).resolve().parent.parent
# Shipped cfg trees (read-only here) listed by GET /api/cfgs
SHIPPED = {"driver": REPO / "CPSL_TI_Radar_cpp" / "config" / "radar",
           "viewer": REPO / "tools" / "radar_viewer" / "configs"}
# Saved files go here. It is a sibling of config/boards, so a system JSON saved in it finds the board
# descriptors through the driver's default "<JSON dir>/../boards" lookup.
DEFAULT_USER_DIR = REPO / "CPSL_TI_Radar_cpp" / "config" / "user"
# deprecated output_mode values, accepted by generate() as aliases for a firmware
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
    firmware: str | None = None            # firmware id for generation (default: the board's)


class ParamsReq(BaseModel):
    board: str
    base_cfg_text: str                     # the cfg whose profile/chirp/frame/channel lines are rewritten
    params: dict | None = None             # radar_gui.cfg.params schema; partial is fine, None = just read the base
    firmware: str | None = None


class SaveReq(BaseModel):
    board: str
    name: str                              # base name, no extension; used for both files
    cfg_text: str
    force: bool = False                    # save even when validate() reports an error
    cli_port: str = "/dev/ttyACM0"
    firmware: str | None = None            # firmware id (default: the board's); sets the enables below when they are omitted
    serial_enabled: bool | None = None     # None = the firmware's system_enables
    data_port: str = "/dev/ttyACM1"
    dca1000_enabled: bool | None = None
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


def _fw_issue(board: str, firmware: str | None) -> dict | None:
    """Error issue when `firmware` is unknown / does not support `board` / is a pending stub, else None."""
    if not firmware:
        return None
    fw = fwmod.get(firmware)
    src = f"config/firmware/{firmware}.json"
    if fw is None:
        return {"level": "error", "code": "unknown_firmware", "source": "", "confidence": "",
                "message": f"unknown firmware {firmware!r}; expected one of {list(fwmod.load_all())}"}
    if not fwmod.supports(fw, board):
        return {"level": "error", "code": "firmware_board_mismatch", "source": f"config/boards/{board}.json",
                "confidence": "repo",
                "message": f"{board} does not list firmware {firmware!r} (it lists {[d['id'] for d in fwmod.for_board(board)]})"}
    if fw.get("pending"):
        return {"level": "error", "code": "firmware_pending", "source": src, "confidence": "repo",
                "message": f"firmware {firmware!r}: {fw['pending']}"}
    return None


def _analyze_text(board: str, text: str, firmware: str | None = None) -> dict:
    pre = _fw_issue(board, firmware)
    try:
        cfg = parse_cfg(text)
        rep = validate(cfg, board, None if pre else firmware)
    except CfgError as e:
        return {"board": board, "ok": False, "source": "cfg", "text": text, "metrics": None,
                "issues": [{"level": "error", "code": "parse", "message": str(e), "source": "", "confidence": ""}]}
    d = rep.to_dict()
    issues = ([pre] if pre else []) + d["issues"]
    return {"board": board, "ok": d["ok"] and not pre, "source": "cfg", "text": text, "metrics": d["metrics"],
            "issues": issues}


def system_json(req: SaveReq, cfg_name: str) -> dict:
    """The driver's schema v2 (docs/ARCHITECTURE.md "Configuration"); paths resolve against the JSON's dir.
    serial/dca1000 enables come from the firmware descriptor unless the request sets them explicitly."""
    fw = fwmod.get(req.firmware) if req.firmware else fwmod.default_for(req.board)
    en = fw["system_enables"] if fw else {"serial": True, "dca1000": False}
    serial = en["serial"] if req.serial_enabled is None else req.serial_enabled
    dca = en["dca1000"] if req.dca1000_enabled is None else req.dca1000_enabled   # never inferred from the cfg (gui-22)
    return {
        "schema_version": 2,
        "board": req.board,
        "radar_cfg": cfg_name,
        "cli": {"port": req.cli_port},
        "serial_stream": {"enabled": serial, "port": req.data_port},
        "dca1000": {"enabled": dca, "fpga_ip": req.fpga_ip, "host_ip": req.host_ip,
                    "cmd_port": req.cmd_port, "data_port": req.data_udp_port},
        "output": {"save_adc_frames": req.save_adc_frames, "save_raw_lvds": req.save_raw_lvds},
        "runtime": {"log_level": req.log_level},
    }


def lvds_mismatch_warnings(req: SaveReq, dca: bool) -> list[str]:
    """gui-22: cfg LVDS and the DCA1000 system enable are separate settings; say so when they disagree.
    Only for a TLV firmware that has an LVDS output on this board (the demo on 1843/6843)."""
    fw = fwmod.get(req.firmware) if req.firmware else fwmod.default_for(req.board)
    if not fw or req.board not in fw["outputs"]:
        return []
    o = fw["outputs"][req.board]
    if not (o["tlv"] and o["lvds"]):
        return []
    try:
        lv = parse_cfg(req.cfg_text).first("lvdsStreamCfg")
        on = bool(lv and len(lv.args) >= 3 and int(lv.floats()[2]) != 0)
    except (CfgError, ValueError):
        return []
    if on and not dca:
        return ["The cfg turns LVDS streaming on (lvdsStreamCfg) but the DCA1000 stream is off in the system settings: "
                "the radar will stream ADC data that nothing captures."]
    if dca and not on:
        return ["The DCA1000 stream is on in the system settings but the cfg has LVDS streaming off (lvdsStreamCfg): "
                "the capture card will receive no data."]
    return []


def make_router(user_dir: Path | None = None) -> APIRouter:
    udir = Path(user_dir) if user_dir else Path(os.environ.get("RADAR_GUI_USER_CFG_DIR") or DEFAULT_USER_DIR)
    r = APIRouter()

    def roots():
        return {**SHIPPED, "user": udir}

    @r.get("/api/cfg/boards")
    def boards():
        return {"boards": list(BOARDS), "output_modes": OUTPUT_MODES,   # DEPRECATED alias, unused by the UI
                "firmware": fwmod.summary(), "log_levels": LOG_LEVELS,
                "limits": limits_dict(), "user_dir": str(udir)}

    @r.get("/api/cfg/firmware")
    def firmware(board: str | None = None):
        if board is not None:
            _bad_board(board)
        return {"firmware": fwmod.summary(board)}

    @r.post("/api/cfg/analyze")
    def analyze(req: AnalyzeReq):
        _bad_board(req.board)
        if req.cfg_text is not None:
            return _analyze_text(req.board, req.cfg_text, req.firmware)
        if req.targets is not None:
            return _generated(req.board, req.targets, req.firmware)
        raise HTTPException(422, "give cfg_text or targets")

    @r.post("/api/cfg/params")
    def params(req: ParamsReq):
        """Direct chirp-parameter mode (gui-11): apply `params` to `base_cfg_text`, then validate as usual.
        Bad values come back as error issues (ok false), never as a 5xx."""
        _bad_board(req.board)
        try:
            pw: list = []
            text = apply_params(req.base_cfg_text, req.params or {}, board=req.board, firmware=req.firmware,
                                warnings=pw)
        except CfgError as e:
            return {"board": req.board, "ok": False, "source": "params", "text": req.base_cfg_text, "metrics": None,
                    "issues": [{"level": "error", "code": "params", "message": str(e), "source": "", "confidence": ""}],
                    "params": None, "report": {"ok": False, "issues": [{"level": "error", "code": "params",
                                                                         "message": str(e)}]}}
        res = _analyze_text(req.board, text, req.firmware)
        res["source"] = "params"
        for code, msg in pw:
            res["issues"].append({"level": "warning", "code": code, "message": msg, "source": "params",
                                  "confidence": ""})
        try:
            res["params"] = params_from_cfg(parse_cfg(text), req.board)
        except CfgError:
            res["params"] = None
        res["report"] = {"ok": res["ok"], "issues": res["issues"]}
        return res

    def _generated(board, targets, firmware=None):
        g = generate(board, targets, firmware=firmware).to_dict()
        return {"board": board, "ok": g["ok"], "source": "targets", "text": g["text"], "name": g["name"],
                "metrics": g["metrics"], "issues": g["report"]["issues"], "achieved": g["achieved"],
                "targets": g["targets"]}

    @r.post("/api/cfg/generate")
    def gen(req: AnalyzeReq):
        _bad_board(req.board)
        return _generated(req.board, req.targets or {}, req.firmware)

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
        res = _analyze_text(req.board, req.cfg_text, req.firmware)
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
        sysj = system_json(req, cfg_path.name)
        return {"ok": True, "cfg_path": str(cfg_path), "json_path": str(json_path), "issues": res["issues"],
                "warnings": lvds_mismatch_warnings(req, sysj["dca1000"]["enabled"]),
                "validate_cmd": f"CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP {json_path} --validate"}

    return r
