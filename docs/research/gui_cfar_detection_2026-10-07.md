# On-chip CFAR detection commands per firmware (gui-35 Step 1)

**Date:** 2026-10-07
**Memo:** docs/research/gui_cfar_detection_2026-10-07.md

## Question as asked

For directive gui-35 Step 1: for each shipped firmware (IWR1443 SDK 2.x demo, IWR1843 / IWR6843 / IWR6843ODS SDK 3.6 demo, AWR2243 cascade AM273x DDM demo; SAR and `dca1000_raw` have none) give the exact `cfarCfg`, `cfarFovCfg` and peak-grouping argument order, types, units, valid ranges, shipped defaults, cross-field rules, whether a direction can be disabled, whether the command is accepted while running, and the cascade-only fields. Scope per the user's ruling: CFAR only; the C++ driver does not enforce. No hardware.

Confidence tags: **[C]** confident (read in source or UG, and unambiguous), **[L]** likely (source-read, behaviour inferred), **[U]** unknown. SDK sources were read from the TI SDK trees extracted from the installers in `firmware_dev/downloads` (SDK 3.6 and 2.1.0.4; extracted trees were in session scratch, so re-extract to re-check). Cascade sources are tracked in `firmware_dev/projects/awr2243_cascade_ddm/src/` (cited as `casc:`). Paths below with no prefix are relative to the SDK `packages/ti/`.

## TL;DR

