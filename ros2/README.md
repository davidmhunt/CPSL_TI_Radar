# ROS 2 packages (`ros2/`)

Two colcon packages that drive a TI radar from ROS 2 through the CPSL_TI_Radar v2 driver (`CPSL_TI_Radar_cpp/`, compiled in by CMake; nothing separate to install). This is the package reference; the build-launch-echo walkthrough, with the ROS 2 install links, is [tutorial 6](../docs/tutorials/06_ros2.md).

| Package | What it is |
|---------|------------|
| `raw_radar_msgs` | Messages: `ADCDataCube` (raw ADC samples, int16 arrays) and `ADCChirpMeta` (SAR per-chirp metadata) |
| `ti_radar_connect` | The driver node `ti_radar_connect` and the launch file `connect_ti_radar_launch.py` |

Topics, all under `<radar_name>/` (default `Radar_0`):

| Topic | Type | When |
|-------|------|------|
| `adc_data_cube` | `raw_radar_msgs/ADCDataCube` | DCA1000 streaming enabled in the config |
| `adc_meta` | `raw_radar_msgs/ADCChirpMeta` | only with `publish_chirp_meta:=true` (below) |
| `detected_points` | `sensor_msgs/PointCloud2` | only firmware with a data UART and `serial_stream.enabled: true` (e.g. `demo`) |
| `radar_config_path` | `std_msgs/String` | always: path of the active JSON config |

## Build and run

Build in a plain workspace as in [tutorial 6](../docs/tutorials/06_ros2.md): clone this repo under `ws/src/`, `git submodule update --init CPSL_TI_Radar_cpp/include/json` (the only submodule used; `CPSL_TI_Radar_cpp/COLCON_IGNORE` keeps colcon from listing the C++ tree as a package), then `colcon build --base-paths src --symlink-install`.

```bash
ros2 launch ti_radar_connect connect_ti_radar_launch.py config_file:=<name or absolute path> radar_name:=Radar_0
```

| Launch argument | Default | Meaning |
|-----------------|---------|---------|
| `config_file` | `IWR1843_iwr1843_sar_lvds_SAR_2ms_fmt2.json` | setup name in `install/ti_radar_connect/share/ti_radar_connect/config/system/`; an absolute path also works |
| `radar_name` | `Radar_0` | topic namespace and frame id |
| `tf_prefix` | `''` | prefix for the frame id |
| `stamp_delay_sec` | `0.0` | subtracted from every `header.stamp` |
| `publish_chirp_meta` | `false` | publish `<radar_name>/adc_meta` |

The launch file passes the full path to the node as the ROS parameter `config_path`; to run the node directly: `ros2 run ti_radar_connect ti_radar_connect --ros-args -p config_path:=<full path>`. Configs come from `CPSL_TI_Radar_cpp/config/` (installed into `share/.../config/`). Shipped configs name the lab's ports (the SAR default uses `/dev/ttyACM0`): copy one into `config/user/`, edit the ports (and `dca1000.host_ip`), and pass its absolute path. A node that cannot load its config or open a port logs the reason and exits 1.

## SAR firmware: no point cloud, optional per-chirp metadata

The `iwr1843_sar_lvds` firmware has no on-chip detection and no data UART, so there is no `detected_points` publisher; the node logs `point cloud disabled: ...` and runs ADC-only. With `lvdsStreamCfg ... dataFmt 2` in the radar cfg (the shipped SAR config has it), each chirp carries a metadata record, and `publish_chirp_meta:=true` publishes one `ADCChirpMeta` per cube on `<radar_name>/adc_meta`, right after its `ADCDataCube` with the same `header.stamp`. Without `dataFmt 2` the topic is absent. The parameter is read at start. Fields: `ros2 interface show raw_radar_msgs/msg/ADCChirpMeta`.

| Field (per chirp unless noted) | Meaning |
|--------------------------------|---------|
| `frame_index` (per cube) | driver frame counter; a jump between messages means lost frames |
| `record_valid`, `adc_complete` | record passed validation; all ADC bytes arrived |
| `flags` | `0x1` sat valid, `0x2` sat monitor on, `0x4` late, `0x8` skip, `0x10` resync |
| `global_chirp_idx`, `run_idx`, `ts_ticks` | firmware chirp counter, run, start time (10 ns ticks since boot) |
| `has_time`, `time_interpolated`, `t_s` | seconds since the run's first valid record |

## Add the radar to another colcon workspace

Put this repo under that workspace's `src/` (a git submodule works), initialise only `CPSL_TI_Radar_cpp/include/json`, then build the two packages. If you moved the sources from an older path, delete `build/raw_radar_msgs` and `build/ti_radar_connect` first (colcon's CMake cache refuses a moved source directory).

```bash
source /opt/ros/jazzy/setup.bash
colcon build --base-paths src --symlink-install --packages-select raw_radar_msgs ti_radar_connect
```
