"""Per-firmware descriptors (gui-10): the cfg template per board, what the firmware outputs on each board, the
system-JSON enables it implies, the per-board limits (with their sources) and its MIMO scheme.

Each BOARD lists the firmwares it supports (`firmwares`, default first, in config/boards/<board>.json); a
firmware descriptor at CPSL_TI_Radar_cpp/config/firmware/<id>.json (JSON so the C++ driver can read the same
files via include/json; gui-04) holds, schema 2:

  id               file stem
  description      one line
  outputs          {board: {"tlv": bool, "lvds": bool}}   what the firmware provides on that board (TLV over
                   serial / ADC over LVDS). One `demo` serves 1443/1843/6843; its LVDS output is switched on by
                   the cfg (lvdsStreamCfg) on 1843/6843 and does not exist on the 1443.
  lvds_data_fmts   {"value": [int], "source", "confidence"}   lvdsStreamCfg dataFmt values the firmware accepts (gui-24);
                   required when any board output has lvds, absent otherwise
  templates        {board: cfg path relative to config/}   one per board
  system_enables   {"serial": bool, "dca1000": bool}       what a system JSON for it turns on by default
  limits           {board: {name: {"value", "level", "source", "confidence"}}}
                   confidence: "repo" | "high" | "medium" | "low" | "unverified" ("recalled" is legacy); level: "error" | "warning"
  mimo             {"scheme": "tdm"|"ddma", "bpm": bool, "max_chirps_per_loop": int|null, "subframes": int|null,
                    "source", "confidence", optional "note", optional "boards": {board: {overrides of the above}}}
                   the MIMO scheme is a property of the firmware, not inferred from the board (gui-10 ruling);
                   confidence: "high" | "medium" | "low" | "unverified"
  identify         optional {board: {level, timeout_ms, once_safe, probes, flash_hint, note, source}}  (gui-33) what the board answers
                   to `version` / `sarStats` when this firmware runs; matched by radar_gui/fwident.py (schema checked there).
                   source: null (prebuilt only) | {fw_project, artifact} back-reference to firmware_dev/projects (fwstd-03).
                   level: "bench" (reply recorded on hardware) | "source" (derived from firmware source) | "unverified".
  cfg_rules        optional {board: {"skip_commands": [str], "required_commands": [str], "forbidden_commands": [str]}}  (gui-33 Step 4)
                   cfg commands this firmware on that board rejects (left in the cfg, never sent) / needs / does not implement.
                   Read through `cfg_rules(board, firmware)`; the C++ driver reads the same block. Absent board = no rules.
  cli_overrides    optional {board: {"prompt": str}}  the CLI prompt this firmware prints on that board; overrides the board
                   descriptor's `cli.prompt` (the prompt of the board's default firmware). Read through `cfg_rules(...)["prompt"]`.
  detection        optional (gui-35) null (+ `detection_note`) or {boards, variants, notes}: the on-chip CFAR command schema per board;
                   format and rules in radar_gui/cfg/detection.py. GUI-only: the C++ driver ignores it and never enforces its rules.
  pending          optional string; present = stub (no cfg generation/validation yet)
  driver_board     optional {gui board: driver board}  (gui-30) the C++ driver board (config/boards/<name>.json) a system JSON
                   writes for this firmware on that GUI board, and whose cfg_dialect (required/forbidden commands) the cfg is
                   validated against. Host-GUI metadata; absent = the GUI board is the driver board. E.g. iwr1843_sar_lvds
                   {"IWR1843": "IWR1843_SAR"}: the SAR image is a separate driver board with its own dialect.

The boards a firmware supports are the keys of `templates` (= `outputs`); `check_boards()` verifies the board
lists and the descriptors agree.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "CPSL_TI_Radar_cpp" / "config"
FIRMWARE_DIR = CONFIG_DIR / "firmware"
BOARDS_DIR = CONFIG_DIR / "boards"
CONFIDENCES = ("repo", "high", "medium", "low", "recalled", "unverified")   # gui-13: memo vocabulary added
LEVELS = ("error", "warning")


MIMO_SCHEMES = ("tdm", "ddma")
MIMO_CONFIDENCES = ("high", "medium", "low", "unverified")
_MIMO_KEYS = ("scheme", "bpm", "max_chirps_per_loop", "subframes", "source", "confidence")


def _check_mimo_entry(m, where: str, full: bool) -> list[str]:
    bad: list[str] = []
    if not isinstance(m, dict):
        return [f"{where}: must be an object"]
    if full:
        missing = [k for k in _MIMO_KEYS if k not in m]
        if missing:
            return [f"{where}: missing {missing}"]
    if "scheme" in m and m["scheme"] not in MIMO_SCHEMES:
        bad.append(f"{where}: scheme must be one of {MIMO_SCHEMES}")
    if "bpm" in m and not isinstance(m["bpm"], bool):
        bad.append(f"{where}: bpm must be a bool")
    for k in ("max_chirps_per_loop", "subframes"):
        if k in m and not (m[k] is None or (isinstance(m[k], int) and not isinstance(m[k], bool) and m[k] >= 0)):
            bad.append(f"{where}: {k} must be a non-negative int or null")
    if "confidence" in m and m["confidence"] not in MIMO_CONFIDENCES:
        bad.append(f"{where}: confidence must be one of {MIMO_CONFIDENCES}")
    if "source" in m and not m["source"]:
        bad.append(f"{where}: source is empty")
    return bad


RULE_KEYS = ("skip_commands", "required_commands", "forbidden_commands")


def _check_rules(rules, overrides, boards: list[str]) -> list[str]:
    """Shape problems of `cfg_rules` / `cli_overrides` (same rules as the C++ FirmwareDescriptor loader)."""
    bad: list[str] = []
    if rules is not None:
        if not isinstance(rules, dict):
            return ["cfg_rules must be {board: {skip_commands|required_commands|forbidden_commands: [command word]}}"]
        for b, r in rules.items():
            if b not in boards:
                bad.append(f"cfg_rules[{b}]: board is not in templates")
            elif not isinstance(r, dict) or not set(r) <= set(RULE_KEYS):
                bad.append(f"cfg_rules[{b}]: must be an object with keys from {RULE_KEYS}")
            else:
                for k, v in r.items():
                    if not (isinstance(v, list) and all(isinstance(x, str) and x and not any(c.isspace() for c in x) for x in v)
                            and len(set(v)) == len(v)):
                        bad.append(f"cfg_rules[{b}].{k}: must be a list of distinct one-word command names")
                req = set(r.get("required_commands") or [])
                for other in ("forbidden_commands", "skip_commands"):
                    both = req & set(r.get(other) or [])
                    if both:
                        bad.append(f"cfg_rules[{b}]: {sorted(both)} in both required_commands and {other}")
    if overrides is not None:
        if not isinstance(overrides, dict):
            return bad + ["cli_overrides must be {board: {prompt: str}}"]
        for b, o in overrides.items():
            if b not in boards:
                bad.append(f"cli_overrides[{b}]: board is not in templates")
            elif not (isinstance(o, dict) and set(o) == {"prompt"} and isinstance(o["prompt"], str) and o["prompt"]):
                bad.append(f"cli_overrides[{b}]: must be {{\"prompt\": non-empty string}}")
    return bad


def check_descriptor(d: dict, stem: str | None = None) -> list[str]:
    """Schema problems of one descriptor dict ([] = valid)."""
    bad: list[str] = []
    if d.get("schema") != 2:
        bad.append("schema must be 2")
    if not isinstance(d.get("id"), str) or not d["id"]:
        bad.append("id missing")
    elif stem and d["id"] != stem:
        bad.append(f"id {d['id']!r} != file stem {stem!r}")
    if not d.get("description"):
        bad.append("description missing")
    if "boards" in d:
        bad.append("'boards' is gone: boards list their firmwares (config/boards/<board>.json firmwares)")
    tpl = d.get("templates")
    if not isinstance(tpl, dict) or not tpl:
        return bad + ["templates must be a non-empty {board: path}"]
    boards = list(tpl)
    for b in boards:
        if not (BOARDS_DIR / f"{b}.json").is_file():
            bad.append(f"board {b!r} has no config/boards/{b}.json")
    for b, p in tpl.items():
        if not (CONFIG_DIR / p).is_file():
            bad.append(f"template for {b}: {p} does not exist")
    out = d.get("outputs")
    if not isinstance(out, dict) or set(out) != set(boards):
        bad.append("outputs must have exactly one entry per board (same keys as templates)")
    else:
        for b, o in out.items():
            if not (isinstance(o, dict) and set(o) == {"tlv", "lvds"} and all(isinstance(v, bool) for v in o.values())):
                bad.append(f'outputs[{b}] must be {{"tlv": bool, "lvds": bool}}')
            elif not (o["tlv"] or o["lvds"]):
                bad.append(f"outputs[{b}]: firmware provides no output")
    db = d.get("driver_board")
    if db is not None:
        if not (isinstance(db, dict) and db and set(db) <= set(boards) and all(isinstance(v, str) for v in db.values())):
            bad.append("driver_board must be {gui board (a key of templates): driver board name}")
        else:
            for b, v in db.items():
                if not (BOARDS_DIR / f"{v}.json").is_file():
                    bad.append(f"driver_board[{b}]: {v!r} has no config/boards/{v}.json")
    from .. import fwident

    bad += fwident.check_identify(d.get("identify"), boards)
    bad += _check_rules(d.get("cfg_rules"), d.get("cli_overrides"), boards)
    from . import detection

    bad += detection.check_detection(d, boards)
    fm = d.get("lvds_data_fmts")
    if fm is None:
        if isinstance(out, dict) and any(isinstance(o, dict) and o.get("lvds") for o in out.values()):
            bad.append("lvds_data_fmts missing (firmware has an LVDS output)")
    elif not (isinstance(fm, dict) and {"value", "source", "confidence"} <= set(fm)
              and isinstance(fm["value"], list) and fm["value"]
              and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in fm["value"])
              and fm["source"] and fm["confidence"] in CONFIDENCES):
        bad.append("lvds_data_fmts must be {value: [int, ...], source, confidence}")
    en = d.get("system_enables")
    if not (isinstance(en, dict) and set(en) == {"serial", "dca1000"} and all(isinstance(v, bool) for v in en.values())):
        bad.append('system_enables must be {"serial": bool, "dca1000": bool}')
    lim = d.get("limits")
    if not isinstance(lim, dict) or not set(lim) <= set(boards):
        bad.append("limits keys must be boards of this firmware")
    elif "pending" not in d and set(lim) != set(boards):
        bad.append("non-pending firmware needs limits for every board")
    else:
        for b, entries in lim.items():
            for name, e in entries.items():
                if not (isinstance(e, dict) and {"value", "level", "source", "confidence"} <= set(e)):
                    bad.append(f"limits[{b}][{name}] needs value/level/source/confidence")
                elif e["level"] not in LEVELS or e["confidence"] not in CONFIDENCES or not e["source"]:
                    bad.append(f"limits[{b}][{name}]: bad level/confidence/source")
    m = d.get("mimo")
    bad += _check_mimo_entry(m, "mimo", True) if m is not None else ["mimo block missing"]
    if isinstance(m, dict):
        ov = m.get("boards", {})
        if not isinstance(ov, dict) or not set(ov) <= set(boards):
            bad.append("mimo.boards keys must be boards of this firmware")
        else:
            for b, o in ov.items():
                bad += _check_mimo_entry(o, f"mimo.boards[{b}]", False)
    return bad


def board_firmwares(board: str) -> list[str] | None:
    """The `firmwares` list of config/boards/<board>.json (default first); None if the board has no file/key."""
    p = BOARDS_DIR / f"{board}.json"
    if not p.is_file():
        return None
    v = json.loads(p.read_text()).get("firmwares")
    return list(v) if isinstance(v, list) else None


def cfg_dialect(board: str) -> dict:
    """The `cfg_dialect` block of config/boards/<board>.json ({} if the board has no file/key). Silicon facts only
    (rx_mask_fields, frame_period_field): the command rules moved to the firmware descriptors (`cfg_rules`)."""
    p = BOARDS_DIR / f"{board}.json"
    v = json.loads(p.read_text()).get("cfg_dialect") if p.is_file() else None
    return v if isinstance(v, dict) else {}


def default_firmware_id(board: str) -> str | None:
    """The firmware a config without a `firmware` key means on `board`: the first of the board's `firmwares` list (the one
    the GUI preselects; the C++ driver's default_firmware_id agrees). None if the board lists none."""
    fws = board_firmwares(board)
    return fws[0] if fws else None