Three dialects, but the 3.6 demo splits into two CFAR engines: IWR1843 uses the HWA DPU, IWR6843 and ODS use the DSP DPU, with different rules (below). **Corrections to the Planner's table:** (1) the shipped IWR1443 binary is byte-identical (sha256 `b6b6d8f3...`) to `xwr14xx_mmw_demo.bin` in SDK 2.1.0.4, so the 1443 SDK is **02.01.00.04 [C]**; (2) `cfarFovCfg` is **not registered at all in the cascade DDM build** (it sits under `#ifdef MMWDEMO_TDM`, `casc: mmw_cli.c:2297-2311`), so the GUI must never emit it for the cascade [C]; (3) the cascade's `isEnabled=0` on Doppler prints an error but does **not** return failure and the line is still stored (`mmw_cli.c:697-700`) [C for the code, bench for the effect]. The 1443 threshold is a raw log2 Q9 value, convertible to dB: $T_{cli}=512\,\frac{T_{dB}}{6}\,\frac{N}{N'}$ with $N$ virtual antennas, $N'=2^{\lceil\log_2 N\rceil}$ [C]; the shipped `1280` is 15 dB and `2304` is 27 dB for the 2-TX, 4-RX shipped cfg ($N=8$). On 3.6 and the cascade, `cfarCfg` threshold is dB (float, 0-100, stored x100) [C], both directions of `cfarCfg` and `cfarFovCfg` are mandatory before the first `sensorStart` on 3.6 [C], and Doppler CFAR can be switched off only by `threshold 0` on the 1843 HWA DPU [L]; it cannot on the cascade.

## Evidence

### 1. Command forms, one table (args after the command name)

| | IWR1443 (SDK 2.1.0.4) | IWR1843 (SDK 3.6, HWA DPU) | IWR6843 / ODS (SDK 3.6, DSP DPU) | AWR2243 cascade (MCU+ 4.4 DDM) |
|---|---|---|---|---|
| `cfarCfg` argc | 7 args (argc 8) [C] | 9 args (argc 10) [C] | 9 args [C] (handler diff-identical to 18xx) | 12 args (argc 13) [C] |
| order | `procDir mode noiseWin guardLen divShift cyclic thresholdScale` | `subFrame procDir mode noiseWin guardLen divShift cyclic thresholdDb peakGrouping` | same as 1843 | 1843 order + `osKvalue osEdgeKscaleEn isEnabled` |
| separate `peakGrouping` cmd | yes: `scheme rangeEn dopplerEn startIdx endIdx` (5 args) [C] | no, last arg of `cfarCfg` [C] | no, same [C] | no, `peakGrouping` field inside `cfarCfg` [C] |
| `cfarFovCfg` | not in this firmware [C] | `subFrame procDir min max` [C] | same [C] | **not registered** [C] |
| mandatory | `cfarCfg`, `peakGrouping` per UG; not enforced by the CLI [C] | both directions of `cfarCfg` and `cfarFovCfg` or first `sensorStart` fails [C] | same [C] | not enforced [C] |

Sources: 1443 `demo/xwr14xx/mmw/mmw_cli.c:162-187` (cfarCfg), `:206-236` (peakGrouping), `:765-781` (table; `helpString` is NULL in the shipped build, so there is no on-board usage text); 3.6 `demo/xwr18xx/mmw/mss/mmw_cli.c:454-510` (cfarCfg), `:526-557` (cfarFovCfg), `:1356-1358`, `:1396-1398` (help strings, argument order); the 68xx handlers are textually identical (diffed); cascade `casc: demo/am273x/mmw/mss/mmw_cli.c:643-704` (DDM cfarCfg), `:2255-2262` (help), registration of `cfarFovCfg` only inside `#ifdef MMWDEMO_TDM` at `:2297-2311` (DDM is the built variant: `build/stage/*.projectspec` define `MMWDEMO_DDM`). Mandatory check: 3.6 `demo/xwr18xx/mmw/mss/mmw_cli.c:155-170` ("Error: Full configuration must be provided before sensor can be started the first time") calls `MmwDemo_isAllCfgInPendingState`, which requires `isCfarCfgDopplerPending`, `isCfarCfgRangePending`, `isFovDopplerPending`, `isFovRangePending` (and the other detection-chain commands) (`mss_main.c:890-905`). The cascade has no such check (`casc: mss_main.c:1171-1193` only sets pending bits).

The argument count is exact (`argc != N` is an error, `MmwDemo_CLIGetSubframe` at `mmw_cli.c:369-391` on 3.6; `argc != 8` on 1443). All integer fields are cast to `uint8_t` (`atoi`), so 256 wraps to 0 silently on every firmware; the GUI should cap them at 255 or lower [C]. The 1443 procDirection is read but ignored (`mmw_cli.c:177` is commented out), UG says "only Range direction is supported", the shipped value is 0 [C]. SubFrame index: -1 = all subframes (legacy frame); `0..RL_MAX_SUBFRAMES-1` for advanced frame (`mmw_cli.c:381`); the corpus has explicit `0..3` only in four advanced-subframe cfgs (`profile_advanced_subframe.cfg` x3, `tests/fixtures/mimo/adv_subframe_4.cfg`), consistent with the directive's read-only treatment [C].

### 2. Field semantics, ranges, units

| Field | 1443 | 3.6 (1843 / 6843 / ODS) | Cascade |
|---|---|---|---|
| `mode` (averageMode) | 0 CA, 1 CAGO, 2 CASO (UG) [C] | 0 CA, 1 CAGO, 2 CASO (UG p. 27) [C] | **3 = CFAR-OS** (header: "3-CFAR_OS (HWA2.0 only)", `casc: dopplerprochwaDDMA.h:630`); 0-2 as before [C] |
| `noiseWin` | uint8; HWA programs `winLen>>1` per side (`config_hwa_util.c:638-639`) [C]; sidedness [U] | uint8, UG: "one sided"; HWA DPU: `winLen>>1` per side in HWA param (`cfarcaprochwa.c:194-195`) [U on sidedness]; DSP DPU passes `winLen` as one-sided `noiseLen` (`cfarcaprocdsp.c:723, 877`; mmwavelib `@pre len > 2*(noiseLen+guardLen)`) [C] | uint8, "one sided" (header), HWA programs `winLen>>1` (`casc: dopplerprochwaDDMA.c:2052-2053`); shipped 16 [C] |
| `guardLen` | uint8, one sided guard cells [L] | uint8, one sided (UG p. 27) [C] | must be **0 for the Doppler direction** ("Not applicable for CFAR-OS", `casc: dopplerprochwaDDMA.c:4000-4003` returns `DPU_DOPPLERPROCHWA_ERROR_METHOD_CFAR`); range direction unknown [U] |
| `divShift` | $\log_2$ of noise-sum divisor (UG p. 20: CA `log2(2*noiseWin)`, CAGO/CASO `log2(noiseWin)`, "should match") [C] | UG p. 27: CA `ceil(log2(2*noiseWin))`, CAGO/CASO `ceil(log2(noiseWin))`; DSP DPU adds 1 internally for mode != 0 (`cfarcaprocdsp.c:306-330`) so the user value follows the same formula [C] | not applicable in OS mode (`casc: dopplerprochwaDDMA.c:2065` "not applicable in CFAR_OS"); shipped 0 [C] |
| `cyclic` | 0/1, HWA [C] | 0/1. **DSP DPU ignores it** (no use of `cyclicMode` in `cfarcaprocdsp.c`; Doppler uses the wrap function, range the non-wrap one) [L]; HWA honours it [C] | 0/1; shipped 1 [C] |
| threshold | `uint16` raw, `atoi` (`mmw_cli.c:183`), passed to HWA `cfarThresholdScale` unchanged (`data_path.c:1511`). UG p. 20: log2 Q9, $T_{cli}=512\,T_{dB}/6\cdot N/N'$ [C]; max 65535 (cast), no range check [C] | float dB, **error if > 100.0** (`mmw_cli.c:480-483`), stored x100 as `uint16` (2 decimals kept, `MMWDEMO_CFAR_THRESHOLD_ENCODING_FACTOR 100.0`, `mmw_mss.h:71`), converted at config time to Q8 $T=T_{dB}\cdot\frac{256}{6}\cdot\frac{N}{N'}$ (`mss_main.c:1698-1714`) [C]. No lower-bound check; negative is undefined (float to `uint16`) [C]. UG p. 28: "Maximum value allowed is 100dB" | float dB, same 100.0 limit (`casc: mmw_cli.c:672-675`), conversion $\mathrm{lin}=\log_2(10^{T_{dB}/20})\cdot 2^{11}+0.5$ (`casc: mss_main.c:2226-2240`, amplitude dB, Q11) [C] |
| peak grouping | see section 3 | boolean per direction, last arg [C] | boolean per direction, arg 9 [C] |
| extra | n/a | n/a | `osKvalue` (uint8, the ordered-statistic K), `osEdgeKscaleEn` (0/1, "only used in CFAR_OS non-cyclic mode, scaling of K for edge samples", `casc: dopplerprochwaDDMA.h:652-660`), `isEnabled` (0/1) |

