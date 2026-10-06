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
| `Radar::open(cfg[, transports])` | `Result<unique_ptr<Radar>>`: creates `output.dir`, opens the output files, the DCA1000 sockets, the data UART and the CLI port; sends nothing; sets the log level from `runtime.log_level`. `Transports{cli, packets, data}` swaps in a fake CLI `ByteStream`, a `ReplayPacketSource` or a fake serial data `ByteStream` |
| `configure()` | DCA1000 FPGA setup, then the radar cfg. With `lifecycle.config_once_per_boot`, a second call in the process (same CLI port) sends nothing and returns `already_configured` |
| `start()` | `recordStart` and the RX thread, the DCA worker and serial reader threads (CPUs and priorities from `runtime.*`, see "DCA1000 RX path"), then `sensorStart` |
| `next_adc_frame(f, timeout[, &why])` / `next_point_cloud(...)` | ADC: the oldest queued frame, blocking until one is ready (`AdcFrame`: `[rx][sample][chirp]` buffer swapped into `data`, not copied, plus `index`, `completed_at`, `missing_bytes`, `shape`); serial: the latest `PointCloud` (`frame_number`, `completed_at`, and `Point{x,y,z,v,snr_db,noise_db}` swapped into `points`, not copied; see "Serial TLV path"). false with `why` = `timeout`, `stalled`, `stopped` (also when `stop()` begins during the wait), `io_error` (the stream's worker thread failed), `invalid_state` or `disabled` |
| `stats()` | the counters of the `stats v1` lines below |
| `stop()` | see below; the destructor calls it |
| `set_log_sink(fn)`, `set_log_level(l)` | process-wide; default sink: one line per message to stderr, `warning: `/`error: ` prefixes |

**Stop and shutdown.** SIGINT/SIGTERM only set an atomic flag
(`src/utilities/StopSignal`, `SA_RESETHAND`: a second Ctrl-C terminates).
`main` checks it on every pass of its loop, leaves the loop and calls `Radar::stop()`, then
returns normally. `stop()` is idempotent and safe from several threads: one
lifecycle mutex, so a second caller waits for the first and gets the same
`Status`. It first wakes a consumer blocked in `next_adc_frame` or
`next_point_cloud` (`Code::stopped`) and ends the serial reader's read, then joins the worker threads, then `DCA1000Handler::stop()`
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
the format is versioned (`v1`): keys may be appended (readers skip keys
they do not know; core-15 appended `kernel_drops` … `resyncs`), and a key
may be narrowed to its documented meaning (core-15: `drop_events`), but
renaming or removing a key needs a new version:

```
stats v1 dca t=<s> frames=<n> packets=<n> dropped=<n> drop_events=<n> late=<n> duplicate=<n> incomplete=<n> skipped=<n> overrun=<n> overwritten=<n> stalls=<n> rcvbuf=<bytes> kernel_drops=<n> ring_full=<n> implausible=<n> resyncs=<n>
stats v1 serial t=<s> frames=<n> missed=<n> overwritten=<n> stalls=<n>
```

`frames` counts completed frames (DCA: the frames in `adc_data.bin`;
serial: valid TLV frames). `packets` … `skipped` are the `FrameAssembler`
counters (see "DCA1000 UDP packet format"), sampled at each completed frame
and at stop (`drop_events` counts only gaps that stayed missing since
core-15; a reorder is no longer one). `overrun` counts packets discarded in
user space because the RX ring was full; since core-15 the RX thread never
discards, so it stays 0 (kept so the key keeps its meaning). `kernel_drops`
counts packets the kernel dropped on the data socket (`sk_drops`: almost
always a full `SO_RCVBUF`, the one place a slow consumer loses data now;
datagrams with a bad checksum count too), and `ring_full` how
often the RX thread found its ring full and stopped reading (back-pressure,
not a loss). `implausible` and `resyncs` are the `FrameAssembler`
plausibility counters (see "DCA1000 UDP packet format"). `overwritten`
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
`find_package` for what it uses (Threads), so a target gets the headers
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
        └── SerialStreamer        (serial TLV frames → PointCloud, over a ByteStream)
              └── TLVProcessing      (parse_uart_frame in UartFrame.cpp: one frame per TLV dialect; TLV codes)
  Log, Status                   (every library; Log has no dependencies)
```

`Radar::start()` spawns a DCA worker thread (`runtime.worker_cpu` /
`worker_priority`, default any CPU, normal priority) and a serial reader
thread; `DCA1000Socket` adds the RX thread (`runtime.rx_cpu` /
`rx_priority`, default any CPU, normal priority). Both serial ports are a
`SerialPortStream` (`src/utilities/ByteStream`): a non-blocking descriptor in
raw mode whose every read and write is bounded by `poll()`. Baud rates go
through `src/utilities/SerialBaud*`: termios for the standard rates,
termios2/`BOTHER` for others (the cascade's 3,125,000 baud data port).

## DCA1000 RX path

- **RX thread** (`DCA1000Socket`): `recvmmsg` straight into the free slots
  of a 512-slot single-producer/single-consumer ring of 1472-byte packets,
  up to 32 datagrams per call (design P5). `MSG_WAITFORONE` blocks only for
  the first datagram, bounded by the data socket's 500 ms `SO_RCVTIMEO`, so
  `stop_rx()` returns within about 0.5 s. One head publish per batch.
- **Back-pressure** (design P6): when the ring is full the RX thread stops
  reading and waits for the worker to free a slot. Nothing is discarded in
  user space (`rx_overrun` stays 0); the backlog waits in the socket's
  `SO_RCVBUF` (`dca1000.rcvbuf_bytes`, default 64 MB, capped by
  `net.core.rmem_max`). Only when that buffer is full does the kernel drop,
  and those drops are counted: `SO_RXQ_OVFL` delivers the socket's drop
  count with each datagram, and `SO_MEMINFO` completes it in `stats()` and
  at stop (`kernel_drops`). At the IWR1843 baseline rate (~3460 packets/s)
  a 200 ms consumer stall is ~700 packets, a few MB of buffer at most
  (`bench_pipeline --udp --stall-ms 200`: 0 discards, 0 kernel drops).
- **Worker thread** (`Radar`'s DCA worker, `DCA1000Handler::process_next_packet`):
  takes up to 32 packets at once as views into the ring (no per-packet
  copy) and hands their slots back after ingesting them (design P4). The
  RX thread notifies the worker's condition variable only when the worker
  has flagged that it is about to sleep, so a busy worker costs no futex
  call per packet. The worker places each payload by byte offset
  (`FrameAssembler`), converts the ADC cube into a pooled buffer, queues it
  for the consumer, then writes `adc_data.bin`. An exception in the loop
  ends the stream, not the process: it is logged and `next_adc_frame`
  returns `Code::io_error` with the reason.
- **Placement** (design P11): `runtime.rx_cpu` / `worker_cpu` pin the RX /
  worker thread to one CPU (`null`, the default: not pinned);
  `runtime.rx_priority` / `worker_priority` (default 0, range 0-99) request
  SCHED_RR when above 0. Without `cap_sys_nice` that request fails with one
  warning, and the thread runs at normal priority; a CPU that cannot be used is also only a
  warning (`src/utilities/ThreadPlacement`).
- **Resync**: a DCA1000 restart (byte counts back to 0) or a wild byte
  count no longer leaves the stream dead; see "DCA1000 UDP packet format".
  `DCA1000Handler` logs one warning per resync (at most one a second).
- Counters in `stats()` and the `stats v1` lines: `dropped_packets`,
  `dropped_packet_events`, `late`, `duplicate`, `incomplete` and `skipped`
  frames, `implausible`, `resyncs` (all `FrameAssembler`), `kernel_drops`,
  `ring_full` and `rx_overrun` (always 0). With
  `runtime.log_level: "debug"` one `DCA1000: frames ...` line logs them at
  most once a second. Nothing on the per-packet or per-frame path logs or
  prints (design P10).

`bench_pipeline --udp` runs this whole path over loopback (a sender thread
in place of the DCA1000) and reports discards, kernel drops, CPU and context
switches; see `CPSL_TI_Radar_cpp/Readme.md`.

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
packets to `dropped_packets` and is one `dropped_packet_events`; an older
packet is `duplicate` if already seen, else `late`, and a late packet that
fills a gap takes its drop back. Once every packet of a gap has arrived
late, the gap's event is taken back too (core-15): `dropped_packet_events`
counts gaps that end with packets missing, so a reorder is not a drop
event (bench `dup_reorder`: 695 events before, 0 after). Data for an
already-emitted frame is dropped and counted late. `incomplete_frames` /
`skipped_frames` count frames emitted with zeros / never emitted.

**Plausibility and resync** (core-15, core-11 review S1). Once the stream
has started, a packet is *implausible* when its byte count is more than
one frame (the window W) past the furthest payload, beyond what its
sequence number explains (each sequence number it moves on allows one more
payload), or when its whole payload lies more than W behind the oldest open
frame. An implausible packet ahead is discarded (`implausible`), so one
wild byte count costs only its own payload; one behind is late, as before.
Four consecutive implausible packets whose payloads follow each other byte
for byte (a DCA1000 restart that starts the count at 0 again, or the real
stream after a wild count that was accepted) trigger a *resync*: the open
frames are dropped (counted in `skipped_frames`), assembly and sequence
tracking restart at the first of the four, the four are replayed, and
`resyncs` goes up by one. The first frame of the new stream is whole when
the restart's first packets arrive in order.

**Documented compromise, accepted by the user 2026-10-06.** A restart is
detected only once its packets lie more than W behind the oldest open
frame, so not before the old stream is about two frames in (692 packets
at the IWR1843 baseline); a restart in the first 64 packets also looks
like sequence duplicates, which never count toward a resync. Inside that
window there is no resync: the stream continues on the new counts, but
one emitted frame mixes old and new bytes with `missing_bytes` 0, and one
new-stream frame is lost (late). The reverse also holds: a contiguous run
of 4 or more genuinely late packets more than a frame late, or re-delivered
duplicates older than 64 packets, cannot be told apart from a restart by
their headers. They trigger a resync: the open frames are dropped and
`dropped_packets` grows by the sequence distance. Neither occurs on a
direct DCA1000 link.

Legitimate losses keep a sequence gap that matches the byte gap and are
placed exactly as before. Frame indices keep increasing across a resync
(the next index follows the dropped frames), so after one an index is no
longer byte offset / `bytes_per_frame`.

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

## Serial TLV path

The on-chip demo sends one frame per radar frame on the data UART. Every
dialect shares the framing: an 8-byte magic word (`02 01 04 03 06 05 08 07`),
a header (`version`, `totalPacketLen`, `platform`, `frameNumber`,
`timeCpuCycles`, `numDetectedObj`, `numTLVs`, and `subFrameNumber` except on
SDK 2), then `numTLVs` x `{u32 type, u32 length, payload}` where `length`
excludes the 8-byte TLV header, then zero to 31 padding bytes
(`totalPacketLen` is a multiple of 32).

**Framing (core-16, P8).** `SerialStreamer` (reader thread, `Radar`'s serial
worker) reads from a `ByteStream`: it finds the magic word (skipping any
bytes before it), reads the header, then reads **exactly** the rest of
`totalPacketLen`, parses, and publishes at once. It never waits for the
next frame's magic word, which v1 did, so v1 delivered every frame one frame
period late (50 ms at 20 Hz). `bench/bench_serial_latency` writes frames to
a pty at the frame period and measures last byte written ->
`next_point_cloud` return: 52.6 ms median before, 0.17 ms after (core-16
Log); its short run is the ctest test `test_serial_latency_pty`. A frame
cut off by `data_uart.timeout_ms` keeps its bytes for the next call. A
`totalPacketLen` outside [header, 1 MiB] or a frame that fails parsing is
dropped with a warning and the search restarts one byte after its magic
word; a frame that fails parsing never changes the published frame or the
`missed` count.

**`UartFrame` and `parse_uart_frame`** (`src/SerialStreamer/UartFrame.{hpp,cpp}`).
`parse_uart_frame(bytes, len, dialect, out)` is pure: no I/O, no logging,
no exceptions, no read outside `[bytes, bytes + len)`. It fills
`UartFrame{header, points, has_side_info, compact_points_skipped}` and
returns a `Status` (`Code::malformed_frame` with the reason) on: a short
header or frame, no magic word, `totalPacketLen` shorter than the header or
above 1 MiB, `numTLVs` that cannot fit, a TLV header or payload past
`totalPacketLen`, two type-1 or two type-7 TLVs, a points payload that is
not a whole number of points, a point count different from
`numDetectedObj`, or side info whose count differs from the points'. All
other TLV types are skipped by their length. This is the seam for a new TLV
type: decode it here, add a golden frame to `tests/test_uart_parse.cpp`.

**Dialects.** The board descriptor's `data_uart.tlv_dialect` picks the
decoder (`config/boards/README.md`, "TLV dialects", has the details and
sources):

| `tlv_dialect` | Boards | Header | TLV 1 (points) | TLV 7 (side info) | Other |
|---------------|--------|--------|----------------|-------------------|-------|
| `sdk3` | IWR1843, IWR6843 | 40 B | float x, y, z, v (16 B) | int16 snr, noise, 0.1 dB (4 B) | |
| `mcuplus_cascade` | AWR2243 cascade | 40 B | as `sdk3` | as `sdk3` | TLV 12 (compact points, `guiMonitor` detectedObjects 3) is not decoded: the driver warns once |
| `sdk2` | IWR1443 | 36 B | `{u16 n, u16 xyzQFormat}` + 12 B per point, x, y, z = int16 / 2^xyzQFormat m | none | v, snr_db, noise_db are NaN |

Without a TLV 7, `snr_db` and `noise_db` are 0 on `sdk3` and
`mcuplus_cascade`. A frame without a TLV 1 (no detections, or detected
objects turned off in `guiMonitor`) is an empty cloud.

**Documented compromise (`sdk2`), approved by the user 2026-10-06 for now; to be improved (compute velocity from the radar .cfg, SNR/noise from firmware if it exposes them).** The SDK 2 demo sends no velocity, SNR or
noise, so on the IWR1443 `Point::v`, `snr_db` and `noise_db` are NaN; check
them with `std::isnan`. The demo does send a signed Doppler bin index, and
`v` could be the bin times the Doppler resolution, but the driver does not
compute the Doppler resolution from the radar cfg, so it reports NaN rather
than guess. The format comes from TI's SDK 2.1 source
(`docs/research/sdk2_uart_format_2026-10-05.md`); no IWR1443 has run it yet.
A firmware that does not match `tlv_dialect` mostly yields empty clouds
with no error; `config/boards/README.md` ("TLV dialects") says how to spot
it from the `platform` word in the debug-level frame lines.

**Buffers.** The receive buffer, the parsed frame's points, the published
points and the consumer's `PointCloud::points` are reused: `take_frame`
swaps the published vector with the caller's, so a consumer that reuses one
`PointCloud` costs no allocation per frame. Only the newest frame waits; a
frame replaced before it was taken counts in `serial_overwritten`.
`next_point_cloud` blocks on a condition variable (no polling) and `stop()`
wakes it.

## Configuration

Three files describe a run (design §1, §2):

1. **System config** (`CPSL_TI_Radar_cpp/config/system/*.json`, schema v2,
   read by `SystemConfigReader`): `"schema_version": 2`, `board`,
   `board_overrides`, `radar_cfg`, `cli.port`, `serial_stream`, `dca1000`,
   `output` (`dir`, `save_adc_frames`, `save_raw_lvds`) and `runtime`
   (`log_level`, `stall_timeout_ms`, `frame_queue_depth`, and since core-15
   `rx_cpu`, `worker_cpu`, `rx_priority`, `worker_priority`; all applied). `Radar::open` creates `output.dir`. Paths resolve against the JSON file's directory. Loading
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
board without LVDS); an error fails the load. Loading a descriptor also
checks that `data_uart.header_bytes` matches `tlv_dialect` (36 for `sdk2`,
40 otherwise).

**Dispatch.** No component branches on a board name; each reads descriptor
fields through `SystemConfigReader::getBoard()`:

| Behaviour | Descriptor field | Used in |
|-----------|------------------|---------|
| cfg commands sent | `cli.skip_prefixes`, `cli.start_cmd`, `cfg_dialect.skip_commands` (`filter_cfg_commands`) | `CLIController` |
| CLI handshake | `cli.baud`, `ack`, `prompt`, `prompt_wait_ms`, `cmd_timeout_ms`, `stop_timeout_ms`, `start_cmd`, `stop_cmd` | `CLIController` |
| Rx count, frame period | `cfg_dialect.rx_mask_fields`, `frame_period_field` | `RadarConfigReader` |
| Data UART | `data_uart.baud`, `timeout_ms`, `tlv_dialect` (and the matching `header_bytes`) | `SerialStreamer`, `parse_uart_frame` |
| DCA1000 FPGA setup | `lvds.lanes`, `dca1000.packet_bytes`, `packet_delay_us`, `fpga_timer_s` | `UdpPacketSource` |
| ADC decoder | `lvds.layout`, `lvds.iq_order` | `ADCCubeConverter` |
| One cfg per power-up | `lifecycle.config_once_per_boot` | `Radar` |

`cfg_dialect.skip_commands` drops commands the board's firmware rejects
before they are sent (the IWR1843 skips `calibData`); the `.cfg` files keep
the line, and a skipped command does not count as unacknowledged.

DCA1000 network defaults: FPGA `192.168.33.180`, host `192.168.33.30/24`,
command port 4096, data port 4098.

Supported boards: `IWR1843`, `IWR6843` (2-lane, non-interleaved),
`IWR1443` (4-lane, interleaved; serial `sdk2` confirmed from TI source but
not yet run on the board), `AWR2243_CASCADE` (serial TLV only so far;
data port 3,125,000 baud).

## Host prerequisites

See `CPSL_TI_Radar_cpp/Readme.md`: raise `net.core.rmem_max` to
134217728 (at least `dca1000.rcvbuf_bytes`: the kernel caps the request
at `rmem_max` and reports twice the capped value, the `rcvbuf` stat;
`tools/setup/host_setup.py --apply` does it). Serial ports need the `dialout` group. SCHED_RR is optional
(`cap_sys_nice` or an `rtprio` limit, only if you set a priority).
