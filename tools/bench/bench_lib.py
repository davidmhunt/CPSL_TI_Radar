"""Pure parsing / summary logic for the streaming bench harness (no hardware).

The harness runs the unmodified ``CPSL_TI_Radar_CPP`` binary with a system
config that has ``"verbose": true`` and reads its stdout.  Everything the
driver already prints is enough:

* ``[DCA1000] SO_RCVBUF granted: <bytes> bytes``
* per DCA1000 frame (verbose)::

      frame: <received_frames>
      \tpackets: <n>
      \tdata bytes: <n>
      \tdropped packets: <n>
      \tdropped packet events: <n>
      \trx_overrun_count: <n>

* per serial header (verbose; same ``frame:`` prefix, followed by ``\tversion:``)
* ``TLV frame <n>: <k> detected points`` (main.cpp, one per delivered frame)
* ``SerialStreamer: frame number jumped from a to b (M missed in total)``

Nothing here imports the driver or touches a port.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

CSV_COLUMNS = [
    "second",
    "dca_frames",
    "dca_packets",
    "dca_dropped_packets",
    "dca_dropped_packet_events",
    "dca_rx_overrun_count_cum",
    "serial_headers",
    "tlv_frames",
    "tlv_missed_frames",
    "cpu_pct",
    "rss_kb",
]

# glibc/libstdc++ ofstream buffer; used only to classify a short .bin
OFSTREAM_BUFFER_BYTES = 8192

_RE_RCVBUF = re.compile(r"SO_RCVBUF granted:\s*(\d+)\s*bytes")
_RE_FRAME = re.compile(r"^frame:\s*(\d+)\s*$")
_RE_TLV_FRAME = re.compile(r"^TLV frame\s+(\d+):\s*(\d+)\s+detected points")
_RE_MISSED = re.compile(r"frame number jumped from\s+(\d+)\s+to\s+(\d+)\s+\((\d+)\s+missed in total\)")
_RE_KV = re.compile(r"^\t([A-Za-z_ ]+):\s*(-?\d+)")
_WARN_WORDS = ("timed out", "warning", "failed", "error", "not acknowledge")


@dataclass
class Parser:
    """Stateful line parser: feed (timestamp, line); collects events."""

    events: list = field(default_factory=list)  # dicts with t, kind, ...
    granted_rcvbuf: int | None = None
    warnings: list = field(default_factory=list)
    _pending: dict | None = None

    def feed(self, t: float, line: str) -> None:
        line = line.rstrip("\r\n")
        m = _RE_RCVBUF.search(line)
        if m:
            self.granted_rcvbuf = int(m.group(1))
            return
        m = _RE_FRAME.match(line)
        if m:
            self._flush_pending()
            self._pending = {"t": t, "frame": int(m.group(1)), "kv": {}}
            return
        if self._pending is not None:
            m = _RE_KV.match(line)
            if m:
                self._pending["kv"][m.group(1).strip()] = int(m.group(2))
                return
            if not line.startswith("\t"):
                self._flush_pending()
        m = _RE_TLV_FRAME.match(line)
        if m:
            self.events.append({"t": t, "kind": "tlv_frame", "frame": int(m.group(1)),
                                "points": int(m.group(2))})
            return
        m = _RE_MISSED.search(line)
        if m:
            self.events.append({"t": t, "kind": "tlv_missed", "cum": int(m.group(3))})
            return
        low = line.lower()
        if any(w in low for w in _WARN_WORDS) and len(self.warnings) < 50:
            self.warnings.append(line.strip())

    def _flush_pending(self) -> None:
        p, self._pending = self._pending, None
        if p is None:
            return
        kv = p["kv"]
        if "packets" in kv:
            self.events.append({
                "t": p["t"], "kind": "dca_frame", "frames_cum": p["frame"],
                "packets": kv.get("packets", 0),
                "dropped": kv.get("dropped packets", 0),
                "events": kv.get("dropped packet events", 0),
                "overrun": kv.get("rx_overrun_count", 0),
            })
        elif "version" in kv:
            self.events.append({"t": p["t"], "kind": "serial_header", "frame": p["frame"]})

    def finish(self) -> None:
        self._flush_pending()


def first_frame_time(events: list) -> float | None:
    """Time of the first frame of any stream (t0 of the run)."""
    for e in events:
        if e["kind"] in ("dca_frame", "tlv_frame", "serial_header"):
            return e["t"]
    return None


def aggregate(events: list, cpu_samples: list, t0: float, seconds: int) -> list:
    """Per-second rows over [t0+k-1, t0+k).

    cpu_samples: [(t, cpu_ticks_total, clk_tck, rss_kb)] sampled at/near each
    boundary; the first sample must be at t0.  Cumulative counters are
    differenced against the last value seen before the bucket (0 before t0).
    """
    rows = []
    cum = {"packets": 0, "dropped": 0, "events": 0, "overrun": 0, "missed": 0}
    for k in range(1, seconds + 1):
        lo, hi = t0 + k - 1, t0 + k
        bucket = [e for e in events if lo <= e["t"] < hi]
        dca = [e for e in bucket if e["kind"] == "dca_frame"]
        row = {c: 0 for c in CSV_COLUMNS}
        row["second"] = k
        row["dca_frames"] = len(dca)
        for e in dca:
            row["dca_packets"] = e["packets"] - cum["packets"]
            row["dca_dropped_packets"] = e["dropped"] - cum["dropped"]
            row["dca_dropped_packet_events"] = e["events"] - cum["events"]
        if dca:
            last = dca[-1]
            cum.update(packets=last["packets"], dropped=last["dropped"],
                       events=last["events"], overrun=last["overrun"])
        row["dca_rx_overrun_count_cum"] = cum["overrun"]
        row["serial_headers"] = sum(e["kind"] == "serial_header" for e in bucket)
        row["tlv_frames"] = sum(e["kind"] == "tlv_frame" for e in bucket)
        missed = [e for e in bucket if e["kind"] == "tlv_missed"]
        if missed:
            row["tlv_missed_frames"] = missed[-1]["cum"] - cum["missed"]
            cum["missed"] = missed[-1]["cum"]
        row["cpu_pct"], row["rss_kb"] = _cpu_for_second(cpu_samples, k)
        rows.append(row)
    return rows


def _cpu_for_second(samples: list, k: int):
    if len(samples) <= k:
        return "", ""
    (t_a, ticks_a, tck, _), (t_b, ticks_b, _, rss_b) = samples[k - 1], samples[k]
    dt = t_b - t_a
    if dt <= 0 or tck <= 0:
        return "", ""
    return round(100.0 * (ticks_b - ticks_a) / tck / dt, 1), rss_b


def parse_proc_stat(text: str):
    """(utime+stime ticks, rss pages) from /proc/<pid>/stat text."""
    # comm may contain spaces/parens: split after the last ')'
    rest = text[text.rindex(")") + 2:].split()
    utime, stime, rss_pages = int(rest[11]), int(rest[12]), int(rest[21])
    return utime + stime, rss_pages


def summarize(rows: list) -> dict:
    n = len(rows)
    out = {"seconds": n}
    if not n:
        return out
    def col(name):
        return [r[name] for r in rows if r[name] != ""]
    for name, key in (("dca_frames", "dca"), ("tlv_frames", "tlv")):
        vals = col(name)
        out[f"{key}_frames_total"] = sum(vals)
        out[f"{key}_fps_mean"] = round(sum(vals) / n, 3)
        out[f"{key}_fps_min"] = min(vals)
        out[f"{key}_fps_max"] = max(vals)
    out["dca_dropped_packets_total"] = sum(col("dca_dropped_packets"))
    out["dca_dropped_packet_events_total"] = sum(col("dca_dropped_packet_events"))
    out["dca_packets_total"] = sum(col("dca_packets"))
    out["dca_rx_overrun_count_final"] = rows[-1]["dca_rx_overrun_count_cum"]
    out["serial_headers_total"] = sum(col("serial_headers"))
    out["tlv_missed_frames_total"] = sum(col("tlv_missed_frames"))
    cpu = col("cpu_pct")
    if cpu:
        out["cpu_pct_mean"] = round(sum(cpu) / len(cpu), 1)
        out["cpu_pct_max"] = max(cpu)
    return out


def expected_from_radar_cfg(cfg_text: str) -> dict:
    """bytes_per_frame and frame period, mirroring RadarConfigReader.

    bytes_per_frame = 4 * rx_antennas * adc_samples * chirps_per_frame
    (rx_antennas defaults to 4; popcount of channelCfg rxMask, plus the slave
    mask for the 6-field cascade form).  Only the last profileCfg/frameCfg
    counts, as in the C++ reader.
    """
    rx, samples, frame = 4, None, None
    for line in cfg_text.splitlines():
        v = line.split()
        if not v or v[0].startswith("%"):
            continue
        if v[0] == "channelCfg":
            rx = bin(int(v[1])).count("1")
            if len(v) >= 6:
                rx += bin(int(v[4])).count("1")
        elif v[0] == "profileCfg":
            samples = int(v[10])
        elif v[0] == "frameCfg":
            frame = v
    if samples is None or frame is None:
        raise ValueError("radar cfg lacks profileCfg or frameCfg")
    chirps = (int(frame[2]) - int(frame[1]) + 1) * int(frame[3])
    period = float(frame[6]) if len(frame) >= 10 else float(frame[5])
    return {
        "rx_antennas": rx, "adc_samples": samples, "chirps_per_frame": chirps,
        "bytes_per_frame": 4 * rx * samples * chirps, "frame_period_ms": period,
        "expected_fps": round(1000.0 / period, 3),
    }


def check_bin_size(actual: int, bytes_per_frame: int, received_frames: int,
                   stopped_by_sigint: bool) -> dict:
    """Compare adc_data.bin size with bytes_per_frame x received_frames.

    The driver prints a frame's stats before writing it and the SIGINT
    handler calls exit() without destroying the Runner, so the ofstream is
    never flushed.  A short file on the SIGINT path is therefore classified
    separately from a genuine mismatch (it is still reported as a diff).
    """
    expected = bytes_per_frame * received_frames
    diff = expected - actual
    if diff == 0:
        verdict = "exact"
    elif stopped_by_sigint and 0 < diff <= bytes_per_frame + OFSTREAM_BUFFER_BYTES:
        verdict = "short_sigint_tail"
    else:
        verdict = "MISMATCH"
    return {"expected_bytes": expected, "actual_bytes": actual, "short_by_bytes": diff,
            "short_by_frames": round(diff / bytes_per_frame, 4) if bytes_per_frame else None,
            "verdict": verdict}


def safe_label(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")


def result_basename(tag: str, config_stem: str, rep: int, seconds: int, stamp: str) -> str:
    return f"{safe_label(tag)}__{safe_label(config_stem)}__rep{rep}__{seconds}s__{stamp}"


def write_csv(path: Path, rows: list) -> None:
    # 'x': never overwrite an earlier result (rule 1)
    with open(path, "x", newline="") as fh:
        fh.write(",".join(CSV_COLUMNS) + "\n")
        for r in rows:
            fh.write(",".join(str(r[c]) for c in CSV_COLUMNS) + "\n")


def write_sidecar(path: Path, record: dict) -> None:
    with open(path, "x") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
