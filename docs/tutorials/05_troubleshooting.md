# 5. Troubleshooting: messages, `stats v1`, drops

The executable prints each failure as `error: <message>` and exits 1 (2 for a bad command line). `runtime.log_level: "debug"` shows every CLI command and reply.

In the GUI, the same text is in the run's `driver.log` (Logs tab) and the Radar tab cards show the counters below. **If the DCA1000 drops packets, go straight to [Reading `--stats`](#reading---stats).** Host-side causes (receive buffer, NIC, CPU pinning) are set up in [tutorial 1](01_install.md); thresholds are in [`14_bench_validation.md`](14_bench_validation.md) section 7.

## It failed before or at start

| Message (code) | Meaning and fix |
|---|---|
| `cannot open the CLI port ...` / `... serial data port ...` (`open_failed`) | Wrong port, board not powered, or you are not in `dialout`. Check `ls /dev/ttyACM*` and `ls /dev/serial/by-id` (or the GUI Devices tab). |
| `cannot open the DCA1000 sockets ...` (`open_failed`) | The host NIC does not have `dca1000.host_ip`, or another process holds the ports. `host_setup.py` checks the address. |
| `DCA1000 did not answer ...` (`device_error`) | The capture card is unpowered, unplugged, or on another subnet. |
| `not every config command was acknowledged with 'Done'` (`config_rejected`) | A cfg command got no `Done`: an older IWR1843 image rejects `calibData` (skip it with `board_overrides`); otherwise the firmware does not know the command, or the board is in flashing mode or wrong firmware. |
| `... can only be configured once per boot: power-cycle the EVM` (`config_rejected`) | Cascade board: power-cycle (12 V off and on) before **every** run. |
| `no frame for 2 s, stopping` | Configured and started, but no data arrived. DCA1000: check the `.cfg` has `lvdsStreamCfg`, the LVDS cable, and that `--stats` shows `packets` rising. Serial: the data port, `data_uart` baud, and that the firmware matches the board's `tlv_dialect`. |
| `sensorStop was not acknowledged` (warning) | The demo answers only after the current frame. Harmless if the exit status is 0. |
| `could not set SCHED_RR` (warning) | Your config sets `runtime.rx_priority` or `worker_priority` and the process lacks `cap_sys_nice` or an `rtprio` limit. Remove the key (the default 0 needs neither) or grant it (Readme). |

## Reading `--stats`

One line per stream per second, cumulative since start, and one more after the stop:

```
stats v1 dca t=<s> frames=<n> packets=<n> dropped=<n> drop_events=<n> late=<n> duplicate=<n> incomplete=<n> skipped=<n> overrun=<n> overwritten=<n> stalls=<n> rcvbuf=<bytes> kernel_drops=<n> ring_full=<n> implausible=<n> resyncs=<n>
stats v1 serial t=<s> frames=<n> missed=<n> overwritten=<n> stalls=<n>
```

A healthy DCA run has `dropped`, `kernel_drops`, `resyncs` and `implausible` at 0 and `frames` rising at the frame rate. When not:

| You see | Meaning | Fix |
|---|---|---|
| `kernel_drops` > 0 | The socket buffer overflowed: the consumer or worker stalled longer than `rcvbuf` holds. `ring_full` > 0 says the driver's own ring filled first. | Check `rcvbuf=` (134217728 expected; a low `rmem_max` lowers it), CPU load, a slow consumer; pin the threads. |
| `dropped` > 0, `kernel_drops` = 0 | Lost before the host socket: NIC, cable or the DCA1000 (no retransmission). `drop_events` counts the bursts, `incomplete` the frames zero-filled. | `ethtool -S <dca-nic>` for rx drops; check link speed and cable. |
| `resyncs` > 0 (`implausible` alone is harmless) | The DCA1000 restarted its byte count mid-capture (power glitch, a second tool sending `recordStart`), or sent a corrupt header. | The frames open at that moment are dropped (`skipped`); if a late burst triggered it, `dropped` jumps by the sequence distance. The stream recovers by itself; find what restarted the card. |
| `overwritten` > 0 | Your consumer was slower than the radar: the oldest frame in a full queue was dropped (still in `adc_data.bin`). | See [tutorial 12](12_consume_frames.md). |
| serial `missed` > 0 | Gaps in the demo's frame counter. | Check the data cable and baud. |

To survive longer stalls, raise `dca1000.rcvbuf_bytes` and `rmem_max`. Pass/fail thresholds per counter on a real board: [`14_bench_validation.md`](14_bench_validation.md) section 7.
