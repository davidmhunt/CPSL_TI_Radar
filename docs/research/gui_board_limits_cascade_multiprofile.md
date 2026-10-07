# gui-13 Step 2: cascade limits, multi-profile/chirp restrictions and firmware matrix

**Date:** 2026-10-06
**Memo:** docs/research/gui_board_limits_cascade_multiprofile.md

Working note (exempt from rule 16). Paths: `CAS/` = `firmware_dev/projects/awr2243_cascade_ddm/src/ti/`; `SDK36/` = `packages/ti/` of mmWave SDK 3.6.02.00-LTS (installer in `firmware_dev/downloads/`, unpacked in scratch for this pass; it is the source of the `ti_stock_demos` and `iwr1843_sar_lvds` builds). `SAR/` = `firmware_dev/projects/iwr1843_sar_lvds/src/`. The IWR1443 (SDK 2.x) and the prebuilt v1 `.bin` files have no source in the tree and were not opened.

## Question as asked

Directive gui-13 Step 2: (1) verify every limit in `config/firmware/cascade_ddm.json` (`AWR2243_CASCADE`); (2) per board/firmware, how many profiles / chirpCfg entries per frame, `advFrameCfg`/subframe support, profile-index rules, TX-to-chirp mapping (TDM vs DDMA/BPM); (3) confirm/correct `boards`/`outputs` of each `config/firmware/*.json`; (4) is the cascade DDMA Doppler FFT over `loops` or over `chirps_per_loop x loops`? Table verdicts: confirmed / corrected / unverifiable.

**User feedback applied (2026-10-06, binding).** (a) The user's Doppler model (FFT over loops, $T_{loop}=n_{cpl}T_c$, $v_{res}=\lambda/(2\,L\,T_{loop})$, $v_{max}=\lambda/(4T_{loop})$) is compared with the firmware and with `radar_gui/cfg/metrics.py` in section 4. (b) The firmware matrix is framed per board (demo firmware + customizations), section 3. No code was edited.

## TL;DR

- **DDMA Doppler FFT is over all chirps in the frame, $N=n_{cpl}\times L$, not over `loops`.** `CAS/demo/utils/mmwdemo_rfparserDDMA.c:786-789`. So `metrics.py` `n_chirps = cpl x loops` for velocity resolution is **confirmed**; the "up to 8x too fine" worry does not apply. The user's resolution formula gives the same number ($N T_c = L\,T_{loop}$). The user's FFT-length statement and $v_{max}=\lambda/(4T_{loop})$ do **not** match the firmware: it reports velocity over the full $\pm\lambda/(4T_c)$ span (`objectdetection.c:698-716`), which is what `metrics.py` uses. Divergence flagged for the user (section 4).
- Cascade limits: TX 6 / RX 8, 76-81 GHz, `numLoops` 255 confirmed; **max slope and sample-rate bounds are corrected** (silicon 266 MHz/us, 2000-50000 ksps; the 100 MHz/us and 2000-10000 ksps are repo/TI-tested values, keep them as "tested" warnings, not as hardware limits); 192 samples / 256 chirps are TI-tested only (confirmed as such), the firmware does not enforce them.
- Firmware matrix corrections: `demo_stock` and `demo_lvds` are the **same SDK 3.6 binary** on 1843/6843 (lvdsStreamCfg is in its CLI), so `demo_stock.outputs.lvds=false` is wrong for 1843/6843; `dca1000_raw` also ships for the **IWR6843** (missing from `boards`); the 1443 demo lacks LVDS (web evidence only). The user's per-board model is consistent with the sources.

## Evidence

### 1. Cascade (`cascade_ddm`) limits: verification table

Verdict key: C confirmed, X corrected, U unverifiable (here). Confidence H/M/L.

