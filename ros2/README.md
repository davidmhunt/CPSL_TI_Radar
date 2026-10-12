# ROS 2 packages (`ros2/`)

Two colcon packages that drive a TI radar from ROS 2 through the CPSL_TI_Radar v2 driver
(`CPSL_TI_Radar_cpp/`, compiled in by CMake; there is nothing separate to install).

| Package | What it is |
|---------|------------|
| `raw_radar_msgs` | Messages: `ADCDataCube` (raw ADC samples, int16 arrays) and `ADCChirpMeta` (SAR per-chirp metadata) |
| `ti_radar_connect` | The driver node `ti_radar_connect` and the launch file `connect_ti_radar_launch.py` |

Topics, all under `<radar_name>/` (default `Radar_0`):

| Topic | Type | When |
|-------|------|------|
| `adc_data_cube` | `raw_radar_msgs/ADCDataCube` | DCA1000 streaming enabled in the config |
| `adc_meta` | `raw_radar_msgs/ADCChirpMeta` | only with `publish_chirp_meta:=true` (see below) |
| `detected_points` | `sensor_msgs/PointCloud2` | only firmware with a data UART and `serial_stream.enabled: true` (e.g. `demo`) |
| `radar_config_path` | `std_msgs/String` | always: path of the active JSON config |

## Build standalone

Needs ROS 2 Jazzy, `colcon`, a C++ compiler and `cmake`. From a fresh workspace:

```bash
mkdir -p ws/src && cd ws/src
git clone -b feature/ros2 https://github.com/davidmhunt/CPSL_TI_Radar.git
git -C CPSL_TI_Radar submodule update --init CPSL_TI_Radar_cpp/include/json
cd .. && source /opt/ros/jazzy/setup.bash
colcon list --base-paths src        # expect exactly raw_radar_msgs and ti_radar_connect
colcon build --base-paths src --symlink-install
source install/setup.bash
```

Initialise only `CPSL_TI_Radar_cpp/include/json` (the JSON header library the driver needs).
Do **not** initialise the other submodules: `firmware_dev` (firmware build environment), `shipped_firmware/.../iwr_raw_rosnode` and `.friday`
(project tooling) are not used by the build.
`CPSL_TI_Radar_cpp/COLCON_IGNORE` keeps colcon from listing the C++ tree as a third package.

## Run

```bash
ros2 launch ti_radar_connect connect_ti_radar_launch.py \
    config_file:=radar_0_IWR1843_SAR_2ms_fmt2.json radar_name:=Radar_0 publish_chirp_meta:=true
```

| Launch argument | Default | Meaning |
|-----------------|---------|---------|
| `config_file` | `radar_0_IWR1843_SAR_2ms_fmt2.json` | bare filename in `install/ti_radar_connect/share/ti_radar_connect/config/system/` |
| `radar_name` | `Radar_0` | topic namespace and frame id |
| `tf_prefix` | `''` | prefix for the frame id |
| `stamp_delay_sec` | `0.0` | subtracted from every `header.stamp` |
| `publish_chirp_meta` | `false` | publish `<radar_name>/adc_meta` |

The launch file passes the full path to the node as the ROS parameter `config_path`; to run the
node directly: `ros2 run ti_radar_connect ti_radar_connect --ros-args -p config_path:=<full path>`.

Configs come from `CPSL_TI_Radar_cpp/config/` (installed into `share/.../config/`) with
`ros2/ti_radar_connect/config/` installed on top, so a same-named file there wins. The shipped SAR
config has `cli.port` `/dev/ttyACM0`. For now: copy the system JSON in the same directory and edit
the ports (and `dca1000.host_ip`) in the copy.

The v1 configs still under `ros2/ti_radar_connect/config/system/` (every file except
`radar_0_IWR1843_SAR_2ms_fmt2.json`) are v1 schema, not loadable by v2; convert with
`tools/migrate_config_v1_to_v2.py --add-firmware`.

A node that cannot load its config or open a port logs the reason (e.g. `cannot open the CLI port
...`) and exits 1; the launch file reports the process died.

## SAR firmware: no point cloud, optional per-chirp metadata

The `iwr1843_sar_lvds` firmware has no on-chip detection and no data UART, so no `detected_points`
publisher exists; the node logs `point cloud disabled: ...` and runs ADC-only.

With `lvdsStreamCfg ... dataFmt 2` in the radar cfg (the shipped SAR config has it), each chirp
carries a metadata record. `publish_chirp_meta:=true` (off by default) publishes one `ADCChirpMeta`
per cube on `<radar_name>/adc_meta`, right after its `ADCDataCube` with the same `header.stamp`.
The log then says `chirp metadata enabled: publishing Radar_0/adc_meta`; when it is off, or the
config has no `dataFmt 2`, the topic is absent. The parameter is read at start.

| Field (per chirp unless noted) | Meaning |
|--------------------------------|---------|
| `frame_index` (per cube) | driver frame counter; a jump between messages means lost frames |
| `record_valid`, `adc_complete` | record passed validation; all ADC bytes arrived |
| `flags` | `0x1` sat valid, `0x2` sat monitor on, `0x4` late, `0x8` skip, `0x10` resync |
| `global_chirp_idx`, `run_idx`, `ts_ticks` | firmware chirp counter, run, start time (10 ns ticks since boot) |
| `sat_slices`, `sat_ref_lag`, `sat_slices_aligned` | saturation results; see `ros2 interface show raw_radar_msgs/msg/ADCChirpMeta` |
| `has_time`, `time_interpolated`, `t_s` | seconds since the run's first valid record |

## Add the radar to another colcon workspace

Example: CPSL_ROS2_Sensors, which carries this repo as the submodule `src/CPSL_TI_Radar`.

```bash
cd CPSL_ROS2_Sensors
git submodule init src/CPSL_TI_Radar && git submodule update src/CPSL_TI_Radar
git -C src/CPSL_TI_Radar submodule update --init CPSL_TI_Radar_cpp/include/json
source /opt/ros/jazzy/setup.bash
colcon build --base-paths src --symlink-install --packages-select raw_radar_msgs ti_radar_connect
```

Those are the commands of its `scripts/install.sh` and of console's Sensors picker (Settings >
Sensors > radar: it inits the submodule plus the json one, then runs the `colcon build` line above).
`scripts/deps/radar.sh` has no system dependencies; `rosdep install --from-paths src` covers the rest.
For your own workspace, add this repo under `src/` the same way and keep the json-only init.
If you moved the sources from an older path, delete `build/raw_radar_msgs` and `build/ti_radar_connect`
first (colcon's CMake cache refuses a moved source directory).

## Host prerequisites

Serial access (`dialout` group), the DCA1000 NIC address and the UDP receive buffer are host
settings, not ROS ones. Check and fix them with `uv run tools/setup/host_setup.py --nic <if>`
(add `--apply` to fix; `--dry-run` shows the commands first); details in
[`CPSL_TI_Radar_cpp/Readme.md`](../CPSL_TI_Radar_cpp/Readme.md).
