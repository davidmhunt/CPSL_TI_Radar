"""Hardware-free tests for tools/bench (parsing, summary, end-to-end with a fake driver)."""
import json
import stat
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools/bench"))
import bench_lib as lib  # noqa: E402
import bench_run  # noqa: E402
import host_setup  # noqa: E402  (on sys.path via bench_run)

STRESS_JSON = REPO / "CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test.json"
STRESS_CFG = REPO / "CPSL_TI_Radar_cpp/config/radar/nav_configs/1843_stress_test.cfg"


def dca_line(t, frames, pkts, dropped=0, events=0, overrun=0):
    return (f"stats v1 dca t={t:.3f} frames={frames} packets={pkts} dropped={dropped} "
            f"drop_events={events} late=0 duplicate=0 incomplete=0 skipped=0 overrun={overrun} "
            f"overwritten=0 stalls=0 rcvbuf=134217728")


def feed(parser, items):
    for t, line in items:
        parser.feed(t, line)
    parser.finish()


def test_parser_reads_only_stats_lines():
    p = lib.Parser()
    feed(p, [(0.0, "Using config: x.json"),
             (0.1, "[DCA1000] SO_RCVBUF granted: 134217728 bytes"),
             (0.2, "frame: 1"), (0.2, "\tpackets: 345"),  # old debug lines: ignored
             (1.0, dca_line(1.0, 10, 3450)),
             (1.0, "stats v1 serial t=1.000 frames=9 missed=1 overwritten=0 stalls=0"),
             (1.1, "TLV frame 7: 3 detected points (first: x=1 y=2 z=0 v=0)"),
             (1.2, "warning: Radar: sensorStop was not acknowledged with 'Done'"),
             (1.3, "stats v2 dca t=1 frames=99")])  # unknown version: ignored
    kinds = [e["kind"] for e in p.events]
    assert kinds == ["dca_stats", "serial_stats"]
    assert p.granted_rcvbuf == 134217728
    assert p.events[0]["frames"] == 10 and p.events[0]["packets"] == 3450
    assert p.events[0]["t_driver"] == 1.0 and p.events[0]["t"] == 1.0
    assert p.events[1]["missed"] == 1
    assert p.warnings == ["warning: Radar: sensorStop was not acknowledged with 'Done'"]


def test_aggregate_deltas_and_cpu():
    p = lib.Parser()
    # driver lines once a second (driver t, host arrival 9.0 s later +- 0.2 s), then
    # the final line after the stop. The first line already counts 1 frame.
    feed(p, [(10.0, dca_line(1.0, 1, 100)),
             (11.2, dca_line(2.0, 4, 400)),
             (11.8, dca_line(2.95, 6, 600, 4, 1, 2)),  # printed early: still ends row 3
             (13.1, dca_line(4.0, 6, 600, 4, 1, 2)),
             (13.3, dca_line(4.2, 7, 700, 4, 1, 2)),  # final line, after the stop
             (10.0, "stats v1 serial t=1.000 frames=0 missed=0 overwritten=0 stalls=0"),
             (11.0, "stats v1 serial t=2.000 frames=5 missed=0 overwritten=0 stalls=0"),
             (12.0, "stats v1 serial t=3.000 frames=14 missed=1 overwritten=0 stalls=0")])
    t0 = lib.first_frame_time(p.events)
    assert t0 == 9.0  # the driver's start(): arrival of the t=1.0 line minus 1.0 s
    samples = [(t0 + k, 50 * k, 100, 2048) for k in range(5)]  # 50% CPU
    rows = lib.aggregate(p.events, samples, t0, 4)
    # row 1 is measured from zero; the last row runs to the final line
    assert [r["dca_frames"] for r in rows] == [1, 3, 2, 1]
    assert [r["dca_dropped_packets"] for r in rows] == [0, 0, 4, 0]
    assert [r["dca_dropped_packet_events"] for r in rows] == [0, 0, 1, 0]
    assert [r["dca_rx_overrun_count_cum"] for r in rows] == [0, 0, 2, 2]
    assert [r["dca_packets"] for r in rows] == [100, 300, 200, 100]
    assert [r["tlv_frames"] for r in rows] == [0, 5, 9, 0]
    assert [r["tlv_missed_frames"] for r in rows] == [0, 0, 1, 0]
    assert all(r["cpu_pct"] == 50.0 for r in rows)
    s = lib.summarize(rows, p.events)
    assert s["dca_frames_total"] == 7 == sum(r["dca_frames"] for r in rows)
    assert s["dca_dropped_packets_total"] == 4 and s["dca_packets_total"] == 700
    assert s["dca_fps_min"] == 1 and s["dca_rx_overrun_count_final"] == 2
    assert s["tlv_frames_total"] == 14 and s["tlv_missed_frames_total"] == 1
    assert s["dca_kernel_drops_final"] == 0 and s["dca_resyncs_final"] == 0  # keys absent: 0


