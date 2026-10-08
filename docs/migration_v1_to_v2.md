# v1 -> v2 migration

For anyone moving from the v1 code or configs. New users can skip this page.

v2.0 is a rework and may break v1 interfaces. The old top-level `Firmware/` folder is now `shipped_firmware/<BOARD>/<fw>/` ([`shipped_firmware/README.md`](../shipped_firmware/README.md)), and `tools/radar_viewer/` is replaced by the GUI (`radar_gui/`). Removed from the tree (all recoverable from git history; the last commit that contained `archived_code/` is `4cc80474927025ff7935ddb1bb1f09ed78e0ca2d`):

- `archived_code/` — the v1 Python DCA1000/serial driver (`CPSL_TI_Radar_py`, `ConfigManager`, conda environments), early C++ prototypes, and the superseded `DCA1000Runner`. Use the C++ driver in `CPSL_TI_Radar_cpp/`; `cpsl::radar::Radar` replaces `DCA1000Runner` (see "Library" below).
- `MAIN_NO_RUNNER` executable (`main_no_runner.cpp`) — only `CPSL_TI_Radar_CPP` is built now.
- `utilities/Postprocess_adc_data.py` and `utilities/bartlet.ipynb` — depended on removed v1 modules or v1 capture files. The remaining notebooks no longer import `ConfigManager`; they parse the `.cfg` directly.
- CMake package renamed: `find_package(CPSL_TI_Radar_CPP)` / `CPSL_TI_Radar_CPP::<target>` is now `find_package(CPSL_TI_Radar)` / `CPSL_TI_Radar::driver`. A deprecated `CPSL_TI_Radar_CPP` compatibility package (old target names as aliases, with a deprecation message) is installed for one release and then removed. See `CPSL_TI_Radar_cpp/Readme.md`.
- Generated/stray files: `generated_config.json`, `config/radar/IWR_Demos/generated_config.{cfg,json}` and `jsonconfig.json` (outputs of the v1 `ConfigManager`), the empty root `build/`, and the tracked `CPSL_TI_Radar_cpp/.vscode/`.
- `planning/current_plan.md` — all phases done or superseded; the cascade plan is kept in `docs/archive/CASCADE_PLAN.md`.

## System configs (schema v2)

v2 system configs carry `"schema_version": 2` and name a board descriptor (`"board": "IWR1843"`,
from `CPSL_TI_Radar_cpp/config/boards/`) and the firmware it runs (`"firmware": "demo"`, from
`CPSL_TI_Radar_cpp/config/firmware/`; required, see the key table in `CPSL_TI_Radar_cpp/Readme.md`). The driver rejects a v1 file (no `schema_version`) and
names the script that converts it. All tracked configs in `CPSL_TI_Radar_cpp/config/system/` are
already converted. To convert your own:

```bash
uv run tools/migrate_config_v1_to_v2.py my_config.json              # print the v2 JSON, write nothing
uv run tools/migrate_config_v1_to_v2.py my_configs/ --in-place      # rewrite every v1 *.json in a directory
uv run tools/migrate_config_v1_to_v2.py my_configs/ --check         # exit 1 if any file is still v1
```

A v2 file without `firmware` (every `config/user/*.json` made before it was required) is refused by the driver; add it with
`uv run tools/migrate_config_v1_to_v2.py my_config.json --add-firmware --in-place` (`--check` lists files still missing it), or with the
GUI Radar tab's **Add firmware** button.

The script is idempotent (v2 files are left alone) and reports any key it cannot map instead of
converting that file.