def cfg_rules(board: str, firmware: str | None = None) -> dict:
    """THE accessor for what a firmware changes about the cfg and the CLI on a board (gui-33 Step 4; used by the cfg
    validator, the serial source and the GUI error checks). `board` is the GUI board or the driver board
    (IWR1843_SAR is looked up as IWR1843 under iwr1843_sar_lvds); `firmware` None = `default_firmware_id(board)`.
    Returns {"firmware": id|None, "skip_commands": [...], "required_commands": [...], "forbidden_commands": [...],
    "prompt": str|None (None = the board's own cli.prompt), "source": "config/firmware/<id>.json cfg_rules.<board>"}."""
    fid = firmware or default_firmware_id(board)
    d = get(fid) if fid else None
    out = {"firmware": fid, "skip_commands": [], "required_commands": [], "forbidden_commands": [], "prompt": None,
           "source": f"config/firmware/{fid}.json" if fid else ""}
    if d is None:
        return out
    gui = next((g for g, drv in (d.get("driver_board") or {}).items() if drv == board), board)
    r = (d.get("cfg_rules") or {}).get(gui) or {}
    for k in RULE_KEYS:
        out[k] = list(r.get(k) or [])
    out["prompt"] = ((d.get("cli_overrides") or {}).get(gui) or {}).get("prompt")
    out["source"] = f"config/firmware/{fid}.json cfg_rules.{gui}"
    return out


