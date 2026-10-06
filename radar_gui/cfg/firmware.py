"""Per-firmware descriptors (gui-10): which boards a firmware runs on, what it outputs, the cfg template
per board, the system-JSON enables it implies, and the per-board limits (with their sources).

Files live at CPSL_TI_Radar_cpp/config/firmware/<id>.json (JSON so the C++ driver can read the same
files via include/json; gui-04). Schema (`schema` = 1):

  id               file stem
  description      one line
  boards           board names; each needs config/boards/<board>.json
  outputs          {"tlv": bool, "lvds": bool}   what the firmware provides (TLV over serial / ADC over LVDS)
  templates        {board: cfg path relative to config/}   one per board
  system_enables   {"serial": bool, "dca1000": bool}       what a system JSON for it turns on
  default_for      boards for which this is the default firmware (also supplies the default limits)
  limits           {board: {name: {"value", "level", "source", "confidence"}}}
                   confidence: "repo" | "recalled" | "unverified"; level: "error" | "warning"
  pending          optional string; present = stub (no cfg generation/validation yet)
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[2] / "CPSL_TI_Radar_cpp" / "config"
FIRMWARE_DIR = CONFIG_DIR / "firmware"
BOARDS_DIR = CONFIG_DIR / "boards"
CONFIDENCES = ("repo", "recalled", "unverified")
LEVELS = ("error", "warning")


def check_descriptor(d: dict, stem: str | None = None) -> list[str]:
    """Schema problems of one descriptor dict ([] = valid)."""
    bad: list[str] = []
    if d.get("schema") != 1:
        bad.append("schema must be 1")
    if not isinstance(d.get("id"), str) or not d["id"]:
        bad.append("id missing")
    elif stem and d["id"] != stem:
        bad.append(f"id {d['id']!r} != file stem {stem!r}")
    if not d.get("description"):
        bad.append("description missing")
    boards = d.get("boards")
    if not isinstance(boards, list) or not boards:
        return bad + ["boards must be a non-empty list"]
    for b in boards:
        if not (BOARDS_DIR / f"{b}.json").is_file():
            bad.append(f"board {b!r} has no config/boards/{b}.json")
    out = d.get("outputs")
    if not (isinstance(out, dict) and set(out) == {"tlv", "lvds"} and all(isinstance(v, bool) for v in out.values())):
        bad.append('outputs must be {"tlv": bool, "lvds": bool}')
    elif not (out["tlv"] or out["lvds"]):
        bad.append("firmware provides no output")
    en = d.get("system_enables")
    if not (isinstance(en, dict) and set(en) == {"serial", "dca1000"} and all(isinstance(v, bool) for v in en.values())):
        bad.append('system_enables must be {"serial": bool, "dca1000": bool}')
    tpl = d.get("templates")
    if not isinstance(tpl, dict) or set(tpl) != set(boards):
        bad.append("templates must have exactly one entry per board")
    else:
        for b, p in tpl.items():
            if not (CONFIG_DIR / p).is_file():
                bad.append(f"template for {b}: {p} does not exist")
    if not set(d.get("default_for", [])) <= set(boards):
        bad.append("default_for must be a subset of boards")
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


def for_board(board: str) -> list[dict]:
    """Firmwares that support `board`, default first."""
    fws = [d for d in load_all().values() if board in d["boards"]]
    return sorted(fws, key=lambda d: (board not in d["default_for"], d["id"]))


def default_for(board: str) -> dict | None:
    fws = for_board(board)
    return fws[0] if fws and board in fws[0]["default_for"] else None


def template_path(fw: dict, board: str) -> Path:
    return CONFIG_DIR / fw["templates"][board]


def legacy_mode(fw: dict) -> str:
    """The generator's internal cfg flavour: 'tlv' (demo), 'lvds' (demo + lvdsStreamCfg on), 'raw' (no demo)."""
    o = fw["outputs"]
    return "raw" if not o["tlv"] else ("lvds" if o["lvds"] else "tlv")


def summary(board: str | None = None) -> list[dict]:
    """JSON-able firmware list (optionally only those supporting `board`) for the HTTP layer."""
    fws = for_board(board) if board else list(load_all().values())
    return [{"id": d["id"], "description": d["description"], "boards": d["boards"], "outputs": d["outputs"],
             "system_enables": d["system_enables"], "pending": d.get("pending"),
             "default": bool(board and board in d["default_for"]),
             "template": d["templates"].get(board) if board else None} for d in fws]
