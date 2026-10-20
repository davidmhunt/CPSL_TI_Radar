# Tutorials

Short, copy-pasteable lessons for a new lab member on a fresh Ubuntu. Do 0 to 5 in order to install the repo and use it with a radar; 6 to 8 when you need them. 10 to 14 are for changing the driver. Reference detail lives in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`CPSL_TI_Radar_cpp/Readme.md`](../../CPSL_TI_Radar_cpp/Readme.md).

## Using the repo

0. [Before you start](00_before_you_start.md): the boards, the DCA1000, cables, and a glossary (no commands)
1. [Install](01_install.md): packages, `uv`, build, tests, demo GUI
2. [Host setup](02_host_setup.md): serial group, DCA1000 network, firewall, stable port names
3. [Flash a radar](03_flash_a_radar.md): which image for which board, UniFlash
4. [First run with the GUI](04_first_run_gui.md)
5. [Driver CLI and recording ADC](05_driver_cli_and_adc.md)
6. [Run the radar in ROS 2](06_ros2.md)
7. [Several radars](07_several_radars.md): ports, DCA1000 addresses
8. [Troubleshooting](08_troubleshooting.md): messages, `stats v1`, dropped packets

## Extending the driver

10. [Code map](10_code_map.md)
11. [Add a board, add a TLV type](11_add_a_board_and_tlv_type.md)
12. [Consume frames in your own program](12_consume_frames.md)
13. [Write a test, measure performance](13_tests_and_performance.md)
14. [Bench validation: check a board against the reference numbers](14_bench_validation.md)
