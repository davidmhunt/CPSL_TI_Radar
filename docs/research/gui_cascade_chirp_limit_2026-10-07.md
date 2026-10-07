# AWR2243 cascade demo: real limit on chirps per frame (gui-09 D11)

**Date:** 2026-10-07
**Memo:** docs/research/gui_cascade_chirp_limit_2026-10-07.md

## Question as asked

What is the real limit on chirps per frame (and related frame-size limits) for the AWR2243 2-chip cascade running the MCU+ SDK cascade DDM demo (AM273x), so the cfg validator can turn "N chirps exceeds tested 256" into an error when the firmware will fail? Bench: `frameCfg 0 7 32 0 128 100 1 0 2` (256 chirps) works; `bench_cascade.cfg` (`frameCfg 0 7 128 ...`, 1024 chirps) gets no Done at `sensorStart`. Scope: source reading only (`firmware_dev/projects/awr2243_cascade_ddm/src/ti`, its build map, the shipped user guide). No hardware.

## TL;DR

The limit is on the **Doppler FFT size** $N$ = `mathUtils_getValidFFTSize(chirps per frame)` (power of 2 or 3x power of 2), not on `numLoops` (255) and not (for 128 samples) on the radar cube. Reason: the DSS core-local L2 heap that holds the Doppler/azimuth scratch buffers is only **82 KiB** (`gDPC_ObjDetL2Heap`) and the scratch needs about $N(2V+16R_x+8)$ bytes ($V$ virtual antennas, $R_x$ RX count). For 6 TX x 8 RX ($V=48$, $R_x=8$): 256 chirps needs about 58 KiB (fits), 384 about 87 KiB (does not), 1024 about 232 KiB (does not). So **chirps per frame <= 256 for the full 6TX/8RX config is a real firmware limit**, and the validator can make it an error. The radar-cube (L3, 2.53 MiB) is a second, independent limit that bites for large range-bin counts.

## Evidence

**1. Chirps feed the Doppler FFT size (all chirps, not loops).** `mmwdemo_rfparserDDMA.c:786-789` (also `:1104`): `numDopplerChirps = numChirpsPerFrame = chirps_per_loop x numLoops`; `numDopplerBins = mathUtils_getValidFFTSize(numDopplerChirps)`. `mss_main.c:2511` sets `staticCfg->numChirps = numDopplerChirps`. `numLoops` itself is only bounded at 255 (`rl_sensor.h`), so 128 loops is legal for the radar front end.

