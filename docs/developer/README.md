# Developer guide

For someone changing the driver, the GUI or the configs. To install and run a radar first, do the [tutorials](../tutorials/README.md). Reference detail: [`../ARCHITECTURE.md`](../ARCHITECTURE.md) (pipeline, config keys, output files) and [`CPSL_TI_Radar_cpp/Readme.md`](../../CPSL_TI_Radar_cpp/Readme.md).

| Page | Read it to |
|---|---|
| this page | find where code lives |
| [`add_a_board_and_tlv_type.md`](add_a_board_and_tlv_type.md) | add or tune a board descriptor; decode another serial TLV |
| [`consume_frames.md`](consume_frames.md) | link the driver into your own program; the buffer-swap and queue rules |
| [`tests_and_performance.md`](tests_and_performance.md) | write a fake-transport test; run the benchmarks and the before/after gate |
| [`bench_validation.md`](bench_validation.md) | check a board on the bench against the reference numbers; run a flashing session |
| [`config_and_migration.md`](config_and_migration.md) | the config tree, its naming rules, and the v1 to v2 migration tool |
| [`radar_notes.md`](radar_notes.md) | what TI's sources say: UART formats, board limits, chirp rules, CFAR, HPF/gain |

Also: the GUI's HTTP and WebSocket API is in [`radar_gui/README.md`](../../radar_gui/README.md); the firmware projects follow [`../specs/fw_project_contract.md`](../specs/fw_project_contract.md); the descriptor schema is in [`config/boards/README.md`](../../CPSL_TI_Radar_cpp/config/boards/README.md).

## How data moves

```
 DCA1000 --UDP--> RX thread --ring--> DCA worker --> FrameAssembler --> ADCCubeConverter
                  (DCA1000Socket)     (Radar)         (zero-fills gaps)  (board's lvds layout)
                                                                              |
                          adc_data.bin <--- one write per frame ---+          v
                                                              frame queue (depth N, drop-oldest)
                                                                              |
 radar --UART--> serial reader --> parse_uart_frame --> newest PointCloud     |
                  (SerialStreamer)  (UartFrame.cpp)           |               |
                                                              v               v
                                                  Radar::next_point_cloud / next_adc_frame  --> your code
 your code --> Radar::configure/start/stop --> CLIController --CLI UART--> radar (cfg commands)
```

## The C++ driver (`CPSL_TI_Radar_cpp/src/`)

| Directory | What it owns | Tests |
|---|---|---|
| `Radar/` | The public API `cpsl::radar::Radar` (`open`, `configure`, `start`, `next_adc_frame`, `next_point_cloud`, `stats`, `stop`); `main.cpp` is a thin caller | `test_radar_e2e_fake`, `test_radar_serial_fake` |
| `utilities/` | `RadarConfig`, `SystemConfigReader` (system JSON), `RadarConfigReader` (the `.cfg`), `Status`/`Result`, `Log`, `ByteStream` (serial I/O, faked in tests), thread placement | `test_system_config_v2`, `test_radar_config*`, `test_log` |
| `BoardDescriptor/` | Loads `config/boards/*.json` and cross-checks the `.cfg` against the board | `test_board_descriptor` |
| `CLIController/` | Sends the `.cfg` commands, waits for `Done` | `test_cli_stop` |
| `DCA1000/` | `DCA1000Socket` (RX thread, ring), `FrameAssembler`, `ADCCubeConverter`, `DCA1000Handler`, `DCA1000Commands` | `test_frame_assembler`, `test_adc_cube_converter`, `test_dca_*` |
| `SerialStreamer/` | Frames the serial stream; `UartFrame.cpp` holds `parse_uart_frame`, the pure parser | `test_uart_parse`, `test_serial_streamer_frames` |

Two rules keep this map small. **Board-specific behaviour is data**: no component branches on a board name; each reads fields of the board descriptor (`../ARCHITECTURE.md`, "Dispatch"), so most new boards need only a JSON file ([add a board](add_a_board_and_tlv_type.md)). **Nothing throws, exits or prints**: calls return a `Status` and messages go to the log sink, which is what makes the fake-transport tests possible. A new library gets its own `src/<dir>/CMakeLists.txt` and one line in `src/CMakeLists.txt`; `CPSL_TI_Radar::driver` links them all for outside projects.

## The rest of the repository

| Path | What |
|---|---|
| `radar_gui/` | The browser GUI (FastAPI plus plain JS). `cfg/` holds the cfg parser, generator, metrics and validator; it reads its limits from `config/firmware/<id>.json` and `config/limits/host.json`, each value with a `source` that points into [`radar_notes.md`](radar_notes.md) |
| `CPSL_TI_Radar_cpp/config/` | Everything the driver and GUI read at startup: `boards/`, `firmware/`, `limits/`, `system/`, `radar/`, `user/` ([`config_and_migration.md`](config_and_migration.md)) |
| `tools/` | `bench/` (bench run, pipeline gate), `setup/` (host setup), `gui_shots.py`, `migrate_config_v1_to_v2.py` |
| `tests/` | pytest: GUI, config tree, migration, tooling; the C++ tests live in `CPSL_TI_Radar_cpp/tests/` |
| `firmware_dev/` | Optional submodule that builds and flashes the firmware images (`fw`) |
| `shipped_firmware/`, `ros2/`, `docker/` | Prebuilt images, the ROS 2 packages, the GUI containers |

## Where to start for common changes

| You want to | Open |
|---|---|
| tune or add a board | `config/boards/`, `config/boards/README.md` |
| decode another serial TLV | `src/SerialStreamer/UartFrame.cpp` ([add a board](add_a_board_and_tlv_type.md)) |
| change a GUI limit or rule | `config/limits/`, `radar_gui/cfg/validate.py`; check the value in [`radar_notes.md`](radar_notes.md) first |
| use frames in your own program | `src/Radar/Radar.hpp` ([consume frames](consume_frames.md)) |
| measure speed | `bench/`, `tools/bench/` ([tests and performance](tests_and_performance.md)) |
