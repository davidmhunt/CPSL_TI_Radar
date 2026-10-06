"""Pure parsing / summary logic for the streaming bench harness (no hardware).

The harness runs the unmodified ``CPSL_TI_Radar_CPP`` binary with ``--stats``
and reads only its ``stats v1`` lines (format: docs/ARCHITECTURE.md, "Stats
lines"). Once a second, and once more after the driver has stopped, it
prints one line per enabled stream with counters cumulative since start::

    stats v1 dca t=<s> frames=<n> packets=<n> dropped=<n> drop_events=<n> late=<n>
        duplicate=<n> incomplete=<n> skipped=<n> overrun=<n> overwritten=<n>
        stalls=<n> rcvbuf=<bytes> kernel_drops=<n> ring_full=<n>
        implausible=<n> resyncs=<n>                               (one line)
    stats v1 serial t=<s> frames=<n> missed=<n> overwritten=<n> stalls=<n>

Any other line is only scanned for warning words. Nothing here imports the
driver or touches a port.
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
    "tlv_frames",
    "tlv_missed_frames",
    "cpu_pct",
    "rss_kb",
]

# glibc/libstdc++ ofstream buffer; used only to classify a short .bin
OFSTREAM_BUFFER_BYTES = 8192

_RE_STATS = re.compile(r"^stats v1 (dca|serial)\s+(.*)$")
_WARN_WORDS = ("timed out", "warning", "failed", "error", "not acknowledge")


@dataclass
class Parser:
    """Stateful line parser: feed (timestamp, line); collects stats events.

    Each ``stats v1`` line becomes {"t": arrival time, "kind": "dca_stats" or
    "serial_stats", "t_driver": the line's t=, <key>: <int>, ...}.
    """

    events: list = field(default_factory=list)
    granted_rcvbuf: int | None = None
    warnings: list = field(default_factory=list)

    def feed(self, t: float, line: str) -> None:
        line = line.rstrip("\r\n")
        m = _RE_STATS.match(line)
        if m:
            ev = {"t": t, "kind": m.group(1) + "_stats"}
            for tok in m.group(2).split():
                key, _, val = tok.partition("=")
                try:
                    if key == "t":
                        ev["t_driver"] = float(val)
                    else:
                        ev[key] = int(val)
                except ValueError:
                    continue
            self.events.append(ev)
            if ev["kind"] == "dca_stats" and "rcvbuf" in ev:
                self.granted_rcvbuf = ev["rcvbuf"]
            return
        low = line.lower()
        if any(w in low for w in _WARN_WORDS) and len(self.warnings) < 50:
            self.warnings.append(line.strip())

    def finish(self) -> None:
        """Nothing is buffered across lines; kept for the harness's call order."""


def first_frame_time(events: list) -> float | None:
    """Host time at which the first second with a frame began (t0 of the run).

    That is the arrival of the first stats line reporting a frame, minus the
    driver-clock interval it covers (its t= minus the previous line's t=, or
    minus 0 when it is the first line). On a normal start this is the
    driver's start(); row 1 then covers start() to that line.
    """
    prev = {}
    for e in events:
        if e.get("frames", 0) > 0:
            return e["t"] - (e.get("t_driver", 0.0) - prev.get(e["kind"], 0.0))
        prev[e["kind"]] = e.get("t_driver", 0.0)
    return None


def last_stats(events: list, kind: str, t: float | None = None) -> dict | None:
    """The last stats event of `kind` that arrived at or before `t` (any time if None)."""
    last = None
    for e in events:
        if e["kind"] == kind and (t is None or e["t"] <= t):
            last = e
    return last


def _first_frame_line(events: list) -> dict | None:
    for e in events:
        if e.get("frames", 0) > 0:
            return e
    return None


def aggregate(events: list, cpu_samples: list, t0: float, seconds: int) -> list:
    """Per-second rows from the cumulative stats lines, on the driver's clock.

    Rows follow the lines' own t= values: the first line reporting a frame
    (driver time T1) closes row 1, which is measured from zero, so nothing
    counted before it is lost. Row k ends at the last line with
    t <= T1 + k - 0.5 (the half second absorbs print jitter), and the last
    row runs to the final line, printed after the stop. The rows therefore
    add up to the final line's counters.
    cpu_samples: [(t, cpu_ticks_total, clk_tck, rss_kb)] sampled at/near
    t0 + k on the host clock (t0 from first_frame_time).
    """
    first = _first_frame_line(events)
    t1 = first.get("t_driver", 0.0) if first else 0.0

    def upto(kind, hi):
        last = None
        for e in events:
            if e["kind"] == kind and e.get("t_driver", 0.0) <= hi:
                last = e
        return last

    def delta(kind, key, k):
        hi = float("inf") if k == seconds else t1 + k - 0.5
        b = upto(kind, hi)
        if b is None:
            return 0
        a = upto(kind, t1 + k - 1.5) if k > 1 else None
        return b.get(key, 0) - (a.get(key, 0) if a else 0)

    rows = []
    for k in range(1, seconds + 1):
        row = {c: 0 for c in CSV_COLUMNS}
        row["second"] = k
        row["dca_frames"] = delta("dca_stats", "frames", k)
        row["dca_packets"] = delta("dca_stats", "packets", k)
        row["dca_dropped_packets"] = delta("dca_stats", "dropped", k)
        row["dca_dropped_packet_events"] = delta("dca_stats", "drop_events", k)
        hi = float("inf") if k == seconds else t1 + k - 0.5
        row["dca_rx_overrun_count_cum"] = (upto("dca_stats", hi) or {}).get("overrun", 0)
        row["tlv_frames"] = delta("serial_stats", "frames", k)
        row["tlv_missed_frames"] = delta("serial_stats", "missed", k)
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


def summarize(rows: list, events: list | None = None) -> dict:
    """Run summary. Rates (fps) come from the rows; with `events`, the totals
    and the final overrun count come from the driver's final stats lines
    (printed after its stop), so they match adc_data.bin even for a run that
    ended early."""
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
    out["tlv_missed_frames_total"] = sum(col("tlv_missed_frames"))
    if events:
        dca, ser = last_stats(events, "dca_stats"), last_stats(events, "serial_stats")
        if dca:
            out["dca_frames_total"] = dca.get("frames", 0)
            out["dca_packets_total"] = dca.get("packets", 0)
            out["dca_dropped_packets_total"] = dca.get("dropped", 0)
            out["dca_dropped_packet_events_total"] = dca.get("drop_events", 0)
            out["dca_rx_overrun_count_final"] = dca.get("overrun", 0)
            # since core-15: the RX path never discards (overrun stays 0);
            # a backlog the socket buffer could not hold is a kernel drop
            out["dca_kernel_drops_final"] = dca.get("kernel_drops", 0)
            out["dca_resyncs_final"] = dca.get("resyncs", 0)
        if ser:
            out["tlv_frames_total"] = ser.get("frames", 0)
            out["tlv_missed_frames_total"] = ser.get("missed", 0)
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

    Before core-11 the driver's SIGINT handler called exit() without
    destroying the Runner, so the ofstream was never flushed (896 B short in
    the baseline).  A short file on the SIGINT path is therefore classified
    separately from a genuine mismatch (it is still reported as a diff); a
    build with the core-11 stop path should give "exact".
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


def parse_cmake_cache(text: str) -> dict:
    """KEY -> value for the build-type and compiler flag entries of a CMakeCache.txt."""
    want = ("CMAKE_BUILD_TYPE", "CMAKE_CXX_FLAGS", "CMAKE_CXX_FLAGS_RELEASE",
            "CMAKE_CXX_FLAGS_DEBUG", "CMAKE_CXX_COMPILER", "CMAKE_CXX_STANDARD")
    out = {}
    for line in text.splitlines():
        if line.startswith(("//", "#")) or ":" not in line or "=" not in line:
            continue
        key = line.split(":", 1)[0]
        if key in want:
            out[key] = line.split("=", 1)[1]
    return out


def frame_cfg_num_frames(cfg_text: str):
    """numFrames of the last frameCfg line (0 = run forever), or None."""
    n = None
    for line in cfg_text.splitlines():
        v = line.split()
        if v and v[0] == "frameCfg" and len(v) > 4:
            n = int(v[4])
    return n


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
