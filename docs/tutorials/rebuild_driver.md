# Rebuild the driver (runbook)

Use this after pulling new driver code, or before a bench session. It rebuilds `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP`, runs the hardware-free tests, checks one config, and re-applies the host settings that a rebuild removes.

Run every block from the repository root, the folder that contains `pyproject.toml`. This takes about 5 minutes.

## 1. Update the code and submodules

```bash
git pull
git submodule update --init CPSL_TI_Radar_cpp/include/json
```

## 2. Build and test (Release)

```bash
cd CPSL_TI_Radar_cpp
cmake --preset release            # configures build/ as Release
cmake --build --preset release -j
ctest --preset release            # hardware-free unit tests; all must pass
cd ..
```

You need CMake 3.25 or newer for presets (`cmake --version`). Without presets, the same build is `cmake -S CPSL_TI_Radar_cpp -B CPSL_TI_Radar_cpp/build` (Release is the default) followed by `cmake --build CPSL_TI_Radar_cpp/build -j`.

Debugging a crash? `--preset asan-ubsan` builds and tests under AddressSanitizer and UndefinedBehaviorSanitizer in `build-asan-ubsan/`. It does not replace `build/`.

## 3. Check your config without hardware

```bash
cd CPSL_TI_Radar_cpp/build
./CPSL_TI_Radar_CPP ../config/system/front_radar_IWR1843_stress_test.json --validate
cd ../..
```

Use the config you plan to run. `--validate` prints the board, ports and frame settings, and exits 0 if the config is good. A config in the old v1 format exits 1 and names the conversion command (`uv run tools/migrate_config_v1_to_v2.py <file>`).

## 4. Re-apply host settings (every rebuild)

The real-time capability (`cap_sys_nice`) is stored on the binary file, so every rebuild removes it. The tool also makes the 128 MB UDP receive buffer survive reboots, if it doesn't already.

```bash
uv run tools/setup/host_setup.py --nic enp3s0                      # report: OK / MISSING / WARN
uv run tools/setup/host_setup.py --nic enp3s0 --apply --dry-run    # optional: show the exact commands
uv run tools/setup/host_setup.py --nic enp3s0 --apply              # run them; asks for sudo per command
uv run tools/setup/host_setup.py --nic enp3s0                      # confirm: nothing MISSING (exit 0)
```

- Replace `enp3s0` with the wired interface cabled to the DCA1000. Run the tool without `--nic` to list the candidates.
- Don't put `sudo` in front of the tool. It calls `sudo` itself for each command, so you see every prompt.

## Done when

- `ctest --preset release` reports 100% tests passed.
- `--validate` exits 0 for your config.
- The final `host_setup.py` report shows no MISSING line.

For first-time machine setup (CMake, Boost, the DCA1000 static IP, the `dialout` group), see `CPSL_TI_Radar_cpp/Readme.md`.
