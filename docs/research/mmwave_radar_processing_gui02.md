# Can gui-02 be built on `mmwave_radar_processing` instead of a new module?

**Date:** 2026-10-06
**Memo:** docs/research/mmwave_radar_processing_gui02.md

## Question as asked

Can directive gui-02 (cfg parse/generate for IWR1443/1843/6843 and the AWR2243 cascade; range/velocity/angular resolution, max range/velocity, frame period, bytes per frame; validation against per-board firmware limits) be built on the user's library `davidmhunt/mmwave_radar_processing` (config manager + range, range-Doppler, range-angle processors), possibly after a `release/v2`-style upgrade? Compare (A) new module here, (B) adopt the library after a v2 upgrade, (C) port its config manager here now, upstream later. Scope: read-only static review of commit `4c6597d` (main, 103 commits, last 2026-05-20); nothing from the library was executed; the other repo was not modified.

## TL;DR

Recommend **(A)**: build gui-02 as proposed, in this repo, and keep the library as an *offline reference oracle* (a test that the two agree on resolution/max values for a few shipped cfgs, run only where the library is installed). The library's `ConfigManager` covers about 20% of gui-02: it parses six commands and computes four metrics for profile 0 on a TDM single-chip, with no generation, no validation, no bytes/frame, no cascade/DDMA, and no 1443/AWR2243 knowledge. A v2 upgrade of the library is real but separable work (about 2-4 days) that would not shorten gui-02; coupling gui-02 to it would put that work on the critical path. Its formulas are right for what they cover, so it is a good test oracle. For gui-07 the same conclusion holds (reimplement ~50 lines of FFT here).

## Evidence

