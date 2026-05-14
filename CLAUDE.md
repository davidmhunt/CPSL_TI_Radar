# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### C++ (CPSL_TI_Radar_cpp)

```bash
cd CPSL_TI_Radar_cpp/build
cmake ../
cmake --build .
./CPSL_TI_Radar_CPP
```

The build produces two executables: `CPSL_TI_Radar_CPP` (uses `Runner`, supports both DCA1000 and serial) and `MAIN_NO_RUNNER` (manual wiring of components). Rebuild is required after config file changes if paths are hardcoded in `main.cpp`.

Submodule (`include/json`) must be present — if missing:
```bash
git submodule update --init --recursive
```

### Python (CPSL_TI_Radar)

```bash
cd CPSL_TI_Radar
poetry install          # first-time setup
poetry run pytest --json_config radar_1.json        # run all tests
poetry run pytest --json_config radar_1.json -x     # stop on first failure
poetry run pytest tests/test_ethernet.py            # single test file
```

If Poetry keyring errors appear: `export PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`

## Architecture

### Two Parallel Implementations

There are **two separate implementations** that are not interchangeable:

| | `CPSL_TI_Radar/` (Python) | `CPSL_TI_Radar_cpp/` (C++) |
|---|---|---|
| Language | Python 3.10–3.12 (Poetry) | C++14 (CMake) |
| Streaming | Serial (IWR demo TLV) or DCA1000 | DCA1000 or Serial |
| Processing | Full pipeline (range-azimuth, range-doppler, point cloud) | Raw ADC cube only |
| IPC | `multiprocessing` with `Pipe` connections | `std::thread` with mutexes |
| Status | Legacy; DCA1000 support superseded by C++ | Active / primary |

The Python implementation's DCA1000 code (`Streamers/Handlers/DCA1000.py`, `DCA1000_Streamer.py`) is largely superseded by the C++ implementation. The Python code remains valuable for its TLV processing pipeline and tutorial notebooks.

### C++ Component Graph

```
main.cpp
  └── Runner
        ├── SystemConfigReader   (parses JSON config)
        ├── RadarConfigReader    (parses IWR .cfg, computes bytes_per_frame)
        ├── CLIController        (serial → IWR, sends .cfg commands)
        ├── DCA1000Handler       (UDP sockets, packet RX, ADC cube assembly)
        │     └── DCA1000Commands (FPGA command protocol)
        └── SerialStreamer        (serial TLV stream → detected points)
```

`Runner` spawns two threads (`run_dca1000`, `run_serial`) with `SCHED_RR` priority 10. `DCA1000Handler::process_next_packet()` is the hot loop — called continuously from the DCA1000 thread. Frames are signaled via `new_frame_available` flag (mutex-protected); consumers poll via `get_next_adc_cube(timeout_ms)`.

### Python Component Graph

```
Radar.py (orchestrator)
  ├── ConfigManager         (JSON + .cfg parsing, exports radar_config dict)
  ├── CLI_Controller        (serial → IWR)
  ├── DCA1000Streamer       (multiprocessing.Process)
  │     └── DCA1000Handler  (raw UDP socket, forwards packets via Pipe)
  └── DCA1000Processor      (multiprocessing.Process, assembles ADC cube)
        └── TLV_Processors/ (range-azimuth, range-doppler, AoA)
```

All inter-process communication uses `multiprocessing.Pipe` connections. `_Message` / `_MessageTypes` carry control signals (start, stop, errors) over the parent pipe; raw bytes travel over dedicated data pipes.

### DCA1000 UDP Packet Format

Each UDP packet from the DCA1000 FPGA has a 10-byte header:
- Bytes 0–3: sequence number (uint32, little-endian)
- Bytes 4–9: byte count (uint48, little-endian, stored as 6 bytes)
- Bytes 10+: ADC payload (1462 bytes per full packet, max UDP = 1472)

Both implementations detect dropped packets by checking `seq_num != prev_seq_num + 1` and zero-pad the gap. There is no retransmission.

### ADC Data Cube Layout

The assembled cube is indexed `[Rx channel][sample][chirp]` as `complex<int16_t>`. Data arrives interleaved from LVDS; `DCA1000Handler::update_latest_adc_cube_interleaved()` vs `update_latest_adc_cube_noninterleaved()` handles the two IWR SDK behaviors. IWR1843 with SDK 3.x uses interleaved; use an **even number of ADC samples** when using a single RX channel with SDK 3+.

### Configuration Files

Two config files are always required:

1. **JSON system config** (`CPSL_TI_Radar_cpp/configs/*.json` or `CPSL_TI_Radar/json_radar_settings/*.json`) — specifies serial ports, DCA1000 IP/ports, streaming mode, save-to-file, and the path to the radar .cfg file.
2. **Radar .cfg file** (`configurations/`) — TI mmWave SDK chirp configuration. Must include `lvdsStreamCfg -1 0 1 0` (ADC only) or `lvdsStreamCfg -1 1 1 1` (all data) when using DCA1000.

DCA1000 network defaults: FPGA IP `192.168.33.180`, system IP `192.168.33.30`, cmd port `4096`, data port `4098`. Host must have a static IP of `192.168.33.30/24` on the DCA1000 interface.

### DCA1000 RX Architecture (Phase 1 fixes applied)

`DCA1000Handler` now uses a dedicated RX thread decoupled from frame assembly:

- **RX thread** (SCHED_RR 99): runs `recvfrom` in a tight loop, pushes raw 1472-byte packets into a 512-slot lock-free ring buffer.
- **Worker thread** (existing Runner thread): pops from the ring, does sequence checking, frame assembly, ADC cube conversion, and file I/O.
- **SO_RCVBUF**: 64 MB requested on the data socket (kernel doubles; actual granted size printed at startup).
- **Data socket timeout**: 500 ms (RX thread exits promptly when DCA1000 stops streaming).
- **Ring overruns** (`rx_overrun_count`): printed in `print_status()` — non-zero only if the worker thread falls far behind.

The `dropped_packets`, `dropped_packet_events`, and `rx_overrun_count` counters are printed per frame when `verbose: true` in the JSON config.

## System Prerequisites (DCA1000 High-Rate Streaming)

The kernel UDP receive buffer cap must be raised before the 64 MB `SO_RCVBUF` request takes effect:

```bash
sudo sysctl -w net.core.rmem_max=134217728
```

To make permanent (Ubuntu/Debian):
```bash
echo 'net.core.rmem_max=134217728' | sudo tee /etc/sysctl.d/99-radar.conf
sudo sysctl -p /etc/sysctl.d/99-radar.conf
```

The RX thread uses SCHED_RR priority 99. Without root, grant the capability to the binary:
```bash
sudo setcap 'cap_sys_nice=eip' ./CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP
```
Or add to `/etc/security/limits.conf` (then log out/in):
```
<username>  -  rtprio  99
```

## Hardware Notes

- **Firmware**: DCA1000 streaming requires `Firmware/DCA1000_Streaming/` binaries; IWR demo (TLV/serial) requires `Firmware/IWR_Demos/` binaries. Flash with TI UniFlash.
- **SOP mode**: IWR must be in Flashing Mode to flash, Functional Mode to run.
- **Serial port**: CLI port is typically the lower-numbered port (e.g., `/dev/ttyACM0`). Add user to `dialout` group: `sudo usermod -a -G dialout $USER`.
- **DCA1000 EEPROM reprogramming**: Use `DCA_Programming/` to change the FPGA's network config when running multiple radars simultaneously.
