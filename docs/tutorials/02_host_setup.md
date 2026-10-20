# 2. Host setup: serial access, the DCA1000 network, stable port names

The one place these host settings are described; the other tutorials link here. Needs [tutorial 1](01_install.md). A serial-only run (point cloud) needs just the first row; a DCA1000 run needs all of them. The settings belong to the host, not the repo, so any container shares them.

| Need | Why | Manual fix |
|---|---|---|
| your user in the serial device's group (`dialout`; `plugdev` on some hosts: `stat -L -c %G /dev/ttyACM0` with a board attached) | read the radar's `/dev/ttyACM*` | `sudo usermod -a -G <group> $USER`, then log out and in |
| DCA1000 NIC at `192.168.33.30/24` | the card is `192.168.33.180` | static IPv4 address on the wired NIC |
| `net.core.rmem_max` >= `dca1000.rcvbuf_bytes` | the kernel caps the UDP receive buffer; too small and packets drop | `sudo sysctl -w net.core.rmem_max=134217728` |
| an allow rule for the card if `ufw` is active | the card's replies look unrelated to the host's commands and are dropped | `sudo ufw allow in on <dca-nic> from 192.168.33.180` |

## Let the tool do it

`tools/setup/host_setup.py` checks all four and applies the same fixes, so use it or the manual column, not both. Run it without `--nic` first: it checks everything else and lists the wired interfaces. `<dca-nic>` is the one cabled to the DCA1000 (it is never auto-picked, e.g. `enp3s0`; `ip -br link` lists yours).

```bash
uv run tools/setup/host_setup.py                                    # list candidate NICs, check the rest
uv run tools/setup/host_setup.py --nic <dca-nic>                    # report: OK / MISSING / WARN, exit 1 if any MISSING
uv run tools/setup/host_setup.py --nic <dca-nic> --apply --dry-run  # print the exact commands, run nothing
uv run tools/setup/host_setup.py --nic <dca-nic> --apply            # run them
```

Do not put `sudo` in front: the tool calls `sudo` itself, one confirmation per fix. You should see one line per check; after `--apply` the re-check shows `OK`. Without root, the firewall line is `WARN ... cannot verify`, which is not a failure: confirm with `sudo ufw status verbose`. More on firewalls and undoing the rule: [`docs/hardware/dca1000_firewall.md`](../hardware/dca1000_firewall.md).

`--apply` adds `192.168.33.30/24` to the NIC's NetworkManager profile (keeping its other addresses). If the NIC is not managed by NetworkManager, it prints the manual `nmcli` command instead. `--fpga-ip` checks another card address.

## Stable port names

`/dev/ttyACM*` numbers change between boots and with several boards. Either use the `/dev/serial/by-id/...` paths (`ls /dev/serial/by-id`; `-if00` is the CLI port, `-if03` the data port) or add `--udev`:

```bash
uv run tools/setup/host_setup.py --udev --apply
```

It writes `/etc/udev/rules.d/99-radar.rules` so every XDS110 and CP2105 board gets `/dev/radar/<id>-cli` and `/dev/radar/<id>-data`. `<id>` is the board's USB serial, or its USB port path (for example `1-2.3`) when another connected board reports the same serial. `--json` lists each board's `id`.

## On a loaded host

Pin the driver's two threads to cores your own pipeline does not use with `runtime.rx_cpu` and `runtime.worker_cpu` in the system JSON (driver reference [`CPSL_TI_Radar_cpp/Readme.md`](../../CPSL_TI_Radar_cpp/Readme.md), "Choosing CPUs").

Next: [tutorial 3, flash a radar](03_flash_a_radar.md).
