# Results

Single source of truth for numbers in this repo. Every result here
cites the artifact (script, log, notebook, run ID, commit) it came from.
Update on significant milestones, not every incremental step. Negative
results get recorded with honest caveats, same as positive ones.

Notes on reading it:

- **Names are as of the run.** Config and file names are the ones used on the day (v1 layout). Where a v2 name exists it is given once, in the baseline conditions below.
- **Evidence that is not in the repo.** `runs/gui/`, `tools/bench/runs/` and `/tmp/bench_run/` are gitignored or machine-local, so those run directories are named but cannot be re-read from a clone. The tracked artifacts are `docs/results/baseline/` and `docs/results/validation/`. Firmware bench records live in the `firmware_dev` submodule (`projects/<fw>/project.toml`, `[[bench]]` entries).
- **Bench session notes.** The step-by-step records of the 2026-10-10 and 2026-10-12 bench sessions were removed from the tree in `cee2a5d` (last present at `968e140`); their outcomes are folded into the sections "Bench session 1" and "Bench session 2" below.
- **Commit hashes** replace the work-item labels used while the results were produced. Defect labels such as D10 and item labels such as A2 are the labels used in the bench log at the time; each is explained where it appears.

## Baseline (pre-rework), IWR1843

Before-numbers for the current driver, for later "no regression" claims (measured at `ff4aad5`, `95d4e6e` and `6796509` onward; notebook smoke test `3b61a2b`). All runs: status `ok`, 60 s, SIGINT stop, exit code 0. Every row below is read from the CSV and same-basename `.json` sidecar named in it (all under `docs/results/baseline/`, tracked by git); the sidecars were re-read and agree with the values shown.

### Conditions (from the sidecars)

- Build: Release, `CMAKE_CXX_FLAGS_RELEASE=-O3 -DNDEBUG`, `CMAKE_CXX_FLAGS` empty, `/usr/bin/c++`; driver sha256 `e9e1d5ba...638ea8` (all runs).
- Host: `cpsl-gmk-6`, 4 CPUs, Linux 7.0.0-34-generic x86_64; `rmem_max` 134217728; NIC `enp3s0` (igc) 1000 Mb/s, MTU 1500, RX ring 256 of 4096, host IP 192.168.33.30.
- **No `cap_sys_nice`.** The DCA RX thread could not get SCHED_RR 99 (driver warning: "could not set RX thread to SCHED_RR 99"). All DCA numbers are without real-time priority.
- Configs: DCA `front_radar_IWR1843_stress_test_baseline.json` with radar cfg `1843_stress_test_baseline_numframes0.cfg` (`numFrames 0`, commit d7a0a2b; the v2 names are `IWR1843/demo/stress_test_baseline_numframes0.cfg` and `IWR1843_demo_stress_test_baseline_front.json`, and `save_to_file` is now `output.save_adc_frames`; the sidecars and file basenames keep the v1 names; 4 RX, 250 samples, 126 chirps, 10 Hz, 504000 B/frame, `save_to_file: true`); serial `radar_0_IWR1843_demo.json` with `IWR1843_demo.cfg` (`numFrames 0`, 10 Hz). SDK 3.6.
- Sidecar `commit` (repo HEAD at run time, no dirty driver/bench paths): DCA rep1 `21cc2c0`, DCA rep2/3 and all serial `5c53cdb`. Later runs record their own HEAD (I/Q `ff4aad5`, unplug `6796509`, ethpull `ade2a69`); HEAD advanced through docs/design/bench commits only, while every sidecar records the same driver binary sha256, which is the measured artifact.
- The firmware CLI rejects `calibData` on every run ("not every config command was acknowledged"). Harmless to these results; left as it was and not re-checked here.

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

