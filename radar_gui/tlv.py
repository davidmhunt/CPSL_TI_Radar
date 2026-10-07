"""TLV frame parsing for the GUI (own implementation; layouts mirror CPSL_TI_Radar_cpp/src/SerialStreamer/UartFrame.cpp).

Dialects (board descriptor `data_uart.tlv_dialect`):
  sdk2             36 B header; TLV 1 = {u16 n, u16 xyzQFormat} + 12 B/object, x/y/z = int16 / 2^Q m; no v, SNR, noise
                   (sent to the page as 0).
  sdk3             40 B header; TLV 1 = float32 x, y, z, v (16 B/point); TLV 7 = int16 snr, noise in 0.1 dB.
  mcuplus_cascade  as sdk3; TLV 12 (compact points, guiMonitor detectedObjects 3) is not decoded, only flagged
                   (`compact_points_skipped`), exactly as the driver does.
"""
from __future__ import annotations

import math
import struct
import time

MAGIC = b"\x02\x01\x04\x03\x06\x05\x08\x07"
DIALECTS = ("sdk2", "sdk3", "mcuplus_cascade")
HEADER_BYTES = {"sdk2": 36, "sdk3": 40, "mcuplus_cascade": 40}
HEADER_LEN = 40            # the sdk3 / cascade header (kept for callers that predate dialects)
HEADER_FMT = "<8sIIIIIIII"
MAX_PACKET = 1 << 20       # kUartMaxPacketBytes
TLV_POINTS, TLV_SIDE, TLV_COMPACT = 1, 7, 12


class TlvError(ValueError):
    """A malformed frame (mirrors Code::malformed_frame)."""


def _check(dialect):
    if dialect not in HEADER_BYTES:
        raise TlvError(f"unknown tlv dialect {dialect!r}; one of {list(DIALECTS)}")
    return HEADER_BYTES[dialect]


def parse_frame(pkt: bytes, dialect: str = "sdk3") -> dict:
    """One whole packet (magic .. totalPacketLen) -> {"type":"frame","frame","platform","n","t","pts":[[x,y,z,v,snr,noise]...]}.
    `compact_points_skipped: True` is added when a cascade frame carried TLV 12. Raises TlvError if malformed."""
    hdr = _check(dialect)
    if len(pkt) < hdr:
        raise TlvError(f"truncated header: {len(pkt)} of {hdr} bytes")
    if pkt[:8] != MAGIC:
        raise TlvError("no magic word at the start of the frame")
    _, _, total, platform, frame_num, _, num_obj, num_tlvs = struct.unpack_from("<8sIIIIIII", pkt)
    if total < hdr or total > MAX_PACKET:
        raise TlvError(f"totalPacketLen {total} outside [{hdr}, {MAX_PACKET}]")
    if len(pkt) < total:
        raise TlvError(f"truncated frame: {len(pkt)} of {total} bytes")
    if num_tlvs > (total - hdr) // 8:
        raise TlvError(f"numTLVs {num_tlvs} cannot fit in {total - hdr} bytes")
    off, points, side, compact = hdr, None, None, False
    for i in range(num_tlvs):
        if total - off < 8:
            raise TlvError(f"TLV {i} header runs past totalPacketLen {total}")
        ttype, tlen = struct.unpack_from("<II", pkt, off)
        if tlen > total - off - 8:
            raise TlvError(f"TLV {i} (type {ttype}) length {tlen} runs past totalPacketLen {total}")
        body = pkt[off + 8:off + 8 + tlen]
        if ttype == TLV_POINTS:
            if points is not None:
                raise TlvError("two detected-points TLVs (type 1)")
            points = body
        elif ttype == TLV_SIDE and dialect != "sdk2":
            if side is not None:
                raise TlvError("two side info TLVs (type 7)")
            side = body
        elif ttype == TLV_COMPACT and dialect == "mcuplus_cascade":
            compact = True
        off += 8 + tlen
    pts = _points(points, side, num_obj, dialect) if points is not None else []
    out = {"type": "frame", "frame": frame_num, "platform": platform, "n": num_obj, "t": time.time(), "pts": pts}
    if compact:
        out["compact_points_skipped"] = True
    return out


