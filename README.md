# CPSL TI Radar

Tools for capturing raw ADC data from TI IWR mmWave radar sensors using the TI DCA1000 data capture card.

## Primary Implementation: C++ Streamer

The C++ implementation in [`CPSL_TI_Radar_cpp/`](./CPSL_TI_Radar_cpp/) is the primary entry point. It provides reliable high-rate DCA1000 streaming via a dedicated RX thread, lock-free ring buffer, and tuned UDP socket buffers.

See **[`CPSL_TI_Radar_cpp/Readme.md`](./CPSL_TI_Radar_cpp/Readme.md)** for:
- Prerequisites and build instructions
- System settings required for high-rate streaming (`SO_RCVBUF`, SCHED_RR, `rmem_max`)
- JSON config file format and all available fields
- How to run the executable and pass a config path

## DCA1000 Setup

To program or reconfigure the DCA1000 FPGA's network settings (required when running multiple radars simultaneously), see **[`DCA_Programming/README.md`](./DCA_Programming/README.md)**.

Default DCA1000 network configuration:
- FPGA IP: `192.168.33.180`
- Host IP (static): `192.168.33.30`, subnet `255.255.255.0`
- Command port: `4096`, Data port: `4098`

## Radar Configurations

Sample `.cfg` files for each supported board are in [`configurations/`](./configurations/). Use the [TI mmWave Demo Visualizer](https://dev.ti.com/gallery/view/mmwave/mmWave_Demo_Visualizer/ver/2.1.0/) to generate additional configurations.

Supported boards:

| Board | LVDS lanes | ADC format | `board_type` in JSON |
|---|---|---|---|
| IWR1843 | 2-lane | non-interleaved (SDK 3+) | `"IWR1843"` |
| IWR6843 | 2-lane | non-interleaved (SDK 3+) | `"IWR6843"` |
| IWR1443 | 4-lane | interleaved (SDK 2) | `"IWR1443"` |

## Firmware

Pre-built firmware binaries for flashing via TI UniFlash are in [`Firmware/`](./Firmware/):
- `Firmware/DCA1000_Streaming/` — use when streaming to the DCA1000
- `Firmware/IWR_Demos/` — use when streaming TLV data directly from the IWR serial port

## Data Analysis Notebooks

Python notebooks for analyzing C++ output files are in [`utilities/`](./utilities/):

| Notebook | Purpose |
|---|---|
| `process_adc_data.ipynb` | Load and analyze `adc_data.bin` files written by the C++ `save_to_file` option |
| `process_raw_lbds_data.ipynb` | Load and decode raw LVDS packet streams (`LVDS_Raw_0.bin`) |
| `print_config.ipynb` | Decode a radar `.cfg` file and display key parameters |
| `determine_serial_ports.ipynb` | List available serial ports on the host |
| `bartlet.ipynb` | Angle-of-arrival estimation demo (Bartlett and Capon beamforming) |
| `test_ethernet_traffic.ipynb` | DCA1000 network debugging utility |

## Archived Code

Legacy implementations that have been superseded:

- [`archived_code/CPSL_TI_Radar/`](./archived_code/CPSL_TI_Radar/) — Python DCA1000 streaming package (superseded by C++). See `ARCHIVE_NOTE.md` inside for details.
- [`archived_code/CPP_Development/`](./archived_code/CPP_Development/) — early C++ prototypes used during development.

## ROS Integration

A companion ROS package for consuming streamed data is available at [CPSL_TI_Radar_ROS](https://github.com/davidmhunt/CPSL_TI_Radar_ROS).
