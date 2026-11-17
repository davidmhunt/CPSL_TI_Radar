# CPSL TI Radar

Host-side stack for TI mmWave radars (IWR1443/1843/6843 and the AWR2243 2-chip cascade): a C++ driver
that configures a board over its CLI serial port and streams raw ADC through a DCA1000 (UDP) or the
demo's TLV point cloud over serial; a Python web GUI; ROS 2 packages; shipped firmware. Work targets
the v2.0 rework. Users read `README.md`; driver internals are in `docs/ARCHITECTURE.md`.

This repo uses the friday plugin: plan with `/friday:plan`, run approved directives with
`/friday:execute <id>`. Directives live in `docs/directives/`.

## Running things
- Every build, test and script goes through `./run` (dev container by default, native where a
  machine sets `FRIDAY_RUNTIME=native`). A hook refuses bare `python`, `uv`, `cmake`, `ctest`, `pytest`.
- Full hardware-free check, the default `Verify:`: `./run tools/check.sh` (C++ build, ctest,
  `pytest -m "not slow"`; about 2 min cold). Add `--full` for the slow pytest tests.
- One test: `./run uv run pytest tests/test_x.py -q`; one C++ test: `./run ctest --test-dir CPSL_TI_Radar_cpp/build -R test_x --output-on-failure`.
- C++ replay benchmark: Release build, then `./run ctest --test-dir CPSL_TI_Radar_cpp/build -C bench -L bench --verbose`.
- ROS 2 Jazzy is sourced on the dev host and is not in the dev container; `ros2/` builds on the host.

## Layout
| Path | What |
|---|---|
| `CPSL_TI_Radar_cpp/` | C++ driver; configs in `config/` (`boards/`, `firmware/`, `radar/<BOARD>/<fw>/`, `system/`, gitignored `user/`); unit tests in `tests/` |
| `radar_gui/` | Web GUI: Python backend (`python -m radar_gui`) + no-build `web/` frontend |
| `tests/` | pytest suite (`slow` marker for subprocess/driver/server tests) |
| `firmware_dev/` | opt-in submodule: firmware sources and the `fw` build/flash tool (see the `firmware` skill) |
| `shipped_firmware/` | prebuilt images with provenance |
| `docker/app/`, `docker/dev/` | runtime image (demo / hw profiles) and the dev container behind `./run` |
| `docs/` | `ARCHITECTURE.md`, `RESULTS.md`, `firmware.md`, `docker.md`, `tutorials/`, `directives/` |

## Conventions
- Paths relative to the repo root; no absolute paths in code. uv manages Python dependencies.
- Tests pin current behaviour. A bug found while writing tests is recorded with `KNOWN_BUG(...)`
  (C++) and reported, not fixed in the same change. Add a C++ test as `CPSL_TI_Radar_cpp/tests/test_<name>.cpp`
  plus an `add_driver_test` line in `tests/CMakeLists.txt`.
- `docs/RESULTS.md` is the single source for measured numbers (rates, drop counts, on-board checks);
  every number there cites its command, commit and board.

## Hardware (see the `hardware` skill)
- Boards, their serial ports and the DCA1000 are single-user. Commands that touch them ask the user
  first (patterns in `.claude/friday.json`).
- Flashing, SOP switches, the cascade's J6 jumper and power cycles need a person at the bench.
- The cascade demo accepts a cfg only once per power-up: any on-board check that sends a cfg needs a
  power cycle first.
- `CPSL_TI_Radar_CPP <system.json> --validate` checks a config without touching hardware.

## Credentials
A gitignored, mode-600 `.env` at the repo root holds a GitHub token. Never read or print it (no
`cat`/`grep` of `.env`, no `env` dumps, no `gh auth token`). If `gh` returns 401, tell the user.
