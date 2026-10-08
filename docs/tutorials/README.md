# Tutorials

Short, copy-pasteable lessons. Do 1 to 5 in order to install the repo and use it with a radar; 10 to 14 are for changing the driver. Reference detail lives in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and `CPSL_TI_Radar_cpp/Readme.md`.

## Using the repo

1. [Install: build, test, host setup, Docker](01_install.md)
2. [First run with the GUI](02_first_run_gui.md) (demo mode needs no hardware)
3. [First run with the driver CLI: system config, `--validate`, serial or DCA1000](03_first_run_driver_cli.md)
4. [Recording ADC data: capture, read `adc_data.bin`, several radars](04_recording_adc.md)
5. [Troubleshooting: messages, `stats v1`, dropped packets](05_troubleshooting.md)

## Extending the driver

10. [Code map](10_code_map.md)
11. [Add a board, add a TLV type](11_add_a_board_and_tlv_type.md)
12. [Consume frames in your own program](12_consume_frames.md)
13. [Write a test, measure performance](13_tests_and_performance.md)
14. [Bench validation: check a board against the reference numbers](14_bench_validation.md)

## Terms

- **TLV**: the demo firmware's serial packet format (type-length-value); it carries the detected points.
- **cfg vs system JSON**: a `.cfg` is TI's chirp configuration sent to the radar; a system JSON tells the driver which board, firmware, `.cfg`, ports and outputs to use.
- **SOP mode / boot modes**: switches that set whether the board boots its firmware (functional) or accepts a flash (flashing); the diagrams are in [`../images/boot_modes/`](../images/boot_modes/).
- **`lvdsStreamCfg`**: the `.cfg` line that makes the radar send raw ADC samples over its LVDS pins to the DCA1000.
- **DCA1000**: TI's capture card; it receives LVDS and forwards raw ADC to the host over UDP at `192.168.33.180`.
- **`rmem_max`**: the kernel limit on a UDP socket's receive buffer; too low and packets drop.
- **firmware id**: the `"firmware"` key (`demo`, `dca1000_raw`, `iwr1843_sar_lvds`, `cascade_ddm`) naming the image on the board.
