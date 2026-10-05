# Architecture

The main source directory is `CPSL_TI_Radar_cpp/` (C++, CMake). This doc
describes the driver as of the start of the v2.0 rework (`release/v2.0`);
update it as the rework changes structure. Firmware is described in
`docs/firmware.md`.

## Build

```bash
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
./CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP <system config .json> [--validate]
```

With no `-DCMAKE_BUILD_TYPE`, the top-level `CMakeLists.txt` sets the type to
Release in the cache and prints it at configure time. An explicit type
(`-DCMAKE_BUILD_TYPE=Debug`, or the `asan-ubsan` preset) is left alone.
`tools/bench` and the host-setup doctor's `build-type` check expect Release,
so the plain command passes them.

One executable: `CPSL_TI_Radar_CPP` (uses `Runner`; DCA1000 and serial). The
config argument is required (no argument: usage, exit 2). `--validate` loads
the config, board descriptor and radar cfg, runs the cross-checks, prints a
summary and exits 0/1 without opening any port or socket.
Built as C++17 (`-std=gnu++17`).

**Stop and shutdown.** SIGINT/SIGTERM only set an atomic flag
(`src/utilities/StopSignal`, `SA_RESETHAND`: a second Ctrl-C terminates).
`main` polls it, leaves its frame loop and calls `Runner::stop()`, then
returns normally. `stop()` is idempotent and never throws: it joins the run
threads, then `DCA1000Handler::stop()` (RX thread, `recordStop`, flush and
close `adc_data.bin` / `LVDS_Raw_0.bin`), then `sensorStop`. Every step runs
even if an earlier one failed. `CLIController` sends over a
`cpsl::radar::ByteStream` (`src/utilities/ByteStream`; `SerialPortStream`
in the driver, a fake in tests) and turns any write/read error into a false
return and `io_error()`. The executable exits 1 when `stop()` hit an I/O
error (e.g. the radar's USB was unplugged); a missing acknowledgement is
only a warning.

**Sanitizers.** `CPSL_TI_Radar_cpp/CMakePresets.json` has an `asan-ubsan`
preset (ASan + UBSan, `-O1 -g`, UB not recoverable) that builds in
`CPSL_TI_Radar_cpp/build-asan-ubsan` and runs the whole ctest suite:
`cmake --preset asan-ubsan && cmake --build --preset asan-ubsan -j && ctest --preset asan-ubsan`
(from `CPSL_TI_Radar_cpp/`).
`include/json` (nlohmann/json) is a
submodule and must be present.

CMake structure: each library's `src/<dir>/CMakeLists.txt` declares its own
`target_include_directories` (PUBLIC, build and install interfaces) and calls
`find_package` for what it uses (Threads, Boost), so a target gets the headers
of everything it links and no central include list exists. Tests list only
`LIBS` in `add_driver_test`. `src/CMakeLists.txt` also defines the interface
target `driver` (links `Runner`), exported with the install as
`CPSL_TI_Radar::driver`. New libraries get their own subdirectory, are added
in `src/CMakeLists.txt`, and need no other include wiring. `src/BoardDescriptor/`
(board descriptor loader, see Configuration) is linked by `Utilities` and
`ADCCubeConverter`. Downstream use:

```cmake
find_package(CPSL_TI_Radar REQUIRED)   # -DCMAKE_PREFIX_PATH=<install prefix>
target_link_libraries(my_app PRIVATE CPSL_TI_Radar::driver)
```

**Replay benchmark.** `bench/bench_pipeline` (top-level `bench/`, built with
the tests) replays synthetic DCA1000 packets, with injected drops, duplicates
and reordering, through `FrameAssembler` and an ADC converter. It reports
frames/s, ns per ADC byte and heap allocations per frame for three converter
variants: today's `ADCCubeConverter`, and two bench-local kernels (nested with a
reused buffer, and flat `[chirp][rx][sample]`) kept as data for design D5. The
default `ctest` run never lists it (registered with `CONFIGURATIONS bench`);
`ctest -C bench -L bench` runs it. Build with
Release (the default build type) for comparable numbers.

