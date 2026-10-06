# IWR1443 SDK 2 out-of-box demo UART frame format (D7)

**Date:** 2026-10-05
**Memo:** docs/research/sdk2_uart_format_2026-10-05.md

## Question as asked

Directive core-16, Step 1 (Researcher): "Confirm or refute audit (b)'s hypothesis on the
IWR1443 SDK 2 out-of-box demo UART frame from TI sources: header length (36 B per the
descriptor); field order; the TLV header (does `length` include the TLV header?); the
detected-points encoding (Q-format, `xyzQFormat`). Verdict: `confirmed` (the Coder adds
`sdk2` in Step 4) or `not confirmed` (`sdk2` stays a load error). No hardware."

Scope: the xWR14xx out-of-box "mmw" demo shipped with mmWave SDK 2.1.0.4 (the LTS
release that supports IWR1443), data (logging) UART only. Bench capture is out of scope.
The audit hypothesis (docs/design/driver_v2_audit.md:171-173) was: 7-word header with no
`subFrameNumber`, type-1 objects as a Q-format descriptor followed by 12-byte `int16`
records.

## TL;DR

**Verdict: `confirmed`.** The audit hypothesis matches TI's SDK 2.1.0.4 source exactly:
the xWR14xx demo sends an 8-byte magic word plus 7 `uint32` header words (36 bytes, no
`subFrameNumber`), then TLVs with an 8-byte `{type, length}` header where `length`
**excludes** the TLV header. Type 1 is a 4-byte descriptor `{uint16 numDetetedObj,
uint16 xyzQFormat}` followed by `numObj` x 12-byte records of six 16-bit fields; x/y/z
are Q-format meters (`value / 2^xyzQFormat`). Two points differ from SDK 3 and matter
to the parser: the packet is zero-padded to a multiple of 32 bytes (included in
`totalPacketLen`), and the point record has no SNR or noise (only `peakVal`).

## Evidence

All paths below are inside the TI package `mmwave_sdk_02_01_00_04`, obtained from
`https://software-dl.ti.com/ra-processors/esd/MMWAVE-SDK/02_01_00_04/exports/mmwave_sdk_02_01_00_04-Linux-x86-Install.bin`
(unattended install into a scratch directory; `mmw_output.h` sha256
`f879704f138e8ed063353924cac313767953a2606a88974a7fc1d47364209ea9`, `xwr14xx/mmw/main.c`
sha256 `29869f48d850f0efced77eef70fffe1ca925b954f6a9167c6f36d6d733a67076`). The paths are
relative to `packages/ti/demo/`. Line numbers refer to those files.

### 1. Header: 36 bytes, no `subFrameNumber`

- `io_interface/mmw_output.h:87-119` defines `MmwDemo_output_message_header_t` as
  `uint16_t magicWord[4]; uint32_t version; totalPacketLen; platform; frameNumber;
  timeCpuCycles; numDetectedObj; numTLVs;` and then `#ifdef SOC_XWR16XX ...
  uint32_t subFrameNumber; #endif` (lines 113-118). `uint16/uint32` members here are
  naturally aligned with no padding, so the xWR14xx size is 8 + 7 x 4 = **36 bytes**.
- The xWR14xx build defines `SOC_XWR14XX` only: `packages/ti/common/mmwave_sdk_xwr14xx.mak:10`
  (`PLATFORM_DEFINE = SOC_XWR14XX`), so the `SOC_XWR16XX` field is compiled out. This is
  consistent with the descriptor's `data_uart.header_bytes = 36`.
- `xwr14xx/mmw/main.c:1484-1497` fills the header: `platform = 0xA1443`, `magicWord =
  {0x0102,0x0304,0x0506,0x0708}`, `numDetectedObj = obj->numObjOut`, `version` =
  `build | bugfix<<8 | minor<<16 | major<<24`. `main.c:1542-1550` sets `numTLVs`,
  `totalPacketLen`, `timeCpuCycles = Pmu_getCount(0)` (R4F cycles, per
  `mmw_output.h:104`) and `frameNumber`. `main.c:1552` writes
  `sizeof(MmwDemo_output_message_header)` bytes, which is 36 on this target.
