# Firmware

Facts for TI mmWave firmware work in CPSL TI Radar. This file is the
Firmware role's source of project facts
(`.friday/active/harness/roles/firmware.md`): keep it current.

## Where things live

| Path | What | Repo / branch |
|------|------|---------------|
| `firmware_dev/` | Firmware sources, Docker build env, download/build/flash scripts | submodule `CPSL_TI_Radar_Firmware_Dev`, `release/v2.0`; opt-in (`update = none`) — fetch with `git submodule update --init --checkout firmware_dev` |
| `firmware_dev/firmware/cascade/src/demo/` | AM273x + AWR2243 2-chip cascade DDM demo (projectspecs, chirp configs, TI docs) | ″ |
| `firmware_dev/firmware/legacy/src/` | Single-chip mmWave SDK 3.x demos (IWR1843/IWR6843) | ″ |
| `firmware_dev/downloads/` | TI installers, fetched by `download.sh` (~3.6 GB, gitignored) | ″ |
| `firmware_dev/build/{cascade,legacy}/` | Build outputs (gitignored) | ″ |
| `Firmware/` | v1 prebuilt images (`IWR_Demos/`, `DCA1000_Streaming/`) | this repo — to be reorganized into the v2.0 shipped-firmware directory |

## Toolchain (in the Docker image, under `/opt/ti/`)

| Tool | Version |
|------|---------|
| mmWave MCU+SDK (AM273x) | 04.04.00.01 (MCU+ SDK AM273x 08.05.00.24, mmWave DFP 02.04.08.01) |
| mmWave SDK (legacy) | 03.06.02.00-LTS |
| SysConfig | 1.22.0 |
| TI Arm Clang | 2.1.1.LTS (AM273x R5F / MSS) |
| TI C6000 | 8.3.12 (AM273x C66x / DSS) |
| TI ARM CGT | 20.2.7.LTS (legacy single-chip) |
| Radar Toolbox | 4.00.00.05 (also supplies cascade prebuilt libraries) |
| Code Composer Studio | 12.8.1, headless only |

Cascade versions follow `firmware/cascade/src/demo/src/awr2243/*.projectspec`.

## Commands (run from `firmware_dev/`)

| Task | Command |
|------|---------|
| Fetch installers | `./downloads/download.sh` |
| Build image | `docker compose build` (image `cpsl-ti-radar-firmware-dev:latest`) |
| Build cascade | `docker compose run --rm firmware-env /build_context/build_cascade.sh` (`CCS_CONFIG=Debug` for debug) |
| Build legacy | `docker compose run --rm firmware-env /build_context/build_legacy.sh` |
| Flash cascade | `docker compose run --rm flash /build_context/scripts/flash_cascade.sh <CLI port> [prebuilt]` — success only on `All commands from config file are executed !!!` |
| Bring-up check | `docker compose run --rm flash python3 /build_context/scripts/cascade_serial_check.py --cli <CLI> --data <DATA> --cfg <cfg>` (`--skip-config` to only listen) |
| Python helpers | `uv run python scripts/md_to_pdf.py <file.md>` |

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
- The `flash` compose service bind-mounts `/dev` so ports that
  re-enumerate after a power-cycle stay visible.

## Open v2.0 items

- `firmware_dev` still tracks TI prebuilt `.aer5f`/`.ae66` libraries and a
  TI prebuilt `.appimage`; the build falls back to the Radar Toolbox copy,
  so these are candidates to drop (confirm libcli first).
- Shipped-firmware directory + publish script with a provenance manifest.
- Licensing check on any TI binaries shipped publicly (user decision).