def test_summary_reads_kernel_drops_and_resyncs():
    p = lib.Parser()
    feed(p, [(1.0, dca_line(1.0, 10, 3450) + " kernel_drops=7 ring_full=3 implausible=1 resyncs=2")])
    s = lib.summarize([{c: 0 for c in lib.CSV_COLUMNS}], p.events)
    assert s["dca_kernel_drops_final"] == 7 and s["dca_resyncs_final"] == 2


def test_first_interval_counts_reach_the_totals():
    """Frames and drops on the first stats line are in row 1 and in the totals."""
    p = lib.Parser()
    feed(p, [(5.0, dca_line(1.0, 10, 3450, 5, 2)),   # a startup drop burst, then none
             (6.0, dca_line(2.0, 20, 6900, 5, 2)),
             (6.3, dca_line(2.3, 23, 7935, 5, 2))])  # final line
    t0 = lib.first_frame_time(p.events)
    assert t0 == 4.0
    rows = lib.aggregate(p.events, [], t0, 2)
    assert [r["dca_frames"] for r in rows] == [10, 13]
    assert [r["dca_dropped_packets"] for r in rows] == [5, 0]
    s = lib.summarize(rows, p.events)
    assert s["dca_dropped_packets_total"] == 5 and s["dca_dropped_packet_events_total"] == 2
    assert s["dca_frames_total"] == 23  # = the frames in adc_data.bin


def test_slow_start_anchors_on_the_first_second_with_a_frame():
    p = lib.Parser()
    feed(p, [(1.0, dca_line(1.0, 0, 0)), (2.0, dca_line(2.0, 0, 0)),
             (3.0, dca_line(3.0, 8, 2760)), (4.0, dca_line(4.0, 18, 6210))])
    assert lib.first_frame_time(p.events) == 2.0
    rows = lib.aggregate(p.events, [], 2.0, 2)
    assert [r["dca_frames"] for r in rows] == [8, 10]


def test_parse_proc_stat_with_spaces_in_comm():
    fields = ["S"] + ["0"] * 10 + ["30", "12"] + ["0"] * 8 + ["999"] + ["0"] * 5
    text = "1234 (my (odd) prog) " + " ".join(fields)
    assert lib.parse_proc_stat(text) == (42, 999)


def test_expected_from_stress_cfg():
    e = lib.expected_from_radar_cfg(STRESS_CFG.read_text())
    assert e["rx_antennas"] == 4 and e["adc_samples"] == 250 and e["chirps_per_frame"] == 126
    assert e["bytes_per_frame"] == 4 * 4 * 250 * 126
    assert e["expected_fps"] == 10.0


def test_expected_cascade_form_and_errors():
    cfg = "channelCfg 15 1 0 15 1\nprofileCfg 0 77 1 1 1 1 1 1 1 1 64 1\nframeCfg 0 1 2 0 64 100 1 0 0\n"
    e = lib.expected_from_radar_cfg(cfg)
    assert e["rx_antennas"] == 8 and e["frame_period_ms"] == 100.0
    with pytest.raises(ValueError):
        lib.expected_from_radar_cfg("channelCfg 15 1 0\n")


