"""Firmware identity matcher (gui-33): pure, no I/O. Given what the board answered to a firmware's `identify` probes
(config/firmware/<fw>.json -> identify.<board>), say whether it runs that firmware.

  identify(fw, board, replies) -> {verdict, fields, found, detail, flash_hint, level, probes}

verdict: match | mismatch | unknown | skipped
  skipped   no identify data for (fw, board), or a once-per-power-up board whose entry is not `once_safe` (never queried)
  unknown   level `unverified`, or no / partial reply with no failing probe (warn and continue)
  mismatch  a probe's reply fails `require` or hits `reject` (fatal under the default policy)
  match     every probe answered and passed
`replies` maps a probe cmd to the board's reply text; None / blank = no reply. A failing probe wins over a missing one.
Regexes use the subset shared by Python `re` and C++ `std::regex` ECMAScript (no lookbehind, named groups, inline flags);
the C++ port mirrors this file (parity through CPSL_TI_Radar_cpp/tests/data/fw_replies/manifest.json)."""
from __future__ import annotations

import json
import re


LEVELS = ("bench", "source", "unverified")
PROBE_KEYS = {"cmd", "require", "reject", "show"}
ENTRY_KEYS = {"level", "timeout_ms", "once_safe", "probes", "flash_hint", "note"}
DEFAULT_TIMEOUT_MS = 1000


def strip_fixture(text: str) -> str:
    """A fixture file's reply text: drop the '# ...' provenance header lines."""
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))


def check_identify(ident, boards=None) -> list[str]:
    """Schema problems of a descriptor's `identify` block ([] = valid; absent block is valid)."""
    if ident is None:
        return []
    if not isinstance(ident, dict):
        return ["identify must be {board: entry}"]
    bad: list[str] = []
    for b, e in ident.items():
        w = f"identify[{b}]"
        if boards is not None and b not in boards:
            bad.append(f"{w}: not a board of this firmware")
        if not isinstance(e, dict):
            bad.append(f"{w}: must be an object")
            continue
        if set(e) - ENTRY_KEYS:
            bad.append(f"{w}: unknown keys {sorted(set(e) - ENTRY_KEYS)}")
        if e.get("level") not in LEVELS:
            bad.append(f"{w}: level must be one of {LEVELS}")
        if "timeout_ms" in e and not (isinstance(e["timeout_ms"], int) and not isinstance(e["timeout_ms"], bool) and e["timeout_ms"] > 0):
            bad.append(f"{w}: timeout_ms must be a positive int")
        if "once_safe" in e and not isinstance(e["once_safe"], bool):
            bad.append(f"{w}: once_safe must be a bool")
        if not isinstance(e.get("flash_hint"), str) or not e.get("flash_hint"):
            bad.append(f"{w}: flash_hint missing")
        pr = e.get("probes")
        if not isinstance(pr, list) or not pr:
            bad.append(f"{w}: probes must be a non-empty list")
            continue
        for i, p in enumerate(pr):
            pw = f"{w}.probes[{i}]"
            if not isinstance(p, dict) or set(p) - PROBE_KEYS or not isinstance(p.get("cmd"), str) or not p.get("cmd"):
                bad.append(f"{pw}: must be {{cmd, require, reject, show}}")
                continue
            for k in ("require", "reject"):
                if not (isinstance(p.get(k, []), list) and all(isinstance(x, str) for x in p.get(k, []))):
                    bad.append(f"{pw}.{k}: must be a list of regex strings")
            if not isinstance(p.get("show", {}), dict):
                bad.append(f"{pw}.show: must be {{field: regex}}")
            pats = [*p.get("require", []), *p.get("reject", []), *(p.get("show", {}) or {}).values()]
            for rx in pats:
                try:
                    re.compile(rx)
                except (re.error, TypeError):
                    bad.append(f"{pw}: bad regex {rx!r}")
            if not (p.get("require") or p.get("reject")):
                bad.append(f"{pw}: needs a require or reject pattern")
        if e.get("level") in ("bench", "source") and not any(p.get("require") or p.get("reject") for p in pr if isinstance(p, dict)):
            bad.append(f"{w}: no probe can fail")
    return bad


def entry(fw: str, board: str) -> dict | None:
    from .cfg import firmware as fwmod   # lazy: cfg.firmware imports this module for check_identify

    d = fwmod.get(fw)
    return ((d or {}).get("identify") or {}).get(board)


def probes(fw: str, board: str) -> list[dict]:
    e = entry(fw, board)
    return list(e["probes"]) if e else []


def timeout_ms(fw: str, board: str) -> int:
    e = entry(fw, board)
    return int((e or {}).get("timeout_ms", DEFAULT_TIMEOUT_MS))


def _board_once(board: str) -> bool:
    from .cfg import firmware as fwmod

    try:
        d = json.loads((fwmod.BOARDS_DIR / f"{board}.json").read_text())
    except (OSError, ValueError):
        return False
    return bool((d.get("lifecycle") or {}).get("config_once_per_boot"))


def _clean(reply) -> str:
    return (reply or "").replace("\r", "")


def _first_line(replies: dict, cmds: list[str]) -> str:
    """First informative reply line (not the echoed command, not a prompt-only line, not 'Done')."""
    for c in cmds:
        for ln in _clean(replies.get(c)).split("\n"):
            s = ln.strip()
            if s and s != c and s != "Done" and not s.endswith(":/>"):
                return s
    return ""


def identify(fw: str, board: str, replies: dict, *, once: bool | None = None) -> dict:
    e = entry(fw, board)
    out = {"verdict": "skipped", "fields": {}, "found": "", "detail": "", "flash_hint": "", "level": None, "probes": []}
    if e is None:
        out["detail"] = f"no identify data for {fw} on {board}"
        return out
    out.update(level=e["level"], flash_hint=e["flash_hint"], probes=[p["cmd"] for p in e["probes"]])
    once = _board_once(board) if once is None else once
    if once and not e.get("once_safe", False):
        out["detail"] = "once-per-power-up board, not once_safe: not queried"
        return out
    fields, failed, missing = {}, [], []
    for p in e["probes"]:
        text = _clean(replies.get(p["cmd"]))
        if not text.strip():
            missing.append(p["cmd"])
            continue
        for name, rx in (p.get("show") or {}).items():
            m = re.search(rx, text)
            if m:
                fields[name] = m.group(1).strip()
        for rx in p.get("require", []):
            if not re.search(rx, text):
                failed.append(f"{p['cmd']}: reply lacks /{rx}/")
        for rx in p.get("reject", []):
            if re.search(rx, text):
                failed.append(f"{p['cmd']}: reply matches /{rx}/")
    cmds = out["probes"]
    out["fields"] = fields
    out["found"] = " ".join(f"{k}={v}" for k, v in fields.items()) or _first_line(replies, cmds) or "no reply"
    if e["level"] == "unverified":
        out.update(verdict="unknown", detail="identify entry is unverified: not enforced")
    elif failed:
        out.update(verdict="mismatch", detail="; ".join(failed))
    elif missing:
        out.update(verdict="unknown", detail=f"no reply to {', '.join(missing)}")
    else:
        out.update(verdict="match", detail="")
    return out


def mismatch_message(fw: str, board: str, res: dict, port: str = "") -> str:
    where = f" on {port}" if port else ""
    return (f"firmware mismatch{where}: system JSON expects {fw} ({board}), board answered {res['found']}. "
            f"Flash it: {res['flash_hint']}")
