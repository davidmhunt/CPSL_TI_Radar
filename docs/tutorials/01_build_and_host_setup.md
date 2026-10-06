# 1. Build the driver, run its tests, set up the host

Build `CPSL_TI_Radar_CPP`, run the hardware-free unit tests, and prepare the host for DCA1000 streaming. No radar needed. Run every command from the repository root.

## Build and test

You need `g++` 7 or newer, `cmake`, and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone --recurse-submodules https://github.com/davidmhunt/CPSL_TI_Radar
cd CPSL_TI_Radar
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

The configure step prints `Build type: Release` (the default). `ctest` must end with `100% tests passed`. If the build cannot find the JSON library (a submodule), run `git submodule update --init CPSL_TI_Radar_cpp/include/json`. After pulling new code, follow [`rebuild_driver.md`](rebuild_driver.md).

## Prepare the host

Serial-only runs need just the first row. DCA1000 runs need all four.

| Need | Why | Fix |
|------|-----|-----|
| `dialout` group | read the radar's `/dev/ttyACM*` | `sudo usermod -a -G dialout $USER`, then log out and in |
| DCA1000 NIC at `192.168.33.30/24` | the DCA1000 FPGA is `192.168.33.180` | static address on the wired NIC |
| `net.core.rmem_max` >= `dca1000.rcvbuf_bytes` | the kernel caps the socket buffer at `rmem_max` | `sudo sysctl -w net.core.rmem_max=134217728` |
| `cap_sys_nice` on the binary | real-time priority for the RX and worker threads | `sudo setcap cap_sys_nice+ep <binary>` |

The socket's receive buffer (`dca1000.rcvbuf_bytes`, default 64 MB) holds any backlog; only a full buffer loses data (`kernel_drops`, [tutorial 4](04_troubleshooting.md)).

One tool checks all four and applies the fixes. `<dca-nic>` is the wired interface cabled to the DCA1000 (run without `--nic` to list them):

```bash
uv run tools/setup/host_setup.py --nic <dca-nic>                    # report: OK / MISSING / WARN
uv run tools/setup/host_setup.py --nic <dca-nic> --apply --dry-run  # show the exact commands
uv run tools/setup/host_setup.py --nic <dca-nic> --apply            # run them (it calls sudo itself)
```

Do not put `sudo` in front of it. The capability lives on the binary file, so **every rebuild removes it**: re-run `--apply` after building.

On a loaded host, pin the two threads to cores your own pipeline does not use with `runtime.rx_cpu` and `runtime.worker_cpu` (Readme, "Choosing CPUs").

Next: [tutorial 2](02_first_run.md).
