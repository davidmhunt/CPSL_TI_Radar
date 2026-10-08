"""On-chip detection (CFAR) editing from the firmware descriptor (gui-35).

The schema is data: `config/firmware/<fw>.json` -> `detection` (read with the rest of the descriptor by
`firmware.py`, ignored by the C++ driver as a GUI-only key). Rule *logic* lives here, keyed by `code`; the
descriptor picks which rules a variant uses (and their severity/params).

    detection: null  +  detection_note: str                     firmware without on-chip detection (SAR, raw)
    detection: {
      "boards":   {board: variant id | null},                    null / absent = no detection on that board
      "notes":    [str],                                         shown under the card (also per variant: "notes")
      "variants": {id: {
          "level": "bench"|"source"|"unverified", "source": str,
          "commands": {name: {"per_direction": bool,             a cfg command line per direction (range 0, Doppler 1)
                              "lead": [token...],                tokens before the args: "$sf" (subframe, -1 = all), "$dir", or a constant
                              "args": [field key | fixed key],   argument order after `lead`
                              "fixed": {key: value}}},           args that are constants (written when a line is inserted, never edited)
          "fields":  [{"key","label","type": int|float|enum|bool, "min","max","step","decimals","unit","options",
                       "default": scalar | {"range","doppler"}, "max_code": rule code owning the upper bound,
                       "help","cite"}],
          "fov":     {"command","lead","units":{"range","doppler"},"help","cite"}   optional (`cfarFovCfg`; absent = none)
          "rules":   [{"code", "severity"?, "params"?}]}}}

Values (`from_cfg` / `apply`): {"range": {key: v}, "doppler": {key: v}, "shared": {key: v},
"fov": {"mode": "auto"|"manual", "range": [min, max], "doppler": [min, max]}}. A command line with a subframe
index other than -1, or one that does not match the command's layout, makes the cfg read-only here.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from . import firmware as fwmod
from .parse import Cfg, CfgError, parse_cfg

DIRS = ("range", "doppler")
LEVELS = ("bench", "source", "unverified")
TYPES = ("int", "float", "enum", "bool")
_CONF = {"bench": "high", "source": "high", "unverified": "unverified"}


class DetectionError(CfgError):
    """A detection value is unusable, or the cfg's detection lines cannot be edited."""


# --------------------------------------------------------------------------------------------- descriptor access
def _fw(firmware, board):
    fid = firmware if isinstance(firmware, str) and firmware else fwmod.default_firmware_id(board)
    d = fwmod.get(fid) if fid else None
    return d


def variant(firmware, board: str) -> dict | None:
    """The detection variant of `firmware` (id, descriptor or None = board default) on `board`, with its id added."""
    d = firmware if isinstance(firmware, dict) else _fw(firmware, board)
    det = d.get("detection") if d else None
    if not isinstance(det, dict):
        return None
    vid = (det.get("boards") or {}).get(board)
    v = (det.get("variants") or {}).get(vid) if vid else None
    if v is None:
        return None
    out = copy.deepcopy(v)
    out["id"], out["firmware"] = vid, d["id"]
    out["notes"] = list(det.get("notes") or []) + list(v.get("notes") or [])
    return out


def note(firmware, board: str) -> str | None:
    d = firmware if isinstance(firmware, dict) else _fw(firmware, board)
    return (d or {}).get("detection_note")


def _fields(v: dict) -> dict:
    return {f["key"]: f for f in v["fields"]}


def _per_direction(v: dict, key: str) -> bool:
    return any(c["per_direction"] and key in c["args"] for c in v["commands"].values())


def schema(firmware, board: str) -> dict | None:
    """JSON-able schema for the UI (None = no detection on this firmware/board)."""
    v = variant(firmware, board)
    if v is None:
        return None
    fields = []
    for f in v["fields"]:
        g = dict(f)
        g["per_direction"] = _per_direction(v, f["key"])
        fields.append(g)
    return {"variant": v["id"], "firmware": v["firmware"], "level": v["level"], "source": v["source"], "notes": v["notes"],
            "directions": list(DIRS) if any(c["per_direction"] for c in v["commands"].values()) else [],
            "fields": fields, "fov": v.get("fov"), "commands": list(v["commands"]),
            "rules": [r["code"] for r in v.get("rules", [])]}


