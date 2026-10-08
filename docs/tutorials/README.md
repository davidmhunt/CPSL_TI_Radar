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
