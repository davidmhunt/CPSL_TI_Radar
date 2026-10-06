# gui-20: multiple chirpCfg entries on one profile (TX patterns) per firmware

**Date:** 2026-10-06
**Memo:** docs/research/gui_multichirp_tdm.md

Working note (exempt from rule 16). Paths: `SDK36/` = `packages/ti/` of mmWave SDK 3.6.02.00-LTS (installer in `firmware_dev/downloads/`, unpacked in scratch); `RP` = `SDK36/demo/utils/mmwdemo_rfparser.c`; `CAS/` = `firmware_dev/projects/awr2243_cascade_ddm/src/ti/`. Builds the stock 1843/6843 demos and the SAR firmware use this parser (gui-13 memo). The 1443 (SDK 2.x) and the `dca1000_raw` binaries have no source in the tree.

## Question as asked

gui-20: the user's need is several `chirpCfg` entries on ONE profile, each with its own TX mask (TDM-MIMO patterns), looped `numLoops` times, not multi-profile. Per firmware: what chirp patterns are accepted, how the demo derives virtual antennas and Doppler from them, what `radar_gui/cfg/metrics.py` and `params.py` already handle or miss, and whether the cascade firmware can do one-TX-per-chirp TDM. User expectation: "other configurations use 1 TX at a time."

## TL;DR

- **Stock 1843/6843 demo (SDK 3.6): the pattern must be a cyclic one-TX-per-chirp sequence, each TX once per loop, at most 32 chirps.** Virtual antennas $=n_{TX}\,n_{RX}$ with $n_{TX}$ = distinct TX in the pattern (azimuth TX1/TX3, elevation TX2). Doppler uses $n_{TX}T_c$ as the per-TX interval (`RP:902-904`), so `metrics.py`'s `chirps_per_loop*Tc` is right only when `chirps_per_loop == n_TX`.
- **Multi-TX masks on one chirp** are accepted only as BPM (`bpmCfg`, both azimuth TX) or as "SIMO" (non-power-of-2 mask counted as one azimuth TX, 4 virtual antennas); `metrics.py` counts $\text{popcount}$ TX and gets SIMO wrong (8 virtual, firmware 4).
- **Cascade: confirmed, all 6 TX fire on every chirp (DDMA).** One-TX-per-chirp cannot be selected by cfg in the shipped build: TI's source has a compile-time TDM variant (`-DMMWDEMO_TDM`, `objdethwa/`, `mmw_resTDM.h`), but the repo build defines only `MMWDEMO_DDM`; a TDM build is untested here (HYPOTHESIS: it would also need another rebuild and a bench check).
- **Re-scope gui-14..16 around chirp patterns, not profiles** (section 4).

## Evidence

### 1. Stock 1843/6843 demo rules (standard parser, `USE_2D_AOA_DPU` off)

`USE_2D_AOA_DPU` is defined only for the AOP build target (`SDK36/demo/xwr18xx/mmw/mss/mmw_mss.mak:115`); the standard build uses the parser branch `RP:467-624`. Both 18xx and 68xx set `azimTxAntMask=0x5`, `elevTxAntMask=0x2` (`RP:160-200`; 14xx same, `RP:131-136`, demo not in tree).

