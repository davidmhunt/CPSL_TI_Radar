# Cfg performance formulas

Hand-check sheet for every number `radar_gui/cfg/metrics.py` derives from a `.cfg`, plus the inverse solver in `radar_gui/cfg/generate.py` (directive gui-12, #51). This content migrates to `mmwave_radar_processing` (gui-17); this file is then a pointer.

## Chirp timeline

```
 one chirp, Tc = idle + ramp                         frame = n_chirps * Tc active, then dead time
 |<-- idle -->|<------------ ramp (ramp_us) ------------>|<-- idle -->|<-- ramp --> ...
              |<adcStart>|<--- ADC window N/fs --->|margin|
 freq         .          .  /|                      |     |
  ^                        /                             B = slope * N/fs  (sampled band)
  |            ________/  slope (MHz/us)
  +-------------------------------------------------------------> time
 |<------------------- frame_period (frameCfg) ----------------------->|
 |<-- n_chirps * Tc (active_ms) -->|<---------- dead time ------------>|   duty = active / period
```

## Formulas

Units: `slope` MHz/us, `fs` ksps, times us unless noted, `c` m/s, `lambda = c/fc`.

| Quantity | Formula | Code (`radar_gui/cfg/`) |
|---|---|---|
| ADC window | `t_s = N*1000/fs` (us) | `metrics.metrics` `sampling_us` |
| Sampled bandwidth | `B = slope * t_s` (MHz) | `metrics.metrics` `bw` |
| Centre frequency | `fc = start + (slope*adcStart + B/2)/1000` (GHz) | `metrics.metrics` `fc_ghz` |
| Chirp time | `Tc = idle + ramp` | `metrics.metrics` `tc` |
| Range resolution | `dR = c / (2 B)` | `metrics.metrics` `range_res` |
| Max range | `Rmax = 0.9 * c * fs / (2 slope)` (halved if `adcCfg` fmt 0, real) | `metrics.metrics` `ideal`, `USABLE_IF` |
| Velocity resolution | `dv = lambda / (2 * n_chirps * Tc)`, `n_chirps = chirps_per_loop * loops` | `metrics.metrics` `vel_res` |
| Max velocity, TDM | `vmax = lambda / (4 * chirps_per_loop * Tc)` | `metrics.metrics` `max_v` |
| Max velocity, cascade DDMA | `vmax = lambda / (4 * Tc)` | `metrics.metrics` `max_v` |
| Azimuth resolution | `dTheta = 2 / N_az` rad `= degrees(2/N_az)` | `metrics.metrics` `az_res` |
| Frame period / rate | `period = frameCfg period (ms)`, `rate = 1000/period` Hz | `metrics.frame_layout` |
| Active time, duty | `active = n_chirps * Tc * 1e-3` (ms); `duty = active / period` | `metrics.metrics` `active_ms`, `duty_cycle` |
| Bytes per sample | 2 if `adcCfg` fmt 0 (real), else 4 (16-bit I + Q) | `metrics.metrics` `bps` |
| Bytes per chirp | `N * n_rx * bps + meta`, `meta = 64` iff `lvdsStreamCfg` dataFmt 2 | `metrics.metrics` `per_chirp` |
| Bytes per frame | `per_chirp * n_chirps` | `metrics.metrics` `per_frame` |
| Average rate | `bytes_per_frame * 8 / (period*1e3)` (Mbit/s) | `metrics.metrics` `avg_data_rate_mbps` |
| Burst rate | `fs*1e3 * n_rx * bps * 8 / 1e6` (Mbit/s, while sampling) | `metrics.metrics` `burst_rate_mbps` |
| Per-chirp rate | `bytes_per_chirp * 8 / Tc` (Mbit/s; ADC buffer drains between chirps) | `metrics.metrics` `chirp_avg_rate_mbps` |

`N_az`: cascade = `n_tx * n_rx` (all enabled TX and RX); single chip = (azimuth TX in use, `TX1`/`TX3` mask `0b101`, at least 1) `* n_rx`. Rates are decimal Mbit/s (1e6), not MiB/s.

**Solver (`generate._design`, inverse of the above).** Given target range `R`, max velocity `v`, sample count `N`:
slope `= 0.9 * fs*1e3 * c / (2R) / 1e12` (rounded to 0.001); ramp `= ceil(100*(adcStart + t_s + margin))/100`; `Tc = c / (4 * factor * fc * v)` (us), `idle = round(Tc - ramp, 2)`, `factor = popcount(tx_mask)` (TDM) or `1` (DDMA); `N = round(R / (0.9 * dR) / 2) * 2` when `range_res_m` is given (follows from `dR = c/2B` with the slope above: `dR = R/(0.9 N)`); loops from `dv`: `chirps = lambda / (2 * dv * Tc)`, `loops = ceil(chirps / chirps_per_loop)` (`generate._loop_options`). Candidates are then re-run through `metrics`/`validate`; `duty <= 0.5` is preferred (`DUTY_PREFERRED`), `0.9` otherwise.

## Where code and textbook differ (flagged, not reconciled)

1. **Speed of light.** Code `C = 299_792_458.0` (exact). Hand calculations with `c = 3e8` differ by 0.07 % in `dR`, `Rmax`, `lambda`, `vmax`, `dv`. The `metrics.py`/`generate.py` docstrings write `c` without a value.
2. **0.9 factor (`USABLE_IF`).** Not derived. Textbook `Rmax = fs*c/(2*slope)` (complex sampling, Nyquist at `fs`); the code takes 90 % of it as "usable IF band", inherited from `tools/radar_viewer/cfggen.py` `USABLE_IF` (comment: "~90 % of the IF band is usable"); an empirical margin, no derivation in the repo. Reported as `max_range_m`; the un-derated value is `max_range_ideal_m`. The solver applies the factor in both directions, so a hand check against the ideal formula is off by exactly 0.9.
3. **Range resolution uses sampled bandwidth** `B = slope*N/fs`, not the swept `slope*ramp` (`sweep_mhz`). Textbook `c/(2B)` with the full ramp gives a finer, unattainable number.
4. **Max velocity multiplier is `chirps_per_loop`** (frameCfg `end-start+1`) in `metrics`, but `popcount(tx_mask)` in the solver. Equal for the shipped TDM cfgs; differ if a loop has chirps that do not map one-to-one to TX channels.
5. **DDMA slow time.** `dv` uses `n_chirps = chirps_per_loop * loops` (cascade: 8 chirps per loop) as the Doppler observation length, i.e. total active frame time. Whether the DDMA Doppler FFT length equals this is unverified against the firmware.
6. **Azimuth `2/N_az` is a boresight small-angle approximation**: `lambda / (N_az * d * cos(theta))` with `d = lambda/2`, `theta = 0`. It degrades off-boresight (`1/cos(theta)`) and ignores windowing (real 3 dB width is wider). FUTURE(gui-12): replace the uniform half-wavelength virtual array with real per-board geometry (6843 ODS/AOP, 2-chip cascade).
7. **Units.** `slope` MHz/us and `fs` ksps in the cfg; code converts with `1e3`/`1e12`/`1e6` inline (`ideal = c*fs*1e3 / (2*slope*1e12)`). Data rates are megabit/s, labelled `_mbps`.
8. **Real-only ADC.** Only `adcCfg` fmt 0 halves `Rmax` and uses 2 B/sample; any other fmt is treated as complex 4 B/sample.
9. **`fc` and `lambda`.** Textbook uses `fc = start`; code uses the sampled-band centre `start + slope*adcStart + B/2`, so `lambda` is shorter (B = 4 GHz shifts `fc` by 2 GHz, about 2.6 % at 77 GHz).
10. **Duty cycle** counts only `n_chirps * Tc` (idle included); frame-start jitter and inter-loop gaps are not modelled. `inf` when period `<= 0`.

## Assumptions

| # | Assumption | Effect if wrong |
|---|---|---|
| 1 | Complex 1x ADC (unless fmt 0) | `Rmax` and bytes off by 2x |
| 2 | Uniform half-wavelength virtual array, boresight | azimuth resolution optimistic |
| 3 | Single chip: `TX1`/`TX3` are the azimuth pair | 6843 ODS/AOP wrong |
| 4 | Cascade uses all 6 TX x 8 RX as one azimuth aperture | resolution optimistic |
| 5 | Cascade = DDMA (`vmax = lambda/(4 Tc)`); single chip = TDM | wrong `vmax` if a cfg differs |
| 6 | 0.9 IF usability and `c` exact | see items 1-2 |
| 7 | LVDS dataFmt 2 adds 64 B per chirp (`docs/firmware.md`) | bytes per frame off by 64 B/chirp |
| 8 | Metrics read the first `profileCfg` only (single profile) | multi-profile cfgs misreported (revised by gui-14) |