def elevation_tx_bit(board: str) -> int:
    """Chirp-mask bit of the board's elevation TX (`elevation_tx_bit` in config/boards/<board>.json; default 2 = TX2,
    the single-chip EVM layout)."""
    p = BOARDS_DIR / f"{board}.json"
    v = json.loads(p.read_text()).get("elevation_tx_bit") if p.is_file() else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0b010


def check_boards(descs: dict[str, dict] | None = None) -> list[str]:
    """Consistency of the board lists with the descriptors ([] = consistent): every board lists >= 1 firmware,
    every listed id has a descriptor with a template (+ limits unless pending) for that board, and every
    descriptor board lists the descriptor back. A driver-only board (the `driver_board` target of a descriptor, e.g.
    IWR1843_SAR) is not a GUI board: it needs no template/limits, but must list that firmware itself."""
    descs = load_all() if descs is None else descs
    bad: list[str] = []
    driver_only = {v: f for f, d in descs.items() for v in (d.get("driver_board") or {}).values()}
    for p in sorted(BOARDS_DIR.glob("*.json")):
        b = p.stem
        if b in driver_only and b not in {x for d in descs.values() for x in d["templates"]}:
            if driver_only[b] not in (board_firmwares(b) or []):
                bad.append(f"{b}: driver board of {driver_only[b]!r} but does not list it")
            continue
        fws = board_firmwares(b)
        if not fws:
            bad.append(f"{b}: no firmwares list")
            continue
        if len(set(fws)) != len(fws):
            bad.append(f"{b}: duplicate firmware ids")
        for f in fws:
            d = descs.get(f)
            if d is None:
                bad.append(f"{b}: lists unknown firmware {f!r}")
            elif b not in d["templates"]:
                bad.append(f"{b}: lists {f!r} but it has no template for {b}")
            elif "pending" not in d and b not in d["limits"]:
                bad.append(f"{b}: lists {f!r} but it has no limits for {b}")
    for f, d in descs.items():
        for b in d["templates"]:
            if f not in (board_firmwares(b) or []):
                bad.append(f"{f}: has a template for {b} but {b} does not list it")
    return bad


