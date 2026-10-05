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
| `lvds.layout` | `two_lane_iq_pairs` (SWRA581B §7) \| `lane_per_rx` (SWRA581B §5 4-lane) | `ADCCubeConverter.cpp:24-31` |
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
  names the migration script.

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
the 38 tracked files in one go. It is idempotent and reports any key it could
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

struct AdcFrame {                          // contiguous, native LVDS order = adc_data.bin order
  uint64_t index; std::chrono::steady_clock::time_point completed_at;
  uint32_t missing_bytes; FrameShape shape;
  std::vector<std::complex<int16_t>> data;                       // [chirp][rx][sample]
  const std::complex<int16_t>& at(size_t rx, size_t sample, size_t chirp) const;
};
struct PointCloud { uint32_t frame_number; std::vector<Point> points; };  // Point{x,y,z,v,snr_db,noise_db}
```

**Why the storage order is [chirp][rx][sample].** It is the order the 2-lane
LVDS stream already arrives in, after I/Q pairing (audit (a), file output).
Conversion becomes one sequential pass, and saving becomes one `write()`. The
old index order `[rx][sample][chirp]` survives as the `at()` accessor, plus a
`to_nested()` helper for one release to ease migration.

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
| P2 | Pool of pre-zeroed frame buffers; swap on completion instead of copy | audit (a) rows 4, 9, 10 | about 2,000 → 0 allocations/frame; 3 full-frame copies removed | counting allocator |
| P3 | Single-pass converter into contiguous `AdcFrame` | rows 5–8 | 4 passes and their allocations → 1 sequential pass | replay ns/byte |
| P4 | Pop packets by reference or in batches; notify only when the worker sleeps; atomic stop flag | `DCA1000Socket.cpp:144-160,188`; `Runner.cpp:260-267` | removes copy 2 and about 1 futex per packet | `perf stat` context switches; CPU% |
| P5 | `recvmmsg` (batch 32) | `DCA1000Socket.cpp:183` | syscalls per packet ÷ up to 32 | `strace -c` / CPU% |
| P6 | Ring full → stop reading (kernel buffer absorbs); count `SO_RXQ_OVFL` | `DCA1000Socket.cpp:174-179` | fewer drops under transient consumer stalls | harness drops with an injected stall |
| P7 | Condition-variable frame queue instead of 5 ms polling | `Runner.cpp:320-332` | ≤5 ms → µs consumer latency; no lost-wakeup race | timestamp delta frame complete → consumer |
| P8 | Serial: read the header, then exactly `totalPacketLen`; reuse buffers; flat `Point` | `SerialStreamer.cpp:344-376`, `TLVProcessing.cpp:40-43` | removes one frame period of latency (50 ms at 20 Hz) | timestamp delta vs frame period on a pty replay |
| P9 | Contiguous frame written with one `write()`, optionally on a writer thread | `DCA1000Handler.cpp:734-755` | 252k calls → 1 per frame | replay with `save_adc_frames` |
| P10 | No `endl`-flushed prints in per-packet or per-frame paths; periodic stats at `debug` | `FrameAssembler.cpp:85,96`; `DCA1000Handler.cpp:649-659` | removes stdout stalls in drop storms | replay with 1% injected drops |
| P11 | Configurable affinity and priorities | `DCA1000Socket.cpp:99-104`; `Runner.cpp:231-243` | lower jitter on loaded hosts | harness drops under `stress-ng` load |

**Ordering.** Every item lands after the core-04 gate. P0 gets its own
directive (core-12) so its large gain is measured in isolation; P1 goes with
the correctness fixes (core-11) because it is a correctness change first.

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
    policy, and `config_once_per_boot`.
- **Sanitizer preset.** A `CMakePresets.json` `asan-ubsan` preset runs the
  whole suite. It catches the TLV out-of-bounds read class of bugs.
- **Benchmark.** `bench_pipeline` is built but not run by default ctest. A
  `ctest -L bench` label runs it.
- **Hardware.** Only core-04 (baseline) needs it. After that, bench
  confirmation of a directive is an optional step through core-06's
  procedure, which the Controller offers to the user.

## 7. Follow-up directives (core-07+)

**Ordering rules.**
- core-07 to core-09 change no runtime behaviour and may land before core-04
  finishes.
- core-10 and everything after waits for core-04's baseline.

Every directive below:
- includes a docs step that keeps `docs/ARCHITECTURE.md`,
  `CPSL_TI_Radar_cpp/Readme.md` and `README.md` accurate for what it changed;
- ends its Verify with "docs match: a `grep` for every renamed key, class or
  path finds no stale mention in those three files, and the Reviewer reads
  the changed sections".

| ID | Title (tag) | Steps (Coder unless noted) | Verify idea | Needs |
|----|-------------|----------------------------|-------------|-------|
| core-07 | Hygiene: stale comments, dead code, doc errors `[light]` | Remove `main.cpp:29-30,40` comments, `JSONHandler`, `write_vector_to_file`, `udp_packet_buffer`, garbled `TLVCodes` constant, commented debug blocks; fix the comma operator; fix ARCHITECTURE worker priority; remove Readme `Processor`/`ROS/Listeners`; fix the "four lanes" comment. **Docs step:** ARCHITECTURE, Readme. | ctest green; `grep -rn "DCA1000Runner\|JSONHandler\|INFOATS" CPSL_TI_Radar_cpp/src CPSL_TI_Radar_cpp/main.cpp` empty; no runtime-path diff beyond deletions; docs match | — |
| core-08 | CMake modernization, flags unchanged `[light]` | Per-target `target_include_directories` in each `src/*/CMakeLists.txt`; delete the central block; `find_package(Threads/Boost)` before use; tests drop `INCLUDES`; one exported `CPSL_TI_Radar::driver` interface target; remove `DEFAULT_CONFIG_PATH`; `-std=c++17` only if D2 is approved. **Docs step:** Readme build/install, ARCHITECTURE build. | ctest green; compile flags in `compile_commands.json` identical to before except `-I` order (and `-std`, if D2 is approved); `tests/CMakeLists.txt` has no `INCLUDES`; `cmake --install` + a 10-line consumer project builds; docs match | — |
| core-09 | Board descriptors + loader (not wired in) `[heavy]` | Add `config/boards/{IWR1443,IWR1843,IWR6843,AWR2243_CASCADE}.json` per §1; `BoardDescriptor::load` with strict validation; cfg cross-checks as a function. Runtime unchanged. **Docs step:** ARCHITECTURE "Configuration" gains the descriptor; Readme lists the board files. | `test_board_descriptor` passes (4 boards + 6 rejection cases); the runtime source diff touches only new files; docs match | — |
| **gate** | **core-04 baseline committed** | | | |
| core-10 | Schema v2 + migration + board dispatch from data `[heavy]` | v2 parser; `tools/migrate_config_v1_to_v2.py` + migrate the 38 JSONs; replace every `board_type ==` check (audit (b)) with descriptor fields; `--validate` flag. **Docs step:** README migration section gets §9's note; Readme JSON section rewritten for v2; ARCHITECTURE configuration. | `grep -rn '"IWR1443"\|"IWR1843"\|"IWR6843"\|"AWR2243_CASCADE"' CPSL_TI_Radar_cpp/src` empty; `--validate` passes for every tracked JSON; migration golden test; existing ctest green; docs match | core-09 |
| core-11 | Correctness: FrameAssembler placement (P1) + core-02 bugs `[heavy]` | P1; SerialStreamer validates before publishing; TLV length guard; RadarConfigReader bounds + init; `push_packet` pre-configure guard; `asan-ubsan` preset; add the `bench_pipeline` replay target (`ctest -L bench`) and record its ns/byte for the current build in the Log. **Docs step:** ARCHITECTURE "UDP packet format" (byte-offset placement, late/duplicate counters). | all core-02 `KNOWN_BUG`s are `CHECK`s and pass; ctest green under `asan-ubsan`; replay golden frames equal; docs match | core-10 |
| core-12 | Default Release build (P0) `[light]` | Default `CMAKE_BUILD_TYPE=Release` when unset; print it at configure time. **Docs step:** Readme build section. | `cmake` with no build type gives `-O2`/`-O3` in `compile_commands.json`; `bench_pipeline` replay CPU ns/byte recorded before/after in the Log; optional bench row; docs match | core-04, core-11 (`bench_pipeline` lands in core-11) |
| core-13 | Library API v2 (`Radar`, `RadarConfig`, `Status`, log sink) `[heavy]` | §3 API over today's internals; no `exit`, no unconditional prints, no escaping exceptions; idempotent stop; stall policy; signal flag in `main`; non-copyable owners; fake-transport seams. **Docs step:** ARCHITECTURE component graph + API; Readme usage; README; unblocks core-05's OUTLINE "API" lessons. | `test_radar_e2e_fake` passes; `grep -rn "exit(\|std::cout" CPSL_TI_Radar_cpp/src` only in the log sink; `--validate` still works; docs match | core-10, core-11 |
| core-14 | Zero-copy DCA pipeline (P2, P3, P7, P9, P10) `[heavy]` | Frame pool, contiguous `AdcFrame`, single-pass converter, cv frame queue with `frames_overwritten`, single-write file output, quiet hot path. **Docs step:** ARCHITECTURE "ADC cube layout" + "RX path"; Readme output files; `utilities/` notebook note if the file format is unchanged (it should be). | `bench_pipeline` shows 0 steady-state allocations/frame and lower ns/byte than core-12's recorded value; `adc_data.bin` byte-identical to the old writer on a replay; ctest green; optional bench row vs baseline; docs match | core-13 |
| core-15 | RX socket: batching, back-pressure, affinity (P4, P5, P6, P11) `[heavy]` | `recvmmsg`, no discard on a full ring, `SO_RXQ_OVFL` counter, runtime affinity and priorities. **Docs step:** ARCHITECTURE RX path; Readme host prerequisites (affinity, caps). | replay over loopback UDP (`bench_pipeline --udp`) shows fewer syscalls per packet (`strace -c` excerpt in Log) and no user-space discard under an injected 200 ms stall within SO_RCVBUF; ctest green; docs match | core-14 |
| core-16 | Serial path rework (P8) + `parse_uart_frame` seam + TLV dialects `[heavy]` | Length-driven framing; pure parser; `sdk3`/`mcuplus_cascade` dialects; `sdk2` dialect once confirmed (Researcher first; see Decisions D7); remove `#define private public`. **Docs step:** Readme drops the "one frame old" note; ARCHITECTURE serial path. | `test_uart_parse` + pty replay: frame delivered before the next magic word (timestamp check); tests contain no `#define private`; docs match | core-13 |
| core-17 | Apply the I/Q bench result `[light]` | Set `lvds.iq_order` for IWR1843/6843 from the core-04 bench check; add a golden test with a real captured frame. **Docs step:** ARCHITECTURE ADC layout cites SWRA581B and the bench result. | the range-FFT peak of the committed capture lands at the reflector bin in a ctest/pytest; docs match | core-04 bench check, core-09 |

**Not proposed (design question only):** cascade 4-lane raw ADC (D4).

## 8. Decisions needed (user)

| # | Question | Recommendation |
|---|----------|----------------|
| D1 | nlohmann_json: vendored submodule or system package? | Keep the pinned submodule as the default (offline, reproducible, Docker-simple). Add `CPSL_USE_SYSTEM_JSON=ON` to use `find_package(nlohmann_json 3.11)`. |
| D2 | Bump to C++17? | **Yes** in core-08: `std::filesystem`, `optional`, `string_view`, `[[nodiscard]]`. GCC 13 on Ubuntu 24.04 and ROS 2 Jazzy are C++17 already. |
| D3 | Windows support? | **No.** Linux-only (termios2, SCHED_RR, `recvmmsg`, `endian.h`). Keep platform calls behind `PacketSource`/`ByteStream` so a port stays possible. |
| D4 | Cascade 4-lane raw ADC via DCA1000? | **Defer.** The descriptor reserves `lvds.supported:false`. It needs firmware-loop work, a DCA1000 and cascade hardware that is not on the bench, and a new `layout` decoder. Revisit after core-17. |
| D5 | Change `AdcFrame` to contiguous `[chirp][rx][sample]`? This breaks the nested-vector API and `CPSL_TI_Radar_ROS`. | **Yes**, with `at()` plus a one-release `to_nested()` shim. Update the ROS package in its own repo. |
| D6 | Drop Boost (asio only does serial I/O) for plain termios + `poll`? | **Yes** in core-16. Removes a system dependency; `termios2` already exists. |
| D7 | IWR1443 serial (SDK 2) support | Have a Researcher confirm the SDK 2 UART format first (audit (b) hypothesis). Until then, `sdk2` is a load error with a clear message. |
| D8 | Loading v1 configs | Hard error that names the migration script (recommended), not dual-schema reading. |
| D9 | Amend core-04 to add the I/Q range-FFT check (about 10 min with a reflector) and a `numFrames 0` stress cfg? | **Yes.** It is the only way to settle the I/Q question (audit), and the shipped stress cfg stops after 30 frames. |

## 9. v1 → v2 migration note (draft for `README.md`, landed by core-10)

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
> ADC frames are contiguous `[chirp][rx][sample]` (`frame.at(rx, sample, chirp)`;
> `to_nested()` for one release). Points are `Point{x,y,z,v,snr_db,noise_db}`.
> Link `CPSL_TI_Radar::driver`.
>
> **Output files.** `adc_data.bin` keeps its byte layout but is written to
> `output.dir`. The raw LVDS file is opt-in (`save_raw_lvds`).
>
> **Boards.** To add or tune a board, copy a file in `config/boards/` and edit
> it. No rebuild is needed.
