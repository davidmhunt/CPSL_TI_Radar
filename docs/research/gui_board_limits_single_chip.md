# Single-chip board limits (IWR1443, IWR1843, IWR6843): verification of `radar_gui/cfg/limits.py`

**Date:** 2026-10-06
**Memo:** docs/research/gui_board_limits_single_chip.md

## Question as asked

gui-13 Step 1: for IWR1443, IWR1843 and IWR6843, check every limit in `radar_gui/cfg/limits.py` (max slope, max/min sample rate, min idle, numLoops, ADC buffer, L3 radar cube, LVDS per-lane rate, DCA1000 headroom, duty cycle, 76-81 / 60-64 GHz bands, TX/RX counts) against TI documents and the firmware/SDK sources. Per firmware (out-of-box demo, demo+LVDS, DCA1000 raw streaming, SAR), separate what the firmware enforces from what the silicon allows. Centerpiece: a verification table the user can audit. Working note, exempt from rule 16. Out of scope: the cascade (gui-13 Step 2), editing code or descriptors (Step 3).

## TL;DR

Of the limit kinds checked, five have wrong or mis-scoped values in `limits.py`: max slope for IWR1843 (266 is the AWR2243 figure; the IWR1843 limit is **100** MHz/us) and IWR6843 (**250**), L3 radar cube (IWR1843 and IWR6843 are **swapped**: 1843 = 1024 KB, 6843 = 768 KB; IWR1443 = up to 384 KB, not 256), max sample rate for IWR1443 (**18750** ksps complex-1x, not 12500), DCA1000 headroom (800 Mb/s exceeds TI's own theoretical maximum of ~706 Mb/s, and at the configured 100 us packet delay the ceiling is ~105 Mb/s), and "min idle 2 us" (TI documents a minimum **chirp cycle** of 15 us xWR1xxx / 13 us xWR6843, not a standalone idle minimum). TX/RX counts, bands, numLoops 255, LVDS lanes and 600 Mbps/lane are confirmed. The demo firmware enforces far less than the silicon (it never range-checks slope, rate or idle; those are the BSS radar firmware's job), so the GUI is the only early check for most of them. Unverifiable from files here: SDK 2.x (IWR1443) demo behaviour, the IWR1443 ADC-buffer layout, the duty-cycle heuristic.

## Evidence

**Sources and how they were read.** Abbreviations used in the table (all line numbers read this session):

- `RL` = mmWave SDK 3.6 `packages/ti/control/mmwavelink/include/rl_sensor.h` (also `rl_device.h`). Read from an extracted SDK 3.6 copy (the installer is `firmware_dev/downloads/mmwave_sdk_03_06_02_00-LTS-Linux-x86-Install.bin`; the symlinked `/opt/ti` tree is not present on this host). Its line numbers match those cited by `firmware_dev/projects/iwr1843_sar_lvds/docs/sar_feasibility.md` for 3.6.02 (:653, :665, :710, :742, :958, :983), so the two copies agree.
- `RFP` = `packages/ti/demo/utils/mmwdemo_rfparser.c`; `CLI`/`MSS` = demo `mss/mmw_cli.c`, `mss/mss_main.c` (the xwr18xx/xwr68xx copies are in `firmware_dev/projects/ti_stock_demos/build/sdk/packages/ti/demo/`); `DPC` = `ti/datapath/dpc/objectdetection/objdetdsp/src/objectdetection.c`; `MAK`/`SYS` = `packages/ti/common/mmwave_sdk_xwr{14,18,68}xx.mak` and `sys_common_xwr{14,18,68}xx.h`.
- `DS14` IWR1443 SWRS211C (Oct 2018), `DS18` IWR1843 SWRS228B (Sep 2024), `DS68` IWR6843 SWRS219F (Apr 2025), `DCA` DCA1000EVM User's Guide SPRUIJ4A (2019), `SAR` = `iwr1843_sar_lvds/docs/sar_feasibility.md` / `sar_cfg_guide.md` (project docs, not TI).
- Not available here: mmWave SDK **2.x** sources (the IWR1443 shipped demo is a prebuilt `Firmware/IWR_Demos/xwr14xx_mmw_demo.bin`; the DCA image `Firmware/DCA1000_Streaming/iwr_raw_rosnode/firmware/xwr14xx_lvds_stream.bin` has TI `lvds_stream` source next to it). IWR1443 rows therefore rest on the datasheet, the SDK 3.6 `xwr14xx` platform files and the 3.6 `rl_sensor.h`; they are device facts, but "what the SDK 2 demo enforces" is unverified. The 2nd-gen (AWR2243) interface-control document was read only to rule it out as the source of `266 MHz/us`.

