# CPSL TI Radar

Host-side software for TI mmWave radars, from the Collaborative Perception and Sensing Lab (CPSL). It configures a radar over its CLI serial port, then streams either **raw ADC data** through a TI DCA1000 capture card (UDP, high rate, real-time threads) or the on-chip demo's **TLV point cloud** over a serial data port. A web GUI builds radar configs, runs the driver and shows the data live; a firmware build environment and prebuilt images cover the boards themselves. This is branch `release/v2.0`, a rework of the v1 code ([what changed](docs/migration_v1_to_v2.md)).

![The GUI's Radar tab](docs/images/gui/radar.png)

*The GUI's Radar tab (a hardware-free demo run). Screenshots of every tab are in [tutorial 2](docs/tutorials/02_first_run_gui.md).*

## Supported boards

Each board is a descriptor in [`CPSL_TI_Radar_cpp/config/boards/`](CPSL_TI_Radar_cpp/config/boards/); the firmware a board runs is a descriptor in [`config/firmware/`](CPSL_TI_Radar_cpp/config/firmware/) and is a mandatory `"firmware"` key in every system config.

| Board | Firmware (`"firmware"`) | Output |
|---|---|---|
| IWR1443 | `demo` | serial TLV point cloud |
| IWR1443 | `dca1000_raw` | raw ADC via DCA1000 (4 LVDS lanes) |
| IWR1843 | `demo` | serial TLV; raw ADC via DCA1000 when the cfg has `lvdsStreamCfg` (2 lanes) |
| IWR1843 (`"board": "IWR1843_SAR"`) | `iwr1843_sar_lvds` | raw ADC via DCA1000, no serial data |
| IWR6843, IWR6843ODS | `demo` | serial TLV; raw ADC via DCA1000 as for the IWR1843 |
| AWR2243 2-chip cascade (AM273x) | `cascade_ddm` | serial TLV only; accepts a cfg once per power-up |

The IWR1843 SAR firmware's `dataFmt` 2 mode has not yet been benched on a board. Radar `.cfg` files live in `config/radar/<BOARD>/<firmware>/`, ready-made system configs in `config/system/<BOARD>_<firmware>_<purpose>[_<mount>].json` (index: [`config/README.md`](CPSL_TI_Radar_cpp/config/README.md)), and your own in `config/user/` (gitignored).

## Quick start

**Native** (Linux; needs `git`, `git-lfs`, `g++` 7+, `cmake`, [`uv`](https://docs.astral.sh/uv/)):

```bash
git clone --recurse-submodules https://github.com/davidmhunt/CPSL_TI_Radar && cd CPSL_TI_Radar
git lfs install && git lfs pull
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build && cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
# GUI in demo mode, no hardware: open http://127.0.0.1:8090/
RADAR_GUI_DRIVER=tests/fakes/fake_driver.py uv run python -m radar_gui --port 8090 \
    --source replay --file tests/fixtures/replay/iwr1843_sdk3_20frames.bin
# the driver CLI: check a shipped config without a radar
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_tlv_default.json --validate
```

With a board, run `uv run python -m radar_gui` (port 8000) and follow the tutorials; DCA1000 runs also need host setup (`uv run tools/setup/host_setup.py --nic <nic>`, [tutorial 1](docs/tutorials/01_install.md)).

**Docker** (the driver and GUI in one image, no toolchain on the host):

```bash
docker compose -f docker/app/compose.yaml build demo
docker compose -f docker/app/compose.yaml up demo      # http://127.0.0.1:8090/
```

The `hw` profile for real boards is described in [`docs/docker.md`](docs/docker.md) but not yet verified on a real board.

**Tests:** `uv run pytest -m "not slow"` is the fast loop; `uv run pytest` runs the whole suite (about 1085 tests, about 1 minute); the C++ tests run through `ctest` as above. None need hardware.

## Documentation

- **Tutorials** ([index](docs/tutorials/README.md)): [1 install](docs/tutorials/01_install.md) · [2 GUI](docs/tutorials/02_first_run_gui.md) · [3 driver CLI](docs/tutorials/03_first_run_driver_cli.md) · [4 recording ADC](docs/tutorials/04_recording_adc.md) · [5 troubleshooting](docs/tutorials/05_troubleshooting.md); then 10 to 14 for changing the driver and for bench validation.
- [`CPSL_TI_Radar_cpp/Readme.md`](CPSL_TI_Radar_cpp/Readme.md): the driver reference (config keys, flags, library API, host prerequisites).
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): how the driver works. [`radar_gui/README.md`](radar_gui/README.md): the GUI's API and layout.
- [`docs/RESULTS.md`](docs/RESULTS.md): measured streaming rates and on-board checks (all numbers live there).
- Firmware: [`docs/firmware.md`](docs/firmware.md) (build and flash), [`shipped_firmware/README.md`](shipped_firmware/README.md) (prebuilt images).
- Hardware: [`docs/hardware/cascade_setup.md`](docs/hardware/cascade_setup.md), [`DCA_Programming/README.md`](DCA_Programming/README.md) (reprogram a DCA1000's address to run several radars), [boot-mode diagrams](docs/images/boot_modes/).
- [`docs/migration_v1_to_v2.md`](docs/migration_v1_to_v2.md): for anyone coming from v1.

## Repository map

| Path | Contents |
|------|----------|
| `CPSL_TI_Radar_cpp/` | C++ driver: `Radar` API, DCA1000 and serial streaming, tests, and `config/` (boards, firmware, radar `.cfg`, system JSONs, `user/`) |
| `radar_gui/` | the web GUI: Python backend plus a no-build `web/` frontend |
| `firmware_dev/` | opt-in submodule: firmware sources and a Docker build environment (not fetched by the clone) |
| `shipped_firmware/` | prebuilt firmware images, `<BOARD>/<firmware>/` |
| `DCA_Programming/` | DCA1000 FPGA network reprogramming |
| `docker/app/` | image and compose file for the driver and GUI |
| `tools/` | host setup (`setup/`), bench harness (`bench/`), config migration, GUI screenshot tool |
| `utilities/` | notebooks for ADC cubes (`process_adc_data`), raw LVDS (`process_raw_lbds_data`) and DCA1000 network debugging (`test_ethernet_traffic`) |
| `tests/` | pytest suite and fixtures |
| `docs/` | tutorials, architecture, results, firmware notes, `hardware/`, `images/` (GUI shots via git LFS, boot modes), `archive/` (finished design notes), `research/` |

A companion ROS package for consuming the streams is [CPSL_TI_Radar_ROS](https://github.com/davidmhunt/CPSL_TI_Radar_ROS); it still uses the v1 `Runner` API and does not build against v2.0 yet.
