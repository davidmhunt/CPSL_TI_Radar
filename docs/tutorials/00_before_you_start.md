# 0. Before you start: what is in the box

No commands here. Read it once so the rest makes sense. Everything in this repo runs on Linux (the steps assume Ubuntu 24.04); you need no ROS and no other repository until [tutorial 6](06_ros2.md).

## What you need

- **A TI mmWave radar board**: IWR1443, IWR1843, IWR6843, IWR6843ODS, or the AWR2243 2-chip cascade EVM. Plug it into the host with its USB cable. Its USB chip (an XDS110) shows up as two serial ports: a **CLI port** (commands and the radar config go here) and a **data port** ([which is which](02_host_setup.md#which-port-is-the-cli-which-the-data-port)). The cascade EVM needs its 12 V supply on before USB shows up.
- **Optional, for raw ADC: a TI DCA1000 capture card.** The radar's LVDS pins feed the card, and the card sends the raw samples to the host as UDP packets over a wired Ethernet port. The card answers at `192.168.33.180`; the host port must be `192.168.33.30`. A laptop without a spare wired NIC needs a USB Ethernet adapter.
- **A host**: Linux, a free USB port, and for the DCA1000 a wired NIC. Internet for the first install.

## Two ways to get data

| You get | How | Needs |
|---|---|---|
| **Point cloud** (x, y, z, velocity, SNR of detected points) | the board's demo firmware sends it over the data port | board and USB only |
| **Raw ADC** (every sample, every chirp, every rx) | the board streams over LVDS to the DCA1000 | DCA1000, a firmware that streams LVDS, [host setup](02_host_setup.md) |

The board table in the [README](../../README.md) lists which firmware gives which output on which board. The cascade is serial only.

## Terms

- **cfg vs system JSON**: a `.cfg` is TI's chirp configuration, sent to the radar line by line; a **system JSON** tells the driver which board, firmware, `.cfg`, ports and outputs to use.
- **TLV**: the demo firmware's serial packet format (type-length-value); it carries the detected points.
- **Firmware id**: the `"firmware"` key (`demo`, `dca1000_raw`, `iwr1843_sar_lvds`, `cascade_ddm`) naming the image on the board. It must match what is flashed.
- **`lvdsStreamCfg`**: the `.cfg` line that makes the radar send raw samples out of its LVDS pins.

Next: [tutorial 1, install](01_install.md).
