# Driver v2 design

Design for reworking `CPSL_TI_Radar_cpp/` into a faster, config-driven v2.0
driver. Written for directive core-03 (issue #18). The evidence behind each
item is in [`driver_v2_audit.md`](driver_v2_audit.md), cited below as
"audit (a)…(d)".

**Ground rules (user rulings, 2026-10-05):**
- v2.0 may break the v1 config schema, the CLI and the library API.
- Every supported board (IWR1443, IWR1843, IWR6843, AWR2243 cascade) must run
  from config/data alone, with no recompile.
- No performance change lands before core-04's IWR1843 baseline exists.
- Every follow-up directive keeps the docs accurate.

**What "config only" means.** Adding or tuning a board whose LVDS layout,
UART dialect and cfg dialect the driver already implements is a **data file
only**. A board with a genuinely new wire format (for example cascade 4-lane
raw ADC) needs a new decoder in code. That is the honest limit; the
descriptor names the decoder so the rest stays data.

## 1. Board descriptor

**Location and selection.**
- One JSON file per board in `CPSL_TI_Radar_cpp/config/boards/<name>.json`.
- The system config names it with `"board": "IWR1843"` (a file in that
  directory) or with a path.
- It may override any field with a `board_overrides` object, which is
  deep-merged.
- Unknown keys are a load error, which catches typos. Every file carries
  `"schema": 1`.

```json
{
  "schema": 1,
  "name": "IWR1843",
  "sdk": "mmwave_sdk_3",
  "cli":       { "baud": 115200, "ack": "Done", "error_tokens": ["Error", "not recognized"],
                 "prompt": "mmwDemo:/>", "prompt_wait_ms": 500, "cmd_timeout_ms": 100,
                 "start_cmd": "sensorStart", "stop_cmd": "sensorStop", "skip_prefixes": ["%", "#"] },
  "lifecycle": { "config_once_per_boot": false },
  "cfg_dialect": { "rx_mask_fields": [1], "frame_period_field": 5 },
  "data_uart": { "baud": 921600, "header_bytes": 40, "tlv_dialect": "sdk3", "timeout_ms": 1000 },
  "lvds":      { "supported": true, "lanes": 2, "layout": "two_lane_iq_pairs", "iq_order": "q_first" },
  "dca1000":   { "packet_bytes": 1472, "packet_delay_us": 100, "fpga_timer_s": 30 }
}
```

| Field | Type / values | Replaces (audit (b)) |
|-------|---------------|----------------------|
| `name` | string; must match the file name | `board_type` whitelist |
| `sdk` | `mmwave_sdk_2` \| `mmwave_sdk_3` \| `mmwave_mcuplus` | `SDK_version` |
| `cli.*` | handshake strings and timings | `CLIController.cpp:135,156,165,223,229` |
| `lifecycle.config_once_per_boot` | bool. If true, `configure()` refuses a second cfg in one process and `stop()` prints the power-cycle note | `Runner.cpp:94-101,217-220` |
| `cfg_dialect.rx_mask_fields` | `channelCfg` field indices whose set bits are summed into the Rx count | `RadarConfigReader.cpp:285-289` |
| `cfg_dialect.frame_period_field` | `frameCfg` field index of the period (5, or 6 on the cascade) | field-count guess `RadarConfigReader.cpp:270-274` |
| `data_uart.header_bytes` | 40 (SDK 3, MCU+) or 36 (SDK 2, **HYPOTHESIS**, audit (b)) | fixed 32+8 |
| `data_uart.tlv_dialect` | `sdk3` (type 1 = float x/y/z/v, type 7 = int16 SNR/noise) \| `sdk2` (Q-format objects) \| `mcuplus_cascade` (sdk3 plus types 10/11/12) | `TLVProcessing.*` |
| `lvds.supported` | bool | cascade DCA1000 rejection `SystemConfigReader.cpp:477-482` |
| `lvds.lanes` | 2 \| 4 (sent in `CONFIG_FPGA_GEN`) | `DCA1000Handler.cpp:381-391` |
| `lvds.layout` | `two_lane_iq_pairs` (SWRA581B §6) \| `lane_per_rx` (SWRA581B §5 4-lane) | `ADCCubeConverter.cpp:24-31` |
| `lvds.iq_order` | `i_first` \| `q_first` | `ADCCubeConverter.cpp:72-78` |
| `dca1000.*` | FPGA packet size, delay and timer | `DCA1000Handler.cpp:403,594-595` |

**The four boards.** Values outside the shared defaults above:

| Field | IWR1443 | IWR1843 | IWR6843 | AWR2243_CASCADE |
|-------|---------|---------|---------|-----------------|
| `sdk` | mmwave_sdk_2 | mmwave_sdk_3 | mmwave_sdk_3 | mmwave_mcuplus |
| `cli.cmd_timeout_ms` | 100 | 100 | 100 | 5000 |
| `lifecycle.config_once_per_boot` | false | false | false | **true** |
| `cfg_dialect.rx_mask_fields` | [1] | [1] | [1] | [1, 4] |
| `cfg_dialect.frame_period_field` | 5 | 5 | 5 | 6 |
| `data_uart.baud` | 921600 | 921600 | 921600 | 3125000 |
| `data_uart.timeout_ms` | 1000 | 1000 | 1000 | 5000 (tracked cascade JSON; pre-gate keeps behaviour) |
| `data_uart.header_bytes` / `tlv_dialect` | 36 / sdk2 (to verify) | 40 / sdk3 | 40 / sdk3 | 40 / mcuplus_cascade |
| `lvds` | 4 lanes, `lane_per_rx`, `i_first` | 2 lanes, `two_lane_iq_pairs`, `q_first`* | same as 1843* | `supported: false` |

\* `q_first` keeps today's behaviour. The core-04 bench check (audit, I/Q
note) settles the value, and core-17 applies it.

