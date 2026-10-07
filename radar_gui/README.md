# radar_gui

Single-process radar GUI prototype (gui-01): FastAPI + uvicorn backend, plain-JS ES-module frontend (no bundler,
no build step). The look, layout and point-cloud views are ported from `tools/radar_viewer/`, which is left
untouched as a reference; `tlv.py` loads its `parse_frame`.

    uv run python -m radar_gui                      # http://127.0.0.1:8000/
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

## Live tab Source card (gui-06)

The **Source** card on the Live tab switches what feeds the point cloud, at runtime: **Mock**, **Replay** (a TLV dump) or **Serial** (a real board's TLV point cloud, GUI-owned serial path: configures the radar over its CLI port, then reads the data port).

Serial, step by step: choose **Serial**, pick the **Board** (IWR1443/1843/6843/6843ODS/AWR2243_CASCADE; the CLI/data baud and TLV dialect come from `config/boards/<board>.json`), pick a **Radar cfg** (shipped or saved from Configure, filtered to the board), check the **CLI port** and **Data port** (pre-filled with the board's usual XDS110 by-id paths for the IWR1843 and the cascade, `/dev/ttyACM0`/`ACM1` otherwise; edit them if your bench differs), then **Start serial**. For boards that accept a cfg only once per power-up (the cascade) tick *Already configured this power-up* to skip the cfg and just read the stream. Status (`configuring i/N`, `streaming`, `stalled`, `no board`, `cfg failed` with a power-cycle hint, the compact-points hint) shows in the card and the header; the header pill names the live source and Frame/Points/Rate follow it. **Stop** releases the ports and the radar lock (a driver run on the same ports is refused while the source holds them, 409). "Also capture raw bytes" writes the data-port bytes to `runs/gui/dumps/<board>_<time>.bin` (gitignored), replayable from the same card.

API: `GET /api/source`, `POST /api/source` (`{kind, board, cfg_id, cli_port, data_port, skip_configure, file, dump}`), `POST /api/source/stop`, `GET /api/source/boards`, `GET /api/source/files`. The GUI is unauthenticated, so the paths are confined: replay accepts only `tests/fixtures/**/*.bin`, `*.bin` in the dumps directory (`runs/gui/dumps/`, or `RADAR_GUI_DUMP_DIR`) and the file the GUI was started with, anything else is 422; `dump` must be a plain file name and is always written inside the dumps directory.

## Run tab (gui-05)

Open `http://127.0.0.1:8000/#run` (or the **Run** tab): pick a system JSON (saved ones from `config/user/` first, then `config/system/`;
Configure's Save result has an **Open in Run** link that preselects the file), **Validate** (runs `<driver> <json> --validate`; shows
OK / INVALID, frame geometry, bytes/frame, notes and the raw text), optionally set **Frames** / **Duration**, then **Start** (spawns
`<driver> <json> --stats [--frames N] [--duration S]`, validating first) and **Stop** (SIGINT so the driver flushes its files; SIGKILL after
`max(5 s, 2 x frame period)`). The header shows a `driver <state>` pill on every tab. Per stream (DCA1000, serial) the cards show frames, rate
(from successive `stats v1` lines; flagged when below 90 % of the config's frame rate), dropped / kernel drops / incomplete (DCA) or missed (serial),
and any other non-zero counters; a stream with drops is outlined red. After exit: run directory, files with sizes, and the `adc_data.bin` size verdict
(`exact` / `short_sigint_tail` / `MISMATCH`, expected = bytes/frame x final DCA frames). The log pane is the driver's stdout+stderr (last 500 lines;
`stats v1` lines hidden by default).

Refusals show in a red box: **409** radar in use (another session, e.g. a driver run already active) or `ports busy: <port> held by <pid> <comm>`,
**422** config not listed / INVALID / port not found, **503** driver binary missing. One run at a time; the radar lock is shared with future serial sources.
The driver ports check covers the CLI and serial-data ports (not the DCA UDP ports).

**Driver binary:** `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` by default; override with `--driver-bin PATH` or `RADAR_GUI_DRIVER`.
Runs happen in `runs/gui/<UTC>_<json stem>/` (gitignored; override `RADAR_GUI_RUN_DIR`), unless the JSON sets `output.dir`.

    uv run python -m radar_gui                                        # real driver, default binary
    uv run python -m radar_gui --driver-bin tests/fakes/fake_driver.py   # no hardware

Wire format (additions to `/stream`): `driver_state` (full status minus the log; also sent on connect), `driver_stats` (`stream`, `stats`
with `rate_hz`), `driver_log_batch` (`lines`, `run`: output lines buffered and sent every 150 ms, in order; a backend older than gui-09 Step 4c sent one `driver_log` with `line` per line, which the page still accepts), `driver_cli` (`entry`, `run`, `first_fail`: one board command and its reply; see below). Endpoints: `GET /api/driver/configs`, `GET /api/driver/status`, `POST /api/driver/{validate,start,stop}`
(body `{config, frames?, duration?}`; only configs listed by `/configs` are accepted). Tests: `tests/test_radar_gui_driver.py` (fake driver
`tests/fakes/fake_driver.py`, modes via `FAKE_DRIVER_MODE`). Shots: `uv run python tools/gui_shots.py --scenarios tools/gui_shots_specs/gui05.json`
(own server, fake driver; the spec's `user_cfgs` carry the system JSONs, `@PORT@` stands for a scratch file used as the CLI port).

**Board command transcript (gui-34).** The driver's CLI traffic is parsed into `status.cli` (`[{seq, i, n, tag, cmd, ok, verdict
DONE|ERROR|TIMEOUT|SKIP, reply, ms}]`, first 500) and `cli_first_fail` (the first failing `seq`), from either the info-level
`cli [i/N] <cmd> -> DONE|ERROR|TIMEOUT (<ms> ms) "<reply>"` line or, for older binaries at `log_level` debug, the `Sent command:` /
`Received response:` pair plus the reply lines up to the prompt. `SerialSource` records the same shape for its own configure attempt
(`GET /api/source` -> `cli`, `cli_first_fail`). The Run tab (under the log) and the Live Source card show it as a collapsible
"Board commands" panel that opens on the first failing line.

## Remote access over Tailscale

**Recommended: one command, no Tailscale privileges or admin changes.**

```
uv run python -m radar_gui --tailscale      # composes with --source/--port
```

The server keeps listening on `127.0.0.1:<port>` and also on this machine's Tailscale IPv4 address (from `tailscale status --json`), same port, plain HTTP/`ws:`. It never binds `0.0.0.0`. It prints `GUI on tailnet: http://<tailscale-ip>:8000/` and `http://<machine-name>:8000/` (MagicDNS); open either from any device on the tailnet. Nothing to clean up on exit.
If tailscale is missing, logged out, or the address cannot be bound, it prints the specific reason and keeps serving locally.

**Optional: HTTPS via `tailscale serve`.** `--tailscale-serve` (or `--tailscale=serve`) keeps the server on `127.0.0.1` and proxies it with `tailscale serve` on :443 (tailnet-only; never `funnel`), printing `https://<machine>.<tailnet>.ts.net/`. Prerequisites: (1) HTTPS certificates enabled for the tailnet (admin console: DNS -> HTTPS Certificates), (2) operator rights (run once `sudo tailscale set --operator=$USER`). Without them it prints the reason (including `tailscale serve`'s own error) and serves locally. Ctrl-C/SIGTERM removes only this mapping; an existing serve config is left untouched.

**Manual alternative.** `uv run python -m radar_gui --host <tailscale-ip>` listens only on the Tailscale interface; or run `tailscale serve --bg 8000` in a second terminal (`tailscale serve status` shows the URL; stop with `tailscale serve --https=443 off`).


> [!WARNING]
> The GUI has **no authentication**. Anyone your Tailscale ACLs allow to reach this machine's tailnet IP (bind mode) or the serve URL can save cfgs and (once run control exists) start radar runs.
> Restrict access with Tailscale ACLs, and never expose it with `tailscale funnel` (public internet).

**Live follows the driver run (gui-36).** A run started from the Run tab hands the Live tab its point cloud: the GUI creates a pipe and
spawns the driver with `--tap-fd <n>`, so there is no second connection to the board. The tap is used only when the driver's usage text
(`<driver> --help`, checked once per binary path + mtime) lists `--tap-fd`; an older build runs untapped and Live says "driver run has no
live tap (rebuild the driver)". On a successful start the Hub switches to a `DriverSource`; the Source card becomes read-only ("driver run
\u00b7 cfg \u00b7 pid", **Manage in Run tab**), the Run tab shows **Watching in Live**, and the header numbers are Live's. When the run ends Live shows
"driver run ended (exit 0, N frames)" (last frame stays) or the red "driver died (exit -9)"; the picker is usable again, and Live never falls
back to a serial source by itself. While a run is followed `POST /api/source*` answers 409; a driver start while the Live serial source holds
the board answers 409 "Live serial source holds the radar (<port>); stop it in the Live tab". `GET /api/driver/status` has `tap` (`on`/`off`).
Wire format (`radar_gui/tap.py`): `u32 len (LE)`, `u8 type`, payload; 1 hello (JSON), 2 points (the Live frame JSON), 3 adc (JSON header line +
int16 I/Q; counted and parsed, not displayed yet). Tests: `tests/test_radar_gui_tap.py` (fake driver modes `tap`/`no-tap`). Shots:
`tools/gui_shots_specs/gui36.json` (running, ended, died) and `gui36_notap.json`.

**No source by default (gui-36 3b).** `python -m radar_gui` starts with `--source none`: the Live tab says "pick Serial or Replay, or start a driver run in the Run tab". `--source mock` remains (hidden from the UI) for tests and `tools/gui_shots.py`. The Replay card has a **TLV dialect** select (sdk2 / sdk3 / mcuplus_cascade), preset from the file name (`AWR2243_CASCADE_*` -> mcuplus_cascade, `IWR1443*` -> sdk2, else sdk3); `POST /api/source` takes `dialect` (default: the same detection). **Skip cfg (Run tab):** for once-per-boot boards (the cascade) the Run tab offers "Already configured this power-up (skip cfg)", sent as `skip_configure` and passed to the driver as `--skip-configure` only when its usage text lists the flag; otherwise the box is disabled ("rebuild the driver") and the API answers 422. `GET /api/driver/configs` carries `caps` (`tap`, `skip_configure`) and per-config `once_per_boot`.
