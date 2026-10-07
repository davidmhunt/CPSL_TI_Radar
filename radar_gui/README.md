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

Open `http://127.0.0.1:8000/#configure` (or the **Configure** tab). Pick a board and a firmware (the firmware list is filtered by board; its outputs show read-only), enter targets
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
| `GET /api/cfg/boards` | boards, firmware summaries, `limits_dict()`, user dir |
| `POST /api/cfg/analyze` | `{board, cfg_text}` or `{board, targets}` -> `{ok, metrics, issues, text, ...}` |
| `POST /api/cfg/generate` | `{board, targets, firmware?}` -> same shape (`targets`, `achieved`, `name` included); `firmware` = descriptor id, default the board's; `output_mode` in targets is a deprecated alias (backend only; the UI no longer sends it) |
| `GET /api/cfg/firmware[?board=]` | firmware descriptors (id, boards, outputs, system_enables, pending), default first for a board. Descriptors: `CPSL_TI_Radar_cpp/config/firmware/<id>.json` (schema in `radar_gui/cfg/firmware.py`); limits are loaded from them |
| `GET /api/cfgs`, `GET /api/cfg/file?id=` | shipped (`config/radar`, `tools/radar_viewer/configs`) + user cfgs; read one |
| `POST /api/cfg/params` | `{board, base_cfg_text, params, firmware?}` -> analyze shape + `report`, `params` (gui-11): `params` (schema in `radar_gui/cfg/params.py`) is applied to the base cfg's profile/chirp/frame/channel lines, then validated; bad values are error issues, not 4xx/5xx |
| `POST /api/cfg/save` | write the `.cfg` + system JSON (new names only) |

Tests: `uv run pytest tests/test_radar_gui_skeleton.py tests/test_radar_gui_cfgapi.py` (the driver `--validate` test
skips when `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` is absent).

## MIMO panel and chirp table (gui-16)

The Configure tab's MIMO card shows the scheme badge (TDM / TDM+BPM / DDMA), a loop timing diagram and each derived number with its
formula, all read from `metrics` (`scheme`, `chirp_sequence`, `derivations`, ...). Under the diagram, the **chirp table** lists one row per
chirp of the loop with TX1/TX2/TX3 checkboxes, add / remove / move-up / move-down (up to the firmware descriptor's
`mimo.max_chirps_per_loop`) and presets: SIMO (1 TX), 2-TX TDM (1,4), 3-TX with elevation (1,4,2), and BPM (2 TX), the last shown only where
`mimo.bpm` is true. Editing the table switches to the chirp-parameter mode and posts only the difference from the seed to
`POST /api/cfg/params`: `chirp_tx_masks` (list of ints), or `{"bpm": true}` for the BPM preset (the backend writes masks `[5, 5]` and enables
`bpmCfg`; `{"bpm": false}` leaves BPM). Warnings and errors come back in `issues` (e.g. `tx_pattern_invalid`, `bpm_unsupported`); chirp-pattern
codes outline the table. Below the rows, a **phase table** (gui-23) lists every chirp of the loop with one degree column per TX (headers coloured like the timing diagram; `metrics.chirp_phases`/`phase_tx`/`phase_source`/`phase_note`; `—` = not BPM-coded; scrolls with a sticky header past 12 rows): BPM 0/180, plain TDM 0. On the cascade (DDMA) the table is read-only: every chirp is listed with the firmware-derived per-TX phases, labelled unverified (chirp order may be reversed), since the phases are set by firmware, not cfg
(`chirp_tx_masks` edits there are ignored with `cascade_chirp_mask_ignored`). `tests/test_radar_gui_cfgapi.py::test_chirp_table_payloads`
pins the payload shapes (no browser harness).

## Remote access over Tailscale

**Recommended: one command.** `--tailscale` keeps the server on `127.0.0.1` and proxies it onto your tailnet with `tailscale serve` (HTTPS, tailnet-only; never `funnel`):

```
uv run python -m radar_gui --source mock --tailscale      # composes with --source/--port
```

It prints `GUI on tailnet: https://<machine>.<tailnet>.ts.net/`; open that from any device on the tailnet (the live WebSocket picks `wss:` automatically). Ctrl-C/SIGTERM removes only this mapping (`tailscale serve --https=443 off`).
If tailscale is missing, logged out, denied (run once `sudo tailscale set --operator=$USER`), or a serve config already exists (left untouched), it says why and keeps serving locally.

**Manual alternative.** Same result in two terminals:

```
uv run python -m radar_gui          # terminal 1
tailscale serve --bg 8000           # terminal 2 (runs in the background)
```

`tailscale serve status` shows the URL; stop sharing with `tailscale serve --https=443 off` (or `tailscale serve reset` to clear all serve config).

**Alternative: bind to the Tailscale interface.** `uv run python -m radar_gui --host <tailscale-ip> [--port 8000]` listens only on that
interface (plain HTTP/`ws:`, no TLS); browse to `http://<tailscale-ip>:8000/`.

> [!WARNING]
> The GUI has **no authentication**. Anyone who can reach it on the tailnet can save cfgs and (once run control exists) start radar runs.
> Restrict access with Tailscale ACLs, and never expose it with `tailscale funnel` (public internet).
