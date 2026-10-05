# Results

Single source of truth for numbers (harness rule 2). Every result here
cites the artifact (script, log, notebook, run ID) it came from. Update on
significant milestones — not every incremental step. Negative results get
recorded with honest caveats, same as positive ones.

Nothing has been run yet.

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
