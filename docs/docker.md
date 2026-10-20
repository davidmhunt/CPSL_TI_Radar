# Docker: the driver and GUI in one image

One image, `cpsl-ti-radar:dev`, holds the C++ driver (Release), the web GUI and the shipped configs, so you can run both with no compiler or `uv` on the host. Files: `docker/app/Dockerfile`, `docker/app/compose.yaml`. This image is not the firmware build image (`firmware_dev/`).

## Prerequisites

Linux with Docker Engine and the compose plugin ([install guide](https://docs.docker.com/engine/install/ubuntu/); your user in the `docker` group). Clone the repo and fetch the JSON library the driver build copies in; nothing else from the submodules is needed:

```bash
git clone https://github.com/davidmhunt/CPSL_TI_Radar && cd CPSL_TI_Radar
git submodule update --init CPSL_TI_Radar_cpp/include/json
```

## Build

```bash
docker compose -f docker/app/compose.yaml build demo
```

Both services share the image and each sits in a compose profile, so name one (a bare `build` says "No services to build"). The build compiles the driver and runs `ctest` inside the image; a failing test fails the build. Your host `build/`, `config/user/` and `runs/` never enter the image.

## Demo, no hardware

```bash
docker compose -f docker/app/compose.yaml up demo
```

Open `http://127.0.0.1:8090/`. The GUI replays `tests/fixtures/replay/iwr1843_sdk3_20frames.bin` and the Radar tab uses the stand-in `tests/fakes/fake_driver.py`. The port is published on loopback only. Stop with Ctrl-C, then `docker compose -f docker/app/compose.yaml --profile demo down` (`down` ignores profiled services unless you name the profile).

## Real boards (Linux host only)

```bash
docker/app/setup_env.sh        # writes docker/app/.env: uid/gid, the device's group, by-id ports, GUI host/port
mkdir -p runs CPSL_TI_Radar_cpp/config/user   # Docker would otherwise create them root-owned
docker compose -f docker/app/compose.yaml --profile hw up hw
```

`setup_env.sh` picks the board from `/dev/serial/by-id/*XDS110*` (it asks when there are several), reads the group that owns the node, and asks for the GUI host (default loopback) and port. Flags: `--non-interactive`, `--print` (stdout only), `--force` (overwrite). `docker/app/.env.example` documents every key. Then open `http://127.0.0.1:8090/` (or your `GUI_HOST`). The `hw` service:

- uses host networking, so the driver reaches the DCA1000 on `192.168.33.x`;
- gets exactly the two serial devices `RADAR_CLI` and `RADAR_DATA`, runs as your uid, joins the group that owns them (`SERIAL_GID`; `dialout` or `plugdev`, and a wrong group gives "Permission denied" on the port), and is not `privileged`;
- maps them to `/dev/ttyACM0` and `/dev/ttyACM1` inside, which is what the shipped system JSONs name; other names go in Quick setup or `RADAR_CLI_IN` / `RADAR_DATA_IN` in `.env`;
- mounts `CPSL_TI_Radar_cpp/config/user/` and `runs/` from the host, so saved configs and run output survive.

**Security.** The GUI has no authentication; a LAN or tailnet `GUI_HOST` lets anyone who can reach it start the radar. The GUI's `--tailscale` flag does not work in the container (no `tailscale` CLI): set `GUI_HOST` to the tailnet IP.

## What stays a host setting

A container shares the host kernel, so [tutorial 2](tutorials/02_host_setup.md) still applies on the host: `net.core.rmem_max` at least `dca1000.rcvbuf_bytes`, the static `192.168.33.30` address on the DCA1000 NIC, the firewall rule, and membership of the device's group. The image inherits only the group id.

`runtime.rx_priority` / `worker_priority` above 0 need `SYS_NICE` and an `rtprio` limit; `hw` adds both, `demo` has neither (without them the driver warns once and runs at normal priority).

A device passed into a running container does not follow a USB re-plug: `up hw --force-recreate`. By-id paths survive a renumbered `/dev/ttyACM*` across restarts.

## Not covered

Publishing the image to a registry; macOS and Windows (serial passthrough and host networking to the DCA1000 do not work through Docker Desktop). The `hw` profile is built to this design; confirm it on your own board before relying on it.
