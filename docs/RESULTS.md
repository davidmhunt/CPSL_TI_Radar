# Results

Single source of truth for numbers (harness rule 2). Every result here
cites the artifact (script, log, notebook, run ID) it came from. Update on
significant milestones — not every incremental step. Negative results get
recorded with honest caveats, same as positive ones.

## Baseline (pre-rework), IWR1843

Before-numbers for the current driver, for later "no regression" claims (directive core-04, tracker #19). All runs: status `ok`, 60 s, SIGINT stop, exit code 0. Every row below is read from the CSV and same-basename `.json` sidecar named in it (all under `docs/results/baseline/`, tracked by git); the sidecars were re-read and agree with the values shown.

### Conditions (from the sidecars)

- Build: Release, `CMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG`, `CMAKE_CXX_FLAGS` empty, `/usr/bin/c++`; driver sha256 `e9e1d5ba...638ea8` (all runs).
- Host: `cpsl-gmk-6`, 4 CPUs, Linux 7.0.0-34-generic x86_64; `rmem_max` 134217728; NIC `enp3s0` (igc) 1000 Mb/s, MTU 1500, RX ring 256 of 4096, host IP 192.168.33.30.
- **No `cap_sys_nice`.** The DCA RX thread could not get SCHED_RR 99 (driver warning: "could not set RX thread to SCHED_RR 99"). All DCA numbers are without real-time priority.
- Configs: DCA `front_radar_IWR1843_stress_test_baseline.json` with radar cfg `1843_stress_test_baseline_numframes0.cfg` (`numFrames 0`, commit d7a0a2b; 4 RX, 250 samples, 126 chirps, 10 Hz, 504000 B/frame, `save_to_file: true`); serial `radar_0_IWR1843_demo.json` with `IWR1843_demo.cfg` (`numFrames 0`, 10 Hz). SDK 3.6.
- Sidecar `commit` (repo HEAD at run time, no dirty driver/bench paths): DCA rep1 `21cc2c0`, DCA rep2/3 and all serial `5c53cdb`. Later runs record their own HEAD (I/Q `ff4aad5`, unplug `6796509`, ethpull `ade2a69`); HEAD advanced through docs/design/bench commits only, while every sidecar records the same driver binary sha256, which is the measured artifact.
- The firmware CLI rejects `calibData` on every run ("not every config command was acknowledged"). Harmless to these results; deferred to core-10.

### DCA1000 raw-ADC path (tag `baseline_pre_rework_iwr1843_dca_release`)

Sidecar/CSV basename: `baseline_pre_rework_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep<k>__60s__<UTC>` (rep1 `20261005T172423Z`, rep2 `20261005T172615Z`, rep3 `20261005T172720Z`).

| Rep | fps mean / min / max | Dropped packets | rx_overrun_count | CPU % mean / max | RSS max (kB) | Granted SO_RCVBUF | .bin check |
|---|---|---|---|---|---|---|---|
| 1 | 10.0 / 9 / 11 | 0 | 0 | 9.1 / 11.1 | 8928 | 134217728 | short_sigint_tail, 896 B short |
| 2 | 10.0 / 9 / 11 | 0 | 0 | 9.6 / 12.4 | 8784 | 134217728 | short_sigint_tail, 896 B short |
| 3 | 10.017 / 9 / 11 | 0 | 0 | 10.5 / 12.1 | 8560 | 134217728 | short_sigint_tail, 896 B short |

fps is DCA frames per second from the CSV (600, 600, 601 frames in 60 s); about 3460 packets/s. RSS max is the maximum of the CSV `rss_kb` column. Expected `.bin` size is 303408000 B (`bytes_per_frame` x frames); actual 303407104 B in each rep.

### Serial TLV path (tag `baseline_pre_rework_iwr1843_serial_release`)

Basename: `baseline_pre_rework_iwr1843_serial_release__radar_0_IWR1843_demo__rep<k>__60s__<UTC>` (rep1 `20261005T172829Z`, rep2 `20261005T172938Z`, rep3 `20261005T173043Z`).

| Rep | TLV fps mean / min / max | TLV frames | Missed TLV frames | CPU % mean / max | RSS max (kB) |
|---|---|---|---|---|---|
| 1 | 9.983 / 9 / 10 | 599 | 1 | 0.6 / 1.9 | 4660 |
| 2 | 10.0 / 9 / 10 | 600 | 0 | 0.6 / 2.0 | 4720 |
| 3 | 10.0 / 9 / 10 | 600 | 0 | 0.5 / 2.0 | 4724 |

### Findings

1. **SIGINT stop leaves `adc_data.bin` 896 B short; a natural stop does not.** All three DCA baseline runs above are `short_sigint_tail` (896 B, 0.002 frame). The natural stop by pulling the DCA1000 Ethernet (tag `natural_stop_ethpull_iwr1843_dca_release`, 89 frames, commit `ade2a69`) gave `adc_data.bin` 44856000 B equal to the expected 44856000 B (`exact`), a clean exit 0 and `sensorStop` acknowledged. Evidence: `natural_stop_ethpull_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep1__180s__20261005T190150Z.{csv,json}`. This is a controlled comparison of the same config and build, SIGINT stop against clean exit with destructors run (rule 9). The SIGINT path skips the flush. Fix is core-11.
2. **Unplugging the radar USB mid-capture crashes the driver.** Tag `natural_stop_iwr1843_dca_release` (commit `6796509`, 264 frames): after "runner timed out waiting for next adc_cube", the `sensorStop` write threw an uncaught `boost::system::system_error` (write: Input/output error), terminating with SIGABRT (exit -6). The `.bin` was 1536 B short (133054464 of 133056000 B, verdict MISMATCH), but destructors never ran, so this is not a flush measurement. Evidence: `natural_stop_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep1__180s__20261005T174908Z.{csv,json}`. Fix is core-11.
3. **I/Q lane order: not confirmed.** Tag `iqcheck_ground_R1.0m` (evidence committed in `6796509`; the sidecar records repo HEAD `ff4aad5`), capture of 101 frames, ground return at a nominal 1.0 m. The spectrum is single-sided in the current converter order (mirror bins at noise level, about 1.8k to 2.2k against a peak of about 32k), which is consistent with the current order. But the peak is at bin 8 (about 2.1 m at 0.2638 m/bin) against about bin 3.8 (1.0 m) expected, and `iq_check.py` returned `inconclusive`. The range mismatch is unexplained (the target was the ground, not a lone reflector), so the order is not confirmed. A second check is deferred: the user will verify through the live GUI. Evidence: `iqcheck_ground_R1.0m__front_radar_IWR1843_stress_test_baseline__rep1__10s__20261005T173201Z.{csv,json,iqbins.txt}`.

### Not measured / not run

- Latency: not measurable through the current public API; not recorded.
- Notebook smoke test (`process_adc_data.ipynb` on the ethpull `adc_data.bin`, 89 frames): partial pass (commit `3b61a2b`). The cube loads as (89, 4, 250, 126) and the ADC-sample, range-FFT and range-azimuth plots render (`*.notebook_*.png` next to the ethpull sidecar). Two notebook defects, not capture or driver faults, left unfixed: loading needs `numpy<2` (`np.reshape(newshape=...)` fails on numpy 2.x), and the range-Doppler cell fails (63 velocity bins vs 126 chirps per frame in the TDM cfg). Follow-up for the notebook.
- Other boards: out of scope (IWR1843 only).

## Bench validation, IWR1843 (core-06)

Tag `validation_iwr1843_dca_release`, DCA1000 raw-ADC, `front_radar_IWR1843_stress_test_baseline.json`, 3 x 60 s SIGINT stops (plus a rep 4 confirm run), run by following `docs/tutorials/bench_validation.md`. Driver binary sha256 `3ecd94cd17a3...` (with `cap_sys_nice`), repo HEAD `6281aad`. Files in `docs/results/validation/`, basenames `validation_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep<k>__60s__<UTC>` (rep1 `20261005T214321Z`, rep2 `20261005T214452Z`, rep3 `20261005T214602Z`).

| Rep | fps mean / min / max | Dropped packets | rx_overrun_count | CPU % mean / max | RSS max (kB) | Granted SO_RCVBUF | .bin check |
|---|---|---|---|---|---|---|---|
| 1 | 10.0 / 9 / 11 | 0 | 0 | 16.1 / 20.0 | 10004 | 134217728 | exact |
| 2 | 10.0 / 9 / 11 | 0 | 0 | 16.3 / 18.9 | 9908 | 134217728 | exact |
| 3 | 10.0 / 9 / 11 | 0 | 0 | 16.2 / 19.0 | 10820 | 134217728 | exact |
| 4 (confirm) | 10.0 / 9 / 11 | 0 | 0 | 16.2 / 19.0 | 10780 | 134217728 | exact |

Rep 4: tag `validation_iwr1843_dca_release_confirm`, basename `validation_iwr1843_dca_release_confirm__front_radar_IWR1843_stress_test_baseline__rep4__60s__20261005T214741Z`, same binary `3ecd94cd`, run after the doc fixes with the doc unmodified (600 frames, status ok, exit 0). Its files were committed in `6845a0a` under a core-11 subject.

Caveats: exit 0 on all four; every run logs `sensorStop was not acknowledged with 'Done'` (likely the 100 ms command timeout equalling the frame period; tracked for core-13; harmless). CPU is higher than the pre-rework core-04 baseline (9 to 10 %; 16.1 to 16.3 % over 4 reps here). (Superseded: that driver was intermediate; the current driver is about 4 to 5 %, see the later bench section.) The cause is not isolated: the baseline used the pre-rework driver and this binary has both the driver changes and `cap_sys_nice`; an A/B run with and without `cap_sys_nice` would settle it. The < 20 % guide in the runbook comes from these runs. The core-11 SIGINT flush fix is confirmed (`exact`, was 896 B short).

## Bench pass, reworked v2 driver, IWR1843 (core-11 to core-16, core-20)

Release build of the reworked driver on `release/v2.0`, 2026-10-06, host `cpsl-gmk-6`, 10 Hz `front_radar_IWR1843_stress_test_baseline.json` (DCA) and `radar_0_IWR1843_demo.json` (serial), SIGINT stops, run per `docs/tutorials/bench_validation.md`. Every value below is read from the CSV and `.json` sidecars in `docs/results/validation/` (basenames abbreviated to tag, `rep<k>` and UTC stamp). Driver sha256 `2e44b47c...` for the core-16 and ab2 runs; `09abcbec...` for core-20 (default build). Kernel drops, resyncs and `rx_overrun_count` are 0 in every successful run.

### DCA1000 validation, 3 x 60 s (tag `validation_iwr1843_dca_core16`, with `cap_sys_nice`)

| Rep (UTC) | fps mean / min / max | Frames | Dropped packets | Kernel drops / resyncs / overruns | CPU % mean / max | RSS max (kB) | .bin check |
|---|---|---|---|---|---|---|---|
| 1 (`20261006T115551Z`) | 10.017 / 9 / 12 | 601 | 0 | 0 / 0 / 0 | 5.0 / 6.0 | 10748 | exact |
| 2 (`20261006T115823Z`) | 10.017 / 9 / 11 | 601 | 0 | 0 / 0 / 0 | 5.0 / 6.3 | 10840 | exact |
| 3 (`20261006T120220Z`) | 10.017 / 9 / 11 | 601 | 0 | 0 / 0 / 0 | 2.2 / 3.5 | 10812 | exact |

All: status `ok`, exit 0, `adc_data.bin` 302904000 B equal to expected, granted `SO_RCVBUF` 134217728, no driver warnings. Against the core-04 pre-rework baseline (same config, 0 drops, `.bin` 896 B short, CPU 9.1 to 10.5 % mean): CPU is roughly halved (2.2 to 5.0 % here) and the SIGINT `.bin` is `exact`. The core-06 figure of 16 % came from an intermediate driver and is superseded. Rep 3 ran at 2.2 %, less than half of reps 1 and 2; its sidecar records a different repo HEAD (`8ed1aa2`, against `87affa5`) with the same binary hash. The cause of the spread is not isolated.

### Serial validation, 1 x 60 s (tag `validation_iwr1843_serial_core16`, `20261006T120347Z`)

TLV fps 10.017 / 9 / 11, 601 TLV frames, 0 missed, CPU 0.3 % mean / 1.0 % max, RSS max 4096 kB, status `ok`, exit 0. Baseline for comparison: 9.983 to 10.0 fps, 0 to 1 missed, CPU 0.5 to 0.6 %.

### `cap_sys_nice` A/B and core-20 default build

| Tag | Rep (UTC) | CPU % mean / max | Dropped | .bin |
|---|---|---|---|---|
| `ab2_iwr1843_dca_nocap` (no capability) | 1 (`20261006T123856Z`) | 4.8 / 6.0 | 0 | exact |
| | 2 (`20261006T124453Z`) | 4.9 / 6.0 | 0 | exact |
| | 3 (`20261006T124812Z`) | 4.7 / 6.3 | 0 | exact |
| `core20_iwr1843_dca_default` (default build) | 1 (`20261006T134130Z`) | 5.6 / 7.4 | 0 | exact |
| | 3 (`20261006T134310Z`) | 5.3 / 7.0 | 0 | exact |

Without the capability the driver warns that the RX thread "could not set SCHED_RR 99" and runs at normal priority; with it (core16 rows above) CPU was 5.0 / 5.0 / 2.2 %. Every run has fps 10.017 mean, 0 drops, 0 kernel drops, 0 resyncs and an `exact` `.bin`. Conclusion: on this config the capability is not needed. No drop or CPU difference is visible, and the with-capability spread (2.2 to 5.0 %) is wider than the gap to the without-capability runs (4.7 to 4.9 %). Across all 8 successful runs CPU is 2.2 to 5.6 %. The core-20 sidecars record no `realtime` preflight entry and no SCHED_RR warning, so whether that build had the capability is not stated in them.

### Failed runs and causes

- **First A/B set (tag `ab_iwr1843_dca_nocap`, binary run from a temporary path, commit `49bafeb`):** reps 1 and 2 were `ok` (CPU 4.9 and 4.8 %, 0 drops, `exact`); rep 3 (`20261006T120918Z`) is `FAILED`, "no frame received before start timeout". Its start stamp is 10 s after rep 2 (`20261006T120908Z`), and a 60 s rep cannot be over in 10 s, so overlapping reps are the likely cause. This is unverified: no driver log was checked for a bind error. These reps were not used in the table above; the A/B was repeated as `ab2` with all three reps `ok`.
- **core-20 rep 2 (`20261006T134220Z`):** `FAILED`, same start-timeout note. The driver log shows "failed to bind the cmd socket to 192.168.33.30:4096" and "cannot open the DCA1000 sockets". The Runner launched it 50 s after rep 1 (`134130Z`, `134220Z`) while rep 1 ran 60 s; the sidecar timestamps and the driver log agree. It is an operator-side overlap, not a driver fault. The user accepted 2 of 3 reps for core-20.

### USB unplug (tool `tools/bench/usb_unplug_test.py`, run dir `tools/bench/runs/usb_unplug_20261006T123112Z_6gi10qkf`)

Pre-rework, unplugging the radar USB aborted the driver (SIGABRT, `.bin` short; above). Now: frames flowed for about 21 s (212 frames, 0 drops, 0 kernel drops in `driver.log`), the radar was unplugged, the driver took SIGINT, logged "sensorStop could not be sent (radar disconnected?)" and exited 1 with "stopped with errors". No crash, no hang. **Design ruling:** the driver does not stop itself when the CLI port disappears, because raw ADC capture needs no CLI; it keeps capturing until told to stop. The run's `summary.json` originally scored FAIL by the first script version (a criterion bug: needing SIGINT was counted as failure); re-scored PASS with the corrected script (`40e7e20`; `--rescore` on this run's `driver.log`, offline): frames flowed, exit 1, "sensorStop could not be sent", no crash, no hang. The tool's two `PASS` runs in `tools/bench/runs/` (`...123405Z`, `...123417Z`) and its crash/hang `FAIL` runs (`...123407Z`, `...123410Z`, `...123428Z`) end in short `stats v1 frames=5` logs, which look like the tool's self-tests (not verified); they are not used here.

### Caveats

One board, one config (10 Hz baseline), IWR1843 only; other frame rates, boards and hosts are unmeasured. At most 3 reps per condition, so the CPU spread above is not characterized. The sdk2 and serial dialects and the I/Q lane order are still unconfirmed (core-17 is parked until the GUI exists).
