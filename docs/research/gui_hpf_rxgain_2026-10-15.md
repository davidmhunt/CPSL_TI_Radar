# HPF1/HPF2 corner codes and profileCfg rxGain: per-chip values and encoding

**Date:** 2026-10-15
**Memo:** docs/research/gui_hpf_rxgain_2026-10-15.md

## Question as asked

Directive radar-36 Step 1: for each chip family (xWR1443, xWR1642/1843, xWR6843/6843ODS, AWR2243
cascade) tabulate HPF1 and HPF2 code -> kHz, and the profileCfg `rxGain` field (valid range, step,
dB, how the word encodes RF gain target bits vs the code in the cfg, e.g. `0x5E` in the Studio json),
whether `hpf1`/`hpf2` mean the same on all chips, and whether the SDK-3 CLI `profileCfg` (and the
cascade mmwavelink path) accepts every chip-allowed code. One row per value with source and
confidence; anything not confirmable is UNVERIFIED. Also: IF bandwidth / HPF roll-off order for the
UI's "range at corner" note. In scope: profileCfg fields 11-13 only.

## TL;DR

HPF codes are identical on every chip: HPF1 code 0..3 = 175/235/350/700 kHz, HPF2 code 0..3 =
350/700/1400/2800 kHz (datasheets of all five parts + mmwavelink doxygen + SDK user guide; high).
`rxGain` is a packed word: bits 5:0 = RX gain in dB (even values only; step 2 dB), bits 7:6 = RF
gain target code, bits 15:8 reserved. Valid gain: 24..48 (IWR1443, IWR1642, IWR1843), 30..48
(IWR6843/ODS), 32..52 (AWR2243); datasheet-backed (high). The RF-target code table differs by
family (xWR1xxx 30/34/rsvd/26 dB; xWR6843 ES2.0 30/33/36/rsvd dB; AWR2243 not confirmable from an
official document), so a GUI must range-check only bits 5:0 and preserve bits 7:6 (shipped cfgs use
158 = 0x9E on IWR6843/ODS). Both HPFs are first-order (20 dB/decade). Usable IF bandwidth is min(chip max IF, 0.9 fs) in complex 1x and min(max IF, 0.45 fs) in complex 2x/real (SWRA553); in complex 1x bins above fs/2 are real positive IF, not mirrors, and the passband edge is 0.9 fs (138.4 m for SAR_ugv_fmt2, matching the observed cliff).

## Evidence

### E1. HPF corner codes (same on all chips)

| Chip | HPF1 code 0/1/2/3 (kHz) | HPF2 code 0/1/2/3 (kHz) | Source | Conf. |
|------|-------------------------|-------------------------|--------|-------|
| IWR1443 | 175 / 235 / 350 / 700 | 350 / 700 / 1400 / 2800 | `swrs211c` §5.7 RF Specification, footnote (2), p.24-25 | high |
| IWR1642 (xWR1642) | 175 / 235 / 350 / 700 | 350 / 700 / 1400 / 2800 | `swrs212b` §5.7 RF Specification, "Available HPF Corner Frequencies" | high |
| IWR1843 | 175 / 235 / 350 / 700 | 350 / 700 / 1400 / 2800 | `swrs228b` §7.7 RF Specification, footnote (3), p.28-29 | high |
| IWR6843 (and ODS, same die) | 175 / 235 / 350 / 700 | 350 / 700 / 1400 / 2800 | `swrs219f` §7.9 RF Specification, footnote (2), p.32-33 | high |
| AWR2243 (cascade) | 175 / 235 / 350 / 700 | 350 / 700 / 1400 / 2800 | `swrs223d` §7.7 RF Specification, footnote (2), p.19-20 | high |
| all (code -> kHz mapping, field-level) | 0x00..0x03 as above | 0x00..0x03 as above | `mmwavelink_rlprofilecfg` rlProfileCfg_t `hpfCornerFreq1`/`hpfCornerFreq2` (rl_sensor.h line 522 ff.), SDK 3.3 build; same text in `mmwave_sdk_ug_36` §3.3.1 mmWave Demo CLI table (PDF p.23 of 83) and `mmwave_sdk_ug_11` | high |

