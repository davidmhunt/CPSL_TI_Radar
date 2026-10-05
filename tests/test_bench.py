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


def dca_block(n, pkts, dropped, events, overrun):
    return [f"frame: {n}", f"\tpackets: {pkts}", f"\tdata bytes: {pkts * 1462}",
            f"\tdropped packets: {dropped}", f"\tdropped packet events: {events}",
            f"\trx_overrun_count: {overrun}"]


def feed(parser, items):
    for t, line in items:
        parser.feed(t, line)
    parser.finish()


def test_parser_dca_serial_and_misc():
    p = lib.Parser()
    feed(p, [(0.0, "[DCA1000] SO_RCVBUF granted: 134217728 bytes"),
             *[(1.0, l) for l in dca_block(1, 345, 0, 0, 0)],
             (1.1, "frame: 7"), (1.1, "\tversion: 33620994"), (1.1, "\tDetected Objects: 3"),
             (1.1, "TLV frame 7: 3 detected points (first: x=1 y=2 z=0 v=0)"),
             (1.2, "SerialStreamer: frame number jumped from 7 to 10 (2 missed in total)"),
             (1.3, "runner timed out waiting for next adc_cube")])
    kinds = [e["kind"] for e in p.events]
    assert kinds == ["dca_frame", "serial_header", "tlv_frame", "tlv_missed"]
    assert p.granted_rcvbuf == 134217728
    assert p.events[0]["packets"] == 345 and p.events[3]["cum"] == 2
    assert p.warnings == ["runner timed out waiting for next adc_cube"]


def test_aggregate_deltas_and_cpu():
    p = lib.Parser()
    items = []
    # 3 frames in second 1, 2 in second 2 (with 4 dropped in 1 event), none in second 3
    for t, n, pk, dr, ev, ov in [(10.1, 1, 100, 0, 0, 0), (10.4, 2, 200, 0, 0, 0),
                                 (10.8, 3, 300, 0, 0, 0), (11.2, 4, 400, 4, 1, 0),
                                 (11.7, 5, 500, 4, 1, 2)]:
        items += [(t, l) for l in dca_block(n, pk, dr, ev, ov)]
    feed(p, items)
    t0 = lib.first_frame_time(p.events)
    assert t0 == 10.1
    samples = [(t0 + k, 50 * k, 100, 2048) for k in range(4)]  # 50% CPU
    rows = lib.aggregate(p.events, samples, t0, 3)
    assert [r["dca_frames"] for r in rows] == [3, 2, 0]
    assert [r["dca_dropped_packets"] for r in rows] == [0, 4, 0]
    assert [r["dca_dropped_packet_events"] for r in rows] == [0, 1, 0]
    assert [r["dca_rx_overrun_count_cum"] for r in rows] == [0, 2, 2]
    assert [r["dca_packets"] for r in rows] == [300, 200, 0]
    assert all(r["cpu_pct"] == 50.0 for r in rows)
    s = lib.summarize(rows)
    assert s["dca_frames_total"] == 5 and s["dca_dropped_packets_total"] == 4
    assert s["dca_fps_min"] == 0 and s["dca_rx_overrun_count_final"] == 2


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


def test_driver_output_formats_still_in_source():
    """Guard: the strings the parser keys on must still be printed by the driver."""
    src = REPO / "CPSL_TI_Radar_cpp"
    sock = (src / "src/DCA1000/DCA1000Socket.cpp").read_text()
    hand = (src / "src/DCA1000/DCA1000Handler.cpp").read_text()
    ser = (src / "src/SerialStreamer/SerialStreamer.cpp").read_text()
    main = (src / "main.cpp").read_text()
    assert "SO_RCVBUF granted: " in sock
    for key in ('"frame: "', '"\\tpackets: "', '"\\tdropped packets: "',
                '"\\tdropped packet events: "', '"\\trx_overrun_count: "'):
        assert key in hand, key
    assert '"\\tversion: "' in ser and "frame number jumped from " in ser
    assert '"TLV frame "' in main


FAKE_DRIVER = textwrap.dedent('''\
    #!{py}
    import signal, sys, time
    from pathlib import Path
    mode = sys.argv[1] and Path(sys.argv[1]).read_text()
    stop = []
    def on_int(*a):
        stop.append(1)
    signal.signal(signal.SIGINT, on_int)
    print("[DCA1000] SO_RCVBUF granted: 134217728 bytes", flush=True)
    time.sleep(0.3)
    n = 0
    bpf = 504000
    out = open("adc_data.bin", "wb")
    while not stop:
        n += 1
        out.write(b"\\0" * bpf); out.flush()
        print("frame: %d\\n\\tpackets: %d\\n\\tdata bytes: 0\\n\\tdropped packets: 0\\n"
              "\\tdropped packet events: 0\\n\\trx_overrun_count: 0" % (n, n * 345), flush=True)
        time.sleep(0.1)
    out.close()
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
    assert 20 <= r["summary"]["dca_frames_total"] <= 33  # ~10 Hz for 3 s
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


def test_requires_debug_log_level(tmp_path):
    cfg = json.loads(STRESS_JSON.read_text())
    cfg["runtime"]["log_level"] = "info"
    p = tmp_path / "quiet.json"
    p.write_text(json.dumps(cfg))
    with pytest.raises(SystemExit) as e:
        bench_run.main([str(p)])
    assert "log_level" in str(e.value)


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