1. **SIGINT stop leaves `adc_data.bin` 896 B short; a natural stop does not.** All three DCA baseline runs above are `short_sigint_tail` (896 B, 0.002 frame). The natural stop by pulling the DCA1000 Ethernet (tag `natural_stop_ethpull_iwr1843_dca_release`, 89 frames, commit `ade2a69`) gave `adc_data.bin` 44856000 B equal to the expected 44856000 B (`exact`), a clean exit 0 and `sensorStop` acknowledged. Evidence: `natural_stop_ethpull_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep1__180s__20261005T190150Z.{csv,json}`. This is a controlled comparison of the same config and build, SIGINT stop against clean exit with destructors run. The SIGINT path skips the flush. Fixed by the driver rework: the validation runs below are `exact` (first confirmed in `6845a0a`).
2. **Unplugging the radar USB mid-capture crashes the driver.** Tag `natural_stop_iwr1843_dca_release` (commit `6796509`, 264 frames): after "runner timed out waiting for next adc_cube", the `sensorStop` write threw an uncaught `boost::system::system_error` (write: Input/output error), terminating with SIGABRT (exit -6). The `.bin` was 1536 B short (133054464 of 133056000 B, verdict MISMATCH), but destructors never ran, so this is not a flush measurement. Evidence: `natural_stop_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep1__180s__20261005T174908Z.{csv,json}`. Fixed by the driver rework; see "USB unplug" below.
3. **I/Q lane order: confirmed `q_first` for the IWR1843 and IWR1843_SAR (2026-10-12; commits `22ba4ec`, `c1db0c5`).** Capture `core17_iq_raw_R0.9m` (stock demo, 100 frames, 0 dropped; `tools/bench/runs/core17_iq_raw_R0.9m/`, gitignored; sidecar `core17_iq_raw_R0.9m__core17_iq_raw__rep1__10s__20261012T140939Z.{csv,json}` in `tools/bench/runs/core17_sidecar/`), corner reflector at about 0.9 m (a user estimate, not tape-measured; expected bin about 10.4 at 0.0868 m/bin). `iq_check.py` on frames 0/50/99 x rx0-3: 12/12 "current order OK" (peak bin 9 or 11; the swapped order's peak lands on the mirror, bins 117-119). An earlier capture (`runs/gui/20261012T134218Z_bench_1843_dca`) gave 11/12, one inconclusive. The golden test `test_iq_golden` (commit `22ba4ec`) pins frame 99 of the raw LVDS file: rx 0 chirp-averaged DFT peak at bin 9 (82.7 dB), mirror about 31 dB down (51.5 dB), and flipping `iq_order` fails it. The user also confirmed in the live GUI range-Doppler that range tracks a moving target correctly. Caveats: single reflector at an estimated distance, strong clutter at bins 21-27, and the 3.0/5.0 m protocol was dropped by user ruling; the capture was the stock demo, so IWR1843_SAR rests on its descriptor sharing the same LVDS path (both descriptors are `q_first`), and the IWR6843 and IWR6843ODS are inferred, not bench-verified. The earlier inconclusive attempts (`iqcheck_ground_R1.0m`, ground return peak at bin 8 instead of about 3.8, evidence `6796509`; the dataFmt 2 reflector check below) are superseded.

### Not measured / not run

- Latency: not measurable through the current public API; not recorded.
- Notebook smoke test (`process_adc_data.ipynb` on the ethpull `adc_data.bin`, 89 frames): partial pass (commit `3b61a2b`). The cube loads as (89, 4, 250, 126) and the ADC-sample, range-FFT and range-azimuth plots render (`*.notebook_*.png` next to the ethpull sidecar). Two notebook defects, not capture or driver faults, left unfixed: loading needs `numpy<2` (`np.reshape(newshape=...)` fails on numpy 2.x), and the range-Doppler cell fails (63 velocity bins vs 126 chirps per frame in the TDM cfg). Follow-up for the notebook.
- Other boards: out of scope (IWR1843 only).

## Bench validation, IWR1843, first release build

Tag `validation_iwr1843_dca_release`, DCA1000 raw-ADC, `front_radar_IWR1843_stress_test_baseline.json`, 3 x 60 s SIGINT stops (plus a rep 4 confirm run), run by following `docs/developer/bench_validation.md`. Driver binary sha256 `3ecd94cd17a3...` (with `cap_sys_nice`), repo HEAD `6281aad`. Files in `docs/results/validation/`, basenames `validation_iwr1843_dca_release__front_radar_IWR1843_stress_test_baseline__rep<k>__60s__<UTC>` (rep1 `20261005T214321Z`, rep2 `20261005T214452Z`, rep3 `20261005T214602Z`).

| Rep | fps mean / min / max | Dropped packets | rx_overrun_count | CPU % mean / max | RSS max (kB) | Granted SO_RCVBUF | .bin check |
|---|---|---|---|---|---|---|---|
| 1 | 10.0 / 9 / 11 | 0 | 0 | 16.1 / 20.0 | 10004 | 134217728 | exact |
| 2 | 10.0 / 9 / 11 | 0 | 0 | 16.3 / 18.9 | 9908 | 134217728 | exact |
| 3 | 10.0 / 9 / 11 | 0 | 0 | 16.2 / 19.0 | 10820 | 134217728 | exact |
| 4 (confirm) | 10.0 / 9 / 11 | 0 | 0 | 16.2 / 19.0 | 10780 | 134217728 | exact |

Rep 4: tag `validation_iwr1843_dca_release_confirm`, basename `validation_iwr1843_dca_release_confirm__front_radar_IWR1843_stress_test_baseline__rep4__60s__20261005T214741Z`, same binary `3ecd94cd`, run after the doc fixes with the doc unmodified (600 frames, status ok, exit 0). Its files were committed in `6845a0a`, the stop-flush re-check commit.

Caveats: exit 0 on all four; every run logs `sensorStop was not acknowledged with 'Done'` (likely the 100 ms command timeout equalling the frame period; left as is; harmless). CPU is higher than the pre-rework baseline above (9 to 10 %; 16.1 to 16.3 % over 4 reps here). (Superseded: that driver was intermediate; the current driver is about 4 to 5 %, see the later bench section.) The cause is not isolated: the baseline used the pre-rework driver and this binary has both the driver changes and `cap_sys_nice`; an A/B run with and without `cap_sys_nice` would settle it. The < 20 % guide in the runbook comes from these runs. The SIGINT flush fix is confirmed (`exact`, was 896 B short).

## Bench pass, reworked v2 driver, IWR1843

Release build of the reworked driver on `release/v2.0`, 2026-10-06, host `cpsl-gmk-6`, 10 Hz `front_radar_IWR1843_stress_test_baseline.json` (DCA) and `radar_0_IWR1843_demo.json` (serial), SIGINT stops, run per `docs/developer/bench_validation.md`. Every value below is read from the CSV and `.json` sidecars in `docs/results/validation/` (basenames abbreviated to tag, `rep<k>` and UTC stamp). Driver sha256 `2e44b47c...` for the `core16` and `ab2` runs; `09abcbec...` for the `core20` runs (default build). Kernel drops, resyncs and `rx_overrun_count` are 0 in every successful run.

### DCA1000 validation, 3 x 60 s (tag `validation_iwr1843_dca_core16`, with `cap_sys_nice`)

| Rep (UTC) | fps mean / min / max | Frames | Dropped packets | Kernel drops / resyncs / overruns | CPU % mean / max | RSS max (kB) | .bin check |
|---|---|---|---|---|---|---|---|
| 1 (`20261006T115551Z`) | 10.017 / 9 / 12 | 601 | 0 | 0 / 0 / 0 | 5.0 / 6.0 | 10748 | exact |
| 2 (`20261006T115823Z`) | 10.017 / 9 / 11 | 601 | 0 | 0 / 0 / 0 | 5.0 / 6.3 | 10840 | exact |
| 3 (`20261006T120220Z`) | 10.017 / 9 / 11 | 601 | 0 | 0 / 0 / 0 | 2.2 / 3.5 | 10812 | exact |

All: status `ok`, exit 0, `adc_data.bin` 302904000 B equal to expected, granted `SO_RCVBUF` 134217728, no driver warnings. Against the pre-rework baseline above (same config, 0 drops, `.bin` 896 B short, CPU 9.1 to 10.5 % mean): CPU is roughly halved (2.2 to 5.0 % here) and the SIGINT `.bin` is `exact`. The first-release-build figure of 16 % came from an intermediate driver and is superseded. Rep 3 ran at 2.2 %, less than half of reps 1 and 2; its sidecar records a different repo HEAD (`8ed1aa2`, against `87affa5`) with the same binary hash. The cause of the spread is not isolated.

### Serial validation, 1 x 60 s (tag `validation_iwr1843_serial_core16`, `20261006T120347Z`)

TLV fps 10.017 / 9 / 11, 601 TLV frames, 0 missed, CPU 0.3 % mean / 1.0 % max, RSS max 4096 kB, status `ok`, exit 0. Baseline for comparison: 9.983 to 10.0 fps, 0 to 1 missed, CPU 0.5 to 0.6 %.

### `cap_sys_nice` A/B and default build (`core20` tag)

| Tag | Rep (UTC) | CPU % mean / max | Dropped | .bin |
|---|---|---|---|---|
| `ab2_iwr1843_dca_nocap` (no capability) | 1 (`20261006T123856Z`) | 4.8 / 6.0 | 0 | exact |
| | 2 (`20261006T124453Z`) | 4.9 / 6.0 | 0 | exact |
| | 3 (`20261006T124812Z`) | 4.7 / 6.3 | 0 | exact |
| `core20_iwr1843_dca_default` (default build) | 1 (`20261006T134130Z`) | 5.6 / 7.4 | 0 | exact |
| | 3 (`20261006T134310Z`) | 5.3 / 7.0 | 0 | exact |

Without the capability the driver warns that the RX thread "could not set SCHED_RR 99" and runs at normal priority; with it (core16 rows above) CPU was 5.0 / 5.0 / 2.2 %. Every run has fps 10.017 mean, 0 drops, 0 kernel drops, 0 resyncs and an `exact` `.bin`. Conclusion: on this config the capability is not needed. No drop or CPU difference is visible, and the with-capability spread (2.2 to 5.0 %) is wider than the gap to the without-capability runs (4.7 to 4.9 %). Across all 8 successful runs CPU is 2.2 to 5.6 %. The `core20` sidecars record no `realtime` preflight entry and no SCHED_RR warning, so whether that build had the capability is not stated in them.

### Failed runs and causes

- **First A/B set (tag `ab_iwr1843_dca_nocap`, binary run from a temporary path, commit `49bafeb`):** reps 1 and 2 were `ok` (CPU 4.9 and 4.8 %, 0 drops, `exact`); rep 3 (`20261006T120918Z`) is `FAILED`, "no frame received before start timeout". Its start stamp is 10 s after rep 2 (`20261006T120908Z`), and a 60 s rep cannot be over in 10 s, so overlapping reps are the likely cause. This is unverified: no driver log was checked for a bind error. These reps were not used in the table above; the A/B was repeated as `ab2` with all three reps `ok`.
- **`core20` rep 2 (`20261006T134220Z`):** `FAILED`, same start-timeout note. The driver log shows "failed to bind the cmd socket to 192.168.33.30:4096" and "cannot open the DCA1000 sockets". It was launched 50 s after rep 1 (`134130Z`, `134220Z`) while rep 1 ran 60 s; the sidecar timestamps and the driver log agree. It is an operator-side overlap, not a driver fault. The user accepted 2 of 3 reps for that tag.

### USB unplug (tool `tools/bench/usb_unplug_test.py`, run dir `tools/bench/runs/usb_unplug_20261006T123112Z_6gi10qkf`)

Pre-rework, unplugging the radar USB aborted the driver (SIGABRT, `.bin` short; above). Now: frames flowed for about 21 s (212 frames, 0 drops, 0 kernel drops in `driver.log`), the radar was unplugged, the driver took SIGINT, logged "sensorStop could not be sent (radar disconnected?)" and exited 1 with "stopped with errors". No crash, no hang. **Design ruling:** the driver does not stop itself when the CLI port disappears, because raw ADC capture needs no CLI; it keeps capturing until told to stop. The run's `summary.json` originally scored FAIL by the first script version (a criterion bug: needing SIGINT was counted as failure); re-scored PASS with the corrected script (`40e7e20`; `--rescore` on this run's `driver.log`, offline): frames flowed, exit 1, "sensorStop could not be sent", no crash, no hang. The tool's two `PASS` runs in `tools/bench/runs/` (`...123405Z`, `...123417Z`) and its crash/hang `FAIL` runs (`...123407Z`, `...123410Z`, `...123428Z`) end in short `stats v1 frames=5` logs, which look like the tool's self-tests (not verified); they are not used here.

