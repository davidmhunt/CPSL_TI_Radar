# Bench validation (runbook)

Use this to check that a board streams correctly with the current driver build: no dropped packets, the right frame rate, a clean exit. The IWR1843 with a DCA1000 is the worked example. The pass thresholds come from the core-04 baseline in [`../RESULTS.md`](../RESULTS.md). One 60 s run takes about 2 minutes once the board is wired.

Run every command from the repository root. The driver runs against real hardware, so only one person at a time may hold the board and the DCA1000.

## 1. Prerequisites

1. Build the driver, run `--validate` and apply the host settings by following [`rebuild_driver.md`](rebuild_driver.md). Do this after every rebuild: `cap_sys_nice` is lost each time.
2. The host needs `rmem_max` of at least 128 MB, the DCA1000 NIC at `192.168.33.30/24`, and your user in `dialout`. Check with `uv run tools/setup/host_setup.py --nic <dca-nic>`; it must show nothing MISSING. The harness repeats the `rmem_max` and `cap_sys_nice` checks and refuses to run without them.
3. `CPSL_TI_Radar_cpp/build` must be a Release build. The harness refuses anything else.
4. About 600 MB of disk per 60 s DCA run for this config (`adc_data.bin` and `LVDS_Raw_0.bin`, 300 MB each). Raw captures land in `tools/bench/runs/` (git-ignored).

## 2. Hardware setup (IWR1843 + DCA1000)

1. Power the board off. Set the SOP jumpers to **functional mode** using [`readme_images/IWR1843_SOP_nodes.png`](../../readme_images/IWR1843_SOP_nodes.png). The board reads them only at power-up. Flashing mode is a different setting of the same jumpers.
2. Connect the board to the host by USB. Two ports appear: `ls /dev/ttyACM*` shows `/dev/ttyACM0` (CLI) and `/dev/ttyACM1` (data), the paths in the config below. Other port names mean you must edit `cli.port` in the config (see section 4).
3. For raw ADC, connect the DCA1000 to the board's LVDS connector and by Ethernet to the host NIC, then power both. The DCA1000 answers at `192.168.33.180`; `uv run tools/setup/host_setup.py --nic <dca-nic> --ping` checks it.
4. Power-cycle the board before every run if the firmware was just flashed or the last run crashed.

## 3. Firmware

The board must run the SDK 3.6 mmWave demo (IWR1843) or the matching image for your board. Flashing and building are not covered here: see [`../firmware.md`](../firmware.md) and `firmware_dev/projects/README.md`. For the cascade, `planning/CASCADE_HARDWARE_SETUP.md` Steps 2 to 4.

## 4. Choose a config

A system config (schema v2) names the board, the radar `.cfg`, the ports and the data path. Pick one from the table in section 9, or copy one and edit it. The worked example is
`CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json`, which streams 4 RX x 250 samples x 126 chirps at 10 Hz (504000 B per frame) through the DCA1000, with `numFrames 0` so the radar runs until stopped.

Requirements for a bench config:

- `runtime.log_level` must be `"debug"`. The harness reads frame counts from the driver's debug output and rejects the config otherwise.
- The radar `.cfg` should have `frameCfg ... numFrames 0`. Otherwise the radar stops early and the harness warns.
- Check it without hardware first:

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json --validate
```

It must print `OK:` and exit 0. Read the `frame:` and `bytes/frame:` lines; they are the expected values the harness compares against. On the IWR1843, `--validate` lists `calibData` as skipped; the flashed firmware rejects it, which is known and harmless.

## 5. Run the harness

```bash
uv run tools/bench/bench_run.py CPSL_TI_Radar_cpp/config/system/front_radar_IWR1843_stress_test_baseline.json \
    --seconds 60 --rep 1 --tag validation_iwr1843_dca_release --out-dir docs/results/validation