**Packaging (confirms and extends the Planner's finding).** Library `pyproject.toml`: `requires-python >=3.10,<3.13`; hard deps `numpy>=1.25,<2`, `pytest>=7.4.4,<8`, `opencv-python>4.7,<4.9.0.80`, `open3d>=0.19,<0.20`, `pyqt6`, `pyqtgraph`, `pyopengl`, `jupyter`, `ipywidgets`, `plotly`, `pandas`, `scikit-learn`, `imageio[ffmpeg]`, `addict`, `poetry-dotenv-plugin`; Poetry build backend; a `poetry.lock`; `black<23` in the test group. This repo needs `python>=3.12`, `pytest>=9.1.1`, numpy 2.x (`pyproject.toml`). A plain `uv add git+...` is unresolvable (pytest and numpy conflicts). Positive: a grep for numpy-2-removed aliases (`np.float`, `np.int`, `np.complex`, `np.product`, ...) in the package found **0 hits**, and the core `config_managers/` and `processors/` import only numpy, scipy, stdlib (plus sklearn in `velocity_estimator.py` only; `logging/logger.py` is stdlib). So the code is probably numpy-2 clean; the pins are declarations, not need (HYPOTHESIS until a test run under numpy 2).

**Config manager (`config_managers/cfgManager.py`, 363 lines).**

| gui-02 need | Library state |
|---|---|
| Commands parsed | `channelCfg`, `adcCfg`, `adcbufCfg`, `profileCfg`, `chirpCfg`, `frameCfg` only. Not `lvdsStreamCfg`, `cfarCfg`, `guiMonitor`, etc. |
| Parsing robustness | `line.split(" ")` (breaks on tabs/double spaces); skips any line containing `%` anywhere; file handle never closed; no error reporting; hardware-trigger flag read from `params[6]` |
| Boards | None named. `array_geometry` is `"standard"` or `"ods"` (6843 ODS antenna layout); no 1443, no AWR2243, no board concept |
| Range res / bin / max | Present, formulas correct: $\Delta R = \frac{c\, f_s}{2 S N}$ (equals $c/2B$ with $B=SN/f_s$), $R_{max}=\frac{c f_s}{2S}$, bin size with padded power-of-two FFT. Matches TI's chirp-programming relations `ti_swra553` |
| Velocity res / max | Present, correct for **TDM-MIMO**: $\Delta v = \frac{\lambda}{2 T_c N_{tx} N_{loops}}$, $v_{max}=\frac{\lambda}{4 T_c N_{tx}}$ with $T_c$ = idle + rampEnd and $N_{tx}$ = chirp slots per loop. Wrong for cascade DDMA (all TX fire in one slot, so slot count is 1 and the velocity-sub-band split is ignored); uses `startFreq`, not center frequency (small) |
| Angular resolution | **Absent.** `_compute_angular_performance` only sets a boolean `virtual_antennas_enabled` |
| Frame period, duty cycle, ADC data rate, bytes/frame | Frame period stored raw; active time printed only in `print_cfg_overview`; no rate, no bytes/frame |
| Multi-profile / multi-chirp | Stores lists but all metrics use profile 0 |
| cfg generation | **None** (read-only) |
| Validation vs board/firmware limits | **None** (no limits table, no errors/warnings) |
| Cascade (12 Tx / 16 Rx virtual array, 4 chips) | **None**; `num_tx_antennas` is the popcount of the channel mask, one chip |
| Tests | `tests/` holds only manual `verify_*.py` scripts and one `test_*` file; no cfg-manager unit tests |

The library ships ~27 single-chip cfgs in `configs/` (1843, 6843, RadSAR...), useful as extra corpus.

**Processing modules (for gui-07, brief).** `RangeDopplerProcessor`, `RangeAngleProcessor`, `RangeProcessor` take a `ConfigManager` and an ADC cube shaped `(n_rx, n_samples, n_chirps)`; each `process()` is a few vectorized numpy calls (`np.hanning` broadcast windows, `np.fft.fft2`, `fftshift`, `np.abs`); no Python per-sample loops in these three. Per-frame cost is therefore FFT-bound (about a few ms for a 1843 frame: HYPOTHESIS, not measured). The cube layout differs from the driver's (`docs/ARCHITECTURE.md`), and dB scaling, clutter removal and decimation for WebSocket would be added here regardless, so the saving is the ~50 lines gui-07 already plans to write. The library's heavier processors (beamformer, velocity estimator with sklearn RANSAC, SAR, doppler-azimuth at 491 lines) are not gui-07 scope.

**What a "v2" of the library would need** (to be consumable by this repo; no work done):
1. Python `>=3.10` with `<3.13` removed (target 3.12-3.13); numpy `>=1.25` unpinned upper bound; run the suite under numpy 2.
2. Core dependencies reduced to `numpy`, `scipy`; everything else into extras: `viz` (matplotlib, plotly, imageio, opencv), `gui` (pyqt6, pyqtgraph, pyopengl), `pointcloud` (open3d, scikit-learn, pandas), `notebooks` (jupyter, ipywidgets), `dev` (pytest, black). Remove `poetry-dotenv-plugin`, `addict`, `tqdm` from core.
3. PEP 621 `[project]` only with a non-Poetry backend (hatchling/setuptools) so uv builds it; drop duplicated `[tool.poetry]` and the duplicate `imageio` pin; move `submodules/cpsl_datasets` to an optional group.
4. Relax test pins (`pytest>=8`, drop `black<23`), convert `tests/verify_*.py` into real pytest tests, add CI for 3.12/3.13.
5. Make `import mmwave_radar_processing` and `config_managers`/`processors` import-light (no open3d/Qt at import time; `visualization/` and `plotting/` behind extras).
6. For gui-02 specifically: new `cfg` parsing hardening (whitespace, comments, error list), board/cascade/DDMA model, angular resolution, frame/ADC rate/bytes metrics, a generator, and a limits table: this is the bulk and is the same work as gui-02 itself.
7. Tag (e.g. `v2.0.0`) on a `release/v2` branch; consumers use `mmwave-radar-processing = { git = "...", tag = "v2.0.0" }` under `[tool.uv.sources]`.
Rough size: items 1-5 about 2-3 days (mostly dependency triage and test conversion); item 6 is the gui-02 build (~2-3 days as scoped, light tier).

**Options compared.**

| | (A) new module here | (B) adopt after v2 | (C) port manager now, upstream later |
|---|---|---|---|
| Delay to gui-02 | none | blocks on v2 items 1-5 (2-3 d) | none, but ~360 lines ported then rewritten |
| Reuse value | cfggen.py solvers already here (299 lines, cascade DDMA) | metrics/parse only (~20%) | same as B, copied |
| Dependency risk | none | uv git pin plus two repos' release cadence; driver, not Python, becomes the limits authority (gui-04) so limits cannot live in the library | none |
| Drift risk | one metrics implementation (Python) plus the driver `--validate --json` parity test (gui-04) | one implementation, but in another repo | two implementations |
| Verdict | recommended | defensible later, not now | worst of both |

## Applicability to CPSL TI Radar

- gui-02 stays as written. The library's value here is as an **independent oracle**: add one optional test (skipped when the library is not importable) that computes range/velocity resolution and maxima via `ConfigManager` for the standard 1843 and 6843 TDM cfgs and compares to `radar_gui.cfg.metrics()` within 1e-6 relative. This catches a formula slip in either implementation at no dependency cost. (Install via a throwaway venv, not the project lock.)
- Limits belong to this repo and, after gui-04, to the C++ board descriptors in `CPSL_TI_Radar_cpp/config/boards/*.json`, the sole authority; the library has no equivalent and gui-04 deliberately makes the driver authoritative, which removes the main reason to centralize logic in the Python library.
- gui-07: the earlier plan (reimplement range/Doppler in numpy, library as an offline equivalence reference) is consistent with this review. Cube layout and dB/decimation make direct reuse awkward even after a v2.
- Upstreaming later (the reverse direction) is cheap: once `radar_gui/cfg/` is stable and has tests, it can be offered to the library's v2 as its new config manager, replacing the 363-line one. That is the right moment, not now.

## Recommended Experiment

Zero-hardware cross-check, 1 hour, only if the user wants to firm up the formula claim: in a throwaway venv (python 3.12, `numpy<2`, `scipy`), run `ConfigManager().load_cfg(<1843_RadVel_10Hz.cfg>)` and print `range_res_m`, `range_max_m`, `vel_res_m_s`, `vel_max_m_s`; compare against a hand calculation from the cfg's `profileCfg` and `frameCfg`. Separately, in a numpy-2 uv environment with the package's `config_managers/` and `processors/` directories, check that they import and `RangeDopplerProcessor.process` runs on a synthetic cube (validates the HYPOTHESIS that numpy 2 compatibility is a packaging issue only). Not required for the gui-02 decision.

## Confidence

**Medium-high (about 80%) for (A).** Settled by reading the code: feature coverage gap, correct-but-TDM-only formulas, dependency pins, absence of any generate/validate/cascade logic. Not settled: the library was not executed, so numpy-2 compatibility, per-frame timing and the formulas' numeric output are inferred from source, not measured; whether the user wants the library to grow into a general-purpose upstream for these cfg tools (a goal, not a technical question) could tip the choice to (B) later at modest cost.

## Sources

- `mmwave_radar_processing_repo` — Hunt, D. (2026), "mmwave_radar_processing (commit 4c6597d, main): pyproject.toml, config_managers/cfgManager.py, processors/range_doppler_resp.py, processors/range_angle_resp.py," *GitHub*. url:https://github.com/davidmhunt/mmwave_radar_processing
- `ti_swra553` — Texas Instruments (2017), "Programming Chirp Parameters in TI Radar Devices (SWRA553)," *TI application report*. url:https://www.ti.com/lit/pdf/swra553

Note for the Reviewer: this repo has no `docs/references/references.bib`; sources are repo-code citations by URL, as in prior memos. The TI formulas used (range resolution $c/2B$, max velocity $\lambda/4T_c$ per TX slot) are standard and were checked by derivation, not by re-fetching SWRA553.