**Cross-checks against the radar cfg.** These run at load time and fail with a
message rather than producing garbage data:
- `adcbufCfg` `chanInterleave` must match `lvds.layout`: interleaved goes with
  `lane_per_rx`, non-interleaved with `two_lane_iq_pairs`.
- `adcbufCfg`/`adcCfg` must give complex output. Real-only output halves
  `bytes_per_frame` and needs a `*_real` layout that does not exist yet, so
  it is rejected.
- `lvdsStreamCfg` must enable ADC streaming when `dca1000.enabled`.

**What still lives in code.** Each layout, each TLV dialect and the DCA1000
command protocol are C++ decoders. Each is selected by its string from a
closed registry, so an unknown value is a load error.

## 2. System-config schema v2

Example (IWR1843, DCA1000):

```json
{
  "schema_version": 2,
  "board": "IWR1843",
  "board_overrides": {},
  "radar_cfg": "../radar/nav_configs/1843_stress_test.cfg",
  "cli":           { "port": "/dev/ttyACM0" },
  "serial_stream": { "enabled": false, "port": "/dev/ttyACM1" },
  "dca1000": { "enabled": true, "fpga_ip": "192.168.33.180", "host_ip": "192.168.33.30",
               "cmd_port": 4096, "data_port": 4098, "rcvbuf_bytes": 67108864 },
  "output":  { "dir": "out/front_radar", "save_adc_frames": true, "save_raw_lvds": false },
  "runtime": { "log_level": "info", "frame_queue_depth": 4, "stall_timeout_ms": 0,
               "rx_cpu": null, "worker_cpu": null, "rx_priority": 99, "worker_priority": 80 }
}
```

**Rules.**
- Sections for disabled streams may be omitted.
- Anything set in the board descriptor (baud rates, timeouts) can be
  overridden per run with `board_overrides`.
- Paths resolve relative to the JSON file, as they do today.
- A file with no `schema_version` is v1. Loading it fails with a message that
  names the migration script (recommended; pending D8).

**Change list (v1 → v2):**

| v1 key | v2 | Note |
|--------|----|------|
| `verbose` | `runtime.log_level` (`"debug"` = old `true`) | required in v1, optional in v2 |
| `TI_Radar_Config_Management.TI_Radar_config_path` | `radar_cfg` | flattened |
| `CLI_Controller.CLI_port` | `cli.port` | |
| `CLI_Controller.baud_rate`, `.cmd_timeout_ms` | `board_overrides.cli.baud`, `.cmd_timeout_ms` | default from board |
| `Streamer.serial_streaming.{enabled,data_port}` | `serial_stream.{enabled,port}` | section optional if disabled |
| `Streamer.serial_streaming.{baud_rate,timeout_ms}` | `board_overrides.data_uart.{baud,timeout_ms}` | |
| `Streamer.DCA1000_streaming` | `dca1000` | section optional if disabled |
| `….FPGA_IP`, `….system_IP` | `dca1000.fpga_ip`, `dca1000.host_ip` | |
| `….data_port`, `….cmd_port` | `dca1000.data_port`, `dca1000.cmd_port` | |
| — | `dca1000.rcvbuf_bytes` | new (was hard-coded 64 MB) |
| `Streamer.save_to_file` | `output.save_adc_frames` + `output.save_raw_lvds` | split, plus a new `output.dir` (was CWD) |
| `Streamer.board_type` | `board` | names a descriptor |
| `Streamer.SDK_version` | **removed** | the descriptor carries `sdk` |
| `Processor`, `ROS/Listeners` | **removed** (Readme only, never read) | |
| — | `runtime.*` | new: queue depth, stall policy, affinity, priorities |

