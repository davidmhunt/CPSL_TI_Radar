# 5. Driver CLI and recording ADC: system config, `--validate`, `adc_data.bin`

Check a config without hardware, run it, and record raw ADC data. Needs [tutorial 1](01_install.md); a board run also needs [2](02_host_setup.md) and [3](03_flash_a_radar.md). Run from the repository root; the executable is `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` (`--help` lists every flag).

## What a run is made of

A **system config** (`CPSL_TI_Radar_cpp/config/system/<BOARD>_<fw>_<purpose>[_<mount>].json`) names a **board** (a descriptor in `config/boards/`), the **firmware** on it (`"firmware"`, must match the flashed image), a radar **`.cfg`** (`"radar_cfg"`, in `config/radar/<BOARD>/<firmware>/`) and the lab-specific parts: ports, IPs, output folder. Paths inside are relative to that file. Loading is strict: an unknown key or wrong type is an error naming the JSON path. Keys: [`CPSL_TI_Radar_cpp/Readme.md`](../../CPSL_TI_Radar_cpp/Readme.md); file index: [`config/README.md`](../../CPSL_TI_Radar_cpp/config/README.md).

The shipped configs hold the lab's own ports and IPs, so **copy one into `CPSL_TI_Radar_cpp/config/user/`** (gitignored; the GUI saves there too) and edit the copy; the relative paths still resolve.

| | Serial point cloud (`serial_stream`) | Raw ADC (`dca1000`) |
|---|---|---|
| Needs | the board's demo firmware, USB | DCA1000 on LVDS and Ethernet, [tutorial 2](02_host_setup.md), a cfg with `lvdsStreamCfg` |
| Example | `IWR1843_demo_tlv_default.json` | `IWR1843_demo_stress_test_front.json` |

Enable one or both (`"enabled": true`). The cascade (`AWR2243_CASCADE_cascade_ddm_shortrange.json`) is serial only and takes a cfg **once per power-up**: power-cycle it before every run.

## Check it without hardware

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_tlv_default.json --validate
```

It opens no port or socket, prints the board, ports, `frame:` shape and `bytes/frame:`, and ends with `OK: <file>` (exit 0); a bad config prints why and exits 1.

## Run a serial point cloud

```bash
cp CPSL_TI_Radar_cpp/config/system/IWR1843_demo_tlv_default.json CPSL_TI_Radar_cpp/config/user/my_1843.json
```

Edit `cli.port` and `serial_stream.port` (which is which: [tutorial 2](02_host_setup.md#which-port-is-the-cli-which-the-data-port)). Run `--validate` on the copy, put the board in functional mode, then:

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/user/my_1843.json --frames 100 --stats
```

With a radar streaming you should see one `TLV frame <n>: <k> detected points` line per frame and a `stats v1 serial ...` line every second ([tutorial 8](08_troubleshooting.md) reads them). The run ends after `--frames N`, `--duration S`, Ctrl-C (one press is a clean stop, exit 0) or when no frame arrives for 2 s. `--skip-configure` sends no cfg, for a board already streaming this power-up. `error: cannot open the CLI port` with a permission message: log out and in after the group change ([tutorial 2](02_host_setup.md)); other causes: [tutorial 8](08_troubleshooting.md).

## Record raw ADC data

Copy the DCA1000 example and edit the copy:

```bash
cp CPSL_TI_Radar_cpp/config/system/IWR1843_demo_stress_test_front.json CPSL_TI_Radar_cpp/config/user/my_1843_dca.json
```

The keys a DCA1000 run needs: `board`, `firmware`, `radar_cfg` (a cfg with `lvdsStreamCfg`), `cli.port`, `dca1000.enabled` with `host_ip` (your NIC, `192.168.33.30`) and `fpga_ip` (the card, `192.168.33.180`), `cmd_port` 4096 and `data_port` 4098, and `output.save_adc_frames`. Leave `serial_stream.enabled` false. Add the output folder, relative to the JSON file (created if missing; unset, the file lands in the launch folder): `"output": {"save_adc_frames": true, "save_raw_lvds": false, "dir": "../../../runs/cli"}`.

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/user/my_1843_dca.json --frames 20 --stats
stat -c %s runs/cli/adc_data.bin     # a whole multiple of 504000 (bytes/frame from --validate)
```

`save_adc_frames` writes `adc_data.bin`; `save_raw_lvds` writes `LVDS_Raw_0.bin`, the raw LVDS stream, for debugging packet loss. A size that is not a whole number of frames means a killed process. The GUI records the same file when you tick **Save ADC frames** ([tutorial 4](04_first_run_gui.md)), into `runs/gui/<UTC>_<name>/`.

The file has no header: per frame, for chirp, for rx, for sample, an int16 real part then an int16 imaginary part, little-endian. Lost packets stay as zeros. Take rx, samples and chirps from the `frame:` line (here 4 x 250 x 126). Why the chirp axis moves in the last line: [`docs/raw_data/README.md`](../raw_data/README.md) section 7.

```python
import numpy as np
rx, samples, chirps = 4, 250, 126
raw = np.fromfile("runs/cli/adc_data.bin", dtype=np.int16).reshape(-1, chirps, rx, samples, 2)
cube = (raw[..., 0] + 1j * raw[..., 1]).transpose(0, 2, 3, 1)   # (frame, rx, sample, chirp)
```

For range, Doppler and azimuth, `utilities/process_adc_data.ipynb` reads this file plus the `.cfg` the run used (`CFG_FILE`, `ADC_DATA_FILE`; run it with `uv run --group notebooks jupyter`). `tests/fixtures/adc/iwr1843_bench_dca_2frames.bin` with `bench_1843_dca.cfg` is a 2-frame capture to try it on.

Next: [tutorial 6, ROS 2](06_ros2.md); for several DCA1000s, [tutorial 7](07_several_radars.md).
