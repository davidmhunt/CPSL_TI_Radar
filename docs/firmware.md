# Firmware

Facts for TI mmWave firmware work in CPSL TI Radar. This file is the
Firmware role's source of project facts
(`.friday/active/harness/roles/firmware.md`): keep it current.

## Where things live

| Path | What | Repo / branch |
|------|------|---------------|
| `firmware_dev/` | Firmware sources, Docker build env, download/build/flash scripts | submodule `CPSL_TI_Radar_Firmware_Dev`, `release/v2.0`; opt-in (`update = none`) — fetch with `git submodule update --init --checkout firmware_dev` |
| `firmware_dev/projects/` | One self-contained firmware per folder (`README.md`, `project.toml`, `build.sh`, `flash.sh`, `src/`, `configs/`, `tools/`, `tests/`, `docs/`, `build/`), copied from `_template/`. **Start at [`firmware_dev/README.md`](../firmware_dev/README.md)** (5-step path and tutorials); verb/manifest reference: [`projects/README.md`](../firmware_dev/projects/README.md) | ″ |
| `firmware_dev/fw` | Bash entry point to `tools/fwcli/` (stdlib Python >= 3.11): `list`, `ports`, `new`, `deps`, `build`, `test`, `flash`, `verify`, `publish`, `help`, each with `--json` (JSON Lines, final `result`, exit codes per `docs/specs/fw_project_contract.md` App. A); runs compose as the host UID. Reads each project's `project.toml`. Own tests: `cd firmware_dev && uv run --group dev pytest tests -q` (fake compose/fuser/pty, no hardware) | ″ |
| `firmware_dev/tools/` | Cross-project code: `fwcli/` (the `fw` logic); `md_to_pdf.py` was removed in fwstd-07 and `cascade_serial_check.py` moved into `awr2243_cascade_ddm/tools/` in fwstd-06 | ″ |
| `firmware_dev/projects/awr2243_cascade_ddm/` | AM273x + AWR2243 2-chip cascade DDM demo (`src/` projectspecs + sources, `configs/` chirp cfgs, `docs/`, `prebuilt_binaries/` SBL images + demo.cfg) | ″ |
| `firmware_dev/projects/ti_stock_demos/` | Stock SDK 3.6 IWR1843/IWR6843 mmw demos, built out of tree (overlay in `build/sdk/`; no TI source tracked) | ″ |
| `firmware_dev/projects/iwr1843_sar_lvds/` | IWR1843 SAR/LVDS raw-ADC firmware from the SDK 3.6 `xwr18xx/mmw` demo (pristine baseline `bb3a348` in `firmware_dev`), built out of tree. Since firmware-07: MSS-only metaimage (DSS `NULL`, DSP halted), DSP chain/TLV/SW session removed, CBUFF HW session streams ADC per chirp, `sensorStop` -> `flushCfg` + cfg -> `sensorStart` without a power cycle (`channelCfg`/`adcCfg`/`lowPower` changes rejected), periodic runtime calibration off. Since firmware-08: `lvdsStreamCfg` dataFmt 2 = ADC + two 32-byte per-chirp metadata record slots (counters, RTI 100 MHz timestamp, lag-1 saturation), CLI `sarStats`, SDK CBUFF platform table compiled with `ENABLE_ALL_NON_INTERLEAVED`; format in its `docs/lvds_data_format.md`; see its README | ″ |
| `firmware_dev/downloads/` | TI installers, fetched by `download.sh` (~3.6 GB, gitignored) | ″ |
| `shipped_firmware/` | v1 prebuilt images keyed `<BOARD>/<firmware>/` (`IWR1443/demo/`, `IWR1443/dca1000_raw/iwr_raw_rosnode` submodule, `legacy/`); README lists board, descriptor, provenance; future home of published `firmware_dev` images | this repo |

## Toolchain (in the Docker image, under `/opt/ti/`)