**Migration script.** `tools/migrate_config_v1_to_v2.py` (`uv run`) converts
every tracked v1 system config in one go. It is idempotent and reports any key it could
not map.

## 3. Target library API

A single public CMake target, `CPSL_TI_Radar::driver`, under namespace
`cpsl::radar`:

```cpp
// All fallible calls return Status/Result; nothing throws, prints unconditionally, or exits.
struct Status { Code code; std::string message; explicit operator bool() const; };
template <class T> struct Result { Status status; T value; };      // std::optional under C++17

struct RadarConfig {                       // system JSON + board descriptor + parsed .cfg, validated
  static Result<RadarConfig> load(const std::string& system_json);
  const BoardDescriptor& board() const;  const FrameShape& frame_shape() const;  // rx, samples, chirps, bytes
};

class Radar {                              // non-copyable, movable; destructor = stop()
 public:
  static Result<std::unique_ptr<Radar>> open(const RadarConfig&);   // opens ports/sockets only
  Status configure();                      // sends the cfg; honours config_once_per_boot
  Status start();                          // DCA recordStart, then sensorStart
  Status stop();                           // idempotent
  bool next_adc_frame(AdcFrame& out, std::chrono::milliseconds timeout);     // swaps a pooled buffer, no copy
  bool next_point_cloud(PointCloud& out, std::chrono::milliseconds timeout);
  Stats stats() const;                     // packets, drops, late/duplicate, overruns, kernel drops, frames overwritten
};
void set_log_sink(std::function<void(LogLevel, const std::string&)>);   // default: stderr at configured level

struct AdcFrame {                          // nested [rx][sample][chirp], same type as v1; buffers are pooled and reused
  uint64_t index; std::chrono::steady_clock::time_point completed_at;
  uint32_t missing_bytes; FrameShape shape;
  std::vector<std::vector<std::vector<std::complex<int16_t>>>> data;   // [rx][sample][chirp]
};
struct PointCloud { uint32_t frame_number; std::vector<Point> points; };  // Point{x,y,z,v,snr_db,noise_db}
```

**Why the nested `[rx][sample][chirp]` order is kept** (user ruling on D5, 2026-10-05). The user
wrote a note on this section, summarised here: the nested order was inherited from the IWR1443's
old notation, and keeping it matters because it affects everything downstream. The user
maintains several downstream dataset-generator and data-processing repos that depend on it. The
per-frame allocations the flat layout was meant to remove are removed another way: `AdcFrame`
buffers come from a pool of reused nested buffers and are still swapped on completion, never
copied. A flat layout is revisited only if `bench_pipeline` (core-09, core-14) shows the
converter is a real bottleneck. If a flat layout is ever adopted, the v2 README, the migration
note and the docs must call out the format change prominently so people migrating can adapt.
Because the type is unchanged, `CPSL_TI_Radar_ROS` is not broken by this.

**Internal seams for tests.**
- `PacketSource`: UDP or replay.
- `ByteStream`: serial port or in-memory buffer.
- A pure `parse_uart_frame(span) -> Result<UartFrame>`. This removes the
  `#define private public` in `tests/test_serial_streamer_frames.cpp`.

**CLI.** `CPSL_TI_Radar_CPP <system.json> [--validate] [--frames N]
[--duration S]`. A config argument is required: the baked-in
`DEFAULT_CONFIG_PATH` goes. `--validate` loads and cross-checks the config
without touching hardware; core-05's cold-reader check uses it. SIGINT sets an
atomic flag, and the main loop calls `stop()`.

## 4. Threading and data flow

```
RX thread (SCHED_RR rx_priority, rx_cpu)          worker (worker_priority, worker_cpu)              consumer
 recvmmsg batch ──> SPSC packet ring ──────────>  FrameAssembler: place payload at       ──> SPSC frame queue ──> next_adc_frame()
 (ring full: stop reading; kernel                 header byte offset into pooled frame        (depth N, drop-oldest   (cv wake, swap)
  SO_RCVBUF absorbs; SO_RXQ_OVFL counts)          converter: one pass, I/Q pairing             + frames_overwritten)
                                                  optional writer: one write() per frame
```

