"""Decode raw LVDS bytes of a 2-lane IWR1843/6843 capture, from docs/raw_data/ alone.

Written from README.md sections 3, 4 and 7 and demo.md / sar_lvds.md. numpy only.

Usage:
    python decode_example.py demo FRAME.bin RX NS NC           # stock demo, one frame
    python decode_example.py sar  LVDS_Raw_0.bin RX NS [HDR]   # iwr1843_sar_lvds (dataFmt 2)

Stream (no header): per chirp, R x Ns x 4 B; order chirp, RX, sample.
Sample: two little-endian int16, two's complement; SampleSwap 1 (stock demo, SAR) = Q first.
2 lanes: file int16 words repeat [A0 A1 B0 B1] = [Q(2g) Q(2g+1) I(2g) I(2g+1)].
"""
import sys

import numpy as np


def decode_payload(payload, n_rx, n_samples, n_chirps, q_first=True):
    """Bytes of n_chirps ADC payloads -> int16 array [chirp][rx][sample][re, im] (re = I)."""
    words = np.frombuffer(payload, dtype="<i2")
    if words.size != n_chirps * n_rx * n_samples * 2:
        raise ValueError("payload size is not 4 x rx x samples x chirps")
    if n_samples % 2:
        raise ValueError("samples per chirp must be even (two samples per word group)")
    g = words.reshape(n_chirps, n_rx, n_samples // 2, 4)  # [A0 A1 B0 B1]
    first, second = g[..., 0:2], g[..., 2:4]
    q, i = (first, second) if q_first else (second, first)
    out = np.empty((n_chirps, n_rx, n_samples // 2, 2, 2), dtype=np.int16)
    out[..., 0] = i  # re
    out[..., 1] = q  # im
    return out.reshape(n_chirps, n_rx, n_samples, 2)


def to_cube(chirp_rx_sample_iq):
    """[chirp][rx][sample][re, im] -> complex cube [rx][sample][chirp] (int16 parts, as complex64)."""
    a = chirp_rx_sample_iq.astype(np.float32)
    return (a[..., 0] + 1j * a[..., 1]).transpose(1, 2, 0)


def decode_demo_frame(raw, n_rx, n_samples, n_chirps):
    """Stock demo, no header: one frame is 4 x R x Ns x Nc bytes (README section 7)."""
    need = 4 * n_rx * n_samples * n_chirps
    return decode_payload(bytes(raw[:need]), n_rx, n_samples, n_chirps)


def sar_packets(raw, n_rx, n_samples, header=0):
    """Split a SAR dataFmt 2 capture into whole chirp packets (sar_lvds.md).

    Packet = header H, ADC payload 4 x R x Ns, then two 32 B metadata slots (B = H + payload + 64).
    Returns (adc_payload_bytes_per_chirp list as 2D uint8 array, slot bytes array [chirp, 2, 32]).
    """
    pay = 4 * n_rx * n_samples
    size = header + pay + 64
    n = len(raw) // size
    p = np.frombuffer(raw, dtype=np.uint8, count=n * size).reshape(n, size)
    return p[:, header:header + pay], p[:, header + pay:].reshape(n, 2, 32)


def undo_lane_order(b):
    """File 16-bit word order A0 A1 B0 B1 = memory units u0 u2 u1 u3 (README section 4): swap words 1,2."""
    w = np.frombuffer(bytes(b), dtype="<u2").reshape(-1, 4)
    return w[:, [0, 2, 1, 3]].astype("<u2").tobytes()


META_FIELDS = ("magic", "version", "flags", "frameIdx", "chirpInFrame", "numChirpsPerFrame",
               "globalChirpIdx", "runIdx", "satSlices", "satRefLag", "tsTicks")
META_FMT = "<IHHIHHIHBBQ"  # sar_lvds.md record table, 32 bytes, little-endian
SAR_MAGIC = 0x4D524153


def decode_sar_meta(slots):
    """Slot bytes [chirp, 2, 32] -> dict of arrays, one record per chirp k (slot k mod 2).

    Lane undo first (sar_lvds.md): swap the middle two 16-bit units of each 8-byte group.
    'valid' = magic, version == 1 and globalChirpIdx == k (the doc's rule for packet k's own record).
    """
    n = slots.shape[0]
    sel = slots[np.arange(n), np.arange(n) % 2]  # [n, 32]
    w = np.ascontiguousarray(sel).view("<u2").reshape(n, 4, 4)[:, :, [0, 2, 1, 3]]
    rec = np.ascontiguousarray(w.astype("<u2").reshape(n, 16)).view(np.dtype(
        [("magic", "<u4"), ("version", "<u2"), ("flags", "<u2"), ("frameIdx", "<u4"),
         ("chirpInFrame", "<u2"), ("numChirpsPerFrame", "<u2"), ("globalChirpIdx", "<u4"),
         ("runIdx", "<u2"), ("satSlices", "u1"), ("satRefLag", "u1"), ("tsTicks", "<u8")]))[:, 0]
    out = {f: rec[f] for f in META_FIELDS}
    out["valid"] = (rec["magic"] == SAR_MAGIC) & (rec["version"] == 1) & (rec["globalChirpIdx"] == np.arange(n))
    return out


def decode_sar(raw, n_rx, n_samples, header=0):
    adc, slots = sar_packets(raw, n_rx, n_samples, header)
    n = adc.shape[0]
    return decode_payload(adc.tobytes(), n_rx, n_samples, n), slots


if __name__ == "__main__":
    mode, path = sys.argv[1], sys.argv[2]
    data = open(path, "rb").read()
    if mode == "demo":
        r, ns, nc = map(int, sys.argv[3:6])
        arr = decode_demo_frame(data, r, ns, nc)
    else:
        r, ns = map(int, sys.argv[3:5])
        arr, slots = decode_sar(data, r, ns, int(sys.argv[5]) if len(sys.argv) > 5 else 0)
        meta = decode_sar_meta(slots)
        print("records valid", int(meta["valid"].sum()), "of", len(meta["valid"]))
    print(arr.shape, arr.dtype, arr.min(), arr.max())
