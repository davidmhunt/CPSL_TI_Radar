"""SerialSource (gui-06): configure a TI radar over its CLI port and stream the demo's TLV point cloud from the
data port. Ports the configure / stream / reconnect logic of tools/radar_viewer/server.py; serial settings and the
TLV dialect come from CPSL_TI_Radar_cpp/config/boards/<board>.json (`cli`, `data_uart`, `lifecycle`, `cfg_dialect`).

Only pyserial-touching code is `open_serial`; everything else talks to a `SerialPort` (read/write/reset_input_buffer/
close), so tests pass fakes. Blocking port I/O runs in worker threads; status goes through `on_status(state, msg)`
on the event loop. Status states: configuring, cfg_failed, wrong_firmware (gui-33), waiting, streaming, stalled, no_board, error."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Callable, Protocol

from . import fwident
from . import ports as portsmod
from . import tlv
from .cfg import firmware as fwmod
from .sources import Source

CLI_STALL_HINT = "No data for 3 s."
COMPACT_HINT = "cfg sends compact points; use guiMonitor detectedObjects 1"
ONCE_HINT = "power-cycle the board"


class SerialSourceError(ValueError):
    """Bad request (unknown board, no data UART, unreadable cfg)."""


class PortBusy(RuntimeError):
    """The radar lock or a serial port is held by someone else."""


class SerialPort(Protocol):
    def read(self, n: int) -> bytes: ...          # up to n bytes; b"" when nothing arrived in the short timeout
    def write(self, data: bytes) -> None: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...


def open_serial(path: str, baud: int) -> SerialPort:
    import serial  # pyserial: the only place it is imported

    return serial.Serial(path, baud, timeout=0.05)


def load_board(board: str) -> dict:
    p = fwmod.BOARDS_DIR / f"{board}.json"
    if not board or "/" in board or not p.is_file():
        raise SerialSourceError(f"unknown board {board!r}")
    d = json.loads(p.read_text())
    du = d.get("data_uart") or {}
    if du.get("supported") is False or "baud" not in du:
        raise SerialSourceError(f"{board} has no data UART (LVDS-only firmware): the serial source cannot read it")
    if du.get("tlv_dialect") not in tlv.DIALECTS:
        raise SerialSourceError(f"{board}: unknown tlv_dialect {du.get('tlv_dialect')!r}")
    # the command rules and prompt depend on the firmware the source needs (gui-33 Step 4), not on the board
    rules = fwmod.cfg_rules(board, expected_firmware(board))
    d["cfg_dialect"] = {**(d.get("cfg_dialect") or {}), "skip_commands": rules["skip_commands"]}
    if rules["prompt"]:
        d["cli"] = {**d["cli"], "prompt": rules["prompt"]}
    return d


def expected_firmware(board: str) -> str | None:
    """The firmware a serial source needs on `board`: the first one it lists that outputs TLV (IWR1843 -> demo,
    AWR2243_CASCADE -> cascade_ddm); None if the board lists none."""
    for fid in fwmod.board_firmwares(board) or []:
        d = fwmod.get(fid)
        if d and (d.get("outputs") or {}).get(board, {}).get("tlv"):
            return fid
    return None


def cfg_lines(path, desc: dict) -> list[str]:
    cli, dia = desc["cli"], desc.get("cfg_dialect") or {}
    prefixes, skip = tuple(cli.get("skip_prefixes") or ()), set(dia.get("skip_commands") or ())
    try:
        text = open(path, errors="replace").read()
    except OSError as e:
        raise SerialSourceError(f"cannot read cfg {path}: {e}") from e
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or (prefixes and line.startswith(prefixes)) or line.split()[0] in skip:
            continue
        out.append(line)
    if not out:
        raise SerialSourceError(f"cfg {path} has no commands")
    return out


class SerialSource(Source):
    name = "serial"
    drives_status = True     # the Hub leaves status to the source

    def __init__(self, board, cfg_path, cli_port, data_port, skip_configure=False, dump=None, *,
                 opener: Callable[[str, int], SerialPort] = open_serial, exists=os.path.exists,
                 lock=portsmod.radar_lock, check=portsmod.check_ports, on_status=None,
                 stall_s=3.0, poll_s=0.5, settle_s=1.5, stop_wait_s=0.3, skip_firmware_check=False):
        self.board, self.desc = board, load_board(board)
        self.cfg_path, self.cli_port, self.data_port = str(cfg_path), cli_port, data_port
        self.lines = cfg_lines(cfg_path, self.desc)
        self.skip_configure, self.dump = bool(skip_configure), dump
        self.opener, self.exists, self.lock, self.check = opener, exists, lock, check
        self.on_status = on_status or (lambda s, m: None)
        self.stall_s, self.poll_s, self.settle_s, self.stop_wait_s = stall_s, poll_s, settle_s, stop_wait_s
        self.once = bool(self.desc.get("lifecycle", {}).get("config_once_per_boot"))
        self.dialect = self.desc["data_uart"]["tlv_dialect"]
        self.state, self.msg = "starting", ""
        self._last_raw = b""
        self.cli: list[dict] = []        # board command transcript of the latest configure attempt (gui-34)
        self.skip_firmware_check = bool(skip_firmware_check)
        self.fw_expected = expected_firmware(board)
        self.firmware: dict | None = None    # latest firmware identity check (gui-33): fwident.identify result + expected
        self.claimed = self.started = False
        self.info = self._info()

    # -- hints for the page -------------------------------------------------
    def _info(self):
        info = {"max_range_m": 10, "fov": [-60, 60], "board": self.board}
        try:
            from .cfg import metrics, parse_cfg_file

            info["max_range_m"] = round(metrics(parse_cfg_file(self.cfg_path), self.board).max_range_m, 2)
        except Exception:  # a cfg the analyser rejects still streams; keep the default hint
            pass
        return info

    @property
    def cli_first_fail(self):
        """1-based position in `cli` of the first command the board did not answer Done to, else None."""
        return next((e["seq"] for e in self.cli if e["verdict"] in ("ERROR", "TIMEOUT") and e.get("tag") != "id"), None)

    def _record(self, line, ok, reply, ms, i=None, n=None, tag=None):
        verdict = "DONE" if ok else ("ERROR" if self._has_error(reply) else "TIMEOUT")
        self.cli.append({"seq": len(self.cli) + 1, "i": i, "n": n, "tag": tag, "cmd": line, "ok": ok, "verdict": verdict,
                         "reply": reply, "ms": ms})

    def _has_error(self, reply):
        return any(t in reply for t in self.desc["cli"].get("error_tokens", []))

    def _status(self, state, msg=""):
        self.state, self.msg = state, msg
        self.on_status(state, msg)

    # -- exclusion ------------------------------------------------------------
    @property
    def holds_lock(self):
        return self.claimed

    def claim(self):
        """Take the radar lock and check the ports; raise PortBusy with the reason otherwise. Idempotent."""
        if self.claimed:
            return
        if not self.lock.acquire("serial"):
            raise PortBusy(f"radar in use by {self.lock.owner}")
        why = self.check([self.cli_port, self.data_port])
        if why:
            self.lock.release("serial")
            raise PortBusy(why)
        self.claimed = True

    def release(self):
        if self.claimed:
            self.claimed = False
            self.lock.release("serial")

    # -- configure ---------------------------------------------------------------
    def _read_until(self, port, needles, timeout_s):
        resp, end = b"", time.monotonic() + timeout_s
        while time.monotonic() < end:
            resp += port.read(256)
            if any(n in resp for n in needles):
                break
        return resp

    def _timed_send(self, cli, line, i=None, n=None, tag=None):
        """_send_line plus a transcript entry (reply as ' | '-joined lines without the echo / prompt, capped)."""
        t0 = time.monotonic()
        ok, reply = self._send_line(cli, line)
        ms = round((time.monotonic() - t0) * 1000)
        prompt = self.desc["cli"].get("prompt", "")
        parts = [p.strip() for p in self._last_raw.decode(errors="replace").replace("\r", "").split("\n")]
        parts = [p for p in parts if p and p != line and not (prompt and p.endswith(prompt)) and not (ok and p == "Done")]
        text = " | ".join(parts)
        self._record(line, ok, text if len(text) <= 200 else text[:199] + "\u2026", ms, i, n, tag)
        return ok, reply

    def _send_line(self, cli, line):
        """(ok, reply). Waits for the prompt too on the cascade, whose CLI drops input while it prints it."""
        c = self.desc["cli"]
        ack, errs = c.get("ack", "Done").encode(), [t.encode() for t in c.get("error_tokens", [])]
        prompt = c.get("prompt", "").encode()
        cli.write((line + "\n").encode())
        resp = self._read_until(cli, [ack] + errs, max(c.get("cmd_timeout_ms", 1000), 1000) / 1000)
        self._last_raw = resp
        text = resp.decode(errors="replace").strip().replace("\n", " ")
        if any(e in resp for e in errs) or ack not in resp:
            return False, text
        if self.dialect == "mcuplus_cascade" and prompt and prompt not in resp:
            self._read_until(cli, [prompt], c.get("prompt_wait_ms", 500) / 1000)
        return True, text

    def _probe(self, cli, cmd, timeout_ms):
        """Send one identify probe, read until the ack / an error token / the timeout; (reply text, None if no reply)."""
        c = self.desc["cli"]
        needles = [c.get("ack", "Done").encode()] + [t.encode() for t in c.get("error_tokens", [])]
        cli.reset_input_buffer()
        t0 = time.monotonic()
        cli.write((cmd + "\n").encode())
        resp = self._read_until(cli, needles, timeout_ms / 1000)
        if any(n in resp for n in needles):      # let the rest of the reply (and the prompt) arrive
            resp += self._read_until(cli, [c.get("prompt", "").encode() or b"\0"], 0.15)
        text = resp.decode(errors="replace").replace("\r", "")
        parts = [p.strip() for p in text.split("\n")]
        prompt = c.get("prompt", "")
        parts = [p for p in parts if p and p != cmd and not (prompt and p.endswith(prompt)) and p != "Done"]
        shown = " | ".join(parts)
        self.cli.append({"seq": len(self.cli) + 1, "i": None, "n": None, "tag": "id", "cmd": cmd, "ok": bool(text.strip()),
                         "verdict": "DONE" if text.strip() else "TIMEOUT", "reply": shown if len(shown) <= 200 else shown[:199] + "\u2026",
                         "ms": round((time.monotonic() - t0) * 1000)})
        return text if text.strip() else None

    def _check_firmware(self, cli) -> dict | None:
        """Ask the board what it runs (before any cfg line) and compare with the expected firmware; None = not checked."""
        fw = self.fw_expected
        if self.skip_firmware_check or not fw:
            self.firmware = None
            return None
        res = fwident.identify(fw, self.board, {}, once=self.once) if self.once else None
        if res is None or res["verdict"] != "skipped":
            to = fwident.timeout_ms(fw, self.board)
            replies = {p["cmd"]: self._probe(cli, p["cmd"], to) for p in fwident.probes(fw, self.board)}
            res = fwident.identify(fw, self.board, replies, once=self.once)
        self.firmware = {"expected": fw, **res}
        return self.firmware

    async def _configure(self) -> bool:
        n = len(self.lines)
        self.cli = []
        self._status("configuring", f"configuring 0/{n}")
        cli = await asyncio.to_thread(self.opener, self.cli_port, self.desc["cli"]["baud"])
        try:
            await asyncio.to_thread(cli.reset_input_buffer)
            fwr = await asyncio.to_thread(self._check_firmware, cli)
            if fwr and fwr["verdict"] == "mismatch":
                self._status("wrong_firmware", fwident.mismatch_message(fwr["expected"], self.board, fwr, self.cli_port)
                             + ". Or tick 'Skip firmware check' to send the cfg anyway. Ports released.")
                return False
            if fwr and fwr["verdict"] == "unknown":
                self._status("configuring", f"configuring 0/{n} (firmware not verified: {fwr['detail']})")
            for i, line in enumerate(self.lines, 1):
                ok, reply = await asyncio.to_thread(self._timed_send, cli, line, i, n)
                if not ok:
                    msg = f"line {i}/{n} '{line}' was not accepted ({reply[:80] or 'no reply'})."
                    if self.once:
                        msg += f" This board takes a cfg once per power-up: {ONCE_HINT}, or tick 'already configured' to just attach."
                    else:
                        msg += " Ports released: fix the cfg or the board, then press Start to retry."
                    self._status("cfg_failed", msg)
                    return False
                self._status("configuring", f"configuring {i}/{n} {line.split()[0]}")
        finally:
            await asyncio.to_thread(cli.close)
        return True

    # -- stream ------------------------------------------------------------------
    def _both_exist(self):
        return self.exists(self.cli_port) and self.exists(self.data_port)

    async def _wait_ports(self):
        self._status("no_board", "Board not found on USB. Is it powered?")
        while not self._both_exist():
            await asyncio.sleep(self.poll_s)
        await asyncio.sleep(self.settle_s)   # let the XDS110 finish enumerating

    async def _stream(self):
        reader = tlv.FrameReader(self.dialect)
        data = await asyncio.to_thread(self.opener, self.data_port, self.desc["data_uart"]["baud"])
        dump = open(self.dump, "ab") if self.dump else None
        try:
            await asyncio.to_thread(data.reset_input_buffer)
            self._status("waiting", "Listening on the data port")
            last_rx = last_exist = time.monotonic()
            hinted = False
            while True:
                chunk = await asyncio.to_thread(data.read, 8192)
                now = time.monotonic()
                if chunk:
                    last_rx = now
                    if dump:
                        dump.write(chunk)
                        dump.flush()
                elif now - last_rx > self.stall_s and self.state in ("waiting", "streaming"):
                    self._status("stalled", CLI_STALL_HINT + (f" {ONCE_HINT.capitalize()} to restart it." if self.once
                                                              else " Check the cfg and the data port."))
                if now - last_exist > 1.0:
                    last_exist = now
                    if not self._both_exist():
                        raise OSError("serial port disappeared")
                for fr in reader.feed(chunk) if chunk else ():
                    if fr.get("compact_points_skipped") and not hinted:
                        hinted = True
                        self._status("streaming", COMPACT_HINT)
                    elif self.state != "streaming":
                        self._status("streaming", COMPACT_HINT if hinted else "")
                    yield fr
        finally:
            if dump:
                dump.close()
            await asyncio.to_thread(data.close)

    async def frames(self):
        self.claim()
        skip = self.skip_configure
        try:
            while True:
                try:
                    if not self._both_exist():
                        await self._wait_ports()
                        skip = False   # a fresh power-up needs the cfg
                    if not skip:
                        if not await self._configure():
                            if not self.once:
                                # A board that takes repeated cfgs: free the ports and the radar lock so the user can
                                # fix the cfg and press Start again; keep the cfg_failed status until then.
                                self.release()
                                while True:
                                    await asyncio.sleep(3600)
                            while self._both_exist():   # stay put until the board is power-cycled
                                await asyncio.sleep(self.poll_s)
                            skip = False
                            continue
                    self.started, skip = True, True   # never re-send to the same power-up
                    async for fr in self._stream():
                        yield fr
                except OSError as e:
                    self._status("no_board", f"Serial port lost ({e.__class__.__name__}). Waiting for the board.")
                    await asyncio.sleep(self.settle_s)   # a power cycle drops USB for ~2-3 s
                    skip = False
        finally:
            self._stop_radar()
            self.release()

    def _stop_radar(self):
        """sensorStop for boards that take repeated cfgs; the once-per-boot cascade is left streaming."""
        stop = self.desc["cli"].get("stop_cmd")
        if not (self.started and stop and not self.once and self._both_exist()):
            return
        try:
            cli = self.opener(self.cli_port, self.desc["cli"]["baud"])
        except OSError:
            return
        try:
            t0 = time.monotonic()
            cli.write((stop + "\n").encode())
            resp = self._read_until(cli, [self.desc["cli"].get("ack", "Done").encode()], self.stop_wait_s)
            ok = self.desc["cli"].get("ack", "Done").encode() in resp
            self._last_raw = resp
            self._record(stop, ok, "" if ok else resp.decode(errors="replace").strip().replace("\n", " | ")[:200],
                         round((time.monotonic() - t0) * 1000), tag="stop")
        except OSError:
            pass
        finally:
            try:
                cli.close()
            except OSError:
                pass
