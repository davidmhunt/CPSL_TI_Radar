# shipped_firmware

Prebuilt firmware images that ship with the repo, laid out as
`shipped_firmware/<BOARD>/<firmware>/`, the same keying as
`CPSL_TI_Radar_cpp/config/radar/<BOARD>/<firmware>/`. `<firmware>` is the name
of a descriptor in `CPSL_TI_Radar_cpp/config/firmware/<firmware>.json`.
Images that no descriptor uses sit in `legacy/`.

These are the v1 images moved here from `Firmware/` (rel-03); every file is
byte-identical to its old path (sha256 recorded in the rel-03 directive log).

| Image | Board | Firmware descriptor | Provenance | Flashing |
|-------|-------|---------------------|------------|----------|
| `IWR1443/demo/xwr14xx_mmw_demo.bin` | IWR1443 | `demo` | v1 prebuilt TI mmw demo; source not in this repo, SDK version unknown | UniFlash in SOP flashing mode; `CPSL_TI_Radar_cpp/Readme.md` ("Flash the correct firmware") and `docs/images/boot_modes/IWR_SOP_modes.png` |
| `IWR1443/dca1000_raw/iwr_raw_rosnode/firmware/xwr14xx_lvds_stream.bin` | IWR1443 | `dca1000_raw` | v1 prebuilt raw-ADC LVDS streaming image (SDK 2.1 per binary strings); inside the `iwr_raw_rosnode` submodule (https://github.com/davidmhunt/iwr_raw_rosnode, pinned commit `315e514`), which moved as a unit; its `lvds_stream/xwr14xx/` sources are in the submodule | same as above |
| `IWR1443/dca1000_raw/iwr_raw_rosnode/firmware/xwr68xx_lvds_stream.bin` | IWR6843 | none (the 6843 demo streams LVDS natively) | v1 prebuilt, inside the submodule | not used by the driver |
| `legacy/xwr16xx_mmw_demo.bin` | IWR1642 | none | v1 prebuilt TI mmw demo; IWR1642 is not a supported board | not used |
| `legacy/studio_cli/` | IWR1443/1642/1843/6843 | none | v1 mmWave Studio CLI prebuilt binaries (`prebuilt_binaries/`) and profiles (`profiles/`); used by no descriptor | not used |

The submodule is initialised with `git submodule update --init shipped_firmware/IWR1443/dca1000_raw/iwr_raw_rosnode`.

## Images not in this directory

- The IWR1843 and IWR6843 stock demos, and the IWR1843 SAR/LVDS image
  (`iwr1843_sar_lvds`), are built from `firmware_dev/` (an opt-in submodule;
  see `docs/firmware.md`) and are not tracked here yet.
- The cascade (AWR2243 + AM273x) image is built from
  `firmware_dev/projects/awr2243_cascade_ddm/`; TI's two SBL `.tiimage` files
  it needs for flashing sit in that project's `prebuilt_binaries/`.

A future publish script is meant to fill this directory from `firmware_dev`
builds and record each image's provenance (`firmware_dev` commit, build config,
chirp config) next to it.

## Licensing

These are TI-derived binaries. Whether they may be redistributed in a public
release is an open question for the release gate (the user's call), tracked in
`docs/firmware.md` under "Open v2.0 items".
