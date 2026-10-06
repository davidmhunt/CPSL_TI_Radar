# Tutorials

Short, copy-pasteable lessons for a new lab member. Do the first four in order to use the driver; the last four to change it. Reference detail lives in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and `CPSL_TI_Radar_cpp/Readme.md`.

## Using the driver

1. [Build, test, host setup](01_build_and_host_setup.md)
2. [First run: system config, `--validate`, serial or DCA1000](02_first_run.md)
3. [Read `adc_data.bin`, run several radars](03_adc_data_and_multiple_radars.md)
4. [Troubleshooting: messages, `stats v1`, drops](04_troubleshooting.md)

Also: [`rebuild_driver.md`](rebuild_driver.md) (repeatable rebuild runbook) and [`bench_validation.md`](bench_validation.md) (check a board against the reference numbers).

## Extending the driver

10. [Code map](10_code_map.md)
11. [Add a board, add a TLV type](11_add_a_board_and_tlv_type.md)
12. [Consume frames in your own program](12_consume_frames.md)
13. [Write a test, measure performance](13_tests_and_performance.md)
