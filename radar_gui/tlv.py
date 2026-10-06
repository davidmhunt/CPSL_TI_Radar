"""TLV frame helpers. Parsing reuses tools/radar_viewer/server.py (kept untouched as reference)."""
import importlib.util
import os
import struct
import sys

_VIEWER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "radar_viewer")


def _load_viewer():
    path = os.path.normpath(os.path.join(_VIEWER, "server.py"))
    sys.path.insert(0, os.path.dirname(path))  # server.py does `import cfggen`
    try:
        spec = importlib.util.spec_from_file_location("radar_viewer_server", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(os.path.dirname(path))


_v = _load_viewer()
parse_frame = _v.parse_frame
MAGIC = _v.MAGIC
HEADER_FMT = _v.HEADER_FMT
HEADER_LEN = _v.HEADER_LEN


def split_packets(data: bytes):
    """Yield each frame packet in a raw dump (magic word + totalPacketLen framing)."""
    i = 0
    while True:
        i = data.find(MAGIC, i)
        if i < 0 or i + HEADER_LEN > len(data):
            return
        total = struct.unpack_from("<I", data, i + 12)[0]
        if total < HEADER_LEN or i + total > len(data):
            return
        yield data[i:i + total]
        i += total


def build_packet(frame_num, pts, snr_db=None):
    """Build one TLV packet: pts = [(x, y, z, v)], snr_db = per-point SNR in dB (default 10)."""
    body1 = b"".join(struct.pack("<ffff", *p) for p in pts)
    body7 = b"".join(struct.pack("<hh", int(round((snr_db[i] if snr_db else 10.0) * 10)), 0)
                     for i in range(len(pts)))
    tlvs = struct.pack("<II", 1, len(body1)) + body1 + struct.pack("<II", 7, len(body7)) + body7
    total = HEADER_LEN + len(tlvs)
    head = struct.pack(HEADER_FMT, MAGIC, 0, total, 0, frame_num, 0, len(pts), 2, 0)
    return head + tlvs