| Limit | Current | Verified | Source | Conf. | Verdict |
|---|---|---|---|---|---|
| `n_tx` | 6 | 6 max; valid TX counts for DDMA are 2, 3, 4, 6 (1 and 5 give `numBandsEmpty=-1`) | `CAS/common/syscommon.h:72` (`SYS_CASCADE_NUM_TX_ANTENNAS 6`); `CAS/demo/am273x/mmw/mss/mss_main.c:4032-4058`; `rfparserDDMA.c:463-473` | H | C (add "2/3/4/6 only") |
| `n_rx` | 8 | 8 (2 x 4); 3-RX-per-chip rejected by range DPU | `syscommon.h:67`; `rangeprochwaDDMA.c` (`numRxAntennas == 3U` -> ENOTIMPL); `mss_main.c:2437` merges both chips' RX masks | M | C |
| `band_ghz` | 76-81 | 76-81 (VCO2); other VCOs exist but are outside the EVM's tested range | `CAS/control/mmwave/include/rl_sensor.h` startFreqConst note ("AWR2243: VCO2 range is 76-81 GHz"); datasheet SWRS223D | H | C |
| `max_slope_mhz_us` | 100 | Silicon 266 MHz/us (`freqSlopeConst` -5510..5510, 48.28 kHz/us LSB). 100 is `cfggen.py MAX_SLOPE`, not a hardware bound | `rl_sensor.h` rlProfileCfg `freqSlopeConst` note; datasheet SWRS223D | H | X (hardware 266; keep 100 as "tested") |
| `max_sample_rate_ksps` | 10000 | Silicon `digOutSampleRate` 2000..50000 ksps (20 MHz IF); firmware does not check; TI cfgs use 5000/10000 | `rl_sensor.h` rlProfileCfg `digOutSampleRate` note; `CAS/configs/*.cfg` | H | X (hardware 50000; 10000 is tested) |
| `min_sample_rate_ksps` | 2000 | 2000 | same `rl_sensor.h` note | H | C |
| `tested_sample_rates_ksps` | [5000,10000] | Same set in the four shipped cfgs (5000: short/very long; 10000: long) | `firmware_dev/.../configs/cascade_*.cfg` `profileCfg` | H | C |
| `min_idle_us` | 4.0 | Field range 0..524287 x 10 ns; the true minimum is a device-timing figure (datasheet / ICD) that no source here states. TI cfgs use 4-5 us. `cfggen.py` value is a guess | `rl_sensor.h` idleTimeConst; `configs/cascade_longrange.cfg` (idle 4) | L | U |
| `max_loops` | 255 | 255 in legacy frame mode (`numLoops` 1..255); 32768 total chirps in advanced-chirp mode (not used by the DDMA cfgs) | `rl_sensor.h` rlFrameCfg `numLoops` (lines ~972-980) | H | C |
| `max_samples` | 192 | **Not enforced** by firmware. Silicon ADC buffer: 16 kB (1024 complex samples for 4 RX/chip); TI "tested only" statement is the limit | Two_Chip_Cascade_user_guide.html ("Chirp design is limited to 192 adc samples, 256 chirps, and 8 channels. No other configuration has been tested"); `rl_sensor.h` numAdcSamples table | H (as tested) | C (as tested, not as hardware) |
| `max_chirps` | 256 | Same TI-tested statement. Firmware only needs $N$ valid FFT size (`mathUtils_getValidFFTSize`, power of 2 or 3x power of 2 per `dopplerprochwaDDMA.c:1081`) and radar-cube size to match | user guide (above); `dopplerprochwaDDMA.c:1081-1086` | M | C (as tested) |
| `lvds_supported` | false | false: neither `LVDS_STREAM` nor `ENET_STREAM` is defined in the build (`mmw_cli.c:111-118` are `#ifdef`'d; projectspec defines only `MMWDEMO_DDM`, `CASCADE_EVM`) | `mmwave2chipCascade_mss.projectspec:54-55`; `mmw_cli.c:111-118` | H | C |
| `sdk` | mmwave_mcuplus | MCU+ SDK 04.04.00.01 | `docs/firmware.md` toolchain table | H | C |
| `frame_cfg_args` | 9 | cfg shows `frameCfg` with 9 fields (`0 7 32 0 192 50 1 0 2`); field meaning (field 5 = numAdc, 6 = period) is read from cfg, not the parser | `configs/cascade_shortrange.cfg` | M | C |
| `channel_cfg_args` | 5 | 5 (`channelCfg 15 7 1 15 7`) | same cfg | H | C |
| `config_once_per_boot` | true | true (user guide: "sending another configuration is not supported ... power cycle") | user guide text above; `docs/firmware.md` quirks | H | C |

Cascade-only facts worth putting in the descriptor: `numDopplerBins` of 3x2^n is allowed; Doppler bins per TX sub-band $=N_{FFT}/n_{bands}$ with $n_{bands}=6+2$ empty $=8$ (`mss_main.c:4032-4058`, `dopplerprochwaDDMA.c:604`); `numDopplerChirps<=4` forces 8 bins (`mss_main.c:2394-2397`, only meaningful for tiny frames).

### 2. Multi-profile / multi-chirp restrictions per firmware

Common SDK 3.6 mmWave library (stock, SAR) and MCU+ cascade library: `MMWAVE_MAX_PROFILE = 4` (`SDK36/control/mmwave/mmwave.h:276`; `CAS/control/mmwave/mmwave.h:346`), `RL_MAX_PROFILES_CNT = 4`, `RL_MAX_SUBFRAMES = 4` (`rl_sensor.h:89,94`). The CLI stores each `profileCfg` in the first free slot and fails the fifth (`SDK36/utils/cli/src/cli_mmwave.c:680-692`); `chirpCfg` attaches to a profile by id via `MMWave_getProfileHandle` (`cli_mmwave.c:775-780`). Chirp indices 0-511 (`rl_sensor.h` rlFrameCfg).

**The demo data path uses one profile.** The RF parser comment says "we support only one profile in this processing chain" (`SDK36/demo/utils/mmwdemo_rfparser.c:788`; `CAS/.../mmwdemo_rfparserDDMA.c:669`). It takes the first profile (lowest slot) that has chirps inside the frame's `chirpStartIdx..chirpEndIdx` with a TX in `channelCfg`, and reads all RF parameters from that profile alone; extra profiles are accepted by the CLI but ignored by the processing chain. For `numChirpsPerFrame` the chirps in the range must all belong to that one profile (any index in the range with `txEn==0` makes the profile invalid -> `EINVAL__VALID_PROFILECFG_NOT_FOUND`, `mmwdemo_rfparser.c:517-521`). Profile id need not be 0.

| Firmware | Profiles accepted (CLI) / used | chirpCfg entries / chirps per loop | `advFrameCfg` + `subFrameCfg` | TX-to-chirp mapping rule | Source | Conf. |
|---|---|---|---|---|---|---|
| `demo_stock` (1843, 6843; SDK 3.6) | up to 4 / 1 used | any number in `chirpStart..chirpEnd`; parser flags >32 unique chirps (`ENOIMPL`) but **does not enforce it** (`retVal` overwritten at `mmwdemo_rfparser.c:782-784` then `:800`), and `validChirpTxEnBits[32]` would overflow, so treat 32 as the real limit | Supported, up to 4 subframes, `numOfBurst` must be 1 (`mmwdemo_rfparser.c:774-778`); each subframe is parsed on its own with one profile (`forceProfileIdx`), shipped `profile_advanced_subframe.cfg` uses 4 subframes | TDM: one TX per chirp, same mode on all chirps (mixing TDM and SIMO rejected, `:526-560`); elevation chirp = `elevTxAntMask` (3-TX chips); BPM: `bpmCfg` and every chirp must enable both azimuth TX (`:530-540`); $N_{Dopp}=N_{chirps}/n_{TX}$, bins = next pow2 (`:885-888`) | `mmwdemo_rfparser.c` ranges cited; `cli_mmwave.c:913-945`; `ti_stock_demos/configs/xwr18xx/profile_advanced_subframe.cfg` | H |
| `demo_lvds` (1843, 6843) | same binary as `demo_stock` | same | same; HW LVDS session reconfigured per subframe, SW and HW sessions never both active (`xwr18xx/mmw/mss/mss_main.c:~425-436`); with both HW and SW LVDS on, header must be enabled (`mmw_cli.c:1126-1131`) | same | `SDK36/demo/xwr18xx/mmw/mss/` | H |
| `dca1000_raw` (Studio-CLI / lvds_stream binaries) | not checkable (binaries only) | cfgs in repo use 2 chirps (`profile_monitor_xwr18xx.cfg`: `chirpCfg 0 0` and `1 1`, TX 1 and 4) and one profile | unknown | unknown | `Firmware/DCA1000_Streaming/studio_cli/profiles/*.cfg` | L, **U** for rules |
| `iwr1843_sar_lvds` (MSS-only) | up to 4 / `validProfileIdx` one used (`SAR/mss/mss_main.c:1087-1107,1146`) | uses the SDK 3.6 parser: same chirp rules; frame mode only ("frame mode: sub-frame 0", line 1087) | **No subframes**: only subframe 0 is parsed; `profile_advanced_subframe.cfg` is a leftover in `configs/` (not a supported mode; no on-board test seen) | TDM as stock; cfg is applied after `flushCfg`, `channelCfg`/`adcCfg`/`lowPower` frozen after first start (`mss_main.c:~64-70`) | `SAR/mss/mss_main.c` | M |
| `cascade_ddm` | up to 4 / 1 used (first profile with chirps in range) | `chirpStart..chirpEnd` = chirps per loop (TI: 8 identical chirps, one `chirpCfg 0 7 ...` line, `frameCfg 0 7 32`); `>32` check is commented out (`rfparserDDMA.c:663-665`) | **Not supported**: `MmwDemo_configPhaseShifterChirps` prints "Advanced Subframe Config is not currently supported with the DDMA chain" and returns -1 (`mss_main.c:3888-3891`); parser accepts advanced frame but the chain stops there | **DDMA, not TDM.** All 6 TX transmit on every chirp; per-chirp phase shifts `phi = (chirp k)*(tx rank)/n_bands` (`mss_main.c:3796-3850`; `txAntMaskEnable = 63` is hard-coded, line ~3828); the parser overwrites `validChirpTxEnBits` with the merged `channelCfg` TX mask, so `chirpCfg txEnable` only has to overlap it (`rfparserDDMA.c:~716`). `n_bands` = 6 TX + 2 empty = 8 (valid TX counts 2/3/4/6) | as cited | H |
| `demo_stock` 1443 (SDK 2.x) | not in tree | not in tree | not in tree | not in tree | -- | **U** |

Inferred, not enforced by any check found (HYPOTHESIS for the validator, discriminating test = run a cfg with chirps per loop not a multiple of 8 and see whether detections stay coherent): for DDMA the phase pattern repeats every `n_bands` chirps (`(chirpEnd+1-k) % n_bands`), so chirps per loop should be a multiple of `n_bands` (8 for 6 TX). Every shipped TI cascade cfg uses exactly 8 (`configs/cascade_*.cfg`).

All 36 repo cfgs under `CPSL_TI_Radar_cpp/config/radar/` carry exactly one `profileCfg`, consistent with the one-profile chain.

### 3. Firmware matrix (per board, as the user framed it)

Sources: `Firmware/` file listing; `docs/firmware.md`; `SDK36/demo/xwr{18,68}xx/mmw/mss/mmw_cli.c` (each has `lvdsStreamCfg`); `SAR/mss/mss_main.c:40-70`; `CAS/.../mmw_cli.c:111-118`; web for the 1443.

| Board | Demo firmware (TLV / LVDS) | Customizations / alternates | Where it comes from | Conf. |
|---|---|---|---|---|
| IWR1443 | `xwr14xx_mmw_demo.bin`: TLV yes, **LVDS no** | `xwr14xx_lvds_stream.bin` (raw ADC, DCA1000, no TLV); `mmwave_Studio_cli_xwr14xx.bin` | `Firmware/IWR_Demos/`, `Firmware/DCA1000_Streaming/iwr_raw_rosnode/firmware/`, `.../studio_cli/prebuilt_binaries/` | TLV: H; "no LVDS": M (TI E2E: LVDS in the 14xx SDK demo is "unverified code ... conflicts with data path"; no source here) |
| IWR1843 | SDK 3.6 `mmw` demo (`ti_stock_demos` -> `iwr1843_demo.bin`): TLV yes, **LVDS yes** via `lvdsStreamCfg` (HW session ADC; SW session user data) | `iwr1843_sar_lvds` (TLV no, LVDS dataFmt 1/2, `sarStats`); `mmwave_Studio_cli_xwr18xx.bin` (raw) | `firmware_dev/projects/`, `Firmware/DCA1000_Streaming/studio_cli/` | H |
| IWR6843 | SDK 3.6 `mmw` demo (`iwr6843_demo.bin`): TLV yes, LVDS yes | `xwr68xx_lvds_stream.bin` + `lvds_stream_68xx.cfg` (raw); `mmwave_Studio_cli_xwr68xx.bin` | same | H |
| AWR2243 cascade | `am273x_cascade.appimage` (DDMA demo): TLV yes (UART data port 3,125,000 baud), **LVDS to host no**, Ethernet stream no (compile flags off) | none | `firmware_dev/projects/awr2243_cascade_ddm` | H |

Note: the v1 prebuilt `Firmware/IWR_Demos/` holds only `xwr14xx_mmw_demo.bin` and `xwr16xx_mmw_demo.bin`; the 1843/6843 demo images come from `ti_stock_demos` builds (no prebuilt 18xx/68xx demo is tracked).

**Corrections to `config/firmware/*.json` (read, not edited):**

| File | Field | Current | Verified | Verdict |
|---|---|---|---|---|
| `demo_stock.json` | `outputs.lvds` | false | true for 1843/6843 (same binary as `demo_lvds`); false only for 1443 | X |
| `demo_stock.json` | `boards` | 1443, 1843, 6843 | confirmed, but outputs differ per board (needs per-board outputs, which the user's inversion gives) | C / X (schema) |
| `demo_lvds.json` | existence | separate firmware, boards 1843, 6843, `tlv:true, lvds:true` | correct outputs, but not a separate firmware: one binary, enabled by cfg (`lvdsStreamCfg`). Fold into `demo_stock` per board | X |
| `dca1000_raw.json` | `boards` | 1443, 1843 | add 6843 (`xwr68xx_lvds_stream.bin`, `studio_cli` 68xx) | X |
| `dca1000_raw.json` | `outputs` | tlv false, lvds true | confirmed from `lvds_stream` naming and Studio-CLI cfgs (`lvdsStreamCfg`); binaries not inspected | C (M) |
| `iwr1843_sar_lvds.json` | `boards` / `outputs` | `IWR1843_SAR`, tlv false, lvds true | confirmed (`SAR/mss/mss_main.c:40-48`) | C |
| `cascade_ddm.json` | `boards` / `outputs` | cascade, tlv true, lvds false | confirmed (above) | C |

The user's statements: "1843/6843 demos support TLV and LVDS out of the box" **confirmed** (`lvdsStreamCfg` registered in both `mmw_cli.c`; ties to `demo_lvds`); "1443 demo has no LVDS" **plausible, not source-verified** (SDK 2 not available); "cascade has no LVDS" **confirmed**; "DCA1000 raw firmware ships for 1443/1843" **confirmed and also 6843**.

### 4. DDMA Doppler FFT length and the user's convention

Firmware (`CAS/demo/utils/mmwdemo_rfparserDDMA.c`):
- `:786` `numChirpsPerFrame = frameTotalChirps * numLoops` (= $n_{cpl}L$);
- `:788-789` `numDopplerChirps = numChirpsPerFrame`; `numDopplerBins = mathUtils_getValidFFTSize(numDopplerChirps)` (the TDM parser divides by `numTxAntennas`, the DDMA one does not);
- `:796` `chirpInterval = idle + rampEnd` ($T_c$, one chirp);
- `:803-807` `dopplerStep = c/(2*numDopplerBins*fc*Tc)`, `dopplerResolution = c/(2*numChirpsPerFrame*fc*Tc)`;
- `dopplerprochwaDDMA.c:1081-1086,1106` the HWA FFT size is `numDopplerBins` over `numChirps` input samples;
- per-TX sub-band bins $=N_{FFT}/n_{bands}$ (`dopplerprochwaDDMA.c:604`);
- `objectdetection.c:698-716` reported velocity = signed `dopIdxActual * dopplerStep`, folded about `numDopplerBins/2`: the span is $\pm N_{FFT}\,\text{step}/2=\pm\lambda/(4T_c)$.

Comparison:

| Quantity | Firmware | `metrics.py` (`:190-194`) | User's model | Match |
|---|---|---|---|---|
| FFT length | $N=n_{cpl}L$ (rounded to valid size) | $n_{cpl}L$ | $L$ | firmware = metrics, user differs |
| $v_{res}$ | $\lambda/(2NT_c)$ | $\lambda/(2NT_c)$ | $\lambda/(2LT_{loop})=\lambda/(2NT_c)$ | all equal numerically |
| $v_{max}$ reported | $\pm\lambda/(4T_c)$ | $\lambda/(4T_c)$ | $\lambda/(4T_{loop})$ | firmware = metrics; user's value is $n_{cpl}\times$ smaller |

Why the models differ: in DDMA every chirp is transmitted by all 6 TX with a different phase step, so a "loop" is not one TX per chirp, and the loop period is not the per-TX slow-time interval. TX separation happens in Doppler frequency: each TX owns one of $n_{bands}=8$ sub-bands of width $1/(8T_c)$. A target whose Doppler exceeds $\pm\lambda/(4\,n_{bands}\,T_c)$ falls into a neighbouring band (the 2 empty bands give slack, `mss_main.c:4032-4058`). With TI's $n_{cpl}=n_{bands}=8$, $T_{loop}=8T_c$ and the user's $\lambda/(4T_{loop})$ equals this **per-TX-band unambiguous velocity** (e.g. shortrange: $T_c=50\,\mu s$, $T_{loop}=400\,\mu s$: 2.4 m/s versus 19.5 m/s full span). So: the firmware convention is the full span (metrics matches); the user's number is the safer physical "no band aliasing" limit and holds only while $n_{cpl}=n_{bands}$; in general the band-limited value is $\lambda/(4\,n_{bands}T_c)$ independent of $n_{cpl}$. Corroboration: TI's `gtrack` line in `cascade_shortrange.cfg` carries 19.41 and 0.1522, i.e. $\lambda/(4T_c)$ and $\lambda/(2NT_c)$ at 77 GHz, 50 us, 256 chirps (parameter meaning not checked against the tracker source, M).

**Divergence for the user to rule on** (no code edited): `metrics.py` DDMA `max_velocity` is the full firmware-reported span; the user's convention gives a value $n_{cpl}$ times smaller. Suggest displaying the band-limited figure $\lambda/(4\,n_{bands}T_c)$ beside it, or replacing it, per the user's choice. $v_{res}$ needs no change.

## Applicability to CPSL TI Radar

- Descriptor values to adopt in Step 3: add cascade `max_slope` hardware 266 and `max_sample_rate` hardware 50000 as `error`-level bounds if desired, with the 100 / 10000 values staying as "tested" warnings; `n_tx` valid set {2,3,4,6}; `min_idle_us` stays `unverified`.
- gui-15 restrictions to encode: one profile used (extra profiles are silently ignored); DDMA: no `advFrameCfg`, chirps per loop a multiple of `n_bands` (HYPOTHESIS, not enforced by firmware), TX count in {2,3,4,6}, one cfg per boot; stock 1843/6843: up to 4 subframes, `numOfBurst=1`, all chirps from one profile, TDM one TX per chirp; SAR: no subframes; effective limit 32 chirps per loop for stock.
- Descriptor schema: per-board firmware list (user's model) fits; `demo_lvds` should not be a separate firmware id.

## Recommended Experiment

1. Bench (cascade, one power cycle per cfg): run `cascade_shortrange.cfg` with `chirpCfg 0 3` and `frameCfg 0 3 64 ...` (4 chirps per loop) and compare detections and `dopplerStep` against the 8-chirp case; discriminates the multiple-of-8 hypothesis.
2. Bench (1843): `profileCfg 0` and `profileCfg 1` with chirps split across them; confirm the second profile is ignored (expect parameters from the lower-slot profile covering the frame).
3. Bench (1843 SAR): send `advFrameCfg`; expect no subframe behaviour.
4. Optional: unpack SDK 2.1 and `strings`-free check `xwr14xx/mmw/` CLI table for `lvdsStreamCfg`.

## Confidence

High on everything cited from source (cascade and SDK 3.6 parsers, CLI, `rl_sensor.h`). Medium on the 1443 "no LVDS" claim (web only), on `dca1000_raw` outputs (binaries and their sources not inspected), and on the multiple-of-8 chirp rule (inferred from the phase-shifter code, not enforced). **Unverifiable here:** cascade `min_idle_us` (datasheet/ICD timing; not in headers); multi-profile/subframe rules for the 1443 (SDK 2.x not in tree), for `dca1000_raw` binaries and the Studio-CLI image; hardware (not TI-tested) ceilings for cascade samples and chirps beyond TI's "tested" statement; whether the shipped prebuilt cascade `.appimage` equals this source build (not compared). Web figures come from the AWR2243 datasheet SWRS223D via search snippets and are cross-checked locally against `rl_sensor.h` for slope and sample rate.

## Sources

- `ti_mmwsdk36_rfparser` — Texas Instruments (2021), "mmWave SDK 3.6.02.00-LTS packages/ti/demo/utils/mmwdemo_rfparser.c, utils/cli/src/cli_mmwave.c, demo/xwr18xx/mmw/mss, control/mmwave/mmwave.h," *TI MMWAVE-SDK installer (firmware_dev/downloads)*. url:https://www.ti.com/tool/MMWAVE-SDK
- `ti_cascade_ddm_src` — Texas Instruments (2026), "Radar Toolbox 4.00.00.05 mmwave_2_chip_cascade source as tracked in firmware_dev/projects/awr2243_cascade_ddm (mmwdemo_rfparserDDMA.c, mss_main.c, dopplerprochwaDDMA.c, rl_sensor.h)," *TI Radar Toolbox* (download page; local copy cited). url:https://www.ti.com/tool/download/RADAR-TOOLBOX
- `ti_cascade_user_guide` — Texas Instruments (2026), "Two Chip Cascade user guide (Two_Chip_Cascade_user_guide.html), config-once and tested-design statement," *TI Radar Toolbox docs* (bundled HTML; local copy at firmware_dev/projects/awr2243_cascade_ddm/docs/). url:https://www.ti.com/tool/download/RADAR-TOOLBOX
- `ti_awr2243_datasheet` — Texas Instruments (2024), "AWR2243 datasheet SWRS223D (76-81 GHz, 266 MHz/us ramp, 45 Msps, 20 MHz IF)," *TI*. url:https://ti.com/document-viewer/AWR2243/datasheet/GUID-DFD2124E-689E-4659-8779-296EBD24389C
- `ti_e2e_1443_lvds` — TI E2E forum (2019), "iwr1443 xwr14xx lvds streaming," *TI E2E*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/732245/iwr1443-xwr14xx-lvds-streaming

Note: descriptive keys as in `sdk2_uart_format_2026-10-05.md`; no PDFs archived (installer sources); `references.bib` not edited (Researcher namespace for this pass is the memo only).
