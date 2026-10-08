"""The effective system JSON of one driver run (gui-37): `runs/gui/<UTC>_<name>/session.json` + the cfg copy `radar.cfg`.

Every GUI start builds one, from either
  * a saved system JSON plus overrides (save flags, skip cfg, firmware check), or
  * a quick setup (board, firmware, cfg, ports, DCA1000 on/off, save flags),
and the driver runs that file, so a run folder carries its own provenance. Paths in the file:
  radar_cfg   "radar.cfg", the copy beside session.json (the original is resolved against the saved JSON's directory)
  board       the absolute path of the board descriptor (session.json is not next to config/boards; a path is accepted
              by every driver build, and the driver finds config/firmware/ from the descriptor's directory)
  output.dir  absolute, when the saved JSON had one
Keys a driver build rejects are written only when `caps` says it accepts them (`probe_caps`): `firmware`,
`runtime.firmware_check` and `output.save_serial_bytes` are newer than the Rebuild 1 binary.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import cfgapi
from .cfg import firmware as fwmod

_XDS = "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.{}__Embed_with_CMSIS-DAP_{}"
# Defaults only (the bench's XDS110 interfaces); the page lets the user edit both ports.
DEFAULT_PORTS = {"AWR2243_CASCADE": (_XDS.format("29", "00000000") + "-if00", _XDS.format("29", "00000000") + "-if03"),
                 "IWR1843": (_XDS.format("05", "R2101050") + "-if00", _XDS.format("05", "R2101050") + "-if03")}
FALLBACK_PORTS = ("/dev/ttyACM0", "/dev/ttyACM1")
# Serial ports a start may open: USB-serial only (no /dev/tty, /dev/ttyS*, ...). Checked on the literal string.
PORT_NAME = re.compile(r"^(/dev/serial/by-id/[A-Za-z0-9_.:+-]+|/dev/tty(ACM|USB)[0-9]+)$")
SERIAL_BOARDS = ("IWR1443", "IWR1843", "IWR6843", "IWR6843ODS", "AWR2243_CASCADE")
FIRMWARE_CHECKS = ("auto", "warn", "off")
SAVE_KEYS = ("save_adc_frames", "save_raw_lvds", "save_serial_bytes")
DCA_DEFAULTS = {"fpga_ip": "192.168.33.180", "host_ip": "192.168.33.30", "cmd_port": 4096, "data_port": 4098}
SESSION_JSON, CFG_COPY, DRIVER_LOG = "session.json", "radar.cfg", "driver.log"


class SessionError(Exception):
    """Bad input for a session (the API answers 422)."""


def check_port(path: str, what: str) -> str:
    if not isinstance(path, str) or not PORT_NAME.match(path):
        raise SessionError(f"{what} {path!r} is not allowed: use /dev/serial/by-id/<name>, /dev/ttyACM<N> or /dev/ttyUSB<N>")
    return path


def default_ports(board: str) -> tuple[str, str]:
    return DEFAULT_PORTS.get(board, FALLBACK_PORTS)


# ---- driver capabilities ------------------------------------------------------------------------------------
_PROBE_BASE = {"schema_version": 2, "board": "IWR1843", "radar_cfg": "probe.cfg", "cli": {"port": "/dev/ttyACM0"},
               "serial_stream": {"enabled": True, "port": "/dev/ttyACM1"}}


def _accepts_key(binary: Path, mutate) -> bool:
    """True when `binary --validate` does not call the key set by `mutate(doc)` unknown.

    Why a probe and not the usage text: the key lists the reader accepts are not in `--help`, and the three keys landed in
    different commits. The reader checks key names first (before it opens the board, the cfg or any port) and a build that
    does not know the key says `<path>: unknown key (allowed: ...)`. We validate a throw-away JSON that sets only that key;
    any other complaint (no such cfg, ...) means the key itself was accepted. A binary that cannot be run reads as False.
    """
    doc = copy.deepcopy(_PROBE_BASE)
    mutate(doc)
    with tempfile.TemporaryDirectory(prefix="radar_gui_probe_") as d:
        doc["board"] = str(fwmod.BOARDS_DIR / "IWR1843.json")
        p = Path(d) / "probe.json"
        p.write_text(json.dumps(doc))
        try:
            r = subprocess.run([str(binary), str(p), "--validate"], capture_output=True, text=True, timeout=15,
                               stdin=subprocess.DEVNULL, cwd=d)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return "unknown key" not in r.stdout + r.stderr


def probe_caps(binary: Path) -> dict:
    """{"firmware_key", "firmware_check", "save_serial_bytes"}: which optional system-JSON keys `binary` accepts."""
    binary = Path(binary).absolute()   # the probe runs in a temp cwd: a relative path would not launch
    return {
        "firmware_key": _accepts_key(binary, lambda d: d.update(firmware="demo")),
        "firmware_check": _accepts_key(binary, lambda d: d.update(runtime={"firmware_check": "auto"})),
        "save_serial_bytes": _accepts_key(binary, lambda d: d.update(output={"save_serial_bytes": False})),
    }


# ---- boards (the quick-setup picker) ------------------------------------------------------------------------
def boards_info() -> list[dict]:
    """Per GUI board: the serial defaults and the firmwares quick setup may pick (default first), each with what it outputs
    (so the page offers DCA1000 only where the firmware streams LVDS)."""
    out = []
    for b in SERIAL_BOARDS:
        fws = fwmod.for_board(b)
        if not fws:
            continue
        try:
            d = json.loads((fwmod.BOARDS_DIR / f"{b}.json").read_text())
        except (OSError, ValueError):
            continue
        du = d.get("data_uart") or {}
        cli, data = default_ports(b)
        out.append({"board": b, "once_per_boot": bool((d.get("lifecycle") or {}).get("config_once_per_boot")),
                    "cli_baud": (d.get("cli") or {}).get("baud"), "data_baud": du.get("baud"),
                    "tlv_dialect": du.get("tlv_dialect"), "cli_port": cli, "data_port": data,
                    "default_firmware": fws[0]["id"],
                    "firmwares": [{"id": f["id"], "description": f.get("description", ""), "pending": f.get("pending"),
                                   "tlv": bool(f["outputs"][b]["tlv"]), "lvds": bool(f["outputs"][b]["lvds"]),
                                   "serial": bool(f["system_enables"]["serial"]), "dca1000": bool(f["system_enables"]["dca1000"])}
                                  for f in fws]})
    return out


# ---- building the effective JSON ----------------------------------------------------------------------------
def _flag(d: dict | None, key: str):
    v = (d or {}).get(key)
    if v is not None and not isinstance(v, bool):
        raise SessionError(f"{key} must be true or false")
    return v


def _apply_common(eff: dict, ov: dict, caps: dict, notes: list[str]) -> bool:
    """Save flags, firmware check and log level from `ov` into `eff`; returns the effective skip-cfg. Raises SessionError."""
    out = eff.setdefault("output", {})
    for k in SAVE_KEYS:
        v = _flag(ov, k)
        if v is None:
            continue
        if k == "save_serial_bytes":
            if v and not caps.get("save_serial_bytes"):
                raise SessionError("this driver binary cannot save the raw serial bytes (output.save_serial_bytes): rebuild the driver")
            if v:
                out[k] = True
            elif caps.get("save_serial_bytes"):
                out[k] = False
        else:
            out[k] = v
    dca_on, ser_on = (eff.get("dca1000") or {}).get("enabled"), (eff.get("serial_stream") or {}).get("enabled")
    if (ov.get("save_adc_frames") or ov.get("save_raw_lvds")) and not dca_on:
        raise SessionError("saving ADC frames / raw LVDS needs the DCA1000 stream on (dca1000.enabled)")
    if ov.get("save_serial_bytes") and not ser_on:
        raise SessionError("saving the raw serial bytes needs the serial stream on (serial_stream.enabled)")
    rt = eff.setdefault("runtime", {})
    fc = ov.get("firmware_check")
    if fc is not None:
        if fc not in FIRMWARE_CHECKS:
            raise SessionError(f"firmware_check must be one of {list(FIRMWARE_CHECKS)}")
        if caps.get("firmware_check"):
            rt["firmware_check"] = fc
        elif fc != "auto":
            notes.append(f"firmware check {fc!r} not applied: this driver binary has no firmware check")
    if (ll := ov.get("log_level")) is not None:
        if ll not in cfgapi.LOG_LEVELS:
            raise SessionError(f"log_level must be one of {cfgapi.LOG_LEVELS}")
        rt["log_level"] = ll
    skip = _flag(ov, "skip_configure")
    if skip:
        rt["skip_configure"] = True
    if not rt:
        eff.pop("runtime")
    if not out:
        eff.pop("output")
    return bool(skip)


def _gate_firmware(eff: dict, caps: dict, notes: list[str]):
    if "firmware" in eff and not caps.get("firmware_key"):
        notes.append(f"firmware {eff['firmware']!r} not written: this driver binary does not accept the firmware key")
        eff.pop("firmware")


def from_saved(path: Path, overrides: dict | None, caps: dict) -> dict:
    """Plan from a saved system JSON: {"eff", "cfg_src", "name", "label", "skip_configure", "notes"}."""
    path = Path(path).resolve()
    try:
        eff = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise SessionError(f"cannot read system config {path}: {e}")
    if not isinstance(eff, dict) or "radar_cfg" not in eff:
        raise SessionError(f"system config {path} is not a schema v2 system JSON")
    here, notes = path.parent, []
    cfg_src = (here / str(eff["radar_cfg"])).resolve()
    if cfg_src.is_file():
        eff["radar_cfg"] = CFG_COPY
    else:   # no copy to make; the driver's --validate reports the missing file with its usual message
        eff["radar_cfg"], cfg_src = str(cfg_src), None
    board = eff.get("board")
    if isinstance(board, str) and board:
        if "/" in board or board.endswith(".json"):
            eff["board"] = str((here / board).resolve())
        else:
            env = os.environ.get("CPSL_TI_RADAR_BOARDS_DIR")
            for d in ([Path(env)] if env else []) + [here.parent / "boards", fwmod.BOARDS_DIR]:
                if (d / f"{board}.json").is_file():
                    eff["board"] = str((d / f"{board}.json").resolve())
                    break
    if isinstance(eff.get("output"), dict) and eff["output"].get("dir"):
        eff["output"]["dir"] = str((here / eff["output"]["dir"]).resolve())
    _gate_firmware(eff, caps, notes)
    skip = _apply_common(eff, overrides or {}, caps, notes)
    skip = skip or bool((eff.get("runtime") or {}).get("skip_configure"))
    return {"eff": eff, "cfg_src": cfg_src, "name": path.stem, "label": path.stem, "skip_configure": skip, "notes": notes}


def from_setup(setup: dict, caps: dict) -> dict:
    """Plan from a quick setup. `setup` keys: board, cfg_path (resolved by the API from a cfg id), firmware, cli_port,
    data_port, serial, dca1000, fpga_ip/host_ip/cmd_port/data_udp_port, plus the common overrides (save flags, skip_configure,
    firmware_check, log_level)."""
    board = setup.get("board")
    if board not in SERIAL_BOARDS:
        raise SessionError(f"unknown board {board!r}; one of {list(SERIAL_BOARDS)}")
    cfg_src = Path(setup["cfg_path"]).resolve()
    if not cfg_src.is_file():
        raise SessionError(f"cfg not found: {cfg_src}")
    if (cfgapi.guess_board(str(cfg_src)) == "AWR2243_CASCADE") != (board == "AWR2243_CASCADE") and not setup.get("allow_cfg_mismatch"):
        raise SessionError(f"cfg {cfg_src.name!r} is not for board {board}")
    fw = fwmod.get(setup["firmware"]) if setup.get("firmware") else fwmod.default_for(board)
    if fw is None:
        raise SessionError(f"unknown firmware {setup.get('firmware')!r} for {board}")
    if not fwmod.supports(fw, board):
        raise SessionError(f"{board} does not list firmware {fw['id']!r} (it lists {[d['id'] for d in fwmod.for_board(board)]})")
    if fw.get("pending"):
        raise SessionError(f"firmware {fw['id']!r}: {fw['pending']}")
    out_caps, en = fwmod.outputs(fw, board), fw["system_enables"]
    serial = en["serial"] if setup.get("serial") is None else bool(setup["serial"])
    dca = en["dca1000"] if setup.get("dca1000") is None else bool(setup["dca1000"])
    if serial and not out_caps["tlv"]:
        raise SessionError(f"firmware {fw['id']!r} has no TLV (serial) output on {board}")
    if dca and not out_caps["lvds"]:
        raise SessionError(f"firmware {fw['id']!r} has no LVDS output on {board}: the DCA1000 stream cannot be turned on")
    if not (serial or dca):
        raise SessionError("nothing to stream: turn on the serial stream or the DCA1000")
    dcli, ddata = default_ports(board)
    cli = check_port(setup.get("cli_port") or dcli, "cli_port")
    data = check_port(setup.get("data_port") or ddata, "data_port")
    net = {"fpga_ip": setup.get("fpga_ip") or DCA_DEFAULTS["fpga_ip"], "host_ip": setup.get("host_ip") or DCA_DEFAULTS["host_ip"],
           "cmd_port": setup.get("cmd_port") or DCA_DEFAULTS["cmd_port"], "data_port": setup.get("data_udp_port") or DCA_DEFAULTS["data_port"]}
    for k in ("fpga_ip", "host_ip"):
        try:
            ipaddress.IPv4Address(net[k])
        except ValueError:
            raise SessionError(f"{k} {net[k]!r} is not an IPv4 address")
    for k in ("cmd_port", "data_port"):
        if not (isinstance(net[k], int) and not isinstance(net[k], bool) and 1 <= net[k] <= 65535):
            raise SessionError(f"{k} must be 1-65535")
    drv_board = fwmod.driver_board(fw, board)
    bpath = fwmod.BOARDS_DIR / f"{drv_board}.json"
    if not bpath.is_file():
        raise SessionError(f"no board descriptor for {drv_board}")
    eff = {"schema_version": 2, "board": str(bpath.resolve()), "radar_cfg": CFG_COPY, "firmware": fw["id"],
           "cli": {"port": cli}, "serial_stream": {"enabled": serial, "port": data},
           "dca1000": {"enabled": dca, **net}, "output": {}, "runtime": {"log_level": "info"}}
    notes: list[str] = []
    _gate_firmware(eff, caps, notes)
    skip = _apply_common(eff, setup, caps, notes)
    label = f"{board} · {cfg_src.stem}"
    return {"eff": eff, "cfg_src": cfg_src, "name": f"quick_{board}_{cfg_src.stem}", "label": label,
            "skip_configure": skip, "notes": notes}


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-")[:80] or "run"


def saving_of(eff: dict) -> dict:
    o = eff.get("output") or {}
    return {k: bool(o.get(k)) for k in SAVE_KEYS}


def write_session(run_dir: Path, plan: dict) -> Path:
    """Write session.json and the cfg copy into `run_dir` (must exist). Returns the session.json path."""
    if plan["cfg_src"] is not None:
        shutil.copyfile(plan["cfg_src"], run_dir / CFG_COPY)
    p = run_dir / SESSION_JSON
    p.write_text(json.dumps(plan["eff"], indent=2) + "\n")
    return p