**Firmware codes** used in the Notes column: **D** out-of-box demo (stock mmw demo: SDK 3.6 for 1843/6843, SDK 2 prebuilt for 1443); **DL** demo + `lvdsStreamCfg` (1843/6843 demo; 1443 unverified); **R** DCA1000 raw `lvds_stream` (TI TestFmk demo, no DSP/DPC); **S** `iwr1843_sar_lvds` (MSS-only, DSP halted).

### Verification table

Boards: 14 = IWR1443, 18 = IWR1843, 68 = IWR6843. "Current" is `limits.py`. Level = severity now; "->" is a recommendation for the user to accept or reject.

| # | Limit | Bd | Current | Verified | Source | Conf. | Verdict |
|---|-------|----|---------|----------|--------|-------|---------|
| 1 | n_tx | 14 | 3 | 3 | DS14 Table 3-1; `SYS14:454` | high | confirmed |
| | | 18 | 3 | 3 (3 simultaneous only in 1-V LDO-bypass mode; max 2 per chirp) | DS18 Table 5-1 + note (2); `SYS18:299`; `RL:925` | high | confirmed |
| | | 68 | 3 | 3 (max 2 per chirp) | DS68 Table 5-1; `SYS68:299`; `RL:925` | high | confirmed |
| 2 | n_rx | all | 4 | 4 | DS14/18/68 feature tables; `SYS_COMMON_NUM_RX_CHANNEL`=4 (`sys_common.h:70`) | high | confirmed |
| 3 | band | 14,18 | 76-81 GHz | 76-81 device; **a sweep must lie in 76-78 or 77-81** | DS14 §5.7, DS18 §7.7; `RL:667` | high | confirmed + sub-rule added |
| | | 68 | 60-64 | 60-64 (DS); DFP also lists 57-60.75 or 60-64 sweeps | DS68 §7.9; `RL:668` | high | confirmed + sub-rule added |
| 4 | max slope | 14 | 100 MHz/us | 100 (code +-2072, LSB 48.279 kHz/us) | DS14 §5.7 "Ramp rate"; `RL:710` | high | confirmed |
| | | 18 | **266** | **100** | DS18 §7.7 "Ramp rate 100 MHz/us"; `RL:710`. 266 is the AWR2243 figure (ICD rev 2.23 §1.1) | high | **corrected** |
| | | 68 | **266** | **250** (code +-6905, even only, LSB 36.21 kHz/us) | DS68 §7.9 "Ramp rate 250"; `RL:713` | high | **corrected** |
| 5 | max sample rate (complex 1x, regular ADC mode) | 14 | **12500** ksps | **18750** (real/complex-2x 37500); low-power ADC mode 9375 | DS14 §5.7; `RL:742,750` | high | **corrected** |
| | | 18 | 12500 | 12500 (real/complex-2x 25000); low-power ADC mode (`lowPower 0 1`) 9375 | DS18 §7.7 (IF 10 MHz); `RL:757` + low-power rows | high | confirmed |
| | | 68 | 12500 | 12500 (low-power mode same) | DS68 §7.9; `RL:743,757` | high | confirmed |
| 6 | min sample rate | all | (absent) | 2000 ksps | `RL:742-743` | high | confirmed (add row) |
| 7 | min idle | all | 2.0 us, warning | **no standalone idle minimum is documented**; idle 0..524287 x 10 ns. Documented limit is the **chirp cycle** (idle + rampEnd) >= **15 us** (14, 18) / **13 us** (68); +10 us if WDT on (xWR1xxx) | `RL:651-654`, `RL:4570-4573` | high (cycle), none (2 us) | **corrected** (replace with min chirp cycle) |
| 8 | numLoops | all | 255, warning | 1..255 (frameCfg), 1..255 per sub-frame (advanced); chirp indices 0..511 | `RL:958`, `RL:1066` | high | confirmed; level -> error (documented range) |
| 9 | ADC buffer (per chirp, all RX, 4 B/sample) | 14 | 16384 "half" | 16384 B is the **whole** buffer (`SOC_XWR14XX_MSS_ADCBUF_SIZE` 0x4000; profile limit "16 kB"). DS14 diagram says "2x16KB": ping/pong split unresolved | `SYS14:312`; `RL:728`; `RFP:982`; DS14 §6 diagram | low | unverifiable (16384 vs 8192) |
| | | 18, 68 | 16384 "half" | buffer 32768 B total; profile max 32768 (4 RX complex: 2048 samples); demo divides the **full** 32 KB by bytes/chirp, but ping and pong each hold `chirpThreshold` chirps, so streaming usable per chirp is 16384 (inferred) | `SYS18:306`, `SYS68:306`; `RL:728`; `RFP:982`; `ADCBuf.h:511-518`; `SAR` §(a) "inferred" | medium | confirmed as streaming limit; hard max 32768 |
| 10 | L3 radar cube | 14 | **256 KB** | **384 KB** max (radar data mem 128..384 KB in 64 KB steps; SDK 3.6 default 6 x 64 KB). Shipped SDK 2 image's split unverifiable | DS14 §6 Table 6-1; `MAK14:14,18-19` | medium | **corrected** (upper bound) |
| | | 18 | **768 KB** | **1024 KB** (SDK default 8 x 128 KB); DS18 CPU table says 1024; DS18 §8.3 footnote says "768 KB within 2 MB": conflict, SDK build value used | DS18 CPU table, Table 8-1 note; `MAK18:15,19`; `SYS18:304` | medium-high | **corrected** |
| | | 68 | **1024 KB** | **768 KB** (6 x 128 KB) | DS68 §1/§7.10 "Shared L3 768 KB"; `MAK68:15,19` | high | **corrected** |
| 11 | LVDS lanes | 14 / 18, 68 | 4 / 2 | 4 / 2 | DS14 §5.9.5; DS18, DS68 §7.10.4; `mmw_lvds_stream.c:154` (0x3); `lvds_stream.c:1527-1529` (0xF 14xx) | high | confirmed |
| 12 | LVDS per-lane rate | all | 600 Mbps | 600 is the **practical** ceiling: DCA1000 max 600; demo and SAR program 0x9 = 600. Silicon allows 900 (7 rates 150..900) | `DCA` §1 features; `MSS18:2912`, `MSS68:3322`; `rl_device.h:1001`; DS §LVDS rates | high | confirmed |
| 13 | LVDS capacity (not in limits.py) | all | (absent) | bytes/chirp `roundup256(Ns*Nrx*4+52)` <= `Tc*lanes*Mbps/8`; else "this configuration will not work" | `MSS18:372-381` (demo note) | high | add as error for D-L, S |
| 14 | DCA1000 Ethernet link | host | 1000 Mb/s | 1 Gbps port | `DCA` host PC configuration list ("1-Gbps Ethernet port") | high | confirmed |
| 15 | DCA1000 headroom | host | **800 Mb/s** | TI max 706 Mb/s at 5 us packet delay; 545 / 325 / 193 at 10 / 25 / 50 us. Fits $R \approx 11776\,\text{bit} / (d + 11.5\,\mu s)$; at the project's `packet_delay_us` = 100 this gives **~105 Mb/s** (derived, not TI) | `DCA` §10 Table 19; board JSON `dca1000.packet_delay_us` | high (table), medium (fit) | **corrected** |
| 16 | duty cycle | all | 0.9, warning | no TI duty-cycle limit. Real constraints: frame period >= chirps x Tc + inter-frame blank (typ. >= 300 us; +150 us if profile changes); frame period 300 us..1.342 s | `RL:978-987`; DS power use cases 25/50 % (DS18 Table 7-4) are test conditions, not limits | medium | 0.9 heuristic unverifiable; add frame-blank rule |

