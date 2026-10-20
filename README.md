# CPSL TI Radar

Host-side software for TI mmWave radars, from the Collaborative Perception and Sensing Lab (CPSL). It configures a radar over its CLI serial port, then streams either **raw ADC data** through a TI DCA1000 capture card (UDP, high rate) or the on-chip demo's **TLV point cloud** over a serial data port. A web GUI builds radar configs, runs the driver and shows the data live; a ROS 2 node publishes the streams; a firmware build environment and prebuilt images cover the boards themselves. This is v2.0 (the `main` branch), a rework of v1 ([what changed](docs/migration_v1_to_v2.md)).

![The GUI's Radar tab](docs/images/gui/radar.png)

## Supported boards

Each board is a descriptor in [`CPSL_TI_Radar_cpp/config/boards/`](CPSL_TI_Radar_cpp/config/boards/); the firmware it runs is a descriptor in [`config/firmware/`](CPSL_TI_Radar_cpp/config/firmware/) and a mandatory `"firmware"` key in every system config.

| Board | Firmware (`"firmware"`) | Output |
|---|---|---|
| IWR1443 | `demo` | serial TLV point cloud |
| IWR1443 | `dca1000_raw` | raw ADC via DCA1000 (4 LVDS lanes) |
| IWR1843 | `demo` | serial TLV; raw ADC via DCA1000 when the cfg has `lvdsStreamCfg` (2 lanes) |
| IWR1843 (`"board": "IWR1843_SAR"`) | `iwr1843_sar_lvds` | raw ADC via DCA1000, no serial data |
| IWR6843, IWR6843ODS | `demo` | serial TLV; raw ADC via DCA1000 as for the IWR1843 |
| AWR2243 2-chip cascade (AM273x) | `cascade_ddm` | serial TLV only; accepts a cfg once per power-up |

Radar `.cfg` files live in `config/radar/<BOARD>/<firmware>/`, ready-made system configs in `config/system/<BOARD>_<firmware>_<purpose>[_<mount>].json` (index: [`config/README.md`](CPSL_TI_Radar_cpp/config/README.md)), and your own in `config/user/` (gitignored).

## Quick start

On Ubuntu with `build-essential`, `cmake`, `git` and [`uv`](https://docs.astral.sh/uv/) ([tutorial 1](docs/tutorials/01_install.md) has the exact packages), no board needed:

```bash
git clone https://github.com/davidmhunt/CPSL_TI_Radar && cd CPSL_TI_Radar
git submodule update --init CPSL_TI_Radar_cpp/include/json     # the only submodule the build needs
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build && cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
# GUI in demo mode (a stand-in driver, a recorded capture): open http://127.0.0.1:8090/
RADAR_GUI_DRIVER=tests/fakes/fake_driver.py uv run python -m radar_gui --port 8090 \
    --source replay --file tests/fixtures/replay/iwr1843_sdk3_20frames.bin
```

Or use the Docker image instead of a toolchain ([`docs/docker.md`](docs/docker.md), after the `json` step above): `docker compose -f docker/app/compose.yaml up --build demo`.

**With a board:** read [tutorial 0](docs/tutorials/00_before_you_start.md), then set up the host ([2](docs/tutorials/02_host_setup.md)), flash ([3](docs/tutorials/03_flash_a_radar.md)) and run the GUI ([4](docs/tutorials/04_first_run_gui.md)).

## Documentation

- **Tutorials** ([index](docs/tutorials/README.md)): 0 before you start · 1 install · 2 host setup · 3 flash a radar · 4 GUI · 5 driver CLI and recording ADC · 6 ROS 2 · 7 several radars · 8 troubleshooting; 10 to 14 are for changing the driver.
- [`CPSL_TI_Radar_cpp/Readme.md`](CPSL_TI_Radar_cpp/Readme.md): the driver reference (config keys, flags, library API). [`radar_gui/README.md`](radar_gui/README.md): the GUI's API. [`ros2/README.md`](ros2/README.md): the ROS 2 packages.
- [`docs/raw_data/README.md`](docs/raw_data/README.md): the raw ADC data format and how to decode it.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (how the driver works), [`docs/RESULTS.md`](docs/RESULTS.md) (measured rates and on-board checks).
- Firmware: [`docs/firmware.md`](docs/firmware.md), [`shipped_firmware/README.md`](shipped_firmware/README.md). Hardware: [`docs/hardware/cascade_setup.md`](docs/hardware/cascade_setup.md), [`DCA_Programming/README.md`](DCA_Programming/README.md), [boot-mode diagrams](docs/images/boot_modes/).

## More

**Also usable from [console](https://github.com/cpsl-research/console)**, the lab's robot web UI, which builds and runs this driver as one of its sensors.

**Legacy (v1):** [CPSL_TI_Radar_ROS](https://github.com/davidmhunt/CPSL_TI_Radar_ROS) uses the v1 `Runner` API and does not build against v2.0; the v1 code is the `v1.0` tag.
