# Firmware

Facts for TI mmWave firmware work in CPSL TI Radar. This file is the
Firmware role's source of project facts
(`.friday/active/harness/roles/firmware.md`): keep it current.

## Where things live

| Path | What | Repo / branch |
|------|------|---------------|
| `firmware_dev/` | Firmware sources, Docker build env, download/build/flash scripts | submodule `CPSL_TI_Radar_Firmware_Dev`, `release/v2.0`; opt-in (`update = none`) — fetch with `git submodule update --init --checkout firmware_dev` |
| `firmware_dev/projects/` | One self-contained firmware per folder (`README.md`, `project.env`, `build.sh`, `flash.sh`, `src/`, `configs/`, `tools/`, `docs/`, `build/`), copied from `_template/`. **Usage guide: [`firmware_dev/projects/README.md`](../firmware_dev/projects/README.md)** | ″ |
| `firmware_dev/fw` | Dispatcher: `list`, `new <p>`, `build <p>`, `flash <p> <port> [image]`, `help`; runs compose as the host UID, so `projects/*/build/` is user-owned | ″ |
| `firmware_dev/tools/` | Cross-project scripts (`cascade_serial_check.py`, `md_to_pdf.py`) | ″ |
| `firmware_dev/projects/awr2243_cascade_ddm/` | AM273x + AWR2243 2-chip cascade DDM demo (`src/` projectspecs + sources, `configs/` chirp cfgs, `docs/`, `prebuilt_binaries/` SBL images + demo.cfg) | ″ |
| `firmware_dev/projects/ti_stock_demos/` | Stock SDK 3.6 IWR1843/IWR6843 mmw demos, built out of tree (overlay in `build/sdk/`; no TI source tracked) | ″ |
| `firmware_dev/downloads/` | TI installers, fetched by `download.sh` (~3.6 GB, gitignored) | ″ |
| `firmware_dev/build/{cascade,legacy}/` | Old-flow build outputs (gitignored; root-owned from pre-`fw` container runs; the cascade baseline is no longer needed, firmware-05 removes the folder with `docker compose run --rm firmware-env rm -rf /build_context/build`) | ″ |
| `Firmware/` | v1 prebuilt images (`IWR_Demos/`, `DCA1000_Streaming/`) | this repo — to be reorganized into the v2.0 shipped-firmware directory |

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

| Task | Command |
|------|---------|
| List / create projects | `./fw list` · `./fw new <project>` (guide: `projects/README.md`) |
| Build a project | `./fw build <project>` → `projects/<project>/build/` (`CCS_CONFIG`, `FW_*` passed through; build.sh gets the commit as `FW_COMMIT`) |
| Flash a project | `./fw flash <project> <port> [image]` — `flash.sh` exits 0 flashed, 1 failed, 2 bad args, 3 manual steps printed (no headless flasher) |
| Fetch installers | `./downloads/download.sh` |
| Build image | `docker compose build` (image `cpsl-ti-radar-firmware-dev:latest`) |
| Build cascade | `./fw build awr2243_cascade_ddm` → `projects/awr2243_cascade_ddm/build/am273x_cascade.appimage` (`CCS_CONFIG=Debug` for debug) |
| Build SDK 3.6 stock demos | `./fw build ti_stock_demos [18xx\|68xx]` → `projects/ti_stock_demos/build/iwr{1843,6843}_demo.{bin,elf}` |
| Flash cascade | `./fw flash awr2243_cascade_ddm <CLI port> [image\|prebuilt]` — success only on `All commands from config file are executed !!!` |
| Bring-up check | `docker compose run --rm flash python3 /build_context/tools/cascade_serial_check.py --cli <CLI> --data <DATA> --cfg <cfg>` (`--skip-config` to only listen) |
| Python helpers | `uv run python tools/md_to_pdf.py <file.md>` |

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
- The submodule's `.git` points outside the bind mount, so `git` does not work inside the
  container; `fw` passes the commit in as `FW_COMMIT`.
- The `flash` compose service bind-mounts `/dev` so ports that
  re-enumerate after a power-cycle stay visible.

## Open v2.0 items

- Cascade TI binaries: `.gitignore` still has exceptions for `.aer5f`/`.ae66`/`.appimage`
  under `projects/awr2243_cascade_ddm/`, but none are tracked (the build takes the libraries
  from the Radar Toolbox); `prebuilt_binaries/` keeps TI's two SBL `.tiimage` files for
  `flash.sh`. Dropping/relicensing them is still open.
- Shipped-firmware directory + publish script with a provenance manifest.
- Licensing check on any TI binaries shipped publicly (user decision).
