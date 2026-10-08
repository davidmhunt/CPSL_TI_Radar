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

**Driver verdict on Save (gui-04).** `POST /api/cfg/save` also returns `driver`: the real driver's
`<json> --validate --json` verdict on the file just written (`available`, `ok`, `errors[]`, `warnings[]`, `text`), and Configure
shows it under the Saved message ("Driver check: OK" or the error codes). `available: false` when no driver binary is found (the
Python verdict above it still stands). The driver, not the Python validator, is the final gate: both read the same
`config/firmware/*.json` limits, and `tests/test_validate_parity.py` pins them together. `radar_gui/driver.py` `validate_config()`
(used by Radar-tab Validate and Start too) runs `--validate --json` and falls back to the plain-text `--validate` on a driver
without `--json`. A saved system JSON carries `firmware`; a `config/user/*.json` without it is refused by the driver and is fixed
with the Radar tab's **Add firmware** button or `tools/migrate_config_v1_to_v2.py --add-firmware`. Shots:
`tools/gui_shots_specs/gui04_save.json`.

## Detection (CFAR) card (gui-35)

The Configure tab's "Detection (CFAR)" card edits the on-chip detector: `cfarCfg`, `cfarFovCfg` (FOV) and, on the IWR1443,
`peakGrouping`. It is drawn only from the firmware descriptor, `CPSL_TI_Radar_cpp/config/firmware/<fw>.json` -> `detection`
(variants `sdk2_14xx`, `sdk3_hwa` = IWR1843, `sdk3_dsp` = IWR6843/ODS in `demo.json`; `ddm` in `cascade_ddm.json`;
`detection: null` + `detection_note` for `iwr1843_sar_lvds` and `dca1000_raw`, where the card shows why it is off).
Per-direction fields have a Range and a Doppler column; every field carries `help` and a `cite` (tooltip) and the variant a
`level` (`bench` / `source` / `unverified`; all are `source` until the Step 5 bench run). The 1443 threshold is the raw log2-Q9
value with the dB it means for the cfg's antenna count next to it. The FOV is **auto** (follows max range and +-max velocity)
until "Manual field of view" is ticked; the cascade DDM build has no `cfarFovCfg`, so no FOV controls.

- Backend: `radar_gui/cfg/detection.py` (`schema`, `from_cfg`, `apply`, `issues`, `describe`). `apply` rewrites only the lines
  whose numbers change (comments and every other byte kept) and inserts a missing line before `sensorStart`, only when you
  gave values for it. A cfg whose detection lines address a subframe (`subFrameIdx != -1`) or do not fit the firmware's argument
  layout is read-only here ("edit the cfg text").
- API: `/api/cfg/analyze`, `/params`, `/generate` results carry `detection: {schema, values, editable, note, context}`;
  `POST /api/cfg/detection {board, firmware, base_cfg_text, values}` returns the `/params` shape. The same `values` go in
  `targets.detection` (Targets mode) and `params.detection` (Chirp parameters mode). `cfar_range_db` / `cfar_doppler_db`
  target keys still work as threshold aliases.
- Checks (`cfar_*` codes, GUI-only: the C++ driver does not enforce them; the firmware answers `Done`/errors itself): argument
  count and ranges, unknown enum, threshold above 100 dB, FOV min >= max, a missing direction line, cascade Doppler mode /
  guard / enable, and as warnings `2*(noiseWin+guardLen)` against the FFT bins (the shipped `1843_RadarHD.cfg` violates it,
  so it is not an error until a bench run settles it) and the TI `divShift` formula. FOV beyond the cfg's range or velocity is info.
- Live re-tune while streaming is not part of this card.
- Screenshots: `uv run python tools/gui_shots.py --scenarios tools/gui_shots_specs/gui35.json` (1843, 1443, cascade, SAR note,
  an error state, Chirp-parameters mode with a manual FOV; each at 1400 and 800 px).

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

## Session, header bar and tabs (gui-37)

The board has **one engine and one session**: every board Start, from the header, the Radar tab or the Point cloud tab, runs the C++ driver through `POST /api/driver/start`. The Python serial source is no longer offered in the UI (its backend path stays until Step 6). Tabs: **Configure** (`#configure`), **Radar** (`#run`, the backend session), **Point cloud** (`#live`), **Raw ADC** (`#adc`), **Devices** (`#settings`) and **Logs** (`#logs`); the internal `data-tab` ids and old hashes still work, `#radar`/`#pointcloud`/`#devices` are aliases. With no hash the page lands on Point cloud if a session is live, else on Radar. Tabs are an ARIA tablist: arrow keys, Home/End and digits 1-N (when focus is not in a field). There is deliberately **no global Start/Stop hotkey**.

