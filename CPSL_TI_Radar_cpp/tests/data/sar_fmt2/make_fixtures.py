#!/usr/bin/env python3
"""Regenerate the core-24 dataFmt 2 (adc_sar_meta) fixtures that tests/test_sar_meta.cpp replays through the driver.

    uv run python CPSL_TI_Radar_cpp/tests/data/sar_fmt2/make_fixtures.py [OUT_DIR]

OUT_DIR defaults to this directory. The captures are built with the firmware project's synthetic-capture tool
(firmware_dev/projects/iwr1843_sar_lvds/tools/sar_synth.py: ADC blocks, records, the DCA1000 byte order and
datagram split) and the goldens are that project's reference parser's output (sar_parse.py analyze() +
write_outputs(), i.e. its _meta.csv rows, and a per-chirp FNV-1a 64 hash of its _adc.bin). Nothing here models the
format itself; firmware_dev must be checked out. Deterministic: tests/test_sar_fmt2_fixtures.py regenerates into a
temporary directory and requires byte-equal files, so a change in the firmware tools shows up as a test failure.

Files: <cfg>.cfg (the run's radar cfg), <scenario>.sarcap (SARCAP1 capture: per datagram u16 LE length + the
datagram with its 10-byte DCA1000 header), <golden>_meta.csv (sar_parse rows), manifest.json.
"""
import json
import os
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TOOLS = REPO / "firmware_dev" / "projects" / "iwr1843_sar_lvds" / "tools"
sys.path.insert(0, str(TOOLS))
import sar_common as common  # noqa: E402
import sar_parse  # noqa: E402
import sar_synth  # noqa: E402

NC = 8  # chirps per frame


def fnv1a64(data):
    h = 0xCBF29CE484222325
    for b in data:
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return "%016x" % h


def cfg_variant(ns, hdr):
    text = sar_synth.make_cfg(ns=ns, nc=NC)
    if not hdr:
        text = text.replace("lvdsStreamCfg -1 1 2 0", "lvdsStreamCfg -1 0 2 0")
    return text, common.cfg_params(text)


def lagged_run(cfg, n, run_idx=1, sat=(), late=(), missed=(), seed=3):
    """Device-order packets like sar_synth._build_run, but with the bench's saturation lags (format doc section 3):
    2 in a frame, 1 at chirp 1 of the run and at chirp 0 of odd frames, 2 at chirp 0 of even frames (so a frame's
    last two chirps are reported by the next frame). `late`: LATE flag set (record still valid). `missed`: the
    chirp-start write missed packet k, whose own slot still holds chirp k-2's record (it fails validation)."""
    rng = random.Random(seed)
    nc, H = cfg["nchirps"], cfg["H"]
    tc, tb = int(round(cfg["tc_s"] * 1e8)), int(round(cfg["tb_s"] * 1e8))
    sat_set = set(sat)
    recs = []
    for j in range(n):
        frame, cif = divmod(j, nc)
        lag = 0 if j == 0 else 1 if (j == 1 or (cif == 0 and frame % 2 == 1)) else 2
        flags = 0x2 | (0x1 if lag else 0) | (0x4 if j in late else 0)
        target = j - lag
        slices = (5 + target % 3) if (lag and target in sat_set) else 0
        ts = 10_000_000 + j * tc + frame * tb
        recs.append(sar_parse.REC.pack(sar_parse.MAGIC, 1, flags, frame, cif, nc, j, run_idx, slices, lag, ts))
    pk = []
    for k in range(n):
        own, other = recs[k], (recs[k - 1] if k >= 1 else bytes(32))
        if k in missed:
            own = recs[k - 2] if k >= 2 else bytes(32)
        slots = (own + other) if k % 2 == 0 else (other + own)
        pk.append(bytes(H) + sar_synth.adc_block(k, cfg, sat_set, rng, 3.0, 400.0, 200) + slots)
        assert len(pk[-1]) == cfg["B"]
    return pk


def drop_lost(cfg, dg):
    """Drop one datagram wholly inside one packet's ADC block (packet 9..30) and one that covers packet k's own
    record slot (packet 17..30, another frame); both frames are followed by more data, so the driver emits them."""
    B, M, H = cfg["B"], cfg["M"], cfg["H"]
    adc_i = rec_i = None
    for i, d in enumerate(dg):
        lo = int.from_bytes(d[4:10], "little")
        hi = lo + len(d) - 10
        k = lo // B
        if adc_i is None and 9 <= k <= 14 and k == (hi - 1) // B and lo % B >= H and (hi - k * B) <= M:
            adc_i = i
        own = k * B + M + 32 * (k % 2)
        if rec_i is None and 17 <= k <= 30 and lo <= own < hi and own + 32 <= hi:
            rec_i = i
    assert adc_i is not None and rec_i is not None and adc_i != rec_i
    return [d for i, d in enumerate(dg) if i not in (adc_i, rec_i)]