### What the firmware enforces versus the silicon

| Constraint | Silicon / BSS radar firmware (all firmwares) | Demo firmware (D, DL) | Raw R / SAR S |
|---|---|---|---|
| slope, sample rate, idle, rampEnd, band | Range-checked by the radar subsystem through mmwavelink; the demo itself checks **none** of them except slope >= 0 (`RFP:874-880`, unless `MMW_ENABLE_NEGATIVE_FREQ_SLOPE`) | same | same; S `sensorStart` rejects `channelCfg`/`adcCfg`/`lowPower` changes (docs/firmware.md) |
| ADC format | complex 1x and others allowed by silicon | 16-bit **complex only** (`RFP:724`, `RFP:966`); `adcbufCfg` chirpThreshold must be 1 (`CLI:819-821`) | R: ADC buffer size per SOC (`lvds_stream.c:1188-1211`) |
| chirps per frame | numLoops 1..255, indices 0..511 | unique chirps <= 32 (`RFP:782-784`); one valid profile used (`RFP:787`); advanced frame needs numOfBurst = 1 (`RFP:776`); Doppler bins = pow2roundup(chirps/TX) (`RFP:886-889`) | S: dfeDataOutputMode 1 only; >255 chirps via several identical chirp indices (`SAR`) |
| radar cube / L3 | n/a | cube + detection matrix must fit L3, else `DPC_OBJECTDETECTION_ENOMEM__L3_RAM_RADAR_CUBE` (`DPC:1817`) | not applicable (no DPC; S has DSP halted) |
| LVDS (DL, R, S) | 4 lanes (14) / 2 (18, 68), <= 900 Mbps | `numAdcSamples` >= 64, HSI header needed with SW session, single-chirp formats only, CBUFF minimum 64 B (`MSS18:360-410`); `CLI:1130` | S: dataFmt 2 exists only here (docs/firmware.md) |
| one chirp larger than ADC buffer | profile limit 32 KB (18, 68) | no check: `maxChirpThreshold` = 0 then `numChirpsPerFrame % maxChirpThreshold` (`RFP:982-1000`) divides by zero (read from source, not run) | R: not checked |

