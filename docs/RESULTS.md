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

## IWR1843 SAR LVDS firmware (`iwr1843_sar_lvds`), firmware-10 Set A + 10-min no-reflector soak

Bench run 2026-10-06, one IWR1843BOOST with DCA1000, example cfg (`sar_example_2ms.cfg`, default gain and HPF, `analogMonitor`/CQRxSat on), no reflector in the scene. Every value is read from the firmware-10 directive Log (Set A table and soak entry; `.friday/active/harness/plans/directives/firmware-10.md`) and from the soak artifacts `/tmp/bench_run/soak_summary.txt` and `/tmp/bench_run/soak_summary.json` (capture `/tmp/bench_run/soak.cap`, `/tmp/bench_run/soak.cap.sarstats.json`; not tracked in the repo). Set A rows use `/tmp/bench_run/long.cap`, `bytes.cap`, `bsize*.cap`, `fmt1.cap`, `fmt4.cap` and the like in the same folder. Firmware_dev commits: flash image built at `946f48d`; Set A run at `314ec2e`; soak run at `778f806`.

**Verdict: firmware-10 Set A + 10-min no-reflector soak: GO on G1, G2, G5 and the G7 non-reflector rows; G3 phase continuity, G4 tuned point/SNR/ADC bits, G6 boundary/Tb, saturation-vs-gain, I/Q order are NOT EVALUATED (firmware-18).**

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

Not measured (firmware-18, needs a placed reflector): tuned gain/HPF point; clipped-chirp count; ADC bits; phase step at boundaries (G3); minimum clean Tb (G6); saturation-vs-gain sweep; I/Q order. The soak entry lists these as `NOT EVALUATED`.

### Caveats

- The soak and the 60 s capture each contain 1 invalid record, the tail hole where the capture stops mid-packet. The pass criteria tolerate it; it is not a mid-stream loss (0 UDP gaps, 0 wholly missing).
- dt was measured with no reflector placed and default gain/HPF, so it says nothing about timing under a tuned or saturating scene.
- Set A was measured on the pre-firmware-17 image (sha256 `53948f4d...4267a`); the image is not re-verified after firmware-17.
- Phase-like numbers taken from reflector-less data are indicative only and are not reported here.
- The `dataFmt 4` block contents (CP, sigImg, satMon) are not parsed; only packet size, HSI id, gaps and counters were checked.

## GUI bench validation (gui-09), IWR1843 + DCA1000 and AWR2243 cascade

Bench session 2026-10-07 (host `cpsl-gmk-6`, Release driver sha256 `f34182371d0b...a4e6`, repo HEAD at start `fc385db`), driven from the `radar_gui` Run and Live tabs by a human at the bench. Every value below is read from the gui-09 directive Log (`.friday/active/harness/plans/directives/gui-09.md`) and the run directories named there under `runs/gui/` (gitignored, not in the repo). IWR1843 = XDS110 `R2101050` running the SDK 3.6.2 demo image; DCA1000 at 192.168.33.180. Each item was **one run** (no repetitions), and pass/fail was judged largely from the numbers the user read off the GUI; serial-only runs write no files, so those counts have no file to cross-check.

