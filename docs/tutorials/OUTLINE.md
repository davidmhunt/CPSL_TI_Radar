# Tutorials outline

Skeleton for core-05. These are planned lessons, one line each. "Depends on"
names the design decision or follow-up directive the lesson waits for (see
[`../design/driver_v2_design.md`](../design/driver_v2_design.md) §7–8).
This file has no prose yet.

## A. Using the driver

| # | File (planned) | Lesson | Depends on |
|---|----------------|--------|------------|
| A1 | `01_build_and_test.md` | Build the driver and run the unit tests (`cmake`, `ctest`) | core-08 (CMake), core-10 (C++17 if D2), core-12 (default build type) |
| A2 | `02_host_setup.md` | Host setup: `rmem_max`, static IP for the DCA1000, `dialout`, `cap_sys_nice` | core-15 (affinity/priority settings) |

Already written: `rebuild_driver.md`, a one-page repeatable runbook (build, `ctest`, `--validate`, `host_setup.py --apply`). A1 and A2 should link to it rather than repeat its commands.
| A3 | `03_first_run.md` | First run from a system config, plus `--validate` without hardware | core-10 (schema v2, `--validate`) |
| A4 | `04_serial_vs_dca1000.md` | Serial TLV point cloud vs DCA1000 raw ADC: when to use which, and the config switches | core-10, core-16 (serial framing) |
| A5 | `05_reading_adc_data.md` | Read `adc_data.bin` with the `utilities/` notebooks | core-14 (output dir, unchanged layout), D5 (frame layout) |
| A6 | `06_multiple_radars.md` | Run several radars: one process per radar, ports, output dirs, IPs | core-10 (`output.dir`), core-13 (API) |
| A7 | `07_troubleshooting.md` | Troubleshooting: no `Done`, timeouts, drops/overruns, cascade power-cycle | core-13 (Status messages), core-15 (drop counters) |
| A8 | `bench_validation.md` | Bench-validate a board with the core-04 harness (written by **core-06**, linked, not duplicated) | core-04, core-06 |

## B. Extending the driver

| # | File (planned) | Lesson | Depends on |
|---|----------------|--------|------------|
| B1 | `10_code_map.md` | Repo and library map: `Radar`, transports, assembler, converter, UART parser | core-13 (API), core-14 |
| B2 | `11_add_a_board.md` | Add or tune a board with a descriptor in `config/boards/` (no rebuild) | core-09, core-10 |
| B3 | `12_add_a_tlv_type.md` | Add a TLV type to a UART dialect, with a test | core-16 (`parse_uart_frame` seam) |
| B4 | `13_consume_frames.md` | Write a frame consumer with `next_adc_frame` / `next_point_cloud` | core-13 (API), D5 |
| B5 | `14_write_a_test.md` | Write and run a ctest test (fake transports, replay data, `asan-ubsan` preset) | core-11, core-13 |
| B6 | `15_measure_performance.md` | Measure performance: `bench_pipeline` replay, then the core-04 harness against `docs/RESULTS.md` | core-04, core-09 (`bench_pipeline`) |
