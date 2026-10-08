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
    bpm                         bool: bpmCfg enabled (single chip only; gui-15). Writing true needs a board + firmware whose
                                descriptor says `mimo.bpm` (else ParamsError); default/false = plain TDM, bpmCfg disabled
    lvds_stream                 {subframe, header, data_fmt, sw} = lvdsStreamCfg (gui-22); only when the cfg has the
                                line. data_fmt 0 = HW (ADC) stream off, 1 = ADC data, 2 = ADC + metadata (SAR firmware)
    low_power                   0 = regular ADC, 1 = low-power ADC = `lowPower 0 <adcMode>` (gui-26); single chip only, and
                                only when the cfg has the line (the cascade cfgs carry `lowPower 0 0` but it is not offered)
    detection                   optional on-chip CFAR values (gui-35, radar_gui/cfg/detection.py), applied last with `detection.apply`
    derived                     read-only (ignored by apply_params): metrics-derived bandwidth, ramp, sample window ...

Coupling (gui-15, docs/design/mimo_modes.md s4): single chip -> channelCfg tx_mask = OR(chirp_tx_masks) whenever
chirp_tx_masks is given; a tx_mask-only edit regenerates the chirps in TI's azimuth-first order (TX1, TX3, TX2 =
1,4,2); `bpm: true` writes mask 5 on both chirps and enables bpmCfg. Cascade (DDMA): chirp_tx_masks edits are
ignored (all TX fire every chirp; the firmware overwrites the chirp masks); a warning is appended to `warnings`.

Partial dicts are fine: missing keys keep the base cfg's value. Only `profiles[0]` is applied for now and its
`id` is read-only (chirpCfg lines refer to it). To add multi-profile later: `profiles` gains entries (written as
extra profileCfg lines) and each chirp entry gains a profile id; `chirp_tx_masks` becomes a list of chirp dicts.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from . import detection
from . import firmware as fwmod
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


_LVDS = {"subframe": 1, "header": 2, "data_fmt": 3, "sw": 4}   # lvdsStreamCfg token index (0 = the command name)


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
    if not cascade:
        out["bpm"] = bool(cfg.bpm_enabled)
    lv = cfg.first("lvdsStreamCfg")
    if lv is not None and len(lv.args) >= 4:
        a = _num_list(lv.args[:4], "lvdsStreamCfg")
        out["lvds_stream"] = {k: int(a[i - 1]) for k, i in _LVDS.items()}
    lp = cfg.first("lowPower")
    if lp is not None and len(lp.args) >= 2 and not cascade:
        out["low_power"] = int(_num_list(lp.args[:2], "lowPower")[1])
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


def _truthy(v: Any, key: str) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    raise ParamsError(f"{key}: expected true/false, got {v!r}")


