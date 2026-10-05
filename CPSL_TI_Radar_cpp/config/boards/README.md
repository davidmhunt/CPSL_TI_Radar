# Board descriptors

One JSON file per board, read by `BoardDescriptor::load` (`src/BoardDescriptor/`).
The schema is in [`docs/design/driver_v2_design.md`](../../../docs/design/driver_v2_design.md) §1.
Loading is strict: an unknown key, a wrong type, an unknown enum string, or a `lanes`/`layout`
mismatch is an error. `name` must equal the file name. `dca1000` is required when
`lvds.supported` is true and not allowed when it is false.

Status: added in core-09 and **not read by the driver yet**. Today's runtime still uses the
system config's `board_type`. core-10 switches the driver over to these files.

| File | SDK | LVDS (DCA1000) | Serial TLV |
|------|-----|----------------|------------|
| `IWR1443.json` | `mmwave_sdk_2` | 4 lanes, `lane_per_rx`, `i_first` | `sdk2`: **unconfirmed, rejected for serial use** (D7) |
| `IWR1843.json` | `mmwave_sdk_3` | 2 lanes, `two_lane_iq_pairs`, `q_first` | `sdk3` |
| `IWR6843.json` | `mmwave_sdk_3` | same as IWR1843 | `sdk3` |
| `AWR2243_CASCADE.json` | `mmwave_mcuplus` | `supported: false` (D4) | `mcuplus_cascade`, 3,125,000 baud |

## Where each value comes from

Line numbers refer to `CPSL_TI_Radar_cpp/` at commit `6d6aa59`. The audit is
`docs/design/driver_v2_audit.md` (b).

| Field | Value(s) | Evidence |
|-------|----------|----------|
| `cli.baud` | 115200 | `SystemConfigReader.cpp:15` default |
| `cli.ack` | `Done` | `CLIController.cpp:223,246` |
| `cli.prompt`, `prompt_wait_ms` | `mmwDemo:/>`, 500 | `CLIController.cpp:225-230`. The same prompt string is set in the SDK 3.6 demo (`firmware_dev/projects/iwr1843_sar_lvds/src/mss/mmw_cli.c:1325`) and in the cascade demo (`firmware_dev/projects/awr2243_cascade_ddm/.../mss/mmw_cli.c:2220`). **IWR1443 (SDK 2): not checked against source.** |
| `cli.cmd_timeout_ms` | 100; cascade 5000 | `SystemConfigReader.cpp:16` default; `config/system/radar_0_AWR2243_cascade_serial.json:9` |
| `cli.start_cmd`, `stop_cmd` | `sensorStart`, `sensorStop` | `CLIController.cpp:135,156,165` |
| `cli.skip_prefixes` | `%`, `#` | `CLIController.cpp:132` |
| `cli.error_tokens` | `Error`, `not recognized` | **Not used by today's code** (design §1 adds it). `Error` matches the demos' `CLI_write("Error: ...")` replies (SDK 3.6 `mmw_cli.c:377,821`, for example). `not recognized` is the TI CLI utility's unknown-command reply, quoted from memory: **unverified**, so check it before core-10 relies on it. |
| `lifecycle.config_once_per_boot` | cascade only | `Runner.cpp:94-99,217-218` |
| `cfg_dialect.rx_mask_fields` | `[1]`; cascade `[1, 4]` | `RadarConfigReader.cpp:285-289` (slave mask when `channelCfg` has 6 or more fields) |
| `cfg_dialect.frame_period_field` | 5; cascade 6 | `RadarConfigReader.cpp:261-276` (field-count guess) |
| `data_uart.baud` | 921600; cascade 3,125,000 | `SystemConfigReader.cpp:17` default; cascade JSON `:15` |
| `data_uart.timeout_ms` | 1000; cascade 5000 | `SystemConfigReader.cpp:18` default; cascade JSON `:16`. The cascade value follows the tracked JSON. Design §1's table lists no override for it. |
| `data_uart.header_bytes` | 40; IWR1443 36 | 8-byte magic word + 32-byte header (`SerialStreamer.cpp:22`). **IWR1443 36 is a HYPOTHESIS** (audit (b): SDK 2 header has no `subFrameNumber`). |
| `data_uart.tlv_dialect` | `sdk3`, `mcuplus_cascade`, `sdk2` | `TLVProcessing.hpp:11-21`. The cascade TLV codes 10 and 104 are defined but not parsed. **`sdk2` is unconfirmed (D7)**: the file loads, but `cross_check_radar_cfg` rejects serial streaming with it. |
| `lvds.supported` | cascade `false` | `SystemConfigReader.cpp:476-482`; D4 |
| `lvds.lanes` | 4 (IWR1443), 2 | `DCA1000Handler.cpp:377-387` (CONFIG_FPGA_GEN byte 1) |
| `lvds.layout` | `lane_per_rx` (IWR1443), `two_lane_iq_pairs` | `ADCCubeConverter.cpp:24-27`; TI SWRA581B §5/§6 |
| `lvds.iq_order` | `i_first` (IWR1443), `q_first` | Keeps today's behaviour: `ADCCubeConverter.cpp:74-77` (2-lane: first pair is imaginary) and `:93-94` (4-lane: first group is real). **Not settled**, see the audit's I/Q note and D9. core-17 sets the value from a bench capture. The SDK 3.6 demo maps `adcbufCfg` sampleSwap 1 to `DPIF_DATAFORMAT_COMPLEX16_IMRE` (`mss_main.c:1869-1876`). That is consistent with `q_first`, but it describes the ADC buffer, not the LVDS wire order. |
| `dca1000.packet_bytes`, `packet_delay_us` | 1472, 100 | `DCA1000Handler.cpp:590-591` |
| `dca1000.fpga_timer_s` | 30 | `DCA1000Handler.cpp:398-399` |