| Tool | Version |
|------|---------|
| mmWave MCU+SDK (AM273x) | 04.04.00.01 (MCU+ SDK AM273x 08.05.00.24, mmWave DFP 02.04.08.01) |
| mmWave SDK (legacy) | 03.06.02.00-LTS |
| SysConfig | 1.22.0 |
| TI Arm Clang | 2.1.1.LTS (AM273x R5F / MSS) |
| TI C6000 | 8.3.12 (AM273x C66x / DSS) |
| TI ARM CGT | 20.2.7.LTS (installed but unused: the SDK 3.6 make flow uses its bundled 16.9.6.LTS + C6000 8.3.3) |
| Radar Toolbox | 4.00.00.05 (also supplies cascade prebuilt libraries) |
| Code Composer Studio | 12.8.1, headless only |

Cascade versions follow `firmware_dev/projects/awr2243_cascade_ddm/src/*.projectspec`.

## Commands (run from `firmware_dev/`)

One row per `fw` verb; arguments, flash modes and per-project details are in [`firmware_dev/README.md`](../firmware_dev/README.md), the tutorials and each project README. `./fw help` is the live summary.

| Verb | What it does |
|------|--------------|
| `./downloads/download.sh` · `docker compose build` | Once: fetch the TI installers (~3.6 GB, gitignored; includes UniFlash 9.6.0) and build image `cpsl-ti-radar-firmware-dev:latest` |
| `./fw list` · `./fw ports` | Projects (status, board, SDK, baseline, build state); candidate by-id serial ports and who holds them |
| `./fw new <p>` · `./fw deps [p]` | Copy `_template/`; check the installers a project needs |
| `./fw build <p> [--variant V] [--dry-run]` | Build in the container as the host UID to `projects/<p>/build/` with `build_info.json`; `CCS_CONFIG`/`FW_*` pass through; `FW_COMMIT` = short `firmware_dev` HEAD, `-dirty` if `git status --porcelain` is non-empty. |
| `./fw test [p]` | Hardware-free checks (manifest, descriptors, cfgs, `[test].commands`, `build --dry-run`) |
| `./fw flash <p> <by-id -if00 port> [image] [--dry-run \| --plan \| --confirm TOKEN]` | Gated flash: no process holds the port, typed `FLASH MODE CONFIRMED` on a TTY (a non-by-id port also needs `USE THIS PORT`; wrong phrase or no TTY exits 5; scripts use `--plan` then `--confirm`). Power-cycle before EVERY attempt. Exit 3 = no headless flasher, manual steps printed. Bench-confirmed projects and their jumper/power steps: project READMEs and `docs/bench_check.md` |
| `./fw verify <p> [--port P]` | Descriptor identify probes, never a cfg (the cascade only listens: `once_safe` false) |
| `./fw publish <p> [--dest D] [--dry-run]` | Clean builds only: images + provenance to `shipped_firmware/<BOARD>/<descriptor>/` |
| Bench host tool | `picocom` for the CLI port (`sudo apt install picocom`); no-install fallback `uv run python -m serial.tools.miniterm <by-id port> 115200` (Ctrl-] exits) |

## Boards (single-user: claim in `status.md` before use)

| Board | Reached via | Notes |
|-------|-------------|-------|
| AWR2243-2X-CAS-EVM (AM273x) | XDS110 USB (`0451:bef3`): CLI `/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000-if00`, data `…-if03` | USB only enumerates with 12 V on. J6 bottom two pins = UART flash mode, top two = QSPI run mode; change only with power off. CLI 115200, data 3,125,000 baud. |
| IWR1843 / IWR6843 / IWR1443 | serial (`/dev/ttyACM*`) + DCA1000 (UDP, FPGA `192.168.33.180`, host `192.168.33.30`) | SOP jumpers: flashing vs functional mode. |

## Quirks

- **One cfg per power-up.** The cascade demo accepts a chirp cfg only once
  after boot; power-cycle before every configured run.
- **New-board flash failures** may mean the QSPI Quad Enable bit is unset —
  see "Possible Flashing Issues" in the cascade user guide (rebuild
  `sbl_uart_uniflash` with "Quad Enable Type" = 6).
- Containers run fine as the host UID (`--user $(id -u):$(id -g)`, `HOME=/tmp/fwhome`):
  both the CCS headless cascade build and the SDK 3.6 make flow were verified unprivileged
  (firmware-01). The SDK 3.6 demo makefiles include everything via
  `$(MMWAVE_SDK_INSTALL_PATH)`, so a demo builds from a copy outside `/opt/ti`; TI's
  `setenv.sh` must be sourced from its own folder (it sources `./checkenv.sh`).