def _points(body, side, num_obj, dialect):
    raw = []  # (x, y, z, v)
    if dialect == "sdk2":
        if len(body) < 4:
            raise TlvError(f"sdk2 points TLV length {len(body)} is shorter than its 4-byte descriptor")
        n, q = struct.unpack_from("<HH", body)
        if len(body) != 4 + 12 * n:
            raise TlvError(f"sdk2 points TLV length {len(body)} does not match its {n} objects")
        if n != num_obj:
            raise TlvError(f"sdk2 points TLV holds {n} objects but numDetectedObj is {num_obj}")
        if q > 31:
            raise TlvError(f"sdk2 xyzQFormat {q} is out of range")
        s = 2.0 ** -q
        for _rng, _dop, _peak, x, y, z in struct.iter_unpack("<HhHhhh", body[4:]):
            raw.append((x * s, y * s, z * s, 0.0))
        snr = []
    else:
        if len(body) % 16:
            raise TlvError(f"points TLV length {len(body)} is not a multiple of 16 (float x, y, z, v)")
        if len(body) // 16 != num_obj:
            raise TlvError(f"points TLV holds {len(body) // 16} points but numDetectedObj is {num_obj}")
        raw = list(struct.iter_unpack("<ffff", body))
        if side is not None:
            if len(side) % 4:
                raise TlvError(f"side info TLV length {len(side)} is not a multiple of 4")
            if len(side) // 4 != len(raw):
                raise TlvError(f"side info TLV holds {len(side) // 4} entries for {len(raw)} points")
        snr = list(struct.iter_unpack("<hh", side)) if side is not None else []
    out = []
    for i, (x, y, z, v) in enumerate(raw):
        if not all(map(math.isfinite, (x, y, z, v))):
            continue
        s, nz = (snr[i][0] * 0.1, snr[i][1] * 0.1) if i < len(snr) else (0.0, 0.0)
        out.append([round(x, 3), round(y, 3), round(z, 3), round(v, 3), round(s, 1), round(nz, 1)])
    return out


class FrameReader:
    """Incremental serial framing like SerialStreamer: magic resync, totalPacketLen bound, bad frames dropped and the
    search restarted one byte after their magic. feed(bytes) -> list of frame dicts; counters: frames, errors, gaps."""

    def __init__(self, dialect: str = "sdk3"):
        self.hdr = _check(dialect)
        self.dialect = dialect
        self.buf = b""
        self.frames = self.errors = self.gaps = 0
        self.last_frame = None
        self.quiet = False   # True while re-syncing after a dropped frame (its skipped bytes are not a second error)

    def feed(self, data: bytes) -> list:
        self.buf += data
        out = []
        while True:
            i = self.buf.find(MAGIC)
            if i < 0:
                self.buf = self.buf[-(len(MAGIC) - 1):]
                break
            if i > 0:
                self.errors += 1 if self.frames and not self.quiet else 0  # junk before a frame (not the first partial one)
                self.buf = self.buf[i:]
            self.quiet = False
            if len(self.buf) < self.hdr:
                break
            total = struct.unpack_from("<I", self.buf, 12)[0]
            if total < self.hdr or total > MAX_PACKET:
                self.errors += 1
                self.quiet = True
                self.buf = self.buf[1:]
                continue
            if len(self.buf) < total:
                break
            pkt, self.buf = self.buf[:total], self.buf[total:]
            try:
                fr = parse_frame(pkt, self.dialect)
            except TlvError:
                self.errors += 1
                self.quiet = True
                self.buf = pkt[1:] + self.buf  # restart one byte after the bad frame's magic
                continue
            if self.last_frame is not None and fr["frame"] != self.last_frame + 1:
                self.gaps += 1
            self.last_frame = fr["frame"]
            self.frames += 1
            fr.update(gaps=self.gaps, errors=self.errors)
            out.append(fr)
        return out


def split_packets(data: bytes, dialect: str = "sdk3"):
    """Yield each frame packet in a raw dump (magic word + totalPacketLen framing)."""
    hdr = _check(dialect)
    i = 0
    while True:
        i = data.find(MAGIC, i)
        if i < 0 or i + hdr > len(data):
            return
        total = struct.unpack_from("<I", data, i + 12)[0]
        if total < hdr or i + total > len(data):
            return
        yield data[i:i + total]
        i += total


def build_packet(frame_num, pts, snr_db=None):
    """Build one sdk3 TLV packet: pts = [(x, y, z, v)], snr_db = per-point SNR in dB (default 10)."""
    body1 = b"".join(struct.pack("<ffff", *p) for p in pts)
    body7 = b"".join(struct.pack("<hh", int(round((snr_db[i] if snr_db else 10.0) * 10)), 0)
                     for i in range(len(pts)))
    tlvs = struct.pack("<II", 1, len(body1)) + body1 + struct.pack("<II", 7, len(body7)) + body7
    total = HEADER_LEN + len(tlvs)
    head = struct.pack(HEADER_FMT, MAGIC, 0, total, 0, frame_num, 0, len(pts), 2, 0)
    return head + tlvs
