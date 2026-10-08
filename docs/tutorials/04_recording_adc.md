# 4. Recording ADC data: capture, read `adc_data.bin`, run several radars

Needs a board running the demo firmware with a DCA1000 cabled, and the host set up ([tutorial 1](01_install.md)). To record from the GUI instead, tick **Save ADC frames** in the Radar tab ([tutorial 2](02_first_run_gui.md)); the file lands in the run folder `runs/gui/<UTC>_<name>/adc_data.bin`.

## Capture from the CLI

Copy the DCA1000 example config into `config/user/`, then edit the copy ([tutorial 3](03_first_run_driver_cli.md) shows how to find ports; the serial demo config there writes no `adc_data.bin`):

```bash
cp CPSL_TI_Radar_cpp/config/system/IWR1843_demo_stress_test_front.json CPSL_TI_Radar_cpp/config/user/my_1843_dca.json
```

In `my_1843_dca.json` set `cli.port`; leave `serial_stream.enabled` false; check `dca1000.host_ip` is your NIC's address (`192.168.33.30`) and `dca1000.fpga_ip` your DCA1000's (`192.168.33.180`); and add an output folder so captures stay out of the repo root, `"output": {"save_adc_frames": true, "save_raw_lvds": false, "dir": "../../../runs/cli"}` (relative to the JSON file, created for you; unset, the file lands in the launch folder). Then run, with `--stats` so you can watch for drops:

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/user/my_1843_dca.json --frames 20 --stats
```

N = 20 is below the cfg's `numFrames` 30, so the driver ends the run, not the radar.

The file has no header: per frame, for chirp, for rx, for sample, an int16 real part then an int16 imaginary part, little-endian. Lost packets stay as zeros, so after a clean stop the size is a whole multiple of `bytes/frame` (printed by `--validate`; 504000 for this config). Anything else means a killed process.

```bash
stat -c %s runs/cli/adc_data.bin     # a whole multiple of 504000, at least 20 frames
```

## Read it

Take rx, samples and chirps from the `frame:` line of `--validate` (this config: 4 rx x 250 samples x 126 chirps):

```python
import numpy as np
rx, samples, chirps = 4, 250, 126
raw = np.fromfile("runs/cli/adc_data.bin", dtype=np.int16).reshape(-1, chirps, rx, samples, 2)
cube = (raw[..., 0] + 1j * raw[..., 1]).transpose(0, 2, 3, 1)   # (frame, rx, sample, chirp)
print(cube.shape)
```

`reshape` fails if the file is not a whole number of frames. The cube's last three axes match `AdcFrame::data[rx][sample][chirp]`, which a live consumer sees ([tutorial 12](12_consume_frames.md)).

For range, Doppler and azimuth processing use the notebook. It reads the radar `.cfg` for the chirp structure, so give it both files, the cfg being the one the run used:

```bash
cd utilities
CFG_FILE=../CPSL_TI_Radar_cpp/config/radar/IWR1843/demo/stress_test.cfg \
ADC_DATA_FILE=../runs/cli/adc_data.bin \
uv run --group notebooks jupyter nbconvert --to html --execute process_adc_data.ipynb --output-dir ../runs/cli --output adc_report
```

The executed notebook lands in `runs/cli/adc_report.html`; open it in a browser. A 2-frame real capture to try the notebook on without a board is `tests/fixtures/adc/iwr1843_bench_dca_2frames.bin` with `tests/fixtures/adc/bench_1843_dca.cfg` (4 rx x 128 samples x 256 chirps).

`utilities/process_raw_lbds_data.ipynb` decodes `LVDS_Raw_0.bin` (`output.save_raw_lvds`, for debugging packet loss), and `utilities/test_ethernet_traffic.ipynb` helps debug the DCA1000 network link.

## Several radars

One process per radar, each with its own config and terminal:

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_RadVel_10Hz_front.json
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_RadVel_10Hz_back.json
```

Those two shipped configs show what must differ between radars:

| Setting | Why |
|---------|-----|
| `cli.port`, `serial_stream.port` | one board each (`/dev/ttyACM0,1` and `/dev/ttyACM2,3` in the example) |
| `dca1000.fpga_ip`, `cmd_port`, `data_port` | each DCA1000 needs its own address and ports; `host_ip` is your NIC's address |
| `output.dir` | otherwise both write `adc_data.bin` into the launch folder |

The DCA1000's network address is programmed into its FPGA: to change it, see [`DCA_Programming/README.md`](../../DCA_Programming/README.md). Pin each radar's two threads to different cores with `runtime.rx_cpu` / `worker_cpu`. USB port numbers can change across reboots; `host_setup.py --udev` gives stable port names ([tutorial 1](01_install.md)).

If packets drop, run again with `--stats` and read the counters with [tutorial 5](05_troubleshooting.md).
