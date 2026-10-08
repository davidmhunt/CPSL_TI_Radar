# Docker: driver + GUI

One image (`cpsl-ti-radar:dev`) holds the C++ driver (Release), the web GUI and the shipped configs, so you can run both without a toolchain. It is separate from the firmware build image (`firmware_dev/`) and the harness dev container. Files: `docker/app/Dockerfile`, `docker/app/compose.yaml`.

## Build

From the repo root:

```
docker compose -f docker/app/compose.yaml build
```

The build compiles the driver and runs `ctest` inside the image; a failing test fails the build. The host `build/`, `config/user/` and `runs/` never enter the image.

## Mode (a): demo, no hardware

```
docker compose -f docker/app/compose.yaml up demo
```

Open `http://127.0.0.1:8090/`. The GUI replays `tests/fixtures/replay/iwr1843_sdk3_20frames.bin` and the Run tab uses `tests/fakes/fake_driver.py` instead of the real driver. The port is published on loopback only. Stop with `docker compose -f docker/app/compose.yaml --profile demo down` (`down` ignores profiled services unless you name the profile; use `--profile hw` for mode (b)).

## Mode (b): real boards (Linux host only)

```
export HOST_UID=$(id -u) HOST_GID=$(id -g) DIALOUT_GID=$(getent group dialout | cut -d: -f3)
export RADAR_CLI=/dev/ttyACM0 RADAR_DATA=/dev/ttyACM1   # your boards' ports
docker compose -f docker/app/compose.yaml --profile hw up hw
```

Then open `http://127.0.0.1:8090/` on the host. The `hw` service:

- uses host networking, so the driver reaches the DCA1000 on 192.168.33.x; the GUI binds `127.0.0.1` because it has no authentication;
- gets the two serial devices named by `RADAR_CLI` and `RADAR_DATA` (a `devices:` entry per port, chosen over a `/dev` bind plus cgroup rule because it grants exactly two nodes), runs as your uid, and joins the host `dialout` group;
- is not `privileged`;
- mounts `CPSL_TI_Radar_cpp/config/user/` and `runs/` from the host, so saved configs and run output survive the container.

Docker is Linux-only for this mode: serial passthrough and host networking to the DCA1000 do not work through Docker Desktop on macOS or Windows.

## What stays a host setting

A container shares the host kernel, so these are not set by the image:

- `net.core.rmem_max` is a host sysctl. Raise it as in `CPSL_TI_Radar_cpp/Readme.md` ("UDP receive buffer"), at least `dca1000.rcvbuf_bytes`, or the driver's socket buffer is capped and packets drop.
- The static IP on the DCA1000 NIC (192.168.33.x) is configured on the host.
- udev rules for the radar ports and membership of the `dialout` group are host-side; the container only inherits the group id you pass.

## Real-time priority

By default the RX and worker threads run at normal priority. `runtime.rx_priority` / `worker_priority` above 0 request SCHED_RR, which needs `SYS_NICE` plus an `rtprio` limit; the `hw` service already adds `cap_add: [SYS_NICE]` and `ulimits: rtprio: 99`. Without them the driver prints one warning and runs at normal priority. The `demo` service has neither.

## USB re-plug

Re-plugging a board can give it a new `/dev/ttyACM*` number. A device passed into a running container does not follow it: update `RADAR_CLI` / `RADAR_DATA` and recreate the container (`up hw --force-recreate`).

## Not covered

Publishing the image to a registry, and macOS/Windows hardware mode. Mode (b) is built to the above design but has not yet been checked against a real board (see the rel-05 directive Log).