def check_detection(d: dict, boards: list[str]) -> list[str]:
    """Schema problems of a descriptor's detection block ([] = valid); called from firmware.check_descriptor."""
    bad: list[str] = []
    det = d.get("detection", "absent")
    if det == "absent":
        return bad
    if det is None:
        return bad if d.get("detection_note") else ["detection is null: detection_note must say why"]
    if not isinstance(det, dict) or not isinstance(det.get("boards"), dict) or not isinstance(det.get("variants"), dict):
        return ["detection must be null or {boards, variants}"]
    if set(det["boards"]) != set(boards):
        bad.append("detection.boards must list every board of the firmware (variant id or null)")
    for b, vid in det["boards"].items():
        if vid is not None and vid not in det["variants"]:
            bad.append(f"detection.boards[{b}]: unknown variant {vid!r}")
    if any(vid is None for vid in det["boards"].values()) and not d.get("detection_note"):
        bad.append("a board without detection needs detection_note")
    for vid, v in det["variants"].items():
        w = f"detection.variants[{vid}]"
        if v.get("level") not in LEVELS or not v.get("source"):
            bad.append(f"{w}: level/source missing or bad")
        fields = {}
        for f in v.get("fields", []):
            k = f.get("key")
            if f.get("type") not in TYPES or not k:
                bad.append(f"{w}: field {k!r} needs key and type in {TYPES}")
                continue
            fields[k] = f
            for need in ("label", "help", "cite", "default"):
                if f.get(need) in (None, ""):
                    bad.append(f"{w}: field {k} has no {need}")
            if f["type"] == "enum" and not isinstance(f.get("options"), dict):
                bad.append(f"{w}: enum field {k} needs options")
        cmds = v.get("commands")
        if not isinstance(cmds, dict) or not cmds:
            bad.append(f"{w}: commands missing")
            continue
        for cn, c in cmds.items():
            if not isinstance(c.get("per_direction"), bool) or not isinstance(c.get("lead"), list):
                bad.append(f"{w}: command {cn} needs per_direction and lead")
            for a in c.get("args", []):
                if a not in fields and a not in c.get("fixed", {}):
                    bad.append(f"{w}: command {cn} arg {a!r} is neither a field nor fixed")
        fov = v.get("fov")
        if fov is not None and not (isinstance(fov, dict) and fov.get("command") and fov.get("help") and fov.get("cite")):
            bad.append(f"{w}: fov needs command, help and cite")
        for r in v.get("rules", []):
            if r.get("code") not in _RULES:
                bad.append(f"{w}: unknown rule code {r.get('code')!r}")
            if r.get("severity", "error") not in ("error", "warning", "info"):
                bad.append(f"{w}: rule {r.get('code')} has a bad severity")
    return bad


# --------------------------------------------------------------------------------------------- reading a cfg
def _num(tok: str) -> float | None:
    try:
        x = float(tok)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _records(cfg: Cfg, v: dict) -> list[dict]:
    """One record per detection command line: {cmd, line, dir, sf, tokens, vals, problems}."""
    out = []
    flds = _fields(v)
    specs = [(n, c, c["args"]) for n, c in v["commands"].items()]
    if v.get("fov"):
        fv = v["fov"]
        specs.append((fv["command"], {"per_direction": True, "lead": fv["lead"], "fov": True}, ["fovMin", "fovMax"]))
    for name, c, args in specs:
        lead = c["lead"]
        for cmd in cfg.all(name):
            rec = {"cmd": name, "line": cmd.line, "dir": None, "sf": -1, "tokens": list(cmd.args), "vals": {}, "problems": [],
                   "fov": bool(c.get("fov"))}
            out.append(rec)
            if len(cmd.args) != len(lead) + len(args):
                rec["problems"].append(("count", f"line {cmd.line}: {name} has {len(cmd.args)} fields; this firmware expects "
                                        f"{len(lead) + len(args)} ({' '.join(lead_names(lead) + list(args))})"))
                continue
            for i, spec in enumerate(lead):
                x = _num(cmd.args[i])
                if spec == "$sf":
                    rec["sf"] = None if x is None or x != int(x) else int(x)
                elif spec == "$dir":
                    rec["dir"] = DIRS[int(x)] if x in (0, 1) else None
            if c["per_direction"] and rec["dir"] is None:
                rec["problems"].append(("dir", f"line {cmd.line}: {name} direction must be 0 (range) or 1 (Doppler)"))
            for j, key in enumerate(args):
                x = _num(cmd.args[len(lead) + j])
                if x is None:
                    rec["problems"].append(("num", f"line {cmd.line}: {name} {key} is not a number"))
                    continue
                if flds.get(key, {}).get("type") in ("int", "bool", "enum") and x != int(x):
                    rec["problems"].append(("num", f"line {cmd.line}: {name} {key} must be a whole number, got {cmd.args[len(lead) + j]}"))
                    continue
                f = flds.get(key)
                rec["vals"][key] = int(x) if f and f["type"] in ("int", "bool", "enum") else x
    return out