| Item | What was run | Board / firmware | Recorded result | Verdict |
|---|---|---|---|---|
| A1 | Run tab, `bench_1843_tlv` (GUI-saved copy of `IWR1843_demo.cfg`), serial TLV only | IWR1843, SDK 3.6.2 demo | First attempt: 0 frames, `sensorStart` replied "Full configuration must be provided before sensor can be started the first time". After the calibData fix (`dbde0ad`) it streamed (run `20261007T191802Z_bench_1843_tlv`); frame count not recorded in the Log | PASS after fix |
| A2 | Run tab, shipped `front_radar_IWR1843_stress_test_baseline.json` (DCA1000, `log_level debug`), ~64.6 s | IWR1843 + DCA1000 | dca frames 646 (10 Hz); dropped 0, kernel drops 0, incomplete 0; `adc_data.bin` 325,584,000 B = 646 x 504,000 B, verdict `exact`; `LVDS_Raw_0.bin` 325,608,192 B (run `20261007T192639Z_...baseline`) | PASS |
| A3 | Configure -> `bench_1843_dca` (10 m / 3 m/s / 10 Hz, LVDS on; 256 chirps x 128 samples x 4 RX = 524,288 B/frame), Serial TLV + DCA1000 + save ADC, ~20.1 s | IWR1843 + DCA1000 | dca frames 200, dropped 0, kernel 0, incomplete 0; serial frames 200, missed 0; `adc_data.bin` 104,857,600 B = 200 x 524,288 B, verdict `exact` (run `20261007T193806Z_bench_1843_dca`) | PASS |
| A4 | During the A3 run: Live -> Serial on the same ports; Run tab Start | IWR1843 | Refused "Ports busy: radar in use by driver"; Run Start greyed while running (user-reported) | PASS |
| A5 part 1 | Run tab, shipped `radar_0_AWR2243_cascade_serial.json`, fresh power-up | AWR2243 cascade, `cascade_ddm` | 630 frames, 0 missed (~63 s at 10 Hz); on Stop "driver did not stop after SIGINT; killed (SIGKILL)" (run `20261007T194842Z_...cascade_serial`) | PASS with defect (D10) |
| A5 part 2 | `bench_cascade` (GUI-generated, user-edited), power-cycle first | cascade | 1024 chirps/frame (`frameCfg 0 7 128 ...`): every line Done except `sensorStart` ("no Done within 5000 ms"), 0 frames. Retry `bench_cascade_revA`, 256 chirps (`frameCfg 0 7 32 ...`), 128 samples, 100 ms: streamed, Stop clean (runs `20261007T200759Z_bench_cascade_revA`) | FAIL, then PASS at 256 chirps |
| B1 | Live -> Serial, IWR1843, `IWR1843_demo.cfg`, dump on | IWR1843 demo | `configuring i/N` -> `streaming`; header 10 Hz; points visible; Stop/Start reconfigures and streams. Dumps `runs/gui/dumps/IWR1843_2026-10-07T20-14-44.bin` (427,008 B) and `...T20-17-17.bin` | PASS |
| B2 | Live -> Serial, cascade | cascade | Streamed; Stop -> "already configured" tick -> restart streams; restart without tick -> `cfg_failed` with power-cycle notice; power-cycle while running -> auto reconfigure and stream | PASS |

### Findings