def test_check_bin_size():
    bpf = 504000
    assert lib.check_bin_size(bpf * 600, bpf, 600, True)["verdict"] == "exact"
    assert lib.check_bin_size(bpf * 600 - 4096, bpf, 600, True)["verdict"] == "short_sigint_tail"
    assert lib.check_bin_size(bpf * 600 - 4096, bpf, 600, False)["verdict"] == "MISMATCH"
    assert lib.check_bin_size(bpf * 590, bpf, 600, True)["verdict"] == "MISMATCH"


def test_names_and_no_overwrite(tmp_path):
    b = lib.result_basename("baseline pre/rework", "front radar", 2, 60, "20261005T000000Z")
    assert b == "baseline-pre-rework__front-radar__rep2__60s__20261005T000000Z"
    path = tmp_path / "a.csv"
    lib.write_csv(path, [])
    with pytest.raises(FileExistsError):
        lib.write_csv(path, [])
    lib.write_sidecar(tmp_path / "a.json", {"x": 1})
    with pytest.raises(FileExistsError):
        lib.write_sidecar(tmp_path / "a.json", {"x": 1})


def test_driver_stats_format_still_in_source():
    """Guard: the stats v1 keys the parser reads must still be printed by the driver."""
    main = (REPO / "CPSL_TI_Radar_cpp/main.cpp").read_text()
    assert '"stats v1 dca t="' in main and '"stats v1 serial t="' in main
    for key in ('" frames="', '" packets="', '" dropped="', '" drop_events="', '" overrun="',
                '" rcvbuf="', '" missed="', '" kernel_drops="', '" resyncs="'):
        assert key in main, key


FAKE_DRIVER = textwrap.dedent('''\
    #!{py}
    import signal, sys, time
    from pathlib import Path
    mode = sys.argv[1] and Path(sys.argv[1]).read_text()
    if "--stats" not in sys.argv:
        sys.exit("fake driver: bench must pass --stats")
    stop = []
    def on_int(*a):
        stop.append(1)
    signal.signal(signal.SIGINT, on_int)
    t0 = time.monotonic()
    def stats(n):
        print("stats v1 dca t=%.3f frames=%d packets=%d dropped=0 drop_events=0 late=0 duplicate=0 "
              "incomplete=0 skipped=0 overrun=0 overwritten=0 stalls=0 rcvbuf=134217728"
              % (time.monotonic() - t0, n, n * 345), flush=True)
    time.sleep(0.3)
    n = 0
    bpf = 504000
    out = open("adc_data.bin", "wb")
    next_stats = time.monotonic() + 1.0
    while not stop:
        n += 1
        out.write(b"\\0" * bpf); out.flush()
        if time.monotonic() >= next_stats:
            stats(n)
            next_stats += 1.0
        time.sleep(0.1)
    out.close()
    stats(n)  # the final line, after the stop
''')


class PreflightHost(host_setup.Host):
    """Real host, except rmem_max and getcap report a bench-ready machine."""

    def __init__(self, rmem="134217728", cap=True):
        self.rmem, self.cap = rmem, cap

    def read(self, path):
        return self.rmem + "\n" if path == "/proc/sys/net/core/rmem_max" else super().read(path)

    def run(self, argv):
        if argv[0] == "getcap":
            return 0, f"{argv[1]} cap_sys_nice=ep\n" if self.cap else ""
        return super().run(argv)

    def rtprio_limit(self):
        return 0