| Topic | Rule | Source | Conf. |
|---|---|---|---|
| Chirps per frame loop | `frameTotalChirps = chirpEnd-chirpStart+1`; `>32` sets an error that is then overwritten, but `validChirpTxEnBits[32]` would overflow: 32 is the real limit | `RP:769,782-784,794` | H |
| chirpCfg entries | Any number of `chirpCfg` lines, ranges allowed (one line may cover several indices); only chirps in `chirpStart..chirpEnd` with `(txEnable & channelCfg.tx) > 0` count; every index of the loop must be covered, else the profile is invalid | `RP:826-845`, `RP:515-519` | H |
| Per-chirp TX mask | Elevation chirp iff mask `== 0x2` (3-TX chips). Otherwise either (a) BPM: `bpmCfg` on and mask `== 0x5` on every chirp, or (b) one-TX-per-chirp (power of 2). Mixing one-TX and multi-TX chirps is rejected | `RP:522-560` | H |
| TX per chirp, several TX | Non-BPM multi-TX mask on all chirps: accepted, $n_{TX,az}=1$ ("SIMO"), both TX transmit simultaneously | `RP:608-616` | H |
| $n_{TX}$ | TDM: number of distinct azimuth TX in the OR of chirp masks, +1 if any elevation chirp; BPM: 2; max 3 | `RP:586-605`, `:628-632` | H |
| TX order / virtual array | `txAntOrder[i] = log2(mask of chirp i)` for the first $n_{TX}$ chirps; the range DPU de-interleaves chirp $k$ to TX $k \bmod n_{TX}$ (3 TX: stride 6 chirps, so `numLoops` should be even; 2 TX: stride 2) | `RP:644-660`; `SDK36/datapath/dpu/rangeproc/src/rangeprochwa.c:966-1140` (`/6U` at 1027) | H (order), M (parity, inferred) |
| Pattern shape | The parser never checks that the sequence repeats with period $n_{TX}$ or that each TX appears once per loop; patterns like `[1,4,1,4]` happen to work (period 2), `[1,4,1,2]` would be misdecoded | derived from the two rows above; HYPOTHESIS, test in section 5 | M |
| Order convention | TI cfgs list azimuth first, elevation last: `profile_3d.cfg` TX 1,4,2; `profile_2d.cfg` 1,4; calibration 1,4,2 | `SDK36/demo/xwr18xx/mmw/profiles/profile_{2d,3d,calibration}.cfg` | H (convention), L (that firmware needs it) |
| Doppler | $N_{chirps}=n_{cpl}L$; `numDopplerChirps = N/n_TX`; bins = next pow2; step $=c/(2\,N_{bins}\,n_{TX}\,f_c T_c)$; resolution $=c/(2\,N\,f_c T_c)$; reported span $\pm\lambda/(4 n_{TX} T_c)$ | `RP:885-906` | H |
| Subframes | `advFrameCfg` up to 4 subframes, each its own chirp range/loops, `numOfBurst==1`; each subframe parsed separately (so a different TX pattern per subframe is possible, stock and not SAR) | `RP:774-778`; gui-13 memo | H |
| AOP variant (`USE_2D_AOA_DPU`) | All 4 RX required; every chirp must be one-TX; $n_{TX}$ = popcount of the union | `RP:370-440` | M (line ranges approximate) |

So the Doppler model in firmware terms is the user's: slow-time per virtual antenna is sampled every $n_{TX}T_c$, $v_{max}=\lambda/(4 n_{TX}T_c)$, $T_{loop}=n_{TX}T_c$ for a conforming loop. For the typical user case "one TX at a time" (cpl $=n_{TX}$: SIMO 1 chirp, 2 TX 2 chirps, 3 TX 3 chirps) this equals `metrics.py`.

### 2. Per firmware

| Firmware | Chirp pattern rules | Conf. |
|---|---|---|
| `demo_stock` / `demo_lvds` 1843, 6843 | Section 1 table; one binary, LVDS via cfg | H |
| `iwr1843_sar_lvds` | Same parser (SDK 3.6, gui-13 memo); frame mode only, no subframes. No pattern difference found | M |
| `dca1000_raw` (Studio-CLI / lvds_stream) | Binaries, no source. Raw ADC out, so no parser restricts the pattern; the radar subsystem takes any `chirpCfg` entries (indices 0-511, `rl_sensor.h` rlFrameCfg per gui-13 memo). Shipped example: 2 chirps TX1/TX4, `profile_monitor_xwr18xx.cfg` | L, U for rules |
| IWR1443 demo | Not in tree. SDK 3.6 parser carries 14xx masks (0x5/0x2) but the shipped `xwr14xx_mmw_demo.bin` is SDK 2.x | U |
| Cascade DDM | Section 3 | H |

### 3. Cascade: DDMA, and no cfg-selectable TDM

