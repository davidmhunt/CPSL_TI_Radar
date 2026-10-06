# Architecture

The main source directory is `CPSL_TI_Radar_cpp/` (C++, CMake). This doc
describes the driver as of the start of the v2.0 rework (`release/v2.0`);
update it as the rework changes structure. Firmware is described in
`docs/firmware.md`.

## Build

```bash
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
./CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP <system config .json> [--validate] [--stats] [--frames N] [--duration S]
```

With no `-DCMAKE_BUILD_TYPE`, the top-level `CMakeLists.txt` sets the type to
Release in the cache and prints it at configure time. An explicit type
(`-DCMAKE_BUILD_TYPE=Debug`, or the `asan-ubsan` preset) is left alone.
`tools/bench` and the host-setup doctor's `build-type` check expect Release,
so the plain command passes them.

One executable: `CPSL_TI_Radar_CPP` (`main.cpp`, on the public API below;
DCA1000 and serial). The config argument is required (no argument: usage,
exit 2). `--validate` loads the config, board descriptor and radar cfg, runs
the cross-checks, checks `output.dir` (exists / will be created / error),
prints a summary and exits 0/1 without opening any port or socket. A run
ends on SIGINT/SIGTERM, after `--frames N` completed frames or `--duration S`
seconds, or when no frame arrives for 2 s (with `runtime.stall_timeout_ms`
set, on a stall instead). Built as C++17 (`-std=gnu++17`).

**Public API** (namespace `cpsl::radar`; `src/Radar/Radar.hpp`,
`src/utilities/{RadarConfig,Status,Log}.hpp`). No call throws, exits or
prints; failures are a `Status {code, message}` and messages go to the log
sink.

| Call | Does |
|------|------|
| `RadarConfig::load(path)` | `Result<RadarConfig>`: system JSON + board descriptor (with `board_overrides`) + parsed radar cfg, cross-checked; `board()`, `frame_shape()`, `commands()` |
| `Radar::open(cfg[, transports])` | `Result<unique_ptr<Radar>>`: creates `output.dir`, opens the output files, the DCA1000 sockets, the data UART and the CLI port; sends nothing; sets the log level from `runtime.log_level`. `Transports{cli, packets}` swaps in a fake `ByteStream` or a `ReplayPacketSource` |
| `configure()` | DCA1000 FPGA setup, then the radar cfg. With `lifecycle.config_once_per_boot`, a second call in the process (same CLI port) sends nothing and returns `already_configured` |
| `start()` | `recordStart` and the RX thread, the DCA worker (SCHED_RR 80) and serial reader threads, then `sensorStart` |
| `next_adc_frame(f, timeout[, &why])` / `next_point_cloud(...)` | latest completed frame (`AdcFrame`: `[rx][sample][chirp]` cube copied in, `index`, `completed_at`, `missing_bytes`, `shape`; `PointCloud` of `Point{x,y,z,v,snr_db,noise_db}`); false with `why` = `timeout`, `stalled`, `stopped`, `invalid_state` or `disabled` |
| `stats()` | the counters of the `stats v1` lines below |
| `stop()` | see below; the destructor calls it |
| `set_log_sink(fn)`, `set_log_level(l)` | process-wide; default sink: one line per message to stderr, `warning: `/`error: ` prefixes |