```

- The harness starts the driver, samples CPU once per second, sends SIGINT after `--seconds`, and prints a JSON summary. Use `--rep 1..3` for three repeats, and a new `--tag` for a different board or build.
- `--stop-mode natural` waits for the driver to exit on its own (pull the DCA1000 Ethernet cable to end a capture); use it to check the `.bin` flush, see `--help`.
- `--allow-non-release` and `--allow-missing-prereq` override the preflight. A run that used either is not a valid validation; the sidecar records the override.
- Output files are never overwritten. `tools/bench/runs/<basename>/driver_stdout.log` is the full driver log.

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

Thresholds are the core-04 IWR1843 baseline (3 reps of 60 s each, `docs/results/baseline/`), rounded. Every row must pass.

| Check | DCA1000 raw-ADC | Serial TLV | Baseline value |
|---|---|---|---|
| `result.status` | `ok` | `ok` | `ok` |
| Driver exit code (`stop.exit_code`; nonzero marks the run failed) | 0 | 0 | 0 |
| Seconds recorded | equals `--seconds` | same | 60 |
| Frames per second mean (`dca_fps_mean` / `tlv_fps_mean`) | 10.0 +/- 0.1 (`expected.expected_fps`) | same | 10.0, 10.0, 10.017 / 9.983, 10.0, 10.0 |
| Per-second min / max | 9 to 11 | 9 to 10 | 9 / 11 (DCA), 9 / 10 (TLV) |
| Dropped packets (`dca_dropped_packets_total`) | 0 | n/a | 0 |
| Rx overruns (`dca_rx_overrun_count_final`) | 0 | n/a | 0 |
| Missed TLV frames (`tlv_missed_frames_total`) | n/a | 1 or fewer | 1, 0, 0 |
| `adc_data.bin` size (`bin_size_check.verdict`) | SIGINT stop: `short_sigint_tail` (<= 896 B short, known bug, core-11). Natural stop: `exact` | n/a | 896 B short x3 |
| CPU % mean | below 15 | below 3 | 9.1 to 10.5 / 0.5 to 0.6 |

For other frame rates, scale the first rows by `expected_fps` from the sidecar; the baseline only covers 10 Hz. The CPU and per-second min/max limits are loose guides from three reps, not guarantees. The baseline ran without `cap_sys_nice`, so DCA numbers are without real-time priority.

A DCA run that is `INCOMPLETE`, shows any drop or overrun, or exits nonzero is a fail: record it and see section 10.

## 8. Record results

1. Keep the CSV and JSON in `docs/results/validation/` (or `baseline/` for a new reference) and commit them; `tools/bench/runs/` is not tracked.
2. Add a row to `docs/RESULTS.md` under a heading for the board, following the baseline tables: fps mean/min/max, dropped packets, `rx_overrun_count`, CPU, the sidecar basename, and the driver sha256 and commit. Record failures and caveats too.
3. Delete the multi-hundred-MB `adc_data.bin` and `LVDS_Raw_0.bin` from `tools/bench/runs/<basename>/` when you no longer need them.

## 9. Per-board differences

| | IWR1843 | IWR1443 | IWR6843 | AWR2243 cascade |
|---|---|---|---|---|
| Board descriptor | `config/boards/IWR1843.json` | `IWR1443.json` | `IWR6843.json` | `AWR2243_CASCADE.json` |
| LVDS lanes | 2, `q_first` | 4, `lane_per_rx`, `i_first` | 2, `q_first` | none (`lvds.supported: false`) |
| Example system config | `front_radar_IWR1843_stress_test_baseline.json` (DCA), `radar_0_IWR1843_demo.json` (serial) | `radar_1.json` | `radar_0_IWR6843_ods_dca_RadVel.json` | `radar_0_AWR2243_cascade_serial.json` |
| DCA1000 needed | yes for raw ADC; no for serial | yes (serial TLV rejected) | yes for raw ADC; no for serial | no (serial only) |
| One cfg per boot | no | no | no | **yes**: power-cycle (12 V off and on) before every run |
| Serial baud (data) | 921600 | n/a | 921600 | 3125000 |
| Known limits | `calibData` rejected by the flashed firmware; I/Q order not confirmed | serial TLV (`sdk2`) unconfirmed; bench-unproven; `radar_1.json`'s cfg has no `lvdsStreamCfg` | not yet run on the bench | raw ADC unsupported (D4); never run through `bench_run.py` |

All config paths are under `CPSL_TI_Radar_cpp/config/system/`. Ports in the shipped configs are the lab's; edit `cli.port` and `serial_stream.port` for yours. Only the IWR1843 has baseline numbers. For the other boards, run the same procedure, treat the pass table as a guide, and record the first good run as that board's reference.

Cascade notes: use the by-id ports and the J6 jumper (bottom two pins to flash, top two to run) from `planning/CASCADE_HARDWARE_SETUP.md`. The cascade config ships with `log_level: "info"`; the harness needs a copy with `"debug"`. The expected rate is the config's 50 ms period (20 Hz) with serial TLV frames and no missed frames. The harness has not been run on this board, so these steps are untested.

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `bench: refusing to run, host preflight failed` | Run `uv run tools/setup/host_setup.py --nic <dca-nic> --apply`, then retry. A rebuild removes `cap_sys_nice`. |
| `no frame received before start timeout` (`FAILED`, exit 2) | Check board mode (SOP jumpers), USB ports, DCA1000 power and cable, and the ping in section 2. For the cascade, power-cycle first. Read `driver_stdout.log`. |
| `not every config command was acknowledged` | Harmless if only `calibData` is rejected. Otherwise the cfg has a command the firmware does not know. |
| Dropped packets or overruns | `rmem_max` below 128 MB, no `cap_sys_nice`, or a slow NIC. Re-run `host_setup.py`; confirm `granted_so_rcvbuf_bytes` in the sidecar is 134217728. |
| Run ends early (`INCOMPLETE`) | The cfg has `numFrames` above 0, or the board lost power or USB. |
| `exit=-6` after a USB unplug | Known crash on a lost radar port (core-11). Reconnect, power-cycle, rerun. |
| Cascade rejects the cfg | It accepts one cfg per power-up. Turn 12 V off and on. |