def test_end_to_end_with_fake_driver(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_run, "PREFLIGHT_HOST", PreflightHost())
    drv = tmp_path / "fake_driver.py"
    drv.write_text(FAKE_DRIVER.format(py=sys.executable))
    drv.chmod(drv.stat().st_mode | stat.S_IXUSR)
    cfg = json.loads(STRESS_JSON.read_text())
    cfg["radar_cfg"] = str(STRESS_CFG)
    cfg["runtime"]["log_level"] = "info"  # stats come from --stats, not debug output
    cfg_path = tmp_path / "fake_system.json"
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(bench_run, "RUNS", tmp_path / "runs")
    out = tmp_path / "out"
    (tmp_path / "CMakeCache.txt").write_text(
        "//x\nCMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG\n")
    rc = bench_run.main([str(cfg_path), "--seconds", "3", "--rep", "1", "--tag", "unit",
                         "--driver", str(drv), "--out-dir", str(out), "--start-timeout", "10"])
    assert rc == 0
    csvs = list(out.glob("*.csv"))
    sides = list(out.glob("*.json"))
    assert len(csvs) == 1 and len(sides) == 1 and csvs[0].stem == sides[0].stem
    assert csvs[0].name.startswith("unit__fake_system__rep1__3s__")
    lines = csvs[0].read_text().splitlines()
    assert lines[0] == ",".join(lib.CSV_COLUMNS) and len(lines) == 4
    side = json.loads(sides[0].read_text())
    r = side["result"]
    assert r["status"] == "ok" and r["granted_so_rcvbuf_bytes"] == 134217728
    assert 20 <= r["summary"]["dca_frames_total"] <= 45  # ~10 Hz for 3 s, plus start and stop
    assert r["summary"]["dca_frames_total"] == r["dca_received_frames_cum_at_exit"]
    assert 0 <= r["startup_s"] <= 1.0  # launch -> the fake's start (its t=0)
    chk = r["bin_size_check"]
    assert chk["verdict"] == "exact"  # fake driver flushes; real-driver SIGINT tail is classified separately
    for k in ("commit", "system_config", "board", "host", "nic", "expected"):
        assert k in side
    assert side["system_config_schema_version"] == 2
    assert side["save_adc_frames"] is True and side["output_dir"] is None
    assert r["output_files_dir"] == r["bin_size_check"]["file"].rsplit("/", 1)[0]  # per-run dir
    assert side["build"]["CMAKE_BUILD_TYPE"] == "Release"
    assert side["build"]["CMAKE_CXX_FLAGS_RELEASE"] == "-O3 -DNDEBUG"
    assert side["radar_cfg_numFrames"] == 30  # the shipped stress cfg, only a warning
    assert side["board"] == "IWR1843" and "kernel" in side["host"] and "rmem_max" in side["host"]
    assert [(c["name"], c["status"]) for c in side["preflight"]] == [
        ("sysctl", "OK"), ("realtime", "OK"), ("build-type", "OK")]
    assert side["preflight_overridden"] == []


def test_nonzero_driver_exit_code_is_surfaced(tmp_path, monkeypatch):
    monkeypatch.setattr(bench_run, "PREFLIGHT_HOST", PreflightHost())
    drv = tmp_path / "fake_driver.py"
    drv.write_text(FAKE_DRIVER.format(py=sys.executable) + "sys.exit(1)\n")
    drv.chmod(drv.stat().st_mode | stat.S_IXUSR)
    cfg = json.loads(STRESS_JSON.read_text())
    cfg["radar_cfg"] = str(STRESS_CFG)
    cfg_path = tmp_path / "fake_system.json"
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(bench_run, "RUNS", tmp_path / "runs")
    out = tmp_path / "out"
    (tmp_path / "CMakeCache.txt").write_text(
        "//x\nCMAKE_BUILD_TYPE:STRING=Release\nCMAKE_CXX_FLAGS_RELEASE:STRING=-O3 -DNDEBUG\n")
    rc = bench_run.main([str(cfg_path), "--seconds", "3", "--rep", "1", "--tag", "unit",
                         "--driver", str(drv), "--out-dir", str(out), "--start-timeout", "10"])
    assert rc == 1
    r = json.loads(next(out.glob("*.json")).read_text())["result"]
    assert r["status"] == "exit=1" and r["stop"]["exit_code"] == 1
    assert "driver exit code 1" in r["note"]