def lead_names(lead: list) -> list[str]:
    return [{"$sf": "subFrameIdx", "$dir": "procDirection"}.get(s, s) for s in lead]


def context(cfg: Cfg, board: str) -> dict | None:
    """Numbers the checks and the auto FOV need from the cfg, or None when the cfg's chirp structure is unusable."""
    from .metrics import _pow2, metrics
    try:
        m = metrics(cfg, board)
    except CfgError:
        return None
    except (IndexError, ValueError, KeyError, ZeroDivisionError):
        return None
    return {"max_range_m": m.max_range_m, "max_velocity_ms": m.max_velocity_ms, "range_bins": _pow2(m.num_samples),
            "doppler_bins": int(m.doppler_bins), "n_virtual": m.n_virtual}


def _auto_fov(ctx: dict) -> dict:
    v = round(ctx["max_velocity_ms"], 2)
    return {"range": [0.0, round(ctx["max_range_m"], 2)], "doppler": [-v, v]}


def _auto_like(direction: str, lo: float, hi: float, ctx: dict) -> bool:
    if direction == "range":
        top = ctx["max_range_m"]
        return lo == 0 and abs(hi - top) <= max(0.02, 0.01 * top)
    top = ctx["max_velocity_ms"]
    tol = max(0.02, 0.01 * top)
    return abs(lo + top) <= tol and abs(hi - top) <= tol


def from_cfg(cfg: Cfg | str, firmware, board: str) -> dict:
    """{"editable", "reason", "values", "present"} for the detection lines of `cfg`.
    `values` is None when not editable. Missing lines read as the descriptor defaults (`present` says which exist)."""
    v = variant(firmware, board)
    if v is None:
        return {"editable": False, "reason": note(firmware, board), "values": None, "present": {}}
    if isinstance(cfg, str):
        cfg = parse_cfg(cfg)
    recs = _records(cfg, v)
    for r in recs:
        if r["problems"]:
            return {"editable": False, "reason": r["problems"][0][1] + " (edit the cfg text)", "values": None, "present": {}}
        if r["sf"] != -1:
            return {"editable": False, "values": None, "present": {},
                    "reason": f"line {r['line']}: {r['cmd']} targets subframe {r['sf']}; per-subframe detection is not editable here (edit the cfg text)"}
    vals: dict[str, Any] = {d: {} for d in (DIRS if any(c["per_direction"] for c in v["commands"].values()) else ())}
    if any(not c["per_direction"] for c in v["commands"].values()):
        vals["shared"] = {}
    for f in v["fields"]:
        dflt = f["default"]
        if _per_direction(v, f["key"]):
            for d in DIRS:
                vals[d][f["key"]] = dflt[d] if isinstance(dflt, dict) else dflt
        else:
            vals["shared"][f["key"]] = dflt
    present: dict[str, bool] = {}
    for r in recs:
        if r["fov"]:
            continue
        c = v["commands"][r["cmd"]]
        tgt = vals[r["dir"]] if c["per_direction"] else vals["shared"]
        tgt.update({k: x for k, x in r["vals"].items() if k in _fields(v)})
        present[r["cmd"] + ("/" + r["dir"] if c["per_direction"] else "")] = True
    if v.get("fov"):
        ctx = context(cfg, board)
        fov = {"mode": "auto", "range": None, "doppler": None}
        auto = _auto_fov(ctx) if ctx else {"range": [0.0, 0.0], "doppler": [0.0, 0.0]}
        manual = False
        for r in recs:
            if not r["fov"]:
                continue
            lo, hi = r["vals"]["fovMin"], r["vals"]["fovMax"]
            fov[r["dir"]] = [lo, hi]
            present["fov/" + r["dir"]] = True
            if ctx is None or not _auto_like(r["dir"], lo, hi, ctx):
                manual = True
        for d in DIRS:
            fov[d] = fov[d] or auto[d]
        fov["mode"] = "manual" if manual else "auto"
        vals["fov"] = fov
    return {"editable": True, "reason": None, "values": vals, "present": present}


