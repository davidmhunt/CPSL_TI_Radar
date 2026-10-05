# AWR2243 2-Chip Cascade: Demo Bring-up + C++ Serial Integration Plan

**Goal:** (1) build and flash the stock AM273x + AWR2243 cascade DDM demo from Docker, and
(2) stream its UART TLV point cloud into the `CPSL_TI_Radar` C++ driver.
Raw ADC capture over the DCA1000 is out of scope here (see "Later").

Repos:
- `CPSL_TI_Radar_Firmware_Dev/` — firmware source, Docker build env, flashing
- `CPSL_TI_Radar/CPSL_TI_Radar_cpp/` — C++ driver (`CLIController`, `SerialStreamer`, `Runner`)

## Branches

All work happens off `main` so the working IWR1843/IWR6843 setups stay untouched:

| Repo | Branch | Covers |
|---|---|---|
| `CPSL_TI_Radar_Firmware_Dev` | `cascade-demo-bringup` | Phases 1–2 (download/build scripts, Dockerfile, flashing) |
| `CPSL_TI_Radar` | `cascade-serial-integration` | Phases 3–4 (C++ driver changes, configs, docs) |

Both are local-only for now (`git push -u origin <branch>` when ready). Merge to `main` via PR only
after the phase's "Done when" criteria pass; for the driver, also re-run an existing IWR1843 config to
confirm no regressions. Custom firmware work later should branch from `cascade-demo-bringup` once the
stock baseline builds and flashes.

---

## Status (updated 2026-10-01 — Phase 1 complete; Phase 2–4 software done; TI prebuilt streams on the real EVM)

