# Notes on TI's sources

What the TI documents and SDK sources say about the things this repo's code depends on: serial frame formats, board limits, chirp rules, CFAR commands, analog settings. Code comments, `config/firmware/*.json` `source` strings and tests cite sections by anchor (for example `radar_notes.md#single-chip-limits`, "row 15").

How to read it: a fact was read from TI source or a TI document unless it is marked HYPOTHESIS (inferred, not tested). Confidence is `high`, `medium` or `low` as stated. "Bench" means a real board; no section below was bench-tested unless it says so. Paths such as `rl_sensor.h:742` are inside TI's package (mmWave SDK 3.6.02.00-LTS unless stated; `casc:` is `firmware_dev/projects/awr2243_cascade_ddm/src/ti/`). The tables the code reads directly are in the appendix. Re-check a number against the TI source before you change a limit that rests on it.

## SDK 2 UART frame

**Finding.** The IWR1443's SDK 2 demo frame is exactly what `tlv_dialect: sdk2` decodes, read from mmWave SDK 2.1.0.4 (`packages/ti/demo/io_interface/mmw_output.h`, `detected_obj.h`, `xwr14xx/mmw/main.c`, `data_path.c`). The SDK 1.2.0.5 headers are identical, so it covers SDK 1.x and 2.x xWR14xx demos, not SDK 3. Confidence about 95%. Used by `UartFrame.cpp` (`parse_uart_frame`), `UartFrame.hpp`, `tests/test_uart_parse.cpp`, `tests/test_board_descriptor.cpp`, `config/boards/IWR1443.json`.

Header: 8-byte magic word (`02 01 04 03 06 05 08 07`) plus 7 `uint32`, 36 bytes, little-endian. There is no `subFrameNumber`: it exists only under `#ifdef SOC_XWR16XX` (`mmw_output.h:113-118`) and the xWR14xx build defines `SOC_XWR14XX` only.

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | magic word |
| 8 | 4 | `version` |
| 12 | 4 | `totalPacketLen` (whole packet, including header, TLVs and padding) |
| 16 | 4 | `platform` (`0xA1443`) |
| 20 | 4 | `frameNumber` |
| 24 | 4 | `timeCpuCycles` |
| 28 | 4 | `numDetectedObj` |
| 32 | 4 | `numTLVs` |
| 36 | - | first TLV |

TLVs: `{u32 type, u32 length}`, 8 bytes, and `length` **excludes** that header (`mmw_output.h:176-184`; `main.c:1500-1503`), so the next TLV starts at `+8+length`, as in SDK 3. Types: 1 detected points, 2 range profile, 3 noise profile, 4 azimuth heat map, 5 range-Doppler heat map, 6 stats (six `uint32`, 24 bytes). There is no type 7. Which TLVs are sent depends on `guiMonitor`; a frame with no detections has **no** type-1 TLV, which the parser must treat as an empty cloud, not an error.