**Header session bar** (`web/js/session.js`): a status pill (`role=status`, `aria-live=polite`, text always carries the state: `No session`, `Starting`, `Configuring 5/27 · IWR1843`, `IWR1843 · cfg · pid N`, `Stopping`, `Replay · file`, `Ended`, `Died`, `Config failed`, `Wrong firmware`), a `● saving` / `not saving` badge (while idle, `will save: ADC frames` when the recording boxes differ from the config's own), a description line and one button: **Stop** while a session runs, else **Start <last setup>** (or **Set up...** before the first start). After this GUI process sent the cfg to a once-per-boot board (the cascade) the button becomes **Restart (skip cfg)** with **Send cfg (after a power-cycle)** next to it; the evidence is keyed on the backend's `boot` id (`/api/driver/status`), so a restarted GUI or an older backend never skips on its own. One session at a time: Start is disabled with "Stop <current> first" while one runs; starting a board session replaces a running replay.

**Radar tab** holds the setup both tabs share (`spec`, kept in `localStorage`): **Saved config** (a system JSON from `config/user/` or `config/system/`) or **Quick setup** (board, firmware, cfg, CLI/data ports, DCA1000 on where the firmware streams LVDS; the backend writes `runs/gui/<UTC>_<name>/session.json` + `radar.cfg`). **Recording** boxes (Save ADC frames, Save raw LVDS, Save serial bytes) start from the selected config's own values (`saves` in `/api/driver/configs`) and are sent as `overrides` only when they differ; ADC/LVDS need a DCA1000 stream, serial bytes need `caps.save_serial_bytes`. **Save to config** writes the flags back (`POST /api/driver/config/save`): a `config/user/` file is overwritten after a confirm with the previous version kept as `<name>.json.bak` (indent 4, atomic write, re-validated); a shipped `config/system/` file is never overwritten, only copied into `config/user/` under a name you choose; paths are confined to the user directory (422 otherwise). The JSON writer is `radar_gui/sysjson.py`.

**Point cloud tab** "Now showing" card: **Board** (a compact picker bound to the same setup, Start/Stop, firmware line, board commands, "More options in Radar") or **Replay** (a TLV file and dialect; the list includes `runs/gui/*/serial_data.bin` run captures, dialect from the run's `session.json`). Controls whose capability the backend lacks are hidden, and an older backend still offers saved configs (JS tolerates a missing `caps`, `/api/driver/boards` or `config/save`).

API (additive): `POST /api/driver/start` takes `config` + `overrides` or `setup`; `GET /api/driver/{configs,boards,status}`; `POST /api/driver/config/save`; `GET /api/source/files` (adds the `runs` group). Tests: `tests/test_radar_gui_session.py`, `tests/test_radar_gui_saveconfig.py`. Shots: `tools/gui_shots_specs/gui37.json` (server `tests/fakes/gui_fake_session.py` lifts the quick-setup port allowlist; test scaffolding only).

**Logs tab** (`#logs`, `radar_gui/logs_api.py`): lists the run folders under the run root (`runs/gui/`, or `RADAR_GUI_RUN_DIR`), newest first, with start time, board/firmware (from `session.json`), size, files and a `saving` badge; **View** shows `driver.log` (last 200/500/5000 lines), `session.json` or `radar.cfg` as plain text (`textContent`); **Replay** (when `serial_data.bin` exists) shows that capture in the Point cloud tab; **Delete selected** asks for a confirm that names the folders and total size, then `POST /api/logs/delete {names}`. Server rules: a session is addressed by its folder name only (`<UTC>_<name>`, no `/` or `..`), must be a real directory directly under the run root (symlinks rejected), all names are validated before anything is removed (422), the running session is refused (409), and `config/user/`, `runs/gui/dumps/` and everything else outside the run root are not addressable. No auto-pruning. Tests: `tests/test_radar_gui_logs.py` (temp run root only), shots `tools/gui_shots_specs/gui37_logs.json` (`run_files` seeds the scratch run root).

## Settings tab (gui-32)

A read-only **Settings** tab (`#settings`). **Serial ports** lists `/dev/serial/by-id/*` grouped by XDS110 serial (`-if00` = CLI, `-if03` = data, ttyACM node, and the process holding each port from a `/proc` scan, via `ports.py`); serial `00000000` is labelled as the cascade. Nothing is opened or probed. "Use for Configure -> Save" / "Use for Quick setup (Radar tab)" only fill the existing port fields. **DCA1000 host check** runs `tools/setup/host_setup.py`'s `check_dca_nic` (never confirmed, so no fix is ever applied) and `check_sysctl` (`rmem_max`), plus an optional single ping of 192.168.33.180; fix commands are shown as text only. Changing the host stays a terminal job (`uv run tools/setup/host_setup.py --nic <nic> --apply`).

API: `GET /api/settings/ports`, `GET /api/settings/dca?nic=<wired NIC>&ping=0|1` (a `nic` that is not a wired ethernet interface is 422). Tests: `tests/test_radar_gui_settings.py` (fake by-id dir mirroring the bench, host_setup's FakeHost). Shots: `tools/gui_shots_specs/gui32.json`.

## Radar tab: driver runs (gui-05; the tab was called Run)

Open `http://127.0.0.1:8000/#run` (or the **Run** tab): pick a system JSON (saved ones from `config/user/` first, then `config/system/`;
Configure's Save result has an **Open in Run** link that preselects the file), **Validate** (runs `<driver> <json> --validate`; shows
OK / INVALID, frame geometry, bytes/frame, notes and the raw text), optionally set **Frames** / **Duration**, then **Start** (spawns
`<driver> <json> --stats [--frames N] [--duration S]`, validating first) and **Stop** (SIGINT so the driver flushes its files; SIGKILL after
`max(5 s, 2 x frame period)`). The header session bar shows the state on every tab. Per stream (DCA1000, serial) the cards show frames, rate
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

## ADC tab (gui-07)

Live range profile, range-Doppler, range-azimuth and raw-ADC diagnostics from the driver tap's `adc` messages, so `save_adc_frames` can stay off.
Needs a Run-tab driver run with a DCA1000 config and a driver whose usage text lists `--tap-fd` and `--tap-adc-every` (Rebuild 1 or later).

- **Rate.** Run tab "ADC views": **every frame** (default, K=1), **every K frames**, or **off**; remembered per config in the browser and sent as
  `adc_every` in `POST /api/driver/start` (null = 1, 0 = off). The GUI passes `--tap-adc-every K` only when K > 0, the system JSON has
  `dca1000.enabled` and the binary lists the flag; `GET /api/driver/configs` carries `caps.adc_tap`. The processor thread keeps only the newest
  frame: if it falls behind it drops (counted as `dropped(gui)` in the tab) and never stalls the tap reader. Median `proc` time is shown too
  (about 30 ms for the bench 4x128x256 cube, `tests/test_radar_gui_adc.py`).
  The default test only guards `proc` < 250 ms (host-load tolerant); the strict < 50 ms check is opt-in on an idle host:
  `RADAR_GUI_PERF=1 uv run pytest tests/test_radar_gui_adc.py -k timing_bench -q -s`.
- **Processing** (`radar_gui/adc.py`, hand-written numpy, no new dependency). Hann-windowed range FFT; the range profile shows all N bins (complex
  1x gives positive IF only, so an I/Q swap puts a reflector at N-k and the image ratio goes negative). Range-Doppler: FFT over loops per virtual
  channel, centre = 0 m/s, **+ = receding**. Range-azimuth: azimuth-TX slots x RX as a lambda/2 line, 64-point zero-padded FFT per loop,
  uniform in sin(theta), **right = positive angle / +x**, bench-confirmed on the IWR1843 2026-10-07; the sign is per board (`AZ_SIGN_BY_BOARD` in `radar_gui/adc.py`; IWR1443 and IWR6843 are assumed the same). Disabled (with the reason shown) for BPM, DDMA, IWR6843ODS and fewer than 2 azimuth virtual channels. No TDM motion compensation.
  Geometry comes from the run's system JSON and cfg, not from the tap; a different frame shape is rejected (counted) with both shapes named.
  "clutter removal" subtracts the mean over loops per range bin (default off). Diagnostics per RX: peak I/Q, bits used, RMS dBFS, DC offsets,
  I/Q power ratio, clipped count (|x| >= 32767), bit-usage bars, and one chirp's I/Q time series (chirp selectable).
- **Transport.** A separate binary WebSocket `/adc` (u32 LE header length, JSON header, arrays; heatmaps uint8 over a 60 dB window, axes above
  256 max-pooled), newest wins per client, so heatmaps never delay `/stream`. The browser may send `{"clutter": bool, "chirp": int}`. The socket
  is open only while the ADC tab is shown.
- **Range-azimuth views.** Cartesian (x = r sin, y = r cos; default) and Polar (angle across, range up) are drawn from the same array; toggle in the card.
- **States** (shown in every panel): needs a driver run / driver has no live tap or ADC tap (rebuild) / this run has no DCA1000 stream / ADC views
  off / waiting / ended or died (last frame stays).
- **Tests and shots.** `tests/test_radar_gui_adc.py` (synthetic cube with exact bins + 2 real bench frames in `tests/fixtures/adc/`),
  `tests/test_radar_gui_adc_api.py` (gate, `/adc`, states); `uv run python tools/gui_shots.py --scenarios tools/gui_shots_specs/gui07.json`
  (and `gui07_notap.json`, which needs `FAKE_DRIVER_MODE=no-tap`). Fake driver: `FAKE_DRIVER_ADC=bench` sends a synthetic bench-shaped cube.