**2. L2 heap size (the binding limit).** `dss_main.c:107-119`: with `MMWDEMO_DDM` (defined in `mmwave2chipCascade_dss.projectspec:62`) and no `LVDS_STREAM`, `MMWDEMO_OBJDET_L2RAM_SIZE = 82 KiB`; `gDPC_ObjDetL2Heap[...]` is handed to the DPC as `CoreLocalRamCfg` (`dss_main.c:838-839`). The build map confirms `.dpc_l2Heap` = 0x14800 = 83,968 B (`build/ccs_workspace/am273x_mmw_cascade_demo_dss/Release/*.Release.map:42`; the map filename carries a stale project name, content is this build's DSS image).

**3. What is allocated from it, in terms of $N$** (`objdethwaDDMA/src/objectdetection.c`, `numBandsTotal` = 8 for 6 TX, `mss_main.c:2534`):
- `dopFFTSubMat` = $(N/8)\,V\cdot 8\cdot 2 = 2NV$ B (`:2442-2446`), retained through the Doppler stage.
- Doppler FFT scratch, ping and pong: $2\times N R_x\cdot 8$ B (`:2485`, allocated `/2` twice at `:2530`, `:2586`); DDMA metric $2\times 4N$ B (`:2486`). Azimuth/CFAR/local-max scratch overlaps these (`:2511-2526`, max of the two end addresses), and for $V=48$ is smaller.
- Plus the range window buffer (`:2157`) and the 4 KiB alignment of the pool.

$$L2(N) \approx N\,(2V + 16R_x + 8)\ \text{B} \;\le\; 83{,}968\ \text{B}$$

For $V=48,\ R_x=8$ (`channelCfg 15 7 ...`: 4 RX x 2 chips, 3 TX x 2 chips; `MMWAVE_RADAR_DEVICES=2`, `mmwave.h:334`; rx count loop `rfparserDDMA.c:611-638`): $232N$ B.

| chirps/frame | $N$ | L2 estimate | vs 82 KiB |
|---|---|---|---|
| 128 | 128 | 29 KiB | fits |
| 192 | 192 | 43.5 KiB | fits |
| 256 | 256 | 58 KiB | fits (bench-confirmed) |
| 257..384 | 384 | 87 KiB | **over** |
| 512 | 512 | 116 KiB | **over** |
| 1024 | 1024 | 232 KiB | **over** (bench-failed) |

This reproduces both bench outcomes and matches TI's statement "Chirp design is limited to 192 adc samples, 256 chirps, and 8 channels" (`docs/Two_Chip_Cascade_user_guide.html`). The overhead beyond the model (window, alignment, pointers) is not computed, so the exact threshold lies between 256 and 384 chirps; it cannot be lower than 256 because 256 works on the bench.

**4. L3 radar cube (second limit).** `dss_main.c:99`: `gMmwL3` has size `CSL_DSS_L3_U_SIZE - SYS_COMMON_HSRAM_SIZE - 0x100000`; the map gives `.l3ram` = 0x288000 = 2,654,208 B (`...Release.map:51`, `:1100`). Radar cube (`objectdetection.c:3261-3264`) is
$$B_{cube} = R\cdot C\cdot R_x\cdot 4\cdot \rho,$$
$R$ = `numRangeBins` (valid FFT of samples, `rfparserDDMA.c:780-783`), $C$ = chirps, $\rho$ = achieved compression ratio (0.5 for the shipped `compressionCfg -1 1 0 0.5 8`; formula `:3230-3250`). Also in L3: decompression scratch $C\cdot R_x\cdot 4\cdot 8$ (`:2434`, 8 = `rangeBinsPerBlock`), detection matrix $R\,(N/8)\,2$ (`:3281`), plus object lists (800 objects, `objectdetection.h:116`). Exceeding it returns `DPC_OBJECTDETECTION_ENOMEM__L3_RAM_RADAR_CUBE` (-11 in the -40100 block; documented `mss_main.c:615`). For the failed bench cfg ($R=128$, $C=1024$, $R_x=8$, $\rho=0.5$): cube 2.10 MB + scratch 0.26 MB + det matrix 0.03 MB + lists ~= 2.4-2.45 MB < 2.65 MB, so **L3 alone would probably not have failed the bench cfg; L2 does**. L3 binds for e.g. $R\ge 1024$ at 256 chirps, or no compression with $R=512$.

**5. Failure symptom.** DPC configuration happens at `sensorStart`; a memory error there is consistent with "no Done for sensorStart" and the board needing a power cycle. The exact failure path (assert vs. error print on the DSS UART) was not traced; treat as consistent, not proven.

## Applicability to CPSL TI Radar

Current rule: `config/firmware/cascade_ddm.json` `max_chirps` = 256 at level `warning` (source "cfggen.py: TI only tested"); `radar_gui/cfg/validate.py:387-388` emits the warning; `metrics.py` already computes `n_chirps` (chirps per loop x loops). Prior memo `gui_board_limits_cascade_multiprofile.md` said "not firmware-enforced"; that holds for an explicit check, but the memory sizing enforces it implicitly, so that row should be upgraded.

Recommended validator rule (cascade_ddm, DDMA):
1. **Error** if $N=\text{validFFT}(n_{chirps}) > N_{max}$ where $N_{max}$ solves $N(2V+16R_x+8)+4096 \le 83{,}968$ with $V=$ azim virtual antennas (TX count x RX count), $R_x$ = total RX. For the standard 6TX/8RX config this is **$n_{chirps} \le 256$** (hard error); for 384 chirps it is also an error. Simplest safe implementation: error at `n_chirps > 256` when $V\ge 48$; allow the formula (with warning "untested by TI") for smaller $V$.
2. **Error** if $B_{cube} + C R_x 32 + R(N/8)2 + 64\,\text{KiB} > 2{,}654{,}208$ ($\rho$ from `compressionCfg`).
3. Keep 192 samples as a warning ("tested only"); samples are limited by item 2, not by an explicit check.
4. Generator: cap loops so that $n_{cpl}\times L \le 256$ for the cascade (D11 Targets generator chose 128 loops x 8 = 1024).

HYPOTHESIS (not bench-confirmed): a smaller-TX cfg (e.g. 2 TX, $V=16$) allows $N=512$ ($512\cdot(32+128+8)=84{,}000$ B, borderline) or only $N=384$; do not rely on it without the bench check.

## Recommended Experiment

One power cycle per cfg (the cascade accepts a cfg once per boot). From `bench_cascade_revA.cfg` (6TX/8RX, 128 samples) change only `frameCfg`:
1. `frameCfg 0 7 48 ...` (384 chirps, $N=384$, predicted L2 87 KiB): predict **fail** at `sensorStart`. If it passes, the 82 KiB model overstates usage and the limit lies at $N=384$; update $N_{max}$.
2. Optional: a 2-TX variant at 512 chirps to test the smaller-$V$ hypothesis.
Also capture the DSS/MSS UART (if reachable) during the 1024-chirp failure; the DPC error code (-40111 would mean L3 radar cube, a `CORE_LOCAL_RAM` code would confirm L2) settles which memory failed.

## Confidence

High (source + build map) that chirps feed $N$ and that the L2 and L3 pools are 82 KiB and 2.54 MiB; high that 1024 chirps exceeds the L2 model by about 3x; medium on the exact threshold between 257 and 384 chirps (fixed overheads and the exact azimuth-bin constant `OBJECTDETECTION_NUM_AZIM_FFT_BINS`, 32 or 48 at `objectdetection.c:228-230`, were not resolved; neither changes the conclusion because Doppler scratch dominates); low-medium on the failure path for the symptom (not traced). Does not settle: 192-sample cfgs at 256 chirps in your build (should fit), configs with fewer TX, and whether `LVDS_STREAM` builds (smaller L2: 60-80 KiB) are in use (the shipped project does not define it).

## Sources

- `ti_cascade_ddm_src` — Texas Instruments (2026), "Radar Toolbox 4.00.00.05 mmwave_2_chip_cascade source as tracked in firmware_dev/projects/awr2243_cascade_ddm (dss_main.c, objdethwaDDMA/objectdetection.c, mmwdemo_rfparserDDMA.c, mss_main.c)," *TI Radar Toolbox*. url:https://dev.ti.com/tirex/explore/node?node=A__AGNPb0uiuxHxMUl5gDbVZw__RADAR-ACADEMY__GwxShWe__LATEST
- `ti_cascade_user_guide` — Texas Instruments (2026), "Two Chip Cascade user guide (Two_Chip_Cascade_user_guide.html), tested-design statement," *TI Radar Toolbox docs*. url:https://dev.ti.com/tirex/explore/node?node=A__AGNPb0uiuxHxMUl5gDbVZw__RADAR-ACADEMY__GwxShWe__LATEST

Note: descriptive keys as in `gui_board_limits_cascade_multiprofile.md`; no PDFs archived (installer-derived sources); `references.bib` not edited.
