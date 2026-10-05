# Bench validation (runbook)

Use this to check that a board streams correctly with the current driver build: no dropped packets, the right frame rate, a clean exit. The IWR1843 with a DCA1000 is the worked example. The pass thresholds come from the core-04 baseline in [`../RESULTS.md`](../RESULTS.md).

Run every command from the repository root. Only one person at a time may hold the board and the DCA1000.

## 1. Prerequisites

1. Build the driver (Release; the harness refuses other builds) and apply the host settings by following [`rebuild_driver.md`](rebuild_driver.md). Repeat after every rebuild.
2. Check the host with `uv run tools/setup/host_setup.py --nic <dca-nic>`: nothing may show MISSING. It needs the DCA1000 NIC at `192.168.33.30/24` and your user in `dialout`.
3. About 600 MB of free disk per 60 s DCA run (raw captures in `tools/bench/runs/`, git-ignored).

## 2. Hardware setup (IWR1843 + DCA1000)

1. Power the board off. Set the S1 switch to **functional mode**: SOP2 = 0, SOP1 = 0, SOP0 = 1 (SOP mode 4); flashing mode is 101. The board reads the switch only at power-up. See [`readme_images/IWR1843_SOP_nodes.png`](../../readme_images/IWR1843_SOP_nodes.png), which labels the ON side of S1.
2. Connect the board by USB. `ls /dev/ttyACM*` should show `/dev/ttyACM0` (CLI) and `/dev/ttyACM1` (data), the ports in the config below; otherwise edit `cli.port` and `serial_stream.port`.
3. For raw ADC, connect the DCA1000 to the LVDS connector and by Ethernet to the host NIC, then power both. `uv run tools/setup/host_setup.py --nic <dca-nic> --ping` pings `192.168.33.180` (report only). A working DCA1000 may not answer ping (the IWR1843 bench's does not), so the real check is the first run in section 5.
4. Power-cycle the board before a run if the firmware was just flashed or the last run crashed.

## 3. Firmware

The board must run the SDK 3.6 mmWave demo (IWR1843) or the matching image for your board. For flashing and building see [`../firmware.md`](../firmware.md) and `firmware_dev/projects/README.md`. For the cascade, `planning/CASCADE_HARDWARE_SETUP.md` Steps 2 to 4.

## 4. Choose a config

Pick a system config from the table in section 9 or copy one. The worked example, `CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json`, streams 4 RX x 250 samples x 126 chirps at 10 Hz (504000 B per frame) through the DCA1000.

Copy the example system config and set `runtime.log_level` to `"debug"` (the harness reads frame counts from the debug output and rejects the config otherwise) and, for DCA runs, `output.save_adc_frames` to `true` (otherwise there is no `adc_data.bin` size check) before running the harness. The radar `.cfg` needs `frameCfg ... numFrames 0`. Check it without hardware:

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json --validate
```

It must print `OK:` and exit 0. The `frame:` and `bytes/frame:` lines are the values the harness compares against. On the IWR1843 `calibData` is listed as skipped: the flashed firmware rejects it, which is harmless.

## 5. Run the harness

```bash
uv run tools/bench/bench_run.py CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json \
    --seconds 60 --rep 1 --tag validation_iwr1843_dca_release --out-dir docs/results/validation
```

The harness starts the driver, samples CPU once per second, sends SIGINT after `--seconds`, and prints a JSON summary. Use `--rep 1..3` for repeats and a new `--tag` per board or build. Files are never overwritten; the full driver log is `tools/bench/runs/<basename>/driver_stdout.log`. A run that used `--allow-non-release` or `--allow-missing-prereq` is not a valid validation. For other options (`--stop-mode natural`) see `--help`.

## 6. Read the results

Each run writes two files to `--out-dir`, with the same basename `<tag>__<config>__rep<k>__<N>s__<UTC>`:

- `.csv`, one row per second: `dca_frames`, `dca_packets`, `dca_dropped_packets`, `dca_dropped_packet_events`, `dca_rx_overrun_count_cum`, `serial_headers`, `tlv_frames`, `tlv_missed_frames`, `cpu_pct`, `rss_kb`.
- `.json` sidecar, the provenance and verdict: driver sha256, build flags, host and NIC settings, the config used, `expected` (frame size and rate), and `result` (`status`, `stop.exit_code`, `summary`, `bin_size_check`).

Quick read:

```bash
jq '{status: .result.status, exit: .result.stop.exit_code, bin: .result.bin_size_check.verdict, s: .result.summary}' \
    docs/results/validation/<basename>.json
```

## 7. Pass or fail

Thresholds come from the core-04 IWR1843 baseline (3 reps of 60 s, `docs/results/baseline/`, summarized in `../RESULTS.md`), rounded by the Author, except CPU (core-06 runs). Every row must pass. Rows marked (guide) are loose limits from only three reps, not guarantees.

| Check | DCA1000 raw-ADC | Serial TLV | Baseline value |
|---|---|---|---|
| `result.status` | `ok` | `ok` | `ok` |
| Driver exit code (`stop.exit_code`; nonzero marks the run failed) | 0 | 0 | 0 |
| Seconds recorded | equals `--seconds` | same | 60 |
| Frames per second mean (`dca_fps_mean` / `tlv_fps_mean`) | 10.0 +/- 0.1 (`expected.expected_fps`) | same | 10.0, 10.0, 10.017 / 9.983, 10.0, 10.0 |
| Per-second min / max (guide) | 9 to 11 | 9 to 10 | 9 / 11 (DCA), 9 / 10 (TLV) |
| Dropped packets (`dca_dropped_packets_total`) | 0 | n/a | 0 |
| Rx overruns (`dca_rx_overrun_count_final`) | 0 | n/a | 0 |
| Missed TLV frames (`tlv_missed_frames_total`) | n/a | 1 or fewer | 1, 0, 0 |
| `adc_data.bin` size (`bin_size_check.verdict`) | `exact` (SIGINT or natural stop; the 896 B `short_sigint_tail` was fixed in core-11) | n/a | 896 B short x3 (pre-core-11); `exact` x3 after |
| CPU % mean (guide) | below 20 (see note) | below 3 | 9.1 to 10.5 (core-04, pre-rework driver), 16.1 to 16.3 (v2 driver, binary sha256 `3ecd94cd…`, with `cap_sys_nice`; core-06) / 0.5 to 0.6 |

For other frame rates, scale the fps rows by `expected_fps` from the sidecar; the baseline covers 10 Hz only. The 20 % CPU guide comes from the core-06 runs of the reworked driver (16.1 to 16.3 % over 4 reps); the core-04 baseline used the pre-rework driver (9 to 10 %). The cause of the difference is not isolated, since the driver code and the real-time priority (`cap_sys_nice`) both changed; an A/B run with and without `cap_sys_nice` would settle it.

A DCA run that is `INCOMPLETE`, shows any drop or overrun, or exits nonzero is a fail: record it and see section 10.

## 8. Record results

1. Keep the CSV and JSON in `docs/results/validation/` (or `baseline/` for a new reference) and commit them; `tools/bench/runs/` is not tracked.
2. Add a row to `docs/RESULTS.md` under a heading for the board, following the baseline tables: fps mean/min/max, dropped packets, `rx_overrun_count`, CPU, the sidecar basename, and the driver sha256 and commit. Record failures and caveats too.
3. Delete the large `adc_data.bin` and `LVDS_Raw_0.bin` in `tools/bench/runs/<basename>/` when done.

## 9. Per-board differences

| | IWR1843 | IWR1443 (untested) | IWR6843 (untested) | AWR2243 cascade (untested) |
|---|---|---|---|---|
| Board descriptor | `config/boards/IWR1843.json` | `IWR1443.json` | `IWR6843.json` | `AWR2243_CASCADE.json` |
| LVDS lanes | 2, `q_first` | 4, `lane_per_rx`, `i_first` | 2, `q_first` | none (`lvds.supported: false`) |
| Example system config | `front_radar_IWR1843_stress_test_baseline.json` (DCA), `radar_0_IWR1843_demo.json` (serial) | `radar_1.json` | `radar_0_IWR6843_ods_dca_RadVel.json` | `radar_0_AWR2243_cascade_serial.json` |
| DCA1000 needed | yes for raw ADC; no for serial | yes (serial TLV rejected) | yes for raw ADC; no for serial | no (serial only) |
| One cfg per boot | no | no | no | **yes**: power-cycle (12 V off and on) before every run |
| Serial baud (data) | 921600 | n/a | 921600 | 3125000 |
| Known limits | `calibData` rejected by the flashed firmware; I/Q order not confirmed | serial TLV (`sdk2`) unconfirmed; bench-unproven; `radar_1.json`'s cfg has no `lvdsStreamCfg` | not yet run on the bench | raw ADC unsupported (D4); never run through `bench_run.py` |

Config paths are under `CPSL_TI_Radar_cpp/config/system/`; ports in them are the lab's. Only the IWR1843 has baseline numbers: for other boards treat the pass table as a guide and record the first good run as that board's reference.

Cascade (untested with the harness): use the by-id ports and the J6 jumper (bottom two pins flash, top two run) from `planning/CASCADE_HARDWARE_SETUP.md`. Its config ships with `log_level: "info"`; see section 4. Expect 20 Hz (50 ms period) and no missed TLV frames.

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `bench: refusing to run, host preflight failed` | Run `uv run tools/setup/host_setup.py --nic <dca-nic> --apply`, then retry. A rebuild removes `cap_sys_nice`. |
| `no frame received before start timeout` (`FAILED`, exit 2) | Check board mode (SOP jumpers), USB ports, DCA1000 power and cable, and the ping in section 2. For the cascade, power-cycle first. Read `driver_stdout.log`. |
| `Runner: sensorStop was not acknowledged with 'Done'` in `driver_warnings_first` | Seen at the end of every healthy IWR1843 SIGINT run: likely the 100 ms command timeout equals the 100 ms frame period, so the board's `Done` arrives too late (tracked for core-13). Harmless if `status` is `ok` and the `.bin` is `exact`. |
| `not every config command was acknowledged` | Harmless if only `calibData` is rejected. Otherwise the cfg has a command the firmware does not know. |
| Dropped packets or overruns | `rmem_max` below 128 MB, no `cap_sys_nice`, or a slow NIC. Re-run `host_setup.py`; confirm `granted_so_rcvbuf_bytes` in the sidecar is 134217728. |
| Run ends early (`INCOMPLETE`) | The cfg has `numFrames` above 0, or the board lost power or USB. |
| Non-zero exit after a USB unplug | The driver now exits 1 with `sensorStop could not be sent` (core-11) instead of crashing. Reconnect, power-cycle, rerun. |
