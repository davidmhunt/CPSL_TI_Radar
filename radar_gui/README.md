# radar_gui

Single-process radar GUI prototype (gui-01): FastAPI + uvicorn backend, plain-JS ES-module frontend (no bundler,
no build step). The look, layout and point-cloud views are ported from `tools/radar_viewer/`, which is left
untouched as a reference; `tlv.py` loads its `parse_frame`.

    uv run python -m radar_gui --source mock              # http://127.0.0.1:8000/
    uv run python -m radar_gui --source replay --file tests/fixtures/sample_frames.bin
    # options: --rate HZ  --host H  --port P

## Layout

| Path | What |
|------|------|
| `__main__.py` | CLI, starts uvicorn |
| `app.py` | `create_app(source)`: `/api/health`, `/api/state`, WebSocket `/stream`, serves `web/`; `Hub` fans frames to clients |
| `sources.py` | `Source` interface, `MockSource` (moving synthetic targets), `ReplaySource` (TLV byte dump, looped) |
| `tlv.py` | frame parsing (reuses the viewer's `parse_frame`), `split_packets`, `build_packet` (fixtures) |
| `web/index.html`, `web/style.css` | page and styles |
| `web/js/` | `main.js` (stream, controls), `state.js`, `colors.js`, `views.js` (top/3D/front/sparkline canvases) |

Wire format on `/stream` (JSON text messages): `status`, `cfg` (page hints: `max_range_m`, `fov`) and
`frame` (`frame`, `n`, `pts` = `[x, y, z, v, snr, noise]`, `rate`, `gaps`, `errors`).
New sources subclass `Source` and yield frame dicts from `async frames()`.

## Configure tab (gui-03)

Open `http://127.0.0.1:8000/#configure` (or the **Configure** tab). Pick a board and output mode, enter targets
(max range / velocity required; range / velocity resolution, frame rate and advanced overrides optional) and the
resolution / max-range / max-velocity tiles and the constraint list update live (200 ms debounce). Issues show their
level and the confidence of the limit behind them (`repo`, `recalled`, `unverified limit`; hover for the source).
"Load an existing cfg" analyses any shipped or saved `.cfg` (the board is guessed from its path; change it if wrong).
Save writes `<name>.cfg` + `<name>.json` (driver system JSON, schema v2, `radar_cfg` = the sibling cfg).

**Where saves go:** `CPSL_TI_Radar_cpp/config/user/` (gitignored; override with `RADAR_GUI_USER_CFG_DIR` or
`create_app(user_cfg_dir=...)`). It sits next to `config/boards/`, so the driver finds the board descriptor with its
default lookup: `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/user/<name>.json --validate`.
Saving never overwrites: an existing `<name>.cfg` or `<name>.json` gives 409, and shipped dirs are never written.
A cfg with error-level issues is refused unless `force` ("Save even with errors") is set. Ports / IPs default to the
repo's usual values (`/dev/ttyACM0` CLI, `/dev/ttyACM1` data, DCA1000 192.168.33.180 / .30) and are editable.

| Endpoint | |
|---|---|
| `GET /api/cfg/boards` | boards, output modes, `limits_dict()`, user dir |
| `POST /api/cfg/analyze` | `{board, cfg_text}` or `{board, targets}` -> `{ok, metrics, issues, text, ...}` |
| `POST /api/cfg/generate` | `{board, targets, firmware?}` -> same shape (`targets`, `achieved`, `name` included); `firmware` = descriptor id, default the board's; `output_mode` in targets is a deprecated alias |
| `GET /api/cfg/firmware[?board=]` | firmware descriptors (id, boards, outputs, system_enables, pending), default first for a board. Descriptors: `CPSL_TI_Radar_cpp/config/firmware/<id>.json` (schema in `radar_gui/cfg/firmware.py`); limits are loaded from them |
| `GET /api/cfgs`, `GET /api/cfg/file?id=` | shipped (`config/radar`, `tools/radar_viewer/configs`) + user cfgs; read one |
| `POST /api/cfg/save` | write the `.cfg` + system JSON (new names only) |

Tests: `uv run pytest tests/test_radar_gui_skeleton.py tests/test_radar_gui_cfgapi.py` (the driver `--validate` test
skips when `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` is absent).
