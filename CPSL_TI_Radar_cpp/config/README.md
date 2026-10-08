# Driver config tree

Everything the C++ driver reads at startup. `boards/` and `firmware/` describe the hardware and the firmware images
(see [`boards/README.md`](boards/README.md)), `limits/` holds the GUI's safe-range limits, `system/` holds the system
JSONs you pass to `CPSL_TI_Radar_CPP`, and `radar/` holds the radar `.cfg` files they point at. `user/` is yours:
the GUI saves there and nothing in it is renamed or moved.

```
config/
  boards/  firmware/  limits/           descriptors (unchanged)
  system/<BOARD>_<fw>_<purpose>[_<mount>].json    flat; the driver finds <JSON dir>/../boards
  radar/<BOARD>/<firmware>/<name>.cfg   BOARD = a board descriptor name, firmware = a firmware descriptor id
  archive/radar/<BOARD>/<firmware>/     legacy cfgs kept out of the live tree (see archive/README.md)
  moved_paths.json                      {"radar": {old: new}, "system": {old: new}}, paths relative to config/ (radar) and config/system/ (system)
  user/                                 gitignored, the GUI's saved configs
```

## Naming

- **System JSON:** `<BOARD>_<fw>_<purpose>[_<mount>].json`. BOARD is the radar folder's board (the GUI board; the SAR
  file is `IWR1843_...` although its `"board"` key is `IWR1843_SAR`). `fw` is the file's `firmware` key. `purpose` is
  `[A-Za-z0-9]` tokens. `mount` is one of `front`, `back`, `down`, `r1`: the old slot label (`radar_1` became `r1`,
  `radar_0` has none); it is not tied to ports. Outputs (TLV, DCA1000) are not in the name; the index below has them.
- **Radar cfg:** `radar/<BOARD>/<firmware>/<purpose>[_<variant>].cfg`. The board prefix (`1843_`, `6843_`) was dropped
  because the folder gives it; project names (`RadVel_10Hz`, `IcaRAus`) are kept. Copies from `iwr_raw_rosnode` carry
  a `rosnode_` prefix. Where two names collided in one folder the later one kept its old stem (`IWR6843/demo/6843_vel_sr.cfg`).
- `tests/test_config_tree.py` enforces the layout, the names and that this index is complete.

## System JSON index

`Outputs` are what the file enables (`serial_stream`, `dca1000`, `output`). Files sharing a radar cfg are listed
under "Same-cfg groups" below.

