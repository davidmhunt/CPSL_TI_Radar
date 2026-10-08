#!/usr/bin/env python3
"""Live point-cloud web viewer for the AWR2243 2-chip cascade EVM.

Opens the CLI and data ports, sends the chirp cfg, parses TLV frames (type 1 points, type 7 side
info) and streams them to the browser with Server-Sent Events. Only needs Python 3 + pyserial.

    python3 server.py                 # configure the board, then open http://localhost:8080
    python3 server.py --skip-config   # attach to a board that is already running

The demo accepts a cfg only once per power-up. When the board is power-cycled (USB drops and comes
back) the server notices, waits for the ports and configures it again automatically, re-reading the
cfg file, so you can edit thresholds and just power-cycle to try them.

The page's "Radar config" panel generates new cfgs (cfggen.py), picks which one the next power-up gets,
and runs TI's antenna calibration (the board prints the result on the CLI port every frame).
"""
import argparse
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial

import cfggen

BY_ID = "/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000"
HERE = os.path.dirname(os.path.abspath(__file__))
CFG_DIRS = {
    "driver": os.path.normpath(os.path.join(HERE, "..", "..", "CPSL_TI_Radar_cpp", "config", "radar",
                                            "AWR2243_CASCADE", "cascade_ddm")),
    "viewer": cfggen.OUT_DIR,
}
DEFAULT_CFG = os.path.join(CFG_DIRS["driver"], "shortrange.cfg")
CALIB_RE = re.compile(r"range\s+(-?[\d.]+)\s+peakVal\s+(\d+)\s+" +
                      r"\s+".join(rf"(antennaCalibParams{i}(?:\s+-?\d+\.\d+){{32}})" for i in (1, 2, 3)))

MAGIC = b"\x02\x01\x04\x03\x06\x05\x08\x07"
HEADER_FMT = "<8sIIIIIIII"  # magic, version, totalPacketLen, platform, frameNumber,
HEADER_LEN = struct.calcsize(HEADER_FMT)  # timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
PROMPT = b"mmwDemo:/>"


class Hub:
    """Fan-out of the latest frame / status to every connected browser."""

    def __init__(self):
        self.clients = set()
        self.lock = threading.Lock()
        self.status = {"type": "status", "state": "starting", "msg": "Starting"}
        self.cfg_info = {}
        self.cfg_path = None      # what the next power-up gets
        self.board_cfg = None     # what the board is running now
        self.calib = None         # {"distance", "window", "results": [...]} while a calibration cfg is active

    def subscribe(self):
        q = queue.Queue(maxsize=8)
        with self.lock:
            self.clients.add(q)
        q.put(self.status)
        if self.cfg_info:
            q.put(self.cfg_info)
        if self.calib and self.calib["results"]:
            q.put(self.calib["results"][-1])
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)

    def publish(self, msg):
        if msg.get("type") == "status":
            self.status = msg
            print(f"[{msg['state']}] {msg['msg']}", flush=True)
        elif msg.get("type") == "cfg":
            self.cfg_info = msg
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(msg)
            except queue.Full:  # slow browser: drop its oldest frame, keep the newest
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except (queue.Empty, queue.Full):
                    pass

    def set_status(self, state, msg):
        self.publish({"type": "status", "state": state, "msg": msg})

    def publish_cfg(self):
        """Tell the page what the board runs and what the next power-up will get."""
        info = {"type": "cfg"}
        if self.board_cfg:
            try:
                info.update(cfggen.analyze(cfggen.read_lines(self.board_cfg)))
            except OSError:
                pass
            info["name"] = os.path.basename(self.board_cfg)
        if self.cfg_path != self.board_cfg:
            info["next"] = os.path.basename(self.cfg_path)
        info["calibrating"] = bool(self.calib) and self.board_cfg == self.cfg_path
        self.publish(info)


def read_cfg(path):
    with open(path) as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith(("%", "#"))]


def read_until(port, needles, timeout_s):
    resp = b""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp += port.read(256)
        if any(n in resp for n in needles):
            break
    return resp


def configure(cli_path, baud, lines, hub):
    hub.set_status("configuring", f"Sending {len(lines)} cfg lines")
    with serial.Serial(cli_path, baud, timeout=0.05) as cli:
        cli.reset_input_buffer()
        for i, line in enumerate(lines, 1):
            cli.write((line + "\n").encode())
            resp = read_until(cli, (b"Done", b"Error", b"not recognized"), 5.0)
            if b"Done" not in resp:
                text = resp.decode(errors="replace").strip().replace("\n", " ")
                hub.set_status("cfg_failed",
                               f"'{line.split()[0]}' was not accepted ({text[:80] or 'no reply'}). "
                               "The board takes a cfg once per power-up: power-cycle it and the viewer "
                               "will reconfigure automatically.")
                return False
            # The cascade CLI drops input while it prints its prompt, so wait for it before the next line.
            if PROMPT not in resp:
                read_until(cli, (PROMPT,), 0.5)
            hub.set_status("configuring", f"{i}/{len(lines)} {line.split()[0]}")
    return True