**Stop and shutdown.** SIGINT/SIGTERM only set an atomic flag
(`src/utilities/StopSignal`, `SA_RESETHAND`: a second Ctrl-C terminates).
`main` checks it on every pass of its loop, leaves the loop and calls `Radar::stop()`, then
returns normally. `stop()` is idempotent and safe from several threads: one
lifecycle mutex, so a second caller waits for the first and gets the same
`Status`. It first wakes a consumer blocked in `next_adc_frame`
(`Code::stopped`), then joins the worker threads, then `DCA1000Handler::stop()`
(packet source: RX thread, `recordStop`; then flush and close
`adc_data.bin` / `LVDS_Raw_0.bin`), then `sensorStop`. Every step runs even
if an earlier one failed. `CLIController` sends over a
`cpsl::radar::ByteStream` (`src/utilities/ByteStream`; `SerialPortStream`
in the driver, a fake in tests); every write and read is bounded by the
command's timeout, and a write/read error makes the command fail with
`io_error()` (cleared at the start of each command). `sensorStop` waits
`max(cli.cmd_timeout_ms, frame period + 200 ms)`, or the descriptor's
`cli.stop_timeout_ms`, because the demo acknowledges it only after the
current frame. `stop()` returns `io_error` when `sensorStop` could not be
sent (e.g. the radar's USB was unplugged) and `file_error` when an output
file failed to flush; the executable then exits 1. A missing
acknowledgement is only a warning.

**Stall policy.** `runtime.stall_timeout_ms` > 0: when a stream completes no
frame for that long while running, the next `next_adc_frame` /
`next_point_cloud` call logs a warning, adds 1 to `Stats::stalls` and
returns false with `stalled`, once per stall (later calls in the same stall
time out normally). `main` stops the run on it. 0 (the default) turns it
off, and `main` keeps its 2 s no-frame exit.

**Stats lines.** `--stats` prints, once a second and once more after
`stop()`, one line per enabled stream, counters cumulative since `start()`
and `t` in seconds since `start()`. `tools/bench` reads only these lines;
the format is versioned (`v1`), and a change to its keys needs a new version:

```
stats v1 dca t=<s> frames=<n> packets=<n> dropped=<n> drop_events=<n> late=<n> duplicate=<n> incomplete=<n> skipped=<n> overrun=<n> overwritten=<n> stalls=<n> rcvbuf=<bytes>
stats v1 serial t=<s> frames=<n> missed=<n> overwritten=<n> stalls=<n>
```

`frames` counts completed frames (DCA: the frames in `adc_data.bin`;
serial: valid TLV frames). `packets` … `skipped` are the `FrameAssembler`
counters (see "DCA1000 UDP packet format"), sampled at each completed frame
and at stop. `overrun` is `rx_overrun_count` (RX ring full), `overwritten`
counts frames dropped before `next_*` took them (DCA: the oldest frame of a
full frame queue, see "DCA1000 RX path"; serial: the previous TLV frame),
`rcvbuf` is the `SO_RCVBUF` the kernel granted, `missed` counts gaps in the
demo's frame number.

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
target `driver` (links `Radar`), exported with the install as
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
main.cpp (CLI)
  └── Radar                     (public API; src/Radar)
        ├── RadarConfig          (src/utilities)
        │     ├── SystemConfigReader   (JSON system config v2; loads the board)
        │     │     └── BoardDescriptor    (board descriptor, cfg cross-checks, cfg command filter)
        │     └── RadarConfigReader    (TI .cfg with the board's cfg dialect, bytes_per_frame)
        ├── CLIController        (sends the filtered .cfg commands over a ByteStream)
        ├── DCA1000Handler       (assembles, converts, publishes and saves frames)
        │     ├── PacketSource       (UdpPacketSource: DCA1000Socket + DCA1000Commands; or ReplayPacketSource)
        │     ├── FrameAssembler     (sequence check, frame assembly, drop stats)
        │     └── ADCCubeConverter   (ADC conversion per lvds.layout / lvds.iq_order)
        └── SerialStreamer        (serial TLV stream → detected points; TLVProcessing)
  Log, Status                   (every library; Log has no dependencies)
```

`Radar::start()` spawns a DCA worker thread (SCHED_RR 80) and a serial
reader thread; `DCA1000Socket` adds the RX thread. Serial baud handling
(including the cascade's 3,125,000 baud data port) lives in
`src/utilities/SerialBaud*` (termios2).

## DCA1000 RX path

- **RX thread** (SCHED_RR 99): tight `recvfrom` loop pushing raw 1472-byte
  packets into a 512-slot lock-free ring buffer.
- **Worker thread** (`Radar`'s DCA worker): pops packets, places them by byte
  offset (`FrameAssembler`), converts the ADC cube into a pooled buffer,
  queues it for the consumer, then writes `adc_data.bin`. An exception in
  the loop ends the stream, not the process: it is logged and
  `next_adc_frame` returns `Code::io_error` with the reason.
- `SO_RCVBUF` requests `dca1000.rcvbuf_bytes` (default 64 MB; needs
  `net.core.rmem_max` raised); data socket timeout 500 ms.
- `dropped_packets`, `dropped_packet_events`, `late packets`, `duplicate
  packets`, `incomplete frames`, `skipped frames` and `rx_overrun_count`
  are in `stats()` and the `stats v1` lines, and with
  `runtime.log_level: "debug"` one `DCA1000: frames ...` line logs them at
  most once a second. Nothing on the per-packet or per-frame path logs or
  prints (design P10).

**Frame queue** (core-14 P7, design D10). Completed frames wait in a
drop-oldest single-producer queue of `runtime.frame_queue_depth` frames
(default 4; `1` keeps only the newest frame). The worker converts a frame
outside any lock into its work buffer, then, under one mutex, swaps that
buffer into the queue's next slot; if the queue is full it first drops the
oldest frame and counts it in `frames_overwritten`. Only after that does it
notify a condition variable, so a frame is never visible before its cube
(core-11 G2) and a woken consumer always finds it (`test_dca_frame_publish`).
`Radar::next_adc_frame` blocks on that condition variable (it returns tens
of µs after the frame is published, where the core-13 timer loop cost
about 3 ms on average) and takes
the oldest frame by swapping buffers with the caller's `AdcFrame`. Frames
therefore come out in order and once each; every frame a consumer did not
get is counted in `frames_overwritten` (`test_radar_e2e_fake` races a
consumer against the producer). `stop()` wakes a waiting consumer at once
(`Code::stopped`). `DCA1000Handler::configure_pipeline()` + `ingest_packet()`
run this path without a socket (tests, `bench_pipeline` `drv_*` rows).

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

Indexed `[Rx channel][sample][chirp]` as `complex<int16_t>`: `AdcFrame::data`
is the same nested `std::vector` type as in v1 (design D5; core-14 kept it).
The board descriptor's `lvds.layout` picks the decoder in `ADCCubeConverter`:
`lane_per_rx` (interleaved, IWR1443) or `two_lane_iq_pairs`
(non-interleaved, IWR1843/6843), and `lvds.iq_order` says which component
comes first. With SDK 3+ and a single RX channel, use an even number of ADC
samples.

**Buffers (core-14 P2, P3).** The cubes are a pool of nested buffers,
allocated when the radar is opened: one per frame-queue slot plus the
worker's work buffer. They are swapped, never copied: the converter writes
a frame into the work buffer in place, the work buffer is swapped into the
queue, and `next_adc_frame` swaps the queued buffer with the one the caller
passes in (which joins the pool). Reuse one `AdcFrame` and nothing is
allocated per frame (`bench_pipeline` measures 0 allocations/frame). The
converter makes one pass over the packed bytes in output order: for each
`[rx][sample]` row it walks the chirps, so writes are sequential and only
the reads stride (0.19 ns/byte on an Intel N150, against 1.6 for the v1
four-pass converter). A frame shorter than its shape reads as zeros.

### Output files

With `output.save_adc_frames`, every completed frame (including frames the
consumer never took) is appended to `adc_data.bin` in `output.dir`: for
chirp, for rx, for sample, the int16 real part then the int16 imaginary
part, host byte order (little-endian on x86/ARM). That is
`bytes_per_frame` per frame, no header; the layout is unchanged since v1.
The frame is written with **one** `write()` from a staging buffer that the
converter fills in file order in one sequential pass (core-14 P9; v1 made
two 2-byte writes per sample, about 252 000 per frame). The write happens
after the frame is queued, so the consumer does not wait for the disk. With
`output.save_raw_lvds`, `LVDS_Raw_0.bin` gets every packet's payload as it
arrives (no reordering or zero fill). `stop()` flushes and closes both.

## Configuration

Three files describe a run (design §1, §2):

1. **System config** (`CPSL_TI_Radar_cpp/config/system/*.json`, schema v2,
   read by `SystemConfigReader`): `"schema_version": 2`, `board`,
   `board_overrides`, `radar_cfg`, `cli.port`, `serial_stream`, `dca1000`,
   `output` (`dir`, `save_adc_frames`, `save_raw_lvds`) and `runtime`
   (`log_level`, `stall_timeout_ms`; the queue/affinity/priority keys are
   validated but reserved for core-14/15). `Radar::open` creates `output.dir`. Paths resolve against the JSON file's directory. Loading
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
| CLI handshake | `cli.baud`, `ack`, `prompt`, `prompt_wait_ms`, `cmd_timeout_ms`, `stop_timeout_ms`, `start_cmd`, `stop_cmd` | `CLIController` |
| Rx count, frame period | `cfg_dialect.rx_mask_fields`, `frame_period_field` | `RadarConfigReader` |
| Data UART | `data_uart.baud`, `timeout_ms` | `SerialStreamer` |
| DCA1000 FPGA setup | `lvds.lanes`, `dca1000.packet_bytes`, `packet_delay_us`, `fpga_timer_s` | `UdpPacketSource` |
| ADC decoder | `lvds.layout`, `lvds.iq_order` | `ADCCubeConverter` |
| One cfg per power-up | `lifecycle.config_once_per_boot` | `Radar` |

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