- The on-wire magic is bytes `02 01 04 03 06 05 08 07` (little-endian `uint16`).
  Independent corroboration: an SDK 1.x IWR1443 parser compares against
  `magicWord = [2, 1, 4, 3, 6, 5, 8, 7]`, reads `version, totalPacketLen, platform,
  frameNumber, timeCpuCycles, numDetectedObj, numTLVs` and then starts the TLV loop with
  the `subFrameNumber` read commented out (`readData_IWR1443.py`, header block;
  `https://github.com/ibaiGorordo/IWR1443-Read-Data-Python-MMWAVE-SDK-1`).

Field order and offsets (little-endian, from the start of the magic word):

| Offset | Size | Field |
|---|---|---|
| 0 | 8 | magic word: `02 01 04 03 06 05 08 07` |
| 8 | 4 | `version` |
| 12 | 4 | `totalPacketLen` (bytes, whole packet incl. header, TLVs, padding) |
| 16 | 4 | `platform` (`0xA1443`) |
| 20 | 4 | `frameNumber` |
| 24 | 4 | `timeCpuCycles` |
| 28 | 4 | `numDetectedObj` |
| 32 | 4 | `numTLVs` |
| 36 | - | first TLV (no `subFrameNumber`) |

### 2. TLV header: 8 bytes; `length` excludes the TLV header

- `io_interface/mmw_output.h:176-184`: `MmwDemo_output_message_tl_t { uint32_t type;
  uint32_t length; }` = 8 bytes.
- `xwr14xx/mmw/main.c:1500-1503`: `tl.length = sizeof(MmwDemo_detectedObj) * numObjOut +
  sizeof(MmwDemo_output_message_dataObjDescr);` and the very next statement adds
  `sizeof(MmwDemo_output_message_tl) + tl.length` to `packetLen`. So `length` is the
  payload only (descriptor + records), and the TLV header is counted separately. The same
  pattern holds for every other TLV (`main.c:1508-1538`). This is the same convention as
  SDK 3 (the next TLV starts at `tlv_start + 8 + length`).
- TLV types: `mmw_output.h:57-78`: 1 detected points, 2 range profile, 3 noise profile,
  4 azimuth static heat map, 5 range-Doppler heat map, 6 stats. (SDK 3 adds types 7+;
  SDK 2 type 7 does not exist.) Type 6 payload is six `uint32`
  (`mmw_output.h:129-149`) = 24 bytes.
- Which TLVs appear depends on the CLI `guiMonitor` setting. Points are sent only when
  `detectedObjects` is set and `numObjOut > 0` (`main.c:1498-1505`): a frame with zero
  detections has no type-1 TLV (and `numTLVs` may be 0 or only the stats TLV). The
  parser must treat a missing points TLV as an empty cloud, not an error.

### 3. Detected points: descriptor, 12-byte records, Q-format

