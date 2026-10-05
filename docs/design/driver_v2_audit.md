# Driver v2 audit

Audit of `CPSL_TI_Radar_cpp/` at commit `d3d7aa5` (`release/v2.0`, after
core-01 and core-02), written for directive core-03 (issue #18). Paths are
relative to `CPSL_TI_Radar_cpp/`; `file:line` refers to that commit. The
design that answers these findings is
[`driver_v2_design.md`](driver_v2_design.md).

Claims marked **HYPOTHESIS** have not been isolated by an experiment (rule 9).
Each one names the experiment that would settle it.

Running example: the core-04 baseline config
`config/system/front_radar_IWR1843_stress_test.json`, which loads
`config/radar/nav_configs/1843_stress_test.cfg`. That config has 4 Rx, 250
samples, 2 chirps x 63 loops = 126 chirps, and a 100 ms period. That gives
`bytes_per_frame` = 4 x 4 x 250 x 126 = 504,000 B, which is about 345 UDP
packets per frame and about 5 MB/s.

## (a) Hot-path costs

### DCA1000 raw-ADC path, per frame

The packet path goes from the RX thread to the worker thread, then to the
consumer.

| # | Pass over the frame's bytes | Evidence | Allocation |
|---|-----------------------------|----------|------------|
| 1 | kernel → ring slot (`recvfrom`, one syscall per packet) | `src/DCA1000/DCA1000Socket.cpp:183-184` | none |
| 2 | ring slot → stack `pkt_buf` | `DCA1000Socket.cpp:158-160`, `src/DCA1000/DCA1000Handler.cpp:473-475` | none |
| 3 | `pkt_buf` → frame buffer, **one byte at a time** with a bounds check per byte | `src/DCA1000/FrameAssembler.cpp:103-110` | none |
| 4 | frame buffer → `completed_frame_` (full copy) plus re-zeroing the whole buffer | `FrameAssembler.cpp:52-56` | `assign` (may reuse) |
| 5 | bytes → `vector<int16_t>` | `src/DCA1000/ADCCubeConverter.cpp:35-45` | 1 per frame |
| 6 | int16 → 2D "reshape" (4 or 8 row vectors) | `ADCCubeConverter.cpp:48-61` | 5 or 9 per frame |
| 7 | 2D → `vector<complex>` (2-lane path only) | `ADCCubeConverter.cpp:65-80`, `:105` | 1 per frame |
| 8 | complex → nested `cube_` with strided writes (chirp is the innermost index, so every write jumps rows) | `ADCCubeConverter.cpp:89-97`, `:108-114` | none |
| 9 | `return cube_` by value: a deep copy of `vector<vector<vector>>` | `ADCCubeConverter.cpp:32` | 1 + Rx + Rx x samples (1,005 for the example) |
| 10 | consumer `get_latest_adc_cube()` deep-copies again under the lock | `DCA1000Handler.cpp:534-536` | about 1,005 again |

The current path makes about 9 user-space passes over each frame and about
2,000 heap allocations per frame. A contiguous buffer would need one pass
(packet → frame) plus one conversion pass, with no allocations in steady
state. The design's P2/P3 items target this.

### Locks, syscalls and thread handoff

- **Per-packet futex wake.** The RX thread calls `notify_one()` after every
  packet (`DCA1000Socket.cpp:188`). The worker takes a mutex and runs
  `wait_for` on every pop, even when data is already queued
  (`DCA1000Socket.cpp:144-150`).
- **Per-packet stop-flag mutex.** The worker locks and unlocks
  `stop_called_mutex` once per packet (`src/Runners/Runner.cpp:260-267`). An
  `std::atomic<bool>` would do the same job.
- **No batching.** There is one `recvfrom` per 1472-byte datagram
  (`DCA1000Socket.cpp:183`). `recvmmsg` is not used anywhere (checked with
  `grep`).
- **Ring-full policy throws data away.** When the 512-slot ring is full, the
  RX thread reads the next datagram into a discard buffer and counts an
  overrun (`DCA1000Socket.cpp:174-179`). This turns consumer back-pressure
  into guaranteed loss, even though the 64 MB `SO_RCVBUF`
  (`DCA1000Socket.hpp:39`, `.cpp:64-70`) could have absorbed the burst. The
  ring holds 512 x 1472 B, about 0.75 MB or 1.5 frames of the example.
- **Consumer polling.** `get_next_adc_cube` and both
  `get_next_tlv_detected_points` overloads poll a flag every 5 ms
  (`Runner.cpp:320-332`, `:353-365`, `:393-404`). This adds up to 5 ms of
  latency per frame.
- **Lost-wakeup race.** The consumer copies the cube and then clears
  `new_frame_available` under a second lock (`DCA1000Handler.cpp:534-541`).
  A frame that completes between those two steps is never signalled. The
  serial path has the same pattern (`src/SerialStreamer/SerialStreamer.cpp:277-284`).
- **Queue growth and back-pressure.** There is no queue, only "latest frame
  wins". An overwritten frame is not counted anywhere: `save_frame_byte_buffer`
  overwrites `adc_data_cube` without checking the flag
  (`DCA1000Handler.cpp:684-693`).
- **Hot-path printing.**
  - `std::cout << … << std::endl` runs on every drop event
    (`FrameAssembler.cpp:85`, `:96`). In a drop storm, each line flushes stdout
    from the worker thread.
  - With `verbose`, every frame prints six `endl`-flushed lines
    (`DCA1000Handler.cpp:649-659`) and every serial frame prints eight
    (`SerialStreamer.cpp:462-464`, `:485-496`).
- **CPU affinity and priority.** There is no affinity anywhere (`grep
  affinity` finds nothing). Priorities are hard-coded:
  - RX thread: SCHED_RR 99 (`DCA1000Socket.cpp:99-104`).
  - DCA worker: SCHED_RR 80 (`Runner.cpp:231-243`).
  - Serial worker: default policy (`Runner.cpp:279`).

  `docs/ARCHITECTURE.md` says "SCHED_RR priority 10" for both workers, which
  is wrong.
- **File output.** `write_adc_data_cube_to_file` makes two `ofstream::write`
  calls per sample: 252,000 calls per frame for the example
  (`DCA1000Handler.cpp:734-755`). The on-disk order is chirp → Rx → sample,
  with I then Q. That is the native 2-lane LVDS order, so a contiguous frame
  could be written with a single `write`. The raw LVDS file gets one buffered
  write per packet (`DCA1000Handler.cpp:484-489`), which is fine.

### Serial TLV path

- **One frame of latency.** `async_read_until(magic_word)` ends a message at
  the *next* frame's magic word (`SerialStreamer.cpp:344-354`). Each point
  cloud is therefore delivered one frame period late: 50 ms at 20 Hz. The C++
  `Readme.md` already admits this. The header carries `totalPacketLen`
  (`SerialStreamer.cpp:454`), so a length-driven read could deliver the frame
  as soon as its last byte arrives.
- **Per-frame allocations:**
  - message buffer: `SerialStreamer.cpp:371`
  - one `vector` per TLV: `:563-566`
  - one `vector<float>` per detected point: `src/SerialStreamer/TLVProcessing.cpp:40-43`, `:96-99`
  - a full copy for the consumer: `SerialStreamer.cpp:276-279`
  - a `stringstream` hex conversion of two header fields every frame: `:453-455`, `:652-657`
- The deprecated `io_context::reset()` runs once per frame and once per CLI
  command (`SerialStreamer.cpp:365`, `src/CLIController/CLIController.cpp:202`).

### Build

- **No build type is set.** The documented build command
  (`cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build`) does not set
  `CMAKE_BUILD_TYPE`, and no `CMakeLists.txt` sets a default (`grep
  CMAKE_BUILD_TYPE` finds nothing). A fresh build from the README is
  therefore **unoptimized** (no `-O` flag on GCC). The local
  `build/CMakeCache.txt` holds `CMAKE_BUILD_TYPE=Release`, set outside the
  documented command.
  - **HYPOTHESIS:** this is the largest single CPU cost on a fresh checkout.
    Experiment: run the core-04 harness twice, once with an empty build type
    and once with `Release`, on the same config.
  - **Action for core-04:** its sidecar must record the build type.

## (b) Hard-coded board knowledge that should be data

| Knowledge | Where | Becomes (design §1) |
|-----------|-------|---------------------|
| Board whitelist | `src/utilities/SystemConfigReader.cpp:469-475` | the set of descriptor files |
| Cascade cannot use the DCA1000 | `SystemConfigReader.cpp:477-482` | `lvds.supported: false` |
| SDK major → board (2→IWR1443, 3→IWR1843) | `SystemConfigReader.cpp:490-505` | removed; the descriptor names the SDK |
| LVDS lane count (4 for 1443, 2 for 1843/6843) | `DCA1000Handler.cpp:381-391` | `lvds.lanes` |
| ADC layout chosen by board name | `ADCCubeConverter.cpp:24-31` | `lvds.layout`, cross-checked against the cfg's `adcbufCfg` |
| I/Q order of the 2-lane format (first pair → imag) | `ADCCubeConverter.cpp:72-78` | `lvds.iq_order` (see the I/Q note below) |
| Complex samples assumed (4 B per sample) | `src/utilities/RadarConfigReader.cpp:132` | parsed from the cfg's `adcbufCfg`/`adcCfg` output format |
| DCA1000 FPGA settings: raw mode, LVDS capture, Ethernet, 16-bit, 30 s timer, 1472 B packets, 100 µs delay | `DCA1000Handler.cpp:378-403`, `:594-595` | `dca1000` descriptor block |
| One cfg per boot (cascade) | `Runner.cpp:94-101`, `:217-220` | `lifecycle.config_once_per_boot` |
| CLI handshake: `Done`, prompt `mmwDemo:/>`, 500 ms prompt wait, `sensorStart`/`sensorStop` | `CLIController.cpp:223`, `:229`, `:135`, `:156`, `:165` | `cli` descriptor block |
| Default baud rates 115200 / 921600 (cascade data port needs 3,125,000) | `SystemConfigReader.cpp:15-18`, `:42-45` | `cli.baud`, `data_uart.baud` |
| `frameCfg` period field index guessed from field count (≥10 fields → cascade) | `RadarConfigReader.cpp:268-274` | `cfg_dialect.frame_period_field` |
| `channelCfg` slave Rx mask when there are ≥6 fields | `RadarConfigReader.cpp:285-289` | `cfg_dialect.rx_mask_fields` |
| UART header size (32 B after the magic word) and type-1 float x/y/z/v points | `SerialStreamer.cpp:429-460`, `TLVProcessing.cpp:27-57` | `data_uart.header_bytes`, `data_uart.tlv_dialect` |
| Cascade TLV codes defined but never parsed (10, 104) | `src/SerialStreamer/TLVProcessing.hpp:21-22` | `tlv_dialect`; parsers are code |

**Serial path for IWR1443 (HYPOTHESIS).** The serial path probably mis-parses
IWR1443 frames. The parser assumes the SDK 3 header (8 words after the magic
word, including `subFrameNumber`) and SDK 3 type-1 points (four float32 values
per point).

- From memory, the SDK 2.x xWR14xx demo sends a 7-word header with no
  `subFrameNumber`, and type-1 objects as a Q-format descriptor followed by
  12-byte `int16` records.
- No SDK 2 source is available locally to check this (`firmware_dev` holds
  only the 18xx and cascade `mmw_output.h`).
- Experiment: a Researcher reads `mmw_output.h`/`detected_obj.h` from the
  xWR14xx SDK 2.x package, or someone captures one IWR1443 UART frame.

## (c) API and ownership problems that block reuse as a library

- **Public mutable state.**
  - `initialized` is public on every class (`src/Runners/Runner.hpp:30`,
    `src/DCA1000/DCA1000Handler.hpp:26`,
    `src/SerialStreamer/SerialStreamer.hpp:35`, …).
  - `new_frame_available` is public even though it is guarded by a private
    mutex (`DCA1000Handler.hpp:28`, `SerialStreamer.hpp:38`).
- **Copyable owners of OS resources.**
  - `DCA1000Handler` has a hand-written copy constructor and assignment
    operator. They share `ofstream`s and give the copy a fresh, unbound
    socket while marking it `initialized` (`DCA1000Handler.cpp:70-94`,
    `:96-132`).
  - `SerialStreamer` and `CLIController` copies share one `serial_port`
    through `shared_ptr` (`SerialStreamer.cpp:81-108`,
    `CLIController.cpp:36-62`). Two objects can then read one port.
  - `Runner`'s copy is disabled only by a comment (`Runner.hpp:56-60`). The
    implicit copy happens to be deleted because of its mutex and thread
    members.
- **Config held by value four times.** Each of `Runner`, `DCA1000Handler`,
  `SerialStreamer` and `CLIController` keeps its own `SystemConfigReader`
  copy (`Runner.hpp:37`, `DCA1000Handler.hpp:37`, `SerialStreamer.hpp:54`,
  `CLIController.hpp:39`).
- **Error handling.**
  - Errors are reported as `bool` plus an unconditional `std::cout`/`cerr`
    print everywhere. There is no log sink or log level, apart from
    `verbose`.
  - Exceptions escape the library:
    - `json::parse` and `.get<T>()` (`SystemConfigReader.cpp:336`, `:341`, …)
    - `std::stoi`/`stof` on cfg fields (`RadarConfigReader.cpp:237-290`)
  - `operator[]` on short cfg lines is out of bounds
    (`RadarConfigReader.cpp:237-241`, `:252-253`, `:264-266`). This was
    reported in core-02.
  - Members such as `profileCfg_adc_samples` are uninitialized when their cfg
    line is missing (`RadarConfigReader.hpp:46-63`). Only `rx_antennas` gets
    a default (`RadarConfigReader.cpp:112`).
- **Partial initialization is accepted silently.** If DCA1000 initialization
  fails but the serial streamer succeeds, the `Runner` still reports
  `initialized` (`Runner.cpp:84-89`). `start_dca1000` then runs on an
  uninitialized handler (`Runner.cpp:155-162`).
- **Return values ignored.**
  - `send_recordStart()` result: `Runner.cpp:157`
  - `send_command()` result in every DCA1000 command: `DCA1000Handler.cpp:209`, `:237`, …
- **Data races.** `running_dca1000` and `running_serial` are written without
  their mutex (`Runner.cpp:158`, `:180`, `:224-225`) and with it from the
  worker thread (`:274-276`, `:305-307`).
- **Lifecycle.**
  - **Streams end permanently on one timeout.** A single timeout (500 ms DCA,
    `timeout_ms` serial) ends that stream for the rest of the run, because
    the worker loop `break`s (`Runner.cpp:268-271`, `:299-302`). A cfg with a
    frame period above 500 ms cannot stream raw ADC at all.
  - **Stop runs twice.** `stop()` is not idempotent. `main` and `~Runner`
    both call it, so `recordStop` and `sensorStop` are sent twice
    (`Runner.cpp:48-52`, `:198-221`).
  - **Unsafe signal handler.** The SIGINT handler calls `Runner::stop()` and
    `exit(0)` from signal context. Neither is async-signal-safe
    (`main.cpp:15-22`).
- **Output paths.** The output files are hard-coded names in the current
  working directory (`adc_data.bin`, `LVDS_Raw_0.bin`:
  `DCA1000Handler.cpp:707`, `:715`). Two radars run from one directory
  overwrite each other's files.
- **Data shape.** The ADC cube API is `vector<vector<vector<complex<int16_t>>>>`
  returned by value (`Runner.hpp:73-75`). Points are `vector<vector<float>>`
  (`Runner.hpp:76-82`). Neither carries a frame index, timestamp or drop
  count.
- **Testability.** There are no seams for transports. Tests reach
  `SerialStreamer` internals with `#define private public`
  (`tests/test_serial_streamer_frames.cpp:23`).
- **Initialization order.** The DCA1000 FPGA is configured before the radar
  cfg is loaded (`DCA1000Handler.cpp:177-189`). That works today, but it
  stops a cfg-derived FPGA setting (for example real-only data) from being
  applied.

## (d) Stale comments, dead code, C++14/CMake modernization

**Stale or wrong text:**
- `main.cpp:40` `// DCA1000Runner dca1000_runner(config_file);`: the class was removed in core-01.
- `main.cpp:29-30`: commented-out config paths.
- `src/DCA1000/ADCCubeConverter.hpp:10-11` says "four LVDS lanes" for the IWR1843/6843 format. The DCA1000 is set to 2 lanes for those boards (`DCA1000Handler.cpp:384-386`). The "4" is the four int16 words per two samples.
- `TLVProcessing.hpp:17`: a garbled duplicate constant `STMMWDEMO_OUTPUT_MSG_DETECTED_POINTS_SIDE_INFOATS = 7`.
- `SerialStreamer.cpp:180-181` says "cli controller" in the serial streamer's error. `SystemConfigReader.hpp:69` closes with a `RADAR_CONFIG_READER_H` comment.
- `SerialStreamer.cpp:378-391`, `:400-408`: blocks of commented-out debug code.
- `SystemConfigReader.cpp:108-109`: assignments joined with `,` (the comma operator) instead of `;`.
- `CPSL_TI_Radar_cpp/Readme.md:241-247` documents `Processor` and `ROS/Listeners` JSON sections. No code reads them.
- `docs/ARCHITECTURE.md` gives the wrong worker priority (see (a)).

**Dead code:**
- `src/utilities/JSONHandler.{hpp,cpp}` is compiled into `Utilities` (`src/utilities/CMakeLists.txt:3`) but nothing references it (`grep JSONHandler::`).
- `DCA1000Handler::write_vector_to_file` (`DCA1000Handler.cpp:761-777`) has no caller.
- `udp_packet_buffer` (`DCA1000Handler.cpp:624`) is never read.
- `RadarConfigReader` parses `chirpCfg`, start frequency, idle time and ramp end time and never uses them (`RadarConfigReader.cpp:237-239`, `:249-254`).
- The `SDK_version` getters are used only by tests.

**Duplication:**
- The seven `send_*` DCA1000 commands repeat the same send / receive / parse-status block (`DCA1000Handler.cpp:203-462`).
- Constructors repeat member-init lists (`Runner.cpp:7-46`, `SerialStreamer.cpp:11-74`, …).

**C++14:**
- `CMakeLists.txt:9` sets C++14. A C++17 bump would allow:
  - `std::filesystem` for the hand-rolled path join at `SystemConfigReader.cpp:353-357`
  - `std::optional` and `string_view`
  - `[[nodiscard]]` on the `bool` results that are being ignored

  This is a user decision (design §8).
- `le16toh`/`le32toh` are applied *after* the bytes have already been
  assembled little-endian by hand (`ADCCubeConverter.cpp:40-42`,
  `FrameAssembler.cpp:33-38`, `:42-49`, `SerialStreamer.cpp:618-623`). That
  is a no-op on x86 and a double swap on a big-endian host. The `<endian.h>`
  calls are also Linux-only.

**CMake:**
- One central include block in `src/CMakeLists.txt:101-133` adds include
  dirs for only 4 of 11 targets. `Utilities`, `FrameAssembler`,
  `ADCCubeConverter`, `DCA1000Commands`, `DCA1000Socket` and `TLVProcessing`
  export none. As a result:
  - The tests have to add raw `src/` subdirectories by hand (`tests/CMakeLists.txt:26-32`, `INCLUDES`).
  - The install interface has no paths for those targets.
- `find_package(Threads)` is called after the target that links
  `Threads::Threads` (`src/DCA1000/CMakeLists.txt:10-12`).
- Boost (used by `SerialStreamer` and `CLIController`) is never found or
  linked. It works only because its headers sit in `/usr/include`.
- `DEFAULT_CONFIG_PATH` bakes an absolute source path into the binary
  (`CMakeLists.txt:34-36`).
- Eleven separately installed micro-libraries are exported
  (`CMakeLists.txt:50`) instead of one public target.
- `project(... VERSION 0.1.0)` (`CMakeLists.txt:2`) does not reflect v2.0.
- There is no default build type (see (a)).

## Known bugs carried in from core-02

These are pinned in `tests/` with `KNOWN_BUG`. They are confirmed here and
assigned a fix in the design (§6).

- `FrameAssembler.cpp:95-100`: on a byte-count mismatch the packet's payload
  bytes are copied (`:103-110`) but not counted in `adc_data_byte_count_`.
- `FrameAssembler.cpp:58-72`: `zero_pad` finalizes at most one frame and
  drops the overshoot past a frame boundary.
- `FrameAssembler.cpp:84-92`: a duplicate or out-of-order packet
  (`seq_num <= received_packets_`) makes `seq_num - received_packets_ - 1`
  underflow, giving about 4e9 drops.
- `SerialStreamer.cpp:451-469`: header fields such as `header_frameNumber`
  are published before `check_valid_message()` rejects the frame.
- Untested UB:
  - `TLVProcessing.cpp:63-68` reads past the end when the TLV length is not a
    multiple of 4.
  - `push_packet` called before `configure()` indexes an empty buffer
    (`FrameAssembler.cpp:105`).
  - `RadarConfigReader` short-line indexing and uninitialized members (see (c)).

**Root cause.** All three FrameAssembler bugs come from one design choice. The
assembler tracks its own running byte count and patches it on mismatch,
instead of placing each payload at the absolute offset the packet header
already gives (`parse_byte_count`, `FrameAssembler.cpp:41-50`). Design §5 P1
replaces the bookkeeping with direct placement.

## I/Q lane order (`ADCCubeConverter.cpp:72-78`): open question

The code treats each group of four int16 words in the 2-lane (IWR1843/6843)
stream as `[Q0, Q1, I0, I1]`, with the first pair assigned to `imag`.

**What TI documents (authoritative source found).** TI SWRA581B, *mmWave
Radar Device ADC Raw Data Capture* (rev. Oct 2018):
- §7 (xWR16xx/IWR6843 with DCA1000): "lane 1 contains the real part … lane 2
  contains the imaginary part … The saved file has non-interleaved format
  beginning with the real part of every two samples and followed by the
  imaginary part of the every two samples."
- §9.2 MATLAB reader: `%read in file: 2I is followed by 2Q`, then
  `LVDS(counter) = adcData(i) + sqrt(-1)*adcData(i+2)`.

So, for mmWave Studio captures with "I first" (§5), the first pair is
**real**, which is the opposite of this code.

**Why it is still unresolved for this repo.** The repo captures through the
SDK demo, not mmWave Studio. Every repo cfg sets `adcbufCfg` `sampleSwap = 1`:
`-1 0 1 1 1` on the SDK 3 boards (40+ files) and `0 1 0 1` on the SDK 2
IWR1443 files. In the SDK 3 user guide's description of `adcbufCfg`,
sampleSwap 1 means "Q in LSB, I in MSB" (quoted from memory, not re-checked
here), which would put Q first on the wire. That would make the code right
for these cfgs.

But the IWR1443 (4-lane) path assigns the *first* group to `real`
(`ADCCubeConverter.cpp:93-94`), matching SWRA581B §5's "I first", under the
same `sampleSwap = 1`. The two paths contradict each other unless the SDK 2
and SDK 3 HSI paths treat the swap bit differently.

**HYPOTHESIS:** the 2-lane path is correct for `sampleSwap=1` cfgs and wrong
for `sampleSwap=0`.

**Discriminating bench check (proposed for core-04).** Swapping I and Q turns
`x` into `j·conj(x)`, which mirrors the range spectrum.
1. Put one corner reflector or a flat plate at a measured range `R`, about
   2–3 m, with nothing else near it.
2. Capture one DCA1000 frame on the IWR1843 with
   `1843_stress_test.cfg`.
3. Take the range FFT of one chirp/Rx with
   `utilities/process_adc_data.ipynb`.

A peak at bin `R / range_resolution` means the current order is right. A peak
at `N - that bin` means I and Q are swapped. The result sets the descriptor's
`lvds.iq_order` (design §1). No code change is needed either way after core-09.

## Notes for core-04 (baseline)

- **Short run.** `1843_stress_test.cfg` has `frameCfg … 30 100 …`: 30 frames,
  then the sensor stops. A 60 s run would end after about 3 s and then hit
  the 2 s timeout in `main.cpp:50-75`. The baseline needs `numFrames = 0` (a
  copy of the cfg) or a run length matched to the cfg.
- **Build type.** Record `CMAKE_BUILD_TYPE` in the sidecar (see (a)).
