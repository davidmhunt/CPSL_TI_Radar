# CPSL_TI_Radar_ROS2

ROS2 packages for integrating TI mmWave radars (IWR1443, IWR1843, IWR6843) with the [CPSL_TI_Radar C++ library](https://github.com/davidmhunt/CPSL_TI_Radar). Supports both serial TLV point-cloud streaming and raw ADC capture via a DCA1000 capture card.

## Packages

| Package | Description |
|---------|-------------|
| `raw_radar_msgs` | Custom message definitions: `ADCDataCube` (raw ADC samples as int16 arrays) |
| `ti_radar_connect` | Driver node — connects to IWR radar and/or DCA1000, publishes point clouds or ADC cubes |

## Prerequisites

1. **C++ library dependencies** — follow the "Pre-requisite packages" instructions in the [CPSL_TI_Radar_cpp README](./src/ti_radar_connect/include/CPSL_TI_Radar/CPSL_TI_Radar_cpp/Readme.md).

2. **Serial port access** — add your user to the `dialout` group (log out and back in after):
   ```bash
   sudo usermod -a -G dialout $USER
   ```

3. **DCA1000 high-rate streaming** — raise the kernel UDP receive buffer cap before running:
   ```bash
   sudo sysctl -w net.core.rmem_max=134217728
   ```
   To make permanent:
   ```bash
   echo 'net.core.rmem_max=134217728' | sudo tee /etc/sysctl.d/99-radar.conf
   sudo sysctl -p /etc/sysctl.d/99-radar.conf
   ```

## Build

This package is used as part of the [CPSL_ROS2_Sensors](https://github.com/cpsl-research/CPSL_ROS2_Sensors) workspace. Follow the build instructions in that repo's README. Build these packages first:

```bash
eval $(poetry env activate)
python -m colcon build --packages-select raw_radar_msgs --symlink-install
python -m colcon build --packages-select ti_radar_connect --symlink-install
source install/setup.$(basename $SHELL)
```

## Launch

Each radar is launched individually via `connect_ti_radar_launch.py`:

```bash
ros2 launch ti_radar_connect connect_ti_radar_launch.py \
    config_file:=radar_0_IWR1843_vel_sr.json \
    radar_name:=radar_0 \
    tf_prefix:=cpsl_ugv_1 \
    stamp_delay_sec:=0.1
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `config_file` | `radar_0_IWR1843_demo.json` | Bare filename from `config/system/` |
| `radar_name` | `Radar_0` | Topic namespace and TF frame ID |
| `stamp_delay_sec` | `0.0` | Header timestamp offset in seconds |
| `tf_prefix` | `''` | Prefix prepended to the TF frame ID |

In practice, radars are launched from a higher-level bringup file (e.g. `ugv_sensor_bringup.launch.py`) rather than directly.

## Topics Published

All topics are scoped under `<radar_name>/`:

| Topic | Type | Description |
|-------|------|-------------|
| `<radar_name>/detected_points` | `sensor_msgs/PointCloud2` | Detected point cloud (serial streaming) |
| `<radar_name>/adc_data_cube` | `raw_radar_msgs/ADCDataCube` | Raw ADC samples (DCA1000 only) |
| `<radar_name>/adc_meta` | `raw_radar_msgs/ADCChirpMeta` | SAR per-chirp metadata; only when `publish_chirp_meta` is true (see below) |
| `<radar_name>/radar_config_path` | `std_msgs/String` | Path to the active JSON config |

## Configuration Files

Two files are needed for each radar:

### Adding or customising configs

The accessible config location is:
```
src/ti_radar_connect/config/
├── system/   ← add or edit JSON system configs here
└── radar/
    └── nav_configs/   ← add new .cfg chirp profiles here
```

This location is pre-populated with the 11 configs used by the CPSL_ROS2_Sensors bringup launch files. Files here are installed after the upstream submodule configs, so a file with the same name in this location overrides the submodule default.

The full set of upstream configs (37 JSON + all `.cfg` files) is still available deep in the submodule at `src/ti_radar_connect/include/CPSL_TI_Radar/CPSL_TI_Radar_cpp/config/` for reference.

### v2 driver and config schema (`release/v2.0`)

On this branch `ti_radar_connect` drives the radar through the CPSL_TI_Radar v2 library (`cpsl::radar::Radar`, linked as `CPSL_TI_Radar::driver`). The v2 driver only reads **schema-v2** system configs (`schema_version: 2`, `board`, `firmware`, `cli`, `serial_stream`, `dca1000`, ...); it rejects the v1 shape shown below, and the node then exits non-zero with the driver's message.

- **Ported (schema v2):** `config/system/radar_0_IWR1843_SAR_2ms_fmt2.json` (IWR1843 with the `iwr1843_sar_lvds` firmware, LVDS ADC via a DCA1000, 1 TX / 1 RX, 3300 samples, 255 chirps, per-chirp metadata format `dataFmt 2`). It is the launch file's default `config_file`.
- **v1 schema, not ported:** every other file in `config/system/` (the `*_docker.json` pairs and all `front_/back_/down_/radar_N_*` configs). They stay as they were; convert one with `tools/migrate_config_v1_to_v2.py --add-firmware` from the CPSL_TI_Radar repo before use.
- The install tree now also carries the library's `config/boards`, `config/firmware` and `config/limits` beside `config/system`; the driver resolves them relative to the system JSON.

On a fault the node fails loudly: a config that cannot be loaded, a port/socket that cannot be opened (the message names it, e.g. `cannot open the CLI port /dev/ttyACM0`), a rejected configure, or a failed start logs an error and exits with a non-zero code. An `already_configured` result (board configured earlier in the same process) is only a warning. A frame stall is logged by the driver and the node keeps running. `frames_overwritten` and the other counters are logged once per second at debug level and at shutdown at info level.

`header.stamp` of every message is ROS time derived from the frame's steady-clock completion time (the steady-to-ROS offset is taken once at start), minus `stamp_delay_sec`.

### No point cloud on the SAR firmware

The `iwr1843_sar_lvds` firmware has no on-chip detection and no data UART, so there is no point cloud. When the loaded config has `serial_stream.enabled: false` the node creates **no** `detected_points` publisher, starts no point-cloud read, logs once at info `point cloud disabled: ...` and runs ADC-only; it never waits for points. Only configs whose firmware has a data UART (for example `demo`) with `serial_stream.enabled: true` publish `detected_points`.

### SAR per-chirp metadata

With the `iwr1843_sar_lvds` firmware and a radar cfg using `lvdsStreamCfg ... dataFmt 2` (the shipped `radar_0_IWR1843_SAR_2ms_fmt2.json` does), every chirp carries a metadata record next to its ADC samples. The node can publish it as `raw_radar_msgs/ADCChirpMeta` on **`<radar_name>/adc_meta`**, one message per cube.

It is **off by default**, in every config. Enable it with the ROS parameter `publish_chirp_meta`:

```
ros2 launch ti_radar_connect connect_ti_radar_launch.py publish_chirp_meta:=true
# or on the node directly:  --ros-args -p publish_chirp_meta:=true
```

The parameter is read at start; to change it, restart the node. When it is false, or the config does not stream metadata (firmware without dataFmt 2), no publisher is created and the node logs one info line saying which (`chirp metadata disabled: ...`); the topic is simply absent.

Fields (`ADCChirpMeta.msg`; every per-chirp array has one entry per chirp, so index `i` is chirp `i` of the cube's `chirp` dimension):

| Field | Meaning |
|-------|---------|
| `header` | same `stamp` and `frame_id` as the cube |
| `frame_index` | driver frame counter (32-bit) |
| `record_valid[]`, `adc_complete[]` | record passed validation (else its fields are 0); all ADC bytes of the chirp arrived |
| `flags[]` | `0x1` sat valid, `0x2` sat monitor on, `0x4` late, `0x8` skip, `0x10` resync |
| `global_chirp_idx[]`, `run_idx[]`, `ts_ticks[]` | firmware chirp counter, run index, chirp start in 10 ns ticks since boot |
| `sat_slices[]`, `sat_ref_lag[]` | saturation result of chirp `global_chirp_idx - sat_ref_lag` (not this chirp) |
| `sat_slices_aligned[]` | this chirp's own saturated slices, -1 unknown |
| `has_time[]`, `time_interpolated[]`, `t_s[]` | seconds since the run's first valid record; interpolated when the record was invalid |
| `prev_tail_sat[2]` | saturation results for the previous frame's last two chirps (-1 none) |
| `run_known`, `run_idx_frame`, `records_valid/invalid/other_run` | per-frame record counts and the run |

Matching to the cube: the metadata message is published right after its `ADCDataCube` with an identical `header.stamp` and `frame_id`; pair them on the stamp. `frame_index` is the driver's per-frame counter (it increases by one per frame), so a jump between consecutive metadata messages shows frames the driver or a subscriber lost.

Why a sibling message: `ADCDataCube.msg` is unchanged, so its type hash and every existing subscriber (console, dataset_generator) keep working; added fields would change the type for all of them.

### 1. JSON system config, v1 shape (`config/system/*.json`, v1 files only)

Specifies serial ports, DCA1000 network settings, streaming mode, and points to the radar `.cfg` file:

```json
{
    "verbose": false,
    "TI_Radar_Config_Management": {
        "TI_Radar_config_path": "../radar/nav_configs/1843_vel_sr.cfg"
    },
    "CLI_Controller": {
        "CLI_port": "/dev/ttyACM0"
    },
    "Streamer": {
        "serial_streaming": {
            "enabled": true,
            "data_port": "/dev/ttyACM1"
        },
        "DCA1000_streaming": {
            "enabled": false,
            "FPGA_IP": "192.168.33.180",
            "system_IP": "192.168.33.30",
            "data_port": 4098,
            "cmd_port": 4096
        },
        "save_to_file": false,
        "board_type": "IWR1843"
    }
}
```

`TI_Radar_config_path` accepts **relative paths** (resolved relative to the JSON file's location) or absolute paths. All configs in `config/system/` use portable relative paths of the form `../radar/<subdir>/<file>.cfg`.

### 2. Radar `.cfg` file (`config/radar/`)

TI mmWave SDK chirp configuration. Must include `lvdsStreamCfg -1 0 1 0` when using DCA1000. Sample configs are organized under `config/radar/nav_configs/`, `config/radar/DCA1000/`, etc.

## Coordinate Frame Note

TI radars output point clouds in **East-North-Up (ENE)** convention. A 90° rotation is required to align with the ROS standard **Forward-Left-Up (FLU)** frame. This rotation is defined in the platform URDF (under `platform_descriptions/urdf/`), not in this driver.
