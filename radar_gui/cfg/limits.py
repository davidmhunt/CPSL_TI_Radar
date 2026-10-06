"""Per-board constraints. Every entry names its source and how far it is trusted.

`confidence`:
  "repo"       taken from this repo (board descriptor, cfggen.py, docs/firmware.md, docs/RESULTS.md,
               or the shipped cfgs themselves)
  "recalled"   a well-known TI datasheet/SDK figure written down from memory; NOT re-checked
               against the TI document in this session
  "unverified" best-effort estimate; a violation is only ever a warning

The values live in CPSL_TI_Radar_cpp/config/firmware/<id>.json (see firmware.py); this module loads them.
The driver stays the authority; gui-04 makes the C++ driver read the same files.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from . import firmware as fwmod

CAS = "AWR2243_CASCADE"


@dataclass(frozen=True)
class Limit:
    value: object
    level: str          # severity when violated: "error" | "warning"
    source: str
    confidence: str     # "repo" | "recalled" | "unverified"


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
BOARD_LIMITS = {b: firmware_limits(b) for b in ("IWR1443", "IWR1843", "IWR6843", CAS)}

# Host side, board independent.
DCA1000_ETHERNET_MBPS = L(1000, "error", "docs/RESULTS.md: NIC 1000 Mb/s link to the DCA1000", "repo")
DCA1000_ETHERNET_HEADROOM_MBPS = L(800, "warning", "80 % of the 1 Gb/s link; overhead/headroom is a guess", "unverified")
DUTY_WARN = L(0.9, "warning", "heuristic: little time left for chirp-end processing/output", "unverified")
SAR_FIRMWARE_FMT2 = "docs/firmware.md: lvdsStreamCfg dataFmt 2 exists only in the iwr1843_sar_lvds firmware"


def limits_dict() -> dict:
    """BOARD_LIMITS as plain JSON-able dicts (for the HTTP layer)."""
    return {b: {k: (asdict(v) if isinstance(v, Limit) else v) for k, v in d.items()}
            for b, d in BOARD_LIMITS.items()}
