"""Per-board constraints. Every entry names its source and how far it is trusted.

`confidence`:
  "repo"        taken from this repo (board descriptor, cfggen.py, docs/firmware.md, docs/RESULTS.md,
                or the shipped cfgs themselves)
  "high" / "medium" / "low"
                verified against TI documents / SDK sources by the gui-13 memos (docs/research/gui_board_limits_*.md);
                the memo row is cited in `source`
  "unverified"  best-effort estimate no source could confirm; a violation is only ever a warning (so is "low")

Nothing is hard-coded here: board/firmware limits live in CPSL_TI_Radar_cpp/config/firmware/<id>.json (see
firmware.py) and host-side ones in CPSL_TI_Radar_cpp/config/limits/host.json. The driver stays the authority;
gui-04 makes the C++ driver read the same files.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache

from . import firmware as fwmod

CAS = "AWR2243_CASCADE"
HOST_LIMITS_FILE = fwmod.CONFIG_DIR / "limits" / "host.json"


@dataclass(frozen=True)
class Limit:
    value: object
    level: str          # severity when violated: "error" | "warning"
    source: str
    confidence: str     # see the module docstring


def L(value, level, source, confidence):
    return Limit(value, level, source, confidence)


def _from_descriptor(d: dict) -> dict:
    return {k: L(tuple(e["value"]) if isinstance(e["value"], list) else e["value"], e["level"], e["source"],
                 e["confidence"]) for k, e in d.items()}


def firmware_limits(board: str, firmware: str | None = None) -> dict | None:
    """Limits of `board` as declared by a firmware descriptor (None: unknown firmware or no limits there).
    `firmware=None` means the board's default firmware."""
    fw = fwmod.get(firmware) if firmware else fwmod.default_for(board)
    if fw is None or board not in fw["limits"]:
        return None
    return _from_descriptor(fw["limits"][board])


# Default per-board limits (the board's default firmware); validate() takes a firmware to override.
BOARD_LIMITS = {b: firmware_limits(b) for b in ("IWR1443", "IWR1843", "IWR6843", "IWR6843ODS", CAS)}


@lru_cache(maxsize=None)
def host_limits() -> dict:
    """Board-independent limits from config/limits/host.json (DCA1000 link/throughput, duty heuristic)."""
    d = json.loads(HOST_LIMITS_FILE.read_text())
    if d.get("schema") != 2 or not isinstance(d.get("limits"), dict):
        raise ValueError(f"{HOST_LIMITS_FILE.name}: bad schema")
    for k, e in d["limits"].items():
        if not ({"value", "level", "source", "confidence"} <= set(e) and e["level"] in fwmod.LEVELS
                and e["confidence"] in fwmod.CONFIDENCES and e["source"]):
            raise ValueError(f"{HOST_LIMITS_FILE.name}: limits[{k}] needs value/level/source/confidence")
    return _from_descriptor(d["limits"])


def dca1000_params(board: str) -> tuple[int, float]:
    """(packet_bytes, packet_delay_us) the driver programs for `board` (config/boards/<board>.json dca1000)."""
    p = json.loads((fwmod.BOARDS_DIR / f"{board}.json").read_text())["dca1000"]
    return int(p["packet_bytes"]), float(p["packet_delay_us"])


def dca1000_ceiling_mbps(board: str) -> float:
    """Sustainable DCA1000 rate at the board's packet delay: min(TI's 706 Mb/s maximum,
    packet_bits / (delay + fitted per-packet overhead)). ~105 Mb/s at the shipped 100 us delay."""
    h = host_limits()
    pkt, delay = dca1000_params(board)
    return min(float(h["dca1000_max_mbps"].value), pkt * 8 / (delay + float(h["dca1000_packet_overhead_us"].value)))


def limits_dict() -> dict:
    """BOARD_LIMITS as plain JSON-able dicts (for the HTTP layer)."""
    return {b: {k: (asdict(v) if isinstance(v, Limit) else v) for k, v in d.items()}
            for b, d in BOARD_LIMITS.items()}