## 5. Performance plan

Gains below are **estimates** until measured. Each item is measured two ways:
- **Hardware-free:** a `bench_pipeline` replay target replays synthetic DCA1000
  packets (with injected drops, duplicates and reordering) through the
  assembler and converter. It reports frames/s, CPU ns per byte and heap
  allocations per frame (counting allocator).
- **On hardware (optional):** the core-04 harness reports frames/s, dropped
  packets, `rx_overrun_count`, kernel drops and process CPU%, compared against
  the `docs/RESULTS.md` baseline.

| ID | Change | Evidence | Expected gain (estimate) | Measure |
|----|--------|----------|--------------------------|---------|
| P0 | Default `CMAKE_BUILD_TYPE=Release` when unset | audit (a) Build | largest CPU drop on a fresh checkout (`-O0` → `-O2`) | replay CPU ns/byte; harness CPU% |
| P1 | Place each payload at `byte_count % bytes_per_frame` (frame = `byte_count / bytes_per_frame`); `memcpy` per packet; late or duplicate packets counted, not mis-counted | `FrameAssembler.cpp:84-110` | fixes 3 KNOWN_BUGs; assembly step several times faster than the per-byte loop | replay: frames equal golden, ns/byte |
| P2 | Pool of reused nested `[rx][sample][chirp]` frame buffers; swap on completion instead of copy | audit (a) rows 4, 9, 10 | about 2,000 → 0 allocations/frame; 3 full-frame copies removed | counting allocator |
| P3 | Converter writes in place into the reused nested buffer | rows 5–8 | 4 passes and their allocations → 1 pass over the packed bytes, no per-frame allocation | replay ns/byte |
| P4 | Pop packets by reference or in batches; notify only when the worker sleeps; atomic stop flag | `DCA1000Socket.cpp:144-160,188`; `Runner.cpp:260-267` | removes copy 2 and about 1 futex per packet | `perf stat` context switches; CPU% |
| P5 | `recvmmsg` (batch 32) | `DCA1000Socket.cpp:183` | syscalls per packet ÷ up to 32 | `strace -c` / CPU% |
| P6 | Ring full → stop reading (kernel buffer absorbs); count `SO_RXQ_OVFL` | `DCA1000Socket.cpp:174-179` | fewer drops under transient consumer stalls | harness drops with an injected stall |
| P7 | Condition-variable frame queue instead of 5 ms polling | `Runner.cpp:320-332` | ≤5 ms → µs consumer latency; no lost-wakeup race | timestamp delta frame complete → consumer |
| P8 | Serial: read the header, then exactly `totalPacketLen`; reuse buffers; flat `Point` | `SerialStreamer.cpp:344-376`, `TLVProcessing.cpp:40-43` | removes one frame period of latency (50 ms at 20 Hz) | timestamp delta vs frame period on a pty replay |
| P9 | Single-write file output, optionally on a writer thread. With the nested type this may need a flat staging buffer or per-rx writes; decide with bench data | `DCA1000Handler.cpp:734-755` | 252k calls → 1 per frame (or one per rx) | replay with `save_adc_frames` |
| P10 | No `endl`-flushed prints in per-packet or per-frame paths; periodic stats at `debug` | `FrameAssembler.cpp:85,96`; `DCA1000Handler.cpp:649-659` | removes stdout stalls in drop storms | replay with 1% injected drops |
| P11 | Configurable affinity and priorities | `DCA1000Socket.cpp:99-104`; `Runner.cpp:231-243` | lower jitter on loaded hosts | harness drops under `stress-ng` load |

**Ordering.** Every item lands after the core-04 gate, one commit per item,
each with a `bench_pipeline` before/after row (§7 measurement rule).
`bench_pipeline` itself lands first, in core-09, and does not change
behaviour. P1 goes with the correctness fixes (core-11). P0 gets its own
directive (core-12).

## 6. Test plan (on the core-02 net)

- **KNOWN_BUGs.** Every `KNOWN_BUG` turns into `CHECK` in the directive that
  fixes it:
  - core-11: FrameAssembler × 3, SerialStreamer header
  - core-16: parse_frame seam