**Defaults seen in shipped cfgs** (corpus of 95 cfgs containing the commands; computed from every `*.cfg` outside `build/`): 1443: `cfarCfg 0 2 8 4 3 0 1280` x10, `... 2304` x1 (`radar_cfg_higher_CFAR.cfg`). 3.6: range (dir 0) always mode 2 (CASO), noiseWin 7-8, guard 4, divShift 3, cyclic 0; Doppler (dir 1) mode 0 (CA) or 1 (CAGO), noiseWin 4-8, guard 2-4, divShift 3-4, cyclic 1; thresholds 7-25 dB; peak grouping 0 or 1 per line. **All 168 3.6 lines (any subframe) satisfy the UG divShift formula**, so a divShift warning will not fire on the corpus. Cascade (24 lines): mode 3, winLen 16, guard 0, divShift 0, cyclic 1, K 7, edgeKscale 0, isEnabled 1 in every line; range threshold 10-15 dB, Doppler 12-25 dB; the only varying fields are the threshold and the peak-grouping flag (`1` on the Doppler line of the long-range cfgs). FOV (`cfarFovCfg`, 3.6 only, 168 lines): range min 0-1.5 m, max = the cfg's max range; Doppler symmetric $\pm v_{max}$. `radar_gui/cfg/generate.py:474-482, 509-510` already produces these.

### 3. Peak grouping

