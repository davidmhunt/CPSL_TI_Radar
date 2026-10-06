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
| A3 | `03_first_run.md` | First run from a system config, plus `--validate` without hardware | core-10 (schema v2, `--validate`) |
| A4 | `04_serial_vs_dca1000.md` | Serial TLV point cloud vs DCA1000 raw ADC: when to use which, and the config switches | core-10, core-16 (serial framing) |
| A5 | `05_reading_adc_data.md` | Read `adc_data.bin` with the `utilities/` notebooks | **Unblocked**: core-10 (`output.dir`), D5 (layout kept), core-14 (file layout documented in `ARCHITECTURE.md` "Output files") |
| A6 | `06_multiple_radars.md` | Run several radars: one process per radar, ports, output dirs, IPs | **Unblocked**: core-10 (`output.dir`), core-13 (API) |
| A7 | `07_troubleshooting.md` | Troubleshooting: no `Done`, timeouts, drops/overruns, cascade power-cycle | **Unblocked** for Status messages (core-13); the drop-counter part waits on core-15 |
| A8 | `bench_validation.md` | Bench-validate a board with the core-04 harness (written by **core-06**, linked, not duplicated). Proven on the IWR1843 (core-06) | core-04, core-06 |

Already written: `bench_validation.md` (A8), `rebuild_driver.md`, a one-page repeatable runbook (build, `ctest`, `--validate`, `host_setup.py --apply`). A1 and A2 should link to it rather than repeat its commands.

## B. Extending the driver

| # | File (planned) | Lesson | Depends on |
|---|----------------|--------|------------|
| B1 | `10_code_map.md` | Repo and library map: `Radar`, transports, assembler, converter, frame pool and queue, UART parser | **Unblocked**: core-13 (API), core-14 (frame pool, queue, converter) |
| B2 | `11_add_a_board.md` | Add or tune a board with a descriptor in `config/boards/` (no rebuild) | core-09, core-10 |
| B3 | `12_add_a_tlv_type.md` | Add a TLV type to a UART dialect, with a test | core-16 (`parse_uart_frame` seam) |
| B4 | `13_consume_frames.md` | Write a frame consumer with `next_adc_frame` / `next_point_cloud` | **Unblocked**: core-13 (API), D5 |
| B5 | `14_write_a_test.md` | Write and run a ctest test (fake transports, replay data, `asan-ubsan` preset) | **Unblocked**: core-11, core-13 (`tests/fake_transports.hpp`, `ReplayPacketSource`) |
| B6 | `15_measure_performance.md` | Measure performance: `bench_pipeline` replay and the two-build perf gate (`tools/bench/pipeline_gate.py`), then the core-04 harness against `docs/RESULTS.md` | core-04, core-09 (`bench_pipeline`), core-14 (gate) |
