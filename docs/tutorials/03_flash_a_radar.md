# 3. Flash a radar: the right image for the config you will run

The board must run the image that matches the `"firmware"` key of the system config (the table in the [README](../../README.md)), or a run fails or shows nothing. Many boards arrive with the stock demo already on them: skip this tutorial, run [tutorial 5](05_driver_cli_and_adc.md), and come back if it reports `config_rejected` ([tutorial 8](08_troubleshooting.md)). Flashing needs a person at the bench, and one person per board at a time.

## Which image

| Board and firmware | Image | Where it comes from |
|---|---|---|
| IWR1443 `demo` | `shipped_firmware/IWR1443/demo/xwr14xx_mmw_demo.bin` | in this repo |
| IWR1443 `dca1000_raw` | `shipped_firmware/IWR1443/dca1000_raw/iwr_raw_rosnode/firmware/xwr14xx_lvds_stream.bin` | the `iwr_raw_rosnode` submodule (below) |
| IWR1843, IWR6843, IWR6843ODS `demo` | TI's mmWave SDK 3.6 `mmw` demo | built from `firmware_dev` (project `ti_stock_demos`), or TI's SDK 3.6 install (its `packages/ti/demo/xwr18xx/mmw/` holds a prebuilt demo) |
| IWR1843 `iwr1843_sar_lvds` | SAR / LVDS image | built from `firmware_dev` |
| AWR2243 cascade `cascade_ddm` | cascade DDM demo | built and flashed from `firmware_dev`; cascade steps: [`docs/hardware/cascade_setup.md`](../hardware/cascade_setup.md) |

**`iwr_raw_rosnode`.** A fork (by this lab) of [moodoki/iwr_raw_rosnode](https://github.com/moodoki/iwr_raw_rosnode), a ROS node for the IWR1443 and DCA1000. This repo uses none of its ROS code; the fork is here only because it holds the prebuilt LVDS image `xwr14xx_lvds_stream.bin` (with its sources under `lvds_stream/xwr14xx/`). Fetch it only for that image: `git submodule update --init shipped_firmware/IWR1443/dca1000_raw/iwr_raw_rosnode`. Details: [`shipped_firmware/README.md`](../../shipped_firmware/README.md).

## Flash with UniFlash (prebuilt images)

1. Install TI [UniFlash](https://www.ti.com/tool/UNIFLASH#downloads) on the host.
2. Power the board off and set the boot switches to **flashing mode**. IWR1843: SOP2 = 1, SOP1 = 0, SOP0 = 1; the diagrams show the switch positions: [IWR1843](../images/boot_modes/IWR1843_SOP_nodes.png), [IWR1443](../images/boot_modes/IWR_SOP_modes.png). Power on.
3. In UniFlash select the device, point it at the board's CLI port (the lower-numbered `/dev/ttyACM*`, or the `-if00` by-id path) and load the image from the table.
4. Power off, set the switches to **functional mode** (IWR1843: SOP2 = 0, SOP1 = 0, SOP0 = 1), and power on. The board reads the switches only at power-up.

Take other boards' switch settings from their diagram, not from this page.

## Build an image from source

`firmware_dev` builds and flashes inside Docker, so you install no TI software, but it downloads about 3.6 GB of TI tools. Its own tutorials cover it:

```bash
git submodule update --init --checkout firmware_dev && cd firmware_dev
./downloads/download.sh && docker compose build     # once
./fw build ti_stock_demos                           # then ./fw flash <project> <port>
```

Start at [`firmware_dev/README.md`](https://github.com/davidmhunt/CPSL_TI_Radar_Firmware_Dev#readme); [`docs/firmware.md`](../firmware.md) is the pointer. The cascade accepts a cfg only once per power-up, so power-cycle it before every run.

Next: [tutorial 4, the GUI](04_first_run_gui.md).
