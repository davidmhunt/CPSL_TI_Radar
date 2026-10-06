# MIMO modes: TDM vs DDMA

Reference the GUI/cfg code follows (gui-21, #59); each firmware descriptor names its scheme in a `mimo` block. Restates `docs/research/gui_multichirp_tdm.md` (**M1**) and `docs/research/gui_board_limits_cascade_multiprofile.md` (**M2**); no new research. Source refs: `RP` = SDK 3.6 `demo/utils/mmwdemo_rfparser.c`; `CAS` = `firmware_dev/projects/awr2243_cascade_ddm/src/ti/`. Other cfg formulas: [`cfg_formulas.md`](cfg_formulas.md), which links here for `n_TX`/`vmax`.

Symbols: `Tc` full chirp period = idle + ramp (us); `cpl` chirps per loop (frameCfg `end-start+1`); `L` loops; `N = cpl*L` chirps per frame; `n_RX` enabled RX (cascade: 8 = 2 chips x 4); `lambda = c/fc = 3.893 mm` at 77 GHz, rounded to 3.9 mm below. **`n_TX` = number of TX time slots per loop**, i.e. the interval at which one TX is sampled is `n_TX*Tc`; it is **not** `cpl` and not the popcount of a mask. Rule: one TX per chirp -> distinct azimuth TX (TX1/TX3), +1 if a TX2 (elevation) chirp exists; BPM (mask 5 + `bpmCfg` on) -> 2; SIMO (multi-TX mask, no `bpmCfg`) -> 1. Masks: bit0 = TX1, bit1 = TX2, bit2 = TX3 (5 = TX1+TX3).

## 1. Side by side

| | **TDM** (1443/1843/6843 demos, SAR) | **DDMA** (AWR2243 cascade demo) |
|---|---|---|
| TX per chirp | one TX per chirp (plain TDM), or a multi-TX mask as BPM / SIMO only (M1 s1, `RP:522-560`) | all enabled TX every chirp (M1 s3) |
| Loop structure | `cpl <= 32` chirps; pattern repeats with period `n_TX` (M1 s1) | `cpl` identical chirps (TI: 8); TX separation is by Doppler band (M2 s3) |
| Doppler FFT | over `N/n_TX` chirps per virtual antenna, bins = next pow2 (`RP:885-906`) | over all `N` chirps, bins = valid FFT size (M2 s4); per-TX sub-band = bins/8 |
| Doppler step / resolution | step `= lambda/(2*bins*n_TX*Tc)`; `dv = lambda/(2*N*Tc)` | step `= lambda/(2*bins*Tc)`; `dv = lambda/(2*N*Tc)` |
| `vmax` | `lambda/(4*n_TX*Tc)` (user ruling; = `RP:902-904`) | Two numbers: full Doppler span `+-lambda/(4*Tc)` (what the firmware/`metrics` reports), and each TX's own unambiguous range `+-lambda/(4*n_bands*Tc)`, `n_bands` = 8 (6 TX + 2 empty). See s3. GUI headline: pending user ruling |
| Virtual array | `n_TX*n_RX` | `n_TX*n_RX` = 6 x 8 = 48 |
| Cfg that sets it | `channelCfg`, `chirpCfg` (per-chirp TX mask), `frameCfg`, `bpmCfg` (opt-in), `advFrameCfg` (stock only; subframes may each use a different pattern; not SAR) | `channelCfg` (TX count 2,3,4 or 6), `frameCfg`; `chirpCfg txEnable` is overwritten by the parser (`CAS/.../mmwdemo_rfparserDDMA.c:717-733`); no `advFrameCfg` (`mss_main.c:3888-3891`) |
| Phase codes | none (BPM sign is switched by the demo when `bpmCfg` is on) | firmware only: `rlRfSetPhaseShiftConfig` per chirp, `txAntMaskEnable=63` hard-coded (`mss_main.c:3796-3850`); not a cfg command |

## 2. Timing diagrams (one column per chirp, `#` = TX on)

**TDM, 3 TX, pattern 1,4,2 (TX1, TX3, TX2), `cpl = 3`, `L = 2`.**
```
chirp  : 0  1  2 | 3  4  5          n_TX = 3  (TX1, TX3 azimuth; TX2 elevation)
TX1    : #  .  . | #  .  .          interval per TX = 3*Tc
TX2    : .  .  # | .  .  #
TX3    : .  #  . | .  #  .
```

**TDM, 2 TX BPM (opt-in), mask 5 on both chirps, `cpl = 2`.** `bpmCfg` flips the sign of one TX on alternate chirps (sign pattern is the BPM concept, not read from source here). A chirp pair is the decode unit: combining the two chirps separates TX1 from TX3, so each TX gets one sample per pair, i.e. `n_TX = 2`, interval `2*Tc`.
```
chirp  : 0  1 | 2  3
TX1    : #  # | #  #
TX3    : #  # | #  #     (sign pattern, e.g. +,+ then +,-: unverified)
```

**DDMA, 6 TX, `cpl = 8`.** All six TX fire on every chirp; TX of rank `r` gets phase `phi = k*r/n_bands` turns on chirp `k` (M2 s3), so the Doppler spectrum splits into `n_bands = 8` sub-bands, one per TX, 2 left empty. The per-chirp step `360*r/8 = 45*r` degrees is my derivation from that form, not quoted from M2; whether `r` runs 0..5 or 1..6, and which bands are empty, is not established here.
```
Doppler: -vmax                                    +vmax    (vmax = lambda/(4 Tc))
         | b0 | b1 | b2 | b3 | b4 | b5 | b6 | b7 |        each band = 1/8 of the span
         | T  | T  | T  | T  | T  | T  | -  | -  |        T = one TX's band; - = empty (positions unverified)
```

## 3. Worked numbers (`lambda = 3.9 mm`, `Tc = 50 us`)

**TDM 3 TX (1,4,2), `cpl = 3`, `L = 64`:** `N = 192`; Doppler chirps per antenna `= 192/3 = 64`, bins 64; `vmax = 3.9e-3/(4*3*50e-6) = 6.5 m/s`; `dv = 3.9e-3/(2*192*50e-6) = 0.203 m/s`; step `= 3.9e-3/(2*64*3*50e-6) = 0.203 m/s`. Virtual 12 (8 azimuth + 4 elevation, n_RX = 4).

**TDM `[1,4,1,4]` repeat, `cpl = 4`, `L = 32`:** `n_TX = 2` (distinct azimuth TX), not 4. `vmax = 3.9e-3/(4*2*50e-6) = 9.75 m/s`; code using `cpl*Tc` would give 4.875 m/s (M1 s4 item 3).

**BPM, mask 5 on both chirps, `cpl = 2`, `L = 64`:** `N = 128`, `n_TX = 2`, 64 Doppler chirps per TX; `vmax = 9.75 m/s`; `dv = 3.9e-3/(2*128*50e-6) = 0.305 m/s`. Virtual 8 (n_RX = 4). Non-power-of-2 case: `[1,4,2]` with `L = 50` gives `N = 150`, 50 chirps per antenna, so 64 bins (next pow2) and the step shrinks to `lambda/(2*64*3*Tc)`.

**SIMO (multi-TX mask on every chirp, no `bpmCfg`):** accepted, `n_TX = 1`, both TX transmit together, virtual `= n_RX` (4), not 8 (`RP:608-616`). `cpl = 1`: `vmax = 3.9e-3/(4*1*50e-6) = 19.5 m/s`.

**DDMA 6 TX, `cpl = 8`, `L = 32` (TI `cascade_shortrange`):** `N = 256`; `dv = 3.9e-3/(2*256*50e-6) = 0.152 m/s`; full span `+-3.9e-3/(4*50e-6) = +-19.5 m/s`; each TX's own range `+-3.9e-3/(4*8*50e-6) = +-2.44 m/s` (a band is 4.9 m/s wide); sub-band bins `256/8 = 32`. A target faster than 2.44 m/s lands in a neighbouring TX's band, so it is attributed to the wrong TX (wrong virtual-array phase) unless the firmware resolves it. Established (M2 s3): the 2 empty bands exist as slack for this, and TI's `gtrack` line carries 19.41 (= the full span). HYPOTHESIS: the empty bands let the firmware disambiguate TX identity beyond 2.44 m/s; the algorithm was not read here (test: move a known target above 2.44 m/s and check angle coherence).

## 4. What you can edit

**TDM:** the chirp table (presets SIMO / 2-TX / 3-TX / BPM), `L`, period, profile. `channelCfg` TX = OR of the chirp masks (parser requires `(chirp mask & channelCfg tx) > 0` per chirp; `RP:836`). Rules: no mixing one-TX and multi-TX chirps; keep the pattern `n_TX`-periodic; TI order is 1,4,2. **GUI default = plain TDM, `bpmCfg` disabled; BPM is an opt-in preset** available only where the stock demo supports it: 1843/6843 yes, 1443 no, SAR not confirmed (descriptor `bpm` false).

**DDMA:** profile, `L`, period, `channelCfg` TX count. `cpl` should be a multiple of `n_bands` (8; shipped cfgs all use 8; inferred, HYPOTHESIS, M2 experiment 1). The chirp table and phase codes are **view-only**, since the firmware sets them. One cfg per power-up; one profile used.

## 5. Unverified (carried from M1/M2)

- HYPOTHESIS: TX order 1,4,2 vs 1,2,4 may mislabel azimuth/elevation virtual antennas (no bench test). M1 experiment 2.
- HYPOTHESIS: non-cyclic patterns (`[1,4,1,2]`) misdecode; `[1,4,1,4]` working is inferred from the parser, not run. 3-TX `L` should be even (medium): the range DPU de-interleaves chirp `k` to TX `k mod 3` with a stride of 6 chirps, i.e. two loops, so an odd `L` leaves a partial stride. M1 experiment 1.
- Cascade TDM exists only as the compile-time `MMWDEMO_TDM` build (untested here); the shipped build is DDMA, and a one-TX-per-chirp cfg will not decode as TDM (HYPOTHESIS, M1 s3).
- 1443 BPM and all 1443 rules (shipped demo is SDK 2.x, no source); `dca1000_raw` TDM/BPM rules (binaries, `tdm` true, `bpm` false, limits unverified); SAR BPM (same parser, not confirmed).