| Item | State |
|---|---|
| Both repos cloned, `CPSL_TI_Radar` submodules initialized | ✅ |
| Git LFS installed, firmware repo PDFs pulled | ✅ |
| Docker 29.8.1 + Compose, `cpsl` in `docker` group, `hello-world` passes | ✅ |
| C++ driver builds natively (`CPSL_TI_Radar_CPP`) | ✅ |
| Feature branches created (`cascade-demo-bringup`, `cascade-serial-integration`) | ✅ |
| Cascade demo source committed (`firmware/cascade/src/demo/src/awr2243/ti/`) | ✅ |
| `.gitignore` tracks `downloads/download.sh` (`40fdb42`) | ✅ |
| Versions aligned to projectspec in `download.sh`, Dockerfile, compose, build script, README, guide (uncommitted on `cascade-demo-bringup`) | ✅ 1.1 |
| Prebuilt libs: build script pulls all 7 from the installed Radar Toolbox (repo copies win); `.gitignore` allows committing them | ✅ 1.2 |
| Headless CCS 12.8.1 projectspec build (Dockerfile + `build_mcuplus_ddm.sh`; uncommitted on `cascade-demo-bringup`) | ✅ 1.3 |
| All 8 installers incl. Radar Toolbox + CCS downloaded and size-verified; toolbox zip integrity OK, contains all 7 cascade libs + TI prebuilt appimage | ✅ |
| `docker compose build` — image `cpsl-ti-radar-firmware-dev` (4.9 GB content, 18.3 GB on disk) | ✅ |
| Cascade DDM demo builds headless: 0 errors DSS + MSS; `am273x_cascade.appimage` 427,998 B vs TI prebuilt 427,974 B | ✅ 1.6 |
| `scripts/flash_cascade.sh <port> [appimage\|prebuilt]` — stages a temp cfg; checked in-container up to the serial open (no board) | ✅ 2.1 |
| `flash` compose service: `/dev` bind + cgroup rules for ttyUSB (188) / ttyACM (166), `dialout` | ✅ 2.2 |
| `scripts/cascade_serial_check.py` (cfg → `Done` check, TLV frame/gap/rate check) — tested on a pty with synthetic frames | ✅ 2.4 |
| C++ driver Phase 3 items 1–9 (uncommitted on `cascade-serial-integration`) — tested against a simulated board on ptys | ✅ |
| READMEs updated (both repos) | ✅ |
| EVM enumerates on USB (needs 12 V on; XDS110 `0451:bef3`): CLI `ttyACM0` (`…-if00`), data `ttyACM1` (`…-if03`); both open from the `flash` container | ✅ |
| 2.3 TI prebuilt `am273x_mmw_cascade_demo_DDM.appimage` flashed over `ttyACM0` (all 3 uniflash commands OK, ~70 s total at ~11 KB/s) | ✅ |
| `flash_cascade.sh` runs a patched temp copy of `uart_uniflash.py` that flushes serial input before each XMODEM send (first attempt aborted in <1 s with `expected ACK; got b'C'`) | ✅ |
| `radar_0_AWR2243_cascade_serial.json` points at the XDS110 by-id paths (`-if00` CLI, `-if03` data) | ✅ |
| 2.4 on hardware with TI prebuilt: `cascade_shortrange.cfg` accepted, 200 frames at 20.03 Hz, 0 frame-number gaps, 0 framing errors at 3.125 Mbaud over the XDS110 | ✅ |
| **TLV mismatch:** `cascade_shortrange.cfg` has `guiMonitor -1 3 …` (detectedObjects = 3), so frames carry type **12** (radial compact point cloud, 8 B/pt: quantized az/el sin-phase, range idx, Doppler idx) + type **11** (RANSAC mask, 1 B/pt) and **no type 1/7**. The C++ driver only parses 1/7, so it would print no points. **Fixed 2026-10-01:** the driver's copy `config/radar/cascade/cascade_shortrange.cfg` now has `guiMonitor -1 1 …` → types 1 (16 B/pt) + 7 (4 B/pt) + 11 (RANSAC mask, skipped by the driver). Rechecked on hardware: 35/35 `Done`, 200 frames at 20.03 Hz, 0 gaps, 0 framing errors, ~57 pts/frame. The firmware repo's cfg keeps TI's `3` | ✅ |
| C++ driver on hardware, first try: the cascade CLI dropped the leading characters of every few commands (`'eDataOutputMode' is not recognized`), because `CLIController` sent the next command the moment `Done` arrived while the board was still printing `mmwDemo:/>`. Fixed: `sendCommand` now waits up to 500 ms for the prompt after `Done` (`read_until_with_timeout` helper). The Python check only avoided this through its 0.1 s read timeout | ✅ |
| C++ driver on hardware (TI prebuilt firmware), 75 s run: all cfg lines `Done`, 1479 frames (≈20 Hz), 0 frame-number gaps, no timeouts, 28–101 points/frame (avg 59), clean `sensorStop` on Ctrl+C | ✅ |
| Our `am273x_cascade.appimage` (427,998 B, built 2026-09-29, no firmware source changed since) flashed: all 3 uniflash commands OK | ✅ |
| Our build, `cascade_serial_check.py` with the driver's cfg (`guiMonitor -1 1`): 35/35 `Done`, 200 frames at 20.02 Hz, 0 gaps, 0 framing errors, 50–74 pts/frame (avg 59): matches TI prebuilt | ✅ |
| **Remaining on hardware:** C++ driver on our build, multi-minute driver soak, Phase 4 checks | ⏳ |
| Commit the Phase 1–4 work on both feature branches | ⏳ |

### Required toolchain (source of truth: `mmwave2chipCascade_{mss,dss}.projectspec`)

| Component | projectspec needs | Repo currently uses | Where the mismatch is |
|---|---|---|---|
| mmWave MCU+ SDK | **4.4.0.01** | ✅ fixed | — |
| MCU+ SDK AM273x | **8.5.0.24** | 08_05_00_24 | ✅ (bundled with mmWave MCU+ SDK, verify) |
| SysConfig | **1.22.0** | ✅ fixed (TI `.syscfg` files were authored with 1.14.0; 1.22 should open them) | — |
| TI ARM Clang (R5F/MSS) | **2.1.1.LTS** | ✅ fixed | — |
| TI C6000 CGT (C66x/DSS) | **8.3.12** | ✅ fixed — now downloaded/installed separately | — |
| mmWave DFP | **02_04_08_01** | ✅ fixed (expected bundled with SDK — verify) | — |
| TI ARM CGT 20.2.7 / mmWave SDK 3.6 | not used by cascade | installed for legacy demos | fine — keep for `build_legacy.sh` |