def parse_frame(pkt):
    (_, _, total_len, platform, frame_num, _, num_obj, num_tlvs, _) = struct.unpack_from(HEADER_FMT, pkt)
    off = HEADER_LEN
    pts, side = [], []
    for _ in range(num_tlvs):
        if off + 8 > len(pkt):
            break
        tlv_type, tlv_len = struct.unpack_from("<II", pkt, off)
        off += 8
        body = pkt[off:off + tlv_len]
        if tlv_type == 1:
            pts = list(struct.iter_unpack("<ffff", body[:len(body) // 16 * 16]))
        elif tlv_type == 7:
            side = list(struct.iter_unpack("<hh", body[:len(body) // 4 * 4]))
        off += tlv_len
    out = []
    for i, (x, y, z, v) in enumerate(pts):
        if not all(map(math.isfinite, (x, y, z, v))):
            continue
        snr = side[i][0] * 0.1 if i < len(side) else 0.0  # 0.1 dB units
        noise = side[i][1] * 0.1 if i < len(side) else 0.0
        out.append([round(x, 3), round(y, 3), round(z, 3), round(v, 3), round(snr, 1), round(noise, 1)])
    return {"type": "frame", "frame": frame_num, "platform": platform, "n": num_obj, "t": time.time(),
            "pts": out}


def stream(data_path, baud, hub, stop):
    """Read frames until the port disappears. Returns when the board is unplugged / power-cycled."""
    buf = b""
    last_frame = None
    gaps = errors = frames = 0
    t0 = time.monotonic()
    last_rx = time.monotonic()
    with serial.Serial(data_path, baud, timeout=0.05) as data:
        data.reset_input_buffer()
        hub.set_status("waiting", "Listening on the data port")
        while not stop.is_set():
            chunk = data.read(8192)
            if chunk:
                buf += chunk
                last_rx = time.monotonic()
            elif time.monotonic() - last_rx > 3 and hub.status["state"] == "streaming":
                hub.set_status("stalled", "No data for 3 s. Power-cycle the board to restart it.")
            while True:
                i = buf.find(MAGIC)
                if i < 0:
                    buf = buf[-7:]
                    break
                if i > 0:
                    errors += 1 if frames else 0
                    buf = buf[i:]
                if len(buf) < HEADER_LEN:
                    break
                total_len = struct.unpack_from("<I", buf, 12)[0]
                if total_len < HEADER_LEN or total_len > 1 << 20:
                    errors += 1
                    buf = buf[8:]
                    continue
                if len(buf) < total_len:
                    break
                pkt, buf = buf[:total_len], buf[total_len:]
                try:
                    msg = parse_frame(pkt)
                except struct.error:
                    errors += 1
                    continue
                if last_frame is not None and msg["frame"] != last_frame + 1:
                    gaps += 1
                last_frame = msg["frame"]
                frames += 1
                msg.update(gaps=gaps, errors=errors, frames=frames,
                           rate=frames / max(time.monotonic() - t0, 1e-3))
                if hub.status["state"] != "streaming":
                    hub.set_status("streaming", "Streaming")
                hub.publish(msg)


def publish_calib(hub, cal, rng, peak, lines):
    prev = cal["results"][-1] if cal["results"] else None
    change = None
    if prev:  # largest change in any calibration coefficient since the last frame: a steady setup stays small
        a = [float(v) for l in lines for v in l.split()[1:]]
        b = [float(v) for l in prev["lines"] for v in l.split()[1:]]
        change = max(abs(x - y) for x, y in zip(a, b))
    res = {"type": "calib", "range": rng, "peak": peak, "lines": lines, "n": len(cal["results"]) + 1,
           "distance": cal["distance"], "window": cal["window"], "change": change,
           "ok": abs(rng - cal["distance"]) <= cal["window"], "t": time.time()}
    cal["results"] = (cal["results"] + [res])[-20:]
    hub.publish(res)
    print(f"[calib] range {rng:.3f} m peakVal {peak}", flush=True)


def calib_monitor(cli_path, baud, hub, stop):
    """While a calibration cfg runs, the demo prints 'range R peakVal P' and antennaCalibParams1..3 every frame."""
    buf = ""
    try:
        with serial.Serial(cli_path, baud, timeout=0.2) as cli:
            while not stop.is_set():
                buf += cli.read(4096).decode(errors="replace")
                end = 0
                for m in CALIB_RE.finditer(buf):
                    end = m.end()
                    cal = hub.calib
                    if not cal:
                        return
                    publish_calib(hub, cal, float(m.group(1)), int(m.group(2)),
                                  [" ".join(m.group(i).split()) for i in (3, 4, 5)])
                buf = buf[end:][-8192:]
    except (serial.SerialException, OSError):
        pass


def load_cfg(path, hub):
    """Read the cfg fresh each time, so edits take effect on the next power cycle."""
    return read_cfg(path)


def radar_loop(args, hub, stop):
    hub.cfg_path = hub.board_cfg = args.cfg
    hub.publish_cfg()
    skip = args.skip_config
    while not stop.is_set():
        if not (os.path.exists(args.cli) and os.path.exists(args.data)):
            hub.set_status("no_board", "Board not found on USB. Is the 12 V supply on?")
            while not stop.is_set() and not (os.path.exists(args.cli) and os.path.exists(args.data)):
                time.sleep(0.5)
            time.sleep(1.5)  # let the XDS110 finish enumerating
            skip = False  # fresh power-up: it needs the cfg
            continue
        try:
            if not skip:
                path = hub.cfg_path
                ok = configure(args.cli, args.cli_baud, load_cfg(path, hub), hub)
                hub.board_cfg = path if ok else None
                hub.publish_cfg()
            skip = True  # never re-send to the same power-up; only a reconnect resets this
            mon_stop = threading.Event()
            if hub.calib and hub.board_cfg == hub.cfg_path:
                hub.calib["results"] = []
                threading.Thread(target=calib_monitor, args=(args.cli, args.cli_baud, hub, mon_stop),
                                 daemon=True).start()
            try:
                stream(args.data, args.data_baud, hub, stop)
            finally:
                mon_stop.set()
        except (serial.SerialException, OSError) as e:
            hub.set_status("no_board", f"Serial port lost ({e.__class__.__name__}). Waiting for the board.")
            time.sleep(2)  # a power cycle drops USB for ~2-3 s; don't configure a half-enumerated board
            skip = False


def list_cfgs():
    out = []
    for where, d in CFG_DIRS.items():
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".cfg"):
                    out.append({"name": f, "where": where, "path": os.path.join(d, f)})
    return out


def api(hub, path, body):
    """JSON API for the config panel. Returns (status, payload)."""
    if path == "/api/state":
        cal = cfggen.load_calibration()
        return 200, {"cfgs": list_cfgs(), "next": hub.cfg_path, "board": hub.board_cfg, "defaults": cfggen.DEFAULTS,
                     "samples": cfggen.SAMPLE_OPTIONS, "chirps": cfggen.CHIRP_OPTIONS,
                     "calibration": cal and cal["comment"],
                     "calib_results": hub.calib["results"][-1:] if hub.calib else []}
    if path in ("/api/preview", "/api/save"):
        try:
            res = cfggen.generate(body.get("params", {}))
        except cfggen.CfgError as e:
            return 200, {"error": str(e)}
        if path == "/api/save":
            res["path"] = cfggen.write(res)
            if body.get("use"):
                hub.cfg_path, hub.calib = res["path"], None
                hub.publish_cfg()
        return 200, res
    if path == "/api/use":
        allowed = {c["path"] for c in list_cfgs()}
        if body.get("path") not in allowed:
            return 400, {"error": "Unknown cfg"}
        hub.cfg_path = body["path"]
        hub.calib = None
        hub.publish_cfg()
        return 200, {"next": hub.cfg_path}
    if path == "/api/calibrate":
        try:
            dist, win = float(body.get("distance", 3)), float(body.get("window", 0.5))
            hub.cfg_path = cfggen.calibration_cfg(dist, win)
        except (cfggen.CfgError, ValueError) as e:
            return 200, {"error": str(e)}
        hub.calib = {"distance": dist, "window": win, "results": []}
        hub.publish_cfg()
        return 200, {"next": hub.cfg_path}
    if path == "/api/calibration/save":
        results = hub.calib["results"] if hub.calib else []
        if not results:
            return 200, {"error": "No calibration result yet."}
        cfggen.save_calibration(results[-1])
        return 200, {"saved": cfggen.CALIB_FILE, "comment": cfggen.load_calibration()["comment"]}
    return 404, {"error": "not found"}


def make_handler(hub):
    page = os.path.join(HERE, "index.html")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send_json(self, status, payload):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self.send_json(400, {"error": "bad JSON"})
            self.send_json(*api(hub, self.path, body))

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                with open(page, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/state":
                self.send_json(*api(hub, self.path, {}))
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = hub.subscribe()
                try:
                    while True:
                        try:
                            msg = q.get(timeout=10)
                            self.wfile.write(b"data: " + json.dumps(msg).encode() + b"\n\n")
                        except queue.Empty:
                            self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    hub.unsubscribe(q)
            else:
                self.send_error(404)

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cli", default=BY_ID + "-if00", help="CLI (Application/User UART) port")
    p.add_argument("--data", default=BY_ID + "-if03", help="data port")
    p.add_argument("--cfg", default=os.path.normpath(DEFAULT_CFG), help="chirp cfg (needs guiMonitor -1 1 ...)")
    p.add_argument("--cli-baud", type=int, default=115200)
    p.add_argument("--data-baud", type=int, default=3125000)
    p.add_argument("--skip-config", action="store_true", help="board is already configured and running")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    args = p.parse_args()
    args.cfg = os.path.abspath(args.cfg)

    hub = Hub()
    stop = threading.Event()
    threading.Thread(target=radar_loop, args=(args, hub, stop), daemon=True).start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(hub))
    server.daemon_threads = True
    print(f"Viewer on http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.port}  "
          f"(cfg: {args.cfg})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
