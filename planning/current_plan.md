# CPSL_TI_Radar Improvement Plan

Tasks use `[x]` when complete. Leave comments as `> **COMMENT:** ...` blocks — these are read before any action is taken.

---

## Phase 1: Fix DCA1000 Packet Drops (Critical)

The root causes, ranked by severity:

### 1a — Increase UDP receive buffer (`SO_RCVBUF`)
**File:** `CPSL_TI_Radar_cpp/src/DCA1000/DCA1000Handler.cpp` → `init_sockets()`

The kernel drops incoming UDP datagrams when the socket receive buffer fills up. No `SO_RCVBUF` is currently set, so the default (~128 KB on Linux) is used. At high ADC rates (e.g., 10 Msps × 4 Rx = 40 MB/s of ADC data + UDP overhead), bursts of packets easily overflow this before userspace can drain them.

- [x] Add `setsockopt(*data_socket, SOL_SOCKET, SO_RCVBUF, &buf_size, sizeof(buf_size))` with a 64 MB request immediately after socket creation.
- [x] Log the actual granted buffer size via `getsockopt` (the kernel silently doubles the value, so the granted size will appear as 128 MB if `rmem_max` allows it).
- [x] Update `CLAUDE.md` with the required sysctl: `sudo sysctl -w net.core.rmem_max=134217728` and how to make it permanent.

>**COMMENT:** Also add this to the readme.md file inside of the CPSL_TI_Radar_cpp folder

### 1b — Decouple RX from frame assembly (producer/consumer ring buffer)
**File:** `CPSL_TI_Radar_cpp/src/DCA1000/DCA1000Handler.cpp` — `process_next_packet()` and `get_next_udp_packets()`

Currently, the single DCA1000 thread does: `recvfrom` → drop detection → byte-copy into frame buffer → (optionally) byte-by-byte raw file write, all sequentially. Any time spent in frame assembly or file I/O is time the socket is not being drained.

New architecture:
```
[RX Thread — highest RT priority]
    recvfrom → push raw 1472-byte packet into ring buffer

[Worker Thread — existing priority]
    pop from ring buffer → sequence check → frame assemble → cube convert → file write
```

- [x] Add a lock-free circular ring buffer using `std::atomic` head/tail and a `std::array<std::array<uint8_t, 1472>, 512>` slot array (~750 KB). No heap allocation during streaming.
- [x] Spawn a dedicated RX thread inside `DCA1000Handler::init_sockets()` (or at `send_recordStart()` time). Set it to `SCHED_RR` priority 99 (highest allowable).
>**COMMENT:** in the readme.md file, specify any os commands that may be needed to enable setting the thread priority like this
- [x] Move all assembly/conversion/file-write logic out of `process_next_packet()` into a new `process_from_ring_buffer()` method called from the existing worker thread.
- [x] On ring full, increment an `rx_overrun_count` counter and drop the packet (do not block the RX thread). Log overruns in `print_status()`.

### 1c — Fix byte-by-byte file I/O in the hot path
**File:** `DCA1000Handler.cpp:619–639` — raw LVDS write inside the per-byte copy loop

Each byte of the ADC payload is currently written with a separate `write()` call (~1462 syscalls/packet).

- [x] Replace the per-byte write with a single `raw_lvds_out_file->write(reinterpret_cast<const char*>(udp_packet_buffer.data() + 10), adc_data_bytes_in_packet)` after the frame assembly loop.
- [x] This write moves to the worker thread as part of 1b — the RX thread never touches the file handle.

### 1d — Shorten socket timeout
**File:** `DCA1000Handler.cpp:757–761`

The current 2-second `SO_RCVTIMEO` causes the RX thread to block for 2 seconds when the DCA1000 stops sending. ~~Reduce to 200ms.~~

- [x] Change to `timeout.tv_sec = 0; timeout.tv_usec = 500000` (500 ms) for the data socket only, to safely handle long frame periods while still exiting promptly.

---

### Phase 1 Verification

After implementing 1a–1d:

1. **Smoke test — build**: `cd CPSL_TI_Radar_cpp/build && cmake ../ && cmake --build .` must succeed with no new warnings.
2. **Socket buffer check**: Run `./CPSL_TI_Radar_CPP` and confirm stdout shows the granted `SO_RCVBUF` value ≥ 67108864 (indicates kernel honored the request, or report actual value if `rmem_max` is smaller).
3. **Drop rate test — baseline vs. fixed**: Record drop counts at your highest-rate ADC config before and after these changes. Use `print_status()` output (dropped_packets, dropped_packet_events).
4. **Ring buffer overrun check**: Confirm `rx_overrun_count` stays 0 at normal ADC rates; only non-zero if the worker thread falls badly behind.
5. **File I/O sanity**: With `save_to_file: true`, collect one run and verify the `.bin` file size = `bytes_per_frame × received_frames` (use `process_raw_lbds_data.ipynb`).

---

## Phase 2: Correctness Fixes

