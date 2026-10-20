# Tutorials

Short, copy-pasteable lessons for a new lab member on a fresh Ubuntu. Do 0 to 5 in order to install the repo and use it with a radar; 6 to 8 when you need them. To change the driver, use the developer guide. Reference detail lives in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) and [`CPSL_TI_Radar_cpp/Readme.md`](../../CPSL_TI_Radar_cpp/Readme.md).

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

See the [developer guide](../developer/README.md): code map, adding a board or TLV type, consuming frames, tests and performance, bench validation, the config tree and migration, and the notes on TI's sources.