---

## Phase 1 — Build the stock demo in Docker

1. **Align versions to the projectspec table above** in `download.sh`, Dockerfile, README, and
   `scripts/build_mcuplus_ddm.sh`. After building the image, `ls /opt/ti` to confirm which components
   (AM273x MCU+ SDK, DFP, C6000 CGT, DSPLIB/MATHLIB, xdctools) the mmWave MCU+ SDK 4.4.0.01 installer
   bundles; add separate installers only for what's missing.
2. ✅ **Done — provide the prebuilt libraries.** The projectspecs copy **7** prebuilt libs from
   the source tree that exist only in the Radar Toolbox (`*.aer5f`/`*.ae66`, ignored by default):
   - `ti/utils/cli/lib/libcli_cascade_am273x.aer5f` — **no CLI source is in the repo at all**
   - `ti/control/mmwave/lib/libmmwave_cascade_am273x.aer5f`
   - `ti/control/mmwavelink/lib/libmmwavelink_cascade_am273x.aer5f`
   - `ti/control/dpm/lib/libdpm_am273x.aer5f` and `libdpm_am273x.ae66`
   - `ti/datapath/dpu/rangeprocDDMA/lib/librangeproc_hwa_ddma_cascade_am273x.ae66`
   - `ti/datapath/dpu/dopplerprocDDMA/lib/libdopplerproc_hwa_ddma_cascade_am273x.ae66`

   `build_mcuplus_ddm.sh` stages the source and fills any missing lib from the installed toolbox
   (`*/mmwave_2_chip_cascade/src/awr2243/`); a copy committed in the repo takes precedence (for libs you
   rebuild later via the `*lib.mak` files). `.gitignore` allows `ti/**/lib/*.aer5f|*.ae66` in that tree.
