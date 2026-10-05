# CPSL_TI_RADAR C++ code

## Installation

### Pre-requisite packages
Before building and installing this package, you must first have the following software installed:
1. C++ compiler (supporting at least C++ 11)
2. C++ boost libraries
3. CMake

The following installation instructions will work for linux devices, but should be similar for Windows and Mac devices as well.

#### 1. Install C++ compiler
1. First check to see if c+ is installed by running the following command
```
g++ --version
```
If this returns at least version 4.8.1, you can move onto the next step

2. If you don't have c++ installed or if your c++ version is out of date, run the following command to install c++ (for linux).
```
sudo apt update
sudo apt install build-essential
```

#### 2. Install boost libraries
1. Next, check to see if the C++ boost libraries are installed on your system. To do this, run the following command (in linux):
```
dpkg -s libboost-dev | grep Version
```

2. If you don't have the boost libraries installed, run the following command to install the requisite packages (for debian based systems including Ubuntu)
```
sudo apt update
sudo apt install libboost-all-dev
```

#### 3. Install CMake
1. Next, confirm that CMake is installed. To do this, run the following command:
```
cmake --version
```
2. If it isn't installed, run the following command to install it (for debian based systems including ubuntu)
```
sudo apt update
sudo apt install cmake
```

> **Quick setup.** Steps 4 and 5, and the DCA1000 static IP under "Preparing your hardware", are checked by one command. Run it from the repository root:
> ```bash
> uv run tools/setup/host_setup.py --nic <dca-nic>                    # read-only report: OK / MISSING / WARN / N-A, with the fix for each
> uv run tools/setup/host_setup.py --nic <dca-nic> --apply --dry-run  # print the exact commands and file contents, run nothing
> uv run tools/setup/host_setup.py --nic <dca-nic> --apply            # run them (sudo per command, one confirmation per check)
> ```
> `<dca-nic>` is the wired interface cabled to the DCA1000, for example `enp3s0`. The tool never picks it for you. Without `--nic` it lists the candidates. The report exits 1 while anything is MISSING. Don't run the tool with `sudo`: it calls `sudo` itself for each command, so you see every prompt. `cap_sys_nice` is lost on every rebuild of the driver, so re-run the tool after building. Add `--udev` for stable `/dev/radar/<serial>-cli` and `-data` names when more than one XDS110 board is connected. The manual commands below still work if you'd rather do it by hand.

#### 4. Allow access to serial ports
1. Finally, to ensure that your system has access to the serial ports to connect to the radar, run the following command
```
sudo usermod -a -G dialout $USER
```
2. To allow the command to take effect, simply reboot or log out and then log back in on your system

#### 5. System settings for high-rate DCA1000 streaming

At high ADC sampling rates, the default Linux UDP receive buffer (~128 KB) is too small and causes packet drops. Raise the system-wide cap with:
```bash
sudo sysctl -w net.core.rmem_max=134217728
```

To make this permanent across reboots:
```bash
echo 'net.core.rmem_max=134217728' | sudo tee /etc/sysctl.d/99-radar.conf
sudo sysctl -p /etc/sysctl.d/99-radar.conf
```

The DCA1000 RX thread runs at real-time priority (SCHED_RR 99). To allow this without running as root, either grant the executable the capability after building:
```bash
sudo setcap cap_sys_nice+ep ./build/CPSL_TI_Radar_CPP
```

Or add the following to `/etc/security/limits.conf` (replace `<username>` with your username), then log out and back in:
```
<username>  -  rtprio  99
```

The capability is stored on the binary file, so a rebuild removes it; grant it again after each build. `uv run tools/setup/host_setup.py` reports whether it is set (see "Quick setup" above). An existing `rtprio` limit below 99, such as PipeWire's `@pipewire - rtprio 95`, is not enough for the RX thread.

The pre-rework IWR1843 baseline (core-04) ran without `cap_sys_nice`, so the RX thread did not get real-time priority. Any later hardware performance comparison must say whether the capability was set.

## Building CPSL_TI_Radar_cpp

To download, build, and install the CPSL_TI_Radar c++ code, perform the following instructions:
1. Clone the repository
```
git clone --recurse-submodules https://github.com/davidmhunt/CPSL_TI_Radar
```

