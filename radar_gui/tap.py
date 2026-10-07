"""Driver live tap reader (gui-36). The GUI creates a pipe and spawns the driver with `--tap-fd <write end>`; the driver
writes length-prefixed messages: `u32 len (LE, bytes after this field)`, `u8 type`, payload.
  1 hello   JSON {"version":1,"board":..,"streams":[..],"adc_every":K}
  2 points  JSON in the Live wire format {"type":"frame","frame","n","t","pts":[[x,y,z,v,snr,noise],...]} (NaN -> null)
  3 adc     one JSON header line (index, shape, missing_bytes, layout, iq_order) + "\\n" + int16 I,Q pairs
"""
import json
import os
import select

HELLO, POINTS, ADC = 1, 2, 3
MAX_MESSAGE = 256 * 1024 * 1024   # a corrupt length must not make the reader allocate gigabytes


class TapClosed(Exception):
    """EOF (the driver exited), a stop request, or a corrupt stream."""


def _read_exact(fd: int, n: int, stop) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        if stop():
            raise TapClosed("stopped")
        r, _, _ = select.select([fd], [], [], 0.2)
        if not r:
            continue
        try:
            chunk = os.read(fd, n - len(buf))
        except OSError as e:
            raise TapClosed(str(e)) from e
        if not chunk:
            raise TapClosed("eof")
        buf += chunk
    return bytes(buf)


def read_message(fd: int, stop=lambda: False) -> tuple[int, bytes]:
    """Next (type, payload); raises TapClosed on EOF / stop / an implausible length."""
    n = int.from_bytes(_read_exact(fd, 4, stop), "little")
    if n < 1 or n > MAX_MESSAGE:
        raise TapClosed(f"bad message length {n}")
    body = _read_exact(fd, n, stop)
    return body[0], body[1:]


def decode_json(payload: bytes) -> dict:
    return json.loads(payload.decode("utf-8"))


def decode_adc(payload: bytes) -> tuple[dict, bytes]:
    """(header dict, raw int16 I/Q bytes) of an adc message."""
    head, _, data = payload.partition(b"\n")
    return json.loads(head.decode("utf-8")), data
