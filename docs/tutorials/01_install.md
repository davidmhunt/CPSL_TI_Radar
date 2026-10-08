# 1. Install: build the driver, run the tests, set up the host

Get a working checkout, build `CPSL_TI_Radar_CPP`, and prepare the host. No radar is needed until tutorial 3. Run every command from the repository root (the folder with `pyproject.toml`).

## Install

You need Linux, `git`, `git-lfs`, `g++` 7 or newer, `cmake`, and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone --recurse-submodules https://github.com/davidmhunt/CPSL_TI_Radar
cd CPSL_TI_Radar
git lfs install && git lfs pull          # the GUI screenshots in docs/images/ are LFS files
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

- The configure step prints `Build type: Release` (the default); `ctest` (about 20 s) must end with `100% tests passed`. It reads the repo-root `tests/fixtures/`, so run it from a full checkout.
- If the build cannot find the JSON library, run `git submodule update --init CPSL_TI_Radar_cpp/include/json`.
- `firmware_dev/` is an opt-in submodule and is not fetched by the clone. You only need it to build firmware ([`docs/firmware.md`](../firmware.md)).
- Check the Python side: `uv run pytest -m "not slow"` is the fast loop; `uv run pytest` runs everything (about 1085 tests, about 1 minute). Neither needs hardware.

Prefer a container? [`docs/docker.md`](../docker.md) builds the driver and GUI into one image: `docker compose -f docker/app/compose.yaml build demo`, then `up demo` serves a hardware-free demo on `http://127.0.0.1:8090/`. Its `hw` profile (real boards) is built to the design in that page but is **not yet verified on a real board**.

## Prepare the host (DCA1000 and serial)

Serial-only runs need just the first row. DCA1000 runs need all three.

| Need | Why | Fix |
|------|-----|-----|
| `dialout` group | read the radar's `/dev/ttyACM*` | `sudo usermod -a -G dialout $USER`, then log out and in |
| DCA1000 NIC at `192.168.33.30/24` | the DCA1000 FPGA is `192.168.33.180` | static address on the wired NIC |
| `net.core.rmem_max` >= `dca1000.rcvbuf_bytes` | the kernel caps the socket buffer at `rmem_max` | `sudo sysctl -w net.core.rmem_max=134217728` |

One tool checks all three and applies the fixes. `<dca-nic>` is the wired interface cabled to the DCA1000 (run without `--nic` to list them):

```bash
uv run tools/setup/host_setup.py --nic <dca-nic>                    # report: OK / MISSING / WARN
uv run tools/setup/host_setup.py --nic <dca-nic> --apply --dry-run  # show the exact commands
uv run tools/setup/host_setup.py --nic <dca-nic> --apply            # run them (it calls sudo itself)
```

Do not put `sudo` in front of it. Add `--udev` to also write stable `/dev/radar/<serial>-cli` and `-data` port names.

On a loaded host, pin the driver's two threads to cores your own pipeline does not use with `runtime.rx_cpu` and `runtime.worker_cpu` (driver Readme, "Choosing CPUs").

## After pulling new code

```bash
git pull && git submodule update --init CPSL_TI_Radar_cpp/include/json
cmake --build CPSL_TI_Radar_cpp/build -j && ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

For a debug crash hunt, `cd CPSL_TI_Radar_cpp && cmake --preset asan-ubsan && cmake --build --preset asan-ubsan -j && ctest --preset asan-ubsan` builds under AddressSanitizer in `build-asan-ubsan/` and leaves `build/` alone (presets need CMake 3.25 or newer).

Next: [tutorial 2, the GUI](02_first_run_gui.md).
