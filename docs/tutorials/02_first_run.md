# 2. First run: system config, `--validate`, serial or DCA1000

You will check a config without hardware, then run it. Needs [tutorial 1](01_build_and_host_setup.md) done. Commands run from `CPSL_TI_Radar_cpp/build`:

```bash
cd CPSL_TI_Radar_cpp/build
```

## What a run is made of

A **system config** (`config/system/*.json`) names three things: a **board descriptor** (`config/boards/<board>.json`: the board's serial handshake, TLV format and LVDS layout), a **radar `.cfg`** (the TI chirp configuration, `config/radar/`), and the lab-specific parts: ports, IPs, output folder. Paths inside a system config are relative to that file. The field table is in `CPSL_TI_Radar_cpp/Readme.md` ("Updating the .json config files"). Loading is strict: an unknown key or wrong type is an error naming the JSON path.

## Check it without hardware

```bash
./CPSL_TI_Radar_CPP ../config/system/radar_0_IWR1843_demo.json --validate
```

It opens no port or socket. It prints the board, ports, `frame:` shape, `bytes/frame:` and the cfg commands it will skip (`calibData` on the IWR1843: the flashed firmware rejects it, harmless), and exits 0 after `OK:`. A config that fails prints why and exits 1. Run it on every config before taking it to a bench.

## Serial point cloud or DCA1000 raw ADC

| | Serial TLV (`serial_stream`) | DCA1000 (`dca1000`) |
|---|---|---|
| You get | detected points: x, y, z, v, SNR | the raw ADC cube, `adc_data.bin` |
| Needs | the board's demo firmware, USB | DCA1000 on LVDS and Ethernet, host settings from tutorial 1 |
| Switch | `"serial_stream": {"enabled": true, "port": ...}` | `"dca1000": {"enabled": true, ...}` plus the radar `.cfg` `lvdsStreamCfg` line |
| Example | `radar_0_IWR1843_demo.json` | `front_radar_IWR1843_stress_test.json` |

Enable one or both; at least one is required. Which `Point` fields are filled depends on the board's TLV dialect (`config/boards/README.md`, "TLV dialects"): the IWR1443 sends no velocity or SNR, so those are NaN. The cascade (`radar_0_AWR2243_cascade_serial.json`) is serial only, and its demo accepts a cfg **once per power-up**: power-cycle the EVM before every run.

## Run

Edit `cli.port` (and `serial_stream.port`) in your config to your board's ports: `utilities/determine_serial_ports.ipynb` lists them, and the lower-numbered `/dev/ttyACM*` is the CLI. Power the board in functional mode (`bench_validation.md` section 2 shows the switches), then:

```bash
./CPSL_TI_Radar_CPP ../config/system/radar_0_IWR1843_demo.json --frames 100 --stats
```

Serial runs print one line per frame, `TLV frame <n>: <k> detected points`. DCA1000 runs print nothing per frame; `--stats` prints one `stats v1 ...` line per stream every second (columns in [tutorial 4](04_troubleshooting.md)). A DCA1000 run with `output.save_adc_frames` true writes `adc_data.bin` in `output.dir`; if that key is unset the file lands in the current directory.

The run ends after `--frames N` frames, `--duration S` seconds, on Ctrl-C, or when no frame arrives for 2 s. Ctrl-C is a clean stop: the driver sends `sensorStop`, stops the DCA1000 and flushes the files. Press it once. Exit status 0 means a clean stop.

To check a board against reference numbers, use [`bench_validation.md`](bench_validation.md).

Next: [tutorial 3](03_adc_data_and_multiple_radars.md).