Type 1: a 4-byte descriptor `{uint16 numDetetedObj, uint16 xyzQFormat}` (the typo is TI's), then `numObj` records of 12 bytes: `uint16 rangeIdx, int16 dopplerIdx, uint16 peakVal, int16 x, y, z`. So `length = 4 + 12 n`: a multiple of 4 but **not** of 16, and the SDK 3 "multiple of 16" check must not run on this dialect.
- Meters = `int16 / 2^xyzQFormat`; parse as `int16`, never `uint16`. `xyzQFormat = ceil(log2(16 / |rangeResolution|))` depends on the cfg, so read it from every descriptor (`main.c:1420`, `data_path.c:2234-2253`).
- With the 1D chain `x = z = 0` and `y` is range: legitimate output.
- `dopplerIdx` is a signed bin, not m/s. `v = dopplerIdx * dopplerResolution` needs the cfg. `peakVal` is a log magnitude, not dB, and the packet carries no noise or SNR.

Padding: `MMWDEMO_OUTPUT_MSG_SEGMENT_LEN 32` rounds `totalPacketLen` up (`main.c:1543-1545`); TI's guide says "Output packet of mmW demo data over UART is in TLV format and its length is a multiple of 32 bytes". Read exactly `totalPacketLen` bytes, skip up to 31 pad bytes (uninitialised stack), and allow `sum(8 + length) <= totalPacketLen - 36`. UART defaults: data 921600 baud, command 115200 (`main.c:2455-2456`).

**Decisions in the code.** `Point::v`, `snr_db`, `noise_db` are NaN on this dialect (no SDK 2 source for them; `peakVal` is not dB); computing `v` would need the Doppler resolution from the cfg, which the driver does not derive. Load-time rejection of serial plus `sdk2` was removed; `header_bytes` must be 36 for `sdk2`.

**Golden frame.** The test recipe: a 36-byte header, one type-1 TLV with 2 objects and `xyzQFormat = 7`, one type-6 TLV, zero padding to a multiple of 32; assert exact x/y/z and that the trailing pad is skipped.

**Open.** No real IWR1443 frame has been captured. A bench check would confirm `platform == 0xA1443`, `totalPacketLen % 32 == 0` and `header_bytes == 36`. The firmware actually flashed on a lab board could be a custom or other-SDK build; SDK 2.0.0.4 was not inspected separately.

## Headless flashing

**Finding.** The IWR1843 can be flashed with no GUI step. TI's UniFlash ships a command-line flasher (`dslite.sh`) whose xWR18xx serial target writes a `.bin` as `META_IMAGE1` over the UART port; a logged AWR1843 run (UniFlash 5.1, Windows) shows `dslite.bat -c AWR1843_uniflash5.ccxml -s COMPort=COM6 -f xwr18xx_test.bin,1` ending in "SUCCESS!! File type META_IMAGE1 downloaded successfully to SFLASH." The earlier claim that the repo has "no xWR18xx serial target" is true only of the CCS 12.8.1 DSLite inside the firmware container (its Python flasher answers "not Supported" for anything but am243x/am263x/am263px/am273x). UniFlash's own bundle has the mmWave flasher. Confidence at the time: about 75% for `dslite.sh`, low for installer headlessness. It then worked: `firmware_dev`'s `fw flash` (method `dslite`) flashed an IWR1843BOOST on 2026-10-06 and 2026-10-10, and restored the stock demo, from `-if00` by-id ports.

What to remember when flashing:
- **Erase scope:** the logged run formatted all of SFLASH, so flashing wipes the stock demo. Restore with `ti_stock_demos`' `iwr1843_demo.bin` (324804 B) the same way. Meta images 1..4 go to 512 KB offsets; the ROM bootloader boots offset 0 first.
- **Mode and power:** flash mode is SOP0 + SOP2 closed (101), power-cycled before the flasher starts; functional mode is SOP0 only (001). After a failed attempt re-power, re-plug, kill a stale `DSLite` or `Python` process; use a 5 V supply of about 3 A.
- **Port:** the XDS110 "Application/User UART", on Linux the `-if00` by-id link. Nothing else may hold it.
- **Trailing error:** the logged run ends with `error: Cortex_R4_0: Can't Run Target CPU: Unsupported GTI Function.` Treat it as benign only if the `SUCCESS` line for the meta image was logged before it; otherwise the flash failed.
- UniFlash 9.6 spells the arguments differently from 5.1 (`-f` is a flag, files listed at the end), and the ccxml setting ids come from `dslite flash -c <ccxml> -S '.*'`. The Linux `.run` installer's unattended flags are not documented by TI. Fallback: "Generate Package" in the UniFlash GUI on any machine.

| Route | Headless | Note |
|---|---|---|
| UniFlash `dslite.sh` + ccxml | yes | used |
| UniFlash "Generate Package" on a GUI PC | host side yes | copy the zip, edit the COM port |
| UniFlash desktop or cloud GUI | no | |
| mmWave Studio | no | Windows only |
| SDK `utils/sbl`, Radar Toolbox `JTAG_Flasher` | no | JTAG/SBL, not UART |
| custom tool per SWRA551 (break signal, bootloader protocol, CRC32) | yes | last resort |

TI sources: UniFlash 9.6 quick-start guide; TI E2E "AWR1843: Using Uniflash command line tool" and the mmWave UniFlash FAQ; SWRA551; mmWave SDK 3.6 user guide, "How to flash an image onto mmWave EVM".

## ODS antenna

**Finding.** On the IWR6843ISK-ODS, TX1 and TX2 are the **azimuth** pair (lambda apart horizontally, same height) and TX2 and TX3 are the **elevation** pair (lambda apart vertically). Mask bits: 1 and 2 = azimuth, 4 = elevation. On the standard ISK it is TX1 + TX3 (bits 1, 4) azimuth and TX2 (bit 2) elevation. So "azimuth TX first, elevation TX last" is chirp order **1,2,4 on the ODS** and 1,4,2 on the ISK (TI's `profile_3d.cfg` lists 1,4,2). Source: TI SWRU546E sec. 3.7, Figures 3-16 and 3-17, p. 40 (positions read from a raster figure; confidence high for the layout, medium for absolute TX-to-RX offsets, which the figure does not dimension). Used by `radar_gui/cfg/metrics.py`, `validate.py` (`tx_order_convention`), `docs/design/cfg_formulas.md`, `docs/design/mimo_modes.md`, `tests/test_radar_gui_ods_pairing.py`.

| Antenna | x (lambda = 5 mm) | z |
|---|---|---|
| RX1 / RX4 | 0 / +lambda/2 | 0 (top row) |
| RX2 / RX3 | 0 / +lambda/2 | -lambda/2 (bottom row) |
| TX1 / TX2 | x0 / x0+lambda | z0 |
| TX3 | x0+lambda | z0-lambda |

The 12-channel virtual array ("4 x 3 virtual antennas positions") is each TX block, the 2x2 RX square, translated by its TX: TX1+TX2 form a contiguous 4-wide x 2-high array at lambda/2 pitch, TX3's block sits directly below TX2's. The figure note: "RX2 and RX3 are 180 degrees out of phase with respect to RX1 and RX4. Because of this, a 180 degree phase inversion needs to be applied in software processing for the corresponding virtual RX channels (highlighted in Red)" (channels 2, 3, 6, 7, 10, 11). That matters for angle processing, not for cfg editing.

**In the code.** The board descriptor key `elevation_tx_bit` (ODS 4, ISK and BOOST 2; default 2) drives the order rule: warn if the elevation TX is in the loop and is not last. The message names TX3 for the ODS. `az_res` uses `az_tx = 2` on the ODS, not the ISK-style count. The five shipped ODS system configs use `channelCfg 15 7 0` and chirp masks 1,2,4.

**Open.** TI's guide says nothing about chirp order on the ODS. Physically TDM-MIMO works in any order; only the slot-to-channel mapping changes. Whether the SDK demo's antenna-geometry table requires 1,2,4 is not sourced (HYPOTHESIS: no). Bench check: run a 1,2,4 and a 1,4,2 cfg on a corner reflector at known elevation and compare elevation estimates.

## Cascade chirp limit

**Finding.** On the AWR2243 two-chip cascade running the MCU+ DDM demo, **chirps per frame <= 256** (for 6 TX x 8 RX) is a real firmware limit, enforced by memory, not by `numLoops` (255). The Doppler FFT size `N = mathUtils_getValidFFTSize(chirps per frame)` (power of 2 or 3x power of 2; `mmwdemo_rfparserDDMA.c:786-789`) sets the scratch needed in the DSS core-local L2 heap, which is only 82 KiB (`gDPC_ObjDetL2Heap`, `dss_main.c:107-119`; the build map shows `.dpc_l2Heap` = 0x14800 = 83,968 B). TI's own statement agrees: "Chirp design is limited to 192 adc samples, 256 chirps, and 8 channels. No other configuration has been tested". Used by `config/firmware/cascade_ddm.json` (`max_chirps`), `radar_gui/cfg/validate.py`, `generate.py`, `tests/test_radar_gui_cascade_limits.py`.

Scratch model, with `V` virtual antennas and `Rx` RX channels: `L2(N) ~ N (2V + 16 Rx + 8)` bytes, which must fit 83,968 B. For `V = 48`, `Rx = 8` that is `232 N` bytes (the `objectdetection.c` allocations are `dopFFTSubMat` 2NV, Doppler ping/pong 2 x N Rx 8, DDMA metric 2 x 4N):

| Chirps/frame | N | L2 estimate | vs 82 KiB |
|---|---|---|---|
| 128 | 128 | 29 KiB | fits |
| 192 | 192 | 43.5 KiB | fits |
| 256 | 256 | 58 KiB | fits (bench-confirmed) |
| 257..384 | 384 | 87 KiB | over |
| 512 | 512 | 116 KiB | over |
| 1024 | 1024 | 232 KiB | over (bench-failed) |

This reproduces both bench outcomes: `frameCfg 0 7 32 0 128 100 1 0 2` (256 chirps) works; `bench_cascade.cfg` (`frameCfg 0 7 128 ...`, 1024 chirps) gets no `Done` at `sensorStart`. Fixed overheads (range window, 4 KiB pool alignment) are not modelled, so the exact threshold lies between 256 and 384 chirps; it cannot be lower than 256.

**Second limit: the L3 radar cube.** `gMmwL3` is 2,654,208 B (`.l3ram` = 0x288000). Cube bytes `B = R * C * Rx * 4 * rho` (`R` range bins, `C` chirps, `rho` the compression ratio, 0.5 for `compressionCfg -1 1 0 0.5 8`), plus decompression scratch `C Rx 32`, detection matrix `R (N/8) 2` and object lists. Exceeding it returns `DPC_OBJECTDETECTION_ENOMEM__L3_RAM_RADAR_CUBE`. The failed 1024-chirp cfg needs about 2.4 MB, so L2 fails first. L3 binds for example at `R >= 1024` with 256 chirps, or `R = 512` uncompressed.

**Validator rule adopted.** Error when `n_chirps > 256` and `V >= 48`; keep 192 samples as a "tested only" warning. The generator caps loops so `chirps per loop x loops <= 256`. HYPOTHESIS: fewer TX (2 TX, `V = 16`) might allow `N = 512` (84,000 B, borderline); do not rely on it.

**Open.** The failure path (assert versus error print on the DSS UART) was not traced. Bench check (one power-cycle per cfg): `frameCfg 0 7 48 ...` (384 chirps) should fail at `sensorStart`; if it passes, the model overstates usage.

TI sources: Radar Toolbox 4.00.00.05 `mmwave_2_chip_cascade` source (as tracked in `firmware_dev/projects/awr2243_cascade_ddm`); its `Two_Chip_Cascade_user_guide.html`.

## Chirp patterns

**Finding.** The stock SDK 3.6 demo (IWR1843, IWR6843) accepts only a cyclic **one-TX-per-chirp** sequence, each TX once per loop, at most 32 chirps per loop; the cascade fires all 6 TX on every chirp (DDMA) and cannot do TDM by cfg. Used by `docs/design/mimo_modes.md`, `radar_gui/cfg/validate.py` (mimo rules), `params.py`, `metrics.py`, `tests/test_radar_gui_validate_mimo.py`, `tests/test_radar_gui_cfg.py`. Source: `RP` = `packages/ti/demo/utils/mmwdemo_rfparser.c`.

| Topic | Rule | Source |
|---|---|---|
| Chirps per loop | `chirpEnd-chirpStart+1`; more than 32 would overflow `validChirpTxEnBits[32]`: 32 is the real limit | `RP:769,782-784,794` |
| `chirpCfg` entries | any number, ranges allowed; every index of the loop must be covered by a chirp whose `txEnable & channelCfg.tx` is non-zero, else the profile is invalid | `RP:826-845`, `:515-519` |
| Per-chirp TX mask | elevation chirp iff mask `== 0x2` (3-TX chips). Otherwise BPM (`bpmCfg` on, mask `0x5` on every chirp) or one-TX-per-chirp. Mixing is rejected | `RP:522-560` |
| Several TX, no BPM | all chirps multi-TX: accepted as "SIMO", one azimuth TX counted, 4 virtual antennas | `RP:608-616` |
| `n_TX` | TDM: distinct azimuth TX in the OR of masks, +1 for an elevation chirp; BPM: 2; max 3 | `RP:586-632` |
| De-interleave | chirp `k` goes to TX `k mod n_TX` (3 TX: stride 6, so `numLoops` should be even) | `rangeprochwa.c:966-1140` |
| Doppler | `N = cpl * L`; `numDopplerChirps = N / n_TX`; bins = next power of 2; resolution `c/(2 N fc Tc)`; reported span `+-lambda/(4 n_TX Tc)` | `RP:885-906` |
| Order convention | TI cfgs list azimuth first, elevation last: `profile_3d.cfg` 1,4,2; `profile_2d.cfg` 1,4 | `demo/xwr18xx/mmw/profiles/` |
| Subframes | `advFrameCfg` up to 4, `numOfBurst == 1`, each parsed on its own (a different pattern per subframe is possible; not on the SAR image) | `RP:774-778` |
| One profile | only one profile is used; extra profiles are accepted by the CLI and ignored ("we support only one profile in this processing chain", `RP:788`) | `RP:788` |

The parser never checks that the sequence repeats with period `n_TX`: `[1,4,1,4]` happens to work, `[1,4,1,2]` would be misdecoded (HYPOTHESIS, untested). So the Doppler span is `lambda/(4 n_TX Tc)`; `chirps_per_loop * Tc` is right only when `chirps_per_loop == n_TX`.

**Cascade.** The DDMA parser ignores the chirp mask: it writes the merged `channelCfg` TX mask into every chirp (`mmwdemo_rfparserDDMA.c:717-733`), the demo hard-codes `txAntMaskEnable = 63` (`mss_main.c:3825`) and programs per-chirp phase shifts (`mmwave_link_common.c:919,952,986`). TX separation is in the Doppler domain: 8 bands (6 TX + 2 empty). A TDM variant exists only as source (`-DMMWDEMO_TDM`, `objdethwa/`, `mmw_resTDM.h`); the shipped projectspec defines only `MMWDEMO_DDM`, so TDM is a different build, untested here. Advanced frames are refused by the DDMA chain: "Advanced Subframe Config is not currently supported with the DDMA chain" (`mss_main.c:3888-3891`).

**Rules the GUI encodes.** `tx_pattern_invalid` (mix, wrong period, more than 32); `channelCfg` TX is the OR of the chirp masks; order convention (warning); `cascade_chirp_mask_ignored`; a chirp table editor with presets (SIMO, 2-TX TDM, 3-TX with elevation, BPM). Known gaps in `metrics.py`: SIMO counts `popcount` TX where the firmware counts 1; `advFrameCfg` is not modelled.

**Open (bench).** Pattern `[1,4,1,4]` versus `[1,4]` with doubled loops should give equal Doppler step; 1,4,2 versus 1,2,4 on a reflector at known elevation; a one-TX-per-chirp cfg sent to the DDM build, to record its error.

TI sources: mmWave SDK 3.6.02.00-LTS (`rfparser`, `rangeproc`, `xwr18xx` profiles); Radar Toolbox cascade source.

## Single-chip limits

**Finding.** The limits for IWR1443, IWR1843 and IWR6843 in `config/firmware/*.json` were checked against the datasheets (SWRS211C, SWRS228B, SWRS219F), the DCA1000 guide (SPRUIJ4A) and SDK 3.6 sources; the verification table with its 16 rows is in the appendix ("Single-chip limits: rows 1-16"), and each firmware descriptor `source` cites a row. Five values that had been wrong are corrected there: IWR1843 max slope **100** MHz/us (266 is the AWR2243 figure) and IWR6843 **250**; the L3 radar cube for IWR1843 (**1024 KB**) and IWR6843 (**768 KB**) had been swapped, IWR1443 is up to 384 KB; IWR1443 max complex-1x rate **18750** ksps (not 12500); DCA1000 headroom 800 Mb/s exceeds TI's own maximum of about 706 Mb/s; and "min idle 2 us" is not a TI figure (TI documents a minimum **chirp cycle** of 15 us on xWR1xxx, 13 us on xWR6843). Confirmed: TX/RX counts, bands, `numLoops` 255, LVDS lanes, 600 Mbps per lane. Used by `config/firmware/*.json`, `config/limits/host.json`, `radar_gui/cfg/limits.py`, `validate.py`.

**Firmware table: what the firmware enforces versus the silicon.** The demo never range-checks slope, sample rate or idle: the radar subsystem does, through mmwavelink. So the GUI is the only early check for most of them.

| Constraint | Demo firmware (stock, with or without LVDS) | Raw (`dca1000_raw`) / SAR image |
|---|---|---|
| slope, rate, idle, band | none, except slope >= 0 (`RFP:874-880`) | same; SAR `sensorStart` rejects `channelCfg`/`adcCfg`/`lowPower` changes |
| ADC format | 16-bit complex only (`RFP:724,966`); `adcbufCfg` chirpThreshold must be 1 (`CLI:819-821`) | raw: ADC buffer size per SOC |
| chirps per frame | unique chirps <= 32 (`RFP:782-784`); one profile; advanced frame needs `numOfBurst = 1` | SAR: `dfeDataOutputMode` 1 only; > 255 chirps via repeated chirp indices |
| radar cube / L3 | must fit, else `DPC_OBJECTDETECTION_ENOMEM__L3_RAM_RADAR_CUBE` (`DPC:1817`) | not applicable (no DPC) |
| LVDS | `numAdcSamples` >= 64, HSI header with SW session, single-chirp formats, CBUFF minimum 64 B (`MSS18:360-410`) | SAR: `dataFmt 2` exists only here |
| one chirp larger than the ADC buffer | no check: `maxChirpThreshold` = 0 then a modulo by zero (`RFP:982-1000`, read from source, not run) | raw: not checked |

**LVDS capacity (row 13).** Bytes per chirp `roundup256(Ns * Nrx * 4 + 52)` must be <= `Tc * lanes * Mbps / 8`, else the demo says "this configuration will not work" (`MSS18:372-381`).

**DCA1000 headroom (row 15).** TI's table: 706 / 545 / 325 / 193 Mb/s at 5 / 10 / 25 / 50 us packet delay. A two-parameter fit (derived, not TI) is `R ~ 11776 bit / (d + 11.5 us)`; at the project's `packet_delay_us = 100` that gives **about 105 Mb/s**. A bench capture above that rate would confirm it; `docs/RESULTS.md` has only 53 Mb/s.

**Low-power ADC mode (correction).** The only source is the mmwavelink doc comment for `rlProfileCfg_t.digOutSampleRate` (`rl_sensor.h:742-767`): complex-1x low-power caps are **9375** ksps for IWR1443 and IWR1843 (the xWR1xxx row of the 10 MHz table, below the 12500 regular cap), **12500** for IWR6843. 6250 appears only in the 5 MHz IF table, which none of these boards uses. No datasheet mentions low-power mode; no bench check.

**Severity.** Errors for what the API documents as invalid (`numLoops` outside 1..255, slope code outside +-2072 / +-6905, sweep outside the allowed sub-bands, chirp cycle below 15/13 us) and, for the demo, a cube larger than L3 or LVDS bytes per chirp above lane capacity. Warnings for heuristics (duty cycle 0.9, DCA headroom).

**Open.** IWR1443 SDK 2 demo behaviour and its ADC-buffer layout (16384 B whole versus 2 x 16 KB; the datasheet conflicts) are unverified. The IWR1843 datasheet gives IF 10 MHz and complex-1x 12.5 Msps; the SAR docs allow 18750 on the IWR1843 by the generic xWR1xxx header text (HYPOTHESIS: accepted by the API but outside the specified IF; untested). Bench checks: 15000 ksps on the 1843; raw capture above 16384 B per chirp; idle + rampEnd of 14 / 12 us; DCA delay 5 / 25 / 50 / 100 us; IWR1443 radar cubes of 256 / 384 / 512 KB.

## Cascade limits and firmware matrix

**Finding.** The cascade limits in `config/firmware/cascade_ddm.json` were verified against the AWR2243 datasheet (SWRS223D), `rl_sensor.h` and the MCU+ demo source (appendix: "Cascade limits"). Corrections: silicon max slope is **266** MHz/us and sample rate 2000-50000 ksps; the repo's 100 MHz/us and 10000 ksps are TI-tested values, kept as "tested" warnings, not hardware bounds. 192 samples and 256 chirps are TI-tested only (the firmware does not enforce samples; chirps are limited by memory, see "Cascade chirp limit"). Valid DDMA TX counts are 2, 3, 4, 6 (1 and 5 give `numBandsEmpty = -1`; `mss_main.c:4032-4058`). `numLoops` 255 in legacy frame mode. Minimum idle time is unverified (TI cfgs use 4-5 us).

**Doppler convention.** The DDMA Doppler FFT is over **all** chirps in the frame, `N = n_cpl * L` (`mmwdemo_rfparserDDMA.c:786-789`), not over `loops`. So `metrics.py`'s `n_chirps = cpl * loops` is right, and velocity resolution `lambda/(2 N Tc)` is the same under every convention. Reported velocity spans `+-lambda/(4 Tc)` (`objectdetection.c:698-716`); a "loop-period" model (`lambda/(4 T_loop)`, `T_loop = n_cpl Tc`) gives a value `n_cpl` times smaller. That smaller number is the per-TX-band unambiguous velocity (`lambda/(4 n_bands Tc)`), valid while `n_cpl = n_bands = 8`: a target beyond it aliases into a neighbouring TX band (the 2 empty bands give slack). The code shows the firmware's full span; the band-limited figure is the safe "no TX-band aliasing" limit.

**Profiles and chirps per firmware.** All use `MMWAVE_MAX_PROFILE = 4`, `RL_MAX_SUBFRAMES = 4`; the CLI fails a fifth `profileCfg`. The data path uses one profile everywhere.

| Firmware | Profiles used | Subframes | TX-to-chirp rule |
|---|---|---|---|
| `demo` 1843/6843 | 1 (first with chirps in range) | up to 4, `numOfBurst = 1` | TDM or BPM as in "Chirp patterns"; <= 32 unique chirps |
| `iwr1843_sar_lvds` | 1 | none (only subframe 0; `profile_advanced_subframe.cfg` is a leftover) | as stock; cfg applied after `flushCfg`, `channelCfg`/`adcCfg`/`lowPower` frozen after first start |
| `cascade_ddm` | 1 | refused | DDMA; chirps per loop should be a multiple of `n_bands` = 8 (HYPOTHESIS, not enforced; all shipped TI cfgs use exactly 8) |
| `dca1000_raw` | binaries only, not checkable | unknown | unknown |

All 36 cfgs under `config/radar/` at the time carried exactly one `profileCfg`.

**Firmware matrix (per board).**

| Board | Demo | Alternates |
|---|---|---|
| IWR1443 | `xwr14xx_mmw_demo.bin`: TLV yes, LVDS no (web evidence only) | `xwr14xx_lvds_stream.bin` (raw ADC, no TLV) |
| IWR1843 | SDK 3.6 `mmw` demo (`ti_stock_demos`): TLV yes, **LVDS yes** via `lvdsStreamCfg` | `iwr1843_sar_lvds` (no TLV, LVDS `dataFmt` 1/2); `dca1000_raw` |
| IWR6843 | SDK 3.6 `mmw` demo: TLV yes, LVDS yes | `xwr68xx_lvds_stream.bin` (raw) |
| AWR2243 cascade | `am273x_cascade.appimage`: TLV yes (3,125,000 baud), LVDS no, Ethernet stream no | none |

Consequences adopted in the descriptors: the stock demo and the "LVDS demo" are **one binary** on 1843/6843 (LVDS is enabled by the cfg), so there is a single `demo` firmware; `dca1000_raw` also ships for the IWR6843; the cascade has no `cfarFovCfg` (see "CFAR commands"). The IWR1443 prebuilt `xwr14xx_mmw_demo.bin` is byte-identical (sha256 `b6b6d8f3f518c1b6f324fed2db1fa8088a43f4b90358a7918d03adace0cdfae9`) to SDK 2.1.0.4's, so that board runs SDK 02.01.00.04.

**Config once per boot.** TI's cascade guide: "Reconfiguration of the chirp design by stopping transmission and then sending another configuration is not supported ... power cycle" (`Two_Chip_Cascade_user_guide.html`, Notes), which is `lifecycle.config_once_per_boot` in the board descriptor.

**Open.** Cascade `min_idle_us`; multi-profile and subframe rules for IWR1443 (SDK 2 not in tree) and the `dca1000_raw` binaries; whether the prebuilt cascade `.appimage` equals the source build. Bench: chirps per loop of 4 versus 8; a second profile on the 1843 (expect it ignored); `advFrameCfg` on the SAR image (expect no subframe behaviour).

TI sources: AWR2243 datasheet SWRS223D; Radar Toolbox cascade source; mmWave SDK 3.6; the TI E2E thread on IWR1443 LVDS streaming.

## CFAR commands

**Finding.** Three CLI dialects, and the 3.6 demo has two CFAR engines: the IWR1843 uses the HWA DPU, IWR6843 and ODS use the DSP DPU, with different rules. Used by `radar_gui/cfg/detection.py`, `generate.py` and the detection card (`tests/test_radar_gui_detection.py`). All three command tables are in the appendix ("CFAR command forms"). The points to remember:
- **Argument counts are exact** and each integer is cast to `uint8` (`atoi`), so 256 silently wraps to 0 on every firmware: cap fields at 255. The 1443's `procDirection` is read but ignored (only range is supported).
- **3.6 needs both directions** of `cfarCfg` and `cfarFovCfg` or the first `sensorStart` fails: "Error: Full configuration must be provided before sensor can be started the first time" (`mmw_cli.c:155-170`). Peak grouping is the last `cfarCfg` argument there; the 1443 has a separate `peakGrouping` command.
- **Cascade: `cfarFovCfg` is not registered** in the DDM build (under `#ifdef MMWDEMO_TDM`, `casc: mmw_cli.c:2297-2311`): never emit it. Mode 3 = CFAR-OS (HWA 2.0 only), with extra fields `osKvalue`, `osEdgeKscaleEn`, `isEnabled`. The Doppler direction needs `mode == 3` and `guardLen == 0` (`casc: dopplerprochwaDDMA.c:3993-4003`). Doppler `isEnabled = 0` prints "Doppler CFAR Cannot be disabled." but the CLI still answers `Done` and stores the line (`mmw_cli.c:697-700`); the DPU never reads it, so it is a no-op.
- **Threshold units differ:** 1443 raw log2 Q9 (`T_cli = 512 * T_dB / 6 * N/N'`, with `N = nRx*nTx`, `N'` the next power of 2; shipped 1280 = 15 dB at N=8); 3.6 float dB, **error above 100.0** (`mmw_cli.c:480-483`), stored x100 as `uint16`; cascade float dB, same limit, amplitude dB converted to Q11.
- **Failures show at `sensorStart`, not at the `cfarCfg` line:** the CLI answers `Done`, the DPU rejects when it configures: `2*(noiseWin+guardLen) >= numRangeBins` (range) or `>= numDopplerBins` (Doppler) is `EINVAL` on both 3.6 engines (`cfarcaprochwa.c:832-843`, `cfarcaprocdsp.c:1115-1126`); HWA `winLen == 2` is invalid for range, and for Doppler when its threshold is above 0 (`cfarcaprochwa.c:846-858`). Bins: `numRangeBins = pow2roundup(numAdcSamples)`, `numDopplerBins = pow2roundup(numChirpsPerFrame / numTx)`. The presentation of the failure (UART text versus a DSS-side hang) was not read to the end.
- `divShift` follows the user-guide formula (CA `ceil(log2(2*noiseWin))`, CAGO/CASO `ceil(log2(noiseWin))`); the CLI checks nothing, a mismatch only rescales the threshold. All 168 shipped 3.6 lines satisfy it, so that warning fires only on user edits.
- **Source-read, not benched:** the DSP DPU ignores `cyclic` (range) and the Doppler `mode`; threshold 0 disables a direction on the 1843 HWA (Doppler only), each direction on the 6843 DSP, range via `isEnabled` on the cascade. Label such help text "source-derived".
- **Peak grouping:** 1443 `peakGrouping <scheme> <rangeEn> <dopplerEn> <startIdx> <endIdx>` (scheme 1 only; start/end are the range bins kept); 3.6 a 0/1 flag per direction, scheme hard-wired to det-matrix based, the FOV replaces the index window; cascade the same flag layout.
- **Live re-tune:** TI's guides say `cfarCfg`, `peakGrouping` and `cfarFovCfg` "can be changed between sensorStop and sensorStart and even when the sensor is running" on the 1443 and 3.6 (not bench-verified); the cascade applies CFAR only at the first start.
- SAR and `dca1000_raw` have no on-chip detection (`detection: null`). The IWR6843ODS has no firmware of its own: it maps to the 6843 SDK 3.6 demo.

**Defaults seen in 95 shipped cfgs:** 1443 `cfarCfg 0 2 8 4 3 0 1280`; 3.6 range always CASO (mode 2), `noiseWin` 7-8, guard 4, `divShift` 3, cyclic 0, Doppler mode 0 or 1, `noiseWin` 4-8, guard 2-4, `divShift` 3-4, cyclic 1, thresholds 7-25 dB; cascade mode 3, `winLen` 16, guard 0, `divShift` 0, cyclic 1, K 7, range 10-15 dB, Doppler 12-25 dB. Four advanced-subframe cfgs carry explicit subframe indices 0-3; the editor treats them read-only.

**Open.** Whether `noiseWin` is one-sided or total (HWA programs `winLen>>1` per side while the guide says one-sided); the cascade `osKvalue` range versus `winLen` and the range-direction CFAR limits (the library is not in the repo); the failure presentation of the DPU errors. Bench: seed a cfg with `2*(win+guard) >= numRangeBins` on the 1843 and record the `sensorStart` output (may need a power-cycle); Doppler threshold 0; on the cascade a `cfarFovCfg` line ("not recognized"), Doppler `isEnabled 0`, a changed `osKvalue`.

TI sources: mmWave SDK 3.6 and 2.1 user guides (CLI table, sec. 3.4); SDK 3.6/2.1.0.4 `mmw_cli.c`, `cfarcaprochwa.c`, `cfarcaprocdsp.c`, `data_path.c`; cascade `mmw_cli.c`, `dopplerprochwaDDMA.c/.h`.

## HPF, rxGain and ADC

**Finding.** The HPF corner codes are identical on every chip: HPF1 code 0..3 = 175 / 235 / 350 / 700 kHz, HPF2 code 0..3 = 350 / 700 / 1400 / 2800 kHz (the datasheets list the values, the mmwavelink `rlProfileCfg_t` doc and SDK user guide give the code order; confidence high). `profileCfg rxGain` is a packed word: **bits 5:0 = RX gain in dB (even values only, 2 dB step), bits 7:6 = RF gain target code, bits 15:8 reserved**. Valid gain (bits 5:0): 24..48 for IWR1443, IWR1642, IWR1843; 30..48 for IWR6843/ODS; 32..52 for AWR2243. The RF-target code table differs by family (see appendix E3), so a GUI must range-check only bits 5:0 and **preserve bits 7:6**: the shipped IWR6843/ODS cfgs use 158 = 0x9E (30 dB with RF target code 10), which a naive 24..48 check would reject. Used by `radar_gui/cfg/analog.py`, `config/firmware/*.json` (`hpf*`, `rx_gain_*`, `if_bw_*`), `tests/test_radar_gui_analog.py`, `test_radar_gui_cfg.py`. Appendix tables E1-E6 carry the values with sources.

- **What `b5:0` means:** the doxygen says "Rx VGA gain"; a TI engineer on E2E calls it the total RX chain gain and the wording a documentation error. Treat it as "RX gain (dB)".
- **CLI:** SDK 3.6 `profileCfg` hands `hpfCornerFreq1/2` and `rxGain` to `rlSetProfileConfig` unmodified, so every datasheet code is accepted by syntax; how firmware treats an out-of-range or odd value is unverified.
- **Cascade `rxGain 30`:** the generator writes 30 for the cascade, below the 32 dB minimum the datasheet implies; the cascade bench runs show it is not rejected, but whether it is clamped is unverified. Do not "fix" it on this evidence.
- **Roll-off:** both HPFs are first order (20 dB/decade); `|H(f)| = f / sqrt(f^2 + fc^2)`: -3 dB at `fc`, about -7 dB at `fc/2`, -12 dB at `fc/4`, -20 dB at `fc/10` (the formula is standard, not in the datasheets; whether HPF1 and HPF2 are in series is not stated). Range at a corner: `R = f c / (2 S)` for slope `S`. No corner below 175 kHz exists, and there is no "off" code.

**Usable IF bandwidth.** SWRA553 sec. 2.1: "In a complex 1x sampling mode, the IF bandwidth is limited to 0.9*(ADCsampling). In case of complex 2x and real sampling modes, the IF bandwidth is limited to 0.9*(ADCsampling)/2". So usable bandwidth is `min(max IF, 0.9 fs)` in complex 1x and `min(max IF, 0.45 fs)` in complex 2x and real (an E2E snippet claiming 80% for the IWR1443 conflicts; two TI documents say 0.9). At a lower sample rate the digital limit governs: SAR_ugv_fmt2 (`fs` = 2 Msps, complex 1x, slope 1.95 MHz/us) has range axis end `fs c/(2S)` = 153.8 m and passband edge `0.9 fs c/(2S)` = 138.4 m, which matches the observed cliff at about 138 m (derived; HYPOTHESIS that it is the DFE filter and not the range-FFT window or CFAR edge handling).

**Bins above fs/2 in complex 1x** are real positive IF, not mirror images: TI's baseband note says the complex output spectrum "is one-sided and is devoid of image band noise fold-back" and that "the mapping between the beat frequency and the range measurement remains unchanged". So the whole `0..fs c/(2S)` axis is valid up to `0.9 fs`, after which the anti-alias filter rolls off; only image-band leakage (IMRR 30 dB typical, 21 dB on IWR1642) is mirrored. In complex 2x and real modes the usable region is `0..0.45 fs` and real mode mirrors about `fs/2`. The note is for AR1243/1642 (2015) and applies to the others by shared DFE architecture: medium confidence.

**ADC full scale.** For `adcCfg <numADCBits> <fmt>` (0/1/2 = 12/14/16 bit): `adcCfg 2 x` (16 bit) is +-32767 (two's complement), medium confidence: `rlAdcBitFormat_t` defines `b2AdcBits` "0(12 Bits), 1(14 Bits), 2(16 Bits)" and a TI reply says the DFE output is 16 bits wide; no TI page states +-32767 literally. So the SAR_ugv_fmt2 peak of 1481 at rxGain 46 dB is `20 log10(1481/32767)` = -26.9 dBFS, about 26.9 dB of headroom, not 2.8 dB (the 12-bit rail 2047 that `radar_gui/tune.py` assumed is wrong for `adcCfg 2`). `adcCfg 0 x` (12 bit) is +-2047, right-justified and sign-extended (medium-low); 14 bit presumably +-8191; `b8FullScaleReducFctr` reduces full scale further and is documented only as 0 for 16 bit. The RF ADC is described as 12 bit in the datasheet (resolution, not container width), so 16-bit output does not imply 16 effective bits. Which stage saturates first is not documented; the firmware saturation monitor (`rlRxSatMonConf`, a per-chirp counter) is the vendor-intended indicator.

**Open.** The AWR2243 RF-target table (forum posts give 30 / 33 / 36 dB; the ICD was not retrievable); odd-value behaviour; whether the cascade path accepts every code; the IWR6843ODS has no datasheet entry of its own (IWR6843 silicon). Bench: on the cascade, `rxGain` 31, 32, 34 and `0x40|32`, `0x80|32`, compare amplitude with the table; raise gain or move a reflector close until the saturated-chirp counter is non-zero and record the peak.

TI sources: datasheets SWRS211C, SWRS212B, SWRS228B, SWRS219F, SWRS223D (RF Specification); mmwavelink `rlProfileCfg_t` and `rlAdcBitFormat_t` doxygen; mmWave SDK 3.6 and 1.1 user guides; SWRA553; the AR1243/AR1642 digital baseband application note.

## Appendix: tables the code reads

### Single-chip limits: rows 1-16

Boards: 14 = IWR1443, 18 = IWR1843, 68 = IWR6843. Abbreviations: `RL` `rl_sensor.h`; `RFP` `mmwdemo_rfparser.c`; `CLI`/`MSS` demo `mmw_cli.c`/`mss_main.c`; `DS14`/`DS18`/`DS68` the datasheets; `DCA` the DCA1000 guide. Verdict: C confirmed, X corrected.

| # | Limit | Bd | Was | Verified | Source | Verdict |
|---|---|---|---|---|---|---|
| 1 | n_tx | 14/18/68 | 3 | 3 (18, 68: max 2 per chirp; 3 only in 1-V LDO-bypass) | DS Table 3-1/5-1; `RL:925` | C |
| 2 | n_rx | all | 4 | 4 | `sys_common.h:70` | C |
| 3 | band | 14, 18 / 68 | 76-81 / 60-64 | device range; a sweep must lie in 76-78 or 77-81 (68: 57-60.75 or 60-64) | DS14 5.7, DS18 7.7; `RL:667-668` | C + sub-rule |
| 4 | max slope | 14 / 18 / 68 | 100 / **266** / **266** | 100 / **100** / **250** (code +-2072 / +-6905; LSB 48.279 / 36.21 kHz/us) | DS ramp rate; `RL:710,713` | 18, 68 X |
| 5 | max rate, complex 1x | 14 / 18 / 68 | **12500** / 12500 / 12500 | **18750** / 12500 / 12500 ksps (real or complex 2x: 37500 / 25000 / 25000) | DS14 5.7; `RL:742,750,757` | 14 X |
| 6 | min rate | all | none | 2000 ksps | `RL:742-743` | add |
| 7 | min idle | all | 2.0 us | no standalone idle minimum; idle 0..524287 x 10 ns. Min **chirp cycle** (idle + rampEnd) >= 15 us (14, 18) / 13 us (68); +10 us if WDT on | `RL:651-654,4570-4573` | X |
| 8 | numLoops | all | 255 | 1..255 (frameCfg and per sub-frame); chirp indices 0..511 | `RL:958,1066` | C; level error |
| 9 | ADC buffer | 14 / 18, 68 | 16384 "half" | 16384 B whole (low; DS14 diagram says 2 x 16 KB) / 32768 B total, streaming usable 16384 (inferred from ping/pong) | `SYS14:312`; `RL:728`; `RFP:982` | unverifiable / C |
| 10 | L3 radar cube | 14 / 18 / 68 | **256** / **768** / **1024** KB | **384** (max) / **1024** / **768** KB (18: the datasheet also says 768 KB within 2 MB; SDK build value used) | `MAK14/18/68:15,19`; DS Table 6-1 | all X |
| 11 | LVDS lanes | 14 / 18, 68 | 4 / 2 | 4 / 2 | DS14 5.9.5; DS18 7.10.4 | C |
| 12 | LVDS per-lane | all | 600 Mbps | 600 practical (DCA1000 max; demo and SAR program 0x9); silicon allows 900 | `DCA` 1; `MSS18:2912`, `MSS68:3322` | C |
| 13 | LVDS capacity | all | none | `roundup256(Ns*Nrx*4+52) <= Tc*lanes*Mbps/8` | `MSS18:372-381` | add (error, demo and SAR) |
| 14 | DCA1000 link | host | 1000 Mb/s | 1 Gbps port | `DCA` host list | C |
| 15 | DCA1000 headroom | host | **800 Mb/s** | 706 max at 5 us delay; 545 / 325 / 193 at 10 / 25 / 50 us; about 105 at 100 us (fit) | `DCA` Table 19 | X |
| 16 | duty cycle | all | 0.9, warning | no TI limit; real constraints: frame period >= chirps x Tc + blank (typ. >= 300 us, +150 us on a profile change); frame period 300 us..1.342 s | `RL:978-987` | heuristic; add blank rule |

Descriptor shape that follows: `max_slope_mhz_us` 100 / 100 / 250; `max_sample_rate_ksps` 18750 / 12500 / 12500; `min_sample_rate_ksps` 2000; `min_chirp_cycle_us` 15 / 15 / 13; `l3_radar_cube_bytes` 384K / 1024K / 768K (only for firmware with a DPC); low-power complex-1x caps 9375 / 9375 / 12500.

### Cascade limits

| Limit | Value | Verdict, source |
|---|---|---|
| `n_tx` | 6 (valid DDMA counts 2, 3, 4, 6) | C: `syscommon.h:72`; `mss_main.c:4032-4058` |
| `n_rx` | 8 (2 x 4); 3 RX per chip rejected by the range DPU | C: `syscommon.h:67` |
| band | 76-81 GHz (VCO2) | C: `rl_sensor.h` startFreqConst note |
| `max_slope_mhz_us` | silicon 266 (code +-5510, 48.28 kHz/us); 100 is `cfggen.py`'s tested value | X: keep 100 as "tested" |
| `max_sample_rate_ksps` | silicon 2000..50000; 10000 tested; shipped cfgs use 5000, 10000 | X |
| `max_loops` | 255 (legacy frame); 32768 chirps in advanced-chirp mode | C |
| `max_samples` | 192, TI-tested only (ADC buffer 16 kB) | C as tested |
| `max_chirps` | 256: TI-tested, and memory-limited ("Cascade chirp limit") | C |
| `lvds_supported` | false: neither `LVDS_STREAM` nor `ENET_STREAM` is defined (`mmw_cli.c:111-118`) | C |
| `config_once_per_boot` | true | C |
| `min_idle_us` | 4.0 is a guess; field range 0..524287 x 10 ns | unverifiable |
| `tested_sample_rates_ksps` | 5000 (short, very long range), 10000 (long range): the same set in the four shipped `cascade_*.cfg` | C |
| `frame_cfg_args`, `channel_cfg_args` | 9 (`frameCfg 0 7 32 0 192 50 1 0 2`), 5 (`channelCfg 15 7 1 15 7`) | C |
| `sdk` | MCU+ SDK 04.04.00.01 | C: `docs/firmware.md` |

### CFAR command forms

Arguments after the command name.

| | IWR1443 (SDK 2.1.0.4) | IWR1843 (SDK 3.6, HWA) | IWR6843/ODS (SDK 3.6, DSP) | Cascade (MCU+ 4.4 DDM) |
|---|---|---|---|---|
| `cfarCfg` | 7 args: `procDir mode noiseWin guardLen divShift cyclic thresholdScale` | 9: `subFrame procDir mode noiseWin guardLen divShift cyclic thresholdDb peakGrouping` | same as 1843 | 12: the 1843 order + `osKvalue osEdgeKscaleEn isEnabled` |
| `peakGrouping` | separate: `scheme rangeEn dopplerEn startIdx endIdx` | last `cfarCfg` arg | same | `cfarCfg` field |
| `cfarFovCfg` | none | `subFrame procDir min max` (range m, Doppler m/s) | same | **not registered** |
| `mode` | 0 CA, 1 CAGO, 2 CASO | same | same | + 3 CFAR-OS |
| `noiseWin`, `guardLen` | uint8, one sided (guide) | uint8, one sided (guide); HWA programs `winLen>>1` per side | DSP passes `winLen` as one-sided `noiseLen` | `winLen` 16 shipped; Doppler `guardLen` 0 |
| threshold | `uint16` raw log2 Q9 | float dB, <= 100, 2 decimals kept | same | float dB, <= 100 |
| `subFrame` | n/a | -1 = all, 0..3 advanced frame | same | -1 |

Sources: SDK 2.1.0.4 `xwr14xx/mmw/mmw_cli.c:162-236,765-781`; SDK 3.6 `xwr18xx/mmw/mss/mmw_cli.c:454-557` (68xx textually identical); cascade `mmw_cli.c:643-704,2255-2262`.

### HPF and rxGain tables (E1-E6)

**E1. HPF corner codes (all chips):** HPF1 0/1/2/3 = 175 / 235 / 350 / 700 kHz; HPF2 0/1/2/3 = 350 / 700 / 1400 / 2800 kHz. Datasheet footnotes: SWRS211C 5.7 (2), SWRS212B 5.7, SWRS228B 7.7 (3), SWRS219F 7.9 (2) (IWR6843 and ODS: the same die), SWRS223D 7.7 (2). Code order: `rlProfileCfg_t` `hpfCornerFreq1/2` (`rl_sensor.h:522`ff.) and the SDK 3.6 user guide sec. 3.3.1.

**E2. `rxGain` word:**

| Item | Value |
|---|---|
| Layout | b5:0 gain (1 LSB = 1 dB, even values), b7:6 RF gain target code, b15:8 reserved |
| 0x5E (Studio json) | b5:0 = 30 dB, b7:6 = 01 (34 dB on xWR1xxx, 33 dB on xWR6843 ES2.0, AWR2243 unverified) |
| 158 = 0x9E (shipped IWR6843/ODS) | b5:0 = 30, b7:6 = 10 (36 dB on xWR6843 ES2.0; RESERVED on xWR1xxx); TI staff: 158 = RF-gain bits + RX-gain bits |
| 160 on AWR2243 ("32+2<<6") | VGA 32 dB + RF target code 2 (medium) |
| 30 / 40 (shipped IWR1443, 1843, cascade) | b7:6 = 00 (30 dB) |

**E3. Valid range and RF target code (b7:6 = 00 / 01 / 10 / 11):**

| Chip | b5:0 min..max (step 2) | RF target dB | Source |
|---|---|---|---|
| IWR1443, IWR1642, IWR1843 | 24..48 | 30 / 34 / RESERVED / 26 | datasheet 5.7 / 7.7; mmwavelink doc (high) |
| IWR6843 / ODS | 30..48 | ES2.0: 30 / 33 / 36 / RESERVED (ES1.0 fixed 34) | SWRS219F 7.9; quoted header text (medium) |
| AWR2243 | 32..52 | unverified; forum posts give 30 / 33 / 36, TI advises a 36 dB target | SWRS223D 7.7 (high range), forum (low) |

The family header says "24 to 52"; use the tighter per-part datasheet bounds.

**E5. IF bandwidth and ADC rate (max):** IWR1443 15 MHz, 37.5 / 18.75 Msps (real / complex 1x); IWR1642 5 MHz, 12.5 / 6.25; IWR1843 10 MHz, 25 / 12.5; IWR6843/ODS 10 MHz, 25 / 12.5; AWR2243 20 MHz, 45 / 22.5. Complex-1x usable bandwidth at max rate is the IF limit on all five (`min(IF, 0.9 fs)`: 15 / 5 / 10 / 10 / 20 MHz).

**E6. Digital passband by ADC output mode (`adcCfg` `<adcOutputFmt>`: 0 real, 1 complex 1x "image band filtered output", 2 complex 2x "image band visible"):** complex 1x `0.9 fs`; complex 2x and real `0.45 fs`. `adcbufCfg` `<adcOutputFmt>`: 0 complex, 1 real (ADC-buffer terms). The DCA1000 stream's mode is fixed by `adcCfg`, not `adcbufCfg`.

## Sources

TI documents and tools (all read for the sections above; datasheet revisions as cited in the text):
- mmWave SDK 02.01.00.04 (`mmwave_sdk_02_01_00_04-Linux-x86-Install.bin`), `mmw_output.h` sha256 `f879704f138e8ed063353924cac313767953a2606a88974a7fc1d47364209ea9`, `xwr14xx/mmw/main.c` sha256 `29869f48d850f0efced77eef70fffe1ca925b954f6a9167c6f36d6d733a67076`; SDK 1.2.0.5 mirror `sgs-weather-and-environmental-systems/TI-mmWave-SDK`; MMWAVE SDK User Guide 2.1 sec. 6.12; Gorordo, IWR1443 Read Data Python (`github.com/ibaiGorordo/IWR1443-Read-Data-Python-MMWAVE-SDK-1`).
- mmWave SDK 03.06.02.00-LTS (`ti.com/tool/MMWAVE-SDK`) and its user guide; mmWave SDK 1.1 user guide.
- Radar Toolbox 4.00.00.05 `mmwave_2_chip_cascade` and `Two_Chip_Cascade_user_guide.html` (`ti.com/tool/download/RADAR-TOOLBOX`).
- Datasheets: IWR1443 SWRS211C, IWR1642 SWRS212B, IWR1843 SWRS228B, IWR6843 SWRS219F, AWR2243 SWRS223D (`ti.com/lit/ds/symlink/<part>.pdf`); DCA1000EVM user's guide SPRUIJ4A; mmWave Radar Interface Control Document rev 2.23 (AWR2243).
- SWRU546E (xWR6843ISK / ISK-ODS / AOP EVMs, `ti.com/lit/ug/swru546e/swru546e.pdf`); SWRA553 (Programming Chirp Parameters, `ti.com/lit/pdf/swra553`); SWRA551 (AWR1642 bootloader flow); SWRA581B (LVDS format); AR1243/AR1642 digital baseband application note v0.6.
- UniFlash 9.6 (`ti.com/tool/UNIFLASH`, quick-start guide); TI E2E threads: AWR1843 UniFlash command line (843614), mmWave UniFlash FAQ (856044), AWR6843 Rx gain (1023606), IWR6843 rxgain bounds (1349124), AWR2243 PF_RX_GAIN (1067971) and RF target (1185429), IWR1443 LVDS streaming (732245); mmwavelink doxygen `rlProfileCfg_t`, `rlAdcBitFormat_t`.
