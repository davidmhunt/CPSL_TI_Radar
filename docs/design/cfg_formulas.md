# Cfg performance formulas

Hand-check sheet for every number `radar_gui/cfg/metrics.py` derives from a `.cfg`, plus the inverse solver in `radar_gui/cfg/generate.py` (gui-12, #51). Migrates to `mmwave_radar_processing` (gui-17).

## Chirp timeline

```
 chirp Tc = idle + ramp (ramp_us)            frame = n_chirps * Tc active, then dead time
 |<-- idle -->|<------------ ramp ------------>|<-- idle -->|<-- ramp --> ...
              |<adcStart>|<-- ADC window N/fs -->|margin|
 freq ^        ________/  slope (MHz/us); B = slope * N/fs (sampled band)
 |<------------------- frame period (frameCfg) ------------------->|
 |<-- n_chirps * Tc (active_ms) -->|<--------- dead time --------->|   duty = active / period
```

## Formulas

Symbols (cfg field, unit): `N` profileCfg numAdcSamples; `fs` digOutSampleRate (ksps); `slope` freqSlopeConst (MHz/us); `start` startFreqConst (GHz); `adcStart`, `idle`, `ramp` adcStartTime, idleTime, rampEndTime (us); `margin` solver guard after the ADC window (us, not a cfg field); `loops` frameCfg numLoops; `chirps_per_loop` frameCfg `end-start+1`; `n_chirps = chirps_per_loop*loops`; `period` frameCfg periodicity (ms); `n_rx`, `n_tx` enabled RX/TX in channelCfg; `fmt 0` adcCfg adcOutputFmt 0 (real; else complex); `dataFmt 2` lvdsStreamCfg (adds 64 B header). Times us, `c` m/s, `lambda = c/fc`. Inline `1e3`/`1e12`/`1e6` convert units; rates are decimal Mbit/s.

| Quantity | Formula | Code: `radar_gui/cfg/metrics.py`, `metrics()` variable unless noted |
|---|---|---|
| ADC window | `t_s = N*1000/fs` (us) | `sampling_us` |
| Sampled bandwidth | `B = slope * t_s` (MHz) | `bw` |
| Centre frequency | `fc = start + (slope*adcStart + B/2)/1000` (GHz) | `fc_ghz` |
| Chirp time | `Tc = idle + ramp` | `tc` |
| Range resolution | `dR = c / (2 B)` | `range_res` |
| Max range | `Rmax = 0.9 * c * fs / (2 slope)` (halved if `fmt 0`) | `ideal`, `USABLE_IF` |
| Velocity resolution | `dv = lambda / (2 * n_chirps * Tc)` | `vel_res` |
| Max velocity | `n_TX`, `T_loop`, Doppler bins/step and `vmax` per MIMO scheme: see `mimo_modes.md` (source). Reports `vmax_full_ms` (= `max_velocity_ms`) and `vmax_per_tx_ms`; GUI headline pending user ruling | `max_v`, `vmax_full_ms`, `vmax_per_tx_ms` |
| Azimuth resolution | `dTheta = 2 / N_az` rad (`degrees()` for deg) | `az_res` |
| Frame rate | `rate = 1000 / period` Hz | `frame_layout()` |
| Active time, duty | `active = n_chirps * Tc * 1e-3` (ms); `duty = active / period` | `active_ms`, `duty_cycle` |
| Bytes per sample | 2 if `fmt 0`, else 4 (16-bit I + Q) | `bps` |
| Bytes per chirp | `per_chirp = N * n_rx * bps + meta`, `meta = 64` iff `dataFmt 2` | `per_chirp` |
| Bytes per frame | `per_frame = per_chirp * n_chirps` | `per_frame` |
| Average rate | `per_frame * 8 / (period * 1e3)`: bytes*8 / us (`period` ms to us) = Mbit/s | `avg_data_rate_mbps` |
| Burst rate | `fs*1e3 * n_rx * bps * 8 / 1e6` (Mbit/s, sampling) | `burst_rate_mbps` |
| Per-chirp rate | `per_chirp * 8 / Tc`: bytes*8 / us = Mbit/s | `chirp_avg_rate_mbps` |

`N_az`: cascade = `n_tx * n_rx`; single chip = (azimuth TX in use: `TX1`/`TX3`, mask `0b101`, min 1) `* n_rx`.

**Solver (`generate._design`, inverse of the above).** Given target range `R`, `v_target`, `dv_target`, sample count `N`: slope `= 0.9 * fs*1e3 * c / (2R) / 1e12` (rounded to 0.001); ramp `= ceil(100*(adcStart + t_s + margin))/100`; `Tc = c / (4 * factor * fc * v_target)` (us), `idle = round(Tc - ramp, 2)`, `factor = popcount(tx_mask)` (TDM) or `1` (DDMA); `N = round(R / (0.9 * dR) / 2) * 2` if `range_res_m` given (`dR = R/(0.9 N)`); `chirps = lambda / (2 * dv_target * Tc)`, `loops = ceil(chirps / chirps_per_loop)` (`generate._loop_options`). Candidates are re-checked by `metrics`/`validate`; `duty <= 0.5` preferred (`DUTY_PREFERRED`), else `0.9`.

## Where code and textbook differ (flagged, not reconciled)

1. **Speed of light.** Code `C = 299_792_458.0` (exact). Hand calculations with `c = 3e8` differ by 0.07 % in `dR`, `Rmax`, `lambda`, `vmax`, `dv`.
2. **0.9 factor (`USABLE_IF`).** Not derived. Textbook `Rmax = fs*c/(2*slope)`; code takes 90 % as "usable IF band", inherited from `tools/radar_viewer/cfggen.py` (empirical). Reported as `max_range_m`; un-derated is `max_range_ideal_m`. The solver applies it both ways, so a hand check against the ideal formula is off by exactly 0.9.
3. **Range resolution uses sampled bandwidth** `B = slope*N/fs`, not the swept `slope*ramp` (`sweep_mhz`).
4. **TDM `n_TX` and `vmax`** use `n_TX*Tc` per `mimo_modes.md`, not `chirps_per_loop*Tc`. Solver still uses `popcount(tx_mask)`.
5. **DDMA slow time.** `dv` uses `n_chirps = chirps_per_loop * loops` as the Doppler observation length (total active frame time; cascade: 8 chirps per loop). Confirmed by the cascade memo (M2 s4, `rfparserDDMA.c:786-807`).
6. **Azimuth `2/N_az` is a boresight small-angle approximation**: `lambda / (N_az * d * cos(theta))` with `d = lambda/2`, `theta = 0`. Degrades off-boresight (`1/cos(theta)`); ignores windowing. FUTURE(gui-12): replace the uniform half-wavelength virtual array with real per-board geometry (6843 ODS/AOP, 2-chip cascade).
7. **Real-only ADC.** Only `fmt 0` halves `Rmax` and uses 2 B/sample; any other fmt is treated as complex 4 B/sample.
8. **`fc` and `lambda`.** Textbook uses `fc = start`; code uses the sampled-band centre `start + slope*adcStart + B/2`, so `lambda` is shorter (B = 4 GHz: `fc` shifts 2 GHz, ~2.6 %).
9. **Duty cycle** ignores frame-start jitter and inter-loop gaps; `inf` when period `<= 0`.

## Assumptions

| # | Assumption | Effect if wrong |
|---|---|---|
| 1 | Complex ADC unless `fmt 0` (item 7); cascade = DDMA, single chip = TDM (item 4) | `Rmax`, bytes, `vmax` off |
| 2 | Uniform half-wavelength virtual array at boresight; cascade: all 6 TX x 8 RX one aperture; single chip: `TX1`/`TX3` azimuth pair (item 6) | azimuth optimistic; 6843 ODS/AOP wrong |
| 3 | `dataFmt 2` adds 64 B/chirp (`docs/firmware.md`); metrics read first `profileCfg` only (gui-14) | bytes off; multi-profile misreported |