### 2a — Fix hardcoded `rx_antennas = 4`
**File:** `RadarConfigReader.cpp:116` — `// TODO: remove the hardcoding when possible`

`rx_antennas` is always set to 4 regardless of the actual radar `.cfg`. This will silently corrupt `bytes_per_frame` for any future config that uses fewer than 4 Rx channels.

`channelCfg` format: `channelCfg <rxMask> <txMask> <cascading>`. The first parameter is the Rx bitmask. All current configs in the repo use `rxMask = 15` (0b1111 = 4 Rx), so this is not currently breaking anything — but parsing it correctly is the right fix.

> **Note:** Verified — all existing configs (IWR1843, IWR6843 ODS, IWR1443) use `channelCfg 15 ...`, meaning 4 Rx antennas. IWR6843 ODS uses 4 Rx / 3 Tx (mask 7). Default remains 4 if `channelCfg` is absent.

- [x] Add `channelCfg` parsing to `RadarConfigReader::process_cfg()`.
- [x] Add `read_channel_cfg(values)` helper: `rx_antennas = __builtin_popcount(std::stoi(values[1]))`.
- [x] Initialize `rx_antennas = 4` as the default before parsing (preserves behavior if channelCfg is missing).
- [x] Remove the hardcoded `rx_antennas = 4` post-parse line.

### 2b — Fix dropped packet counter arithmetic
**File:** `DCA1000Handler.cpp:597`

Current: `dropped_packets += (packet_sequence_number - received_packets + 1)` — off by one, overcounts drops by 1 per event. Correct formula: `(packet_sequence_number - received_packets - 1)`.

- [x] Change `+ 1` to `- 1`. *(done as part of Phase 1 implementation)*

### 2c — Replace `SDK_version` with `board_type` in JSON config
**Background:** `SDK_version` already exists in the JSON schema and already drives both LVDS lane selection (`send_configFPGAGen`) and ADC cube interleaving (`save_frame_byte_buffer`). The field works but the semantics are indirect — the actual meaningful distinction is board type, not SDK string.

Behavior mapping (unchanged):
| `board_type` | LVDS lanes | ADC cube format |
|---|---|---|
| `"IWR1843"` | 2-lane | non-interleaved (SDK 3+) |
| `"IWR6843"` | 2-lane | non-interleaved (SDK 3+) |
| `"IWR1443"` | 4-lane | interleaved (SDK 2) |

- [x] Add `board_type` string field and `getBoardType()` getter to `SystemConfigReader`.
- [x] Replace `getSDKMajorVersion() == 2/3` logic in `send_configFPGAGen()` and `save_frame_byte_buffer()` with `getBoardType() == "IWR1443"` vs. `"IWR1843"/"IWR6843"`.
- [x] Keep `SDK_version` field in the JSON for backwards compatibility (still parsed, but `board_type` takes precedence when present).
- [x] Add `"board_type"` to all JSON configs in `CPSL_TI_Radar_cpp/configs/`. IWR1843 configs → `"IWR1843"`, IWR6843 configs → `"IWR6843"`.
- [x] Add error message if `board_type` is unrecognized, with the list of valid values.

---

### Phase 2 Verification

1. **Antenna count**: Add a `std::cout` in `RadarConfigReader::initialize()` that prints the parsed `rx_antennas`. Run with each of your three board configs and confirm 4 is reported for all (given all current configs use `channelCfg 15 ...`).
2. **Drop counter**: Induce a known drop (unplug/replug ethernet briefly during streaming) and confirm `dropped_packets` matches the gap in sequence numbers exactly.
3. **Board type dispatch**: Run with an IWR1843 config; confirm stdout shows the `board_type` being selected and no "invalid SDK major version" errors.
4. **IWR6843 frame size**: Run with `radar_0_IWR6843_ods_dca_RadVel.json`; confirm printed `bytes_per_frame` matches hand-calculated value from its `.cfg` (4 Rx × samples × chirps × 4 bytes).

---

## Phase 3: Structural / Organizational Improvements

### 3a — Accept config path from command line in `main.cpp`
**File:** `CPSL_TI_Radar_cpp/main.cpp:30`

Config path is hardcoded, requiring a recompile to switch configs.

- [x] Parse `argv[1]` as the config path if provided; fall back to the current hardcoded default otherwise.
- [x] Print the config path being used at startup.

### 3b — Archive `DCA1000Runner`
**File:** `CPSL_TI_Radar_cpp/src/Runners/DCA1000Runner.{hpp,cpp}`

Confirmed dead code: the only reference to `DCA1000Runner` outside its own files is a **commented-out line** in `main.cpp:32`. `main_no_runner.cpp` does not use it either — it manually wires `DCA1000Handler` directly (and even that code is commented out). `Runner` is a strict superset.

