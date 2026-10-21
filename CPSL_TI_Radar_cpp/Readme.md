# CPSL_TI_Radar_cpp

The C++17 driver: it configures a TI mmWave radar over its CLI serial port and streams raw ADC data (DCA1000, UDP) or the on-chip demo's TLV point cloud (serial). It builds to the `CPSL_TI_Radar_CPP` command-line program and a library other CMake projects can link.

Where to look:

- Prerequisites, cloning and building: [tutorial 1](../docs/tutorials/01_install.md).
- Serial ports, the DCA1000 network address, `net.core.rmem_max` and real-time priority: [tutorial 2](../docs/tutorials/02_host_setup.md) and [`docs/docker.md`](../docs/docker.md).
- Flashing the board: [tutorial 3](../docs/tutorials/03_flash_a_radar.md).
- Running the CLI against a system config, and reading the ADC output: [tutorial 5](../docs/tutorials/05_driver_cli_and_adc.md).
- System configs, board and firmware descriptors, radar `.cfg` files: [`config/README.md`](config/README.md) and [`config/boards/README.md`](config/boards/README.md).
- Design, config schema and migration from v1: [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md), [`docs/developer/config_and_migration.md`](../docs/developer/config_and_migration.md), [`docs/migration_v1_to_v2.md`](../docs/migration_v1_to_v2.md).
- Consuming frames from your own code, tests and the replay benchmark: [`docs/developer/consume_frames.md`](../docs/developer/consume_frames.md), [`docs/developer/tests_and_performance.md`](../docs/developer/tests_and_performance.md).
