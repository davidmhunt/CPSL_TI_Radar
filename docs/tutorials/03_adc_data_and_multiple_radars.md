# 3. Read `adc_data.bin`, run several radars

## Read a capture

Capture first. With the DCA1000 cabled and configured as in tutorials [1](01_build_and_host_setup.md) and [2](02_first_run.md) (the serial demo config of tutorial 2 writes no `adc_data.bin`), run the DCA1000 example config for 20 frames (any N below the cfg's `numFrames` 30, so the driver ends the run, not the radar):

```bash
cd CPSL_TI_Radar_cpp/build
./CPSL_TI_Radar_CPP ../config/system/front_radar_IWR1843_stress_test.json --frames 20
```

That config sets `save_adc_frames` true and has no `output.dir`, so every completed frame is appended to `adc_data.bin` in the launch folder (`CPSL_TI_Radar_cpp/build`). To choose the folder, add `"dir": "out/front"` to its `output` block (relative to the JSON file, created for you). The file has no header: per frame, for chirp, for rx, for sample, an int16 real part then an int16 imaginary part, little-endian. Lost packets stay in the file as zeros, so after a clean stop the size is a whole multiple of `bytes/frame` (from `--validate`). Anything else means a killed process.

From the repository root:

```bash
stat -c %s CPSL_TI_Radar_cpp/build/adc_data.bin   # whole multiple of bytes/frame, at least 20 frames (a frame or two past N is possible)
```

Load it in NumPy. Take rx, samples and chirps from the `frame:` line of `--validate` (for the stress-test config: 4 rx x 250 samples x 126 chirps):

```python
import numpy as np
rx, samples, chirps = 4, 250, 126
raw = np.fromfile("CPSL_TI_Radar_cpp/build/adc_data.bin", dtype=np.int16).reshape(-1, chirps, rx, samples, 2)
cube = (raw[..., 0] + 1j * raw[..., 1]).transpose(0, 2, 3, 1)   # (frame, rx, sample, chirp)
print(cube.shape)
```

`print(cube.shape)` shows the actual frame count. `reshape` fails if the file is not a whole number of frames. The cube's last three axes match `AdcFrame::data[rx][sample][chirp]`, which is what a live consumer sees ([tutorial 12](12_consume_frames.md)).

For range, Doppler and azimuth processing, use the notebook. It reads the radar `.cfg` to get the chirp structure, so give it both files, the cfg being the one the run used (from the repository root):

```bash
cd utilities
CFG_FILE=../CPSL_TI_Radar_cpp/config/radar/nav_configs/1843_stress_test.cfg \
ADC_DATA_FILE=../CPSL_TI_Radar_cpp/build/adc_data.bin \
uv run --group notebooks jupyter nbconvert --to html --execute process_adc_data.ipynb --output-dir ../CPSL_TI_Radar_cpp/build --output adc_report
```

The executed notebook, with its plots, lands in `CPSL_TI_Radar_cpp/build/adc_report.html` next to `adc_data.bin` (git ignores that folder); open it in any browser, e.g. `xdg-open ../CPSL_TI_Radar_cpp/build/adc_report.html`. The source notebook is not modified.

`process_raw_lbds_data.ipynb` decodes `LVDS_Raw_0.bin` (`output.save_raw_lvds`, for debugging packet loss).

## Several radars

One process per radar; run one per config, each in its own terminal:

```bash
./CPSL_TI_Radar_CPP ../config/system/front_radar_IWR1843_dca_RadVel_10Hz.json
./CPSL_TI_Radar_CPP ../config/system/back_radar_IWR1843_dca_RadVel_10Hz.json
```

Those two tracked configs show what must differ between radars:

| Setting | Why |
|---------|-----|
| `cli.port`, `serial_stream.port` | one board each (`/dev/ttyACM0,1` and `/dev/ttyACM2,3` in the example) |
| `dca1000.fpga_ip`, `cmd_port`, `data_port` | each DCA1000 needs its own address and ports; `host_ip` is your NIC's address |
| `output.dir` | otherwise both write `adc_data.bin` into the current directory |

The DCA1000's network address is programmed into its FPGA: to change it, see `DCA_Programming/README.md`. Pin each radar's two threads to different cores with `runtime.rx_cpu` / `worker_cpu` ([tutorial 1](01_build_and_host_setup.md)). USB port numbers can change across reboots; adding `--udev` to the `host_setup.py --apply` command writes udev rules with stable `/dev/radar/<serial>-cli` and `-data` names.

Next: [tutorial 4](04_troubleshooting.md).
