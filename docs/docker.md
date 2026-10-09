# Docker: driver + GUI

One image (`cpsl-ti-radar:dev`) holds the C++ driver (Release), the web GUI and the shipped configs, so you can run both without a toolchain. It is separate from the firmware build image (`firmware_dev/`) and the harness dev container. Files: `docker/app/Dockerfile`, `docker/app/compose.yaml`.

## Build

From the repo root:

```
docker compose -f docker/app/compose.yaml build demo
```

Both services use the same image, and each is in a compose profile, so the service is named (a bare `build` says "No services to build"). The build compiles the driver and runs `ctest` inside the image; a failing test fails the build. The host `build/`, `config/user/` and `runs/` never enter the image.

## Mode (a): demo, no hardware

```
docker compose -f docker/app/compose.yaml up demo
```

Open `http://127.0.0.1:8090/`. The GUI replays `tests/fixtures/replay/iwr1843_sdk3_20frames.bin` and the Radar tab uses `tests/fakes/fake_driver.py` instead of the real driver. The port is published on loopback only. Stop with `docker compose -f docker/app/compose.yaml --profile demo down` (`down` ignores profiled services unless you name the profile; use `--profile hw` for mode (b)).

## Mode (b): real boards (Linux host only)

```
docker/app/setup_env.sh        # writes docker/app/.env: uid/gid, the device's group, by-id ports, GUI host/port
mkdir -p runs CPSL_TI_Radar_cpp/config/user   # gitignored; Docker would create them root-owned
docker compose -f docker/app/compose.yaml --profile hw up hw
```

`setup_env.sh` picks the board from `/dev/serial/by-id/*XDS110*` (it asks when there are several), reads the group that owns the node (`stat -L -c %g`) and asks for the GUI host (default loopback; it offers your `tailscale ip -4` address) and port. Flags: `--non-interactive`, `--print` (stdout only), `--force` (overwrite an existing `.env`). `docker/app/.env.example` documents every key. Fallback without the script: export `HOST_UID`, `HOST_GID`, `SERIAL_GID` (the device's group, `stat -L -c %g <port>`), `RADAR_CLI`, `RADAR_DATA` yourself; `DIALOUT_GID` still works as an old name for `SERIAL_GID`.

Then open `http://127.0.0.1:8090/` (or your `GUI_HOST`) on the host. The `hw` service:

- uses host networking, so the driver reaches the DCA1000 on 192.168.33.x; the GUI binds `GUI_HOST` (default `127.0.0.1`);
- gets the two serial devices named by `RADAR_CLI` and `RADAR_DATA` (a `devices:` entry per port, chosen over a `/dev` bind plus cgroup rule because it grants exactly two nodes), runs as your uid, and joins the group that owns the device (`SERIAL_GID`; `plugdev` on some hosts, `dialout` on others; a wrong group gives "Permission denied" on the port, and the GUI's failed-run message then names the group);
- maps each host port to a fixed path inside the container: `RADAR_CLI` to `/dev/ttyACM0` and `RADAR_DATA` to `/dev/ttyACM1`, which is what the shipped system JSONs name. A system JSON naming other ports needs them set in Quick setup, or `RADAR_CLI_IN` / `RADAR_DATA_IN` in `.env`;
- is not `privileged`;
- mounts `CPSL_TI_Radar_cpp/config/user/` and `runs/` from the host, so saved configs and run output survive the container.

**Security.** The GUI has no authentication. Loopback is the default. A LAN or tailnet `GUI_HOST` lets anyone who can reach it start the radar. The GUI's `--tailscale` flag does not work in the container (no `tailscale` CLI): set `GUI_HOST` to the tailnet IP instead.

Docker is Linux-only for this mode: serial passthrough and host networking to the DCA1000 do not work through Docker Desktop on macOS or Windows.

## What stays a host setting

A container shares the host kernel, so these are not set by the image:

- `net.core.rmem_max` is a host sysctl. Raise it as in `CPSL_TI_Radar_cpp/Readme.md` ("UDP receive buffer"), at least `dca1000.rcvbuf_bytes`, or the driver's socket buffer is capped and packets drop.
- The static IP on the DCA1000 NIC (192.168.33.x) is configured on the host.
- udev rules for the radar ports and membership of the device's group (`dialout` or `plugdev`) are host-side; the container only inherits the group id you pass.

## Real-time priority

By default the RX and worker threads run at normal priority. `runtime.rx_priority` / `worker_priority` above 0 request SCHED_RR, which needs `SYS_NICE` plus an `rtprio` limit; the `hw` service already adds `cap_add: [SYS_NICE]` and `ulimits: rtprio: 99`. Without them the driver prints one warning and runs at normal priority. The `demo` service has neither.

## USB re-plug

By-id paths (`/dev/serial/by-id/...`, what `setup_env.sh` writes) survive a renumbered `/dev/ttyACM*`. A device passed into a running container still does not follow a re-plug: recreate it (`up hw --force-recreate`).

## Not covered

Publishing the image to a registry, and macOS/Windows hardware mode. Mode (b) is built to the above design but has not yet been checked against a real board; confirm it on your hardware before relying on it.