The datasheets list the available corner *values* only; the code -> value ordering (index in the
list = code) comes from the mmwavelink struct documentation and the SDK user guide, both of which
state it explicitly. Meaning is therefore the same on all five chips. IWR6843ODS has no separate
datasheet entry in what was retrieved; it is the IWR6843 silicon on a different antenna/EVM
(medium confidence that it shares the IWR6843 table, high that the DFP struct is shared).

### E2. rxGain field: encoding

| Item | Value | Source | Conf. |
|------|-------|--------|-------|
| Word layout (16-bit) | b5:0 gain code, 1 LSB = 1 dB; b7:6 RF gain target code; b15:8 reserved | `mmwavelink_rlprofilecfg` rlProfileCfg_t `rxGain` | high |
| Meaning of b5:0 | The doxygen text calls it "Rx VGA gain"; a TI engineer on E2E (AWR1843 thread) says it is the total RX chain gain and the "VGA" wording is a documentation error. Datasheets treat it as total gain (24-48 dB). Treat as "RX gain (dB)". | `e2e_awr1843_rxgain_meaning` (via search snippet, thread not fetchable), `e2e_awr6843_rxgain_info` | medium |
| Step | 2 dB; doxygen "all even values" | `mmwavelink_rlprofilecfg`; datasheet "Gain step size 2 dB" in all five datasheets (RF Specification tables) | high |
| Decoding of 0x5E (Studio json, `22xx_monitor.mmwave.json:105`) | 0x5E = 0b01011110: b5:0 = 30 dB; b7:6 = 01 (RF target code 01). Meaning of code 01: 34 dB on xWR1xxx; 33 dB on xWR6843 ES2.0; AWR2243: UNVERIFIED (see below) | derived from the layout above | high for the split, see E3 for dB |
| Decoding of 158 (shipped IWR6843/ODS cfgs) | 0x9E = 0b10011110: b5:0 = 30 dB; b7:6 = 10 (RF target 36 dB on xWR6843 ES2.0; RESERVED on xWR1xxx table). TI staff confirm 158 = RF-gain bits + RX-gain bits combined. | `e2e_iwr6843_bounds` (TI reply by Santosh Krishnan, 2023-ish), `e2e_awr6843_rxgain_info` | medium-high |
| Decoding of 160 on AWR2243 ("32+2<<6" in a TI-hosted mmwaveconfig.txt) | VGA 32 dB + RF target code 2 | `e2e_awr2243_dfp_thread` (search snippet) | medium |
| Decoding of 30 / 40 (shipped IWR1443, IWR1843, cascade cfgs) | b7:6 = 00 -> RF target code 00 (30 dB on xWR1xxx and xWR6843; AWR2243 presumably 30 dB, see E3) | layout | high for the split |

### E3. rxGain valid range and RF gain target table per chip

