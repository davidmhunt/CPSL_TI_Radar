"""Writing a system JSON back to config/user/ (gui-37): "Save to config" for the recording flags and other run overrides.

Shareable helper (gui-04 Step 2b's Add-firmware button writes the same file kind): `update_user_json` overwrites a file that lives
in the user dir, keeping a `<name>.json.bak` of the previous bytes; `copy_to_user` writes a new file there from any listed config.
Both write atomically (temp file + rename) as indent-4 JSON with a trailing newline and keep key order.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,60}$")
SAVE_KEYS = ("save_adc_frames", "save_raw_lvds", "save_serial_bytes")


class SysJsonError(Exception):
    def __init__(self, msg: str, status: int = 422):
        super().__init__(msg)
        self.status = status


def atomic_write_json(path: Path, doc: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=4)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply_overrides(doc: dict, ov: dict, caps: dict) -> dict:
    """Set the save flags (and firmware_check / log_level) in `doc`. Raises SysJsonError for a flag the config/driver cannot honour."""
    out = doc.setdefault("output", {})
    for k in SAVE_KEYS:
        v = ov.get(k)
        if v is None:
            continue
        if k == "save_serial_bytes" and not caps.get("save_serial_bytes"):
            raise SysJsonError("this driver binary cannot save raw serial bytes (output.save_serial_bytes)")
        out[k] = bool(v)
    if (ov.get("save_adc_frames") or ov.get("save_raw_lvds")) and not (doc.get("dca1000") or {}).get("enabled"):
        raise SysJsonError("saving ADC frames / raw LVDS needs dca1000.enabled in this config")
    if ov.get("save_serial_bytes") and not (doc.get("serial_stream") or {}).get("enabled"):
        raise SysJsonError("saving raw serial bytes needs serial_stream.enabled in this config")
    rt = doc.setdefault("runtime", {})
    if ov.get("firmware_check") is not None:
        if not caps.get("firmware_check"):
            raise SysJsonError("this driver binary has no runtime.firmware_check")
        rt["firmware_check"] = ov["firmware_check"]
    if ov.get("log_level") is not None:
        rt["log_level"] = ov["log_level"]
    for k in ("runtime", "output"):
        if not doc.get(k):
            doc.pop(k, None)
    return doc


def update_user_json(path: Path, user_dir: Path, ov: dict, caps: dict) -> Path:
    """Overwrite `path` (must resolve inside `user_dir`) with `ov` applied; the previous file is kept as `<path>.bak`."""
    p, root = Path(path).resolve(), Path(user_dir).resolve()
    if root not in p.parents or p.suffix != ".json" or not p.is_file():
        raise SysJsonError(f"{path} is not a system JSON in the user config directory")
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        raise SysJsonError(f"cannot read {p.name}: {e}")
    apply_overrides(doc, ov, caps)
    shutil.copyfile(p, p.with_name(p.name + ".bak"))
    atomic_write_json(p, doc)
    return p


def copy_to_user(src: Path, user_dir: Path, name: str, ov: dict, caps: dict) -> Path:
    """Write `src` + `ov` as a new `<user_dir>/<name>.json`. Paths that were relative to src's folder become absolute."""
    if not isinstance(name, str) or not NAME_RE.match(name) or ".." in name:
        raise SysJsonError("name must be letters, digits, _ . - (no path)")
    name = name[:-5] if name.endswith(".json") else name
    root = Path(user_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    dst = (root / f"{name}.json").resolve()
    if dst.parent != root:
        raise SysJsonError("name must not contain a path")
    if dst.exists():
        raise SysJsonError(f"{dst.name} already exists in the user config directory: pick another name", 409)
    src = Path(src).resolve()
    try:
        doc = json.loads(src.read_text())
    except (OSError, ValueError) as e:
        raise SysJsonError(f"cannot read {src.name}: {e}")
    here = src.parent
    if isinstance(doc.get("radar_cfg"), str):
        doc["radar_cfg"] = str((here / doc["radar_cfg"]).resolve())
    b = doc.get("board")
    if isinstance(b, str) and ("/" in b or b.endswith(".json")):
        doc["board"] = str((here / b).resolve())
    if isinstance(doc.get("output"), dict) and doc["output"].get("dir"):
        doc["output"]["dir"] = str((here / doc["output"]["dir"]).resolve())
    apply_overrides(doc, ov, caps)
    atomic_write_json(dst, doc)
    return dst
