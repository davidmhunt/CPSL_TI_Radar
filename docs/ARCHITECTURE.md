# Architecture

The main source directory is `CPSL_TI_Radar_cpp/` (C++, CMake). This doc
describes the driver as of the start of the v2.0 rework (`release/v2.0`);
update it as the rework changes structure. Firmware is described in
`docs/firmware.md`.

## Build

```bash
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
./CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP <system config .json>
```

One executable: `CPSL_TI_Radar_CPP` (uses `Runner`; DCA1000 and serial).
`include/json` (nlohmann/json) is a
submodule and must be present.

CMake structure: each library's `src/<dir>/CMakeLists.txt` declares its own
`target_include_directories` (PUBLIC, build and install interfaces) and calls
`find_package` for what it uses (Threads, Boost), so a target gets the headers
of everything it links and no central include list exists. Tests list only
`LIBS` in `add_driver_test`. `src/CMakeLists.txt` also defines the interface
target `driver` (links `Runner`), exported with the install as
`CPSL_TI_Radar::driver`. New libraries (and a future `bench/`) get their own
subdirectory, are added in `src/CMakeLists.txt`, and need no other include
wiring. Downstream use:

```cmake
find_package(CPSL_TI_Radar REQUIRED)   # -DCMAKE_PREFIX_PATH=<install prefix>
target_link_libraries(my_app PRIVATE CPSL_TI_Radar::driver)
```

## Component graph

```
main.cpp
  └── Runner
        ├── SystemConfigReader   (parses JSON system config)
        ├── RadarConfigReader    (parses TI .cfg, computes bytes_per_frame)
        ├── CLIController        (serial → radar, sends .cfg commands)
        ├── DCA1000Handler       (thin coordinator)
        │     ├── DCA1000Socket      (UDP socket, RX thread SCHED_RR 99, ring buffer)
        │     ├── FrameAssembler     (sequence check, frame assembly, drop stats)
        │     ├── ADCCubeConverter   (interleaved / non-interleaved ADC conversion)
        │     └── DCA1000Commands    (FPGA command protocol)
        └── SerialStreamer        (serial TLV stream → detected points; TLVProcessing)
```

`Runner` spawns `run_dca1000` and `run_serial` threads. The DCA worker
raises itself to SCHED_RR 80; the serial worker keeps the default policy.
Serial baud handling (including the cascade's 3,125,000 baud data
port) lives in `src/utilities/SerialBaud*` (termios2).

## DCA1000 RX path

- **RX thread** (SCHED_RR 99): tight `recvfrom` loop pushing raw 1472-byte
  packets into a 512-slot lock-free ring buffer.
- **Worker thread** (Runner thread): pops packets, checks sequence numbers,
  assembles frames, converts the ADC cube, does file I/O.
- `SO_RCVBUF` requests 64 MB (needs `net.core.rmem_max` raised); data
  socket timeout 500 ms.
- `dropped_packets`, `dropped_packet_events`, `rx_overrun_count` print per
  frame with `verbose: true`.

Frames are signaled via a mutex-protected `new_frame_available` flag;
consumers poll `get_next_adc_cube(timeout_ms)`.

## DCA1000 UDP packet format

10-byte header, then payload:

- Bytes 0–3: sequence number (uint32, little-endian)
- Bytes 4–9: byte count (uint48, little-endian)
- Bytes 10+: ADC payload (1462 bytes per full packet; max UDP 1472)

Dropped packets are detected by `seq_num != prev_seq_num + 1` and
zero-padded. There is no retransmission.

## ADC cube layout

Indexed `[Rx channel][sample][chirp]` as `complex<int16_t>`. LVDS data
arrives interleaved or not depending on SDK:
`update_latest_adc_cube_interleaved()` vs
`update_latest_adc_cube_noninterleaved()`. With SDK 3+ and a single RX
channel, use an even number of ADC samples.

## Configuration

Two files are always required:

1. **JSON system config** (`CPSL_TI_Radar_cpp/config/system/*.json`):
   serial ports, DCA1000 IP/ports, streaming mode, save-to-file, and
   `TI_Radar_config_path` (relative to the JSON file, or absolute).
2. **Radar .cfg** (`CPSL_TI_Radar_cpp/config/radar/`): TI chirp config.
   DCA1000 streaming needs `lvdsStreamCfg -1 0 1 0` (ADC only) or
   `lvdsStreamCfg -1 1 1 1` (all data).

DCA1000 network defaults: FPGA `192.168.33.180`, host `192.168.33.30/24`,
command port 4096, data port 4098.

Supported `board_type`s: `IWR1843`, `IWR6843` (2-lane, non-interleaved),
`IWR1443` (4-lane, interleaved), `AWR2243_CASCADE` (serial TLV only so far;
data port 3,125,000 baud).

## Host prerequisites

See `CPSL_TI_Radar_cpp/Readme.md`: raise `net.core.rmem_max` to
134217728, and grant `cap_sys_nice` (or `rtprio 99`) for the SCHED_RR 99
RX thread. Serial ports need the `dialout` group.
