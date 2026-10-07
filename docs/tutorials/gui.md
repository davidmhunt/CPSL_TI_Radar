# GUI tutorial: configure, run, watch

The radar GUI (`radar_gui/`) is one process: a Python backend plus a no-build web page. It generates and validates a cfg, runs the C++ driver, and shows the point cloud. Reference detail: [`radar_gui/README.md`](../../radar_gui/README.md). Measured behaviour: [`../RESULTS.md`](../RESULTS.md) "GUI bench validation".

## Launch

```
uv run python -m radar_gui                 # http://127.0.0.1:8000/, no live source
uv run python -m radar_gui --port 8001     # another port
uv run python -m radar_gui --tailscale     # also listen on this machine's tailnet IP
uv run python -m radar_gui --driver-bin PATH   # driver binary for the Run tab
```

The default is `--source none` (Live says "pick Serial or Replay, or start a driver run"). Build the driver first (`docs/tutorials/01_build_and_host_setup.md`); the Run tab uses `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP`. The GUI has no authentication: use Tailscale ACLs and never `tailscale funnel`.

> The live tap (Live follows a driver run), `--skip-configure` (Run-tab skip-cfg box) and the ADC tab are in the driver built in `build/` (Rebuild 1, `bc54c7a`). The driver-side firmware check (gui-33) needs a driver built after Rebuild 2 (pending). On an older binary the GUI says "rebuild the driver" and disables the affected features; everything else works. Rebuild: [`rebuild_driver.md`](rebuild_driver.md).

## The tabs

- **Configure.** Pick a board and a firmware, enter targets (max range, max velocity; optional resolution, frame rate), and watch the metrics and the constraint list update. Warnings and errors carry a confidence label. "Load an existing cfg" analyses a shipped or saved cfg. Tick "Stream raw ADC over LVDS" for DCA1000 use. **Save** writes `<name>.cfg` and `<name>.json` to `CPSL_TI_Radar_cpp/config/user/` (never overwrites; an error-level cfg is refused unless "Save even with errors"). The cascade is limited to 256 chirps per frame (an error above that; see `docs/research/gui_cascade_chirp_limit_2026-10-07.md`).
- **Run.** Pick a system JSON (saved ones first), **Validate** (OK / INVALID, bytes per frame, notes, the echo of the cfg commands), then **Start**, optional Frames / Duration. **Stop** sends SIGINT. Cards show frames, rate, dropped / kernel drops / incomplete (DCA1000) or missed (serial); after exit you get the run directory (`runs/gui/<UTC>_<name>/`) and the `adc_data.bin` verdict (`exact` expected). A "Board commands" panel opens on the first failing cfg command. For once-per-power-up boards (the cascade) a "skip cfg" box streams without sending a cfg . One run at a time; refusals show "radar in use" or "ports busy".
- **Live.** Source card: **Serial** (the GUI configures the board over its CLI port and reads the data port), **Replay** (a TLV dump; pick the TLV dialect; fixtures are in `tests/fixtures/replay/`), or it **follows a driver run** started in the Run tab. Views: top, 3D, front, sparkline; header shows rate, gaps, errors. "Also capture raw bytes" saves a dump to `runs/gui/dumps/`. The cascade source has an "already configured this power-up" tick.
- **ADC.** For a Run-tab driver run with a DCA1000 config, four panels update live from the driver tap: range profile, range-Doppler, range-azimuth and raw-ADC diagnostics (bits used, clipping, RMS, I/Q image ratio). The Run tab "ADC views" selector sets the rate: every frame (default), every K frames, or off; so "Save ADC frames" can stay off. Without a tap-capable driver or a DCA1000 stream the panels say why. On one real bench capture the diagnostics read 11/16 bits used, 0 clipped, RMS about -45 dBFS (single-capture evidence; see RESULTS).
- **Settings.** Read-only: serial ports grouped by board (XDS110 `-if00` = CLI, `-if03` = data; serial `00000000` = cascade; which process holds each port) and DCA1000 host checks (NIC address, `rmem_max`, optional ping). Fix commands are shown as text; run `uv run tools/setup/host_setup.py --nic <nic> --apply` yourself.

## Session: IWR1843 + DCA1000

1. Board on the SDK 3.6 demo image (SOP 001), DCA1000 powered and cabled, host set up (Settings tab shows no missing items).
2. Configure: board IWR1843, firmware demo, targets (for example 10 m / 3 m/s / 10 Hz), tick "Stream raw ADC over LVDS". Save as `my_1843_dca` with by-id CLI and data ports (`ls -l /dev/serial/by-id/`), Serial TLV on, DCA1000 on, Save ADC frames on.
3. "Open in Run" -> Validate (expect OK, the DCA1000 line shows 192.168.33.180) -> Start.
4. Watch dca `frames` rise at the cfg rate with dropped = 0 and kernel drops = 0. Stop. Expect verdict `exact`.
5. While the run is active the Live serial source is refused ("ports busy"); that is by design. The IWR1843 can be restarted any number of times.

Serial only: Live -> Serial, board IWR1843, `IWR1843_demo.cfg`, the by-id ports, Start. Status goes `configuring i/N` -> `streaming`.

## Session: cascade (AWR2243)

1. **Power-cycle first** (12 V off, 5 s, on, wait ~10 s for USB). The cascade accepts a cfg once per power-up, and a failed `sensorStart` also needs a power cycle.
2. Configure: board AWR2243_CASCADE, firmware cascade_ddm, targets (for example 15 m / 5 m/s / 10 Hz); keep chirps per frame at or below 256. Save with the cascade by-id ports (ids end `CMSIS-DAP_00000000`).
3. Start from the Run tab (or Live -> Serial). Expect frames at the cfg rate, missed = 0.
4. To start again without a power cycle, use the skip-cfg box (Run tab) or Live's "already configured this power-up" tick. Starting without it gives `cfg_failed` with a power-cycle notice.
5. The cascade firmware shows "not checked" in the Source card. Stopping a driver run on the cascade is quick (the driver skips `sensorStop` on once-per-boot boards).
