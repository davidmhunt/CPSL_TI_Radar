# MIMO modes: TDM vs DDMA

Reference the GUI/cfg code follows (gui-21, #59); each firmware descriptor names its scheme in a `mimo` block. Restates `docs/research/gui_multichirp_tdm.md` (**M1**, sections cited as M1 s1..s4) and `docs/research/gui_board_limits_cascade_multiprofile.md` (**M2**, s3/s4); no new research. Source refs: `RP` = SDK 3.6 `demo/utils/mmwdemo_rfparser.c`; `CAS` = `firmware_dev/projects/awr2243_cascade_ddm/src/ti/`. Cfg formulas (`Tc`, `lambda`, `dv`, ...) are in [`cfg_formulas.md`](cfg_formulas.md); that doc links here for `n_TX`/`vmax`.

Symbols: `Tc` chirp time (us); `cpl` chirps per loop (frameCfg `end-start+1`); `L` loops; `N = cpl*L` chirps per frame; `n_TX` distinct azimuth TX in the loop (+1 if an elevation chirp exists; TX1/TX3 azimuth, TX2 elevation), **not** `cpl`; `n_RX` enabled RX; `lambda = c/fc`. Masks: bit0 = TX1, bit1 = TX2, bit2 = TX3 (so mask 1 = TX1, 2 = TX2, 4 = TX3, 5 = TX1+TX3).

## 1. Side by side

| | **TDM** (1443/1843/6843 demos, SAR) | **DDMA** (AWR2243 cascade demo) |
|---|---|---|
| TX per chirp | one (power-of-2 mask); elevation chirp iff mask 2 (M1 s1, `RP:522-560`) | all enabled TX every chirp (M1 s3) |
| Loop structure | `cpl` chirps, any count of `chirpCfg` lines covering `chirpStart..chirpEnd`, `cpl <= 32`; pattern should repeat with period `n_TX` (M1 s1) | `cpl` identical chirps (TI: 8); TX separation is by Doppler band, not by chirp (M2 s3) |
| Doppler FFT | over `N/n_TX` chirps per virtual antenna, bins = next pow2 (`RP:885-906`) | over all `N = cpl*L` chirps, bins = valid FFT size (M2 s4); per-TX sub-band = bins/8 |
| Doppler step / resolution | step `= lambda/(2*bins*n_TX*Tc)`; `dv = lambda/(2*N*Tc)` | step `= lambda/(2*bins*Tc)`; `dv = lambda/(2*N*Tc)` |
| `vmax` | `lambda/(4*n_TX*Tc)` (user ruling; = `RP:902-904`) | `lambda/(4*Tc)` (firmware span; user-accepted because all TX fire every chirp). Per-TX band: `lambda/(4*8*Tc)` |
| Virtual array | `n_TX*n_RX` (3 TX: 8 azimuth + 4 elevation = 12 with 4 RX) | `n_TX*n_RX` = 6 x 8 = 48 |
| Cfg that sets it | `channelCfg` (RX/TX masks), `chirpCfg` (per-chirp TX mask), `frameCfg` (cpl, `L`, period), `bpmCfg` (opt-in), `advFrameCfg` (stock only: up to 4 subframes, each its own pattern; not SAR) | `channelCfg` (TX count: 2,3,4 or 6), `frameCfg`; `chirpCfg txEnable` only has to overlap `channelCfg` (parser overwrites it with the merged mask, `CAS/.../mmwdemo_rfparserDDMA.c:717-733`); no `advFrameCfg` (`mss_main.c:3888-3891`) |
| Phase codes | none (BPM sign is switched by the demo when `bpmCfg` is on) | firmware only: `rlRfSetPhaseShiftConfig` per chirp, `txAntMaskEnable=63` hard-coded (`mss_main.c:3796-3850`); not a cfg command |

## 2. Timing diagrams (one column per chirp, `#` = TX on)

**TDM, 3 TX, pattern 1,4,2 (masks 1,4,2 = TX1, TX3, TX2), `cpl = 3`, `L = 2`.**
```
chirp  : 0  1  2 | 3  4  5          n_TX = 3  (TX1, TX3 azimuth; TX2 elevation)
TX1    : #  .  . | #  .  .          interval per TX = 3*Tc
TX2    : .  .  # | .  .  #
TX3    : .  #  . | .  #  .
```

**TDM, 2 TX BPM (opt-in), mask 5 on both chirps, `cpl = 2`.** `bpmCfg` flips the sign of one TX on alternate chirps (sign pattern is the BPM concept, not read from source here). `n_TX = 2`, interval `2*Tc`.
```
chirp  : 0  1 | 2  3
TX1    : #  # | #  #
TX3    : #  # | #  #     (relative sign +,+ / +,- per chirp pair; unverified)
```

**DDMA, 6 TX, `cpl = 8`, one loop shown.** All TX lit every chirp; TX rank `r` gets a firmware phase step of `r * 360/8 = 45*r` degrees per chirp (M2 s3 form `chirp k * rank / n_bands`; `n_bands = 6 + 2` empty).
```
chirp  : 0  1  2  3  4  5  6  7 |
TX1..6 : #  #  #  #  #  #  #  #      (all six every chirp; no per-TX slot in time)
```

## 3. Worked numbers (`fc` = 77 GHz, `lambda = 3.9 mm`, `Tc = 50 us`)

**TDM 3 TX (1,4,2), `cpl = 3`, `L = 64`:** `N = 192`; Doppler chirps per antenna `= 192/3 = 64`, bins 64; `vmax = 3.9e-3/(4*3*50e-6) = 6.5 m/s`; `dv = 3.9e-3/(2*192*50e-6) = 0.203 m/s`; step `= 3.9e-3/(2*64*3*50e-6) = 0.203 m/s`; check `64*0.203/2 = 6.5`. Virtual 12 (n_RX = 4).

**TDM `[1,4,1,4]` repeat, `cpl = 4`, `L = 32`:** `n_TX = 2` (distinct azimuth TX), not 4. `vmax = 3.9e-3/(4*2*50e-6) = 9.75 m/s`. Code using `cpl*Tc` would give 4.875 m/s (M1 s4 item 3). Same output as `[1,4]`, `L = 64` (`N = 128`, 64 Doppler bins).

**SIMO (non-BPM multi-TX mask, e.g. mask 5 on every chirp, no `bpmCfg`):** accepted, `n_TX = 1`, both TX transmit together, virtual `= n_RX` (4), not 8 (`RP:608-616`). `cpl = 1`: `vmax = 3.9e-3/(4*1*50e-6) = 19.5 m/s`. Popcount of the mask (2) is wrong.

**DDMA 6 TX, `cpl = 8`, `L = 32` (TI `cascade_shortrange`):** `N = 256`; `vmax = 3.9e-3/(4*50e-6) = 19.5 m/s`; `dv = 3.9e-3/(2*256*50e-6) = 0.152 m/s`; per-TX band `3.9e-3/(4*8*50e-6) = 2.44 m/s`; sub-band bins `256/8 = 32`; virtual 48.

## 4. What you can edit

**TDM:** the chirp table (TX mask per chirp; presets SIMO / 2-TX / 3-TX with elevation / BPM), `cpl <= 32`, `L`, period, profile. `channelCfg` TX = OR of the chirp masks (parser requires `(chirp mask & channelCfg tx) > 0` per chirp; `RP:836`). Rules: no mixing one-TX and multi-TX chirps; multi-TX masks only as BPM or SIMO; keep the pattern `n_TX`-periodic; TI order is azimuth first, elevation last (1,4,2). **GUI default = plain TDM, `bpmCfg` disabled; BPM is an opt-in preset** available only where the stock demo supports it: 1843/6843 yes, 1443 no, SAR not confirmed (descriptor `bpm` false). `advFrameCfg` subframes (stock only) may each use a different pattern.

**DDMA:** profile, `L`, period, `channelCfg` TX count (2, 3, 4 or 6). `cpl` should be a multiple of `n_bands` (8; shipped cfgs all use 8; inferred, HYPOTHESIS, M2 experiment 1). The chirp table and phase codes are **view-only**: shown, not editable, since the firmware sets them. One cfg per power-up; one profile used.

## 5. Unverified (carried from M1/M2)

- HYPOTHESIS: TX order 1,4,2 vs 1,2,4 may mislabel azimuth/elevation virtual antennas (TI cfgs use 1,4,2; no bench test). M1 experiment 2.
- HYPOTHESIS: non-cyclic patterns (`[1,4,1,2]`) misdecode; `[1,4,1,4]` working is inferred from the parser, not run. 3-TX `L` should be even (stride 6, medium). M1 experiment 1.
- Cascade TDM exists only as the compile-time `MMWDEMO_TDM` build (untested here); the shipped build is DDMA, and a one-TX-per-chirp cfg will not decode as TDM (HYPOTHESIS, M1 s3).
- 1443 BPM and all 1443 rules (shipped demo is SDK 2.x, no source); `dca1000_raw` TDM/BPM rules (binaries, `tdm` true, `bpm` false, limits unverified); SAR BPM (same parser, not confirmed).