- **New ctest suites** (all hardware-free):
  - `test_board_descriptor`: all four files load; unknown keys, bad enums
    and layout/cfg mismatches are rejected.
  - `test_system_config_v2`: parses the v2 schema. A v1 file gives the
    migration message.
  - Migration golden test: every tracked v1 JSON converts and loads as v2.
    Run under `uv run pytest`, plus a ctest that loads the outputs.
  - `test_frame_assembler` replay cases: drops, duplicates, reordering across
    a frame boundary, gaps longer than a frame, `push_packet` before
    `configure()` (returns an error).
  - `test_adc_layouts`: golden vectors per `layout × iq_order`.
  - `test_uart_parse`: SDK 3 frames, truncated TLVs, a length not divisible
    by 4.
  - `test_radar_e2e_fake`: `Radar` over a fake `PacketSource` and fake
    `ByteStream`, covering configure/start/stop idempotence, the stall
    policy, and `config_once_per_boot`. From core-14 it adds a
    publish-ordering case: no stale or duplicate frame under a racing
    consumer.
  - `test_dca_frame_publish` (core-11): the frame flag is never visible
    before the cube it announces.
- **Sanitizer preset.** A `CMakePresets.json` `asan-ubsan` preset runs the
  whole suite. It catches the TLV out-of-bounds read class of bugs.
- **Benchmark.** `bench_pipeline` (core-09) is built but not run by default
  ctest: it is registered with `CONFIGURATIONS bench`, and
  `ctest -C bench -L bench` runs it.
- **Keep the core-04 harness working.** `tools/bench/` (commit `a4ed54a`)
  reads v1 JSON keys (`verbose`, `Streamer`; `bench_run.py:87,154-155`) and
  parses the driver's stdout (`bench_lib.py:47-51`: `SO_RCVBUF granted`,
  `frame:`, tab-indented counters, `TLV frame`, `frame number jumped`). Any
  directive that changes those keys or lines updates the harness in the same
  commit. Since `d7a0a2b` the harness also records the build type and refuses
  non-Release builds. The v2 driver gets a stable `--stats` line format that the harness
  switches to in core-13. `uv run pytest tests/test_bench.py` is in those
  directives' Verify.
- **Hardware.** Only core-04 (baseline) needs it. After that, bench
  confirmation of a directive is an optional step through core-06's
  procedure, which the Controller offers to the user.

## 7. Follow-up directives (core-07+)

**Ordering rules.**
- core-07 to core-09 may land before core-04 finishes.
  - They delete dead code, restructure CMake with identical compile flags
    apart from `-I` order, or add new files and a new build target.
  - None changes the driver binary's behaviour or codegen. Behaviour-visible
    changes (CLI default config, `-std=c++17`) were moved to core-10 for
    that reason.
- core-10 and everything after waits for core-04's committed baseline.

**Every directive below:**
- includes a docs step that keeps `docs/ARCHITECTURE.md`,
  `CPSL_TI_Radar_cpp/Readme.md` and `README.md` accurate for what it changed;
- ends its Verify with **"docs match"**: a `grep` for every renamed key,
  class or path finds no stale mention in those three files, and the Reviewer
  reads the changed sections.

**Measurement rule.**
- Every perf item (P0–P11) lands in its own commit.
- That commit's directive Log carries a `bench_pipeline` row with ns/byte
  and allocations/frame, taken before and after on the same host and build
  type.
- `bench_pipeline` exists from core-09 on.

### core-07 Hygiene: stale comments, dead code, doc errors `[light]`

Needs: none (pre-gate).

**Steps.** Remove:
- the `main.cpp:29-30,40` comments
- `JSONHandler`
- `write_vector_to_file` and `udp_packet_buffer`
- the garbled `TLVCodes` constant
- the commented-out debug blocks

Fix:
- the comma operator
- the ARCHITECTURE worker priority
- the "four lanes" comment

Also remove the Readme's `Processor` and `ROS/Listeners` sections.

**Docs step.** ARCHITECTURE and the C++ Readme.

**Verify.**
- ctest green.
- `grep -rn "DCA1000Runner\|JSONHandler\|INFOATS" CPSL_TI_Radar_cpp/src CPSL_TI_Radar_cpp/main.cpp` is empty.
- The diff only deletes code or edits comments in `src/`.
- docs match.

### core-08 CMake modernization, flags unchanged `[light]`

Needs: none (pre-gate).

**Steps.**
- Per-target `target_include_directories` in each `src/*/CMakeLists.txt`.
- Delete the central block (`src/CMakeLists.txt:14-46`).
- Call `find_package(Threads/Boost)` before use.
- Tests drop `INCLUDES`.
- One exported `CPSL_TI_Radar::driver` interface target.
- `DEFAULT_CONFIG_PATH` and the C++ standard are **not** touched here.