- The SDK 3.6 make flow uses the SDK-bundled `ti-cgt-arm_16.9.6.LTS` and
  `ti-cgt-c6000_8.3.3`, not the image's `ti-cgt-arm_20.2.7.LTS` (unused, kept); confirmed from the
  `ti_stock_demos` build log (firmware-03).
- Out-of-tree SDK 3.x builds (`ti_stock_demos`): `build.sh` overlays the SDK in `build/sdk/` (symlinks
  except the demo folder, which is copied) and sets `MMWAVE_SDK_INSTALL_PATH` after `setenv.sh`.
  The 68xx demo makefile has no `mmwDemo` target (use `all`). The `.bin` size depends on the build
  path (path strings in `.text`), so a rebuilt `.bin` matches TI's prebuilt in section layout, not
  byte for byte; two builds at the same path are byte-identical.
  `iwr1843_sar_lvds` (path 2 characters longer) gives the same 324804 B `.bin` and an identical MSS map
  layout; its DSS `.const.2` grows 4 B and the linker then places `.bss` before `.far`. At a path of the
  same length as `ti_stock_demos`, both maps match exactly and the project's `src/` and the SDK demo folder
  give byte-identical `.bin`s (firmware-04).
- Binaries embed the in-container build path (`/build_context/projects/<p>/build/...`), so build
  hashes compare only at the same project folder name. The pre-layout cascade build (29 Sep,
  427998 B, `9ff9d3cc…`) does not match the new layout (428030 B); not a regression (firmware-02).
- The submodule's `.git` points outside the bind mount, so `git` does not work inside the
  container; `fw` passes the commit in as `FW_COMMIT`.
- The `flash` compose service bind-mounts `/dev` so ports that
  re-enumerate after a power-cycle stay visible.

## Bench status (iwr1843_sar_lvds)

- Image sha256 `a06ee615b56b12282f2fe9b4a02bb556ceaa81a1b72176e2060cd9209a070924` (firmware-17, prompt `mm_sar_lvds:/>`) flashed 2026-10-10 via TTY `./fw flash`; `fw verify` pass; bench_check capture ACCEPTED (bench-confirmed). The earlier 53948f4d image below was the 2026-10-06 Set A / soak image.
- Verified at the bench: Set A + 10 min no-reflector soak, 299,880 chirps, 0 gaps, 0 missing, 6.66 MB/s.
- NOT yet verified (firmware-18, needs reflector + GUI): phase continuity, tuned gain/HPF point, boundary steps/Tb, ADC full scale, I/Q order, saturation-vs-gain.
- Tools (`./bench`, from `firmware_dev/`): long, restart, chan, finite, start0, adc, fmt4, fmt1, bsize, bytes, late, irq, tune, sat, soak, endurance, tb.

Driver support (core-22): the `IWR1843_SAR` board descriptor and `config/system/IWR1843_iwr1843_sar_lvds_SAR_2ms.json` capture this image in `lvdsStreamCfg` dataFmt 1; the image has no TLV/data UART. The driver also decodes `lvdsStreamCfg` dataFmt 2 (`adc_sar_meta`: per-chirp metadata, `SAR_2ms_fmt2.cfg`); bench-verified 2026-10-09 against `sar_parse.py` and in a 600 s live soak (see `docs/RESULTS.md`).

## Open v2.0 items

- Cascade TI binaries: `.gitignore` still has exceptions for `.aer5f`/`.ae66`/`.appimage`
  under `projects/awr2243_cascade_ddm/`, but none are tracked (the build takes the libraries
  from the Radar Toolbox); `prebuilt_binaries/` keeps TI's two SBL `.tiimage` files for
  `flash.sh`. Dropping/relicensing them is still open.
- `iwr1843_sar_lvds/src/mss/mmw_mss.cfg` (XDC config; the DSS one was removed in firmware-07) carries TI's old "Restricted rights" header;
  the SDK software manifest lists `packages\ti\demo` as BSD-3-Clause. Whether that suffices for a
  public release is the user's call. The `ti_stock_demos` `.cfg`/`.pl` copies have no header (also BSD per the manifest).
- Shipped-firmware directory + publish script with a provenance manifest.
- Licensing check on any TI binaries shipped publicly (user decision).