Verified the Controller's reading:
- Shipped cfg: `channelCfg 15 7 1 15 7`, `chirpCfg 0 7 0 0 0 0 0 7`, `frameCfg 0 7 32 0 192 50 1 0 2` (`firmware_dev/projects/awr2243_cascade_ddm/configs/cascade_shortrange.cfg:8,18,19`): 8 identical chirps, mask 7 on each chip.
- The DDMA parser does not use the chirp mask: it writes the merged `channelCfg` TX mask into every chirp (`CAS/demo/utils/mmwdemo_rfparserDDMA.c:717-733`) and sets $n_{TX}$ from it (`:463-473`). The demo then hard-codes `txAntMaskEnable = 63` for the phase shifter (`CAS/demo/am273x/mmw/mss/mss_main.c:3825`) and programs per-chirp phase shifts through `rlRfSetPhaseShiftConfig` (`CAS/control/mmwave/src/mmwave_link_common.c:919,952,986`). TX separation is in the Doppler domain (8 bands: 6 TX + 2 empty); gui-13 memo section 4.
- A `chirpCfg` with one TX per chirp would still be sent to the radar front end (`rlSetChirpConfig`, `mmwave_link_common.c:1116`), but the DDMA range/Doppler chain assumes all-TX DDMA with phase codes, so the output would not decode as TDM (HYPOTHESIS; see experiment 3).
- TDM exists only in source: `#ifdef MMWDEMO_TDM` selects `objdethwa/` and `mmw_resTDM.h` (`CAS/demo/am273x/mmw/mss/mmw_mss.h:51-55`, `mss_main.c:1140`, `dss_main.c:70`), both of which are in the tree; the `.projectspec` files define only `MMWDEMO_DDM` and `mmw_resDDM.h` (`src/mmwave2chipCascade_mss.projectspec:54,57`). So TDM is a different firmware build, not a cfg. Whether it builds and runs on the cascade EVM is unverified (not built or tested here).

## Applicability to CPSL TI Radar

### 4. Gaps in `radar_gui/cfg/` and re-scope

`metrics.py`:
1. **No pattern validation.** `chirp_tx_masks` (`:117-127`) only collects masks. Not checked: one TX per chirp, each TX once per loop, loop period equals $n_{TX}$, $\le 32$ chirps, no mixing of one-TX and multi-TX chirps, `bpmCfg` consistency.
2. **$n_{TX}$ wrong for non-BPM multi-TX masks:** `popcount(used)` (`:184`) gives 2 for mask 5 on every chirp, firmware gives 1 (`RP:608-616`); `n_az`/`n_virtual` (`:185,188`) inherit it. `bpmCfg` is not parsed at all (BPM happens to match, 2 TX).
3. **TDM `max_velocity` uses `chirps_per_loop*Tc`** (`:191-193`); firmware uses $n_{TX}T_c$. Differs for repeated patterns (`[1,4,1,4]`: 4Tc vs firmware 2Tc) and for SIMO with several chirps per loop. Resolution `:194` already matches. Doppler bin count ($\mathrm{pow2}(N/n_{TX})$) is not reported.
4. **`advFrameCfg`/`subFrameCfg` ignored:** `frame_layout` needs `frameCfg` (`:104-114`), so `profile_advanced_subframe.cfg`-style cfgs raise "missing frameCfg". Per-subframe chirp patterns are the stock-firmware way to alternate patterns.
5. Per-chirp `chirpCfg` variation fields (startFreqVar, freqSlopeVar, idleVar, adcStartVar) are ignored; the demo parser also reads RF values from the profile only, so this matches the demo (but not the raw radar).
6. Cascade: chirp masks are irrelevant to the DDMA decode, but `chirp_tx_masks` is still merged and shown; the DDMA bands rule (cpl multiple of 8, gui-13) is not modelled.

`params.py`:
1. Good base: `chirp_tx_masks` is already a per-chirp list in `frameCfg` order (`:91`), regenerated into `chirpCfg 0..n-1` lines (`:165-174`).
2. **`channelCfg.tx_mask` is not tied to the chirp masks.** The parser requires `(chirpTxEn & channelCfg.tx) > 0` per chirp (`RP:836`); editing `chirp_tx_masks` to a TX outside `channelCfg` leaves a chirp uncovered, so the firmware finds no valid profile. Needs `tx_mask = OR(chirp_tx_masks)` coupling.
3. **Single-chip `tx_mask`-only edit emits chirps in bit order (TX1, TX2, TX3)** (`:159-163`); TI's order is azimuth first, elevation last (1,4,2). HYPOTHESIS that this mislabels azimuth/elevation virtual antennas; experiment 2.
4. Regeneration clones the first chirpCfg line for every chirp (`:166-172`): per-chirp variation fields and profile ids are flattened, chirp indices renumbered from 0, `chirpStart` forced to 0 (`:180`).
5. No `bpmCfg`, no subframes, no pattern limit (32); cascade accepts mask edits that the firmware ignores.
6. `validate.py` has `n_tx > limit` and loop/chirp counts only (`:100-146`); no pattern rule (`tx_pattern_invalid` is planned in gui-15 but its content is now known).

