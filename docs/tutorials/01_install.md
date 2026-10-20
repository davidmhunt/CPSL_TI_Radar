# 1. Install: build the driver, run the tests, try the demo GUI

From a fresh Ubuntu to a working build, with no radar. You need `sudo` once. Run every command from the repository root (the folder with `pyproject.toml`).

## Packages and `uv`

```bash
sudo apt update
sudo apt install -y build-essential cmake git git-lfs curl
curl -LsSf https://astral.sh/uv/install.sh | sh     # installs uv; open a new shell afterwards
```

`g++` 7 or newer and any CMake from 3.11 are enough. [`uv`](https://docs.astral.sh/uv/getting-started/installation/) runs all the Python here and fetches Python 3.12 itself if your system has an older one. `git-lfs` is for the doc screenshots and TI PDFs only; nothing builds or runs from them.

## Clone and build

```bash
git lfs install
git clone https://github.com/davidmhunt/CPSL_TI_Radar
cd CPSL_TI_Radar
git submodule update --init CPSL_TI_Radar_cpp/include/json
cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build
cmake --build CPSL_TI_Radar_cpp/build -j
ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

You should see `Build type: Release` from the configure step and `100% tests passed` from `ctest` (28 tests, a short run). `ctest` reads the repo's `tests/fixtures/`, so run it from the full checkout.

**Why not `--recurse-submodules`?** It also fetches submodules you do not need; only `include/json` (the JSON library) is needed to build. Fetch these only if you need them:

| Submodule | Fetch it only if |
|---|---|
| `shipped_firmware/IWR1443/dca1000_raw/iwr_raw_rosnode` | you flash the IWR1443 raw-ADC image ([tutorial 3](03_flash_a_radar.md)) |
| `firmware_dev` | you build firmware from source (`git submodule update --init --checkout firmware_dev`) |

## Check the Python side and the demo GUI

```bash
uv run pytest -m "not slow"        # the fast loop; `uv run pytest` runs all of it (about a minute)
RADAR_GUI_DRIVER=tests/fakes/fake_driver.py uv run python -m radar_gui --port 8090 \
    --source replay --file tests/fixtures/replay/iwr1843_sdk3_20frames.bin
```

`--source replay --file` plays a recorded IWR1843 capture instead of a live radar, and `RADAR_GUI_DRIVER` swaps the C++ driver for a stand-in, so no board is needed. The first line of output is `radar_gui: source=replay  open http://127.0.0.1:8090/`; open that address. Stop it with Ctrl-C. [Tutorial 4](04_first_run_gui.md) tours the tabs.

## After pulling new code

```bash
git pull && git submodule update --init CPSL_TI_Radar_cpp/include/json
cmake --build CPSL_TI_Radar_cpp/build -j && ctest --test-dir CPSL_TI_Radar_cpp/build --output-on-failure
```

Prefer a container with no toolchain on the host? [`docs/docker.md`](../docker.md) builds the same driver and GUI into one image.

Next: [tutorial 2, host setup](02_host_setup.md) if you have a board, otherwise [tutorial 4](04_first_run_gui.md).