If you forgot to perform the --recurse-submodules when cloning the repository, you can use the following command to load the necessary submodules
```
git submodule update --init --recursive
```

2. Next build and make the project
```
cd CPSL_TI_Radar
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
```

3. (Optional) Install the libraries and headers, e.g. into a local prefix:
```
cmake --install CPSL_TI_Radar_cpp/build --prefix ~/cpsl_install
```

### Using the driver from another CMake project

The install provides one CMake package, `CPSL_TI_Radar`, exporting one target, `CPSL_TI_Radar::driver`. Linking it brings in all driver libraries, their include directories and their dependencies (Threads, Boost, nlohmann_json):
```cmake
cmake_minimum_required(VERSION 3.11)
project(consumer CXX)
find_package(CPSL_TI_Radar REQUIRED)
add_executable(consumer main.cpp)
target_link_libraries(consumer PRIVATE CPSL_TI_Radar::driver)
```
Configure it with `-DCMAKE_PREFIX_PATH=<install prefix>`.

**Renamed in v2.0.** The package was previously found as `find_package(CPSL_TI_Radar_CPP)` with targets such as `CPSL_TI_Radar_CPP::Runner`. For one release a deprecated compatibility package of that name is still installed: it calls `find_package(CPSL_TI_Radar)`, defines the old `CPSL_TI_Radar_CPP::<target>` names as aliases and prints a deprecation message. It will be removed after the next release, so switch to `find_package(CPSL_TI_Radar)` and `CPSL_TI_Radar::driver`. Headers are installed under `<prefix>/include/CPSL_TI_Radar_CPP/<subdir>/` and are reached through the target, so `#include "Runner.hpp"` works without extra include paths.

## Running tests

Unit tests live in `tests/` and need no radar, serial port, DCA1000 or network. They use a small in-tree harness (`tests/test_harness.hpp`), so there is nothing extra to install. Building the project builds them; run them with:

