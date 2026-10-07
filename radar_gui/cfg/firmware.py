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
  pending          optional string; present = stub (no cfg generation/validation yet)

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


def check_boards(descs: dict[str, dict] | None = None) -> list[str]:
    """Consistency of the board lists with the descriptors ([] = consistent): every board lists >= 1 firmware,
    every listed id has a descriptor with a template (+ limits unless pending) for that board, and every
    descriptor board lists the descriptor back."""
    descs = load_all() if descs is None else descs
    bad: list[str] = []
    for p in sorted(BOARDS_DIR.glob("*.json")):
        b = p.stem
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


def template_path(fw: dict, board: str) -> Path:
    return CONFIG_DIR / fw["templates"][board]


def outputs(fw: dict, board: str) -> dict:
    return fw["outputs"][board]


def lvds_data_fmts(fw: dict) -> list[int] | None:
    """lvdsStreamCfg dataFmt values `fw` accepts (None: the firmware declares none, i.e. has no LVDS output)."""
    f = fw.get("lvds_data_fmts")
    return list(f["value"]) if f else None


def flavour(fw: dict, board: str, lvds: bool = False) -> str:
    """The generator's internal cfg flavour: 'tlv' (demo), 'lvds' (demo + lvdsStreamCfg on), 'raw' (no demo).
    `lvds` asks a TLV firmware to also stream ADC data; ignored where the firmware has no LVDS output."""
    o = outputs(fw, board)
    if not o["tlv"]:
        return "raw"
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
             "default": bool(board and fws and d is fws[0]),
             "template": d["templates"].get(board) if board else None} for d in fws]