def apply_params(base_cfg_text: str, params: Mapping[str, Any], *, board: str | None = None,
                 firmware: str | None = None, warnings: list | None = None) -> str:
    """`base_cfg_text` with `params` applied. Raises CfgError (ParamsError) for a missing base command, a
    non-numeric value, or `bpm: true` where the board/firmware does not support BPM (`board` and `firmware`
    are required for that; `firmware` defaults to the board's default). Range problems are left for
    `validate` to report. Non-fatal notices (ignored cascade chirp-mask edits, ...) are appended to
    `warnings` (a list of `(code, message)`) when given."""
    warn = warnings if warnings is not None else []
    cfg = parse_cfg(base_cfg_text)
    base = params_from_cfg(cfg, board)
    prof_in = params.get("profiles")
    if prof_in is not None and (not isinstance(prof_in, (list, tuple)) or not prof_in or
                                not isinstance(prof_in[0], Mapping)):
        raise ParamsError("profiles: expected a non-empty list of objects")
    prof_in = dict(prof_in[0]) if prof_in else {}
    cascade_frame = len(cfg.first("frameCfg").args) >= 9
    cascade = cascade_frame or board == "AWR2243_CASCADE"
    bpm_in = None
    if "bpm" in params and params["bpm"] is not None:
        bpm_in = _truthy(params["bpm"], "bpm")
        if bpm_in == base.get("bpm"):
            bpm_in = None                           # unchanged: nothing to write or check
        elif bpm_in:
            if cascade:
                raise ParamsError("bpm: the cascade DDMA firmware has no bpmCfg (docs/design/mimo_modes.md s1)")
            fw = (fwmod.get(firmware) if firmware else fwmod.default_for(board)) if board else None
            if fw is None:
                raise ParamsError("bpm: needs a known board (and firmware) to check that BPM is supported")
            mm = fwmod.mimo(board, fw)
            if mm["scheme"] != "tdm" or not mm.get("bpm"):
                raise ParamsError(f"bpm: firmware {fw['id']!r} on {board} does not support BPM "
                                  f"(descriptor mimo.bpm is false; {mm.get('source', '')})")
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
    tx_edit = ("tx_mask" in params and _num(params["tx_mask"], int, "tx_mask") != base["tx_mask"])
    if "chirp_tx_masks" in params:
        raw = params["chirp_tx_masks"]
        if not isinstance(raw, (list, tuple)) or not raw:
            raise ParamsError("chirp_tx_masks: expected a non-empty list")
        masks_new = [_num(m, int, "chirp_tx_masks") for m in raw]
    else:
        masks_new = list(masks)
    if cascade:
        if masks_new != masks:
            warn.append(("cascade_chirp_mask_ignored", "cascade DDMA: all TX fire on every chirp and the firmware "
                         "overwrites the chirpCfg TX masks; chirp_tx_masks edit ignored"))
        masks_new = list(masks)
    elif bpm_in:
        if "chirp_tx_masks" not in params:
            masks_new = [5, 5]                      # BPM: TX1+TX3 on both chirps of the pair
    elif "chirp_tx_masks" not in params and (tx_edit or (bpm_in is False and base.get("bpm"))):
        txm = _num(params["tx_mask"], int, "tx_mask") if "tx_mask" in params else base["tx_mask"]
        masks_new = [b for b in (1, 4, 2) if txm & b] or [0]     # TI's azimuth-first order
    if not cascade and (masks_new != masks or bpm_in):
        want = 0
        for m_ in masks_new:
            want |= m_
        if "tx_mask" in params and _num(params["tx_mask"], int, "tx_mask") != want:
            warn.append(("tx_mask_from_chirps", f"channelCfg tx_mask set to {want} = OR of the chirp masks "
                         f"(asked {params['tx_mask']})"))
        tok = new[cc.line].split()
        _set(tok, 2, want, int, "tx_mask")
        new[cc.line] = " ".join(tok)
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

    # bpmCfg (single chip): enable/disable only when asked and different from the base
    if bpm_in is not None and not cascade:
        bc = [c for c in cfg.all("bpmCfg")]
        if bc:
            for c in bc:
                tok = tokens(c)
                _set(tok, 2, int(bpm_in), int, "bpm")
                if bpm_in:
                    _set(tok, 3, 0, int, "bpm")
                    _set(tok, 4, 1, int, "bpm")
                new[c.line] = " ".join(tok)
        else:
            new[cc.line] = new[cc.line] + f"\nbpmCfg -1 {int(bpm_in)} 0 1"

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

    # lvdsStreamCfg (gui-22): only the changed fields
    lv, lv_in = cfg.first("lvdsStreamCfg"), params.get("lvds_stream")
    if lv_in is not None:
        if not isinstance(lv_in, Mapping):
            raise ParamsError("lvds_stream: expected an object")
        if lv is None or "lvds_stream" not in base:
            raise ParamsError("lvds_stream: the base cfg has no lvdsStreamCfg line")
        tok = tokens(lv)
        for key, i in _LVDS.items():
            if key in lv_in:
                _set(tok, i, lv_in[key], int, "lvds_stream." + key)
        new[lv.line] = " ".join(tok)

    # lowPower 0 <adcMode> (gui-26): only when changed
    lpc = cfg.first("lowPower")
    if params.get("low_power") is not None:
        if "low_power" not in base:
            raise ParamsError("low_power: the base cfg has no lowPower line (or the board is the cascade)")
        lpv = _num(params["low_power"], int, "low_power")
        if lpv not in (0, 1):
            raise ParamsError(f"low_power: expected 0 (regular) or 1 (low power), got {params['low_power']!r}")
        tok = tokens(lpc)
        _set(tok, 2, lpv, int, "low_power")
        new[lpc.line] = " ".join(tok)

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
    text = "\n".join(out) + "\n"
    if params.get("detection") is not None:       # gui-35: on-chip CFAR values, see radar_gui/cfg/detection.py
        if not board:
            raise ParamsError("detection: needs a board")
        text = detection.apply(text, params["detection"], firmware, board)
    return text
