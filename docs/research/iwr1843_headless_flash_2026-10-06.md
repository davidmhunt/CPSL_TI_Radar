# Can the IWR1843 be flashed headless (UniFlash CLI / dslite / other tool)?

**Date:** 2026-10-06
**Memo:** docs/research/iwr1843_headless_flash_2026-10-06.md

## Question as asked

Directive firmware-13: how to flash `iwr1843_sar_lvds.bin` (SDK 3.6 meta image, 152132 B) to the
IWR1843BOOST QSPI from a headless Linux host over the XDS110 UART port, or whether it cannot be done
without the GUI. Covers UniFlash version and Linux install, the exact CLI, other routes, display need,
and risks. No hardware touched, nothing installed; the host and the firmware Docker image were inspected
read-only. User feedback: UniFlash may already be on this host; installing it is acceptable.

## TL;DR

UniFlash is **not installed** on this host. TI's UniFlash ships a command-line flasher (`dslite.sh`) whose
xWR18xx serial target flashes a `.bin` as `META_IMAGE1` over the UART port, with no GUI step (a logged
AWR1843 run exists, Windows, UniFlash 5.1). So a headless flash is very likely possible: install UniFlash
9.6.0 (free direct `.run`, 365 MiB, no login), hand-write the ccxml, run `dslite.sh flash`. Two points
are unproven here: the exact 9.6 argument spelling, and whether the Linux install itself needs a display.
Fallbacks that need no install on this host: generate a CLI package on any GUI machine, or flash on that machine.
The repo's earlier "no xWR18xx serial target" claim is true of the CCS 12.8.1 DSLite in the Docker image
only, not of UniFlash.

## Evidence

### 1. Host state (read-only, 2026-10-06)

- No `uniflash`/`dslite` on `PATH`; no `~/ti`, `/opt/ti`, `~/.ti`, `/usr/local/ti` on the host; a
  filesystem search found only SDK 2.1 test logs. Only CCS and SDK installers are in
  `firmware_dev/downloads/`. A full TI toolchain (CCS 12.8.1, SDK 3.6.02.00) exists **inside** image
  `cpsl-ti-radar-firmware-dev:latest` under `/opt/ti`.
- User `cpsl` is in `dialout` and `plugdev`; `/dev/ttyACM0,1` are `root:plugdev rw`, so no extra
  permission step. `/dev/serial/by-id/usb-Texas_Instruments_XDS110__03.00.00.05__Embed_with_CMSIS-DAP_R2101050-if00`
  (CLI/UART) and `-if03` are enumerated now (a board is plugged in). Not opened.
- `DISPLAY=localhost:10.0` is set in this shell (an SSH-X11-style value); no local display. Free disk 194 GB.

### 2. UniFlash version and Linux install

- Current release 9.6.0 (1 Jul 2026); Linux file `uniflash_sl.9.6.0.5764.run`, listed as 373717 K
  `ti_uniflash_page`. Direct URL `https://software-dl.ti.com/ccs/esd/uniflash/uniflash_sl.9.6.0.5764.run`
  answered HTTP 200, `Content-Length: 382687118`, no login (header check only; not downloaded).
- macOS lacks mmWave support; Linux is supported `ti_uniflash_page`. mmWave support is by device family
  (IWR14xx/IWR16xx guide; the SDK 3.6 guide says xWR1xxx flashing uses UniFlash desktop or cloud, Windows or
  Linux PC) `ti_uniflash_qsg` `ti_mmwave_sdk_ug`.