```bash
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

Each `tests/test_*.cpp` is one executable and one ctest test (config readers, TLV/serial frame parsing, DCA1000 packet assembly, ADC cube conversion, DCA1000 command encoding). To add one, write `tests/test_<name>.cpp` with `TEST_CASE`s and a `TEST_MAIN()`, then add an `add_driver_test(...)` line to `tests/CMakeLists.txt`. The tests are characterization tests: they pin current behaviour. `KNOWN_BUG(...)` marks a bug that is not fixed yet; it starts failing once the bug is fixed, which is the cue to turn it into a normal check. Use `-DBUILD_TESTING=OFF` to skip building them.

`test_board_descriptor` covers the board descriptor files in [`config/boards/`](./config/boards/) (see "Board descriptors" below).

### Replay benchmark (`ctest -C bench -L bench`)

`bench/bench_pipeline` replays synthetic DCA1000 packets (clean, 1% dropped, duplicated/reordered) through `FrameAssembler` and the ADC converter, with no hardware. For each of three converter variants it prints frames/s, CPU ns per ADC byte and heap allocations per frame: (a) today's `ADCCubeConverter`, (b) a nested `[rx][sample][chirp]` cube with a reused buffer, and (c) a flat `[chirp][rx][sample]` buffer. (b) and (c) are bench-only kernels in `bench/converter_kernels.hpp`. The frame shape comes from `config/radar/nav_configs/1843_stress_test.cfg` unless you pass `--cfg`. The test is registered with `CONFIGURATIONS bench`, so the plain `ctest` run above never lists or runs it. `-C bench` adds it and `-L bench` runs only it. Use a Release build for numbers you can compare:

```bash
cmake -S CPSL_TI_Radar_cpp -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j
ctest --test-dir build-release -C bench -L bench --verbose     # or: build-release/bench/bench_pipeline [--frames N] [--reps N]
```

## Preparing your hardware

To stream samples from the DCA1000, the following steps must be completed
1. Configure your machine's I.P address for the DCA1000
2. Flash the correct firmware onto the IWR1443

### 1.Setup Static IP Address
`uv run tools/setup/host_setup.py --nic <dca-nic>` checks this and, with `--apply`, adds the address to the NIC's NetworkManager profile without removing its other addresses (see "Quick setup" above). To do it by hand, configure the TCP/IPv4 to have the following settings:
1. Static IP Address
2. IP address: 192.168.33.30
3. Subnet mask: 255.255.255.0

### 2.Flash the correct firmware onto the device
To flash the correct firmware onto the IWR1443, you will need the UNIFLASH tool from Texas Instruments. Start by downloading the correct version of the tool from the [downloads page](https://www.ti.com/tool/UNIFLASH#downloads). Next, follow the instructions below corresponding to the board that you are using.

#### [IWR1443] DCA Streaming
1. Power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](../readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the binary located in the [firmware folder](../Firmware/DCA1000_Streaming). Make sure you use the firmware in the IWR_Demos folder if streaming data directly from the IWR

#### [IWR1443] IWR Streaming
1. Power off the IWR1443, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR_SOP_Modes](../readme_images/IWR_SOP_modes.png)
3. Use the Uniflash tool to install the mmWave SDK found as part of the [TI mmWave SDK 2.01.00.04](https://www.ti.com/tool/download/MMWAVE-SDK/02.01.00.04)

#### [IWR1843] DCA Streaming and IWR Demos
1. Power off the IWR1843, and place it into Flashing Mode mode. Refer to the following diagram for placing the IWR in flashing mode ![IWR1843_Modes](../readme_images/IWR1843_SOP_nodes.png)
2. For the IWR1843 (or any radar that can run the mmWave SDK boost, you should be able to load the default "demo" firmware provided by TI onto the board to stream samples to the DCA1000 board.)

    a.We developed this pipeline using mmWave 3.6. Using a different pipeline may require slight changes in the code.
    b. NOTE: additional documentation on the demo firmware can be found in the index.html file located in (ti/mmwave_sdk_03_06_02_00-LTS/packages/ti/demo/xwr18xx/mmw/docs/doxygen/html)


#### [AWR2243 2-chip cascade] IWR Demo (serial TLV)
The cascade EVM (AM273x + 2× AWR2243) runs TI's 2-chip cascade DDM demo. Build and flash it with the
[`CPSL_TI_Radar_Firmware_Dev`](https://github.com/davidmhunt/CPSL_TI_Radar_Firmware_Dev) repo
(`scripts/flash_cascade.sh`, J6 jumper on the bottom pins to flash and on the top pins to run), then check it with
`scripts/cascade_serial_check.py` before using this driver.

Once the correct firmware is flashed onto your board, power cycle the board and place it into functional mode.

## Architecture

The C++ code is organized as follows:

```
main.cpp
  └── Runner
        ├── SystemConfigReader   — parses JSON system config
        ├── RadarConfigReader    — parses IWR .cfg, computes bytes_per_frame
        ├── CLIController        — sends .cfg commands over serial to the IWR
        ├── DCA1000Handler       — thin coordinator; owns the three classes below
        │     ├── DCA1000Socket      — UDP socket lifecycle, SCHED_RR 99 RX thread,
        │     │                        lock-free ring buffer for decoupled packet reception
        │     ├── FrameAssembler     — sequence checking, drop detection, frame assembly
        │     └── ADCCubeConverter   — interleaved (IWR1443) and non-interleaved
        │                              (IWR1843/IWR6843) ADC cube conversion
        └── SerialStreamer        — serial TLV stream → detected points
