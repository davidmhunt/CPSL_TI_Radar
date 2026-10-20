# DCA1000 and the host firewall

## Symptom

The driver stops with `DCA1000 did not answer SYSTEM_CONNECT` (tutorial 8, `device_error`), although the card is powered, `ip neigh` / ARP resolves `192.168.33.180`, and the same card works on another machine.

## Why

The DCA1000 answers from UDP source port 1024 to host port 4096. A stateful firewall with default-deny inbound (ufw's default) does not match that to the command the host sent, so it does not treat it as a reply and drops it silently. Seen on the rover host (2026-10-12, NIC `igc`): a pcap showed the reply on the wire, but the driver never received it.

## Check

```bash
uv run tools/setup/host_setup.py --nic <dca-nic>     # the "firewall" line: OK / WARN / MISSING / N-A
sudo ufw status verbose                              # ufw: look for an allow from 192.168.33.180
```

`/etc/ufw/user.rules` is readable only by root, so without root the tool reports `WARN ... cannot verify DCA1000 rule without root`. That is not a failure; use `sudo ufw status verbose` to confirm. `N-A` means ufw is absent or inactive.

Other firewalls (the tool does not check these; commands below are not bench-tested):

```bash
sudo firewall-cmd --get-active-zones && sudo firewall-cmd --list-all   # firewalld
sudo nft list ruleset                                                  # raw nftables
```

## Fix

```bash
uv run tools/setup/host_setup.py --nic <dca-nic> --apply    # asks once, calls sudo itself
sudo ufw allow in on <dca-nic> from 192.168.33.180 comment 'DCA1000'   # the same, by hand
```

Re-running is harmless; ufw skips a rule that already exists. For a card at another address pass `--fpga-ip`.

firewalld (not bench-tested): put the NIC in the trusted zone, `sudo firewall-cmd --permanent --zone=trusted --add-interface=<dca-nic>`, or add a rich rule, `sudo firewall-cmd --permanent --add-rich-rule='rule family=ipv4 source address=192.168.33.180 accept'`, then `sudo firewall-cmd --reload`.

## Verify

Re-run a SAR or LVDS session; the `SYSTEM_CONNECT` error should be gone. To diagnose without changing anything:

```bash
grep -E '^(Ip|Udp):' /proc/net/snmp      # run before and after a start
sudo tcpdump -ni <dca-nic> host 192.168.33.180
```

`Ip InReceives` rising while `Udp InDatagrams` does not means the firewall dropped the packets; tcpdump showing the reply (from port 1024) means it reached the NIC.

## Undo

```bash
sudo ufw delete allow in on <dca-nic> from 192.168.33.180
```