## Radar .cfg cross-checks

`cross_check_radar_cfg(board, cfg, {dca1000, serial})` returns errors (refuse the run) and
notes (a check could not be made). With the DCA1000 enabled, it checks the following against TI's
demo sources and mmWaveLink:

| cfg line | Rule | Source |
|----------|------|--------|
| `adcCfg <bits> <fmt>` | bits = 2 (16-bit), because the DCA1000 is set to 16-bit (`DCA1000Handler.cpp:395-396`). fmt must be 1 or 2 (complex 1x or 2x): 0 is real and 3 is pseudo-real. | `rl_sensor.h:106-119` (`RL_ADC_DATA_16_BIT`, `RL_ADC_FORMAT_*`) |
| `adcbufCfg [<subFrameIdx>] <fmt> <swap> <interleave> <thr>` | fmt = 0 (complex). interleave 0 (interleaved) needs `lane_per_rx`, and 1 (non-interleaved) needs `two_lane_iq_pairs`. | SDK 3.6 `mmw_cli.c:1377` (help string), `:812-815`; `mss_main.c:1867,1877-1884` |
| `adcbufCfg` field count | 5 fields after the command on SDK 3 and MCU+ boards. 4 on `mmwave_sdk_2`, which has no subFrameIdx: this is inferred from the tracked IWR1443 cfgs (`adcbufCfg 0 1 0 1`), with no SDK 2 source checked. | |
| `lvdsStreamCfg <subFrameIdx> <hdr> <dataFmt> <sw>` | dataFmt = 1 (ADC). 0 disables streaming, and 4 (CP_ADC_CQ) adds data the assembler does not expect. | SDK 3.6 `mmw_cli.c:1118-1119,1421`; `mmw_config.h:104-110` |

A missing `adcbufCfg` or `lvdsStreamCfg` is a note, not an error. The raw-capture cfgs in
`config/radar/DCA1000/iwr_raw_rosnode/` have neither line.