# --------------------------------------------------------------------------------------------- writing a cfg
def _coerce(f: dict, x: Any, where: str):
    t = f["type"]
    if t == "bool":
        if isinstance(x, bool) or x in (0, 1):
            return int(bool(x))
        raise DetectionError(f"{where}: expected true/false, got {x!r}")
    if isinstance(x, bool) or x is None:
        raise DetectionError(f"{where}: expected a number, got {x!r}")
    try:
        n = float(x)
    except (TypeError, ValueError):
        raise DetectionError(f"{where}: expected a number, got {x!r}") from None
    if not math.isfinite(n):
        raise DetectionError(f"{where}: must be finite")
    if t in ("int", "enum"):
        if n != int(n):
            raise DetectionError(f"{where}: must be a whole number, got {x!r}")
        n = int(n)
        if t == "enum" and str(n) not in f["options"]:
            raise DetectionError(f"{where}: {n} is not one of {sorted(f['options'])}")
    return n


def _fmt(x, f: dict) -> str:
    if f["type"] in ("int", "bool", "enum"):
        return str(int(x))
    return f"{round(float(x), f.get('decimals', 6)):.10g}"


def _fmt_plain(x: float) -> str:
    return f"{round(float(x), 2):.10g}"


def _merge(v: dict, cur: dict, new: Mapping[str, Any] | None) -> dict:
    out = copy.deepcopy(cur)
    flds = _fields(v)
    for grp, body in (new or {}).items():
        if grp == "fov":
            if "fov" not in out:
                raise DetectionError("fov: this firmware has no cfarFovCfg")
            if not isinstance(body, Mapping):
                raise DetectionError("fov: expected an object")
            if body.get("mode") is not None:
                if body["mode"] not in ("auto", "manual"):
                    raise DetectionError("fov.mode: expected 'auto' or 'manual'")
                out["fov"]["mode"] = body["mode"]
            for d in DIRS:
                if body.get(d) is not None:
                    pair = body[d]
                    if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
                        raise DetectionError(f"fov.{d}: expected [min, max]")
                    out["fov"][d] = [_coerce({"type": "float"}, pair[0], f"fov.{d}[0]"),
                                     _coerce({"type": "float"}, pair[1], f"fov.{d}[1]")]
                    if body.get("mode") is None:
                        out["fov"]["mode"] = "manual"
            continue
        if grp not in out or grp == "fov":
            raise DetectionError(f"{grp}: not a detection group of this firmware (one of {[k for k in out if k != 'fov']})")
        if not isinstance(body, Mapping):
            raise DetectionError(f"{grp}: expected an object")
        for k, x in body.items():
            f = flds.get(k)
            if f is None or (grp == "shared") == _per_direction(v, k):
                raise DetectionError(f"{grp}.{k}: unknown field")
            out[grp][k] = _coerce(f, x, f"{grp}.{k}")
    return out


def _line_tokens(rec_tokens: list[str], idx: int, new: str) -> bool:
    x, y = _num(rec_tokens[idx]), _num(new)
    if x is not None and y is not None and x == y:
        return False
    rec_tokens[idx] = new
    return True


