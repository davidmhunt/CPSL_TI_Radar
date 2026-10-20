# 7. Several radars on one host: ports, DCA1000 addresses, output folders

One driver process per radar, each with its own system JSON and terminal. Serial-only radars differ only in their ports. Several **DCA1000** cards also need different network addresses, because every card ships as `192.168.33.180` ports 4096 and 4098. Needs [tutorials 2](02_host_setup.md) and [5](05_driver_cli_and_adc.md).

```bash
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_RadVel_10Hz_front.json
CPSL_TI_Radar_cpp/build/CPSL_TI_Radar_CPP CPSL_TI_Radar_cpp/config/system/IWR1843_demo_RadVel_10Hz_back.json
```

Those two shipped configs show what must differ (copy and edit your own in `config/user/`):

| Setting | Why |
|---------|-----|
| `cli.port`, `serial_stream.port` | one board each; use `/dev/serial/by-id/...` or the `/dev/radar/<id>-cli` names from `host_setup.py --udev` ([tutorial 2](02_host_setup.md#stable-port-names)) |
| `dca1000.fpga_ip`, `cmd_port`, `data_port` | each card needs its own address and ports |
| `dca1000.host_ip` | your NIC's address on that card's subnet |
| `output.dir` | neither shipped config sets it: give each radar its own, or both write `adc_data.bin` into the launch folder |

Pin each radar's two threads to different cores with `runtime.rx_cpu` and `worker_cpu`. `host_setup.py` checks the default `192.168.33.30` only; for other addresses configure the NIC yourself.

## Give a DCA1000 its own address

A card's address lives in its FPGA configuration, set once with TI's DCA1000EVM CLI (source in `DCA_Programming/`; full guide: [`DCA_Programming/README.md`](../../DCA_Programming/README.md)). One card at a time on the wire:

1. Set the card's switch **SW2.6** to pin 11 (default FPGA settings), power-cycle it, and give the host NIC `192.168.33.30/24`.
2. Build the CLI and edit a JSON. `ethernetConfigUpdate` holds the new `systemIPAddress`, `DCA1000IPAddress`, MAC (unique per card) and ports; `eeprom_config_change_from_orig.json` is an example.

```bash
cd DCA_Programming/SourceCode && make && cd Release
export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:$PWD            # if it reports libRF_API.so missing
./DCA1000EVM_CLI_Control fpga_version ../eeprom_config_change_from_orig.json   # the card answers
./DCA1000EVM_CLI_Control eeprom ../eeprom_config_change_from_orig.json         # program it
```

`eeprom` prints `EEPROM Configuration command: Success`. Then power the card off, set SW2.6 to pin 6 (use the saved address), power it on, and set the host NIC to the new `systemIPAddress`. `eeprom_config_revert_to_orig.json` programs the defaults back.

Rules of thumb from the lab (README in `DCA_Programming/`): cards on **separate NICs** (a second USB Ethernet adapter) need different third octets (`192.168.XX.YY`) because the netmask is `255.255.255.0`; cards behind **one switch** share the host address but need different card addresses, ports and MACs.

If packets drop with several radars running, read `--stats` with [tutorial 8](08_troubleshooting.md).
