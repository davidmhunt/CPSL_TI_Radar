"""Closed-form synthetic ADC cube for the gui-07 tests and the fake driver (independent of radar_gui.adc).

Cube [rx, sample, chirp] complex, chirp c = loop c // cpl, TX slot c % cpl. A target is
  A * exp(j * (2*pi*kr*n/N + 2*pi*kd*l/L - pi*sin(theta) * m)),  m = az_slot_index * n_rx + rx,
i.e. range bin kr, Doppler bin offset kd (signed, 0 = zero velocity), and an azimuth virtual-array phase ramp.
"""
import numpy as np


def cube(n_rx=4, n_samples=128, n_loops=128, cpl=2, targets=(), noise=0.0, seed=1):
    n = np.arange(n_samples)[None, :, None]
    c = np.arange(n_loops * cpl)[None, None, :]
    loop, slot = c // cpl, c % cpl
    rx = np.arange(n_rx)[:, None, None]
    x = np.zeros((n_rx, n_samples, n_loops * cpl), np.complex128)
    for t in targets:
        m = slot * n_rx + rx
        ph = (2 * np.pi * t["kr"] * n / n_samples + 2 * np.pi * t.get("kd", 0) * loop / n_loops
              - np.pi * t.get("sin", 0.0) * m)
        x += t.get("amp", 4000.0) * np.exp(1j * ph)
    if noise:
        rng = np.random.default_rng(seed)
        x += noise * (rng.standard_normal(x.shape) + 1j * rng.standard_normal(x.shape))
    return x


def to_int16(x, swap_iq=False):
    """[rx, sample, chirp, 2] int16 (I, Q), rounded and clipped to the int16 rails."""
    i, q = np.rint(x.real), np.rint(x.imag)
    if swap_iq:
        i, q = q, i
    return np.clip(np.stack([i, q], axis=-1), -32768, 32767).astype("<i2")


def wire(x, index=0, missing=0, **kw):
    """(header dict, payload bytes) exactly as the driver's tap `adc` message carries them."""
    a = to_int16(x, **kw)
    rx, ns, nc, _ = a.shape
    return ({"index": index, "shape": [rx, ns, nc], "missing_bytes": missing, "layout": "rx,sample,chirp",
             "iq_order": "IQ"}, a.tobytes())
