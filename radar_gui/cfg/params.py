"""Direct chirp-parameter editing (gui-11): cfg <-> a flat, JSON-friendly params dict.

`params_from_cfg(cfg)` reads the editable fields; `apply_params(base_text, params)` writes them back into
`base_text`, rewriting only the profileCfg / chirpCfg / frameCfg / channelCfg lines (everything else, comments
included, is kept verbatim). A token is only rewritten when its value changed, so the round trip of an
unedited dict is a text-level identity, not just a metrics one.

Schema (single profile; the profile fields live in `profiles[0]`, so gui-14..16 can add entries):

    profiles: [ {id, start_ghz, slope_mhz_us, idle_us, adc_start_us, ramp_us, tx_start_us,
                 num_samples, sample_rate_ksps, hpf1, hpf2, rx_gain_db} ]   # hpf*/rx_gain: when profileCfg has them
    rx_mask, tx_mask            channelCfg enables (cascade: also rx_mask2, tx_mask2 for the second chip)
    chirp_tx_masks              TX mask of each chirp of the loop, frameCfg chirpStart..chirpEnd order
    n_loops, frame_period_ms, frames
    derived                     read-only (ignored by apply_params): metrics-derived bandwidth, ramp, sample window ...

Partial dicts are fine: missing keys keep the base cfg's value. Only `profiles[0]` is applied for now and its
`id` is read-only (chirpCfg lines refer to it). To add multi-profile later: `profiles` gains entries (written as
extra profileCfg lines) and each chirp entry gains a profile id; `chirp_tx_masks` becomes a list of chirp dicts.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from .metrics import infer_board_kind, metrics
from .parse import Cfg, CfgError, parse_cfg

# profileCfg arg index per params key (profileCfg: id start idle adcStart ramp txPwr txPhase slope txStart
# numSamples fs hpf1 hpf2 rxGain)
_PROFILE = {"start_ghz": (1, float), "idle_us": (2, float), "adc_start_us": (3, float), "ramp_us": (4, float),
            "slope_mhz_us": (7, float), "tx_start_us": (8, float), "num_samples": (9, int),
            "sample_rate_ksps": (10, float), "hpf1": (11, int), "hpf2": (12, int), "rx_gain_db": (13, int)}
_DERIVED = ("bandwidth_mhz", "sweep_mhz", "ramp_us", "sampling_us", "adc_end_us", "chirp_us", "center_ghz",
            "range_res_m", "max_range_m", "velocity_res_ms", "max_velocity_ms", "frame_rate_hz")


class ParamsError(CfgError):
    """A params value is not a usable number."""


def _num(v: Any, kind, key: str):
    if isinstance(v, bool) or v is None:
        raise ParamsError(f"{key}: expected a number, got {v!r}")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ParamsError(f"{key}: expected a number, got {v!r}") from None
    if not math.isfinite(x):
        raise ParamsError(f"{key}: must be finite")
    if kind is int:
        if x != int(x):
            raise ParamsError(f"{key}: must be a whole number, got {v!r}")
        return int(x)
    return x


def _fmt(x) -> str:
    return str(int(x)) if isinstance(x, int) or float(x).is_integer() else f"{x:.10g}"


def _num_list(args: list[str], line_name: str) -> list[float]:
    try:
        return [float(a) for a in args]
    except ValueError:
        raise CfgError(f"{line_name}: non-numeric field") from None


def params_from_cfg(cfg: Cfg, board: str | None = None) -> dict:
    """Editable fields of `cfg` (first profileCfg / channelCfg / frameCfg; chirps of the frame's loop).
    Raises CfgError when the cfg is missing a command or is malformed (same checks as `metrics`)."""
    m = metrics(cfg, board)            # validates the structure once
    cascade = (board == "AWR2243_CASCADE") if board else infer_board_kind(cfg) == "cascade"
    p = cfg.first("profileCfg").floats()
    prof: dict[str, Any] = {"id": int(p[0])}
    for key, (i, kind) in _PROFILE.items():
        if i < len(p):
            prof[key] = int(p[i]) if kind is int else p[i]
    ch = cfg.first("channelCfg").floats()
    out: dict[str, Any] = {"profiles": [prof], "rx_mask": int(ch[0]), "tx_mask": int(ch[1])}
    if cascade and len(ch) >= 5:
        out["rx_mask2"], out["tx_mask2"] = int(ch[3]), int(ch[4])
    f = cfg.first("frameCfg").floats()
    start, end = int(f[0]), int(f[1])
    masks: dict[int, int] = {}
    for c in cfg.all("chirpCfg"):
        a = c.floats()
        for i in range(int(a[0]), int(a[1]) + 1):
            if start <= i <= end:
                masks[i] = masks.get(i, 0) | int(a[7])
    out["chirp_tx_masks"] = [masks[i] for i in range(start, end + 1)]
    out["n_loops"] = int(f[2])
    out["frames"] = int(f[3])
    out["frame_period_ms"] = m.frame_period_ms
    d = m.to_dict()
    out["derived"] = {k: d[k] for k in _DERIVED}
    return out


def _set(tok: list[str], i: int, val, kind, key: str) -> None:
    """tok[i] = val when the numeric value differs from what is there (keeps the original text otherwise)."""
    v = _num(val, kind, key)
    if i >= len(tok):
        raise ParamsError(f"{key}: the base cfg line has no field {i}")
    try:
        same = float(tok[i]) == v
    except ValueError:
        same = False
    if not same:
        tok[i] = _fmt(v)


def apply_params(base_cfg_text: str, params: Mapping[str, Any]) -> str:
    """`base_cfg_text` with `params` applied. Raises CfgError (ParamsError) for a missing base command or a
    non-numeric value; range problems are left for `validate` to report."""
    cfg = parse_cfg(base_cfg_text)
    base = params_from_cfg(cfg)
    prof_in = params.get("profiles")
    if prof_in is not None and (not isinstance(prof_in, (list, tuple)) or not prof_in or
                                not isinstance(prof_in[0], Mapping)):
        raise ParamsError("profiles: expected a non-empty list of objects")
    prof_in = dict(prof_in[0]) if prof_in else {}
    cascade_frame = len(cfg.first("frameCfg").args) >= 9
    first_chirp = cfg.first("chirpCfg")
    if first_chirp is None:
        raise CfgError("missing chirpCfg")

    new: dict[int, str] = {}       # source line number -> replacement text (None = delete)
    delete: set[int] = set()

    def tokens(cmd) -> list[str]:
        return [cmd.name] + list(cmd.args)

    # profileCfg (first one)
    pc = cfg.first("profileCfg")
    tok = tokens(pc)
    for key, (i, kind) in _PROFILE.items():
        if key in prof_in and key in base["profiles"][0]:
            _set(tok, i + 1, prof_in[key], kind, key)
    new[pc.line] = " ".join(tok)

    # channelCfg
    cc = cfg.first("channelCfg")
    tok = tokens(cc)
    for key, i in (("rx_mask", 0), ("tx_mask", 1), ("rx_mask2", 3), ("tx_mask2", 4)):
        if key in params and key in base:
            _set(tok, i + 1, params[key], int, key)
    new[cc.line] = " ".join(tok)

    # chirpCfg: regenerate when the per-chirp masks changed, or (single chip) when only tx_mask changed
    masks = base["chirp_tx_masks"]
    if "chirp_tx_masks" in params:
        raw = params["chirp_tx_masks"]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ParamsError("chirp_tx_masks: expected a non-empty list")
        masks_new = [_num(m, int, "chirp_tx_masks") for m in raw]
    else:
        masks_new = list(masks)
    if (not cascade_frame and "tx_mask" in params and "chirp_tx_masks" not in params
            and _num(params["tx_mask"], int, "tx_mask") != base["tx_mask"]):
        masks_new = [b for b in (1, 2, 4) if _num(params["tx_mask"], int, "tx_mask") & b]
        if not masks_new:
            masks_new = [0]
    regenerate = masks_new != masks
    if regenerate:
        proto = tokens(first_chirp)
        lines = []
        for i, m in enumerate(masks_new):
            t = list(proto)
            t[1] = t[2] = str(i)
            t[8] = str(m)
            lines.append(" ".join(t))
        new[first_chirp.line] = "\n".join(lines)
        delete |= {c.line for c in cfg.all("chirpCfg") if c.line != first_chirp.line}

    # frameCfg
    fc = cfg.first("frameCfg")
    tok = tokens(fc)
    if regenerate:
        _set(tok, 1, 0, int, "chirp_start")
        _set(tok, 2, len(masks_new) - 1, int, "chirp_end")
    for key, i, kind in (("n_loops", 3, int), ("frames", 4, int), ("frame_period_ms", 6 if cascade_frame else 5, float)):
        if key in params:
            _set(tok, i, params[key], kind, key)
    new[fc.line] = " ".join(tok)

    out = []
    for n, raw in enumerate(base_cfg_text.splitlines(), 1):
        if n in delete:
            continue
        if n in new:
            old = raw.split("%", 1)[0].split()
            if new[n].split() == old:      # untouched: keep the original line (spacing, trailing comment)
                out.append(raw)
            else:
                comment = raw.split("%", 1)[1] if "%" in raw else None
                out.append(new[n] + (f" %{comment}" if comment is not None else ""))
        else:
            out.append(raw)
    return "\n".join(out) + "\n"