- `mmw_output.h:158-166`: descriptor `{ uint16_t numDetetedObj; uint16_t xyzQFormat; }`
  (sic, the typo is in TI's field name). Written at `main.c:1564-1566`, immediately after
  the TLV header, followed by the array at `main.c:1569`
  (`sizeof(MmwDemo_detectedObj) * numObjOut`).
- `io_interface/detected_obj.h:27-39`: record = `uint16 rangeIdx; int16 dopplerIdx;
  uint16 peakVal; int16 x; int16 y; int16 z;` = **12 bytes**, little-endian, no padding.
  TLV `length` = 4 + 12 x numObj, which is therefore `4 mod 12` (always `== 4 mod 4`, i.e.
  a multiple of 4 but **not** of 16: the SDK 3 "multiple of 16" check must not be applied
  to this dialect).
- Q-format: `main.c:1420` computes `xyzOutputQFormat = ceil(log2(16 /
  |rangeResolution|))`, and `data_path.c:2234` sets `oneQFormat = 1 << xyzOutputQFormat`
  and stores coordinates as `(int16)(coordinate_m * oneQFormat +/- 0.5)`
  (`data_path.c:2234-2253`). So `meters = (float) int16_value / (1 << xyzQFormat)`.
  The Q value is per frame (it depends on the cfg's range resolution), so decode it from
  every descriptor rather than caching it.
- With the 1D (no azimuth) processing chain, `x = z = 0` and `y = range`
  (`data_path.c:2234-2253`); the 2D/3D chain fills x/y/z from the angle estimate.
- `dopplerIdx` is a signed Doppler bin (`data_path.c:2253,2286` via `DOPPLER_IDX_TO_SIGNED`,
  `detected_obj.h:16-17`). There is **no velocity in meters per second** in the packet:
  `v = dopplerIdx * dopplerResolution`, and `dopplerResolution` must come from the radar
  cfg (profile, chirp loop, number of Doppler bins, Tx count). `peakVal` is the
  log-magnitude of the range-Doppler cell (`data_path.c:2250`), not an SNR in dB, and there
  is no noise field in SDK 2.

### 4. Padding: `totalPacketLen` is a multiple of 32

- `mmw_output.h:47`: `MMWDEMO_OUTPUT_MSG_SEGMENT_LEN 32`. `main.c:1543-1545` rounds
  `totalPacketLen` up to a multiple of 32, and `main.c:1652-1661` writes the trailing
  `numPaddingBytes = 32 - (packetLen & 31)` bytes when that is less than 32 (uninitialized
  stack bytes, so ignore their value). The SDK 2.1 user guide also states it: "Output
  packet of mmW demo data over UART is in TLV format and its length is a multiple of 32
  bytes" (MMWAVE SDK User Guide 2.1, section 6.12). Consequence for framing: read
  exactly `totalPacketLen` bytes; after the last TLV, up to 31 pad bytes remain and must
  be skipped, not parsed. A bounds check must allow `sum(8 + length) <= totalPacketLen - 36`
  (strictly less is normal).

### 5. UART defaults (descriptor cross-check)

- `main.c:2455-2456`: `loggingBaudRate = 921600`, `commandBaudRate = 115200`. The data
  port (UART instance 1, `main.c:2280`) matches `IWR1443.json` `data_uart.baud = 921600`
  (CPSL_TI_Radar_cpp/config/boards/IWR1443.json:19).

### 6. Is SDK 1.2 identical?

`diff` of `io_interface/mmw_output.h` and `detected_obj.h` between SDK 2.1.0.4 and the SDK
1.2.0.5 mirror shows no differences (the header uses the same `#ifdef SOC_XWR16XX`
guard). So the memo applies to SDK 1.x and 2.x xWR14xx demos. It does **not** say anything
about SDK 3.x (xWR14xx is not supported there).

## Applicability to CPSL TI Radar

Established facts (from TI source above), for `tlv_dialect: sdk2` with `header_bytes: 36`:

- Header parse: magic (8) + 7 words; `totalPacketLen` at offset 12; `numTLVs` at offset 32;
  TLVs start at offset 36.
- TLV: `{u32 type, u32 length}`, payload = `length` bytes, next TLV at `+8+length`.
  Validate `numTLVs`, each TLV's bounds, and `numDetectedObj` against the type-1 payload:
  `length == 4 + 12 * descr.numDetetedObj` and `descr.numDetetedObj ==
  header.numDetectedObj`.
- Point decode (type 1): `x,y,z = int16 / 2^xyzQFormat` meters. Parse as `i16`
  little-endian, never as `u16`.

Project-level decisions the Coder must make (HYPOTHESES / design choices, not TI facts):

- `Point{x,y,z,v,snr_db,noise_db}` has no SDK 2 source for `snr_db` and `noise_db`.
  Recommend NaN for both (documented as an approved compromise per the firmware-docs
  convention), not `peakVal`, which is not dB.
- `v` needs the cfg: either derive `dopplerResolution` from `RadarConfigReader` (profile
  and frame cfg) or leave `v = NaN` and document it. Doing this derivation correctly is a
  larger task than the format itself. Recommend the `sdk2` dialect decode `v` from
  `dopplerIdx` only if the Radar already exposes the Doppler resolution; otherwise NaN.
  (The SDK 3 demo sends float v directly, so no existing code path computes it.)
- The 2D/1D chain case (`x = z = 0`) is legitimate output, not a parse error.
- Coder Step 4 also needs the cross-check in `BoardDescriptor.cpp:493` (the load-time
  rejection of serial + `sdk2`) removed or relaxed, and
  `config/boards/README.md:16,42-43` and `docs/design/driver_v2_design.md:56-57,75`
  updated from "HYPOTHESIS/unconfirmed" to "confirmed, see this memo".

## Recommended Experiment

No hardware experiment is needed to confirm the layout; TI source is authoritative for the
shipped demo. A golden test for the Coder is the discriminating check: build a synthetic
frame from the layout above (36-byte header, one type-1 TLV with 2 objects and
`xyzQFormat = 7`, one type-6 TLV, zero padding to a multiple of 32), assert exact parsed
x/y/z and that a trailing pad is skipped. Optional later bench check (out of scope per the
directive): capture one real IWR1443 UART frame and confirm `platform == 0xA1443`,
`totalPacketLen % 32 == 0`, and `header_bytes == 36`. That would settle the one gap below.

## Confidence

High (about 95%) that the layout above is what the stock SDK 2.1.0.4 xWR14xx demo
transmits: it is read directly from TI's `mmw_output.h`, `detected_obj.h` and the
transmit function in `main.c`, and it matches the audit's from-memory hypothesis and an
independent SDK 1.x parser. Not settled: (a) the firmware actually flashed on the lab's
IWR1443 (a custom or different-SDK-version build could differ; no capture exists); (b) the
SDK 2.0.0.4 point release was not separately inspected (only 2.1.0.4 and the 1.2.0.5
mirror, which are identical in these headers); (c) values of the trailing pad bytes (not
needed); (d) the mmWave Demo Visualizer docs were not consulted. Secondary web sources
(a ROS driver's `mmWave.h` and TI E2E threads found by search) agree on the header and
descriptor fields but were not used as evidence because the primary source was available.

## Sources

- `ti_mmwsdk2104_package` — Texas Instruments (2018), "mmWave SDK 02.01.00.04 Linux installer (packages/ti/demo/io_interface/mmw_output.h, detected_obj.h, xwr14xx/mmw/main.c, data_path.c; packages/ti/common/mmwave_sdk_xwr14xx.mak)," *TI MMWAVE-SDK download*. url:https://software-dl.ti.com/ra-processors/esd/MMWAVE-SDK/02_01_00_04/exports/mmwave_sdk_02_01_00_04-Linux-x86-Install.bin
- `ti_mmwsdk2104_userguide` — Texas Instruments (2018), "MMWAVE SDK User Guide, Product Release 2.1, section 6.12 SDK Demos: miscellaneous information," *TI MMWAVE-SDK documentation*. url:https://software-dl.ti.com/ra-processors/esd/MMWAVE-SDK/02_01_00_04/exports/mmwave_sdk_user_guide.pdf
- `ti_mmwsdk1205_mirror` — Texas Instruments (2018), "mmWave SDK 01.02.00.05 packages/ti/demo/io_interface/mmw_output.h and detected_obj.h (GitHub mirror, diffed against 2.1.0.4)," *sgs-weather-and-environmental-systems/TI-mmWave-SDK*. url:https://github.com/sgs-weather-and-environmental-systems/TI-mmWave-SDK/tree/master/mmwave_sdk_01_02_00_05/packages/ti/demo/io_interface
- `gorordo_iwr1443_parser` — Gorordo, I. (2019), "IWR1443 Read Data Python MMWAVE SDK 1, readData_IWR1443.py," *GitHub*. url:https://github.com/ibaiGorordo/IWR1443-Read-Data-Python-MMWAVE-SDK-1
- `cpsl_driver_audit` — CPSL TI Radar (2026), "Driver v2 audit, (b) serial path for IWR1443 (HYPOTHESIS)," *docs/design/driver_v2_audit.md:165-177*. url:https://github.com/davidmhunt/CPSL_TI_Radar/blob/HEAD/docs/design/driver_v2_audit.md

Note for the Reviewer: this repo has no `docs/references/references.bib` (the `docs/references/`
directory does not exist), so `lint_research_memo.py` bib-key existence checks cannot pass
for any memo here. The keys above are descriptive; the TI package files are the evidence
(no PDF is archived, because the source tree is a 375 MB installer).
