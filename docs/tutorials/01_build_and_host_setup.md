# 1. Build the driver, run its tests, set up the host

You will build `CPSL_TI_Radar_CPP`, run the hardware-free unit tests, and (for DCA1000 raw-ADC streaming) prepare the host. About 10 minutes, no radar needed. Run every command from the repository root, the folder that contains `pyproject.toml`.

## Build and test

You need `g++` 7 or newer, `cmake`, and [`uv`](https://docs.astral.sh/uv/). Installing the compiler and CMake is in `CPSL_TI_Radar_cpp/Readme.md` ("Installation").

```bash
git clone --recurse-submodules https://github.com/davidmhunt/CPSL_TI_Radar
cd CPSL_TI_Radar
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

The configure step prints `Build type: Release` (the default). `ctest` must end with `100% tests passed`. If the build cannot find the JSON library (a submodule), run `git submodule update --init CPSL_TI_Radar_cpp/include/json`. After pulling new code, follow [`rebuild_driver.md`](rebuild_driver.md) instead: it repeats these steps and the host settings below.

The tests open no port, socket or radar. To add one, see [tutorial 13](13_tests_and_performance.md).

## Prepare the host

Serial-only runs need just the first row. DCA1000 runs need all four.

| Need | Why | Fix |
|------|-----|-----|
| `dialout` group | read the radar's `/dev/ttyACM*` | `sudo usermod -a -G dialout $USER`, then log out and in |
| DCA1000 NIC at `192.168.33.30/24` | the DCA1000 FPGA is `192.168.33.180` | static address on the wired NIC |
| `net.core.rmem_max` >= `dca1000.rcvbuf_bytes` | the kernel caps the socket buffer at `rmem_max` | `sudo sysctl -w net.core.rmem_max=134217728` |
| `cap_sys_nice` on the binary | real-time priority for the RX and worker threads | `sudo setcap cap_sys_nice+ep <binary>` |

The driver never discards a packet itself. When it falls behind, the socket's receive buffer (`dca1000.rcvbuf_bytes`, default 64 MB) holds the backlog, and only a full buffer loses data (`kernel_drops`, see [tutorial 4](04_troubleshooting.md)). That is why `rmem_max` must not be smaller.

One tool checks all four and applies the fixes. `<dca-nic>` is the wired interface cabled to the DCA1000 (run the tool without `--nic` to list them, for example `enp3s0`):

```bash
uv run tools/setup/host_setup.py --nic <dca-nic>                    # report: OK / MISSING / WARN
uv run tools/setup/host_setup.py --nic <dca-nic> --apply --dry-run  # show the exact commands
uv run tools/setup/host_setup.py --nic <dca-nic> --apply            # run them (it calls sudo itself)
```

Do not put `sudo` in front of it. The capability lives on the binary file, so **every rebuild removes it**: re-run `--apply` after building. Without it the driver warns once per thread and runs at normal priority.

On a loaded host, pin the two threads to cores your own pipeline does not use with `runtime.rx_cpu` and `runtime.worker_cpu` (for example 2 and 3 on a 4-core machine; see the Readme, "Choosing CPUs").

Next: [tutorial 2](02_first_run.md).
