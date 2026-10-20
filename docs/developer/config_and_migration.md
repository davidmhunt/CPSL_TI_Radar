# The config tree and the v1 to v2 migration

What the driver and the GUI read at startup, how the files are named, and the tool that converts old (v1) system configs. The file-by-file index is [`config/README.md`](../../CPSL_TI_Radar_cpp/config/README.md); the board descriptor schema is [`config/boards/README.md`](../../CPSL_TI_Radar_cpp/config/boards/README.md).

## The tree (`CPSL_TI_Radar_cpp/config/`)

| Path | What |
|---|---|
| `boards/<BOARD>.json` | One descriptor per board: CLI handshake, UART, LVDS layout, DCA1000 settings. The file name equals its `"name"` |
| `firmware/<id>.json` | One descriptor per firmware image: which boards run it, cfg rules, the limits the GUI enforces (each with a `source` into [`radar_notes.md`](radar_notes.md)) |
| `limits/host.json` | Host-side limits (DCA1000 throughput) |
| `system/<BOARD>_<fw>_<purpose>[_<mount>].json` | The file you pass to `CPSL_TI_Radar_CPP`: board, firmware, radar cfg, ports, outputs. Flat; the driver finds `<JSON dir>/../boards` |
| `radar/<BOARD>/<firmware>/<name>.cfg` | The TI chirp configs the system JSONs point at |
| `moved_paths.json` | `{"radar": {old: new}, "system": {old: new}}`: every shipped name that changed in the reorganisation |
| `user/` | Gitignored: the GUI's saved configs. Nothing here is renamed or moved |

## Naming rules

- **System JSON:** `BOARD` is the radar folder's board (the GUI board: the SAR file is `IWR1843_...` although its `"board"` key is `IWR1843_SAR`); `fw` is the file's `firmware` key; `purpose` is `[A-Za-z0-9]` tokens; `mount` is one of `front`, `back`, `down`, `r1`. Outputs are not in the name.
- **Radar cfg:** `<purpose>[_<variant>].cfg` under `radar/<BOARD>/<firmware>/`. The board prefix was dropped because the folder gives it; project names (`RadVel_10Hz`, `IcaRAus`) stay. Copies from `iwr_raw_rosnode` carry a `rosnode_` prefix.
- **Enforced** by `tests/test_config_tree.py`: names and folders match the keys inside, every `moved_paths.json` target exists and its old path does not, and `config/README.md` indexes every system JSON and every moved path. Add a file, then add its row to `config/README.md`, or that test fails.

## Why `moved_paths.json` exists

A v1 or early v2 config points at a radar cfg by its old path. The migration tool rewrites such a `radar_cfg` through the `"radar"` table, and `tests/test_migrate_config.py` uses the `"system"` table to match each v1 fixture to the tracked file it became. If you rename a shipped file, add its old name here pointing at the new one; `tests/test_config_tree.py` fails when a target is missing or an old path still exists.

## The migration tool

`tools/migrate_config_v1_to_v2.py` converts v1 system configs (`verbose`, `TI_Radar_Config_Management`, `CLI_Controller`, `Streamer`) to schema v2. Why the driver names it: `SystemConfigReader.cpp:276-281` refuses a file with no `schema_version` and prints the exact command (`kMigrationScript` in `SystemConfigReader.hpp`), instead of reading both schemas. The key-by-key mapping and the behaviour changes are in [`../migration_v1_to_v2.md`](../migration_v1_to_v2.md); the v1 code is the `v1.0` tag.

```bash
uv run tools/migrate_config_v1_to_v2.py my_config.json                      # print the v2 JSON, write nothing
uv run tools/migrate_config_v1_to_v2.py my_configs/ --in-place              # rewrite every v1 *.json in a directory
uv run tools/migrate_config_v1_to_v2.py my_configs/ --check                 # exit 1 if any file is still v1
uv run tools/migrate_config_v1_to_v2.py my_config.json --add-firmware --in-place   # add the mandatory "firmware" key to a v2 file
```

Properties the tests rely on:

- **Idempotent.** A v2 file comes back unchanged; running twice changes nothing.
- **Never silent.** An unknown v1 key is reported and the file is not converted (`--drop-unmapped` converts anyway, dropping the key). Without `--in-place` nothing is written.
- **Inference.** `board` comes from `Streamer.board_type`, else from `SDK_version` (2.x is IWR1443, 3.x is IWR1843), as v1 did. `firmware` is inferred from the board (one firmware: that one; IWR1843, IWR6843, IWR6843ODS: `demo`; IWR1443: `dca1000_raw` if the DCA1000 is enabled, else `demo`); `--firmware` overrides.
- **Board overrides.** A v1 baud or timeout becomes `board_overrides` only when it differs from the board descriptor's own value (found via `$CPSL_TI_RADAR_BOARDS_DIR`, else `<config dir>/../boards`).
- **Moved cfgs.** A `radar_cfg` that points at a pre-reorganisation cfg is rewritten through `moved_paths.json`, also in a v2 file under `--in-place` or `--check`.
- The GUI's **Add firmware** button writes the same bytes (both use `radar_gui/sysjson.py`).

## Tests

`tests/test_migrate_config.py` converts the v1 files in `tests/fixtures/v1_configs/` and compares each with the tracked v2 file it became (the deliberate edits made afterwards are listed in the test); it also covers in-place and directory runs, idempotence, `--check`, key mapping, override dropping, board inference, unmapped keys, `--add-firmware`, and the moved-cfg rewrite. `uv run pytest -q tests/test_migrate_config.py tests/test_config_tree.py`.

## Reaching old files

Removed v1 files stay in git: `git show v1.0:<path>` prints one (for example `git show v1.0:CPSL_TI_Radar_cpp/config/radar/DCA1000/IWR1843_configs/IWR1843_demo.cfg`), and `moved_paths.json` gives the new name of every shipped cfg that moved.