def apply(text: str, values: Mapping[str, Any] | None, firmware, board: str) -> str:
    """`text` with the detection `values` applied (partial is fine). Only lines whose numbers change are rewritten (the
    trailing comment is kept); a line that is absent is inserted before `sensorStart` only when values for it were given.
    Raises DetectionError for an unusable value or a cfg whose detection lines are read-only."""
    v = variant(firmware, board)
    if v is None:
        raise DetectionError(note(firmware, board) or f"this firmware has no on-chip detection on {board}")
    cfg = parse_cfg(text)
    cur = from_cfg(cfg, firmware, board)
    if not cur["editable"]:
        raise DetectionError(cur["reason"])
    vals = _merge(v, cur["values"], values)
    supplied = values or {}
    flds = _fields(v)
    recs = _records(cfg, v)
    edits: dict[int, list[str]] = {}
    inserts: list[str] = []
    ctx = context(cfg, board)

    def build(name, lead, args, fixed, dirname, getter, c_fmt):
        toks = [name]
        for s in lead:
            toks.append("-1" if s == "$sf" else str(DIRS.index(dirname)) if s == "$dir" else str(s))
        for a in args:
            toks.append(str(fixed[a]) if a in fixed else c_fmt(a, getter(a)))
        return " ".join(toks)

    for name, c in v["commands"].items():
        for d in (DIRS if c["per_direction"] else ("shared",)):
            grp = vals[d]
            lines = [r for r in recs if r["cmd"] == name and (r["dir"] == d or not c["per_direction"])]
            wanted = bool(set(supplied.get(d) or {}) & set(c["args"]))
            if lines:
                for r in lines:
                    toks = edits.get(r["line"]) or [name] + list(r["tokens"])
                    changed = False
                    for j, key in enumerate(c["args"]):
                        if key in flds and key in grp:
                            if _line_tokens(toks, 1 + len(c["lead"]) + j, _fmt(grp[key], flds[key])):
                                changed = True
                    if changed:
                        edits[r["line"]] = toks
            elif wanted:
                inserts.append(build(name, c["lead"], c["args"], c.get("fixed", {}), d, lambda a: grp[a],
                                     lambda a, x: _fmt(x, flds[a])))
    fv = v.get("fov")
    if fv and "fov" in supplied:
        want = vals["fov"]
        if want["mode"] == "auto":
            if ctx is None:
                raise DetectionError("fov: auto needs a cfg with a valid chirp setup (range / velocity limits)")
            auto = _auto_fov(ctx)
        for d in DIRS:
            lines = [r for r in recs if r["fov"] and r["dir"] == d]
            if want["mode"] == "auto":
                pair = [lines[-1]["vals"]["fovMin"], lines[-1]["vals"]["fovMax"]] if lines and ctx and _auto_like(
                    d, lines[-1]["vals"]["fovMin"], lines[-1]["vals"]["fovMax"], ctx) else auto[d]
            else:
                pair = want[d]
            if lines:
                for r in lines:
                    toks = edits.get(r["line"]) or [fv["command"]] + list(r["tokens"])
                    ch = _line_tokens(toks, 1 + len(fv["lead"]), _fmt_plain(pair[0]))
                    ch = _line_tokens(toks, 2 + len(fv["lead"]), _fmt_plain(pair[1])) or ch
                    if ch:
                        edits[r["line"]] = toks
            else:
                inserts.append(f"{fv['command']} -1 {DIRS.index(d)} {_fmt_plain(pair[0])} {_fmt_plain(pair[1])}")
    if not edits and not inserts:
        return text
    raw = text.splitlines(keepends=True)
    out = []
    for n, ln in enumerate(raw, 1):
        if n in edits:
            body = ln.rstrip("\r\n")
            eol = ln[len(body):]
            code, pct, comment = body.partition("%")
            out.append(" ".join(edits[n]) + ((" %" + comment) if pct else "") + eol)
        else:
            out.append(ln)
    if inserts:
        at = max((i for i, ln in enumerate(out) if ln.split("%", 1)[0].split()[:1] == ["sensorStart"]), default=None)
        block = [s + "\n" for s in inserts]
        if at is None:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            out += block
        else:
            out[at:at] = block
    return "".join(out)


# --------------------------------------------------------------------------------------------- checks
def _thr(rule, key, default):
    return (rule.get("params") or {}).get(key, default)


def _r_args(ctx, rule):
    out = []
    flds = ctx["flds"]
    for r in ctx["recs"]:
        for _, msg in r["problems"]:
            out.append(msg)
        if r["problems"]:
            continue
        for key, x in r["vals"].items():
            f = flds.get(key)
            if f is None:
                continue
            if f.get("min") is not None and x < f["min"]:
                out.append(f"line {r['line']}: {r['cmd']} {key} {x:g} is below {f['min']:g}")
            if f.get("max") is not None and x > f["max"] and not f.get("max_code"):
                out.append(f"line {r['line']}: {r['cmd']} {key} {x:g} is above {f['max']:g} (the firmware stores it in one byte and wraps)")
    return out