**Docs step.** Readme build/install section and ARCHITECTURE build section.

**Verify.**
- ctest green.
- Compile flags in `compile_commands.json` are identical to before except for `-I` order.
- `tests/CMakeLists.txt` has no `INCLUDES`.
- `cmake --install` plus a 10-line consumer project builds.
- docs match.

### core-09 Board descriptors, loader, and `bench_pipeline` `[heavy]`

Needs: none (pre-gate).

**Steps.**
- Add `config/boards/{IWR1443,IWR1843,IWR6843,AWR2243_CASCADE}.json` per §1.
- `BoardDescriptor::load` with strict validation, and the cfg cross-checks as a function. Not wired into the runtime.
- Add the `bench_pipeline` replay target. It drives today's `FrameAssembler` and `ADCCubeConverter` with synthetic packets (`ctest -C bench -L bench`, not in the default run) and reports frames/s, ns/byte and allocations/frame.
- Record the first values in the Log for a Release build.

**Docs step.** ARCHITECTURE "Configuration" gains the descriptor. The Readme lists the board files and `ctest -C bench -L bench`.

**Verify.**
- `test_board_descriptor` passes (4 boards + 6 rejection cases).
- `bench_pipeline` runs and prints the three metrics; the Log row is pasted.
- The runtime source diff touches only new files.
- docs match.

**── Gate: core-04 baseline committed ──**

### core-10 Schema v2, migration, data-driven board dispatch, CLI, C++17 `[heavy]`

Needs: core-09, core-04.

**Steps.**
- v2 parser.
- `tools/migrate_config_v1_to_v2.py`, then migrate **every tracked v1 system config**.
- Replace every `board_type ==` check (audit (b)) with descriptor fields.
- `--validate` flag; require the config argument (remove `DEFAULT_CONFIG_PATH`).
- Update `tools/bench` to v2 keys.
- If D2 is approved, `-std=c++17` goes in its own commit with a `bench_pipeline` before/after row.

**Docs step.** README migration section gets §9's note. The Readme JSON section is rewritten for v2. ARCHITECTURE configuration section.

**Verify.**
- `grep -rn '"IWR1443"\|"IWR1843"\|"IWR6843"\|"AWR2243_CASCADE"' CPSL_TI_Radar_cpp/src` is empty.
- `--validate` passes for every tracked JSON; no-argument run prints usage.
- Migration golden test passes.
- `uv run pytest tests/test_bench.py` passes.
- ctest green.
- docs match.

### core-11 Correctness: FrameAssembler placement (P1), frame-flag ordering, core-02 bugs `[heavy]`

Needs: core-10.

**Steps.**
- P1 in its own commit, with a `bench_pipeline` before/after row.
- Publish the DCA frame flag **after** the cube is written, under one lock (audit (a), producer-side ordering bug).
- SerialStreamer validates before publishing.
- TLV length guard.
- RadarConfigReader bounds and initialization.
- `push_packet` pre-configure guard.
- `asan-ubsan` preset.

**Docs step.** ARCHITECTURE "UDP packet format" (byte-offset placement, late/duplicate counters).

**Verify.**
- All core-02 `KNOWN_BUG`s are `CHECK`s and pass.
- New `test_dca_frame_publish`: a consumer polling in the publish window never receives the previous frame flagged as new. Uses a hook between convert and publish.
- ctest green under `asan-ubsan`.
- Replay golden frames equal.
- docs match.

### core-12 Default Release build (P0) `[light]`

Needs: core-11.

**Steps.**
- Default `CMAKE_BUILD_TYPE=Release` when unset; print it at configure time.

**Docs step.** Readme build section.

**Verify.**
- `cmake` with no build type gives `-O2`/`-O3` in `compile_commands.json`.
- `bench_pipeline` row before/after (empty vs Release).
- Optional bench row through core-06.
- docs match.

### core-13 Library API v2 (`Radar`, `RadarConfig`, `Status`, log sink) `[heavy]`

Needs: core-10, core-11.

**Steps.**
- The §3 API over today's internals.
- No `exit`, no unconditional prints, no escaping exceptions.
- Idempotent stop; stall policy; signal flag in `main`.
- Non-copyable owners; fake-transport seams.
- A stable `--stats` line format, with `tools/bench` switched to it.

**Docs step.** ARCHITECTURE component graph and API. Readme usage. README. This unblocks the OUTLINE "API" lessons.

