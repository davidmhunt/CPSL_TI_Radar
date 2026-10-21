# 3. Flash a radar: the right image for the config you will run

The board must run the image that matches the `"firmware"` key of the system config (the table in the [README](../../README.md)), or a run fails or shows nothing. Many boards arrive with the stock demo already on them: skip this tutorial, run [tutorial 5](05_driver_cli_and_adc.md), and come back if it reports `config_rejected` ([tutorial 8](08_troubleshooting.md)). Flashing needs a person at the bench, and one person per board at a time.

## Which image

**No IWR1843 or IWR6843 demo `.bin` ships in this repo**; only the IWR1443 images do. For those boards you get the image from TI or build it (below).

| Board and firmware | Image | Where it comes from |
|---|---|---|
| IWR1443 `demo` | `shipped_firmware/IWR1443/demo/xwr14xx_mmw_demo.bin` | in this repo |
| IWR1443 `dca1000_raw` | `shipped_firmware/IWR1443/dca1000_raw/iwr_raw_rosnode/firmware/xwr14xx_lvds_stream.bin` | the `iwr_raw_rosnode` submodule (below) |
| IWR1843, IWR6843, IWR6843ODS `demo` | TI's mmWave SDK 3.6 `mmw` demo | route 1 or 2 below |
| IWR1843 `iwr1843_sar_lvds` | SAR / LVDS image | route 2 (`firmware_dev`) |
| AWR2243 cascade `cascade_ddm` | cascade DDM demo | route 2; cascade steps: [`docs/hardware/cascade_setup.md`](../hardware/cascade_setup.md) |

**Route 1, TI's SDK install.** Download mmWave SDK 3.6.x for Linux from [TI's mmWave SDK page](https://www.ti.com/tool/MMWAVE-SDK) (a free TI login) and run the installer. The prebuilt demo is in the install under `packages/ti/demo/xwr18xx/mmw/` (IWR1843; `xwr68xx` for the IWR6843); the image to flash is the `.bin` there (`xwr18xx_mmw_demo.bin`).

**Route 2, build it.** [`firmware_dev`](https://github.com/davidmhunt/CPSL_TI_Radar_Firmware_Dev#readme) builds and flashes inside Docker, so you install no TI software, but it downloads about 3.6 GB of TI tools, wants about 25 GB of disk, and the image build is long (the cascade build alone is about 15 minutes). The `ti_stock_demos` project builds TI's own 3.6.02.00 demos unchanged (`iwr1843_demo.bin`, `iwr6843_demo.bin` in its `build/`). From this repo's root:

```bash
git submodule update --init --checkout firmware_dev && cd firmware_dev
./downloads/download.sh && docker compose build     # once
./fw build ti_stock_demos                           # then ./fw flash <project> <port>
```

`./fw flash` drives UniFlash for you after a typed confirmation, so the manual steps below are for route 1 and other images. [`docs/firmware.md`](../firmware.md) lists the projects.

**What does the board run now?** Send `version` on the CLI port (the 115200-baud CLI; any serial terminal) with the board in functional mode; `./fw verify ti_stock_demos --port <CLI port>` does it for you without sending a cfg. A `config_rejected` run ([tutorial 8](08_troubleshooting.md)) also means a mismatch.

**`iwr_raw_rosnode`.** A fork (by this lab) of [moodoki/iwr_raw_rosnode](https://github.com/moodoki/iwr_raw_rosnode), a ROS node for the IWR1443 and DCA1000. This repo uses none of its ROS code; the fork is here only because it holds the prebuilt LVDS image `xwr14xx_lvds_stream.bin` (with its sources under `lvds_stream/xwr14xx/`). Fetch it only for that image: `git submodule update --init shipped_firmware/IWR1443/dca1000_raw/iwr_raw_rosnode`. Details: [`shipped_firmware/README.md`](../../shipped_firmware/README.md).

## Flash with UniFlash (a prebuilt `.bin`)

1. Install TI [UniFlash](https://www.ti.com/tool/UNIFLASH#downloads) on the host (the lab's `firmware_dev` uses 9.6.0). Close every program holding the board's ports (the GUI, the driver, a terminal).
2. Power the board off and set the boot switches to **flashing mode**. IWR1843: SOP2 = 1, SOP1 = 0, SOP0 = 1; diagrams for the switch positions: [IWR1843](../images/boot_modes/IWR1843_SOP_nodes.png), [IWR1443](../images/boot_modes/IWR_SOP_modes.png). Power on.
3. In UniFlash pick the device (for example IWR1843), the board's CLI port (see [tutorial 2](02_host_setup.md#which-port-is-the-cli-which-the-data-port)) and the `.bin` as the meta image to flash; the format is `bin`. The exact UI labels differ between UniFlash versions. `firmware_dev` flashes the IWR1843 with image slot `1`; its [ti_stock_demos README](https://github.com/davidmhunt/CPSL_TI_Radar_Firmware_Dev/blob/main/projects/ti_stock_demos/README.md) has the by-hand steps. Wait for UniFlash's success message.
4. Power off, set the switches to **functional mode** (IWR1843: SOP2 = 0, SOP1 = 0, SOP0 = 1), and power on. The board reads the switches only at power-up.

Take other boards' switch settings from their diagram, not from this page. The cascade accepts a cfg only once per power-up, so power-cycle it before every run.

Next: [tutorial 4, the GUI](04_first_run_gui.md).