## Applicability to CPSL TI Radar

- **Fact (from TI documents and SDK source):** the corrections in rows 4, 5, 7, 10 and 15 are direct readings. Rows 4, 10 and 15 are cross-confirmed by two independent sources each (datasheet plus SDK constant, or TI table plus project JSON).
- **Severity recommendations (user decision):** raise to **error** the violations the API documents as invalid ranges (numLoops outside 1..255, slope code outside +-2072 / +-6905, sample rate outside 2000..datasheet max where the BSS rejects, sweep outside the allowed sub-bands, chirp cycle below 15/13 us) and, for D/DL, radar cube larger than L3 and LVDS bytes/chirp above lane capacity (the demo itself says these do not work). Keep **warning** for heuristics (duty 0.9, DCA headroom).
- **Per-board descriptor shape implied:** `max_slope_mhz_us` 100/100/250; `max_sample_rate_ksps` 18750/12500/12500 (plus `low_power_adc` factor 0.5 on 14/18); `min_sample_rate_ksps` 2000; `min_chirp_cycle_us` 15/15/13 replacing `min_idle_us`; `l3_radar_cube_bytes` 384K/1024K/768K, applicable only to firmware with a DPC; ADC buffer total 16384/32768/32768 with a per-firmware streaming ceiling (S and R: see below); `dca1000_effective_mbps` as a function of `packet_delay_us`.
- **Discrepancy outside limits.py (for the firmware loop):** `SAR` §(a) and `sar_cfg_check.py` allow **18750 ksps** on the IWR1843 by applying the generic xWR1xxx header text (`RL:742`, "15 MHz IF"). The IWR1843 datasheet lists IF 10 MHz and complex-1x 12.5 Msps (DS18 §7.7, `RL:757` 10 MHz table). The 18750 cap belongs to the IWR1443-class (15 MHz IF) only. HYPOTHESIS: on the IWR1843 a complex-1x rate above 12.5 Msps is accepted by the API but is outside the specified IF bandwidth; it is a firmware-docs fix, not a limits.py one, and is untested on the bench.
- **Firmware scoping:** L3 and `numAdcSamples` >= 64 rules apply only to D/DL; S has no DPC; IWR1443 D/DL/R rows are device facts only until SDK 2.x or a board test says otherwise. The 1843/6843 stock demo also supports `lvdsStreamCfg` (DL); whether the shipped IWR1443 SDK 2 demo supports it was not verified.

## Recommended Experiment