- [x] Move `DCA1000Runner.hpp` and `DCA1000Runner.cpp` to `archived_code/cpp/` with a note: "Superseded by Runner. DCA1000Handler is now used directly."
- [x] Remove `DCA1000Runner` from the `install(TARGETS ...)` list in `CPSL_TI_Radar_cpp/CMakeLists.txt` (comment out, don't delete).
- [x] Remove the `DCA1000Runner` `add_library` / `target_link_libraries` lines from `src/CMakeLists.txt` (comment out with note).

### 3c — Split `DCA1000Handler` into focused classes
`DCA1000Handler` (~1360 lines) mixes FPGA command protocol, UDP socket lifecycle, packet reception, drop detection, frame assembly, ADC cube construction, and file I/O.

- [x] Review and approve the class interfaces above before implementation begins.
- [x] Implement `ADCCubeConverter` (moves interleaved/non-interleaved conversion logic).
- [x] Implement `FrameAssembler` (sequence check, drop detection, frame assembly).
- [x] Implement `DCA1000Socket` (moves socket + RX thread from 1b into its own class).
- [x] Refactor `DCA1000Handler` to delegate to the three new classes, keeping its public API identical. (776 lines, down from 1,458)

### 3d — Documentation

- [x] Updated `Readme.md`: added Architecture section, updated Running section (argv[1] usage), added `board_type` field to Streamer config docs, removed redundant rebuild step.
- [x] Added file-level doc comments to `DCA1000Socket.hpp`, `FrameAssembler.hpp`, `ADCCubeConverter.hpp`.
- [x] Updated `CLAUDE.md` component graph to show three sub-components owned by `DCA1000Handler`.

---

### Phase 3 Verification

1. **Build**: Clean build must succeed: `rm -rf build && mkdir build && cd build && cmake ../ && cmake --build .`
2. **Config switch**: `./CPSL_TI_Radar_CPP path/to/config.json` works; default path works when no arg given.
3. **Regression — streaming**: Run a full acquisition session with IWR1843 config. Frame count and drop count must match Phase 2 baseline.
4. **3c interfaces**: After class split, run the same session again — `get_latest_adc_cube()` output must be bit-identical to pre-split (validate with `process_adc_data.ipynb`).

---

## Phase 4: Python Utility Preservation & Cleanup

### 4a — Archive entire `CPSL_TI_Radar/` Python package
The Python streaming code is superseded by the C++ implementation. The `utilities/` notebooks that load `.bin` files for debugging C++ output must be preserved.

- [x] Move `CPSL_TI_Radar/CPSL_TI_Radar/` (the Python package) to `archived_code/CPSL_TI_Radar/CPSL_TI_Radar_py/` with an ARCHIVE_NOTE.md. Entire `CPSL_TI_Radar/` directory archived; `CPP_Development/` also archived.
- [x] Unique notebooks from `utilities_and_notebooks/` (bartlet.ipynb, test_ethernet_traffic.ipynb) promoted to top-level `utilities/`.
- [x] `readme_images/` moved to top-level; image paths updated in `CPSL_TI_Radar_cpp/Readme.md` and archived `CPSL_TI_Radar/README.md`.

### 4b — Audit and document `utilities/` notebooks
These notebooks are the primary tool for verifying C++ output files:

| Notebook | Purpose |
|---|---|
| `process_adc_data.ipynb` | Load `.bin` ADC cube files written by C++ `save_to_file` |
| `process_raw_lbds_data.ipynb` | Load raw LVDS `.bin` packet stream |
| `print_config.ipynb` | Decode `.cfg` radar config files |
| `determine_serial_ports.ipynb` | Find serial ports on the host |

- [x] Verified `process_adc_data.ipynb` reshape logic matches C++ write format (code audit — live validation still pending hardware run).
- [x] Binary format unchanged from Phase 1–3; notebook logic confirmed correct.
- [x] Added `utilities/README.md` documenting file formats and loading recipes.

---

### Phase 4 Verification

1. **Build still succeeds**: C++ build is unaffected by Python archive.
2. **Notebook smoke test**: Open `process_adc_data.ipynb`, point it at a `.bin` file from a Phase 1/2 run, and confirm plots render correctly.

---

## Notes / Constraints

- **SDK version → board type mapping** (for any future reference): IWR1843 = SDK 3.x (2-lane LVDS, non-interleaved); IWR6843 = SDK 3.5 (2-lane LVDS, non-interleaved); IWR1443 = SDK 2.x (4-lane LVDS, interleaved).
- **IWR6843 ODS antenna config**: 4 Rx / 3 Tx (verified from `channelCfg 15 7 0`). All existing configs use `channelCfg 15 ...` = 4 Rx. The `rx_antennas = 4` default is correct for all current hardware.
- **Even ADC sample counts**: Use even numbers when operating with a single Rx channel on SDK 3+ (per existing README note — interleaving behavior is undefined for odd sample counts).
- **`net.core.rmem_max` sysctl**: Must be ≥ 128 MB system-wide before the 64 MB `SO_RCVBUF` request takes effect. Add to CLAUDE.md.
- **`main_no_runner.cpp`**: This is a serial-only dev/debug entrypoint; its DCA1000 code is commented out. Keep as-is.
