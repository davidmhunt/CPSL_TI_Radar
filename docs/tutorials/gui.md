# GUI tutorial: configure, run, watch

The radar GUI (`radar_gui/`) is one process: a Python backend plus a no-build web page. It generates and validates a cfg, runs the C++ driver, and shows the point cloud. Reference detail: [`radar_gui/README.md`](../../radar_gui/README.md). Measured behaviour: [`../RESULTS.md`](../RESULTS.md) "GUI bench validation".

## Launch

```
uv run python -m radar_gui                 # http://127.0.0.1:8000/, no live source
uv run python -m radar_gui --port 8001     # another port
uv run python -m radar_gui --tailscale     # also listen on this machine's tailnet IP
uv run python -m radar_gui --driver-bin PATH   # driver binary for the Radar tab
```

The default is `--source none` (no session; the header says "No session"). Build the driver first (`docs/tutorials/01_build_and_host_setup.md`); the Radar tab uses `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP`. The GUI has no authentication: use Tailscale ACLs and never `tailscale funnel`.

> The live tap (Live follows a driver run), `--skip-configure` (Run-tab skip-cfg box) and the ADC tab are in the driver built in `build/` (Rebuild 1, `bc54c7a`). The driver-side firmware check (gui-33) needs a driver built after Rebuild 2 (pending). On an older binary the GUI says "rebuild the driver" and disables the affected features; everything else works. Rebuild: [`rebuild_driver.md`](rebuild_driver.md).

## The tabs

Tabs: **Configure · Radar · Point cloud · Raw ADC · Devices · Logs** (keys 1-6 when focus is not in a field; arrow keys move between tabs). The header bar is the one place that shows the session: a status pill (always with text: `No session`, `Configuring 5/27 · IWR1843`, `IWR1843 · name · pid N`, `Ended`, `Died`, ...), `saving` / `not saving`, and one **Start / Stop** button. There is no Start hotkey on purpose. Every board Start runs the C++ driver; only one session runs at a time.

- **Configure.** Pick a board and a firmware, enter targets (max range, max velocity; optional resolution, frame rate), and watch the metrics and the constraint list update. Warnings and errors carry a confidence label. "Load an existing cfg" analyses a shipped or saved cfg. Tick "Stream raw ADC over LVDS" for DCA1000 use. **Save** writes `<name>.cfg` and `<name>.json` to `CPSL_TI_Radar_cpp/config/user/` (never overwrites; an error-level cfg is refused unless "Save even with errors"). The cascade is limited to 256 chirps per frame (an error above that; see `docs/research/gui_cascade_chirp_limit_2026-10-07.md`).
- **Radar** (was Run). The backend session. Choose **Saved config** (a system JSON, saved ones first) or **Quick setup** (board, firmware, cfg, ports, DCA1000). The **Recording** boxes (Save ADC frames, Save raw LVDS, Save serial bytes) start from the config's own values; **Save to config** writes your choice back (a `config/user/` file is overwritten after a confirm, keeping `<name>.json.bak`; a shipped config is only copied into `config/user/`). **Validate**, then **Start**, optional Frames / Duration. **Stop** sends SIGINT. Cards show frames, rate, dropped / kernel drops / incomplete (DCA1000) or missed (serial); after exit you get the run directory (`runs/gui/<UTC>_<name>/`, with `session.json`, `radar.cfg`, `driver.log`) and the `adc_data.bin` verdict (`exact` expected). A "Board commands" panel opens on the first failing cfg command. For once-per-power-up boards (the cascade), after this GUI has configured the board the default becomes **Restart (skip cfg)**, with **Send cfg (after a power-cycle)** one click away; the GUI never skips on its own otherwise.
- **Point cloud** (was Live). "Now showing": **Board** (pick a saved config or quick setup, Start / Stop, same setup as the Radar tab) or **Replay** (a TLV dump; run captures `runs/gui/*/serial_data.bin` are listed once the driver can save them). Views: top, 3D, front, sparkline; header shows rate, gaps, errors.
- **Raw ADC** (was ADC). Needs a DCA1000 session. Four panels update live from the driver tap: range profile, range-Doppler, range-azimuth and raw-ADC diagnostics (bits used, clipping, RMS, I/Q image ratio). "Clutter removal" subtracts the per-frame chirp mean, so only moving targets remain. The Radar tab "ADC views" selector sets the rate: every frame (default), every K frames, or off; so "Save ADC frames" can stay off. Without a tap-capable driver or a DCA1000 stream the panels say why. On one real bench capture the diagnostics read 11/16 bits used, 0 clipped, RMS about -45 dBFS (single-capture evidence; see RESULTS).
- **Devices** (was Settings). Read-only: serial ports grouped by board (XDS110 `-if00` = CLI, `-if03` = data; serial `00000000` = cascade; which process holds each port) and DCA1000 host checks (NIC address, `rmem_max`, optional ping). Fix commands are shown as text; run `uv run tools/setup/host_setup.py --nic <nic> --apply` yourself.
- **Logs.** Every Start writes `runs/gui/<UTC>_<name>/` (gitignored, never pruned automatically). The Logs tab lists them (size, board, whether they saved), shows `driver.log` / `session.json` / `radar.cfg`, replays a run's `serial_data.bin`, and deletes selected folders after a confirm that names them and their total size. The running session cannot be deleted, and nothing outside `runs/gui/` (your `config/user/`) is ever touched.

## Session: IWR1843 + DCA1000

1. Board on the SDK 3.6 demo image (SOP 001), DCA1000 powered and cabled, host set up (Settings tab shows no missing items).
2. Configure: board IWR1843, firmware demo, targets (for example 10 m / 3 m/s / 10 Hz), tick "Stream raw ADC over LVDS". Save as `my_1843_dca` with by-id CLI and data ports (`ls -l /dev/serial/by-id/`), Serial TLV on, DCA1000 on, Save ADC frames on.
3. "Open in Run" opens it in the Radar tab -> Validate (expect OK, the DCA1000 line shows 192.168.33.180) -> Start.
4. Watch dca `frames` rise at the cfg rate with dropped = 0 and kernel drops = 0. Stop. Expect verdict `exact`.
5. Only one session runs at a time (Start is disabled with "Stop <current> first"). The IWR1843 can be restarted any number of times.

Serial only: Point cloud -> Board -> Quick setup, board IWR1843, `IWR1843_demo.cfg`, Start (ports default to the bench by-id paths; edit them in the Radar tab). Status goes `Configuring i/N` -> running.

## Session: cascade (AWR2243)

1. **Power-cycle first** (12 V off, 5 s, on, wait ~10 s for USB). The cascade accepts a cfg once per power-up, and a failed `sensorStart` also needs a power cycle.
2. Configure: board AWR2243_CASCADE, firmware cascade_ddm, targets (for example 15 m / 5 m/s / 10 Hz); keep chirps per frame at or below 256. Save with the cascade by-id ports (ids end `CMSIS-DAP_00000000`).
3. Start from the Radar or Point cloud tab (or the header). Expect frames at the cfg rate, missed = 0.
4. To start again without a power cycle, use the header's **Restart (skip cfg)** (or the skip-cfg box). Sending the cfg again without a power-cycle fails with `Config failed` and a power-cycle notice.
5. The cascade firmware shows "not checked" until the driver has its firmware check (Rebuild 2). Stopping a driver run on the cascade is quick (the driver skips `sensorStop` on once-per-boot boards).