```

`Runner` spawns two threads (`run_dca1000`, `run_serial`). The `DCA1000Socket` RX thread runs at real-time priority (SCHED_RR 99) and pushes raw packets into a 512-slot ring buffer; the worker thread pops packets, assembles frames via `FrameAssembler`, and converts to the ADC cube via `ADCCubeConverter`. Frames are signaled via `new_frame_available` (mutex-protected); consumers call `get_next_adc_cube(timeout_ms)`.

## Running

To run the cpp code, perform the following:
1. update the .json config file
2. run the c++ code

### 1. Updating the .json config files

The driver reads a **system config** (JSON, schema v2) that names a **board descriptor** and a
**radar `.cfg`**. The tracked system configs are in [config/system](./config/system/). Loading is
strict: an unknown key, a wrong type or a repeated key is an error that names the JSON path. A v1
file (no `"schema_version"`) is rejected with the command that converts it (see the README's
v1 -> v2 migration section).

```json
{
    "schema_version": 2,
    "board": "IWR1843",
    "board_overrides": {},
    "radar_cfg": "../radar/nav_configs/1843_stress_test.cfg",
    "cli": { "port": "/dev/ttyACM0" },
    "serial_stream": { "enabled": false, "port": "/dev/ttyACM1" },
    "dca1000": { "enabled": true, "fpga_ip": "192.168.33.180", "host_ip": "192.168.33.30",
                 "cmd_port": 4096, "data_port": 4098, "rcvbuf_bytes": 67108864 },
    "output": { "dir": "out/front_radar", "save_adc_frames": true, "save_raw_lvds": false },
    "runtime": { "log_level": "info" }
}
```

| Key | Required | Meaning |
|-----|----------|---------|
| `schema_version` | yes | `2` |
| `board` | yes | A board name (`IWR1443`, `IWR1843`, `IWR6843`, `AWR2243_CASCADE`), looked up as `<boards dir>/<name>.json`: the boards dir is `$CPSL_TI_RADAR_BOARDS_DIR` if set, otherwise `../boards` next to the JSON file (the layout of `config/`). Or a path to a descriptor file (relative to the JSON file). |
| `board_overrides` | no | Deep-merged over the descriptor, then validated like it. Baud rates and timeouts live here, for example `{"cli": {"cmd_timeout_ms": 300}, "data_uart": {"baud": 3125000, "timeout_ms": 5000}}`. |
| `radar_cfg` | yes | The TI `.cfg` sent to the radar. Relative paths resolve against the JSON file's directory; the tracked configs use `../radar/<subdir>/<file>.cfg`. |
| `cli.port` | yes | CLI serial port (usually the lower-numbered `/dev/ttyACM*`; [determine_serial_ports.ipynb](../utilities/determine_serial_ports.ipynb) lists them). |
| `serial_stream.enabled`, `.port` | no | TLV point cloud from the demo over the data UART. `port` is required when enabled. The section may be omitted when off. |
| `dca1000.enabled`, `.fpga_ip`, `.host_ip`, `.cmd_port`, `.data_port` | no | Raw ADC through the DCA1000. The four address fields are required when enabled; the section may be omitted when off. |
| `dca1000.rcvbuf_bytes` | no | `SO_RCVBUF` requested for the data socket (default 67108864; see the host settings above). |
| `output.dir` | no | Where `adc_data.bin` and `LVDS_Raw_0.bin` are written, relative to the JSON file. Unset: the current directory. |
| `output.save_adc_frames` | no | Write every ADC frame to `adc_data.bin` (default `false`). |
| `output.save_raw_lvds` | no | Write the raw LVDS payload to `LVDS_Raw_0.bin` (default `false`; only needed to debug packet loss). |
| `runtime.log_level` | no | `error`, `warn`, `info` (default) or `debug`. `debug` prints the per-frame status lines (the v1 `"verbose": true`) and each skipped cfg command. |
| `runtime.frame_queue_depth`, `.stall_timeout_ms`, `.rx_cpu`, `.worker_cpu`, `.rx_priority`, `.worker_priority` | no | **Reserved**: validated (defaults 4, 0, `null`, `null`, 99, 80) but not applied yet. |

At least one of `serial_stream` and `dca1000` must be enabled.

Notes on the radar `.cfg` for DCA1000 streaming with the mmWave SDK demos (for example SDK 3.5 on
the IWR1843): `lvdsStreamCfg -1 0 1 0` streams ADC samples only. `lvdsStreamCfg -1 1 1 1` also
enables the LVDS header and SW data, which costs extra processing and streaming time. The
load-time cross-check requires `dataFmt` (third field) to be 1, ADC.
With SDK 3+ and a single Rx, use an even number of ADC samples, and use 1, 2 or 4 receivers.

#### Board descriptors
[`config/boards/`](./config/boards/) holds one descriptor per board. It gives the board's CLI
handshake, cfg field layout (`cfg_dialect`), data-UART baud/timeout/TLV format, LVDS lanes,
layout and I/Q order, DCA1000 packet settings, and whether the demo accepts a cfg only once per
boot. [`config/boards/README.md`](./config/boards/README.md) cites the source of every value.
Every board-specific behaviour in the driver comes from these files, so adding or tuning a board
with a known wire format is a data change, not a rebuild.

| Board | LVDS lanes | ADC layout | Serial TLV |
|---|---|---|---|
| `IWR1843` | 2 | `two_lane_iq_pairs` (non-interleaved, SDK 3+) | yes |
| `IWR6843` | 2 | `two_lane_iq_pairs` (non-interleaved, SDK 3+) | yes |
| `IWR1443` | 4 | `lane_per_rx` (interleaved, SDK 2) | rejected until the SDK 2 format is confirmed |
| `AWR2243_CASCADE` | not supported yet | — | yes (3,125,000 baud) |

At load time the driver cross-checks the radar `.cfg` against the board (16-bit complex ADC,
`adcbufCfg` interleave vs the LVDS layout, `lvdsStreamCfg` ADC streaming) and refuses a mismatch
with a message. `cfg_dialect.skip_commands` lists cfg commands the board's firmware rejects. They
stay in the `.cfg` file but are never sent: the IWR1843 skips `calibData`.

##### AWR2243 cascade notes
* Use [`radar_0_AWR2243_cascade_serial.json`](./config/system/radar_0_AWR2243_cascade_serial.json) with
  [`cascade_shortrange.cfg`](./config/radar/cascade/cascade_shortrange.cfg). Replace the port paths
  with the EVM's `/dev/serial/by-id/...` paths. Use the Application/User UART for the CLI and the other port for data.
  The descriptor sets the 5000 ms command timeout and the 3,125,000 baud data port.
* **Configure only once per boot.** TI doesn't support stopping the cascade demo and sending a new config. Power-cycle
  the EVM before every run. If any config command isn't acknowledged, the driver doesn't start and prints a
  power-cycle reminder (`lifecycle.config_once_per_boot`).
* `channelCfg` has 5 fields (`<rxMaster> <txMaster> <cascading> <rxSlave> <txSlave>`), so the Rx count is master + slave (8).
  `frameCfg` adds `<numAdcSamples>` before the frame period. The descriptor's `cfg_dialect` says so.
* DCA1000 streaming is rejected for this board until 4-lane LVDS capture is added.
* TI has only tested up to 192 ADC samples, 256 chirps, and 8 Rx channels. BFP compression isn't supported.
* Like the other boards, a frame is only handed over when the next frame's magic word arrives, so the newest point
  cloud is one frame period old.

### 2. Radar .cfg file

Several sample .cfg files are located in the [config/radar](./config/radar/) folder. For generating additional configurations, we recommend using the [TI mmWave Demo Visualizer](https://dev.ti.com/gallery/view/mmwave/mmWave_Demo_Visualizer/ver/2.1.0/). There, you can specify settings, and then use the "Save config to PC" button to download a configuration. To fully understand the configurations, please refer to the mmWave sdk documentation. 
* To understand a particular configuration, there are a few helpful notebooks located in the [utilities](../utilities/) folder including the [print_config](../utilities/print_config.ipynb) notebook which will parse the config and print its commands. 


### 3. Run the project

The system config path is a required argument:

```bash
cd CPSL_TI_Radar/CPSL_TI_Radar_cpp/build

# check a config without hardware: loads the board descriptor and radar cfg, runs the
# cross-checks, prints the board, ports, frame shape, bytes/frame and skipped commands;
# opens no port or socket; exit 0 if usable, 1 otherwise
./CPSL_TI_Radar_CPP ../config/system/front_radar_IWR1843_stress_test.json --validate

# run it
./CPSL_TI_Radar_CPP ../config/system/front_radar_IWR1843_stress_test.json
```

Running without an argument prints the usage and exits with status 2. The executable prints the
config path at startup so you can confirm which file is loaded. A rebuild is only needed after
changes to source code: switching configs or editing a board descriptor does not require recompiling.