**Verify.**
- `test_radar_e2e_fake` passes.
- `grep -rn "exit(\|std::cout" CPSL_TI_Radar_cpp/src` finds hits only in the log sink.
- `uv run pytest tests/test_bench.py` passes against `--stats`.
- docs match.

### core-14 Zero-copy DCA pipeline (P2, P3, P7, P9, P10) `[heavy]`

Needs: core-13, plus D5 and D10 (and D11 for output files).

**Steps.** One commit per item, in this order:
1. P10 quiet hot path
2. P2 pool of reused nested buffers
3. P3 converter writes in place into the reused nested buffer
4. P7 cv frame queue with `frames_overwritten`
5. P9 single-write file output (may need a flat staging buffer or per-rx writes; decide with bench data)

**Docs step.** ARCHITECTURE "ADC cube layout" and "RX path". Readme output files.

**Verify.**
- The Log has five `bench_pipeline` rows, one per commit (ns/byte, allocations/frame), each measured against the previous commit.
- Steady state reaches 0 allocations/frame.
- `adc_data.bin` is byte-identical to the old writer on a replay.
- `test_radar_e2e_fake` gains a publish-ordering case: no stale or duplicate frame through the queue under a consumer racing the producer.
- `uv run pytest tests/test_bench.py` passes.
- Optional bench row vs baseline.
- docs match.

### core-15 RX socket: batching, back-pressure, affinity (P4, P5, P6, P11) `[heavy]`

Needs: core-14.

**Steps.** One commit per item:
- `recvmmsg`
- no discard on a full ring, plus a `SO_RXQ_OVFL` counter
- runtime affinity and priorities

**Docs step.** ARCHITECTURE RX path. Readme host prerequisites.

**Verify.**
- A row per commit from `bench_pipeline --udp` (loopback), including a `strace -c` excerpt for P5.
- No user-space discard under an injected 200 ms stall within SO_RCVBUF.
- ctest green.
- docs match.

### core-16 Serial path rework (P8), `parse_uart_frame` seam, TLV dialects `[heavy]`

Needs: core-13; D6, D7.

**Steps.**
- Length-driven framing.
- Pure parser.
- `sdk3` and `mcuplus_cascade` dialects; `sdk2` only once confirmed.
- Remove `#define private public`.
- If D6 is approved, drop Boost.

**Docs step.** The Readme drops the "one frame old" note. ARCHITECTURE serial path.

**Verify.**
- `test_uart_parse` passes.
- pty replay delivers each frame before the next magic word (timestamp check).
- Tests contain no `#define private`.
- docs match.

### core-17 Apply the I/Q bench result `[light]`

Needs: core-09 and the core-04 `tools/bench/iq_check.py` result (30b3b34).

**Steps.**
- Set `lvds.iq_order` for IWR1843/6843 from the core-04 bench check.
- Add a golden test on the committed capture.

**Docs step.** ARCHITECTURE ADC layout cites SWRA581B §6 and the bench result.

**Verify.**
- The range-FFT peak of the capture lands at the reflector bin in a ctest or pytest.
- docs match.

**Not proposed (design question only):** cascade 4-lane raw ADC (D4).

## 8. Decisions needed (user)

The user ruled on 2026-10-05 (source: `plans/history.md`): every recommendation
was accepted except D5. §3, §5, §7 and §9 reflect the rulings.

