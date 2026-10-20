# shipped_firmware

Prebuilt firmware images that ship with the repo, laid out as
`shipped_firmware/<BOARD>/<firmware>/`, the same keying as
`CPSL_TI_Radar_cpp/config/radar/<BOARD>/<firmware>/`. `<firmware>` is the name
of a descriptor in `CPSL_TI_Radar_cpp/config/firmware/<firmware>.json`.

Which image a board needs, and how to flash it: [tutorial 3](../docs/tutorials/03_flash_a_radar.md).

| Image | Board | Firmware descriptor | Provenance | Flashing |
|-------|-------|---------------------|------------|----------|
| `IWR1443/demo/xwr14xx_mmw_demo.bin` | IWR1443 | `demo` | v1 prebuilt TI mmw demo; source not in this repo, SDK version unknown | UniFlash in SOP flashing mode; [tutorial 3](../docs/tutorials/03_flash_a_radar.md) and `docs/images/boot_modes/IWR_SOP_modes.png` |
| `IWR1443/dca1000_raw/iwr_raw_rosnode/firmware/xwr14xx_lvds_stream.bin` | IWR1443 | `dca1000_raw` | v1 prebuilt raw-ADC LVDS streaming image (SDK 2.1 per binary strings); inside the `iwr_raw_rosnode` submodule (https://github.com/davidmhunt/iwr_raw_rosnode, pinned commit `315e514`), which moved as a unit; its `lvds_stream/xwr14xx/` sources are in the submodule | same as above |
| `IWR1443/dca1000_raw/iwr_raw_rosnode/firmware/xwr68xx_lvds_stream.bin` | IWR6843 | none (the 6843 demo streams LVDS natively) | v1 prebuilt, inside the submodule | not used by the driver |

## Images not in this directory

- The IWR1843 and IWR6843 stock demos, and the IWR1843 SAR/LVDS image
  (`iwr1843_sar_lvds`), are built from `firmware_dev/` (an opt-in submodule;
  see [`docs/firmware.md`](../docs/firmware.md)).
- The cascade (AWR2243 + AM273x) image is built from
  `firmware_dev/projects/awr2243_cascade_ddm/`; TI's two SBL `.tiimage` files
  it needs for flashing sit in that project's `prebuilt_binaries/`.

`fw publish` (from `firmware_dev/`, clean builds only) fills this directory from `firmware_dev` builds:
`./fw publish <project> [--dry-run]` copies each flashable image to `<BOARD>/<descriptor>/` with an
`<image>.provenance.json` (`firmware_dev` commit, variant, toolchain, image sha256, chirp cfgs). Add a
row to the table above for each published image, and commit it with the image, its provenance and the
bumped `firmware_dev` pointer. See `firmware_dev/docs/tutorials/04_publish.md`. No `fw publish` image is tracked here yet.

## Licensing

These are TI-derived binaries. Whether they may be redistributed in a public
release is an open question for the maintainers.