3. ✅ **Done — headless CCS projectspec build** replaces the SDK `make mmwDemoDDM` (which
   built the SDK's stock demo, not the cascade projects):
   - **Image:** CCS 12.8.1 (`PF_MMWAVE,PF_SITARA_MCU`; override with `--build-arg CCS_COMPONENTS=PF_ALL`)
     + the libraries CCS 12 needs that Ubuntu 24.04 dropped (libtinfo5, libgconf-2-4, libpython2.7).
     Installers are now bind-mounted (not `COPY`'d) and each tool has its own layer, so the ~4 GB of
     installers never land in the image and a failed step only re-runs itself.
   - **Build script:** stage source → fill libs → patch Windows-only pre/post-build steps
     (`utils/cygwin/rm` → `rm`, `nodejs/node.exe` → `nodejs/node`) → register products with
     `com.ti.common.core.initialize` → `projectImport` both specs → `projectBuild` DSS then MSS →
     verify `.xe66`, `.xer5f`, `.appimage` exist → copy to `build/cascade/`. Workspace + logs kept in
     `build/cascade/ccs_workspace/`. `CCS_CONFIG=Debug` for debug builds.
   - Reference used for CCS-in-Docker on 24.04: github.com/zfb132/ccstudio.
4. ✅ **Done — `.gitignore` hardening** (no files are lost today — verified every file referenced by the
   committed `*.mak` files is present — but these patterns are unanchored and will bite later):
   - `ti/`, `bin/`, `build/` match at *any* depth → anchor as `/ti/`, `/bin/`, `/build/`, `/sdks/` and drop
     the `!firmware/.../ti/` negation.
   - `*.appimage` also blocks `prebuilt_binaries/am273x_mmw_cascade_demo_DDM.appimage` (the TI prebuilt
     `demo.cfg` flashes) — add an exception if you want it versioned (or via LFS), else pull it from the zip.
5. ✅ **Done (cascade build script) — make scripts path-agnostic:** replace hard-coded `/opt/ti` with `${TI_ROOT:-/opt/ti}` so the same
   scripts also work natively (`TI_ROOT=~/ti`).
6. ✅ **Done — build:** `docker compose build` → `docker compose run --rm firmware-env /build_context/build_cascade.sh`
   (~2.5 min). Outputs: `build/cascade/am273x_cascade.appimage`, `am273x_cascade.elf`, `am273x_cascade_dss.xe66`.
   Our appimage is within 24 bytes of TI's prebuilt one (embedded paths/timestamps), a good sign it's equivalent.
   Installed layout (flat under `/opt/ti`): mmWave MCU+ SDK 04.04.00.01 also brings MCU+ SDK AM273x 08.05.00.24,
   DFP 02.04.08.01, DSPLIB/MATHLIB, xdctools, and its own SysConfig 1.14.0 + C6000 8.3.3 (unused by the projectspecs).

**Done when:** a clean `.appimage` is produced from a fresh container using the committed sources + libs.

## Phase 2 — Flash + bring-up (no C++ yet)

> **Shortcut:** the Radar Toolbox zip ships TI's prebuilt `am273x_mmw_cascade_demo_DDM.appimage`
> (the only file `prebuilt_binaries/demo.cfg` references that isn't in the repo — `*.appimage` is
> gitignored). Flashing that first validates the EVM, cabling, and ports **before** our own build
> works, and lets Phase 3 start in parallel with Phase 1.

1. **Write `scripts/flash_cascade.sh <port> [appimage]`** wrapping the MCU+ SDK UART uniflash tool —
   the TI guide's command is `python {MCU_PLUS_SDK}/tools/boot/uart_uniflash.py -p <port> --cfg=demo.cfg`,
   run from `prebuilt_binaries/`. `demo.cfg` flashes:
   - flash writer: `sbl_uart_uniflash.release.tiimage`
   - `sbl_qspi.release.tiimage` @ `0x0`
   - `am273x_mmw_cascade_demo_DDM.appimage` @ `0xA0000`

   The script should generate a temp cfg pointing at either TI's prebuilt appimage or our
   `build/cascade/am273x_cascade.appimage`. `pyserial`, `xmodem`, `tqdm` are already in the image.
2. **Serial passthrough in compose:** add a `flash` service (or extend `firmware-env`) with
   `devices: [...]` (or `/dev:/dev` + `group_add: [dialout]`). Identify ports with
   `ls -l /dev/serial/by-id/` once plugged in; the TI guide flashes over the **Application/User UART**
   port and uses a separate **data** port for TLV output.
3. **Flash** (per TI user guide):
   - **J6 jumper on the bottom two pins** → UART boot (flash mode); connect micro-USB, then 12 V (>2 A, 2.1 mm center-positive).
   - Run the flash script; success prints `All commands from config file are executed !!!`.
   - **Move J6 to the top two pins** → QSPI boot (run mode); power-cycle.
   - If flashing fails on a new board, the flash's Quad Enable bit may be unset — TI's fix is rebuilding
     `sbl_uart_uniflash` with "Quad Enable Type" = 6 (see user guide "Possible Flashing Issues").
4. **Sanity check before touching C++:** TI's visualizer is Windows `.exe`/MATLAB only, so use a small
   Python script: send `chirp_configs/cascade_shortrange.cfg` over the CLI port (115200), confirm each
   line returns `Done`, then confirm frames starting with the magic word `02 01 04 03 06 05 08 07`
   arrive on the data port (**3,125,000 baud**).

**Done when:** the demo (TI prebuilt first, then ours) streams TLV frames after the cfg is sent.

> **Status 2026-10-01:** 2.1, 2.2, and 2.4 (the script) are done. The EVM is connected (CLI `/dev/ttyACM0`, data `/dev/ttyACM1`; 12 V must be on for USB to enumerate) TI's prebuilt demo is flashed (2.3), and 2.4 passes on hardware (20.03 Hz, 0 gaps, 0 framing errors). The 3.125 Mbaud open question is answered: the XDS110 handles it.
> Usage is in the firmware README ("Headless Flashing Instructions"). `uart_uniflash.py` exits 0 on most
> failures, so the flash script checks for the success line instead.

## Phase 3 — Integrate serial streaming into the C++ driver

Scope: control over CLI UART + TLV point cloud over data UART. The driver's TLV framing
(40-byte header, same magic word, 8-byte TLV header, type 1 = x/y/z/velocity floats) already
matches the cascade demo, so this is mostly configuration + a few extensions.

| # | Change | Where |
|---|---|---|
| 1 | Add `board_type` `"AWR2243_CASCADE"` (accept in validation; keep existing boards unchanged) | `utilities/SystemConfigReader.cpp` (~L393) |
| 2 | **Configurable data-port baud** — currently hard-coded `921600`; cascade uses `3125000`. Add optional `Streamer.serial_streaming.baud_rate` in JSON (default 921600). | `SerialStreamer/SerialStreamer.cpp` (~L163) |
| 3 | **Non-standard baud support:** 3,125,000 isn't a standard termios `Bxxx` rate, so `boost::asio` `baud_rate` will likely reject it. Set it via `termios2`/`BOTHER` (`ioctl(TCSETS2)`) on the native handle. Verify the host USB-UART bridge supports 3.125 Mbaud. | `SerialStreamer.cpp` |
| 4 | CLI: baud 115200 and `Done` response already match. Verify long `antennaCalibParams*` lines and `%` comments (already skipped) behave; bump read timeout if calibration commands are slow. Allow CLI baud to be configurable too. | `CLIController/CLIController.cpp` |
| 5 | Radar cfg parsing: cascade `channelCfg` has 5 fields (`15 7 1 15 7`). In serial-only mode ensure `RadarConfigReader` doesn't fail/mis-size; parse Rx count as 4 per chip × 2 chips = 8 for cascade. | `utilities/RadarConfigReader.cpp` |
| 6 | TLV parsing: keep type 1 (detected points). Add type 7 (side info: SNR/noise int16) and optionally type 10 (tracker) / 104 (compact point cloud); unknown types are already skipped via `default`. | `SerialStreamer/SerialStreamer.cpp` (~L491), `TLVProcessing.*` |
| 7 | **No live reconfiguration:** TI lists "stop + send new config" as unsupported — the board must be power-cycled between configs. Driver should send the cfg once per boot and not rely on `sensorStop` → reconfigure; document this. | `CLIController`, `Runner` |
| 8 | Serial-only operation: confirm `Runner` works with `DCA1000_streaming.enabled = false` and doesn't touch DCA1000 code paths for the new board type (`DCA1000Handler::send_configFPGAGen` rejects unknown boards). | `Runners/Runner.cpp` |
| 9 | Add configs: `config/radar/cascade/cascade_shortrange.cfg` (copied from firmware repo) and `config/system/radar_0_AWR2243_cascade_serial.json` (serial on, DCA off, `board_type: AWR2243_CASCADE`, `/dev/serial/by-id/...` ports). | `config/` |

> **Status 2026-10-01 — all 9 items implemented:**
> 1. `AWR2243_CASCADE` accepted. Cascade + DCA1000 is rejected at config load (covers 8).
> 2–3. `serial_streaming.baud_rate` (default 921600) via `utilities/SerialBaud.*`: boost first, then `termios2`/`BOTHER`
>    with read-back. Boost 1.83 rejects 3125000. Also `serial_streaming.timeout_ms` (default 1000). The cascade JSON uses 5000,
>    so a slow `sensorStart` doesn't kill the serial thread.
> 4. `CLI_Controller.baud_rate` / `cmd_timeout_ms`. **Fixed a pre-existing bug:** the timeout timer was never cancelled
>    when `Done` arrived, so every command took the full timeout. CRLF/trailing whitespace is stripped. `sendCommand` now returns success.
> 5. `channelCfg` Rx count = master + slave mask (8). The cascade `frameCfg` period is field 6 (`numAdcSamples` is inserted).
>    Tokenizer now splits on any whitespace. Old and new parsers give identical results for all 72 existing cfgs.
> 6. TLV 7 parsed (`TLVDetectedPointsSideInfo`, dB). Points and side info are cleared every frame (previously a frame with no
>    detections kept returning the previous frame's points). TLV bounds checks added. Frame-number gap counter added.
> 7. The cascade fails init with a power-cycle message if any cfg command isn't acknowledged. `stop()` prints a reminder.
> 9. `config/radar/cascade/cascade_shortrange.cfg` + `config/system/radar_0_AWR2243_cascade_serial.json` (ports are
>    XDS110 by-id paths `…_00000000-if00` / `-if03` as of 2026-10-01).
>
> `main.cpp`: a frame with zero points no longer ends the run (new `bool get_next_tlv_detected_points(points&, timeout)`).
> Per-frame summary printing added. Non-zero exit if init fails. Simulated-board runs on ptys (cascade 3.125 Mbaud, IWR1843 921600):
> frames, 0-point frames, a dropped frame, slow `sensorStart`, and rejected-cfg all behave as expected.
> Known limitation (all boards): a frame is delivered only when the next magic word arrives, so the newest frame is one period old,
> and the final frame before a stop is dropped.

**Done when:** `CPSL_TI_Radar_CPP` configures the cascade from the JSON, starts the sensor, and
prints detected points each frame with no framing/timeout errors over a multi-minute run.

## Phase 4 — Validation

- Frame rate matches `frameCfg` period (e.g. 50 ms → 20 Hz); `frameNumber` increments with no gaps.
- Point positions sane against a corner reflector / known target.
- Clean shutdown via `sensorStop`; restart requires a power-cycle (TI known issue) — confirm the driver fails clearly, not silently, if the board was already configured.
- ✅ Update `CPSL_TI_Radar/README.md` supported-boards table and `CPSL_TI_Radar_cpp/Readme.md`.
- The driver reports frame-number gaps (`SerialStreamer: frame number jumped ...`) and prints `Received N frames, M missed`
  on exit. The per-frame `TLV frame <n>: <k> detected points` lines give the rate. The remaining checks need the EVM.

## Later (out of scope)

- Raw ADC via DCA1000: 4-lane LVDS FPGA config, new `ADCCubeConverter` layout
  (master Rx0–3 block then slave Rx4–7 block per chirp; see `cascade_demo_guide.md` §7), DDM virtual-channel mapping.
- Custom firmware changes on top of the stock-demo baseline.

## Open questions / risks

- ~~Untested headless-CCS assumptions~~ — all verified by the first successful build.
- Build outputs written from the container are owned by root on the host (compose runs as root).
- `Runner::stop()` runs twice (explicit call + destructor), so `sensorStop` is sent twice. This is pre-existing and harmless, but noisy.

- **Chirp limits (TI known issue):** only tested up to 192 ADC samples, 256 chirps, 8 Rx channels; BFP compression unsupported.
- **Calibration:** `antennaCalibParams1-3` in the cfgs are TI's defaults; per-board calibration needs a corner reflector at 3 m + the `cascade_shortrange_calib.cfg` flow (TI's tool is MATLAB — could be ported to Python later).

- Which toolchain components does the mmWave MCU+ SDK 4.4.0.01 installer bundle vs. need separate installers (Phase 1.1)?
- Is the 4.4.0.01 installer still on TI's direct-download server, or only via the archive page?
- ~~Does the EVM's USB-UART bridge + Linux driver accept 3.125 Mbaud? If not, lower the data UART rate
  in firmware (`mss.syscfg` `uart1.baudRate`) or via the demo's baud-rate CLI command.~~ **Resolved 2026-10-01:** yes, 0 framing errors over 200 frames.
- ~~Exact `/dev/ttyUSB*` / `/dev/ttyACM*` enumeration of the EVM ports~~ **Resolved 2026-10-01:** on-board XDS110
  (`0451:bef3`, cdc_acm). It only enumerates with 12 V applied. `if00` → `/dev/ttyACM0` (Application/User UART,
  CLI), `if03` → `/dev/ttyACM1` (Auxiliary Data Port). by-id:
  `/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.29__Embed_with_CMSIS-DAP_00000000-if0{0,3}`.
  The XDS110 reports serial `00000000`, so by-id paths would collide if two of these EVMs were plugged in at once.
  Device nodes are `root:plugdev`; `cpsl` is in `plugdev`, and the `flash` container runs as root.