| # | Question | Recommendation | User ruling (2026-10-05) |
|---|----------|----------------|---|
| D1 | nlohmann_json: vendored submodule or system package? | Keep the pinned submodule as the default (offline, reproducible, Docker-simple). Add `CPSL_USE_SYSTEM_JSON=ON` to use `find_package(nlohmann_json 3.11)`. | Accepted as recommended. |
| D2 | Bump to C++17? | **Yes**, in core-10 after the gate, in its own measured commit: `std::filesystem`, `optional`, `string_view`, `[[nodiscard]]`. GCC 13 on Ubuntu 24.04 and ROS 2 Jazzy are C++17 already. | Accepted as recommended. |
| D3 | Windows support? | **No.** Linux-only (termios2, SCHED_RR, `recvmmsg`, `endian.h`). Keep platform calls behind `PacketSource`/`ByteStream` so a port stays possible. | Accepted as recommended. |
| D4 | Cascade 4-lane raw ADC via DCA1000? | **Defer.** The descriptor reserves `lvds.supported:false`. It needs firmware-loop work, a DCA1000 and cascade hardware that is not on the bench, and a new `layout` decoder. Revisit after core-17. | Accepted as recommended. |
| D5 | Change `AdcFrame` to a flat contiguous chirp-major layout? This breaks the nested-vector API and `CPSL_TI_Radar_ROS`. | **Yes**, with an `at()` accessor and a migration shim; update the ROS package in its own repo. (Not adopted, see the ruling.) | **Overruled: nested `[rx][sample][chirp]` kept.** Downstream dataset and processing repos depend on it (the user's note, §3). Reuse buffers instead of allocating per frame. Revisit a flat layout only if `bench_pipeline` shows the converter is a real bottleneck; then the v2 docs must stress the format change. |
| D6 | Drop Boost (asio only does serial I/O) for plain termios + `poll`? | **Yes**, in core-16. Removes a system dependency; `termios2` already exists. | Accepted as recommended. |
| D7 | IWR1443 serial (SDK 2) support | Have a Researcher confirm the SDK 2 UART format first (audit (b) hypothesis). Until then, `sdk2` is a load error with a clear message. | Accepted as recommended. |
| D8 | Loading v1 configs | Hard error that names the migration script, not dual-schema reading. | Accepted as recommended. |
| D9 | I/Q check in core-04 | Already partly done: core-04 added `tools/bench/iq_check.py` (30b3b34) and a `numFrames 0` baseline cfg (d7a0a2b). **Recommend** the user runs the reflector capture during the core-04 bench session (about 10 min). It is the only way to settle the I/Q question. | **Recommendation accepted, result partial.** Lane order looks right (single-sided spectrum, commit 6796509), but the ground return peaked near 2.1 m against about 1.0 m expected. A second capture is deferred; the user will verify through the live GUI later. Source: `plans/history.md` 2026-10-05. |
| D10 | Frame delivery: change from "latest frame wins" (today; overwritten frames are uncounted) to a drop-oldest queue, default depth 4, with `frames_overwritten` in `Stats`? | **Yes.** Slow consumers see a short backlog instead of silent loss. `runtime.frame_queue_depth: 1` restores latest-wins. | Accepted as recommended. |
| D11 | Make the raw LVDS file (`LVDS_Raw_0.bin`, written on every run with `save_to_file` today) opt-in through `output.save_raw_lvds`? | **Yes.** It doubles disk I/O and is only needed to debug packet loss. `adc_data.bin` stays on with `save_adc_frames`. | Accepted as recommended. |

## 9. v1 → v2 migration note (draft for `README.md`, landed by core-10)

This draft reflects the user's rulings on D8, D10 and D11 (accepted) and D5
(nested layout kept).


> **Configs.** v2 system configs carry `"schema_version": 2` and name a board
> descriptor (`"board": "IWR1843"`, from `CPSL_TI_Radar_cpp/config/boards/`).
> Convert old files with `uv run tools/migrate_config_v1_to_v2.py <file-or-dir>`.
> v1 files are rejected with that hint. Renamed keys: `TI_Radar_config_path` →
> `radar_cfg`; `CLI_Controller.CLI_port` → `cli.port`;
> `Streamer.serial_streaming` → `serial_stream` (`data_port` → `port`);
> `Streamer.DCA1000_streaming` → `dca1000` (`FPGA_IP` → `fpga_ip`, `system_IP` →
> `host_ip`); `board_type` → `board`; `save_to_file` → `output.save_adc_frames` /
> `output.save_raw_lvds` with a new `output.dir`; `verbose` →
> `runtime.log_level`. Baud rates and timeouts default from the board and are
> overridden under `board_overrides`. `SDK_version` is removed. Disabled
> stream sections may be omitted.
>
> **Command line.** `CPSL_TI_Radar_CPP <system.json>` now requires the config
> path (no built-in default). Add `--validate` to check a config without
> hardware.
>
> **Library.** `Runner` is replaced by `cpsl::radar::Radar`
> (`RadarConfig::load` → `Radar::open` → `configure` → `start` → `next_adc_frame` /
> `next_point_cloud` → `stop`). Calls return `Status` instead of printing.
> ADC frame layout is unchanged (`[rx][sample][chirp]`). Points are `Point{x,y,z,v,snr_db,noise_db}`.
> Link `CPSL_TI_Radar::driver`.
>
> **Output files.** `adc_data.bin` keeps its byte layout but is written to
> `output.dir`. The raw LVDS file is opt-in (`save_raw_lvds`).
>
> **Boards.** To add or tune a board, copy a file in `config/boards/` and edit
> it. No rebuild is needed.