- **1443:** separate command, `peakGrouping <scheme> <rangeDirEn> <dopplerDirEn> <startRangeIdx> <endRangeIdx>` (`mmw_cli.c:206-236`). `scheme` must be 1 or 2 or the CLI errors ("Invalid peak grouping scheme"); the SDK 2.1 UG (p. 20) says the 1443 supports only scheme 1 (1 = det-matrix based, 2 = CFAR-peak based), so offer 1 only [C for the CLI check, L for scheme 2 on 1443]. `rangeDirEn` feeds the HWA `peakGroupEn` (`data_path.c:1483`), `dopplerDirEn` the software grouping (`post_processing.c:66-213`). `startIdx`/`endIdx` are range-bin indices of detections that are *kept*: with both direction flags 0 the filter still applies (`post_processing.c:117-128`, `noGrouping` branch). Shipped: `1 1 1 1 229` x5, `1 0 1 1 229` x2, others `1 1 1 1 {459,114,256}` (end index tracks the cfg's range FFT size) [C]. No upper-bound check; `endIdx` above `numRangeBins-1` keeps everything [L].
- **SDK 3.6:** no command; a 0/1 flag per direction at the end of `cfarCfg`. The scheme is hard-wired to det-matrix based (`datapath/dpc/objectdetection/objdetdsp/src/objectdetection.c:1387-1388, 2458, 2485`) [C]. The 1443-style start/end index is replaced by the FOV (`cfarFovCfg` range) [C].
- **Cascade:** same flag layout as 3.6; `peakGroupingScheme` is never set by the CLI (memset 0), and the header notes scheme 2 is unsupported on HWA (`dopplerprochwaDDMA.h:645-648`), so only the on/off flag is meaningful [C].

### 4. Cross-field rules (what the firmware enforces vs only the UG says)

| Rule | Where | Firmware behaviour | Tag |
|---|---|---|---|
| `2*(noiseWin+guardLen) < numRangeBins` (range), `< numDopplerBins` (Doppler) | UG p. 27 "make sure"; enforced as `(guard+win)*2 >= bins -> EINVAL` in `cfarcaprochwa.c:832-843` (HWA, 1843) and `cfarcaprocdsp.c:1115-1126` (DSP, 6843) | **not checked by the CLI**; the CLI answers `Done`, the DPU rejects at `sensorStart` config time. Failure presentation (UART text vs DSS-side assert/hang) not read to the end | rule [C], presentation [U] |
| `numRangeBins = pow2roundup(numAdcSamples)`, `numDopplerBins = pow2roundup(numChirpsPerFrame / numTx)` | `utils/mmwdemo_rfparser.c:884-888` (3.6) | inputs for the rule above; the GUI already knows both | [C] |
| HWA (1843): range `winLen == 2` invalid; Doppler `winLen == 2` invalid when Doppler threshold > 0 | `cfarcaprochwa.c:846-858` | `EINVAL` | [C] |
| divShift vs UG formula | UG p. 27 | no check anywhere in the CLI/DPC; a mismatch just rescales the threshold | [C] (warning is right) |
| cascade Doppler direction: `mode == 3` and `guardLen == 0` | `casc: dopplerprochwaDDMA.c:3993-4003` | DPU config error (`DPU_DOPPLERPROCHWA_ERROR_METHOD_CFAR`) | [C] |
| cascade `isEnabled == 0` on Doppler | `casc: mmw_cli.c:697-700` | prints "Error: Doppler CFAR Cannot be disabled." **but falls through** (no `return -1`), stores the line, CLI still answers `Done`; the DPU never reads Doppler `isEnabled`, so it is a no-op | [C code], effect bench |
| cascade `osKvalue` vs `winLen`, K range, `winLen` max, range-direction constraints | `rangecfarprocDDMA` is a precompiled SDK library, not in the repo | none readable. HWA 2.0 CFAR-OS limits live in the MCU+ SDK / HWA TRM | [U] |
| `thresholdScale == 0` = direction off | 1843 HWA: Doppler skipped when threshold 0 (`cfarcaprochwa.c:852, 880, 972, 1014, 1051`), range always runs. 6843 DSP: each direction skipped when its threshold is 0 (`cfarcaprocdsp.c:1198, 1216`). Cascade: range via `isEnabled` (`casc: objectdetection.c:1702, 1871`), Doppler never | gives a real "Doppler off" on the 1843 only; not documented in the UG | [L], bench |
| FOV | `cfarFovCfg`: range min/max in metres, Doppler in m/s, `min`/`max` are `float` with no ordering check (`mmw_cli.c:526-557`); converted to bin indices with `+0.5` rounding, Doppler symmetric (`cfarcaprochwa.c:367-419`) and applied by dropping detections outside the index window after CFAR (`:1060-1072`, DSP `:900-903`). HWA DPC adds `rangeBias` to the range min (`objdethwa/src/objectdetection.c:1775`) | `min >= max` selects nothing; a range window past max range is a no-op | [C] |

### 5. Live re-tune (input to a later item, not this directive)

- 1443 and 3.6: UG says `cfarCfg`, `peakGrouping` (1443) and `cfarFovCfg` (3.6) "can be changed between sensorStop and sensorStart and even when the sensor is running" (SDK 2.1 UG pp. 19-21; SDK 3.6 UG pp. 27, 29-30). 3.6 uses the pending-flag mechanism (`MmwDemo_CfgUpdate`); the 1443 re-reads `cliCfg->cfarCfg` every frame in `MmwDemo_configCFAR_HWA` (`data_path.c:2015-2018`) so live change is plausible [L]. Not bench-verified.
- Cascade: not live. The cascade guide's Known Issues: "Reconfiguration of the chirp design by stopping transmission and then sending another configuration is not supported ... power cycle" (`firmware_dev/projects/awr2243_cascade_ddm/docs/Two_Chip_Cascade_user_guide.html`, Notes); CFAR is in `datapathStaticCfg` (`casc: mss_main.c:1171-1182`), applied only at the first start [C].

### 6. SAR and raw

`iwr1843_sar_lvds` has the CFAR/FOV chain removed (the repo's SAR descriptor forbids `cfarCfg`/`cfarFovCfg`; I did not read the SAR source for this memo) and `dca1000_raw` runs no on-chip detection: `detection: null` plus note [C, from descriptors and `docs/firmware.md`]. IWR6843ODS has no firmware of its own in the repo: `demo.json` maps it to the 6843 template cfg and the 6843 stock SDK 3.6 xwr68xx demo build (`firmware_dev/projects/ti_stock_demos`); the Radar Toolbox "ODS" examples are the unrelated door-obstacle demo [L: the ODS binary identity was inferred from the descriptor, not checked on a board].

### 7. The 1443 SDK version, resolved

`Firmware/IWR_Demos/xwr14xx_mmw_demo.bin` and the SDK 2.1.0.4 `packages/ti/demo/xwr14xx/mmw/xwr14xx_mmw_demo.bin` have the same size (151172 B) and sha256 (`b6b6d8f3f518c1b6f324fed2db1fa8088a43f4b90358a7918d03adace0cdfae9`), `cmp` reports no differences [C]. This agrees with `CPSL_TI_Radar_cpp/Readme.md:197` ("TI mmWave SDK 2.01.00.04"). The binary contains no literal version text (only the format string `mmWave SDK Version : %02d.%02d.%02d.%02d`, `Platform : xWR14xx`, banner `xWR14xx MMW Demo %02d...`), so the gui-33 `version` probe is the on-board confirmation: expect `Platform : xWR14xx` and `mmWave SDK Version : 02.01.00.04`; add that as the 1443 `identify` probe (`level: bench` once recorded).

### 8. Draft `detection` blocks

Variant split recommendation: **four** variants, not three: the 3.6 demo differs between 1843 (HWA DPU) and 6843/ODS (DSP DPU) in the points flagged above (cyclic and Doppler mode ignored on DSP, threshold-0 semantics, `winLen==2`). They can share one field list and differ in `rules`/`board_notes`. Abbreviated JSON (keys as in the directive Design; `cite` strings are the ones above):

```json
{"boards": {"IWR1443": "sdk2_14xx"},
 "variants": {"sdk2_14xx": {
  "level": "source", "source": "SDK 2.1.0.4 xwr14xx mmw_cli.c:162-236; UG 2.1 pp.19-20; shipped bin sha256 = SDK 2.1.0.4",
  "commands": {
   "cfarCfg": {"per_direction": false, "fixed": {"procDir": 0},
     "args": ["procDir", "mode", "noiseWin", "guardLen", "divShift", "cyclic", "thresholdRaw"]},
   "peakGrouping": {"per_direction": false, "fixed": {"scheme": 1},
     "args": ["scheme", "pgRange", "pgDoppler", "pgStartIdx", "pgEndIdx"]}},
  "fields": [
   {"key": "mode", "type": "enum", "options": {"0": "CA", "1": "CAGO", "2": "CASO"}, "default": 2},
   {"key": "noiseWin", "type": "int", "min": 1, "max": 255, "default": 8},
   {"key": "guardLen", "type": "int", "min": 0, "max": 255, "default": 4},
   {"key": "divShift", "type": "int", "min": 0, "max": 255, "default": 3},
   {"key": "cyclic", "type": "bool", "default": 0},
   {"key": "thresholdRaw", "type": "int", "min": 0, "max": 65535, "unit": "log2 Q9", "default": 1280,
     "help": "dB = raw * 6 / 512 * N'/N, N = nRx*nTx, N' = next pow2 (shipped 1280 = 15 dB at N=8)"},
   {"key": "pgRange", "type": "bool", "default": 1}, {"key": "pgDoppler", "type": "bool", "default": 1},
   {"key": "pgStartIdx", "type": "int", "min": 0, "default": 1}, {"key": "pgEndIdx", "type": "int", "min": 0, "default": "numRangeBins-1"}],
  "rules": [{"code": "cfar_args"}, {"code": "cfar_guard_vs_bins_range", "params": {"bins": "numRangeBins"}},
            {"code": "cfar_divshift_formula", "severity": "warning"}]}}}
```

```json
{"boards": {"IWR1843": "sdk3_hwa", "IWR6843": "sdk3_dsp", "IWR6843ODS": "sdk3_dsp"},
 "variants": {"sdk3_hwa": {
  "level": "source", "source": "SDK 3.6 xwr18xx mmw_cli.c:454-557; cfarcaprochwa.c:832-858; UG 3.6 pp.27-29",
  "commands": {
   "cfarCfg": {"per_direction": true, "fixed": {"subframe": -1},
     "args": ["mode", "noiseWin", "guardLen", "divShift", "cyclic", "thresholdDb", "peakGrouping"]},
   "cfarFovCfg": {"per_direction": true, "fixed": {"subframe": -1}, "args": ["fovMin", "fovMax"], "default": "auto"}},
  "fields": [
   {"key": "mode", "type": "enum", "options": {"0": "CA", "1": "CAGO", "2": "CASO"},
     "default": {"range": 2, "doppler": 0}},
   {"key": "noiseWin", "type": "int", "min": 1, "max": 255, "default": {"range": 8, "doppler": 4}},
   {"key": "guardLen", "type": "int", "min": 0, "max": 255, "default": {"range": 4, "doppler": 2}},
   {"key": "divShift", "type": "int", "min": 0, "max": 255, "default": {"range": 3, "doppler": 3}},
   {"key": "cyclic", "type": "bool", "default": {"range": 0, "doppler": 1}},
   {"key": "thresholdDb", "type": "float", "min": 0, "max": 100, "step": 0.01, "unit": "dB", "default": {"range": 15, "doppler": 15}},
   {"key": "peakGrouping", "type": "bool", "default": {"range": 1, "doppler": 1}},
   {"key": "fovMin", "type": "float", "unit": {"range": "m", "doppler": "m/s"}},
   {"key": "fovMax", "type": "float", "unit": {"range": "m", "doppler": "m/s"}}],
  "rules": [{"code": "cfar_args"}, {"code": "cfar_threshold_max", "params": {"max": 100}},
            {"code": "cfar_guard_vs_bins", "params": {"range": "numRangeBins", "doppler": "numDopplerBins"}},
            {"code": "cfar_divshift_formula", "severity": "warning"}, {"code": "cfar_fov_order"},
            {"code": "cfar_fov_noop", "severity": "info"}, {"code": "cfar_missing_direction"},
            {"code": "cfar_win2_invalid", "params": {"engine": "hwa"}}]},
  "sdk3_dsp": {"same_as": "sdk3_hwa", "rules_remove": ["cfar_win2_invalid"],
   "board_notes": ["cyclic and Doppler mode are ignored by the DSP CFAR (source-read, bench check)"]}}}
```

```json
{"boards": {"AWR2243_CASCADE": "ddm"},
 "variants": {"ddm": {
  "level": "source", "source": "casc: mmw_cli.c:643-704, 2255-2262; dopplerprochwaDDMA.c:3993-4003; dopplerprochwaDDMA.h:612-661",
  "commands": {"cfarCfg": {"per_direction": true, "fixed": {"subframe": -1},
     "args": ["mode", "winLen", "guardLen", "divShift", "cyclic", "thresholdDb", "peakGrouping", "osKvalue", "osEdgeKscaleEn", "isEnabled"]}},
  "fields": [
   {"key": "mode", "type": "enum", "options": {"0": "CA", "1": "CAGO", "2": "CASO", "3": "CFAR-OS"}, "default": 3,
     "directions": {"doppler": ["3"]}},
   {"key": "winLen", "type": "int", "min": 1, "max": 255, "default": 16},
   {"key": "guardLen", "type": "int", "min": 0, "max": 255, "default": 0, "directions": {"doppler": [0]}},
   {"key": "divShift", "type": "int", "default": 0, "help": "not applicable in CFAR-OS"},
   {"key": "cyclic", "type": "bool", "default": 1},
   {"key": "thresholdDb", "type": "float", "min": 0, "max": 100, "unit": "dB", "default": {"range": 10, "doppler": 12}},
   {"key": "peakGrouping", "type": "bool", "default": {"range": 0, "doppler": 0}},
   {"key": "osKvalue", "type": "int", "min": 0, "max": 255, "default": 7, "help": "range vs winLen unverified"},
   {"key": "osEdgeKscaleEn", "type": "bool", "default": 0},
   {"key": "isEnabled", "type": "bool", "default": 1, "directions": {"doppler": [1]}}],
  "rules": [{"code": "cfar_args"}, {"code": "cfar_threshold_max", "params": {"max": 100}},
            {"code": "cfar_doppler_enabled"}, {"code": "cfar_doppler_os_guard0"}, {"code": "cfar_missing_direction"}]},
  "notes": ["cfarFovCfg is not registered in the DDM build: never emit it", "once per power-up"]}}
```

SAR / raw: `detection: null`, `detection_note`: "`iwr1843_sar_lvds`: the SAR build removes the on-chip detection chain and the demo CLI refuses cfarCfg/cfarFovCfg" / "`dca1000_raw`: raw ADC capture, no on-chip detection".

## Applicability to CPSL TI Radar

Direct design inputs for gui-35 Steps 2-5:

1. **Do not split directions blindly.** 3.6: send both directions always (sensorStart refuses otherwise), `cfarFovCfg` both directions too; the GUI's "auto FOV" (today's `generate.py` behaviour) stays correct for 3.6. Cascade: never emit `cfarFovCfg`; change `generate.py` accordingly (it does not emit it today, only 3.6 branch at `:477`).
2. **Severities.** Keep errors for: threshold > 100 (3.6, cascade); `2*(win+guard) >= bins` (hard EINVAL at start on both 3.6 engines); HWA `winLen == 2`; cascade Doppler `mode != 3` or `guardLen != 0` or `isEnabled == 0`. The CLI will answer `Done` to the first three, so the gui-34 transcript will not show them at the `cfarCfg` line; they show at `sensorStart`. Keep divShift as a warning (the corpus is clean, so it will only fire on user edits).
3. **Cascade Doppler `isEnabled=0` error** is still the right GUI error, but note the board itself answers `Done` after printing a message (bench item).
4. **Extra 3.6 observations worth a field-level `help`:** DSP DPU ignores `cyclic` (range) and Doppler `mode`; threshold 0 disables a direction (1843: Doppler only). These are source-read hypotheses, so label `help` text "source-derived" and keep the 1843/6843 variants separate.
5. **1443 threshold UI:** store raw, display derived dB next to it (needs $N=n_{rx}\cdot n_{tx}$ from the cfg); the generator's `cfar_*_db` aliases do not apply to the 1443.
6. **Corpus facts for the round-trip test:** 95 cfgs contain these commands; 136 `cfarCfg` 3.6 lines are subframe `-1`, 32 are explicit `0-3` (read-only); the sweep of Step 2 should treat the 4 advanced-subframe cfgs as read-only.

## Recommended Experiment

Bench checks for Step 5 (IWR1843 demo; cascade only on a fresh power-up; each as a small cfg variant, board in a safe state, with a power-cycle available):

1. **Accept test.** GUI-written `cfarCfg`/`cfarFovCfg` lines (new threshold, Doppler mode 1, manual FOV) each answered `Done`; the stream starts [pass criterion in the directive].
2. **Hard-reject presentation (1843).** One seeded-bad cfg with `2*(noiseWin+guardLen) >= numRangeBins`: record what the board prints at `sensorStart` and whether it hangs (needs the user's OK, may need a power-cycle). Decides how the gui-34 transcript should surface rule violations.
3. **Doppler off (1843).** Doppler `thresholdDb 0` accepted and the stream continues with more points (confirms the HWA threshold-0 behaviour, [L] above).
4. **Cascade.** (a) a `cfarFovCfg` line returns the CLI's "not recognized" error; (b) Doppler `isEnabled 0` prints the error and still streams; (c) a changed `osKvalue` (e.g. 5) is accepted. These need a fresh power-up each.
5. **1443 (if a board is free).** `version` reply `02.01.00.04`; one shipped cfg at `1280` vs a cfg with `2304` for point-count direction (observation only).
6. **6843.** Optional: confirm Doppler `mode`/`cyclic` changes have no effect on point count (DSP ignores them).

## Confidence

High: command argument order and count, thresholds units/limits and conversions, the sensorStart mandatory check on 3.6, the 1443 binary being SDK 2.1.0.4 (byte-identical), cascade `cfarFovCfg` not registered, cascade mode 3 = CFAR-OS and its Doppler constraints (`mode == 3`, `guardLen == 0`), cascade Doppler `isEnabled` fall-through, peak grouping layout. Medium (source-read, no bench): HWA vs DSP behaviour differences (cyclic/mode ignored on DSP, threshold-0 direction off), live re-tune on the 1443, failure presentation of the DPU `EINVAL`s.

Not settled: (a) whether `noiseWin` is one-sided or total (HWA programs `winLen>>1` per side while the DPU header and UG say one-sided; shipped CA/CASO `divShift` values follow the UG formula either way); (b) cascade `osKvalue` valid range vs `winLen`, `osEdgeKscaleEn` effect, and the range-direction CFAR constraints (library not in repo; resolving needs the MCU+ SDK sources or HWA TRM); (c) the HWA `winLen` maximum and `cfarThresholdScale` register width; (d) behaviour of an out-of-order or missing `cfarFovCfg` on 6843/ODS beyond the sensorStart check, which was read only for the 1843 source (the 68xx demo is textually the same CLI but its DSS/DPC path was not read to the end); (e) UG pages are the printed page numbers of the PDFs in `docs/references/`.

## Sources

- `ti_mmwave_sdk_ug_3_6` — Texas Instruments (2022), "mmWave SDK User Guide, 03.06.02.00-LTS (mmw demo CLI table, sec. 3.4)," *TI mmWave SDK*. file-only (docs/references/ti_mmwave_sdk_ug_3_6.pdf)
- `ti_mmwave_sdk_ug_2_1` — Texas Instruments (2018), "mmWave SDK User Guide, 02.01.00.04 (mmw demo CLI table, sec. 3.4)," *TI mmWave SDK*. file-only (docs/references/ti_mmwave_sdk_ug_2_1.pdf)
- `ti_mmwave_sdk_3_6` — Texas Instruments (2022), "mmWave SDK 03.06.02.00-LTS (rl_sensor.h, mmwdemo_rfparser.c, demo and platform sources)," *TI mmWave SDK*. url:https://www.ti.com/tool/MMWAVE-SDK
- `ti_mmwave_sdk_2_1` — Texas Instruments (2018), "mmWave SDK 02.01.00.04 (xwr14xx mmw demo sources and prebuilt binary)," *TI mmWave SDK*. url:https://www.ti.com/tool/MMWAVE-SDK