- Silent/unattended flags for the `.run`: **not found in any TI source**. HYPOTHESIS: it is a
  BitRock-style installer taking `--mode unattended --prefix <dir>` (as TI's CCS installers do); check with
  `./uniflash_sl.*.run --help` first. A Linux report needed `sudo ln -sf /lib/x86_64-linux-gnu/libudev.so.1
  /lib/x86_64-linux-gnu/libusb-0.1.so.4` for the XDS110 side `hackmd_iwr1642_linux`; that is the debug probe,
  which a UART flash does not use (HYPOTHESIS: not needed).
- Placement: the installer is a download like the others (`download.sh`); install it to a path outside git
  (e.g. under `firmware_dev/downloads/` ignored, or an image layer for the `flash` service). Docker needs
  `/dev` passthrough, which the `flash` service already bind-mounts.

### 3. The CLI for xWR18xx serial flash

- CLI: `dslite.sh` in the install root (Linux), mode `flash` is the default; usage
  `dslite flash --config=ccxml-file [options] [flash-file1 ...]` with `-s id=value` settings, `-p`
  (list ops), `-S '.*'` (list settings), `-g` (log file), `-e` (verbose) `ti_uniflash_qsg`.
- A real AWR1843 serial run (UniFlash 5.1, Windows):
  `dslite.bat -c AWR1843_uniflash5.ccxml -s COMPort=COM6 -f xwr18xx_test.bin,1`. Log lines include
  `Connecting to COM Port COM6...`, `Set break signal`, `AWR1843 device, fileType=META_IMAGE1 detected -> OK`,
  `Formatting SFLASH storage...`, `Erase storage completed successfully!`, `Downloading [META_IMAGE1]
  size [227204]`, and `SUCCESS!! File type META_IMAGE1 downloaded successfully to SFLASH.` Then a final
  `error: Cortex_R4_0: Can't Run Target CPU: Unsupported GTI Function.`, which the poster called a
  nuisance after a flash that "works without problems" in the GUI; TI did not explain it `ti_e2e_843614`.
- The ccxml in that thread uses `connections/Serial_Connection.xml` with the `serial_*` driver files and
  `devices/awr1843.xml`. HYPOTHESIS: for the IWR1843BOOST use `devices/iwr1843.xml` (exists in CCS 12.8.1's
  targetdb, with `Meta Image 1`..`4` image types and `.bin` extension); the SDK 3.6 guide says the demo
  `.bin` files are the meta images to flash and that a custom demo's meta image is flashed the same way
  `ti_mmwave_sdk_ug`.
- **Argument spelling in 9.6 differs from the 5.1 log**: 9.6 documents `-f` as a flag with files listed at
  the end, not `-f file,1`; the image-slot syntax for Meta Image 1 in 9.6 is not documented. Settings ids
  (`COMPort`, format-on-download) must be read from `dslite flash -c <ccxml> -S '.*'` on the bench.
- The documented way to get a correct ccxml and command is the GUI "Generate Package" (device, `Meta Image
  1` file, COM port, format option) which emits a zip with `dslite` plus a script; TI's mmWave FAQ calls it the command-line route
  and notes a bug in 5.1 with a workaround link `ti_e2e_856044`.

### 4. Other routes

| Route | TI-supported | Headless | Note |
|-------|--------------|----------|------|
| UniFlash `dslite.sh` + ccxml | yes | yes (HYPOTHESIS, no GUI step in the log) | recommended |
| UniFlash "Generate Package" on a GUI PC | yes | host side yes | copy zip; edit COM port |
| UniFlash desktop/cloud GUI (cloud needs Chrome + TI Cloud Agent) | yes | no | user flashes elsewhere |
| CCS 12.8.1 DSLite in Docker image | n/a for xWR18 | n/a | see section 5 |
| mmWave Studio | yes, Windows only | no | |
| SDK 3.6 `packages/ti/utils/sbl`, Radar Toolbox `tools/JTAG_Flasher` | JTAG/SBL, not UART flash | needs JTAG debug and a gel | not a replacement |
| Custom UART tool per SWRA551 (break signal, bootloader UART protocol, CRC32) | document yes, tool no | yes | last resort; AWR1642 doc, same ROM family (HYPOTHESIS) |

A TI mmWave FAQ answer points at SWRA551 and an E2E script thread for anyone writing their own
flasher `ti_e2e_856044` `ti_swra551`.

### 5. Display, and the earlier DSLite claim

- The CLI log above is console-only; the GUI is the separate node-webkit app, so no X11/xvfb/VNC is
  needed to **run** `dslite.sh` (HYPOTHESIS: not exercised on Linux here). Whether the `.run` installer
  itself opens a GUI wizard is unknown; BitRock installers normally fall back to text mode without a
  display.
- Claim check, from the image (`docker run --rm`, read-only): CCS 12.8.1's `DSLite` maps
  `AWR*`/`IWR*` to a `FlashPython` flasher and its targetdb has the IWR1843 device with Meta Image types,
  but the only Python flasher on disk (`ccs_base/sitara_mcu/serial/FlashPython.py`) returns
  "not Supported" for anything but am243x/am263x/am263px/am273x, and there is no mmWave flasher
  directory (`libFlashPython.so` names one, "mmWave"). So the firmware-04 statement holds for that
  image; HYPOTHESIS: UniFlash's own bundle adds the missing mmWave serial flasher (the 5.1 log shows it
  exists there). Copying DSLite between installs is untested; do not rely on it.

### 6. Risks

- **Erase scope:** the logged run formatted all of SFLASH before download. A flash with format on wipes the
  stock demo; restore with `firmware_dev/projects/ti_stock_demos/build/iwr1843_demo.bin` (324804 B) the same
  way. FAQ: meta images 1..4 go to 512 KB offsets and the ROM bootloader boots offset 0 first, then 512 KB
  `ti_e2e_856044`. Not erasing everything is possible (E2E thread cited there, not read).
- **Mode and power:** flash mode needs SOP0 + SOP2 closed, power-cycled before UniFlash starts; functional
  mode is SOP0 only; the SDK guide lists the same `ti_mmwave_sdk_ug`. FAQ: after a failed attempt,
  re-power, re-plug, kill a stale `DSLite` or `Python` process `ti_e2e_856044`; 5 V ~3 A supply.
