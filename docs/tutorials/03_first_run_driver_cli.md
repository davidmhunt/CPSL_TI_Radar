# 3. First run with the driver CLI: system config, `--validate`, serial or DCA1000

Check a config without hardware, then run it. Needs [tutorial 1](01_install.md). Run from the repository root; the executable is `CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP` (`--help` lists every flag).

## What a run is made of

A **system config** (`CPSL_TI_Radar_cpp/config/system/<BOARD>_<fw>_<purpose>[_<mount>].json`, 40 shipped) names:

- a **board** (`"board": "IWR1843"`, a descriptor in `config/boards/`: the serial handshake, TLV format and LVDS layout);
- the **firmware** the board runs (`"firmware": "demo"`, a descriptor in `config/firmware/`; required, and it must match the image on the board);
- a **radar `.cfg`** (`"radar_cfg"`, the TI chirp configuration, in `config/radar/<BOARD>/<firmware>/`);
- the lab-specific parts: ports, IPs, output folder.

Paths inside a system config are relative to that file. Loading is strict: an unknown key or wrong type is an error naming the JSON path. Field list: `CPSL_TI_Radar_cpp/Readme.md` ("Updating the .json config files"); file index: `CPSL_TI_Radar_cpp/config/README.md`. Shipped configs hold the lab's own ports and IPs, so **copy one into `CPSL_TI_Radar_cpp/config/user/`** (gitignored; the GUI saves there too) and edit the copy. The relative paths still resolve from there.

## Check it without hardware

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_tlv_default.json --validate
```

It opens no port or socket. It prints the board, ports, `frame:` shape, `bytes/frame:` and the cfg commands it will skip (none on the shipped boards), and exits 0 after `OK:`; a bad config prints why and exits 1. A v1-format config exits 1 and names the converter (`uv run tools/migrate_config_v1_to_v2.py <file>`; `--add-firmware --in-place` adds a missing `firmware` key).

## Serial point cloud or DCA1000 raw ADC

| | Serial TLV (`serial_stream`) | DCA1000 (`dca1000`) |
|---|---|---|
| You get | detected points: x, y, z, v, SNR | the raw ADC cube, `adc_data.bin` |
| Needs | the board's demo firmware, USB | DCA1000 on LVDS and Ethernet, host settings from tutorial 1 |
| Switch | `"serial_stream": {"enabled": true, "port": ...}` | `"dca1000": {"enabled": true, ...}` plus the radar `.cfg` `lvdsStreamCfg` line |
| Example | `IWR1843_demo_tlv_default.json` | `IWR1843_demo_stress_test_front.json` |

Enable one or both; at least one is required. Which `Point` fields are filled depends on the board's TLV dialect (`config/boards/README.md`): the IWR1443 sends no velocity or SNR, so those are NaN. The cascade (`AWR2243_CASCADE_cascade_ddm_shortrange.json`) is serial only and accepts a cfg **once per power-up**: power-cycle the EVM before every run.

## Run

Make your copy and set the ports. `ls /dev/serial/by-id` and the GUI Devices tab list them; the lower-numbered `/dev/ttyACM*` is the CLI port.

```bash
cp CPSL_TI_Radar_cpp/config/system/IWR1843_demo_tlv_default.json CPSL_TI_Radar_cpp/config/user/my_1843.json
```

Edit `my_1843.json`: `cli.port` (the CLI port) and `serial_stream.port` (the data port). Check with `--validate` (the same command as above on your copy). Power the board in functional mode (SOP switches: [`14_bench_validation.md`](14_bench_validation.md) section 2), then:

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/user/my_1843.json --frames 100 --stats
```

Serial runs print one line per frame, `TLV frame <n>: <k> detected points`. DCA1000 runs print nothing per frame; `--stats` prints one `stats v1 ...` line per stream every second (columns in [tutorial 5](05_troubleshooting.md)).

The run ends after `--frames N` frames, `--duration S` seconds, on Ctrl-C, or when no frame arrives for 2 s. Press Ctrl-C once: it is a clean stop (`sensorStop`, DCA1000 stopped, files flushed), exit status 0. `--skip-configure` sends no cfg, for a board already streaming this power-up.

Next: [tutorial 4, recording ADC data](04_recording_adc.md).