def golden(name, dg, cfg, chirp_avail, run_idx, tmp):
    res = sar_parse.analyze(dg, cfg, {"chirpAvail": chirp_avail, "runIdx": run_idx})
    prefix = os.path.join(tmp, name)
    sar_parse.write_outputs(res, prefix)
    adc = Path(prefix + "_adc.bin").read_bytes()
    per = 4 * cfg["nrx"] * cfg["ns"]
    assert len(adc) == chirp_avail * per
    meta = Path(prefix + "_meta.csv").read_bytes()
    return {"meta_csv": name + "_meta.csv", "chirps": chirp_avail, "accepted": bool(res["accepted"]),
            "failing_checks": res["failing"], "adc_chirp_fnv1a64": [fnv1a64(adc[k * per:(k + 1) * per])
                                                                     for k in range(chirp_avail)]}, meta


def write_capture(path, dg):
    with open(path, "wb") as fh:
        common.write_capture_header(fh)
        for d in dg:
            common.write_datagram(fh, d)


def main(argv=None):
    out = Path(argv[0]) if argv else HERE
    out.mkdir(parents=True, exist_ok=True)
    cfgs = {"sar_fmt2_h64.cfg": cfg_variant(512, True), "sar_fmt2_h56.cfg": cfg_variant(510, True),
            "sar_fmt2_h0.cfg": cfg_variant(512, False)}
    for fname, (text, _) in cfgs.items():
        (out / fname).write_text(text)
    c64 = cfgs["sar_fmt2_h64.cfg"][1]
    scen = []

    def add(name, cfg_file, dg, goldens, notes):
        write_capture(out / (name + ".sarcap"), dg)
        scen.append({"name": name, "cfg": cfg_file, "capture": name + ".sarcap", "datagrams": len(dg),
                     "goldens": goldens, "notes": notes})

    with tempfile.TemporaryDirectory() as tmp:
        def gold(name, dg, cfg, n, run):
            g, meta = golden(name, dg, cfg, n, run, tmp)
            (out / g["meta_csv"]).write_bytes(meta)
            return g

        # clean: sar_synth's own run (saturation lag 1), 5 frames
        sat = (3, 7, 8, 15, 23, 38)
        dg = sar_synth.to_datagrams(sar_synth.build_run(c64, 40, sat_chirps=sat))
        add("clean", "sar_fmt2_h64.cfg", dg, [gold("clean", dg, c64, 40, 1)], "sar_synth.build_run, H 64")
        # header variants: H 56 (rx x samples % 4 == 2) and header off
        for name, cf in (("clean_h56", "sar_fmt2_h56.cfg"), ("clean_h0", "sar_fmt2_h0.cfg")):
            c = cfgs[cf][1]
            dg = sar_synth.to_datagrams(sar_synth.build_run(c, 16, sat_chirps=(2, 9)))
            add(name, cf, dg, [gold(name, dg, c, 16, 1)], "sar_synth.build_run, H %d" % c["H"])
        # late record: LATE-flagged valid records, one missed record write (stale slot), lag 2 / cross-frame results
        pk = lagged_run(c64, 40, sat=(3, 6, 7, 14, 15, 22, 30, 31), late=(5, 20), missed=(13,))
        dg = sar_synth.to_datagrams(pk)
        add("late_record", "sar_fmt2_h64.cfg", dg, [gold("late_record", dg, c64, 40, 1)],
            "LATE flag on chirps 5, 20; chirp 13's record write missed (slot holds chirp 11's); lags 1/2")
        # lost datagrams: one inside an ADC block, one over a record slot
        dg = drop_lost(c64, sar_synth.to_datagrams(sar_synth.build_run(c64, 40, sat_chirps=sat)))
        add("lost_datagram", "sar_fmt2_h64.cfg", dg, [gold("lost_datagram", dg, c64, 40, 1)],
            "two datagrams dropped: one ADC-only, one covering a record slot")
        # run restart, same recording (sensorStop/sensorStart without re-arming): run 2's records never validate
        dg = sar_synth.to_datagrams(sar_synth.build_run(c64, 40, sat_chirps=sat) +
                                    sar_synth.build_run(c64, 16, run_idx=2, seed=2))
        add("run_restart", "sar_fmt2_h64.cfg", dg, [gold("run_restart", dg, c64, 56, 1)],
            "run 1 (40 chirps) then run 2 (16 chirps, runIdx 2) in one recording; golden over all 56 packets")
        # DCA1000 restart: recording A (run 1), then recording B (run 2) with byte counts and sequence from 0/1.
        # A is > 64 datagrams so B's first sequence numbers are outside the duplicate window (FrameAssembler resync).
        dga = sar_synth.to_datagrams(sar_synth.build_run(c64, 48, sat_chirps=sat))
        dgb = sar_synth.to_datagrams(sar_synth.build_run(c64, 24, run_idx=2, seed=5, sat_chirps=(4, 9)))
        add("dca_restart", "sar_fmt2_h64.cfg", dga + dgb,
            [gold("dca_restart_a", dga, c64, 48, 1), gold("dca_restart_b", dgb, c64, 24, 2)],
            "recording A (48 chirps, run 1, %d datagrams) + recording B (24 chirps, run 2, counts from 0)" % len(dga))

    manifest = {"generator": "CPSL_TI_Radar_cpp/tests/data/sar_fmt2/make_fixtures.py (core-24)",
                "tools": "firmware_dev/projects/iwr1843_sar_lvds/tools (sar_synth.py, sar_parse.py)",
                "chirps_per_frame": NC, "scenarios": scen}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