| Chip | b5:0 min | b5:0 max | Step | Source for range | Conf. | RF target (b7:6) 00 / 01 / 10 / 11 | Source for RF target | Conf. |
|------|----------|----------|------|------------------|-------|-------------------------------------|----------------------|-------|
| IWR1443 | 24 | 48 | 2 | `swrs211c` §5.7 (Maximum gain 48 dB, range 24 dB, step 2 dB); `mmwave_sdk_ug_11` CLI table "rx gain in dB (valid values 24 to 48)" | high | 30 / 34 / RESERVED / 26 dB | `mmwavelink_rlprofilecfg`; `e2e_awr6843_rxgain_info` (quotes header text with per-family table) | high (doxygen) |
| IWR1642 (xWR1642) | 24 | 48 | 2 | `swrs212b` §5.7 (48 / 24 / 2) | high | 30 / 34 / RESERVED / 26 dB | same as IWR1443 | high |
| IWR1843 | 24 | 48 | 2 | `swrs228b` §7.7 (48 / 24 / 2) | high | 30 / 34 / RESERVED / 26 dB | same | high |
| IWR6843 / ODS | 30 | 48 | 2 | `swrs219f` §7.9 (Max 48, range 18, step 2 -> min 30); header text "xWR6x43: all even values from 30 to 48" quoted in `e2e_awr6843_rxgain_info`; ES2.0 "30 dB to 48 dB" quoted in `e2e_iwr6843_bounds` | high | ES2.0: 30 / 33 / 36 / RESERVED dB (ES1.0: RF gain fixed 34 dB, not applicable) | `e2e_awr6843_rxgain_info` (quotes rl_sensor.h text; the astroa.net doxygen mirror is an older header that lacks this table) | medium (secondary quote of header) |
| AWR2243 (cascade) | 32 | 52 | 2 | `swrs223d` §7.7 (Max 52, range 20, step 2 -> min 32); ICD "all even values from 32 to 52" quoted in `e2e_awr2243_pf_rx_gain` | high (datasheet), medium (ICD quote) | UNVERIFIED. Forum/MMWCAS posts give 30 / 33 / 36 / RESERVED dB and TI recommends 36 dB target for best NF; the `rxGain=160 #32+2<<6` TI example fits code 10 = 36 dB. The official ICD (mmWave-Radar-Interface-Control.pdf, DFP-2G) was not retrievable. | `e2e_awr2243_rf_target`, `e2e_mmwcas_rf_evm` (snippet), `mmwave_dfp_2g_release_notes` (MMWL-261: "Updated RF gain target settings ... in rlProfileCfg_t"; values not given) | low-medium |

Notes:

- The doxygen header for the whole xWR1xxx/2xxx family says "all even values from 24 to 52"
  (`mmwavelink_rlprofilecfg`); the datasheet maxima (48 for 1443/1642/1843/6843, 52 for AWR2243)
  are the tighter, per-part bounds and should be what the GUI enforces. The 52 in the family header
  is the AWR1243/AWR2243 maximum.
- The datasheet noise-figure-vs-gain plots (IWR1843 Figure 7-1, IWR6843 Figure 7-2, AWR2243 Figure
  7-1, IWR1443 Figure 5-1) are the basis for the "higher gain = lower NF, lower P1dB" annotation.
  AWR2243 plot assumes the 36 dB RF gain target (`e2e_awr2243_rf_target`, TI reply, medium).
- Odd values: doxygen says "all even values" are valid; whether firmware rejects, rounds or accepts
  odd values is UNVERIFIED.

### E4. Does the CLI / cascade path accept every chip-allowed code?

- SDK 3.6 mmWave Demo CLI `profileCfg`: `hpfCornerFreq1`, `hpfCornerFreq2` and `rxGain` are
  documented as "any value as per mmwavelink doxygen / device datasheet", with the code lists above;
  `rxGain` is "OR'ed value of RX gain in dB and RF gain target (see mmwavelink doxygen)"
  (`mmwave_sdk_ug_36`, §3.3.1, PDF p.23). The CLI hands the integers to `rlSetProfileConfig`
  unmodified; there is no CLI-side table. So all four HPF codes and every datasheet gain value are
  accepted by the CLI syntax (high). The CLI doc does not say how the firmware treats a
  range-violating value: UNVERIFIED (no source found).
- Cascade (MMWCAS / mmwavelink on AWR2243): the same `rlProfileCfg_t` struct, so the same fields
  and HPF table apply (high, E1). No MMWCAS-specific restriction on hpf/rxGain codes was found in
  the sources reachable here; that the cascade path accepts every code is UNVERIFIED (absence of
  evidence). The RF-target table is the open item (E3).
- Related: a forum thread says rlProfileCfg_t cannot bypass HPFs (no "off" code) (`e2e_awr1642_hpf_bypass`,
  search snippet only, low).

### E5. IF bandwidth and HPF roll-off (for the "range at corner" note)

| Chip | IF bandwidth (max) | ADC rate real / complex 1x | Source | Conf. |
|------|--------------------|-----------------------------|--------|-------|
| IWR1443 | 15 MHz | 37.5 / 18.75 Msps | `swrs211c` §5.7 | high |
| IWR1642 | 5 MHz | not extracted | `swrs212b` §5.7 | high |
| IWR1843 | 10 MHz | 25 / 12.5 Msps | `swrs228b` §7.7 | high |
| IWR6843 / ODS | 10 MHz | 25 / 12.5 Msps | `swrs219f` §7.9 | high |
| AWR2243 | 20 MHz | 45 / 22.5 Msps | `swrs223d` §7.7 | high |