- **Port:** use the XDS110 "Application/User UART", on Linux the `-if00` by-id link (the SDK guide
  names it as the Windows "XDS110 Class Application/User UART") `ti_mmwave_sdk_ug`. Permissions already fine.
- **Nothing else may hold the port** (serial driver, viewer); claim it in `status.md`.

## Applicability to CPSL TI Radar

`flash.sh` can stay a manual stub until one bench flash succeeds; then it can call `dslite.sh` from a
`flash` service layer. The 152132 B MSS-only image is a normal SDK 3.6 meta image (built with
`generateMetaImage.sh`), so header validation should pass as it does for the stock `.bin`
(HYPOTHESIS; the log's "correct header for AWR1843" check is the discriminator).

## Recommended Experiment

Numbered recommendation (install tool, command, fallback):

1. Ask the user: install UniFlash 9.6.0 on this host (decision for firmware-14). Download the `.run` with
   `curl -L -O -C -` (no login), run `--help`, install headless (`--mode unattended --prefix ...` if offered).
2. Bench (human sets SOP0+SOP2, power-cycles, claims the board): `dslite.sh flash -c IWR1843_serial.ccxml -S '.*'`
   to read setting ids and `-p` for ops; then flash with COM port set to the `-if00` by-id path, Meta Image 1
   = `iwr1843_sar_lvds.bin`, `-e -g flash.log`. Success text: `SUCCESS!! File type META_IMAGE1 downloaded
   successfully to SFLASH.` Ignore a trailing `Can't Run Target CPU` only if the process also reached it
   after the SUCCESS line. Functional mode, re-power, check `mmwDemo:/>` on the CLI port.
3. If the 9.6 CLI rejects the ccxml, use the fallback: on any GUI machine "Generate Package", copy the zip.
4. Restore test: flash `iwr1843_demo.bin` back the same way.

## Confidence

**Medium-high (about 75%)** that `dslite.sh` flashes the IWR1843BOOST headless over UART: one real
AWR1843 CLI log (old version, Windows), a CLI that TI documents for this family, TI's own FAQ naming the
CLI route. **Medium** on exact 9.6 arguments and the ccxml (derived from a 5.1 thread plus the CCS targetdb).
**Low** on installer headlessness. What only the first bench flash confirms: (a) 9.6 `dslite.sh`
argument form and setting ids on Linux; (b) the `.run` installs with no display; (c) the ccxml for
`iwr1843.xml` works; (d) the trailing `Can't Run Target CPU` error and the exit code; (e) the SDK 3.6
MSS-only image passes the header check; (f) whether `-if00` is the port the bootloader answers on; (g) the
stock demo restore; (h) whether format-on-download can be turned off. The 421 on the TI wiki mmWave UniFlash
PDF means the device-family guide could not be read; E2E threads 795052/823136 were not read.

## Sources

- `ti_uniflash_page` — Texas Instruments (2026), "UNIFLASH Software programming tool," *ti.com*. url:https://www.ti.com/tool/UNIFLASH
- `ti_uniflash_qsg` — Texas Instruments (2026), "UniFlash Quick Start Guide (v9.6)," *software-dl.ti.com*. url:https://software-dl.ti.com/ccs/esd/uniflash/docs/v9_6/uniflash_quick_start_guide.html
- `ti_e2e_843614` — Brueckner, S. (2020), "AWR1843: Using Uniflash command line tool with AWR1843," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/843614/awr1843-using-uniflash-command-line-tool-with-awr1843
- `ti_e2e_856044` — Gupta, J. (2020), "[FAQ] mmWave Sensor- Uniflash related queries," *TI E2E Sensors forum*. url:https://e2e.ti.com/support/sensors-group/sensors/f/sensors-forum/856044/faq-mmwave-sensor--uniflash-related-queries
- `ti_swra551` — Texas Instruments (2017), "AWR1642 Bootloader Flow," SWRA551. url:https://www.ti.com/lit/an/swra551/swra551.pdf
- `ti_mmwave_sdk_ug` — Texas Instruments (2021), "mmWave SDK 3.6.02.00-LTS package, docs/mmwave_sdk_user_guide.pdf, section How to flash an image onto mmWave EVM," *TI MMWAVE-SDK download*. url:https://dr-download.ti.com/software-development/software-development-kit-sdk/MD-PIrUeCYr3X/03.06.02.00-LTS/mmwave_sdk_03_06_02_00-LTS-Linux-x86-Install.bin
- `hackmd_iwr1642_linux` — octobersky (2020), "mazu-radar01 and IWR1642BOOST (mmwave)," *HackMD*. url:https://hackmd.io/@octobersky/BJbRPLMpL

Note for the Reviewer: this repo has no `docs/references/references.bib`, so the bib-key existence
checks of `lint_research_memo.py` cannot pass (same as the 2026-10-05 memo). The SDK user guide was read
from the copy inside the firmware Docker image (`/opt/ti/mmwave_sdk_03_06_02_00-LTS/docs/`); no PDF archived.