| System JSON | Board | Firmware | Outputs | Radar cfg (under `radar/`) | Purpose |
|---|---|---|---|---|---|
| [`AWR2243_CASCADE_cascade_ddm_shortrange.json`](system/AWR2243_CASCADE_cascade_ddm_shortrange.json) | AWR2243_CASCADE | cascade_ddm | serial TLV | `AWR2243_CASCADE/cascade_ddm/shortrange.cfg` | cascade short-range TLV point cloud (serial only) |
| [`IWR1443_dca1000_raw_ISAR_mocap_revised_r1.json`](system/IWR1443_dca1000_raw_ISAR_mocap_revised_r1.json) | IWR1443 | dca1000_raw | DCA1000 | `IWR1443/dca1000_raw/ISAR_mocap_revised.cfg` | ISAR mocap capture (named `ISAR_mocap_revised`) |
| [`IWR1443_dca1000_raw_RadCloud_NetSW.json`](system/IWR1443_dca1000_raw_RadCloud_NetSW.json) | IWR1443 | dca1000_raw | DCA1000 | `IWR1443/dca1000_raw/RadCloud.cfg` | `RadCloud` raw-ADC capture (named "NetSW") |
| [`IWR1443_dca1000_raw_RadSAR_NetSW.json`](system/IWR1443_dca1000_raw_RadSAR_NetSW.json) | IWR1443 | dca1000_raw | DCA1000 | `IWR1443/dca1000_raw/RadSAR.cfg` | `RadSAR` raw-ADC capture (named "NetSW") |
| [`IWR1443_dca1000_raw_RadarHD_NetSW.json`](system/IWR1443_dca1000_raw_RadarHD_NetSW.json) | IWR1443 | dca1000_raw | DCA1000 | `IWR1443/dca1000_raw/RadarHD.cfg` | `RadarHD` raw-ADC capture (named "NetSW") |
| [`IWR1843_demo_Hermes_front.json`](system/IWR1843_demo_Hermes_front.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadSAR.cfg` | Hermes project config (purpose unknown beyond the name) |
| [`IWR1843_demo_IcaRAus_back.json`](system/IWR1843_demo_IcaRAus_back.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/IcaRAus.cfg` | IcaRAus project config |
| [`IWR1843_demo_IcaRAus_front.json`](system/IWR1843_demo_IcaRAus_front.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/IcaRAus.cfg` | IcaRAus project config |
| [`IWR1843_demo_RaGNNarok_UAV_10m_front.json`](system/IWR1843_demo_RaGNNarok_UAV_10m_front.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_10m.cfg` | RaGNNarok UAV 10m project config |
| [`IWR1843_demo_RaGNNarok_UAV_50m_front.json`](system/IWR1843_demo_RaGNNarok_UAV_50m_front.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_50m.cfg` | RaGNNarok UAV 50m project config |
| [`IWR1843_demo_RaGNNarok_UAV_5m_front.json`](system/IWR1843_demo_RaGNNarok_UAV_5m_front.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_5m.cfg` | RaGNNarok UAV 5m project config |
| [`IWR1843_demo_RaGNNarok_UGV_10m_back.json`](system/IWR1843_demo_RaGNNarok_UGV_10m_back.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_10m.cfg` | RaGNNarok UGV 10m project config |
| [`IWR1843_demo_RaGNNarok_UGV_10m_front.json`](system/IWR1843_demo_RaGNNarok_UGV_10m_front.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_10m.cfg` | RaGNNarok UGV 10m project config |
| [`IWR1843_demo_RaGNNarok_UGV_5m_back.json`](system/IWR1843_demo_RaGNNarok_UGV_5m_back.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_5m.cfg` | RaGNNarok UGV 5m project config |
| [`IWR1843_demo_RaGNNarok_UGV_5m_front.json`](system/IWR1843_demo_RaGNNarok_UGV_5m_front.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/RaGNNarok_UAV_5m.cfg` | RaGNNarok UGV 5m project config |
| [`IWR1843_demo_RadCloud_front.json`](system/IWR1843_demo_RadCloud_front.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadCloud.cfg` | RadCloud project config |
| [`IWR1843_demo_RadVel_10Hz_back.json`](system/IWR1843_demo_RadVel_10Hz_back.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadVel_10Hz_lr.cfg` | RadVel 10Hz project config |
| [`IWR1843_demo_RadVel_10Hz_front.json`](system/IWR1843_demo_RadVel_10Hz_front.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadVel_10Hz_lr.cfg` | RadVel 10Hz project config |
| [`IWR1843_demo_RadarHD_front.json`](system/IWR1843_demo_RadarHD_front.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadarHD.cfg` | RadarHD project config |
| [`IWR1843_demo_human_movement.json`](system/IWR1843_demo_human_movement.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/human_movement.cfg` | human-movement TLV capture |
| [`IWR1843_demo_mmstudio_r1.json`](system/IWR1843_demo_mmstudio_r1.json) | IWR1843 | demo | DCA1000, saves ADC frames | `IWR1843/demo/mmstudio_original.cfg` | mmWave Studio-derived cfg, saves ADC frames |
| [`IWR1843_demo_nav.json`](system/IWR1843_demo_nav.json) | IWR1843 | demo | serial TLV, saves ADC frames | `IWR1843/demo/vel_nav.cfg` | purpose unknown (named "nav") |
| [`IWR1843_demo_nav_RadSAR.json`](system/IWR1843_demo_nav_RadSAR.json) | IWR1843 | demo | DCA1000 | `IWR1843/demo/RadSAR.cfg` | nav-series config `RadSAR`, purpose unknown beyond the name |
| [`IWR1843_demo_nav_RadSAR_lr.json`](system/IWR1843_demo_nav_RadSAR_lr.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadSAR.cfg` | nav-series config `RadSAR_lr`, purpose unknown beyond the name |
| [`IWR1843_demo_nav_RadVel.json`](system/IWR1843_demo_nav_RadVel.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadVel.cfg` | nav-series config `RadVel`, purpose unknown beyond the name |
| [`IWR1843_demo_nav_RadVel_10Hz.json`](system/IWR1843_demo_nav_RadVel_10Hz.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadVel_10Hz_lr.cfg` | nav-series config `RadVel_10Hz`, purpose unknown beyond the name |
| [`IWR1843_demo_nav_RadVel_20Hz.json`](system/IWR1843_demo_nav_RadVel_20Hz.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadVel_20Hz.cfg` | nav-series config `RadVel_20Hz`, purpose unknown beyond the name |
| [`IWR1843_demo_nav_RadVel_5Hz.json`](system/IWR1843_demo_nav_RadVel_5Hz.json) | IWR1843 | demo | serial TLV, DCA1000 | `IWR1843/demo/RadVel_5Hz.cfg` | nav-series config `RadVel_5Hz`, purpose unknown beyond the name |
| [`IWR1843_demo_nav_r1.json`](system/IWR1843_demo_nav_r1.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/vel_nav.cfg` | purpose unknown (named "nav") |
| [`IWR1843_demo_stress_test_baseline_front.json`](system/IWR1843_demo_stress_test_baseline_front.json) | IWR1843 | demo | DCA1000, saves ADC frames, saves raw LVDS | `IWR1843/demo/stress_test_baseline_numframes0.cfg` | bench: pre-rework baseline stress test (never-ending frames, writes `adc_data.bin` and `LVDS_Raw_0.bin`) |
| [`IWR1843_demo_stress_test_front.json`](system/IWR1843_demo_stress_test_front.json) | IWR1843 | demo | DCA1000, saves ADC frames | `IWR1843/demo/stress_test.cfg` | bench: DCA1000 streaming stress test (`tools/bench/`) |
| [`IWR1843_demo_tlv_default.json`](system/IWR1843_demo_tlv_default.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/demo_tlv_default.cfg` | default TLV point cloud on the IWR1843 demo |
| [`IWR1843_demo_vel_sr.json`](system/IWR1843_demo_vel_sr.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/vel_sr.cfg` | purpose unknown (named "vel_sr") |
| [`IWR1843_demo_vel_sr_r1.json`](system/IWR1843_demo_vel_sr_r1.json) | IWR1843 | demo | serial TLV | `IWR1843/demo/vel_sr.cfg` | purpose unknown (named "vel_sr") |
| [`IWR1843_iwr1843_sar_lvds_SAR_2ms.json`](system/IWR1843_iwr1843_sar_lvds_SAR_2ms.json) | IWR1843_SAR | iwr1843_sar_lvds | DCA1000 | `IWR1843/iwr1843_sar_lvds/SAR_2ms_fmt1.cfg` | SAR raw-ADC capture over LVDS (iwr1843_sar_lvds firmware) |
| [`IWR1843_iwr1843_sar_lvds_SAR_2ms_fmt2.json`](system/IWR1843_iwr1843_sar_lvds_SAR_2ms_fmt2.json) | IWR1843_SAR | iwr1843_sar_lvds | DCA1000 | `IWR1843/iwr1843_sar_lvds/SAR_2ms_fmt2.cfg` | same capture as `SAR_2ms` with `lvdsStreamCfg ... dataFmt 2` (ADC + per-chirp SAR metadata, core-24; needs the firmware-17 image) |
| [`IWR6843ODS_demo_IcaRAus_10Hz_down.json`](system/IWR6843ODS_demo_IcaRAus_10Hz_down.json) | IWR6843ODS | demo | DCA1000 | `IWR6843ODS/demo/IcaRAus_ods_10Hz.cfg` | IcaRAus 10Hz project config |
| [`IWR6843ODS_demo_RadVel.json`](system/IWR6843ODS_demo_RadVel.json) | IWR6843ODS | demo | serial TLV, DCA1000 | `IWR6843ODS/demo/RadVel_ods_10Hz.cfg` | RadVel project config |
| [`IWR6843ODS_demo_RadVel_10Hz_down.json`](system/IWR6843ODS_demo_RadVel_10Hz_down.json) | IWR6843ODS | demo | DCA1000 | `IWR6843ODS/demo/RadVel_ods_10Hz.cfg` | RadVel 10Hz project config |
| [`IWR6843ODS_demo_human_movement.json`](system/IWR6843ODS_demo_human_movement.json) | IWR6843ODS | demo | serial TLV, DCA1000 | `IWR6843ODS/demo/RadVel_ods_10Hz.cfg` | human-movement TLV capture |

### Same-cfg groups

System JSONs that point at the same radar cfg (they differ in mount, ports or outputs):

- `IWR1843/demo/IcaRAus.cfg`: `IWR1843_demo_IcaRAus_back`, `IWR1843_demo_IcaRAus_front`
- `IWR1843/demo/RaGNNarok_UAV_10m.cfg`: `IWR1843_demo_RaGNNarok_UAV_10m_front`, `IWR1843_demo_RaGNNarok_UGV_10m_back`, `IWR1843_demo_RaGNNarok_UGV_10m_front`
- `IWR1843/demo/RaGNNarok_UAV_5m.cfg`: `IWR1843_demo_RaGNNarok_UAV_5m_front`, `IWR1843_demo_RaGNNarok_UGV_5m_back`, `IWR1843_demo_RaGNNarok_UGV_5m_front`
- `IWR1843/demo/RadSAR.cfg`: `IWR1843_demo_Hermes_front`, `IWR1843_demo_nav_RadSAR`, `IWR1843_demo_nav_RadSAR_lr`
- `IWR1843/demo/RadVel_10Hz_lr.cfg`: `IWR1843_demo_RadVel_10Hz_back`, `IWR1843_demo_RadVel_10Hz_front`, `IWR1843_demo_nav_RadVel_10Hz`
- `IWR1843/demo/vel_nav.cfg`: `IWR1843_demo_nav`, `IWR1843_demo_nav_r1`
- `IWR1843/demo/vel_sr.cfg`: `IWR1843_demo_vel_sr`, `IWR1843_demo_vel_sr_r1`
- `IWR6843ODS/demo/RadVel_ods_10Hz.cfg`: `IWR6843ODS_demo_RadVel`, `IWR6843ODS_demo_RadVel_10Hz_down`, `IWR6843ODS_demo_human_movement`


## Old to new: system JSONs

Run directories, results and old launch scripts cite the old names. `IWR6843ODS_demo_RadVel_down.json` (a gui-38 name) was a byte-identical duplicate of `_10Hz_down` and was removed in rel-01. `moved_paths.json` holds the same map.

| Old (`system/`) | New |
|---|---|
| `back_radar_IWR1843_IcaRAus.json` | `IWR1843_demo_IcaRAus_back.json` |
| `back_radar_IWR1843_RaGNNarok_UGV_10m.json` | `IWR1843_demo_RaGNNarok_UGV_10m_back.json` |
| `back_radar_IWR1843_RaGNNarok_UGV_5m.json` | `IWR1843_demo_RaGNNarok_UGV_5m_back.json` |
| `back_radar_IWR1843_dca_RadVel_10Hz.json` | `IWR1843_demo_RadVel_10Hz_back.json` |
| `down_radar_6843_IcaRAus_ods_10Hz.json` | `IWR6843ODS_demo_IcaRAus_10Hz_down.json` |
| `down_radar_6843_RadVel_ods_10Hz.json` | `IWR6843ODS_demo_RadVel_10Hz_down.json` |
| `down_radar_IWR6843_ods_dca_RadVel.json` | `IWR6843ODS_demo_RadVel_10Hz_down.json` |
| `IWR6843ODS_demo_RadVel_down.json` | `IWR6843ODS_demo_RadVel_10Hz_down.json` |
| `front_radar_IWR1843_Hermes.json` | `IWR1843_demo_Hermes_front.json` |
| `front_radar_IWR1843_IcaRAus.json` | `IWR1843_demo_IcaRAus_front.json` |
| `front_radar_IWR1843_RaGNNarok_UAV_10m.json` | `IWR1843_demo_RaGNNarok_UAV_10m_front.json` |
| `front_radar_IWR1843_RaGNNarok_UAV_50m.json` | `IWR1843_demo_RaGNNarok_UAV_50m_front.json` |
| `front_radar_IWR1843_RaGNNarok_UAV_5m.json` | `IWR1843_demo_RaGNNarok_UAV_5m_front.json` |
| `front_radar_IWR1843_RaGNNarok_UGV_10m.json` | `IWR1843_demo_RaGNNarok_UGV_10m_front.json` |
| `front_radar_IWR1843_RaGNNarok_UGV_5m.json` | `IWR1843_demo_RaGNNarok_UGV_5m_front.json` |
| `front_radar_IWR1843_RadCloud.json` | `IWR1843_demo_RadCloud_front.json` |
| `front_radar_IWR1843_RadarHD.json` | `IWR1843_demo_RadarHD_front.json` |
| `front_radar_IWR1843_dca_RadVel_10Hz.json` | `IWR1843_demo_RadVel_10Hz_front.json` |
| `front_radar_IWR1843_stress_test.json` | `IWR1843_demo_stress_test_front.json` |
| `front_radar_IWR1843_stress_test_baseline.json` | `IWR1843_demo_stress_test_baseline_front.json` |
| `radar_0_AWR2243_cascade_serial.json` | `AWR2243_CASCADE_cascade_ddm_shortrange.json` |
| `radar_0_IWR1843_SAR.json` | `IWR1843_iwr1843_sar_lvds_SAR_2ms.json` |
| `radar_0_IWR1843_demo.json` | `IWR1843_demo_tlv_default.json` |
| `radar_0_IWR1843_human_movement.json` | `IWR1843_demo_human_movement.json` |
| `radar_0_IWR1843_nav.json` | `IWR1843_demo_nav.json` |
| `radar_0_IWR1843_nav_dca_RadSAR.json` | `IWR1843_demo_nav_RadSAR.json` |
| `radar_0_IWR1843_nav_dca_RadSAR_lr.json` | `IWR1843_demo_nav_RadSAR_lr.json` |
| `radar_0_IWR1843_nav_dca_RadVel.json` | `IWR1843_demo_nav_RadVel.json` |
| `radar_0_IWR1843_nav_dca_RadVel_10Hz.json` | `IWR1843_demo_nav_RadVel_10Hz.json` |
| `radar_0_IWR1843_nav_dca_RadVel_20Hz.json` | `IWR1843_demo_nav_RadVel_20Hz.json` |
| `radar_0_IWR1843_nav_dca_RadVel_5Hz.json` | `IWR1843_demo_nav_RadVel_5Hz.json` |
| `radar_0_IWR1843_vel_sr.json` | `IWR1843_demo_vel_sr.json` |
| `radar_0_IWR6843_ods_dca_RadVel.json` | `IWR6843ODS_demo_RadVel.json` |
| `radar_0_IWR6843_ods_human_movement.json` | `IWR6843ODS_demo_human_movement.json` |
| `radar_0_RadCloud_NetSW.json` | `IWR1443_dca1000_raw_RadCloud_NetSW.json` |
| `radar_0_RadSAR_NetSW.json` | `IWR1443_dca1000_raw_RadSAR_NetSW.json` |
| `radar_0_RadarHD_NetSW.json` | `IWR1443_dca1000_raw_RadarHD_NetSW.json` |
| `radar_1.json` | `IWR1443_dca1000_raw_ISAR_mocap_revised_r1.json` |
| `radar_1_IWR1843_DCA_demo.json` | `IWR1843_demo_mmstudio_r1.json` |
| `radar_1_IWR1843_nav.json` | `IWR1843_demo_nav_r1.json` |
| `radar_1_IWR1843_vel_sr.json` | `IWR1843_demo_vel_sr_r1.json` |

## Old to new: radar cfgs

Old paths are relative to `config/`; new paths are too. The cfg contents did not change. The 18 cfgs that never
carried `calibData` (the old `DCA1000/custom_configs/` and `IWR_Demos/` SDK-2 cfgs) are now under `IWR1443/`, where the
SDK 2 demo does not need it.

### `archive/radar/IWR1443/dca1000_raw/`

| Old | New |
|---|---|
| `radar/DCA1000/custom_configs/archived_configs/standard.cfg` | `standard.cfg` |
| `radar/DCA1000/custom_configs/archived_configs/vel_detection.cfg` | `vel_detection.cfg` |

### `radar/AWR2243_CASCADE/cascade_ddm/`

| Old | New |
|---|---|
| `radar/cascade/cascade_shortrange.cfg` | `shortrange.cfg` |
| `radar/cascade/cascade_shortrange_dense.cfg` | `shortrange_dense.cfg` |
| `tools/radar_viewer/configs/calibration_run.cfg` | `calibration_run.cfg` |
| `tools/radar_viewer/configs/cascade_R15m_V5ms_20Hz.cfg` | `cascade_R15m_V5ms_20Hz.cfg` |

### `radar/IWR1443/dca1000_raw/`

| Old | New |
|---|---|
| `radar/DCA1000/custom_configs/ISAR_1.cfg` | `ISAR_1.cfg` |
| `radar/DCA1000/custom_configs/ISAR_2.cfg` | `ISAR_2.cfg` |
| `radar/DCA1000/custom_configs/ISAR_mocap.cfg` | `ISAR_mocap.cfg` |
| `radar/DCA1000/custom_configs/ISAR_mocap_revised.cfg` | `ISAR_mocap_revised.cfg` |
| `radar/DCA1000/custom_configs/RadCloud.cfg` | `RadCloud.cfg` |
| `radar/DCA1000/custom_configs/RadSAR.cfg` | `RadSAR.cfg` |
| `radar/DCA1000/custom_configs/RadarHD.cfg` | `RadarHD.cfg` |
| `radar/DCA1000/custom_configs/long_range.cfg` | `long_range.cfg` |
| `radar/DCA1000/custom_configs/long_range_no_virtual_array.cfg` | `long_range_no_virtual_array.cfg` |
| `radar/DCA1000/custom_configs/medium_range.cfg` | `medium_range.cfg` |
| `radar/DCA1000/iwr_raw_rosnode/14xx/indoor_human_rcs.cfg` | `rosnode_indoor_human_rcs.cfg` |
| `radar/DCA1000/iwr_raw_rosnode/14xx/outdoor_human_rcs_30m.cfg` | `rosnode_outdoor_human_rcs_30m.cfg` |
| `radar/DCA1000/iwr_raw_rosnode/14xx/outdoor_human_rcs_50m.cfg` | `rosnode_outdoor_human_rcs_50m.cfg` |
| `radar/DCA1000/custom_configs/short_range.cfg` | `short_range.cfg` |
| `radar/DCA1000/custom_configs/short_range_40_chirps_10_fps.cfg` | `short_range_40_chirps_10_fps.cfg` |

### `radar/IWR1443/demo/`

| Old | New |
|---|---|
| `radar/IWR_Demos/athena/1443_athena.cfg` | `athena.cfg` |
| `radar/IWR_Demos/1443config.cfg` | `config.cfg` |
| `radar/IWR_Demos/rad_nav_configs/1443_high_v_res_config.cfg` | `high_v_res_config.cfg` |
| `radar/IWR_Demos/indoor_scene.cfg` | `indoor_scene.cfg` |
| `radar/IWR_Demos/rad_nav_configs/1443_lr.cfg` | `lr.cfg` |
| `radar/IWR_Demos/rad_nav_configs/1443_lr_3D.cfg` | `lr_3D.cfg` |
| `radar/IWR_Demos/radar_cfg_higher_CFAR.cfg` | `radar_cfg_higher_CFAR.cfg` |
| `radar/IWR_Demos/radar_cfg_low_CFAR.cfg` | `radar_cfg_low_CFAR.cfg` |
| `radar/IWR_Demos/short_range_3D.cfg` | `short_range_3D.cfg` |
| `radar/IWR_Demos/rad_nav_configs/1443_vel.cfg` | `vel.cfg` |
| `radar/IWR_Demos/rad_nav_configs/1443_vel_sr.cfg` | `vel_sr.cfg` |

### `radar/IWR1843/demo/`

| Old | New |
|---|---|
| `radar/nav_configs/1843_IcaRAus.cfg` | `IcaRAus.cfg` |
| `radar/nav_configs/1843_RaGNNarok.cfg` | `RaGNNarok.cfg` |
| `radar/nav_configs/1843_RaGNNarok_UAV_10m.cfg` | `RaGNNarok_UAV_10m.cfg` |
| `radar/nav_configs/1843_RaGNNarok_UAV_50m.cfg` | `RaGNNarok_UAV_50m.cfg` |
| `radar/nav_configs/1843_RaGNNarok_UAV_5m.cfg` | `RaGNNarok_UAV_5m.cfg` |
| `radar/nav_configs/1843_RadCloud.cfg` | `RadCloud.cfg` |
| `radar/nav_configs/1843_RadSAR.cfg` | `RadSAR.cfg` |
| `radar/nav_configs/1843_RadVel.cfg` | `RadVel.cfg` |
| `radar/nav_configs/1843_RadVel_10Hz.cfg` | `RadVel_10Hz.cfg` |
| `radar/nav_configs/1843_RadVel_10Hz_lr.cfg` | `RadVel_10Hz_lr.cfg` |
| `radar/nav_configs/1843_RadVel_20Hz.cfg` | `RadVel_20Hz.cfg` |
| `radar/nav_configs/1843_RadVel_5Hz.cfg` | `RadVel_5Hz.cfg` |
| `radar/nav_configs/1843_RadarHD.cfg` | `RadarHD.cfg` |
| `radar/DCA1000/IWR1843_configs/IWR1843_demo.cfg` | `demo_tlv_default.cfg` |
| `radar/human_movement/1843_human_movement.cfg` | `human_movement.cfg` |
| `radar/DCA1000/IWR1843_configs/Iwr18xx_DCA_mmStudio_1rx_1chirp.cfg` | `mmstudio_1rx_1chirp.cfg` |
| `radar/DCA1000/IWR1843_configs/Iwr18xx_DCA_mmStudio_original.cfg` | `mmstudio_original.cfg` |
| `radar/DCA1000/iwr_raw_rosnode/18xx/indoor_human_rcs.cfg` | `rosnode_indoor_human_rcs.cfg` |
| `radar/DCA1000/iwr_raw_rosnode/18xx/outdoor_human_rcs_30m.cfg` | `rosnode_outdoor_human_rcs_30m.cfg` |
| `radar/DCA1000/iwr_raw_rosnode/18xx/outdoor_human_rcs_50m.cfg` | `rosnode_outdoor_human_rcs_50m.cfg` |
| `radar/nav_configs/1843_stress_test.cfg` | `stress_test.cfg` |
| `radar/nav_configs/1843_stress_test_baseline_numframes0.cfg` | `stress_test_baseline_numframes0.cfg` |
| `radar/nav_configs/1843_vel_nav.cfg` | `vel_nav.cfg` |
| `radar/nav_configs/1843_vel_sr.cfg` | `vel_sr.cfg` |

### `radar/IWR1843/iwr1843_sar_lvds/`

| Old | New |
|---|---|
| `radar/sar_configs/1843_SAR_2ms_fmt1.cfg` | `SAR_2ms_fmt1.cfg` |

### `radar/IWR6843/demo/`

| Old | New |
|---|---|
| `radar/IWR_Demos/rad_nav_configs/6843_vel_sr.cfg` | `6843_vel_sr.cfg` |
| `radar/IWR_Demos/athena/6843_athena.cfg` | `athena.cfg` |
| `radar/IWR_Demos/6843.cfg` | `default.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_high_v_res_config.cfg` | `high_v_res_config.cfg` |
| `radar/IWR_Demos/6843_long_range.cfg` | `long_range.cfg` |
| `radar/IWR_Demos/6843_long_range_high_CFAR.cfg` | `long_range_high_CFAR.cfg` |
| `radar/IWR_Demos/6843_long_range_high_v_res_CFAR.cfg` | `long_range_high_v_res_CFAR.cfg` |
| `radar/IWR_Demos/6843_low_CFAR.cfg` | `low_CFAR.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_lr_CFAR_10dB.cfg` | `lr_CFAR_10dB.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_lr_CFAR_15dB.cfg` | `lr_CFAR_15dB.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_lr_CFAR_7dB.cfg` | `lr_CFAR_7dB.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_lr_CFAR_7dB_3D.cfg` | `lr_CFAR_7dB_3D.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_vel.cfg` | `vel.cfg` |
| `radar/nav_configs/6843_vel_sr.cfg` | `vel_sr.cfg` |

### `radar/IWR6843ODS/demo/`

| Old | New |
|---|---|
| `radar/nav_configs/6843_IcaRAus_ods_10Hz.cfg` | `IcaRAus_ods_10Hz.cfg` |
| `radar/nav_configs/6843_RadVel_ods_10Hz.cfg` | `RadVel_ods_10Hz.cfg` |
| `radar/nav_configs/6843_RadVel_ods_20Hz.cfg` | `RadVel_ods_20Hz.cfg` |
| `radar/nav_configs/6843_RadVel_ods_5Hz.cfg` | `RadVel_ods_5Hz.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_ODS_lr_CFAR_10dB.cfg` | `lr_CFAR_10dB.cfg` |
| `radar/IWR_Demos/rad_nav_configs/6843_ODS_lr_CFAR_7dB.cfg` | `lr_CFAR_7dB.cfg` |