- Roll-off order: every datasheet footnote says "two independently configurable first-order
  high-pass corner frequencies" (all five datasheets). First-order = 20 dB/decade, 6 dB/octave per
  filter; magnitude $|H(f)| = f / \sqrt{f^2 + f_c^2}$ (standard first-order HPF; this formula is not
  stated in the datasheets, but follows from "first-order"). At $f = f_c$ it is $-3$ dB; at
  $f_c/2$ about $-7$ dB; at $f_c/4$ about $-12$ dB; at $f_c/10$ about $-20$ dB (per HPF, confidence
  high for the order, medium for exact analog response). With both enabled the two stages combine
  (the datasheets do not state explicitly that HPF1 and HPF2 are in series; medium).
- A beat frequency $f$ corresponds to range $R = f c / (2 S)$ with slope $S$; so the "range at
  corner" for corner $f_c$ is $f_c c/(2S)$, and the upper edge for IF bandwidth $B_{IF}$ is
  $B_{IF} c / (2S)$ (geometry, not a TI-sourced value; the datasheet also targets
  < 0.5 dB droop and > 60 dB alias rejection in the digital baseband).
- Datasheet 1-dB compression point (out of band) is measured with a 10 kHz tone "well below the lowest
  HPF cut-off" (50 kHz on IWR1443): the lowest corner is 175 kHz, so corner choices below 175 kHz
  do not exist.

### E6. Usable IF bandwidth per ADC output mode (scope addition)