def _r_enum(ctx, rule):
    out = []
    for r in ctx["recs"]:
        for key, x in r["vals"].items():
            f = ctx["flds"].get(key)
            if f and f["type"] == "enum" and str(x) not in f["options"]:
                out.append(f"line {r['line']}: {r['cmd']} {key} {x} is not one of {sorted(f['options'])}")
    return out


def _r_threshold_max(ctx, rule):
    out = []
    for r in ctx["recs"]:
        for key, x in r["vals"].items():
            f = ctx["flds"].get(key)
            if f and f.get("max_code") == "cfar_threshold_max":
                lim = _thr(rule, "max", f.get("max"))
                if lim is not None and x > lim:
                    out.append(f"line {r['line']}: {r['cmd']} {key} {x:g} is above {lim:g}; the firmware CLI rejects it")
    return out


def _bins(ctx, d):
    c = ctx["ctx"]
    return None if c is None else (c["range_bins"] if d == "range" else c["doppler_bins"])


def _r_guard(ctx, rule):
    out = []
    nk, gk = _thr(rule, "noise", "noiseWin"), _thr(rule, "guard", "guardLen")
    for r in ctx["recs"]:
        if r["problems"] or nk not in r["vals"] or gk not in r["vals"] or r["fov"]:
            continue
        d = r["dir"] or "range"
        bins = _bins(ctx, d)
        if bins and 2 * (r["vals"][nk] + r["vals"][gk]) >= bins:
            out.append(f"line {r['line']}: {d} CFAR needs 2*({nk}+{gk}) < {bins} {d} bins, cfg has "
                       f"2*({r['vals'][nk]}+{r['vals'][gk]}) = {2 * (r['vals'][nk] + r['vals'][gk])}; the sensor refuses to start")
    return out


def _r_divshift(ctx, rule):
    out = []
    nk, dk, mk = _thr(rule, "noise", "noiseWin"), _thr(rule, "div", "divShift"), _thr(rule, "mode", "mode")
    for r in ctx["recs"]:
        vv = r["vals"]
        if r["problems"] or nk not in vv or dk not in vv or mk not in vv or vv[nk] < 1 or r["fov"]:
            continue
        want = math.ceil(math.log2(2 * vv[nk] if vv[mk] == 0 else vv[nk]))
        if vv[dk] != want:
            out.append(f"line {r['line']}: {dk} {vv[dk]} differs from the TI formula ({want} for {nk} {vv[nk]}, mode {vv[mk]}); "
                       f"the firmware accepts it but the threshold scales differently")
    return out


def _r_fov_order(ctx, rule):
    return [f"line {r['line']}: {r['cmd']} min {r['vals']['fovMin']:g} is not below max {r['vals']['fovMax']:g}; the filter keeps nothing"
            for r in ctx["recs"] if r["fov"] and not r["problems"] and r["vals"]["fovMin"] >= r["vals"]["fovMax"]]


def _r_fov_noop(ctx, rule):
    out, c = [], ctx["ctx"]
    if c is None:
        return out
    for r in ctx["recs"]:
        if not r["fov"] or r["problems"]:
            continue
        lo, hi = r["vals"]["fovMin"], r["vals"]["fovMax"]
        if r["dir"] == "range" and hi > c["max_range_m"] * 1.15 + 0.1:
            out.append(f"line {r['line']}: range FOV max {hi:g} m is beyond the cfg's max range {c['max_range_m']:.2f} m (the filter does nothing there)")
        if r["dir"] == "doppler" and (hi > c["max_velocity_ms"] * 1.15 + 0.1 or lo < -c["max_velocity_ms"] * 1.15 - 0.1):
            out.append(f"line {r['line']}: Doppler FOV {lo:g}..{hi:g} m/s is beyond the cfg's +-{c['max_velocity_ms']:.2f} m/s (the filter does nothing there)")
    return out


def _r_missing_direction(ctx, rule):
    out = []
    for name in _thr(rule, "commands", ["cfarCfg"]):
        have = {r["dir"] for r in ctx["recs"] if r["cmd"] == name and not r["problems"]}
        if have and set(DIRS) - have:
            out.append(f"{name} is given for {'/'.join(sorted(have))} only; this firmware needs both the range and the Doppler line "
                       f"(missing: {'/'.join(sorted(set(DIRS) - have))})")
    return out