- **A1 root cause (isolated).** The board and CLI were alive (`version` reported mmWave SDK 03.06.02.00); the driver reproduced 0 frames from the command line, so it was not a GUI-launch problem. The flashed SDK 3.6.2 demo requires `calibData` as part of the "full configuration", but the IWR1843 board descriptor listed `calibData` in `skip_commands` (a leftover for older firmware). Removing it (`dbde0ad`) fixed the run on the bench. The same missing `calibData` was found in `Iwr18xx_DCA_mmStudio_original.cfg` and fixed in `70668a9`; that cfg was not run on the bench.
- **DCA1000 path.** A2 and A3 are exact frame multiples with 0 drops and 0 kernel drops. They agree with the earlier core-16 bench (section "Bench pass, reworked v2 driver, IWR1843") but are one run each. A2 ran ~64.6 s rather than the planned 60 s, so the criterion was judged as frames = 10 Hz x duration (646 / 64.6 s). A3 ran ~20.1 s, not 60 s, so it shows 200 frames at 10 Hz but nothing about a longer soak.
- **B1 header rate.** The header showed 10 Hz at the cfg rate of 10 Hz. This is the user's reading of the live header; no Gaps/Errors values were written to the Log, so "0 gaps/errors over 60 s" is not claimed here.
- **Cascade 256 vs 1024 chirps.** The GUI generator had chosen 128 loops (1024 chirps) for 15 m / 5 m/s / 10 Hz and only warned; the cascade then failed at `sensorStart`. With 32 loops (256 chirps) it worked. Besides the chirp count, the failed and working cfgs were otherwise the same family but several parameters differed from the shipped cfg (see the Log), so the bench by itself is one failing and one passing run and does not isolate the chirp count. The cause is explained by the Researcher memo `docs/research/gui_cascade_chirp_limit_2026-10-07.md` (`f48b1e5`): the Doppler FFT size is bounded by the 82 KiB DSS L2 heap, so for 6 TX / 8 RX the chirps per frame must be <= 256, and the 2.53 MiB L3 radar cube is a second limit for large range-bin counts. The memo derives this from sources; its confidence is "medium" and a 384-chirp bench check (`frameCfg 0 7 48 ...`) was not run. The GUI now treats >256 chirps on the full cascade as an error and caps the generator at 256 (`3a032e0`). The C++ driver does not read these limits.
- **Replay fixtures** (`1e977d4`, `tests/fixtures/replay/`): 20 frames of the IWR1843 SDK 3 capture (5,760 B, 7 points per frame) and 20 frames of the cascade capture (25,952 B, 49-68 points per frame, no TLV 12), with 7 tests in `tests/test_radar_gui_replay_bench.py`. The cascade capture holds 177 frames in total, so with the CFAR settings used (12 / 10 dB) the cascade does produce points.
- **GUI lag (D8/D9).** The user found the GUI "a little laggy" in the A2 run. In a fake-driver measurement at the A2 rate (10 s window, headless Firefox) log re-renders fell from ~66/s to 5.5/s and time in log rendering was 7-10x lower (`fb15de0`). The cause of the user's lag was not isolated and the bench re-check of responsiveness is not recorded. After exit the stream cards now show the average rate (frames / duration) instead of "0.0 Hz".
- **Fixed GUI defects** (Log, commits): D1 header followed the Live mock during a driver run, D2 plain "0 frames received" verdict, D3 screenshot runs wrote into `runs/gui/`, D4 source ports restricted to by-id / `ttyACM` / `ttyUSB` (`400398c`); D5 retry after `cfg_failed` on repeatable boards (`400398c`); D12 `wrong_firmware` header colour (`914197b`); D13 test hang mitigations (`9528964`, hang itself not reproduced); D15 Source card "Restart" only for the running board/cfg (`26981fe`); D16 replay dialect select (`86b48f6`); D17 tap-test flake (`ebfec94`).

### Negative results and caveats

- **The cascade accepts one cfg per power-up.** Every cascade item that sends a cfg needs a fresh power cycle; a failed `sensorStart` (A5 part 2) leaves the board unusable until the next power cycle. Restarting a driver run on the cascade fails for the same reason (D14); the fix (`--skip-configure`) is in gui-36 and needs a driver rebuild.
- **Stop needed SIGKILL on the cascade (D10) and is not fixed.** The driver sends `sensorStop` and waits 5000 ms for a `Done` the cascade never sends, while the GUI's SIGKILL grace is `max(5 s, 2 x period)`, so the GUI killed the driver in A5 part 1. The fix is a C++ driver change (skip or shorten `sensorStop` on once-per-boot boards) that lands with the post-bench driver rebuild; until then a cascade driver run ends with SIGKILL (the stream had been received; whether the run's logs flushed was not checked).
- **"No points" during cascade driver runs was display-only.** During a driver run the GUI did not display driver point clouds at all (header Points showed "-"). The replay fixture shows the cascade capture does contain points. Live following of a driver run is gui-36 (`41bc977`), which needs a driver built with `--tap-fd`; that rebuild is pending, so it is not bench-verified.
- **Cascade firmware check is off.** The Source card shows "cascade_ddm (not checked)" because the cascade identify probe is not yet safe; it stays off until gui-33 Step 7. The IWR1843 firmware check (gui-33 Step 1, `272e017`) showed "demo" in B1.
- **Not run:** a 60 s soak of A1/A3/B1 (shorter runs were used), the live ADC-view check (moved to gui-07), the optional 384-chirp cascade check, and any reflector-based measurement. The B1/B2 "points visible" judgements are user observations; the Log has no screenshot paths for them.