Bench checks (hardware, one board at a time, claim in `status.md`); each is a one-line cfg change on a known-good cfg, accepted/rejected at the CLI:

1. **1843 sample rate:** `profileCfg` with 15000 ksps complex 1x on the stock demo: does the CLI accept it (expected yes, per API), and is ADC data distorted? Discriminates whether 12500 should be error or warning on 1843.
2. **ADC buffer per chirp:** raw capture on 1843 with `Ns*Nrx*4` of 12 KB, 20 KB, 30 KB (e.g. 4 RX, Ns 768/1280/1920) with LVDS: does streaming still work above 16384? Repeat on 1443 at 6 / 10 / 14 KB to resolve the 16384 vs 8192 question.
3. **Chirp cycle:** 1843/6843 profile with idle+rampEnd of 14 / 12 us: expected `sensorStart` failure or async error; also test idle alone at 1 us with a long ramp (shows whether 2 us idle matters).
4. **DCA packet delay:** capture at `packet_delay_us` 5 / 25 / 50 / 100 with a data rate above 105 Mb/s to confirm the ~$1472\cdot 8/(d+11.5\,\mu s)$ ceiling; `docs/RESULTS.md` currently shows only 53 Mb/s (6.66 MB/s SAR), which is below every ceiling.
5. **IWR1443 L3:** on the shipped demo load cfgs with radar cubes (range bins x Doppler bins x virtual antennas x 4 B, all powers of two) of 256 KB (128 x 64 x 8), 384 KB (256 x 32 x 12) and 512 KB (256 x 64 x 8) and record which are accepted; 512 KB must fail, and the 384 KB case also needs room for the detection matrix, so it probably fails even if the split is 384 KB. This tests the shipped SDK 2 split.

## Confidence

High: TX/RX counts, bands, slope maxima, sample-rate maxima, numLoops, LVDS lanes and 600 Mbps, DCA1000 throughput table (TI text read directly; the three datasheets and SDK 3.6 headers are current-revision documents). Medium: L3 for IWR1843 (datasheet internally inconsistent; SDK build value chosen; consistent with the 2 MB / 1.75 MB on-chip totals), the 1443 L3 (device max, shipped split unknown), streaming ADC-buffer ceiling 16384 on 1843/6843 (inferred from the ping/pong API, same inference as `SAR`), the DCA1000 delay model (two-parameter fit to four TI points; reproduces them within 2 Mb/s). Low or unsettled: IWR1443 ADC buffer (TI documents conflict), anything about the SDK 2.x IWR1443 demo, the duty-cycle heuristic, min idle as a standalone number (TI gives none), effective max slope under APLL/synth bandwidth control (`RL:714`, `rlRfApllSynthBwControl`, not read), whether the DCA1000 FPGA release in use matches the 2019 guide. Not settled: behaviour when limits are exceeded (reject versus degrade) is documented as "valid range" only; nothing here was run on a board.

## Sources

- `ti_swrs211c_iwr1443` — Texas Instruments (2018), "IWR1443 Single-Chip 76- to 81-GHz mmWave Sensor, SWRS211C," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr1443.pdf
- `ti_swrs228b_iwr1843` — Texas Instruments (2024), "IWR1843 Single-Chip 76- to 81-GHz FMCW mmWave Sensor, SWRS228B," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr1843.pdf
- `ti_swrs219f_iwr6843` — Texas Instruments (2025), "IWR6843, IWR6443 Single-Chip 60- to 64-GHz mmWave Sensor, SWRS219F," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr6843.pdf
- `ti_spruij4a_dca1000` — Texas Instruments (2019), "DCA1000EVM Data Capture Card, SPRUIJ4A," *User's Guide*. url:https://www.ti.com/lit/ug/spruij4a/spruij4a.pdf
- `ti_mmwave_sdk_3_6` — Texas Instruments (2022), "mmWave SDK 03.06.02.00-LTS (rl_sensor.h, mmwdemo_rfparser.c, demo and platform sources)," *Software*. url:https://www.ti.com/tool/MMWAVE-SDK
- `ti_icd_rev223_awr2243` — Texas Instruments (2022), "mmWave Radar Interface Control Document, Revision 2.23 (AWR2243/xWR6243)," *Interface control document*. url:https://www.ti.com/tool/MMWAVE-DFP