def _dop(ctx, key):
    return [r for r in ctx["recs"] if r["dir"] == "doppler" and key in r["vals"] and not r["problems"] and not r["fov"]]


def _r_win2(ctx, rule):
    nk = _thr(rule, "noise", "noiseWin")
    out = []
    for r in ctx["recs"]:
        if r["fov"] or r["problems"] or r["vals"].get(nk) != 2:
            continue
        if r["dir"] == "range" or r["vals"].get("thresholdDb", 1) > 0:
            out.append(f"line {r['line']}: {r['dir']} {nk} 2 is invalid for the HWA CFAR")
    return out


def _r_dop_enabled(ctx, rule):
    return [f"line {r['line']}: Doppler CFAR cannot be disabled on this firmware (isEnabled 0)" for r in _dop(ctx, "isEnabled")
            if r["vals"]["isEnabled"] == 0]


def _r_dop_os_mode(ctx, rule):
    return [f"line {r['line']}: Doppler CFAR must use mode 3 (CFAR-OS) on this firmware, cfg has {r['vals']['mode']}"
            for r in _dop(ctx, "mode") if r["vals"]["mode"] != 3]


def _r_dop_guard0(ctx, rule):
    return [f"line {r['line']}: Doppler CFAR-OS needs guardLen 0, cfg has {r['vals']['guardLen']}"
            for r in _dop(ctx, "guardLen") if r["vals"]["guardLen"] != 0]


# code -> (default severity, function)
_RULES = {
    "cfar_args": ("error", _r_args), "cfar_enum": ("error", _r_enum), "cfar_threshold_max": ("error", _r_threshold_max),
    "cfar_guard_vs_bins": ("error", _r_guard), "cfar_divshift_formula": ("warning", _r_divshift),
    "cfar_fov_order": ("error", _r_fov_order), "cfar_fov_noop": ("info", _r_fov_noop),
    "cfar_missing_direction": ("error", _r_missing_direction), "cfar_win2_invalid": ("error", _r_win2),
    "cfar_doppler_enabled": ("error", _r_dop_enabled), "cfar_doppler_os_mode": ("error", _r_dop_os_mode),
    "cfar_doppler_os_guard0": ("error", _r_dop_guard0),
}


def issues(cfg: Cfg, board: str, firmware, m=None) -> list[tuple[str, str, str, str, str]]:
    """Detection-rule findings of `cfg` as (level, code, message, source, confidence); [] when the firmware has none.
    GUI-only: the C++ driver does not enforce these (gui-35 ruling)."""
    v = variant(firmware, board)
    if v is None:
        return []
    recs = _records(cfg, v)
    if not recs:
        return []
    skip_bins = bool(cfg.subframes)
    ctx = {"recs": recs, "flds": _fields(v), "ctx": None if skip_bins else context(cfg, board)}
    src = f"config/firmware/{v['firmware']}.json detection.{v['id']}: {v['source']}"
    conf = _CONF[v["level"]]
    out = []
    for rule in v.get("rules", []):
        sev, fn = _RULES[rule["code"]][0], _RULES[rule["code"]][1]
        sev = rule.get("severity", sev)
        for msg in fn(ctx, rule):
            lv = "warning" if sev == "error" and conf == "unverified" else sev
            out.append((lv, rule["code"], msg, src, conf))
    return out


def describe(text: str, board: str, firmware=None) -> dict:
    """The `detection` block of /api/cfg/analyze, /params and /detection: {schema, values, editable, note, present, context}."""
    d = _fw(firmware, board)
    if d is None or board not in d["templates"]:
        return {"schema": None, "values": None, "editable": False, "note": None, "present": {}, "context": None}
    sch = schema(d, board)
    if sch is None:
        return {"schema": None, "values": None, "editable": False, "note": note(d, board), "present": {}, "context": None}
    try:
        cfg = parse_cfg(text)
        cur = from_cfg(cfg, d, board)
        ctx = context(cfg, board)
    except CfgError as e:
        return {"schema": sch, "values": None, "editable": False, "note": str(e), "present": {}, "context": None}
    return {"schema": sch, "values": cur["values"], "editable": cur["editable"], "note": cur["reason"],
            "present": cur["present"], "context": ctx}