### Caveats

One board, one config (10 Hz baseline), IWR1843 only; other frame rates, boards and hosts are unmeasured. At most 3 reps per condition, so the CPU spread above is not characterized. The sdk2 and serial dialects are still unconfirmed; the IWR1843 I/Q lane order is confirmed (finding 3).

## IWR1843 SAR LVDS firmware (`iwr1843_sar_lvds`), Set A + 10-min no-reflector soak

Bench run 2026-10-06, one IWR1843BOOST with DCA1000, example cfg (`sar_example_2ms.cfg`, default gain and HPF, `analogMonitor`/CQRxSat on), no reflector in the scene. Values were recorded in the bench log at the time (a local working log, not in this repo) and in the soak artifacts `/tmp/bench_run/soak_summary.txt` and `/tmp/bench_run/soak_summary.json` (capture `/tmp/bench_run/soak.cap`, `/tmp/bench_run/soak.cap.sarstats.json`; not tracked in the repo). Set A rows use `/tmp/bench_run/long.cap`, `bytes.cap`, `bsize*.cap`, `fmt1.cap`, `fmt4.cap` and the like in the same folder. Firmware_dev commits: flash image built at `946f48d`; Set A run at `314ec2e`; soak run at `778f806`. The repo-reachable record is the `partial` `[[bench]]` entry in `firmware_dev/projects/iwr1843_sar_lvds/project.toml` (dated 2026-10-06).

**Verdict: Set A + 10-min no-reflector soak: GO on G1, G2, G5 and the G7 non-reflector rows (G1-G7 are the gate labels of the bench plan); G3 phase continuity, G4 tuned point/SNR/ADC bits, G6 boundary/Tb and saturation-vs-gain are NOT EVALUATED (they need a placed reflector); I/Q order is settled by finding 3.**

| Item | Measured |
|---|---|
| Flash (`./fw flash`, DSLite) | rc=0, `Flashed (DSLite rc=0)`, no trailing `Can't Run Target CPU`; board booted to `mmwDemo:/>`; image sha256 `53948f4d...4267a`, 152132 B |
| 60 s capture (`long.cap`) | 30090 chirps, 0 sequence gaps, 0 wholly missing; checks 1, 2, 4 pass, check 3 deferred (tail hole 336 B); in-frame dt 2000.00 us, boundary dt 2300.54 us |
| 10 min soak (`soak_summary.txt`) | 299880 chirps, 2745055 datagrams, 3996.8 MB, 6.66 MB/s; 0 UDP gaps, 0 wholly missing, 1 invalid record (the tail hole); parser checks 1-4 accepted |
| Soak timing | in-frame dt mean 2000.00 us, p99.9 deviation 3.03 us; boundary dt mean 2300.51 us, max deviation 0.77 us; late 0 |
| Soak counters | `chirps` = `chirpStartIsr` = `chirpAvail` = 299880, 1176 frames; `lateIsr`, `missedChirpIsr`, `frameResync`, `availResync` all 0 |
| Packet sizes | 13328 B header on, 13264 B header off (Ns 3300); 13328 B at Ns 3302 (H 56); `dataFmt 4` CQ on 13616 B / 13392 B |
| `satRefLag` (soak, 9 polls) | lag 2 in 298702 records (99.61%), lag 1 in 1175 (0.39%, frame starts only); `SAT_VALID=0` on 2 records; saturation counters recorded without a target: firmware 0, parser 0 |
| Other-slot regime | k+1 |
| Restart without power cycle | 4 cycles x 30 s, each clean |
| `channelCfg` change | rejected at `sensorStart` with a clean CLI error |
| Finite `numFrames`, `sensorStart 0` | both pass |
| `dataFmt 1` regression | 137058 datagrams, 0 gaps, LVDS frames 59 = sent, restart back to `dataFmt 2` clean |

Not measured (needs a placed reflector; not yet run): tuned gain/HPF point; clipped-chirp count; ADC bits; phase step at boundaries (G3); minimum clean Tb (G6); saturation-vs-gain sweep. I/Q order is not part of that list; see finding 3. The soak entry lists these as `NOT EVALUATED`.

### Caveats

- The soak and the 60 s capture each contain 1 invalid record, the tail hole where the capture stops mid-packet. The pass criteria tolerate it; it is not a mid-stream loss (0 UDP gaps, 0 wholly missing).
- dt was measured with no reflector placed and default gain/HPF, so it says nothing about timing under a tuned or saturating scene.
- Set A was measured on the earlier image (sha256 `53948f4d...4267a`). The image was rebuilt afterwards (prompt `mm_sar_lvds:/>`, sha256 `a06ee615...`, identity check in `2b31cc8`; see the next section and "Bench session 1"); this set was not re-run on it.
- Phase-like numbers taken from reflector-less data are indicative only and are not reported here.
- The `dataFmt 4` block contents (CP, sigImg, satMon) are not parsed; only packet size, HSI id, gaps and counters were checked.

## Core driver on the SAR image, dataFmt 1 and dataFmt 2 (IWR1843_SAR), 2026-10-09

