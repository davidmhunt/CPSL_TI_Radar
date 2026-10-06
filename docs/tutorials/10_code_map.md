# 10. Code map: where things live

This is the entry point of the "extending" track. All driver code is in `CPSL_TI_Radar_cpp/`; the rest of this track assumes you built it ([tutorial 1](01_build_and_host_setup.md)). Reference detail (every call, the stop sequence, packet formats) is in `docs/ARCHITECTURE.md`; this page tells you which file to open.

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

Four threads matter: the RX thread (packets into the ring), the DCA worker (assemble, convert, queue, save), the serial reader, and yours.

## Directory map

| Directory under `src/` | What it owns | Tests |
|---|---|---|
| `Radar/` | The public API `cpsl::radar::Radar` (`open`, `configure`, `start`, `next_adc_frame`, `next_point_cloud`, `stats`, `stop`); `main.cpp` is a thin caller | `test_radar_e2e_fake`, `test_radar_serial_fake` |
| `utilities/` | `RadarConfig`, `SystemConfigReader` (system JSON), `RadarConfigReader` (the `.cfg`), `Status`/`Result`, `Log`, `ByteStream` (serial I/O, faked in tests), thread placement | `test_system_config_v2`, `test_radar_config*`, `test_log` |
| `BoardDescriptor/` | Loads `config/boards/*.json` and cross-checks the `.cfg` against the board | `test_board_descriptor` |
| `CLIController/` | Sends the `.cfg` commands, waits for `Done` | `test_cli_stop` |
| `DCA1000/` | `DCA1000Socket` (RX thread, ring), `FrameAssembler`, `ADCCubeConverter`, `DCA1000Handler`, `DCA1000Commands` | `test_frame_assembler`, `test_adc_cube_converter`, `test_dca_*` |
| `SerialStreamer/` | Frames the serial stream; `UartFrame.cpp` holds `parse_uart_frame`, the pure parser | `test_uart_parse`, `test_serial_streamer_frames` |

Two rules keep this map small. **Board-specific behaviour is data**: no component branches on a board name; each reads fields of the board descriptor (`docs/ARCHITECTURE.md`, "Dispatch"), so most new boards need only a JSON file ([tutorial 11](11_add_a_board_and_tlv_type.md)). **Nothing throws, exits or prints**: calls return a `Status` and messages go to the log sink, which is what makes the fake-transport tests possible.

## Where to start for common changes

| You want to | Open |
|---|---|
| tune or add a board | `config/boards/`, `config/boards/README.md` |
| decode another serial TLV | `src/SerialStreamer/UartFrame.cpp` ([tutorial 11](11_add_a_board_and_tlv_type.md)) |
| use frames in your own program | `src/Radar/Radar.hpp` ([tutorial 12](12_consume_frames.md)) |
| measure speed | `bench/`, `tools/bench/` ([tutorial 13](13_tests_and_performance.md)) |

A new library gets its own `src/<dir>/CMakeLists.txt` and one line in `src/CMakeLists.txt`; `CPSL_TI_Radar::driver` links them all for outside projects.