**Recommended re-scope (user's expectation: 1 TX per chirp):**
- **gui-14** (parse + metrics): drop the multi-profile oracle (the demo uses one profile, gui-13). New content: chirp sequence model (`chirp_sequence`: index, TX mask), `n_TX` per firmware rules above, $T_{loop}=n_{TX}T_c$ vs repeat period, Doppler bins/step, `bpmCfg`, subframes as separate patterns. Oracle cases: SIMO (1 chirp), 2-TX azimuth TDM (mask 1,4), 3-TX with elevation (1,4,2), BPM (mask 5, 2 chirps), repeated pattern `[1,4,1,4]`, cascade DDMA 8-chirp (unchanged).
- **gui-15** (validation/generation): rules `tx_pattern_invalid` (mix, repeat/period, `>32`, non-power-of-2 without `bpmCfg` as an info/warning), `tx_not_in_channelcfg`, order convention (warning), `cascade_chirp_mask_ignored`; descriptor field `chirp_pattern` per firmware (TDM/BPM, max 32, subframes yes/no); `apply_params` ties `channelCfg` TX to the chirp masks and fixes (1,4,2) ordering. Multi-profile reduced to a "profiles beyond the first are ignored" warning.
- **gui-16** (UI): the editor is a chirp table (one row per chirp, TX checkboxes, preset buttons "SIMO / 2-TX TDM / 3-TX with elevation / BPM"), not profile cards; profile card only for the single profile; subframes deferred as in the directive; cascade: table read-only (DDMA), with the 6-TX phase-coded description.

## Recommended Experiment

1. **Pattern repeat rule (1843, bench, one board):** run `[1,4,1,4]` (4 chirps, loops 32) versus `[1,4]` loops 64 with the same profile; expect equal `dopplerStep` and range-azimuth outputs. Then `[1,4,1,2]` to see the misdecode (HYPOTHESIS: azimuth corrupted).
2. **Order (1843 or 6843):** 3-TX with order 1,4,2 versus 1,2,4 on a corner reflector at known elevation/azimuth; compare heat-map and elevation angle (discriminates params.py gap 3).
3. **Cascade TDM (Firmware role, not Coder):** build with `-DMMWDEMO_TDM`/`mmw_resTDM.h` in a scratch copy, check it compiles; flashing is a separate bench decision (cfg once per power-up). Cheaper first step: send a one-TX-per-chirp cfg to the DDM build and record the demo's error or output.
4. Offline: none needed; the formulas are source-derived, and the Coder can unit-test them against the oracle cases in the re-scope.

## Confidence

High on the SDK 3.6 parser, the Doppler formulas and the cascade DDMA facts (read from source, cross-checked against the shipped cfgs). Medium on the range-DPU de-interleave details (`numLoops` parity, stride) and on AOP line ranges. **Not settled:** whether the firmware tolerates a pattern that is not a $n_{TX}$-periodic cyclic sequence (inferred, not tested); whether TX order matters beyond labelling; 1443 SDK 2.x and `dca1000_raw` binary rules; whether a cascade TDM build is functional; SAR firmware pattern rules beyond "same parser".

## Sources

- `ti_mmwsdk36_rfparser` — Texas Instruments (2021), "mmWave SDK 3.6.02.00-LTS packages/ti/demo/utils/mmwdemo_rfparser.c, datapath/dpu/rangeproc, demo/xwr18xx/mmw profiles," *TI MMWAVE-SDK installer (firmware_dev/downloads)*. url:https://www.ti.com/tool/MMWAVE-SDK
- `ti_cascade_ddm_src` — Texas Instruments (2026), "Radar Toolbox 4.00.00.05 mmwave_2_chip_cascade source as tracked in firmware_dev/projects/awr2243_cascade_ddm (mmwdemo_rfparserDDMA.c, mss_main.c, mmwave_link_common.c, projectspec)," *TI Radar Toolbox*. url:https://dev.ti.com/tirex/explore/node?node=A__AGNPb0uiuxHxMUl5gDbVZw__RADAR-ACADEMY__GwxShWe__LATEST

Note: descriptive keys as in the gui-13 memos; no PDFs archived (installer sources); `references.bib` not edited.