Bench 2026-10-09, IWR1843BOOST + DCA1000, driver `build/CPSL_TI_Radar_CPP` sha256 `751621f1b18a973081ca3d64a372e33fbda62c212b199e1b63f462c40f7390c4` (unchanged between rebuilds 3 and 4), firmware image `iwr1843_sar_lvds` sha256 `a06ee615b56b12282f2fe9b4a02bb556ceaa81a1b72176e2060cd9209a070924`. Board `IWR1843_SAR`, shipped system JSONs, no power cycle between the runs below. Values come from the raw driver logs under `tools/bench/runs/` (`core23_fmt1__...60s...`, `core23_fmt1_restart__...rep1/rep2...`, `core24_fmt2_soak__...600s...`) and the bench session of 2026-10-10 (its tests 5 to 7; the session's other tests are in "Bench session 1" below). The session record is dated 2026-10-10 while this section, as first written, dates the bench 2026-10-09; the difference was not resolved here. Run directories are gitignored.

| Item | Result |
|---|---|
| dataFmt 1, 60 s (`IWR1843_iwr1843_sar_lvds_SAR_2ms.json`) | `firmware: match expected=iwr1843_sar_lvds`; 117 frames, 272,324 packets; 0 dropped, late, incomplete, stalls, kernel drops, resyncs; 3,366,000 B/frame (3300 x 4 B x 255 chirps x 1 Rx) |
| CLI latency | cfg commands 1-6 ms each (no 500 ms prompt stall) |
| `sensorStart` ack | 74 ms on the first start after power-up, 5 ms on later starts; the hard `cli.cmd_timeout_ms` was 100 ms (26 ms margin on the first start), raised to 500 ms in `IWR1843_SAR.json` (`46f9823`) |
| `sensorStop` ack | 102 ms (60 s run) and 204 ms (restarts), about one frame-end wait; the limit is `cli.stop_timeout_ms` = 4000 ms in `IWR1843_SAR.json`, not `cmd_timeout_ms` |
| Restarts | two more 15 s driver processes in the same power-up: cfg accepted every time, 29 frames each, 0 drops |
| dataFmt 2 replay (`SAR_2ms_fmt2.cfg`, 20 s `dca_capture.py` capture, 92,920 datagrams) | driver `adc_data.bin` byte-equal to `sar_parse.py` `_adc.bin` over all 39 complete frames (131,274,000 B); `chirp_meta.csv` rows 0-9943 equal to `_meta.csv`; records_valid 9945, invalid 0, other_run 0. Same result on a second capture |
| dataFmt 2 live soak, 600 s (`..._SAR_2ms_fmt2.json`) | `firmware: match`; 1175 frames, 2,731,404 packets; 0 dropped, late, stalls, kernel drops, resyncs; records_valid 299,625 = 1175 x 255; records_invalid 0; other_run 0; sensorStart 5 ms, sensorStop 102 ms; 0 driver warnings |

### Interpretation

The core driver configures the SAR image, passes the identity check, and streams dataFmt 1 and dataFmt 2 without loss on the bench, and the SAR descriptor restarts without a power cycle. The sensorStop times are normal: the firmware acks after the current frame ends, and the descriptor's stop timeout (4000 ms) is about 20 times larger than the measured wait. The one thin margin was the first `sensorStart` after power-up (74 ms against the then-hard 100 ms); `cmd_timeout_ms` was raised to 500 ms afterwards (not re-benched).

### Honest caveats

- The driver's dataFmt 2 output equals the golden parser only on **complete frames**. The recording ends mid-frame: the driver drops the trailing partial frame by design (`sar_parse.py` emits a 40th frame from the tail hole), and it writes each frame's metadata one frame late so the last chirp's carried saturation field is empty (`sar_parse.py` writes `0`). So `chirp_meta.csv` has 9,946 lines against the golden's 10,201 and differs only at that end-of-recording row.
- The I/Q reflector check on the dataFmt 2 capture was **inconclusive** and is informative only (the I/Q verdict is finding 3). With a reflector at 0.90 m (tape band 0.813-0.991 m), the strongest peak was room clutter at 3.77 m (bin 88, 20x the median); a weaker peak at bin 20 (0.857 m, 7.1x the median) lies inside the band and may be the reflector. It neither confirms nor refutes the I/Q order and needs a cleaner scene or a larger reflector.
- Each run is a single run; the restarts are separate driver processes, not in-process restarts. The ADC scene held no tuned gain or HPF point.
- The end-of-run `sarStats` checks (capture checks 3 and 4) are not in the driver; the bench ran them through `bench_check.py` (check 3 not evaluable on the 20 s capture because of a 1,280 B tail hole).

## Bench session 1, IWR1843 + DCA1000 (2026-10-10)

One IWR1843BOOST (XDS110 `R2101050`) plus DCA1000; the cascade was connected but its USB unplugged. Driver `CPSL_TI_Radar_cpp/build` sha256 `751621f1b18a973081ca3d64a372e33fbda62c212b199e1b63f462c40f7390c4` (Rebuild 4), a human at the bench for the flashes and the GUI items. The step-by-step record is gone from the tree (see the notes at the top); the outcomes are below. Run directories are under `runs/gui/` (gitignored), so these are not re-readable from a clone. Each item is **one run**. Tests 5 to 7 (driver on the SAR image, dataFmt 2 replay, 10-min soak) are in "Core driver on the SAR image" above.

| Test | What was run | Recorded result | Verdict |
|---|---|---|---|
| 1 Baseline identify | `fw verify ti_stock_demos`; `fw verify iwr1843_sar_lvds` | Stock verify passed; the SAR verify failed, as expected with the stock demo on the board | PASS |
| 2 SAR flash dry-run | `fw flash` dry-run for `iwr1843_sar_lvds` | sha256 `a06ee615b56b12282f2fe9b4a02bb556ceaa81a1b72176e2060cd9209a070924`, 152,132 B, both as expected | PASS |
| 3 SAR flash | User, in their own terminal: SOP 101, power cycle, `./fw flash iwr1843_sar_lvds <by-id port>`, then SOP 001 and power cycle | Flasher reported `SUCCESS!! META_IMAGE1` | PASS |
| 4 SAR verify + bench-check capture | `fw verify`, then `bench_check.py` on a short raw capture | `fw verify` matched (`Platform: xWR18xx`, prompt `mm_sar_lvds:/>`). `bench_check` VERDICT ACCEPTED: every cfg line `Done`, chirpAvail 2550 (10 frames x 255), 2549 of 2550 records valid (one tolerated 448 B tail hole), no duplicate, late or saturated chirps, in-frame dt 2000.00 us, boundary dt 2300.58 us against the cfg value 2300. With two XDS110 ports present `bench_check.py` needs `--cli-port` | PASS |
| 8 Restore stock demo | User flashed the stock image; `fw verify ti_stock_demos` | Version matched xWR18xx, SDK 03.06.02.00, IWR18xx non-secure ES 02.00; `sarStats` answered "not recognized", expected on the stock demo. Dry-run image `iwr1843_demo.bin` sha256 `cd43e0df...`. The board ended the session on the stock demo | PASS |
| 9a GUI CFAR card | User's own cfg `IcaRAus_test_cfar_copy` on the stock demo: runs `20261009T131416Z_IcaRAus_test_cfar_copy` (range threshold 25, Doppler 23) and `20261009T131723Z_IcaRAus_test_cfar_copy_1` (27 / 25) | CFAR edits saved and streamed; the user reports the point cloud looked nominal (an observation, no count recorded) | PASS (user) |
| 9b GUI serial-only checks | Start/Stop from the Radar tab; "Save raw serial bytes" for about 15 s, then replay `serial_data.bin` in the Point cloud tab; firmware verdict; keyboard tab switching; Stop from Live | Start showed "running" and Stop ended it; replayed point counts matched the live run; verdict "match"; arrow and digit keys switched tabs. Skipped: ADC exactness (deferred) and cascade restart (cascade unplugged) | PASS (user) |
| 10 Docker `hw` profile | `docker compose ... --profile hw run --rm hw python -m radar_gui ...` | GUI reachable over the tailnet; **Start failed**: `SerialStreamer: cannot open /dev/ttyACM1: Permission denied` (`runs/gui/20261009T134303Z_1843_demo_tlv_default.cfg/driver.log`) | FAIL, root cause found; retested PASS in session 2 |

- **Test 10 root cause (isolated).** On this host the serial nodes belong to group `plugdev` (gid 46), not `dialout` (gid 20); the compose file took the gid from `getent group dialout`. Native runs work because the user is in `plugdev`. Setting the group from the device (`SERIAL_GID`, written by `docker/app/setup_env.sh`) is the fix (`1446d58`, `ca7a761`, `fc9250c`). The container was started with `--rm`, so its own logs were lost; the error text above is from the run directory.
- **Findings from 9a and 10, all fixed afterwards** (re-checked in session 2): the "Open in Run" link was stale after the tab rename; the radar rejected the identify probe `sarStats` on the stock demo (expected, but it looked like a cfg error) and `bpmCfg -1 0 0 0`; saving over an existing user config was refused; configs never opened in the GUI were missing from its lists (the frontend cached the lists). Fixes: `f41520a`, `7578a8c`, `8e2d659`.
- **Caveats.** The 9a/9b GUI checks are the user's observations at the bench; only the run directories named above back them. 9a gives no point counts. Test 4's `bench_check` numbers come from a 10-frame capture, not a soak.

## GUI bench validation, IWR1843 + DCA1000 and AWR2243 cascade (2026-10-07)

Bench session 2026-10-07 (host `cpsl-gmk-6`, Release driver sha256 `f34182371d0b...a4e6`, repo HEAD at start `fc385db`), driven from the `radar_gui` Run and Live tabs by a human at the bench. Values were recorded in the bench log at the time (a local working log; the first write-up of this section is `826346e`) and in the run directories named below under `runs/gui/` (gitignored, not in the repo). IWR1843 = XDS110 `R2101050` running the SDK 3.6.2 demo image; DCA1000 at 192.168.33.180. Each item was **one run** (no repetitions), and pass/fail was judged largely from the numbers the user read off the GUI; serial-only runs write no files, so those counts have no file to cross-check.

| Item | What was run | Board / firmware | Recorded result | Verdict |
|---|---|---|---|---|
| A1 | Run tab, `bench_1843_tlv` (GUI-saved copy of `IWR1843_demo.cfg`), serial TLV only | IWR1843, SDK 3.6.2 demo | First attempt: 0 frames, `sensorStart` replied "Full configuration must be provided before sensor can be started the first time". After the calibData fix (`dbde0ad`) it streamed (run `20261007T191802Z_bench_1843_tlv`); frame count not recorded | PASS after fix |
| A2 | Run tab, shipped `front_radar_IWR1843_stress_test_baseline.json` (DCA1000, `log_level debug`), ~64.6 s | IWR1843 + DCA1000 | dca frames 646 (10 Hz); dropped 0, kernel drops 0, incomplete 0; `adc_data.bin` 325,584,000 B = 646 x 504,000 B, verdict `exact`; `LVDS_Raw_0.bin` 325,608,192 B (run `20261007T192639Z_...baseline`) | PASS |
| A3 | Configure -> `bench_1843_dca` (10 m / 3 m/s / 10 Hz, LVDS on; 256 chirps x 128 samples x 4 RX = 524,288 B/frame), Serial TLV + DCA1000 + save ADC, ~20.1 s | IWR1843 + DCA1000 | dca frames 200, dropped 0, kernel 0, incomplete 0; serial frames 200, missed 0; `adc_data.bin` 104,857,600 B = 200 x 524,288 B, verdict `exact` (run `20261007T193806Z_bench_1843_dca`) | PASS |
| A4 | During the A3 run: Live -> Serial on the same ports; Run tab Start | IWR1843 | Refused "Ports busy: radar in use by driver"; Run Start greyed while running (user-reported) | PASS |
| A5 part 1 | Run tab, shipped `radar_0_AWR2243_cascade_serial.json`, fresh power-up | AWR2243 cascade, `cascade_ddm` | 630 frames, 0 missed (~63 s at 10 Hz); on Stop "driver did not stop after SIGINT; killed (SIGKILL)" (run `20261007T194842Z_...cascade_serial`) | PASS with defect (D10) |
| A5 part 2 | `bench_cascade` (GUI-generated, user-edited), power-cycle first | cascade | 1024 chirps/frame (`frameCfg 0 7 128 ...`): every line Done except `sensorStart` ("no Done within 5000 ms"), 0 frames. Retry `bench_cascade_revA`, 256 chirps (`frameCfg 0 7 32 ...`), 128 samples, 100 ms: streamed, Stop clean (runs `20261007T200759Z_bench_cascade_revA`) | FAIL, then PASS at 256 chirps |
| B1 | Live -> Serial, IWR1843, `IWR1843_demo.cfg`, dump on | IWR1843 demo | `configuring i/N` -> `streaming`; header 10 Hz; points visible; Stop/Start reconfigures and streams. Dumps `runs/gui/dumps/IWR1843_2026-10-07T20-14-44.bin` (427,008 B) and `...T20-17-17.bin` | PASS |
| B2 | Live -> Serial, cascade | cascade | Streamed; Stop -> "already configured" tick -> restart streams; restart without tick -> `cfg_failed` with power-cycle notice; power-cycle while running -> auto reconfigure and stream | PASS |
| S5 (live-tap bench) | Rebuilt driver (Rebuild 1, `bc54c7a`, binary sha256 `5defbd88...`): Live following a driver run on IWR1843 + DCA1000 (run `20261007T214919Z_bench_1843_dca`); cascade driver runs `20261007T215123Z` and `20261007T215156Z` | IWR1843 + DCA1000; cascade | IWR1843: Live auto-followed the run, Stop ended it; `adc_data.bin` 277,348,352 B = 529 x 524,288 B, exact whole frames. Cascade: run, quick Stop with no SIGKILL, then a `--skip-configure` re-run streamed without a power cycle. User: "Everything worked as you described it" | PASS (qualitative; see caveats) |

### Findings

- **A1 root cause (isolated).** The board and CLI were alive (`version` reported mmWave SDK 03.06.02.00); the driver reproduced 0 frames from the command line, so it was not a GUI-launch problem. The flashed SDK 3.6.2 demo requires `calibData` as part of the "full configuration", but the IWR1843 board descriptor listed `calibData` in `skip_commands` (a leftover for older firmware). Removing it (`dbde0ad`) fixed the run on the bench. The same missing `calibData` was found in `Iwr18xx_DCA_mmStudio_original.cfg` and fixed in `70668a9`; that cfg was not run on the bench.
- **DCA1000 path.** A2 and A3 are exact frame multiples with 0 drops and 0 kernel drops. They agree with the earlier bench pass (section "Bench pass, reworked v2 driver, IWR1843") but are one run each. A2 ran ~64.6 s rather than the planned 60 s, so the criterion was judged as frames = 10 Hz x duration (646 / 64.6 s). A3 ran ~20.1 s, not 60 s, so it shows 200 frames at 10 Hz but nothing about a longer soak.
- **B1 header rate.** The header showed 10 Hz at the cfg rate of 10 Hz. This is the user's reading of the live header; no Gaps/Errors values were recorded, so "0 gaps/errors over 60 s" is not claimed here.
- **Cascade 256 vs 1024 chirps.** The GUI generator had chosen 128 loops (1024 chirps) for 15 m / 5 m/s / 10 Hz and only warned; the cascade then failed at `sensorStart`. With 32 loops (256 chirps) it worked. Besides the chirp count, the failed and working cfgs were otherwise the same family but several parameters differed from the shipped cfg, so the bench by itself is one failing and one passing run and does not isolate the chirp count. The cause is explained by `docs/developer/radar_notes.md#cascade-chirp-limit` (first written in `f48b1e5`): the Doppler FFT size is bounded by the 82 KiB DSS L2 heap, so for 6 TX / 8 RX the chirps per frame must be <= 256, and the 2.53 MiB L3 radar cube is a second limit for large range-bin counts. That note derives this from sources; its confidence is "medium" and a 384-chirp bench check (`frameCfg 0 7 48 ...`) was not run. The GUI now treats >256 chirps on the full cascade as an error and caps the generator at 256 (`3a032e0`). The C++ driver does not read these limits.
- **Replay fixtures** (`1e977d4`, `tests/fixtures/replay/`): 20 frames of the IWR1843 SDK 3 capture (5,760 B, 7 points per frame) and 20 frames of the cascade capture (25,952 B, 49-68 points per frame, no TLV 12), with 7 tests in `tests/test_radar_gui_replay_bench.py`. The cascade capture holds 177 frames in total, so with the CFAR settings used (12 / 10 dB) the cascade does produce points.
- **Rebuild 1 bench (2026-10-07, one session).** With the driver at `bc54c7a`: D10 is fixed (`67121cb`: no `sensorStop` on once-per-boot boards, so the cascade Stop was quick with no SIGKILL), the cascade restart works through `--skip-configure` (D14), the live tap followed the IWR1843 + DCA1000 run, and the Run-tab command echo (`86f10f3`) worked. These are the user's observations plus the run directories named above; each was one run.
- **ADC diagnostics on two real frames (`1369ba2`).** Frames 264-265 of the 529-frame capture are stored as the fixture `tests/fixtures/adc/`. On them: bits used 11/16 on all 4 RX with 0 clipped samples; RMS about -44 to -46 dBFS; image ratio +33 dB, consistent with correct I/Q order. This is two adjacent frames of one capture, so it is evidence, not proof; the I/Q order is now confirmed (finding 3).
- **GUI lag (D8/D9).** The user found the GUI "a little laggy" in the A2 run. In a fake-driver measurement at the A2 rate (10 s window, headless Firefox) log re-renders fell from ~66/s to 5.5/s and time in log rendering was 7-10x lower (`fb15de0`). The cause of the user's lag was not isolated and the bench re-check of responsiveness is not recorded. After exit the stream cards now show the average rate (frames / duration) instead of "0.0 Hz".
- **Fixed GUI defects** (commits): D1 header followed the Live mock during a driver run, D2 plain "0 frames received" verdict, D3 screenshot runs wrote into `runs/gui/`, D4 source ports restricted to by-id / `ttyACM` / `ttyUSB` (`400398c`); D5 retry after `cfg_failed` on repeatable boards (`400398c`); D12 `wrong_firmware` header colour (`914197b`); D13 test hang mitigations (`9528964`, hang itself not reproduced); D15 Source card "Restart" only for the running board/cfg (`26981fe`); D16 replay dialect select (`86b48f6`); D17 tap-test flake (`ebfec94`).

### Negative results and caveats

- **The cascade accepts one cfg per power-up.** Every cascade item that sends a cfg needs a fresh power cycle; a failed `sensorStart` (A5 part 2) leaves the board unusable until the next power cycle. Restarting a driver run on the cascade fails for the same reason (D14); `--skip-configure` (`bc54c7a`) fixes this and was bench-confirmed on 2026-10-07 (runs `20261007T215123Z`, `20261007T215156Z`: run, stop, skip-cfg re-run without a power cycle).
- **Stop needed SIGKILL on the cascade (D10), fixed.** In A5 part 1 the driver sent `sensorStop` and waited 5000 ms for a `Done` the cascade never sends, so the GUI killed it. `67121cb` skips `sensorStop` on once-per-boot boards; in the Rebuild 1 binary the cascade Stop was quick with no SIGKILL (two runs, user-observed; no log timing recorded).
- **"No points" during cascade driver runs was display-only.** During a driver run the GUI did not display driver point clouds at all (header Points showed "-"); the replay fixture shows the cascade capture does contain points. The live tap (`41bc977`) is now bench-verified **qualitatively**: Live auto-followed the IWR1843 + DCA1000 run and the capture holds exact whole frames. No final dropped / kernel-drop / tap counters were recorded for that run (the GUI keeps the driver log in memory only and the user did not quote them), so the tap's `sent` / `skipped` counts and zero-drop behaviour under tapping are not established. Live following of a cascade driver run was not separately reported.
- **Cascade firmware check is off.** The Source card shows "cascade_ddm (not checked)" because the cascade identify probe is not yet safe; it stays off until the cascade's version reply is captured on the bench. The IWR1843 firmware check (`272e017`) showed "demo" in B1.
- **Not run:** a 60 s soak of A1/A3/B1 (shorter runs were used), a bench check of the ADC tab itself beyond the two-frame fixture analysis above, the optional 384-chirp cascade check, and any reflector-based measurement. The B1/B2 "points visible" judgements are user observations; no screenshot paths were recorded for them.

## Bench session 2, IWR1843 + AWR2243 cascade (2026-10-12)

Source: the 2026-10-12 bench session (record removed from the tree, see the notes at the top) and the commits named below. Run directories are under `runs/gui/` (gitignored). Each item is one run with the user at the bench.

| Item | Board / firmware | Recorded result | Verdict |
|---|---|---|---|
| 1 Docker `hw` re-check (`setup_env.sh`, `docker compose ... --profile hw up --build hw`) | IWR1843 stock demo | User: "I tested the hw mode. everything seems to be working on there." Resolves session 1 test 10 (serial group now read from the device). No run directory or log was recorded for it | PASS (user report only) |
| 2 GUI follow-ups (a)-(d), run `20261012T133340Z_IcaRAus_test` | IWR1843 stock demo | (a) save, then listed in Radar and via Refresh, and (b) overwrite with confirm: PASS after `c5b3182` (the first Save failed with "Input should be a valid boolean": the Save button passed the click event as `overwrite`). (c) `sarStats` shown as a firmware probe (user report). (d) `driver.log` shows `cli [skip] bpmCfg -1 0 0 0 (skip_commands)`; the only ERROR is the `[id] sarStats` identify probe; firmware match | PASS |
| 3 GUI DCA1000 capture, run `20261012T134218Z_bench_1843_dca` | IWR1843, stock SDK 3.6.2 demo + DCA1000 | 134 frames, 0 missed; dca dropped 0, kernel drops 0, incomplete 0, resyncs 0; `adc_data.bin` 70,254,592 B = 134 x 524,288 B, verdict `exact`; Stop from the Point cloud tab ended it (`sensorStop` DONE) | PASS |
| 4a Cascade restart | cascade, its image at the time | configure run `20261012T135017Z_bench_cascade` (182 frames, 0 missed, `sensorStart` 466 ms); header "Restart (skip cfg)" run `20261012T135050Z_bench_cascade` 134 frames, 0 missed, no power-cycle | PASS |
| 5 Flash our `awr2243_cascade_ddm` build, run `20261012T141433Z_bench_cascade` | cascade, image sha256 `9bf7f418...c30c770` | flashed by the user ("Cascade finished successfully", literal `fw flash` output not pasted); `fw verify` outcome `skipped`, exit 0; GUI run 163 frames, 0 missed, `sensorStart` 466 ms | PASS |
| 4b Cascade DDM range CFAR `cfarCfg -1 0 3 16 2 0 1 13 0 7 0 1` (averageMode 3, guardLen 2), runs `20261012T135326Z`, `20261012T135439Z` | cascade, DDM image | `sensorStart` TIMEOUT 5000 ms in both. Same cfg with guardLen 0 (run `20261012T135918Z`): DONE in 466 ms | guardLen 2 FAIL, guardLen 0 PASS |

### SAR image in the GUI (item 6)

The `iwr1843_sar_lvds` image (IWR1843 flashed 2026-10-12, DCA1000) driven from the GUI: identify, validate, run with live raw-ADC views, stop, save, re-start without a power cycle. Frame = 255 chirps x 3300 samples x 1 RX x 4 B = 3,366,000 B. Offline triage of the logged runs, no hardware touched afterwards. Verdict: PASS (user: "All of the checks now pass just fine on my end").

- **Failure and fix.** The first attempts showed in the Raw ADC tab "cannot build the ADC geometry from the run's cfg: unknown board 'IWR1843_SAR'". The driver tap had sent every frame; the GUI passed the driver board name to a GUI-board lookup. Fixed in `8bb6512`; the runs R1-R3 below predate it.
- **Common to all seven runs below:** no WARN/ERROR line in any `driver.log` other than the `[id] sarStats` probe; `sensorStart` DONE; `dropped=0 drop_events=0 late=0 duplicate=0 incomplete=0 overrun=0 kernel_drops=0 resyncs=0`; stopped from the GUI with `sensorStop` DONE; `session.json` firmware `iwr1843_sar_lvds`, board `IWR1843_SAR`. The firmware `sarStats` probe answered every start (`satMon 1`, `saturatedChirps 0`, `lateIsr 0`, `missedChirpIsr 0`, `frameResync 0`, `availResync 0`); its pre-start counters equal the previous run's frames plus one in flight, so no other run touched the board between them.

| Run | cfg | Frames | Tap `adc_sent` | Duration | `adc_data.bin` / notes |
|---|---|---|---|---|---|
| R1 `20261012T145324Z_SAR_2ms_fmt1` | user `SAR_2ms_fmt1` | 78 | 78 | 40.3 s | 262,548,000 B = 78 frames; `sensorStart` 75 ms |
| R2 `20261012T145440Z_SAR_2ms_fmt1` | same, re-start | 5 | 5 | about 3 s | 16,830,000 B = 5 frames; full re-configure 14/14, `sensorStart` 5 ms, no power cycle |
| R3 `20261012T145616Z_SAR_2ms_fmt2` | user `SAR_2ms_fmt2` | 32 | 32 | 16.8 s | 107,712,000 B = 32 frames; `chirp_meta.csv` 8160 rows (= 32 x 255) all valid |
| `20261012T151257Z` (post-fix) | `SAR_2ms`, dataFmt 1 | 28 | 28 | 14.8 s | saving off |
| `20261012T151342Z` | `SAR_2ms`, dataFmt 1 | 114 | 114 | 58.7 s | saving off |
| `20261012T151449Z` | `SAR_2ms_fmt2`, dataFmt 2 | 197 | 196 | 101.0 s | saving off; `records_valid=50235` (= 197 x 255), `records_invalid=0`, `records_other_run=0`; `sensorStop` 508 ms |
| `20261012T151635Z` | `SAR_2ms_fmt2`, dataFmt 2 | 45 | 45 | 23.5 s | `adc_data.bin` 151,470,000 B = 45 x 3,366,000 B, `exact`; `chirp_meta.csv` 11,475 rows (= 45 x 255), all `record_valid=1`, `adc_complete=1`, `late=0`; `LVDS_Raw_0.bin` 154,925,680 B |

`LVDS_Raw_0.bin` is expected: that run's `session.json` has `output.save_raw_lvds: true` (the other three have false), and its size equals 106,405 packets x 1,456 B payload. Run names of the last four are `<UTC>_IWR1843_iwr1843_sar_lvds_<stem>` (Saved-mode starts).

Anomalies, none failing a pass criterion: in run `151449Z` the dca counted 197 frames but the tap sent 196, and `sensorStop` took 508 ms against 97 to 104 ms elsewhere; HYPOTHESIS: the last frame completed while the stop was closing the tap (not tested; no file was saved). No Quick-setup run exists in `runs/gui/`, and the board's chirp counters show no run between these four, so the Quick-setup check the user reports has no driver run on record; the user's report stands but its evidence is not in the logs. The "validate" step and the live ADC views were judged by the user and are not in the logs (screen not captured).

### Interpretation

- **Our cascade build runs.** The `awr2243_cascade_ddm` image built from `firmware_dev` is flashed and streams gap-free in the GUI run (163 frames, 0 missed). `fw verify` returned `skipped`, so the image identity was not read back from the board; the flash result is the user's report plus the printed sha256, not a pasted log. The scripted `cascade_serial_check.py` was not used (it would have needed another power-up).
- **Range-CFAR guard on the cascade DDM image (controlled).** The failing and passing cfgs differed only in guardLen (2 vs 0) and each run followed a user power-cycle, so for averageMode 3 the guard is the cause of the `sensorStart` hang. Other values (guardLen 1, guardLen 2 with another averageMode) are untested; whether they hang is a HYPOTHESIS, discriminated by running guard 1, and guard 2 with another mode. The GUI now reports any range guardLen > 0 on the DDM variant as an error (`cfar_ddm_range_guard`, `b982f27`), which is stricter than the evidence.
- **Once-per-power-up re-configure.** After this GUI has configured the cascade, a Start that would send the cfg again now asks for confirmation ("accepts a cfg once per power-up; power-cycle it first"), and is bypassed with skip-cfg (`b982f27`; user: the warning appears in both cases checked). This is a guard against the known behaviour in the GUI bench validation section, not a change in it.
- **Closing a loop on the 2026-10-07 bench.** The exact 134-frame capture agrees with the earlier exact DCA1000 captures (A2/A3 above) and adds the GUI-initiated Stop from the Point cloud tab.

### Caveats

- One run per item; the 134-frame DCA capture is about 13 s, not a soak.
- Frame counts and verdicts come from the session record and the run logs as triaged at the time; this pass did not re-open the run directories.
- The GUI behaviour checks (config list, overwrite, probe rows) are not performance numbers.

## Firmware key, driver limits and identity check, 2026-10-08

Measured and checked at `ced49f7`. Values were recorded in the close-out notes and bench log at the time (local working logs, not in this repo) and in the run directories named below under `runs/gui/` (gitignored, not in the repo).

### What the driver now enforces

- **Mandatory `firmware` key** in every system JSON (schema version stays 2). A file without it is refused, naming the key, the board's firmware list and the fix; `tools/migrate_config_v1_to_v2.py --add-firmware [--in-place|--check]` adds it (inferred from the board). All 40 shipped `config/system/*.json` carry it. A firmware the board does not list, or `IWR1843` + `iwr1843_sar_lvds` (needs board `IWR1843_SAR`), is an error.
- **Error-level limit checks** (`8d64b06`), read from `config/firmware/<fw>.json` `limits.<board>` and `config/limits/host.json`, with the same rule `code` as the GUI validator (`radar_gui/cfg/validate.py`): TX/RX counts, band, slope, sample rate, chirp cycle, loops, frame period, ADC buffer, L3 cube, LVDS rate, required/forbidden commands, and others. `--validate --json` prints one JSON object (`ok`, `errors`, `warnings`, `notes`, `frame`, a `metrics` subset), exit 0 or 1. **GUI-only exclusions:** the MIMO / chirp-pattern rules (`subframes_unsupported`, `chirps_span_profiles`, `bpm_unsupported`, `tx_pattern_invalid`, `tx_not_in_channelcfg`), `lvds_fmt_unsupported` and the `cfar_*` rules are not in the driver, so the GUI may reject a config the driver accepts.
- **Identity probe** (`53ac14f`): before any cfg is sent, `Radar::configure` queries the board (`version`, and `sarStats` to tell demo from SAR) and compares the reply with the named firmware, per `runtime.firmware_check`: `auto` (default; a mismatch is fatal, nothing is sent, status `firmware_mismatch` with a flash hint), `warn` (mismatch is a warning), `off` (nothing sent). No reply is a warning and the run continues; a once-per-power-up board without `once_safe` (the cascade) is skipped. `--validate` never opens a port.

### Test evidence

| Check | Result | Source |
|---|---|---|
| ctest | 27/27 passed at `ced49f7`, driver sha256 `8f6d611d...ab922` | close-out run at `ced49f7` |
| pytest | 1086 passed, 0 skipped (parity test ran) | same |
| Driver vs GUI validator parity (`tests/test_validate_parity.py`) | `ok` and error-code sets equal on all 40 shipped system configs and the 33 seeded-bad cases (`tests/fixtures/parity/`), excluding the GUI-only codes above | commits `8d64b06`, `15ce8c3` |
| Missing key | Copy of a shipped JSON without `firmware` -> exit 1, message names the key, `Board AWR2243_CASCADE supports: cascade_ddm`, and the migration command | close-out check |
| Migration check | `--add-firmware --check` on `config/system`: nothing missing | Rebuild 2 |

### Bench evidence (IWR1843, stock SDK 3.6 demo, unattended overnight)

| Run | What was run | Recorded result |
|---|---|---|
| `runs/gui/20261008T021409Z_overnight_tlv/` | Driver, 30 s serial TLV, identity `auto` | `firmware: match expected=demo found=platform=xWR18xx sdk=03.06.02.00 device=IWR18xx non-secure ES 02.00`; 299 frames, 0 missed, ~10 Hz; `serial_data.bin` 150048 B replays to 299 frames, 16-20 points each (mean 18.0) |
| `runs/gui/20261008T021450Z_overnight_mismatch/` | Shipped SAR system JSON copy (expects `iwr1843_sar_lvds`) against the demo image | Exit 1 after only the `version` and `sarStats` queries; `firmware: mismatch expected=iwr1843_sar_lvds ...`; no cfg line sent. Board fine afterwards (`..._overnight_tlv_after/`, 10 s, match, ~98 frames) |
| `runs/gui/20261008T021530Z_IWR1843_demo_tlv_default/` (GUI `runs/gui/20261008T021516Z_overnight_gui/`) | GUI-started 20 s run, **before** the fix | 202 frames but missed = 4294967196: a backward frame-number jump (100 to 1; the board counter restarted after `sensorStart`, stale bytes from the previous run at port open) was counted as a u32 wrap |
| `runs/gui/20261008T025223Z_IWR1843_demo_tlv_default/`, `runs/gui/20261008T025240Z_IWR1843_demo_tlv_default/` | Two back-to-back GUI-started 15 s runs at `ced49f7` (fix `a638392`: a backward jump is a restart, 0 missed; stale input flushed at init) | Both exit 0, 151 frames each, `serial.missed` 0, no "jumped"/"restart" lines, `firmware_check` verdict `match`; `serial_data.bin` 72680 and 71336 B |

Context line only (Rebuild 2b, replay benchmark `ctest -C bench -L bench` at `ced49f7`, median ns/byte): converter 0.187, `drv_clean` 0.303, `drv_drop_1pct` 0.303, `drv_save` 0.608. This is a software replay benchmark, not a hardware streaming rate, and it is not an A/B of this milestone.

### Interpretation

The driver and the GUI validator now agree on every error code they share, on the shipped configs and on the seeded-bad corpus, and a wrong image on the IWR1843 is caught before any cfg is sent. The backward-jump counter bug was real (one GUI-started run reported 4294967196 missed) and did not recur in the two runs after the fix. The same bug was not seen in the direct driver runs, so it appears tied to a run starting right after another on the same port.

### Honest caveats

- The bench runs were **unattended** (an overnight batch), not a human at the bench, and each is one run. The two post-fix runs are a pair, not a statistical sample.
- Only the **IWR1843 demo** identity is bench-recorded. `iwr1843_sar_lvds`, IWR6843/ODS and IWR1443 entries are derived from firmware source. The cascade `once_safe` stays **false** (its version-reply capture was not done), so the cascade check is skipped.
- The **DCA1000 was not reachable** (192.168.33.180 did not answer ping and the board ran the stock demo without LVDS), so there was no ADC run in this session.
- The GUI Live source was accepted through the GUI-backend run (it drives the same C++ driver), not as a separate serial-source session.
- dataFmt 2 (`adc_sar_meta`) and the SAR image were later bench-verified; see "Core driver on the SAR image" above.
- The driver checks error-level rules only; warnings stay in the GUI (user ruling, 2026-10-07).

## RX-gain sweep on the IWR1843 SAR LVDS firmware (Tune tab), 2026-10-15

One real sweep with the radar_gui Tune tab (`radar_gui/tune.py`, commits `7b499e0`..`809c985`), IWR1843BOOST R2101050 on `iwr1843_sar_lvds` + DCA1000, config `SAR_ugv_fmt2`, after a user power cycle, bench scene (no placed reflector). profileCfg `rxGain` 24..48 dB step 2 (board min/max/step from the firmware descriptors, `66966df`), 8 frames per step, 3 dB margin; each step is a full reconfigure by a fresh driver run (a profileCfg-only change then `sensorStart` is rejected after `sensorStop`; `7b499e0`). Run dir `runs/gui/20261015T222501Z_tune_radar37_sweep_SAR_ugv_fmt2` (gitignored; `tune.csv`, `tune.json`, per-step folders); shot `docs/images/gui/tune_real_iwr1843.png` (real board, not masked like the fake-driver tab shots).

| Gain (dB) | Sat chirps / 391 | Clipped | ADC peak | Peak dBFS (16-bit) | Strongest return (dB) | Dev vs 1 dB/dB | Noise (dB) | SNR (dB) |
|---|---|---|---|---|---|---|---|---|
| 24 | 0 | 0 | 112 | -49.3 | 81.1 | 0.00 | 55.3 | 25.8 |
| 28 | 0 | 0 | 163 | -46.1 | 84.9 | -0.21 | 58.7 | 26.3 |
| 32 | 0 | 0 | 236 | -42.9 | 88.8 | -0.29 | 62.4 | 26.4 |
| 36 | 0 | 0 | 349 | -39.5 | 92.6 | -0.56 | 66.3 | 26.3 |
| 40 | 0 | 0 | 594 | -34.8 | 96.7 | -0.46 | 69.8 | 26.8 |
| 44 | 0 | 0 | 1161 | -29.0 | 100.6 | -0.51 | 73.9 | 26.7 |
| 48 | 0 | 0 | 1861 | -24.9 | 104.6 | -0.53 | 77.9 | 26.7 |

All 13 steps (24..48 step 2) are in `tune.csv`; the rows above are every fourth step. The strongest return sits at 35.9 m in every step. Suggestion: **44 dB**, limited by the sweep top ("no compression up to 48").

### Interpretation

- No compression or saturation was reached up to the chip maximum of 48 dB on this scene: 0 saturated chirps and 0 clipped samples at every step; the strongest return tracks gain within 0.6 dB of the 1 dB/dB line.
- SNR is flat (25.8-26.9 dB) because the noise floor rises about 1 dB per dB of gain too. Noise ahead of the gain stage dominates here, so on this scene gain only trades ADC headroom (24.9 dB below full scale at 48 dB); it does not improve SNR.
- The 44 dB suggestion is the rule's 3 dB margin off the sweep top (48), not a measured limit.
- Full scale is taken from `adcCfg` (16-bit container, +-32767; `docs/developer/radar_notes.md#hpf-rxgain-and-adc`, `e9fbc88`, `809c985`), medium confidence; the effective ADC resolution may be lower, which would shrink the real headroom.

### Caveats

- The "saturation-vs-gain" item left open in the SAR LVDS firmware section is partially covered. No saturation was reached, so the saturation onset is still unmeasured; it needs a closer or stronger reflector.
- One bench scene, one board, one config, one sweep, 8 frames per step; no repeat, so the 0.6 dB deviation spread is not characterized.
- The strongest-return peak is the scene's own strongest bin outside the DC/leakage exclusion, not a calibrated target.

## Release readiness: Docker image and test suite (2026-10-08)

Measured 2026-10-08 on `release/v2.0`; values were recorded at close-out for the test-suite audit (`19f949e`) and the Docker image (`d77b9f5`, `3e6526d`, `12a5fd4`) (local working notes, not in this repo). Each is a single run.

| Item | Result |
|------|--------|
| Docker image `cpsl-ti-radar:dev` | about 500 MB (501 MB, then 500 MB after the numpy fix) |
| ctest inside the image build | 27/27 passed (re-run fresh at close-out) |
| Demo mode (`127.0.0.1:8090`) | `/` returned HTTP 200 with the GUI HTML; `/api/cfgs` returned the shipped cfgs |
| Real-board (`hw`) mode | **not verified on hardware** |
| `uv run pytest` (full) | 1085 passed, 53.2 s on a quiet box (80 s under concurrent load) |
| `uv run pytest -m "not slow"` | 1002 passed, 83 deselected, 20.2 s (`slow` marker added in `19f949e`) |
| ctest, Release, host build | 27/27 passed, 20.6 s |
| Line coverage, `radar_gui/` + `tools/` | 88% (6743 statements); lowest per file: `gui_shots` 17%, `__main__` 38%, `migrate_config` 52% |

Interpretation: the image builds, passes the C++ suite and serves the GUI in demo mode, and the Python suite is fast enough to run on every change. The audit found the large test counts come mostly from per-file cfg round-trips that cost milliseconds each and pin real shipped files, so little time was to be saved by cutting; the user chose to keep all tests (no cut commit). Caveats: the `hw` profile (device and port pass-through, DCA1000 capture writing under host `runs/`) has only been checked as compose configuration, not with a board attached, so the image is release-ready for demo use only until a bench check is done. The 20.2 s `not slow` time is the quiet-box figure; the audit's 37 s was measured under load.

## Firmware bench status

Moved here from `docs/firmware.md` (which keeps only the how-to), as of the 2026-10-12 sessions above. The authoritative per-firmware record is the `[[bench]]` entries in `firmware_dev/projects/<fw>/project.toml` (visible with `./fw list` once `firmware_dev` is checked out); this section is a prose summary of them, not a second record.

### `awr2243_cascade_ddm`

Record: `[[bench]]` in `firmware_dev/projects/awr2243_cascade_ddm/project.toml` (pass, 2026-10-12). The cascade runs **our** build (image sha256 `9bf7f418076a1f71720c444c173aaa388a5210326bb031925ba38666af30c770`): the user flashed it with `fw flash` ("Cascade finished successfully"), `fw verify` was `skipped` (exit 0; `once_safe` false), and one configured GUI/driver run on the next power-up (run `20261012T141433Z_bench_cascade`) got `sensorStart` DONE and 163 frames, 0 missed (section "Bench session 2"). TI's prebuilt image stays the fallback (`./fw flash awr2243_cascade_ddm <port> prebuilt`). No identify probe was confirmed, so `identify.level` is unchanged.

### `iwr1843_sar_lvds`

- **Current image:** sha256 `a06ee615b56b12282f2fe9b4a02bb556ceaa81a1b72176e2060cd9209a070924` (prompt `mm_sar_lvds:/>`): flashed with `./fw flash`, `fw verify` pass, bench check accepted (`pass` record dated 2026-10-10; "Bench session 1" tests 2 to 4).
- **Earlier image:** `53948f4d...` (`partial` record dated 2026-10-06) ran a 10 min no-reflector soak: 299,880 chirps, 0 gaps, 0 missing, 6.66 MB/s (section "IWR1843 SAR LVDS firmware ... Set A").
- **Driver support:** the `IWR1843_SAR` board descriptor and `config/system/IWR1843_iwr1843_sar_lvds_SAR_2ms.json` capture this image in `lvdsStreamCfg` dataFmt 1; the image has no TLV/data UART. The driver also decodes dataFmt 2 (`adc_sar_meta`: per-chirp metadata, `SAR_2ms_fmt2.cfg`), bench-verified against `sar_parse.py` and in a 600 s live soak (section "Core driver on the SAR image").
- **Not yet verified** (needs a reflector and the GUI): phase continuity, tuned gain/HPF point, boundary steps/Tb, ADC full scale, saturation-vs-gain. This list said "I/Q order" too when it was kept in `docs/firmware.md`; that item is now settled on the IWR1843 by finding 3 (stock demo capture; the SAR image shares the descriptor). The Tune-tab sweep above touches gain and ADC headroom on this image but placed no reflector.
- **Bench scripts:** `./bench <check>` (from `firmware_dev/`) runs the project's `tools/bench_run.py`; the checks are tabled in its `docs/bench_bringup.md` sections 6 (common), 7 (no-reflector) and 8 (reflector); section 5 is the first bring-up check (`./bench_check` flow), `docs/bench_check.md` the short gated version, and the tuning procedure and four checks are `docs/tuning_guide.md` sections 5 and 6.