def test_preflight_refuses_with_fix_commands(tmp_path, monkeypatch):
    drv = tmp_path / "drv"
    drv.write_text("#!/bin/sh\n")
    drv.chmod(0o755)
    (tmp_path / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=Release\n")
    monkeypatch.setattr(bench_run, "PREFLIGHT_HOST", PreflightHost(rmem="212992", cap=False))
    with pytest.raises(SystemExit) as e:
        bench_run.main([str(STRESS_JSON), "--driver", str(drv)])
    msg = str(e.value)
    assert "sudo sysctl -w net.core.rmem_max=134217728" in msg
    assert f"sudo setcap cap_sys_nice+ep {drv}" in msg and "--allow-missing-prereq" in msg
    assert "build-type" not in msg


def test_rejects_v1_config_with_migration_hint(tmp_path):
    v1 = REPO / "tests/fixtures/v1_configs/front_radar_IWR1843_stress_test.json"
    with pytest.raises(SystemExit) as e:
        bench_run.main([str(v1)])
    assert "migrate_config_v1_to_v2.py" in str(e.value)


def test_output_dir_resolves_relative_to_config(tmp_path):
    cfg_path = tmp_path / "sys" / "c.json"
    run_dir = tmp_path / "run"
    assert bench_run.output_dir(cfg_path, {"output": {}}, run_dir) == run_dir
    assert bench_run.output_dir(cfg_path, {"output": {"dir": "../out/a"}}, run_dir) == tmp_path / "out/a"
    assert bench_run.output_dir(cfg_path, {"output": {"dir": "/abs/x"}}, run_dir) == Path("/abs/x")


def test_end_to_end_bin_in_output_dir(tmp_path, monkeypatch):
    """With output.dir set, the .bin check reads the file from there."""
    monkeypatch.setattr(bench_run, "PREFLIGHT_HOST", PreflightHost())
    drv = tmp_path / "fake_driver.py"
    # the fake driver writes adc_data.bin into its cwd; point output.dir at the
    # per-run dir through an absolute path the test controls instead
    drv.write_text(FAKE_DRIVER.format(py=sys.executable).replace(
        'open("adc_data.bin", "wb")', 'open(__import__("os").environ["FAKE_OUT"] + "/adc_data.bin", "wb")'))
    drv.chmod(drv.stat().st_mode | stat.S_IXUSR)
    out_files = tmp_path / "captures"
    monkeypatch.setenv("FAKE_OUT", str(out_files))
    cfg = json.loads(STRESS_JSON.read_text())
    cfg["radar_cfg"] = str(STRESS_CFG)
    cfg["output"]["dir"] = "captures"  # relative to the config file
    cfg_path = tmp_path / "fake_system.json"
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setattr(bench_run, "RUNS", tmp_path / "runs")
    (tmp_path / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=Release\n")
    rc = bench_run.main([str(cfg_path), "--seconds", "2", "--tag", "unit", "--driver", str(drv),
                         "--out-dir", str(tmp_path / "out"), "--start-timeout", "10"])
    assert rc == 0
    side = json.loads(next((tmp_path / "out").glob("*.json")).read_text())
    assert side["output_dir"] == "captures"
    assert side["result"]["output_files_dir"] == str(out_files)
    assert side["result"]["bin_size_check"]["verdict"] == "exact"


def test_cmake_cache_and_numframes():
    c = lib.parse_cmake_cache("// c\nCMAKE_BUILD_TYPE:STRING=Debug\nCMAKE_CXX_FLAGS:STRING=\nOTHER:BOOL=ON\n")
    assert c == {"CMAKE_BUILD_TYPE": "Debug", "CMAKE_CXX_FLAGS": ""}
    assert lib.frame_cfg_num_frames("frameCfg 0 1 63 30 100 1 0\n") == 30
    assert lib.frame_cfg_num_frames("sensorStart\n") is None


def test_refuses_non_release(tmp_path):
    drv = tmp_path / "drv"
    drv.write_text("#!/bin/sh\n")
    drv.chmod(0o755)
    (tmp_path / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=\n")
    with pytest.raises(SystemExit) as e:
        bench_run.main([str(STRESS_JSON), "--driver", str(drv)])
    assert "Release" in str(e.value)


def test_baseline_configs_run_forever_and_match_stress():
    base = REPO / "CPSL_TI_Radar_cpp/config"
    new_cfg = (base / "radar/nav_configs/1843_stress_test_baseline_numframes0.cfg").read_text()
    assert lib.frame_cfg_num_frames(new_cfg) == 0
    assert lib.frame_cfg_num_frames(STRESS_CFG.read_text()) == 30  # shipped file untouched
    assert lib.expected_from_radar_cfg(new_cfg) == lib.expected_from_radar_cfg(STRESS_CFG.read_text())
    sysj = json.loads((base / "system/front_radar_IWR1843_stress_test_baseline.json").read_text())
    assert sysj["schema_version"] == 2 and sysj["board"] == "IWR1843"
    assert sysj["radar_cfg"].endswith("1843_stress_test_baseline_numframes0.cfg")
    # same work as the pre-rework baseline runs: debug stats, both output files, cwd output
    assert sysj["runtime"]["log_level"] == "debug"
    assert sysj["output"] == {"save_adc_frames": True, "save_raw_lvds": True}
    demo = base / "radar/DCA1000/IWR1843_configs/IWR1843_demo.cfg"
    assert lib.frame_cfg_num_frames(demo.read_text()) == 0


# ---- iq_check ----
import struct as _struct  # noqa: E402
import math as _math  # noqa: E402
import iq_check  # noqa: E402


def _write_tone_bin(path, bin_k, swapped, chirps=8):
    """Synthetic frame in the .bin layout: x[n] = exp(+j 2 pi k n / N) (+ small phase per chirp)."""
    cfg = lib.expected_from_radar_cfg(STRESS_CFG.read_text())
    n, rx = cfg["adc_samples"], cfg["rx_antennas"]
    words = []
    for c in range(cfg["chirps_per_frame"]):
        for _ in range(rx):
            for i in range(n):
                ph = 2 * _math.pi * bin_k * i / n + 0.3 * c
                re, im = 2000 * _math.cos(ph), 2000 * _math.sin(ph)
                if swapped:  # file holds what a wrong converter would have produced
                    re, im = im, re
                words += [int(round(re)), int(round(im))]
    path.write_bytes(_struct.pack(f"<{len(words)}h", *words))


@pytest.mark.parametrize("swapped,expect", [(False, "current order OK"), (True, "SWAPPED")])
def test_iq_check_verdicts(tmp_path, swapped, expect):
    res = iq_check.cfg_params(STRESS_CFG.read_text())["range_resolution_m"]
    assert 0.25 < res < 0.28
    dist = 11 * res
    f = tmp_path / "adc_data.bin"
    _write_tone_bin(f, 11, swapped)
    r = iq_check.run(f, STRESS_CFG.read_text(), dist)
    assert r["verdict"].startswith(expect), r
    assert {r["peak_current"], r["peak_swapped"]} == {11, 250 - 11}


def test_iq_check_inconclusive_and_short_file(tmp_path):
    f = tmp_path / "adc_data.bin"
    _write_tone_bin(f, 40, False)
    assert iq_check.run(f, STRESS_CFG.read_text(), 11 * 0.2638)["verdict"] == "inconclusive"
    f.write_bytes(b"\0" * 100)
    with pytest.raises(SystemExit):
        iq_check.run(f, STRESS_CFG.read_text(), 3.0)
