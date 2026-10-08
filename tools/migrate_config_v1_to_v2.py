#!/usr/bin/env python3
"""Convert CPSL TI Radar system configs from schema v1 to schema v2.

v1 is the pre-2.0 layout (``verbose``, ``TI_Radar_Config_Management``,
``CLI_Controller``, ``Streamer``); v2 is driver v2 design section 2
(``schema_version: 2``, ``board``, ``radar_cfg``, ``cli``, ``serial_stream``,
``dca1000``, ``output``, ``runtime``). The v2 driver rejects v1 files and
names this script.

Usage (from the repo root):
    uv run tools/migrate_config_v1_to_v2.py <file.json>              # print the v2 JSON
    uv run tools/migrate_config_v1_to_v2.py <file-or-dir>... --in-place
    uv run tools/migrate_config_v1_to_v2.py <file-or-dir>... --check
    uv run tools/migrate_config_v1_to_v2.py <file-or-dir>... --add-firmware [--firmware ID] [--in-place | --check]

A directory means every ``*.json`` directly inside it. Files that are already
v2 are left alone, so running it twice changes nothing. Without
``--in-place`` nothing is written. A v1 key the script does not know is
reported and the file is not converted (``--drop-unmapped`` converts it
anyway, dropping the key).

``--add-firmware`` also handles v2 files that lack the mandatory ``firmware`` key (gui-04): it inserts the id right
after ``board`` (inferred: a board with one firmware -> it, IWR1843/IWR6843/IWR6843ODS -> demo, IWR1443 -> dca1000_raw
if dca1000.enabled else demo; ``--firmware`` overrides), is idempotent, and with ``--check`` reports the files still
missing it (exit 1). A v1 conversion always writes ``firmware`` (same inference).

Mapping (v1 -> v2):
    verbose                                   -> runtime.log_level ("debug" if true, else "info")
    TI_Radar_Config_Management.TI_Radar_config_path -> radar_cfg (same relative path; a shipped cfg that moved in
                                                 the gui-38 reorganisation is rewritten via config/moved_paths.json,
                                                 and so is a v2 file's radar_cfg under --in-place / --check)
    CLI_Controller.CLI_port                   -> cli.port
    CLI_Controller.{baud_rate,cmd_timeout_ms} -> board_overrides.cli.{baud,cmd_timeout_ms}
    Streamer.serial_streaming.{enabled,data_port} -> serial_stream.{enabled,port}
    Streamer.serial_streaming.{baud_rate,timeout_ms} -> board_overrides.data_uart.{baud,timeout_ms}
    Streamer.DCA1000_streaming.{enabled,FPGA_IP,system_IP,cmd_port,data_port}
                                              -> dca1000.{enabled,fpga_ip,host_ip,cmd_port,data_port}
    Streamer.save_to_file                     -> output.save_adc_frames; output.save_raw_lvds is
                                                 false (the raw LVDS file is opt-in in v2, design D11)
    Streamer.board_type                       -> board (a descriptor in config/boards/)
    Streamer.SDK_version                      -> removed (the descriptor names the SDK); without
                                                 board_type, 2.x -> IWR1443 and 3.x -> IWR1843,
                                                 as the v1 driver did
    Processor, ROS, Listeners                 -> removed (never read by the driver)

A board_overrides value equal to the board descriptor's own value is dropped
(reported), when the descriptor is found: $CPSL_TI_RADAR_BOARDS_DIR if set,
else <config dir>/../boards, the same rule as the driver. output.dir is not
set, so files are written to the current directory as in v1.

Exit status: 0 on success (``--check``: every file is already v2); 1 if
``--check`` finds a v1 file; 2 on any error or unmapped key.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from radar_gui import sysjson  # noqa: E402  (shared writer: the GUI's Add-firmware button writes identical bytes)

SCHEMA_VERSION = 2
BOARDS_ENV = "CPSL_TI_RADAR_BOARDS_DIR"
REMOVED_TOP = ("Processor", "ROS", "Listeners")
MOVED_PATHS = Path(__file__).resolve().parent.parent / "CPSL_TI_Radar_cpp" / "config" / "moved_paths.json"


def remap_radar_cfg(value):
    """gui-38: a radar_cfg that points at a pre-reorganisation shipped cfg (config/moved_paths.json "radar") is
    rewritten to its new <BOARD>/<firmware>/ location. Any other value, and an already-new one, comes back unchanged."""
    if not isinstance(value, str) or "radar/" not in value or not MOVED_PATHS.is_file():
        return value
    i = value.index("radar/")
    new = json.loads(MOVED_PATHS.read_text()).get("radar", {}).get(value[i:])
    return value if new is None else value[:i] + new


class Unmapped(Exception):
    """v1 content the script cannot map."""


def is_v2(doc: dict) -> bool:
    return isinstance(doc, dict) and "schema_version" in doc


def _leftovers(d: dict, where: str, unmapped: list) -> None:
    for k in d:
        unmapped.append(f"{where}.{k}" if where else k)


def load_board(board: str, cfg_path: Path) -> dict | None:
    env = os.environ.get(BOARDS_ENV)
    boards = Path(env) if env else cfg_path.parent / ".." / "boards"
    p = boards / f"{board}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def convert(v1: dict, cfg_path: Path, forced: str | None = None) -> tuple[dict, list[str], list[str]]:
    """Return (v2 document, notes, unmapped keys). Does not modify ``v1``."""
    if not isinstance(v1, dict):
        raise Unmapped("top level is not a JSON object")
    src = json.loads(json.dumps(v1))  # deep copy; keys are popped as they are mapped
    notes: list[str] = []
    unmapped: list[str] = []

    verbose = src.pop("verbose", None)
    mgmt = src.pop("TI_Radar_Config_Management", None) or {}
    cli_v1 = src.pop("CLI_Controller", None) or {}
    streamer = src.pop("Streamer", None) or {}
    for k in REMOVED_TOP:
        if k in src:
            src.pop(k)
            notes.append(f"{k}: removed (never read by the driver)")
    _leftovers(src, "", unmapped)

    radar_cfg = mgmt.pop("TI_Radar_config_path", None)
    _leftovers(mgmt, "TI_Radar_Config_Management", unmapped)
    if radar_cfg is None:
        raise Unmapped("TI_Radar_Config_Management.TI_Radar_config_path is missing")
    radar_cfg = remap_radar_cfg(radar_cfg)

    overrides: dict = {}
    cli_port = cli_v1.pop("CLI_port", None)
    if cli_port is None:
        raise Unmapped("CLI_Controller.CLI_port is missing")
    if "baud_rate" in cli_v1:
        overrides.setdefault("cli", {})["baud"] = cli_v1.pop("baud_rate")
    if "cmd_timeout_ms" in cli_v1:
        overrides.setdefault("cli", {})["cmd_timeout_ms"] = cli_v1.pop("cmd_timeout_ms")
    _leftovers(cli_v1, "CLI_Controller", unmapped)

    ser_v1 = streamer.pop("serial_streaming", None)
    dca_v1 = streamer.pop("DCA1000_streaming", None)
    save_to_file = streamer.pop("save_to_file", None)
    board = streamer.pop("board_type", None)
    sdk = streamer.pop("SDK_version", None)
    _leftovers(streamer, "Streamer", unmapped)
    if sdk is not None:
        notes.append(f"Streamer.SDK_version {sdk!r}: removed (the board descriptor names the SDK)")
    if board is None:
        major = str(sdk).split(".")[0] if sdk is not None else ""
        board = {"2": "IWR1443", "3": "IWR1843"}.get(major)
        if board is None:
            raise Unmapped("Streamer.board_type is missing and SDK_version does not name a board")
        notes.append(f"board {board!r} derived from SDK_version {sdk!r} (as the v1 driver did)")

    serial = None
    if ser_v1 is not None:
        serial = {}
        if "enabled" in ser_v1:
            serial["enabled"] = ser_v1.pop("enabled")
        if "data_port" in ser_v1:
            serial["port"] = ser_v1.pop("data_port")
        if "baud_rate" in ser_v1:
            overrides.setdefault("data_uart", {})["baud"] = ser_v1.pop("baud_rate")
        if "timeout_ms" in ser_v1:
            overrides.setdefault("data_uart", {})["timeout_ms"] = ser_v1.pop("timeout_ms")
        _leftovers(ser_v1, "Streamer.serial_streaming", unmapped)

    dca = None
    if dca_v1 is not None:
        dca = {}
        for old, new in (("enabled", "enabled"), ("FPGA_IP", "fpga_ip"), ("system_IP", "host_ip"),
                         ("cmd_port", "cmd_port"), ("data_port", "data_port")):
            if old in dca_v1:
                dca[new] = dca_v1.pop(old)
        _leftovers(dca_v1, "Streamer.DCA1000_streaming", unmapped)

    # drop overrides that equal the descriptor's own values
    desc = load_board(board, cfg_path)
    if desc is None:
        if overrides:
            notes.append(f"board descriptor {board!r} not found: board_overrides kept as written")
    else:
        for section in list(overrides):
            for key in list(overrides[section]):
                if desc.get(section, {}).get(key) == overrides[section][key]:
                    notes.append(f"board_overrides.{section}.{key} = {overrides[section][key]!r} dropped "
                                 f"(same as {board}.json)")
                    del overrides[section][key]
            if not overrides[section]:
                del overrides[section]

    v2: dict = {"schema_version": SCHEMA_VERSION, "board": board}
    fw = firmware_for({"board": board, "dca1000": dca or {}}, forced)
    if fw is not None:
        v2["firmware"] = fw
        notes.append(f"firmware {fw!r} inferred from board {board!r}")
    if overrides:
        v2["board_overrides"] = overrides
    v2["radar_cfg"] = radar_cfg
    v2["cli"] = {"port": cli_port}
    if serial is not None:
        v2["serial_stream"] = serial
    if dca is not None:
        v2["dca1000"] = dca
    if save_to_file is not None:
        v2["output"] = {"save_adc_frames": bool(save_to_file), "save_raw_lvds": False}
        if save_to_file:
            notes.append("save_to_file true -> output.save_adc_frames true; output.save_raw_lvds false "
                         "(raw LVDS file is opt-in in v2)")
    if verbose is not None:
        v2["runtime"] = {"log_level": "debug" if verbose else "info"}
    return v2, notes, unmapped


def firmware_for(doc: dict, forced: str | None = None) -> str | None:
    return forced or sysjson.infer_firmware(doc)


dumps = sysjson.dumps


def expand(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            out.extend(sorted(q for q in p.glob("*.json") if q.is_file()))
        else:
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", type=Path, help="system config .json files or directories")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--in-place", action="store_true", help="rewrite v1 files as v2")
    mode.add_argument("--check", action="store_true",
                      help="write nothing; exit 1 if any file is still v1")
    ap.add_argument("--drop-unmapped", action="store_true",
                    help="convert even if a v1 key has no v2 mapping (the key is dropped)")
    ap.add_argument("--add-firmware", action="store_true",
                    help='also add the mandatory "firmware" key to v2 files lacking it')
    ap.add_argument("--firmware", metavar="ID", help="firmware id to write instead of the inferred one")
    ap.add_argument("--quiet", "-q", action="store_true", help="only report problems")
    args = ap.parse_args(argv)

    files = expand(args.paths)
    if not files:
        print("migrate: no .json files found", file=sys.stderr)
        return 2
    status = 0
    for path in files:
        try:
            doc = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            print(f"ERROR {path}: cannot read JSON ({exc})", file=sys.stderr)
            status = 2
            continue
        if is_v2(doc):
            if args.add_firmware and isinstance(doc, dict) and "firmware" not in doc:
                if args.check:
                    print(f"nofw    {path}: missing required key \"firmware\"", file=sys.stderr)
                    status = max(status, 1)
                    continue
                fw = firmware_for(doc, args.firmware)
                if fw is None:
                    print(f"ERROR {path}: cannot infer a firmware for board {doc.get('board')!r}: pass --firmware",
                          file=sys.stderr)
                    status = 2
                    continue
                listed = (load_board(str(doc.get("board")), path) or {}).get("firmwares")
                if isinstance(listed, list) and fw not in listed:
                    print(f"ERROR {path}: board {doc.get('board')} supports {', '.join(listed)}, not {fw!r}: "
                          f"pass --firmware", file=sys.stderr)
                    status = 2
                    continue
                out = dumps(sysjson.with_firmware(doc, fw))
                if args.in_place:
                    sysjson.atomic_write_text(path, out)
                    if not args.quiet:
                        print(f"wrote   {path}: firmware {fw!r}", file=sys.stderr)
                else:
                    if len(files) > 1:
                        sys.stdout.write(f"// {path}\n")
                    sys.stdout.write(out)
                continue
            moved = remap_radar_cfg(doc.get("radar_cfg")) if isinstance(doc, dict) else None
            if isinstance(doc, dict) and moved != doc.get("radar_cfg"):
                if args.check:
                    print(f"moved   {path}: radar_cfg {doc['radar_cfg']!r} is now {moved!r}", file=sys.stderr)
                    status = max(status, 1)
                    continue
                doc = {**doc, "radar_cfg": moved}
                if args.in_place:
                    sysjson.atomic_write_text(path, dumps(doc))
                    if not args.quiet:
                        print(f"wrote   {path}: radar_cfg -> {moved!r}", file=sys.stderr)
                    continue
            if not args.quiet:
                print(f"ok      {path}: already v2", file=sys.stderr)
            if not (args.in_place or args.check) and len(files) == 1:
                sys.stdout.write(dumps(doc))
            continue
        if args.check:
            print(f"v1      {path}: needs migration", file=sys.stderr)
            status = max(status, 1)
            continue
        try:
            v2, notes, unmapped = convert(doc, path, args.firmware)
        except Unmapped as exc:
            print(f"ERROR {path}: {exc}", file=sys.stderr)
            status = 2
            continue
        for k in unmapped:
            print(f"UNMAPPED {path}: {k}" + (" (dropped)" if args.drop_unmapped else ""), file=sys.stderr)
        if unmapped and not args.drop_unmapped:
            print(f"ERROR {path}: not converted, {len(unmapped)} unmapped key(s) "
                  f"(rerun with --drop-unmapped to drop them)", file=sys.stderr)
            status = 2
            continue
        if not args.quiet:
            for n in notes:
                print(f"note    {path}: {n}", file=sys.stderr)
        if args.in_place:
            sysjson.atomic_write_text(path, dumps(v2))
            if not args.quiet:
                print(f"wrote   {path}", file=sys.stderr)
        else:
            if len(files) > 1:
                sys.stdout.write(f"// {path}\n")
            sys.stdout.write(dumps(v2))
    return status


if __name__ == "__main__":
    sys.exit(main())