Rule (TI): usable IF bandwidth is $\min(B_{IF,\max},\, 0.9 f_s)$ in complex 1x and
$\min(B_{IF,\max},\, 0.9 f_s/2)$ in complex 2x and real (`swra553` §2.1 "Measurement Range and
Range Resolution", Eq. 1 and the paragraph after it: "In a complex 1x sampling mode, the IF
bandwidth is limited to 0.9*(ADCsampling). In case of complex 2x and real sampling modes, the IF
bandwidth is limited to 0.9*(ADCsampling)/2"; high). The DFE decimation chain is designed so that
"90% of the final output sampling rate is preserved as the passband of interest" (complex 1x;
`ar_baseband_appnote` §3.1.2.1; medium, see caveat). A TI E2E reply for IWR1443 quotes an 80%
passband (`e2e_iwr1443_adc_rate`, search snippet, low) which conflicts; the first-party app note
and SWRA553 both say 0.9, use 0.9.

| Chip | Max IF (analog) | Max sample rate: real / complex 2x | Max sample rate: complex 1x | Complex-1x usable BW = min(IF, 0.9 fs) at max fs | Source | Conf. |
|------|-----------------|-------------------------------------|------------------------------|---------------------------------------------------|--------|-------|
| IWR1443 | 15 MHz | 37.5 Msps | 18.75 Msps | min(15, 16.9) = 15 MHz | `swrs211c` §5.7; family table in `swrs228b` (cover "Device Comparison" row "Max I/F", "Max real/complex sampling rate") | high |
| IWR1642 | 5 MHz | 12.5 Msps | 6.25 Msps | min(5, 5.6) = 5 MHz | `swrs212b` §5.7; `swrs228b` device-comparison table | high |
| IWR1843 | 10 MHz | 25 Msps | 12.5 Msps | min(10, 11.25) = 10 MHz | `swrs228b` §7.7 | high |
| IWR6843 / ODS | 10 MHz | 25 Msps | 12.5 Msps | min(10, 11.25) = 10 MHz | `swrs219f` §7.9 | high |
| AWR2243 | 20 MHz | 45 Msps | 22.5 Msps | min(20, 20.25) = 20 MHz | `swrs223d` §7.7 | high |

At a given (lower) sample rate the digital limit governs: complex 1x $B = 0.9 f_s$ (so SAR_ugv_fmt2,
$f_s = 2$ Msps complex 1x, gives 1.8 MHz); complex 2x and real $B = 0.45 f_s$. In the SDK CLI the
mode is `adcCfg` `<adcOutputFmt>`: 0 real, 1 complex 1x "image band filtered output", 2 complex 2x
"image band visible" (`mmwave_sdk_ug_36` §3.3.1, PDF p.20 of 83; high); `adcbufCfg`
`<adcOutputFmt>` 0 = complex, 1 = real, in ADC buffer terms (same table). Whether the DCA1000 raw
stream is "complex 1x" at the chip is fixed by `adcCfg`, not `adcbufCfg`. The cascade (AWR2243)
uses the same DFE modes; the AWR2243 datasheet quotes the 45 / 22.5 Msps figures.

Worked check, SAR_ugv_fmt2 (slope $S = 1.95$ MHz/us, $f_s = 2$ Msps, complex 1x): the range
axis end $f_s c / (2S) = 153.8$ m and the TI passband edge $0.9 f_s c / (2S) = 138.4$ m. The
observed cliff at ~138 m therefore matches the documented 0.9 f_s digital passband edge
(derived; HYPOTHESIS that it is the DFE filter and not something else; the range-FFT's windowing
or CFAR edge handling are not excluded by documents).

Bins above $f_s/2$ in complex 1x. Answer: they are real positive IF, not mirror images. Evidence: the
DFE output spectrum for "Complex 1X" is drawn one-sided on the axis $-f_s \ldots 0 \ldots f_s$
with the in-band signal over $0 \ldots f_s$ (alias region beyond), versus "Complex 2X" drawn over
$-f_s/2 \ldots f_s/2$ with in-band and image band, and "Real" as symmetric/mirrored
(`ar_baseband_appnote` Fig. 5 and §3.1.2; medium, because the document is the June 2015 AR1243/1642
note, marked "TI Confidential - NDA Restrictions" but publicly hosted on E2E, and its AWR2243/IWR1843
equivalence is by shared DFE architecture, not stated). The note says the complex output spectrum
"is one-sided and is devoid of image band noise fold-back", and that the frequency centering is
undone so "the mapping between the beat frequency and the range measurement remains unchanged"
(§3.1.3). A TI E2E snippet likewise labels complex 1x as a "0 to Fs upper sideband" mode
(`e2e_iwr1443_adc_rate`, low). Consequences: (a) the N-point complex FFT's upper half (bins $N/2 \ldots N$)
corresponds to beat frequencies $f_s/2 \ldots f_s$ (positive), so range = bin $\cdot f_s/N \cdot c/(2S)$
over the whole axis $0 \ldots f_s c/(2S)$; (b) only the image-band leakage (IMRR 30 dB typical on
1443/1843/2243, 21 dB on IWR1642 from the datasheet tables) is mirrored; (c) usable region ends
at $0.9 f_s$, then the anti-alias filter rolls off ("60 dB suppression for out-of-band signals",
`ar_baseband_appnote` §3.1.2.1; medium). In complex 2x and real modes the usable region is
$0 \ldots 0.45 f_s$ with real mode mirrored about $f_s/2$.

## Applicability to console

The GUI tables can be keyed by chip with the values above. Direct consequences (stated as facts
about TI documentation, not results of this project):

- HPF kHz lists are common to every board: one list pair; high confidence.
- Gain min/max/step per board: 24/48/2 (IWR1443, IWR1642, IWR1843), 30/48/2 (IWR6843, IWR6843ODS),
  32/52/2 (AWR2243_CASCADE). The shipped cfgs (30 on IWR1443/IWR1843/cascade, 158 on IWR6843/ODS,
  40 on one user cfg) are in range only if the check is applied to `rxGain & 0x3F`; the raw 158
  would fail a naive 24..48 check. HYPOTHESIS: the Coder should decode bits 5:0 / 7:6 for display
  and validation and preserve the whole word on write-back, so shipped files round-trip.
- Shipped IWR6843 cfgs use RF target code 10; on IWR1843 that code is RESERVED per the xWR1xxx
  table. The UI should annotate the RF target text only for chips whose table is confirmed
  (xWR1xxx, xWR6843) and show "RF target: UNVERIFIED" on the cascade.
- `generate.py:517` uses `(0,30)` / `(2,42)` for the cascade: 42 and 30 are valid even values in
  32..52? 30 is **below** the 32 dB AWR2243 minimum implied by the datasheet/ICD quote. HYPOTHESIS:
  cascade cfgs with rxGain 30 are being clamped or accepted by firmware; the repo's cascade bench
  work (docs/RESULTS.md) shows they run, so firmware does not reject 30, but whether it is clamped to
  32 is unverified. Do not "fix" the generator on this memo's evidence alone.

## Recommended Experiment

1. (Resolves the RF-target and odd-value open items, no new hardware beyond what exists.) On the
   cascade, issue `profileCfg` with rxGain = 31, 32, 34 and 0x40|32, 0x80|32, read back the profile
   via the mmwavelink get call (or observe ADC amplitude at fixed target); compare ratio in dB vs.
   the table. Cost: one session on the cascade bench; the Runner can do it under a new directive.
2. Obtain `mmWave-Radar-Interface-Control.pdf` and the DFP-2G `rl_sensor.h` from the TI MMWAVE-DFP
   download (needs a TI login, supervised) to settle the AWR2243 RF-target table and the exact
   min/max wording.

## Confidence

Established (high): HPF code tables on all chips; word layout; step 2 dB; datasheet min/max gain
for each chip; first-order HPF; IF bandwidths. Medium: IWR6843 ES2.0 RF-target table and "30 to 48"
(secondary quotes of the header on E2E, forum threads); the "b5:0 is total gain" interpretation.
Low / UNVERIFIED: the 0.9 vs 80% passband conflict for IWR1443 (TI forum, snippet) is resolved in favour of 0.9 by two TI documents but not by a device-specific datasheet statement; the one-sided complex-1x spectrum is from a 2015 AR1243/1642 app note, not from a document for each chip; AWR2243 RF-target table; whether firmware clamps or rejects odd or out-of-range
gain values; whether the cascade/MMWCAS path accepts every code; IWR6843ODS-specific datasheet
(taken from the IWR6843 datasheet); whether HPF1/HPF2 are in series. E2E forum pages were blocked
for direct fetching mid-session; claims that rest on search-engine snippets of those pages are
labelled "snippet". No local PDF copies were stored (this repo has no `docs/references/`); the
datasheet and SDK UG URLs are stable TI links.

## Sources

- `mmwavelink_rlprofilecfg` — Texas Instruments (mmWave SDK 3.x), "rlProfileCfg_t Struct Reference (mmwavelink doxygen, rl_sensor.h)," *TI mmWave SDK documentation (mirror)*. url:https://astroa.net/fmcw-RADAR/mmwave_sdk/packages/ti/control/mmwavelink/docs/doxygen/html/structrl_profile_cfg__t.html
- `mmwave_sdk_ug_36` — Texas Instruments (2021), "MMWAVE SDK User Guide, Product Release 3.6 LTS, section 3.3.1 mmWave Demo CLI," *TI*. url:https://dr-download-cdn.ti.com/software-development/software-development-kit-sdk/MD-PIrUeCYr3X/03.06.00.00-LTS/mmwave_sdk_user_guide.pdf
- `mmwave_sdk_ug_11` — Texas Instruments (2017), "MMWAVE SDK 1.1 User Guide, profileCfg CLI table," *TI*. url:https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/7571.5545.mmwave_5F00_sdk_5F00_user_5F00_guide.pdf
- `swrs211c` — Texas Instruments (2018), "IWR1443 Single-Chip 76-GHz to 81-GHz mmWave Sensor, SWRS211C, section 5.7 RF Specification," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr1443.pdf
- `swrs212b` — Texas Instruments (2018), "IWR1642 Single-Chip 76-GHz to 81-GHz mmWave Sensor, SWRS212B, section 5.7 RF Specification," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr1642.pdf
- `swrs228b` — Texas Instruments (2024), "IWR1843 Single-Chip 76-GHz to 81-GHz Automotive Radar Sensor, SWRS228B, section 7.7 RF Specification," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr1843.pdf
- `swrs219f` — Texas Instruments (2025), "IWR6843 Single-Chip 60-GHz to 64-GHz Intelligent mmWave Sensor, SWRS219F, section 7.9 RF Specification," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/iwr6843.pdf
- `swrs223d` — Texas Instruments (2024), "AWR2243 Single-Chip 76-GHz to 81-GHz FMCW Transceiver, SWRS223D, section 7.7 RF Specification," *Datasheet*. url:https://www.ti.com/lit/ds/symlink/awr2243.pdf
- `mmwave_dfp_2g_release_notes` — Texas Instruments (2020), "MMWAVE-DFP-2G 02.02.02.01 release notes (MMWL-261)," *TI*. url:https://software-dl.ti.com/ra-processors/esd/MMWAVE-DFP-2G/02_02_02_01/exports/mmwave_dfp_release_notes.pdf
- `e2e_awr6843_rxgain_info` — TI E2E (2021), "AWR6843: Rx Gain information / Explanation (quotes rl_sensor.h rxGain text with per-family tables)," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1023606/awr6843-rx-gain-information-explanation
- `e2e_iwr6843_bounds` — TI E2E (2023), "IWR6843: the value bounds for rxgain (TI reply: 158 = RF gain + RX gain bits)," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1349124/iwr6843-the-value-bounds-for-rxgain
- `e2e_awr2243_pf_rx_gain` — TI E2E (2021), "AWR2243: Profile Configuration, PF_RX_GAIN and TX_CAL_EN_CFG (ICD quote: even values 32 to 52)," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1067971/awr2243-profile-configuration-pf_rx_gain-and-tx_cal_en_-cfg
- `e2e_awr2243_rf_target` — TI E2E (2022), "AWR2243: How to decide Rx Gain and RF_Target_Gain (TI: use 36 dB target)," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1185429/awr2243-how-to-decide-rx-gain-and-rf_target_gain
- `e2e_awr2243_dfp_thread` — TI E2E (2021), "AWR2243BOOST: Awr2243 DFP DCA1000 (rxGain=160 #32+2<<6), search snippet only," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/1053573/awr2243boost-awr2243-dfp-dca1000
- `e2e_mmwcas_rf_evm` — TI E2E China (n.d.), "MMWCAS RF EVM (RF gain target 30/33/36 dB, search snippet only)," *TI E2E China forum*. url:https://e2echina.ti.com/support/sensors/f/sensors-forum/208143/mmwcas-rf-evm
- `e2e_awr1843_rxgain_meaning` — TI E2E (2019), "CCS/AWR1843BOOST: The meaning of rxGain in the profile configuration, search snippet only," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/839261/ccs-awr1843boost-the-meaning-of-rxgain-in-the-profile-configuration
- `e2e_awr1642_hpf_bypass` — TI E2E (2018), "AWR1642: how to bypass HPF1/HPF2 in radar API, search snippet only," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/651547/awr1642-how-to-bypass-hpf1-hpf2-in-radar-api
- `swra553` — Vivek Dham (2020), "Programming Chirp Parameters in TI Radar Devices, SWRA553A," *TI application report*. url:https://www.ti.com/lit/pdf/swra553
- `ar_baseband_appnote` — Murali, Ramasubramanian (2015), "Digital Baseband Architecture in AR1243/AR1642 Automotive Radar Devices, v0.6 (TI Confidential - NDA Restrictions legend, publicly hosted)," *TI application report draft*. url:https://e2e.ti.com/cfs-file/__key/communityserver-discussions-components-files/1023/AR_5F00_baseband_5F00_appnote_5F00_v0p6.pdf
- `e2e_iwr1443_adc_rate` — TI E2E (2018), "IWR1443: ADC sampling rate (80% DFE passband; complex 1x as 0 to Fs), search snippet only," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/738323/iwr1443-adc-sampling-rate