@lru_cache(maxsize=None)
def load_all() -> dict[str, dict]:
    """id -> descriptor, sorted by id. A malformed file raises ValueError (fail loud)."""
    out = {}
    for p in sorted(FIRMWARE_DIR.glob("*.json")):
        d = json.loads(p.read_text())
        bad = check_descriptor(d, p.stem)
        if bad:
            raise ValueError(f"{p.name}: " + "; ".join(bad))
        out[d["id"]] = d
    return out


def get(fw_id: str) -> dict | None:
    return load_all().get(fw_id)


def boards_of(fw: dict) -> list[str]:
    """Boards a firmware has templates for (the board lists are checked against this by check_boards)."""
    return list(fw["templates"])


def supports(fw: dict, board: str) -> bool:
    """True when `board` lists the firmware (the board's list is authoritative) and the descriptor serves it."""
    return fw["id"] in (board_firmwares(board) or []) and board in fw["templates"]


def for_board(board: str) -> list[dict]:
    """Firmwares that `board` lists, in the board's order (default first)."""
    all_ = load_all()
    return [all_[i] for i in (board_firmwares(board) or []) if i in all_ and board in all_[i]["templates"]]


def default_for(board: str) -> dict | None:
    fws = for_board(board)
    return fws[0] if fws else None


