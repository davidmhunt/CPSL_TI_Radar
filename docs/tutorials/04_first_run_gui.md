# 4. First run with the GUI: configure, run, watch

The radar GUI (`radar_gui/`) is one process: a Python backend plus a no-build web page. It builds and checks a radar cfg, runs the C++ driver, and shows the point cloud and raw ADC. Needs [tutorial 1](01_install.md); a real run also needs [2](02_host_setup.md) and [3](03_flash_a_radar.md). Reference: [`radar_gui/README.md`](../../radar_gui/README.md).

## Start it

Demo mode, no hardware: the command from [tutorial 1](01_install.md), then open `http://127.0.0.1:8090/` (it replays a recorded IWR1843 capture through a stand-in driver, `RADAR_GUI_DRIVER`; 8090 is also the Docker demo's port). With a board, drop the demo settings and use the default port 8000:

```bash
uv run python -m radar_gui               # http://127.0.0.1:8000/; the Radar tab runs CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP
```

All flags: `uv run python -m radar_gui --help`. This tutorial uses `--port`, `--source`, `--file`. The GUI has no authentication: keep it on loopback, or reach it over Tailscale (`--tailscale`) with ACLs, and never `tailscale funnel`.

## The tabs

**Configure · Radar · Point cloud · Raw ADC · Devices · Logs** (keys 1-6 when focus is not in a field). The header shows the session (`No session`, `Configuring 5/27 · IWR1843`, `Ended`, ...), `saving` / `not saving`, and one **Start / Stop**. Every board Start runs the C++ driver, and only one session runs at a time.

**Configure.** Pick a board and firmware, enter targets (max range, max velocity, optionally resolution and frame rate), and watch the metrics and constraints update. "Load an existing cfg" analyses a shipped cfg. Tick "Stream raw ADC over LVDS" for a DCA1000. **Save** writes `<name>.cfg` and `<name>.json` to `CPSL_TI_Radar_cpp/config/user/` (never overwrites; a cfg with errors is refused unless "Save even with errors"). The cascade is limited to 256 chirps per frame.

![Configure tab](../images/gui/configure.png)

**Radar.** The session. Choose a **Saved config** (a system JSON) or **Quick setup** (board, firmware, cfg, ports, DCA1000). The **Recording** boxes (Save ADC frames, Save raw LVDS, Save serial bytes) start from the config; **Save to config** writes your choice back. Press **Validate**, then **Start**, with optional Frames or Duration. **Stop** sends SIGINT. Cards show frames, rate, and dropped / kernel drops / incomplete (DCA1000) or missed (serial). Afterwards you get the run folder `runs/gui/<UTC>_<name>/` and the `adc_data.bin` verdict (`exact` expected). A "Board commands" panel opens at the first cfg command that fails.

![Radar tab](../images/gui/radar.png)

**Point cloud.** "Now showing" **Board** (same setup and Start / Stop as Radar) or **Replay** (a TLV dump, or a run's `serial_data.bin`). Views: top, 3D, front, sparkline.

![Point cloud tab](../images/gui/point_cloud.png)

**Raw ADC.** Needs a DCA1000 session. Live range profile, range-Doppler, range-azimuth and ADC diagnostics (bits used, clipping, RMS, I/Q ratio). The driver assumes the IWR1843 I/Q order `q_first`. "Clutter removal" leaves only moving targets. The Radar tab's "ADC views" selector sets the rate (every frame, every K, or off).

![Raw ADC tab](../images/gui/raw_adc.png)

**Devices.** Read-only: serial ports grouped by board (XDS110 `-if00` = CLI, `-if03` = data; serial `00000000` = cascade) and which process holds each, plus DCA1000 host checks (NIC address, `rmem_max`). Fixes are shown as text; run `host_setup.py` ([tutorial 2](02_host_setup.md)) yourself.

![Devices tab](../images/gui/devices.png)

**Logs.** Every Start writes `runs/gui/<UTC>_<name>/` (gitignored, never pruned automatically). This tab lists runs, shows `driver.log`, `session.json` and `radar.cfg`, and deletes selected folders after a confirm. Only `runs/gui/` is ever touched.

![Logs tab](../images/gui/logs.png)

## A real session: IWR1843 + DCA1000

1. Board on the SDK 3.6 demo image ([tutorial 3](03_flash_a_radar.md)), DCA1000 powered and cabled, host set up ([tutorial 2](02_host_setup.md); Devices shows nothing missing).
2. Configure: board `IWR1843`, firmware `demo`, targets (for example 10 m / 3 m/s / 10 Hz), tick "Stream raw ADC over LVDS". Save as `my_1843_dca` with the by-id CLI and data ports (`ls -l /dev/serial/by-id/`), Serial TLV on, DCA1000 on, Save ADC frames on.
3. The **Open in Run** button opens it in the Radar tab. **Validate** (expect OK; the DCA1000 line shows 192.168.33.180), then **Start**.
4. Watch `frames` rise at the cfg rate with dropped = 0 and kernel drops = 0. **Stop**; expect verdict `exact`.

Serial only: Point cloud, Board, Quick setup, board `IWR1843`, cfg `demo_tlv_default.cfg`, Start.

**Cascade (AWR2243).** Power-cycle the EVM first: it accepts a cfg once per power-up, and a failed `sensorStart` also needs a power cycle. Configure `AWR2243_CASCADE` / `cascade_ddm` (at most 256 chirps per frame), save with the cascade by-id ports (ids end `CMSIS-DAP_00000000`), and Start. To start again without a power cycle use **Restart (skip cfg)**; sending the cfg again fails with `Config failed`. Setup and flashing: [`docs/hardware/cascade_setup.md`](../hardware/cascade_setup.md).

Next: [tutorial 5, the driver CLI and recording ADC](05_driver_cli_and_adc.md).