## Component graph

```
main.cpp
  └── Runner
        ├── SystemConfigReader   (parses JSON system config v2; loads the board)
        │     └── BoardDescriptor    (board descriptor, cfg cross-checks, cfg command filter)
        ├── RadarConfigReader    (parses TI .cfg with the board's cfg dialect, bytes_per_frame)
        ├── CLIController        (serial → radar, sends the filtered .cfg commands)
        ├── DCA1000Handler       (thin coordinator)
        │     ├── DCA1000Socket      (UDP socket, RX thread SCHED_RR 99, ring buffer)
        │     ├── FrameAssembler     (sequence check, frame assembly, drop stats)
        │     ├── ADCCubeConverter   (ADC conversion per lvds.layout / lvds.iq_order)
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
- **Worker thread** (Runner thread): pops packets, places them by byte
  offset (`FrameAssembler`), converts the ADC cube, does file I/O.
- `SO_RCVBUF` requests `dca1000.rcvbuf_bytes` (default 64 MB; needs
  `net.core.rmem_max` raised); data socket timeout 500 ms.
- `dropped_packets`, `dropped_packet_events`, `late packets`, `duplicate
  packets`, `incomplete frames`, `skipped frames` and `rx_overrun_count`
  print per frame with `runtime.log_level: "debug"`.

The worker converts a completed frame outside any lock, then publishes the
cube and the `new_frame_available` flag together under one mutex, so the
flag is never visible before the cube it announces (core-11 G2;
`test_dca_frame_publish`). Consumers poll `get_next_adc_cube(timeout_ms)`,
which copies the cube and clears the flag under the same mutex.
`DCA1000Handler::configure_pipeline()` + `ingest_packet()` run this path
without a socket (tests).

## DCA1000 UDP packet format

10-byte header, then payload:

- Bytes 0–3: sequence number (uint32, little-endian)
- Bytes 4–9: byte count (uint48, little-endian)
- Bytes 10+: ADC payload (1462 bytes per full packet; max UDP 1472)

`FrameAssembler` places every payload by its byte count: stream offset `o`
is byte `o % bytes_per_frame` of frame `o / bytes_per_frame`, copied with one
`memcpy` per packet (split at a frame boundary). A lost, late or duplicated
packet therefore never shifts later bytes. Two frames are open at a time.
A frame is emitted once all its bytes have arrived, or once the stream is
`reorder_slack` bytes past its end (the driver uses 8 packets, so a packet
reordered across a frame boundary still lands); its missing bytes are zero.
A frame that received nothing is skipped, not emitted. There is no
retransmission.

Counters (sequence numbers, 64-packet window): a forward gap adds its
packets to `dropped_packets` (one `dropped_packet_events`); an older packet
is `duplicate` if already seen, else `late`, and a late packet that fills a
gap takes its drop back. Data for an already-emitted frame is dropped and
counted late. `incomplete_frames` / `skipped_frames` count frames emitted
with zeros / never emitted.

## ADC cube layout

Indexed `[Rx channel][sample][chirp]` as `complex<int16_t>`. The board
descriptor's `lvds.layout` picks the decoder in `ADCCubeConverter`:
`lane_per_rx` (interleaved, IWR1443) or `two_lane_iq_pairs`
(non-interleaved, IWR1843/6843), and `lvds.iq_order` says which component
comes first. With SDK 3+ and a single RX channel, use an even number of ADC
samples.

## Configuration

Three files describe a run (design §1, §2):

1. **System config** (`CPSL_TI_Radar_cpp/config/system/*.json`, schema v2,
   read by `SystemConfigReader`): `"schema_version": 2`, `board`,
   `board_overrides`, `radar_cfg`, `cli.port`, `serial_stream`, `dca1000`,
   `output` (`dir`, `save_adc_frames`, `save_raw_lvds`) and `runtime`
   (`log_level`; the queue/affinity/priority keys are validated but reserved
   for core-14/15). Paths resolve against the JSON file's directory. Loading
   is strict (unknown keys, bad types, repeated keys are errors with a JSON
   path). A v1 file is rejected with the name of
   `tools/migrate_config_v1_to_v2.py`. The fields are listed in
   `CPSL_TI_Radar_cpp/Readme.md`.
2. **Board descriptor** (`CPSL_TI_Radar_cpp/config/boards/<board>.json`:
   `IWR1443`, `IWR1843`, `IWR6843`, `AWR2243_CASCADE`), named by `board`
   (a name is looked up in `$CPSL_TI_RADAR_BOARDS_DIR`, else `../boards`
   next to the system config; a path is used as given). It holds the CLI
   handshake, cfg dialect (`rx_mask_fields`, `frame_period_field`,
   `skip_commands`), data-UART format, LVDS layout and DCA1000 settings.
   `board_overrides` is deep-merged over it before the strict
   `cpsl::radar::BoardDescriptor::load` validates it. Field sources are in
   `config/boards/README.md`.
3. **Radar .cfg** (`CPSL_TI_Radar_cpp/config/radar/`): the TI chirp config.
   DCA1000 streaming needs `lvdsStreamCfg -1 0 1 0` (ADC only) or
   `lvdsStreamCfg -1 1 1 1` (all data).

When the system config loads, `cross_check_radar_cfg` checks the radar .cfg
against the board for the enabled streams (16-bit complex ADC, `adcbufCfg`
interleave vs `lvds.layout`, `lvdsStreamCfg` ADC streaming, no DCA1000 on a
board without LVDS, no serial on the unconfirmed `sdk2` dialect); an error
fails the load.

**Dispatch.** No component branches on a board name; each reads descriptor
fields through `SystemConfigReader::getBoard()`:

| Behaviour | Descriptor field | Used in |
|-----------|------------------|---------|
| cfg commands sent | `cli.skip_prefixes`, `cli.start_cmd`, `cfg_dialect.skip_commands` (`filter_cfg_commands`) | `CLIController` |
| CLI handshake | `cli.baud`, `ack`, `prompt`, `prompt_wait_ms`, `cmd_timeout_ms`, `start_cmd`, `stop_cmd` | `CLIController` |
| Rx count, frame period | `cfg_dialect.rx_mask_fields`, `frame_period_field` | `RadarConfigReader` |
| Data UART | `data_uart.baud`, `timeout_ms` | `SerialStreamer` |
| DCA1000 FPGA setup | `lvds.lanes`, `dca1000.packet_bytes`, `packet_delay_us`, `fpga_timer_s` | `DCA1000Handler` |
| ADC decoder | `lvds.layout`, `lvds.iq_order` | `ADCCubeConverter` |
| One cfg per power-up | `lifecycle.config_once_per_boot` | `Runner` |

`cfg_dialect.skip_commands` drops commands the board's firmware rejects
before they are sent (the IWR1843 skips `calibData`); the `.cfg` files keep
the line, and a skipped command does not count as unacknowledged.

DCA1000 network defaults: FPGA `192.168.33.180`, host `192.168.33.30/24`,
command port 4096, data port 4098.

Supported boards: `IWR1843`, `IWR6843` (2-lane, non-interleaved),
`IWR1443` (4-lane, interleaved), `AWR2243_CASCADE` (serial TLV only so far;
data port 3,125,000 baud).

## Host prerequisites

See `CPSL_TI_Radar_cpp/Readme.md`: raise `net.core.rmem_max` to
134217728, and grant `cap_sys_nice` (or `rtprio 99`) for the SCHED_RR 99
RX thread. Serial ports need the `dialout` group.