def driver_board(fw: dict, board: str) -> str:
    """The C++ driver board a system JSON writes for firmware `fw` on GUI board `board` (descriptor `driver_board`;
    default: `board` itself)."""
    return (fw.get("driver_board") or {}).get(board, board)


def template_path(fw: dict, board: str) -> Path:
    return CONFIG_DIR / fw["templates"][board]


def outputs(fw: dict, board: str) -> dict:
    return fw["outputs"][board]


def lvds_data_fmts(fw: dict) -> list[int] | None:
    """lvdsStreamCfg dataFmt values `fw` accepts (None: the firmware declares none, i.e. has no LVDS output)."""
    f = fw.get("lvds_data_fmts")
    return list(f["value"]) if f else None


def flavour(fw: dict, board: str, lvds: bool = False) -> str:
    """The generator's internal cfg flavour: 'tlv' (demo), 'lvds' (demo + lvdsStreamCfg on), 'raw' (no demo), 'sar'
    (no demo; the firmware is its own driver board with its own cfg dialect, i.e. `driver_board` maps the GUI board).
    `lvds` asks a TLV firmware to also stream ADC data; ignored where the firmware has no LVDS output."""
    o = outputs(fw, board)
    if not o["tlv"]:
        return "sar" if driver_board(fw, board) != board else "raw"
    return "lvds" if (lvds and o["lvds"]) else "tlv"


def _with_editable(m: dict, d: dict) -> dict:
    """Add the single 'what can the GUI do with MIMO here' decision: `editable` (bool), `editable_reason` (one line, None if
    editable) and `editable_note` (one soft line, else None). View-only = DDMA or a stub firmware; unverified TDM stays
    editable (checks are warnings only) with `editable_note` set."""
    reason = note = None
    if d.get("pending"):
        reason = "this firmware is a stub (cfg generation pending); its MIMO scheme is not implemented yet."
    elif m.get("scheme") == "ddma":
        reason = "DDMA: all TX fire every chirp; phase codes are set by the firmware, not the cfg."
    elif m.get("confidence") == "unverified":
        note = "TX-pattern rules for this firmware are unverified \u2014 checks are warnings only."
    return {**m, "editable": reason is None, "editable_reason": reason, "editable_note": note}


def mimo(board: str, fw) -> dict:
    """The MIMO block of firmware `fw` (descriptor or id) for `board`: the firmware-wide values with any
    per-board override applied. Keys: scheme, bpm, max_chirps_per_loop, subframes, source, confidence[, note], editable, editable_reason, editable_note."""
    d = get(fw) if isinstance(fw, str) else fw
    if d is None:
        raise KeyError(f"unknown firmware {fw!r}")
    m = {k: v for k, v in d["mimo"].items() if k != "boards"}
    m.update(d["mimo"].get("boards", {}).get(board, {}))
    return _with_editable(m, d)


def summary(board: str | None = None) -> list[dict]:
    """JSON-able firmware list (optionally only those `board` lists, default first) for the HTTP layer.
    With a board: `outputs`/`mimo` are that board's; without: `outputs` is {board: ...} and `mimo` the base block."""
    fws = for_board(board) if board else list(load_all().values())
    return [{"id": d["id"], "description": d["description"], "boards": boards_of(d),
             "outputs": d["outputs"][board] if board else d["outputs"],
             "mimo": mimo(board, d) if board else _with_editable({k: v for k, v in d["mimo"].items()}, d),
             "lvds_data_fmts": lvds_data_fmts(d), "lvds_data_fmts_source": (d.get("lvds_data_fmts") or {}).get("source"),
             "lvds_data_fmts_confidence": (d.get("lvds_data_fmts") or {}).get("confidence"),
             "system_enables": d["system_enables"], "pending": d.get("pending"),
             "driver_board": driver_board(d, board) if board else d.get("driver_board"),
             "default": bool(board and fws and d is fws[0]),
             "template": d["templates"].get(board) if board else None} for d in fws]