| v1 key | v2 key | Note |
|---|---|---|
| `verbose` | `runtime.log_level` | `true` -> `"debug"`, `false` -> `"info"`; optional in v2 |
| `TI_Radar_Config_Management.TI_Radar_config_path` | `radar_cfg` | same relative path |
| `CLI_Controller.CLI_port` | `cli.port` | |
| `CLI_Controller.baud_rate`, `.cmd_timeout_ms` | `board_overrides.cli.baud`, `.cmd_timeout_ms` | default from the board descriptor |
| `Streamer.serial_streaming.enabled`, `.data_port` | `serial_stream.enabled`, `.port` | section optional when disabled |
| `Streamer.serial_streaming.baud_rate`, `.timeout_ms` | `board_overrides.data_uart.baud`, `.timeout_ms` | default from the board descriptor |
| `Streamer.DCA1000_streaming` | `dca1000` | `FPGA_IP` -> `fpga_ip`, `system_IP` -> `host_ip`; `cmd_port`, `data_port` unchanged; section optional when disabled |
| — | `dca1000.rcvbuf_bytes` | new, default 64 MB (was fixed) |
| `Streamer.save_to_file` | `output.save_adc_frames` + `output.save_raw_lvds` | the script sets `save_raw_lvds` to `false`: the raw LVDS file is now opt-in |
| — | `output.dir` | new; output files were always written to the current directory, which is still the default |
| `Streamer.board_type` | `board` | names a descriptor; the v1 `SDK_version` fallback (2.x -> IWR1443, 3.x -> IWR1843) is applied by the script |
| `Streamer.SDK_version` | removed | the descriptor carries the SDK |
| `Processor`, `ROS`, `Listeners` | removed | never read by the driver |
| — | `runtime.*` | new; `log_level`, `stall_timeout_ms`, `frame_queue_depth`, and the affinity/priority keys `rx_cpu`, `worker_cpu`, `rx_priority`, `worker_priority` (core-15) |

Behaviour changes that come with v2 configs:

- **`calibData` is sent on every board, including the IWR1843.** The stock SDK 3.6 demo needs it
  as part of the "full configuration": without it `sensorStart` fails with `Error -1` and no
  frames stream. An older flashed IWR1843 image answered `'calibData' is not recognized`; on such
  a board a config can drop the command with
  `"board_overrides": {"cfg_dialect": {"skip_commands": ["calibData"]}}`
  (`cfg_dialect.skip_commands`).
- The radar `.cfg` is cross-checked against the board when the config loads (16-bit complex ADC,
  `adcbufCfg` interleave vs the LVDS layout, `lvdsStreamCfg` ADC streaming), and a mismatch stops
  the driver with a message.

## Command line

`CPSL_TI_Radar_CPP <system.json>` now requires the config path; the built-in default config is
gone. Add `--validate` to check a config without hardware: it prints the board, ports, frame
shape, bytes per frame, `output.dir` and skipped commands, and exits 0 or 1 without opening any
port or socket. `--frames N` and `--duration S` end a run; `--stats` prints a versioned
`stats v1` counter line per stream every second (see `CPSL_TI_Radar_cpp/Readme.md`).

## Library

`Runner` is replaced by `cpsl::radar::Radar` (`RadarConfig::load` → `Radar::open` → `configure` →
`start` → `next_adc_frame` / `next_point_cloud` → `stop`). Calls return a `Status` instead of
printing or throwing; messages go to a log sink filtered by `runtime.log_level`. The ADC frame
layout is unchanged (`[rx][sample][chirp]`, the same nested `std::vector` type). Delivery changed:
`next_adc_frame` swaps a pooled buffer into your `AdcFrame` (no copy) and hands out every frame in
order from a queue of `runtime.frame_queue_depth` (default 4; `1` keeps only the newest frame,
as v1 did); frames dropped from a full queue are counted in `frames_overwritten`. Points are `Point{x,y,z,v,snr_db,noise_db}`, and a
point cloud is now handed over as soon as its frame has arrived (v1 delivered it one frame period late). Link
`CPSL_TI_Radar::driver`. [`CPSL_TI_Radar_ROS`](https://github.com/davidmhunt/CPSL_TI_Radar_ROS)
still uses `Runner` and does not build against v2.0 until it moves to `Radar`.

## Output files

`adc_data.bin` keeps its byte layout (for chirp, rx, sample: int16 real then imaginary; see
`docs/ARCHITECTURE.md` "Output files") and is written to `output.dir` (the current directory when
unset), which the driver creates if it does not exist. The raw LVDS file `LVDS_Raw_0.bin` is only written with `output.save_raw_lvds: true`.
