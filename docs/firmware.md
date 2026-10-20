# Firmware

How firmware gets onto a board, and where its sources live. The images and the build tools sit in two places.

| What | Where |
|---|---|
| Prebuilt images (IWR1443 `demo` and `dca1000_raw` only; **no IWR1843 or IWR6843 image ships**: take TI's SDK 3.6 demo or build one, [tutorial 3](tutorials/03_flash_a_radar.md)) and their provenance | [`shipped_firmware/README.md`](../shipped_firmware/README.md) |
| Which image a board needs, and flashing with UniFlash | [tutorial 3](tutorials/03_flash_a_radar.md) |
| Firmware sources, the Docker build environment and the `fw` command (IWR1843, IWR6843, SAR/LVDS, cascade) | the [`CPSL_TI_Radar_Firmware_Dev`](https://github.com/davidmhunt/CPSL_TI_Radar_Firmware_Dev) repo, the optional `firmware_dev/` submodule |

## Build or flash from source

`firmware_dev/` is a submodule that a plain clone skips. Fetch it from this repo's root, then follow its README (about 25 GB of disk, Docker, a user in the `dialout` group):

```bash
git submodule update --init --checkout firmware_dev && cd firmware_dev
./fw help
```

Its README is the entry point: [README](https://github.com/davidmhunt/CPSL_TI_Radar_Firmware_Dev#readme), with five short tutorials under `docs/tutorials/` (build environment, build, flash and verify, publish, new project) and a `fw` reference under `docs/reference/`.

| Project in `firmware_dev/projects/` | Board | `"firmware"` key it provides |
|---|---|---|
| `ti_stock_demos` | IWR1843, IWR6843 | `demo` |
| `iwr1843_sar_lvds` | IWR1843 | `iwr1843_sar_lvds` |
| `awr2243_cascade_ddm` | AWR2243 cascade EVM | `cascade_ddm` |

`./fw publish <project>` copies a clean build and its provenance into `shipped_firmware/`; the contract every project follows is [`docs/specs/fw_project_contract.md`](specs/fw_project_contract.md).

## Things to know before flashing

- Boards are single-user. Flashing needs a person to set the SOP switches (or the cascade's J6 jumper) and to power-cycle.
- Whether TI-derived binaries may be redistributed publicly is an open question for the maintainers.
- Bench results for each firmware are in [`RESULTS.md`](RESULTS.md).
