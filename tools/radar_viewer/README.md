# Cascade Radar Viewer

Live point-cloud viewer for the AWR2243 2-chip cascade EVM. Lives in `CPSL_TI_Radar/tools/`.

```bash
cd tools/radar_viewer
python3 server.py            # then open http://localhost:8080
```

- Needs only Python 3 + pyserial (already installed). Ports default to the XDS110 by-id paths.
- Sends `../../CPSL_TI_Radar_cpp/config/radar/cascade/cascade_shortrange.cfg` by default (needs `guiMonitor -1 1 …`
  so frames carry type 1 points + type 7 SNR). Use `--cfg` for another file.
- The board accepts a cfg once per power-up. Power-cycle before starting. If you power-cycle while the
  viewer runs, it notices the USB drop and reconfigures the board by itself.
- `--skip-config` attaches to a board that is already streaming.
- Can't run at the same time as the C++ driver (they'd fight over the serial ports).
- Views: top (hover a point for range/x/y/z/velocity/SNR), 3D (drag to rotate, scroll to zoom; `#3d` in the URL
  opens it directly), front (x–z). Colour by velocity, SNR or height; trail, range, size and min-SNR sliders.
- Denser points: `python3 server.py --cfg ../../CPSL_TI_Radar_cpp/config/radar/cascade/cascade_shortrange_dense.cfg`.
  The cfg is re-read on every power cycle, so to tune: edit the thresholds, save, power-cycle the board, look.
  `cfarCfg` threshold (8th number, dB): lower = more points. `localMaxCfg -1 <azim> <doppler>`: higher = more points.

## Radar config panel

**Radar config** in the header (or `http://localhost:8080/#config`) opens a panel with three parts.

- **Board:** shows which cfg the board is running. You can also pick which cfg the next power-up gets.
- **Design a cfg:** set max range, max velocity, frame rate, CFAR and local-max thresholds, and the field of view.
  - `cfggen.py` solves for the chirp: sample rate, slope, idle time and ramp time. It writes a cfg to `configs/`, based on the driver's `cascade_shortrange.cfg`.
  - With a fixed number of ADC samples, max range and range resolution are tied (max ≈ 0.9 × samples × resolution). Max velocity and the number of chirps tie velocity resolution the same way.
  - TI only tested 192 samples × 256 chirps. Other counts are allowed but flagged as untested.
- **Antenna calibration:** uses TI's `cascade_shortrange_calib.cfg` with your reflector distance.
  - After a power cycle, the board prints its measurement on the CLI port every frame, and the panel shows it.
  - **Save calibration** writes `configs/antenna_calib.txt`. New cfgs then use it in place of TI's numbers, which were measured on TI's own board.

The demo accepts a cfg only once per power-up, so each change takes effect on the next power cycle.

Run `python3 cfggen.py` to check that the generator reproduces TI's short-range design.
