# 3. Read `adc_data.bin`, run several radars

## Read a capture

Set `"output": {"dir": "out/front", "save_adc_frames": true}` in the system config (the dir is relative to the JSON file and is created for you). Every completed frame is appended to `<dir>/adc_data.bin`, including frames your program never took. The file has no header: per frame, for chirp, for rx, for sample, an int16 real part then an int16 imaginary part, little-endian. Lost packets stay in the file as zeros, so the size is exactly `bytes/frame` (from `--validate`) times the frame count after a clean stop. Anything else means a killed process or the wrong frame shape:

```bash
stat -c %s out/front/adc_data.bin        # expect bytes/frame x frames
```

Load it in NumPy. Take rx, samples and chirps from the `frame:` line of `--validate` (for the stress-test config: 4 rx x 250 samples x 126 chirps):

```python
import numpy as np
rx, samples, chirps = 4, 250, 126
raw = np.fromfile("adc_data.bin", dtype=np.int16).reshape(-1, chirps, rx, samples, 2)
cube = (raw[..., 0] + 1j * raw[..., 1]).transpose(0, 2, 3, 1)   # (frame, rx, sample, chirp)
print(cube.shape)
```

`reshape` fails if the file is not a whole number of frames: re-check the three numbers against `--validate` first. The cube's last three axes match `AdcFrame::data[rx][sample][chirp]`, which is what a live consumer sees ([tutorial 12](12_consume_frames.md)).

For range, Doppler and azimuth processing, use the notebook. It reads the radar `.cfg` to get the chirp structure, so give it both files (from the repository root):

```bash
cd utilities
CFG_FILE=../CPSL_TI_Radar_cpp/config/radar/nav_configs/1843_stress_test_baseline_numframes0.cfg \
ADC_DATA_FILE=/path/to/adc_data.bin \
uv run --group notebooks jupyter nbconvert --to notebook --execute process_adc_data.ipynb --output /tmp/out.ipynb
```

Or open it with `uv run --group notebooks jupyter lab`. `process_raw_lbds_data.ipynb` decodes `LVDS_Raw_0.bin` (`output.save_raw_lvds`, only for debugging packet loss). The layout is in `docs/ARCHITECTURE.md` ("Output files").

## Several radars

The driver is one process per radar. The processes are independent: run one per config, each in its own terminal:

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

The DCA1000's network address is programmed into its FPGA: to change it, see `DCA_Programming/README.md`. Check each config with `--validate` first, then give each radar enough CPU: pin its two threads to different cores with `runtime.rx_cpu` / `worker_cpu` ([tutorial 1](01_build_and_host_setup.md)). USB port numbers can change across reboots; adding `--udev` to the `host_setup.py --apply` command writes udev rules with stable `/dev/radar/<serial>-cli` and `-data` names.

Next: [tutorial 4](04_troubleshooting.md).
